from __future__ import annotations

from pathlib import Path

TRACE_MODULES = (
    "meridian/grade_item_proficiency_explanation.py",
    "meridian/academic_period_proficiency_explanation.py",
    "meridian/planning_signal_derivation_explanation.py",
    "meridian/planning_signal_preview_review_explanation.py",
    "meridian/planning_signal_export_explanation.py",
)


def test_issue42_trace_runtime_modules_are_release_guarded() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in TRACE_MODULES:
        assert member in wheel_checker
        assert member in sdist_checker


def test_issue42_installed_smoke_is_release_guarded() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    wrapper = Path("scripts/smoke_test_explanation_traces_wheel.py").read_text(
        encoding="utf-8"
    )

    assert "smoke_test_explanation_traces_wheel.py" in validator
    assert "smoke_test_explanation_traces_wheel.py" in sdist_checker
    assert "smoke_program_explanation_traces.py" in sdist_checker
    assert '"--no-deps"' in wrapper
    assert "scoreform_wheel" not in wrapper
    assert "quillan_wheel" not in wrapper
    assert "concord_wheel" not in wrapper


def test_issue42_smoke_tests_all_packaged_trace_cli_surfaces() -> None:
    wrapper = Path("scripts/smoke_test_explanation_traces_wheel.py").read_text(
        encoding="utf-8"
    )
    for command in (
        "grade-item-proficiency",
        "academic-period-proficiency",
        "planning-derivation",
        "planning-export",
    ):
        assert command in wrapper
    assert "before_cli" in wrapper
    assert "after_cli" in wrapper
    assert "not deterministic" in wrapper
