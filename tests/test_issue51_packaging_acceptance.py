from __future__ import annotations

from pathlib import Path


def test_wheel_guard_requires_all_standards_grade_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in (
        "meridian/standards_grade.py",
        "meridian/standards_grade_assembly.py",
        "meridian/standards_grade_result.py",
        "meridian/standards_grade_storage.py",
    ):
        assert member in text


def test_sdist_guard_requires_issue51_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/standards-grade-calculation.md",
        "meridian/standards_grade.py",
        "meridian/standards_grade_assembly.py",
        "meridian/standards_grade_result.py",
        "meridian/standards_grade_storage.py",
        "scripts/smoke_test_standards_grade_wheel.py",
        "scripts/smoke_program_standards_grade.py",
        "scripts/smoke_program_standards_grade_reload.py",
        "tests/test_standards_grade.py",
        "tests/test_standards_grade_assembly.py",
        "tests/test_issue51_academic_period_proficiency_freshness.py",
        "tests/test_standards_grade_result.py",
        "tests/test_standards_grade_storage.py",
        "tests/test_issue51_cross_producer_acceptance.py",
        "tests/test_issue51_documentation_acceptance.py",
        "tests/test_issue51_packaging_acceptance.py",
        "tests/test_issue51_installed_acceptance.py",
    ):
        assert member in text


def test_repository_validator_runs_installed_issue51_smoke() -> None:
    text = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert "scripts/smoke_test_standards_grade_wheel.py" in text
    assert "str(scoreform)" in text
    assert "str(quillan)" in text
