"""Teacher-facing Meridian main-menu foundation for issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, TextIO, TypeAlias

from pds_core.menu_navigation import (
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.diagnostics import DiagnosticsDependencies
from meridian.menu_evidence import (
    default_evidence_menu_dependencies,
    run_new_evidence_menu,
)
from meridian.menu_explain import run_explain_menu
from meridian.menu_export import run_export_menu
from meridian.menu_grade_items import run_grade_items_menu
from meridian.menu_grades import run_grade_preview_menu
from meridian.menu_overrides import run_overrides_menu
from meridian.menu_proficiency import (
    default_grade_item_proficiency_action_dependencies,
    run_proficiency_menu,
)
from meridian.menu_snapshots import (
    default_snapshot_freeze_dependencies,
    run_snapshots_menu,
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

TeacherMenuTaskId: TypeAlias = Literal[
    "review-new-evidence",
    "manage-grade-items",
    "review-proficiency",
    "preview-grades",
    "overrides",
    "snapshots",
    "export",
    "explain",
]
MenuTaskHandler: TypeAlias = Callable[[], None]


@dataclass(frozen=True, slots=True)
class TeacherMenuTask:
    """Stable symbolic identity plus teacher-facing presentation for one task."""

    task_id: TeacherMenuTaskId
    number: int
    title: str


TEACHER_MENU_TASKS: Final[tuple[TeacherMenuTask, ...]] = (
    TeacherMenuTask("review-new-evidence", 1, "Review New Evidence"),
    TeacherMenuTask("manage-grade-items", 2, "Manage Grade Items"),
    TeacherMenuTask("review-proficiency", 3, "Review Proficiency"),
    TeacherMenuTask("preview-grades", 4, "Preview Grades"),
    TeacherMenuTask("overrides", 5, "Overrides"),
    TeacherMenuTask("snapshots", 6, "Snapshots"),
    TeacherMenuTask("export", 7, "Export"),
    TeacherMenuTask("explain", 8, "Explain"),
)


@dataclass(frozen=True, slots=True)
class TeacherMenuDependencies:
    """Injected task routes; menu numbering never becomes workflow authority."""

    review_new_evidence: MenuTaskHandler
    manage_grade_items: MenuTaskHandler
    review_proficiency: MenuTaskHandler
    preview_grades: MenuTaskHandler
    overrides: MenuTaskHandler
    snapshots: MenuTaskHandler
    export: MenuTaskHandler
    explain: MenuTaskHandler

    def handler_for(self, task_id: TeacherMenuTaskId) -> MenuTaskHandler:
        """Resolve one stable symbolic task to its injected application route."""
        if task_id == "review-new-evidence":
            return self.review_new_evidence
        if task_id == "manage-grade-items":
            return self.manage_grade_items
        if task_id == "review-proficiency":
            return self.review_proficiency
        if task_id == "preview-grades":
            return self.preview_grades
        if task_id == "overrides":
            return self.overrides
        if task_id == "snapshots":
            return self.snapshots
        if task_id == "export":
            return self.export
        if task_id == "explain":
            return self.explain
        raise AssertionError(f"Unhandled teacher menu task: {task_id!r}")


def default_teacher_menu_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> TeacherMenuDependencies:
    """Compose the eight real teacher controllers over one terminal session."""

    stream = sys.stdout if output is None else output
    evidence_dependencies = default_evidence_menu_dependencies(
        diagnostics=diagnostics,
    )
    freeze_dependencies = default_snapshot_freeze_dependencies(
        diagnostics=diagnostics,
    )
    proficiency_actions = default_grade_item_proficiency_action_dependencies(
        diagnostics=diagnostics,
    )

    return TeacherMenuDependencies(
        review_new_evidence=lambda: run_new_evidence_menu(
            dependencies=evidence_dependencies,
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        manage_grade_items=lambda: run_grade_items_menu(
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        review_proficiency=lambda: run_proficiency_menu(
            action_dependencies=proficiency_actions,
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        preview_grades=lambda: run_grade_preview_menu(
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        overrides=lambda: run_overrides_menu(
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        snapshots=lambda: run_snapshots_menu(
            freeze_dependencies=freeze_dependencies,
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        export=lambda: run_export_menu(
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
        explain=lambda: run_explain_menu(
            input_fn=input_fn,
            output=stream,
            clear_fn=clear_fn,
        ),
    )


def _task_for_choice(choice: str) -> TeacherMenuTask | None:
    for task in TEACHER_MENU_TASKS:
        if choice == str(task.number):
            return task
    return None


def _render_main_menu(output: TextIO) -> None:
    print_menu_header(output)
    for task in TEACHER_MENU_TASKS:
        print(f"{task.number}. {task.title}", file=output)
    print(file=output)
    print("H. Help", file=output)
    print_standard_navigation(
        output,
        back=False,
        main_menu=False,
    )


def _show_main_help(*, output: TextIO, input_fn: InputFunction) -> None:
    print_menu_header(output, "Help")
    write_lines(
        output,
        "Meridian helps teachers review academic evidence, proficiency, Grades,",
        "overrides, frozen reporting snapshots, and deliberate local exports.",
        "",
        "Meridian Grade and report outputs are teacher-controlled local PDS results.",
        "They do not prove that an SIS, LMS, or district gradebook was updated.",
        "",
        "Inside a task, use B for Back, M for Main Menu, and Q to Quit.",
        "For exact noninteractive commands, use: meridian --help",
    )
    pause_for_user(input_fn)


def run_menu(
    *,
    dependencies: TeacherMenuDependencies | None = None,
    diagnostics: DiagnosticsDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> int:
    """Run the composed low-density teacher application.

    Explicit dependencies remain injectable for qualification. Normal launch
    composes all eight real task controllers and passes one terminal session
    through every nested screen.
    """

    stream = sys.stdout if output is None else output
    active = dependencies or default_teacher_menu_dependencies(
        diagnostics=diagnostics,
        input_fn=input_fn,
        output=stream,
        clear_fn=clear_fn,
    )
    while True:
        try:
            clear_fn()
            _render_main_menu(stream)
            choice = read_choice(input_fn)

            if choice.casefold() == "h":
                clear_fn()
                _show_main_help(output=stream, input_fn=input_fn)
                continue

            parse_navigation_choice(
                choice,
                allow_back=False,
                allow_main_menu=False,
                allow_quit=True,
            )

            task = _task_for_choice(choice)
            if task is not None:
                active.handler_for(task.task_id)()
                continue

            write_lines(stream, "", "Please choose 1-8, H, or Q.")
            pause_for_user(input_fn)
        except ReturnToMainMenu:
            continue
        except (QuitPDS, EOFError, KeyboardInterrupt):
            clear_fn()
            return 0
