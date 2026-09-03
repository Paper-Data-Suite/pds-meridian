"""CAS-safe current selection for student attempt-decision revisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection_storage import (
    AttemptSelectionDecisionSelectionResult,
    StoredAttemptSelectionDecision,
    derive_attempt_candidates,
    get_current_attempt_selection_decision_revision,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_policy,
    select_attempt_selection_decision_revision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot


class AttemptDecisionSelectionWorkflowError(RuntimeError):
    """Base error for teacher current attempt-decision selection."""

    code = "teacher_workflow.attempt_decisions.decision_selection_error"


class AttemptDecisionSelectionScopeError(
    AttemptDecisionSelectionWorkflowError, ValueError
):
    """Raised when an attempt-decision selection request is invalid."""

    code = "teacher_workflow.attempt_decisions.decision_selection_invalid"


class AttemptDecisionSelectionStaleError(
    AttemptDecisionSelectionWorkflowError
):
    """Raised when reviewed decision dependencies changed before selection."""

    code = "teacher_workflow.attempt_decisions.decision_selection_stale"


@dataclass(frozen=True, slots=True)
class AttemptDecisionSelectionPreview:
    """Exact read-only basis for selecting one persisted student decision."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    student_id: str
    target: StoredAttemptSelectionDecision
    history: tuple[int, ...]
    expected_current_decision_revision: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise AttemptDecisionSelectionScopeError(
                "work must be a ModuleWorkRef."
            )
        if self.work.class_id != self.class_id:
            raise AttemptDecisionSelectionScopeError(
                "work.class_id must match class_id."
            )
        if not isinstance(self.target, StoredAttemptSelectionDecision):
            raise AttemptDecisionSelectionScopeError(
                "target must be a StoredAttemptSelectionDecision."
            )
        decision = self.target.decision
        if (
            decision.class_id != self.class_id
            or decision.grade_item_id != self.grade_item_id
            or decision.work != self.work
            or decision.student_id != self.student_id
        ):
            raise AttemptDecisionSelectionScopeError(
                "target decision identity must match selection scope."
            )
        if tuple(sorted(self.history)) != self.history:
            raise AttemptDecisionSelectionScopeError(
                "decision history must be deterministically ordered."
            )
        if not self.history or decision.decision_revision not in self.history:
            raise AttemptDecisionSelectionScopeError(
                "target revision must exist in persisted decision history."
            )

    @property
    def target_revision(self) -> int:
        return self.target.decision.decision_revision

    @property
    def target_sha256(self) -> str:
        return self.target.decision_sha256

    @property
    def latest_revision(self) -> int:
        return self.history[-1]

    @property
    def target_is_latest(self) -> bool:
        return self.target_revision == self.latest_revision


@dataclass(frozen=True, slots=True)
class AttemptDecisionSelectionWorkflowResult:
    """Result of selecting one exact persisted student decision revision."""

    selection_result: AttemptSelectionDecisionSelectionResult
    previous_current_decision_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.stored.decision.decision_revision

    @property
    def selected_decision_sha256(self) -> str:
        return self.selection_result.stored.decision_sha256

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def _validate_live_target_dependencies(
    workspace_root: str | Path,
    preview: AttemptDecisionSelectionPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> None:
    decision = preview.target.decision

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision
        != decision.membership_revision
        or membership.decision_sha256
        != decision.membership_revision_sha256
    ):
        raise AttemptDecisionSelectionStaleError(
            "Target decision membership basis is not current and included."
        )

    policy = load_current_attempt_selection_policy(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        decision.policy.policy_id,
    )
    if (
        policy is None
        or policy.policy.policy_revision != decision.policy.policy_revision
        or policy.policy_sha256 != decision.policy.policy_revision_sha256
    ):
        raise AttemptDecisionSelectionStaleError(
            "Target decision policy basis is not the current selected policy."
        )

    derivation = derive_attempt_candidates(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.student_id,
        authorized_snapshot,
    )
    if derivation.status != "applicable":
        raise AttemptDecisionSelectionStaleError(
            "Target decision cannot be selected because current attempt "
            f"derivation status is {derivation.status!r}."
        )
    if (
        derivation.source_snapshot != decision.source_snapshot
        or derivation.candidates != decision.candidates
    ):
        raise AttemptDecisionSelectionStaleError(
            "Target decision candidate or eligibility basis is not current."
        )


def preview_attempt_decision_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptDecisionSelectionPreview:
    """Preview exact historical/current decision selection without mutation."""
    if isinstance(decision_revision, bool) or decision_revision <= 0:
        raise AttemptDecisionSelectionScopeError(
            "decision_revision must be a positive integer."
        )

    history = list_attempt_selection_decision_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
    )
    if not history:
        raise AttemptDecisionSelectionScopeError(
            "No attempt-decision revision history exists."
        )
    if decision_revision not in history:
        raise AttemptDecisionSelectionScopeError(
            "Requested decision revision is not present in persisted history."
        )

    target = load_attempt_selection_decision_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
        decision_revision,
    )
    current = get_current_attempt_selection_decision_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
    )
    preview = AttemptDecisionSelectionPreview(
        class_id=class_id,
        grade_item_id=grade_item_id,
        work=work,
        student_id=student_id,
        target=target,
        history=history,
        expected_current_decision_revision=current,
    )
    _validate_live_target_dependencies(
        workspace_root,
        preview,
        authorized_snapshot=authorized_snapshot,
    )
    return preview


def commit_attempt_decision_selection_preview(
    workspace_root: str | Path,
    preview: AttemptDecisionSelectionPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptDecisionSelectionWorkflowResult:
    """Revalidate reviewed state and CAS-select one exact decision revision."""
    if not isinstance(preview, AttemptDecisionSelectionPreview):
        raise AttemptDecisionSelectionScopeError(
            "preview must be an AttemptDecisionSelectionPreview."
        )

    history = list_attempt_selection_decision_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.student_id,
    )
    if history != preview.history:
        raise AttemptDecisionSelectionStaleError(
            "Attempt-decision revision history changed after preview."
        )

    target = load_attempt_selection_decision_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.student_id,
        preview.target_revision,
    )
    if (
        target.decision_sha256 != preview.target.decision_sha256
        or target.content != preview.target.content
        or target.decision != preview.target.decision
    ):
        raise AttemptDecisionSelectionStaleError(
            "Target attempt-decision revision changed after preview."
        )

    current = get_current_attempt_selection_decision_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.student_id,
    )
    if current != preview.expected_current_decision_revision:
        raise AttemptDecisionSelectionStaleError(
            "Current attempt-decision selector changed after preview."
        )

    _validate_live_target_dependencies(
        workspace_root,
        preview,
        authorized_snapshot=authorized_snapshot,
    )

    selection = select_attempt_selection_decision_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.student_id,
        preview.target_revision,
        authorized_snapshot=authorized_snapshot,
        expected_current_decision_revision=(
            preview.expected_current_decision_revision
        ),
    )
    return AttemptDecisionSelectionWorkflowResult(
        selection_result=selection,
        previous_current_decision_revision=(
            preview.expected_current_decision_revision
        ),
    )
