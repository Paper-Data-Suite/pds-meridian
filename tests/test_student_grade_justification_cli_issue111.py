from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.student_grade_justification_cli as cli
from meridian.cli import main
from meridian.student_grade_justification import (
    StudentGradeJustificationEvidenceRequiredError,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportRow,
    compose_teacher_report_preview,
)

NOW = datetime(2026, 10, 12, 23, 10, tzinfo=UTC)


def _report():
    return compose_teacher_report_preview(
        report_kind="student_current_grade_justification",
        title="Student Grade Justification — student_001",
        class_id="class_2026",
        target_period=AcademicPeriodRef("2026-2027", "q1"),
        calendar_revision=1,
        source_references=(),
        generated_at=NOW,
        summary=("Synthetic CLI report.",),
        columns=(
            TeacherReportColumn("section", "Section"),
            TeacherReportColumn("item", "Item"),
            TeacherReportColumn("value", "Value"),
        ),
        rows=(TeacherReportRow("row_001", ("Grade", "Effective Grade", "87")),),
    )


def test_justify_group_is_registered(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(("reports", "justify")) == 0
    output = capsys.readouterr().out
    assert "current" in output
    assert "snapshot" in output
    assert "protected" in output
    assert "not reproduced" in output


def test_snapshot_cli_renders_exact_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_snapshot_student_grade_justification",
        lambda *args, **kwargs: _report(),
    )
    assert (
        main(
            (
                "reports",
                "justify",
                "snapshot",
                "class_2026",
                "snapshot_001",
                "a" * 64,
                "student_001",
                "--format",
                "markdown",
                "--generated-at",
                "2026-10-12T23:10:00Z",
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "# Student Grade Justification" in output
    assert "Effective Grade" in output


def test_snapshot_cli_safely_writes_exact_local_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_snapshot_student_grade_justification",
        lambda *args, **kwargs: _report(),
    )
    output_path = tmp_path / "justification.json"
    arguments = (
        "reports",
        "justify",
        "snapshot",
        "class_2026",
        "snapshot_001",
        "a" * 64,
        "student_001",
        "--format",
        "json",
        "--generated-at",
        "2026-10-12T23:10:00Z",
        "--output",
        str(output_path),
    )

    assert main(arguments) == 0
    assert main(arguments) == 0
    assert output_path.read_bytes().endswith(b"\n")
    assert "created:" in capsys.readouterr().out


def test_current_nonstandards_error_is_explicit_and_privacy_bounded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args, **kwargs):
        raise StudentGradeJustificationEvidenceRequiredError(
            "explicit authorized work-evidence tuple required"
        )

    monkeypatch.setattr(cli, "build_current_student_grade_justification", fail)
    assert (
        main(
            (
                "reports",
                "justify",
                "current",
                "class_2026",
                "student_001",
                "2026-2027",
                "q1",
                "1",
                "--family",
                "conventional",
            )
        )
        == 1
    )
    error = capsys.readouterr().err
    assert "student_grade_justification.evidence_required" in error
    assert "authorized work-evidence" in error
