"""Teacher-facing Reports menu shell for Meridian Issue #111 Slice 6."""

from __future__ import annotations

import sys
from typing import Final, TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

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


def run_reports_menu(
    *,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    while True:
        clear_fn()
        print_menu_header(stream, "Reports")
        for index, title in enumerate(REPORT_MENU_TITLES, start=1):
            print(f"{index}. {title}", file=stream)
        write_lines(
            stream,
            "",
            "Report framework ready; report-specific generators are added",
            "in subsequent Issue #111 slices.",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice in {str(index) for index in range(1, 9)}:
            write_lines(
                stream, "", "That report generator is not implemented in Slice 6 yet."
            )
            pause_for_user(input_fn)
            continue
        write_lines(stream, "", "Please choose 1-8, B, M, or Q.")
        pause_for_user(input_fn)


__all__ = ["REPORT_MENU_TITLES", "run_reports_menu"]
