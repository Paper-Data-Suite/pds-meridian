"""Teacher-named, read-only Academic Period proficiency explanation (#123 Slice 9D).

Core verifies the class, marking period and student; Meridian's selected-result
catalog binds one Standard to an exact revision and digest. The existing #42
period explanation service exclusively owns academic content and provenance.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.menu_teacher_named_explain_item_proficiency import (
    _ItemExplanationChanged,
    _selected_result_witness,
)
from meridian.menu_teacher_named_grades import (
    _current_choice,
    _marking_period,
    _ScopeChanged,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation

AcademicPeriodExplanationReader: TypeAlias = Callable[
    [Path, str, str, str, str, str], "ExplanationPresentation"
]


class _PeriodExplanationChanged(RuntimeError):
    """A named choice, current result or provenance no longer matches."""


def _checked_ordinary_lines(
    value: "ExplanationPresentation",
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    calendar_revision: int,
    period_label: str,
    student: TeacherChoice,
    standard: TeacherChoice,
) -> tuple[str, ...]:
    """Bind both presentation and exact result witness before displaying names."""
    revision, digest = _selected_result_witness(standard)
    lines = value.lines
    technical = value.technical_lines
    old_period = f"Academic Period: {period_label}"
    old_student = f"Student: {student.identity[0]}"
    old_standard = f"Standard: {standard.identity[0]}"
    required_technical = (
        f"class_id: {class_id}",
        f"school_year: {school_year}",
        f"period_id: {period_id}",
        f"calendar_revision: {calendar_revision}",
        f"student_id: {student.identity[0]}",
        f"standard_id: {standard.identity[0]}",
        f"result_revision: {revision}",
        f"result_sha256: {digest}",
    )
    prefixes = (
        "Result: ",
        "Proficiency: ",
        "Policy: ",
        "Grade Items: ",
        "Selection state: ",
    )
    if (
        value.title != "Academic Period Proficiency Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or any(
            not isinstance(line, str) or "\n" in line or "\r" in line
            for line in (*lines, *technical)
        )
        or len(lines) != 8
        or lines[:3] != (old_period, old_student, old_standard)
        or any(
            not line.startswith(prefix) or not line[len(prefix) :]
            for line, prefix in zip(lines[3:], prefixes)
        )
        or lines[-1] != "Selection state: selected current"
        or any(technical.count(item) != 1 for item in required_technical)
    ):
        raise _PeriodExplanationChanged(
            "Explanation is not the selected current result."
        )
    # Only the five controlled academic summary fields reach ordinary output;
    # canonical student, Standard, period and digest remain in the T view.
    return lines[3:]


def run_named_academic_period_proficiency_explanation(
    *,
    navigation: TeacherNavigationContext,
    academic_period_explainer: AcademicPeriodExplanationReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Explain one verified selected period result without technical-ID input."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        initial_class = navigation.current_class()
        if (
            initial_class is None
            or initial_class.workspace != root
            or initial_class.class_id != class_id
        ):
            raise _PeriodExplanationChanged("Verified class changed.")
        chosen_period = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen_period is None:
            return
        period, period_choice = chosen_period
        student = select_teacher_choice(
            catalog=classes,
            scope="student",
            selected={"class": class_id},
            title="Choose Roster Student",
            question="Whose marking-period proficiency should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        result_scope = {
            "class": class_id,
            "period": period.period_id,
            "student": student.identity[0],
        }
        standard = select_teacher_choice(
            catalog=periods,
            scope="period_standard",
            selected=result_scope,
            title="Choose Current Marking-Period Standard",
            question=(
                "Which Standard has an existing selected period result? "
                "No result is not a zero."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if standard is None:
            return

        def check_scope() -> None:
            if (
                navigation.current_class() != initial_class
                or navigation.current_period() != period
                or period.workspace != root
                or period.class_id != class_id
                or period.school_year != initial_class.school_year
            ):
                raise _PeriodExplanationChanged("Verified period or class changed.")
            for catalog, scope, selected, choice in (
                (periods, "period", {"class": class_id}, period_choice),
                (classes, "student", {"class": class_id}, student),
                (periods, "period_standard", result_scope, standard),
            ):
                _current_choice(catalog, scope=scope, selected=selected, choice=choice)
            _selected_result_witness(standard)

        check_scope()
        value = academic_period_explainer(
            root,
            class_id,
            period.school_year,
            period.period_id,
            student.identity[0],
            standard.identity[0],
        )
        ordinary = _checked_ordinary_lines(
            value,
            class_id=class_id,
            school_year=period.school_year,
            period_id=period.period_id,
            calendar_revision=period.calendar_revision,
            period_label=period.label,
            student=student,
            standard=standard,
        )
        check_scope()
        while True:
            check_scope()
            clear_fn()
            print_menu_header(output, "Academic Period Proficiency Explanation")
            write_lines(
                output,
                f"Marking period: {period.label}",
                f"Student: {student.label}",
                standard.label,
                *ordinary,
                "",
                "An absent or insufficient proficiency result is not zero.",
                "Read-only explanation; no academic record was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                check_scope()
                clear_fn()
                print_menu_header(output, "Period Proficiency — Technical Provenance")
                write_lines(output, *value.technical_lines)
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or choice == "":
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_PeriodExplanationChanged, _ScopeChanged, _ItemExplanationChanged):
        write_lines(
            output,
            "Class, marking period, student, Standard, or selected result changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Academic Period proficiency explanation could not be verified safely.",
            "No record was changed. Check permissions or Advanced diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_academic_period_proficiency_explanation",)
