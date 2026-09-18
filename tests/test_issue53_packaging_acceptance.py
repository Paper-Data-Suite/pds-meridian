from __future__ import annotations

from pathlib import Path

RUNTIME_MODULES = (
    "meridian/teacher_grade_override.py",
    "meridian/teacher_grade_override_storage.py",
    "meridian/teacher_grade_override_workflow.py",
    "meridian/teacher_grade_override_lifecycle.py",
    "meridian/effective_grade.py",
)


def test_wheel_guard_requires_all_issue53_runtime_modules() -> None:
    text = Path("scripts/check_package.py").read_text(encoding="utf-8")
    for member in RUNTIME_MODULES:
        assert member in text


def test_sdist_guard_requires_issue53_acceptance_surface() -> None:
    text = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in (
        "docs/architecture/teacher-grade-overrides.md",
        *RUNTIME_MODULES,
        "scripts/smoke_test_teacher_grade_override_wheel.py",
        "scripts/smoke_program_teacher_grade_override.py",
        "scripts/smoke_program_teacher_grade_override_reload_active.py",
        "scripts/smoke_program_teacher_grade_override_reload_withdrawn.py",
        "tests/test_teacher_grade_override.py",
        "tests/test_teacher_grade_override_storage.py",
        "tests/test_teacher_grade_override_workflow.py",
        "tests/test_teacher_grade_override_lifecycle.py",
        "tests/test_effective_grade.py",
        "tests/test_teacher_grade_override_issue53_integration.py",
        "tests/test_issue53_documentation_acceptance.py",
        "tests/test_issue53_packaging_acceptance.py",
        "tests/test_issue53_installed_acceptance.py",
    ):
        assert member in text


def test_repository_validator_runs_installed_issue53_smoke() -> None:
    text = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    assert "scripts/smoke_test_teacher_grade_override_wheel.py" in text
    assert "str(scoreform)" in text
