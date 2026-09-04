"""Teacher-authored evidence-eligibility revision workflow for issue #41.

This module adds the first mutating New Evidence application action. It authors
one immutable academic evidence-eligibility revision from an exact reviewed row
and an already-authorized projection snapshot. It deliberately does *not*
select the written revision as current.

Teacher identity, policy identity, and decision time are explicit inputs. Core
source lifecycle remains authoritative: this workflow never authors the
``superseded`` or ``withdrawn`` dispositions and refuses academic authoring once
the exact source is no longer current.
"""

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
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityRevisionWriteResult,
    get_current_evidence_eligibility_revision,
    list_evidence_eligibility_revisions,
    observe_evidence_source_state,
    write_evidence_eligibility_revision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    project_new_evidence_review,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

TeacherEligibilityDisposition: TypeAlias = Literal[
    "included",
    "excluded",
    "pending",
    "unsupported",
]

_TEACHER_DISPOSITIONS = frozenset({"included", "excluded", "pending", "unsupported"})


class NewEvidenceEligibilityAuthoringError(RuntimeError):
    """Base application failure for teacher eligibility revision authoring."""

    code: str = "teacher_workflow.new_evidence.eligibility_authoring_error"


class NewEvidenceEligibilityAuthoringScopeError(
    NewEvidenceEligibilityAuthoringError, ValueError
):
    """Raised when the requested teacher action is invalid for the reviewed row."""

    code = "teacher_workflow.new_evidence.eligibility_authoring_invalid"


class NewEvidenceEligibilityAuthoringStaleError(NewEvidenceEligibilityAuthoringError):
    """Raised when the exact teacher-reviewed basis is no longer current."""

    code = "teacher_workflow.new_evidence.eligibility_authoring_stale"


@dataclass(frozen=True, slots=True)
class NewEvidenceEligibilityAuthoringPreview:
    """Exact read-only candidate prepared from current reviewed dependencies."""

    decision: EvidenceEligibilityDecision
    selected_revision: int | None

    @property
    def candidate_revision(self) -> int:
        return self.decision.eligibility_revision

    @property
    def candidate_disposition(self) -> str:
        return self.decision.disposition


@dataclass(frozen=True, slots=True)
class NewEvidenceEligibilityAuthoringResult:
    """One immutable write plus evidence that this action did not select it."""

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
        return self.selected_revision_before_write != self.selected_revision_after_write


def preview_new_evidence_eligibility_revision(
    workspace_root: str | Path,
    review: NewEvidenceReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    item_id: str,
    disposition: TeacherEligibilityDisposition,
    actor_id: str,
    policy_id: str,
    policy_version: str,
    reason_codes: tuple[str, ...] = (),
    rationale: str | None = None,
    decided_at: datetime,
) -> NewEvidenceEligibilityAuthoringPreview:
    """Prepare the exact next teacher revision without writing or selecting it."""

    _validate_request(review, authorized_snapshot, item_id, disposition, reason_codes)
    reviewed_row = _find_reviewed_row(review, item_id)

    fresh_review = project_new_evidence_review(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        authorized_snapshot,
    )
    fresh_row = _find_reviewed_row(fresh_review, item_id)
    _require_same_reviewed_basis(review, fresh_review, reviewed_row, fresh_row)

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        review.work,
    )
    if membership is None or membership.decision.decision != "included":
        raise NewEvidenceEligibilityAuthoringStaleError(
            "The Grade Item membership is no longer explicitly included. Review "
            "New Evidence again before authoring eligibility."
        )
    if membership.decision.membership_revision != fresh_review.membership_revision:
        raise NewEvidenceEligibilityAuthoringStaleError(
            "The selected Grade Item membership revision changed after review."
        )

    source_state = observe_evidence_source_state(workspace_root, fresh_row.source)
    if source_state.state != "current":
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Teacher academic eligibility cannot be authored after the exact Core "
            f"source became {source_state.state}; review lifecycle state instead."
        )

    history = list_evidence_eligibility_revisions(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        fresh_row.source,
    )
    next_revision = 1 if not history else history[-1] + 1
    previous_revision = None if next_revision == 1 else next_revision - 1

    try:
        decision = EvidenceEligibilityDecision(
            schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
            record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
            class_id=review.class_id,
            grade_item_id=review.grade_item_id,
            source=fresh_row.source,
            membership_revision=membership.decision.membership_revision,
            membership_revision_sha256=membership.decision_sha256,
            eligibility_revision=next_revision,
            supersedes_revision=previous_revision,
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
        raise NewEvidenceEligibilityAuthoringScopeError(str(error)) from error

    selected = get_current_evidence_eligibility_revision(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        fresh_row.source,
    )
    return NewEvidenceEligibilityAuthoringPreview(
        decision=decision,
        selected_revision=selected,
    )


def commit_new_evidence_eligibility_preview(
    workspace_root: str | Path,
    preview: NewEvidenceEligibilityAuthoringPreview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> NewEvidenceEligibilityAuthoringResult:
    """Commit one exact preview after revalidating its consequential basis."""

    if not isinstance(preview, NewEvidenceEligibilityAuthoringPreview):
        raise NewEvidenceEligibilityAuthoringScopeError(
            "preview must be a NewEvidenceEligibilityAuthoringPreview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise NewEvidenceEligibilityAuthoringScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )

    decision = preview.decision
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    if (
        publication.work != decision.source.work
        or publication.publication_id != decision.source.publication_id
        or stored.cache_key != decision.source.cache_key
        or stored.snapshot_digest != decision.source.snapshot_digest
    ):
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Authorized projection no longer matches the exact eligibility preview."
        )

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source.work,
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision != decision.membership_revision
        or membership.decision_sha256 != decision.membership_revision_sha256
    ):
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Selected Grade Item membership changed after eligibility preview."
        )

    source_state = observe_evidence_source_state(workspace_root, decision.source)
    if source_state != decision.source_state:
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Core source lifecycle changed after eligibility preview."
        )

    history = list_evidence_eligibility_revisions(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
    )
    expected_previous = decision.eligibility_revision - 1
    if decision.eligibility_revision == 1:
        history_matches = not history
    else:
        history_matches = bool(history) and history[-1] == expected_previous
    if not history_matches:
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Eligibility revision history changed after preview."
        )

    selected_now = get_current_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
    )
    if selected_now != preview.selected_revision:
        raise NewEvidenceEligibilityAuthoringStaleError(
            "Current eligibility selection changed after preview."
        )

    write_result = write_evidence_eligibility_revision(
        workspace_root,
        decision,
        authorized_snapshot=authorized_snapshot,
    )
    selected_after = get_current_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
    )
    return NewEvidenceEligibilityAuthoringResult(
        write_result=write_result,
        selected_revision_before_write=preview.selected_revision,
        selected_revision_after_write=selected_after,
    )


def author_new_evidence_eligibility_revision(
    workspace_root: str | Path,
    review: NewEvidenceReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    item_id: str,
    disposition: TeacherEligibilityDisposition,
    actor_id: str,
    policy_id: str,
    policy_version: str,
    reason_codes: tuple[str, ...] = (),
    rationale: str | None = None,
    decided_at: datetime,
) -> NewEvidenceEligibilityAuthoringResult:
    """Prepare and commit one teacher eligibility revision without selecting it."""

    preview = preview_new_evidence_eligibility_revision(
        workspace_root,
        review,
        authorized_snapshot,
        item_id=item_id,
        disposition=disposition,
        actor_id=actor_id,
        policy_id=policy_id,
        policy_version=policy_version,
        reason_codes=reason_codes,
        rationale=rationale,
        decided_at=decided_at,
    )
    return commit_new_evidence_eligibility_preview(
        workspace_root,
        preview,
        authorized_snapshot,
    )


def _validate_request(
    review: NewEvidenceReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    disposition: TeacherEligibilityDisposition,
    reason_codes: tuple[str, ...],
) -> None:
    if not isinstance(review, NewEvidenceReview):
        raise NewEvidenceEligibilityAuthoringScopeError(
            "review must be a NewEvidenceReview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise NewEvidenceEligibilityAuthoringScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if not isinstance(item_id, str) or not item_id:
        raise NewEvidenceEligibilityAuthoringScopeError(
            "item_id must be a nonempty string."
        )
    if disposition not in _TEACHER_DISPOSITIONS:
        raise NewEvidenceEligibilityAuthoringScopeError(
            "Teacher eligibility disposition must be included, excluded, pending, "
            "or unsupported. Core lifecycle dispositions are system-owned."
        )
    if review.membership_state != "included":
        raise NewEvidenceEligibilityAuthoringScopeError(
            "Eligibility authoring requires explicitly included Grade Item membership."
        )
    if disposition == "included" and reason_codes:
        raise NewEvidenceEligibilityAuthoringScopeError(
            "Included eligibility must not carry exclusion/pending reason codes."
        )
    if disposition != "included" and not reason_codes:
        raise NewEvidenceEligibilityAuthoringScopeError(
            "A non-included eligibility disposition requires at least one reason code."
        )

    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    if (
        publication.work != review.work
        or publication.publication_id != review.publication_id
        or stored.cache_key != review.cache_key
        or stored.snapshot_digest != review.snapshot_digest
    ):
        raise NewEvidenceEligibilityAuthoringScopeError(
            "Authorized projection does not match the exact reviewed provenance."
        )


def _find_reviewed_row(review: NewEvidenceReview, item_id: str) -> NewEvidenceRow:
    matches = tuple(row for row in review.rows if row.source.item_id == item_id)
    if len(matches) != 1:
        raise NewEvidenceEligibilityAuthoringScopeError(
            "item_id must identify exactly one row in the reviewed projection."
        )
    return matches[0]


def _require_same_reviewed_basis(
    reviewed: NewEvidenceReview,
    fresh: NewEvidenceReview,
    reviewed_row: NewEvidenceRow,
    fresh_row: NewEvidenceRow,
) -> None:
    if (
        fresh.work != reviewed.work
        or fresh.publication_id != reviewed.publication_id
        or fresh.cache_key != reviewed.cache_key
        or fresh.snapshot_digest != reviewed.snapshot_digest
        or fresh.membership_state != reviewed.membership_state
        or fresh.membership_revision != reviewed.membership_revision
        or fresh.academic_period_id != reviewed.academic_period_id
        or fresh.academic_period_calendar_revision
        != reviewed.academic_period_calendar_revision
    ):
        raise NewEvidenceEligibilityAuthoringStaleError(
            "The Grade Item or projection basis changed after New Evidence review."
        )

    reviewed_state = (
        reviewed_row.source,
        reviewed_row.membership_state,
        reviewed_row.eligibility_status,
        reviewed_row.selected_eligibility_revision,
        reviewed_row.selected_eligibility_disposition,
        reviewed_row.eligibility_source_state,
    )
    fresh_state = (
        fresh_row.source,
        fresh_row.membership_state,
        fresh_row.eligibility_status,
        fresh_row.selected_eligibility_revision,
        fresh_row.selected_eligibility_disposition,
        fresh_row.eligibility_source_state,
    )
    if fresh_state != reviewed_state:
        raise NewEvidenceEligibilityAuthoringStaleError(
            "The target evidence row changed after New Evidence review. "
            "Review it again before authoring eligibility."
        )
