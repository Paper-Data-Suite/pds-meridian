"""Teacher-named, read-only Grade Item proficiency explanation (#123 Slice 9C).

Core roster and Meridian's existing catalog identify the exact class, Grade
Item, student and selected Standard result. The existing #42 Explain adapter
is the sole authority for provenance. A named choice never changes academic
state, and all witnesses are reread before results are displayed.
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

from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_review import _class, _grade_item
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
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_explain import ExplanationPresentation

GradeItemExplanationReader: TypeAlias = Callable[
    [Path, str, str, str, str], "ExplanationPresentation"
]


class _ItemExplanationChanged(RuntimeError):
    """The underlying canonical result or selected academic scope changed."""


def _selected_result_witness(choice: TeacherChoice) -> tuple[int, str]:
    """Exact selected-result witness emitted by the current Meridian catalog."""
    witness = choice.witness
    if witness is None:
        raise _ItemExplanationChanged("The Standard result has no witness.")
    revision, sep, digest = witness.partition(":")
    if (
        not sep
        or not revision.isascii()
        or not revision.isdecimal()
        or not revision
        or revision.startswith("0")
        or not digest
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise _ItemExplanationChanged("Current result witness is invalid.")
    return int(revision), digest


def _checked_ordinary_lines(
    value: "ExplanationPresentation",
    *,
    class_id: str,
    grade_item: TeacherChoice,
    student: TeacherChoice,
    standard: TeacherChoice,
) -> tuple[str, ...]:
    """Never trust a presentation that cannot be tied to the selected result."""
    lines, technical = value.lines, value.technical_lines
    revision, digest = _selected_result_witness(standard)
    old_grade_item = f"Grade Item: {grade_item.label}"
    old_student = f"Student: {student.identity[0]}"
    old_standard = f"Standard: {standard.identity[0]}"
    required_details = (
        f"class_id: {class_id}",
        f"grade_item_id: {grade_item.identity[0]}",
        f"result_revision: {revision}",
        f"result_sha256: {digest}",
    )
    if (
        value.title != "Grade Item Proficiency Explanation"
        or not isinstance(lines, tuple)
        or not isinstance(technical, tuple)
        or any(not isinstance(line, str) for line in (*lines, *technical))
        or any(
            lines.count(token) != 1
            for token in (old_grade_item, old_student, old_standard)
        )
        or any(technical.count(token) != 1 for token in required_details)
        or not any(line.startswith("Result: ") for line in lines)
        or not any(line.startswith("Selection state: ") for line in lines)
    ):
        raise _ItemExplanationChanged("Proficiency explanation is outside selection.")
    redacted = {old_grade_item, old_student, old_standard}
    return tuple(line for line in lines if line not in redacted)


def run_named_grade_item_proficiency_explanation(
    *,
    navigation: TeacherNavigationContext,
    grade_item_explainer: GradeItemExplanationReader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
) -> None:
    """Explain one existing selected proficiency result using four named choices."""
    try:
        catalog = class_catalog or TeacherAcademicChoiceCatalog(navigation)
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
        initial_class = navigation.current_class()
        if (
            initial_class is None
            or initial_class.workspace != root
            or initial_class.class_id != class_id
        ):
            raise _ItemExplanationChanged("Class identity changed.")
        grade_item = _grade_item(
            catalog,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if grade_item is None:
            return
        student = select_teacher_choice(
            catalog=catalog,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Whose Grade Item proficiency should be explained?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        standard_scope = {
            "class": class_id,
            "grade_item": grade_item.identity[0],
            "student": student.identity[0],
        }
        standard = select_teacher_choice(
            catalog=catalog,
            scope="standard",
            selected=standard_scope,
            title="Choose Selected Standard Result",
            question=(
                "Which Standard's existing current proficiency should be explained? "
                "A missing result does not mean zero."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if standard is None:
            return

        def check_scope() -> None:
            if navigation.current_class() != initial_class:
                raise _ItemExplanationChanged("The verified class changed.")
            for choice, scope, selected in (
                (grade_item, "grade_item", {"class": class_id}),
                (student, "student", {"class": class_id}),
                (standard, "standard", standard_scope),
            ):
                _current_choice(catalog, scope=scope, selected=selected, choice=choice)
            _selected_result_witness(standard)

        check_scope()
        value = grade_item_explainer(
            root,
            class_id,
            grade_item.identity[0],
            student.identity[0],
            standard.identity[0],
        )
        ordinary = _checked_ordinary_lines(
            value,
            class_id=class_id,
            grade_item=grade_item,
            student=student,
            standard=standard,
        )
        check_scope()
        while True:
            check_scope()
            clear_fn()
            print_menu_header(output, "Grade Item Proficiency Explanation")
            write_lines(
                output,
                f"Grade Item: {grade_item.label}",
                f"Student: {student.label}",
                standard.label,
                *ordinary,
                "",
                "An absent selected result is not zero.",
                "Read-only explanation; academic records were not changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            choice = read_choice(input_fn)
            if choice.casefold() == "t":
                check_scope()
                clear_fn()
                print_menu_header(output, "Grade Item — Technical Provenance")
                write_lines(
                    output,
                    f"student_id: {student.identity[0]}",
                    f"standard_id: {standard.identity[0]}",
                    *value.technical_lines,
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(choice)
            if command is NavigationChoice.BACK or choice == "":
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ItemExplanationChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, Grade Item, student, Standard, or selected result changed.",
            "No academic record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Grade Item proficiency explanation could not be verified safely.",
            "No academic record was changed. Check access or Advanced diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_grade_item_proficiency_explanation",)
