from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.calculation_preview_assembly_workflow import BoundedCalculationPreview
from meridian.menu_proficiency import (
    GradeItemProficiencyActionDependencies,
    ProficiencyMenuDependencies,
    run_proficiency_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _menu_deps() -> ProficiencyMenuDependencies:
    return ProficiencyMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        grade_item_loader=lambda *_args: cast(object, object()),
        academic_period_loader=lambda *_args: cast(object, object()),
        planning_loader=lambda *_args: cast(object, object()),
    )  # type: ignore[arg-type]


def _preview() -> BoundedCalculationPreview:
    outcome = SimpleNamespace(
        status="calculated",
        proficiency_level_id="meeting",
        performance_observation_count=2,
        native_state_count=0,
        excluded_count=0,
    )
    calculation = SimpleNamespace(
        outcome=outcome,
        policy_title="Standards Policy",
        strategy="highest",
        current_result_revision=1,
        next_result_revision=2,
        inputs_sha256="a" * 64,
        calculation_fingerprint="b" * 64,
    )
    return cast(
        BoundedCalculationPreview,
        SimpleNamespace(
            grade_item_id="essay",
            student_id="student_1",
            standard_id="NJSLSA.R1",
            calculation=calculation,
            binding_count=2,
        ),
    )


def _actions(
    log: list[str],
    *,
    persistence_preview: object | None = None,
    selection_preview: object | None = None,
) -> GradeItemProficiencyActionDependencies:
    return GradeItemProficiencyActionDependencies(
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        diagnostics=cast(object, object()),  # type: ignore[arg-type]
        preview_builder=lambda *_args: _preview(),
        persistence_previewer=lambda *_args: persistence_preview,
        persistence_committer=lambda *_args: (
            log.append("write")
            or SimpleNamespace(
                write_result=SimpleNamespace(disposition="created"),
                written_revision=2,
                written_status="calculated",
                written_result_sha256="c" * 64,
            )
        ),
        selection_previewer=lambda *_args: selection_preview,
        selection_committer=lambda *_args: (
            log.append("select")
            or SimpleNamespace(
                selection_disposition="updated",
                selected_revision=2,
                selected_status="calculated",
            )
        ),
    )  # type: ignore[arg-type]


def test_proficiency_menu_exposes_grade_item_result_workflows() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Preview Grade Item proficiency calculation" in rendered
    assert "Write Grade Item proficiency result" in rendered
    assert "Select Grade Item proficiency result" in rendered


def test_grade_item_preview_is_read_only() -> None:
    log: list[str] = []
    output = StringIO()
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions(log),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "essay",
            "student_1",
            "NJSLSA.R1",
            "four_level",
            "2",
            "a" * 64,
            "policy_1",
            "3",
            "b" * 64,
            "teacher_review",
            "",
            "0",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    rendered = output.getvalue()
    assert "This is a read-only calculation preview." in rendered
    assert "No result revision or current selection has changed." in rendered


def test_grade_item_result_write_cancel_does_not_commit() -> None:
    log: list[str] = []
    persistence = SimpleNamespace(
        candidate_revision=2,
        candidate_status="calculated",
        candidate_proficiency_level_id="meeting",
        candidate_calculation_fingerprint="d" * 64,
        selected_revision_before=1,
    )
    output = StringIO()
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions(
            log,
            persistence_preview=persistence,
        ),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "essay",
            "student_1",
            "NJSLSA.R1",
            "four_level",
            "2",
            "a" * 64,
            "policy_1",
            "3",
            "b" * 64,
            "teacher_review",
            "",
            "0",
            "teacher_1",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    assert "Writing this immutable result will NOT select it" in output.getvalue()


def test_grade_item_result_selection_requires_select() -> None:
    log: list[str] = []
    selection = SimpleNamespace(
        grade_item_id="essay",
        student_id="student_1",
        standard_id="NJSLSA.R1",
        target_revision=2,
        target_status="calculated",
        target_proficiency_level_id="meeting",
        target_result_sha256="e" * 64,
        expected_current_result_revision=1,
        target_is_latest=True,
    )
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions(log, selection_preview=selection),
        input_fn=ScriptedInput(
            "6",
            "class_1",
            "essay",
            "student_1",
            "NJSLSA.R1",
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]
