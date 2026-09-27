from __future__ import annotations

from pathlib import Path


def test_issue57_installed_wrapper_isolated_and_exercises_menu_contract() -> None:
    wrapper = Path("scripts/smoke_test_teacher_menu_wheel.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        '"pip", "check"',
        "scoreform_wheel",
        "quillan_wheel",
        "concord_wheel",
        "menu_planning_signal",
        'stdin="3\\n10\\nb\\nm\\nq\\n"',
        "Launching/quitting the installed menu created workspace state.",
        "B did not return to Review Proficiency.",
        "M did not return to the main menu.",
        "Direct CLI command became interactive.",
        "Issue #57 installed teacher-menu acceptance passed.",
    ):
        assert token in wrapper


def test_issue57_repository_validation_runs_installed_menu_smoke() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert "scripts.installed_qualification_runner" in validator
    assert "teacher-menu" in runner
    assert "DependencyMatrixId.ALL_ADAPTERS" in runner
