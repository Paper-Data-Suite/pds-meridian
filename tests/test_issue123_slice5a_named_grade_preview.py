"""#123 Slice 5A: bounded, teacher-named, read-only Grade preview."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_grades as named
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
YEAR = "2026-2027"
STUDENT = "opaque-student"
PERIOD = "mp1"


def inputs(*responses: str):
    iterator = iter(responses)
    return lambda _prompt: next(iterator)


def fixture(tmp_path: Path):
    navigation = MagicMock()
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=7,
        label="Marking Period 1",
    )
    navigation.current_class.return_value = verified
    navigation.current_period.return_value = None
    navigation.choose_period.return_value = period
    navigation.session = MagicMock()
    class_catalog = MagicMock()
    period_catalog = MagicMock()
    student = TeacherChoice(identity=(STUDENT,), label="Morgan Reed")
    period_choice = TeacherChoice(identity=(PERIOD,), label="Marking Period 1")
    choices = {"student": (student,), "period": (period_choice,)}
    preview = SimpleNamespace(
        class_id=CLASS,
        student_id=STUDENT,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=7,
        family="standards_based",
        policy_title="Standards Policy",
        base_status="unassessed",
        base_grade=None,
        effective_grade=None,
        effective_source="no_grade",
        freshness_status="current",
        override_applicability="not_applicable",
        freshness_reasons=(),
    )
    loader = MagicMock(return_value=preview)
    return (
        navigation,
        class_catalog,
        period_catalog,
        period,
        student,
        period_choice,
        choices,
        loader,
    )


def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, answers=("1", "")):
    nav, grades, periods, verified, _student, _period_choice, choices, loader = fixture(
        tmp_path
    )
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **kwargs: choices[kwargs["scope"]][0],
    )
    monkeypatch.setattr(
        named,
        "load_teacher_choices",
        lambda _catalog, *, scope, selected: choices[scope],
    )
    # After choosing a period, it is now remembered by the navigation context.
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", verified) or verified
    )
    output = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs(*answers),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    return output.getvalue(), loader, nav, choices, verified


def test_named_grade_review_has_no_ids_and_never_conflates_absence_with_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, loader, nav, _, _ = run(tmp_path, monkeypatch)
    assert "Morgan Reed" in output
    assert "Marking Period 1" in output
    assert "No numeric Grade (not zero)" in output
    assert STUDENT not in output
    assert "sha256" not in output.lower()
    assert "No Grade, override" in output
    assert loader.call_count == 1
    nav.session.select_student.assert_called_once_with(STUDENT)


def test_standards_based_uses_verified_period_and_student_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, loader, _, _, _ = run(tmp_path, monkeypatch)
    args = loader.call_args.args
    assert args[0] == tmp_path
    assert args[1] == CLASS
    assert args[2] == STUDENT
    assert args[3].school_year == YEAR
    assert args[3].period_id == PERIOD
    assert args[4] == 7
    assert args[5] == "standards_based"


def test_retained_period_is_not_reselected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, period, student, _choice, choices, loader = fixture(tmp_path)
    nav.current_period.return_value = period
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    selected = []
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **kwargs: selected.append(kwargs["scope"]) or student,
    )
    monkeypatch.setattr(
        named,
        "load_teacher_choices",
        lambda _catalog, *, scope, selected: choices[scope],
    )
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("1", ""),
        output=StringIO(),
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert selected == ["student"]
    nav.choose_period.assert_not_called()
    loader.assert_called_once()


def test_cancellation_before_grade_reader_does_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, _, _student, _choice, _choices, loader = fixture(tmp_path)
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kwargs: None)
    output = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs(),
        output=output,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    loader.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_back_from_family_does_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _output, loader, _, _, _ = run(tmp_path, monkeypatch, answers=("B",))
    loader.assert_not_called()


def test_wrong_class_grade_result_is_redacted_and_not_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rewrite a successful invocation's output behavior by wrapping the reader.
    nav, grades, periods, period, _student, _choice, choices, loader = fixture(tmp_path)
    loader.return_value.class_id = "wrong-class"
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **kw: choices[kw["scope"]][0]
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda _cat, *, scope, selected: choices[scope]
    )
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", period) or period
    )
    out = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("1", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "changed during review" in out.getvalue()
    nav.session.select_student.assert_not_called()


def test_preview_loader_opaque_errors_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, period, _student, _choice, choices, loader = fixture(tmp_path)
    loader.side_effect = RuntimeError("private /staff/students/opaque location")
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **kw: choices[kw["scope"]][0]
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda _cat, *, scope, selected: choices[scope]
    )
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", period) or period
    )
    out = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("1", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "private" not in out.getvalue()
    assert "not configured" in out.getvalue()
    nav.session.select_student.assert_not_called()


def test_main_quit_propagate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for exception in (ReturnToMainMenu, QuitPDS):
        nav, grades, periods, _period, _student, _choice, _choices, loader = fixture(
            tmp_path
        )
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=exception))
        with pytest.raises(exception):
            named.run_named_current_grade_review(
                navigation=nav,
                current_grade_loader=loader,
                input_fn=inputs(),
                output=StringIO(),
                clear_fn=lambda: None,
                class_catalog=grades,
                period_catalog=periods,
            )


def test_controller_preserves_exact_advanced_routes() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_grades.py"
    ).read_text(encoding="utf-8")
    assert "Advanced: Preview one current Grade (exact records)" in source
    assert "Advanced: Preview a bounded Grade report" in source
    assert "run_named_current_grade_review(" in source
    assert "_show_current(" in source
    assert "_show_report(" in source


def test_actual_zero_is_preserved_as_a_numeric_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, period, _student, _choice, choices, loader = fixture(tmp_path)
    loader.return_value.base_status = "assessed"
    loader.return_value.base_grade = "0.00"
    loader.return_value.effective_grade = "0.00"
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **kw: choices[kw["scope"]][0]
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda _cat, *, scope, selected: choices[scope]
    )
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", period) or period
    )
    out = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("1", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert "Base Grade: 0.00" in out.getvalue()
    assert "Effective Grade: 0.00" in out.getvalue()
    assert "not zero" not in out.getvalue()


def test_student_removed_after_preview_is_not_displayed_or_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, period, _student, _choice, choices, loader = fixture(tmp_path)
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **kw: choices[kw["scope"]][0]
    )
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", period) or period
    )
    reads = {"student": 0}

    def choices_now(_catalog, *, scope, selected):
        if scope == "student":
            reads["student"] += 1
            if reads["student"] == 2:
                return ()
        return choices[scope]

    monkeypatch.setattr(named, "load_teacher_choices", choices_now)
    out = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("1", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert loader.call_count == 1
    assert "changed during review" in out.getvalue()
    nav.session.select_student.assert_not_called()


def test_unavailable_conventional_evidence_produces_no_grade_and_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nav, grades, periods, period, _student, _choice, choices, loader = fixture(tmp_path)
    loader.side_effect = RuntimeError("unavailable authorized work evidence")
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **kw: choices[kw["scope"]][0]
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda _cat, *, scope, selected: choices[scope]
    )
    nav.choose_period.side_effect = lambda _id: (
        setattr(nav.current_period, "return_value", period) or period
    )
    out = StringIO()
    named.run_named_current_grade_review(
        navigation=nav,
        current_grade_loader=loader,
        input_fn=inputs("2", ""),
        output=out,
        clear_fn=lambda: None,
        class_catalog=grades,
        period_catalog=periods,
    )
    assert loader.call_args.args[-1] == "conventional"
    assert "not configured" in out.getvalue()
    assert "unavailable authorized" not in out.getvalue()
    nav.session.select_student.assert_not_called()
