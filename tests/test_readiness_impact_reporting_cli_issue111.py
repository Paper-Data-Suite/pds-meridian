from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.readiness_impact_reporting_cli as cli
from meridian.cli import main
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportRow,
    compose_teacher_report_preview,
)

NOW = datetime(2026, 10, 13, 4, 30, tzinfo=UTC)


def _report(kind: str, title: str):
    return compose_teacher_report_preview(
        report_kind=kind,  # type: ignore[arg-type]
        title=title,
        class_id="english_12",
        target_period=AcademicPeriodRef("2026-2027", "q1"),
        calendar_revision=1,
        source_references=(),
        generated_at=NOW,
        summary=("Synthetic Slice 11 CLI report.",),
        columns=(
            TeacherReportColumn("item", "Item"),
            TeacherReportColumn("value", "Value"),
        ),
        rows=(TeacherReportRow("row_001", ("Status", "Ready")),),
    )


def _request():
    return SimpleNamespace(
        definition_reference=SimpleNamespace(class_id="english_12"),
    )


def test_readiness_cli_is_registered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "load_reporting_snapshot_build_request_file",
        lambda path: _request(),
    )
    monkeypatch.setattr(
        cli,
        "build_marking_period_readiness",
        lambda *args, **kwargs: _report(
            "marking_period_readiness",
            "Marking-Period Readiness",
        ),
    )

    assert (
        main(
            (
                "reports",
                "readiness",
                "request.json",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T04:30:00Z",
            )
        )
        == 0
    )
    assert "# Marking-Period Readiness" in capsys.readouterr().out


def test_impact_cli_is_registered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "load_reporting_snapshot_build_request_file",
        lambda path: _request(),
    )
    monkeypatch.setattr(
        cli,
        "build_assessment_impact",
        lambda *args, **kwargs: _report(
            "assessment_impact",
            "Grade Item / Assessment Impact",
        ),
    )

    assert (
        main(
            (
                "reports",
                "impact",
                "essay_1",
                "request.json",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T04:30:00Z",
            )
        )
        == 0
    )
    assert "# Grade Item / Assessment Impact" in capsys.readouterr().out
