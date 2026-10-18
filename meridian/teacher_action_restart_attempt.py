"""#122 exact attempt-decision selection recovery after process restart.

Recover a single persisted reviewed decision from canonical work/roster indexes.
No attempt, eligibility, or immutable-decision writer is available here. Fresh
projection authorization is mandatory and cannot be reconstructed from a journal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_work_registration_storage import (
    get_current_academic_work_registration_revision,
)
from pds_core.rosters import load_roster
from pds_core.routes import class_roster_path
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_decision_selection_workflow import (
    commit_attempt_decision_selection_preview,
    preview_attempt_decision_selection,
)
from meridian.attempt_selection import AttemptProjectionReference
from meridian.attempt_selection_storage import (
    derive_attempt_candidates,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_decision,
    load_current_attempt_selection_policy,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_work_refs,
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.guided_projection import GUIDED_EVIDENCE_REVIEW_PURPOSE_ID
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    load_authorized_projection_snapshot,
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
AuthorizedLoader = Callable[
    [Path, AttemptProjectionReference], AuthorizedProjectionSnapshot
]
_MAX_WORKS = 2048
_MAX_STUDENTS = 2048
_MAX_PAIRS = 8192


@dataclass(frozen=True, slots=True)
class RestartAttemptInspection:
    """Read-only independently verified eligibility for exact CAS selection."""

    status: str
    reason: str
    can_resume: bool


def load_fresh_restart_attempt_authorization(
    root: Path,
    source: AttemptProjectionReference,
    diagnostics: DiagnosticsDependencies,
) -> AuthorizedProjectionSnapshot:
    """Reauthorize existing source snapshot; do not rebuild or write a cache."""
    registry = diagnostics.producer_registry
    authorizer = diagnostics.authorizer
    if (
        authorizer is None
        or diagnostics.producer_registry_state != "available"
        or registry is None
    ):
        raise TeacherActionConflictError(
            "Current evidence authorization is required for attempt recovery."
        )
    authorized = load_authorized_projection_snapshot(
        root,
        source.publication_id,
        source.cache_key,
        authorizer=authorizer,
        authorization_purpose_id=GUIDED_EVIDENCE_REVIEW_PURPOSE_ID,
        requested_student_ids=(),
        producer_registry=registry,
        adapter_registry=diagnostics.adapter_registry,
        distribution_version_resolver=diagnostics.distribution_version_resolver,
    )
    publication = authorized.current_context.publication
    stored = authorized.stored
    if (
        not authorized.assessment.reusable_for_current_use
        or publication.work != source.work
        or publication.publication_id != source.publication_id
        or stored.cache_key != source.cache_key
        or stored.snapshot_digest != source.snapshot_digest
    ):
        raise TeacherActionConflictError(
            "Authorized attempt source is not the reviewed current publication."
        )
    return authorized


class _RestartAttemptPort:
    kind: ActionKind = "attempt_decision"

    def __init__(
        self,
        root: Path,
        receipt: TeacherActionReceipt,
        authorized_loader: AuthorizedLoader,
        actor_checker: ActorChecker,
    ) -> None:
        self.root = root
        self.preview = receipt.preview
        self.authorized_loader = authorized_loader
        self.actor_checker = actor_checker
        self._check_envelope()

    def _check_envelope(self) -> None:
        preview = self.preview
        scope, target, actor = preview.scope, preview.target, preview.actor
        if preview.kind != self.kind or target.family != self.kind:
            raise TeacherActionConflictError("Wrong attempt-recovery family.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
            or actor.source != "saved"
        ):
            raise TeacherActionConflictError(
                "Attempt intent is incomplete or temporary attribution was used."
            )
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Recovery workspace differs.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError("Attempt academic context is incomplete.")
        if (
            len(preview.basis) != 2
            or preview.basis[0]
            != TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            )
            or preview.basis[1].role != "canonical_source"
            or preview.basis[1].identity_sha256 != target.identity_sha256
        ):
            raise TeacherActionConflictError("Attempt reviewed basis differs.")

    def _subject(self) -> tuple[ModuleWorkRef, str]:
        scope, target = self.preview.scope, self.preview.target
        works = list_grade_item_membership_work_refs(
            self.root, scope.class_id, scope.grade_item_id
        )
        if len(works) > _MAX_WORKS:
            raise TeacherActionConflictError("Work lookup exceeds safe bounds.")
        roster = load_roster(class_roster_path(self.root, scope.class_id))
        if roster.class_id != scope.class_id or len(roster.students) > _MAX_STUDENTS:
            raise TeacherActionConflictError("Roster changed or is oversized.")
        matches: list[tuple[ModuleWorkRef, str]] = []
        scanned = 0
        for work in works:
            if (
                _identity("work", scope.class_id, work.module_id, work.work_id)
                != scope.work_identity_sha256
            ):
                continue
            for student in roster.students:
                scanned += 1
                if scanned > _MAX_PAIRS:
                    raise TeacherActionConflictError(
                        "Attempt identity lookup exceeds safe bounds."
                    )
                if (
                    _identity(
                        "attempt_decision",
                        scope.class_id,
                        scope.grade_item_id,
                        work.module_id,
                        work.work_id,
                        student.student_id,
                    )
                    == target.identity_sha256
                ):
                    matches.append((work, student.student_id))
        if len(matches) != 1:
            raise TeacherActionConflictError(
                "Exact attempt work/student identity is not unique in current roster."
            )
        return matches[0]

    def _validated(
        self, preview: TeacherActionPreview
    ) -> tuple[ModuleWorkRef, str, AuthorizedProjectionSnapshot]:
        if preview != self.preview:
            raise TeacherActionConflictError("Restart attempt intent changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        work, student_id = self._subject()
        history = list_attempt_selection_decision_revisions(
            self.root, scope.class_id, scope.grade_item_id, work, student_id
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError(
                "Attempt history was extended or changed since save."
            )
        stored = load_attempt_selection_decision_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            student_id,
            target.revision,
        )
        decision = stored.decision
        if (
            stored.decision_sha256 != target.candidate_sha256
            or decision.class_id != scope.class_id
            or decision.grade_item_id != scope.grade_item_id
            or decision.work != work
            or decision.student_id != student_id
            or decision.decision_revision != target.revision
            or decision.actor.kind != "teacher"
            or decision.actor.actor_id != preview.actor.actor_id
        ):
            raise TeacherActionConflictError("Persisted attempt decision differs.")
        source = decision.source_snapshot
        source_digest = _identity(
            "attempt_source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            decision.membership_revision_sha256,
            decision.policy.policy_revision_sha256,
        )
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile",
                _identity(preview.actor.actor_id),
                preview.actor.profile_sha256,
            ),
            TeacherActionBasis(
                "canonical_source", target.identity_sha256, source_digest
            ),
        ):
            raise TeacherActionConflictError("Attempt source fingerprint differs.")
        membership = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, work
        )
        if (
            membership is None
            or membership.decision.decision != "included"
            or membership.decision.membership_revision != decision.membership_revision
            or membership.decision_sha256 != decision.membership_revision_sha256
        ):
            raise TeacherActionConflictError("Current work relationship changed.")
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
            raise TeacherActionConflictError("Academic period changed.")
        grade_item = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        if (
            grade_item is None
            or grade_item.revision.grade_item_revision
            != membership.decision.grade_item_revision
            or grade_item.revision_sha256
            != membership.decision.grade_item_revision_sha256
        ):
            raise TeacherActionConflictError("Current Grade Item changed.")
        if get_current_academic_work_registration_revision(self.root, work) != (
            membership.decision.work_reference.registration_revision
        ):
            raise TeacherActionConflictError("Current work registration changed.")
        validate_grade_item_membership_dependencies(self.root, membership.decision)
        policy = load_current_attempt_selection_policy(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            decision.policy.policy_id,
        )
        if (
            policy is None
            or policy.policy.policy_revision != decision.policy.policy_revision
            or policy.policy_sha256 != decision.policy.policy_revision_sha256
        ):
            raise TeacherActionConflictError("Current attempt policy changed.")
        authorized = self.authorized_loader(self.root, source)
        if not authorized.assessment.reusable_for_current_use:
            raise TeacherActionConflictError("Attempt evidence is not current.")
        derivation = derive_attempt_candidates(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            student_id,
            authorized,
        )
        if (
            derivation.status != "applicable"
            or derivation.source_snapshot != source
            or derivation.candidates != decision.candidates
        ):
            raise TeacherActionConflictError(
                "Eligibility-derived attempt candidates changed."
            )
        return work, student_id, authorized

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        work, student_id, _ = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_attempt_selection_decision_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            student_id,
            target.revision,
        )
        current = load_current_attempt_selection_decision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            student_id,
        )
        return CanonicalActionObservation(
            target_sha256=stored.decision_sha256,
            current_revision=(
                None if current is None else current.decision.decision_revision
            ),
            current_sha256=None if current is None else current.decision_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot write another attempt decision."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        work, student_id, authorized = self._validated(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Attempt selection target differs.")
        scope, target = preview.scope, preview.target
        selection = preview_attempt_decision_selection(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            work,
            student_id,
            target.revision,
            authorized_snapshot=authorized,
        )
        if (
            selection.target_sha256 != target.candidate_sha256
            or selection.expected_current_decision_revision
            != target.expected_current_revision
            or selection.history != tuple(range(1, target.revision + 1))
        ):
            raise TeacherActionConflictError("Attempt selector baseline changed.")
        result = commit_attempt_decision_selection_preview(
            self.root, selection, authorized_snapshot=authorized
        )
        if result.selected_decision_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Canonical attempt selector differs.")
        value: str = result.selection_disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unknown attempt selection disposition.")


def inspect_restart_attempt(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> RestartAttemptInspection:
    """Independently check canonical and authorized state without mutation."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Recovery workspace/class mismatch.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Journal changed after inbox review.")
    port = _RestartAttemptPort(root, receipt, authorized_loader, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartAttemptInspection(assessment.status, assessment.reason, can_resume)


def resume_restart_attempt(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """Explicit selection-only RESUME, never a second immutable decision write."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Restart attempt was not confirmed.")
    inspection = inspect_restart_attempt(
        root,
        store,
        receipt,
        authorized_loader=authorized_loader,
        actor_checker=actor_checker,
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError(
            "Saved attempt cannot be resumed; review current evidence."
        )
    port = _RestartAttemptPort(root, receipt, authorized_loader, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartAttemptInspection",
    "inspect_restart_attempt",
    "load_fresh_restart_attempt_authorization",
    "resume_restart_attempt",
)
