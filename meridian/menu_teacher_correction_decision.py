"""#126-F2A: one teacher-reviewed correction-use choice, not a producer correction.

Select an explicit original observation and one currently eligible result; bind
exact teacher testimony to the existing #30/#122 one-action service. No policy,
source, eligibility, producer, Grade, or #31 writer is introduced here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    NativeAttemptInventoryRow,
    StudentAttemptInventoryRow,
)
from meridian.attempt_correction_interpretation import (
    AttemptInterpretationPreview,
    preview_attempt_interpretation,
)
from meridian.attempt_resolution_execution import (
    PreparedAttemptResolution,
    prepare_reviewed_attempt_resolution,
    render_reviewed_attempt_resolution,
)
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import bind_reviewed_actor
from meridian.teacher_profile import TeacherIdentityProvider, TeacherProfileStore


def _saved_actor() -> TeacherActionActor:
    """Reuse the already saved #121 attribution; it is not academic authority."""
    identity, fingerprint = TeacherIdentityProvider(
        TeacherProfileStore()
    ).resolve_with_fingerprint()
    return bind_reviewed_actor(identity.actor_id, profile_sha256=fingerprint)


@dataclass(frozen=True, slots=True)
class CorrectionDecisionPorts:
    """Test seams; production uses the fully qualified #126-D1/#122 service."""

    actor_loader: Callable[[], TeacherActionActor] = _saved_actor
    intention_previewer: Callable[..., AttemptInterpretationPreview] = (
        preview_attempt_interpretation
    )
    resolution_preparer: Callable[..., PreparedAttemptResolution] = (
        prepare_reviewed_attempt_resolution
    )
    resolution_renderer: Callable[[PreparedAttemptResolution], str] = (
        render_reviewed_attempt_resolution
    )


def _safe(text: str, *, maximum: int = 140) -> str:
    """Display only printable, bounded teacher/producer strings."""
    value = "".join(
        ch if ch.isprintable() and ch not in {"\x1b", "\x7f"} else "?" for ch in text
    )
    return value[:maximum] + ("..." if len(value) > maximum else "")


def _label(value: NativeAttemptInventoryRow) -> str:
    parts = [_safe(value.attempt_label)]
    if value.point_result is not None:
        parts.append(f"source points {value.point_result[0]}/{value.point_result[1]}")
    else:
        parts.append("source points unavailable")
    parts.append(
        (
            "operative eligible"
            if value.operative_eligible
            else "historical / not eligible"
        )
    )
    return "; ".join(parts)


def _choose_observation(
    title: str,
    explanation: str,
    options: tuple[NativeAttemptInventoryRow, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> NativeAttemptInventoryRow | None:
    """Exact choice by page number; never choose latest, highest or first implicitly."""
    while True:
        clear_fn()
        print_menu_header(output, title)
        write_lines(output, explanation, "")
        for index, value in enumerate(options, 1):
            write_lines(output, f"{index}. {_label(value)}")
        write_lines(output, "")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if not choice or parse_navigation_choice(choice) is NavigationChoice.BACK:
            return None
        if choice.isascii() and choice.isdigit():
            number = int(choice)
            if 1 <= number <= len(options):
                return options[number - 1]
        write_lines(output, "Choose an explicitly numbered attempt, B, M, or Q.")


def _single_preset(
    dependencies: GuidedAttemptDependencies,
) -> GuidedAttemptPolicyPreset | None:
    """An existing exact-one policy is required; this workflow never creates it."""
    options = tuple(
        value
        for value in dependencies.policies
        if value.minimum_selected == 1 and value.maximum_selected == 1
    )
    return options[0] if len(options) == 1 else None


def run_teacher_correction_decision_menu(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    dependencies: GuidedAttemptDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: CorrectionDecisionPorts | None = None,
) -> bool:
    """Review and optionally Save/Use one exact #30 correction interpretation.

    Always request a fresh F1 assessment projection on return. A user may cancel
    any menu without making a #122 receipt. Post-write uncertainty is not retried.
    """
    services = ports or CorrectionDecisionPorts()
    if (
        not isinstance(inventory, AssessmentAttemptInventory)
        or not isinstance(row, StudentAttemptInventoryRow)
        or sum(student.student_id == row.student_id for student in inventory.students)
        != 1
        or row not in inventory.students
        or inventory.source_status != "current"
        or inventory.membership_state != "included"
        or row.selection_status not in {"no_decision", "selected", "selected_none"}
        or len(row.attempts) < 2
        or not any(item.operative_eligible for item in row.attempts)
    ):
        clear_fn()
        print_menu_header(output, "Correction Review Unavailable")
        write_lines(
            output,
            "Current roster, source, eligibility or selection state is not ready.",
            "Return to assessment eligibility or refresh current evidence.",
            "Nothing was saved or changed.",
        )
        return True
    preset = _single_preset(dependencies)
    if preset is None:
        clear_fn()
        print_menu_header(output, "Correction Review — Policy Needed")
        write_lines(
            output,
            "A qualified exact-one attempt policy is not configured.",
            "Review and select that policy separately in Attempt Setup.",
            "No policy was created or selected here.",
        )
        return True
    original = _choose_observation(
        "Identify Original Observation",
        "Which original attempt did the teacher verify on the source?",
        row.attempts,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if original is None:
        return True
    available = tuple(
        item
        for item in row.attempts
        if item.operative_eligible and item.attempt != original.attempt
    )
    if not available:
        clear_fn()
        print_menu_header(output, "Correction Review — No Eligible Replacement")
        write_lines(
            output,
            "No distinct currently eligible corrected result is available.",
            "Use Assessment Eligibility to review the evidence first.",
            "No attempt selection was saved.",
        )
        return True
    corrected = _choose_observation(
        "Choose Current-Use Correction Result",
        "Choose the result to use; score and sequence cannot choose for you.",
        available,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if corrected is None:
        return True
    clear_fn()
    print_menu_header(output, "Teacher-Reviewed Correction Rationale")
    write_lines(
        output,
        f"Student: {_safe(row.display_label)}",
        f"Original: {_label(original)}",
        f"Current-use result: {_label(corrected)}",
        "This is teacher testimony, NOT producer-certified correction provenance.",
        "Explain what the source inspection established.",
        "",
    )
    # Free-text rationale is NOT a menu command; ':notes', B/M/Q remain literal.
    rationale = read_choice(
        input_fn, "Teacher explanation (required; Enter cancels): "
    ).strip()
    if not rationale:
        write_lines(output, "Cancelled before writing. No decision or receipt created.")
        return True
    try:
        interpretation = services.intention_previewer(
            inventory,
            student_id=row.student_id,
            treatment="teacher_reviewed_correction",
            selected_attempts=(corrected.attempt,),
            original_attempt=original.attempt,
            teacher_rationale=rationale,
        )
        actor = services.actor_loader()
        action = services.resolution_preparer(
            root,
            prepared=prepared,
            interpretation=interpretation,
            preset=preset,
            actor=actor,
            dependencies=dependencies,
        )
    except Exception:
        clear_fn()
        print_menu_header(output, "Correction Decision — Refresh Required")
        write_lines(
            output,
            "The saved teacher attribution, current policy or exact source",
            "could not be verified. Nothing was written by this menu.",
            "Review the prerequisites and return to the assessment.",
        )
        return True
    try:
        review = services.resolution_renderer(action)
    except Exception:
        write_lines(output, "Reviewed action could not be rendered safely; no save.")
        return True
    clear_fn()
    print_menu_header(output, "Review and Use Correction Decision")
    write_lines(
        output,
        review,
        "",
        "1. Save and Use This Decision",
        "2. Cancel without saving",
        "",
    )
    print_standard_navigation(output)
    choice = read_choice(input_fn)
    if choice != "1":
        parse_navigation_choice(choice)  # Allow Core M/Q to unwind; B cancels.
        write_lines(output, "Cancelled before writing. No new decision was saved.")
        return True
    try:
        result = action.apply(confirmed=True)
    except Exception:
        clear_fn()
        print_menu_header(output, "Correction Decision — Outcome Uncertain")
        write_lines(
            output,
            "The canonical action may already have written a decision.",
            "Do not press Save again. Review exact #122 recovery and current state.",
        )
        return True
    clear_fn()
    if (
        result.exact_current
        and result.continue_to_standards_review
        and result.status in {"applied_current", "already_current"}
    ):
        print_menu_header(output, "Correction Decision — Current Verified")
        write_lines(
            output,
            f"Student: {_safe(row.display_label)}",
            "Exactly one reviewed #30 decision is operative current.",
            "Previous source observations remain immutable and auditable.",
            "No ScoreForm result, eligibility, Standard, Grade or report was changed.",
            "Return to the assessment or continue to Standards review.",
        )
    else:
        print_menu_header(output, "Correction Decision — Recovery/Review Required")
        write_lines(
            output,
            f"Outcome: {_safe(str(result.status))}",
            "Current academic use has NOT been independently verified.",
            "Do not repeat Save. Inspect the existing #122 action and canonical state.",
        )
    pause_for_user(input_fn)
    return True


__all__ = (
    "CorrectionDecisionPorts",
    "run_teacher_correction_decision_menu",
)
