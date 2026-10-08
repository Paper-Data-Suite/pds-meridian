"""Teacher-facing guided attempt/reassessment continuation for Issue #110."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.guided_attempts import (
    GuidedAttemptActionError,
    GuidedAttemptDependencies,
    GuidedAttemptError,
    GuidedAttemptPolicyPlan,
    GuidedAttemptPolicyPreset,
    GuidedAttemptReview,
    apply_guided_attempt_policy,
    commit_guided_attempt_decision,
    commit_guided_attempt_selection,
    load_guided_attempt_review,
    plan_guided_attempt_policy,
    preview_guided_attempt_decision,
    preview_guided_attempt_selection,
)
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityGradeItemChoice,
    discover_guided_eligibility_grade_items,
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
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


def _choose_grade_item(
    choices: tuple[GuidedEligibilityGradeItemChoice, ...],
    session: TeacherSessionContext,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedEligibilityGradeItemChoice | None:
    active = session.active_grade_item_id
    if active is not None:
        matches = tuple(choice for choice in choices if choice.grade_item_id == active)
        if len(matches) == 1:
            return matches[0]
    if len(choices) == 1:
        session.select_grade_item(choices[0].grade_item_id)
        return choices[0]

    while True:
        clear_fn()
        print_menu_header(output, "Choose Grade Item")
        write_lines(output, "Choose the Grade Item for attempt review.", "")
        for index, choice in enumerate(choices, start=1):
            print(f"{index}. {choice.display_label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices):
                choice = choices[index - 1]
                session.select_grade_item(choice.grade_item_id)
                return choice
        write_lines(
            output,
            "",
            f"Please choose 1-{len(choices)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_policy(
    policies: tuple[GuidedAttemptPolicyPreset, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedAttemptPolicyPreset | None:
    while True:
        clear_fn()
        print_menu_header(output, "Attempt / Reassessment Policy")
        write_lines(
            output,
            "Choose how many attempts this decision may select.",
            "Meridian will not choose a policy for you.",
            "",
        )
        for index, policy in enumerate(policies, start=1):
            print(f"{index}. {policy.title}", file=output)
            print(f"   {policy.description}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(policies):
                return policies[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(policies)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _policy_action_label(plan: GuidedAttemptPolicyPlan) -> str:
    return {
        "ready": "Use current selected policy",
        "create": "Create and select this policy",
        "revise": "Revise and select this policy",
        "select_existing": "Select the existing matching policy",
    }[plan.action]


def _confirm_policy(
    plan: GuidedAttemptPolicyPlan,
    teacher: str,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> bool:
    if plan.action == "ready":
        return True

    clear_fn()
    print_menu_header(output, "Prepare Attempt Policy")
    write_lines(
        output,
        f"Policy: {plan.preset.title}",
        f"Teacher: {teacher}",
        "",
        _policy_action_label(plan) + ".",
        "No policy identifier or revision needs to be entered.",
        "",
        "1. Continue",
        "2. Cancel",
    )
    return read_choice(input_fn) == "1"


def _parse_attempt_numbers(
    raw: str,
    review: GuidedAttemptReview,
) -> tuple[int, ...]:
    if not raw.strip():
        return ()
    indexes: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value.isdigit():
            raise ValueError("Attempt choices must be menu numbers.")
        index = int(value)
        if index < 1 or index > len(review.candidates):
            raise ValueError("Attempt choice is outside the displayed list.")
        if index in indexes:
            raise ValueError("Attempt choices must not contain duplicates.")
        indexes.append(index)
    return tuple(indexes)


def _choose_attempts(
    review: GuidedAttemptReview,
    preset: GuidedAttemptPolicyPreset,
    *,
    subject_label: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[int, ...] | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Attempts / Reassessments")
        write_lines(
            output,
            f"Student: {subject_label}",
            f"Policy: {preset.title}",
            "",
        )
        for index, candidate in enumerate(review.candidates, start=1):
            print(f"{index}. {candidate.label}", file=output)
            print(
                f"   {candidate.eligible_evidence_count} eligible evidence row(s)",
                file=output,
            )
        write_lines(
            output,
            "",
            "Enter menu numbers separated by commas.",
            "Leave blank only when the selected policy allows no attempts.",
            "B. Back",
            "M. Main Menu",
            "Q. Quit",
        )
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK:
            return None
        try:
            return _parse_attempt_numbers(raw, review)
        except ValueError as error:
            write_lines(output, "", str(error))
            pause_for_user(input_fn)


def _show_blocker(
    title: str,
    *lines: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, title)
    write_lines(output, *lines)
    pause_for_user(input_fn)


def _show_error(
    error: GuidedAttemptError,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    _show_blocker(
        "Attempt Review Unavailable",
        "Attempt/reassessment continuation could not proceed safely.",
        "No attempt decision was changed.",
        "",
        f"Details: {error}",
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


def run_guided_attempt_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    subject_label: str,
    session_context: TeacherSessionContext,
    dependencies: GuidedAttemptDependencies,
    eligibility_dependencies: GuidedEligibilityDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Run teacher-guided policy, attempt decision, write, and selection."""

    if evidence.student_id is None:
        _show_blocker(
            "Student Attempt Review Not Applicable",
            "Shared evidence does not carry a roster student.",
            "Choose student-specific evidence to review attempts.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    try:
        work = prepared.authorized.current_context.publication.work
        grade_items = discover_guided_eligibility_grade_items(
            workspace_root,
            work,
            dependencies=eligibility_dependencies,
        )
    except GuidedAttemptError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    except Exception as error:
        _show_error(
            GuidedAttemptActionError(str(error)),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if not grade_items:
        _show_blocker(
            "Grade Item Relationship Needed",
            "Attempt review requires a current included Grade Item relationship.",
            "Meridian will not infer or create that relationship automatically.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    grade_item = _choose_grade_item(
        grade_items,
        session_context,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if grade_item is None:
        return

    policy = _choose_policy(
        dependencies.policies,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if policy is None:
        return

    clear_fn()
    print_menu_header(output, "Attempt Decision Attribution")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Grade Item: {grade_item.display_label}",
        f"Policy: {policy.title}",
        "",
    )
    teacher = read_choice(input_fn, "Teacher name for attribution: ").strip()
    if not teacher:
        write_lines(output, "", "Attempt decision was not changed.")
        pause_for_user(input_fn)
        return

    try:
        plan = plan_guided_attempt_policy(
            workspace_root,
            class_id=work.class_id,
            grade_item_id=grade_item.grade_item_id,
            work=work,
            preset=policy,
            dependencies=dependencies,
        )
        if not _confirm_policy(
            plan,
            teacher,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        ):
            return
        apply_guided_attempt_policy(
            workspace_root,
            class_id=work.class_id,
            grade_item_id=grade_item.grade_item_id,
            work=work,
            plan=plan,
            teacher_attribution=teacher,
            dependencies=dependencies,
        )
        review = load_guided_attempt_review(
            workspace_root,
            prepared=prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            dependencies=dependencies,
        )
    except GuidedAttemptError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if review.status == "not_applicable":
        _show_blocker(
            "Attempt Review Not Applicable",
            "This publication does not declare multiple-attempt capability.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    if review.status == "unsupported_attempt_shape":
        _show_blocker(
            "Attempt Review Not Available",
            "Current producer attempt context cannot be represented safely.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    if review.status == "stale":
        _show_blocker(
            "Attempt Review Needs Refresh",
            "Current attempt decision state is stale.",
            "Return to evidence review and reload current state.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    if not review.candidates:
        _show_blocker(
            "No Eligible Attempts Yet",
            "No attempt candidates currently have operative included evidence.",
            "Resolve evidence eligibility before creating an attempt decision.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    indexes = _choose_attempts(
        review,
        policy,
        subject_label=subject_label,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if indexes is None:
        return
    selected_attempts = tuple(
        review.candidates[index - 1].attempt for index in indexes
    )

    clear_fn()
    print_menu_header(output, "Attempt Decision Rationale")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Policy: {policy.title}",
        "",
    )
    rationale_text = read_choice(input_fn, "Rationale (optional): ").strip()
    rationale = rationale_text or None

    try:
        preview = preview_guided_attempt_decision(
            workspace_root,
            prepared=prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            preset=policy,
            selected_attempts=selected_attempts,
            teacher_attribution=teacher,
            rationale=rationale,
            dependencies=dependencies,
        )
    except GuidedAttemptError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Review Attempt Decision Before Write")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Grade Item: {grade_item.display_label}",
        f"Policy: {policy.title}",
        f"Selected attempts: {len(selected_attempts)}",
        f"Available attempts: {len(review.candidates)}",
    )
    for index in indexes:
        write_lines(output, f"  {review.candidates[index - 1].label}")
    if rationale is not None:
        write_lines(output, f"Rationale: {rationale}")
    write_lines(
        output,
        "",
        "Writing creates one immutable attempt decision.",
        "It does not make that decision current until you select it.",
        "",
        "1. Write this decision",
        "2. Cancel",
    )
    if read_choice(input_fn) != "1":
        write_lines(output, "", "No attempt decision was written.")
        pause_for_user(input_fn)
        return

    try:
        written = commit_guided_attempt_decision(
            workspace_root,
            prepared=prepared,
            preview=preview,
            dependencies=dependencies,
        )
        selection_preview = preview_guided_attempt_selection(
            workspace_root,
            prepared=prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            written_revision=written.written_revision,
            dependencies=dependencies,
        )
    except GuidedAttemptError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Make Attempt Decision Current")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Selected attempts: {len(selected_attempts)}",
        "",
        "The decision was written but is not current yet.",
        "",
        "1. Make this decision current",
        "2. Leave it unselected",
    )
    if read_choice(input_fn) != "1":
        write_lines(
            output,
            "",
            "The attempt decision remains written but unselected.",
        )
        pause_for_user(input_fn)
        return

    try:
        commit_guided_attempt_selection(
            workspace_root,
            prepared=prepared,
            preview=selection_preview,
            dependencies=dependencies,
        )
        refreshed = load_guided_attempt_review(
            workspace_root,
            prepared=prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            dependencies=dependencies,
        )
    except GuidedAttemptError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Attempt Decision Updated")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Current selected attempts: {refreshed.selected_count}",
        "",
        "Current canonical attempt state was reloaded after selection.",
    )
    pause_for_user(input_fn)


__all__ = ("run_guided_attempt_menu",)
