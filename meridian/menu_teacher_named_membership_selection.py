"""Explicitly use an existing, compatible Grade Item membership decision (#123)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionPreview,
    GradeItemMembershipSelectionStaleError,
    GradeItemMembershipSelectionWorkflowResult,
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
from meridian.teacher_navigation_membership_revisions import (
    TeacherMembershipRevisionCatalog,
)
from meridian.teacher_navigation_terminal import select_teacher_choice
from meridian.teacher_navigation_work import TeacherRegisteredWorkCatalog

Reviewer: TypeAlias = Callable[[Path, str], GradeItemsReview]
Previewer: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, int], GradeItemMembershipSelectionPreview
]
Committer: TypeAlias = Callable[
    [Path, GradeItemMembershipSelectionPreview],
    GradeItemMembershipSelectionWorkflowResult,
]


class _SelectionChanged(RuntimeError):
    """A verified navigation candidate no longer identifies the same record."""


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    grade_catalog: TeacherAcademicChoiceCatalog,
    grade_item: TeacherChoice,
    work_catalog: TeacherRegisteredWorkCatalog,
    work: TeacherChoice,
    revision_catalog: TeacherMembershipRevisionCatalog,
    revision: TeacherChoice,
    context: dict[str, str],
) -> None:
    verified = navigation.current_class()
    if verified is None or verified.workspace != root or verified.class_id != class_id:
        raise _SelectionChanged("Class changed.")
    if grade_item not in load_teacher_choices(
        grade_catalog, scope="grade_item", selected={"class": class_id}
    ):
        raise _SelectionChanged("Grade Item changed.")
    if work not in load_teacher_choices(
        work_catalog,
        scope="registered_work",
        selected={"class": class_id, "grade_item": grade_item.identity[0]},
    ):
        raise _SelectionChanged("Registered work changed.")
    if revision not in load_teacher_choices(
        revision_catalog, scope="membership_revision", selected=context
    ):
        raise _SelectionChanged("Membership revision changed.")


def run_named_membership_revision_selection(
    *,
    navigation: TeacherNavigationContext,
    review_loader: Reviewer,
    previewer: Previewer,
    committer: Committer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    grade_catalog: TeacherAcademicChoiceCatalog | None = None,
    work_catalog: TeacherRegisteredWorkCatalog | None = None,
    revision_catalog: TeacherMembershipRevisionCatalog | None = None,
) -> None:
    """One explicit Use, without creating or guessing a new membership decision."""
    try:
        grades = grade_catalog or TeacherAcademicChoiceCatalog(navigation)
        works = work_catalog or TeacherRegisteredWorkCatalog(
            navigation=navigation, grade_item_reviewer=review_loader
        )
        revisions = revision_catalog or TeacherMembershipRevisionCatalog(
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
        work_context = {"class": class_id, "grade_item": grade_item.identity[0]}
        work = select_teacher_choice(
            catalog=works,
            scope="registered_work",
            selected=work_context,
            title="Choose Registered Work",
            question="Which existing work relationship should Meridian use?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if work is None:
            return
        context = {**work_context, "module": work.identity[0], "work": work.identity[1]}
        revision = select_teacher_choice(
            catalog=revisions,
            scope="membership_revision",
            selected=context,
            title="Membership History",
            question="Choose a previously recorded include/exclude decision.",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if revision is None:
            return
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            grade_catalog=grades,
            grade_item=grade_item,
            work_catalog=works,
            work=work,
            revision_catalog=revisions,
            revision=revision,
            context=context,
        )
        if revision.status != "Available to use":
            write_lines(
                output,
                "This historical decision refers to a different or unavailable basis.",
                "No change made. Use Advanced to inspect its exact provenance.",
            )
            pause_for_user(input_fn)
            return
        chosen_work = ModuleWorkRef(work.identity[0], class_id, work.identity[1])
        revision_number = int(revision.identity[0])
        preview = previewer(
            root, class_id, grade_item.identity[0], chosen_work, revision_number
        )
        if (
            preview.class_id != class_id
            or preview.grade_item_id != grade_item.identity[0]
            or preview.work != chosen_work
            or preview.target_revision != revision_number
            or (revision.witness or "").split(":", 1)[0]
            != preview.target.decision_sha256
            or preview.target_decision.title() + " relationship" != revision.label
        ):
            raise _SelectionChanged("Membership preview differs from selected row.")
        clear_fn()
        print_menu_header(output, "Review Existing Work Relationship")
        decision = preview.target.decision
        period_label = (
            "No marking period"
            if decision.academic_period is None
            else (revision.detail or "").rsplit(" · ", 1)[-1]
        )
        write_lines(
            output,
            f"Grade Item: {grade_item.label}",
            f"Registered work: {work.label}",
            f"Decision: {preview.target_decision}",
            f"Recorded: {decision.decided_at.date().isoformat()}",
            f"Period: {period_label}",
            f"History version: {preview.target_revision}",
            (
                "Currently in use: none"
                if preview.expected_current_membership_revision is None
                else (
                    "Currently in use: version "
                    f"{preview.expected_current_membership_revision}"
                )
            ),
            "",
        )
        if preview.expected_current_membership_revision == preview.target_revision:
            write_lines(output, "This decision is already current. No change made.")
            pause_for_user(input_fn)
            return
        write_lines(
            output,
            "Using this decision changes the current include/exclude relationship.",
            "No new decision is authored; it may affect later proficiency or Grades.",
            "Type USE to confirm, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "USE":
            write_lines(output, "Canceled. No membership selection was changed.")
            pause_for_user(input_fn)
            return
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            grade_catalog=grades,
            grade_item=grade_item,
            work_catalog=works,
            work=work,
            revision_catalog=revisions,
            revision=revision,
            context=context,
        )
        result = committer(root, preview)
        write_lines(
            output,
            "",
            f"Current work relationship: {result.selected_decision}.",
            (
                f"Result: {result.selection_disposition}; "
                f"version {result.selected_revision}."
            ),
            "No new membership decision was authored.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_SelectionChanged, GradeItemMembershipSelectionStaleError):
        write_lines(
            output,
            "The reviewed work relationship or its academic basis changed.",
            "No selection was committed by this attempt. Refresh and review again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "The membership decision could not be safely selected.",
            "Inspect current state before retrying; Advanced has exact details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_membership_revision_selection",)
