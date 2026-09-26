from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_explain import (
    ExplainMenuDependencies,
    ExplanationPresentation,
    run_explain_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _presentation(title: str) -> ExplanationPresentation:
    return ExplanationPresentation(
        title=title,
        lines=("Teacher-facing summary", "Changed: no"),
        technical_lines=("exact_id: object_1", "sha256: " + "a" * 64),
    )


def _deps(log: list[str] | None = None) -> ExplainMenuDependencies:
    events = [] if log is None else log

    def mark(name: str):
        def loader(*args: object) -> ExplanationPresentation:
            events.append(name)
            return _presentation(name)

        return loader

    return ExplainMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        current_grade=mark("current_grade"),  # type: ignore[arg-type]
        snapshot_comparison=mark("comparison"),  # type: ignore[arg-type]
        grade_item_proficiency=mark("grade_item"),  # type: ignore[arg-type]
        academic_period_proficiency=mark("period"),  # type: ignore[arg-type]
        planning_derivation=mark("derivation"),  # type: ignore[arg-type]
        planning_preview_review=mark("preview"),  # type: ignore[arg-type]
        planning_export=mark("planning_export"),  # type: ignore[arg-type]
        export_receipt=mark("receipt"),  # type: ignore[arg-type]
    )


def test_current_grade_summary_hides_technical_detail_until_requested() -> None:
    output = StringIO()
    run_explain_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Teacher-facing summary" in rendered
    assert "sha256: " + "a" * 64 not in rendered


def test_technical_details_do_not_rerun_loader() -> None:
    log: list[str] = []
    output = StringIO()
    run_explain_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "item_1",
            "student_1",
            "ELA.RL.1",
            "t",
            "",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["grade_item"]
    assert "sha256: " + "a" * 64 in output.getvalue()


def test_snapshot_comparison_routes_to_read_only_comparison_loader() -> None:
    log: list[str] = []
    run_explain_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "student_1",
            "snapshot_1",
            "b" * 64,
            "b",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["comparison"]


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("5", "derivation"),
        ("6", "preview"),
        ("7", "planning_export"),
        ("8", "receipt"),
    ],
)
def test_exact_explanation_routes(
    choice: str,
    expected: str,
) -> None:
    log: list[str] = []
    run_explain_menu(
        dependencies=_deps(log),
        input_fn=ScriptedInput(
            choice,
            "class_1",
            "exact_id",
            "b",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == [expected]


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_explain_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_explain_menu(
            dependencies=_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_dependency_contract_accepts_academic_period_type() -> None:
    deps = _deps()
    value = deps.current_grade(
        Path("workspace"),
        "class_1",
        "student_1",
        AcademicPeriodRef("2026-2027", "mp1"),
        4,
        "standards_based",
    )
    assert value.title == "current_grade"
