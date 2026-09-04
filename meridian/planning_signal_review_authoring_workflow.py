"""Explicit #39 teacher review-authoring stage for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewDecision,
    GroupingSignalReviewDecisionValue,
    GroupingSignalReviewValidationError,
    create_grouping_signal_review_decision,
    validate_grouping_signal_review_transition,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    GroupingSignalReviewWriteResult,
    get_current_grouping_signal_review_revision,
    list_grouping_signal_review_revisions,
    load_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import (
    GroupingSignalReviewWorkflowError,
    GroupingSignalReviewWorkflowValidationError,
    record_grouping_signal_review,
)
from meridian.planning_signal_preview_diagnostics_workflow import (
    PlanningSignalPreviewDiagnosticsError,
    PlanningSignalPreviewDiagnosticsScopeError,
    project_planning_signal_preview_diagnostics,
)


class PlanningSignalReviewAuthoringError(RuntimeError):
    """Base failure for the explicit #39 teacher review-authoring stage."""

    code = "teacher_workflow.create_planning_signal.review_authoring_error"


class PlanningSignalReviewAuthoringScopeError(
    PlanningSignalReviewAuthoringError,
    ValueError,
):
    """Raised when requested review content or exact preview scope is invalid."""

    code = "teacher_workflow.create_planning_signal.review_authoring_invalid"


class PlanningSignalReviewAuthoringDependencyError(
    PlanningSignalReviewAuthoringError
):
    """Raised when canonical #39 review dependencies cannot be read safely."""

    code = "teacher_workflow.create_planning_signal.review_authoring_dependency_error"


class PlanningSignalReviewAuthoringStaleError(PlanningSignalReviewAuthoringError):
    """Raised when reviewed state changes before the explicit write."""

    code = "teacher_workflow.create_planning_signal.review_authoring_stale"


@dataclass(frozen=True, slots=True)
class PlanningSignalReviewAuthoringPreview:
    """Read-only exact candidate for one immutable #39 teacher review revision."""

    projection: GroupingSignalTeacherPreviewProjection
    candidate: GroupingSignalReviewDecision
    history: tuple[int, ...]
    expected_current_review_revision: int | None
    warning_diagnostic_ids: tuple[str, ...]
    blocking_diagnostic_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.projection, GroupingSignalTeacherPreviewProjection):
            raise PlanningSignalReviewAuthoringScopeError(
                "projection must be one exact #39 teacher preview projection."
            )
        if not isinstance(self.candidate, GroupingSignalReviewDecision):
            raise PlanningSignalReviewAuthoringScopeError(
                "candidate must be one exact #39 review decision."
            )
        if self.candidate.preview_reference != self.projection.preview_reference:
            raise PlanningSignalReviewAuthoringScopeError(
                "Review candidate must bind the exact projected #39 preview."
            )
        if self.candidate.derivation_reference != self.projection.derivation_reference:
            raise PlanningSignalReviewAuthoringScopeError(
                "Review candidate must bind the exact projected #38 derivation."
            )
        expected_revision = 1 if not self.history else self.history[-1] + 1
        expected_supersedes = None if not self.history else self.history[-1]
        if self.candidate.review_revision != expected_revision:
            raise PlanningSignalReviewAuthoringScopeError(
                "Review candidate revision does not follow verified review history."
            )
        if self.candidate.supersedes_revision != expected_supersedes:
            raise PlanningSignalReviewAuthoringScopeError(
                "Review candidate does not supersede the verified prior revision."
            )
        expected_warnings = tuple(
            sorted(
                item.diagnostic_id
                for item in self.projection.diagnostics
                if item.severity == "warning"
            )
        )
        expected_blockers = tuple(
            sorted(
                item.diagnostic_id
                for item in self.projection.diagnostics
                if item.severity == "blocking"
            )
        )
        if self.warning_diagnostic_ids != expected_warnings:
            raise PlanningSignalReviewAuthoringScopeError(
                "warning_diagnostic_ids do not match the exact #39 preview."
            )
        if self.blocking_diagnostic_ids != expected_blockers:
            raise PlanningSignalReviewAuthoringScopeError(
                "blocking_diagnostic_ids do not match the exact #39 preview."
            )

    @property
    def class_id(self) -> str:
        return self.candidate.class_id

    @property
    def derivation_id(self) -> str:
        return self.candidate.derivation_reference.derivation_id

    @property
    def review_revision(self) -> int:
        return self.candidate.review_revision

    @property
    def decision(self) -> GroupingSignalReviewDecisionValue:
        return self.candidate.decision

    @property
    def acknowledged_warning_ids(self) -> tuple[str, ...]:
        return self.candidate.acknowledged_warning_ids

    @property
    def actor_id(self) -> str:
        return self.candidate.actor.actor_id

    @property
    def reviewed_at(self) -> datetime:
        return self.candidate.reviewed_at

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
class PlanningSignalReviewAuthoringResult:
    """One immutable review write; explicit selection remains untouched."""

    preview: PlanningSignalReviewAuthoringPreview
    write_result: GroupingSignalReviewWriteResult
    selected_revision_before_write: int | None
    selected_revision_after_write: int | None

    def __post_init__(self) -> None:
        if self.write_result.stored.review != self.preview.candidate:
            raise PlanningSignalReviewAuthoringError(
                "Persisted #39 review does not match the exact reviewed candidate."
            )
        if (
            self.selected_revision_before_write
            != self.preview.expected_current_review_revision
        ):
            raise PlanningSignalReviewAuthoringError(
                "Review selection before write does not match reviewed context."
            )

    @property
    def write_disposition(self) -> str:
        return self.write_result.disposition

    @property
    def review_revision(self) -> int:
        return self.write_result.stored.review.review_revision

    @property
    def review_sha256(self) -> str:
        return self.write_result.stored.review_sha256

    @property
    def decision(self) -> GroupingSignalReviewDecisionValue:
        return self.write_result.stored.review.decision

    @property
    def selection_changed_during_write(self) -> bool:
        return self.selected_revision_after_write != self.selected_revision_before_write

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


def preview_planning_signal_review_authoring(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
    *,
    decision: GroupingSignalReviewDecisionValue,
    acknowledged_warning_ids: tuple[str, ...],
    actor_id: str,
    reviewed_at: datetime,
) -> PlanningSignalReviewAuthoringPreview:
    """Build one exact review candidate without writing or selecting it."""
    try:
        projection = project_planning_signal_preview_diagnostics(
            workspace_root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
        )
    except PlanningSignalPreviewDiagnosticsScopeError as error:
        raise PlanningSignalReviewAuthoringScopeError(str(error)) from error
    except PlanningSignalPreviewDiagnosticsError as error:
        raise PlanningSignalReviewAuthoringDependencyError(str(error)) from error

    if decision == "accepted_for_export":
        currentness = projection.live_currentness
        if (
            currentness.state != "current"
            or currentness.current_derivation_reference
            != projection.derivation_reference
        ):
            raise PlanningSignalReviewAuthoringScopeError(
                "accepted_for_export requires the exact #38 derivation to be "
                "current at review-preview time."
            )

    try:
        stored_preview = load_grouping_signal_preview_reference(
            workspace_root,
            projection.preview_reference,
        )
        history = list_grouping_signal_review_revisions(
            workspace_root,
            projection.class_id,
            projection.derivation_reference.derivation_id,
        )
        selected_revision = get_current_grouping_signal_review_revision(
            workspace_root,
            projection.class_id,
            projection.derivation_reference.derivation_id,
        )
    except (
        GroupingSignalPreviewStorageError,
        GroupingSignalReviewStorageError,
    ) as error:
        raise PlanningSignalReviewAuthoringDependencyError(
            "Could not verify exact #39 preview/review history for authoring."
        ) from error

    review_revision = 1 if not history else history[-1] + 1
    supersedes_revision = None if not history else history[-1]
    try:
        candidate = create_grouping_signal_review_decision(
            stored_preview.snapshot,
            projection.preview_reference,
            review_revision=review_revision,
            supersedes_revision=supersedes_revision,
            decision=decision,
            acknowledged_warning_ids=acknowledged_warning_ids,
            actor_id=actor_id,
            reviewed_at=reviewed_at,
        )
        if history:
            previous = load_grouping_signal_review_revision(
                workspace_root,
                projection.class_id,
                projection.derivation_reference.derivation_id,
                history[-1],
            ).review
            validate_grouping_signal_review_transition(previous, candidate)
    except GroupingSignalReviewValidationError as error:
        raise PlanningSignalReviewAuthoringScopeError(str(error)) from error
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewAuthoringDependencyError(
            "Could not validate the prior #39 review revision."
        ) from error

    warnings = tuple(
        sorted(
            item.diagnostic_id
            for item in projection.diagnostics
            if item.severity == "warning"
        )
    )
    blockers = tuple(
        sorted(
            item.diagnostic_id
            for item in projection.diagnostics
            if item.severity == "blocking"
        )
    )
    return PlanningSignalReviewAuthoringPreview(
        projection=projection,
        candidate=candidate,
        history=history,
        expected_current_review_revision=selected_revision,
        warning_diagnostic_ids=warnings,
        blocking_diagnostic_ids=blockers,
    )


def commit_planning_signal_review_authoring(
    workspace_root: str | Path,
    preview: PlanningSignalReviewAuthoringPreview,
) -> PlanningSignalReviewAuthoringResult:
    """Revalidate reviewed state and write only the exact immutable review."""
    if not isinstance(preview, PlanningSignalReviewAuthoringPreview):
        raise PlanningSignalReviewAuthoringScopeError(
            "preview must be a PlanningSignalReviewAuthoringPreview."
        )

    try:
        history = list_grouping_signal_review_revisions(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
        )
        selected_before = get_current_grouping_signal_review_revision(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewAuthoringDependencyError(
            "Could not revalidate #39 review history before write."
        ) from error

    if history != preview.history:
        raise PlanningSignalReviewAuthoringStaleError(
            "Review history changed after the teacher reviewed the candidate."
        )
    if selected_before != preview.expected_current_review_revision:
        raise PlanningSignalReviewAuthoringStaleError(
            "Explicit review selection changed after the teacher reviewed "
            "the candidate."
        )

    candidate = preview.candidate
    try:
        write_result = record_grouping_signal_review(
            workspace_root,
            candidate.preview_reference,
            review_revision=candidate.review_revision,
            supersedes_revision=candidate.supersedes_revision,
            decision=candidate.decision,
            acknowledged_warning_ids=candidate.acknowledged_warning_ids,
            actor_id=candidate.actor.actor_id,
            reviewed_at=candidate.reviewed_at,
        )
    except GroupingSignalReviewWorkflowValidationError as error:
        raise PlanningSignalReviewAuthoringStaleError(str(error)) from error
    except GroupingSignalReviewWorkflowError as error:
        raise PlanningSignalReviewAuthoringDependencyError(str(error)) from error

    try:
        selected_after = get_current_grouping_signal_review_revision(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise PlanningSignalReviewAuthoringDependencyError(
            "Review was written but current review selection could not be re-read."
        ) from error

    return PlanningSignalReviewAuthoringResult(
        preview=preview,
        write_result=write_result,
        selected_revision_before_write=selected_before,
        selected_revision_after_write=selected_after,
    )
