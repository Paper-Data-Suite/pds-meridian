"""Read-only Academic Period proficiency explanation and provenance trace.

This module resolves one exact persisted #35 result without recalculating academic
state.  It verifies the exact Core calendar, #35 policy, proficiency scale, Grade
Item and membership bases, and every stored #34 result reference before returning
a deterministic explanation.  Nested Grade Item explanations always target the
exact historical #34 revision named by #35, never the current #34 selection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_period_queries import (
    AcademicPeriodLookupError,
    get_academic_period,
)
from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.academic_periods import (
    AcademicPeriodCalendar,
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    validate_academic_period_ref,
)
from pds_core.class_metadata import ClassMetadataError, load_class_metadata
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_metadata_path

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyCalculationOutcome,
    AcademicPeriodProficiencyEntryExplanation,
    AcademicPeriodProficiencyInsufficiencyReason,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodScopeMismatchReason,
    resolve_academic_period_proficiency_scope,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    AcademicPeriodProficiencyStorageNotFoundError,
    StoredAcademicPeriodProficiencyResult,
    get_current_academic_period_proficiency_result_revision,
    load_academic_period_proficiency_policy_revision,
    load_academic_period_proficiency_result_revision,
    load_current_academic_period_proficiency_result,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    load_grade_item_membership_revision,
)
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceError,
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
    GradeItemIdentityExplanation,
    GradeItemProficiencyExplanation,
    GradeItemProficiencyTraceTarget,
    ProficiencyLevelExplanation,
    ProficiencyScaleExplanation,
    explain_grade_item_proficiency,
    grade_item_proficiency_explanation_to_dict,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_grade_item_revision,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)
from meridian.standards_evidence import (
    StandardsEvidenceValidationError,
    normalize_standard_id,
)
from meridian.standards_proficiency import (
    StandardProficiencyInsufficiencyReason,
    StandardProficiencyLevelCount,
    StandardProficiencyResultReference,
    StandardProficiencyTieResolution,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    load_standard_proficiency_result_revision,
)

AcademicPeriodProficiencyTargetSelection: TypeAlias = Literal[
    "current",
    "revision",
]
AcademicPeriodProficiencySelectionState: TypeAlias = Literal[
    "selected_current",
    "historical",
    "no_current_selection",
]


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyTraceTarget:
    """Explicit current-selection or exact historical #35 result target."""

    class_id: str
    school_year: str
    period_id: str
    student_id: str
    standard_id: str
    selection: AcademicPeriodProficiencyTargetSelection
    result_revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            _identifier(self.class_id, "class_id"),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        try:
            period = validate_academic_period_ref(
                AcademicPeriodRef(self.school_year, self.period_id)
            )
        except AcademicPeriodValidationError as error:
            raise ExplanationTraceTargetError(
                f"Academic Period target is invalid: {error}"
            ) from error
        object.__setattr__(self, "school_year", period.school_year)
        object.__setattr__(self, "period_id", period.period_id)
        try:
            standard_id = normalize_standard_id(self.standard_id)
        except StandardsEvidenceValidationError as error:
            raise ExplanationTraceTargetError(
                f"standard_id is invalid: {error}"
            ) from error
        object.__setattr__(self, "standard_id", standard_id)
        if self.selection not in {"current", "revision"}:
            raise ExplanationTraceTargetError(
                "selection must be exactly 'current' or 'revision'."
            )
        revision = self.result_revision
        if self.selection == "current":
            if revision is not None:
                raise ExplanationTraceTargetError(
                    "current target must not provide result_revision."
                )
        elif type(revision) is not int or revision < 1:
            raise ExplanationTraceTargetError(
                "revision target requires a positive result_revision."
            )


@dataclass(frozen=True, slots=True)
class AcademicPeriodIdentityExplanation:
    school_year: str
    period_id: str
    calendar_revision: int
    label: str
    period_type: str
    lifecycle: str


@dataclass(frozen=True, slots=True)
class AcademicPeriodCalculationPolicyExplanation:
    policy_id: str
    policy_revision: int
    policy_sha256: str
    title: str
    strategy: str
    period_membership_scope: str
    minimum_calculated_results: int
    mode_tie_rule: str | None
    median_even_rule: str | None
    missing_result_handling: str
    insufficient_result_handling: str
    actor_kind: str
    actor_id: str
    rationale: str | None


@dataclass(frozen=True, slots=True)
class AcademicPeriodMembershipExplanation:
    module_id: str
    class_id: str
    work_id: str
    registration_revision: int
    membership_revision: int
    membership_sha256: str
    school_year: str
    period_id: str
    calendar_revision: int


@dataclass(frozen=True, slots=True)
class AcademicPeriodGradeItemExplanation:
    grade_item: GradeItemIdentityExplanation
    memberships: tuple[AcademicPeriodMembershipExplanation, ...]
    period_scope_status: Literal["eligible", "period_scope_mismatch"]
    period_scope_mismatch_reason: AcademicPeriodScopeMismatchReason | None
    status: Literal[
        "calculated",
        "insufficient_evidence",
        "missing_result",
        "period_scope_mismatch",
    ]
    contributed: bool
    result_reference: StandardProficiencyResultReference | None
    result_algorithm_version: str | None
    result_calculation_fingerprint: str | None
    result_status: Literal["calculated", "insufficient_evidence"] | None
    proficiency_level_id: str | None
    result_insufficiency_reasons: tuple[
        StandardProficiencyInsufficiencyReason,
        ...,
    ]
    nested_grade_item_explanation: GradeItemProficiencyExplanation | None


@dataclass(frozen=True, slots=True)
class AcademicPeriodCalculationExplanation:
    status: Literal["calculated", "insufficient_evidence"]
    proficiency_level_id: str | None
    candidate_count: int
    calculated_result_count: int
    insufficient_result_count: int
    missing_result_count: int
    period_scope_mismatch_count: int
    level_counts: tuple[StandardProficiencyLevelCount, ...]
    insufficiency_reasons: tuple[
        AcademicPeriodProficiencyInsufficiencyReason,
        ...,
    ]
    tie_resolution: StandardProficiencyTieResolution | None


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyExplanation:
    """Deterministic read-only projection for one exact #35 result."""

    class_id: str
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    selection_state: AcademicPeriodProficiencySelectionState
    current_result_revision: int | None
    algorithm_version: str
    calculation_fingerprint: str
    inputs_sha256: str
    calculated_at: datetime
    target_period: AcademicPeriodIdentityExplanation
    policy: AcademicPeriodCalculationPolicyExplanation
    scale: ProficiencyScaleExplanation
    grade_items: tuple[AcademicPeriodGradeItemExplanation, ...]
    calculation: AcademicPeriodCalculationExplanation


def explain_academic_period_proficiency(
    workspace_root: str | Path,
    target: AcademicPeriodProficiencyTraceTarget,
) -> AcademicPeriodProficiencyExplanation:
    """Resolve and verify one exact Academic Period proficiency explanation."""

    if not isinstance(target, AcademicPeriodProficiencyTraceTarget):
        raise ExplanationTraceTargetError(
            "target must be an AcademicPeriodProficiencyTraceTarget."
        )

    stored = _resolve_target(workspace_root, target)
    snapshot = stored.snapshot
    current_revision = _current_result_revision(workspace_root, target)
    if (
        target.selection == "current"
        and current_revision != snapshot.result_revision
    ):
        raise ExplanationTraceIntegrityError(
            "Current #35 result selection changed during explanation resolution."
        )

    _verify_class_scope(workspace_root, snapshot)
    target_period, calendar = _resolve_target_period(
        workspace_root,
        snapshot,
    )
    policy = _resolve_policy(workspace_root, snapshot)
    scale = _resolve_scale(workspace_root, snapshot)
    grade_items = _resolve_grade_items(
        workspace_root,
        snapshot,
        calendar,
    )

    final_current_revision = _current_result_revision(workspace_root, target)
    if (
        target.selection == "current"
        and final_current_revision != snapshot.result_revision
    ):
        raise ExplanationTraceIntegrityError(
            "Current #35 result selection changed during explanation resolution."
        )
    current_revision = final_current_revision

    selection_state: AcademicPeriodProficiencySelectionState
    if current_revision == snapshot.result_revision:
        selection_state = "selected_current"
    elif current_revision is None:
        selection_state = "no_current_selection"
    else:
        selection_state = "historical"

    return AcademicPeriodProficiencyExplanation(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        standard_id=snapshot.standard_id,
        result_revision=snapshot.result_revision,
        result_sha256=stored.result_sha256,
        selection_state=selection_state,
        current_result_revision=current_revision,
        algorithm_version=snapshot.algorithm_version,
        calculation_fingerprint=snapshot.calculation_fingerprint,
        inputs_sha256=snapshot.inputs_sha256,
        calculated_at=snapshot.calculated_at,
        target_period=target_period,
        policy=policy,
        scale=scale,
        grade_items=grade_items,
        calculation=_calculation_projection(snapshot.outcome),
    )


def academic_period_proficiency_explanation_to_dict(
    value: AcademicPeriodProficiencyExplanation,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one #35 explanation."""

    if not isinstance(value, AcademicPeriodProficiencyExplanation):
        raise ExplanationTraceTargetError(
            "value must be an AcademicPeriodProficiencyExplanation."
        )
    tie = value.calculation.tie_resolution
    return {
        "target": {
            "class_id": value.class_id,
            "student_id": value.student_id,
            "standard_id": value.standard_id,
            "school_year": value.target_period.school_year,
            "period_id": value.target_period.period_id,
            "calendar_revision": value.target_period.calendar_revision,
            "result_revision": value.result_revision,
            "result_sha256": value.result_sha256,
            "selection_state": value.selection_state,
            "current_result_revision": value.current_result_revision,
        },
        "calculation_identity": {
            "algorithm_version": value.algorithm_version,
            "calculation_fingerprint": value.calculation_fingerprint,
            "inputs_sha256": value.inputs_sha256,
            "calculated_at": value.calculated_at.isoformat(),
        },
        "academic_period": {
            "school_year": value.target_period.school_year,
            "period_id": value.target_period.period_id,
            "calendar_revision": value.target_period.calendar_revision,
            "label": value.target_period.label,
            "period_type": value.target_period.period_type,
            "lifecycle": value.target_period.lifecycle,
        },
        "policy": {
            "policy_id": value.policy.policy_id,
            "policy_revision": value.policy.policy_revision,
            "policy_sha256": value.policy.policy_sha256,
            "title": value.policy.title,
            "strategy": value.policy.strategy,
            "period_membership_scope": value.policy.period_membership_scope,
            "minimum_calculated_results": (
                value.policy.minimum_calculated_results
            ),
            "mode_tie_rule": value.policy.mode_tie_rule,
            "median_even_rule": value.policy.median_even_rule,
            "missing_result_handling": value.policy.missing_result_handling,
            "insufficient_result_handling": (
                value.policy.insufficient_result_handling
            ),
            "actor": {
                "kind": value.policy.actor_kind,
                "actor_id": value.policy.actor_id,
            },
            "rationale": value.policy.rationale,
        },
        "scale": {
            "scale_id": value.scale.scale_id,
            "scale_revision": value.scale.scale_revision,
            "scale_sha256": value.scale.scale_sha256,
            "title": value.scale.title,
            "description": value.scale.description,
            "levels": [
                {
                    "level_id": level.level_id,
                    "position": level.position,
                    "label": level.label,
                    "description": level.description,
                }
                for level in value.scale.levels
            ],
            "proficiency_threshold_level_id": (
                value.scale.proficiency_threshold_level_id
            ),
            "actor": {
                "kind": value.scale.actor_kind,
                "actor_id": value.scale.actor_id,
            },
            "rationale": value.scale.rationale,
        },
        "grade_items": [
            _grade_item_explanation_to_dict(item)
            for item in value.grade_items
        ],
        "calculation": {
            "status": value.calculation.status,
            "proficiency_level_id": value.calculation.proficiency_level_id,
            "candidate_count": value.calculation.candidate_count,
            "calculated_result_count": (
                value.calculation.calculated_result_count
            ),
            "insufficient_result_count": (
                value.calculation.insufficient_result_count
            ),
            "missing_result_count": value.calculation.missing_result_count,
            "period_scope_mismatch_count": (
                value.calculation.period_scope_mismatch_count
            ),
            "level_counts": [
                {
                    "proficiency_level_id": count.proficiency_level_id,
                    "count": count.count,
                }
                for count in value.calculation.level_counts
            ],
            "insufficiency_reasons": [
                {
                    "kind": reason.kind,
                    "grade_item_ids": list(reason.grade_item_ids),
                    "required_results": reason.required_results,
                    "actual_results": reason.actual_results,
                }
                for reason in value.calculation.insufficiency_reasons
            ],
            "tie_resolution": (
                None
                if tie is None
                else {
                    "kind": tie.kind,
                    "rule": tie.rule,
                    "candidate_level_ids": list(tie.candidate_level_ids),
                    "selected_level_id": tie.selected_level_id,
                }
            ),
        },
    }


def academic_period_proficiency_explanation_to_json_bytes(
    value: AcademicPeriodProficiencyExplanation,
) -> bytes:
    """Render deterministic UTF-8 JSON for machine inspection."""

    return (
        json.dumps(
            academic_period_proficiency_explanation_to_dict(value),
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def render_academic_period_proficiency_explanation_text(
    value: AcademicPeriodProficiencyExplanation,
) -> str:
    """Render a compact teacher-facing #35 trace with exact identities."""

    result = (
        value.calculation.proficiency_level_id
        if value.calculation.proficiency_level_id is not None
        else "no calculated proficiency level"
    )
    lines = [
        "Academic Period proficiency explanation",
        (
            f"Result: {value.class_id} / {value.target_period.school_year} / "
            f"{value.target_period.period_id} / {value.student_id} / "
            f"{value.standard_id}"
        ),
        (
            f"Revision: {value.result_revision} "
            f"({value.selection_state}; sha256={value.result_sha256})"
        ),
        (
            f"Academic Period: {value.target_period.label} "
            f"(calendar revision {value.target_period.calendar_revision})"
        ),
        (
            f"Policy: {value.policy.title} "
            f"({value.policy.strategy}; scope="
            f"{value.policy.period_membership_scope}; "
            f"minimum calculated={value.policy.minimum_calculated_results})"
        ),
        (
            "Missing/insufficient handling: "
            f"{value.policy.missing_result_handling}/"
            f"{value.policy.insufficient_result_handling}"
        ),
        f"Scale: {value.scale.title} (revision {value.scale.scale_revision})",
        f"Calculation: {value.calculation.status} -> {result}",
        (
            "Counts: "
            f"candidates={value.calculation.candidate_count}, "
            f"calculated={value.calculation.calculated_result_count}, "
            f"insufficient={value.calculation.insufficient_result_count}, "
            f"missing={value.calculation.missing_result_count}, "
            f"period_scope_mismatch="
            f"{value.calculation.period_scope_mismatch_count}"
        ),
        f"Grade Item candidates: {len(value.grade_items)}",
    ]
    for item in value.grade_items:
        mismatch = item.period_scope_mismatch_reason or "none"
        result_revision = (
            str(item.result_reference.result_revision)
            if item.result_reference is not None
            else "none"
        )
        lines.append(
            f"- {item.grade_item.grade_item_id}: status={item.status} "
            f"contributed={'yes' if item.contributed else 'no'} "
            f"period_scope={item.period_scope_status} "
            f"mismatch={mismatch} #34_revision={result_revision} "
            f"#34_status={item.result_status or 'none'} "
            f"level={item.proficiency_level_id or 'none'}"
        )
        for membership in item.memberships:
            lines.append(
                "    membership: "
                f"{membership.module_id}/{membership.work_id} "
                f"revision={membership.membership_revision} "
                f"sha256={membership.membership_sha256} "
                f"period={membership.school_year}/{membership.period_id}"
                f"@calendar-{membership.calendar_revision}"
            )
        if item.nested_grade_item_explanation is not None:
            nested = item.nested_grade_item_explanation
            lines.append(
                "    exact #34 drill-down: "
                f"revision={nested.result_revision} "
                f"selection_state={nested.selection_state} "
                f"status={nested.calculation.status} "
                f"level={nested.calculation.proficiency_level_id or 'none'}"
            )
    if value.calculation.insufficiency_reasons:
        lines.append("Insufficiency reasons:")
        for reason in value.calculation.insufficiency_reasons:
            ids = ",".join(reason.grade_item_ids) or "none"
            lines.append(f"- {reason.kind}: grade_items={ids}")
    return "\n".join(lines) + "\n"


def _resolve_target(
    workspace_root: str | Path,
    target: AcademicPeriodProficiencyTraceTarget,
) -> StoredAcademicPeriodProficiencyResult:
    try:
        if target.selection == "current":
            stored = load_current_academic_period_proficiency_result(
                workspace_root,
                target.class_id,
                target.school_year,
                target.period_id,
                target.student_id,
                target.standard_id,
            )
            if stored is None:
                raise ExplanationTraceNotFoundError(
                    "Requested Academic Period proficiency family has no "
                    "explicit current selected result."
                )
            return stored
        revision = target.result_revision
        if revision is None:
            raise ExplanationTraceTargetError(
                "revision target requires result_revision."
            )
        return load_academic_period_proficiency_result_revision(
            workspace_root,
            target.class_id,
            target.school_year,
            target.period_id,
            target.student_id,
            target.standard_id,
            revision,
        )
    except ExplanationTraceError:
        raise
    except AcademicPeriodProficiencyStorageNotFoundError as error:
        raise ExplanationTraceNotFoundError(
            "Requested Academic Period proficiency result does not exist."
        ) from error
    except AcademicPeriodProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Requested Academic Period proficiency result failed canonical "
            f"verification: {error}"
        ) from error


def _current_result_revision(
    workspace_root: str | Path,
    target: AcademicPeriodProficiencyTraceTarget,
) -> int | None:
    try:
        return get_current_academic_period_proficiency_result_revision(
            workspace_root,
            target.class_id,
            target.school_year,
            target.period_id,
            target.student_id,
            target.standard_id,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Current #35 result selection failed canonical verification: "
            f"{error}"
        ) from error


def _verify_class_scope(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> None:
    try:
        metadata = load_class_metadata(
            class_metadata_path(workspace_root, snapshot.class_id)
        )
    except ClassMetadataError as error:
        raise ExplanationTraceIntegrityError(
            "Exact Core class metadata required by the #35 result could not "
            f"be verified: {error}"
        ) from error
    if (
        metadata.class_id != snapshot.class_id
        or metadata.school_year
        != snapshot.target_period.period.school_year
    ):
        raise ExplanationTraceIntegrityError(
            "Core class metadata does not match the exact #35 class and "
            "school-year scope."
        )


def _resolve_target_period(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> tuple[AcademicPeriodIdentityExplanation, AcademicPeriodCalendar]:
    target = snapshot.target_period
    try:
        calendar = load_academic_period_calendar_revision(
            workspace_root,
            target.period.school_year,
            target.calendar_revision,
        )
        period = get_academic_period(calendar, target.period.period_id)
    except (
        AcademicPeriodCalendarStorageError,
        AcademicPeriodLookupError,
    ) as error:
        raise ExplanationTraceIntegrityError(
            "Exact Core Academic Period Calendar revision or target period "
            f"could not be verified: {error}"
        ) from error
    if (
        calendar.school_year != target.period.school_year
        or calendar.calendar_revision != target.calendar_revision
        or period.period_id != target.period.period_id
    ):
        raise ExplanationTraceIntegrityError(
            "Exact Core Academic Period identity does not match #35 provenance."
        )
    return (
        AcademicPeriodIdentityExplanation(
            school_year=calendar.school_year,
            period_id=period.period_id,
            calendar_revision=calendar.calendar_revision,
            label=period.label,
            period_type=period.period_type,
            lifecycle=period.lifecycle,
        ),
        calendar,
    )


def _resolve_policy(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> AcademicPeriodCalculationPolicyExplanation:
    reference = snapshot.policy_reference
    try:
        stored = load_academic_period_proficiency_policy_revision(
            workspace_root,
            reference.class_id,
            reference.policy_id,
            reference.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #35 calculation-policy revision referenced by the result "
            f"could not be verified: {error}"
        ) from error
    if stored.policy_sha256 != reference.policy_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact #35 calculation-policy digest does not match result provenance."
        )
    policy = stored.policy
    if policy.target_scale != snapshot.target_scale:
        raise ExplanationTraceIntegrityError(
            "#35 calculation policy does not bind the exact proficiency scale "
            "used by the result."
        )
    if policy.period_membership_scope != snapshot.inputs.period_membership_scope:
        raise ExplanationTraceIntegrityError(
            "#35 calculation policy scope does not match the stored inputs."
        )
    return AcademicPeriodCalculationPolicyExplanation(
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
        policy_sha256=stored.policy_sha256,
        title=policy.title,
        strategy=policy.strategy,
        period_membership_scope=policy.period_membership_scope,
        minimum_calculated_results=policy.minimum_calculated_results,
        mode_tie_rule=policy.mode_tie_rule,
        median_even_rule=policy.median_even_rule,
        missing_result_handling=policy.missing_result_handling,
        insufficient_result_handling=policy.insufficient_result_handling,
        actor_kind=policy.actor.kind,
        actor_id=policy.actor.actor_id,
        rationale=policy.rationale,
    )


def _resolve_scale(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> ProficiencyScaleExplanation:
    reference = snapshot.target_scale
    try:
        stored = load_proficiency_scale_revision(
            workspace_root,
            reference.class_id,
            reference.scale_id,
            reference.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale revision referenced by the #35 result "
            f"could not be verified: {error}"
        ) from error
    if stored.scale_sha256 != reference.scale_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale digest does not match #35 provenance."
        )
    scale = stored.scale
    return ProficiencyScaleExplanation(
        scale_id=scale.scale_id,
        scale_revision=scale.scale_revision,
        scale_sha256=stored.scale_sha256,
        title=scale.title,
        description=scale.description,
        levels=tuple(
            ProficiencyLevelExplanation(
                level_id=level.level_id,
                position=level.position,
                label=level.label,
                description=level.description,
            )
            for level in scale.levels
        ),
        proficiency_threshold_level_id=scale.proficiency_threshold_level_id,
        actor_kind=scale.actor.kind,
        actor_id=scale.actor.actor_id,
        rationale=scale.rationale,
    )


def _resolve_grade_items(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    calendar: AcademicPeriodCalendar,
) -> tuple[AcademicPeriodGradeItemExplanation, ...]:
    outcome_by_grade_item = {
        item.grade_item_id: item
        for item in snapshot.outcome.explanation_entries
    }
    if len(outcome_by_grade_item) != len(snapshot.outcome.explanation_entries):
        raise ExplanationTraceIntegrityError(
            "#35 calculation explanation contains duplicate Grade Item identities."
        )
    if set(outcome_by_grade_item) != {
        item.grade_item.grade_item_id for item in snapshot.inputs.entries
    }:
        raise ExplanationTraceIntegrityError(
            "#35 calculation explanation does not cover the exact input candidates."
        )

    result: list[AcademicPeriodGradeItemExplanation] = []
    for entry in snapshot.inputs.entries:
        outcome = outcome_by_grade_item[entry.grade_item.grade_item_id]
        _verify_entry_explanation(entry, outcome)
        grade_item = _resolve_grade_item(workspace_root, entry)
        memberships = _resolve_memberships(workspace_root, snapshot, entry)
        scope_status, scope_reason = _verify_period_scope(
            snapshot,
            calendar,
            entry,
        )
        nested = _resolve_nested_grade_item_result(
            workspace_root,
            snapshot,
            entry,
        )
        result.append(
            AcademicPeriodGradeItemExplanation(
                grade_item=grade_item,
                memberships=memberships,
                period_scope_status=scope_status,
                period_scope_mismatch_reason=scope_reason,
                status=entry.status,
                contributed=outcome.contributed,
                result_reference=entry.result_reference,
                result_algorithm_version=entry.result_algorithm_version,
                result_calculation_fingerprint=(
                    entry.result_calculation_fingerprint
                ),
                result_status=entry.result_status,
                proficiency_level_id=entry.proficiency_level_id,
                result_insufficiency_reasons=(
                    entry.result_insufficiency_reasons
                ),
                nested_grade_item_explanation=nested,
            )
        )
    return tuple(result)


def _verify_entry_explanation(
    entry: AcademicPeriodProficiencyAggregationInputEntry,
    outcome: AcademicPeriodProficiencyEntryExplanation,
) -> None:
    if (
        outcome.status != entry.status
        or outcome.result_reference != entry.result_reference
        or outcome.proficiency_level_id != entry.proficiency_level_id
        or outcome.period_scope_mismatch_reason
        != entry.period_scope_mismatch_reason
        or outcome.contributed != (entry.status == "calculated")
    ):
        raise ExplanationTraceIntegrityError(
            "#35 per-Grade-Item explanation does not match its exact input entry."
        )


def _resolve_grade_item(
    workspace_root: str | Path,
    entry: AcademicPeriodProficiencyAggregationInputEntry,
) -> GradeItemIdentityExplanation:
    basis = entry.grade_item
    try:
        stored = load_grade_item_revision(
            workspace_root,
            basis.class_id,
            basis.grade_item_id,
            basis.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact Grade Item revision referenced by #35 could not be verified: "
            f"{error}"
        ) from error
    if stored.revision_sha256 != basis.grade_item_revision_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact Grade Item revision digest does not match #35 provenance."
        )
    revision = stored.revision
    return GradeItemIdentityExplanation(
        class_id=revision.class_id,
        grade_item_id=revision.grade_item_id,
        grade_item_revision=revision.grade_item_revision,
        grade_item_revision_sha256=stored.revision_sha256,
        title=revision.title,
        purpose=revision.purpose,
        status=revision.status,
    )


def _resolve_memberships(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    entry: AcademicPeriodProficiencyAggregationInputEntry,
) -> tuple[AcademicPeriodMembershipExplanation, ...]:
    result: list[AcademicPeriodMembershipExplanation] = []
    for basis in entry.memberships:
        try:
            stored = load_grade_item_membership_revision(
                workspace_root,
                snapshot.class_id,
                basis.grade_item_id,
                basis.work_reference.work,
                basis.membership_revision,
            )
        except GradeItemMembershipStorageError as error:
            raise ExplanationTraceIntegrityError(
                "Exact Grade Item membership revision referenced by #35 "
                f"could not be verified: {error}"
            ) from error
        if stored.decision_sha256 != basis.membership_sha256:
            raise ExplanationTraceIntegrityError(
                "Exact Grade Item membership digest does not match #35 provenance."
            )
        decision = stored.decision
        assignment = decision.academic_period
        if (
            decision.decision != "included"
            or assignment is None
            or decision.grade_item_revision != basis.grade_item_revision
            or decision.grade_item_revision_sha256
            != basis.grade_item_revision_sha256
            or decision.work_reference != basis.work_reference
            or assignment.period != basis.academic_period.period
            or assignment.calendar_revision
            != basis.academic_period.calendar_revision
        ):
            raise ExplanationTraceIntegrityError(
                "Exact Grade Item membership does not match the stored #35 basis."
            )
        work = basis.work_reference.work
        result.append(
            AcademicPeriodMembershipExplanation(
                module_id=work.module_id,
                class_id=work.class_id,
                work_id=work.work_id,
                registration_revision=basis.work_reference.registration_revision,
                membership_revision=basis.membership_revision,
                membership_sha256=basis.membership_sha256,
                school_year=basis.academic_period.period.school_year,
                period_id=basis.academic_period.period.period_id,
                calendar_revision=basis.academic_period.calendar_revision,
            )
        )
    return tuple(result)


def _verify_period_scope(
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    calendar: AcademicPeriodCalendar,
    entry: AcademicPeriodProficiencyAggregationInputEntry,
) -> tuple[
    Literal["eligible", "period_scope_mismatch"],
    AcademicPeriodScopeMismatchReason | None,
]:
    try:
        resolution = resolve_academic_period_proficiency_scope(
            snapshot.target_period,
            calendar,
            entry.memberships,
            snapshot.inputs.period_membership_scope,
        )
    except ValueError as error:
        raise ExplanationTraceIntegrityError(
            "Exact stored Academic Period membership basis could not be "
            f"revalidated: {error}"
        ) from error
    if entry.status == "period_scope_mismatch":
        if (
            resolution.status != "period_scope_mismatch"
            or resolution.mismatch_reason
            != entry.period_scope_mismatch_reason
        ):
            raise ExplanationTraceIntegrityError(
                "Stored #35 period-scope mismatch does not match exact "
                "calendar/membership provenance."
            )
    elif resolution.status != "eligible":
        raise ExplanationTraceIntegrityError(
            "Stored #35 input says period scope is eligible, but exact "
            "calendar/membership provenance disagrees."
        )
    return resolution.status, resolution.mismatch_reason


def _resolve_nested_grade_item_result(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    entry: AcademicPeriodProficiencyAggregationInputEntry,
) -> GradeItemProficiencyExplanation | None:
    reference = entry.result_reference
    if reference is None:
        return None
    try:
        stored = load_standard_proficiency_result_revision(
            workspace_root,
            reference.class_id,
            reference.grade_item_id,
            reference.student_id,
            reference.standard_id,
            reference.result_revision,
        )
    except StandardProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #34 Grade Item proficiency result referenced by #35 "
            f"could not be verified: {error}"
        ) from error
    if stored.reference != reference:
        raise ExplanationTraceIntegrityError(
            "Exact #34 result identity/digest does not match #35 provenance."
        )
    child = stored.snapshot
    if (
        child.inputs.grade_item != entry.grade_item
        or child.student_id != snapshot.student_id
        or child.standard_id != snapshot.standard_id
        or child.target_scale != snapshot.target_scale
        or child.algorithm_version != entry.result_algorithm_version
        or child.calculation_fingerprint
        != entry.result_calculation_fingerprint
        or child.outcome.status != entry.result_status
        or child.outcome.proficiency_level_id != entry.proficiency_level_id
        or child.outcome.insufficiency_reasons
        != entry.result_insufficiency_reasons
    ):
        raise ExplanationTraceIntegrityError(
            "Exact #34 result does not match the normalized #35 input."
        )

    return explain_grade_item_proficiency(
        workspace_root,
        GradeItemProficiencyTraceTarget(
            class_id=reference.class_id,
            grade_item_id=reference.grade_item_id,
            student_id=reference.student_id,
            standard_id=reference.standard_id,
            selection="revision",
            result_revision=reference.result_revision,
        ),
    )


def _calculation_projection(
    outcome: AcademicPeriodProficiencyCalculationOutcome,
) -> AcademicPeriodCalculationExplanation:
    return AcademicPeriodCalculationExplanation(
        status=outcome.status,
        proficiency_level_id=outcome.proficiency_level_id,
        candidate_count=outcome.candidate_count,
        calculated_result_count=outcome.calculated_result_count,
        insufficient_result_count=outcome.insufficient_result_count,
        missing_result_count=outcome.missing_result_count,
        period_scope_mismatch_count=outcome.period_scope_mismatch_count,
        level_counts=outcome.level_counts,
        insufficiency_reasons=outcome.insufficiency_reasons,
        tie_resolution=outcome.tie_resolution,
    )


def _grade_item_explanation_to_dict(
    value: AcademicPeriodGradeItemExplanation,
) -> dict[str, object]:
    reference = value.result_reference
    return {
        "grade_item": {
            "class_id": value.grade_item.class_id,
            "grade_item_id": value.grade_item.grade_item_id,
            "grade_item_revision": value.grade_item.grade_item_revision,
            "grade_item_revision_sha256": (
                value.grade_item.grade_item_revision_sha256
            ),
            "title": value.grade_item.title,
            "purpose": value.grade_item.purpose,
            "status": value.grade_item.status,
        },
        "memberships": [
            {
                "module_id": membership.module_id,
                "class_id": membership.class_id,
                "work_id": membership.work_id,
                "registration_revision": membership.registration_revision,
                "membership_revision": membership.membership_revision,
                "membership_sha256": membership.membership_sha256,
                "academic_period": {
                    "school_year": membership.school_year,
                    "period_id": membership.period_id,
                    "calendar_revision": membership.calendar_revision,
                },
            }
            for membership in value.memberships
        ],
        "period_scope": {
            "status": value.period_scope_status,
            "mismatch_reason": value.period_scope_mismatch_reason,
        },
        "status": value.status,
        "contributed": value.contributed,
        "result_reference": (
            None
            if reference is None
            else {
                "class_id": reference.class_id,
                "grade_item_id": reference.grade_item_id,
                "student_id": reference.student_id,
                "standard_id": reference.standard_id,
                "result_revision": reference.result_revision,
                "result_sha256": reference.result_sha256,
            }
        ),
        "result_algorithm_version": value.result_algorithm_version,
        "result_calculation_fingerprint": (
            value.result_calculation_fingerprint
        ),
        "result_status": value.result_status,
        "proficiency_level_id": value.proficiency_level_id,
        "result_insufficiency_reasons": [
            {
                "kind": reason.kind,
                "source_keys": list(reason.source_keys),
                "required_observations": reason.required_observations,
                "actual_observations": reason.actual_observations,
            }
            for reason in value.result_insufficiency_reasons
        ],
        "nested_grade_item_explanation": (
            None
            if value.nested_grade_item_explanation is None
            else grade_item_proficiency_explanation_to_dict(
                value.nested_grade_item_explanation
            )
        ),
    }


def _identifier(value: str, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name=field_name)
    except IdentifierValidationError as error:
        raise ExplanationTraceTargetError(
            f"{field_name} is invalid: {error}"
        ) from error
