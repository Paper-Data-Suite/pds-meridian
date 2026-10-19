"""#122: exact post-restart eligibility selection; no authoring or cache writes.

The recovered source is located through canonical histories, then reauthorized
through the existing projection-cache reader for the current session. A receipt
is never an evidence-access grant or an immutable-write instruction.
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
from meridian.evidence_eligibility_storage import (
    list_evidence_eligibility_revisions,
    list_evidence_eligibility_sources,
    load_current_evidence_eligibility_decision,
    load_evidence_eligibility_revision,
    validate_evidence_eligibility_dependencies,
)
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_work_refs,
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.guided_projection import GUIDED_EVIDENCE_REVIEW_PURPOSE_ID
from meridian.new_evidence_eligibility_selection_workflow import (
    commit_new_evidence_eligibility_selection_preview,
    preview_new_evidence_eligibility_selection,
)
from meridian.new_evidence_workflow import project_new_evidence_review
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
    [Path, EvidenceSourceReference], AuthorizedProjectionSnapshot
]
_MAX_WORKS = 2048
_MAX_SOURCES = 4096


@dataclass(frozen=True, slots=True)
class RestartEligibilityInspection:
    """Canonical and currently authorized inspection, never journal-only truth."""

    status: str
    reason: str
    can_resume: bool


def load_fresh_restart_authorization(
    root: Path,
    source: EvidenceSourceReference,
    diagnostics: DiagnosticsDependencies,
) -> AuthorizedProjectionSnapshot:
    """Read existing exact snapshot with *fresh* access checks; never project."""
    registry = diagnostics.producer_registry
    authorizer = diagnostics.authorizer
    if (
        authorizer is None
        or diagnostics.producer_registry_state != "available"
        or registry is None
    ):
        raise TeacherActionConflictError(
            "Current authorized evidence access is required for eligibility recovery."
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
    if not authorized.assessment.reusable_for_current_use:
        raise TeacherActionConflictError(
            "The authorized publication is no longer current for evidence review."
        )
    stored = authorized.stored
    publication = authorized.current_context.publication
    if (
        publication.publication_id != source.publication_id
        or publication.work != source.work
        or stored.cache_key != source.cache_key
        or stored.snapshot_digest != source.snapshot_digest
    ):
        raise TeacherActionConflictError("Fresh authorization is for another source.")
    return authorized


class _RestartEligibilityPort:
    kind: ActionKind = "eligibility"

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
            raise TeacherActionConflictError("Wrong eligibility recovery family.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
        ):
            raise TeacherActionConflictError("Reviewed eligibility intent changed.")
        if actor.source != "saved":
            raise TeacherActionConflictError(
                "Temporary attribution cannot be restored."
            )
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Workspace path changed since review.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError(
                "Eligibility academic scope is incomplete."
            )
        if len(preview.basis) != 2 or (
            preview.basis[0]
            != TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            )
            or preview.basis[1].role != "canonical_source"
            or preview.basis[1].identity_sha256 != target.identity_sha256
        ):
            raise TeacherActionConflictError(
                "Unexpected eligibility recovery bindings."
            )

    def _source(self) -> EvidenceSourceReference:
        scope, target = self.preview.scope, self.preview.target
        works = list_grade_item_membership_work_refs(
            self.root, scope.class_id, scope.grade_item_id
        )
        if len(works) > _MAX_WORKS:
            raise TeacherActionConflictError("Source work lookup exceeds safe bounds.")
        matches: list[EvidenceSourceReference] = []
        for work in works:
            if (
                _identity("work", scope.class_id, work.module_id, work.work_id)
                != scope.work_identity_sha256
            ):
                continue
            sources = list_evidence_eligibility_sources(
                self.root, scope.class_id, scope.grade_item_id, work
            )
            if len(sources) > _MAX_SOURCES:
                raise TeacherActionConflictError(
                    "Evidence source lookup exceeds safe bounds."
                )
            for source in sources:
                identity = _identity(
                    "eligibility",
                    scope.class_id,
                    scope.grade_item_id,
                    work.module_id,
                    work.work_id,
                    source.publication_id,
                    source.item_id,
                )
                if identity == target.identity_sha256:
                    matches.append(source)
        if len(matches) != 1:
            raise TeacherActionConflictError("Exact evidence source is not unique.")
        return matches[0]

    def _validated(
        self, preview: TeacherActionPreview
    ) -> tuple[EvidenceSourceReference, AuthorizedProjectionSnapshot]:
        if preview != self.preview:
            raise TeacherActionConflictError("Recovery preview changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        source = self._source()
        history = list_evidence_eligibility_revisions(
            self.root, scope.class_id, scope.grade_item_id, source
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError("Eligibility history changed since save.")
        stored = load_evidence_eligibility_revision(
            self.root, scope.class_id, scope.grade_item_id, source, target.revision
        )
        decision = stored.decision
        if (
            stored.decision_sha256 != target.candidate_sha256
            or decision.class_id != scope.class_id
            or decision.grade_item_id != scope.grade_item_id
            or decision.source != source
            or decision.eligibility_revision != target.revision
            or decision.actor.kind != "teacher"
            or decision.actor.actor_id != preview.actor.actor_id
        ):
            raise TeacherActionConflictError("Canonical eligibility decision differs.")
        expected_source_binding = _identity(
            "source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            decision.membership_revision_sha256,
        )
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile",
                _identity(preview.actor.actor_id),
                preview.actor.profile_sha256,
            ),
            TeacherActionBasis(
                "canonical_source", target.identity_sha256, expected_source_binding
            ),
        ):
            raise TeacherActionConflictError("Eligibility source provenance differs.")
        membership = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, source.work
        )
        if (
            membership is None
            or membership.decision.decision != "included"
            or membership.decision.membership_revision != decision.membership_revision
            or membership.decision_sha256 != decision.membership_revision_sha256
        ):
            raise TeacherActionConflictError("Current Grade Item relationship changed.")
        assignment = membership.decision.academic_period
        if (
            assignment is None
            or scope.school_year != assignment.period.school_year
            or scope.academic_period_id != assignment.period.period_id
            or _calendar_digest(
                self.root, assignment.period.school_year, assignment.calendar_revision
            )
            != scope.calendar_sha256
        ):
            raise TeacherActionConflictError("Academic period changed since save.")
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
            raise TeacherActionConflictError("Grade Item revision changed.")
        registration = get_current_academic_work_registration_revision(
            self.root, source.work
        )
        if registration != membership.decision.work_reference.registration_revision:
            raise TeacherActionConflictError(
                "Current academic work registration changed."
            )
        validate_grade_item_membership_dependencies(self.root, membership.decision)
        authorized = self.authorized_loader(self.root, source)
        if not authorized.assessment.reusable_for_current_use:
            raise TeacherActionConflictError(
                "Authorized projection cannot be used currently."
            )
        # Always run the canonical dependency verifier, including current
        # authorization, membership and *authored* source lifecycle.
        validate_evidence_eligibility_dependencies(
            self.root,
            decision,
            authorized,
            require_current_membership=True,
            require_authored_source_state=True,
        )
        return source, authorized

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        source, _ = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_evidence_eligibility_revision(
            self.root, scope.class_id, scope.grade_item_id, source, target.revision
        )
        current = load_current_evidence_eligibility_decision(
            self.root, scope.class_id, scope.grade_item_id, source
        )
        return CanonicalActionObservation(
            target_sha256=stored.decision_sha256,
            current_revision=None
            if current is None
            else current.decision.eligibility_revision,
            current_sha256=None if current is None else current.decision_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot author eligibility revisions."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        source, authorized = self._validated(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Eligibility record differs from review.")
        scope, target = preview.scope, preview.target
        review = project_new_evidence_review(
            self.root, scope.class_id, scope.grade_item_id, authorized
        )
        selection = preview_new_evidence_eligibility_selection(
            self.root,
            review,
            authorized,
            item_id=source.item_id,
            eligibility_revision=target.revision,
        )
        if (
            selection.target.decision_sha256 != target.candidate_sha256
            or selection.expected_current_revision != target.expected_current_revision
        ):
            raise TeacherActionConflictError("Eligibility CAS baseline changed.")
        result = commit_new_evidence_eligibility_selection_preview(
            self.root, selection, authorized
        )
        if result.selection_result.stored.decision_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError("Selector returned a different decision.")
        value: str = result.selection_disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected eligibility selection status.")


def inspect_restart_eligibility(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> RestartEligibilityInspection:
    """Fresh authorized read; if not authorized, no protected data is displayed."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Class or workspace differs from receipt.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Receipt changed after inbox review.")
    port = _RestartEligibilityPort(root, receipt, authorized_loader, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartEligibilityInspection(
        assessment.status, assessment.reason, can_resume
    )


def resume_restart_eligibility(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """RESUME only: exact persisted target, fresh authority, no immutable writer."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Restart recovery was not confirmed.")
    inspection = inspect_restart_eligibility(
        root,
        store,
        receipt,
        authorized_loader=authorized_loader,
        actor_checker=actor_checker,
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError(
            "Eligibility resume is unavailable under current authority."
        )
    port = _RestartEligibilityPort(root, receipt, authorized_loader, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartEligibilityInspection",
    "inspect_restart_eligibility",
    "load_fresh_restart_authorization",
    "resume_restart_eligibility",
)
