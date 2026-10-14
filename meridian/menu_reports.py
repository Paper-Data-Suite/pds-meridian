"""Teacher-facing Reports menu shell for Meridian Issue #111 Slice 11."""

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
            "Reports 1-8 are available now.",
            "Guided selectors are completed in the next Issue #111 slice.",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            write_lines(
                stream,
                "",
                "SIS Gradebook Reconciliation is available through:",
                "meridian reports reconciliation --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "2":
            write_lines(
                stream,
                "",
                "Student Grade Justification is available through:",
                "meridian reports justify --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "3":
            write_lines(
                stream,
                "",
                "Class Standards Profile is available through:",
                "meridian reports standards profile --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "4":
            write_lines(
                stream,
                "",
                "Student Proficiency Growth is available through:",
                "meridian reports standards growth --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "5":
            write_lines(
                stream,
                "",
                "Evidence Coverage / Missing & Incomplete Evidence is "
                "available through:",
                "meridian reports evidence --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "6":
            write_lines(
                stream,
                "",
                "Grade Checkpoint Comparison is available through:",
                "meridian reports checkpoint --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "7":
            write_lines(
                stream,
                "",
                "Marking-Period Readiness is available through:",
                "meridian reports readiness --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        if choice == "8":
            write_lines(
                stream,
                "",
                "Grade Item / Assessment Impact is available through:",
                "meridian reports impact --help",
                "Guided selectors arrive in the report-menu hardening slice.",
            )
            pause_for_user(input_fn)
            continue
        write_lines(stream, "", "Please choose 1-8, B, M, or Q.")
        pause_for_user(input_fn)


__all__ = ["REPORT_MENU_TITLES", "run_reports_menu"]
