"""Scripted nontechnical menu acceptance for all eight Issue #111 reports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, cast

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.menu_reports import run_reports_menu
from meridian.report_guided_selection import (
    REPORT_GUIDES,
    ReportOption,
    ReportPreparedSelection,
    ReportScope,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportPreview,
    TeacherReportRow,
    compose_teacher_report_preview,
)
from meridian.teacher_report_render import render_teacher_report


class ScriptedInput:
    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


class Catalog:
    def options(
        self,
        *,
        report_kind: str,
        scope: ReportScope,
        selected: Mapping[ReportScope, str],
    ) -> tuple[ReportOption, ...]:
        _ = report_kind, selected
        return {
            "class": (ReportOption("english12_p4", "English 12 - Period 4"),),
            "period": (ReportOption("mp1", "Marking Period 1 - 2026-2027"),),
            "student": (ReportOption("student_1", "Alex Rivera"),),
            "grade_item": (ReportOption("essay_1", "Comparative Essay"),),
            "checkpoint": (ReportOption("checkpoint_1", "October checkpoint"),),
            "mapping": (
                ReportOption(
                    "C:/teacher/mapping.json",
                    "School gradebook scale",
                    "District gradebook - revision 2",
                ),
            ),
        }[scope]


class Executor:
    def __init__(self) -> None:
        self.built: list[ReportPreparedSelection] = []
        self.revalidated: list[str] = []

    def build(self, prepared: ReportPreparedSelection) -> TeacherReportPreview:
        self.built.append(prepared)
        return compose_teacher_report_preview(
            report_kind=cast(object, prepared.report_kind),  # checked by model
            title="Teacher-friendly report",
            class_id="english12_p4",
            target_period=AcademicPeriodRef("2026-2027", "mp1"),
            calendar_revision=2,
            source_references=(),
            generated_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
            summary=("One actionable summary.",),
            columns=(TeacherReportColumn("student", "Student"),),
            rows=(TeacherReportRow("student_1", ("Alex Rivera",)),),
        )

    def revalidate(
        self,
        prepared: ReportPreparedSelection,
        preview: TeacherReportPreview | None = None,
    ) -> None:
        assert preview is not None
        self.revalidated.append(prepared.report_kind)


@pytest.mark.parametrize("report_number", range(1, 9))
def test_teacher_can_select_preview_understand_and_save_each_report(
    tmp_path: Path,
    report_number: int,
) -> None:
    guide = REPORT_GUIDES[report_number - 1]
    destination = tmp_path / f"report-{report_number}.md"
    responses = [str(report_number), "1"]
    responses.extend("1" for _ in guide.scopes)
    responses.extend(("1", "2", "markdown", str(destination), "", "b", "b", "b"))
    executor = Executor()
    output: list[str] = []

    class Writer:
        def write(self, value: str) -> int:
            output.append(value)
            return len(value)

        def flush(self) -> None:
            return None

    run_reports_menu(
        input_fn=ScriptedInput(responses),
        output=cast(object, Writer()),
        clear_fn=lambda: None,
        catalog=Catalog(),
        executor=cast(object, executor),
    )

    assert [item.report_kind for item in executor.built] == [guide.report_kind]
    assert executor.revalidated == [guide.report_kind]
    preview = executor.build(executor.built[0])
    assert destination.read_bytes() == render_teacher_report(preview, "markdown")
    rendered = "".join(output)
    assert "READ-ONLY preview" in rendered
    assert "Nothing was sent to an external system" in rendered
    assert "Alex Rivera" in rendered


def test_second_save_never_replaces_different_existing_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "existing.md"
    destination.write_bytes(b"teacher-owned existing file\n")
    guide = REPORT_GUIDES[2]
    responses = ["3", "1"]
    responses.extend("1" for _ in guide.scopes)
    responses.extend(("1", "2", "markdown", str(destination), "", "b", "b", "b"))
    executor = Executor()

    from io import StringIO

    output = StringIO()
    run_reports_menu(
        input_fn=ScriptedInput(responses),
        output=output,
        clear_fn=lambda: None,
        catalog=Catalog(),
        executor=cast(object, executor),
    )

    assert destination.read_bytes() == b"teacher-owned existing file\n"
    assert "was not saved" in output.getvalue()
