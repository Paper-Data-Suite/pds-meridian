"""Shared low-density terminal helpers for Meridian's teacher menu."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import print_navigation_options

InputFunction: TypeAlias = Callable[[str], str]
ClearFunction: TypeAlias = Callable[[], None]


def clear_screen() -> None:
    """Clear an interactive terminal without affecting captured output."""
    try:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, OSError):
        interactive = False
    if interactive:
        os.system("cls" if os.name == "nt" else "clear")


def write_lines(output: TextIO, *lines: str) -> None:
    """Write bounded teacher-facing lines to one output stream."""
    for line in lines:
        print(line, file=output)


def print_menu_header(output: TextIO, title: str | None = None) -> None:
    """Render Meridian identity plus an optional focused screen title."""
    print("Meridian", file=output)
    if title is not None:
        print(title, file=output)
    print(file=output)


def print_standard_navigation(
    output: TextIO,
    *,
    back: bool = True,
    main_menu: bool = True,
    quit: bool = True,
) -> None:
    """Render Core-owned PDS navigation labels in the shared order."""
    print_navigation_options(
        back=back,
        main_menu=main_menu,
        quit=quit,
        file=output,
    )


def read_choice(input_fn: InputFunction, prompt: str = "Choice: ") -> str:
    """Read one bounded menu choice without interpreting application meaning."""
    return input_fn(prompt).strip()


def pause_for_user(input_fn: InputFunction) -> None:
    """Pause only when the teacher needs to read transient output."""
    input_fn("Press Enter to continue...")
