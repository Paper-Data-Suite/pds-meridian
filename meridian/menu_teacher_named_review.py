"""Read-only named Grade Item and selected proficiency review for Issue #123.

No write, receipt, authorization grant, projection cache or selector mutation.
Existing domain explanation loaders remain the only authority for explanations.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.grade_items_workflow import GradeItemsReview
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.teacher_navigation_choices import TeacherChoice, load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

GradeItemsLoader = Callable[[Path, str], GradeItemsReview]
ProficiencyLoader = Callable[[Path, str, str, str, str], object]


def _class(
    navigation: TeacherNavigationContext,
    catalog: TeacherAcademicChoiceCatalog,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[Path, str] | None:
    """Reuse a currently verified class or choose one explicitly by label."""
    if navigation.session.active_class_id is not None:
        verified = navigation.current_class()
        if verified is None:
            return None
        write_lines(
            output,
            f"Using selected class: {verified.class_id} ({verified.school_year}).",
        )
        return verified.workspace, verified.class_id
    chosen = select_teacher_choice(
        catalog=catalog,
        scope="class",
        title="Choose Class",
        question="Which class would you like to review?",
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if chosen is None:
        return None
    verified = navigation.choose_class(chosen.identity[0])
    # Verify the choice did not change between catalog confirmation and
    # remembering the class. This is a read witness, not academic authority.
    if chosen not in load_teacher_choices(catalog, scope="class"):
        navigation.session.clear()
        write_lines(output, "Class changed. Choose again before reviewing.")
        return None
    return verified.workspace, verified.class_id


def _grade_item(
    catalog: TeacherAcademicChoiceCatalog,
    *,
    class_id: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> TeacherChoice | None:
    return select_teacher_choice(
        catalog=catalog,
        scope="grade_item",
        selected={"class": class_id},
        title="Grade Items",
        question="Choose an existing assignment or assessment to review.",
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


def run_named_grade_item_review(
    *,
    navigation: TeacherNavigationContext,
    catalog: TeacherAcademicChoiceCatalog,
    review_loader: GradeItemsLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Read a named Grade Item, with no implicit author/select operation."""
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
        choice = _grade_item(
            catalog,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return
        scope = navigation.current_class()
        if scope is None or scope.workspace != root or scope.class_id != class_id:
            raise ValueError("Class changed during review.")
        review = review_loader(root, class_id)
        if review.class_id != class_id:
            raise ValueError("Grade Item review belongs to another class.")
        matching = [
            row for row in review.items if row.grade_item_id == choice.identity[0]
        ]
        if len(matching) != 1 or choice not in load_teacher_choices(
            catalog, scope="grade_item", selected={"class": class_id}
        ):
            raise ValueError("Grade Item changed. Refresh the named list.")
        row = matching[0]
        navigation.session.select_grade_item(row.grade_item_id)
        clear_fn()
        print_menu_header(output, "Grade Item and Work Relationships")
        write_lines(
            output,
            f"Class: {class_id}",
            f"Grade Item: {row.title or 'No selected revision'}",
            f"Status: {(row.status or row.selection_state).replace('_', ' ')}",
            f"Purpose: {(row.purpose or 'not selected').replace('_', ' ')}",
            f"Work relationships: {len(row.memberships)}",
            "",
        )
        for membership in row.memberships:
            state = (membership.decision or membership.selection_state).replace(
                "_", " "
            )
            write_lines(
                output,
                f"  {membership.work.module_id} relationship — {state}",
                (
                    "  Period: not currently assigned"
                    if membership.academic_period_id is None
                    else "  Period assignment recorded (see Advanced for exact scope)"
                ),
            )
        write_lines(
            output,
            "",
            "Read-only. No Grade Item revision or membership was selected.",
            "Exact record operations remain in Advanced.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except Exception:
        # Domain and workspace exceptions are not exposed verbatim in ordinary
        # screens. The caller can use Advanced for exact diagnostic details.
        write_lines(
            output,
            "The selected Grade Item could not be reverified safely.",
            "No record was changed. Refresh or use Advanced diagnostics.",
        )
        pause_for_user(input_fn)


def run_named_grade_item_proficiency(
    *,
    navigation: TeacherNavigationContext,
    catalog: TeacherAcademicChoiceCatalog,
    load_proficiency: ProficiencyLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Browse existing selected results only; never infer absent proficiency."""
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
        grade_item = _grade_item(
            catalog,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if grade_item is None:
            return
        context = {"class": class_id, "grade_item": grade_item.identity[0]}
        student = select_teacher_choice(
            catalog=catalog,
            scope="student",
            selected=context,
            title="Choose Student",
            question="Which roster student?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        context["student"] = student.identity[0]
        standard = select_teacher_choice(
            catalog=catalog,
            scope="standard",
            selected=context,
            title="Current Proficiency",
            question=(
                "Choose a Standard with an existing selected result. "
                "No selection does not mean a zero."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if standard is None:
            return
        current_scope = navigation.current_class()
        if (
            current_scope is None
            or current_scope.workspace != root
            or current_scope.class_id != class_id
        ):
            raise ValueError("The class changed.")
        for choice, scope, selected in (
            (grade_item, "grade_item", {"class": class_id}),
            (student, "student", {"class": class_id}),
            (standard, "standard", context),
        ):
            if choice not in load_teacher_choices(
                catalog, scope=scope, selected=selected
            ):
                raise ValueError("One of the selected records changed.")
        result = load_proficiency(
            root,
            class_id,
            grade_item.identity[0],
            student.identity[0],
            standard.identity[0],
        )
        # The existing trace loader determines whether the selected result is
        # actually explainable. Recheck pointer witness even after that read.
        if standard not in load_teacher_choices(
            catalog, scope="standard", selected=context
        ):
            raise ValueError("The selected proficiency result changed.")
        navigation.session.select_grade_item(grade_item.identity[0])
        navigation.session.select_student(student.identity[0])
        clear_fn()
        print_menu_header(output, "Current Grade Item Proficiency")
        status = str(getattr(result, "status"))
        proficiency = getattr(result, "proficiency_label", None)
        proficiency_text = proficiency or status.replace("_", " ")
        write_lines(
            output,
            f"Assessment: {grade_item.label}",
            f"Student: {student.label}",
            f"Standard: {standard.label}",
            f"Current proficiency: {proficiency_text}",
            f"Policy: {getattr(result, 'policy_title')}",
            f"Scale: {getattr(result, 'scale_title')}",
            "",
            "Read-only selected result. No Grade or proficiency was created.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except Exception:
        write_lines(
            output,
            "The selected proficiency could not be verified or explained safely.",
            "No result was created or changed. Review current evidence or Advanced.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_grade_item_review", "run_named_grade_item_proficiency")
