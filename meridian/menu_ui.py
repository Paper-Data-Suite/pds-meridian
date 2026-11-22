"""Shared, capability-aware terminal helpers for Meridian teacher menus.

Core 0.6.6 supplies B/M/Q but not the newer shared teacher header. Probe the
installed Core public capability on demand. Do not claim source-only Core
features are installed, import Core internals, or invent Notes operations.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from collections.abc import Callable
from importlib import import_module
from importlib.util import find_spec
from typing import TextIO, TypeAlias, cast

from pds_core.menu_navigation import print_navigation_options

InputFunction: TypeAlias = Callable[[str], str]
ClearFunction: TypeAlias = Callable[[], None]


class TeacherHeaderCompatibilityError(RuntimeError):
    """An advertised Core header contract is absent or incompatible."""


def _safe_title(title: str) -> None:
    """Never put untrusted terminal control characters in a teacher header."""
    if type(title) is not str or not title.strip():
        raise ValueError("A nonblank teacher-screen title is required.")
    if any(
        unicodedata.category(char).startswith("C")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in title
    ):
        raise ValueError("Teacher-screen titles cannot contain control characters.")


def _qualified_core_header() -> (
    tuple[Callable[..., object], Callable[..., None]] | None
):
    """Probe only installed public Core interfaces; pre-contract is a fallback.

    A missing teacher_experience module denotes historical Core. In contrast,
    a broken import inside an advertised contract is an incompatibility.
    Tokens are declarations of Core implementation, NOT a published-wheel
    provenance statement or a Meridian/Suite installed D3 attestation.
    """
    module_name = "pds_core.teacher_experience"
    try:
        spec = find_spec(module_name)
    except (ImportError, AttributeError, ValueError) as error:
        raise TeacherHeaderCompatibilityError(
            "Installed Core teacher-contract discovery failed."
        ) from error
    if spec is None:
        return None
    try:
        contract = import_module(module_name)
    except ImportError as error:
        raise TeacherHeaderCompatibilityError(
            "Installed Core advertises a broken teacher-contract import."
        ) from error
    if getattr(contract, "TEACHER_EXPERIENCE_CONTRACT_VERSION", None) != "1":
        raise TeacherHeaderCompatibilityError(
            "Unsupported installed Core teacher-contract version."
        )
    capability_reader = getattr(contract, "get_teacher_experience_capabilities", None)
    if not callable(capability_reader):
        raise TeacherHeaderCompatibilityError(
            "Installed Core has no callable teacher-capability reader."
        )
    try:
        capabilities = capability_reader()
    except Exception as error:
        raise TeacherHeaderCompatibilityError(
            "Installed Core teacher-capability reader failed."
        ) from error
    if type(capabilities) is not frozenset or any(
        type(value) is not str or not value.strip() for value in capabilities
    ):
        raise TeacherHeaderCompatibilityError(
            "Installed Core returned invalid teacher-capability tokens."
        )
    if "terminal.header.v1" not in capabilities:
        return None
    try:
        ui = import_module("pds_core.teacher_ui")
    except ImportError as error:
        raise TeacherHeaderCompatibilityError(
            "Installed Core advertises header support but cannot import it."
        ) from error
    header_type = getattr(ui, "TeacherScreenHeader", None)
    printer = getattr(ui, "print_teacher_header", None)
    if not isinstance(header_type, type) or not callable(printer):
        raise TeacherHeaderCompatibilityError(
            "Installed Core advertises an incomplete public header interface."
        )
    return cast(Callable[..., object], header_type), cast(Callable[..., None], printer)


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
    """Use the qualified Core v1 header or retain the plain old-Core fallback.

    Existing call sites depend on the blank line after the task header. Keep
    that spacing on both paths. Only Core's public printer decides ANSI color.
    """
    if title is None:
        print("Meridian", file=output)
        print(file=output)
        return
    _safe_title(title)
    capability = _qualified_core_header()
    if capability is not None:
        factory, printer = capability
        try:
            header = factory(application_name="Meridian", screen_title=title)
            printer(header, output=output, color="auto")
        except (TypeError, ValueError, AttributeError) as error:
            raise TeacherHeaderCompatibilityError(
                "Installed Core's advertised header interface is incompatible."
            ) from error
        print(file=output)
        return
    print("Meridian", file=output)
    print(title, file=output)
    print(file=output)


def print_standard_navigation(
    output: TextIO,
    *,
    back: bool = True,
    main_menu: bool = True,
    quit: bool = True,
) -> None:
    """Render Core-owned B/M/Q labels, never invent navigation meanings."""
    print_navigation_options(
        back=back,
        main_menu=main_menu,
        quit=quit,
        file=output,
    )


def read_choice(input_fn: InputFunction, prompt: str = "Choice: ") -> str:
    """Read a literal menu/data response; never intercept shared commands."""
    return input_fn(prompt).strip()


def pause_for_user(input_fn: InputFunction) -> None:
    """Pause without acting on commands or changing academic state."""
    input_fn("Press Enter to continue...")
