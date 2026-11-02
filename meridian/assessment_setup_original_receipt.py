"""#124 E2F1: read-only exact original #122 receipt reconstruction witness.

A stored receipt is evidence, not authority to rebuild a domain port or RESUME.
No canonical academic writes, journal checkpoints, or arbitrary action selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from meridian.assessment_setup_correlation import create_assessment_setup_correlation
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_restart import inspect_stored_assessment_setup_restart
from meridian.teacher_action_contract import TeacherActionActor, TeacherActionPreview
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_receipts import TeacherActionReceiptStore


@dataclass(frozen=True, slots=True)
class OriginalReceiptWitness:
    disposition: Literal["requires_review", "original_receipt_verified"]
    reason: str
    original_preview: TeacherActionPreview | None = None

    @property
    def may_resume_automatically(self) -> bool:
        return False

    @property
    def may_select_academic_record(self) -> bool:
        return False


def inspect_original_assessment_setup_receipt(
    workspace_root: Path,
    reviewed: AssessmentSetupPreview,
    actor: TeacherActionActor,
) -> OriginalReceiptWitness:
    """Reconcile E2D and the original receipt without constructing an action port."""

    def refuse(reason: str) -> OriginalReceiptWitness:
        return OriginalReceiptWitness("requires_review", reason)

    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not isinstance(reviewed, AssessmentSetupPreview)
        or not isinstance(actor, TeacherActionActor)
    ):
        return refuse("invalid_reconstruction_context")
    try:
        base = create_assessment_setup_correlation(workspace_root, reviewed, actor)
        store = AssessmentSetupCorrelationStore(workspace_root, reviewed.class_id)
        restart = inspect_stored_assessment_setup_restart(
            workspace_root, reviewed, actor
        )
        correlation = store.load(base.intent_sha256)
        if correlation is None or correlation.intent_sha256 != base.intent_sha256:
            return refuse("exact_correlation_missing")
        if restart.intent_sha256 != correlation.intent_sha256:
            return refuse("restart_intent_mismatch")
        if restart.disposition == "original_grade_action_pending":
            family = "grade_item"
            action_id, target_digest = (
                correlation.grade_action_id,
                correlation.grade_target_sha256,
            )
            if restart.canonical_state != "grade_item_written_not_selected":
                return refuse("grade_stage_not_exact")
        elif restart.disposition == "original_membership_action_pending":
            family = "grade_item_membership"
            action_id, target_digest = (
                correlation.membership_action_id,
                correlation.membership_target_sha256,
            )
            if restart.canonical_state != "membership_written_not_selected":
                return refuse("membership_stage_not_exact")
        else:
            return refuse("no_original_pending_selection")
        if action_id is None or target_digest is None:
            return refuse("original_action_not_bound")
        if (
            restart.grade_action_id != correlation.grade_action_id
            or restart.membership_action_id != correlation.membership_action_id
        ):
            return refuse("restart_action_binding_changed")
        journal = TeacherActionReceiptStore(workspace_root, reviewed.class_id)
        receipt = journal.load(action_id)
        if receipt is None:
            return refuse("original_receipt_missing")
        preview = receipt.preview
        scope = preview.scope
        if (
            preview.action_id != action_id
            or preview.kind != family
            or preview.target.family != family
            or preview.target.candidate_sha256 != target_digest
            or preview.reviewed_decision_sha256 != target_digest
            or not preview.make_current
            or preview.actor != actor
            or actor.source != "saved"
            or scope.workspace_sha256 != correlation.workspace_sha256
            or scope.class_id != correlation.class_id
            or scope.grade_item_id != correlation.grade_item_id
        ):
            return refuse("original_receipt_binding_mismatch")
        if family == "grade_item":
            if (
                correlation.kind != "create_and_link"
                or preview.target.revision != 1
                or scope.school_year is not None
            ):
                return refuse("original_grade_scope_mismatch")
        elif (
            scope.school_year != correlation.school_year
            or scope.academic_period_id != correlation.period_id
            or scope.work_identity_sha256
            != _identity(
                "work", correlation.class_id, correlation.module_id, correlation.work_id
            )
        ):
            return refuse("original_membership_scope_mismatch")
        # Do not return evidence from a snapshot that changed while inspecting it.
        if (
            store.load(base.intent_sha256) != correlation
            or journal.load(action_id) != receipt
            or inspect_stored_assessment_setup_restart(workspace_root, reviewed, actor)
            != restart
        ):
            return refuse("reconstruction_evidence_changed")
        return OriginalReceiptWitness(
            "original_receipt_verified", "original_receipt_exact", preview
        )
    except Exception:
        return refuse("original_receipt_inspection_unavailable")
