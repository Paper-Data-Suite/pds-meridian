"""Teacher-facing guided Standard association continuation for Issue #110."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityError,
    GuidedEligibilityGradeItemChoice,
    discover_guided_eligibility_grade_items,
)
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.guided_proficiency import GuidedProficiencyDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import (
    GuidedScaleChoice,
    GuidedStandardChoice,
    GuidedStandardChoices,
    GuidedStandardsDependencies,
    GuidedStandardsError,
    build_guided_standards_projection,
    commit_guided_standard_association,
    commit_guided_standard_selection,
    load_guided_scale_choices,
    load_guided_standard_choices,
    preview_guided_standard_association,
    preview_guided_standard_selection,
    reload_guided_standards_projection,
)
from meridian.menu_teacher_grade_items import run_grade_item_bridge
from meridian.menu_teacher_proficiency import run_guided_proficiency_menu
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.standards_association_authoring_workflow import (
    StandardsAssociationBasis,
    StandardsAssociationDisposition,
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
        write_lines(output, "Choose the Grade Item for Standard review.", "")
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


def _choose_scale(
    choices: tuple[GuidedScaleChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedScaleChoice | None:
    if len(choices) == 1:
        return choices[0]
    while True:
        clear_fn()
        print_menu_header(output, "Choose Proficiency Scale")
        write_lines(
            output,
            "Choose the current scale context for this Standard review.",
            "",
        )
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
                return choices[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(choices)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_from_list(
    title: str,
    choices: tuple[GuidedStandardChoice, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedStandardChoice | None:
    page_size = 10
    page = 0
    while True:
        start = page * page_size
        visible = choices[start : start + page_size]
        clear_fn()
        print_menu_header(output, title)
        write_lines(
            output,
            f"Showing {start + 1}-{start + len(visible)} of {len(choices)}.",
            "",
        )
        for index, choice in enumerate(visible, start=1):
            suffix = " · Producer-declared" if choice.producer_declared else ""
            print(f"{index}. {choice.label}{suffix}", file=output)
        write_lines(output, "")
        if start + page_size < len(choices):
            print("N. Next page", file=output)
        if page > 0:
            print("P. Previous page", file=output)
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.casefold() == "n" and start + page_size < len(choices):
            page += 1
            continue
        if raw.casefold() == "p" and page > 0:
            page -= 1
            continue
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(visible):
                return visible[index - 1]
        write_lines(
            output,
            "",
            f"Please choose 1-{len(visible)}, N, P, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_standard(
    choices: GuidedStandardChoices,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GuidedStandardChoice | None:
    while True:
        clear_fn()
        print_menu_header(output, "Choose Standard")
        if choices.declared:
            write_lines(output, "Producer-declared Standards:", "")
            for index, choice in enumerate(choices.declared, start=1):
                print(f"{index}. {choice.label}", file=output)
            browse_number = len(choices.declared) + 1
            print(
                f"{browse_number}. Browse all active Standards",
                file=output,
            )
        else:
            browse_number = 1
            write_lines(
                output,
                "This evidence declares no resolvable Standards.",
                "",
                "1. Browse all active Standards",
            )
        if choices.unresolved_declared_ids:
            write_lines(
                output,
                "",
                (
                    f"{len(choices.unresolved_declared_ids)} producer-declared "
                    "Standard reference(s) cannot be resolved."
                ),
            )
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices.declared):
                return choices.declared[index - 1]
            if index == browse_number:
                if not choices.active:
                    write_lines(
                        output,
                        "",
                        "No active Standards are available to browse.",
                    )
                    pause_for_user(input_fn)
                    continue
                return _choose_from_list(
                    "Browse Active Standards",
                    choices.active,
                    input_fn=input_fn,
                    output=output,
                    clear_fn=clear_fn,
                )
        upper = browse_number
        write_lines(
            output,
            "",
            f"Please choose 1-{upper}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def _choose_disposition(
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> StandardsAssociationDisposition | None:
    while True:
        clear_fn()
        print_menu_header(output, "Standard Association Decision")
        write_lines(
            output,
            "Does this evidence belong to the selected Standard?",
            "",
            "1. Associated",
            "2. Not associated",
            "",
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw == "1":
            return "associated"
        if raw == "2":
            return "not_associated"
        write_lines(output, "", "Please choose 1, 2, B, M, or Q.")
        pause_for_user(input_fn)


def _choose_basis(
    standard: GuidedStandardChoice,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> StandardsAssociationBasis | None:
    if not standard.producer_declared:
        return "explicit"

    while True:
        clear_fn()
        print_menu_header(output, "Association Basis")
        write_lines(
            output,
            "Choose the basis for this teacher decision.",
            "",
            "1. Producer-declared alignment",
            "2. Explicit teacher judgment",
            "",
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return None
        if raw == "1":
            return "producer_declared"
        if raw == "2":
            return "explicit"
        write_lines(output, "", "Please choose 1, 2, B, M, or Q.")
        pause_for_user(input_fn)


def _humanize(value: str | None) -> str:
    if value is None:
        return "No decision"
    return value.replace("_", " ").capitalize()


def _show_error(
    error: GuidedStandardsError,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Standard Review Unavailable")
    write_lines(
        output,
        "Standard association continuation could not proceed safely.",
        "No Standard association state was changed.",
        "",
        f"Details: {error}",
    )
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


def run_guided_standard_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    subject_label: str,
    session_context: TeacherSessionContext,
    dependencies: GuidedStandardsDependencies,
    eligibility_dependencies: GuidedEligibilityDependencies,
    grade_item_bridge_dependencies: GuidedGradeItemBridgeDependencies | None = None,
    proficiency_dependencies: GuidedProficiencyDependencies | None = None,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Run teacher-guided Standard association preview/write/select."""

    if evidence.student_id is None:
        _show_blocker(
            "Student Standard Review Not Applicable",
            "Shared evidence does not carry a roster student.",
            "Choose student-specific evidence for Standard association.",
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
        standards = load_guided_standard_choices(
            workspace_root,
            evidence,
            dependencies=dependencies,
        )
        scales = load_guided_scale_choices(
            workspace_root,
            work.class_id,
            dependencies=dependencies,
        )
    except GuidedStandardsError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    except GuidedEligibilityError as error:
        _show_error(
            GuidedStandardsError(str(error)),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    if not grade_items:
        if grade_item_bridge_dependencies is None:
            _show_blocker(
                "Grade Item Relationship Needed",
                "Standard review requires a current included Grade Item relationship.",
                "Meridian will not infer or create that relationship automatically.",
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
        grade_items = discover_guided_eligibility_grade_items(
            workspace_root,
            work,
            dependencies=eligibility_dependencies,
        )
        if not grade_items:
            return
    if not scales:
        _show_blocker(
            "Proficiency Scale Needed",
            "Standard review requires a current proficiency scale context.",
            "Create/select a class proficiency scale before continuing.",
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

    standard = _choose_standard(
        standards,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if standard is None:
        return

    scale = _choose_scale(
        scales,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if scale is None:
        return

    try:
        projection = build_guided_standards_projection(
            workspace_root,
            prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            evidence=evidence,
            standard=standard,
            scale=scale,
            dependencies=dependencies,
        )
    except GuidedStandardsError as error:
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

    basis = _choose_basis(
        standard,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if basis is None:
        return

    clear_fn()
    print_menu_header(output, "Standard Association Attribution")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Standard: {standard.label}",
        f"Scale context: {scale.display_label}",
        "",
    )
    teacher = read_choice(input_fn, "Teacher name for attribution: ").strip()
    if not teacher:
        write_lines(output, "", "Standard association was not changed.")
        pause_for_user(input_fn)
        return
    rationale_text = read_choice(input_fn, "Rationale (optional): ").strip()
    rationale = rationale_text or None

    try:
        preview = preview_guided_standard_association(
            workspace_root,
            prepared,
            projection,
            disposition=disposition,
            basis=basis,
            teacher_attribution=teacher,
            rationale=rationale,
            dependencies=dependencies,
        )
    except GuidedStandardsError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Review Standard Association Before Write")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Evidence: {evidence.evidence_label}",
        f"Standard: {standard.label}",
        f"Scale context: {scale.display_label}",
        f"Current association: {_humanize(projection.association_disposition)}",
        f"New decision: {_humanize(disposition)}",
        (
            "Basis: Producer-declared alignment"
            if basis == "producer_declared"
            else "Basis: Explicit teacher judgment"
        ),
        f"Teacher: {teacher}",
    )
    if rationale is not None:
        write_lines(output, f"Rationale: {rationale}")
    write_lines(
        output,
        "",
        "Writing creates one immutable Standard association decision.",
        "It does not make that decision current until you select it.",
        "",
        "1. Write this decision",
        "2. Cancel",
    )
    if read_choice(input_fn) != "1":
        write_lines(output, "", "No Standard association was written.")
        pause_for_user(input_fn)
        return

    try:
        written = commit_guided_standard_association(
            workspace_root,
            prepared,
            preview,
            dependencies=dependencies,
        )
        selection_preview = preview_guided_standard_selection(
            workspace_root,
            prepared,
            projection,
            written.written_revision,
            dependencies=dependencies,
        )
    except GuidedStandardsError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Make Standard Association Current")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Standard: {standard.label}",
        f"Decision: {_humanize(disposition)}",
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
            "The Standard association remains written but unselected.",
        )
        pause_for_user(input_fn)
        return

    try:
        commit_guided_standard_selection(
            workspace_root,
            prepared,
            selection_preview,
            dependencies=dependencies,
        )
        refreshed = reload_guided_standards_projection(
            workspace_root,
            prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            evidence=evidence,
            standard=standard,
            scale=scale,
        )
    except GuidedStandardsError as error:
        _show_error(
            error,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return

    clear_fn()
    print_menu_header(output, "Standard Association Updated")
    write_lines(
        output,
        f"Student: {subject_label}",
        f"Standard: {standard.label}",
        f"Current association: {_humanize(refreshed.association_disposition)}",
        "",
        "Current canonical Standard association state was reloaded.",
    )
    if (
        refreshed.association_disposition == "associated"
        and proficiency_dependencies is not None
    ):
        write_lines(
            output,
            "",
            "Recommended next step:",
            "1. Preview proficiency",
            "2. Finish for now",
        )
        if read_choice(input_fn) == "1":
            run_guided_proficiency_menu(
                workspace_root=workspace_root,
                prepared=prepared,
                evidence=evidence,
                subject_label=subject_label,
                grade_item_id=grade_item.grade_item_id,
                grade_item_label=grade_item.display_label,
                standard=standard,
                scale=scale,
                dependencies=proficiency_dependencies,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
        return
    pause_for_user(input_fn)


__all__ = ("run_guided_standard_menu",)
