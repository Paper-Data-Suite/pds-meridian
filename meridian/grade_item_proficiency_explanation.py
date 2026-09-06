"""Read-only Grade Item proficiency explanation and provenance trace.

Issue #42 begins here: one exact persisted #34 result is resolved without
recalculating academic state, and every exact external provenance reference carried by
that result is verified before a teacher-facing projection is returned.

This module intentionally owns no persistence.  It does not select current state,
change academic decisions, open protected producer evidence, or infer a newer
equivalent record when an exact historical dependency is unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.attempt_selection_storage import (
    AttemptSelectionStorageError,
    load_attempt_selection_decision_revision,
)
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScalar,
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    evidence_source_key,
    evidence_source_reference_to_dict,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityStorageError,
    load_evidence_eligibility_revision,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    load_grade_item_membership_revision,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_grade_item_revision,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_mapping_profile_revision,
    load_proficiency_scale_revision,
)
from meridian.reassessment_storage import (
    ReassessmentStorageError,
    load_reassessment_decision_revision,
)
from meridian.standards_evidence import (
    AggregationDecisionReference,
    StandardAggregationExclusionReason,
    StandardAggregationInputEntry,
    StandardsEvidenceValidationError,
    normalize_standard_id,
)
from meridian.standards_evidence_storage import (
    StandardsEvidenceStorageError,
    load_standard_evidence_association_revision,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationOutcome,
    StandardProficiencyEntryExplanation,
    StandardProficiencyInsufficiencyReason,
    StandardProficiencyLevelCount,
    StandardProficiencyResultSnapshot,
    StandardProficiencyTieResolution,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    StandardProficiencyStorageNotFoundError,
    StoredStandardProficiencyResult,
    get_current_standard_proficiency_result_revision,
    load_current_standard_proficiency_result,
    load_standard_proficiency_policy_revision,
    load_standard_proficiency_result_revision,
)

if TYPE_CHECKING:
    from meridian.diagnostics import DiagnosticsDependencies


GradeItemProficiencyTargetSelection: TypeAlias = Literal["current", "revision"]
GradeItemProficiencySelectionState: TypeAlias = Literal[
    "selected_current",
    "historical",
    "no_current_selection",
]
ProvenanceStageName: TypeAlias = Literal[
    "membership",
    "eligibility",
    "attempt_selection",
    "reassessment",
    "standard_association",
    "mapping_profile",
]
ProvenanceStageStatus: TypeAlias = Literal[
    "verified",
    "not_applicable",
    "not_reached",
    "unresolved",
    "not_supplied",
]
TraceScalar: TypeAlias = str | int | float | bool | None

_GRADE_ITEM_STAGE_NAMES: Final[tuple[ProvenanceStageName, ...]] = (
    "membership",
    "eligibility",
    "attempt_selection",
    "reassessment",
    "standard_association",
    "mapping_profile",
)


class ExplanationTraceError(RuntimeError):
    """Base error for deterministic read-only explanation resolution."""

    code: str = "explanation_trace.error"


class ExplanationTraceTargetError(ExplanationTraceError, ValueError):
    """Raised when an explanation target is ambiguous or malformed."""

    code = "explanation_trace.target_invalid"


class ExplanationTraceNotFoundError(ExplanationTraceError):
    """Raised when the explicitly requested explanation target does not exist."""

    code = "explanation_trace.target_not_found"


class ExplanationTraceIntegrityError(ExplanationTraceError):
    """Raised when an exact stored provenance edge cannot be verified."""

    code = "explanation_trace.integrity_failed"


@dataclass(frozen=True, slots=True)
class GradeItemProficiencyTraceTarget:
    """Explicit current-selection or exact historical #34 result target."""

    class_id: str
    grade_item_id: str
    student_id: str
    standard_id: str
    selection: GradeItemProficiencyTargetSelection
    result_revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
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
class TraceField:
    """One deterministic structured detail in a provenance stage."""

    key: str
    value: TraceScalar


@dataclass(frozen=True, slots=True)
class ProvenanceStageExplanation:
    """Verified, unavailable, or non-applicable state for one provenance stage."""

    name: ProvenanceStageName
    status: ProvenanceStageStatus
    revision: int | None
    sha256: str | None
    details: tuple[TraceField, ...] = ()


AuthorizedEvidenceDetailStatus: TypeAlias = Literal[
    "not_requested",
    "available",
    "denied",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceItemExplanation:
    """Privacy-bounded detail from one authorized persisted EvidenceItem."""

    item_id: str
    student_id: str | None
    target_kind: str
    target_id: str | None
    standard_ids: tuple[str, ...]
    result_kind: str
    value_kind: Literal["scalar", "points", "scaled", "state"]
    value_fields: tuple[TraceField, ...]
    eligibility_status: str
    eligibility_policy_id: str | None
    eligibility_policy_version: str | None
    eligibility_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceDetailExplanation:
    """Whether optional protected evidence detail was requested and available."""

    status: AuthorizedEvidenceDetailStatus = "not_requested"
    reason_code: str | None = None
    item: AuthorizedEvidenceItemExplanation | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.status not in {
            "not_requested",
            "available",
            "denied",
            "unavailable",
        }:
            raise ExplanationTraceTargetError(
                "authorized evidence detail status is invalid."
            )
        if self.status == "available":
            if self.item is None or self.reason_code is not None:
                raise ExplanationTraceTargetError(
                    "available authorized detail requires one item and no reason."
                )
        elif self.item is not None:
            raise ExplanationTraceTargetError(
                "unavailable authorized detail must not contain an evidence item."
            )


@dataclass(frozen=True, slots=True)
class EvidenceSourceExplanation:
    """One exact #33 candidate and its resolved provenance chain."""

    source_key: str
    source: EvidenceSourceReference
    result_kind: str
    target_kind: str
    aggregation_status: Literal["performance", "native_state", "excluded"]
    exclusion_reason: StandardAggregationExclusionReason | None
    mapping_status: Literal[
        "mapped", "native_state", "unmapped", "unsupported"
    ] | None
    proficiency_level_id: str | None
    native_state_code: str | None
    stages: tuple[ProvenanceStageExplanation, ...]
    authorized_detail: AuthorizedEvidenceDetailExplanation = field(
        default_factory=AuthorizedEvidenceDetailExplanation
    )

    @property
    def contributes_performance(self) -> bool:
        return self.aggregation_status == "performance"


@dataclass(frozen=True, slots=True)
class GradeItemIdentityExplanation:
    class_id: str
    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str
    title: str
    purpose: str
    status: str


@dataclass(frozen=True, slots=True)
class CalculationPolicyExplanation:
    policy_id: str
    policy_revision: int
    policy_sha256: str
    title: str
    strategy: str
    minimum_performance_observations: int
    mode_tie_rule: str | None
    median_even_rule: str | None
    blocking_exclusion_reasons: tuple[str, ...]
    native_state_handling: str
    actor_kind: str
    actor_id: str
    rationale: str | None


@dataclass(frozen=True, slots=True)
class ProficiencyLevelExplanation:
    level_id: str
    position: int
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class ProficiencyScaleExplanation:
    scale_id: str
    scale_revision: int
    scale_sha256: str
    title: str
    description: str
    levels: tuple[ProficiencyLevelExplanation, ...]
    proficiency_threshold_level_id: str
    actor_kind: str
    actor_id: str
    rationale: str | None


@dataclass(frozen=True, slots=True)
class GradeItemCalculationExplanation:
    status: Literal["calculated", "insufficient_evidence"]
    proficiency_level_id: str | None
    performance_observation_count: int
    native_state_count: int
    excluded_count: int
    level_counts: tuple[StandardProficiencyLevelCount, ...]
    insufficiency_reasons: tuple[StandardProficiencyInsufficiencyReason, ...]
    tie_resolution: StandardProficiencyTieResolution | None


@dataclass(frozen=True, slots=True)
class GradeItemProficiencyExplanation:
    """Deterministic read-only projection for one exact #34 result."""

    class_id: str
    grade_item_id: str
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    selection_state: GradeItemProficiencySelectionState
    current_result_revision: int | None
    algorithm_version: str
    calculation_fingerprint: str
    inputs_sha256: str
    calculated_at: datetime
    grade_item: GradeItemIdentityExplanation
    policy: CalculationPolicyExplanation
    scale: ProficiencyScaleExplanation
    evidence: tuple[EvidenceSourceExplanation, ...]
    calculation: GradeItemCalculationExplanation


def explain_grade_item_proficiency(
    workspace_root: str | Path,
    target: GradeItemProficiencyTraceTarget,
) -> GradeItemProficiencyExplanation:
    """Resolve and verify one exact Grade Item standards-proficiency explanation.

    The function never recalculates proficiency.  ``selection="current"`` resolves
    the canonical current-result pointer explicitly.  ``selection="revision"``
    loads exactly the requested historical revision and never substitutes whatever
    result happens to be current now.
    """

    if not isinstance(target, GradeItemProficiencyTraceTarget):
        raise ExplanationTraceTargetError(
            "target must be a GradeItemProficiencyTraceTarget."
        )
    stored = _resolve_target(workspace_root, target)
    snapshot = stored.snapshot
    current_revision = _current_result_revision(workspace_root, target)
    if (
        target.selection == "current"
        and current_revision != snapshot.result_revision
    ):
        raise ExplanationTraceIntegrityError(
            "Current-result selection changed during explanation resolution."
        )
    selection_state: GradeItemProficiencySelectionState
    if current_revision == snapshot.result_revision:
        selection_state = "selected_current"
    elif current_revision is None:
        selection_state = "no_current_selection"
    else:
        selection_state = "historical"

    grade_item = _resolve_grade_item(workspace_root, snapshot)
    policy = _resolve_policy(workspace_root, snapshot)
    scale = _resolve_scale(workspace_root, snapshot)
    evidence = _resolve_evidence(workspace_root, snapshot)

    return GradeItemProficiencyExplanation(
        class_id=snapshot.class_id,
        grade_item_id=snapshot.grade_item_id,
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
        grade_item=grade_item,
        policy=policy,
        scale=scale,
        evidence=evidence,
        calculation=_calculation_projection(snapshot.outcome),
    )


def expand_grade_item_evidence_detail(
    workspace_root: str | Path,
    explanation: GradeItemProficiencyExplanation,
    source_key: str,
    *,
    authorization_purpose_id: str,
    requested_student_ids: tuple[str, ...],
    dependencies: DiagnosticsDependencies,
) -> GradeItemProficiencyExplanation:
    """Optionally enrich one source through the existing authorized cache reader.

    The base academic explanation remains usable without protected evidence access.
    This function never opens producer-native state directly; it delegates to the
    established diagnostics/cache authorization boundary and returns a new immutable
    projection with the selected row's detail availability updated.
    """

    if not isinstance(explanation, GradeItemProficiencyExplanation):
        raise ExplanationTraceTargetError(
            "explanation must be a GradeItemProficiencyExplanation."
        )
    if not isinstance(source_key, str) or not source_key:
        raise ExplanationTraceTargetError("source_key must be a nonempty string.")
    matches = tuple(
        item for item in explanation.evidence if item.source_key == source_key
    )
    if len(matches) != 1:
        raise ExplanationTraceTargetError(
            "source_key must identify exactly one evidence row in the explanation."
        )
    source_row = matches[0]
    detail = _resolve_authorized_evidence_detail(
        workspace_root,
        explanation,
        source_row,
        authorization_purpose_id=authorization_purpose_id,
        requested_student_ids=requested_student_ids,
        dependencies=dependencies,
    )
    evidence = tuple(
        replace(item, authorized_detail=detail)
        if item.source_key == source_key
        else item
        for item in explanation.evidence
    )
    return replace(explanation, evidence=evidence)


def grade_item_proficiency_explanation_to_dict(
    value: GradeItemProficiencyExplanation,
) -> dict[str, object]:
    """Return a deterministic JSON-native representation of one explanation."""

    if not isinstance(value, GradeItemProficiencyExplanation):
        raise ExplanationTraceTargetError(
            "value must be a GradeItemProficiencyExplanation."
        )
    tie = value.calculation.tie_resolution
    return {
        "target": {
            "class_id": value.class_id,
            "grade_item_id": value.grade_item_id,
            "student_id": value.student_id,
            "standard_id": value.standard_id,
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
        "grade_item": {
            "class_id": value.grade_item.class_id,
            "grade_item_id": value.grade_item.grade_item_id,
            "grade_item_revision": value.grade_item.grade_item_revision,
            "grade_item_revision_sha256": value.grade_item.grade_item_revision_sha256,
            "title": value.grade_item.title,
            "purpose": value.grade_item.purpose,
            "status": value.grade_item.status,
        },
        "policy": {
            "policy_id": value.policy.policy_id,
            "policy_revision": value.policy.policy_revision,
            "policy_sha256": value.policy.policy_sha256,
            "title": value.policy.title,
            "strategy": value.policy.strategy,
            "minimum_performance_observations": (
                value.policy.minimum_performance_observations
            ),
            "mode_tie_rule": value.policy.mode_tie_rule,
            "median_even_rule": value.policy.median_even_rule,
            "blocking_exclusion_reasons": list(
                value.policy.blocking_exclusion_reasons
            ),
            "native_state_handling": value.policy.native_state_handling,
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
        "evidence": [
            {
                "source_key": item.source_key,
                "source": evidence_source_reference_to_dict(item.source),
                "result_kind": item.result_kind,
                "target_kind": item.target_kind,
                "aggregation_status": item.aggregation_status,
                "contributes_performance": item.contributes_performance,
                "exclusion_reason": item.exclusion_reason,
                "mapping_status": item.mapping_status,
                "proficiency_level_id": item.proficiency_level_id,
                "native_state_code": item.native_state_code,
                "authorized_detail": _authorized_detail_to_dict(
                    item.authorized_detail
                ),
                "stages": [
                    {
                        "name": stage.name,
                        "status": stage.status,
                        "revision": stage.revision,
                        "sha256": stage.sha256,
                        "details": {
                            detail.key: detail.value for detail in stage.details
                        },
                    }
                    for stage in item.stages
                ],
            }
            for item in value.evidence
        ],
        "calculation": {
            "status": value.calculation.status,
            "proficiency_level_id": value.calculation.proficiency_level_id,
            "performance_observation_count": (
                value.calculation.performance_observation_count
            ),
            "native_state_count": value.calculation.native_state_count,
            "excluded_count": value.calculation.excluded_count,
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
                    "source_keys": list(reason.source_keys),
                    "required_observations": reason.required_observations,
                    "actual_observations": reason.actual_observations,
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


def grade_item_proficiency_explanation_to_json_bytes(
    value: GradeItemProficiencyExplanation,
) -> bytes:
    """Render deterministic UTF-8 JSON for machine inspection."""

    return (
        json.dumps(
            grade_item_proficiency_explanation_to_dict(value),
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def render_grade_item_proficiency_explanation_text(
    value: GradeItemProficiencyExplanation,
) -> str:
    """Render a compact teacher-facing text trace without hiding exact identity."""

    status = value.calculation.status
    result = (
        value.calculation.proficiency_level_id
        if value.calculation.proficiency_level_id is not None
        else "no calculated proficiency level"
    )
    lines = [
        "Grade Item proficiency explanation",
        (
            f"Result: {value.class_id} / {value.grade_item_id} / "
            f"{value.student_id} / {value.standard_id}"
        ),
        (
            f"Revision: {value.result_revision} "
            f"({value.selection_state}; sha256={value.result_sha256})"
        ),
        (
            f"Grade Item: {value.grade_item.title} "
            f"(revision {value.grade_item.grade_item_revision})"
        ),
        (
            f"Policy: {value.policy.title} "
            f"({value.policy.strategy}; minimum observations="
            f"{value.policy.minimum_performance_observations})"
        ),
        f"Scale: {value.scale.title} (revision {value.scale.scale_revision})",
        f"Calculation: {status} -> {result}",
        (
            "Counts: "
            f"performance={value.calculation.performance_observation_count}, "
            f"native_state={value.calculation.native_state_count}, "
            f"excluded={value.calculation.excluded_count}"
        ),
        f"Evidence candidates: {len(value.evidence)}",
    ]
    for item in value.evidence:
        mapping = item.mapping_status or "not_supplied"
        if item.proficiency_level_id is not None:
            operative_value = f"level:{item.proficiency_level_id}"
        elif item.native_state_code is not None:
            operative_value = f"native_state:{item.native_state_code}"
        else:
            operative_value = "none"
        exclusion = item.exclusion_reason or "none"
        lines.append(
            f"- {item.source_key}: result={item.result_kind} "
            f"target={item.target_kind} aggregation={item.aggregation_status} "
            f"performance_contribution="
            f"{'yes' if item.contributes_performance else 'no'} "
            f"mapping={mapping} value={operative_value} exclusion={exclusion}"
        )
        detail = item.authorized_detail
        detail_suffix = (
            "" if detail.reason_code is None else f" reason={detail.reason_code}"
        )
        lines.append(
            f"    authorized_detail: {detail.status}{detail_suffix}"
        )
        if detail.item is not None:
            fields = "; ".join(
                f"{field.key}={field.value if field.value is not None else 'none'}"
                for field in detail.item.value_fields
            )
            lines.append(
                "      "
                f"item={detail.item.item_id} target={detail.item.target_kind}:"
                f"{detail.item.target_id} result={detail.item.result_kind} "
                f"value_kind={detail.item.value_kind}"
                + ("" if not fields else f"; {fields}")
            )
        for stage in item.stages:
            suffix = ""
            if stage.revision is not None:
                suffix = f" revision={stage.revision} sha256={stage.sha256}"
            details = "; ".join(
                f"{detail.key}={detail.value if detail.value is not None else 'none'}"
                for detail in stage.details
            )
            if details:
                suffix += f" | {details}"
            lines.append(f"    {stage.name}: {stage.status}{suffix}")
    if value.calculation.level_counts:
        lines.append(
            "Per-level counts: "
            + ", ".join(
                f"{count.proficiency_level_id}={count.count}"
                for count in value.calculation.level_counts
            )
        )
    if value.calculation.tie_resolution is not None:
        tie = value.calculation.tie_resolution
        lines.append(
            f"Tie resolution: {tie.kind}; rule={tie.rule}; "
            f"candidates={','.join(tie.candidate_level_ids)}; "
            f"selected={tie.selected_level_id or 'none'}"
        )
    if value.calculation.insufficiency_reasons:
        lines.append("Insufficiency reasons:")
        for reason in value.calculation.insufficiency_reasons:
            lines.append(f"- {reason.kind}")
    return "\n".join(lines) + "\n"


def _resolve_target(
    workspace_root: str | Path,
    target: GradeItemProficiencyTraceTarget,
) -> StoredStandardProficiencyResult:
    try:
        if target.selection == "current":
            stored = load_current_standard_proficiency_result(
                workspace_root,
                target.class_id,
                target.grade_item_id,
                target.student_id,
                target.standard_id,
            )
            if stored is None:
                raise ExplanationTraceNotFoundError(
                    "Requested Grade Item proficiency family has no explicit "
                    "current selected result."
                )
            return stored
        revision = target.result_revision
        if revision is None:  # defensive: target validation rejects this.
            raise ExplanationTraceTargetError(
                "revision target requires result_revision."
            )
        return load_standard_proficiency_result_revision(
            workspace_root,
            target.class_id,
            target.grade_item_id,
            target.student_id,
            target.standard_id,
            revision,
        )
    except ExplanationTraceError:
        raise
    except StandardProficiencyStorageNotFoundError as error:
        raise ExplanationTraceNotFoundError(
            "Requested Grade Item proficiency result does not exist."
        ) from error
    except StandardProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Requested Grade Item proficiency result failed canonical "
            f"verification: {error}"
        ) from error


def _current_result_revision(
    workspace_root: str | Path,
    target: GradeItemProficiencyTraceTarget,
) -> int | None:
    try:
        return get_current_standard_proficiency_result_revision(
            workspace_root,
            target.class_id,
            target.grade_item_id,
            target.student_id,
            target.standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            f"Current-result selection failed canonical verification: {error}"
        ) from error


def _resolve_grade_item(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
) -> GradeItemIdentityExplanation:
    basis = snapshot.inputs.grade_item
    try:
        stored = load_grade_item_revision(
            workspace_root,
            basis.class_id,
            basis.grade_item_id,
            basis.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact Grade Item revision referenced by the proficiency result "
            f"could not be verified: {error}"
        ) from error
    if stored.revision_sha256 != basis.grade_item_revision_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact Grade Item revision digest does not match proficiency provenance."
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


def _resolve_policy(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
) -> CalculationPolicyExplanation:
    reference = snapshot.policy_reference
    try:
        stored = load_standard_proficiency_policy_revision(
            workspace_root,
            reference.class_id,
            reference.policy_id,
            reference.policy_revision,
        )
    except StandardProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact calculation-policy revision referenced by the proficiency result "
            f"could not be verified: {error}"
        ) from error
    if stored.policy_sha256 != reference.policy_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact calculation-policy digest does not match proficiency provenance."
        )
    policy = stored.policy
    if policy.target_scale != snapshot.target_scale:
        raise ExplanationTraceIntegrityError(
            "Calculation policy does not bind the exact proficiency scale used "
            "by the result."
        )
    return CalculationPolicyExplanation(
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
        policy_sha256=stored.policy_sha256,
        title=policy.title,
        strategy=policy.strategy,
        minimum_performance_observations=policy.minimum_performance_observations,
        mode_tie_rule=policy.mode_tie_rule,
        median_even_rule=policy.median_even_rule,
        blocking_exclusion_reasons=tuple(policy.blocking_exclusion_reasons),
        native_state_handling=policy.native_state_handling,
        actor_kind=policy.actor.kind,
        actor_id=policy.actor.actor_id,
        rationale=policy.rationale,
    )


def _resolve_scale(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
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
            "Exact proficiency-scale revision referenced by the proficiency result "
            f"could not be verified: {error}"
        ) from error
    if stored.scale_sha256 != reference.scale_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale digest does not match proficiency provenance."
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


def _resolve_authorized_evidence_detail(
    workspace_root: str | Path,
    explanation: GradeItemProficiencyExplanation,
    row: EvidenceSourceExplanation,
    *,
    authorization_purpose_id: str,
    requested_student_ids: tuple[str, ...],
    dependencies: DiagnosticsDependencies,
) -> AuthorizedEvidenceDetailExplanation:
    from meridian.diagnostics import (
        DiagnosticsAuthorizationProviderRequiredError,
        DiagnosticsError,
        EvidenceFilters,
        inspect_evidence_diagnostic,
    )
    from meridian.ingestion import PublicationIngestionError
    from meridian.projection_cache import (
        ProjectionCacheAuthorizationDeniedError,
        ProjectionCacheError,
    )

    source = row.source
    try:
        inspection = inspect_evidence_diagnostic(
            workspace_root,
            source.publication_id,
            source.cache_key,
            authorization_purpose_id=authorization_purpose_id,
            requested_student_ids=requested_student_ids,
            filters=EvidenceFilters(item_ids=(source.item_id,)),
            dependencies=dependencies,
        )
    except DiagnosticsAuthorizationProviderRequiredError as error:
        return AuthorizedEvidenceDetailExplanation(
            status="unavailable",
            reason_code=error.code,
        )
    except ProjectionCacheAuthorizationDeniedError as error:
        return AuthorizedEvidenceDetailExplanation(
            status="denied",
            reason_code=error.code,
        )
    except (DiagnosticsError, ProjectionCacheError, PublicationIngestionError) as error:
        return AuthorizedEvidenceDetailExplanation(
            status="unavailable",
            reason_code=getattr(error, "code", "explanation_trace.detail_unavailable"),
        )

    stored = inspection.authorized.stored
    snapshot = stored.snapshot
    if stored.cache_key != source.cache_key:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence cache key does not match the exact source reference."
        )
    if stored.snapshot_digest != source.snapshot_digest:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence snapshot digest does not match the exact source "
            "reference."
        )
    publication = snapshot.source.publication
    if (
        publication.publication_id != source.publication_id
        or publication.work != source.work
    ):
        raise ExplanationTraceIntegrityError(
            "Authorized evidence publication identity does not match the exact "
            "source reference."
        )
    if len(inspection.items) != 1:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence detail did not resolve exactly one source item."
        )
    item = inspection.items[0]
    if item.item_id != source.item_id:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence item identity does not match the exact source "
            "reference."
        )
    if (
        item.provenance.publication.publication_id != source.publication_id
        or item.provenance.publication.work != source.work
    ):
        raise ExplanationTraceIntegrityError(
            "Authorized evidence item provenance does not match the exact source "
            "reference."
        )
    student_id = getattr(item.subject, "student_id", None)
    if student_id is not None and student_id != explanation.student_id:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence student does not match the proficiency target."
        )
    return AuthorizedEvidenceDetailExplanation(
        status="available",
        item=_authorized_evidence_item_projection(item),
    )


def _native_scalar_type(value: NativeScalar) -> str:
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "float"
    return "string"


def _authorized_evidence_item_projection(
    item: EvidenceItem,
) -> AuthorizedEvidenceItemExplanation:
    value = item.value
    value_fields: tuple[TraceField, ...]
    if isinstance(value, NativeScalarValue):
        value_kind: Literal["scalar", "points", "scaled", "state"] = "scalar"
        value_fields = (
            TraceField("scalar_type", _native_scalar_type(value.value)),
            TraceField("value", value.value),
        )
    elif isinstance(value, NativePointValue):
        value_kind = "points"
        value_fields = (
            TraceField("earned_type", _native_scalar_type(value.earned)),
            TraceField("earned", value.earned),
            TraceField("possible_type", _native_scalar_type(value.possible)),
            TraceField("possible", value.possible),
        )
    elif isinstance(value, NativeScaledValue):
        value_kind = "scaled"
        value_fields = (
            TraceField("value_type", _native_scalar_type(value.value)),
            TraceField("value", value.value),
            TraceField("scale_id", value.scale.scale_id),
            TraceField("scale_revision", value.scale.revision),
            TraceField("scale_type", value.scale.scale_type),
            TraceField("scale_status", value.scale.status),
        )
    elif isinstance(value, NativeStateValue):
        value_kind = "state"
        value_fields = (
            TraceField("code", value.code),
            TraceField("label", value.label),
            TraceField("description", value.description),
        )
    else:
        raise ExplanationTraceIntegrityError(
            "Authorized evidence contains an unsupported native value variant."
        )
    eligibility = item.eligibility
    return AuthorizedEvidenceItemExplanation(
        item_id=item.item_id,
        student_id=getattr(item.subject, "student_id", None),
        target_kind=item.target.target_kind,
        target_id=item.target.target_id,
        standard_ids=item.target.standard_ids,
        result_kind=item.result_kind,
        value_kind=value_kind,
        value_fields=value_fields,
        eligibility_status=eligibility.status,
        eligibility_policy_id=eligibility.policy_id,
        eligibility_policy_version=eligibility.policy_version,
        eligibility_reason_codes=eligibility.reason_codes,
    )


def _authorized_detail_to_dict(
    detail: AuthorizedEvidenceDetailExplanation,
) -> dict[str, object]:
    item = detail.item
    return {
        "status": detail.status,
        "reason_code": detail.reason_code,
        "item": (
            None
            if item is None
            else {
                "item_id": item.item_id,
                "student_id": item.student_id,
                "target_kind": item.target_kind,
                "target_id": item.target_id,
                "standard_ids": list(item.standard_ids),
                "result_kind": item.result_kind,
                "value_kind": item.value_kind,
                "value_fields": {
                    field.key: field.value for field in item.value_fields
                },
                "eligibility": {
                    "status": item.eligibility_status,
                    "policy_id": item.eligibility_policy_id,
                    "policy_version": item.eligibility_policy_version,
                    "reason_codes": list(item.eligibility_reason_codes),
                },
            }
        ),
    }


def _resolve_evidence(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
) -> tuple[EvidenceSourceExplanation, ...]:
    outcome_by_source = {
        explanation.source_key: explanation
        for explanation in snapshot.outcome.explanation_entries
    }
    if len(outcome_by_source) != len(snapshot.outcome.explanation_entries):
        raise ExplanationTraceIntegrityError(
            "Calculation explanation contains duplicate source identities."
        )
    result: list[EvidenceSourceExplanation] = []
    seen: set[str] = set()
    for entry in snapshot.inputs.entries:
        key = evidence_source_key(entry.source)
        seen.add(key)
        result_entry = outcome_by_source.get(key)
        if result_entry is None:
            raise ExplanationTraceIntegrityError(
                "Calculation explanation is missing an exact aggregation source."
            )
        _verify_result_entry_matches_input(entry, result_entry)
        stages = _resolve_entry_stages(workspace_root, snapshot, entry)
        native_state_code = (
            None if entry.native_state is None else entry.native_state.code
        )
        result.append(
            EvidenceSourceExplanation(
                source_key=key,
                source=entry.source,
                result_kind=entry.result_kind,
                target_kind=entry.target_kind,
                aggregation_status=entry.status,
                exclusion_reason=entry.exclusion_reason,
                mapping_status=entry.mapping_status,
                proficiency_level_id=entry.proficiency_level_id,
                native_state_code=native_state_code,
                stages=stages,
            )
        )
    if seen != set(outcome_by_source):
        raise ExplanationTraceIntegrityError(
            "Calculation explanation contains a source absent from aggregation inputs."
        )
    return tuple(result)


def _verify_result_entry_matches_input(
    entry: StandardAggregationInputEntry,
    result_entry: StandardProficiencyEntryExplanation,
) -> None:
    status = result_entry.status
    level_id = result_entry.proficiency_level_id
    native_code = result_entry.native_state_code
    exclusion = result_entry.exclusion_reason
    expected_native = None if entry.native_state is None else entry.native_state.code
    if (
        status != entry.status
        or level_id != entry.proficiency_level_id
        or native_code != expected_native
        or exclusion != entry.exclusion_reason
    ):
        raise ExplanationTraceIntegrityError(
            "Calculation explanation does not match its exact aggregation input."
        )


def _resolve_entry_stages(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> tuple[ProvenanceStageExplanation, ...]:
    stages = (
        _membership_stage(workspace_root, snapshot, entry),
        _eligibility_stage(workspace_root, snapshot, entry),
        _attempt_stage(workspace_root, snapshot, entry),
        _reassessment_stage(workspace_root, snapshot, entry),
        _association_stage(workspace_root, snapshot, entry),
        _mapping_stage(workspace_root, snapshot.target_scale, entry),
    )
    if tuple(stage.name for stage in stages) != _GRADE_ITEM_STAGE_NAMES:
        raise ExplanationTraceIntegrityError(
            "Internal provenance-stage order is invalid."
        )
    return stages


def _membership_stage(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.membership_reference
    if reference is None:
        return _missing_stage("membership", entry.exclusion_reason)
    _require_reference_kind(reference, "membership")
    try:
        stored = load_grade_item_membership_revision(
            workspace_root,
            snapshot.class_id,
            snapshot.grade_item_id,
            entry.source.work,
            reference.revision,
        )
    except GradeItemMembershipStorageError as error:
        raise _dependency_error("membership", error) from error
    _require_digest("membership", stored.decision_sha256, reference.decision_sha256)
    decision = stored.decision
    grade_item_basis = snapshot.inputs.grade_item
    if (
        decision.grade_item_revision != grade_item_basis.grade_item_revision
        or decision.grade_item_revision_sha256
        != grade_item_basis.grade_item_revision_sha256
    ):
        raise ExplanationTraceIntegrityError(
            "Membership decision does not bind the exact Grade Item revision "
            "used by the proficiency result."
        )
    return ProvenanceStageExplanation(
        "membership",
        "verified",
        reference.revision,
        reference.decision_sha256,
        (
            TraceField("decision", decision.decision),
            TraceField("actor_id", decision.actor_id),
            TraceField("rationale", decision.rationale),
            TraceField(
                "registration_revision",
                decision.work_reference.registration_revision,
            ),
        ),
    )


def _eligibility_stage(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.eligibility_reference
    if reference is None:
        return _missing_stage("eligibility", entry.exclusion_reason)
    _require_reference_kind(reference, "eligibility")
    try:
        stored = load_evidence_eligibility_revision(
            workspace_root,
            snapshot.class_id,
            snapshot.grade_item_id,
            entry.source,
            reference.revision,
        )
    except EvidenceEligibilityStorageError as error:
        raise _dependency_error("eligibility", error) from error
    _require_digest("eligibility", stored.decision_sha256, reference.decision_sha256)
    decision = stored.decision
    membership = entry.membership_reference
    if membership is not None and (
        decision.membership_revision != membership.revision
        or decision.membership_revision_sha256 != membership.decision_sha256
    ):
        raise ExplanationTraceIntegrityError(
            "Eligibility decision does not bind the exact membership reference "
            "stored by the aggregation input."
        )
    return ProvenanceStageExplanation(
        "eligibility",
        "verified",
        reference.revision,
        reference.decision_sha256,
        (
            TraceField("disposition", decision.disposition),
            TraceField("actor_kind", decision.actor.kind),
            TraceField("actor_id", decision.actor.actor_id),
            TraceField("reason_codes", ",".join(decision.reason_codes)),
            TraceField("source_state", decision.source_state.state),
            TraceField("rationale", decision.rationale),
        ),
    )


def _attempt_stage(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.attempt_selection_reference
    if reference is None:
        return _missing_stage("attempt_selection", entry.exclusion_reason)
    _require_reference_kind(reference, "attempt_selection")
    try:
        stored = load_attempt_selection_decision_revision(
            workspace_root,
            snapshot.class_id,
            snapshot.grade_item_id,
            entry.source.work,
            snapshot.student_id,
            reference.revision,
        )
    except AttemptSelectionStorageError as error:
        raise _dependency_error("attempt selection", error) from error
    _require_digest(
        "attempt selection",
        stored.decision_sha256,
        reference.decision_sha256,
    )
    decision = stored.decision
    membership = entry.membership_reference
    if membership is not None and (
        decision.membership_revision != membership.revision
        or decision.membership_revision_sha256 != membership.decision_sha256
    ):
        raise ExplanationTraceIntegrityError(
            "Attempt-selection decision does not bind the exact membership reference "
            "stored by the aggregation input."
        )
    return ProvenanceStageExplanation(
        "attempt_selection",
        "verified",
        reference.revision,
        reference.decision_sha256,
        (
            TraceField("selected_attempt_count", len(decision.selected_attempts)),
            TraceField("candidate_count", len(decision.candidates)),
            TraceField("actor_kind", decision.actor.kind),
            TraceField("actor_id", decision.actor.actor_id),
            TraceField("rationale", decision.rationale),
        ),
    )


def _reassessment_stage(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.reassessment_reference
    if reference is None:
        return _missing_stage("reassessment", entry.exclusion_reason)
    _require_reference_kind(reference, "reassessment")
    try:
        stored = load_reassessment_decision_revision(
            workspace_root,
            snapshot.class_id,
            snapshot.grade_item_id,
            entry.source.work,
            snapshot.student_id,
            reference.revision,
        )
    except ReassessmentStorageError as error:
        raise _dependency_error("reassessment", error) from error
    _require_digest("reassessment", stored.decision_sha256, reference.decision_sha256)
    decision = stored.decision
    attempt = entry.attempt_selection_reference
    if attempt is not None and (
        decision.attempt_selection.decision_revision != attempt.revision
        or decision.attempt_selection.decision_sha256 != attempt.decision_sha256
    ):
        raise ExplanationTraceIntegrityError(
            "Reassessment decision does not bind the exact attempt-selection "
            "reference stored by the aggregation input."
        )
    return ProvenanceStageExplanation(
        "reassessment",
        "verified",
        reference.revision,
        reference.decision_sha256,
        (
            TraceField("mode", decision.mode),
            TraceField(
                "contributing_attempt_count",
                len(decision.contributing_attempts),
            ),
            TraceField("actor_kind", decision.actor.kind),
            TraceField("actor_id", decision.actor.actor_id),
            TraceField("rationale", decision.rationale),
        ),
    )


def _association_stage(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.association_reference
    if reference is None:
        return _missing_stage("standard_association", entry.exclusion_reason)
    try:
        stored = load_standard_evidence_association_revision(
            workspace_root,
            reference.class_id,
            reference.grade_item_id,
            reference.source,
            reference.standard_id,
            reference.association_revision,
        )
    except StandardsEvidenceStorageError as error:
        raise _dependency_error("standard association", error) from error
    _require_digest(
        "standard association",
        stored.decision_sha256,
        reference.decision_sha256,
    )
    if stored.reference != reference:
        raise ExplanationTraceIntegrityError(
            "Standard-association identity does not match aggregation provenance."
        )
    if (
        reference.class_id != snapshot.class_id
        or reference.grade_item_id != snapshot.grade_item_id
        or reference.source != entry.source
        or reference.standard_id != snapshot.standard_id
    ):
        raise ExplanationTraceIntegrityError(
            "Standard-association scope does not match the exact proficiency result."
        )
    decision = stored.decision
    return ProvenanceStageExplanation(
        "standard_association",
        "verified",
        reference.association_revision,
        reference.decision_sha256,
        (
            TraceField("disposition", decision.disposition),
            TraceField("basis", decision.basis),
            TraceField("actor_kind", decision.actor.kind),
            TraceField("actor_id", decision.actor.actor_id),
            TraceField("rationale", decision.rationale),
        ),
    )


def _mapping_stage(
    workspace_root: str | Path,
    target_scale: ProficiencyScaleReference,
    entry: StandardAggregationInputEntry,
) -> ProvenanceStageExplanation:
    reference = entry.mapping_profile_reference
    if reference is None:
        return _missing_stage("mapping_profile", entry.exclusion_reason)
    try:
        stored = load_mapping_profile_revision(
            workspace_root,
            reference.class_id,
            reference.scale_id,
            reference.profile_id,
            reference.profile_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise _dependency_error("mapping profile", error) from error
    _require_digest("mapping profile", stored.profile_sha256, reference.profile_sha256)
    if stored.reference != reference:
        raise ExplanationTraceIntegrityError(
            "Mapping-profile identity does not match aggregation provenance."
        )
    profile = stored.profile
    if (
        profile.source_signature.result_kind != entry.result_kind
        or profile.source_signature.target_kind != entry.target_kind
    ):
        raise ExplanationTraceIntegrityError(
            "Mapping profile source signature does not match the exact aggregation "
            "entry kind."
        )
    if profile.target_scale != target_scale:
        raise ExplanationTraceIntegrityError(
            "Mapping profile does not bind the exact proficiency scale used by result."
        )
    return ProvenanceStageExplanation(
        "mapping_profile",
        "verified",
        reference.profile_revision,
        reference.profile_sha256,
        (
            TraceField("mapping_status", entry.mapping_status),
            TraceField("mapping_kind", profile.mapping_kind),
            TraceField("actor_kind", profile.actor.kind),
            TraceField("actor_id", profile.actor.actor_id),
            TraceField("rationale", profile.rationale),
        ),
    )


def _missing_stage(
    name: ProvenanceStageName,
    exclusion_reason: StandardAggregationExclusionReason | None,
) -> ProvenanceStageExplanation:
    if name == "attempt_selection":
        status: ProvenanceStageStatus = (
            "unresolved"
            if exclusion_reason == "attempt_selection_unresolved"
            else "not_applicable"
        )
    elif name == "reassessment":
        status = (
            "unresolved"
            if exclusion_reason == "reassessment_unresolved"
            else "not_applicable"
        )
    elif name == "standard_association":
        status = (
            "unresolved"
            if exclusion_reason == "association_unresolved"
            else "not_reached"
        )
    elif name == "mapping_profile":
        if exclusion_reason == "mapping_not_supplied":
            status = "not_supplied"
        else:
            status = "not_reached"
    elif name == "eligibility" and exclusion_reason == "eligibility_unresolved":
        status = "unresolved"
    else:
        status = "not_reached"
    return ProvenanceStageExplanation(name, status, None, None)


def _calculation_projection(
    outcome: StandardProficiencyCalculationOutcome,
) -> GradeItemCalculationExplanation:
    return GradeItemCalculationExplanation(
        status=outcome.status,
        proficiency_level_id=outcome.proficiency_level_id,
        performance_observation_count=outcome.performance_observation_count,
        native_state_count=outcome.native_state_count,
        excluded_count=outcome.excluded_count,
        level_counts=outcome.level_counts,
        insufficiency_reasons=outcome.insufficiency_reasons,
        tie_resolution=outcome.tie_resolution,
    )


def _require_reference_kind(
    reference: AggregationDecisionReference,
    expected: Literal[
        "membership", "eligibility", "attempt_selection", "reassessment"
    ],
) -> None:
    if reference.decision_kind != expected:
        raise ExplanationTraceIntegrityError(
            f"Aggregation provenance expected {expected} reference but found "
            f"{reference.decision_kind}."
        )


def _require_digest(label: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ExplanationTraceIntegrityError(
            f"Exact {label} digest does not match aggregation provenance."
        )


def _dependency_error(label: str, error: Exception) -> ExplanationTraceIntegrityError:
    return ExplanationTraceIntegrityError(
        f"Exact {label} dependency could not be verified: {error}"
    )


def _identifier(value: str, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name=field_name)
    except IdentifierValidationError as error:
        raise ExplanationTraceTargetError(
            f"{field_name} is invalid: {error}"
        ) from error
