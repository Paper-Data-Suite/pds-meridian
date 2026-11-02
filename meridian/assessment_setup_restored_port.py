"""#124 E2F2: restore original selection-only #122 port after process restart.

No preparation, new action ID, immutable authoring, or automatic RESUME.
The existing canonical #122 restart ports are the only selection authorities.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from meridian.assessment_setup_exact_resume import (
    AssessmentSetupExactResumeResult,
    resume_original_assessment_setup_selection,
)
from meridian.assessment_setup_original_receipt import (
    inspect_original_assessment_setup_receipt,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction, _GuidedPort
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_grade_item import (
    _RestartGradeItemPort,
    inspect_restart_grade_item,
)
from meridian.teacher_action_restart_membership import (
    _RestartMembershipPort,
    inspect_restart_membership,
)


def resume_restored_assessment_setup_selection(
    workspace_root: Path,
    reviewed: AssessmentSetupPreview,
    actor: TeacherActionActor,
    *,
    confirmation: str,
) -> AssessmentSetupExactResumeResult:
    """Explicit RESUME through E2F1, original #122 port, then E2E gateway.

    A receipt is not authority. Verify it twice and demand exact live #122
    restart eligibility before passing a selection-only port to E2E.
    """

    def refuse(reason: str) -> AssessmentSetupExactResumeResult:
        return AssessmentSetupExactResumeResult("requires_review", reason, None)

    if confirmation != "RESUME":
        return AssessmentSetupExactResumeResult("cancelled", "not_confirmed", None)
    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not isinstance(reviewed, AssessmentSetupPreview)
        or not isinstance(actor, TeacherActionActor)
    ):
        return refuse("invalid_restoration_context")
    try:
        witness = inspect_original_assessment_setup_receipt(
            workspace_root, reviewed, actor
        )
        if witness.disposition != "original_receipt_verified":
            return refuse(witness.reason)
        original = witness.original_preview
        if original is None:
            return refuse("original_preview_unavailable")
        journal = TeacherActionReceiptStore(workspace_root, reviewed.class_id)
        receipt = journal.load(original.action_id)
        if receipt is None or receipt.preview != original:
            return refuse("original_receipt_changed")
        port: _RestartGradeItemPort | _RestartMembershipPort
        if original.kind == "grade_item":
            inspection = inspect_restart_grade_item(workspace_root, journal, receipt)
            if not inspection.can_resume:
                return refuse("grade_restart_not_eligible")
            port = _RestartGradeItemPort(workspace_root, receipt, _check_actor)
        elif original.kind == "grade_item_membership":
            inspection_m = inspect_restart_membership(workspace_root, journal, receipt)
            if not inspection_m.can_resume:
                return refuse("membership_restart_not_eligible")
            port = _RestartMembershipPort(workspace_root, receipt, _check_actor)
        else:
            return refuse("unsupported_original_family")
        port.revalidate_basis(original)
        again = inspect_original_assessment_setup_receipt(
            workspace_root, reviewed, actor
        )
        if again != witness or journal.load(original.action_id) != receipt:
            return refuse("original_evidence_changed_before_resume")
        # Both canonical restart ports refuse immutable authoring. The cast
        # reflects their closed #122 port protocol; no generic port is created.
        bound = PreparedGuidedAction(original, cast(_GuidedPort, port), journal)
        return resume_original_assessment_setup_selection(
            workspace_root,
            reviewed,
            actor,
            original_action=bound,
            confirmation="RESUME",
        )
    except Exception:
        # A selection may have begun in E2E. Never infer failure/no mutation.
        return refuse("restored_selection_requires_independent_review")


def _check_actor(actor: TeacherActionActor) -> None:
    """Use the original #122 current saved-profile verifier."""
    from meridian.teacher_action_guided import _actor_now

    _actor_now(actor)


__all__ = ("resume_restored_assessment_setup_selection",)
