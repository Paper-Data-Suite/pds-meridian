"""Explicit current selection for Standards Review association revisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.attempt_selection import AttemptObservationReference
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_evidence_storage import (
    StandardEvidenceAssociationSelectionResult,
    StandardsEvidenceStorageConflictError,
    StoredStandardEvidenceAssociationDecision,
    get_current_standard_evidence_association_revision,
    list_standard_evidence_association_revisions,
    load_standard_evidence_association_revision,
    select_standard_evidence_association_revision,
)
from meridian.standards_review_workflow import (
    StandardsReviewProjection,
    build_standards_review_projection,
)


class StandardsAssociationSelectionError(RuntimeError):
    """Base workflow failure for explicit standards-association selection."""

    code = "teacher_workflow.standards_review.association_selection_error"


class StandardsAssociationSelectionScopeError(
    StandardsAssociationSelectionError, ValueError
):
    """Raised when an exact association selection target is invalid."""

    code = "teacher_workflow.standards_review.association_selection_invalid"


class StandardsAssociationSelectionStaleError(
    StandardsAssociationSelectionError
):
    """Raised when reviewed state changes before current selection."""

    code = "teacher_workflow.standards_review.association_selection_stale"


@dataclass(frozen=True, slots=True)
class StandardsAssociationSelectionPreview:
    """Exact persisted #33 target plus reviewed selection CAS basis."""

    projection: StandardsReviewProjection
    target: StoredStandardEvidenceAssociationDecision
    history: tuple[int, ...]
    expected_current_association_revision: int | None
    attempt: AttemptObservationReference | None

    @property
    def target_revision(self) -> int:
        return self.target.decision.association_revision

    @property
    def target_disposition(self) -> str:
        return self.target.decision.disposition

    @property
    def target_basis(self) -> str:
        return self.target.decision.basis

    @property
    def target_sha256(self) -> str:
        return self.target.decision_sha256

    @property
    def authoring_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class StandardsAssociationSelectionWorkflowResult:
    """Canonical #33 current-pointer mutation with no association authoring."""

    selection_result: StandardEvidenceAssociationSelectionResult
    previous_current_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.selection.association_revision

    @property
    def selected_disposition(self) -> str:
        return self.selection_result.stored.decision.disposition

    @property
    def selected_basis(self) -> str:
        return self.selection_result.stored.decision.basis

    @property
    def selected_decision_sha256(self) -> str:
        return self.selection_result.stored.decision_sha256

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def preview_standards_association_selection(
    workspace_root: str | Path,
    projection: StandardsReviewProjection,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    association_revision: int,
    attempt: AttemptObservationReference | None = None,
) -> StandardsAssociationSelectionPreview:
    """Preview one exact persisted #33 association revision without mutation."""
    _validate_request(
        projection,
        authorized_snapshot,
        association_revision,
        attempt,
    )
    fresh = _rebuild_review(
        workspace_root,
        projection,
        authorized_snapshot,
        attempt,
    )
    if fresh != projection:
        raise StandardsAssociationSelectionStaleError(
            "The exact Standards Review projection changed after review."
        )

    history = list_standard_evidence_association_revisions(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        projection.source,
        projection.standard_id,
    )
    if association_revision not in history:
        raise StandardsAssociationSelectionScopeError(
            "association_revision must identify one exact persisted revision."
        )
    target = load_standard_evidence_association_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        projection.source,
        projection.standard_id,
        association_revision,
    )
    decision = target.decision
    if (
        decision.class_id != projection.class_id
        or decision.grade_item_id != projection.grade_item_id
        or decision.source != projection.source
        or decision.standard_id != projection.standard_id
    ):
        raise StandardsAssociationSelectionScopeError(
            "The requested association revision does not belong to the "
            "reviewed evidence/Standard family."
        )

    selected = get_current_standard_evidence_association_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        projection.source,
        projection.standard_id,
    )
    return StandardsAssociationSelectionPreview(
        projection=projection,
        target=target,
        history=history,
        expected_current_association_revision=selected,
        attempt=attempt,
    )


def commit_standards_association_selection_preview(
    workspace_root: str | Path,
    preview: StandardsAssociationSelectionPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> StandardsAssociationSelectionWorkflowResult:
    """Revalidate exact reviewed state and CAS-select the persisted target."""
    if not isinstance(preview, StandardsAssociationSelectionPreview):
        raise StandardsAssociationSelectionScopeError(
            "preview must be a StandardsAssociationSelectionPreview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise StandardsAssociationSelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    _validate_authorized_source(preview.projection, authorized_snapshot)

    fresh = _rebuild_review(
        workspace_root,
        preview.projection,
        authorized_snapshot,
        preview.attempt,
    )
    if fresh != preview.projection:
        raise StandardsAssociationSelectionStaleError(
            "The exact Standards Review projection changed after selection preview."
        )

    history = list_standard_evidence_association_revisions(
        workspace_root,
        preview.projection.class_id,
        preview.projection.grade_item_id,
        preview.projection.source,
        preview.projection.standard_id,
    )
    if history != preview.history:
        raise StandardsAssociationSelectionStaleError(
            "Association revision history changed after selection preview."
        )

    decision = preview.target.decision
    reloaded = load_standard_evidence_association_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.standard_id,
        decision.association_revision,
    )
    if (
        reloaded.decision_sha256 != preview.target.decision_sha256
        or reloaded.content != preview.target.content
        or reloaded.decision != preview.target.decision
    ):
        raise StandardsAssociationSelectionStaleError(
            "Target association revision changed after selection preview."
        )

    selected_now = get_current_standard_evidence_association_revision(
        workspace_root,
        decision.class_id,
        decision.grade_item_id,
        decision.source,
        decision.standard_id,
    )
    if selected_now != preview.expected_current_association_revision:
        raise StandardsAssociationSelectionStaleError(
            "Current association selection changed after selection preview."
        )

    try:
        result = select_standard_evidence_association_revision(
            workspace_root,
            decision.class_id,
            decision.grade_item_id,
            decision.source,
            decision.standard_id,
            decision.association_revision,
            expected_current_association_revision=(
                preview.expected_current_association_revision
            ),
        )
    except StandardsEvidenceStorageConflictError as error:
        raise StandardsAssociationSelectionStaleError(str(error)) from error

    return StandardsAssociationSelectionWorkflowResult(
        selection_result=result,
        previous_current_revision=preview.expected_current_association_revision,
    )


def _validate_request(
    projection: StandardsReviewProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    association_revision: int,
    attempt: AttemptObservationReference | None,
) -> None:
    if not isinstance(projection, StandardsReviewProjection):
        raise StandardsAssociationSelectionScopeError(
            "projection must be a StandardsReviewProjection."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise StandardsAssociationSelectionScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if isinstance(association_revision, bool) or association_revision <= 0:
        raise StandardsAssociationSelectionScopeError(
            "association_revision must be a positive integer."
        )
    if attempt is not None and not isinstance(
        attempt,
        AttemptObservationReference,
    ):
        raise StandardsAssociationSelectionScopeError(
            "attempt must be an AttemptObservationReference or None."
        )
    _validate_authorized_source(projection, authorized_snapshot)


def _rebuild_review(
    workspace_root: str | Path,
    projection: StandardsReviewProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    attempt: AttemptObservationReference | None,
) -> StandardsReviewProjection:
    return build_standards_review_projection(
        workspace_root,
        projection.grade_item_id,
        projection.student_id,
        projection.standard_id,
        projection.item_id,
        projection.target_scale,
        authorized_snapshot=authorized_snapshot,
        mapping_profile=projection.mapping_profile,
        attempt=attempt,
    )


def _validate_authorized_source(
    projection: StandardsReviewProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> None:
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    source = projection.source
    if (
        publication.work != source.work
        or publication.publication_id != source.publication_id
        or stored.cache_key != source.cache_key
        or stored.snapshot_digest != source.snapshot_digest
    ):
        raise StandardsAssociationSelectionStaleError(
            "Authorized projection does not match the reviewed evidence source."
        )
