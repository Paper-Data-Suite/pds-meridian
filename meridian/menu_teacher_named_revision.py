"""Teacher-guided use of an existing Grade Item revision (#123 Slice 4D1).

One deliberate USE confirmation delegates to the original CAS-guarded selection
workflow. Creation/revision authoring remains separate and Advanced.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.grade_item_selection_workflow import (
    GradeItemSelectionPreview,
    GradeItemSelectionStaleError,
    GradeItemSelectionWorkflowResult,
)
from meridian.grade_items_workflow import GradeItemsReview
from meridian.menu_teacher_named_review import _class, _grade_item
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import TeacherChoice, load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_revisions import TeacherGradeItemRevisionCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

Previewer: TypeAlias = Callable[[Path, str, str, int], GradeItemSelectionPreview]
Committer: TypeAlias = Callable[
    [Path, GradeItemSelectionPreview], GradeItemSelectionWorkflowResult
]
Reviewer: TypeAlias = Callable[[Path, str], GradeItemsReview]


class _SelectionChanged(RuntimeError):
    """An exact chosen identity or currentness witness changed."""


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    grade_catalog: TeacherAcademicChoiceCatalog,
    grade_item: TeacherChoice,
    revision_catalog: TeacherGradeItemRevisionCatalog,
    chosen_revision: TeacherChoice,
) -> None:
    scope = navigation.current_class()
    if scope is None or scope.workspace != root or scope.class_id != class_id:
        raise _SelectionChanged("Class changed.")
    if grade_item not in load_teacher_choices(
        grade_catalog, scope="grade_item", selected={"class": class_id}
    ):
        raise _SelectionChanged("Grade Item changed.")
    if chosen_revision not in load_teacher_choices(
        revision_catalog,
        scope="grade_item_revision",
        selected={"class": class_id, "grade_item": grade_item.identity[0]},
    ):
        raise _SelectionChanged("Revision/current selection changed.")


def run_named_grade_item_revision_selection(
    *,
    navigation: TeacherNavigationContext,
    review_loader: Reviewer,
    previewer: Previewer,
    committer: Committer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    revision_catalog: TeacherGradeItemRevisionCatalog | None = None,
    grade_catalog: TeacherAcademicChoiceCatalog | None = None,
) -> None:
    """Choose a version by readable history, review, and explicitly use it."""
    try:
        grades = grade_catalog or TeacherAcademicChoiceCatalog(navigation)
        revisions = revision_catalog or TeacherGradeItemRevisionCatalog(
            navigation=navigation, review_loader=review_loader
        )
        active = _class(
            navigation, grades, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        grade_item = _grade_item(
            grades,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if grade_item is None:
            return
        chosen = select_teacher_choice(
            catalog=revisions,
            scope="grade_item_revision",
            selected={"class": class_id, "grade_item": grade_item.identity[0]},
            title="Grade Item History",
            question="Which existing version should Meridian use?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            grade_catalog=grades,
            grade_item=grade_item,
            revision_catalog=revisions,
            chosen_revision=chosen,
        )
        revision_number = int(chosen.identity[0])
        preview = previewer(root, class_id, grade_item.identity[0], revision_number)
        if (
            preview.class_id != class_id
            or preview.grade_item_id != grade_item.identity[0]
            or preview.target_revision != revision_number
            or preview.target.revision.title != chosen.label
            or (chosen.witness or "").split(":", 1)[0] != preview.target.revision_sha256
        ):
            raise _SelectionChanged("Preview differs from chosen record.")
        clear_fn()
        print_menu_header(output, "Review Grade Item Version")
        write_lines(
            output,
            f"Grade Item: {preview.target.revision.title}",
            f"Version to use: {preview.target_revision}",
            f"Status: {preview.target_status.replace('_', ' ')}",
            (
                "Currently in use: none"
                if preview.expected_current_revision is None
                else f"Currently in use: version {preview.expected_current_revision}"
            ),
            "",
        )
        if preview.expected_current_revision == preview.target_revision:
            write_lines(output, "This version is already current. No change made.")
            pause_for_user(input_fn)
            return
        write_lines(
            output,
            "Using this version changes which existing Grade Item revision is current.",
            "It does not create a new revision or modify work memberships.",
            "Type USE to confirm, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "USE":
            write_lines(output, "Canceled. No Grade Item selection was changed.")
            pause_for_user(input_fn)
            return
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            grade_catalog=grades,
            grade_item=grade_item,
            revision_catalog=revisions,
            chosen_revision=chosen,
        )
        result = committer(root, preview)
        navigation.session.select_grade_item(grade_item.identity[0])
        write_lines(
            output,
            "",
            f"Grade Item version {result.selected_revision} is now current.",
            f"Result: {result.selection_disposition}.",
            "The existing revision was selected; no new revision was authored.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_SelectionChanged, GradeItemSelectionStaleError):
        write_lines(
            output,
            "The selected Grade Item or its revision changed during review.",
            "No selection was confirmed by this attempt. Refresh and review again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "The selected Grade Item version could not be safely used.",
            "Check current state before retrying; see Advanced for details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_grade_item_revision_selection",)
