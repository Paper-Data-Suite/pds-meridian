from __future__ import annotations

from pathlib import Path


def test_wheel_guard_requires_all_conventional_grade_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in (
        "meridian/conventional_grade.py",
        "meridian/conventional_grade_assembly.py",
        "meridian/conventional_grade_storage.py",
    ):
        assert member in text


def test_sdist_guard_requires_issue50_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/conventional-grade-calculation.md",
        "meridian/conventional_grade.py",
        "meridian/conventional_grade_assembly.py",
        "meridian/conventional_grade_storage.py",
        "scripts/smoke_test_conventional_grade_wheel.py",
        "scripts/smoke_program_conventional_grade.py",
        "scripts/smoke_program_conventional_grade_reload.py",
        "tests/test_issue50_cross_producer_acceptance.py",
        "tests/test_issue50_packaging_acceptance.py",
        "tests/test_issue50_documentation_acceptance.py",
    ):
        assert member in text


def test_repository_validator_runs_installed_issue50_smoke() -> None:
    text = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert "scripts/smoke_test_conventional_grade_wheel.py" in text
    assert "str(scoreform)" in text
