"""#117 Slice 7: authorized Report 9 planning from synthetic teacher screens."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from pds_core.rosters import create_roster
from test_issue117_benchmark_plan_authoring import _baseline

import meridian.menu_reports as report_menu
from meridian.benchmark_plan_storage import (
    list_benchmark_plan_revisions,
    load_latest_benchmark_plan_revision,
)
from meridian.menu_benchmark_planner import (
    BenchmarkPlannerMenuServices,
    run_benchmark_planner_menu,
)
from meridian.report_guided_selection import ReportOption, ReportPreparedSelection


class ScriptedInput:
    def __init__(self, *answers: str) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._answers)


def _prepared() -> ReportPreparedSelection:
    return ReportPreparedSelection(
        "benchmark_analysis_instructional_response",
        (
            ("class", ReportOption("class_1", "Synthetic Class")),
            ("period", ReportOption("mp1", "Marking period 1")),
            ("grade_item", ReportOption("assessment_1", "Reading benchmark")),
        ),
    )


def _services(root: Path) -> BenchmarkPlannerMenuServices:
    roster = create_roster(
        "class_1",
        (
            {
                "student_id": "student_1",
                "first_name": "Alex",
                "last_name": "One",
                "period": "1",
            },
            {
                "student_id": "student_2",
                "first_name": "Bo",
                "last_name": "Two",
                "period": "1",
            },
            {
                "student_id": "student_3",
                "first_name": "Cy",
                "last_name": "Three",
                "period": "1",
            },
        ),
    )
    return BenchmarkPlannerMenuServices(
        workspace_resolver=lambda: root,
        roster_loader=lambda _root, _class_id: roster,
    )


def _run(root: Path, *answers: str, revalidate=None) -> str:
    output = StringIO()
    check = revalidate or (lambda _prepared, _preview: None)
    run_benchmark_planner_menu(
        report=_baseline(),
        prepared=_prepared(),
        revalidate=check,
        input_fn=ScriptedInput(*answers),
        output=output,
        services=_services(root),
    )
    return output.getvalue()


def test_save_teacher_interpretation_from_normal_menu(tmp_path: Path) -> None:
    result = _run(
        tmp_path, "1", "teacher_1", "Most students need more evidence.",
        "n", "n", "n", "n", "SAVE PLAN", "b",
    )
    stored = load_latest_benchmark_plan_revision(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    )
    assert stored.revision.plan_revision == 1
    assert stored.revision.teacher_id == "teacher_1"
    assert stored.revision.currentness == "unverified"
    assert any(
        "Most students need more evidence." in (value or "")
        for row in stored.revision.report.rows for value in row.values
    )
    assert "revision 1 saved" in result
    assert "Nothing was sent" not in result  # truthful local-only report


def test_cancel_and_no_confirmation_cannot_persist(tmp_path: Path) -> None:
    result = _run(
        tmp_path, "1", "teacher_1", "Draft is provisional", "n", "n", "n",
        "n", "no", "b",
    )
    assert "Nothing was saved" in result
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == ()


def test_revisions_are_append_only_without_reentering_teacher_id(
    tmp_path: Path,
) -> None:
    _run(
        tmp_path, "1", "teacher_1", "First notes",
        "n", "n", "n", "n", "SAVE PLAN", "b",
    )
    result = _run(tmp_path, "1", "Revised notes", "n", "n", "n", "n", "SAVE PLAN", "b")
    revisions = list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    )
    assert revisions == (1, 2)
    assert "revision 2 saved" in result
    assert "re-enter" in result.casefold()


def test_history_is_hidden_without_current_authority(tmp_path: Path) -> None:
    _run(
        tmp_path, "1", "teacher_1", "Earlier notes",
        "n", "n", "n", "n", "SAVE PLAN", "b",
    )
    called = []

    def reject(_prepared, _preview):
        called.append(True)
        raise RuntimeError("revoked")
    result = _run(tmp_path, "2", "b", revalidate=reject)
    assert called
    assert "Earlier notes" not in result
    assert "unavailable" in result


def test_view_and_browse_authorized_revision_history(tmp_path: Path) -> None:
    _run(
        tmp_path, "1", "teacher_1", "Planning earlier",
        "n", "n", "n", "n", "SAVE PLAN", "b",
    )
    result = _run(tmp_path, "2", "3", "1", "b")
    assert "Planning earlier" in result
    assert "Historical saved revisions" in result
    assert "1" in result


def test_wizard_can_compose_a_group_and_reteaching_response(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "1", "teacher_1", "Students need discussion.",
        "n",  # no standard classification
        "y", "Practice group", "1,3", "Shared reasoning challenge", "n",
        "y", "1", "Reading evidence", "1,3", "Modeled annotations",
        "2026-10-19", "2026-10-23",
        "q2", "reading.analysis", "planned", "Modeling reflection", "n",
        "n", "SAVE PLAN", "b",
    )
    assert "revision 1 saved" in result
    saved = load_latest_benchmark_plan_revision(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    )
    report = saved.revision.report
    assert any(row.values[1] == "Optional group: Practice group" for row in report.rows)
    assert any("Modeled annotations" in (row.values[3] or "") for row in report.rows)


def test_missing_live_revalidation_fails_closed(tmp_path: Path) -> None:
    output = StringIO()
    run_benchmark_planner_menu(
        report=_baseline(), prepared=_prepared(), revalidate=None,
        input_fn=ScriptedInput("1"), output=output, services=_services(tmp_path),
    )
    assert "Live authorization checks" in output.getvalue()
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == ()


def test_report_preview_has_p_action_only_for_benchmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = []
    monkeypatch.setattr(
        report_menu,
        "run_benchmark_planner_menu",
        lambda **kwargs: called.append(kwargs),
    )
    result = report_menu._show_preview(
        _baseline(), prepared=_prepared(),
        revalidate=lambda _prepared, _preview: None,
        input_fn=ScriptedInput("p", "b"),
        output=StringIO(), clear_fn=lambda: None,
    )
    assert result is False
    assert len(called) == 1
    assert called[0]["report"] == _baseline()


def test_bad_reassessment_date_prevents_save(tmp_path: Path) -> None:
    result = _run(
        tmp_path, "1", "teacher_1", "", "n", "n", "n", "y",
        "Exit ticket", "2026-99-10", "b",
    )
    assert "Plan could not be saved" in result
    assert list_benchmark_plan_revisions(
        tmp_path, "class_1", "benchmark_mp1_assessment_1"
    ) == ()
