"""Grade Item membership immutable-authoring teacher workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_storage import (
    GradeItemMembershipRevisionWriteResult,
    get_current_grade_item_membership_revision,
    list_grade_item_membership_revisions,
    load_grade_item_membership_revision,
    validate_grade_item_membership_dependencies,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
    GradeItemMembershipDisposition,
    GradeItemMembershipValidationError,
    validate_grade_item_membership_transition,
)
from meridian.grade_item_storage import (
    get_current_grade_item_revision,
    load_grade_item_revision,
)
from meridian.grade_items import GradeItemValidationError, GradeItemWorkReference

GradeItemMembershipAuthoringOperation: TypeAlias = Literal["create", "revise"]
_GRADE_ITEM_MEMBERSHIP_AUTHORING_OPERATIONS = frozenset({"create", "revise"})


class GradeItemMembershipAuthoringError(RuntimeError):
    """Base error for teacher Grade Item membership authoring."""

    code = "teacher_workflow.grade_items.membership_authoring_error"


class GradeItemMembershipAuthoringScopeError(
    GradeItemMembershipAuthoringError, ValueError
):
    """Raised when a requested membership authoring operation is invalid."""

    code = "teacher_workflow.grade_items.membership_authoring_invalid"


class GradeItemMembershipAuthoringStaleError(GradeItemMembershipAuthoringError):
    """Raised when reviewed membership authoring state has changed."""

    code = "teacher_workflow.grade_items.membership_authoring_stale"


@dataclass(frozen=True, slots=True)
class GradeItemMembershipAuthoringPreview:
    """Exact read-only basis for one immutable membership revision write."""

    operation: GradeItemMembershipAuthoringOperation
    candidate: GradeItemMembershipDecision
    history: tuple[int, ...]
    latest_persisted_decision_sha256: str | None
    expected_current_grade_item_revision: int
    expected_current_membership_revision: int | None

    def __post_init__(self) -> None:
        if self.operation not in _GRADE_ITEM_MEMBERSHIP_AUTHORING_OPERATIONS:
            raise GradeItemMembershipAuthoringScopeError(
                "operation must be create or revise."
            )
        if not isinstance(self.candidate, GradeItemMembershipDecision):
            raise GradeItemMembershipAuthoringScopeError(
                "candidate must be a GradeItemMembershipDecision."
            )
        if tuple(sorted(self.history)) != self.history:
            raise GradeItemMembershipAuthoringScopeError(
                "membership history must be deterministically ordered."
            )
        if self.history:
            expected = tuple(range(1, self.history[-1] + 1))
            if self.history != expected:
                raise GradeItemMembershipAuthoringScopeError(
                    "membership history must be contiguous from revision 1."
                )
        if self.operation == "create":
            if self.history:
                raise GradeItemMembershipAuthoringScopeError(
                    "create requires no existing membership revision history."
                )
            if self.latest_persisted_decision_sha256 is not None:
                raise GradeItemMembershipAuthoringScopeError(
                    "create cannot carry a previous membership decision digest."
                )
            if self.candidate.membership_revision != 1:
                raise GradeItemMembershipAuthoringScopeError(
                    "create candidate must be membership revision 1."
                )
        else:
            if not self.history:
                raise GradeItemMembershipAuthoringScopeError(
                    "revise requires existing membership revision history."
                )
            if self.latest_persisted_decision_sha256 is None:
                raise GradeItemMembershipAuthoringScopeError(
                    "revise requires the latest membership decision digest."
                )
            if self.candidate.membership_revision != self.history[-1] + 1:
                raise GradeItemMembershipAuthoringScopeError(
                    "revise candidate must immediately follow persisted history."
                )
        if (
            self.candidate.grade_item_revision
            != self.expected_current_grade_item_revision
        ):
            raise GradeItemMembershipAuthoringScopeError(
                "candidate Grade Item revision must match the reviewed current "
                "Grade Item selection."
            )

    @property
    def class_id(self) -> str:
        return self.candidate.class_id

    @property
    def grade_item_id(self) -> str:
        return self.candidate.grade_item_id

    @property
    def work(self) -> ModuleWorkRef:
        return self.candidate.work_reference.work

    @property
    def membership_revision(self) -> int:
        return self.candidate.membership_revision

    @property
    def decision(self) -> str:
        return self.candidate.decision


@dataclass(frozen=True, slots=True)
class GradeItemMembershipAuthoringResult:
    """Result of one immutable membership revision write."""

    write_result: GradeItemMembershipRevisionWriteResult
    previous_current_membership_revision: int | None

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.decision.membership_revision

    @property
    def written_decision(self) -> str:
        return self.write_result.stored.decision.decision

    @property
    def write_disposition(self) -> str:
        return self.write_result.disposition

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_grade_item_membership_authoring(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    *,
    operation: GradeItemMembershipAuthoringOperation,
    grade_item_revision: int,
    registration_revision: int,
    decision: GradeItemMembershipDisposition,
    actor_id: str,
    decided_at: datetime,
    academic_period: GradeItemAcademicPeriodAssignment | None,
    rationale: str | None = None,
) -> GradeItemMembershipAuthoringPreview:
    """Build one exact membership write preview without mutating canonical state."""
    if operation not in _GRADE_ITEM_MEMBERSHIP_AUTHORING_OPERATIONS:
        raise GradeItemMembershipAuthoringScopeError(
            "operation must be create or revise."
        )

    selected_grade_item_revision = get_current_grade_item_revision(
        workspace_root,
        class_id,
        grade_item_id,
    )
    if selected_grade_item_revision is None:
        raise GradeItemMembershipAuthoringScopeError(
            "Membership authoring requires an explicitly selected Grade Item "
            "revision."
        )
    if selected_grade_item_revision != grade_item_revision:
        raise GradeItemMembershipAuthoringScopeError(
            "Requested Grade Item revision is not the explicitly selected "
            "current revision."
        )

    grade_item = load_grade_item_revision(
        workspace_root,
        class_id,
        grade_item_id,
        grade_item_revision,
    )
    history = list_grade_item_membership_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    previous = None
    if history:
        previous = load_grade_item_membership_revision(
            workspace_root,
            class_id,
            grade_item_id,
            work,
            history[-1],
        )

    if operation == "create" and history:
        raise GradeItemMembershipAuthoringScopeError(
            "Create requires no existing membership revision history."
        )
    if operation == "revise" and previous is None:
        raise GradeItemMembershipAuthoringScopeError(
            "Revise requires existing membership revision history."
        )

    membership_revision = 1 if previous is None else history[-1] + 1
    try:
        candidate = GradeItemMembershipDecision(
            schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
            record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
            class_id=class_id,
            grade_item_id=grade_item_id,
            grade_item_revision=grade_item_revision,
            grade_item_revision_sha256=grade_item.revision_sha256,
            work_reference=GradeItemWorkReference(
                work=work,
                registration_revision=registration_revision,
            ),
            membership_revision=membership_revision,
            supersedes_revision=None if previous is None else history[-1],
            decision=decision,
            academic_period=academic_period,
            actor_id=actor_id,
            rationale=rationale,
            decided_at=decided_at,
        )
        if previous is not None:
            candidate = validate_grade_item_membership_transition(
                previous.decision,
                candidate,
            )
    except (GradeItemMembershipValidationError, GradeItemValidationError) as error:
        raise GradeItemMembershipAuthoringScopeError(str(error)) from error

    validate_grade_item_membership_dependencies(workspace_root, candidate)
    current_membership_revision = get_current_grade_item_membership_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    return GradeItemMembershipAuthoringPreview(
        operation=operation,
        candidate=candidate,
        history=history,
        latest_persisted_decision_sha256=(
            None if previous is None else previous.decision_sha256
        ),
        expected_current_grade_item_revision=selected_grade_item_revision,
        expected_current_membership_revision=current_membership_revision,
    )


def commit_grade_item_membership_authoring_preview(
    workspace_root: str | Path,
    preview: GradeItemMembershipAuthoringPreview,
) -> GradeItemMembershipAuthoringResult:
    """Revalidate one exact preview and persist only its immutable revision."""
    if not isinstance(preview, GradeItemMembershipAuthoringPreview):
        raise GradeItemMembershipAuthoringScopeError(
            "preview must be a GradeItemMembershipAuthoringPreview."
        )

    current_grade_item_revision = get_current_grade_item_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
    )
    if current_grade_item_revision != preview.expected_current_grade_item_revision:
        raise GradeItemMembershipAuthoringStaleError(
            "Current Grade Item selection changed after membership preview."
        )

    grade_item = load_grade_item_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.candidate.grade_item_revision,
    )
    if grade_item.revision_sha256 != preview.candidate.grade_item_revision_sha256:
        raise GradeItemMembershipAuthoringStaleError(
            "Grade Item revision digest changed after membership preview."
        )

    history = list_grade_item_membership_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if history != preview.history:
        raise GradeItemMembershipAuthoringStaleError(
            "Membership revision history changed after preview."
        )

    if history:
        latest = load_grade_item_membership_revision(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.work,
            history[-1],
        )
        if (
            latest.decision_sha256
            != preview.latest_persisted_decision_sha256
        ):
            raise GradeItemMembershipAuthoringStaleError(
                "Latest membership decision digest changed after preview."
            )
    elif preview.latest_persisted_decision_sha256 is not None:
        raise GradeItemMembershipAuthoringStaleError(
            "Membership history no longer matches the reviewed preview."
        )

    current_membership_revision = get_current_grade_item_membership_revision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if (
        current_membership_revision
        != preview.expected_current_membership_revision
    ):
        raise GradeItemMembershipAuthoringStaleError(
            "Current membership selection changed after preview."
        )

    validate_grade_item_membership_dependencies(
        workspace_root,
        preview.candidate,
    )
    write_result = write_grade_item_membership_revision(
        workspace_root,
        preview.candidate,
    )
    return GradeItemMembershipAuthoringResult(
        write_result=write_result,
        previous_current_membership_revision=(
            preview.expected_current_membership_revision
        ),
    )
