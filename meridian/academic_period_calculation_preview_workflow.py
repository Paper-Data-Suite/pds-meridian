"""Read-only Academic Period standards-proficiency calculation preview."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_period_queries import (
    AcademicPeriodLookupError,
    get_academic_period,
)
from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyCalculationOutcome,
    academic_period_proficiency_aggregation_inputs_sha256,
    calculate_academic_period_proficiency,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_result_revisions,
    load_academic_period_proficiency_policy_revision,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)


class AcademicPeriodCalculationPreviewWorkflowError(RuntimeError):
    """Base error for read-only Academic Period calculation preview."""

    code = "teacher_workflow.calculation_preview.academic_period_error"


class AcademicPeriodCalculationPreviewScopeError(
    AcademicPeriodCalculationPreviewWorkflowError,
    ValueError,
):
    """Raised when exact Academic Period preview scope is invalid."""

    code = "teacher_workflow.calculation_preview.academic_period_invalid"


class AcademicPeriodCalculationPreviewDependencyError(
    AcademicPeriodCalculationPreviewWorkflowError
):
    """Raised when exact #35 policy/scale/calendar state cannot be verified."""

    code = "teacher_workflow.calculation_preview.academic_period_dependency_invalid"


@dataclass(frozen=True, slots=True)
class AcademicPeriodCalculationPreviewProjection:
    """Teacher-facing read-only projection of one exact #35 calculation."""

    inputs: AcademicPeriodProficiencyAggregationInputs
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    policy_title: str
    strategy: str
    period_membership_scope: str
    minimum_calculated_results: int
    mode_tie_rule: str | None
    median_even_rule: str | None
    missing_result_handling: str
    insufficient_result_handling: str
    outcome: AcademicPeriodProficiencyCalculationOutcome
    input_entry_count: int
    input_status_counts: tuple[tuple[str, int], ...]
    result_history: tuple[int, ...]
    next_result_revision: int
    current_result_revision: int | None
    target_period_title: str
    result_write_performed: bool = False
    result_selection_performed: bool = False

    @property
    def class_id(self) -> str:
        return self.inputs.class_id

    @property
    def school_year(self) -> str:
        return self.inputs.target_period.period.school_year

    @property
    def period_id(self) -> str:
        return self.inputs.target_period.period.period_id

    @property
    def calendar_revision(self) -> int:
        return self.inputs.target_period.calendar_revision

    @property
    def student_id(self) -> str:
        return self.inputs.student_id

    @property
    def standard_id(self) -> str:
        return self.inputs.standard_id

    @property
    def inputs_sha256(self) -> str:
        return academic_period_proficiency_aggregation_inputs_sha256(
            self.inputs
        )

    @property
    def status(self) -> str:
        return self.outcome.status

    @property
    def proficiency_level_id(self) -> str | None:
        return self.outcome.proficiency_level_id

    @property
    def calculation_fingerprint(self) -> str:
        return self.outcome.calculation_fingerprint


def build_academic_period_calculation_preview_projection(
    workspace_root: str | Path,
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
) -> AcademicPeriodCalculationPreviewProjection:
    """Run pure #35 calculation over one exact bounded input snapshot."""
    _validate_request(inputs, policy_reference)

    try:
        stored_policy = load_academic_period_proficiency_policy_revision(
            workspace_root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodCalculationPreviewDependencyError(
            f"Exact Academic Period proficiency policy could not be loaded: {error}"
        ) from error
    if stored_policy.policy_sha256 != policy_reference.policy_sha256:
        raise AcademicPeriodCalculationPreviewDependencyError(
            "Exact Academic Period policy SHA-256 does not match stored revision."
        )

    policy = stored_policy.policy
    if policy.target_scale != inputs.target_scale:
        raise AcademicPeriodCalculationPreviewDependencyError(
            "Academic Period policy target scale does not match exact inputs."
        )
    if policy.period_membership_scope != inputs.period_membership_scope:
        raise AcademicPeriodCalculationPreviewDependencyError(
            "Academic Period policy membership scope does not match exact inputs."
        )

    scale_ref = inputs.target_scale
    try:
        stored_scale = load_proficiency_scale_revision(
            workspace_root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise AcademicPeriodCalculationPreviewDependencyError(
            f"Exact target proficiency scale could not be loaded: {error}"
        ) from error
    if stored_scale.scale_sha256 != scale_ref.scale_sha256:
        raise AcademicPeriodCalculationPreviewDependencyError(
            "Exact Academic Period target-scale SHA-256 does not match stored revision."
        )

    target = inputs.target_period
    try:
        calendar = load_academic_period_calendar_revision(
            workspace_root,
            target.period.school_year,
            target.calendar_revision,
        )
        period = get_academic_period(calendar, target.period.period_id)
    except (AcademicPeriodCalendarStorageError, AcademicPeriodLookupError) as error:
        raise AcademicPeriodCalculationPreviewDependencyError(
            f"Exact Core Academic Period target could not be verified: {error}"
        ) from error

    try:
        outcome = calculate_academic_period_proficiency(
            inputs,
            policy,
            stored_scale.scale,
        )
        history = list_academic_period_proficiency_result_revisions(
            workspace_root,
            inputs.class_id,
            target.period.school_year,
            target.period.period_id,
            inputs.student_id,
            inputs.standard_id,
        )
        current = get_current_academic_period_proficiency_result_revision(
            workspace_root,
            inputs.class_id,
            target.period.school_year,
            target.period.period_id,
            inputs.student_id,
            inputs.standard_id,
        )
    except (AcademicPeriodProficiencyStorageError, ValueError) as error:
        raise AcademicPeriodCalculationPreviewDependencyError(str(error)) from error

    statuses = Counter(entry.status for entry in inputs.entries)
    return AcademicPeriodCalculationPreviewProjection(
        inputs=inputs,
        policy_reference=stored_policy.reference,
        policy_title=policy.title,
        strategy=policy.strategy,
        period_membership_scope=policy.period_membership_scope,
        minimum_calculated_results=policy.minimum_calculated_results,
        mode_tie_rule=policy.mode_tie_rule,
        median_even_rule=policy.median_even_rule,
        missing_result_handling=policy.missing_result_handling,
        insufficient_result_handling=policy.insufficient_result_handling,
        outcome=outcome,
        input_entry_count=len(inputs.entries),
        input_status_counts=tuple(sorted(statuses.items())),
        result_history=history,
        next_result_revision=1 if not history else history[-1] + 1,
        current_result_revision=current,
        target_period_title=period.label,
    )


def _validate_request(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
) -> None:
    if not isinstance(inputs, AcademicPeriodProficiencyAggregationInputs):
        raise AcademicPeriodCalculationPreviewScopeError(
            "inputs must be exact AcademicPeriodProficiencyAggregationInputs."
        )
    if not isinstance(
        policy_reference,
        AcademicPeriodProficiencyAggregationPolicyReference,
    ):
        raise AcademicPeriodCalculationPreviewScopeError(
            "policy_reference must be an exact Academic Period policy reference."
        )
    if policy_reference.class_id != inputs.class_id:
        raise AcademicPeriodCalculationPreviewScopeError(
            "Academic Period policy class must match the input class."
        )
