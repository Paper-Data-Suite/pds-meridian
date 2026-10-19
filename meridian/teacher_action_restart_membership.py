"""#122 fail-closed restart selection for one persisted Grade Item/work relation.

This port reconstructs only a unique validated canonical relationship, never
an academic writer. Reopened receipts are NOT permission to create or revise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pds_core.academic_work_registration_storage import (
    get_current_academic_work_registration_revision,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_selection_workflow import (
    commit_grade_item_membership_selection_preview,
    preview_grade_item_membership_selection,
)
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    list_grade_item_membership_work_refs,
    load_current_grade_item_membership_decision,
    load_grade_item_membership_revision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
)
from meridian.teacher_action_guided import _actor_now, _calendar_digest, _identity
from meridian.teacher_action_orchestration import (
    TeacherActionConflictError,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceipt,
    TeacherActionReceiptStore,
    assess_teacher_action_recovery,
)

ActorChecker = Callable[[TeacherActionActor], None]
_MAX_CANDIDATE_WORKS = 2048


@dataclass(frozen=True, slots=True)
class RestartMembershipInspection:
    """Canonical result, not a status inferred from a journal checkpoint."""

    status: str
    reason: str
    work_label: str | None
    can_resume: bool


class _RestartMembershipPort:
    kind: ActionKind = "grade_item_membership"

    def __init__(
        self,
        root: Path,
        receipt: TeacherActionReceipt,
        actor_checker: ActorChecker,
    ) -> None:
        self.root = root
        self.preview = receipt.preview
        self.actor_checker = actor_checker
        self._check_envelope()

    def _check_envelope(self) -> None:
        preview = self.preview
        scope, target, actor = preview.scope, preview.target, preview.actor
        if preview.kind != self.kind or target.family != self.kind:
            raise TeacherActionConflictError("Restart action has an unsupported kind.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
        ):
            raise TeacherActionConflictError(
                "Reviewed membership digest or selection intent changed."
            )
        if actor.source != "saved":
            raise TeacherActionConflictError(
                "Temporary attribution cannot be reconstructed after restart."
            )
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Workspace changed since review.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError("Membership academic scope is incomplete.")
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            ),
            TeacherActionBasis(
                "canonical_source",
                target.identity_sha256,
                _identity("membership_candidate", target.candidate_sha256),
            ),
        ):
            raise TeacherActionConflictError("Membership intent basis differs.")

    def _work(self) -> ModuleWorkRef:
        scope, target = self.preview.scope, self.preview.target
        refs = list_grade_item_membership_work_refs(
            self.root, scope.class_id, scope.grade_item_id
        )
        if len(refs) > _MAX_CANDIDATE_WORKS:
            raise TeacherActionConflictError("Membership lookup exceeds safe bounds.")
        matches = tuple(
            work
            for work in refs
            if (
                _identity("work", scope.class_id, work.module_id, work.work_id)
                == scope.work_identity_sha256
                and _identity(
                    "membership",
                    scope.class_id,
                    scope.grade_item_id,
                    work.module_id,
                    work.work_id,
                )
                == target.identity_sha256
            )
        )
        if len(matches) != 1:
            raise TeacherActionConflictError(
                "Exact saved work relationship cannot be identified uniquely."
            )
        return matches[0]

    def _validated(self, preview: TeacherActionPreview) -> ModuleWorkRef:
        if preview != self.preview:
            raise TeacherActionConflictError("Recovery intent changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        work = self._work()
        history = list_grade_item_membership_revisions(
            self.root, scope.class_id, scope.grade_item_id, work
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError(
                "Membership history was extended or changed since save."
            )
        stored = load_grade_item_membership_revision(
            self.root, scope.class_id, scope.grade_item_id, work, target.revision
        )
        decision = stored.decision
        if (
            stored.decision_sha256 != target.candidate_sha256
            or decision.class_id != scope.class_id
            or decision.grade_item_id != scope.grade_item_id
            or decision.work_reference.work != work
            or decision.membership_revision != target.revision
            or decision.decision != "included"
            or decision.actor_id != preview.actor.actor_id
        ):
            raise TeacherActionConflictError(
                "Canonical relationship differs from save."
            )
        assignment = decision.academic_period
        school_year = scope.school_year
        if (
            assignment is None
            or school_year is None
            or assignment.period.school_year != school_year
            or assignment.period.period_id != scope.academic_period_id
            or _calendar_digest(self.root, school_year, assignment.calendar_revision)
            != scope.calendar_sha256
        ):
            raise TeacherActionConflictError("Academic period changed since save.")
        current_grade_item = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        if (
            current_grade_item is None
            or current_grade_item.revision.grade_item_revision
            != decision.grade_item_revision
            or current_grade_item.revision_sha256 != decision.grade_item_revision_sha256
        ):
            raise TeacherActionConflictError("Current Grade Item changed since save.")
        current_registration = get_current_academic_work_registration_revision(
            self.root, work
        )
        if current_registration != decision.work_reference.registration_revision:
            raise TeacherActionConflictError("Work registration changed since save.")
        validate_grade_item_membership_dependencies(self.root, decision)
        return work

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        work = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_grade_item_membership_revision(
            self.root, scope.class_id, scope.grade_item_id, work, target.revision
        )
        current = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, work
        )
        return CanonicalActionObservation(
            target_sha256=stored.decision_sha256,
            current_revision=(
                None if current is None else current.decision.membership_revision
            ),
            current_sha256=None if current is None else current.decision_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot author a membership revision."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        work = self._validated(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Exact membership target differs.")
        scope, target = preview.scope, preview.target
        selection = preview_grade_item_membership_selection(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            target.revision,
        )
        if (
            selection.target.decision_sha256 != target.candidate_sha256
            or selection.expected_current_membership_revision
            != target.expected_current_revision
            or selection.history != tuple(range(1, target.revision + 1))
        ):
            raise TeacherActionConflictError("Membership selector basis changed.")
        result = commit_grade_item_membership_selection_preview(self.root, selection)
        if result.selection_result.stored.decision_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Canonical selector chose another digest.")
        value = result.selection_disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unknown membership selection disposition.")


def inspect_restart_membership(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    actor_checker: ActorChecker = _actor_now,
) -> RestartMembershipInspection:
    """Inspect a persisted exact membership without academic mutation."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Recovery workspace or class differs.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Journal changed since inbox review.")
    port = _RestartMembershipPort(root, receipt, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    work: ModuleWorkRef | None = None
    if assessment.target_verified_present:
        work = port._work()
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartMembershipInspection(
        assessment.status,
        assessment.reason,
        None if work is None else "Verified registered work relationship",
        can_resume,
    )


def resume_restart_membership(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """Explicit RESUME is selection-only: immutable authoring is disabled."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Restart recovery was not confirmed.")
    inspection = inspect_restart_membership(
        root, store, receipt, actor_checker=actor_checker
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError(
            "Exact membership resume is unavailable; review canonical state."
        )
    port = _RestartMembershipPort(root, receipt, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartMembershipInspection",
    "inspect_restart_membership",
    "resume_restart_membership",
)
