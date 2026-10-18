"""#122: safely reopen exact Standards-association selection after restart.

Canonical identities are discovered from validated immutable histories, not a
journal-supplied directory name. Fresh evidence authorization is indispensable.
There is no immutable authoring route in this port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_work_registration_storage import (
    get_current_academic_work_registration_revision,
)

from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_evidence_storage import (
    list_standard_evidence_association_identities,
    list_standard_evidence_association_revisions,
    load_current_standard_evidence_association_decision,
    load_standard_evidence_association_revision,
    select_standard_evidence_association_revision,
    validate_standard_evidence_association_dependencies,
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
from meridian.teacher_action_restart_eligibility import (
    load_fresh_restart_authorization,
)

ActorChecker = Callable[[TeacherActionActor], None]
AuthorizedLoader = Callable[
    [Path, EvidenceSourceReference], AuthorizedProjectionSnapshot
]
_MAX_IDENTITIES = 4096


@dataclass(frozen=True, slots=True)
class RestartStandardInspection:
    """Live read of exact selector state, never a journal-only success."""

    status: str
    reason: str
    can_resume: bool


def load_fresh_restart_standard_authorization(
    root: Path, source: EvidenceSourceReference, diagnostics: DiagnosticsDependencies
) -> AuthorizedProjectionSnapshot:
    """Reauthorize the original snapshot without a cache or publication write."""
    return load_fresh_restart_authorization(root, source, diagnostics)


class _RestartStandardPort:
    kind: ActionKind = "standards_association"

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
            raise TeacherActionConflictError("Wrong Standard-recovery family.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
            or actor.source != "saved"
        ):
            raise TeacherActionConflictError("Unrecoverable Standard review or actor.")
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Recovery workspace changed.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError("Standard academic scope is incomplete.")
        if (
            len(preview.basis) != 2
            or preview.basis[0]
            != TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            )
            or preview.basis[1].role != "canonical_source"
            or preview.basis[1].identity_sha256 != target.identity_sha256
        ):
            raise TeacherActionConflictError("Standard review bindings are invalid.")

    def _identity(self) -> tuple[EvidenceSourceReference, str]:
        scope, target = self.preview.scope, self.preview.target
        identities = list_standard_evidence_association_identities(
            self.root, scope.class_id, scope.grade_item_id
        )
        if len(identities) > _MAX_IDENTITIES:
            raise TeacherActionConflictError("Standard identity lookup exceeds bound.")
        matches = [
            (source, standard_id)
            for source, standard_id in identities
            if (
                _identity(
                    "work",
                    scope.class_id,
                    source.work.module_id,
                    source.work.work_id,
                )
                == scope.work_identity_sha256
                and _identity(
                    "standard_association",
                    scope.class_id,
                    scope.grade_item_id,
                    source.work.module_id,
                    source.work.work_id,
                    source.publication_id,
                    source.item_id,
                    standard_id,
                )
                == target.identity_sha256
            )
        ]
        if len(matches) != 1:
            raise TeacherActionConflictError(
                "Saved source/Standard pair is not uniquely identifiable."
            )
        return matches[0]

    def _validated(
        self, preview: TeacherActionPreview
    ) -> tuple[EvidenceSourceReference, str, AuthorizedProjectionSnapshot]:
        if preview != self.preview:
            raise TeacherActionConflictError("Standard recovery intent changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        source, standard_id = self._identity()
        history = list_standard_evidence_association_revisions(
            self.root, scope.class_id, scope.grade_item_id, source, standard_id
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError("Standard association history changed.")
        stored = load_standard_evidence_association_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            source,
            standard_id,
            target.revision,
        )
        decision = stored.decision
        if (
            stored.decision_sha256 != target.candidate_sha256
            or decision.class_id != scope.class_id
            or decision.grade_item_id != scope.grade_item_id
            or decision.source != source
            or decision.standard_id != standard_id
            or decision.association_revision != target.revision
            or decision.actor.kind != "teacher"
            or decision.actor.actor_id != preview.actor.actor_id
        ):
            raise TeacherActionConflictError("Canonical Standard decision differs.")
        membership = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, source.work
        )
        if membership is None or membership.decision.decision != "included":
            raise TeacherActionConflictError("Current included membership is missing.")
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
        current_grade = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        if (
            current_grade is None
            or current_grade.revision.grade_item_revision
            != membership.decision.grade_item_revision
            or current_grade.revision_sha256
            != membership.decision.grade_item_revision_sha256
        ):
            raise TeacherActionConflictError("Current Grade Item changed.")
        if get_current_academic_work_registration_revision(self.root, source.work) != (
            membership.decision.work_reference.registration_revision
        ):
            raise TeacherActionConflictError("Academic work registration changed.")
        validate_grade_item_membership_dependencies(self.root, membership.decision)
        binding = _identity(
            "standard_source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            membership.decision_sha256,
            current_grade.revision_sha256,
            standard_id,
        )
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile",
                _identity(preview.actor.actor_id),
                preview.actor.profile_sha256,
            ),
            TeacherActionBasis("canonical_source", target.identity_sha256, binding),
        ):
            raise TeacherActionConflictError("Standard source fingerprint changed.")
        authorized = self.authorized_loader(self.root, source)
        if not authorized.assessment.reusable_for_current_use:
            raise TeacherActionConflictError("Authorized source is not current.")
        resolved = validate_standard_evidence_association_dependencies(
            self.root, decision, authorized
        )
        if (
            resolved.grade_item.revision_sha256 != current_grade.revision_sha256
            or resolved.membership.decision_sha256 != membership.decision_sha256
            or not resolved.standard_resolution.resolved
            or not resolved.standard_resolution.active
        ):
            raise TeacherActionConflictError("Standard authority changed.")
        return source, standard_id, authorized

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        source, standard_id, _ = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_standard_evidence_association_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            source,
            standard_id,
            target.revision,
        )
        current = load_current_standard_evidence_association_decision(
            self.root, scope.class_id, scope.grade_item_id, source, standard_id
        )
        return CanonicalActionObservation(
            target_sha256=stored.decision_sha256,
            current_revision=(
                None if current is None else current.decision.association_revision
            ),
            current_sha256=None if current is None else current.decision_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot write an immutable Standard association."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        source, standard_id, authorized = self._validated(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Exact Standard target differs.")
        scope, target = preview.scope, preview.target
        current = load_current_standard_evidence_association_decision(
            self.root, scope.class_id, scope.grade_item_id, source, standard_id
        )
        current_rev = None if current is None else current.decision.association_revision
        current_sha = None if current is None else current.decision_sha256
        if (
            current_rev != target.expected_current_revision
            or current_sha != target.expected_current_sha256
        ):
            raise TeacherActionConflictError("Standard CAS baseline changed.")
        chosen = select_standard_evidence_association_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            source,
            standard_id,
            target.revision,
            expected_current_association_revision=target.expected_current_revision,
            authorized_snapshot=authorized,
        )
        if chosen.stored.decision_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Standard selection digest mismatch.")
        value: str = chosen.disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected Standard selection status.")


def inspect_restart_standard(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> RestartStandardInspection:
    """Freshly authorized canonical review; never authorize from receipt alone."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Recovery workspace/class mismatch.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Journal changed since inbox review.")
    port = _RestartStandardPort(root, receipt, authorized_loader, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartStandardInspection(assessment.status, assessment.reason, can_resume)


def resume_restart_standard(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """Explicit RESUME only. Never creates another association revision."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Recovery was not confirmed.")
    inspection = inspect_restart_standard(
        root,
        store,
        receipt,
        authorized_loader=authorized_loader,
        actor_checker=actor_checker,
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError("Standard selection cannot be resumed.")
    port = _RestartStandardPort(root, receipt, authorized_loader, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartStandardInspection",
    "inspect_restart_standard",
    "load_fresh_restart_standard_authorization",
    "resume_restart_standard",
)
