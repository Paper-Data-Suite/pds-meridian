"""#126-E2B: explicit new #31 continuation when original #30 is current.

A restart with no #31 history or receipt NEVER implies that the old action may
be replayed. This module requires a fresh #31-only reviewed action and teacher
confirmation. It never authors #30, silently infers a reassessment relationship,
or reuses an uncertain #31 action. All academic writes delegate to existing #122.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.attempt_correction_interpretation import AttemptInterpretationPreview
from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_pair_recovery import (
    DurablePairRecoveryAssessment,
    PairRecoveryPorts,
    _validate_binding,
    inspect_durable_pair_recovery,
)
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_resolution_coordinator import (
    MultiAttemptPorts,
    _aligned,
    _intention_current,
    _reviewed_policy_current,
    _upstream_exact,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionResult,
)
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_reassessment import (
    ReassessmentActionOutcome,
    observe_reviewed_reassessment_action,
    prepare_reviewed_reassessment_action,
)
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)


class AttemptPairNewContinuationError(ValueError):
    """Canonical and journal witnesses cannot authorize one new #31 decision."""

    code = "teacher_workflow.attempt_resolution.new_31_continuation_invalid"


NewContinuationStatus: TypeAlias = Literal[
    "canceled_before_write",
    "blocked_before_write",
    "conflict_requires_review",
    "written_not_current",
    "current_unverified",
    "recovery_required",
    "pair_current_verified",
]


@dataclass(frozen=True, slots=True)
class NewContinuationOutcome:
    """A verified pair needs both authoritative current records, not a receipt."""

    status: NewContinuationStatus
    exact_pair_current: bool
    continue_to_standards_review: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NewContinuationPorts:
    """Narrow test seams; production delegates to #122, E1 and #31 services."""

    inspector: Callable[..., DurablePairRecoveryAssessment] = (
        inspect_durable_pair_recovery
    )
    receipt_reader: Callable[[Path, str], tuple[TeacherActionReceipt, ...]] = (
        lambda root, class_id: TeacherActionReceiptStore(root, class_id).list_receipts()
    )
    action_preparer: Callable[..., PreparedGuidedAction] = (
        prepare_reviewed_reassessment_action
    )
    observer: Callable[..., ReassessmentActionOutcome] = (
        observe_reviewed_reassessment_action
    )


def _recheck(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
    canonical_ports: MultiAttemptPorts | None,
    pair_ports: PairRecoveryPorts | None,
    ports: NewContinuationPorts,
) -> DurablePairRecoveryAssessment:
    """Read all current authority and the entire class receipt inventory.

    A different #31 intent for this same student may have a pending journal but
    a different candidate hash, so an exact-digest E1 witness alone is not enough
    to authorize a NEW action. Do not manufacture negative evidence from absent
    or unreadable history. Canonical CAS is still revalidated by #122 at write.
    """
    _validate_binding(root, authoring, review)
    if not isinstance(actor, TeacherActionActor):
        raise AttemptPairNewContinuationError("Verified teacher attribution required.")
    _aligned(interpretation, authoring, review, actor)
    domain = canonical_ports if canonical_ports is not None else MultiAttemptPorts()
    if not _intention_current(root, prepared, interpretation, domain):
        raise AttemptPairNewContinuationError(
            "The original teacher-reviewed source or eligibility has changed."
        )
    if not _upstream_exact(root, prepared, authoring, domain):
        raise AttemptPairNewContinuationError(
            "Original #30 decision is no longer operative exact current."
        )
    _reviewed_policy_current(root, review, domain)
    assessment = ports.inspector(
        root,
        prepared=prepared,
        authoring=authoring,
        review=review,
        canonical_ports=canonical_ports,
        ports=pair_ports,
    )
    if not isinstance(assessment, DurablePairRecoveryAssessment) or (
        assessment.status != "upstream_current_reassessment_missing"
        or not assessment.exact_upstream_current
        or assessment.exact_reassessment_current
        or assessment.upstream_receipt.status != "in_progress"
        or assessment.upstream_receipt.action_id is None
        or assessment.reassessment_receipt.status != "missing"
    ):
        raise AttemptPairNewContinuationError(
            "Only verified #30 current and definitely no #31 target/receipt "
            "may enter a fresh #31 review."
        )
    first, second = authoring.candidate, review.decision
    receipts = ports.receipt_reader(root, first.class_id)
    if not isinstance(receipts, tuple) or any(
        not isinstance(item, TeacherActionReceipt) for item in receipts
    ):
        raise AttemptPairNewContinuationError(
            "A complete validated class-scoped journal inventory is required."
        )
    first_identity = _identity(
        "attempt_decision",
        first.class_id,
        first.grade_item_id,
        first.work.module_id,
        first.work.work_id,
        first.student_id,
    )
    second_identity = _identity(
        "reassessment_decision",
        second.class_id,
        second.grade_item_id,
        second.work.module_id,
        second.work.work_id,
        second.student_id,
    )
    upstream = tuple(
        item
        for item in receipts
        if item.action_id == assessment.upstream_receipt.action_id
    )
    if len(upstream) != 1:
        raise AttemptPairNewContinuationError(
            "Original #30 receipt disappeared or is duplicated."
        )
    witness = upstream[0]
    if (
        witness.preview.kind != "attempt_decision"
        or witness.preview.actor != actor
        or witness.preview.target.identity_sha256 != first_identity
        or witness.preview.target.candidate_sha256 != review.upstream_decision_sha256
        or witness.preview.target.revision != first.decision_revision
        or witness.phase != "in_progress"
        or not any(
            check.stage == "write" and check.disposition == "completed"
            for check in witness.checkpoints
        )
        or not witness.observed_records
        or any(
            not record.matches_target(witness.preview.target)
            for record in witness.observed_records
        )
    ):
        raise AttemptPairNewContinuationError(
            "Original #30 write/teacher receipt cannot be independently bound."
        )
    for receipt in receipts:
        preview = receipt.preview
        if (
            preview.kind == "reassessment_decision"
            and preview.target.identity_sha256 == second_identity
        ):
            raise AttemptPairNewContinuationError(
                "A #31 action for this student already has a receipt; "
                "reconcile it instead of creating a different action."
            )
    return assessment


def _check_new_action(
    action: PreparedGuidedAction,
    *,
    root: Path,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
) -> None:
    """Validate that the fresh #122 action can only address reviewed #31."""
    decision = review.decision
    preview = action.preview
    identity = _identity(
        "reassessment_decision",
        decision.class_id,
        decision.grade_item_id,
        decision.work.module_id,
        decision.work.work_id,
        decision.student_id,
    )
    source = _identity(
        "reassessment_source",
        review.upstream_decision_sha256,
        review.policy_sha256,
        decision.work.module_id,
        decision.work.work_id,
    )
    basis = {entry.role: entry for entry in preview.basis}
    if (
        preview.kind != "reassessment_decision"
        or preview.actor != actor
        or preview.scope.class_id != decision.class_id
        or preview.scope.grade_item_id != decision.grade_item_id
        or preview.scope.workspace_sha256 != _identity("workspace", str(root))
        or preview.scope.work_identity_sha256
        != _identity(
            "work",
            decision.class_id,
            decision.work.module_id,
            decision.work.work_id,
        )
        or preview.target.family != "reassessment_decision"
        or preview.target.identity_sha256 != identity
        or preview.target.candidate_sha256 != review.reassessment_decision_sha256
        or preview.reviewed_decision_sha256 != review.reassessment_decision_sha256
        or preview.target.revision != decision.decision_revision
        or (
            preview.target.expected_current_revision,
            preview.target.expected_current_sha256,
        )
        != review.expected_current_reassessment
        or not preview.make_current
        or "canonical_source" not in basis
        or basis["canonical_source"].identity_sha256 != identity
        or basis["canonical_source"].content_sha256 != source
        or "actor_profile" not in basis
        or basis["actor_profile"].identity_sha256 != _identity(actor.actor_id)
        or basis["actor_profile"].content_sha256 != actor.profile_sha256
    ):
        raise AttemptPairNewContinuationError(
            "Fresh #122 action does not match the exact new #31 review."
        )


@dataclass(slots=True)
class PreparedNewPairContinuation:
    """One-use confirmed #31-only action after fresh #30/#31/journal rereview."""

    root: Path = field(repr=False)
    prepared: GuidedProjectionResult = field(repr=False)
    interpretation: AttemptInterpretationPreview = field(repr=False)
    authoring: AttemptDecisionAuthoringPreview = field(repr=False)
    review: ProspectiveReassessmentReview = field(repr=False)
    actor: TeacherActionActor = field(repr=False)
    action: PreparedGuidedAction = field(repr=False)
    canonical_ports: MultiAttemptPorts | None = field(repr=False)
    pair_ports: PairRecoveryPorts | None = field(repr=False)
    ports: NewContinuationPorts = field(repr=False)
    attempted: bool = field(default=False, init=False, repr=False)

    def apply(self, *, confirmed: bool) -> NewContinuationOutcome:
        """Never touch #30 writer; uncertain first #31 action cannot be retried."""
        if self.attempted:
            return NewContinuationOutcome(
                "recovery_required", False, False, "new_31_already_attempted"
            )
        self.attempted = True
        if not confirmed:
            return NewContinuationOutcome("canceled_before_write", False, False)
        try:
            _recheck(
                self.root,
                prepared=self.prepared,
                interpretation=self.interpretation,
                authoring=self.authoring,
                review=self.review,
                actor=self.actor,
                canonical_ports=self.canonical_ports,
                pair_ports=self.pair_ports,
                ports=self.ports,
            )
            _check_new_action(
                self.action,
                root=self.root,
                review=self.review,
                actor=self.actor,
            )
        except Exception:
            return NewContinuationOutcome(
                "conflict_requires_review", False, False, "new_31_precommit_drift"
            )
        try:
            result = self.action.apply(confirmed=True)
        except Exception:
            # The canonical writer MAY have already created the target revision.
            return NewContinuationOutcome(
                "recovery_required", False, False, "new_31_outcome_unknown"
            )
        if not isinstance(result, TeacherActionResult) or (
            result.action_id != self.action.preview.action_id
            or result.intent_sha256 != self.action.preview.intent_sha256
        ):
            return NewContinuationOutcome(
                "current_unverified", False, False, "invalid_122_action_result"
            )
        if result.status not in ("applied", "already_applied"):
            kind: NewContinuationStatus
            if result.status == "written_not_current":
                kind = "written_not_current"
            elif result.status == "conflict_requires_review":
                kind = "conflict_requires_review"
            elif result.status == "blocked_before_write":
                kind = "blocked_before_write"
            elif result.status == "current_unverified":
                kind = "current_unverified"
            else:
                kind = "recovery_required"
            return NewContinuationOutcome(
                kind, False, False, result.reason_code or "31_action_not_verified"
            )
        if (
            result.current_state != "matches"
            or result.current_record is None
            or not result.current_record.matches_target(self.action.preview.target)
        ):
            return NewContinuationOutcome(
                "current_unverified", False, False, "122_31_target_not_verified"
            )
        try:
            observed = self.ports.observer(
                self.root,
                prepared=self.prepared,
                review=self.review,
                result=result,
            )
            final = self.ports.inspector(
                self.root,
                prepared=self.prepared,
                authoring=self.authoring,
                review=self.review,
                canonical_ports=self.canonical_ports,
                ports=self.pair_ports,
            )
        except Exception:
            return NewContinuationOutcome(
                "current_unverified", False, False, "pair_readback_unavailable"
            )
        if (
            not isinstance(observed, ReassessmentActionOutcome)
            or not observed.exact_current
            or observed.status not in ("applied_current", "already_current")
            or not isinstance(final, DurablePairRecoveryAssessment)
            or not final.may_continue_to_standards
        ):
            return NewContinuationOutcome(
                "current_unverified", False, False, "pair_not_canonically_verified"
            )
        return NewContinuationOutcome("pair_current_verified", True, True)


def prepare_new_pair_continuation(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
    canonical_ports: MultiAttemptPorts | None = None,
    pair_ports: PairRecoveryPorts | None = None,
    ports: NewContinuationPorts | None = None,
) -> PreparedNewPairContinuation:
    """Read-only preparation; a NEW #31 action requires separate confirmation."""
    _validate_binding(root, authoring, review)
    services = NewContinuationPorts() if ports is None else ports
    try:
        _recheck(
            root,
            prepared=prepared,
            interpretation=interpretation,
            authoring=authoring,
            review=review,
            actor=actor,
            canonical_ports=canonical_ports,
            pair_ports=pair_ports,
            ports=services,
        )
        action = services.action_preparer(
            root,
            prepared=prepared,
            review=review,
            actor=actor,
        )
        _check_new_action(action, root=root, review=review, actor=actor)
    except Exception as error:
        raise AttemptPairNewContinuationError(
            "No safe newly reviewed #31 action can be prepared."
        ) from error
    return PreparedNewPairContinuation(
        root,
        prepared,
        interpretation,
        authoring,
        review,
        actor,
        action,
        canonical_ports,
        pair_ports,
        services,
    )


def render_new_pair_continuation(value: PreparedNewPairContinuation) -> str:
    """Teacher review text: no raw student ID, class hash or receipt token."""
    if not isinstance(value, PreparedNewPairContinuation):
        raise TypeError("Expected typed new #31 continuation review.")
    return "\n".join(
        (
            "Meridian — Continue Multi-Attempt Review (NOT SAVED)",
            "#30: exact prior teacher decision is already current and verified.",
            f"#31 mode: {value.review.decision.mode} (explicit teacher relationship)",
            "#31: no matching history revision or action receipt exists.",
            "One NEW confirmed #31 action will write and select the reviewed record.",
            "No #30 authoring, automatic retry, Grade, Standards, or publishing.",
            "Cancel makes no academic change; failed writes require recovery.",
            "An unverifiable or competing student action blocks continuation.",
        )
    )


__all__ = (
    "AttemptPairNewContinuationError",
    "NewContinuationOutcome",
    "NewContinuationPorts",
    "PreparedNewPairContinuation",
    "prepare_new_pair_continuation",
    "render_new_pair_continuation",
)
