from __future__ import annotations

import json

import pytest

from meridian.cli import main
from meridian.teacher_report import TEACHER_REPORT_KINDS


def test_reports_group_without_subcommand_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports",)) == 0
    output = capsys.readouterr().out
    assert "usage: meridian reports" in output
    assert "kinds" in output
    assert "do not write to an SIS/LMS" in output


def test_reports_kinds_json_is_deterministic_and_nonmutating(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports", "kinds", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["surface"] == "teacher_reports"
    assert payload["academic_mutation"] is False
    assert payload["external_system_write"] is False
    assert [item["report_kind"] for item in payload["report_kinds"]] == list(
        TEACHER_REPORT_KINDS
    )
    statuses = {
        item["report_kind"]: item["generator_status"]
        for item in payload["report_kinds"]
    }
    assert statuses["sis_gradebook_reconciliation"] == "available"
    assert statuses["student_current_grade_justification"] == "available"
    assert statuses["class_standards_profile"] == "available"
    assert statuses["student_proficiency_growth"] == "available"
    assert statuses["evidence_coverage"] == "available"
    assert statuses["grade_checkpoint_comparison"] == "available"
    assert statuses["marking_period_readiness"] == "available"
    assert statuses["assessment_impact"] == "available"
    assert statuses["benchmark_analysis_instructional_response"] == "available"


def test_reports_kinds_text_names_all_nine_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports", "kinds")) == 0
    output = capsys.readouterr().out

    assert "1. SIS Gradebook Reconciliation" in output
    assert "8. Grade Item / Assessment Impact" in output
    assert "9. Benchmark Analysis & Instructional Response Planner" in output
    assert "All nine report-specific generators are available." in output


def test_benchmark_help_supports_file_and_live_workspace_modes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("reports", "benchmark", "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "--input" in output
    assert "--workspace" in output
    assert "--grade-item-id" in output
    assert "--load-plan-id" in output
    assert "--save-plan-id" in output
    assert "--confirm-save" in output
