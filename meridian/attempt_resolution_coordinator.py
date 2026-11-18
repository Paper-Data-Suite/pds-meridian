"""#126-D2B2: non-atomic, explicitly reviewed #30 -> #31 coordinator.

No new academic writer, pointer, or receipt. Canonical #30 and #31 author/
select/journal services remain independent. A partially completed pair is never
reported as a completed academic resolution, and a repeated call never rewrites
#30. Cross-process recovery is observation-only until Slice E qualifies it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    project_assessment_attempt_inventory,
)
from meridian.attempt_correction_interpretation import (
    AttemptInterpretationPreview,
    preview_attempt_interpretation,
)
from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_decisions_workflow import (
    AttemptDecisionWorkflowProjection,
    project_attempt_decisions,
)
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_selection import attempt_selection_decision_to_json_bytes
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPlan,
    GuidedAttemptPolicyPreset,
    plan_guided_attempt_policy,
    preview_guided_attempt_decision,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.reassessment import reassessment_decision_to_json_bytes
from meridian.reassessment_storage import (
    ReassessmentResolution,
    StoredReassessmentDecision,
    StoredReassessmentPolicy,
    list_reassessment_decision_revisions,
    load_current_reassessment_decision,
    load_current_reassessment_policy,
    load_reassessment_decision_revision,
    resolve_current_reassessment,
)
from meridian.teacher_action_attempt_standards import prepare_attempt_decision_action
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction
from meridian.teacher_action_reassessment import (
    ReassessmentActionOutcome,
    observe_reviewed_reassessment_action,
    prepare_reviewed_reassessment_action,
)


class MultiAttemptResolutionError(ValueError):
    """Cannot safely bind a pair of teacher-reviewed canonical decisions."""

    code = "teacher_workflow.attempt_resolution.multi_attempt_invalid"


PairStatus: TypeAlias = Literal[
    "canceled_before_write",
    "conflict_requires_review",
    "upstream_not_current",
    "upstream_current_reassessment_incomplete",
    "reassessment_written_not_current",
    "current_unverified",
    "recovery_required",
    "applied_current",
    "already_current",
]

RecoveryStatus: TypeAlias = Literal[
    "upstream_not_current",
    "upstream_current_reassessment_missing",
    "reassessment_written_not_current",
    "current_unverified",
    "conflict_requires_review",
    "pair_current",
]


@dataclass(frozen=True, slots=True)
class MultiAttemptOutcome:
    status: PairStatus
    upstream_action_status: str | None
    reassessment_action_status: str | None
    exact_pair_current: bool
    continue_to_standards_review: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MultiAttemptRecoveryAssessment:
    """Read-only independent canonical witnesses; not a replay authorization."""

    status: RecoveryStatus
    exact_upstream_current: bool
    exact_reassessment_current: bool
    reason: str | None = None

    @property
    def can_replay_automatically(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class MultiAttemptPorts:
    """Production defaults are canonical readers/writers, not a second store."""

    inventory_loader: Callable[..., AssessmentAttemptInventory] = (
        project_assessment_attempt_inventory
    )
    policy_planner: Callable[..., GuidedAttemptPolicyPlan] = plan_guided_attempt_policy
    authoring_previewer: Callable[..., AttemptDecisionAuthoringPreview] = (
        preview_guided_attempt_decision
    )
    upstream_action_preparer: Callable[..., PreparedGuidedAction] = (
        prepare_attempt_decision_action
    )
    upstream_loader: Callable[..., AttemptDecisionWorkflowProjection] = (
        project_attempt_decisions
    )
    reassessment_policy_loader: Callable[..., StoredReassessmentPolicy | None] = (
        load_current_reassessment_policy
    )
    reassessment_history_loader: Callable[..., tuple[int, ...]] = (
        list_reassessment_decision_revisions
    )
    reassessment_current_loader: Callable[..., StoredReassessmentDecision | None] = (
        load_current_reassessment_decision
    )
    reassessment_target_loader: Callable[..., StoredReassessmentDecision] = (
        load_reassessment_decision_revision
    )
    reassessment_action_preparer: Callable[..., PreparedGuidedAction] = (
        prepare_reviewed_reassessment_action
    )
    reassessment_observer: Callable[..., ReassessmentActionOutcome] = (
        observe_reviewed_reassessment_action
    )
    reassessment_loader: Callable[..., ReassessmentResolution] = (
        resolve_current_reassessment
    )


def _decision_digest(authoring: AttemptDecisionAuthoringPreview) -> str:
    return hashlib.sha256(
        attempt_selection_decision_to_json_bytes(authoring.candidate)
    ).hexdigest()


def _intention_current(
    root: Path,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    ports: MultiAttemptPorts,
) -> bool:
    inventory = ports.inventory_loader(
        root, grade_item_id=interpretation.grade_item_id, prepared=prepared
    )
    again = preview_attempt_interpretation(
        inventory,
        student_id=interpretation.student_id,
        treatment=interpretation.treatment,
        selected_attempts=interpretation.intended_selected_attempts,
        original_attempt=interpretation.original_attempt,
        teacher_rationale=interpretation.teacher_rationale,
    )
    return again == interpretation


def _reviewed_policy_current(
    root: Path,
    review: ProspectiveReassessmentReview,
    ports: MultiAttemptPorts,
    *,
    allow_target_history: bool = False,
) -> None:
    """Check #31 independent witness; forbid creating policy/relationship silently."""
    decision = review.decision
    policy = ports.reassessment_policy_loader(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.policy.policy_id,
    )
    if (
        policy is None
        or policy.policy_sha256 != review.policy_sha256
        or policy.policy_sha256 != decision.policy.policy_revision_sha256
        or policy.policy.policy_revision != decision.policy.policy_revision
        or decision.mode not in policy.policy.allowed_modes
    ):
        raise MultiAttemptResolutionError(
            "Exact independently selected #31 policy changed."
        )
    history = ports.reassessment_history_loader(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
    )
    accepted: tuple[tuple[int, ...], ...] = (review.history_before,)
    if allow_target_history:
        accepted += ((*review.history_before, decision.decision_revision),)
    if history not in accepted:
        raise MultiAttemptResolutionError("#31 revision history changed.")
    if allow_target_history and history != review.history_before:
        target = ports.reassessment_target_loader(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
            decision.decision_revision,
        )
        if (
            target.decision_sha256 != review.reassessment_decision_sha256
            or target.decision != decision
        ):
            raise MultiAttemptResolutionError(
                "#31 immutable target differs from review."
            )
    current = ports.reassessment_current_loader(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
    )
    pointer = (
        (None, None)
        if current is None
        else (current.decision.decision_revision, current.decision_sha256)
    )
    accepted_pointer: tuple[tuple[int | None, str | None], ...] = (
        review.expected_current_reassessment,
    )
    if allow_target_history:
        accepted_pointer += (
            (decision.decision_revision, review.reassessment_decision_sha256),
        )
    if pointer not in accepted_pointer:
        raise MultiAttemptResolutionError("#31 current pointer changed.")
    if history != review.history_before and not allow_target_history:
        raise MultiAttemptResolutionError(
            "#31 target already persisted; recovery needed."
        )


def _upstream_exact(
    root: Path,
    prepared: GuidedProjectionResult,
    authoring: AttemptDecisionAuthoringPreview,
    ports: MultiAttemptPorts,
) -> bool:
    candidate = authoring.candidate
    result = ports.upstream_loader(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.student_id,
        authorized_snapshot=prepared.authorized,
    )
    return (
        result.status == "selected"
        and result.operative_selection
        and result.resolution_status == "selected"
        and result.source_snapshot == candidate.source_snapshot
        and result.selected_decision_revision == candidate.decision_revision
        and result.selected_decision_sha256 == _decision_digest(authoring)
        and result.reviewed_selected_attempts == candidate.selected_attempts
    )


def _reassessment_exact(
    root: Path,
    prepared: GuidedProjectionResult,
    review: ProspectiveReassessmentReview,
    ports: MultiAttemptPorts,
) -> bool:
    decision = review.decision
    result = ports.reassessment_loader(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
        authorized_snapshot=prepared.authorized,
    )
    return (
        result.status == "resolved"
        and result.operative_reassessment
        and result.selected is not None
        and result.selected.decision.decision_revision == decision.decision_revision
        and result.selected.decision_sha256 == review.reassessment_decision_sha256
        and result.selected.decision.attempt_selection == decision.attempt_selection
        and result.contributing_attempts == decision.contributing_attempts
        and result.replacement_relationships == decision.replacement_relationships
        and result.combinations == decision.combinations
        and result.recency_order == decision.recency_order
    )


def _aligned(
    interpretation: AttemptInterpretationPreview,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
) -> None:
    candidate, second = authoring.candidate, review.decision
    if (
        interpretation.treatment != "teacher_reviewed_reassessment"
        or not interpretation.needs_reassessment_decision
        or len(interpretation.intended_selected_attempts) < 2
        or candidate.class_id != interpretation.class_id
        or candidate.grade_item_id != interpretation.grade_item_id
        or candidate.student_id != interpretation.student_id
        or candidate.source_snapshot != interpretation.source_snapshot
        or candidate.selected_attempts != interpretation.intended_selected_attempts
        or candidate.rationale != interpretation.suggested_canonical_rationale
        or candidate.actor.kind != "teacher"
        or candidate.actor.actor_id != actor.actor_id
        or authoring.reviewed_current_decision_revision
        != interpretation.selected_revision_at_preview
        or second.class_id != candidate.class_id
        or second.grade_item_id != candidate.grade_item_id
        or second.work != candidate.work
        or second.student_id != candidate.student_id
        or second.actor.kind != "teacher"
        or second.actor.actor_id != actor.actor_id
        or second.rationale != interpretation.suggested_canonical_rationale
        or review.teacher_treatment != interpretation.treatment
        or review.upstream_decision_sha256 != _decision_digest(authoring)
        or second.attempt_selection.decision_revision != candidate.decision_revision
        or second.attempt_selection.decision_sha256 != review.upstream_decision_sha256
        or second.policy.policy_revision_sha256 != review.policy_sha256
        or hashlib.sha256(reassessment_decision_to_json_bytes(second)).hexdigest()
        != review.reassessment_decision_sha256
    ):
        raise MultiAttemptResolutionError(
            "#30, #31, actor and exact teacher review are not the same intent."
        )


@dataclass(slots=True)
class _RunState:
    """One-process duplicate-write guard; not durable recovery authority."""

    started: bool = False
    upstream_verified: bool = False
    upstream_status: str | None = None
    reassessment_action: PreparedGuidedAction | None = None
    reassessment_attempted: bool = False


@dataclass(frozen=True, slots=True)
class PreparedMultiAttemptResolution:
    """Two independent #122 actions: the first must be current before the second."""

    root: Path = field(repr=False)
    prepared: GuidedProjectionResult = field(repr=False)
    interpretation: AttemptInterpretationPreview
    authoring: AttemptDecisionAuthoringPreview = field(repr=False)
    review: ProspectiveReassessmentReview = field(repr=False)
    actor: TeacherActionActor = field(repr=False)
    upstream_action: PreparedGuidedAction = field(repr=False)
    ports: MultiAttemptPorts = field(repr=False)
    _state: _RunState = field(default_factory=_RunState, repr=False, compare=False)

    def apply(self, *, confirmed: bool) -> MultiAttemptOutcome:
        """One confirmation; verify canonical #30 before any #31 write."""
        if self._state.started:
            return self._outcome("recovery_required", "already_attempted_use_recovery")
        self._state.started = True
        if not confirmed:
            try:
                canceled = self.upstream_action.apply(confirmed=False)
                if canceled.status != "blocked_before_write":
                    raise MultiAttemptResolutionError("Unexpected cancellation state.")
            except Exception:
                return self._outcome("recovery_required", "cancel_unverifiable")
            return self._outcome("canceled_before_write")
        try:
            if not _intention_current(
                self.root, self.prepared, self.interpretation, self.ports
            ):
                raise MultiAttemptResolutionError(
                    "Source or teacher intention changed."
                )
            _reviewed_policy_current(self.root, self.review, self.ports)
            _aligned(self.interpretation, self.authoring, self.review, self.actor)
        except Exception:
            return self._outcome("conflict_requires_review", "precommit_basis_changed")
        try:
            result = self.upstream_action.apply(confirmed=True)
        except Exception:
            return self._outcome("recovery_required", "upstream_write_outcome_unknown")
        self._state.upstream_status = result.status
        if result.status not in ("applied", "already_applied"):
            if result.status == "conflict_requires_review":
                status: PairStatus = "conflict_requires_review"
            elif result.status == "written_not_current":
                status = "upstream_not_current"
            else:
                status = "recovery_required"
            return self._outcome(status, result.reason_code or "upstream_not_verified")
        target = self.upstream_action.preview.target
        if (
            result.current_state != "matches"
            or result.current_record is None
            or not result.current_record.matches_target(target)
        ):
            return self._outcome("current_unverified", "upstream_122_readback_failed")
        try:
            exact = _upstream_exact(
                self.root, self.prepared, self.authoring, self.ports
            )
        except Exception:
            return self._outcome("current_unverified", "upstream_canonical_read_failed")
        if not exact:
            return self._outcome("current_unverified", "upstream_not_exact_current")
        self._state.upstream_verified = True
        return self._continue_reassessment(resume=False)

    def resume(self, *, confirmed: bool) -> MultiAttemptOutcome:
        """Continue original in-memory review; never repeat an upstream #30 write.

        A process restart without original receipts/token requires separate
        Slice E recovery, not reconstruction of a new #30 revision.
        """
        if (
            not confirmed
            or not self._state.started
            or not self._state.upstream_verified
        ):
            return self._outcome(
                "recovery_required", "resume_requires_verified_upstream"
            )
        try:
            if not _intention_current(
                self.root, self.prepared, self.interpretation, self.ports
            ) or not _upstream_exact(
                self.root, self.prepared, self.authoring, self.ports
            ):
                return self._outcome("conflict_requires_review", "upstream_changed")
        except Exception:
            return self._outcome("current_unverified", "upstream_reload_unavailable")
        return self._continue_reassessment(resume=self._state.reassessment_attempted)

    def _continue_reassessment(self, *, resume: bool) -> MultiAttemptOutcome:
        try:
            if not _upstream_exact(
                self.root, self.prepared, self.authoring, self.ports
            ):
                return self._outcome("conflict_requires_review", "upstream_changed")
            if self._state.reassessment_action is None:
                _reviewed_policy_current(self.root, self.review, self.ports)
                self._state.reassessment_action = (
                    self.ports.reassessment_action_preparer(
                        self.root,
                        prepared=self.prepared,
                        review=self.review,
                        actor=self.actor,
                    )
                )
            action = self._state.reassessment_action
            assert action is not None
            if action.preview.kind != "reassessment_decision" or (
                action.preview.target.candidate_sha256
                != self.review.reassessment_decision_sha256
                or action.preview.target.revision
                != self.review.decision.decision_revision
                or action.preview.actor != self.actor
            ):
                raise MultiAttemptResolutionError(
                    "#31 action is not the reviewed target."
                )
        except Exception:
            return self._outcome(
                "upstream_current_reassessment_incomplete",
                "reassessment_preparation_blocked",
            )
        try:
            self._state.reassessment_attempted = True
            outcome = (
                action.resume(confirmed=True)
                if resume
                else action.apply(confirmed=True)
            )
        except Exception:
            return self._outcome(
                "upstream_current_reassessment_incomplete",
                "reassessment_action_unknown",
            )
        if outcome.status not in ("applied", "already_applied"):
            status: PairStatus = (
                "reassessment_written_not_current"
                if outcome.status == "written_not_current"
                else "upstream_current_reassessment_incomplete"
            )
            return self._outcome(
                status,
                outcome.reason_code or outcome.status,
                reassessment_status=outcome.status,
            )
        try:
            verified = self.ports.reassessment_observer(
                self.root,
                prepared=self.prepared,
                review=self.review,
                result=outcome,
            )
        except Exception:
            return self._outcome(
                "current_unverified",
                "reassessment_readback_failed",
                reassessment_status=outcome.status,
            )
        if not verified.exact_current or verified.status not in (
            "applied_current",
            "already_current",
        ):
            return self._outcome(
                "current_unverified",
                "reassessment_not_exact_current",
                reassessment_status=outcome.status,
            )
        try:
            if not _upstream_exact(
                self.root, self.prepared, self.authoring, self.ports
            ) or not _reassessment_exact(
                self.root, self.prepared, self.review, self.ports
            ):
                return self._outcome(
                    "current_unverified",
                    "pair_independent_reload_mismatch",
                    reassessment_status=outcome.status,
                )
        except Exception:
            return self._outcome(
                "current_unverified",
                "pair_canonical_reload_unavailable",
                reassessment_status=outcome.status,
            )
        return MultiAttemptOutcome(
            "already_current"
            if (
                self._state.upstream_status == "already_applied"
                and outcome.status == "already_applied"
            )
            else "applied_current",
            self._state.upstream_status,
            outcome.status,
            True,
            True,
        )

    def _outcome(
        self,
        status: PairStatus,
        reason: str | None = None,
        *,
        reassessment_status: str | None = None,
    ) -> MultiAttemptOutcome:
        return MultiAttemptOutcome(
            status,
            self._state.upstream_status,
            reassessment_status,
            False,
            False,
            reason,
        )


def prepare_reviewed_multi_attempt_resolution(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    review: ProspectiveReassessmentReview,
    preset: GuidedAttemptPolicyPreset,
    actor: TeacherActionActor,
    dependencies: GuidedAttemptDependencies,
    ports: MultiAttemptPorts | None = None,
) -> PreparedMultiAttemptResolution:
    """Read-only preparation; preflight BOTH domains before any #30 write."""
    if not isinstance(root, Path) or not root.is_absolute():
        raise MultiAttemptResolutionError("Absolute workspace root required.")
    if not isinstance(prepared, GuidedProjectionResult):
        raise MultiAttemptResolutionError("Authorized projection required.")
    if not isinstance(interpretation, AttemptInterpretationPreview):
        raise MultiAttemptResolutionError("Typed student review required.")
    if not isinstance(review, ProspectiveReassessmentReview):
        raise MultiAttemptResolutionError("Typed #31 review required.")
    if not isinstance(actor, TeacherActionActor) or preset not in dependencies.policies:
        raise MultiAttemptResolutionError("Qualified actor and policy preset required.")
    if (
        interpretation.treatment != "teacher_reviewed_reassessment"
        or not interpretation.needs_reassessment_decision
    ):
        raise MultiAttemptResolutionError("Multiple exact performances required.")
    published = prepared.authorized.current_context.publication
    if (
        interpretation.source_snapshot.work != published.work
        or interpretation.source_snapshot.publication_id != published.publication_id
        or interpretation.class_id != published.work.class_id
        or not prepared.authorized.assessment.reusable_for_current_use
    ):
        raise MultiAttemptResolutionError("Publication, Core scope or reuse is stale.")
    p = MultiAttemptPorts() if ports is None else ports
    try:
        if not _intention_current(root, prepared, interpretation, p):
            raise MultiAttemptResolutionError(
                "Current roster/source intention changed."
            )
        policy = p.policy_planner(
            root,
            class_id=interpretation.class_id,
            grade_item_id=interpretation.grade_item_id,
            work=interpretation.source_snapshot.work,
            preset=preset,
            dependencies=dependencies,
        )
        if policy.action != "ready" or policy.preset != preset:
            raise MultiAttemptResolutionError("Select #30 policy separately first.")
        _reviewed_policy_current(root, review, p)
        authoring = p.authoring_previewer(
            root,
            prepared=prepared,
            grade_item_id=interpretation.grade_item_id,
            student_id=interpretation.student_id,
            preset=preset,
            selected_attempts=interpretation.intended_selected_attempts,
            teacher_attribution=actor.actor_id,
            rationale=interpretation.suggested_canonical_rationale,
            dependencies=dependencies,
        )
        _aligned(interpretation, authoring, review, actor)
        if authoring.candidate.policy.policy_id != preset.policy_id:
            raise MultiAttemptResolutionError("Wrong selected #30 policy.")
        action = p.upstream_action_preparer(
            root, prepared, authoring, actor, dependencies
        )
        target = action.preview.target
        if (
            action.preview.kind != "attempt_decision"
            or action.preview.actor != actor
            or action.preview.scope.class_id != interpretation.class_id
            or action.preview.scope.grade_item_id != interpretation.grade_item_id
            or target.candidate_sha256 != _decision_digest(authoring)
            or target.revision != authoring.candidate.decision_revision
            or target.expected_current_revision
            != interpretation.selected_revision_at_preview
        ):
            raise MultiAttemptResolutionError("#122 #30 action differs from review.")
    except Exception as error:
        raise MultiAttemptResolutionError(
            "Reviewed #30/#31 preparation was not current; nothing was written."
        ) from error
    return PreparedMultiAttemptResolution(
        root, prepared, interpretation, authoring, review, actor, action, p
    )


def assess_multi_attempt_recovery(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    ports: MultiAttemptPorts | None = None,
) -> MultiAttemptRecoveryAssessment:
    """Read-only restart classification: no receipt recreation or academic writes."""
    p = MultiAttemptPorts() if ports is None else ports
    if not isinstance(root, Path) or not root.is_absolute():
        raise MultiAttemptResolutionError("Absolute workspace root required.")
    if not isinstance(authoring, AttemptDecisionAuthoringPreview) or not isinstance(
        review, ProspectiveReassessmentReview
    ):
        raise MultiAttemptResolutionError("Typed exact review required.")
    if (
        review.upstream_decision_sha256 != _decision_digest(authoring)
        or review.decision.attempt_selection.decision_revision
        != authoring.candidate.decision_revision
    ):
        raise MultiAttemptResolutionError("Cross-action candidate witness differs.")
    try:
        upstream = _upstream_exact(root, prepared, authoring, p)
    except Exception:
        return MultiAttemptRecoveryAssessment(
            "current_unverified", False, False, "upstream_read_failed"
        )
    if not upstream:
        return MultiAttemptRecoveryAssessment(
            "upstream_not_current", False, False, "review_canonical_30"
        )
    try:
        # An existing exact #31 pointer is still useless if policy or #30 drifted.
        _reviewed_policy_current(root, review, p, allow_target_history=True)
    except Exception:
        return MultiAttemptRecoveryAssessment(
            "conflict_requires_review", True, False, "policy_history_or_pointer_drift"
        )
    try:
        if _reassessment_exact(root, prepared, review, p):
            return MultiAttemptRecoveryAssessment("pair_current", True, True)
    except Exception:
        return MultiAttemptRecoveryAssessment(
            "current_unverified", True, False, "reassessment_resolver_failed"
        )
    try:
        decision = review.decision
        history = p.reassessment_history_loader(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
        )
        if history == review.history_before:
            old_pointer = p.reassessment_current_loader(
                root,
                decision.class_id,
                decision.grade_item_id,
                decision.work,
                decision.student_id,
            )
            if old_pointer is not None:
                return MultiAttemptRecoveryAssessment(
                    "conflict_requires_review",
                    True,
                    False,
                    "previous_reassessment_pointer_remains_current",
                )
            return MultiAttemptRecoveryAssessment(
                "upstream_current_reassessment_missing", True, False
            )
        if history == (*review.history_before, decision.decision_revision):
            return MultiAttemptRecoveryAssessment(
                "reassessment_written_not_current", True, False
            )
    except Exception:
        return MultiAttemptRecoveryAssessment(
            "current_unverified", True, False, "reassessment_history_unavailable"
        )
    return MultiAttemptRecoveryAssessment(
        "conflict_requires_review", True, False, "reassessment_history_changed"
    )


def render_reviewed_multi_attempt_resolution(
    value: PreparedMultiAttemptResolution,
) -> str:
    """Accessible review text; no producer claim or automatic score policy."""
    if not isinstance(value, PreparedMultiAttemptResolution):
        raise TypeError("Expected reviewed multi-attempt pair.")
    name = "".join(
        ch if ch.isprintable() else "?" for ch in value.interpretation.student_label
    )
    return "\n".join(
        (
            "Meridian — Review Multi-Attempt Resolution (NOT SAVED)",
            f"Student: {name}",
            (
                "Explicit #30 attempts: "
                f"{len(value.authoring.candidate.selected_attempts)}"
            ),
            f"Explicit #31 mode: {value.review.decision.mode}",
            (
                "Academic contributors: "
                f"{len(value.review.decision.contributing_attempts)}"
            ),
            "Save and Use requires one confirmation and TWO guarded academic actions.",
            "#30 is verified current BEFORE #31 is written or selected.",
            "The pair is NOT an atomic transaction. An interruption requires recovery.",
            "No scan origin certifies a correction, and no score or grade is inferred.",
            "Cancel writes neither action. Policy changes must be separately reviewed.",
        )
    )


__all__ = (
    "MultiAttemptOutcome",
    "MultiAttemptPorts",
    "MultiAttemptRecoveryAssessment",
    "MultiAttemptResolutionError",
    "PreparedMultiAttemptResolution",
    "assess_multi_attempt_recovery",
    "prepare_reviewed_multi_attempt_resolution",
    "render_reviewed_multi_attempt_resolution",
)
