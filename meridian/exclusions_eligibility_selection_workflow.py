"""Explicit current selection for Exclusions eligibility revisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.evidence_eligibility import EvidenceSourceStateObservation
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityDependencyError,
    EvidenceEligibilitySelectionResult,
    EvidenceEligibilityStorageConflictError,
    StoredEvidenceEligibilityDecision,
    get_current_evidence_eligibility_revision,
    load_evidence_eligibility_revision,
    observe_evidence_source_state,
    select_evidence_eligibility_revision,
    validate_evidence_eligibility_dependencies,
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


class ExclusionEligibilitySelectionError(RuntimeError):
    """Base workflow error for explicit Exclusions eligibility selection."""

    code = "teacher_workflow.exclusions.eligibility_selection_error"


class ExclusionEligibilitySelectionScopeError(
    ExclusionEligibilitySelectionError, ValueError
):
    """Raised when an exact selection target is outside reviewed scope."""

    code = "teacher_workflow.exclusions.eligibility_selection_invalid"


class ExclusionEligibilitySelectionStaleError(
    ExclusionEligibilitySelectionError
):
    """Raised when reviewed state changed before current selection."""

    code = "teacher_workflow.exclusions.eligibility_selection_stale"


@dataclass(frozen=True, slots=True)
class ExclusionEligibilitySelectionPreview:
    """Exact read-only basis for selecting one persisted #29 revision."""

    projection: ExclusionsProjection
    row: ExclusionReviewRow
    target: StoredEvidenceEligibilityDecision
    expected_current_revision: int | None
    membership_revision: int
    membership_revision_sha256: str
    source_state: EvidenceSourceStateObservation

    @property
    def item_id(self) -> str:
        return self.row.item_id

    @property
    def target_revision(self) -> int:
        return self.target.decision.eligibility_revision

    @property
    def target_disposition(self) -> str:
        return self.target.decision.disposition

    @property
    def target_sha256(self) -> str:
        return self.target.decision_sha256

    @property
    def authoring_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class ExclusionEligibilitySelectionWorkflowResult:
    """Canonical #29 selector mutation from explicit teacher confirmation."""

    selection_result: EvidenceEligibilitySelectionResult
    previous_current_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.selection.eligibility_revision

    @property
    def selected_disposition(self) -> str:
        return self.selection_result.stored.decision.disposition

    @property
    def selected_decision_sha256(self) -> str:
        return self.selection_result.stored.decision_sha256

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def preview_exclusion_eligibility_selection(
    workspace_root: str | Path,
    projection: ExclusionsProjection,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    eligibility_revision: int,
) -> ExclusionEligibilitySelectionPreview:
    """Preview one exact persisted eligibility revision without mutation."""
    _validate_request(
        projection,
        authorized_snapshot,
        item_id,
        eligibility_revision,
    )
    reviewed_row = _find_row(projection, item_id)

    fresh_projection = build_exclusions_projection(
        workspace_root,
        projection.grade_item_id,
        authorized_snapshot=authorized_snapshot,
    )
    fresh_row = _find_row(fresh_projection, item_id)
    if fresh_projection.class_id != projection.class_id:
        raise ExclusionEligibilitySelectionStaleError(
            "Exclusions class scope changed after review."
        )
    if fresh_row != reviewed_row:
        raise ExclusionEligibilitySelectionStaleError(
            "The exact Exclusions review row changed after review."
        )

    target = load_evidence_eligibility_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        fresh_row.source,
        eligibility_revision,
    )
    if target.decision.source != fresh_row.source:
        raise ExclusionEligibilitySelectionScopeError(
            "The requested eligibility revision does not belong to the "
            "reviewed evidence source."
        )

    try:
        dependencies = validate_evidence_eligibility_dependencies(
            workspace_root,
            target.decision,
            authorized_snapshot,
            require_current_membership=True,
            require_authored_source_state=False,
        )
    except (
        EvidenceEligibilityDependencyError,
        EvidenceEligibilityStorageConflictError,
    ) as error:
        raise ExclusionEligibilitySelectionStaleError(str(error)) from error

    selected = get_current_evidence_eligibility_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        fresh_row.source,
    )
    membership = dependencies.membership
    return ExclusionEligibilitySelectionPreview(
        projection=fresh_projection,
        row=fresh_row,
        target=target,
        expected_current_revision=selected,
        membership_revision=membership.decision.membership_revision,
        membership_revision_sha256=membership.decision_sha256,
        source_state=dependencies.current_source_state,
    )


def commit_exclusion_eligibility_selection_preview(
    workspace_root: str | Path,
    preview: ExclusionEligibilitySelectionPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> ExclusionEligibilitySelectionWorkflowResult:
    """Revalidate exact reviewed state and CAS-select the target revision."""
    if not isinstance(preview, ExclusionEligibilitySelectionPreview):
        raise ExclusionEligibilitySelectionScopeError(
            "preview must be an ExclusionEligibilitySelectionPreview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise ExclusionEligibilitySelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )

    decision = preview.target.decision
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    if (
        publication.work != decision.source.work
        or publication.publication_id != decision.source.publication_id
        or stored.cache_key != decision.source.cache_key
        or stored.snapshot_digest != decision.source.snapshot_digest
    ):
        raise ExclusionEligibilitySelectionStaleError(
            "Authorized projection no longer matches the exact selection preview."
        )

    fresh_projection = build_exclusions_projection(
        workspace_root,
        preview.projection.grade_item_id,
        authorized_snapshot=authorized_snapshot,
    )
    if fresh_projection.class_id != preview.projection.class_id:
        raise ExclusionEligibilitySelectionStaleError(
            "Exclusions class scope changed after selection preview."
        )
    fresh_row = _find_row(fresh_projection, preview.item_id)
    if fresh_row != preview.row:
        raise ExclusionEligibilitySelectionStaleError(
            "The exact Exclusions review row changed after selection preview."
        )

    reloaded = load_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.eligibility_revision,
    )
    if (
        reloaded.decision_sha256 != preview.target.decision_sha256
        or reloaded.content != preview.target.content
        or reloaded.decision != preview.target.decision
    ):
        raise ExclusionEligibilitySelectionStaleError(
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
        or membership.decision.membership_revision
        != preview.membership_revision
        or membership.decision_sha256
        != preview.membership_revision_sha256
    ):
        raise ExclusionEligibilitySelectionStaleError(
            "Grade Item membership changed after eligibility selection preview."
        )

    source_state = observe_evidence_source_state(
        workspace_root,
        decision.source,
    )
    if source_state != preview.source_state:
        raise ExclusionEligibilitySelectionStaleError(
            "Core source lifecycle changed after eligibility selection preview."
        )

    selected_now = get_current_evidence_eligibility_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
    )
    if selected_now != preview.expected_current_revision:
        raise ExclusionEligibilitySelectionStaleError(
            "Current eligibility selection changed after selection preview."
        )

    try:
        result = select_evidence_eligibility_revision(
            workspace_root,
            decision.class_id,
            decision.grade_item_id,
            decision.source,
            decision.eligibility_revision,
            authorized_snapshot=authorized_snapshot,
            expected_current_eligibility_revision=(
                preview.expected_current_revision
            ),
        )
    except (
        EvidenceEligibilityDependencyError,
        EvidenceEligibilityStorageConflictError,
    ) as error:
        raise ExclusionEligibilitySelectionStaleError(str(error)) from error

    return ExclusionEligibilitySelectionWorkflowResult(
        selection_result=result,
        previous_current_revision=preview.expected_current_revision,
    )


def _validate_request(
    projection: ExclusionsProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    item_id: str,
    eligibility_revision: int,
) -> None:
    if not isinstance(projection, ExclusionsProjection):
        raise ExclusionEligibilitySelectionScopeError(
            "projection must be an ExclusionsProjection."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise ExclusionEligibilitySelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if not isinstance(item_id, str) or not item_id:
        raise ExclusionEligibilitySelectionScopeError(
            "item_id must be a nonempty string."
        )
    if isinstance(eligibility_revision, bool) or eligibility_revision <= 0:
        raise ExclusionEligibilitySelectionScopeError(
            "eligibility_revision must be a positive integer."
        )


def _find_row(
    projection: ExclusionsProjection,
    item_id: str,
) -> ExclusionReviewRow:
    matches = tuple(row for row in projection.rows if row.item_id == item_id)
    if len(matches) != 1:
        raise ExclusionEligibilitySelectionScopeError(
            "item_id must identify exactly one row in the reviewed projection."
        )
    return matches[0]
