"""Named explanation of one current Grade (#123 Slice 9A).

The selected class, marking period and student are reverified from Core.
The existing Meridian explanation provider remains the academic authority.
Canonical IDs are technical details, not ordinary teacher-facing questions.
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
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation

CurrentExplanationReader: TypeAlias = Callable[
    [Path, str, str, AcademicPeriodRef, int, GradeCalculationFamily],
    "ExplanationPresentation",
]


class _ExplanationChanged(RuntimeError):
    """Verified selection or the academic explanation no longer matches."""


def _check_explanation(
    value: "ExplanationPresentation",
    *,
    class_id: str,
    student_id: str,
    school_year: str,
    period_id: str,
    revision: int,
    family: GradeCalculationFamily,
) -> None:
    """Bind the read-only presentation back to canonical source identity."""
    lines = value.lines
    technical = value.technical_lines
    if (
        value.title != "Current Grade Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or any(not isinstance(line, str) for line in (*lines, *technical))
        or lines.count(f"Student: {student_id}") != 1
        or lines.count(f"Academic Period: {school_year} / {period_id}") != 1
        or lines.count(f"Calculation family: {family.replace('_', ' ')}") != 1
        or technical.count(f"class_id: {class_id}") != 1
        or technical.count(f"student_id: {student_id}") != 1
        or technical.count(f"calendar_revision: {revision}") != 1
    ):
        raise _ExplanationChanged("Grade explanation refers to another scope.")


def run_named_current_grade_explanation(
    *,
    navigation: TeacherNavigationContext,
    current_grade_explainer: CurrentExplanationReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Explain one current Grade without canonical-ID input or any writes."""
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
            raise _ExplanationChanged("The verified class changed.")
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
            title="Choose Student",
            question="Which roster student's current Grade should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return

        def check_scope() -> None:
            current = navigation.current_class()
            if (
                current is None
                or current != initial_class
                or navigation.current_period() != period
                or period.workspace != root
                or period.class_id != class_id
                or period.school_year != initial_class.school_year
            ):
                raise _ExplanationChanged("The class or marking period changed.")
            _current_choice(
                classes,
                scope="student",
                selected={"class": class_id},
                choice=student,
            )
            _current_choice(
                periods,
                scope="period",
                selected={"class": class_id},
                choice=period_choice,
            )

        check_scope()
        explanation = current_grade_explainer(
            root,
            class_id,
            student.identity[0],
            AcademicPeriodRef(period.school_year, period.period_id),
            period.calendar_revision,
            family,
        )
        _check_explanation(
            explanation,
            class_id=class_id,
            student_id=student.identity[0],
            school_year=period.school_year,
            period_id=period.period_id,
            revision=period.calendar_revision,
            family=family,
        )
        check_scope()
        # Explanations include exact student and academic-period IDs for Advanced.
        # Replace those two ordinary display lines with verified human labels.
        ordinary = tuple(
            line
            for line in explanation.lines
            if line != f"Student: {student.identity[0]}"
            and line != f"Academic Period: {period.school_year} / {period.period_id}"
        )
        while True:
            check_scope()
            clear_fn()
            print_menu_header(output, "Current Grade Explanation")
            write_lines(
                output,
                f"Student: {student.label}",
                f"Marking period: {period.label}",
                *ordinary,
                "",
                "Read-only explanation; no Grade or evidence record was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                check_scope()
                clear_fn()
                print_menu_header(output, "Current Grade — Technical Provenance")
                write_lines(output, *explanation.technical_lines)
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or choice == "":
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ExplanationChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, student, marking period, or Grade explanation changed.",
            "No academic record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "The current Grade explanation is unavailable for this selection.",
            "No academic record was changed. Check policy/evidence access or Advanced.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_current_grade_explanation",)
