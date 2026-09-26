from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_proficiency import (
    AcademicPeriodProficiencyPresentation,
    GradeItemProficiencyPresentation,
    PlanningReadinessPresentation,
    ProficiencyMenuDependencies,
    run_proficiency_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _grade_item() -> GradeItemProficiencyPresentation:
    return GradeItemProficiencyPresentation(
        class_id="class_1",
        grade_item_id="essay_1",
        grade_item_title="Essay 1",
        student_id="student_1",
        standard_id="NJSLSA.W1",
        result_revision=2,
        result_sha256="a" * 64,
        policy_title="Most Recent Evidence",
        scale_title="Course Proficiency",
        status="calculated",
        proficiency_label="Meeting",
        performance_count=3,
        native_state_count=1,
        excluded_count=2,
    )


def _period() -> AcademicPeriodProficiencyPresentation:
    return AcademicPeriodProficiencyPresentation(
        class_id="class_1",
        school_year="2026-2027",
        period_id="mp1",
        period_label="Marking Period 1",
        student_id="student_1",
        standard_id="NJSLSA.W1",
        result_revision=4,
        result_sha256="b" * 64,
        policy_title="Current Grade Items",
        scale_title="Course Proficiency",
        status="calculated",
        proficiency_label="Meeting",
        calculated_count=4,
        insufficient_count=0,
        missing_count=1,
        period_scope_mismatch_count=0,
    )


def _planning(selected: bool = True) -> PlanningReadinessPresentation:
    return PlanningReadinessPresentation(
        class_id="class_1",
        policy_id="support_groups",
        policy_title="Writing Support Groups" if selected else None,
        period_text="2026-2027 / mp1" if selected else None,
        standard_id="NJSLSA.W1" if selected else None,
        dimension_id="writing_support" if selected else None,
        status="generated" if selected else "blocked",
        blocker_codes=() if selected else ("no_selected_policy",),
        ready=selected,
        roster_count=24 if selected else None,
        contributing_count=20 if selected else None,
        noncontributing_count=4 if selected else None,
        policy_revision=3 if selected else None,
        policy_sha256="c" * 64 if selected else None,
        derivation_id="derivation_1" if selected else None,
        calculation_fingerprint="d" * 64 if selected else None,
    )


def _deps(selected: bool = True) -> ProficiencyMenuDependencies:
    return ProficiencyMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        grade_item_loader=lambda *_args: _grade_item(),
        academic_period_loader=lambda *_args: _period(),
        planning_loader=lambda *_args: _planning(selected),
    )


def test_grade_item_primary_view_hides_exact_digest() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "essay_1",
            "student_1",
            "NJSLSA.W1",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Grade Item: Essay 1" in rendered
    assert "Current proficiency: Meeting" in rendered
    assert "Evidence: 3 performance, 1 native-state, 2 excluded" in rendered
    assert "result_sha256" not in rendered


def test_grade_item_technical_view_exposes_exact_result() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "essay_1",
            "student_1",
            "NJSLSA.W1",
            "t",
            "",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Technical details / provenance" in rendered
    assert "result_revision: 2" in rendered
    assert f"result_sha256: {'a' * 64}" in rendered


def test_academic_period_primary_view_is_low_density() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "2026-2027",
            "mp1",
            "student_1",
            "NJSLSA.W1",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Academic Period: Marking Period 1" in rendered
    assert "Current proficiency: Meeting" in rendered
    assert "4 calculated, 0 insufficient, 1 missing" in rendered
    assert "result_sha256" not in rendered


def test_planning_readiness_preserves_read_only_boundary() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_deps(),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "support_groups",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Policy: Writing Support Groups" in rendered
    assert "Readiness: generated" in rendered
    assert "24 rostered, 20 contributing, 4 noncontributing" in rendered
    assert "Nothing has been written or exported from this review." in rendered
    assert "candidate_calculation_fingerprint" not in rendered


def test_planning_missing_selection_is_not_inferred() -> None:
    output = StringIO()
    run_proficiency_menu(
        dependencies=_deps(False),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "support_groups",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "No grouping-signal policy is currently selected" in rendered
    assert "no selected policy" in rendered


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_proficiency_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_proficiency_menu(
            dependencies=_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_cancel_before_scope_does_not_call_grade_item_service() -> None:
    called = False

    def load(*_args: object) -> GradeItemProficiencyPresentation:
        nonlocal called
        called = True
        return _grade_item()

    deps = ProficiencyMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        grade_item_loader=load,
        academic_period_loader=lambda *_args: _period(),
        planning_loader=lambda *_args: _planning(),
    )
    run_proficiency_menu(
        dependencies=deps,
        input_fn=ScriptedInput("1", "", "b"),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert called is False
