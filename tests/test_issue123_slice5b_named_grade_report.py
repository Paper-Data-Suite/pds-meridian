"""#123 Slice 5B: teacher-named bounded Grade report, with no academic writes."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_grade_report as named
from meridian.menu_grades import GradeReportPresentation, GradeReportRowPresentation
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
YEAR = "2026-2027"
PERIOD = "mp1"


def inputs(*responses: str):
    values = iter(responses)
    return lambda _prompt: next(values)


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, count: int = 3):
    navigation = MagicMock()
    school = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=7,
        label="Marking Period 1",
    )
    navigation.current_class.return_value = school
    navigation.current_period.return_value = period
    students = tuple(
        TeacherChoice(
            identity=(f"opaque-{number:02d}",),
            label=f"Student {number:02d}",
            detail=f"Class period 2 · roster position {number}",
        )
        for number in range(1, count + 1)
    )
    period_choice = TeacherChoice(identity=(PERIOD,), label=period.label)
    catalog = MagicMock()
    period_catalog = MagicMock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_k: (period, period_choice)
    )
    monkeypatch.setattr(named, "_family", lambda **_k: "standards_based")

    def check_choice(provider, *, scope, selected, choice):
        if choice not in named.load_teacher_choices(
            provider, scope=scope, selected=selected
        ):
            raise named._ScopeChanged("Chosen record changed.")

    monkeypatch.setattr(named, "_current_choice", check_choice)
    monkeypatch.setattr(
        named,
        "load_teacher_choices",
        lambda _cat, *, scope, selected: (
            students if scope == "student" else (period_choice,)
        ),
    )
    rows = tuple(
        GradeReportRowPresentation(
            student_id=student.identity[0],
            status="available",
            unavailable_reason=None,
            base_status="calculated",
            freshness_status="current",
            effective_grade="87.5",
            effective_source="policy",
        )
        for student in students
    )
    report = GradeReportPresentation(
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=7,
        family="standards_based",
        requested_count=count,
        available_count=count,
        unavailable_count=0,
        stale_count=0,
        override_count=0,
        rows=rows,
    )
    loader = MagicMock(return_value=report)
    return navigation, catalog, period_catalog, students, report, loader


def run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    count: int = 3,
    answers: tuple[str, ...] = ("1", ""),
):
    nav, grades, periods, students, report, loader = setup(
        tmp_path, monkeypatch, count=count
    )
    output = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs(*answers),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    return output.getvalue(), loader, students, report, nav


def test_entire_roster_has_names_no_ids_and_one_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen, loader, students, _, _ = run(tmp_path, monkeypatch)
    for student in students:
        assert student.label in screen
        assert student.identity[0] not in screen
    assert "Marking Period 1" in screen
    assert "No Grade, override, or snapshot was saved" in screen
    assert "sha256" not in screen
    assert loader.call_count == 1
    args = loader.call_args.args
    assert args[0] == tmp_path
    assert args[1] == CLASS
    assert args[2] == tuple(person.identity[0] for person in students)
    assert args[3].period_id == PERIOD
    assert args[4] == 7
    assert args[5] == "standards_based"


def test_29_student_roster_paginated_without_more_evidence_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    screen, loader, _, _, _ = run(
        tmp_path, monkeypatch, count=29, answers=("1", "n", "n", "p", "")
    )
    assert "Page 1 of 3" in screen
    assert "Page 2 of 3" in screen
    assert "Page 3 of 3" in screen
    assert "Student 29" in screen
    assert loader.call_count == 1


def test_no_numeric_grade_and_real_zero_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, _, report, loader = setup(tmp_path, monkeypatch)
    updated = replace(
        report,
        rows=(
            replace(report.rows[0], effective_grade=None),
            replace(report.rows[1], effective_grade="0.00"),
            replace(
                report.rows[2],
                status="unavailable",
                unavailable_reason="no_selected_grade",
            ),
        ),
        available_count=2,
        unavailable_count=1,
    )
    loader.return_value = updated
    out = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("1", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "No numeric Grade (not zero)" in out.getvalue()
    assert "Grade 0.00" in out.getvalue()
    assert "No selected Grade (not zero)" in out.getvalue()


def test_choose_subset_using_names_not_comma_separated_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, students, report, loader = setup(tmp_path, monkeypatch)
    iterator = iter((students[1], students[0]))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: next(iterator))
    loader.return_value = replace(
        report,
        rows=(report.rows[1], report.rows[0]),
        requested_count=2,
        available_count=2,
    )
    out = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("2", "a", "r", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert loader.call_args.args[2] == (
        students[1].identity[0],
        students[0].identity[0],
    )
    assert "Student 02" in out.getvalue()
    assert "Student 01" in out.getvalue()
    assert students[0].identity[0] not in out.getvalue()


def test_duplicate_subset_choice_is_not_added_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, students, report, loader = setup(tmp_path, monkeypatch)
    iterator = iter((students[0], students[0], students[1]))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: next(iterator))
    loader.return_value = replace(
        report, rows=report.rows[:2], requested_count=2, available_count=2
    )
    output = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("2", "a", "a", "r", ""),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "already selected" in output.getvalue()
    assert loader.call_args.args[2] == (
        students[0].identity[0],
        students[1].identity[0],
    )


def test_more_than_50_requires_named_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, grades, _, _, _, _ = setup(tmp_path, monkeypatch, count=51)
    output = StringIO()
    choice = named._choose_students(
        catalog=grades,
        class_id=CLASS,
        input_fn=inputs("1", "", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    assert choice is None
    assert "Select a smaller student subset" in output.getvalue()


def test_cancel_before_report_never_reads_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, loader, _, _, _ = run(tmp_path, monkeypatch, answers=("b",))
    loader.assert_not_called()


def test_family_cancel_never_reads_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, _, _, loader = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_family", lambda **_k: None)
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("1"),
        output=StringIO(),
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    loader.assert_not_called()


def test_report_wrong_class_or_added_student_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, _, report, loader = setup(tmp_path, monkeypatch)
    loader.return_value = replace(report, class_id="wrong-class")
    output = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("1", ""),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "changed during review" in output.getvalue()
    assert "Read-Only Grade Report" not in output.getvalue()


def test_roster_changed_after_report_is_not_displayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, students, _, loader = setup(tmp_path, monkeypatch)
    visits = 0

    def moving_roster(_cat, *, scope, selected):
        nonlocal visits
        if scope == "period":
            return (TeacherChoice(identity=(PERIOD,), label="Marking Period 1"),)
        visits += 1
        return students if visits < 3 else ()

    monkeypatch.setattr(named, "load_teacher_choices", moving_roster)
    output = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("1", ""),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert loader.call_count == 1
    assert "changed during review" in output.getvalue()
    assert "Read-Only Grade Report" not in output.getvalue()


def test_loader_error_is_redacted_and_not_reported_as_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, _, _, loader = setup(tmp_path, monkeypatch)
    loader.side_effect = RuntimeError("SECRET evidence path /student/private")
    output = StringIO()
    named.run_named_grade_report_review(
        navigation=nav,
        report_loader=loader,
        input_fn=inputs("1", ""),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "SECRET" not in output.getvalue()
    assert "could not be verified" in output.getvalue()
    assert "Grade 0" not in output.getvalue()


def test_main_and_quit_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for raised in (ReturnToMainMenu, QuitPDS):
        nav, grades, periods, _, _, loader = setup(tmp_path, monkeypatch)
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=raised))
        with pytest.raises(raised):
            named.run_named_grade_report_review(
                navigation=nav,
                report_loader=loader,
                input_fn=inputs(),
                output=StringIO(),
                clear_fn=lambda: None,
                class_catalog=grades,
                period_catalog=periods,
            )


def test_controller_routes_are_explicitly_advanced_for_raw_ids() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_grades.py"
    ).read_text(encoding="utf-8")
    assert "run_named_grade_report_review(" in source
    assert "Advanced: Preview a bounded Grade report" in source
    assert "Advanced: Preview one current Grade (exact records)" in source
    assert "Review a Grade report for named roster students" in source
    assert "_show_report(" in source
    assert "_show_current(" in source
