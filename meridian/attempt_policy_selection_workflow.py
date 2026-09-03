"""CAS-safe current selection for attempt-selection policy revisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection_storage import (
    AttemptSelectionPolicySelectionResult,
    StoredAttemptSelectionPolicy,
    get_current_attempt_selection_policy_revision,
    list_attempt_selection_policy_revisions,
    load_attempt_selection_policy_revision,
    select_attempt_selection_policy_revision,
)


class AttemptPolicySelectionWorkflowError(RuntimeError):
    """Base error for teacher attempt-policy current selection."""

    code = "teacher_workflow.attempt_decisions.policy_selection_error"


class AttemptPolicySelectionScopeError(
    AttemptPolicySelectionWorkflowError, ValueError
):
    """Raised when an attempt-policy selection request is invalid."""

    code = "teacher_workflow.attempt_decisions.policy_selection_invalid"


class AttemptPolicySelectionStaleError(AttemptPolicySelectionWorkflowError):
    """Raised when reviewed policy state changed before selection."""

    code = "teacher_workflow.attempt_decisions.policy_selection_stale"


@dataclass(frozen=True, slots=True)
class AttemptPolicySelectionPreview:
    """Exact read-only basis for selecting one persisted policy revision."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    policy_id: str
    target: StoredAttemptSelectionPolicy
    history: tuple[int, ...]
    expected_current_policy_revision: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise AttemptPolicySelectionScopeError(
                "work must be a ModuleWorkRef."
            )
        if self.work.class_id != self.class_id:
            raise AttemptPolicySelectionScopeError(
                "work.class_id must match class_id."
            )
        if not isinstance(self.target, StoredAttemptSelectionPolicy):
            raise AttemptPolicySelectionScopeError(
                "target must be a StoredAttemptSelectionPolicy."
            )
        policy = self.target.policy
        if (
            policy.class_id != self.class_id
            or policy.grade_item_id != self.grade_item_id
            or policy.work != self.work
            or policy.policy_id != self.policy_id
        ):
            raise AttemptPolicySelectionScopeError(
                "target policy identity must match selection scope."
            )
        if tuple(sorted(self.history)) != self.history:
            raise AttemptPolicySelectionScopeError(
                "policy history must be deterministically ordered."
            )
        if not self.history or policy.policy_revision not in self.history:
            raise AttemptPolicySelectionScopeError(
                "target revision must exist in persisted policy history."
            )

    @property
    def target_revision(self) -> int:
        return self.target.policy.policy_revision

    @property
    def target_sha256(self) -> str:
        return self.target.policy_sha256

    @property
    def latest_revision(self) -> int:
        return self.history[-1]

    @property
    def target_is_latest(self) -> bool:
        return self.target_revision == self.latest_revision


@dataclass(frozen=True, slots=True)
class AttemptPolicySelectionWorkflowResult:
    """Result of selecting one exact persisted policy revision."""

    selection_result: AttemptSelectionPolicySelectionResult
    previous_current_policy_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.stored.policy.policy_revision

    @property
    def selected_policy_sha256(self) -> str:
        return self.selection_result.stored.policy_sha256

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def preview_attempt_policy_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> AttemptPolicySelectionPreview:
    """Preview exact historical/current policy selection without mutating state."""
    if isinstance(policy_revision, bool) or policy_revision <= 0:
        raise AttemptPolicySelectionScopeError(
            "policy_revision must be a positive integer."
        )

    history = list_attempt_selection_policy_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
    )
    if not history:
        raise AttemptPolicySelectionScopeError(
            "No attempt-selection policy revision history exists."
        )
    if policy_revision not in history:
        raise AttemptPolicySelectionScopeError(
            "Requested policy revision is not present in persisted history."
        )

    target = load_attempt_selection_policy_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
        policy_revision,
    )
    current = get_current_attempt_selection_policy_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
    )
    return AttemptPolicySelectionPreview(
        class_id=class_id,
        grade_item_id=grade_item_id,
        work=work,
        policy_id=policy_id,
        target=target,
        history=history,
        expected_current_policy_revision=current,
    )


def commit_attempt_policy_selection_preview(
    workspace_root: str | Path,
    preview: AttemptPolicySelectionPreview,
) -> AttemptPolicySelectionWorkflowResult:
    """Revalidate exact policy history/target/current pointer and CAS-select it."""
    if not isinstance(preview, AttemptPolicySelectionPreview):
        raise AttemptPolicySelectionScopeError(
            "preview must be an AttemptPolicySelectionPreview."
        )

    history = list_attempt_selection_policy_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.policy_id,
    )
    if history != preview.history:
        raise AttemptPolicySelectionStaleError(
            "Attempt-policy revision history changed after preview."
        )

    target = load_attempt_selection_policy_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.policy_id,
        preview.target_revision,
    )
    if (
        target.policy_sha256 != preview.target.policy_sha256
        or target.content != preview.target.content
        or target.policy != preview.target.policy
    ):
        raise AttemptPolicySelectionStaleError(
            "Target attempt-policy revision changed after preview."
        )

    current = get_current_attempt_selection_policy_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.policy_id,
    )
    if current != preview.expected_current_policy_revision:
        raise AttemptPolicySelectionStaleError(
            "Current attempt-policy selector changed after preview."
        )

    selection = select_attempt_selection_policy_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.policy_id,
        preview.target_revision,
        expected_current_policy_revision=(
            preview.expected_current_policy_revision
        ),
    )
    return AttemptPolicySelectionWorkflowResult(
        selection_result=selection,
        previous_current_policy_revision=preview.expected_current_policy_revision,
    )
