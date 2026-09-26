from __future__ import annotations

from io import StringIO

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu import (
    TEACHER_MENU_TASKS,
    TeacherMenuDependencies,
    TeacherMenuTaskId,
    run_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


def _dependencies(
    calls: list[TeacherMenuTaskId],
    *,
    override: tuple[TeacherMenuTaskId, object] | None = None,
) -> TeacherMenuDependencies:
    def handler(task_id: TeacherMenuTaskId):
        def run() -> None:
            if override is not None and override[0] == task_id:
                value = override[1]
                if isinstance(value, BaseException):
                    raise value
                if callable(value):
                    value()
                    return
            calls.append(task_id)

        return run

    return TeacherMenuDependencies(
        review_new_evidence=handler("review-new-evidence"),
        manage_grade_items=handler("manage-grade-items"),
        review_proficiency=handler("review-proficiency"),
        preview_grades=handler("preview-grades"),
        overrides=handler("overrides"),
        snapshots=handler("snapshots"),
        export=handler("export"),
        explain=handler("explain"),
    )


def test_teacher_menu_catalog_has_exact_issue57_order() -> None:
    assert tuple(
        (task.number, task.task_id, task.title) for task in TEACHER_MENU_TASKS
    ) == (
        (1, "review-new-evidence", "Review New Evidence"),
        (2, "manage-grade-items", "Manage Grade Items"),
        (3, "review-proficiency", "Review Proficiency"),
        (4, "preview-grades", "Preview Grades"),
        (5, "overrides", "Overrides"),
        (6, "snapshots", "Snapshots"),
        (7, "export", "Export"),
        (8, "explain", "Explain"),
    )


def test_main_menu_is_low_density_and_has_only_valid_top_navigation() -> None:
    output = StringIO()
    clears: list[str] = []

    assert run_menu(
        dependencies=_dependencies([]),
        input_fn=ScriptedInput("q"),
        output=output,
        clear_fn=lambda: clears.append("clear"),
    ) == 0

    rendered = output.getvalue()
    for task in TEACHER_MENU_TASKS:
        assert f"{task.number}. {task.title}" in rendered
    assert "H. Help" in rendered
    assert "Q. Quit" in rendered
    assert "B. Back" not in rendered
    assert "M. Main Menu" not in rendered
    assert "SHA-256" not in rendered
    assert "current.json" not in rendered
    assert len(clears) == 2


@pytest.mark.parametrize(
    ("choice", "task_id"),
    [
        ("1", "review-new-evidence"),
        ("2", "manage-grade-items"),
        ("3", "review-proficiency"),
        ("4", "preview-grades"),
        ("5", "overrides"),
        ("6", "snapshots"),
        ("7", "export"),
        ("8", "explain"),
    ],
)
def test_numbered_choice_dispatches_by_symbolic_task_identity(
    choice: str,
    task_id: TeacherMenuTaskId,
) -> None:
    calls: list[TeacherMenuTaskId] = []

    assert run_menu(
        dependencies=_dependencies(calls),
        input_fn=ScriptedInput(choice, "q"),
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert calls == [task_id]


def test_help_is_teacher_facing_and_redraws_main_menu() -> None:
    output = StringIO()
    clears: list[str] = []

    assert run_menu(
        dependencies=_dependencies([]),
        input_fn=ScriptedInput("h", "", "q"),
        output=output,
        clear_fn=lambda: clears.append("clear"),
    ) == 0

    rendered = output.getvalue()
    assert "Meridian\nHelp" in rendered
    assert "SIS, LMS, or district gradebook" in rendered
    assert "B for Back, M for Main Menu, and Q to Quit" in rendered
    assert "meridian --help" in rendered
    assert rendered.count("1. Review New Evidence") == 2
    assert len(clears) == 4


def test_invalid_choice_pauses_then_redraws() -> None:
    output = StringIO()

    assert run_menu(
        dependencies=_dependencies([]),
        input_fn=ScriptedInput("x", "", "q"),
        output=output,
        clear_fn=lambda: None,
    ) == 0

    assert "Please choose 1-8, H, or Q." in output.getvalue()


def test_return_to_main_menu_unwinds_nested_task() -> None:
    calls: list[TeacherMenuTaskId] = []

    assert run_menu(
        dependencies=_dependencies(
            calls,
            override=("review-new-evidence", ReturnToMainMenu()),
        ),
        input_fn=ScriptedInput("1", "q"),
        output=StringIO(),
        clear_fn=lambda: None,
    ) == 0

    assert calls == []


def test_quit_unwinds_nested_task_and_exits_cleanly() -> None:
    calls: list[TeacherMenuTaskId] = []
    clears: list[str] = []

    assert run_menu(
        dependencies=_dependencies(
            calls,
            override=("preview-grades", QuitPDS()),
        ),
        input_fn=ScriptedInput("4"),
        output=StringIO(),
        clear_fn=lambda: clears.append("clear"),
    ) == 0

    assert calls == []
    assert len(clears) == 2


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
def test_terminal_exit_signals_are_clean(error: BaseException) -> None:
    def raising_input(prompt: str) -> str:
        _ = prompt
        raise error

    clears: list[str] = []
    assert run_menu(
        dependencies=_dependencies([]),
        input_fn=raising_input,
        output=StringIO(),
        clear_fn=lambda: clears.append("clear"),
    ) == 0
    assert len(clears) == 2


def test_main_menu_uses_clear_redraw_between_task_visits() -> None:
    clears: list[str] = []

    assert run_menu(
        dependencies=_dependencies([]),
        input_fn=ScriptedInput("1", "q"),
        output=StringIO(),
        clear_fn=lambda: clears.append("clear"),
    ) == 0

    # Initial main screen, redraw after the task returns, then clean exit.
    assert len(clears) == 3
