"""Workspace workflow for deliberate #39 grouping-signal preview reviews."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewReference
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewApplicability,
    GroupingSignalReviewDecisionValue,
    GroupingSignalReviewValidationError,
    assess_grouping_signal_review_applicability,
    create_grouping_signal_review_decision,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    GroupingSignalReviewWriteResult,
    load_current_grouping_signal_review,
    write_grouping_signal_review_revision,
)


class GroupingSignalReviewWorkflowError(RuntimeError):
    """Base error for teacher-facing grouping-signal review workflow."""


class GroupingSignalReviewWorkflowReadError(GroupingSignalReviewWorkflowError):
    """Raised when exact preview/current review state cannot be read."""


class GroupingSignalReviewWorkflowValidationError(
    GroupingSignalReviewWorkflowError,
    ValueError,
):
    """Raised when a requested review decision is invalid."""


def record_grouping_signal_review(
    workspace_root: str | Path,
    preview_reference: GroupingSignalPreviewReference,
    *,
    review_revision: int,
    supersedes_revision: int | None,
    decision: GroupingSignalReviewDecisionValue,
    acknowledged_warning_ids: tuple[str, ...],
    actor_id: str,
    reviewed_at: datetime,
) -> GroupingSignalReviewWriteResult:
    """Create/persist one review revision without selecting it."""

    if not isinstance(preview_reference, GroupingSignalPreviewReference):
        raise GroupingSignalReviewWorkflowValidationError(
            "preview_reference must be an exact #39 preview reference."
        )
    preview_reference.__post_init__()
    try:
        stored_preview = load_grouping_signal_preview_reference(
            workspace_root,
            preview_reference,
        )
    except GroupingSignalPreviewStorageError as error:
        raise GroupingSignalReviewWorkflowReadError(
            "Could not load the exact preview being reviewed."
        ) from error

    if decision == "accepted_for_export":
        try:
            live_currentness = assess_grouping_signal_derivation_currentness(
                workspace_root,
                stored_preview.snapshot.derivation_reference,
            )
        except GroupingSignalCurrentnessError as error:
            raise GroupingSignalReviewWorkflowReadError(
                "Could not re-assess derivation currentness at review time."
            ) from error
        if (
            live_currentness.state != "current"
            or live_currentness.current_derivation_reference
            != stored_preview.snapshot.derivation_reference
        ):
            raise GroupingSignalReviewWorkflowValidationError(
                "accepted_for_export requires the exact derivation to be "
                "current at review time."
            )

    try:
        review = create_grouping_signal_review_decision(
            stored_preview.snapshot,
            preview_reference,
            review_revision=review_revision,
            supersedes_revision=supersedes_revision,
            decision=decision,
            acknowledged_warning_ids=acknowledged_warning_ids,
            actor_id=actor_id,
            reviewed_at=reviewed_at,
        )
        return write_grouping_signal_review_revision(
            workspace_root,
            review,
        )
    except GroupingSignalReviewValidationError as error:
        raise GroupingSignalReviewWorkflowValidationError(str(error)) from error
    except GroupingSignalReviewStorageError as error:
        raise GroupingSignalReviewWorkflowReadError(
            "Could not persist the immutable review revision."
        ) from error


def assess_selected_grouping_signal_review_applicability(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> GroupingSignalReviewApplicability | None:
    """Assess the explicitly selected review against current #38 state."""

    try:
        selected = load_current_grouping_signal_review(
            workspace_root,
            class_id,
            derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise GroupingSignalReviewWorkflowReadError(
            "Could not load the explicitly selected review."
        ) from error
    if selected is None:
        return None

    try:
        currentness = assess_grouping_signal_derivation_currentness(
            workspace_root,
            selected.review.derivation_reference,
        )
    except GroupingSignalCurrentnessError as error:
        raise GroupingSignalReviewWorkflowReadError(
            "Could not assess selected review currentness."
        ) from error

    try:
        return assess_grouping_signal_review_applicability(
            selected.review,
            currentness,
        )
    except GroupingSignalReviewValidationError as error:
        raise GroupingSignalReviewWorkflowValidationError(str(error)) from error
