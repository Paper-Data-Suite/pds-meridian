"""Immutable authoring workflow for explicit attempt-selection policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptSelectionActor,
    AttemptSelectionPolicy,
    AttemptSelectionValidationError,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionPolicyWriteResult,
    get_current_attempt_selection_policy_revision,
    list_attempt_selection_policy_revisions,
    load_attempt_selection_policy_revision,
    write_attempt_selection_policy_revision,
)

AttemptPolicyAuthoringOperation: TypeAlias = Literal["create", "revise"]


class AttemptPolicyAuthoringWorkflowError(RuntimeError):
    """Base error for teacher attempt-policy authoring."""

    code = "teacher_workflow.attempt_decisions.policy_authoring_error"


class AttemptPolicyAuthoringScopeError(
    AttemptPolicyAuthoringWorkflowError, ValueError
):
    """Raised when an attempt-policy authoring request is invalid."""

    code = "teacher_workflow.attempt_decisions.policy_authoring_invalid"


class AttemptPolicyAuthoringStaleError(AttemptPolicyAuthoringWorkflowError):
    """Raised when reviewed policy history changed before commit."""

    code = "teacher_workflow.attempt_decisions.policy_authoring_stale"


@dataclass(frozen=True, slots=True)
class AttemptPolicyAuthoringPreview:
    """Exact read-only basis for one immutable policy revision write."""

    operation: AttemptPolicyAuthoringOperation
    candidate: AttemptSelectionPolicy
    history: tuple[int, ...]
    latest_persisted_policy_sha256: str | None
    reviewed_current_policy_revision: int | None

    def __post_init__(self) -> None:
        if self.operation not in {"create", "revise"}:
            raise AttemptPolicyAuthoringScopeError(
                "operation must be create or revise."
            )
        if not isinstance(self.candidate, AttemptSelectionPolicy):
            raise AttemptPolicyAuthoringScopeError(
                "candidate must be an AttemptSelectionPolicy."
            )
        if tuple(sorted(self.history)) != self.history:
            raise AttemptPolicyAuthoringScopeError(
                "policy history must be deterministically ordered."
            )
        if self.history:
            expected = tuple(range(1, self.history[-1] + 1))
            if self.history != expected:
                raise AttemptPolicyAuthoringScopeError(
                    "policy history must be contiguous from revision 1."
                )
        if self.operation == "create":
            if self.history:
                raise AttemptPolicyAuthoringScopeError(
                    "create requires no existing policy history."
                )
            if self.candidate.policy_revision != 1:
                raise AttemptPolicyAuthoringScopeError(
                    "create candidate must be policy revision 1."
                )
            if self.latest_persisted_policy_sha256 is not None:
                raise AttemptPolicyAuthoringScopeError(
                    "create cannot carry a previous policy digest."
                )
        else:
            if not self.history:
                raise AttemptPolicyAuthoringScopeError(
                    "revise requires existing policy history."
                )
            if self.candidate.policy_revision != self.history[-1] + 1:
                raise AttemptPolicyAuthoringScopeError(
                    "revise candidate must immediately follow persisted history."
                )
            if self.latest_persisted_policy_sha256 is None:
                raise AttemptPolicyAuthoringScopeError(
                    "revise requires the latest persisted policy digest."
                )

    @property
    def class_id(self) -> str:
        return self.candidate.class_id

    @property
    def grade_item_id(self) -> str:
        return self.candidate.grade_item_id

    @property
    def work(self) -> ModuleWorkRef:
        return self.candidate.work

    @property
    def policy_id(self) -> str:
        return self.candidate.policy_id

    @property
    def policy_revision(self) -> int:
        return self.candidate.policy_revision


@dataclass(frozen=True, slots=True)
class AttemptPolicyAuthoringResult:
    """Result of one immutable attempt-policy revision write."""

    write_result: AttemptSelectionPolicyWriteResult

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.policy.policy_revision

    @property
    def write_disposition(self) -> str:
        return self.write_result.disposition

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_attempt_policy_authoring(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    *,
    operation: AttemptPolicyAuthoringOperation,
    minimum_selected: int,
    maximum_selected: int | None,
    actor_id: str,
    revised_at: datetime,
    rationale: str | None = None,
) -> AttemptPolicyAuthoringPreview:
    """Build one exact explicit-selection policy revision without writing it."""
    if operation not in {"create", "revise"}:
        raise AttemptPolicyAuthoringScopeError(
            "operation must be create or revise."
        )

    history = list_attempt_selection_policy_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
    )
    previous = None
    if history:
        previous = load_attempt_selection_policy_revision(
            workspace_root,
            class_id,
            grade_item_id,
            work,
            policy_id,
            history[-1],
        )

    if operation == "create" and history:
        raise AttemptPolicyAuthoringScopeError(
            "Create requires no existing policy revision history."
        )
    if operation == "revise" and previous is None:
        raise AttemptPolicyAuthoringScopeError(
            "Revise requires existing policy revision history."
        )

    revision = 1 if previous is None else history[-1] + 1
    try:
        candidate = AttemptSelectionPolicy(
            schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
            record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            policy_id=policy_id,
            policy_revision=revision,
            supersedes_revision=None if previous is None else history[-1],
            selection_basis="explicit",
            minimum_selected=minimum_selected,
            maximum_selected=maximum_selected,
            actor=AttemptSelectionActor(
                kind="teacher",
                actor_id=actor_id,
            ),
            rationale=rationale,
            revised_at=revised_at,
        )
    except AttemptSelectionValidationError as error:
        raise AttemptPolicyAuthoringScopeError(str(error)) from error

    current_revision = get_current_attempt_selection_policy_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
    )
    return AttemptPolicyAuthoringPreview(
        operation=operation,
        candidate=candidate,
        history=history,
        latest_persisted_policy_sha256=(
            None if previous is None else previous.policy_sha256
        ),
        reviewed_current_policy_revision=current_revision,
    )


def commit_attempt_policy_authoring_preview(
    workspace_root: str | Path,
    preview: AttemptPolicyAuthoringPreview,
) -> AttemptPolicyAuthoringResult:
    """Revalidate exact policy history and persist only the immutable revision."""
    if not isinstance(preview, AttemptPolicyAuthoringPreview):
        raise AttemptPolicyAuthoringScopeError(
            "preview must be an AttemptPolicyAuthoringPreview."
        )

    history = list_attempt_selection_policy_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.policy_id,
    )
    if history != preview.history:
        raise AttemptPolicyAuthoringStaleError(
            "Attempt-policy revision history changed after preview."
        )

    if history:
        latest = load_attempt_selection_policy_revision(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.work,
            preview.policy_id,
            history[-1],
        )
        if latest.policy_sha256 != preview.latest_persisted_policy_sha256:
            raise AttemptPolicyAuthoringStaleError(
                "Latest attempt-policy revision digest changed after preview."
            )
    elif preview.latest_persisted_policy_sha256 is not None:
        raise AttemptPolicyAuthoringStaleError(
            "Attempt-policy history no longer matches the reviewed preview."
        )

    write_result = write_attempt_selection_policy_revision(
        workspace_root,
        preview.candidate,
    )
    return AttemptPolicyAuthoringResult(write_result=write_result)
