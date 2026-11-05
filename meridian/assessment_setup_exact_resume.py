"""#124 E2E: explicit, exact #122 selection resume for a correlated setup.

Never prepare an action, author a Grade Item/membership, or choose a new
revision. No menu integration: the caller must supply the *original*, fully
bound #122 action port and an explicit RESUME confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    create_assessment_setup_correlation,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_restart import (
    AssessmentSetupRestartInspection,
    inspect_stored_assessment_setup_restart,
)
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionPreview,
    TeacherActionResult,
)
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import (
    TeacherActionReceiptStore,
    assess_teacher_action_recovery,
)

ResumeDisposition: TypeAlias = Literal[
    "cancelled",
    "requires_review",
    "original_grade_selected",
    "ready_verified",
    "current_unverified",
]


@dataclass(frozen=True, slots=True)
class AssessmentSetupExactResumeResult:
    """Truthful outcome; only #122 may report an academic selection."""

    disposition: ResumeDisposition
    reason: str
    original_action_id: str | None
    action_result: TeacherActionResult | None = None
    restart_after: AssessmentSetupRestartInspection | None = None

    @property
    def ready(self) -> bool:
        return self.disposition == "ready_verified"

    @property
    def may_resume_automatically(self) -> bool:
        return False

    @property
    def may_author_immutable_revision(self) -> bool:
        return False


def _same_original_action(
    record: AssessmentSetupCorrelation,
    action: PreparedGuidedAction,
    family: Literal["grade_item", "grade_item_membership"],
) -> bool:
    p = action.preview
    scope = p.scope
    if family == "grade_item":
        expected_id, expected_target = (
            record.grade_action_id,
            record.grade_target_sha256,
        )
    else:
        expected_id = record.membership_action_id
        expected_target = record.membership_target_sha256
    return (
        expected_id is not None
        and expected_target is not None
        and p.action_id == expected_id
        and p.kind == family
        and p.target.family == family
        and p.target.candidate_sha256 == expected_target
        and p.scope.workspace_sha256 == record.workspace_sha256
        and scope.class_id == record.class_id
        and scope.grade_item_id == record.grade_item_id
        and p.actor.source == "saved"
        and p.actor.actor_id == record.actor_id
        and p.actor.profile_sha256 == record.actor_profile_sha256
        and p.make_current
        and (
            (
                scope.school_year is None
                and p.target.revision == 1
                and record.kind == "create_and_link"
            )
            if family == "grade_item"
            else (
                scope.school_year == record.school_year
                and scope.academic_period_id == record.period_id
                and scope.work_identity_sha256
                == _identity("work", record.class_id, record.module_id, record.work_id)
            )
        )
    )


def resume_original_assessment_setup_selection(
    workspace_root: Path,
    preview: AssessmentSetupPreview,
    actor: TeacherActionActor,
    *,
    original_action: PreparedGuidedAction,
    confirmation: str,
) -> AssessmentSetupExactResumeResult:
    """Explicit RESUME of the original #122 selection; never a new write.

    The original #122 preview/port/receipt store must already be bound by a
    separate trusted adapter. This module cannot recover an original action
    from a newly generated #122 action ID or a Grade Item title.
    """

    def blocked(
        reason: str, action_id: str | None = None
    ) -> AssessmentSetupExactResumeResult:
        return AssessmentSetupExactResumeResult("requires_review", reason, action_id)

    if confirmation != "RESUME":
        return AssessmentSetupExactResumeResult("cancelled", "not_confirmed", None)
    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not isinstance(preview, AssessmentSetupPreview)
        or not isinstance(actor, TeacherActionActor)
        or not isinstance(original_action, PreparedGuidedAction)
        or not isinstance(original_action.preview, TeacherActionPreview)
        or not isinstance(original_action.store, TeacherActionReceiptStore)
    ):
        return blocked("untyped_or_nonabsolute_resume_context")
    root = workspace_root
    p = original_action.preview
    action_id = p.action_id
    if (
        original_action.store.root != root
        or original_action.store.class_id != preview.class_id
        or actor.source != "saved"
    ):
        return blocked("original_journal_or_actor_scope_mismatch", action_id)
    family: Literal["grade_item", "grade_item_membership"]
    if p.kind == "grade_item":
        family = "grade_item"
    elif p.kind == "grade_item_membership":
        family = "grade_item_membership"
    else:
        return blocked("unsupported_original_action_family", action_id)
    try:
        base = create_assessment_setup_correlation(root, preview, actor)
        record = AssessmentSetupCorrelationStore(root, preview.class_id).load(
            base.intent_sha256
        )
        if record is None or record.intent_sha256 != base.intent_sha256:
            return blocked("original_correlation_missing", action_id)
        if not _same_original_action(record, original_action, family):
            return blocked("original_action_binding_mismatch", action_id)
        first = inspect_stored_assessment_setup_restart(root, preview, actor)
        required = (
            "original_grade_action_pending"
            if family == "grade_item"
            else "original_membership_action_pending"
        )
        canonical_required = (
            "grade_item_written_not_selected"
            if family == "grade_item"
            else "membership_written_not_selected"
        )
        if (
            first.disposition != required
            or first.canonical_state != canonical_required
            or first.intent_sha256 != record.intent_sha256
            or (
                first.grade_action_id
                if family == "grade_item"
                else first.membership_action_id
            )
            != action_id
        ):
            return blocked("restart_not_exact_pending_selection", action_id)
        receipt = original_action.store.load(action_id)
        if receipt is None or receipt.preview != p:
            return blocked("original_receipt_preview_mismatch", action_id)
        # #122 re-reads the immutable target, current CAS pointer and live basis.
        assessment = assess_teacher_action_recovery(
            original_action.store, p, original_action.port.observe
        )
        if (
            not assessment.can_resume_exact_selection
            or assessment.reason != "eligible_to_resume"
            or not assessment.target_verified_present
            or assessment.receipt_generation != receipt.generation
        ):
            return blocked("122_selection_not_eligible", action_id)
        # Close the preflight window conservatively; the #122 RESUME kernel
        # *also* revalidates live basis and current pointer immediately before
        # its own exact CAS selection. This is not a cross-process lock.
        second = inspect_stored_assessment_setup_restart(root, preview, actor)
        if second != first:
            return blocked("restart_changed_before_selection", action_id)
        # Invoke the base #122 method, not a subclass override or .apply().
        result = PreparedGuidedAction.resume(original_action, confirmed=True)
        if (
            not isinstance(result, TeacherActionResult)
            or result.action_id != action_id
            or result.intent_sha256 != p.intent_sha256
            or result.target != p.target
        ):
            return blocked("122_returned_unbound_result", action_id)
        if not result.succeeded:
            return AssessmentSetupExactResumeResult(
                "requires_review", "122_selection_not_verified", action_id, result
            )
        after = inspect_stored_assessment_setup_restart(root, preview, actor)
        if (
            after.intent_sha256 != record.intent_sha256
            or after.grade_action_id != record.grade_action_id
            or after.membership_action_id != record.membership_action_id
        ):
            return AssessmentSetupExactResumeResult(
                "current_unverified",
                "post_resume_correlation_changed",
                action_id,
                result,
                after,
            )
        if (
            family == "grade_item"
            and after.disposition == "original_membership_action_pending"
            and after.canonical_state == "grade_item_selected_link_missing"
        ):
            return AssessmentSetupExactResumeResult(
                "original_grade_selected",
                "original_grade_selection_verified",
                action_id,
                result,
                after,
            )
        if family == "grade_item_membership" and after.disposition == "ready_verified":
            return AssessmentSetupExactResumeResult(
                "ready_verified",
                "canonical_composite_verified",
                action_id,
                result,
                after,
            )
        return AssessmentSetupExactResumeResult(
            "current_unverified",
            "post_resume_canonical_check_incomplete",
            action_id,
            result,
            after,
        )
    except Exception:
        # Any unknown exception is possible after #122 began selection; do
        # not claim no mutation, retry, or readiness from this wrapper.
        return blocked("resume_outcome_requires_independent_review", action_id)


__all__ = (
    "AssessmentSetupExactResumeResult",
    "ResumeDisposition",
    "resume_original_assessment_setup_selection",
)
