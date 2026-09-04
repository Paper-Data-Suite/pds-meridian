"""CAS-safe Grade Item membership current-selection workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_storage import (
    GradeItemMembershipSelectionResult,
    StoredGradeItemMembershipDecision,
    get_current_grade_item_membership_revision,
    list_grade_item_membership_revisions,
    load_grade_item_membership_revision,
    select_grade_item_membership_revision,
)


class GradeItemMembershipSelectionWorkflowError(RuntimeError):
    """Base error for teacher Grade Item membership selection."""

    code = "teacher_workflow.grade_items.membership_selection_error"


class GradeItemMembershipSelectionScopeError(
    GradeItemMembershipSelectionWorkflowError, ValueError
):
    """Raised when a requested membership selection target is invalid."""

    code = "teacher_workflow.grade_items.membership_selection_invalid"


class GradeItemMembershipSelectionStaleError(
    GradeItemMembershipSelectionWorkflowError
):
    """Raised when reviewed membership selection state has changed."""

    code = "teacher_workflow.grade_items.membership_selection_stale"


@dataclass(frozen=True, slots=True)
class GradeItemMembershipSelectionPreview:
    """Exact read-only basis for one membership current-selector change."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    target: StoredGradeItemMembershipDecision
    history: tuple[int, ...]
    expected_current_membership_revision: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise GradeItemMembershipSelectionScopeError(
                "work must be a ModuleWorkRef."
            )
        if self.work.class_id != self.class_id:
            raise GradeItemMembershipSelectionScopeError(
                "work.class_id must match selection class_id."
            )
        decision = self.target.decision
        if decision.class_id != self.class_id:
            raise GradeItemMembershipSelectionScopeError(
                "target membership class_id must match selection class_id."
            )
        if decision.grade_item_id != self.grade_item_id:
            raise GradeItemMembershipSelectionScopeError(
                "target membership Grade Item must match selection grade_item_id."
            )
        if decision.work_reference.work != self.work:
            raise GradeItemMembershipSelectionScopeError(
                "target membership work must match selection work."
            )
        if not self.history:
            raise GradeItemMembershipSelectionScopeError(
                "membership selection requires persisted revision history."
            )
        if tuple(sorted(self.history)) != self.history:
            raise GradeItemMembershipSelectionScopeError(
                "membership history must be deterministically ordered."
            )
        expected = tuple(range(1, self.history[-1] + 1))
        if self.history != expected:
            raise GradeItemMembershipSelectionScopeError(
                "membership history must be contiguous from revision 1."
            )
        if decision.membership_revision not in self.history:
            raise GradeItemMembershipSelectionScopeError(
                "target membership revision must exist in reviewed history."
            )
        current = self.expected_current_membership_revision
        if current is not None and current not in self.history:
            raise GradeItemMembershipSelectionScopeError(
                "expected current membership revision must exist in reviewed history."
            )

    @property
    def target_revision(self) -> int:
        return self.target.decision.membership_revision

    @property
    def target_decision(self) -> str:
        return self.target.decision.decision

    @property
    def target_grade_item_revision(self) -> int:
        return self.target.decision.grade_item_revision

    @property
    def target_registration_revision(self) -> int:
        return self.target.decision.work_reference.registration_revision

    @property
    def latest_revision(self) -> int:
        return self.history[-1]

    @property
    def target_is_latest(self) -> bool:
        return self.target_revision == self.latest_revision


@dataclass(frozen=True, slots=True)
class GradeItemMembershipSelectionWorkflowResult:
    """Result of one explicit membership current-selection change."""

    selection_result: GradeItemMembershipSelectionResult
    previous_current_membership_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.selection.membership_revision

    @property
    def selected_decision(self) -> str:
        return self.selection_result.stored.decision.decision

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def preview_grade_item_membership_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
) -> GradeItemMembershipSelectionPreview:
    """Build an exact read-only preview for one persisted membership revision."""
    if isinstance(membership_revision, bool) or not isinstance(
        membership_revision, int
    ):
        raise GradeItemMembershipSelectionScopeError(
            "membership_revision must be a positive integer."
        )
    if membership_revision <= 0:
        raise GradeItemMembershipSelectionScopeError(
            "membership_revision must be a positive integer."
        )

    history = list_grade_item_membership_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    if not history:
        raise GradeItemMembershipSelectionScopeError(
            "Membership relationship has no persisted revision history."
        )
    if membership_revision not in history:
        raise GradeItemMembershipSelectionScopeError(
            "Requested membership revision is not present in persisted history."
        )

    target = load_grade_item_membership_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        membership_revision,
    )
    current = get_current_grade_item_membership_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    return GradeItemMembershipSelectionPreview(
        class_id=class_id,
        grade_item_id=grade_item_id,
        work=work,
        target=target,
        history=history,
        expected_current_membership_revision=current,
    )


def commit_grade_item_membership_selection_preview(
    workspace_root: str | Path,
    preview: GradeItemMembershipSelectionPreview,
) -> GradeItemMembershipSelectionWorkflowResult:
    """Revalidate and select the exact previewed membership revision."""
    if not isinstance(preview, GradeItemMembershipSelectionPreview):
        raise GradeItemMembershipSelectionScopeError(
            "preview must be a GradeItemMembershipSelectionPreview."
        )

    history = list_grade_item_membership_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if history != preview.history:
        raise GradeItemMembershipSelectionStaleError(
            "Membership revision history changed after selection preview."
        )

    target = load_grade_item_membership_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.target_revision,
    )
    if target.decision != preview.target.decision:
        raise GradeItemMembershipSelectionStaleError(
            "Target membership decision changed after selection preview."
        )
    if target.decision_sha256 != preview.target.decision_sha256:
        raise GradeItemMembershipSelectionStaleError(
            "Target membership decision digest changed after selection preview."
        )

    current = get_current_grade_item_membership_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if current != preview.expected_current_membership_revision:
        raise GradeItemMembershipSelectionStaleError(
            "Current membership selection changed after selection preview."
        )

    selected = select_grade_item_membership_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.target_revision,
        expected_current_membership_revision=(
            preview.expected_current_membership_revision
        ),
    )
    return GradeItemMembershipSelectionWorkflowResult(
        selection_result=selected,
        previous_current_membership_revision=(
            preview.expected_current_membership_revision
        ),
    )
