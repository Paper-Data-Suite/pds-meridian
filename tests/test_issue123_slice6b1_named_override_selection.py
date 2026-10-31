"""#123 Slice 6B1: select latest authored override only, by named teacher scope."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_override_selection as named
from meridian.menu_overrides import OverrideScope, OverrideSelectionPlan
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
STUDENT = "opaque-student-id"
YEAR = "2026-2027"
PERIOD = "mp1"


def inputs(*answers: str):
    items = iter(answers)
    return lambda _prompt: next(items)


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scope = OverrideScope(
        class_id=CLASS,
        student_id=STUDENT,
        period=AcademicPeriodRef(YEAR, PERIOD),
        calendar_revision=3,
        family="standards_based",
    )
    class_scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        label="Marking Period 1",
    )
    nav = MagicMock()
    nav.current_class.return_value = class_scope
    nav.current_period.return_value = period
    period_choice = TeacherChoice(identity=(PERIOD,), label="Marking Period 1")
    student = TeacherChoice(identity=(STUDENT,), label="Morgan Reed")
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_k: (period, period_choice)
    )
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: student)
    monkeypatch.setattr(named, "_family", lambda **_k: "standards_based")
    guard = MagicMock()
    monkeypatch.setattr(named, "_revalidate", guard)
    target = SimpleNamespace(
        class_id=CLASS,
        student_id=STUDENT,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        calculation_family="standards_based",
        override_revision=2,
        override_sha256="a" * 64,
    )
    decision = SimpleNamespace(decision="override", replacement_grade=Decimal("0.00"))
    preview = SimpleNamespace(
        target_reference=target,
        target_decision=decision,
        history=(1, 2),
        expected_current=None,
    )
    plan = OverrideSelectionPlan(
        scope=scope,
        target_revision=2,
        target_sha256="a" * 64,
        target_decision="override",
        replacement_grade="0.00",
        current_revision=None,
        current_sha256=None,
        preview=preview,
    )
    selector = MagicMock(return_value=plan)
    committer = MagicMock(return_value="created")
    return nav, scope, plan, selector, committer, guard


def execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    answers: tuple[str, ...] = ("USE", ""),
    mutate=None,
):
    nav, scope, plan, selector, committer, guard = fixture(tmp_path, monkeypatch)
    if mutate is not None:
        mutate(nav, scope, plan, selector, committer, guard)
    out = StringIO()
    named.run_named_latest_override_selection(
        navigation=nav,
        selection_previewer=selector,
        selection_committer=committer,
        input_fn=inputs(*answers),
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return out.getvalue(), nav, plan, selector, committer, guard


def test_explicit_use_selects_existing_override_once(tmp_path, monkeypatch):
    out, nav, plan, selector, committer, guard = execute(tmp_path, monkeypatch)
    assert "Morgan Reed" in out and "Marking Period 1" in out
    assert "Replacement Grade: 0.00" in out
    assert "latest authored override decision is now current" in out
    assert "opaque-student-id" not in out and "a" * 64 not in out
    assert "Override selection" not in out  # no technical label
    assert selector.call_count == 2
    assert selector.call_args.args[1] == plan.scope
    committer.assert_called_once_with(tmp_path, plan)
    assert guard.call_count == 4
    nav.session.select_student.assert_called_once_with(STUDENT)


def test_cancel_before_commit(tmp_path, monkeypatch):
    out, nav, _plan, selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("", "")
    )
    assert "Canceled" in out
    selector.assert_called_once()
    committer.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_no_op_if_exact_version_already_selected(tmp_path, monkeypatch):
    def same(_nav, _scope, plan, selector, *_):
        current = SimpleNamespace(override_revision=2, override_sha256="a" * 64)
        plan.preview.expected_current = current
        selector.return_value = replace(
            plan, current_revision=2, current_sha256="a" * 64
        )

    out, _nav, _plan, selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=same
    )
    assert "already current. No change made" in out
    selector.assert_called_once()
    committer.assert_not_called()


def test_withdrawal_explained_without_replacement(tmp_path, monkeypatch):
    def withdraw(_nav, _scope, plan, selector, *_):
        plan.preview.target_decision.decision = "withdraw"
        plan.preview.target_decision.replacement_grade = None
        selector.return_value = replace(
            plan, target_decision="withdraw", replacement_grade=None
        )

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, mutate=withdraw
    )
    assert "Latest authored decision: withdrawal" in out
    assert "stop applying the selected replacement Grade" in out
    assert "Replacement Grade:" not in out
    committer.assert_called_once()


def test_preview_second_read_change_aborts_before_commit(tmp_path, monkeypatch):
    def stale(_nav, _scope, plan, selector, *_):
        selector.side_effect = [plan, replace(plan, current_revision=1)]

    out, nav, _plan, selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("USE", ""), mutate=stale
    )
    assert selector.call_count == 2
    assert "changed" in out
    committer.assert_not_called()
    nav.session.select_student.assert_not_called()


def test_revalidation_fails_before_selection(tmp_path, monkeypatch):
    def fail(_nav, _scope, _plan, _selector, _committer, guard):
        guard.side_effect = named._ScopeChanged("roster removed")

    out, _nav, _plan, selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=fail
    )
    assert "changed" in out
    selector.assert_not_called()
    committer.assert_not_called()


def test_wrong_scope_rejected(tmp_path, monkeypatch):
    def invalid(_nav, scope, plan, selector, *_):
        selector.return_value = replace(plan, scope=replace(scope, student_id="other"))

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=invalid
    )
    assert "changed" in out
    committer.assert_not_called()


def test_wrong_target_digest_rejected(tmp_path, monkeypatch):
    def invalid(_nav, _scope, plan, _selector, *_):
        plan.preview.target_reference.override_sha256 = "b" * 64

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=invalid
    )
    assert "changed" in out
    committer.assert_not_called()


def test_stale_history_rejected(tmp_path, monkeypatch):
    def invalid(_nav, _scope, plan, _selector, *_):
        plan.preview.history = (1,)

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=invalid
    )
    assert "changed" in out
    committer.assert_not_called()


def test_unavailable_history_redacts_exception(tmp_path, monkeypatch):
    def fail(_nav, _scope, _plan, selector, *_):
        selector.side_effect = RuntimeError("secret private roster /path")

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=fail
    )
    assert "secret" not in out and "/path" not in out
    assert "could not be verified" in out
    committer.assert_not_called()


def test_commit_failure_does_not_claim_rollback(tmp_path, monkeypatch):
    def fail(_nav, _scope, _plan, _selector, committer, *_):
        committer.side_effect = RuntimeError("private failure may have written")

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, mutate=fail
    )
    assert committer.call_count == 1
    assert "may have changed" in out
    assert "No selection was attempted" not in out
    assert "private failure" not in out


def test_wrong_decision_rejected(tmp_path, monkeypatch):
    def invalid(_nav, _scope, plan, selector, *_):
        selector.return_value = replace(plan, target_decision="revert")

    out, _nav, _plan, _selector, committer, _guard = execute(
        tmp_path, monkeypatch, answers=("",), mutate=invalid
    )
    assert "changed" in out
    committer.assert_not_called()


def test_cancel_at_student_or_family(tmp_path, monkeypatch):
    for field in ("student", "family"):
        nav, scope, plan, selector, committer, _guard = fixture(tmp_path, monkeypatch)
        if field == "student":
            monkeypatch.setattr(named, "select_teacher_choice", lambda **_k: None)
        else:
            monkeypatch.setattr(named, "_family", lambda **_k: None)
        out = StringIO()
        named.run_named_latest_override_selection(
            navigation=nav,
            selection_previewer=selector,
            selection_committer=committer,
            input_fn=inputs(),
            output=out,
            clear_fn=lambda: None,
            class_catalog=MagicMock(),
            period_catalog=MagicMock(),
        )
        selector.assert_not_called()
        committer.assert_not_called()
        monkeypatch.setattr(
            named,
            "select_teacher_choice",
            lambda **_k: TeacherChoice(identity=(STUDENT,), label="Morgan Reed"),
        )


def test_m_q_navigation_preserved(tmp_path, monkeypatch):
    for error in (ReturnToMainMenu, QuitPDS):
        nav, _scope, _plan, selector, committer, _guard = fixture(tmp_path, monkeypatch)
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=error))
        with pytest.raises(error):
            named.run_named_latest_override_selection(
                navigation=nav,
                selection_previewer=selector,
                selection_committer=committer,
                input_fn=inputs(),
                output=StringIO(),
                clear_fn=lambda: None,
                class_catalog=MagicMock(),
                period_catalog=MagicMock(),
            )
        selector.assert_not_called()
        committer.assert_not_called()


def test_advanced_exact_routes_remain() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_overrides.py"
    ).read_text(encoding="utf-8")
    assert "run_named_latest_override_selection(" in source
    assert '"6. Use the latest authored override decision by student"' in source
    for text in (
        "Advanced: Author a new override revision",
        "Advanced: Select the latest authored override",
        "Advanced: Withdraw the current override",
        "Advanced: Review current override (exact records)",
    ):
        assert text in source
    assert "_select_latest(" in source
    assert "_withdraw_override(" in source
