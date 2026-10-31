"""Keyboard-first read-only teacher choice rendering for Issue #123 Slice 2.

This module cannot execute a domain action. Selecting a row returns only an
opaque transient candidate, which domain code must revalidate and authorize.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.menu_ui import ClearFunction, InputFunction
from meridian.teacher_navigation_choices import (
    DEFAULT_PAGE_SIZE,
    MAX_CHOICES,
    TeacherChoice,
    TeacherChoiceCatalog,
    TeacherChoiceUnavailable,
    load_teacher_choices,
    page_teacher_choices,
    search_teacher_choices,
)


def _render(
    *,
    output: TextIO,
    title: str,
    question: str,
    choices: tuple[TeacherChoice, ...],
    query: str,
    page_index: int,
    page_size: int,
) -> None:
    page = page_teacher_choices(
        choices, query=query, page_index=page_index, page_size=page_size
    )
    print("Meridian / " + title, file=output)
    print(question, file=output)
    print(
        f"Matches: {page.match_count} | Page {page.page_number}/{page.page_count}",
        file=output,
    )
    if query:
        print(f"Search: {query}", file=output)
    print(file=output)
    if page.match_count == 0:
        print(
            "No matching current choices. Try S to search or C to clear.", file=output
        )
    for number, item in enumerate(page.items, start=1):
        print(f"{number}. {item.display}", file=output)
    print(file=output)
    if page.has_next:
        print("N. Next page", file=output)
    if page.has_previous:
        print("P. Previous page", file=output)
    print("S. Search | C. Clear search | R. Refresh", file=output)
    if page.items:
        print("T. Advanced / exact record details", file=output)
    print("B. Back | M. Main Menu | Q. Quit", file=output)


def _advanced_details(
    *,
    items: tuple[TeacherChoice, ...],
    input_fn: InputFunction,
    output: TextIO,
) -> None:
    """Opt-in diagnostics for a *single* visible row, not a bulk ID dump."""
    raw = input_fn("Technical details for row (blank to cancel): ").strip()
    navigation = parse_navigation_choice(raw)
    if not raw or navigation is NavigationChoice.BACK:
        return
    if (
        not raw.isascii()
        or not raw.isdecimal()
        or len(raw) > 4
        or not 1 <= int(raw) <= len(items)
    ):
        print("Choose a displayed row number or B.", file=output)
        return
    item = items[int(raw) - 1]
    print("Advanced / exact record details (read-only)", file=output)
    print(f"Label: {item.display}", file=output)
    for number, value in enumerate(item.identity, start=1):
        print(f"Canonical identity part {number}: {value}", file=output)
    print(f"Currentness witness: {item.witness or 'Unavailable'}", file=output)
    print("A later action must still reload and authorize this record.", file=output)
    input_fn("Press Enter to return to choices...")


def select_teacher_choice(
    *,
    catalog: TeacherChoiceCatalog,
    scope: str,
    title: str,
    question: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    selected: Mapping[str, str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_choices: int = MAX_CHOICES,
) -> TeacherChoice | None:
    """Select one verified, exact row or cancel; never silently select a row.

    B/blank returns None. M/Q propagate Core navigation to the main loop.
    R explicitly re-enumerates. At row selection, exact display, identity,
    state and witness must all match a fresh read; no silent replacement.
    Domain adapters MUST recheck at operation time (including authorization).
    """
    if not 1 <= page_size <= 25 or isinstance(page_size, bool):
        raise ValueError("Invalid selector page_size.")
    context = dict(selected or {})
    try:
        choices = load_teacher_choices(
            catalog, scope=scope, selected=context, max_choices=max_choices
        )
    except TeacherChoiceUnavailable:
        print("Current choices could not be verified safely.", file=output)
        print("No record was selected or changed.", file=output)
        return None
    query = ""
    page_index = 0
    while True:
        clear_fn()
        page = page_teacher_choices(
            choices, query=query, page_index=page_index, page_size=page_size
        )
        page_index = page.page_number - 1
        _render(
            output=output,
            title=title,
            question=question,
            choices=choices,
            query=query,
            page_index=page_index,
            page_size=page_size,
        )
        raw = input_fn("Choice: ").strip()
        nav = parse_navigation_choice(raw)
        if not raw or nav is NavigationChoice.BACK:
            return None
        command = raw.casefold()
        if command == "n" and page.has_next:
            page_index += 1
            continue
        if command == "p" and page.has_previous:
            page_index -= 1
            continue
        if command == "c":
            query = ""
            page_index = 0
            continue
        if command == "r":
            try:
                choices = load_teacher_choices(
                    catalog, scope=scope, selected=context, max_choices=max_choices
                )
            except TeacherChoiceUnavailable:
                print("Refresh failed safely. No record was selected.", file=output)
                return None
            page_index = 0
            continue
        if command == "s":
            typed = input_fn("Search visible names (blank clears; B cancels): ")
            search_nav = parse_navigation_choice(typed.strip())
            if search_nav is NavigationChoice.BACK:
                continue
            try:
                search_teacher_choices(choices, typed)
            except ValueError:
                print("That search text is not supported.", file=output)
                continue
            query = typed.strip()
            page_index = 0
            continue
        if command == "t" and page.items:
            _advanced_details(items=page.items, input_fn=input_fn, output=output)
            continue
        if raw.isascii() and raw.isdecimal() and len(raw) <= 4:
            number = int(raw)
            if 1 <= number <= len(page.items):
                choice = page.items[number - 1]
                try:
                    refreshed = load_teacher_choices(
                        catalog, scope=scope, selected=context, max_choices=max_choices
                    )
                except TeacherChoiceUnavailable:
                    print("The choice could not be reverified safely.", file=output)
                    print("No record was selected or changed.", file=output)
                    return None
                if choice in refreshed:
                    return choice
                print(
                    "Stale choice: its exact record or description changed.",
                    file=output,
                )
                print("Review the refreshed list before selecting again.", file=output)
                choices = refreshed
                page_index = 0
                continue
        print("Choose a visible number or one of the listed shortcuts.", file=output)


__all__ = ("select_teacher_choice",)
