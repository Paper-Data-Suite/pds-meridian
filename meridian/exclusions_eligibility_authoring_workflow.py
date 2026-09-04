"""Teacher academic eligibility authoring for the Exclusions workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceEligibilityValidationError,
    EvidenceSourceLifecycleState,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityRevisionWriteResult,
    get_current_evidence_eligibility_revision,
    list_evidence_eligibility_revisions,
    load_evidence_eligibility_revision,
    observe_evidence_source_state,
    write_evidence_eligibility_revision,
)
from meridian.exclusions_workflow import (
    ExclusionReviewRow,
    ExclusionsProjection,
    build_exclusions_projection,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

ExclusionAcademicDisposition: TypeAlias = Literal[
    "included",
    "excluded",
    "pending",
    "unsupported",
]

_ACADEMIC_DISPOSITIONS = frozenset(
    {"included", "excluded", "pending", "unsupported"}
)
_WITHDRAWN_SOURCE_STATES = frozenset(
    {"withdrawn", "withdrawn_superseded"}
)


class ExclusionEligibilityAuthoringError(RuntimeError):
    """Base workflow failure for Exclusions academic authoring."""

    code = "teacher_workflow.exclusions.eligibility_authoring_error"


class ExclusionEligibilityAuthoringScopeError(
    ExclusionEligibilityAuthoringError, ValueError
):
    """Raised for an invalid teacher academic authoring request."""

    code = "teacher_workflow.exclusions.eligibility_authoring_invalid"


class ExclusionEligibilityAuthoringStaleError(
    ExclusionEligibilityAuthoringError
):
    """Raised when reviewed state changed before immutable authoring."""

    code = "teacher_workflow.exclusions.eligibility_authoring_stale"


@dataclass(frozen=True, slots=True)
class ExclusionEligibilityAuthoringPreview:
    """Exact reviewed candidate plus immutable/CAS authoring basis."""

    projection: ExclusionsProjection
    row: ExclusionReviewRow
    candidate: EvidenceEligibilityDecision
    history: tuple[int, ...]
    latest_revision_sha256: str | None
    expected_current_eligibility_revision: int | None
    membership_revision: int
    membership_revision_sha256: str
    source_state: EvidenceSourceLifecycleState

    @property
    def item_id(self) -> str:
        return self.row.item_id

    @property
    def candidate_revision(self) -> int:
        return self.candidate.eligibility_revision

    @property
    def candidate_disposition(self) -> str:
        return self.candidate.disposition

    @property
    def selection_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class ExclusionEligibilityAuthoringResult:
    """Immutable #29 write result with explicit non-selection evidence."""

    write_result: EvidenceEligibilityRevisionWriteResult
    selected_revision_before_write: int | None
    selected_revision_after_write: int | None

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.decision.eligibility_revision

    @property
    def written_disposition(self) -> str:
        return self.write_result.stored.decision.disposition

    @property
    def selection_changed_during_write(self) -> bool:
        return (
            self.selected_revision_before_write
            != self.selected_revision_after_write
        )

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_exclusion_eligibility_authoring(
    workspace_root: str | Path,
    projection: ExclusionsProjection,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    disposition: ExclusionAcademicDisposition,
    actor_id: str,
    policy_id: str,
    policy_version: str,
    reason_codes: tuple[str, ...] = (),
    rationale: str | None = None,
    decided_at: datetime,
) -> ExclusionEligibilityAuthoringPreview:
    """Build one exact academic #29 revision candidate without mutation."""
    _validate_request(
        projection,
        authorized_snapshot,
        item_id,
        disposition,
        reason_codes,
    )
    reviewed_row = _find_row(projection, item_id)

    fresh_projection = build_exclusions_projection(
        workspace_root,
        projection.grade_item_id,
        authorized_snapshot=authorized_snapshot,
    )
    fresh_row = _find_row(fresh_projection, item_id)
    if fresh_projection.class_id != projection.class_id:
        raise ExclusionEligibilityAuthoringStaleError(
            "Exclusions class scope changed after review."
        )
    if fresh_row != reviewed_row:
        raise ExclusionEligibilityAuthoringStaleError(
            "The exact Exclusions review row changed after review."
        )

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        fresh_row.source.work,
    )
    if membership is None or membership.decision.decision != "included":
        raise ExclusionEligibilityAuthoringStaleError(
            "Eligibility authoring requires current explicitly included "
            "Grade Item membership."
        )

    source_state = observe_evidence_source_state(
        workspace_root,
        fresh_row.source,
    )
    if source_state.state in _WITHDRAWN_SOURCE_STATES:
        raise ExclusionEligibilityAuthoringScopeError(
            "Teacher academic eligibility cannot be authored against "
            "Core-withdrawn source state."
        )

    history = list_evidence_eligibility_revisions(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        fresh_row.source,
    )
    latest_sha256: str | None = None
    if history:
        latest_sha256 = load_evidence_eligibility_revision(
            workspace_root,
            projection.class_id,
            projection.grade_item_id,
            fresh_row.source,
            history[-1],
        ).decision_sha256
    next_revision = 1 if not history else history[-1] + 1

    try:
        candidate = EvidenceEligibilityDecision(
            schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
            record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
            class_id=projection.class_id,
            grade_item_id=projection.grade_item_id,
            source=fresh_row.source,
            membership_revision=membership.decision.membership_revision,
            membership_revision_sha256=membership.decision_sha256,
            eligibility_revision=next_revision,
            supersedes_revision=(
                None if next_revision == 1 else next_revision - 1
            ),
            disposition=disposition,
            actor=EvidenceDecisionActor(kind="teacher", actor_id=actor_id),
            policy=EvidenceEligibilityPolicyReference(
                policy_id=policy_id,
                policy_version=policy_version,
            ),
            reason_codes=reason_codes,
            rationale=rationale,
            source_state=source_state,
            decided_at=decided_at,
        )
    except EvidenceEligibilityValidationError as error:
        raise ExclusionEligibilityAuthoringScopeError(str(error)) from error

    selected = get_current_evidence_eligibility_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        fresh_row.source,
    )
    return ExclusionEligibilityAuthoringPreview(
        projection=fresh_projection,
        row=fresh_row,
        candidate=candidate,
        history=history,
        latest_revision_sha256=latest_sha256,
        expected_current_eligibility_revision=selected,
        membership_revision=membership.decision.membership_revision,
        membership_revision_sha256=membership.decision_sha256,
        source_state=source_state.state,
    )


def commit_exclusion_eligibility_authoring_preview(
    workspace_root: str | Path,
    preview: ExclusionEligibilityAuthoringPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> ExclusionEligibilityAuthoringResult:
    """Revalidate exact previewed state and write without selecting current."""
    if not isinstance(preview, ExclusionEligibilityAuthoringPreview):
        raise ExclusionEligibilityAuthoringScopeError(
            "preview must be an ExclusionEligibilityAuthoringPreview."
        )

    fresh_projection = build_exclusions_projection(
        workspace_root,
        preview.projection.grade_item_id,
        authorized_snapshot=authorized_snapshot,
    )
    if fresh_projection.class_id != preview.projection.class_id:
        raise ExclusionEligibilityAuthoringStaleError(
            "Exclusions class scope changed after preview."
        )
    fresh_row = _find_row(fresh_projection, preview.item_id)
    if fresh_row != preview.row:
        raise ExclusionEligibilityAuthoringStaleError(
            "The exact Exclusions review row changed after preview."
        )

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        preview.projection.class_id,
        preview.projection.grade_item_id,
        preview.row.source.work,
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision
        != preview.membership_revision
        or membership.decision_sha256
        != preview.membership_revision_sha256
    ):
        raise ExclusionEligibilityAuthoringStaleError(
            "Grade Item membership changed after preview."
        )

    source_state = observe_evidence_source_state(
        workspace_root,
        preview.row.source,
    )
    if source_state.state in _WITHDRAWN_SOURCE_STATES:
        raise ExclusionEligibilityAuthoringStaleError(
            "Core source state became withdrawn after preview."
        )
    if source_state != preview.candidate.source_state:
        raise ExclusionEligibilityAuthoringStaleError(
            "Core source lifecycle changed after preview."
        )

    history = list_evidence_eligibility_revisions(
        workspace_root,
        preview.projection.class_id,
        preview.projection.grade_item_id,
        preview.row.source,
    )
    if history != preview.history:
        raise ExclusionEligibilityAuthoringStaleError(
            "Eligibility revision history changed after preview."
        )
    if history:
        latest = load_evidence_eligibility_revision(
            workspace_root,
            preview.projection.class_id,
            preview.projection.grade_item_id,
            preview.row.source,
            history[-1],
        )
        if latest.decision_sha256 != preview.latest_revision_sha256:
            raise ExclusionEligibilityAuthoringStaleError(
                "Latest eligibility revision content changed after preview."
            )

    selected_before = get_current_evidence_eligibility_revision(
        workspace_root,
        preview.projection.class_id,
        preview.projection.grade_item_id,
        preview.row.source,
    )
    if selected_before != preview.expected_current_eligibility_revision:
        raise ExclusionEligibilityAuthoringStaleError(
            "Current eligibility selection changed after preview."
        )

    write_result = write_evidence_eligibility_revision(
        workspace_root,
        preview.candidate,
        authorized_snapshot=authorized_snapshot,
    )
    selected_after = get_current_evidence_eligibility_revision(
        workspace_root,
        preview.projection.class_id,
        preview.projection.grade_item_id,
        preview.row.source,
    )
    return ExclusionEligibilityAuthoringResult(
        write_result=write_result,
        selected_revision_before_write=selected_before,
        selected_revision_after_write=selected_after,
    )


def _validate_request(
    projection: ExclusionsProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    disposition: ExclusionAcademicDisposition,
    reason_codes: tuple[str, ...],
) -> None:
    if not isinstance(projection, ExclusionsProjection):
        raise ExclusionEligibilityAuthoringScopeError(
            "projection must be an ExclusionsProjection."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise ExclusionEligibilityAuthoringScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if not isinstance(item_id, str) or not item_id:
        raise ExclusionEligibilityAuthoringScopeError(
            "item_id must be a nonempty string."
        )
    if disposition not in _ACADEMIC_DISPOSITIONS:
        raise ExclusionEligibilityAuthoringScopeError(
            "Teacher Exclusions authoring permits only included, excluded, "
            "pending, or unsupported academic dispositions."
        )
    if disposition == "included" and reason_codes:
        raise ExclusionEligibilityAuthoringScopeError(
            "Included eligibility must not carry reason codes."
        )
    if disposition != "included" and not reason_codes:
        raise ExclusionEligibilityAuthoringScopeError(
            "A non-included academic disposition requires at least one "
            "reason code."
        )


def _find_row(
    projection: ExclusionsProjection,
    item_id: str,
) -> ExclusionReviewRow:
    matches = tuple(row for row in projection.rows if row.item_id == item_id)
    if len(matches) != 1:
        raise ExclusionEligibilityAuthoringScopeError(
            "item_id must identify exactly one row in the reviewed projection."
        )
    return matches[0]
