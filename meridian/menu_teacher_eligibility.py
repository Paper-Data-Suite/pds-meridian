"""Teacher-facing guided eligibility continuation for Issue #110."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityError,
    GuidedEligibilityGradeItemChoice,
    GuidedEligibilityPolicyChoice,
    commit_guided_eligibility,
    commit_guided_eligibility_selection,
    discover_guided_eligibility_grade_items,
    load_guided_eligibility_context,
    preview_guided_eligibility,
    preview_guided_eligibility_selection,
)
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_grade_items import run_grade_item_bridge
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.new_evidence_eligibility_workflow import TeacherEligibilityDisposition
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


def _humanize(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _choose_grade_item(
    choices: tuple[GuidedEligibilityGradeItemChoice, ...],
    session: TeacherSessionContext,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedEligibilityGradeItemChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Grade Item")
        write_lines(
            output,
            "Choose the Grade Item this evidence belongs to.",
            "Only current included relationships are shown.",
            "",
        )
        for index, choice in enumerate(choices, start=1):
            suffix = (
                " · Current Grade Item"
                if session.active_grade_item_id == choice.grade_item_id
                else ""
            )
            print(f"{index}. {choice.display_label}{suffix}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            choice_index = int(raw)
            if 1 <= choice_index <= len(choices):
                choice = choices[choice_index - 1]
                session.select_grade_item(choice.grade_item_id)
                return choice
        write_lines(
            output,
            "",
            f"Please choose 1-{len(choices)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_policy(
    policies: tuple[GuidedEligibilityPolicyChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedEligibilityPolicyChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Eligibility Policy")
        write_lines(output, "Choose a teacher-facing policy.", "")
        for index, policy in enumerate(policies, start=1):
            print(f"{index}. {policy.title}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            choice_index = int(raw)
            if 1 <= choice_index <= len(policies):
                return policies[choice_index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(policies)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_disposition(
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> TeacherEligibilityDisposition | None:
    choices: tuple[tuple[str, TeacherEligibilityDisposition], ...] = (
        ("Included", "included"),
        ("Excluded", "excluded"),
        ("Pending", "pending"),
        ("Unsupported", "unsupported"),
    )
    while True:
        clear_fn()
        print_menu_header(output, "Eligibility Decision")
        write_lines(
            output,
            "Choose the academic eligibility decision.",
            "Meridian will not choose this for you.",
            "",
        )
        for index, (label, _) in enumerate(choices, start=1):
            print(f"{index}. {label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            choice_index = int(raw)
            if 1 <= choice_index <= len(choices):
                return choices[choice_index - 1][1]
        write_lines(output, "", "Please choose 1-4, B, M, or Q.")
        pause_for_user(input_fn)


def _show_grade_item_required(
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Grade Item Relationship Needed")
    write_lines(
        output,
        "This work is not currently included in an active Grade Item.",
        "",
        "Meridian will not infer or create that relationship automatically.",
        "Finish for now, or manage the Grade Item relationship separately.",
    )
    pause_for_user(input_fn)


def _show_error(
    error: GuidedEligibilityError,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Eligibility Unavailable")
    write_lines(
        output,
        "Eligibility continuation could not proceed safely.",
        "No eligibility state was changed.",
        "",
        f"Details: {error}",
    )
    pause_for_user(input_fn)


def run_guided_eligibility_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    subject_label: str,
    session_context: TeacherSessionContext,
    dependencies: GuidedEligibilityDependencies,
    grade_item_bridge_dependencies: GuidedGradeItemBridgeDependencies | None = None,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Run one explicit preview/write/select eligibility continuation."""

    try:
        work = prepared.authorized.current_context.publication.work
        grade_items = discover_guided_eligibility_grade_items(
            workspace_root,
            work,
            dependencies=dependencies,
        )
    except GuidedEligibilityError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if not grade_items:
        if grade_item_bridge_dependencies is None:
            _show_grade_item_required(
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            return
        created = run_grade_item_bridge(
            workspace_root=workspace_root,
            work=work,
            session_context=session_context,
            dependencies=grade_item_bridge_dependencies,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if not created:
            return
        try:
            grade_items = discover_guided_eligibility_grade_items(
                workspace_root,
                work,
                dependencies=dependencies,
            )
        except GuidedEligibilityError as error:
            _show_error(
                error,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            return
        if not grade_items:
            _show_grade_item_required(
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

    try:
        context = load_guided_eligibility_context(
            workspace_root,
            prepared,
            grade_item,
            item_id=evidence.item_id,
            dependencies=dependencies,
        )
    except GuidedEligibilityError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    disposition = _choose_disposition(
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if disposition is None:
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
    print_menu_header(output, "Eligibility Attribution")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Grade Item: {grade_item.display_label}",
        "",
    )
    teacher = read_choice(input_fn, "Teacher name for attribution: ").strip()
    if not teacher:
        write_lines(output, "", "Eligibility was not changed.")
        pause_for_user(input_fn)
        return
    rationale_text = read_choice(input_fn, "Rationale (optional): ").strip()
    rationale = rationale_text or None

    try:
        preview = preview_guided_eligibility(
            workspace_root,
            prepared,
            context,
            disposition=disposition,
            teacher_attribution=teacher,
            policy=policy,
            rationale=rationale,
            dependencies=dependencies,
        )
    except GuidedEligibilityError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Review Eligibility Before Write")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Grade Item: {grade_item.display_label}",
        f"Current eligibility: {_humanize(context.current_status)}",
        f"New decision: {_humanize(disposition)}",
        f"Policy: {policy.title}",
        f"Teacher: {teacher}",
    )
    if rationale is not None:
        write_lines(output, f"Rationale: {rationale}")
    write_lines(
        output,
        "",
        "Writing creates one immutable eligibility decision.",
        "It does not make that decision current until you select it.",
        "",
        "1. Write this decision",
        "2. Cancel",
    )
    raw = read_choice(input_fn)
    if raw != "1":
        write_lines(output, "", "No eligibility decision was written.")
        pause_for_user(input_fn)
        return

    try:
        written = commit_guided_eligibility(
            workspace_root,
            prepared,
            preview,
            dependencies=dependencies,
        )
        selection_preview = preview_guided_eligibility_selection(
            workspace_root,
            prepared,
            context,
            written.written_revision,
            dependencies=dependencies,
        )
    except GuidedEligibilityError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Make Eligibility Current")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Decision: {_humanize(disposition)}",
        "",
        "The decision was written but is not current yet.",
        "",
        "1. Make this decision current",
        "2. Leave it unselected",
    )
    raw = read_choice(input_fn)
    if raw != "1":
        write_lines(
            output,
            "",
            "The eligibility decision remains written but unselected.",
        )
        pause_for_user(input_fn)
        return

    try:
        commit_guided_eligibility_selection(
            workspace_root,
            prepared,
            selection_preview,
            dependencies=dependencies,
        )
        refreshed = load_guided_eligibility_context(
            workspace_root,
            prepared,
            grade_item,
            item_id=evidence.item_id,
            dependencies=dependencies,
        )
    except GuidedEligibilityError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Eligibility Updated")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Current eligibility: {_humanize(refreshed.current_status)}",
        "",
        "Current canonical state was reloaded after selection.",
    )
    pause_for_user(input_fn)


__all__ = ("run_guided_eligibility_menu",)
