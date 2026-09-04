"""Explicit current-selection workflow for New Evidence eligibility revisions.

This module keeps immutable evidence-eligibility revision authoring separate from
selection.  It previews one exact already-persisted #29 eligibility revision and
then, only through a separate commit call, selects that revision as current with
compare-and-swap protection.

The preview captures the reviewed evidence source, target revision digest,
current Grade Item membership, Core source lifecycle, and current eligibility
selector.  Commit revalidates those consequential dependencies so a teacher
never reviews state A and silently selects against changed state B.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.evidence_eligibility import EvidenceSourceStateObservation
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilitySelectionResult,
    StoredEvidenceEligibilityDecision,
    get_current_evidence_eligibility_revision,
    load_evidence_eligibility_revision,
    observe_evidence_source_state,
    select_evidence_eligibility_revision,
    validate_evidence_eligibility_dependencies,
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


class NewEvidenceEligibilitySelectionError(RuntimeError):
    """Base application failure for explicit eligibility selection."""

    code: str = "teacher_workflow.new_evidence.eligibility_selection_error"


class NewEvidenceEligibilitySelectionScopeError(
    NewEvidenceEligibilitySelectionError, ValueError
):
    """Raised when the requested selection is outside the reviewed scope."""

    code = "teacher_workflow.new_evidence.eligibility_selection_invalid"


class NewEvidenceEligibilitySelectionStaleError(NewEvidenceEligibilitySelectionError):
    """Raised when consequential state changed after teacher review/preview."""

    code = "teacher_workflow.new_evidence.eligibility_selection_stale"


@dataclass(frozen=True, slots=True)
class NewEvidenceEligibilitySelectionPreview:
    """Exact read-only basis for selecting one persisted eligibility revision."""

    target: StoredEvidenceEligibilityDecision
    expected_current_revision: int | None
    membership_revision: int
    membership_revision_sha256: str
    source_state: EvidenceSourceStateObservation

    @property
    def target_revision(self) -> int:
        return self.target.decision.eligibility_revision

    @property
    def target_disposition(self) -> str:
        return self.target.decision.disposition


@dataclass(frozen=True, slots=True)
class NewEvidenceEligibilitySelectionWorkflowResult:
    """Canonical #29 selector mutation resulting from one explicit confirmation."""

    selection_result: EvidenceEligibilitySelectionResult
    previous_current_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.selection.eligibility_revision

    @property
    def selected_disposition(self) -> str:
        return self.selection_result.stored.decision.disposition

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition


def preview_new_evidence_eligibility_selection(
    workspace_root: str | Path,
    review: NewEvidenceReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    item_id: str,
    eligibility_revision: int,
) -> NewEvidenceEligibilitySelectionPreview:
    """Preview one exact persisted revision without changing current selection."""

    _validate_request(review, authorized_snapshot, item_id, eligibility_revision)
    reviewed_row = _find_reviewed_row(review, item_id)

    fresh_review = project_new_evidence_review(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        authorized_snapshot,
    )
    fresh_row = _find_reviewed_row(fresh_review, item_id)
    _require_same_reviewed_basis(review, fresh_review, reviewed_row, fresh_row)

    target = load_evidence_eligibility_revision(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        fresh_row.source,
        eligibility_revision,
    )
    if target.decision.source != fresh_row.source:
        raise NewEvidenceEligibilitySelectionScopeError(
            "The requested eligibility revision does not belong to the reviewed "
            "evidence source."
        )

    dependencies = validate_evidence_eligibility_dependencies(
        workspace_root,
        target.decision,
        authorized_snapshot,
        require_current_membership=True,
        require_authored_source_state=False,
    )
    membership = dependencies.membership
    selected = get_current_evidence_eligibility_revision(
        workspace_root,
        review.class_id,
        review.grade_item_id,
        fresh_row.source,
    )
    return NewEvidenceEligibilitySelectionPreview(
        target=target,
        expected_current_revision=selected,
        membership_revision=membership.decision.membership_revision,
        membership_revision_sha256=membership.decision_sha256,
        source_state=dependencies.current_source_state,
    )


def commit_new_evidence_eligibility_selection_preview(
    workspace_root: str | Path,
    preview: NewEvidenceEligibilitySelectionPreview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> NewEvidenceEligibilitySelectionWorkflowResult:
    """Select the exact previewed revision after live dependency revalidation."""

    if not isinstance(preview, NewEvidenceEligibilitySelectionPreview):
        raise NewEvidenceEligibilitySelectionScopeError(
            "preview must be a NewEvidenceEligibilitySelectionPreview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise NewEvidenceEligibilitySelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )

    target = preview.target
    decision = target.decision
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    if (
        publication.work != decision.source.work
        or publication.publication_id != decision.source.publication_id
        or stored.cache_key != decision.source.cache_key
        or stored.snapshot_digest != decision.source.snapshot_digest
    ):
        raise NewEvidenceEligibilitySelectionStaleError(
            "Authorized projection no longer matches the exact selection preview."
        )

    reloaded = load_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.eligibility_revision,
    )
    if reloaded.decision_sha256 != target.decision_sha256:
        raise NewEvidenceEligibilitySelectionStaleError(
            "Target eligibility revision changed after selection preview."
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
        or membership.decision.membership_revision != preview.membership_revision
        or membership.decision_sha256 != preview.membership_revision_sha256
    ):
        raise NewEvidenceEligibilitySelectionStaleError(
            "Selected Grade Item membership changed after eligibility "
            "selection preview."
        )

    source_state = observe_evidence_source_state(workspace_root, decision.source)
    if source_state != preview.source_state:
        raise NewEvidenceEligibilitySelectionStaleError(
            "Core source lifecycle changed after eligibility selection preview."
        )

    selected_now = get_current_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
    )
    if selected_now != preview.expected_current_revision:
        raise NewEvidenceEligibilitySelectionStaleError(
            "Current eligibility selection changed after selection preview."
        )

    result = select_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.eligibility_revision,
        authorized_snapshot=authorized_snapshot,
        expected_current_eligibility_revision=preview.expected_current_revision,
    )
    return NewEvidenceEligibilitySelectionWorkflowResult(
        selection_result=result,
        previous_current_revision=preview.expected_current_revision,
    )


def _validate_request(
    review: NewEvidenceReview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    eligibility_revision: int,
) -> None:
    if not isinstance(review, NewEvidenceReview):
        raise NewEvidenceEligibilitySelectionScopeError(
            "review must be a NewEvidenceReview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise NewEvidenceEligibilitySelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if not isinstance(item_id, str) or not item_id:
        raise NewEvidenceEligibilitySelectionScopeError(
            "item_id must be a nonempty string."
        )
    if (
        isinstance(eligibility_revision, bool)
        or not isinstance(eligibility_revision, int)
        or eligibility_revision < 1
    ):
        raise NewEvidenceEligibilitySelectionScopeError(
            "eligibility_revision must be a positive integer."
        )
    if review.membership_state != "included":
        raise NewEvidenceEligibilitySelectionScopeError(
            "Eligibility selection requires explicitly included Grade Item membership."
        )

    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    if (
        publication.work != review.work
        or publication.publication_id != review.publication_id
        or stored.cache_key != review.cache_key
        or stored.snapshot_digest != review.snapshot_digest
    ):
        raise NewEvidenceEligibilitySelectionScopeError(
            "Authorized projection does not match the exact reviewed provenance."
        )


def _find_reviewed_row(review: NewEvidenceReview, item_id: str) -> NewEvidenceRow:
    matches = tuple(row for row in review.rows if row.source.item_id == item_id)
    if len(matches) != 1:
        raise NewEvidenceEligibilitySelectionScopeError(
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
        raise NewEvidenceEligibilitySelectionStaleError(
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
        raise NewEvidenceEligibilitySelectionStaleError(
            "The target evidence row changed after New Evidence review. Review it "
            "again before selecting eligibility."
        )
