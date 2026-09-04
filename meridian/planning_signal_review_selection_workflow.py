"""Explicit #39 review-selection stage for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewApplicability,
    GroupingSignalReviewReference,
    GroupingSignalReviewValidationError,
    assess_grouping_signal_review_applicability,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewSelectionResult,
    GroupingSignalReviewStorageConflictError,
    GroupingSignalReviewStorageError,
    StoredGroupingSignalReview,
    get_current_grouping_signal_review_revision,
    load_grouping_signal_review_revision,
    select_grouping_signal_review_revision,
)
from meridian.planning_signal_preview_diagnostics_workflow import (
    PlanningSignalPreviewDiagnosticsError,
    PlanningSignalPreviewDiagnosticsScopeError,
    project_planning_signal_preview_diagnostics,
)


class PlanningSignalReviewSelectionError(RuntimeError):
    """Base failure for the explicit #39 review-selection stage."""

    code = "teacher_workflow.create_planning_signal.review_selection_error"


class PlanningSignalReviewSelectionScopeError(
    PlanningSignalReviewSelectionError,
    ValueError,
):
    """Raised when the exact persisted review selection target is invalid."""

    code = "teacher_workflow.create_planning_signal.review_selection_invalid"


class PlanningSignalReviewSelectionDependencyError(
    PlanningSignalReviewSelectionError
):
    """Raised when exact #39 review state cannot be read safely."""

    code = "teacher_workflow.create_planning_signal.review_selection_dependency_error"


class PlanningSignalReviewSelectionStaleError(PlanningSignalReviewSelectionError):
    """Raised when the current review selector changes after teacher preview."""

    code = "teacher_workflow.create_planning_signal.review_selection_stale"


@dataclass(frozen=True, slots=True)
class PlanningSignalReviewSelectionPreview:
    """Read-only CAS intent for one exact persisted #39 review revision."""

    projection: GroupingSignalTeacherPreviewProjection
    target: StoredGroupingSignalReview
    expected_current_review_revision: int | None
    target_applicability: GroupingSignalReviewApplicability

    def __post_init__(self) -> None:
        if not isinstance(self.projection, GroupingSignalTeacherPreviewProjection):
            raise PlanningSignalReviewSelectionScopeError(
                "projection must be one exact #39 teacher preview projection."
            )
        if not isinstance(self.target, StoredGroupingSignalReview):
            raise PlanningSignalReviewSelectionScopeError(
                "target must be one exact persisted #39 review revision."
            )
        review = self.target.review
        if review.class_id != self.projection.class_id:
            raise PlanningSignalReviewSelectionScopeError(
                "Review selection target must share the projected class scope."
            )
        if review.preview_reference != self.projection.preview_reference:
            raise PlanningSignalReviewSelectionScopeError(
                "Review selection target must bind the exact projected #39 preview."
            )
        if review.derivation_reference != self.projection.derivation_reference:
            raise PlanningSignalReviewSelectionScopeError(
                "Review selection target must bind the exact projected #38 derivation."
            )
        if not isinstance(
            self.target_applicability,
            GroupingSignalReviewApplicability,
        ):
            raise PlanningSignalReviewSelectionScopeError(
                "target_applicability must be canonical #39 review applicability."
            )

    @property
    def class_id(self) -> str:
        return self.target.review.class_id

    @property
    def derivation_id(self) -> str:
        return self.target.review.derivation_reference.derivation_id

    @property
    def target_review_revision(self) -> int:
        return self.target.review.review_revision

    @property
    def target_review_sha256(self) -> str:
        return self.target.review_sha256

    @property
    def target_decision(self) -> str:
        return self.target.review.decision

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class PlanningSignalReviewSelectionWorkflowResult:
    """One explicit review-selector mutation; no review or export write."""

    preview: PlanningSignalReviewSelectionPreview
    selection_result: GroupingSignalReviewSelectionResult

    def __post_init__(self) -> None:
        if self.selection_result.stored.reference != self.preview.target.reference:
            raise PlanningSignalReviewSelectionError(
                "Selected #39 review does not match the exact reviewed target."
            )

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def previous_current_review_revision(self) -> int | None:
        return self.preview.expected_current_review_revision

    @property
    def selected_review_revision(self) -> int:
        return self.selection_result.stored.review.review_revision

    @property
    def selected_review_sha256(self) -> str:
        return self.selection_result.stored.review_sha256

    @property
    def selected_decision(self) -> str:
        return self.selection_result.stored.review.decision

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


def preview_planning_signal_review_selection(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
    review_revision: int,
    review_sha256: str,
) -> PlanningSignalReviewSelectionPreview:
    """Resolve one exact persisted review and current selector without mutation."""
    try:
        projection = project_planning_signal_preview_diagnostics(
            workspace_root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
        )
    except PlanningSignalPreviewDiagnosticsScopeError as error:
        raise PlanningSignalReviewSelectionScopeError(str(error)) from error
    except PlanningSignalPreviewDiagnosticsError as error:
        raise PlanningSignalReviewSelectionDependencyError(str(error)) from error

    try:
        requested_reference = GroupingSignalReviewReference(
            class_id=projection.class_id,
            derivation_id=projection.derivation_reference.derivation_id,
            review_revision=review_revision,
            review_sha256=review_sha256,
        )
    except (GroupingSignalReviewValidationError, ValueError) as error:
        raise PlanningSignalReviewSelectionScopeError(str(error)) from error

    try:
        target = load_grouping_signal_review_revision(
            workspace_root,
            projection.class_id,
            projection.derivation_reference.derivation_id,
            requested_reference.review_revision,
        )
        selected_revision = get_current_grouping_signal_review_revision(
            workspace_root,
            projection.class_id,
            projection.derivation_reference.derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewSelectionDependencyError(
            "Could not load the exact persisted #39 review selection target."
        ) from error

    if target.reference != requested_reference:
        raise PlanningSignalReviewSelectionScopeError(
            "Persisted #39 review does not match the exact requested review digest."
        )
    if target.review.preview_reference != projection.preview_reference:
        raise PlanningSignalReviewSelectionScopeError(
            "Persisted #39 review is bound to a different exact preview."
        )
    if target.review.derivation_reference != projection.derivation_reference:
        raise PlanningSignalReviewSelectionScopeError(
            "Persisted #39 review is bound to a different exact derivation."
        )

    try:
        currentness = assess_grouping_signal_derivation_currentness(
            workspace_root,
            target.review.derivation_reference,
        )
        applicability = assess_grouping_signal_review_applicability(
            target.review,
            currentness,
        )
    except (
        GroupingSignalCurrentnessError,
        GroupingSignalReviewValidationError,
    ) as error:
        raise PlanningSignalReviewSelectionDependencyError(
            "Could not assess the exact target review against current #38 state."
        ) from error

    return PlanningSignalReviewSelectionPreview(
        projection=projection,
        target=target,
        expected_current_review_revision=selected_revision,
        target_applicability=applicability,
    )


def commit_planning_signal_review_selection(
    workspace_root: str | Path,
    preview: PlanningSignalReviewSelectionPreview,
) -> PlanningSignalReviewSelectionWorkflowResult:
    """Revalidate exact target and CAS-select only that persisted review."""
    if not isinstance(preview, PlanningSignalReviewSelectionPreview):
        raise PlanningSignalReviewSelectionScopeError(
            "preview must be a PlanningSignalReviewSelectionPreview."
        )

    try:
        fresh_target = load_grouping_signal_review_revision(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
            preview.target_review_revision,
        )
        current_revision = get_current_grouping_signal_review_revision(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewSelectionDependencyError(
            "Could not revalidate #39 review state before selection."
        ) from error

    if fresh_target.reference != preview.target.reference:
        raise PlanningSignalReviewSelectionStaleError(
            "Exact #39 review selection target changed after teacher preview."
        )
    if fresh_target.review != preview.target.review:
        raise PlanningSignalReviewSelectionStaleError(
            "Exact #39 review content changed after teacher preview."
        )
    if current_revision != preview.expected_current_review_revision:
        raise PlanningSignalReviewSelectionStaleError(
            "Current #39 review selection changed after teacher preview."
        )

    try:
        selection_result = select_grouping_signal_review_revision(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
            preview.target_review_revision,
            expected_current_review_revision=(
                preview.expected_current_review_revision
            ),
        )
    except GroupingSignalReviewStorageConflictError as error:
        raise PlanningSignalReviewSelectionStaleError(str(error)) from error
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewSelectionDependencyError(str(error)) from error

    return PlanningSignalReviewSelectionWorkflowResult(
        preview=preview,
        selection_result=selection_result,
    )
