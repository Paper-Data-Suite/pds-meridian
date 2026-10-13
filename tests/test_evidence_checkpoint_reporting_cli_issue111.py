from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.evidence_checkpoint_reporting_cli as cli
from meridian.cli import main
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportRow,
    compose_teacher_report_preview,
)

NOW = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)


def _report(kind: str, title: str):
    return compose_teacher_report_preview(
        report_kind=kind,  # type: ignore[arg-type]
        title=title,
        class_id="english_11",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        source_references=(),
        generated_at=NOW,
        summary=("Synthetic Slice 10 CLI report.",),
        columns=(
            TeacherReportColumn("item", "Item"),
            TeacherReportColumn("value", "Value"),
        ),
        rows=(TeacherReportRow("row_001", ("Status", "Ready")),),
    )


def test_evidence_cli_is_registered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_current_evidence_coverage",
        lambda *args, **kwargs: _report(
            "evidence_coverage",
            "Evidence Coverage / Missing & Incomplete Evidence",
        ),
    )
    assert (
        main(
            (
                "reports",
                "evidence",
                "english_11",
                "2026-2027",
                "mp1",
                "1",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T03:00:00Z",
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "# Evidence Coverage / Missing & Incomplete Evidence" in output
    assert "Ready" in output


def test_checkpoint_snapshots_cli_is_registered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_snapshot_to_snapshot_grade_checkpoint_comparison",
        lambda *args, **kwargs: _report(
            "grade_checkpoint_comparison",
            "Grade Checkpoint Comparison",
        ),
    )
    assert (
        main(
            (
                "reports",
                "checkpoint",
                "snapshots",
                "english_11",
                "prior",
                "a" * 64,
                "current",
                "b" * 64,
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T03:00:00Z",
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "# Grade Checkpoint Comparison" in output
    assert "Ready" in output
