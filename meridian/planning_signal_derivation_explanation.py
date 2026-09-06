"""Read-only explanation for one exact #38 planning-signal derivation.

The projection follows only identities already stored by the immutable #38
snapshot.  It verifies the exact #37 policy, exact proficiency scale, exact
Academic Period policy, and every exact #35 source-result reference before
presenting the contextual-band decision.  It never resolves a "latest"
derivation, reruns #38 generation/currentness, or substitutes a current #35
result for the historical revision bound by the derivation.
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
from pds_core.class_metadata import ClassMetadataError, load_class_metadata
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_metadata_path

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
    AcademicPeriodProficiencyResultSnapshot,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodIdentityExplanation,
    AcademicPeriodProficiencyExplanation,
    AcademicPeriodProficiencyTraceTarget,
    academic_period_proficiency_explanation_to_dict,
    explain_academic_period_proficiency,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    load_academic_period_proficiency_policy_revision,
    load_academic_period_proficiency_result_revision,
)
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceError,
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
    ProficiencyLevelExplanation,
    ProficiencyScaleExplanation,
)
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationSnapshot,
    GroupingSignalStudentDerivation,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    GroupingSignalDerivationStorageNotFoundError,
    StoredGroupingSignalDerivation,
    load_grouping_signal_derivation,
)
from meridian.grouping_signal_policy import (
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyValidationError,
    validate_grouping_signal_derivation_policy_dependencies,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    StoredGroupingSignalDerivationPolicy,
    load_grouping_signal_policy_revision,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    load_proficiency_scale_revision,
)

PlanningSignalDerivationSourceState: TypeAlias = Literal[
    "calculated",
    "missing",
    "insufficient_evidence",
]
PlanningSignalDerivationDisposition: TypeAlias = Literal[
    "contributing",
    "noncontributing",
]
PlanningSignalNoncontributionReason: TypeAlias = Literal[
    "missing_result",
    "insufficient_evidence",
]


@dataclass(frozen=True, slots=True)
class PlanningSignalDerivationTraceTarget:
    """One exact immutable #38 derivation identity; there is no current target."""

    class_id: str
    derivation_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            _identifier(self.class_id, "class_id"),
        )
        derivation_id = _identifier(self.derivation_id, "derivation_id")
        if not derivation_id.startswith("gsd_") or len(derivation_id) != 68:
            raise ExplanationTraceTargetError(
                "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
            )
        digest = derivation_id[4:]
        if any(character not in "0123456789abcdef" for character in digest):
            raise ExplanationTraceTargetError(
                "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
            )
        object.__setattr__(self, "derivation_id", derivation_id)


@dataclass(frozen=True, slots=True)
class PlanningSignalBandDefinitionExplanation:
    band: int
    minimum_scale_position: int
    maximum_scale_position: int


@dataclass(frozen=True, slots=True)
class PlanningSignalDerivationPolicyExplanation:
    policy_id: str
    policy_revision: int
    policy_sha256: str
    title: str
    target_period: AcademicPeriodIdentityExplanation
    standard_id: str
    source_policy_id: str
    source_policy_revision: int
    source_policy_sha256: str
    target_scale_id: str
    target_scale_revision: int
    target_scale_sha256: str
    dimension_id: str
    band_count: int
    band_definitions: tuple[PlanningSignalBandDefinitionExplanation, ...]
    tie_handling: str
    missing_result_handling: str
    insufficient_result_handling: str
    actor_kind: str
    actor_id: str
    rationale: str | None
    revised_at: datetime


@dataclass(frozen=True, slots=True)
class PlanningSignalRosterExplanation:
    class_id: str
    student_ids: tuple[str, ...]
    membership_sha256: str


@dataclass(frozen=True, slots=True)
class PlanningSignalStudentDerivationExplanation:
    student_id: str
    source_state: PlanningSignalDerivationSourceState
    disposition: PlanningSignalDerivationDisposition
    source_result: AcademicPeriodProficiencyResultReference | None
    proficiency_level_id: str | None
    scale_position: int | None
    matching_band_definition: PlanningSignalBandDefinitionExplanation | None
    band: int | None
    noncontribution_reason: PlanningSignalNoncontributionReason | None
    policy_handling: str | None
    nested_academic_period_explanation: AcademicPeriodProficiencyExplanation | None


@dataclass(frozen=True, slots=True)
class PlanningSignalDerivationExplanation:
    """Deterministic projection for one exact immutable #38 derivation."""

    class_id: str
    derivation_id: str
    derivation_sha256: str
    algorithm_version: str
    calculation_fingerprint: str
    dimension_id: str
    band_count: int
    policy: PlanningSignalDerivationPolicyExplanation
    roster: PlanningSignalRosterExplanation
    scale: ProficiencyScaleExplanation
    students: tuple[PlanningSignalStudentDerivationExplanation, ...]


def explain_planning_signal_derivation(
    workspace_root: str | Path,
    target: PlanningSignalDerivationTraceTarget,
) -> PlanningSignalDerivationExplanation:
    """Resolve one exact #38 derivation and verify its complete planning lineage."""

    if not isinstance(target, PlanningSignalDerivationTraceTarget):
        raise ExplanationTraceTargetError(
            "target must be a PlanningSignalDerivationTraceTarget."
        )

    stored = _resolve_derivation(workspace_root, target)
    snapshot = stored.snapshot
    policy = _resolve_policy(workspace_root, snapshot)
    target_period = _resolve_policy_period(workspace_root, policy.policy)
    scale = _resolve_policy_academic_dependencies(
        workspace_root,
        policy.policy,
    )
    _verify_derivation_policy(snapshot, policy.policy)
    students = _resolve_students(
        workspace_root,
        snapshot,
        policy.policy,
        scale,
    )

    return PlanningSignalDerivationExplanation(
        class_id=snapshot.class_id,
        derivation_id=snapshot.derivation_id,
        derivation_sha256=stored.derivation_sha256,
        algorithm_version=snapshot.algorithm_version,
        calculation_fingerprint=snapshot.calculation_fingerprint,
        dimension_id=snapshot.dimension_id,
        band_count=snapshot.band_count,
        policy=_policy_projection(policy, target_period),
        roster=PlanningSignalRosterExplanation(
            class_id=snapshot.roster_basis.class_id,
            student_ids=snapshot.roster_basis.student_ids,
            membership_sha256=snapshot.roster_basis.membership_sha256,
        ),
        scale=_scale_projection(scale),
        students=students,
    )


def planning_signal_derivation_explanation_to_dict(
    value: PlanningSignalDerivationExplanation,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one #38 explanation."""

    if not isinstance(value, PlanningSignalDerivationExplanation):
        raise ExplanationTraceTargetError(
            "value must be a PlanningSignalDerivationExplanation."
        )
    return {
        "target": {
            "class_id": value.class_id,
            "derivation_id": value.derivation_id,
            "derivation_sha256": value.derivation_sha256,
        },
        "calculation_identity": {
            "algorithm_version": value.algorithm_version,
            "calculation_fingerprint": value.calculation_fingerprint,
        },
        "planning_context": {
            "dimension_id": value.dimension_id,
            "band_count": value.band_count,
        },
        "policy": {
            "policy_id": value.policy.policy_id,
            "policy_revision": value.policy.policy_revision,
            "policy_sha256": value.policy.policy_sha256,
            "title": value.policy.title,
            "academic_basis": {
                "target_period": {
                    "school_year": value.policy.target_period.school_year,
                    "period_id": value.policy.target_period.period_id,
                    "calendar_revision": (
                        value.policy.target_period.calendar_revision
                    ),
                    "label": value.policy.target_period.label,
                    "period_type": value.policy.target_period.period_type,
                    "lifecycle": value.policy.target_period.lifecycle,
                },
                "standard_id": value.policy.standard_id,
                "source_policy": {
                    "policy_id": value.policy.source_policy_id,
                    "policy_revision": value.policy.source_policy_revision,
                    "policy_sha256": value.policy.source_policy_sha256,
                },
                "target_scale": {
                    "scale_id": value.policy.target_scale_id,
                    "scale_revision": value.policy.target_scale_revision,
                    "scale_sha256": value.policy.target_scale_sha256,
                },
            },
            "dimension_id": value.policy.dimension_id,
            "band_count": value.policy.band_count,
            "band_definitions": [
                _band_definition_to_dict(item)
                for item in value.policy.band_definitions
            ],
            "tie_handling": value.policy.tie_handling,
            "missing_result_handling": value.policy.missing_result_handling,
            "insufficient_result_handling": (
                value.policy.insufficient_result_handling
            ),
            "actor": {
                "kind": value.policy.actor_kind,
                "actor_id": value.policy.actor_id,
            },
            "rationale": value.policy.rationale,
            "revised_at": value.policy.revised_at.isoformat(),
        },
        "roster_basis": {
            "class_id": value.roster.class_id,
            "student_ids": list(value.roster.student_ids),
            "membership_sha256": value.roster.membership_sha256,
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
        "students": [
            {
                "student_id": item.student_id,
                "source_state": item.source_state,
                "disposition": item.disposition,
                "source_result": (
                    _source_result_to_dict(item.source_result)
                    if item.source_result is not None
                    else None
                ),
                "proficiency_level_id": item.proficiency_level_id,
                "scale_position": item.scale_position,
                "matching_band_definition": (
                    _band_definition_to_dict(item.matching_band_definition)
                    if item.matching_band_definition is not None
                    else None
                ),
                "band": item.band,
                "noncontribution_reason": item.noncontribution_reason,
                "policy_handling": item.policy_handling,
                "academic_period_explanation": (
                    academic_period_proficiency_explanation_to_dict(
                        item.nested_academic_period_explanation
                    )
                    if item.nested_academic_period_explanation is not None
                    else None
                ),
            }
            for item in value.students
        ],
    }


def planning_signal_derivation_explanation_to_json_bytes(
    value: PlanningSignalDerivationExplanation,
) -> bytes:
    """Serialize one explanation as deterministic human-readable JSON bytes."""

    return (
        json.dumps(
            planning_signal_derivation_explanation_to_dict(value),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def render_planning_signal_derivation_explanation_text(
    value: PlanningSignalDerivationExplanation,
) -> str:
    """Render one exact #38 explanation without collapsing missing-band states."""

    if not isinstance(value, PlanningSignalDerivationExplanation):
        raise ExplanationTraceTargetError(
            "value must be a PlanningSignalDerivationExplanation."
        )
    policy = value.policy
    lines = [
        "Planning-signal derivation explanation",
        f"class_id: {value.class_id}",
        f"derivation_id: {value.derivation_id}",
        f"derivation_sha256: {value.derivation_sha256}",
        f"algorithm_version: {value.algorithm_version}",
        f"calculation_fingerprint: {value.calculation_fingerprint}",
        f"dimension_id: {value.dimension_id}",
        f"band_count: {value.band_count}",
        "",
        "Exact #37 policy",
        (
            f"policy: {policy.policy_id} revision={policy.policy_revision} "
            f"sha256={policy.policy_sha256}"
        ),
        f"title: {policy.title}",
        (
            "academic_basis: "
            f"{policy.target_period.school_year}/{policy.target_period.period_id} "
            f"calendar_revision={policy.target_period.calendar_revision} "
            f"standard={policy.standard_id}"
        ),
        (
            "source_#35_policy: "
            f"{policy.source_policy_id} revision={policy.source_policy_revision} "
            f"sha256={policy.source_policy_sha256}"
        ),
        (
            "target_scale: "
            f"{policy.target_scale_id} revision={policy.target_scale_revision} "
            f"sha256={policy.target_scale_sha256}"
        ),
        f"tie_handling: {policy.tie_handling}",
        f"missing_result_handling: {policy.missing_result_handling}",
        (
            "insufficient_result_handling: "
            f"{policy.insufficient_result_handling}"
        ),
        "band_definitions:",
    ]
    lines.extend(
        (
            f"  band={item.band} range={item.minimum_scale_position}-"
            f"{item.maximum_scale_position}"
        )
        for item in policy.band_definitions
    )
    lines.extend(
        [
            "",
            "Exact roster basis",
            f"membership_sha256: {value.roster.membership_sha256}",
            f"student_count: {len(value.roster.student_ids)}",
            "",
            "Per-student band trace",
        ]
    )
    for item in value.students:
        lines.append(
            f"student={item.student_id} source_state={item.source_state} "
            f"disposition={item.disposition}"
        )
        if item.source_result is not None:
            lines.append(
                "  source_#35: "
                f"class={item.source_result.class_id} "
                f"period={item.source_result.school_year}/"
                f"{item.source_result.period_id} "
                f"student={item.source_result.student_id} "
                f"standard={item.source_result.standard_id} "
                f"revision={item.source_result.result_revision} "
                f"sha256={item.source_result.result_sha256}"
            )
        else:
            lines.append("  source_#35: none")
        if item.band is not None:
            definition = item.matching_band_definition
            if definition is None:
                raise ExplanationTraceIntegrityError(
                    "Contributing student explanation is missing its band range."
                )
            lines.append(
                "  mapping: "
                f"level={item.proficiency_level_id} -> "
                f"scale_position={item.scale_position} -> "
                f"band_range={definition.minimum_scale_position}-"
                f"{definition.maximum_scale_position} -> band={item.band}"
            )
        else:
            lines.append(
                "  band: none "
                f"reason={item.noncontribution_reason} "
                f"policy_handling={item.policy_handling}"
            )
        nested = item.nested_academic_period_explanation
        if nested is not None:
            lines.append(
                "  #35_drill_down: "
                f"revision={nested.result_revision} "
                f"selection_state={nested.selection_state} "
                f"status={nested.calculation.status}"
            )
    return "\n".join(lines) + "\n"


def _resolve_derivation(
    workspace_root: str | Path,
    target: PlanningSignalDerivationTraceTarget,
) -> StoredGroupingSignalDerivation:
    try:
        return load_grouping_signal_derivation(
            workspace_root,
            target.class_id,
            target.derivation_id,
        )
    except GroupingSignalDerivationStorageNotFoundError as error:
        raise ExplanationTraceNotFoundError(
            "Requested exact #38 grouping-signal derivation does not exist."
        ) from error
    except GroupingSignalDerivationStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #38 grouping-signal derivation could not be verified."
        ) from error


def _resolve_policy(
    workspace_root: str | Path,
    snapshot: GroupingSignalDerivationSnapshot,
) -> StoredGroupingSignalDerivationPolicy:
    reference = snapshot.policy_reference
    try:
        stored = load_grouping_signal_policy_revision(
            workspace_root,
            reference.class_id,
            reference.policy_id,
            reference.policy_revision,
        )
    except GroupingSignalPolicyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #37 grouping-signal policy dependency is unavailable."
        ) from error
    if stored.reference != reference:
        raise ExplanationTraceIntegrityError(
            "Exact #37 grouping-signal policy digest/identity does not match #38."
        )
    return stored


def _resolve_policy_period(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
) -> AcademicPeriodIdentityExplanation:
    target = policy.academic_basis.target_period
    period_ref = target.period
    try:
        metadata = load_class_metadata(
            class_metadata_path(Path(workspace_root), policy.class_id)
        )
    except ClassMetadataError as error:
        raise ExplanationTraceIntegrityError(
            "Core class metadata required by exact #37 policy is unavailable."
        ) from error
    if (
        metadata.class_id != policy.class_id
        or metadata.school_year != period_ref.school_year
    ):
        raise ExplanationTraceIntegrityError(
            "Core class metadata does not match exact #37 policy scope."
        )
    try:
        calendar = load_academic_period_calendar_revision(
            workspace_root,
            period_ref.school_year,
            target.calendar_revision,
        )
        period = get_academic_period(calendar, period_ref.period_id)
    except (
        AcademicPeriodCalendarStorageError,
        AcademicPeriodLookupError,
    ) as error:
        raise ExplanationTraceIntegrityError(
            "Exact Core Academic Period dependency required by #37 is unavailable."
        ) from error
    return AcademicPeriodIdentityExplanation(
        school_year=period_ref.school_year,
        period_id=period_ref.period_id,
        calendar_revision=target.calendar_revision,
        label=period.label,
        period_type=period.period_type,
        lifecycle=period.lifecycle,
    )


def _resolve_policy_academic_dependencies(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
) -> StoredProficiencyScale:
    basis = policy.academic_basis
    source_reference = basis.source_policy
    try:
        source_policy = load_academic_period_proficiency_policy_revision(
            workspace_root,
            source_reference.class_id,
            source_reference.policy_id,
            source_reference.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #35 policy dependency required by #37 is unavailable."
        ) from error
    if source_policy.reference != source_reference:
        raise ExplanationTraceIntegrityError(
            "Exact #35 policy digest/identity does not match #37 provenance."
        )

    scale_reference = basis.target_scale
    try:
        scale = load_proficiency_scale_revision(
            workspace_root,
            scale_reference.class_id,
            scale_reference.scale_id,
            scale_reference.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale dependency required by #37 is unavailable."
        ) from error
    if scale.reference != scale_reference:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale digest/identity does not match #37 provenance."
        )
    if source_policy.policy.target_scale != scale_reference:
        raise ExplanationTraceIntegrityError(
            "Exact #35 source policy and #37 target scale do not agree."
        )
    try:
        validate_grouping_signal_derivation_policy_dependencies(
            policy,
            source_policy.policy,
            scale.scale,
        )
    except GroupingSignalPolicyValidationError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #37 band policy is invalid against its bound scale."
        ) from error
    return scale


def _verify_derivation_policy(
    snapshot: GroupingSignalDerivationSnapshot,
    policy: GroupingSignalDerivationPolicy,
) -> None:
    if (
        snapshot.class_id != policy.class_id
        or snapshot.dimension_id != policy.dimension_id
        or snapshot.band_count != policy.band_count
    ):
        raise ExplanationTraceIntegrityError(
            "#38 derivation scope does not agree with its exact #37 policy."
        )


def _resolve_students(
    workspace_root: str | Path,
    snapshot: GroupingSignalDerivationSnapshot,
    policy: GroupingSignalDerivationPolicy,
    scale: StoredProficiencyScale,
) -> tuple[PlanningSignalStudentDerivationExplanation, ...]:
    result: list[PlanningSignalStudentDerivationExplanation] = []
    for item in snapshot.student_derivations:
        result.append(
            _resolve_student(
                workspace_root,
                item,
                policy,
                scale,
            )
        )
    return tuple(result)


def _resolve_student(
    workspace_root: str | Path,
    item: GroupingSignalStudentDerivation,
    policy: GroupingSignalDerivationPolicy,
    scale: StoredProficiencyScale,
) -> PlanningSignalStudentDerivationExplanation:
    if item.source_state == "missing":
        if policy.missing_result_handling != "noncontributing":
            raise ExplanationTraceIntegrityError(
                "#38 contains a missing noncontributor under a blocking #37 policy."
            )
        return PlanningSignalStudentDerivationExplanation(
            student_id=item.student_id,
            source_state=item.source_state,
            disposition=item.disposition,
            source_result=None,
            proficiency_level_id=None,
            scale_position=None,
            matching_band_definition=None,
            band=None,
            noncontribution_reason="missing_result",
            policy_handling=policy.missing_result_handling,
            nested_academic_period_explanation=None,
        )

    reference = item.source_result
    if reference is None:
        raise ExplanationTraceIntegrityError(
            "#38 student derivation is missing its exact #35 source reference."
        )
    stored_result = _load_exact_source_result(workspace_root, reference)
    _verify_source_scope(stored_result.snapshot, item.student_id, policy)
    nested = _nested_academic_period_explanation(workspace_root, reference)
    if nested.result_sha256 != reference.result_sha256:
        raise ExplanationTraceIntegrityError(
            "Nested #35 explanation digest does not match #38 source provenance."
        )

    if item.source_state == "insufficient_evidence":
        if stored_result.snapshot.outcome.status != "insufficient_evidence":
            raise ExplanationTraceIntegrityError(
                "#38 insufficient source state disagrees with exact #35 result."
            )
        if policy.insufficient_result_handling != "noncontributing":
            raise ExplanationTraceIntegrityError(
                "#38 contains an insufficient noncontributor under a blocking "
                "#37 policy."
            )
        return PlanningSignalStudentDerivationExplanation(
            student_id=item.student_id,
            source_state=item.source_state,
            disposition=item.disposition,
            source_result=reference,
            proficiency_level_id=None,
            scale_position=None,
            matching_band_definition=None,
            band=None,
            noncontribution_reason="insufficient_evidence",
            policy_handling=policy.insufficient_result_handling,
            nested_academic_period_explanation=nested,
        )

    if stored_result.snapshot.outcome.status != "calculated":
        raise ExplanationTraceIntegrityError(
            "#38 calculated source state disagrees with exact #35 result."
        )
    level_id = stored_result.snapshot.outcome.proficiency_level_id
    if level_id is None or level_id != item.proficiency_level_id:
        raise ExplanationTraceIntegrityError(
            "#38 proficiency level disagrees with exact #35 result."
        )
    level = next(
        (
            candidate
            for candidate in scale.scale.levels
            if candidate.level_id == level_id
        ),
        None,
    )
    if level is None or level.position != item.scale_position:
        raise ExplanationTraceIntegrityError(
            "#38 scale position does not match the exact bound scale level."
        )
    definition = _matching_band_definition(policy, level.position)
    if definition is None or item.band != definition.band:
        raise ExplanationTraceIntegrityError(
            "#38 derived band does not match the exact #37 band definition."
        )
    return PlanningSignalStudentDerivationExplanation(
        student_id=item.student_id,
        source_state=item.source_state,
        disposition=item.disposition,
        source_result=reference,
        proficiency_level_id=level_id,
        scale_position=level.position,
        matching_band_definition=_band_definition_projection(definition),
        band=item.band,
        noncontribution_reason=None,
        policy_handling=None,
        nested_academic_period_explanation=nested,
    )


def _load_exact_source_result(
    workspace_root: str | Path,
    reference: AcademicPeriodProficiencyResultReference,
) -> StoredAcademicPeriodProficiencyResult:
    try:
        stored = load_academic_period_proficiency_result_revision(
            workspace_root,
            reference.class_id,
            reference.school_year,
            reference.period_id,
            reference.student_id,
            reference.standard_id,
            reference.result_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #35 result dependency named by #38 is unavailable."
        ) from error
    if stored.reference != reference:
        raise ExplanationTraceIntegrityError(
            "Exact #35 result digest/identity does not match #38 provenance."
        )
    return stored


def _verify_source_scope(
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    student_id: str,
    policy: GroupingSignalDerivationPolicy,
) -> None:
    basis = policy.academic_basis
    if (
        snapshot.class_id != policy.class_id
        or snapshot.student_id != student_id
        or snapshot.target_period != basis.target_period
        or snapshot.standard_id != basis.standard_id
        or snapshot.policy_reference != basis.source_policy
        or snapshot.target_scale != basis.target_scale
    ):
        raise ExplanationTraceIntegrityError(
            "Exact #35 source result does not match #37 academic basis."
        )


def _nested_academic_period_explanation(
    workspace_root: str | Path,
    reference: AcademicPeriodProficiencyResultReference,
) -> AcademicPeriodProficiencyExplanation:
    try:
        return explain_academic_period_proficiency(
            workspace_root,
            AcademicPeriodProficiencyTraceTarget(
                class_id=reference.class_id,
                school_year=reference.school_year,
                period_id=reference.period_id,
                student_id=reference.student_id,
                standard_id=reference.standard_id,
                selection="revision",
                result_revision=reference.result_revision,
            ),
        )
    except ExplanationTraceError as error:
        raise ExplanationTraceIntegrityError(
            "Exact nested #35 explanation named by #38 could not be verified."
        ) from error


def _matching_band_definition(
    policy: GroupingSignalDerivationPolicy,
    scale_position: int,
) -> GroupingSignalBandDefinition | None:
    matches = tuple(
        item
        for item in policy.band_definitions
        if item.minimum_scale_position <= scale_position <= item.maximum_scale_position
    )
    if len(matches) != 1:
        return None
    return matches[0]


def _policy_projection(
    stored: StoredGroupingSignalDerivationPolicy,
    target_period: AcademicPeriodIdentityExplanation,
) -> PlanningSignalDerivationPolicyExplanation:
    policy = stored.policy
    basis = policy.academic_basis
    return PlanningSignalDerivationPolicyExplanation(
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
        policy_sha256=stored.policy_sha256,
        title=policy.title,
        target_period=target_period,
        standard_id=basis.standard_id,
        source_policy_id=basis.source_policy.policy_id,
        source_policy_revision=basis.source_policy.policy_revision,
        source_policy_sha256=basis.source_policy.policy_sha256,
        target_scale_id=basis.target_scale.scale_id,
        target_scale_revision=basis.target_scale.scale_revision,
        target_scale_sha256=basis.target_scale.scale_sha256,
        dimension_id=policy.dimension_id,
        band_count=policy.band_count,
        band_definitions=tuple(
            _band_definition_projection(item)
            for item in policy.band_definitions
        ),
        tie_handling=policy.tie_handling,
        missing_result_handling=policy.missing_result_handling,
        insufficient_result_handling=policy.insufficient_result_handling,
        actor_kind=policy.actor.kind,
        actor_id=policy.actor.actor_id,
        rationale=policy.rationale,
        revised_at=policy.revised_at,
    )


def _scale_projection(stored: StoredProficiencyScale) -> ProficiencyScaleExplanation:
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


def _band_definition_projection(
    value: GroupingSignalBandDefinition,
) -> PlanningSignalBandDefinitionExplanation:
    return PlanningSignalBandDefinitionExplanation(
        band=value.band,
        minimum_scale_position=value.minimum_scale_position,
        maximum_scale_position=value.maximum_scale_position,
    )


def _band_definition_to_dict(
    value: PlanningSignalBandDefinitionExplanation,
) -> dict[str, int]:
    return {
        "band": value.band,
        "minimum_scale_position": value.minimum_scale_position,
        "maximum_scale_position": value.maximum_scale_position,
    }


def _source_result_to_dict(
    value: AcademicPeriodProficiencyResultReference,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "school_year": value.school_year,
        "period_id": value.period_id,
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "result_sha256": value.result_sha256,
    }


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExplanationTraceTargetError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ExplanationTraceTargetError(str(error)) from error
