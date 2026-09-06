"""Read-only explanation for one exact #39 planning preview/review path.

The projection binds one exact content-addressed preview to its exact #38
Derivation and then resolves either the explicitly selected review or one exact
historical review revision.  Live currentness and export eligibility are read
through the existing #39/#40 services; this module does not define a second
eligibility policy, select reviews, regenerate previews, or write export state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
)
from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockedError,
    GroupingSignalExportEligibilityReadError,
    resolve_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    load_grouping_signal_policy_revision,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    GroupingSignalPreviewReference,
    GroupingSignalPreviewSnapshot,
    build_grouping_signal_preview_snapshot,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    GroupingSignalPreviewStorageNotFoundError,
    StoredGroupingSignalPreview,
    load_grouping_signal_preview,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewApplicability,
    GroupingSignalReviewReference,
    GroupingSignalReviewValidationError,
    assess_grouping_signal_review_applicability,
    validate_grouping_signal_review_against_preview,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    GroupingSignalReviewStorageNotFoundError,
    StoredGroupingSignalReview,
    load_current_grouping_signal_review,
    load_grouping_signal_review_revision,
)
from meridian.planning_signal_derivation_explanation import (
    PlanningSignalDerivationExplanation,
    PlanningSignalDerivationTraceTarget,
    explain_planning_signal_derivation,
    planning_signal_derivation_explanation_to_dict,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)

PlanningPreviewReviewSelection: TypeAlias = Literal["selected", "revision"]
PlanningReviewSelectionState: TypeAlias = Literal[
    "none_selected",
    "selected",
    "not_selected",
]
PlanningPathState: TypeAlias = Literal[
    "ready_for_review",
    "blocked",
    "accepted_but_not_selected",
    "selected_but_stale",
    "selected_and_export_eligible",
    "not_export_eligible",
]


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewReviewTraceTarget:
    """One exact preview plus an explicit review-selection interpretation."""

    class_id: str
    preview_id: str
    review_selection: PlanningPreviewReviewSelection
    review_revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        preview_id = _identifier(self.preview_id, "preview_id")
        if not preview_id.startswith("gsp_") or len(preview_id) != 68:
            raise ExplanationTraceTargetError(
                "preview_id must be gsp_ followed by a lowercase SHA-256 digest."
            )
        digest = preview_id[4:]
        if any(character not in "0123456789abcdef" for character in digest):
            raise ExplanationTraceTargetError(
                "preview_id must be gsp_ followed by a lowercase SHA-256 digest."
            )
        object.__setattr__(self, "preview_id", preview_id)

        if self.review_selection not in {"selected", "revision"}:
            raise ExplanationTraceTargetError(
                "review_selection must be selected or revision."
            )
        revision = self.review_revision
        if self.review_selection == "selected":
            if revision is not None:
                raise ExplanationTraceTargetError(
                    "selected review target must not provide review_revision."
                )
            return
        if type(revision) is not int or revision <= 0:
            raise ExplanationTraceTargetError(
                "revision review target requires a positive review_revision."
            )


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewCoverageExplanation:
    roster_student_count: int
    contributing_student_count: int
    noncontributing_student_count: int
    missing_noncontributor_count: int
    insufficient_noncontributor_count: int
    occupied_band_count: int
    empty_band_count: int


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewBandSummaryExplanation:
    band: int
    minimum_scale_position: int
    maximum_scale_position: int
    proficiency_level_ids: tuple[str, ...]
    student_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewStudentRowExplanation:
    student_id: str
    source_state: str
    disposition: str
    source_result_revision: int | None
    proficiency_level_id: str | None
    scale_position: int | None
    band: int | None


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewTieGroupExplanation:
    proficiency_level_id: str
    scale_position: int
    band: int
    student_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewDiagnosticExplanation:
    diagnostic_id: str
    code: str
    severity: str
    student_ids: tuple[str, ...]
    bands: tuple[int, ...]
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningSignalReviewExplanation:
    preview_id: str
    preview_sha256: str
    review_revision: int
    review_sha256: str
    selection_state: PlanningReviewSelectionState
    decision: str
    acknowledged_warning_ids: tuple[str, ...]
    actor_kind: str
    actor_id: str
    reviewed_at: datetime
    rationale: None
    rationale_status: str
    applicability_status: str
    applicability_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanningSignalExportEligibilityExplanation:
    eligible: bool
    block_code: str | None
    reason_codes: tuple[str, ...]
    selected_review_reference: GroupingSignalReviewReference | None
    selected_preview_reference: GroupingSignalPreviewReference | None
    target_preview_is_authorized_path: bool


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewReviewExplanation:
    class_id: str
    preview_id: str
    preview_sha256: str
    preview_algorithm_version: str
    preview_fingerprint: str
    derivation_reference: GroupingSignalDerivationReference
    policy_id: str
    policy_revision: int
    policy_sha256: str
    policy_title: str
    school_year: str
    period_id: str
    calendar_revision: int
    standard_id: str
    dimension_id: str
    band_count: int
    tie_handling: str
    missing_result_handling: str
    insufficient_result_handling: str
    snapshot_currentness: GroupingSignalPreviewCurrentness
    live_currentness: GroupingSignalPreviewCurrentness
    coverage: PlanningSignalPreviewCoverageExplanation
    band_summaries: tuple[PlanningSignalPreviewBandSummaryExplanation, ...]
    student_rows: tuple[PlanningSignalPreviewStudentRowExplanation, ...]
    tie_groups: tuple[PlanningSignalPreviewTieGroupExplanation, ...]
    diagnostics: tuple[PlanningSignalPreviewDiagnosticExplanation, ...]
    warning_diagnostic_ids: tuple[str, ...]
    blocking_diagnostic_ids: tuple[str, ...]
    review: PlanningSignalReviewExplanation | None
    export_eligibility: PlanningSignalExportEligibilityExplanation
    path_state: PlanningPathState
    nested_derivation_explanation: PlanningSignalDerivationExplanation


def explain_planning_signal_preview_review(
    workspace_root: str | Path,
    target: PlanningSignalPreviewReviewTraceTarget,
) -> PlanningSignalPreviewReviewExplanation:
    """Explain one exact #39 preview/review path without mutating workspace state."""

    if not isinstance(target, PlanningSignalPreviewReviewTraceTarget):
        raise ExplanationTraceTargetError(
            "target must be a PlanningSignalPreviewReviewTraceTarget."
        )

    preview = _resolve_preview(workspace_root, target)
    snapshot = preview.snapshot
    _verify_preview_lineage(workspace_root, preview)

    nested = explain_planning_signal_derivation(
        workspace_root,
        PlanningSignalDerivationTraceTarget(
            class_id=target.class_id,
            derivation_id=snapshot.derivation_reference.derivation_id,
        ),
    )
    if nested.derivation_sha256 != snapshot.derivation_reference.derivation_sha256:
        raise ExplanationTraceIntegrityError(
            "Nested #38 explanation digest does not match exact preview provenance."
        )

    live_currentness = _resolve_live_currentness(
        workspace_root,
        snapshot.derivation_reference,
    )
    selected_before = _load_selected_review(
        workspace_root,
        target.class_id,
        snapshot.derivation_reference.derivation_id,
    )
    review = _resolve_review(
        workspace_root,
        target,
        preview,
        selected_before,
        live_currentness,
    )
    eligibility = _resolve_export_eligibility(
        workspace_root,
        snapshot.derivation_reference,
        preview.reference,
    )
    selected_after = _load_selected_review(
        workspace_root,
        target.class_id,
        snapshot.derivation_reference.derivation_id,
    )
    if _review_reference(selected_before) != _review_reference(selected_after):
        raise ExplanationTraceIntegrityError(
            "Selected #39 review changed while resolving the explanation."
        )

    warnings = tuple(
        sorted(
            item.diagnostic_id
            for item in snapshot.diagnostics
            if item.severity == "warning"
        )
    )
    blocking = tuple(
        item.diagnostic_id
        for item in snapshot.diagnostics
        if item.severity == "blocking"
    )
    path_state = _path_state(
        target,
        review,
        blocking,
        eligibility,
    )

    basis = snapshot.academic_basis.target_period
    return PlanningSignalPreviewReviewExplanation(
        class_id=target.class_id,
        preview_id=snapshot.preview_id,
        preview_sha256=preview.preview_sha256,
        preview_algorithm_version=snapshot.preview_algorithm_version,
        preview_fingerprint=snapshot.preview_fingerprint,
        derivation_reference=snapshot.derivation_reference,
        policy_id=snapshot.policy_reference.policy_id,
        policy_revision=snapshot.policy_reference.policy_revision,
        policy_sha256=snapshot.policy_reference.policy_sha256,
        policy_title=snapshot.policy_title,
        school_year=basis.period.school_year,
        period_id=basis.period.period_id,
        calendar_revision=basis.calendar_revision,
        standard_id=snapshot.academic_basis.standard_id,
        dimension_id=snapshot.dimension_id,
        band_count=snapshot.band_count,
        tie_handling=snapshot.tie_handling,
        missing_result_handling=snapshot.missing_result_handling,
        insufficient_result_handling=snapshot.insufficient_result_handling,
        snapshot_currentness=snapshot.currentness,
        live_currentness=live_currentness,
        coverage=_coverage_projection(snapshot),
        band_summaries=_band_summary_projection(snapshot),
        student_rows=_student_row_projection(snapshot),
        tie_groups=_tie_group_projection(snapshot),
        diagnostics=_diagnostic_projection(snapshot),
        warning_diagnostic_ids=warnings,
        blocking_diagnostic_ids=blocking,
        review=review,
        export_eligibility=eligibility,
        path_state=path_state,
        nested_derivation_explanation=nested,
    )


def planning_signal_preview_review_explanation_to_dict(
    value: PlanningSignalPreviewReviewExplanation,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one #39 path explanation."""

    if not isinstance(value, PlanningSignalPreviewReviewExplanation):
        raise ExplanationTraceTargetError(
            "value must be a PlanningSignalPreviewReviewExplanation."
        )
    return {
        "target": {
            "class_id": value.class_id,
            "preview_id": value.preview_id,
            "preview_sha256": value.preview_sha256,
        },
        "preview_identity": {
            "preview_algorithm_version": value.preview_algorithm_version,
            "preview_fingerprint": value.preview_fingerprint,
            "derivation_reference": _derivation_ref_dict(
                value.derivation_reference
            ),
        },
        "planning_basis": {
            "policy_id": value.policy_id,
            "policy_revision": value.policy_revision,
            "policy_sha256": value.policy_sha256,
            "policy_title": value.policy_title,
            "school_year": value.school_year,
            "period_id": value.period_id,
            "calendar_revision": value.calendar_revision,
            "standard_id": value.standard_id,
            "dimension_id": value.dimension_id,
            "band_count": value.band_count,
            "tie_handling": value.tie_handling,
            "missing_result_handling": value.missing_result_handling,
            "insufficient_result_handling": value.insufficient_result_handling,
        },
        "snapshot_currentness": _currentness_dict(value.snapshot_currentness),
        "live_currentness": _currentness_dict(value.live_currentness),
        "coverage": {
            "roster_student_count": value.coverage.roster_student_count,
            "contributing_student_count": (
                value.coverage.contributing_student_count
            ),
            "noncontributing_student_count": (
                value.coverage.noncontributing_student_count
            ),
            "missing_noncontributor_count": (
                value.coverage.missing_noncontributor_count
            ),
            "insufficient_noncontributor_count": (
                value.coverage.insufficient_noncontributor_count
            ),
            "occupied_band_count": value.coverage.occupied_band_count,
            "empty_band_count": value.coverage.empty_band_count,
        },
        "band_summaries": [
            {
                "band": item.band,
                "minimum_scale_position": item.minimum_scale_position,
                "maximum_scale_position": item.maximum_scale_position,
                "proficiency_level_ids": list(item.proficiency_level_ids),
                "student_ids": list(item.student_ids),
            }
            for item in value.band_summaries
        ],
        "student_rows": [
            {
                "student_id": item.student_id,
                "source_state": item.source_state,
                "disposition": item.disposition,
                "source_result_revision": item.source_result_revision,
                "proficiency_level_id": item.proficiency_level_id,
                "scale_position": item.scale_position,
                "band": item.band,
            }
            for item in value.student_rows
        ],
        "tie_groups": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "scale_position": item.scale_position,
                "band": item.band,
                "student_ids": list(item.student_ids),
            }
            for item in value.tie_groups
        ],
        "diagnostics": [
            {
                "diagnostic_id": item.diagnostic_id,
                "code": item.code,
                "severity": item.severity,
                "student_ids": list(item.student_ids),
                "bands": list(item.bands),
                "details": list(item.details),
            }
            for item in value.diagnostics
        ],
        "warning_diagnostic_ids": list(value.warning_diagnostic_ids),
        "blocking_diagnostic_ids": list(value.blocking_diagnostic_ids),
        "review": _review_dict(value.review),
        "export_eligibility": _eligibility_dict(value.export_eligibility),
        "path_state": value.path_state,
        "derivation": planning_signal_derivation_explanation_to_dict(
            value.nested_derivation_explanation
        ),
    }


def planning_signal_preview_review_explanation_to_json_bytes(
    value: PlanningSignalPreviewReviewExplanation,
) -> bytes:
    return (
        json.dumps(
            planning_signal_preview_review_explanation_to_dict(value),
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def render_planning_signal_preview_review_explanation_text(
    value: PlanningSignalPreviewReviewExplanation,
) -> str:
    """Render a compact teacher-readable exact #39 planning path explanation."""

    lines = [
        "Planning preview/review explanation",
        f"class: {value.class_id}",
        f"preview: {value.preview_id}",
        f"preview_sha256: {value.preview_sha256}",
        f"path_state: {value.path_state}",
        (
            "derivation: "
            f"{value.derivation_reference.derivation_id} "
            f"sha256={value.derivation_reference.derivation_sha256}"
        ),
        (
            "policy: "
            f"{value.policy_id} revision={value.policy_revision} "
            f"sha256={value.policy_sha256}"
        ),
        (
            "academic_basis: "
            f"{value.school_year}/{value.period_id} "
            f"calendar_revision={value.calendar_revision} "
            f"standard={value.standard_id}"
        ),
        (
            "snapshot_currentness: "
            f"{value.snapshot_currentness.state} "
            f"reasons={_csv(value.snapshot_currentness.reason_codes)}"
        ),
        (
            "live_currentness: "
            f"{value.live_currentness.state} "
            f"reasons={_csv(value.live_currentness.reason_codes)}"
        ),
        (
            "coverage: "
            f"roster={value.coverage.roster_student_count} "
            f"contributing={value.coverage.contributing_student_count} "
            f"noncontributing={value.coverage.noncontributing_student_count}"
        ),
        (
            "diagnostics: "
            f"warnings={len(value.warning_diagnostic_ids)} "
            f"blocking={len(value.blocking_diagnostic_ids)}"
        ),
    ]
    if value.review is None:
        lines.append("review: none selected")
    else:
        review = value.review
        lines.extend(
            [
                (
                    "review: "
                    f"preview={review.preview_id} "
                    f"revision={review.review_revision} "
                    f"sha256={review.review_sha256} "
                    f"selection={review.selection_state}"
                ),
                f"review_decision: {review.decision}",
                (
                    "warning_acknowledgments: "
                    f"{_csv(review.acknowledged_warning_ids)}"
                ),
                f"review_actor: {review.actor_kind}:{review.actor_id}",
                f"reviewed_at: {review.reviewed_at.isoformat()}",
                (
                    "review_rationale: not represented by "
                    "meridian_grouping_signal_review v1"
                ),
                (
                    "review_applicability: "
                    f"{review.applicability_status} "
                    f"reasons={_csv(review.applicability_reason_codes)}"
                ),
            ]
        )
    eligibility = value.export_eligibility
    if eligibility.eligible:
        lines.append("export_eligibility: eligible")
    else:
        lines.append(
            "export_eligibility: blocked "
            f"code={eligibility.block_code or 'path_not_authorized'} "
            f"reasons={_csv(eligibility.reason_codes)}"
        )
    lines.append(
        "target_preview_is_authorized_path: "
        + ("yes" if eligibility.target_preview_is_authorized_path else "no")
    )
    for diagnostic in value.diagnostics:
        lines.append(
            f"diagnostic[{diagnostic.severity}]: {diagnostic.code} "
            f"id={diagnostic.diagnostic_id}"
        )
    for row in value.student_rows:
        band = "none" if row.band is None else str(row.band)
        lines.append(
            f"student[{row.student_id}]: source={row.source_state} "
            f"disposition={row.disposition} band={band}"
        )
    return "\n".join(lines) + "\n"


def _resolve_preview(
    workspace_root: str | Path,
    target: PlanningSignalPreviewReviewTraceTarget,
) -> StoredGroupingSignalPreview:
    try:
        return load_grouping_signal_preview(
            workspace_root,
            target.class_id,
            target.preview_id,
        )
    except GroupingSignalPreviewStorageNotFoundError as error:
        raise ExplanationTraceNotFoundError(
            "Exact #39 planning preview does not exist."
        ) from error
    except GroupingSignalPreviewStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #39 planning preview could not be verified."
        ) from error


def _verify_preview_lineage(
    workspace_root: str | Path,
    stored_preview: StoredGroupingSignalPreview,
) -> None:
    preview = stored_preview.snapshot
    try:
        derivation = load_grouping_signal_derivation_reference(
            workspace_root,
            preview.derivation_reference,
        )
        policy = load_grouping_signal_policy_revision(
            workspace_root,
            preview.policy_reference.class_id,
            preview.policy_reference.policy_id,
            preview.policy_reference.policy_revision,
        )
        scale_ref = preview.academic_basis.target_scale
        scale = load_proficiency_scale_revision(
            workspace_root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except (
        GroupingSignalDerivationStorageError,
        GroupingSignalPolicyStorageError,
        ProficiencyMappingStorageError,
    ) as error:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview derivation/policy/scale provenance is unavailable."
        ) from error

    if policy.policy_sha256 != preview.policy_reference.policy_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview policy digest does not match stored provenance."
        )
    if scale.scale_sha256 != scale_ref.scale_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview scale digest does not match stored provenance."
        )
    try:
        rebuilt = build_grouping_signal_preview_snapshot(
            derivation.snapshot,
            policy.policy,
            scale.scale,
            preview.currentness,
        )
    except ValueError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview cannot be reconstructed from its bound inputs."
        ) from error
    if rebuilt != preview:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview does not match its deterministic bound inputs."
        )


def _resolve_live_currentness(
    workspace_root: str | Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> GroupingSignalPreviewCurrentness:
    try:
        return assess_grouping_signal_derivation_currentness(
            workspace_root,
            derivation_reference,
        )
    except GroupingSignalCurrentnessError as error:
        raise ExplanationTraceIntegrityError(
            "Live #38 currentness could not be resolved safely."
        ) from error


def _load_selected_review(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> StoredGroupingSignalReview | None:
    try:
        return load_current_grouping_signal_review(
            workspace_root,
            class_id,
            derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Explicitly selected #39 review could not be verified."
        ) from error


def _resolve_review(
    workspace_root: str | Path,
    target: PlanningSignalPreviewReviewTraceTarget,
    preview: StoredGroupingSignalPreview,
    selected: StoredGroupingSignalReview | None,
    live_currentness: GroupingSignalPreviewCurrentness,
) -> PlanningSignalReviewExplanation | None:
    derivation_id = preview.snapshot.derivation_reference.derivation_id
    if target.review_selection == "selected":
        if selected is None:
            return None
        stored = selected
        if stored.review.preview_reference != preview.reference:
            return _review_projection(
                stored,
                "selected",
                live_currentness,
                validate_against=None,
            )
    else:
        assert target.review_revision is not None
        try:
            stored = load_grouping_signal_review_revision(
                workspace_root,
                target.class_id,
                derivation_id,
                target.review_revision,
            )
        except GroupingSignalReviewStorageNotFoundError as error:
            raise ExplanationTraceNotFoundError(
                "Exact #39 review revision does not exist."
            ) from error
        except GroupingSignalReviewStorageError as error:
            raise ExplanationTraceIntegrityError(
                "Exact #39 review revision could not be verified."
            ) from error
        if stored.review.preview_reference != preview.reference:
            raise ExplanationTraceTargetError(
                "Exact review revision does not bind the target preview."
            )

    try:
        validate_grouping_signal_review_against_preview(
            stored.review,
            preview.snapshot,
        )
    except GroupingSignalReviewValidationError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #39 review does not validate against its target preview."
        ) from error

    selection_state: PlanningReviewSelectionState = "not_selected"
    if selected is not None and selected.reference == stored.reference:
        selection_state = "selected"
    return _review_projection(
        stored,
        selection_state,
        live_currentness,
        validate_against=preview,
    )


def _review_projection(
    stored: StoredGroupingSignalReview,
    selection_state: PlanningReviewSelectionState,
    live_currentness: GroupingSignalPreviewCurrentness,
    *,
    validate_against: StoredGroupingSignalPreview | None,
) -> PlanningSignalReviewExplanation:
    review = stored.review
    if validate_against is not None:
        try:
            validate_grouping_signal_review_against_preview(
                review,
                validate_against.snapshot,
            )
        except GroupingSignalReviewValidationError as error:
            raise ExplanationTraceIntegrityError(
                "Exact #39 review no longer validates against its preview."
            ) from error
    try:
        applicability = assess_grouping_signal_review_applicability(
            review,
            live_currentness,
        )
    except GroupingSignalReviewValidationError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #39 review applicability could not be assessed."
        ) from error
    return _review_projection_from_applicability(
        stored,
        selection_state,
        applicability,
    )


def _review_projection_from_applicability(
    stored: StoredGroupingSignalReview,
    selection_state: PlanningReviewSelectionState,
    applicability: GroupingSignalReviewApplicability,
) -> PlanningSignalReviewExplanation:
    review = stored.review
    return PlanningSignalReviewExplanation(
        preview_id=review.preview_reference.preview_id,
        preview_sha256=review.preview_reference.preview_sha256,
        review_revision=review.review_revision,
        review_sha256=stored.review_sha256,
        selection_state=selection_state,
        decision=review.decision,
        acknowledged_warning_ids=review.acknowledged_warning_ids,
        actor_kind=review.actor.kind,
        actor_id=review.actor.actor_id,
        reviewed_at=review.reviewed_at,
        rationale=None,
        rationale_status="not_represented_by_grouping_signal_review_v1",
        applicability_status=applicability.status,
        applicability_reason_codes=applicability.reason_codes,
    )


def _resolve_export_eligibility(
    workspace_root: str | Path,
    derivation_reference: GroupingSignalDerivationReference,
    target_preview_reference: GroupingSignalPreviewReference,
) -> PlanningSignalExportEligibilityExplanation:
    try:
        eligibility = resolve_grouping_signal_export_eligibility(
            workspace_root,
            derivation_reference.class_id,
            derivation_reference.derivation_id,
        )
    except GroupingSignalExportBlockedError as error:
        selected = _load_selected_review(
            workspace_root,
            derivation_reference.class_id,
            derivation_reference.derivation_id,
        )
        selected_preview = (
            None if selected is None else selected.review.preview_reference
        )
        return PlanningSignalExportEligibilityExplanation(
            eligible=False,
            block_code=error.code,
            reason_codes=error.reason_codes,
            selected_review_reference=(
                None if selected is None else selected.reference
            ),
            selected_preview_reference=selected_preview,
            target_preview_is_authorized_path=(
                selected_preview == target_preview_reference
            ),
        )
    except GroupingSignalExportEligibilityReadError as error:
        raise ExplanationTraceIntegrityError(
            "#40 export eligibility could not be resolved safely."
        ) from error

    return PlanningSignalExportEligibilityExplanation(
        eligible=True,
        block_code=None,
        reason_codes=(),
        selected_review_reference=eligibility.review_reference,
        selected_preview_reference=eligibility.preview_reference,
        target_preview_is_authorized_path=(
            eligibility.preview_reference == target_preview_reference
        ),
    )


def _path_state(
    target: PlanningSignalPreviewReviewTraceTarget,
    review: PlanningSignalReviewExplanation | None,
    blocking_diagnostic_ids: tuple[str, ...],
    eligibility: PlanningSignalExportEligibilityExplanation,
) -> PlanningPathState:
    if blocking_diagnostic_ids:
        return "blocked"
    if review is None:
        return "ready_for_review"
    if (
        target.review_selection == "revision"
        and review.decision == "accepted_for_export"
        and review.selection_state != "selected"
    ):
        return "accepted_but_not_selected"
    if review.selection_state == "selected":
        if (
            eligibility.eligible
            and eligibility.target_preview_is_authorized_path
        ):
            return "selected_and_export_eligible"
        if eligibility.block_code in {"review_stale", "derivation_not_current"}:
            return "selected_but_stale"
    return "not_export_eligible"


def _coverage_projection(
    snapshot: GroupingSignalPreviewSnapshot,
) -> PlanningSignalPreviewCoverageExplanation:
    value = snapshot.coverage
    return PlanningSignalPreviewCoverageExplanation(
        roster_student_count=value.roster_student_count,
        contributing_student_count=value.contributing_student_count,
        noncontributing_student_count=value.noncontributing_student_count,
        missing_noncontributor_count=value.missing_noncontributor_count,
        insufficient_noncontributor_count=value.insufficient_noncontributor_count,
        occupied_band_count=value.occupied_band_count,
        empty_band_count=value.empty_band_count,
    )


def _band_summary_projection(
    snapshot: GroupingSignalPreviewSnapshot,
) -> tuple[PlanningSignalPreviewBandSummaryExplanation, ...]:
    return tuple(
        PlanningSignalPreviewBandSummaryExplanation(
            band=item.band,
            minimum_scale_position=item.minimum_scale_position,
            maximum_scale_position=item.maximum_scale_position,
            proficiency_level_ids=item.proficiency_level_ids,
            student_ids=item.student_ids,
        )
        for item in snapshot.band_summaries
    )


def _student_row_projection(
    snapshot: GroupingSignalPreviewSnapshot,
) -> tuple[PlanningSignalPreviewStudentRowExplanation, ...]:
    return tuple(
        PlanningSignalPreviewStudentRowExplanation(
            student_id=item.student_id,
            source_state=item.source_state,
            disposition=item.disposition,
            source_result_revision=(
                None
                if item.source_result is None
                else item.source_result.result_revision
            ),
            proficiency_level_id=item.proficiency_level_id,
            scale_position=item.scale_position,
            band=item.band,
        )
        for item in snapshot.student_rows
    )


def _tie_group_projection(
    snapshot: GroupingSignalPreviewSnapshot,
) -> tuple[PlanningSignalPreviewTieGroupExplanation, ...]:
    return tuple(
        PlanningSignalPreviewTieGroupExplanation(
            proficiency_level_id=item.proficiency_level_id,
            scale_position=item.scale_position,
            band=item.band,
            student_ids=item.student_ids,
        )
        for item in snapshot.tie_groups
    )


def _diagnostic_projection(
    snapshot: GroupingSignalPreviewSnapshot,
) -> tuple[PlanningSignalPreviewDiagnosticExplanation, ...]:
    return tuple(
        PlanningSignalPreviewDiagnosticExplanation(
            diagnostic_id=item.diagnostic_id,
            code=item.code,
            severity=item.severity,
            student_ids=item.student_ids,
            bands=item.bands,
            details=item.details,
        )
        for item in snapshot.diagnostics
    )


def _review_reference(
    stored: StoredGroupingSignalReview | None,
) -> object | None:
    return None if stored is None else stored.reference


def _review_dict(
    review: PlanningSignalReviewExplanation | None,
) -> dict[str, object] | None:
    if review is None:
        return None
    return {
        "preview_id": review.preview_id,
        "preview_sha256": review.preview_sha256,
        "review_revision": review.review_revision,
        "review_sha256": review.review_sha256,
        "selection_state": review.selection_state,
        "decision": review.decision,
        "acknowledged_warning_ids": list(review.acknowledged_warning_ids),
        "actor": {
            "kind": review.actor_kind,
            "actor_id": review.actor_id,
        },
        "reviewed_at": review.reviewed_at.isoformat(),
        "rationale": review.rationale,
        "rationale_status": review.rationale_status,
        "applicability": {
            "status": review.applicability_status,
            "reason_codes": list(review.applicability_reason_codes),
        },
    }


def _eligibility_dict(
    value: PlanningSignalExportEligibilityExplanation,
) -> dict[str, object]:
    return {
        "eligible": value.eligible,
        "block_code": value.block_code,
        "reason_codes": list(value.reason_codes),
        "selected_review_reference": _generic_reference_dict(
            value.selected_review_reference
        ),
        "selected_preview_reference": _preview_ref_dict(
            value.selected_preview_reference
        ),
        "target_preview_is_authorized_path": (
            value.target_preview_is_authorized_path
        ),
    }


def _generic_reference_dict(
    value: GroupingSignalReviewReference | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "class_id": value.class_id,
        "derivation_id": value.derivation_id,
        "review_revision": value.review_revision,
        "review_sha256": value.review_sha256,
    }


def _preview_ref_dict(
    value: GroupingSignalPreviewReference | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "class_id": value.class_id,
        "preview_id": value.preview_id,
        "preview_sha256": value.preview_sha256,
    }


def _derivation_ref_dict(
    value: GroupingSignalDerivationReference,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "derivation_id": value.derivation_id,
        "derivation_sha256": value.derivation_sha256,
    }


def _currentness_dict(
    value: GroupingSignalPreviewCurrentness,
) -> dict[str, object]:
    return {
        "state": value.state,
        "reason_codes": list(value.reason_codes),
        "current_derivation_reference": (
            None
            if value.current_derivation_reference is None
            else _derivation_ref_dict(value.current_derivation_reference)
        ),
    }


def _csv(values: tuple[str, ...]) -> str:
    return "none" if not values else ",".join(values)


def _identifier(value: str, name: str) -> str:
    try:
        return validate_identifier(value, name)
    except IdentifierValidationError as error:
        raise ExplanationTraceTargetError(str(error)) from error
