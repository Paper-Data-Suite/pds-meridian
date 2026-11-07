"""#125-H1: exact final-gate wiring and evidence ledger, not release approval."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/development/issue125-acceptance-ledger.md"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_final_validator_requires_both_ruff_lint_and_format() -> None:
    code = read("scripts/validate_repository.py")
    assert '[python, "-m", "ruff", "check", "."]' in code
    assert '[python, "-m", "ruff", "format", "--check", "."]' in code
    assert code.index('"ruff", "check"') < code.index('"ruff", "format"')


def test_final_validator_keeps_all_other_release_gates() -> None:
    code = read("scripts/validate_repository.py")
    requirements = (
        '"pytest"',
        '"mypy"',
        '"scripts/check_documentation.py"',
        '"scripts/verify_core_wheel.py"',
        '"scripts/verify_scoreform_wheel.py"',
        '"scripts/verify_quillan_wheel.py"',
        '"scripts/verify_concord_wheel.py"',
        '"scripts/verify_dependency_direction.py"',
        '"scripts.installed_qualification_runner"',
        '"scripts/check_package.py"',
        '"scripts/check_sdist.py"',
        '"twine"',
        '"pip", "check"',
        "_require_clean_repository()",
    )
    for requirement in requirements:
        assert requirement in code, requirement


def test_ci_runs_validator_on_windows_and_ubuntu_python_matrix() -> None:
    workflow = read(".github/workflows/ci.yml")
    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert "python scripts/validate_repository.py" in workflow
    assert "run: >-" in workflow
    for version in ("0.6.6", "0.13.0", "0.10.6", "0.3.2"):
        assert version in workflow


def test_ledger_lists_all_18_criteria_and_keeps_a18_open() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    found = re.findall(r"^\| (A\d+) \|", ledger, flags=re.MULTILINE)
    assert found == [f"A{i}" for i in range(1, 19)]
    assert "**OPEN**" in ledger
    assert "final PR SHA" in ledger
    assert "not a release authorization" in ledger
    assert "29 students" in ledger and "406" in ledger
    assert "174" in ledger


def test_native_gate_uses_canonical_writes_and_no_replay() -> None:
    native = read("tests/test_issue125_sliceg2b_scale_restart.py")
    for item in (
        "test_native_29x6_full_correctness_plan_cancel_is_zero_write",
        "test_native_six_student_actions_canonical_and_repeat_inspection",
        "test_native_interruption_after_second_canonical_apply_does_not_replay",
        "reconcile_sealed_eligibility_batch",
        "execute_batch_with_sealed_progress",
        "TeacherActionReceiptStore",
    ):
        assert item in native
    older = read("tests/test_issue125_sliceg2a_canonical_batch_acceptance.py")
    assert (
        "test_installed_native_producer_real_batch_decisions_and_exact_reconciliation"
        in older
    )
    assert (
        "test_installed_native_scoreform_roster_drift_blocks_all_actions_before_write"
        in older
    )


def test_no_unqualified_suite_or_producer_dependency_in_meridian_contract() -> None:
    config = read("pyproject.toml")
    assert '"pds-core>=0.6.5,<0.7"' in config
    for dependency in (
        '"scoreform>=0.13.0"',
        '"quillan>=0.10.6"',
        '"pds-concord>=0.3.2"',
    ):
        assert dependency in config
    runtime = config.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "scoreform" not in runtime
    assert "quillan" not in runtime
    assert "concord" not in runtime
    assert "suite" not in runtime
