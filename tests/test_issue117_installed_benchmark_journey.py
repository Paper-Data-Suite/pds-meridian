"""Issue #117: installed ScoreForm and Quillan Report 9 acceptance wiring.

These fast tests inspect the production installed-smoke boundary. The normal
six-matrix installed qualifier separately executes both real producer wheels.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.smoke_program_guided_evidence_issue110 import AllowInstalledAcceptance


@pytest.mark.parametrize("purpose", ("review_evidence", "teacher_reporting"))
def test_both_teacher_read_purposes_are_explicitly_accepted(purpose: str) -> None:
    authorizer = AllowInstalledAcceptance()
    request = SimpleNamespace(purpose_id=purpose)
    decision = authorizer.authorize(request)  # type: ignore[arg-type]
    assert decision.allowed is True


def test_unrelated_academic_purpose_is_rejected() -> None:
    authorizer = AllowInstalledAcceptance()
    request = SimpleNamespace(purpose_id="publish_academic_decision")
    with pytest.raises(AssertionError, match="Unexpected"):
        authorizer.authorize(request)  # type: ignore[arg-type]


def test_installed_smoke_runs_benchmark_after_guided_evidence() -> None:
    source = Path("scripts/smoke_program_guided_evidence_issue110.py").read_text(
        encoding="utf-8"
    )
    journey = source[source.index("def main(") :]
    assert journey.index("_run_teacher_journey(") < journey.index(
        "setup_installed_benchmark_records("
    ) < journey.index("run_installed_benchmark_teacher_journey(")
    assert 'version("pds-core") != "0.6.6"' in source


def test_benchmark_uses_authoritative_stores_and_normal_menu() -> None:
    source = Path("scripts/installed_benchmark_helpers.py").read_text(
        encoding="utf-8"
    )
    required = (
        "write_class_metadata(",
        "write_academic_period_calendar(",
        "write_grade_item_revision(",
        "select_grade_item_revision(",
        "write_grade_item_membership_revision(",
        "select_grade_item_membership_revision(",
        "write_proficiency_scale_revision(",
        "select_proficiency_scale_revision(",
        "rebuild_academic_catalog(",
        "run_reports_menu(",
        "LiveReportMenuExecutor(",
        '"9", "1"',
        '"SAVE PLAN"',
        "load_latest_benchmark_plan_revision(",
        "load_benchmark_plan_notes(",
        "render_teacher_report(",
    )
    for snippet in required:
        assert snippet in source
    assert "ReportingSnapshot" in source


def test_six_matrices_remain_without_new_installed_environment() -> None:
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )
    assert runner.count("run_issue110_guided_evidence_prepared_smoke(") == 2
    for name in ("SCOREFORM", "QUILLAN", "CONCORD", "ALL_ADAPTERS"):
        assert f"DependencyMatrixId.{name}" in runner
    script = Path("scripts/smoke_program_guided_evidence_issue110.py").read_text(
        encoding="utf-8"
    )
    assert 'choices=("scoreform", "quillan")' in script


def test_exact_installed_wheel_guard_remains_protected() -> None:
    verify = Path("scripts/verify_core_wheel.py").read_text(
        encoding="utf-8"
    )
    assert 'EXPECTED_CORE_VERSION = "0.6.6"' in verify
    assert "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301" in verify
