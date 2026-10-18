"""Teacher-facing Grade Item bridge for Issue #110."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.grade_items import GradeItemPurpose
from meridian.guided_grade_items import (
    GuidedAcademicPeriodChoice,
    GuidedGradeItemBridgeContext,
    GuidedGradeItemBridgeDependencies,
    GuidedGradeItemBridgeError,
    GuidedGradeItemChoice,
    load_guided_grade_item_bridge_context,
    preview_membership_link,
    preview_new_grade_item,
    verify_current_membership_link,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_action_contract import (
    TeacherActionActor,
    teacher_action_outcome_message,
)
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    prepare_grade_item_action,
    prepare_membership_action,
    resolve_menu_actor,
)
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import TeacherActionReceiptError
from meridian.teacher_profile import TeacherProfileError
from meridian.teacher_session import TeacherSessionContext

_PURPOSES: tuple[tuple[str, GradeItemPurpose], ...] = (
    ("Standards proficiency", "standards_proficiency"),
    ("Conventional grade", "conventional_grade"),
    ("Standards + conventional", "standards_and_conventional"),
    ("Reporting only", "reporting_only"),
)


def _show_error(
    error: GuidedGradeItemBridgeError,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Grade Item Setup Unavailable")
    write_lines(
        output,
        "The Grade Item relationship could not be prepared safely.",
        "No relationship was inferred automatically.",
        "",
        f"Details: {error}",
    )
    pause_for_user(input_fn)


def _choose_period(
    periods: tuple[GuidedAcademicPeriodChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedAcademicPeriodChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Academic Period")
        write_lines(
            output,
            "Choose where this work belongs for reporting.",
            "",
        )
        for index, period in enumerate(periods, start=1):
            print(f"{index}. {period.display_label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(periods):
                return periods[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(periods)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_purpose(
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GradeItemPurpose | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Grade Item Purpose")
        for index, (label, _) in enumerate(_PURPOSES, start=1):
            print(f"{index}. {label}", file=output)
        write_lines(
            output,
            "",
            "Weighting is not configured in this bridge.",
            "",
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(_PURPOSES):
                return _PURPOSES[index - 1][1]
        write_lines(output, "", "Please choose 1-4, B, M, or Q.")
        pause_for_user(input_fn)


def _choose_existing_or_new(
    context: GuidedGradeItemBridgeContext,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[str, GuidedGradeItemChoice | None] | None:
    while True:
        clear_fn()
        print_menu_header(output, "Set Up Grade Item Relationship")
        write_lines(
            output,
            f"Work: {context.work_title}",
            "",
            "Choose an existing Grade Item, or create a new one.",
            "",
        )
        for index, choice in enumerate(context.existing_grade_items, start=1):
            print(f"{index}. {choice.display_label}", file=output)
        create_number = len(context.existing_grade_items) + 1
        print(f"{create_number}. Create a new Grade Item", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(context.existing_grade_items):
                return ("existing", context.existing_grade_items[index - 1])
            if index == create_number:
                return ("new", None)
        write_lines(
            output,
            "",
            f"Please choose 1-{create_number}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _create_grade_item(
    root: Path,
    context: GuidedGradeItemBridgeContext,
    teacher: str,
    *,
    actor: TeacherActionActor,
    dependencies: GuidedGradeItemBridgeDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedGradeItemChoice | None:
    clear_fn()
    print_menu_header(output, "Create Grade Item")
    title = read_choice(input_fn, "Grade Item title: ").strip()
    if not title:
        return None
    purpose = _choose_purpose(input_fn=input_fn, output=output, clear_fn=clear_fn)
    if purpose is None:
        return None
    try:
        preview = preview_new_grade_item(
            root,
            context,
            title=title,
            purpose=purpose,
            teacher_attribution=teacher,
            dependencies=dependencies,
        )
        action = prepare_grade_item_action(root, preview, actor, dependencies)
    except (
        GuidedGradeItemBridgeError,
        TeacherActionConflictError,
        TeacherProfileError,
        TeacherActionReceiptError,
        ValueError,
    ) as error:
        _show_error(
            GuidedGradeItemBridgeError(str(error)),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return None
    clear_fn()
    print_menu_header(output, "Review and Save Grade Item")
    write_lines(
        output,
        f"Title: {title}",
        f"Purpose: {purpose.replace('_', ' ').capitalize()}",
        "Weighting: not set",
        "Save creates the immutable Grade Item and makes this exact revision current.",
        "",
        "1. Save and make current",
        "2. Cancel",
    )
    if not _review_apply(action, input_fn=input_fn, output=output, clear_fn=clear_fn):
        return None
    return GuidedGradeItemChoice(
        grade_item_id=preview.candidate.grade_item_id,
        title=title,
        purpose=purpose,
        display_label=title,
        selected_revision=preview.candidate.grade_item_revision,
    )


def _link_work(
    root: Path,
    context: GuidedGradeItemBridgeContext,
    grade_item: GuidedGradeItemChoice,
    period: GuidedAcademicPeriodChoice,
    teacher: str,
    rationale: str | None,
    *,
    actor: TeacherActionActor,
    dependencies: GuidedGradeItemBridgeDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> bool:
    try:
        preview = preview_membership_link(
            root,
            context,
            grade_item,
            period,
            teacher_attribution=teacher,
            rationale=rationale,
            dependencies=dependencies,
        )
        action = prepare_membership_action(root, preview, actor, dependencies)
    except (
        GuidedGradeItemBridgeError,
        TeacherActionConflictError,
        TeacherProfileError,
        TeacherActionReceiptError,
        ValueError,
    ) as error:
        _show_error(
            GuidedGradeItemBridgeError(str(error)),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return False
    clear_fn()
    print_menu_header(output, "Review and Save Grade Item Relationship")
    write_lines(
        output,
        f"Work: {context.work_title}",
        f"Grade Item: {grade_item.display_label}",
        f"Academic Period: {period.display_label}",
    )
    if rationale is not None:
        write_lines(output, f"Rationale: {rationale}")
    write_lines(
        output,
        "",
        "Save writes the included relationship and makes this exact revision current.",
        "",
        "1. Save and make current",
        "2. Cancel",
    )
    if not _review_apply(action, input_fn=input_fn, output=output, clear_fn=clear_fn):
        return False
    # Additional teacher-facing relational verification remains authoritative.
    try:
        valid = verify_current_membership_link(
            root,
            context,
            grade_item.grade_item_id,
            dependencies=dependencies,
        )
    except GuidedGradeItemBridgeError as error:
        _show_error(error, input_fn=input_fn, output=output, clear_fn=clear_fn)
        return False
    if not valid:
        _show_error(
            GuidedGradeItemBridgeError(
                "Saved relationship could not be verified as applicable."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return False
    clear_fn()
    print_menu_header(output, "Grade Item Relationship Ready")
    write_lines(
        output,
        f"Work: {context.work_title}",
        f"Grade Item: {grade_item.display_label}",
        f"Academic Period: {period.label}",
        "",
        "The current included relationship was reloaded and verified.",
    )
    pause_for_user(input_fn)
    return True


def _review_apply(
    action: PreparedGuidedAction,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> bool:
    if read_choice(input_fn) != "1":
        write_lines(
            output, "", "Canceled before saving. No academic write was requested."
        )
        return False
    outcome = action.apply(confirmed=True)
    write_lines(output, "", teacher_action_outcome_message(outcome))
    if outcome.succeeded:
        return True
    if outcome.status == "written_not_current":
        write_lines(
            output,
            "",
            "1. Resume selecting this exact saved decision",
            "2. Leave unselected / review changes later",
        )
        if read_choice(input_fn) == "1":
            resumed = action.resume(confirmed=True)
            write_lines(output, "", teacher_action_outcome_message(resumed))
            if resumed.succeeded:
                return True
    else:
        write_lines(
            output,
            "",
            "The action was not confirmed current.",
            "Review changes or use exact-action recovery before retrying.",
        )
    pause_for_user(input_fn)
    return False


def run_grade_item_bridge(
    *,
    workspace_root: Path,
    work: object,
    session_context: TeacherSessionContext,
    dependencies: GuidedGradeItemBridgeDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> bool:
    """Set up one explicit current included Grade Item relationship."""

    if not hasattr(work, "class_id"):
        return False
    try:
        context = load_guided_grade_item_bridge_context(
            workspace_root,
            work,  # type: ignore[arg-type]
            dependencies=dependencies,
        )
    except GuidedGradeItemBridgeError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return False

    selected = _choose_existing_or_new(
        context,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if selected is None:
        return False

    clear_fn()
    print_menu_header(output, "Grade Item Attribution")
    teacher = read_choice(input_fn, "Teacher name for attribution: ").strip()
    if not teacher:
        write_lines(
            output,
            "",
            "Teacher name is required to attribute a Grade Item relationship.",
            "No Grade Item relationship was changed.",
        )
        pause_for_user(input_fn)
        return False

    try:
        actor = resolve_menu_actor(teacher, input_fn)
    except (TeacherActionConflictError, TeacherProfileError) as error:
        write_lines(output, "", f"Attribution unavailable: {error}")
        pause_for_user(input_fn)
        return False

    mode, grade_item = selected
    if mode == "new":
        grade_item = _create_grade_item(
            workspace_root,
            context,
            teacher,
            actor=actor,
            dependencies=dependencies,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if grade_item is None:
            return False
    assert grade_item is not None
    session_context.select_grade_item(grade_item.grade_item_id)

    period = _choose_period(
        context.periods,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if period is None:
        return False

    clear_fn()
    print_menu_header(output, "Grade Item Relationship Rationale")
    rationale_text = read_choice(input_fn, "Rationale (optional): ").strip()
    rationale = rationale_text or None

    return _link_work(
        workspace_root,
        context,
        grade_item,
        period,
        teacher,
        rationale,
        actor=actor,
        dependencies=dependencies,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


__all__ = ("run_grade_item_bridge",)
