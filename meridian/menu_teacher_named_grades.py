"""Read one current Grade through named, verified teacher choices (#123 Slice 5A).

Core owns class, roster, and marking-period identity. Meridian's established
Grade preview loader alone evaluates a Grade, including evidence authorization.
A navigation choice is neither academic authority nor a saved Grade.
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
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceCatalog,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    VerifiedPeriodScope,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_grades import GradePreviewPresentation

CurrentGradeReader: TypeAlias = Callable[
    [Path, str, str, AcademicPeriodRef, int, GradeCalculationFamily],
    "GradePreviewPresentation",
]


class _ScopeChanged(RuntimeError):
    """The exact verified navigation target changed during read-only review."""


def _current_choice(
    catalog: TeacherChoiceCatalog,
    *,
    scope: str,
    selected: dict[str, str],
    choice: TeacherChoice,
) -> None:
    if choice not in load_teacher_choices(catalog, scope=scope, selected=selected):
        raise _ScopeChanged("A chosen record or its currentness witness changed.")


def _marking_period(
    navigation: TeacherNavigationContext,
    catalog: PeriodProficiencyChoiceCatalog,
    *,
    class_id: str,
    root: Path,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[VerifiedPeriodScope, TeacherChoice] | None:
    scope = {"class": class_id}
    existing = navigation.current_period()
    if existing is not None:
        available = load_teacher_choices(catalog, scope="period", selected=scope)
        matches = tuple(
            row for row in available if row.identity == (existing.period_id,)
        )
        if len(matches) != 1 or existing.workspace != root:
            raise _ScopeChanged("Remembered marking period is no longer available.")
        selected = matches[0]
        write_lines(output, f"Using selected marking period: {selected.label}.")
        return existing, selected
    interactive_choice = select_teacher_choice(
        catalog=catalog,
        scope="period",
        selected=scope,
        title="Choose Marking Period",
        question="Which current marking period should this Grade review use?",
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if interactive_choice is None:
        return None
    verified = navigation.choose_period(interactive_choice.identity[0])
    _current_choice(catalog, scope="period", selected=scope, choice=interactive_choice)
    if verified.workspace != root or verified.label != interactive_choice.label:
        raise _ScopeChanged("Marking period changed during selection.")
    return verified, interactive_choice


def _family(
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> GradeCalculationFamily | None:
    families: dict[str, GradeCalculationFamily] = {
        "1": "standards_based",
        "2": "conventional",
        "3": "hybrid",
    }
    while True:
        clear_fn()
        print_menu_header(output, "Choose Grade Calculation")
        write_lines(
            output,
            "1. Standards-based Grade",
            "2. Conventional Grade (requires authorized work evidence)",
            "3. Hybrid Grade (requires authorized work evidence)",
            "B. Back",
            "M. Main Menu",
            "Q. Quit",
        )
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if choice == "" or nav is NavigationChoice.BACK:
            return None
        family = families.get(choice)
        if family is not None:
            return family
        write_lines(output, "Choose 1-3, B, M, or Q.")
        pause_for_user(input_fn)


def _grade_text(value: object) -> str:
    return "No numeric Grade (not zero)" if value is None else str(value)


def run_named_current_grade_review(
    *,
    navigation: TeacherNavigationContext,
    current_grade_loader: CurrentGradeReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Preview one Grade without technical IDs or any academic mutation."""
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
        student = select_teacher_choice(
            catalog=grades,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Which roster student needs a current Grade preview?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return
        if navigation.current_period() != period or navigation.current_class() is None:
            raise _ScopeChanged("The class or calendar changed.")
        _current_choice(
            grades, scope="student", selected={"class": class_id}, choice=student
        )
        _current_choice(
            periods,
            scope="period",
            selected={"class": class_id},
            choice=period_choice,
        )
        value = current_grade_loader(
            root,
            class_id,
            student.identity[0],
            AcademicPeriodRef(period.school_year, period.period_id),
            period.calendar_revision,
            family,
        )
        if (
            getattr(value, "class_id", None) != class_id
            or getattr(value, "student_id", None) != student.identity[0]
            or getattr(value, "school_year", None) != period.school_year
            or getattr(value, "period_id", None) != period.period_id
            or getattr(value, "calendar_revision", None) != period.calendar_revision
            or getattr(value, "family", None) != family
        ):
            raise _ScopeChanged("Grade result does not match the chosen context.")
        if navigation.current_period() != period:
            raise _ScopeChanged("Class or calendar changed during the Grade preview.")
        _current_choice(
            grades, scope="student", selected={"class": class_id}, choice=student
        )
        _current_choice(
            periods,
            scope="period",
            selected={"class": class_id},
            choice=period_choice,
        )
        navigation.session.select_student(student.identity[0])
        clear_fn()
        print_menu_header(output, "Current Grade Review")
        write_lines(
            output,
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Calculation: {family.replace('_', ' ')}",
            f"Policy: {value.policy_title}",
            f"Base status: {value.base_status.replace('_', ' ')}",
            f"Base Grade: {_grade_text(value.base_grade)}",
            f"Effective Grade: {_grade_text(value.effective_grade)}",
            f"Effective source: {value.effective_source.replace('_', ' ')}",
            f"Freshness: {value.freshness_status.replace('_', ' ')}",
            f"Override: {value.override_applicability.replace('_', ' ')}",
        )
        if value.freshness_reasons:
            write_lines(output, "Freshness details:")
            for reason in value.freshness_reasons:
                write_lines(output, f"  - {reason.replace('_', ' ')}")
        write_lines(
            output,
            "",
            "Read-only. No Grade, override, reporting snapshot, or evidence was saved.",
            "For exact record details, use the Advanced Grade preview.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "Class, student, or marking period changed during review.",
            "Nothing was saved. Refresh the selection and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "The current Grade cannot be verified or is not configured "
            "for this selection.",
            "Nothing was saved. Check Grade policy/evidence access "
            "or use Advanced details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_current_grade_review",)
