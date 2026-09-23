"""Low-density teacher menu for Meridian Grade Item review."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.grade_item_storage import GradeItemStorageError
from meridian.grade_items_workflow import (
    GradeItemsReview,
    GradeItemsWorkflowError,
    project_grade_items_review,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
GradeItemsReviewLoader: TypeAlias = Callable[[Path, str], GradeItemsReview]

_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class GradeItemsMenuDependencies:
    """Injected read services for deterministic menu testing and composition."""

    workspace_resolver: WorkspaceResolver
    review_loader: GradeItemsReviewLoader


def default_grade_items_menu_dependencies() -> GradeItemsMenuDependencies:
    """Return production read dependencies without creating workspace state."""

    def load_review(root: Path, class_id: str) -> GradeItemsReview:
        return project_grade_items_review(root, class_id)

    return GradeItemsMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        review_loader=load_review,
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _render_review(output: TextIO, review: GradeItemsReview) -> None:
    print_menu_header(output, "Grade Items")
    write_lines(
        output,
        f"Class: {review.class_id}",
        (
            f"Grade Items: {len(review.items)} "
            f"({review.active_count} active, {review.archived_count} archived)"
        ),
        f"Without a current revision: {review.unselected_count}",
        f"Work relationships: {review.membership_relationship_count}",
        "",
    )
    if not review.items:
        write_lines(
            output,
            "No Grade Items have been created for this class.",
            "Nothing was inferred from publications, dates, or evidence.",
        )
        return

    for index, row in enumerate(review.items[:_PAGE_SIZE], start=1):
        title = row.title or "Grade Item without a current revision"
        status = _humanize(row.status or row.selection_state)
        print(f"{index}. {title} — {status}", file=output)
        if row.purpose:
            print(f"   Purpose: {row.purpose}", file=output)
        if row.memberships:
            print(f"   Work relationships: {len(row.memberships)}", file=output)

    remaining = len(review.items) - _PAGE_SIZE
    if remaining > 0:
        print(
            f"... {remaining} more Grade Items not shown on this screen.",
            file=output,
        )


def _render_technical(output: TextIO, review: GradeItemsReview) -> None:
    print_menu_header(output, "Grade Items — Technical details / provenance")
    print(f"class_id: {review.class_id}", file=output)
    if not review.items:
        print("No canonical Grade Item histories.", file=output)
        return
    for row in review.items:
        selected = (
            row.selected_revision
            if row.selected_revision is not None
            else "none"
        )
        print(
            f"{row.grade_item_id}: selected={selected}; "
            f"latest={row.latest_persisted_revision}; "
            f"selection={row.selection_state}",
            file=output,
        )
        for membership in row.memberships:
            membership_selected = (
                membership.selected_revision
                if membership.selected_revision is not None
                else "none"
            )
            print(
                "  "
                f"{membership.work.module_id}/{membership.work.work_id}: "
                f"selected={membership_selected}; "
                f"latest={membership.latest_persisted_revision}; "
                f"decision={membership.decision or 'none'}; "
                f"basis={membership.grade_item_basis_state}",
                file=output,
            )


def _show_review(
    *,
    review: GradeItemsReview,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    while True:
        clear_fn()
        _render_review(output, review)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _render_technical(output, review)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _review_grade_items(
    *,
    dependencies: GradeItemsMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Grade Items")
    class_id = read_choice(input_fn, "Class ID (leave blank to cancel): ")
    if not class_id:
        return
    navigation = parse_navigation_choice(class_id)
    if navigation is NavigationChoice.BACK:
        return

    try:
        root = dependencies.workspace_resolver()
        review = dependencies.review_loader(root, class_id)
    except WorkspaceRootError as error:
        write_lines(
            output,
            "",
            "The Paper Data Suite workspace could not be resolved.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    except (GradeItemsWorkflowError, GradeItemStorageError, ValueError) as error:
        write_lines(
            output,
            "",
            "Grade Item state could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    _show_review(
        review=review,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


def run_grade_items_menu(
    *,
    dependencies: GradeItemsMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run the read-only Grade Item teacher menu for the current slice."""

    stream = sys.stdout if output is None else output
    active = dependencies or default_grade_items_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Manage Grade Items")
        write_lines(
            stream,
            "1. Review Grade Items",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_grade_items(
                dependencies=active,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1, B, M, or Q.")
        pause_for_user(input_fn)
