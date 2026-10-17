"""Teacher-facing Meridian main-menu foundation for issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal, TextIO, TypeAlias

from pds_core.menu_navigation import (
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.diagnostics import (
    DiagnosticsDependencies,
    default_diagnostics_dependencies,
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
from meridian.menu_reports import run_reports_menu
from meridian.menu_snapshots import (
    default_snapshot_freeze_dependencies,
    run_snapshots_menu,
)
from meridian.menu_teacher_authorization import (
    run_teacher_evidence_authorization_menu,
)
from meridian.menu_teacher_evidence import (
    default_teacher_evidence_inbox_menu_dependencies,
    run_teacher_evidence_inbox_menu,
)
from meridian.menu_teacher_settings import run_teacher_settings_menu
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
from meridian.publication_authorization import (
    TeacherLocalPublicationAuthorizer,
)
from meridian.report_menu_execution import (
    LiveReportMenuExecutor,
    ReportMenuExecutionDependencies,
)
from meridian.teacher_attribution_input import (
    OneActionAttributionOverride,
    TeacherAttributionInput,
)
from meridian.teacher_profile import TeacherIdentityProvider, TeacherProfileStore
from meridian.teacher_session import TeacherSessionContext

TeacherMenuTaskId: TypeAlias = Literal[
    "review-new-evidence",
    "manage-grade-items",
    "review-proficiency",
    "preview-grades",
    "overrides",
    "snapshots",
    "export",
    "explain",
    "reports",
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
    TeacherMenuTask("reports", 9, "Reports"),
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
    reports: MenuTaskHandler
    session_context: TeacherSessionContext = field(
        default_factory=TeacherSessionContext
    )
    attribution_provider: TeacherIdentityProvider | None = None
    attribution_override: OneActionAttributionOverride | None = None
    setup_evidence_access: (
        Callable[[], TeacherLocalPublicationAuthorizer | None] | None
    ) = None

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
        if task_id == "reports":
            return self.reports
        raise AssertionError(f"Unhandled teacher menu task: {task_id!r}")


def default_teacher_menu_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
    session_context: TeacherSessionContext | None = None,
    attribution_provider: TeacherIdentityProvider | None = None,
    attribution_override: OneActionAttributionOverride | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> TeacherMenuDependencies:
    """Compose the nine real teacher controllers over one terminal session."""

    stream = sys.stdout if output is None else output
    next_attribution = attribution_override
    if next_attribution is None and attribution_provider is not None:
        next_attribution = OneActionAttributionOverride(attribution_provider)
    teacher_input: InputFunction = (
        TeacherAttributionInput(
            input_fn=input_fn,
            provider=attribution_provider,
            output=stream,
            override=next_attribution,
        )
        if attribution_provider is not None
        else input_fn
    )
    if diagnostics is None:
        diagnostics = default_diagnostics_dependencies()
    session = TeacherSessionContext() if session_context is None else session_context
    inbox_dependencies = default_teacher_evidence_inbox_menu_dependencies(
        diagnostics=diagnostics,
    )
    freeze_dependencies = default_snapshot_freeze_dependencies(
        diagnostics=diagnostics,
    )
    proficiency_actions = default_grade_item_proficiency_action_dependencies(
        diagnostics=diagnostics,
    )

    return TeacherMenuDependencies(
        review_new_evidence=lambda: run_teacher_evidence_inbox_menu(
            dependencies=inbox_dependencies,
            session_context=session,
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        manage_grade_items=lambda: run_grade_items_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        review_proficiency=lambda: run_proficiency_menu(
            action_dependencies=proficiency_actions,
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        preview_grades=lambda: run_grade_preview_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        overrides=lambda: run_overrides_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        snapshots=lambda: run_snapshots_menu(
            freeze_dependencies=freeze_dependencies,
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        export=lambda: run_export_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        explain=lambda: run_explain_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
        reports=lambda: run_reports_menu(
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
            executor=LiveReportMenuExecutor(
                ReportMenuExecutionDependencies(diagnostics=diagnostics)
            ),
        ),
        session_context=session,
        attribution_provider=attribution_provider,
        attribution_override=next_attribution,
        setup_evidence_access=lambda: run_teacher_evidence_authorization_menu(
            diagnostics=diagnostics,
            input_fn=teacher_input,
            output=stream,
            clear_fn=clear_fn,
        ),
    )


def _task_for_choice(choice: str) -> TeacherMenuTask | None:
    for task in TEACHER_MENU_TASKS:
        if choice == str(task.number):
            return task
    return None


def _render_main_menu(
    output: TextIO,
    *,
    setup_available: bool = False,
    pending_override: OneActionAttributionOverride | None = None,
) -> None:
    print_menu_header(output)
    for task in TEACHER_MENU_TASKS:
        print(f"{task.number}. {task.title}", file=output)
    print(file=output)
    if setup_available:
        print("A. Set Up Evidence Access", file=output)
    print("S. Teacher Settings / First-Time Setup", file=output)
    if pending_override is not None and pending_override.pending:
        print(
            "Temporary attribution armed for next action; use S to review/cancel.",
            file=output,
        )
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
        "overrides, frozen snapshots, local exports, and teacher reports.",
        "",
        "Meridian Grade and report outputs are teacher-controlled local PDS results.",
        "They do not prove that an SIS, LMS, or district gradebook was updated.",
        "",
        "S opens teacher identity and classroom navigation settings.",
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
    composes all nine real task controllers and passes one terminal session
    through every nested screen.
    """

    stream = sys.stdout if output is None else output
    active = dependencies or default_teacher_menu_dependencies(
        diagnostics=diagnostics,
        attribution_provider=TeacherIdentityProvider(TeacherProfileStore()),
        input_fn=input_fn,
        output=stream,
        clear_fn=clear_fn,
    )
    while True:
        try:
            clear_fn()
            _render_main_menu(
                stream,
                setup_available=active.setup_evidence_access is not None,
                pending_override=active.attribution_override,
            )
            choice = read_choice(input_fn)

            if choice.casefold() == "a" and (active.setup_evidence_access is not None):
                authorized = active.setup_evidence_access()
                if authorized is not None:
                    # Recompose protected readers with the newly loaded
                    # provider, without restarting Meridian.
                    active = default_teacher_menu_dependencies(
                        diagnostics=default_diagnostics_dependencies(
                            authorizer=authorized
                        ),
                        session_context=active.session_context,
                        attribution_provider=active.attribution_provider,
                        attribution_override=active.attribution_override,
                        input_fn=input_fn,
                        output=stream,
                        clear_fn=clear_fn,
                    )
                continue

            if choice.casefold() == "s":
                run_teacher_settings_menu(
                    session_context=active.session_context,
                    attribution_override=active.attribution_override,
                    profile_store=(
                        active.attribution_provider.store
                        if active.attribution_provider is not None
                        else None
                    ),
                    input_fn=input_fn,
                    output=stream,
                    clear_fn=clear_fn,
                )
                continue

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

            options = (
                "1-9, A, S, H, or Q"
                if (active.setup_evidence_access is not None)
                else "1-9, S, H, or Q"
            )
            write_lines(stream, "", f"Please choose {options}.")
            pause_for_user(input_fn)
        except ReturnToMainMenu:
            continue
        except (QuitPDS, EOFError, KeyboardInterrupt):
            if active.attribution_override is not None:
                active.attribution_override.clear()
            active.session_context.clear()
            clear_fn()
            return 0
