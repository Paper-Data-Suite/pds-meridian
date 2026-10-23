"""Named, bounded read-only Grade report over an exact current Core roster.

Teacher choices are transient hints. The existing Grade report loader retains
all calculation, authorized-evidence and per-student availability decisions.
This module neither persists a report nor changes Grade/override state.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grade_policy import GradeCalculationFamily
from meridian.menu_teacher_named_grades import (
    _current_choice,
    _family,
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
from meridian.teacher_navigation_choices import TeacherChoice, load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_grades import GradeReportPresentation

GradeReportReader: TypeAlias = Callable[
    [
        Path,
        str,
        tuple[str, ...],
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    "GradeReportPresentation",
]

MAX_REPORT_STUDENTS = 50
MAX_SELECTED_STUDENTS = 20
ROWS_PER_PAGE = 10


def _choose_students(
    *,
    catalog: TeacherAcademicChoiceCatalog,
    class_id: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[TeacherChoice, ...] | None:
    """Select a bounded roster or explicitly named subset; do not guess a student."""
    selected_scope = {"class": class_id}
    roster = load_teacher_choices(catalog, scope="student", selected=selected_scope)
    if not roster:
        write_lines(output, "No current roster students are available for review.")
        pause_for_user(input_fn)
        return None
    while True:
        clear_fn()
        print_menu_header(output, "Choose Grade Report Students")
        write_lines(
            output,
            f"Current roster: {len(roster)} students",
            (
                "1. Review the entire current roster"
                if len(roster) <= MAX_REPORT_STUDENTS
                else "1. Entire roster unavailable above the 50-student limit"
            ),
            "2. Choose individual students by name (up to 20)",
            "",
        )
        print_standard_navigation(output)
        response = read_choice(input_fn)
        navigation = parse_navigation_choice(response)
        if navigation is NavigationChoice.BACK or not response:
            return None
        if response == "1":
            if len(roster) > MAX_REPORT_STUDENTS:
                write_lines(output, "Select a smaller student subset instead.")
                pause_for_user(input_fn)
                continue
            return roster
        if response == "2":
            break
        write_lines(output, "Choose 1, 2, B, M, or Q.")
        pause_for_user(input_fn)

    chosen: list[TeacherChoice] = []
    while len(chosen) < MAX_SELECTED_STUDENTS:
        student = select_teacher_choice(
            catalog=catalog,
            scope="student",
            selected=selected_scope,
            title="Choose Report Student",
            question="Choose a current roster student to include.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return None
        if student not in roster or student not in load_teacher_choices(
            catalog, scope="student", selected=selected_scope
        ):
            raise _ScopeChanged("Student changed while building report subset.")
        if student in chosen:
            write_lines(output, "That student is already selected; no duplicate added.")
        else:
            chosen.append(student)
        if len(chosen) == MAX_SELECTED_STUDENTS:
            write_lines(output, "Maximum subset size reached; reviewing selections.")
            break
        clear_fn()
        print_menu_header(output, "Build Grade Report")
        write_lines(output, f"Students chosen: {len(chosen)}")
        for person in chosen:
            write_lines(output, f"  {person.display}")
        write_lines(output, "A. Add another student", "R. Review selected students")
        print_standard_navigation(output)
        while True:
            response = read_choice(input_fn)
            navigation = parse_navigation_choice(response)
            if navigation is NavigationChoice.BACK or not response:
                return None
            if response.casefold() == "a":
                break
            if response.casefold() == "r":
                return tuple(chosen)
            write_lines(output, "Choose A, R, B, M, or Q.")
    return tuple(chosen)


def _validate_scope(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    period: object,
    catalog: TeacherAcademicChoiceCatalog,
    period_catalog: PeriodProficiencyChoiceCatalog,
    period_choice: TeacherChoice,
    students: tuple[TeacherChoice, ...],
) -> None:
    current_class = navigation.current_class()
    if (
        current_class is None
        or current_class.workspace != root
        or current_class.class_id != class_id
    ):
        raise _ScopeChanged("Class changed during report selection.")
    if navigation.current_period() != period:
        raise _ScopeChanged("Marking period changed during report selection.")
    _current_choice(
        period_catalog,
        scope="period",
        selected={"class": class_id},
        choice=period_choice,
    )
    roster_now = load_teacher_choices(
        catalog, scope="student", selected={"class": class_id}
    )
    if not students or len(students) > MAX_REPORT_STUDENTS:
        raise _ScopeChanged("Selected roster is empty or exceeds the report bound.")
    if len({student.identity for student in students}) != len(students):
        raise _ScopeChanged("Selected roster repeated a student identity.")
    if any(student not in roster_now for student in students):
        raise _ScopeChanged("The roster changed during the Grade preview.")


def _validate_report(
    report: GradeReportPresentation,
    *,
    class_id: str,
    student_ids: tuple[str, ...],
    school_year: str,
    period_id: str,
    calendar_revision: int,
    family: GradeCalculationFamily,
) -> None:
    if (
        report.class_id != class_id
        or report.school_year != school_year
        or report.period_id != period_id
        or report.calendar_revision != calendar_revision
        or report.family != family
        or report.requested_count != len(student_ids)
        or len(report.rows) != len(student_ids)
        or len(report.rows) > MAX_REPORT_STUDENTS
        or tuple(row.student_id for row in report.rows) != student_ids
        or report.available_count + report.unavailable_count != len(student_ids)
        or any(row.status not in {"available", "unavailable"} for row in report.rows)
        or sum(row.status == "available" for row in report.rows)
        != report.available_count
    ):
        raise _ScopeChanged("Grade report does not match the requested roster scope.")


def _show_report(
    *,
    report: GradeReportPresentation,
    students: tuple[TeacherChoice, ...],
    period_label: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    pages = (len(students) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
    index = 0
    while True:
        clear_fn()
        print_menu_header(output, "Read-Only Grade Report")
        write_lines(
            output,
            f"Marking period: {period_label}",
            f"Calculation: {report.family.replace('_', ' ')}",
            (
                f"Students: {report.requested_count} selected; "
                f"{report.available_count} available; "
                f"{report.unavailable_count} unavailable"
            ),
            f"Stale selected Grades: {report.stale_count}",
            f"Grades affected by overrides: {report.override_count}",
            f"Page {index + 1} of {pages}",
            "",
        )
        start = index * ROWS_PER_PAGE
        for student, row in zip(
            students[start : start + ROWS_PER_PAGE],
            report.rows[start : start + ROWS_PER_PAGE],
            strict=True,
        ):
            if row.status == "unavailable":
                if row.unavailable_reason == "no_selected_grade":
                    text = "No selected Grade (not zero)"
                else:
                    text = "Unavailable (check Grade policy or evidence access)"
            elif row.effective_grade is None:
                text = "No numeric Grade (not zero)"
            else:
                text = f"Grade {row.effective_grade}"
            if row.freshness_status == "stale":
                text += " · Stale"
            write_lines(output, f"{student.display}: {text}")
        write_lines(
            output,
            "",
            "Read-only preview. No Grade, override, or snapshot was saved.",
        )
        if index < pages - 1:
            write_lines(output, "N. Next page")
        if index > 0:
            write_lines(output, "P. Previous page")
        print_standard_navigation(output)
        response = read_choice(input_fn)
        navigation = parse_navigation_choice(response)
        if navigation is NavigationChoice.BACK or not response:
            return
        if response.casefold() == "n" and index < pages - 1:
            index += 1
        elif response.casefold() == "p" and index > 0:
            index -= 1
        else:
            write_lines(output, "Choose a displayed page shortcut, B, M, or Q.")
            pause_for_user(input_fn)


def run_named_grade_report_review(
    *,
    navigation: TeacherNavigationContext,
    report_loader: GradeReportReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Build and read one Grade report with authoritative named roster selection."""
    try:
        grades = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation, grades, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
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
        students = _choose_students(
            catalog=grades,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if students is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return
        _validate_scope(
            navigation=navigation,
            root=root,
            class_id=class_id,
            period=period,
            catalog=grades,
            period_catalog=periods,
            period_choice=period_choice,
            students=students,
        )
        student_ids = tuple(student.identity[0] for student in students)
        report = report_loader(
            root,
            class_id,
            student_ids,
            AcademicPeriodRef(period.school_year, period.period_id),
            period.calendar_revision,
            family,
        )
        _validate_report(
            report,
            class_id=class_id,
            student_ids=student_ids,
            school_year=period.school_year,
            period_id=period.period_id,
            calendar_revision=period.calendar_revision,
            family=family,
        )
        _validate_scope(
            navigation=navigation,
            root=root,
            class_id=class_id,
            period=period,
            catalog=grades,
            period_catalog=periods,
            period_choice=period_choice,
            students=students,
        )
        _show_report(
            report=report,
            students=students,
            period_label=period.label,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "The roster, class, marking period, or report changed during review.",
            "Nothing was saved. Refresh the choices and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "The Grade report could not be verified safely.",
            "Nothing was saved. Check current Grade policy, authorized evidence, "
            "or Advanced details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_grade_report_review",)
