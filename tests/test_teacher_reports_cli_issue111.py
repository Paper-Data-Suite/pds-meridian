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


def test_reports_kinds_text_names_all_eight_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports", "kinds")) == 0
    output = capsys.readouterr().out

    assert "1. SIS Gradebook Reconciliation" in output
    assert "8. Grade Item / Assessment Impact" in output
    assert "subsequent Issue #111 slices" in output
