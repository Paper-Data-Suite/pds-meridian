"""#126-E2A: guarded process-restart continuation of exact written #31.

Only the original #122 action may resume exact #31 selection. This module
never writes an immutable #30 or #31 revision, manufactures a replacement
receipt, or treats journals as academic truth. Missing #31 writes require a
separate new reviewed action, not this recovery capability.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_pair_recovery import (
    DurablePairRecoveryAssessment,
    PairRecoveryPorts,
    _validate_binding,
    inspect_durable_pair_recovery,
)
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_resolution_coordinator import MultiAttemptPorts
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_action_contract import (
    ActionKind,
    TeacherActionActor,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
)
from meridian.teacher_action_guided import PreparedGuidedAction
from meridian.teacher_action_orchestration import (
    TeacherActionConflictError,
    TeacherActionDomainPort,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_reassessment import (
    ReassessmentActionOutcome,
    observe_reviewed_reassessment_action,
    prepare_reviewed_reassessment_action,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)


class AttemptPairRestartError(ValueError):
    """Exact original #31 receipt cannot safely be bound for restart."""

    code = "teacher_workflow.attempt_resolution.pair_restart_invalid"


RestartStatus: TypeAlias = Literal[
    "canceled_before_selection",
    "conflict_requires_review",
    "recovery_required",
    "written_not_current",
    "current_unverified",
    "pair_current_verified",
]


@dataclass(frozen=True, slots=True)
class PairRestartOutcome:
    """Never report a pair current from a receipt or action result alone."""

    status: RestartStatus
    exact_pair_current: bool
    continue_to_standards_review: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RestartPorts:
    """Explicit dependency seams; defaults use canonical #122 and #31."""

    inspector: Callable[..., DurablePairRecoveryAssessment] = (
        inspect_durable_pair_recovery
    )
    receipt_loader: Callable[[Path, str, str], TeacherActionReceipt | None] = (
        lambda root, class_id, action_id: TeacherActionReceiptStore(
            root, class_id
        ).load(action_id)
    )
    action_preparer: Callable[..., PreparedGuidedAction] = (
        prepare_reviewed_reassessment_action
    )
    resume_service: Callable[..., TeacherActionResult] = resume_exact_teacher_selection
    observer: Callable[..., ReassessmentActionOutcome] = (
        observe_reviewed_reassessment_action
    )


class _OriginalReceiptPort:
    """Forward one recovered preview to a freshly authorized canonical port.

    A newly prepared #31 port is bound to a *new* random action ID. Only after
    exact equality of every other immutable review field may the original
    receipt's action ID be presented to #122. This proxy NEVER authors.
    """

    kind: ActionKind = "reassessment_decision"

    def __init__(
        self, original: TeacherActionPreview, current: PreparedGuidedAction
    ) -> None:
        if (
            original.kind != self.kind
            or current.preview.kind != self.kind
            or replace(current.preview, action_id=original.action_id) != original
            or original.intent_sha256 != current.preview.intent_sha256
        ):
            raise AttemptPairRestartError(
                "Original action and freshly reviewed #31 authority differ."
            )
        self._original = original
        self._current = current

    def _verify(self, preview: TeacherActionPreview) -> None:
        if preview != self._original:
            raise TeacherActionConflictError("Original action token changed.")

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._verify(preview)
        self._current.port.revalidate_basis(self._current.preview)

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        self._verify(preview)
        return self._current.port.observe(self._current.preview)

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        self._verify(preview)
        raise TeacherActionConflictError(
            "Restart is selection-only: immutable authoring is prohibited."
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> Literal["not_attempted", "created", "updated", "existing", "unknown"]:
        self._verify(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Selected record is not exact target.")
        return self._current.port.select_exact(self._current.preview, record)


def _is_original_written(
    assessment: DurablePairRecoveryAssessment,
    receipt: TeacherActionReceipt,
    actor: TeacherActionActor,
    review: ProspectiveReassessmentReview,
) -> bool:
    witness = assessment.reassessment_receipt
    preview = receipt.preview
    return (
        assessment.status == "reassessment_written_not_current"
        and assessment.exact_upstream_current
        and not assessment.exact_reassessment_current
        and assessment.upstream_receipt.status not in ("ambiguous", "unverifiable")
        and witness.status == "in_progress"
        and witness.action_id == receipt.action_id
        and preview.kind == "reassessment_decision"
        and preview.actor == actor
        and preview.make_current
        and preview.target.revision == review.decision.decision_revision
        and preview.target.candidate_sha256 == review.reassessment_decision_sha256
        and preview.target.expected_current_revision
        == review.expected_current_reassessment[0]
        and preview.target.expected_current_sha256
        == review.expected_current_reassessment[1]
        and receipt.phase == "in_progress"
        and "write" in witness.checkpoint_stages
        and any(
            point.stage == "write" and point.disposition == "completed"
            for point in receipt.checkpoints
        )
        and any(
            record.matches_target(preview.target) for record in receipt.observed_records
        )
        and all(
            record.matches_target(preview.target) for record in receipt.observed_records
        )
    )


@dataclass(slots=True)
class PreparedPairRestart:
    """One-use reviewed restart capability bound to original receipt bytes."""

    root: Path = field(repr=False)
    prepared: GuidedProjectionResult = field(repr=False)
    authoring: AttemptDecisionAuthoringPreview = field(repr=False)
    review: ProspectiveReassessmentReview = field(repr=False)
    actor: TeacherActionActor = field(repr=False)
    original_receipt: TeacherActionReceipt = field(repr=False)
    ports: RestartPorts = field(repr=False)
    canonical_ports: MultiAttemptPorts | None = field(repr=False)
    pair_ports: PairRecoveryPorts | None = field(repr=False)
    attempted: bool = field(default=False, init=False, repr=False)

    def resume(self, *, confirmed: bool) -> PairRestartOutcome:
        """Never retry automatically, nor issue a new action ID or write #31."""
        if self.attempted:
            return PairRestartOutcome(
                "recovery_required", False, False, "restart_already_attempted"
            )
        self.attempted = True
        if not confirmed:
            return PairRestartOutcome("canceled_before_selection", False, False)
        try:
            assessment = self.ports.inspector(
                self.root,
                prepared=self.prepared,
                authoring=self.authoring,
                review=self.review,
                canonical_ports=self.canonical_ports,
                ports=self.pair_ports,
            )
            fresh_receipt = self.ports.receipt_loader(
                self.root,
                self.authoring.candidate.class_id,
                self.original_receipt.action_id,
            )
        except Exception:
            return PairRestartOutcome(
                "current_unverified", False, False, "restart_read_failed"
            )
        if (
            not isinstance(assessment, DurablePairRecoveryAssessment)
            or not isinstance(fresh_receipt, TeacherActionReceipt)
            or fresh_receipt != self.original_receipt
            or not _is_original_written(
                assessment, fresh_receipt, self.actor, self.review
            )
        ):
            return PairRestartOutcome(
                "conflict_requires_review", False, False, "restart_basis_changed"
            )
        try:
            fresh_action = self.ports.action_preparer(
                self.root,
                prepared=self.prepared,
                review=self.review,
                actor=self.actor,
            )
            if not isinstance(fresh_action, PreparedGuidedAction):
                raise AttemptPairRestartError("Canonical #31 action is unavailable.")
            port: TeacherActionDomainPort = _OriginalReceiptPort(
                self.original_receipt.preview, fresh_action
            )
        except Exception:
            return PairRestartOutcome(
                "conflict_requires_review", False, False, "fresh_authority_changed"
            )
        try:
            result = self.ports.resume_service(
                self.original_receipt.preview,
                port,
                fresh_action.store,
                confirmation="RESUME",
            )
        except Exception:
            return PairRestartOutcome(
                "recovery_required", False, False, "selection_outcome_unknown"
            )
        if not isinstance(result, TeacherActionResult):
            return PairRestartOutcome(
                "current_unverified", False, False, "invalid_122_result"
            )
        if result.status not in ("applied", "already_applied"):
            label: RestartStatus = (
                "written_not_current"
                if result.status == "written_not_current"
                else "conflict_requires_review"
                if result.status == "conflict_requires_review"
                else "recovery_required"
            )
            return PairRestartOutcome(
                label, False, False, result.reason_code or "not_selected"
            )
        if (
            result.current_state != "matches"
            or result.current_record is None
            or not result.current_record.matches_target(
                self.original_receipt.preview.target
            )
        ):
            return PairRestartOutcome(
                "current_unverified", False, False, "122_target_not_verified"
            )
        try:
            observed = self.ports.observer(
                self.root,
                prepared=self.prepared,
                review=self.review,
                result=result,
            )
            after = self.ports.inspector(
                self.root,
                prepared=self.prepared,
                authoring=self.authoring,
                review=self.review,
                canonical_ports=self.canonical_ports,
                ports=self.pair_ports,
            )
        except Exception:
            return PairRestartOutcome(
                "current_unverified", False, False, "postresume_read_failed"
            )
        if (
            not isinstance(observed, ReassessmentActionOutcome)
            or not observed.exact_current
            or observed.status not in ("applied_current", "already_current")
            or not isinstance(after, DurablePairRecoveryAssessment)
            or not after.may_continue_to_standards
        ):
            return PairRestartOutcome(
                "current_unverified", False, False, "pair_postcondition_unverified"
            )
        return PairRestartOutcome("pair_current_verified", True, True)


def prepare_exact_pair_restart(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
    canonical_ports: MultiAttemptPorts | None = None,
    pair_ports: PairRecoveryPorts | None = None,
    ports: RestartPorts | None = None,
) -> PreparedPairRestart:
    """Read-only preparation. The original #31 receipt must prove a write."""
    _validate_binding(root, authoring, review)
    if not isinstance(actor, TeacherActionActor) or (
        authoring.candidate.actor.actor_id != actor.actor_id
        or review.decision.actor.actor_id != actor.actor_id
    ):
        raise AttemptPairRestartError("Teacher attribution differs from review.")
    service = RestartPorts() if ports is None else ports
    try:
        assessment = service.inspector(
            root,
            prepared=prepared,
            authoring=authoring,
            review=review,
            canonical_ports=canonical_ports,
            ports=pair_ports,
        )
        if (
            not isinstance(assessment, DurablePairRecoveryAssessment)
            or assessment.status != "reassessment_written_not_current"
            or assessment.reassessment_receipt.action_id is None
        ):
            raise AttemptPairRestartError(
                "No exact written-but-not-current #31 receipt is recoverable."
            )
        original = service.receipt_loader(
            root,
            authoring.candidate.class_id,
            assessment.reassessment_receipt.action_id,
        )
        if not isinstance(original, TeacherActionReceipt) or not _is_original_written(
            assessment, original, actor, review
        ):
            raise AttemptPairRestartError(
                "Original #31 write or attribution cannot be verified."
            )
    except AttemptPairRestartError:
        raise
    except Exception as error:
        raise AttemptPairRestartError(
            "Durable #31 state cannot be reconciled; no restart authorized."
        ) from error
    return PreparedPairRestart(
        root,
        prepared,
        authoring,
        review,
        actor,
        original,
        service,
        canonical_ports,
        pair_ports,
    )


def render_exact_pair_restart(value: PreparedPairRestart) -> str:
    """Screen-safe teacher review, no student IDs or action-token exposure."""
    if not isinstance(value, PreparedPairRestart):
        raise TypeError("Expected typed exact selection restart.")
    return "\n".join(
        (
            "Meridian — Resume Written Reassessment (NOT YET SELECTED)",
            "#30 exact reviewed decision: independently current",
            "#31 exact immutable decision: written but not current",
            "Continue will resume ONLY the original #31 CAS selection.",
            "No #30/#31 immutable write, new receipt, grade or publish action.",
            "Cancel makes no academic change.",
            "If source, actor, policy, CAS or receipt changes, recovery stops.",
        )
    )


__all__ = (
    "AttemptPairRestartError",
    "PairRestartOutcome",
    "PreparedPairRestart",
    "RestartPorts",
    "prepare_exact_pair_restart",
    "render_exact_pair_restart",
)
