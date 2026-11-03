"""#124 E2G3O1: class/period-scoped, read-only named assessment discovery.

The derived catalog is a navigation hint, not Grade Item readiness authority.
No entry on this screen prepares, writes or selects academic records.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.class_metadata import load_class_metadata
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routes import class_metadata_path
from pds_core.workspace import resolve_workspace_root

from meridian.assessment_setup_choices import load_named_assessment_choices
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
from meridian.teacher_navigation_choices import page_teacher_choices
from meridian.teacher_session import TeacherSessionContext

WorkspaceResolver = Callable[[], Path]


def run_teacher_assessment_discovery_menu(
    *,
    session_context: TeacherSessionContext,
    input_fn: InputFunction = input,
    output: TextIO,
    clear_fn: ClearFunction = clear_screen,
    workspace_resolver: WorkspaceResolver = resolve_workspace_root,
) -> None:
    """Browse current Core registration hints; never confer execution authority.

    A teacher first selects one class in the shared Meridian session, then
    explicitly chooses a marking period. All discovery is read-only and
    search results never become action decisions or session navigation.
    """
    if not isinstance(session_context, TeacherSessionContext):
        write_lines(output, "Assessment discovery requires a teacher session.")
        return
    class_id = session_context.active_class_id
    if class_id is None:
        write_lines(
            output,
            "Select a class in Teacher Settings before discovering assessments.",
            "No assessment setup or academic selection was requested.",
        )
        pause_for_user(input_fn)
        return
    try:
        root = Path(workspace_resolver()).resolve()
        metadata = load_class_metadata(class_metadata_path(root, class_id))
        if metadata.class_id != class_id:
            raise ValueError("Class metadata differs from the selected class.")
        year = metadata.school_year
        calendar = load_current_academic_period_calendar(root, year)
        if calendar is None or calendar.school_year != year:
            raise ValueError("Current school-year calendar is unavailable.")
        periods = tuple(
            sorted(
                (
                    period
                    for period in calendar.periods
                    if period.period_type == "marking_period"
                    and period.lifecycle != "cancelled"
                ),
                key=lambda period: (period.sequence, period.period_id),
            )
        )
        if not periods:
            raise ValueError("No named marking periods are available.")
    except Exception:
        write_lines(
            output,
            "Assessment discovery cannot verify the selected class/calendar.",
            "Inspect Core class metadata and academic periods before retrying.",
            "No academic record was changed.",
        )
        pause_for_user(input_fn)
        return

    while True:
        clear_fn()
        print_menu_header(output, "Discover Registered Assessments")
        write_lines(
            output,
            f"Class: {class_id}",
            f"School year: {year}",
            "Choose a marking period to inspect registered assessments.",
            "",
        )
        for index, period in enumerate(periods, start=1):
            print(f"{index}. {period.label}", file=output)
        write_lines(output, "")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        navigation = parse_navigation_choice(raw)
        if navigation is NavigationChoice.BACK or raw == "":
            return
        if not (raw.isascii() and raw.isdigit()):
            write_lines(output, "Select a numbered marking period, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        ordinal = int(raw)
        if not 1 <= ordinal <= len(periods):
            write_lines(output, "The marking period number is unavailable.")
            pause_for_user(input_fn)
            continue
        selected_period = periods[ordinal - 1]
        try:
            named = load_named_assessment_choices(
                root,
                class_id=class_id,
                school_year=year,
                period_id=selected_period.period_id,
            )
            if (
                named.class_id != class_id
                or named.school_year != year
                or named.period_id != selected_period.period_id
            ):
                raise ValueError("Named assessment results escaped the selected scope.")
            by_identity = {item.choice.identity: item for item in named.items}
            if len(by_identity) != len(named.items) or len(named.choices) != len(
                named.items
            ):
                raise ValueError("Named assessment choices are ambiguous.")
        except Exception:
            write_lines(
                output,
                "Registered assessment choices could not be verified safely.",
                "Refresh Core's derived academic catalog and try again.",
                "No setup or academic selection was attempted.",
            )
            pause_for_user(input_fn)
            continue

        search = ""
        page_index = 0
        while True:
            page = page_teacher_choices(
                named.choices, query=search, page_index=page_index
            )
            page_index = page.page_number - 1
            clear_fn()
            print_menu_header(output, "Registered Assessments — Read Only")
            write_lines(
                output,
                f"Class: {class_id}",
                f"Period: {selected_period.label} ({selected_period.period_id})",
                f"Matches: {page.match_count} | "
                f"Page {page.page_number} of {page.page_count}",
                "Catalog statuses are hints, not verified Grade Item readiness.",
                "",
            )
            for index, choice in enumerate(page.items, start=1):
                print(f"{index}. {choice.display}", file=output)
            if not page.items:
                write_lines(output, "No assessments match this search.")
            write_lines(
                output,
                "",
                "F. Find by name   C. Clear search",
                "N. Next page   P. Previous page",
                "B. Back to marking periods",
                "",
                "Setup execution is not enabled in this read-only view.",
            )
            print_standard_navigation(output, back=False)
            raw = read_choice(input_fn)
            navigation = parse_navigation_choice(raw)
            if navigation is NavigationChoice.BACK or raw == "":
                break
            lowered = raw.casefold()
            if lowered == "n":
                if page.has_next:
                    page_index += 1
                continue
            if lowered == "p":
                if page.has_previous:
                    page_index -= 1
                continue
            if lowered == "c":
                search, page_index = "", 0
                continue
            if lowered == "f":
                value = read_choice(input_fn, "Assessment name search: ")
                if len(value) > 120 or any(ord(ch) < 32 for ch in value):
                    write_lines(
                        output, "Search must be at most 120 visible characters."
                    )
                    pause_for_user(input_fn)
                else:
                    search, page_index = value, 0
                continue
            if raw.isascii() and raw.isdigit():
                choice_number = int(raw)
                if 1 <= choice_number <= len(page.items):
                    choice = page.items[choice_number - 1]
                    selected = by_identity.get(choice.identity)
                    if selected is None:
                        write_lines(
                            output,
                            "Assessment identity changed; reopen discovery.",
                        )
                        pause_for_user(input_fn)
                        return
                    clear_fn()
                    print_menu_header(output, "Assessment Registration Detail")
                    write_lines(
                        output,
                        f"Assessment: {selected.candidate.title}",
                        f"Producer: {choice.source or 'Unknown'}",
                        f"Registration revision: "
                        f"{selected.candidate.registration_revision}",
                        f"Publication: {selected.publication_state}",
                        f"Catalog setup hint: {selected.candidate.setup_state}",
                        f"Marking period: {selected_period.label}",
                        "",
                        "No Grade Item readiness, currentness or write "
                        "authority was established.",
                        "Setup execution is not enabled on this screen.",
                    )
                    pause_for_user(input_fn)
                    continue
            write_lines(output, "Choose a displayed number, F, C, N, P, B, M or Q.")
            pause_for_user(input_fn)


__all__ = ("run_teacher_assessment_discovery_menu",)
