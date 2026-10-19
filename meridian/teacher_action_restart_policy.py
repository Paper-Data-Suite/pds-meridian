"""#122: reselect precisely one previously saved attempt policy after restart.

A journal is an index, never an academic authority. All identity, history,
actor, work, period and selector state is reloaded from canonical storage.
No immutable policy writer is reachable through this recovery port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_work_registration_storage import (
    get_current_academic_work_registration_revision,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_policy_selection_workflow import (
    commit_attempt_policy_selection_preview,
    preview_attempt_policy_selection,
)
from meridian.attempt_selection_storage import (
    list_attempt_selection_policy_identities,
    list_attempt_selection_policy_revisions,
    load_attempt_selection_policy_revision,
    load_current_attempt_selection_policy,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
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
_MAX_IDENTITIES = 4096


@dataclass(frozen=True, slots=True)
class RestartPolicyInspection:
    """Read-only canonical recovery assessment, not receipt-only success."""

    status: str
    reason: str
    can_resume: bool


class _RestartPolicyPort:
    kind: ActionKind = "attempt_policy"

    def __init__(
        self, root: Path, receipt: TeacherActionReceipt, actor_checker: ActorChecker
    ) -> None:
        self.root = root
        self.preview = receipt.preview
        self.actor_checker = actor_checker
        self._check_envelope()

    def _check_envelope(self) -> None:
        preview = self.preview
        scope, target, actor = preview.scope, preview.target, preview.actor
        if preview.kind != self.kind or target.family != self.kind:
            raise TeacherActionConflictError("Wrong policy recovery family.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
            or actor.source != "saved"
        ):
            raise TeacherActionConflictError("Policy review/actor cannot be resumed.")
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Policy recovery workspace changed.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError("Policy academic scope is incomplete.")
        if (
            len(preview.basis) != 2
            or preview.basis[0]
            != TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            )
            or preview.basis[1].role != "canonical_source"
            or preview.basis[1].identity_sha256 != target.identity_sha256
        ):
            raise TeacherActionConflictError("Policy recovery review bindings differ.")

    def _identity(self) -> tuple[ModuleWorkRef, str]:
        scope, target = self.preview.scope, self.preview.target
        candidates = list_attempt_selection_policy_identities(
            self.root, scope.class_id, maximum_families=_MAX_IDENTITIES
        )
        matches = [
            (work, policy_id)
            for grade_item_id, work, policy_id in candidates
            if grade_item_id == scope.grade_item_id
            and _identity("work", scope.class_id, work.module_id, work.work_id)
            == scope.work_identity_sha256
            and _identity(
                "attempt_policy",
                scope.class_id,
                grade_item_id,
                work.module_id,
                work.work_id,
                policy_id,
            )
            == target.identity_sha256
        ]
        if len(matches) != 1:
            raise TeacherActionConflictError(
                "Saved attempt-policy identity cannot be resolved uniquely."
            )
        return matches[0]

    def _validated(self, preview: TeacherActionPreview) -> tuple[ModuleWorkRef, str]:
        if preview != self.preview:
            raise TeacherActionConflictError("Policy recovery intent changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        work, policy_id = self._identity()
        history = list_attempt_selection_policy_revisions(
            self.root, scope.class_id, scope.grade_item_id, work, policy_id
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError("Policy revision history changed.")
        stored = load_attempt_selection_policy_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            policy_id,
            target.revision,
        )
        policy = stored.policy
        if (
            stored.policy_sha256 != target.candidate_sha256
            or policy.class_id != scope.class_id
            or policy.grade_item_id != scope.grade_item_id
            or policy.work != work
            or policy.policy_id != policy_id
            or policy.policy_revision != target.revision
            or policy.selection_basis != "explicit"
        ):
            raise TeacherActionConflictError("Canonical policy differs from Save.")
        membership = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, work
        )
        if membership is None or membership.decision.decision != "included":
            raise TeacherActionConflictError("Included work relationship changed.")
        assignment = membership.decision.academic_period
        if (
            assignment is None
            or assignment.period.school_year != scope.school_year
            or assignment.period.period_id != scope.academic_period_id
            or _calendar_digest(
                self.root, assignment.period.school_year, assignment.calendar_revision
            )
            != scope.calendar_sha256
        ):
            raise TeacherActionConflictError("Policy academic period changed.")
        grade = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        if (
            grade is None
            or grade.revision_sha256 != membership.decision.grade_item_revision_sha256
        ):
            raise TeacherActionConflictError("Policy Grade Item changed.")
        validate_grade_item_membership_dependencies(self.root, membership.decision)
        if get_current_academic_work_registration_revision(self.root, work) != (
            membership.decision.work_reference.registration_revision
        ):
            raise TeacherActionConflictError("Policy work registration changed.")
        original_binding = preview.basis[1]
        calendar_sha = scope.calendar_sha256
        if calendar_sha is None:
            raise TeacherActionConflictError("Policy calendar fingerprint is missing.")
        actions = ("select_existing", "create" if target.revision == 1 else "revise")
        matched_actions = [
            action
            for action in actions
            if original_binding
            == TeacherActionBasis(
                "canonical_source",
                target.identity_sha256,
                _identity(
                    "attempt_policy_source",
                    work.module_id,
                    work.work_id,
                    policy_id,
                    str(target.revision),
                    target.candidate_sha256,
                    action,
                    membership.decision_sha256,
                    grade.revision_sha256,
                    calendar_sha,
                ),
            )
        ]
        if len(matched_actions) != 1:
            raise TeacherActionConflictError(
                "Saved policy authority fingerprint changed."
            )
        action = matched_actions[0]
        if action != "select_existing" and (
            policy.actor.kind != "teacher"
            or policy.actor.actor_id != preview.actor.actor_id
        ):
            raise TeacherActionConflictError("Policy author attribution changed.")
        if action == "create" and target.expected_current_revision is not None:
            raise TeacherActionConflictError("Initial policy baseline changed.")
        if action == "revise" and target.revision < 2:
            raise TeacherActionConflictError("Policy revision category changed.")
        if action == "select_existing" and target.revision != history[-1]:
            raise TeacherActionConflictError(
                "Existing-policy target is no longer latest."
            )
        return work, policy_id

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        work, policy_id = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_attempt_selection_policy_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            policy_id,
            target.revision,
        )
        selected = load_current_attempt_selection_policy(
            self.root, scope.class_id, scope.grade_item_id, work, policy_id
        )
        return CanonicalActionObservation(
            target_sha256=stored.policy_sha256,
            current_revision=(
                None if selected is None else selected.policy.policy_revision
            ),
            current_sha256=None if selected is None else selected.policy_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart policy recovery never writes an immutable policy."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        work, policy_id = self._validated(preview)
        scope, target = preview.scope, preview.target
        if not record.matches_target(target):
            raise TeacherActionConflictError("Policy recovery target differs.")
        current = load_current_attempt_selection_policy(
            self.root, scope.class_id, scope.grade_item_id, work, policy_id
        )
        current_revision = None if current is None else current.policy.policy_revision
        current_sha = None if current is None else current.policy_sha256
        if (
            current_revision != target.expected_current_revision
            or current_sha != target.expected_current_sha256
        ):
            raise TeacherActionConflictError("Policy CAS baseline changed.")
        selection = preview_attempt_policy_selection(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            policy_id,
            target.revision,
        )
        if (
            selection.target_sha256 != target.candidate_sha256
            or selection.expected_current_policy_revision
            != target.expected_current_revision
            or selection.history != tuple(range(1, target.revision + 1))
        ):
            raise TeacherActionConflictError("Policy selection preview changed.")
        result = commit_attempt_policy_selection_preview(
            self.root,
            selection,
            currentness_check=lambda: self._validated(preview),
        )
        if result.selected_policy_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Policy selector returned another target.")
        value = result.selection_disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unknown policy selection disposition.")


def inspect_restart_policy(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    actor_checker: ActorChecker = _actor_now,
) -> RestartPolicyInspection:
    """Reconcile journal against current canonical academic state, read-only."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Policy recovery workspace/class mismatch.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Journal changed during policy review.")
    port = _RestartPolicyPort(root, receipt, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartPolicyInspection(assessment.status, assessment.reason, can_resume)


def resume_restart_policy(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """One explicit RESUME selects an existing revision; no policy reauthoring."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Policy selection was not confirmed.")
    inspection = inspect_restart_policy(
        root, store, receipt, actor_checker=actor_checker
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError("Policy recovery requires fresh review.")
    port = _RestartPolicyPort(root, receipt, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartPolicyInspection",
    "inspect_restart_policy",
    "resume_restart_policy",
)
