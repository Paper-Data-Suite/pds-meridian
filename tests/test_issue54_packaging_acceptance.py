from __future__ import annotations

from pathlib import Path

RUNTIME_MODULES = (
    "meridian/grade_preview_explanation.py",
    "meridian/conventional_grade_explanation.py",
    "meridian/standards_grade_explanation.py",
    "meridian/hybrid_grade_explanation.py",
    "meridian/current_grade_preview.py",
    "meridian/grade_preview_comparison.py",
    "meridian/grade_report_preview.py",
)


def test_wheel_guard_requires_all_issue54_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in RUNTIME_MODULES:
        assert member in text


def test_sdist_guard_requires_issue54_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/grade-report-preview-explanations.md",
        *RUNTIME_MODULES,
        "scripts/smoke_test_grade_report_preview_wheel.py",
        "scripts/smoke_program_grade_report_preview.py",
        "scripts/smoke_program_grade_report_preview_reload.py",
        "tests/test_grade_preview_explanation.py",
        "tests/test_conventional_grade_explanation.py",
        "tests/test_standards_grade_explanation.py",
        "tests/test_hybrid_grade_explanation.py",
        "tests/test_current_grade_preview.py",
        "tests/test_grade_preview_comparison.py",
        "tests/test_grade_report_preview.py",
        "tests/test_issue54_documentation_acceptance.py",
        "tests/test_issue54_packaging_acceptance.py",
        "tests/test_issue54_installed_acceptance.py",
    ):
        assert member in text


def test_repository_validator_runs_installed_issue54_smoke() -> None:
    text = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert "scripts/smoke_test_grade_report_preview_wheel.py" in text
    assert "str(scoreform)" in text
    assert "str(quillan)" in text
    assert "str(concord)" in text


def test_documentation_checker_includes_issue54_architecture() -> None:
    text = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "docs/architecture/grade-report-preview-explanations.md" in text
