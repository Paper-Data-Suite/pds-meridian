"""#122 exact restart recovery for a *new* Grade Item's current selector.

A receipt cannot authorize academic authoring. Recovery reads the original
immutable revision, authenticates its exact identity and current CAS baseline,
then delegates only to the existing Grade Item selection workflow. Other action
families remain inspection-only until their authority can be rehydrated safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pds_core.class_metadata import load_class_metadata
from pds_core.routes import class_metadata_path

from meridian.grade_item_selection_workflow import (
    commit_grade_item_selection_preview,
    preview_grade_item_selection,
)
from meridian.grade_item_storage import (
    list_grade_item_revisions,
    load_current_grade_item_revision,
    load_grade_item_revision,
)
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
)
from meridian.teacher_action_guided import _actor_now, _identity
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


@dataclass(frozen=True, slots=True)
class RestartGradeItemInspection:
    """Live authority outcome; never a journal-derived declaration of success."""

    status: str
    reason: str
    title: str | None
    can_resume: bool


class _RestartGradeItemPort:
    kind: ActionKind = "grade_item"

    def __init__(
        self,
        root: Path,
        receipt: TeacherActionReceipt,
        actor_checker: ActorChecker,
    ) -> None:
        self.root = root
        self.preview = receipt.preview
        self.actor_checker = actor_checker
        self._check_intent()

    def _check_intent(self) -> None:
        preview = self.preview
        scope, target, actor = preview.scope, preview.target, preview.actor
        if preview.kind != "grade_item" or target.family != "grade_item":
            raise TeacherActionConflictError(
                "Restart action has an unsupported family."
            )
        if actor.source != "saved":
            raise TeacherActionConflictError(
                "A temporary attribution cannot be reconstructed after restart."
            )
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Workspace changed since review.")
        if (
            scope.school_year is not None
            or scope.academic_period_id is not None
            or scope.calendar_sha256 is not None
            or scope.work_identity_sha256 is not None
        ):
            raise TeacherActionConflictError("Unexpected Grade Item recovery scope.")
        identity = _identity("grade_item", scope.class_id, scope.grade_item_id)
        if target.identity_sha256 != identity:
            raise TeacherActionConflictError("Grade Item identity fingerprint differs.")
        if (
            target.revision != 1
            or target.expected_current_revision is not None
            or target.expected_current_sha256 is not None
        ):
            raise TeacherActionConflictError(
                "Only exact new Grade Item creation is restart-resumable."
            )
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            ),
            TeacherActionBasis(
                "canonical_source",
                identity,
                _identity("grade_item_candidate", target.candidate_sha256),
            ),
        ):
            raise TeacherActionConflictError("Reviewed Grade Item basis is invalid.")

    def _check(self, preview: TeacherActionPreview) -> None:
        if preview != self.preview:
            raise TeacherActionConflictError("Recovery intent changed.")
        self._check_intent()
        self.actor_checker(preview.actor)
        class_id = preview.scope.class_id
        metadata = load_class_metadata(class_metadata_path(self.root, class_id))
        if metadata.class_id != class_id:
            raise TeacherActionConflictError("Registered class changed.")
        history = list_grade_item_revisions(
            self.root, class_id, preview.scope.grade_item_id
        )
        if history not in ((), (1,)):
            raise TeacherActionConflictError(
                "Grade Item history changed; select manually after review."
            )

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._check(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        self._check(preview)
        scope, target = preview.scope, preview.target
        history = list_grade_item_revisions(
            self.root, scope.class_id, scope.grade_item_id
        )
        stored = (
            load_grade_item_revision(
                self.root, scope.class_id, scope.grade_item_id, target.revision
            )
            if target.revision in history
            else None
        )
        current = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        return CanonicalActionObservation(
            target_sha256=None if stored is None else stored.revision_sha256,
            current_revision=(
                None if current is None else current.revision.grade_item_revision
            ),
            current_sha256=None if current is None else current.revision_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot author an immutable Grade Item revision."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        self._check(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Exact Grade Item target differs.")
        scope, target = preview.scope, preview.target
        selection = preview_grade_item_selection(
            self.root, scope.class_id, scope.grade_item_id, target.revision
        )
        if (
            selection.target.revision_sha256 != target.candidate_sha256
            or selection.expected_current_revision != target.expected_current_revision
            or selection.history != (1,)
        ):
            raise TeacherActionConflictError("Grade Item selector basis changed.")
        committed = commit_grade_item_selection_preview(self.root, selection)
        if committed.selection_result.stored.revision_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Canonical selector chose another digest.")
        value = committed.selection_disposition
        if value not in ("created", "updated", "existing"):
            raise TeacherActionConflictError("Unrecognized selector disposition.")
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        return "existing"


def inspect_restart_grade_item(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    actor_checker: ActorChecker = _actor_now,
) -> RestartGradeItemInspection:
    """Reopen exact journal/canonical state without any academic mutation."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Recovery workspace or class differs.")
    persisted = store.load(receipt.action_id)
    if persisted != receipt:
        raise TeacherActionConflictError("Journal changed since inbox review.")
    port = _RestartGradeItemPort(root, receipt, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    title: str | None = None
    if assessment.target_verified_present:
        target = load_grade_item_revision(
            root,
            receipt.preview.scope.class_id,
            receipt.preview.scope.grade_item_id,
            receipt.preview.target.revision,
        )
        if target.revision_sha256 != receipt.preview.target.candidate_sha256:
            raise TeacherActionConflictError("Stored Grade Item digest differs.")
        title = target.revision.title
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
    )
    return RestartGradeItemInspection(
        assessment.status, assessment.reason, title, can_resume
    )


def resume_restart_grade_item(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """Explicit RESUME only; the reopened action has NO immutable writer."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Restart recovery was not confirmed.")
    current = inspect_restart_grade_item(
        root, store, receipt, actor_checker=actor_checker
    )
    if not current.can_resume:
        raise TeacherActionConflictError(
            "Exact restart selection is unavailable; review canonical state."
        )
    port = _RestartGradeItemPort(root, receipt, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartGradeItemInspection",
    "inspect_restart_grade_item",
    "resume_restart_grade_item",
)
