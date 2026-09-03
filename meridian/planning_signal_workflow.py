"""Read-only entry projection for Issue #41 Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
)
from meridian.grouping_signal_generation import (
    GroupingSignalGenerationCandidate,
    GroupingSignalGenerationError,
    resolve_current_grouping_signal_derivation,
)
from meridian.grouping_signal_policy import (
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicyReference,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    StoredGroupingSignalDerivationPolicy,
    load_current_grouping_signal_policy,
)
from meridian.proficiency_mapping import ProficiencyScaleReference


class PlanningSignalWorkflowError(RuntimeError):
    """Base error for Issue #41 Create Planning Signal orchestration."""

    code = "teacher_workflow.create_planning_signal.error"


class PlanningSignalWorkflowScopeError(PlanningSignalWorkflowError, ValueError):
    """Raised when planning-signal workflow scope is invalid."""

    code = "teacher_workflow.create_planning_signal.invalid"


class PlanningSignalWorkflowDependencyError(PlanningSignalWorkflowError):
    """Raised when canonical planning-signal dependencies cannot be read."""

    code = "teacher_workflow.create_planning_signal.dependency_error"


class PlanningSignalWorkflowStaleError(PlanningSignalWorkflowError):
    """Raised when selected planning policy changes during projection."""

    code = "teacher_workflow.create_planning_signal.stale"


@dataclass(frozen=True, slots=True)
class PlanningSignalPolicyProjection:
    """Exact selected #37 policy state relevant to the teacher task."""

    reference: GroupingSignalDerivationPolicyReference
    title: str
    target_period: AcademicPeriodProficiencyTarget
    standard_id: str
    source_policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    target_scale_reference: ProficiencyScaleReference
    dimension_id: str
    band_count: int
    band_definitions: tuple[GroupingSignalBandDefinition, ...]
    tie_handling: str
    missing_result_handling: str
    insufficient_result_handling: str
    actor_kind: str
    actor_id: str
    rationale: str | None
    revised_at: datetime


@dataclass(frozen=True, slots=True)
class PlanningSignalReadinessProjection:
    """Stable read-only selected-policy + current-#35 generation readiness."""

    class_id: str
    policy_id: str
    policy: PlanningSignalPolicyProjection | None
    generation: GroupingSignalGenerationCandidate

    @property
    def generation_status(self) -> str:
        return self.generation.status

    @property
    def blocker_codes(self) -> tuple[str, ...]:
        return tuple(blocker.code for blocker in self.generation.blockers)

    @property
    def ready_for_derivation_persistence(self) -> bool:
        return self.generation.status == "generated"

    @property
    def candidate_derivation_id(self) -> str | None:
        snapshot = self.generation.snapshot
        return None if snapshot is None else snapshot.derivation_id

    @property
    def candidate_calculation_fingerprint(self) -> str | None:
        snapshot = self.generation.snapshot
        return None if snapshot is None else snapshot.calculation_fingerprint

    @property
    def roster_student_count(self) -> int | None:
        snapshot = self.generation.snapshot
        return None if snapshot is None else len(snapshot.roster_basis.student_ids)

    @property
    def contributing_student_count(self) -> int | None:
        snapshot = self.generation.snapshot
        if snapshot is None:
            return None
        return sum(
            item.disposition == "contributing"
            for item in snapshot.student_derivations
        )

    @property
    def noncontributing_student_count(self) -> int | None:
        snapshot = self.generation.snapshot
        if snapshot is None:
            return None
        return sum(
            item.disposition == "noncontributing"
            for item in snapshot.student_derivations
        )

    @property
    def derivation_write_action(self) -> str:
        return "not_performed"

    @property
    def preview_write_action(self) -> str:
        return "not_performed"

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


def project_planning_signal_readiness(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> PlanningSignalReadinessProjection:
    """Resolve Create Planning Signal entry state without writing anything."""
    exact_class_id = _identifier(class_id, "class_id")
    exact_policy_id = _identifier(policy_id, "policy_id")

    selected_before = _load_selected_policy(
        workspace_root,
        exact_class_id,
        exact_policy_id,
    )
    try:
        generation = resolve_current_grouping_signal_derivation(
            workspace_root,
            exact_class_id,
            exact_policy_id,
        )
    except GroupingSignalGenerationError as error:
        raise PlanningSignalWorkflowDependencyError(str(error)) from error
    selected_after = _load_selected_policy(
        workspace_root,
        exact_class_id,
        exact_policy_id,
    )

    before_reference = (
        None if selected_before is None else selected_before.reference
    )
    after_reference = (
        None if selected_after is None else selected_after.reference
    )
    if before_reference != after_reference:
        raise PlanningSignalWorkflowStaleError(
            "Selected grouping-signal policy changed during readiness projection."
        )

    if selected_after is None:
        if generation.status != "blocked" or generation.snapshot is not None:
            raise PlanningSignalWorkflowDependencyError(
                "Read-only generation state disagrees with missing selected policy."
            )
        if tuple(blocker.code for blocker in generation.blockers) != (
            "no_selected_policy",
        ):
            raise PlanningSignalWorkflowDependencyError(
                "Missing selected policy must produce no_selected_policy blocker."
            )
        policy_projection = None
    else:
        if any(
            blocker.code == "no_selected_policy"
            for blocker in generation.blockers
        ):
            raise PlanningSignalWorkflowStaleError(
                "Generation resolver observed no selected policy during projection."
            )
        policy_projection = _policy_projection(selected_after)
        snapshot = generation.snapshot
        if snapshot is not None and (
            snapshot.class_id != exact_class_id
            or snapshot.policy_reference != selected_after.reference
        ):
            raise PlanningSignalWorkflowStaleError(
                "Generated derivation candidate does not bind the stable selected "
                "policy."
            )

    return PlanningSignalReadinessProjection(
        class_id=exact_class_id,
        policy_id=exact_policy_id,
        policy=policy_projection,
        generation=generation,
    )


def _load_selected_policy(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> StoredGroupingSignalDerivationPolicy | None:
    try:
        return load_current_grouping_signal_policy(
            workspace_root,
            class_id,
            policy_id,
        )
    except GroupingSignalPolicyStorageError as error:
        raise PlanningSignalWorkflowDependencyError(
            "Could not load the explicitly selected #37 grouping-signal policy."
        ) from error


def _policy_projection(
    stored: StoredGroupingSignalDerivationPolicy,
) -> PlanningSignalPolicyProjection:
    policy = stored.policy
    basis = policy.academic_basis
    return PlanningSignalPolicyProjection(
        reference=stored.reference,
        title=policy.title,
        target_period=basis.target_period,
        standard_id=basis.standard_id,
        source_policy_reference=basis.source_policy,
        target_scale_reference=basis.target_scale,
        dimension_id=policy.dimension_id,
        band_count=policy.band_count,
        band_definitions=policy.band_definitions,
        tie_handling=policy.tie_handling,
        missing_result_handling=policy.missing_result_handling,
        insufficient_result_handling=policy.insufficient_result_handling,
        actor_kind=policy.actor.kind,
        actor_id=policy.actor.actor_id,
        rationale=policy.rationale,
        revised_at=policy.revised_at,
    )


def _identifier(value: str, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise PlanningSignalWorkflowScopeError(str(error)) from error
