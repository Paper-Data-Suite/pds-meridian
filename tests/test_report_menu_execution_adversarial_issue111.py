"""Cross-report controller currentness and privacy acceptance for Issue #111."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import meridian.report_menu_execution as execution
from meridian.report_guided_selection import ReportOption, ReportPreparedSelection
from meridian.report_menu_execution import (
    LiveReportMenuExecutor,
    ReportMenuExecutionDependencies,
    ReportMenuSelectionChangedError,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportRow,
    compose_teacher_report_preview,
)

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


def _preview(calendar_revision: int = 2):
    from pds_core.academic_periods import AcademicPeriodRef

    return compose_teacher_report_preview(
        report_kind="class_standards_profile",
        title="Class Standards Profile",
        class_id="english12_p4",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=calendar_revision,
        source_references=(),
        generated_at=NOW,
        columns=(TeacherReportColumn("state", "State"),),
        rows=(TeacherReportRow("student_1", ("Meeting",)),),
    )


def _selection() -> ReportPreparedSelection:
    return ReportPreparedSelection(
        "class_standards_profile",
        (
            ("class", ReportOption("english12_p4", "English 12 - Period 4")),
            ("period", ReportOption("mp1", "Marking Period 1")),
        ),
    )


def _install_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    periods: list[object],
) -> None:
    metadata_path = tmp_path / "class.json"
    metadata_path.write_text("{}\n", encoding="utf-8")
    roster_path = tmp_path / "roster.csv"
    roster_path.write_text("student_id\nstudent_1\n", encoding="utf-8")
    folder = SimpleNamespace(
        class_id="english12_p4",
        metadata=SimpleNamespace(school_year="2026-2027"),
        metadata_path=metadata_path,
        roster_path=roster_path,
    )
    monkeypatch.setattr(
        execution,
        "list_class_folders",
        lambda *args, **kwargs: (folder,),
    )
    monkeypatch.setattr(
        execution,
        "query_academic_period_catalog",
        lambda *args, **kwargs: (periods[0],),
    )


def _period(revision: int) -> object:
    return SimpleNamespace(
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=revision,
        lifecycle="active",
    )


def test_period_move_during_engine_execution_fails_without_mixed_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    periods = [_period(2)]
    _install_context(monkeypatch, tmp_path, periods)

    def moving_builder(*args: object, **kwargs: object):
        periods[0] = _period(3)
        return _preview()

    monkeypatch.setattr(
        execution,
        "build_current_class_standards_profile",
        moving_builder,
    )
    executor = LiveReportMenuExecutor(
        ReportMenuExecutionDependencies(
            workspace_resolver=lambda: tmp_path,
            clock=lambda: NOW,
        )
    )

    with pytest.raises(ReportMenuSelectionChangedError) as captured:
        executor.build(_selection())

    message = str(captured.value)
    assert "changed during report generation" in message
    assert str(tmp_path) not in message


def test_exact_same_frozen_inputs_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    periods = [_period(2)]
    _install_context(monkeypatch, tmp_path, periods)
    monkeypatch.setattr(
        execution,
        "build_current_class_standards_profile",
        lambda *args, **kwargs: _preview(),
    )
    executor = LiveReportMenuExecutor(
        ReportMenuExecutionDependencies(
            workspace_resolver=lambda: tmp_path,
            clock=lambda: NOW,
        )
    )

    first = executor.build(_selection())
    second = executor.build(_selection())

    assert first == second
    assert first.preview_sha256 == second.preview_sha256
    executor.revalidate(_selection(), first)
