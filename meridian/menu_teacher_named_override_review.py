"""Read-only current Grade override review with named Core scope (#123 Slice 6A).

The shared navigation choices are hints, not authority. The original override
review loader remains the canonical reader. No selection, authoring, grading,
or receipt is performed in this module.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

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
    write_lines,
)
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    VerifiedPeriodScope,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_overrides import OverrideReviewPresentation, OverrideScope

OverrideReader: TypeAlias = Callable[
    [Path, "OverrideScope"], "OverrideReviewPresentation"
]


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    school_year: str,
    period: VerifiedPeriodScope,
    period_choice: TeacherChoice,
    student: TeacherChoice,
    class_catalog: TeacherAcademicChoiceCatalog,
    period_catalog: PeriodProficiencyChoiceCatalog,
) -> None:
    current = navigation.current_class()
    if (
        current is None
        or current.workspace != root
        or current.class_id != class_id
        or current.school_year != school_year
        or navigation.current_period() != period
    ):
        raise _ScopeChanged("Class or period changed during review.")
    if not isinstance(period_choice, TeacherChoice) or not isinstance(
        student, TeacherChoice
    ):
        raise _ScopeChanged("A selected candidate is not verified.")
    _current_choice(
        period_catalog,
        scope="period",
        selected={"class": class_id},
        choice=period_choice,
    )
    _current_choice(
        class_catalog,
        scope="student",
        selected={"class": class_id},
        choice=student,
    )


def run_named_current_override_review(
    *,
    navigation: TeacherNavigationContext,
    review_loader: OverrideReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Display exact currently selected override state, without academic writes."""
    try:
        # Import only when invoked to avoid a runtime menu-controller cycle.
        from meridian.menu_overrides import OverrideScope

        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation,
            classes,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if active is None:
            return
        root, class_id = active
        verified_class = navigation.current_class()
        if (
            verified_class is None
            or verified_class.workspace != root
            or verified_class.class_id != class_id
        ):
            raise _ScopeChanged("Class scope changed.")
        period_selection = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if period_selection is None:
            return
        period, period_choice = period_selection
        student = select_teacher_choice(
            catalog=classes,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Whose current Grade override should Meridian review?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return
        scope = OverrideScope(
            class_id=class_id,
            student_id=student.identity[0],
            period=AcademicPeriodRef(period.school_year, period.period_id),
            calendar_revision=period.calendar_revision,
            family=family,
        )

        def check_scope() -> None:
            _revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified_class.school_year,
                period=period,
                period_choice=period_choice,
                student=student,
                class_catalog=classes,
                period_catalog=periods,
            )

        check_scope()
        original = review_loader(root, scope)
        if original.scope != scope:
            raise _ScopeChanged("Override review belongs to another target.")
        check_scope()
        # A second authoritative read prevents displaying an obsolete selected
        # decision, including a change from override to withdrawal or none.
        refreshed = review_loader(root, scope)
        if refreshed != original or refreshed.scope != scope:
            raise _ScopeChanged("The current override selection changed.")
        check_scope()
        if original.selected and original.decision not in {"override", "withdraw"}:
            raise _ScopeChanged("Unknown selected override state.")
        if not original.selected and original.decision is not None:
            raise _ScopeChanged("Unselected override carries a decision.")
        if original.decision == "override" and original.replacement_grade is None:
            raise _ScopeChanged("Override Grade is unavailable.")
        navigation.session.select_student(student.identity[0])
        clear_fn()
        print_menu_header(output, "Current Grade Override Review")
        write_lines(
            output,
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Grade calculation: {family.replace('_', ' ')}",
            "",
        )
        if not original.selected:
            write_lines(
                output,
                "Current override: none selected",
                "This is not a zero Grade, and no override was assumed.",
            )
        elif original.decision == "withdraw":
            write_lines(
                output,
                "Current override decision: withdrawn",
                "No replacement Grade is applied by this selected withdrawal.",
            )
        else:
            write_lines(
                output,
                "Current override decision: replacement Grade",
                f"Replacement Grade: {original.replacement_grade}",
            )
        if original.selected:
            write_lines(
                output,
                "Teacher decision and rationale are recorded.",
                "Use Advanced for exact history and attribution details.",
            )
        write_lines(
            output,
            "",
            "Read-only. No override, Grade, or current selection was changed.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "Class, marking period, student, or current override changed.",
            "Nothing was saved. Refresh the selections and review again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Current override state is unavailable or could not be verified.",
            "Nothing was saved. Review configuration or use Advanced details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_current_override_review",)
