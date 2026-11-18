"""#126-D1: one reviewed correction/reassessment intention into canonical #30.

The existing #122 port is the *only* writer/selector. This bridge never creates
its own current pointer, change to #29 eligibility, or producer correction. A
multi-selected intention is blocked until an explicit #31 composition exists.
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
from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
)
from meridian.attempt_decisions_workflow import (
    AttemptDecisionWorkflowProjection,
    project_attempt_decisions,
)
from meridian.attempt_selection import attempt_selection_decision_to_json_bytes
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPlan,
    GuidedAttemptPolicyPreset,
    plan_guided_attempt_policy,
    preview_guided_attempt_decision,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_action_attempt_standards import prepare_attempt_decision_action
from meridian.teacher_action_contract import TeacherActionActor, TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction


class AttemptResolutionExecutionError(ValueError):
    """A stale/unsupported teacher intention must not reach an academic writer."""

    code = "teacher_workflow.attempt_resolution.invalid"


class AttemptResolutionNeedsReassessment(AttemptResolutionExecutionError):
    """Two or more selected performances need a separate reviewed #31 action."""

    code = "teacher_workflow.attempt_resolution.reassessment_required"


ResolutionOutcomeStatus: TypeAlias = Literal[
    "canceled_before_write",
    "blocked_before_write",
    "conflict_requires_review",
    "written_not_current",
    "current_unverified",
    "recovery_required",
    "applied_current",
    "already_current",
]


@dataclass(frozen=True, slots=True)
class AttemptResolutionOutcome:
    """Truthful one-action outcome; source facts and Grade remain untouched."""

    status: ResolutionOutcomeStatus
    action_status: str | None
    canonical_resolution_status: str | None
    exact_current: bool
    continue_to_standards_review: bool
    reason: str | None = None


# Optional injected read-only/writer adapters permit in-memory acceptance tests.
# Production defaults remain the existing, independently validating services.
@dataclass(frozen=True, slots=True)
class AttemptResolutionPorts:
    inventory_loader: Callable[..., AssessmentAttemptInventory] = (
        project_assessment_attempt_inventory
    )
    policy_planner: Callable[..., GuidedAttemptPolicyPlan] = plan_guided_attempt_policy
    authoring_previewer: Callable[..., AttemptDecisionAuthoringPreview] = (
        preview_guided_attempt_decision
    )
    action_preparer: Callable[..., PreparedGuidedAction] = (
        prepare_attempt_decision_action
    )
    selection_loader: Callable[..., AttemptDecisionWorkflowProjection] = (
        project_attempt_decisions
    )


def _reload_intention(
    *,
    root: Path,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    ports: AttemptResolutionPorts,
) -> AttemptInterpretationPreview:
    """Recheck precise roster/eligibility/source/selection in read-only layers."""
    inventory = ports.inventory_loader(
        root, grade_item_id=interpretation.grade_item_id, prepared=prepared
    )
    return preview_attempt_interpretation(
        inventory,
        student_id=interpretation.student_id,
        treatment=interpretation.treatment,
        selected_attempts=interpretation.intended_selected_attempts,
        original_attempt=interpretation.original_attempt,
        teacher_rationale=interpretation.teacher_rationale,
    )


@dataclass(frozen=True, slots=True)
class PreparedAttemptResolution:
    """One guarded, reviewed #30 author/select action, not a second writer."""

    interpretation: AttemptInterpretationPreview
    authoring: AttemptDecisionAuthoringPreview = field(repr=False)
    action: PreparedGuidedAction = field(repr=False)
    root: Path = field(repr=False)
    prepared: GuidedProjectionResult = field(repr=False)
    ports: AttemptResolutionPorts = field(repr=False)

    def apply(self, *, confirmed: bool) -> AttemptResolutionOutcome:
        """One explicit confirmation; independently inspect exact current #30.

        Any failure after the #122 call is *not* evidence of a rolled-back
        transaction. Do not retry blindly; use the canonical #122 recovery UI.
        """
        if not confirmed:
            # The existing #122 cancel path is side-effect-free. Calling it is
            # intentional: no homegrown pseudo-cancellation receipt is created.
            result = self.action.apply(confirmed=False)
            if result.status != "blocked_before_write":
                raise AttemptResolutionExecutionError(
                    "Canonical cancellation returned an unexpected outcome."
                )
            return AttemptResolutionOutcome(
                "canceled_before_write", result.status, None, False, False
            )

        try:
            refreshed = _reload_intention(
                root=self.root,
                prepared=self.prepared,
                interpretation=self.interpretation,
                ports=self.ports,
            )
        except Exception:
            return AttemptResolutionOutcome(
                "conflict_requires_review",
                None,
                None,
                False,
                False,
                "precommit_source_or_roster_unverifiable",
            )
        if refreshed != self.interpretation:
            return AttemptResolutionOutcome(
                "conflict_requires_review",
                None,
                None,
                False,
                False,
                "precommit_intention_changed",
            )
        try:
            result = self.action.apply(confirmed=True)
        except Exception:
            # The #122 bridge may already have written a revision. It is never
            # safe to pretend that an exception implies no academic mutation.
            return AttemptResolutionOutcome(
                "recovery_required",
                None,
                None,
                False,
                False,
                "canonical_action_outcome_unknown",
            )
        return self._observe(result)

    def _observe(self, result: TeacherActionResult) -> AttemptResolutionOutcome:
        status = result.status
        if status not in {"applied", "already_applied"}:
            other: ResolutionOutcomeStatus
            if status == "blocked_before_write":
                other = "blocked_before_write"
            elif status == "conflict_requires_review":
                other = "conflict_requires_review"
            elif status == "written_not_current":
                other = "written_not_current"
            elif status == "current_unverified":
                other = "current_unverified"
            else:
                other = "recovery_required"
            return AttemptResolutionOutcome(
                other, status, None, False, False, result.reason_code
            )
        if result.current_state != "matches" or (
            result.current_record is None
            or not result.current_record.matches_target(self.action.preview.target)
        ):
            return AttemptResolutionOutcome(
                "current_unverified",
                status,
                None,
                False,
                False,
                "canonical_action_target_not_verified",
            )

        candidate = self.authoring.candidate
        try:
            canonical = self.ports.selection_loader(
                self.root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                authorized_snapshot=self.prepared.authorized,
            )
        except Exception:
            return AttemptResolutionOutcome(
                "current_unverified",
                status,
                None,
                False,
                False,
                "canonical_reload_unavailable",
            )
        digest = self.action.preview.target.candidate_sha256
        exact = (
            canonical.status == "selected"
            and canonical.operative_selection
            and canonical.resolution_status == "selected"
            and canonical.source_snapshot == candidate.source_snapshot
            and canonical.selected_decision_revision == candidate.decision_revision
            and canonical.selected_decision_sha256 == digest
            and canonical.reviewed_selected_attempts == candidate.selected_attempts
        )
        if not exact:
            return AttemptResolutionOutcome(
                "current_unverified",
                status,
                canonical.resolution_status,
                False,
                False,
                "independent_current_selection_mismatch",
            )
        return AttemptResolutionOutcome(
            "already_current" if status == "already_applied" else "applied_current",
            status,
            canonical.resolution_status,
            True,
            # Multi-selection is intentionally unavailable in D1.
            True,
        )


def prepare_reviewed_attempt_resolution(
    workspace_root: Path,
    *,
    prepared: GuidedProjectionResult,
    interpretation: AttemptInterpretationPreview,
    preset: GuidedAttemptPolicyPreset,
    actor: TeacherActionActor,
    dependencies: GuidedAttemptDependencies,
    ports: AttemptResolutionPorts | None = None,
) -> PreparedAttemptResolution:
    """Bind C's exact testimony to existing #30/#122, without any write.

    Policy creation/revision/selection is a *separate* consequential decision.
    Multiple operative selections require #31 and are therefore blocked here.
    """
    if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
        raise AttemptResolutionExecutionError("Absolute workspace root required.")
    if not isinstance(prepared, GuidedProjectionResult):
        raise AttemptResolutionExecutionError("Authorized projection is required.")
    if not isinstance(interpretation, AttemptInterpretationPreview):
        raise AttemptResolutionExecutionError("Typed Slice C interpretation required.")
    if interpretation.treatment == "unresolved":
        raise AttemptResolutionExecutionError(
            "Unresolved relationship cannot be saved."
        )
    if interpretation.needs_reassessment_decision or (
        len(interpretation.intended_selected_attempts) != 1
    ):
        raise AttemptResolutionNeedsReassessment(
            "Multiple selected attempts require explicit #31 relationship; "
            "nothing was saved."
        )
    if preset not in dependencies.policies:
        raise AttemptResolutionExecutionError("Unqualified policy preset.")
    if not isinstance(actor, TeacherActionActor):
        raise AttemptResolutionExecutionError("Verified #121 actor required.")
    source = interpretation.source_snapshot
    publication = prepared.authorized.current_context.publication
    if (
        source.work != publication.work
        or source.publication_id != publication.publication_id
        or interpretation.class_id != publication.work.class_id
    ):
        raise AttemptResolutionExecutionError(
            "Intention belongs to another exact work or publication."
        )
    services = AttemptResolutionPorts() if ports is None else ports
    try:
        refreshed = _reload_intention(
            root=workspace_root,
            prepared=prepared,
            interpretation=interpretation,
            ports=services,
        )
    except Exception as error:
        raise AttemptResolutionExecutionError(
            "Source, authorization, eligibility or roster could not be revalidated."
        ) from error
    if refreshed != interpretation:
        raise AttemptResolutionExecutionError(
            "Teacher intention no longer matches the current authorized review."
        )
    try:
        plan = services.policy_planner(
            workspace_root,
            class_id=interpretation.class_id,
            grade_item_id=interpretation.grade_item_id,
            work=source.work,
            preset=preset,
            dependencies=dependencies,
        )
    except Exception as error:
        raise AttemptResolutionExecutionError(
            "Selected attempt policy could not be reviewed."
        ) from error
    if plan.action != "ready" or plan.preset != preset:
        raise AttemptResolutionExecutionError(
            "Explicit attempt policy setup/selection is required separately."
        )
    try:
        authoring = services.authoring_previewer(
            workspace_root,
            prepared=prepared,
            grade_item_id=interpretation.grade_item_id,
            student_id=interpretation.student_id,
            preset=preset,
            selected_attempts=interpretation.intended_selected_attempts,
            teacher_attribution=actor.actor_id,
            rationale=interpretation.suggested_canonical_rationale,
            dependencies=dependencies,
        )
    except Exception as error:
        raise AttemptResolutionExecutionError(
            "Canonical #30 authoring preview unavailable; nothing was written."
        ) from error
    candidate = authoring.candidate
    if (
        candidate.class_id != interpretation.class_id
        or candidate.grade_item_id != interpretation.grade_item_id
        or candidate.student_id != interpretation.student_id
        or candidate.work != source.work
        or candidate.source_snapshot != source
        or candidate.selected_attempts != interpretation.intended_selected_attempts
        or candidate.rationale != interpretation.suggested_canonical_rationale
        or candidate.actor.kind != "teacher"
        or candidate.actor.actor_id != actor.actor_id
        or candidate.policy.policy_id != preset.policy_id
        or authoring.reviewed_current_decision_revision
        != interpretation.selected_revision_at_preview
    ):
        raise AttemptResolutionExecutionError(
            "Canonical candidate differs from reviewed teacher intention."
        )
    try:
        action = services.action_preparer(
            workspace_root, prepared, authoring, actor, dependencies
        )
    except Exception as error:
        raise AttemptResolutionExecutionError(
            "Canonical #122 guarded action unavailable; nothing was written."
        ) from error
    digest = hashlib.sha256(
        attempt_selection_decision_to_json_bytes(candidate)
    ).hexdigest()
    if (
        action.preview.kind != "attempt_decision"
        or action.preview.actor != actor
        or action.preview.scope.class_id != interpretation.class_id
        or action.preview.scope.grade_item_id != interpretation.grade_item_id
        or action.preview.target.candidate_sha256 != digest
        or action.preview.target.revision != candidate.decision_revision
        or action.preview.target.expected_current_revision
        != interpretation.selected_revision_at_preview
    ):
        raise AttemptResolutionExecutionError(
            "#122 reviewed action is not bound to the exact #30 candidate."
        )
    return PreparedAttemptResolution(
        interpretation, authoring, action, workspace_root, prepared, services
    )


def render_reviewed_attempt_resolution(value: PreparedAttemptResolution) -> str:
    """Teacher-facing pre-confirmation text; no IDs or hidden permission claims."""
    if not isinstance(value, PreparedAttemptResolution):
        raise TypeError("Expected one prepared canonical attempt action.")
    interpretation = value.interpretation
    candidate = value.authoring.candidate
    label = "".join(
        ch if ch.isprintable() else "?" for ch in interpretation.student_label
    )
    attempt = interpretation.intended_selected_attempts[0]
    attempt_label = (
        f"Attempt {attempt.native.sequence}"
        if attempt.native.sequence is not None
        else "Native attempt (exact source identity retained)"
    )
    return "\n".join(
        (
            "Meridian — Review Attempt Resolution (NOT YET SAVED)",
            f"Student: {label}",
            "Source: current publication, exact snapshot reviewed",
            f"Teacher account: {interpretation.treatment.replace('_', ' ')}",
            f"Current-use choice: {attempt_label}",
            f"Current decision revision after save: {candidate.decision_revision}",
            "This WILL record/select one exact #30 decision with your testimony.",
            "This WILL NOT remove old attempts, certify a producer correction,",
            "edit ScoreForm, select Standards, set proficiency or Grade, or publish.",
            "Save and Use This Decision — one confirmation; Cancel — no write.",
            "If selection fails after write, use #122 recovery; do not retry blindly.",
        )
    )


__all__ = (
    "AttemptResolutionExecutionError",
    "AttemptResolutionNeedsReassessment",
    "AttemptResolutionOutcome",
    "AttemptResolutionPorts",
    "PreparedAttemptResolution",
    "prepare_reviewed_attempt_resolution",
    "render_reviewed_attempt_resolution",
)
