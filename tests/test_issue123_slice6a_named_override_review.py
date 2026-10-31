"""#123 Slice 6A: read-only, named current override scope and exact selection."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_override_review as named
from meridian.menu_overrides import OverrideReviewPresentation, OverrideScope
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
STUDENT = "student-opaque"
YEAR = "2026-2027"
PERIOD = "mp1"


def scripted(*responses: str):
    iterator = iter(responses)
    return lambda _prompt: next(iterator)


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cls = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        label="Marking Period 1",
    )
    navigation = MagicMock()
    navigation.current_class.return_value = cls
    navigation.current_period.return_value = period
    navigation.session = MagicMock()
    period_choice = TeacherChoice(identity=(PERIOD,), label="Marking Period 1")
    student = TeacherChoice(identity=(STUDENT,), label="Morgan Reed")
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_kw: (period, period_choice)
    )
    monkeypatch.setattr(named, "_family", lambda **_kw: "standards_based")
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: student)
    monkeypatch.setattr(named, "_current_choice", lambda *_a, **_kw: None)
    expected_scope = OverrideScope(
        class_id=CLASS,
        student_id=STUDENT,
        period=__import__(
            "pds_core.academic_periods", fromlist=["AcademicPeriodRef"]
        ).AcademicPeriodRef(YEAR, PERIOD),
        calendar_revision=3,
        family="standards_based",
    )
    value = OverrideReviewPresentation(
        scope=expected_scope,
        selected=True,
        decision="override",
        override_revision=2,
        override_sha256="a" * 64,
        replacement_grade="0.00",
        actor_id="opaque-teacher",
        rationale="Approved exception",
        source_result_revision=3,
        source_result_sha256="b" * 64,
    )
    reader = MagicMock(return_value=value)
    return navigation, reader, expected_scope, value, student, period


def execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate=None,
    answers=("",),
):
    nav, reader, scope, value, student, period = setup(tmp_path, monkeypatch)
    if mutate is not None:
        mutate(nav, reader, scope, value, student, period)
    output = StringIO()
    named.run_named_current_override_review(
        navigation=nav,
        review_loader=reader,
        input_fn=scripted(*answers),
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return output.getvalue(), reader, nav, scope, value


def test_selected_override_uses_name_and_actual_zero(tmp_path, monkeypatch):
    out, reader, nav, scope, _ = execute(tmp_path, monkeypatch)
    assert "Morgan Reed" in out and "Marking Period 1" in out
    assert "Replacement Grade: 0.00" in out
    assert "decision: replacement Grade" in out
    assert STUDENT not in out and "opaque-teacher" not in out
    assert "Approved exception" not in out
    assert "sha256" not in out.lower()
    assert reader.call_count == 2
    assert reader.call_args.args == (tmp_path, scope)
    nav.session.select_student.assert_called_once_with(STUDENT)


def test_selected_withdrawal_is_not_an_active_replacement(tmp_path, monkeypatch):
    out, _, _, _, _ = execute(
        tmp_path,
        monkeypatch,
        mutate=lambda _nav, reader, _s, value, *_: setattr(
            reader,
            "return_value",
            replace(value, decision="withdraw", replacement_grade=None),
        ),
    )
    assert "decision: withdrawn" in out
    assert "No replacement Grade is applied" in out
    assert "Replacement Grade: " not in out


def test_no_selected_override_is_not_zero(tmp_path, monkeypatch):
    out, _, nav, _, _ = execute(
        tmp_path,
        monkeypatch,
        mutate=lambda _nav, reader, _s, value, *_: setattr(
            reader,
            "return_value",
            replace(
                value,
                selected=False,
                decision=None,
                replacement_grade=None,
                override_revision=None,
                override_sha256=None,
            ),
        ),
    )
    assert "none selected" in out and "not a zero Grade" in out
    nav.session.select_student.assert_called_once()


def test_family_is_preserved_and_not_inferred(tmp_path, monkeypatch):
    out, reader, _, scope, _ = execute(tmp_path, monkeypatch)
    assert scope.family == "standards_based"
    assert "standards based" in out
    assert reader.call_args.args[1].family == "standards_based"


def test_cancel_student_before_reader_is_read_only(tmp_path, monkeypatch):
    def cancel(_nav, _reader, _scope, _value, _student, _period):
        monkeypatch.setattr(named, "select_teacher_choice", lambda **kw: None)

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=cancel, answers=())
    assert out == "" or "selected" not in out
    reader.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_cancel_family_before_reader_is_read_only(tmp_path, monkeypatch):
    def cancel(_nav, _reader, _scope, _value, _student, _period):
        monkeypatch.setattr(named, "_family", lambda **kw: None)

    _, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=cancel, answers=())
    reader.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_wrong_review_scope_fails_closed(tmp_path, monkeypatch):
    def wrong(_nav, reader, scope, value, *_):
        reader.return_value = replace(value, scope=replace(scope, class_id="wrong"))

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=wrong)
    assert reader.call_count == 1
    assert "changed" in out
    nav.session.select_student.assert_not_called()


def test_current_override_changes_between_reads(tmp_path, monkeypatch):
    def changed(_nav, reader, _scope, value, *_):
        reader.side_effect = [
            value,
            replace(value, decision="withdraw", replacement_grade=None),
        ]

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=changed)
    assert reader.call_count == 2 and "changed" in out
    nav.session.select_student.assert_not_called()


def test_roster_witness_disappears_after_read(tmp_path, monkeypatch):
    def removed(_nav, reader, _scope, _value, *_):
        calls = {"n": 0}

        def revalidate(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise named._ScopeChanged("student removed")

        monkeypatch.setattr(named, "_current_choice", revalidate)

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=removed)
    assert reader.call_count <= 1
    assert "changed" in out
    nav.session.select_student.assert_not_called()


def test_stale_period_prevents_unauthorized_read(tmp_path, monkeypatch):
    def stale(nav, _reader, _scope, _value, *_):
        nav.current_period.return_value = None

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=stale)
    assert "changed" in out
    reader.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_opaque_domain_exception_is_redacted(tmp_path, monkeypatch):
    def secret(_nav, reader, *_):
        reader.side_effect = RuntimeError("secret student record /private/path")

    out, reader, nav, _, _ = execute(tmp_path, monkeypatch, mutate=secret)
    assert "secret" not in out and "/private/path" not in out
    assert "could not be verified" in out
    nav.session.select_student.assert_not_called()


def test_invalid_selected_decision_is_blocked(tmp_path, monkeypatch):
    def corrupt(_nav, reader, _scope, value, *_):
        reader.return_value = replace(value, decision="not-recognized")

    out, _, nav, _, _ = execute(tmp_path, monkeypatch, mutate=corrupt)
    assert "changed" in out
    nav.session.select_student.assert_not_called()


def test_blank_override_grade_is_blocked(tmp_path, monkeypatch):
    def missing(_nav, reader, _scope, value, *_):
        reader.return_value = replace(value, replacement_grade=None)

    out, _, nav, _, _ = execute(tmp_path, monkeypatch, mutate=missing)
    assert "changed" in out
    nav.session.select_student.assert_not_called()


def test_main_quit_unwind(tmp_path, monkeypatch):
    for error in (ReturnToMainMenu, QuitPDS):
        nav, reader, _, _, _, _ = setup(tmp_path, monkeypatch)
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=error))
        with pytest.raises(error):
            named.run_named_current_override_review(
                navigation=nav,
                review_loader=reader,
                input_fn=scripted(),
                output=StringIO(),
                clear_fn=lambda: None,
            )
        reader.assert_not_called()


def test_menu_advanced_compatibility_and_routine_route() -> None:
    path = Path(__file__).resolve().parents[1] / "meridian/menu_overrides.py"
    source = path.read_text(encoding="utf-8")
    assert '"1. Review current override by student and marking period"' in source
    assert "run_named_current_override_review(" in source
    for operation in (
        "Advanced: Review current override (exact records)",
        "Advanced: Author a new override revision",
        "Advanced: Select the latest authored override",
        "Advanced: Withdraw the current override",
    ):
        assert operation in source
    assert "_review_current(" in source
    assert "_author_override(" in source
    assert "_select_latest(" in source
    assert "_withdraw_override(" in source
