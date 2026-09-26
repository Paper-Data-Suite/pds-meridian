from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.academic_period_calculation_assembly_workflow import (
    BoundedAcademicPeriodCalculationPreview,
)
from meridian.menu_proficiency import (
    AcademicPeriodProficiencyActionDependencies,
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


def _grade_item_actions() -> GradeItemProficiencyActionDependencies:
    return cast(GradeItemProficiencyActionDependencies, object())


def _preview() -> BoundedAcademicPeriodCalculationPreview:
    outcome = SimpleNamespace(
        status="calculated",
        proficiency_level_id="meeting",
        calculated_result_count=2,
        insufficient_result_count=0,
        missing_result_count=0,
        period_scope_mismatch_count=0,
    )
    calculation = SimpleNamespace(
        outcome=outcome,
        student_id="student_1",
        standard_id="NJSLSA.R1",
        target_period_title="Marking Period 1",
        policy_title="Period Policy",
        strategy="mode",
        current_result_revision=1,
        next_result_revision=2,
        inputs_sha256="a" * 64,
        calculation_fingerprint="b" * 64,
    )
    inputs = SimpleNamespace(
        target_scale=SimpleNamespace(scale_id="four_level"),
    )
    return cast(
        BoundedAcademicPeriodCalculationPreview,
        SimpleNamespace(
            calculation=calculation,
            inputs=inputs,
            candidate_count=2,
        ),
    )


def _actions(
    log: list[str],
    *,
    persistence_preview: object | None = None,
    selection_preview: object | None = None,
    captured: list[object] | None = None,
) -> AcademicPeriodProficiencyActionDependencies:
    def build(*args: object) -> BoundedAcademicPeriodCalculationPreview:
        if captured is not None:
            captured.extend(args)
        return _preview()

    return AcademicPeriodProficiencyActionDependencies(
        clock=lambda: datetime(2026, 9, 23, 22, 0, tzinfo=UTC),
        preview_builder=build,  # type: ignore[arg-type]
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


def _request_prefix(choice: str) -> tuple[str, ...]:
    return (
        choice,
        "class_1",
        "2026-2027",
        "mp1",
        "3",
        "student_1",
        "NJSLSA.R1",
        "period_policy",
        "2",
        "a" * 64,
    )


def test_proficiency_menu_exposes_academic_period_result_workflows() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_grade_item_actions(),
        period_action_dependencies=_actions([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Preview Academic Period proficiency calculation" in rendered
    assert "Write Academic Period proficiency result" in rendered
    assert "Select Academic Period proficiency result" in rendered


def test_academic_period_preview_is_read_only() -> None:
    log: list[str] = []
    output = StringIO()
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_grade_item_actions(),
        period_action_dependencies=_actions(log),
        input_fn=ScriptedInput(
            *_request_prefix("7"),
            "0",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    rendered = output.getvalue()
    assert "This is a read-only Academic Period calculation preview." in rendered
    assert "No result revision or current selection has changed." in rendered


def test_academic_period_request_preserves_exact_candidate_bindings() -> None:
    captured: list[object] = []
    run_proficiency_menu(
        dependencies=_menu_deps(),
        action_dependencies=_grade_item_actions(),
        period_action_dependencies=_actions([], captured=captured),
        input_fn=ScriptedInput(
            *_request_prefix("7"),
            "1",
            "essay",
            "4",
            "b" * 64,
            "1",
            "quillan",
            "work_1",
            "3",
            "c" * 64,
            "yes",
            "5",
            "d" * 64,
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert len(captured) == 6
    target = captured[1]
    candidates = captured[4]
    policy = captured[5]
    assert target.period.school_year == "2026-2027"  # type: ignore[attr-defined]
    assert target.period.period_id == "mp1"  # type: ignore[attr-defined]
    assert target.calendar_revision == 3  # type: ignore[attr-defined]
    assert policy.policy_id == "period_policy"  # type: ignore[attr-defined]
    candidate = candidates[0]  # type: ignore[index]
    assert candidate.grade_item_id == "essay"
    assert candidate.grade_item_revision == 4
    assert candidate.memberships[0].work.module_id == "quillan"
    assert candidate.memberships[0].work.work_id == "work_1"
    assert candidate.memberships[0].membership_revision == 3
    assert candidate.result_revision == 5
    assert candidate.result_sha256 == "d" * 64


def test_academic_period_result_write_cancel_does_not_commit() -> None:
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
        action_dependencies=_grade_item_actions(),
        period_action_dependencies=_actions(
            log,
            persistence_preview=persistence,
        ),
        input_fn=ScriptedInput(
            *_request_prefix("8"),
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


def test_academic_period_result_selection_requires_select() -> None:
    log: list[str] = []
    selection = SimpleNamespace(
        school_year="2026-2027",
        period_id="mp1",
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
        action_dependencies=_grade_item_actions(),
        period_action_dependencies=_actions(log, selection_preview=selection),
        input_fn=ScriptedInput(
            "9",
            "class_1",
            "2026-2027",
            "mp1",
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
