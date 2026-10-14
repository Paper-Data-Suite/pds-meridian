from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.report_export_roster as roster_module
from meridian.report_export_commit import ReportExportArtifactConflictError
from meridian.report_export_roster import (
    build_report_display_name_observation,
    export_roster_observation_sha256,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
    teacher_report_preview_from_json_bytes,
    teacher_report_preview_to_json_bytes,
)
from meridian.teacher_report_output import write_teacher_report_file
from meridian.teacher_report_render import render_teacher_report

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def _preview():
    return compose_teacher_report_preview(
        report_kind="class_standards_profile",
        title="Synthetic standards profile",
        class_id="class_2026",
        target_period=PERIOD,
        calendar_revision=3,
        source_references=(
            TeacherReportSourceReference(
                "selected_proficiency", "selection_002", "b" * 64
            ),
            TeacherReportSourceReference("grade_policy", "policy_001", "a" * 64),
        ),
        generated_at=NOW,
        summary=("Synthetic Slice 6 acceptance preview.",),
        columns=(
            TeacherReportColumn("student_id", "Student ID"),
            TeacherReportColumn("standard", "Standard"),
            TeacherReportColumn("proficiency", "Proficiency"),
        ),
        rows=(
            TeacherReportRow("row_002", ("student_002", "RL.CR.11-12.1", None)),
            TeacherReportRow("row_001", ("student_001", "RL.CR.11-12.1", "Meeting")),
        ),
        diagnostics=(
            TeacherReportDiagnostic(
                "report.synthetic",
                "info",
                "Synthetic foundation acceptance only.",
            ),
        ),
    )


def test_common_preview_is_canonical_digest_bound_and_round_trips() -> None:
    preview = _preview()
    assert [item.source_kind for item in preview.source_references] == [
        "grade_policy",
        "selected_proficiency",
    ]
    assert [row.row_id for row in preview.rows] == ["row_001", "row_002"]

    encoded = teacher_report_preview_to_json_bytes(preview)
    loaded = teacher_report_preview_from_json_bytes(encoded)

    assert loaded == preview
    assert teacher_report_preview_to_json_bytes(loaded) == encoded
    assert len(preview.preview_sha256) == 64


def test_renderers_are_deterministic_and_preserve_missing_as_blank() -> None:
    preview = _preview()

    assert render_teacher_report(preview, "csv") == (
        b"Student ID,Standard,Proficiency\n"
        b"student_001,RL.CR.11-12.1,Meeting\n"
        b"student_002,RL.CR.11-12.1,\n"
    )
    assert b"student_001\tRL.CR.11-12.1\tMeeting\n" in render_teacher_report(
        preview, "tsv"
    )
    markdown = render_teacher_report(preview, "markdown")
    assert b"# Synthetic standards profile" in markdown
    assert b"SIS, LMS, or district gradebook" in markdown
    assert render_teacher_report(
        preview, "json"
    ) == teacher_report_preview_to_json_bytes(preview)


def test_safe_local_report_write_reuses_nonoverwrite_verification(
    tmp_path: Path,
) -> None:
    preview = _preview()
    path = tmp_path / "report.csv"

    first = write_teacher_report_file(path, preview, "csv")
    second = write_teacher_report_file(path, preview, "csv")

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert path.read_bytes() == render_teacher_report(preview, "csv")

    path.write_bytes(b"different\n")
    with pytest.raises(ReportExportArtifactConflictError):
        write_teacher_report_file(path, preview, "csv")


def test_display_name_observation_reuses_bounded_roster_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roster = object()
    student = object()
    monkeypatch.setattr(
        roster_module,
        "load_class_roster",
        lambda workspace, class_id: roster,
    )
    monkeypatch.setattr(
        roster_module,
        "student_lookup",
        lambda value: {"student_001": student},
    )
    monkeypatch.setattr(
        roster_module,
        "student_display_name",
        lambda value: "Jane Doe",
    )

    observation = build_report_display_name_observation(
        Path("."),
        "class_2026",
        ("student_001",),
    )

    assert observation.source_fields == ("roster.display_name",)
    assert observation.students[0].student_id == "student_001"
    assert observation.students[0].values[0].value == "Jane Doe"
    assert len(export_roster_observation_sha256(observation)) == 64
