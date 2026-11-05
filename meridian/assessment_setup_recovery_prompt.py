"""#124 E2G1: one explicit teacher-facing composite restart prompt.

The reviewed preview and actor come from the caller's trusted current context.
No menu registration, implicit resume, new academic writer, or action generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from meridian.assessment_setup_original_receipt import (
    inspect_original_assessment_setup_receipt,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_restored_port import (
    resume_restored_assessment_setup_selection,
)
from meridian.teacher_action_contract import TeacherActionActor


@dataclass(frozen=True, slots=True)
class RecoveryPromptOutcome:
    status: str
    reason: str
    original_action_id: str | None


def offer_assessment_setup_recovery(
    workspace_root: Path,
    reviewed: AssessmentSetupPreview,
    actor: TeacherActionActor,
    *,
    input_fn: Callable[[str], str],
    output: TextIO,
) -> RecoveryPromptOutcome:
    """Review one original pending selector, then require literal RESUME.

    The original receipt inspector and restored selector each revalidate the
    durable and live state. A display-only observation confers no authority.
    """
    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not isinstance(reviewed, AssessmentSetupPreview)
        or not isinstance(actor, TeacherActionActor)
    ):
        return RecoveryPromptOutcome("requires_review", "invalid_context", None)
    try:
        witness = inspect_original_assessment_setup_receipt(
            workspace_root, reviewed, actor
        )
        if witness.disposition != "original_receipt_verified":
            print(
                "Exact assessment recovery requires review; no selection requested.",
                file=output,
            )
            return RecoveryPromptOutcome("requires_review", witness.reason, None)
        original = witness.original_preview
        if original is None:
            return RecoveryPromptOutcome("requires_review", "missing_original", None)
        if original.kind not in ("grade_item", "grade_item_membership"):
            return RecoveryPromptOutcome("requires_review", "unsupported_family", None)
        print("Assessment setup recovery", file=output)
        print(f"Assessment: {reviewed.assessment_title}", file=output)
        print(f"Grade Item: {reviewed.grade_item_title}", file=output)
        print(f"Academic period: {reviewed.marking_period_label}", file=output)
        print(f"Original stage: {original.kind.replace('_', ' ')}", file=output)
        print(
            "Only the original immutable revision's selection may resume.", file=output
        )
        print("No new Grade Item or membership will be authored.", file=output)
        print(
            "Type RESUME to attempt exact selection; anything else cancels.",
            file=output,
        )
        if input_fn("Confirmation: ") != "RESUME":
            print("Canceled. No academic selection requested.", file=output)
            return RecoveryPromptOutcome(
                "cancelled", "not_confirmed", original.action_id
            )
        result = resume_restored_assessment_setup_selection(
            workspace_root, reviewed, actor, confirmation="RESUME"
        )
        print(f"Recovery disposition: {result.disposition}", file=output)
        print(f"Reason: {result.reason}", file=output)
        if result.disposition != "ready_verified":
            print("Do not treat the combined assessment as ready.", file=output)
        return RecoveryPromptOutcome(
            result.disposition, result.reason, result.original_action_id
        )
    except Exception:
        print(
            "Recovery outcome uncertain. Inspect canonical state independently.",
            file=output,
        )
        return RecoveryPromptOutcome(
            "requires_review", "recovery_outcome_uncertain", None
        )


__all__ = ("RecoveryPromptOutcome", "offer_assessment_setup_recovery")
