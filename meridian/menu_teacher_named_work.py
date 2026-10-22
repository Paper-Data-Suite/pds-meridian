"""Teacher-first, read-only registered-work membership review (#123 Slice 4C)."""

from __future__ import annotations

from typing import TextIO

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_items_workflow import GradeItemsReview
from meridian.menu_teacher_named_review import _class, _grade_item
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
from meridian.teacher_navigation_terminal import select_teacher_choice
from meridian.teacher_navigation_work import (
    GradeItemsReviewer,
    TeacherRegisteredWorkCatalog,
)


def run_named_work_membership_review(
    *,
    navigation: TeacherNavigationContext,
    review_loader: GradeItemsReviewer,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    catalog: TeacherRegisteredWorkCatalog | None = None,
) -> None:
    """Inspect a named work relationship, never create/select a membership."""
    active_catalog = catalog or TeacherRegisteredWorkCatalog(
        navigation=navigation, grade_item_reviewer=review_loader
    )
    try:
        grade_catalog = TeacherAcademicChoiceCatalog(navigation)
        active = _class(
            navigation,
            grade_catalog,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if active is None:
            return
        root, class_id = active
        grade_item = _grade_item(
            grade_catalog,
            class_id=class_id,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if grade_item is None:
            return
        context = {"class": class_id, "grade_item": grade_item.identity[0]}
        work = select_teacher_choice(
            catalog=active_catalog,
            scope="registered_work",
            selected=context,
            title="Registered Work",
            question=(
                "Choose current registered work to inspect its relationship "
                "with this Grade Item."
            ),
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if work is None:
            return
        scope = navigation.current_class()
        if scope is None or scope.workspace != root or scope.class_id != class_id:
            raise ValueError("Class changed during selection.")
        review: GradeItemsReview = review_loader(root, class_id)
        if review.class_id != class_id:
            raise ValueError("Grade Item review class changed.")
        items = tuple(
            row for row in review.items if row.grade_item_id == grade_item.identity[0]
        )
        if len(items) != 1:
            raise ValueError("Grade Item no longer available.")
        # Both selections must still have identical identities AND witnesses.
        if grade_item not in load_teacher_choices(
            grade_catalog, scope="grade_item", selected={"class": class_id}
        ) or work not in load_teacher_choices(
            active_catalog, scope="registered_work", selected=context
        ):
            raise ValueError("Selected academic records changed.")
        matching = tuple(
            membership
            for membership in items[0].memberships
            if (membership.work.module_id, membership.work.work_id) == work.identity
        )
        if len(matching) > 1:
            raise ValueError("Ambiguous current relationship.")
        membership = matching[0] if matching else None
        if membership is None:
            outcome = "No recorded Grade Item relationship"
            period_text = "No marking period assigned by this relationship"
        else:
            outcome = (
                "No selected membership decision"
                if membership.decision is None
                else f"Current membership decision: {membership.decision}"
            )
            if membership.academic_period_id is None:
                period_text = "No marking period currently assigned"
            elif membership.academic_period_school_year != scope.school_year:
                period_text = "Historical period assignment; inspect Advanced"
            else:
                try:
                    verified_period = navigation.verify_period(
                        membership.academic_period_id
                    )
                except Exception:
                    period_text = "Period assignment requires review in Advanced"
                else:
                    if (
                        verified_period.calendar_revision
                        != membership.academic_period_calendar_revision
                    ):
                        period_text = "Historical calendar assignment; inspect Advanced"
                    else:
                        period_text = f"Marking period: {verified_period.label}"
        # Retain navigation hints after authoritative rereads. No domain write.
        navigation.session.select_work(
            ModuleWorkRef(work.identity[0], class_id, work.identity[1])
        )
        navigation.session.select_grade_item(grade_item.identity[0])
        clear_fn()
        print_menu_header(output, "Registered Work and Grade Item Relationship")
        write_lines(
            output,
            f"Grade Item: {grade_item.label}",
            f"Registered work: {work.label}",
            f"Producer: {work.source or 'Unknown'}",
            f"Registration: {work.status or 'Unknown'}",
            outcome,
            period_text,
            "",
            "Read-only. No Grade Item, membership or period was changed.",
            "Advanced retains exact revision and membership author/select commands.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except Exception:
        write_lines(
            output,
            "Registered work or its Grade Item relationship could not be verified.",
            "No academic record was changed. Refresh or use Advanced details.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_work_membership_review",)
