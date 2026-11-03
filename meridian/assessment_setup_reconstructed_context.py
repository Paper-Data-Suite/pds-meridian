"""#124 E2G3B: verify a freshly reviewed restart context, read-only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from meridian.assessment_setup_correlation import create_assessment_setup_correlation
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_original_receipt import (
    inspect_original_assessment_setup_receipt,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_restart import inspect_restart_context_candidate
from meridian.teacher_action_contract import TeacherActionActor

PreviewLoader = Callable[[], AssessmentSetupPreview]


@dataclass(frozen=True, slots=True)
class ReconstructedContextInspection:
    disposition: Literal["verified_for_review", "requires_review"]
    reason: str
    reviewed: AssessmentSetupPreview | None = None

    @property
    def may_resume_automatically(self) -> bool:
        return False

    @property
    def may_select_academic_record(self) -> bool:
        return False


def inspect_reconstructed_assessment_context(
    workspace_root: Path,
    class_id: str,
    module_id: str,
    work_id: str,
    actor: TeacherActionActor,
    *,
    load_fresh_review: PreviewLoader,
) -> ReconstructedContextInspection:
    """Compare fresh teacher-reviewed intent to durable identity and original receipt.

    Caller must obtain fresh teacher choices and canonical data. This function
    never deserializes a preview from a receipt, performs writes, or selects.
    """

    def refuse(reason: str) -> ReconstructedContextInspection:
        return ReconstructedContextInspection("requires_review", reason)

    if not callable(load_fresh_review):
        return refuse("missing_review_loader")
    try:
        first = inspect_restart_context_candidate(
            workspace_root, class_id, module_id, work_id, actor
        )
        if first.disposition != "unique_candidate" or first.intent_sha256 is None:
            return refuse(first.reason)
        reviewed = load_fresh_review()
        if not isinstance(reviewed, AssessmentSetupPreview):
            return refuse("invalid_fresh_review")
        if (
            reviewed.class_id != class_id
            or reviewed.work.module_id != module_id
            or reviewed.work.work_id != work_id
            or reviewed.actor_attribution != actor.actor_id
        ):
            return refuse("fresh_review_scope_changed")
        expected = create_assessment_setup_correlation(workspace_root, reviewed, actor)
        if expected.intent_sha256 != first.intent_sha256:
            return refuse("fresh_review_intent_changed")
        store = AssessmentSetupCorrelationStore(workspace_root, class_id)
        record = store.load(first.intent_sha256)
        if record is None or record.intent_sha256 != expected.intent_sha256:
            return refuse("durable_intent_missing")
        receipt = inspect_original_assessment_setup_receipt(
            workspace_root, reviewed, actor
        )
        if receipt.disposition != "original_receipt_verified":
            return refuse(receipt.reason)
        # Reject moving context after original receipt verification.
        second = inspect_restart_context_candidate(
            workspace_root, class_id, module_id, work_id, actor
        )
        if second != first or store.load(first.intent_sha256) != record:
            return refuse("reconstruction_evidence_changed")
        # Reconstruct once more to ensure the current reader is stable.
        if load_fresh_review() != reviewed:
            return refuse("fresh_review_changed")
        return ReconstructedContextInspection(
            "verified_for_review", "requires_explicit_teacher_resume", reviewed
        )
    except Exception:
        return refuse("reconstruction_unavailable")


__all__ = (
    "PreviewLoader",
    "ReconstructedContextInspection",
    "inspect_reconstructed_assessment_context",
)
