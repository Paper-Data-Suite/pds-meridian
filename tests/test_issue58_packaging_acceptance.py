from __future__ import annotations

from pathlib import Path


def test_issue58_runtime_and_qualification_assets_are_distribution_guarded() -> None:
    wheel_check = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_check = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    assert '"meridian/grade_report_attention.py"' in wheel_check
    for member in (
        "docs/architecture/grade-report-attention-summaries.md",
        "scripts/smoke_program_grade_report_attention.py",
        "scripts/smoke_test_grade_report_attention_wheel.py",
        "tests/test_issue58_installed_acceptance.py",
        "tests/test_issue58_packaging_acceptance.py",
        "tests/test_issue58_documentation_acceptance.py",
    ):
        assert f'"{member}"' in sdist_check


def test_issue58_repository_validation_uses_central_prepared_runner() -> None:
    validator = Path("scripts/validate_repository.py").read_text(encoding="utf-8")
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert "scripts.installed_qualification_runner" in validator
    assert "grade-report-attention" in runner
