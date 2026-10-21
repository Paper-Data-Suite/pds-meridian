"""Named, read-only review of already-selected academic-period proficiency."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

PeriodExplanationLoader = Callable[[Path, str, str, str, str, str], object]


def run_named_period_proficiency(
    *,
    navigation: TeacherNavigationContext,
    catalog: TeacherAcademicChoiceCatalog,
    period_catalog: PeriodProficiencyChoiceCatalog,
    load_proficiency: PeriodExplanationLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Choose exact class/period/student/Standard, then explain current result.

    The domain explanation reader still validates academic dependencies and
    authorization. This menu never creates results, grades, or selections.
    """
    try:
        active = _class(
            navigation,
            catalog,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if active is None:
            return
        root, class_id = active
        context = {"class": class_id}
        period = select_teacher_choice(
            catalog=period_catalog,
            scope="period",
            selected=context,
            title="Choose Marking Period",
            question="Which current marking period would you like to review?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if period is None:
            return
        verified_period = navigation.choose_period(period.identity[0])
        if period not in load_teacher_choices(
            period_catalog, scope="period", selected=context
        ):
            navigation.clear_period()
            raise ValueError("Marking period changed after choosing it.")
        student = select_teacher_choice(
            catalog=catalog,
            scope="student",
            selected=context,
            title="Choose Student",
            question="Which student is in this class?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        context.update({"period": period.identity[0], "student": student.identity[0]})
        standard = select_teacher_choice(
            catalog=period_catalog,
            scope="period_standard",
            selected=context,
            title="Current Marking-Period Proficiency",
            question=(
                "Choose a Standard with a selected result. "
                "No selected result does not mean zero proficiency."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if standard is None:
            return
        current_period = navigation.current_period()
        if (
            current_period is None
            or current_period != verified_period
            or current_period.workspace != root
        ):
            raise ValueError("Class or calendar changed during selection.")
        for candidate, choice_scope, choice_context, choice_catalog in (
            (period, "period", {"class": class_id}, period_catalog),
            (student, "student", {"class": class_id}, catalog),
            (standard, "period_standard", context, period_catalog),
        ):
            if candidate not in load_teacher_choices(
                choice_catalog, scope=choice_scope, selected=choice_context
            ):
                raise ValueError("Selected record or its current state changed.")
        explanation = load_proficiency(
            root,
            class_id,
            verified_period.school_year,
            verified_period.period_id,
            student.identity[0],
            standard.identity[0],
        )
        if (
            navigation.current_period() != verified_period
            or standard
            not in load_teacher_choices(
                period_catalog, scope="period_standard", selected=context
            )
        ):
            raise ValueError("Current result changed during explanation.")
        navigation.session.select_student(student.identity[0])
        clear_fn()
        print_menu_header(output, "Current Marking-Period Proficiency")
        status = str(getattr(explanation, "status"))
        proficiency = getattr(explanation, "proficiency_label", None)
        write_lines(
            output,
            f"Class: {class_id}",
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Standard: {standard.label}",
            f"Current proficiency: {proficiency or status.replace('_', ' ')}",
            f"Policy: {getattr(explanation, 'policy_title')}",
            f"Scale: {getattr(explanation, 'scale_title')}",
            "",
            "Read-only selected result. No Grade, policy or selection was written.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except Exception:
        write_lines(
            output,
            "The marking-period proficiency result could not be verified safely.",
            "No academic record was changed. Refresh or use Advanced diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_period_proficiency",)
