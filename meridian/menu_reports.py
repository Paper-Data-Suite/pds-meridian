"""Teacher-first Reports discovery and guided selection, Issue #111 Slice 12.2.

Report computations remain in the existing report engine / direct CLI.
Read-only live canonical discovery is enabled; preview/export follow later.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Final, TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.report_guided_selection import (
    REPORT_GUIDES,
    ReportChoiceCatalog,
    ReportPreparedSelection,
    collect_guided_report_selection,
)
from meridian.report_live_catalog import LiveReportChoiceCatalog

# Retained for API and historical report-family identity compatibility.
REPORT_MENU_TITLES: Final[tuple[str, ...]] = (
    "SIS Gradebook Reconciliation",
    "Student Current Grade Justification",
    "Class Standards Profile",
    "Student Proficiency Growth / Trajectory",
    "Evidence Coverage / Sufficiency",
    "Grade Checkpoint Comparison",
    "Marking-Period Readiness",
    "Grade Item / Assessment Impact",
)

SelectionHandler = Callable[[ReportPreparedSelection], None]


def _report_detail(
    *,
    index: int,
    catalog: ReportChoiceCatalog | None,
    on_prepared: SelectionHandler | None,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    guide = REPORT_GUIDES[index]
    while True:
        clear_fn()
        print_menu_header(output, "About this report")
        write_lines(
            output,
            guide.question,
            "",
            guide.explanation,
            "",
            "You will choose:",
        )
        labels = {
            "class": "Class",
            "period": "Marking period",
            "student": "Student",
            "grade_item": "Assignment or assessment",
            "checkpoint": "Earlier grade checkpoint",
            "mapping": "Teacher's external gradebook mapping",
        }
        for item in guide.scopes:
            print(f"  - {labels[item]}", file=output)
        write_lines(
            output,
            "",
            "1. Choose report details",
            "T. Advanced command information",
            "",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            return
        if choice.casefold() == "t":
            write_lines(
                output,
                "",
                "For advanced use:",
                guide.advanced_command,
                "This generates no report by itself.",
                "",
            )
            input_fn("Press Enter to return to this report...")
            continue
        if choice == "1":
            if catalog is None:
                write_lines(
                    output,
                    "",
                    "Verified class choices are not available.",
                    "Try checking your workspace and academic calendar.",
                    "No report was generated or saved.",
                    "",
                )
                input_fn("Press Enter to return to this report...")
                continue
            prepared = collect_guided_report_selection(
                guide,
                catalog=catalog,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            if prepared is None:
                continue
            if on_prepared is not None:
                on_prepared(prepared)
            else:
                write_lines(
                    output,
                    "",
                    "Your selections are ready.",
                    "Preview/export wiring is a later Slice 12 increment.",
                    "No report was generated or saved.",
                )
                input_fn("Press Enter to return to this report...")
            continue
        write_lines(output, "", "Choose 1, T, B, M, or Q.")


def run_reports_menu(
    *,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
    catalog: ReportChoiceCatalog | None = None,
    on_prepared: SelectionHandler | None = None,
) -> None:
    """Show eight teacher-facing questions, preserving Core B/M/Q semantics."""
    stream = sys.stdout if output is None else output
    active_catalog = LiveReportChoiceCatalog() if catalog is None else catalog
    while True:
        clear_fn()
        print_menu_header(stream, "Reports")
        write_lines(
            stream,
            "What would you like to find out?",
            "Choose a question to see what the report shows.",
            "",
        )
        for index, guide in enumerate(REPORT_GUIDES, start=1):
            print(f"{index}. {guide.question}", file=stream)
            print(f"   {REPORT_MENU_TITLES[index - 1]}", file=stream)
        write_lines(
            stream,
            "",
            "Guided choices use your existing class and reporting records.",
            "Reports are read-only and do not write to an external gradebook.",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            return
        if choice in {str(number) for number in range(1, 9)}:
            _report_detail(
                index=int(choice) - 1,
                catalog=active_catalog,
                on_prepared=on_prepared,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-8, B, M, or Q.")


__all__ = ("REPORT_MENU_TITLES", "run_reports_menu")
