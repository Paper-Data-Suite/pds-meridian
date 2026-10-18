"""#122 exact restart selection for one recoverable guided proficiency result.

This port is selection-only. It rebuilds one exact, currently authorized
calculation from the persisted input source and never authors another result.
Multiple-source or unreconstructable calculations are intentionally blocked.
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

from meridian.calculation_preview_assembly_workflow import (
    build_bounded_calculation_preview,
)
from meridian.calculation_result_selection_workflow import (
    commit_calculation_result_selection_preview,
    preview_calculation_result_selection,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.proficiency_mapping_storage import load_current_proficiency_scale
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_evidence_storage import StandardAggregationCandidateBinding
from meridian.standards_proficiency_storage import (
    list_standard_proficiency_result_identities,
    list_standard_proficiency_result_revisions,
    load_current_standard_proficiency_policy,
    load_current_standard_proficiency_result,
    load_standard_proficiency_result_revision,
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
_MAX_ROSTER_STUDENTS = 4096


@dataclass(frozen=True, slots=True)
class RestartProficiencyInspection:
    """Live canonical result assessment; never inferred from the receipt alone."""

    status: str
    reason: str
    can_resume: bool


def load_fresh_restart_proficiency_authorization(
    root: Path,
    source: EvidenceSourceReference,
    diagnostics: DiagnosticsDependencies,
) -> AuthorizedProjectionSnapshot:
    """Reauthorize the original cached projection without new projection writes."""
    return load_fresh_restart_authorization(root, source, diagnostics)


class _RestartProficiencyPort:
    kind: ActionKind = "proficiency_result"

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
            raise TeacherActionConflictError("Wrong proficiency recovery family.")
        if (
            not preview.make_current
            or preview.reviewed_decision_sha256 != target.candidate_sha256
            or actor.source != "saved"
        ):
            raise TeacherActionConflictError("Result intent or saved actor differs.")
        if scope.workspace_sha256 != _identity("workspace", str(self.root)):
            raise TeacherActionConflictError("Result workspace changed.")
        if (
            scope.school_year is None
            or scope.academic_period_id is None
            or scope.calendar_sha256 is None
            or scope.work_identity_sha256 is None
        ):
            raise TeacherActionConflictError("Result academic scope incomplete.")
        if (
            len(preview.basis) != 2
            or preview.basis[0]
            != TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            )
            or preview.basis[1].role != "canonical_source"
            or preview.basis[1].identity_sha256 != target.identity_sha256
        ):
            raise TeacherActionConflictError("Result review bindings differ.")

    def _subject(self) -> tuple[str, str]:
        scope, target = self.preview.scope, self.preview.target
        roster = load_roster(class_roster_path(self.root, scope.class_id))
        if (
            roster.class_id != scope.class_id
            or len(roster.students) > _MAX_ROSTER_STUDENTS
        ):
            raise TeacherActionConflictError("Current class roster cannot be verified.")
        student_ids = {student.student_id for student in roster.students}
        identities = list_standard_proficiency_result_identities(
            self.root, scope.class_id, maximum_families=_MAX_IDENTITIES
        )
        if len(identities) > _MAX_IDENTITIES:
            raise TeacherActionConflictError("Result identity lookup exceeds bound.")
        matches = [
            (student, standard)
            for grade_item, student, standard in identities
            if grade_item == scope.grade_item_id
            and student in student_ids
            and _identity(
                "proficiency_result",
                scope.class_id,
                scope.grade_item_id,
                student,
                standard,
            )
            == target.identity_sha256
        ]
        if len(matches) != 1:
            raise TeacherActionConflictError(
                "Saved result student/Standard is not uniquely identifiable."
            )
        return matches[0]

    def _validated(self, preview: TeacherActionPreview) -> tuple[str, str]:
        if preview != self.preview:
            raise TeacherActionConflictError("Recovery result intent changed.")
        self._check_envelope()
        self.actor_checker(preview.actor)
        scope, target = preview.scope, preview.target
        student, standard = self._subject()
        history = list_standard_proficiency_result_revisions(
            self.root, scope.class_id, scope.grade_item_id, student, standard
        )
        if history != tuple(range(1, target.revision + 1)):
            raise TeacherActionConflictError("Result revision history changed.")
        stored = load_standard_proficiency_result_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            student,
            standard,
            target.revision,
        )
        snapshot = stored.snapshot
        if (
            stored.result_sha256 != target.candidate_sha256
            or snapshot.class_id != scope.class_id
            or snapshot.grade_item_id != scope.grade_item_id
            or snapshot.student_id != student
            or snapshot.standard_id != standard
            or snapshot.result_revision != target.revision
        ):
            raise TeacherActionConflictError("Persisted proficiency target differs.")
        # Only the originally supported single-source guided form can be rebuilt.
        # A saved result with no source, several entries or a required explicit
        # attempt object cannot be reconstructed with sufficient authority.
        if len(snapshot.inputs.entries) != 1:
            raise TeacherActionConflictError(
                "Result source context is not uniquely reconstructable."
            )
        entry = snapshot.inputs.entries[0]
        source = entry.source
        work = source.work
        if (
            _identity("work", scope.class_id, work.module_id, work.work_id)
            != scope.work_identity_sha256
        ):
            raise TeacherActionConflictError("Source work fingerprint changed.")
        membership = load_current_grade_item_membership_decision(
            self.root, scope.class_id, scope.grade_item_id, work
        )
        if membership is None or membership.decision.decision != "included":
            raise TeacherActionConflictError("Current included membership unavailable.")
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
            raise TeacherActionConflictError("Current academic period changed.")
        grade_item = load_current_grade_item_revision(
            self.root, scope.class_id, scope.grade_item_id
        )
        if (
            grade_item is None
            or grade_item.revision_sha256
            != snapshot.inputs.grade_item.grade_item_revision_sha256
            or grade_item.revision.grade_item_revision
            != snapshot.inputs.grade_item.grade_item_revision
            or membership.decision.grade_item_revision_sha256
            != grade_item.revision_sha256
        ):
            raise TeacherActionConflictError("Current Grade Item changed.")
        if (
            get_current_academic_work_registration_revision(self.root, work)
            != membership.decision.work_reference.registration_revision
        ):
            raise TeacherActionConflictError("Work registration changed.")
        validate_grade_item_membership_dependencies(self.root, membership.decision)
        policy = load_current_standard_proficiency_policy(
            self.root, scope.class_id, snapshot.policy_reference.policy_id
        )
        if policy is None or policy.reference != snapshot.policy_reference:
            raise TeacherActionConflictError("Calculation policy changed.")
        scale = load_current_proficiency_scale(
            self.root, scope.class_id, snapshot.target_scale.scale_id
        )
        if scale is None or scale.reference != snapshot.target_scale:
            raise TeacherActionConflictError("Current proficiency scale changed.")
        binding = _identity(
            "proficiency_source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            source.item_id,
            snapshot.inputs_sha256,
            snapshot.calculation_fingerprint,
            snapshot.policy_reference.policy_sha256,
            snapshot.target_scale.scale_sha256,
            membership.decision_sha256,
        )
        if preview.basis != (
            TeacherActionBasis(
                "actor_profile",
                _identity(preview.actor.actor_id),
                preview.actor.profile_sha256,
            ),
            TeacherActionBasis("canonical_source", target.identity_sha256, binding),
        ):
            raise TeacherActionConflictError("Proficiency source fingerprint differs.")
        authorized = self.authorized_loader(self.root, source)
        if not authorized.assessment.reusable_for_current_use:
            raise TeacherActionConflictError("Source is not current or authorized.")
        # Intentionally no guessed attempt selection. A decision depending on
        # a non-default attempt context must fail the exact-input comparison.
        reconstructed = build_bounded_calculation_preview(
            self.root,
            scope.grade_item_id,
            student,
            standard,
            snapshot.target_scale,
            (
                StandardAggregationCandidateBinding(
                    source, authorized, entry.mapping_profile_reference, None
                ),
            ),
            snapshot.policy_reference,
        )
        if (
            reconstructed.grade_item_basis != snapshot.inputs.grade_item
            or reconstructed.inputs != snapshot.inputs
            or reconstructed.calculation.outcome != snapshot.outcome
            or reconstructed.calculation.policy_reference != snapshot.policy_reference
        ):
            raise TeacherActionConflictError(
                "Current sources or pure proficiency calculation changed."
            )
        return student, standard

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._validated(preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        student, standard = self._validated(preview)
        scope, target = preview.scope, preview.target
        stored = load_standard_proficiency_result_revision(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            student,
            standard,
            target.revision,
        )
        current = load_current_standard_proficiency_result(
            self.root, scope.class_id, scope.grade_item_id, student, standard
        )
        return CanonicalActionObservation(
            target_sha256=stored.result_sha256,
            current_revision=(
                None if current is None else current.snapshot.result_revision
            ),
            current_sha256=None if current is None else current.result_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        raise TeacherActionConflictError(
            "Restart recovery cannot author another proficiency result."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        student, standard = self._validated(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Exact proficiency target differs.")
        scope, target = preview.scope, preview.target
        selected = preview_calculation_result_selection(
            self.root,
            scope.class_id,
            scope.grade_item_id,
            student,
            standard,
            target.revision,
        )
        if (
            selected.target_result_sha256 != target.candidate_sha256
            or selected.expected_current_result_revision
            != target.expected_current_revision
            or selected.history != tuple(range(1, target.revision + 1))
        ):
            raise TeacherActionConflictError("Proficiency selector baseline changed.")
        result = commit_calculation_result_selection_preview(
            self.root, selected, currentness_check=lambda: self._validated(preview)
        )
        if result.selected_result_sha256 != target.candidate_sha256:
            raise TeacherActionConflictError(
                "Proficiency selector returned wrong result."
            )
        value: str = result.selection_disposition
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        if value == "existing":
            return "existing"
        raise TeacherActionConflictError("Unknown proficiency selector disposition.")


def inspect_restart_proficiency(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> RestartProficiencyInspection:
    """Inspect exact saved result against live authorized canonical sources."""
    if root != store.root or receipt.preview.scope.class_id != store.class_id:
        raise TeacherActionConflictError("Workspace or class differs from receipt.")
    if store.load(receipt.action_id) != receipt:
        raise TeacherActionConflictError("Receipt changed after inbox review.")
    port = _RestartProficiencyPort(root, receipt, authorized_loader, actor_checker)
    port.revalidate_basis(receipt.preview)
    assessment = assess_teacher_action_recovery(store, receipt.preview, port.observe)
    can_resume = (
        assessment.can_resume_exact_selection
        and assessment.reason == "eligible_to_resume"
        and receipt.phase == "in_progress"
        and receipt.checkpoints[-1].stage != "receipt_finalized"
    )
    return RestartProficiencyInspection(
        assessment.status, assessment.reason, can_resume
    )


def resume_restart_proficiency(
    root: Path,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    *,
    confirmation: str,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker = _actor_now,
) -> TeacherActionResult:
    """Explicit RESUME is selection-only; academic authoring is disabled."""
    if confirmation != "RESUME":
        raise TeacherActionConflictError("Proficiency recovery was not confirmed.")
    inspection = inspect_restart_proficiency(
        root,
        store,
        receipt,
        authorized_loader=authorized_loader,
        actor_checker=actor_checker,
    )
    if not inspection.can_resume:
        raise TeacherActionConflictError("Proficiency result cannot be resumed.")
    port = _RestartProficiencyPort(root, receipt, authorized_loader, actor_checker)
    return resume_exact_teacher_selection(
        receipt.preview, port, store, confirmation="RESUME"
    )


__all__ = (
    "RestartProficiencyInspection",
    "inspect_restart_proficiency",
    "load_fresh_restart_proficiency_authorization",
    "resume_restart_proficiency",
)
