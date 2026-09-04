"""CAS-safe Grade Item current-revision selection workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grade_item_storage import (
    GradeItemSelectionResult,
    StoredGradeItemRevision,
    get_current_grade_item_revision,
    list_grade_item_revisions,
    load_grade_item_revision,
    select_grade_item_revision,
)


class GradeItemSelectionWorkflowError(RuntimeError):
    """Base error for teacher Grade Item selection workflows."""

    code = "teacher_workflow.grade_items.selection_error"


class GradeItemSelectionScopeError(GradeItemSelectionWorkflowError, ValueError):
    """Raised when a requested selection target is invalid."""

    code = "teacher_workflow.grade_items.selection_invalid"


class GradeItemSelectionStaleError(GradeItemSelectionWorkflowError):
    """Raised when reviewed Grade Item selection state has changed."""

    code = "teacher_workflow.grade_items.selection_stale"


@dataclass(frozen=True, slots=True)
class GradeItemSelectionPreview:
    """Exact read-only basis for one Grade Item current-selection change."""

    class_id: str
    grade_item_id: str
    target: StoredGradeItemRevision
    history: tuple[int, ...]
    expected_current_revision: int | None

    def __post_init__(self) -> None:
        revision = self.target.revision
        if revision.class_id != self.class_id:
            raise GradeItemSelectionScopeError(
                "Target Grade Item class_id must match selection class_id."
            )
        if revision.grade_item_id != self.grade_item_id:
            raise GradeItemSelectionScopeError(
                "Target Grade Item identity must match selection grade_item_id."
            )
        if not self.history:
            raise GradeItemSelectionScopeError(
                "Selection preview requires persisted Grade Item history."
            )
        if tuple(sorted(self.history)) != self.history:
            raise GradeItemSelectionScopeError(
                "Selection preview history must be deterministically ordered."
            )
        expected = tuple(range(1, self.history[-1] + 1))
        if self.history != expected:
            raise GradeItemSelectionScopeError(
                "Selection preview history must be contiguous from revision 1."
            )
        if revision.grade_item_revision not in self.history:
            raise GradeItemSelectionScopeError(
                "Selection target must exist in the reviewed Grade Item history."
            )
        current = self.expected_current_revision
        if current is not None and current not in self.history:
            raise GradeItemSelectionScopeError(
                "Expected current revision must exist in reviewed Grade Item history."
            )

    @property
    def target_revision(self) -> int:
        return self.target.revision.grade_item_revision

    @property
    def target_status(self) -> str:
        return self.target.revision.status

    @property
    def latest_revision(self) -> int:
        return self.history[-1]

    @property
    def target_is_latest(self) -> bool:
        return self.target_revision == self.latest_revision


@dataclass(frozen=True, slots=True)
class GradeItemSelectionWorkflowResult:
    """Result of one explicit current Grade Item revision selection."""

    selection_result: GradeItemSelectionResult
    previous_current_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.selection.grade_item_revision

    @property
    def selected_status(self) -> str:
        return self.selection_result.stored.revision.status

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition


def preview_grade_item_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
) -> GradeItemSelectionPreview:
    """Build an exact read-only selection preview for one persisted revision."""
    if isinstance(grade_item_revision, bool) or not isinstance(
        grade_item_revision, int
    ):
        raise GradeItemSelectionScopeError(
            "grade_item_revision must be a positive integer."
        )
    if grade_item_revision <= 0:
        raise GradeItemSelectionScopeError(
            "grade_item_revision must be a positive integer."
        )

    history = list_grade_item_revisions(
        workspace_root,
        class_id,
        grade_item_id,
    )
    if not history:
        raise GradeItemSelectionScopeError(
            "Grade Item has no persisted immutable revision history."
        )
    if grade_item_revision not in history:
        raise GradeItemSelectionScopeError(
            "Requested Grade Item revision is not present in persisted history."
        )

    target = load_grade_item_revision(
        workspace_root,
        class_id,
        grade_item_id,
        grade_item_revision,
    )
    current = get_current_grade_item_revision(
        workspace_root,
        class_id,
        grade_item_id,
    )
    return GradeItemSelectionPreview(
        class_id=class_id,
        grade_item_id=grade_item_id,
        target=target,
        history=history,
        expected_current_revision=current,
    )


def commit_grade_item_selection_preview(
    workspace_root: str | Path,
    preview: GradeItemSelectionPreview,
) -> GradeItemSelectionWorkflowResult:
    """Revalidate and explicitly select the exact previewed Grade Item revision."""
    if not isinstance(preview, GradeItemSelectionPreview):
        raise GradeItemSelectionScopeError(
            "preview must be a GradeItemSelectionPreview."
        )

    history = list_grade_item_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
    )
    if history != preview.history:
        raise GradeItemSelectionStaleError(
            "Grade Item revision history changed after selection preview."
        )

    target = load_grade_item_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.target_revision,
    )
    if target.revision != preview.target.revision:
        raise GradeItemSelectionStaleError(
            "Target Grade Item revision changed after selection preview."
        )
    if target.revision_sha256 != preview.target.revision_sha256:
        raise GradeItemSelectionStaleError(
            "Target Grade Item revision digest changed after selection preview."
        )

    current = get_current_grade_item_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
    )
    if current != preview.expected_current_revision:
        raise GradeItemSelectionStaleError(
            "Current Grade Item selection changed after selection preview."
        )

    selected = select_grade_item_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.target_revision,
        expected_current_revision=preview.expected_current_revision,
    )
    return GradeItemSelectionWorkflowResult(
        selection_result=selected,
        previous_current_revision=preview.expected_current_revision,
    )
