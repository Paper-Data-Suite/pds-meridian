from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.standards_reporting_cli as cli
from meridian.cli import main
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportRow,
    compose_teacher_report_preview,
)

NOW = datetime(2026, 10, 13, 0, 0, tzinfo=UTC)


def _report(kind: str, title: str):
    return compose_teacher_report_preview(
        report_kind=kind,  # type: ignore[arg-type]
        title=title,
        class_id="english_11",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=1,
        source_references=(),
        generated_at=NOW,
        summary=("Synthetic Slice 9 CLI report.",),
        columns=(
            TeacherReportColumn("item", "Item"),
            TeacherReportColumn("value", "Value"),
        ),
        rows=(TeacherReportRow("row_001", ("Status", "Ready")),),
    )


def test_standards_report_group_is_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("reports", "standards")) == 0
    output = capsys.readouterr().out
    assert "profile" in output
    assert "growth" in output
    assert "Missing judgments" in output
    assert "historical attempts" in output
    assert "averaged" in output


def test_profile_cli_renders_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_current_class_standards_profile",
        lambda *args, **kwargs: _report(
            "class_standards_profile",
            "Class Standards Profile",
        ),
    )
    assert (
        main(
            (
                "reports",
                "standards",
                "profile",
                "english_11",
                "2026-2027",
                "mp1",
                "1",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T00:00:00Z",
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "# Class Standards Profile" in output
    assert "Ready" in output


def test_growth_cli_renders_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_student_proficiency_growth",
        lambda *args, **kwargs: _report(
            "student_proficiency_growth",
            "Student Proficiency Growth / Trajectory",
        ),
    )
    assert (
        main(
            (
                "reports",
                "standards",
                "growth",
                "english_11",
                "student_001",
                "2026-2027",
                "mp1",
                "1",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-13T00:00:00Z",
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "# Student Proficiency Growth / Trajectory" in output
    assert "Ready" in output
