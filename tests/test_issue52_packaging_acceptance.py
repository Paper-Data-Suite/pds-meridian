from __future__ import annotations

from pathlib import Path


def test_wheel_guard_requires_all_hybrid_grade_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in (
        "meridian/hybrid_grade.py",
        "meridian/hybrid_grade_assembly.py",
        "meridian/hybrid_grade_result.py",
        "meridian/hybrid_grade_storage.py",
    ):
        assert member in text


def test_sdist_guard_requires_issue52_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/hybrid-grade-calculation.md",
        "meridian/hybrid_grade.py",
        "meridian/hybrid_grade_assembly.py",
        "meridian/hybrid_grade_result.py",
        "meridian/hybrid_grade_storage.py",
        "scripts/smoke_test_hybrid_grade_wheel.py",
        "scripts/smoke_program_hybrid_grade.py",
        "scripts/smoke_program_hybrid_grade_reload.py",
        "tests/issue52_hybrid_test_support.py",
        "tests/test_hybrid_grade.py",
        "tests/test_hybrid_grade_assembly.py",
        "tests/test_hybrid_grade_result.py",
        "tests/test_hybrid_grade_storage.py",
        "tests/test_issue52_cross_producer_acceptance.py",
        "tests/test_issue52_documentation_acceptance.py",
        "tests/test_issue52_packaging_acceptance.py",
        "tests/test_issue52_installed_acceptance.py",
    ):
        assert member in text


def test_repository_validator_runs_installed_issue52_smoke() -> None:
    text = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert "scripts/smoke_test_hybrid_grade_wheel.py" in text
    assert "str(scoreform)" in text
    assert "str(quillan)" in text
