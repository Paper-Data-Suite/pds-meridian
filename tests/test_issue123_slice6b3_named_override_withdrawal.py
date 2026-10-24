"""#123 Slice 6B3: named withdrawal records but never selects a decision."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_override_withdrawal as named
from meridian.menu_overrides import OverrideScope, OverrideWithdrawalPlan
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
STUDENT = "private-student-id"
YEAR = "2026-2027"
PERIOD = "mp1"
RATIONALE = "Documented withdrawal rationale"


def scripted(*answers: str):
    choices = iter(answers)
    return lambda _prompt: next(choices)


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    scope = OverrideScope(
        class_id=CLASS,
        student_id=STUDENT,
        period=AcademicPeriodRef(YEAR, PERIOD),
        calendar_revision=3,
        family="standards_based",
    )
    cls = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        label="Marking Period 1",
    )
    nav = MagicMock()
    nav.current_class.return_value = cls
    nav.current_period.return_value = period
    period_choice = TeacherChoice(identity=(PERIOD,), label="Marking Period 1")
    student = TeacherChoice(identity=(STUDENT,), label="Morgan Reed")
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_kw: (period, period_choice)
    )
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: student)
    monkeypatch.setattr(named, "_family", lambda **_kw: "standards_based")
    guard = MagicMock()
    monkeypatch.setattr(named, "_revalidate", guard)
    selected = SimpleNamespace(
        class_id=CLASS,
        student_id=STUDENT,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        calculation_family="standards_based",
        override_revision=2,
        override_sha256="a" * 64,
    )
    source_ref = SimpleNamespace(identity="source-result")
    prior = SimpleNamespace(
        decision="override",
        replacement_grade=Decimal("0.00"),
        source_result=source_ref,
    )
    candidate = SimpleNamespace(
        class_id=CLASS,
        student_id=STUDENT,
        target_period=scope.period,
        calendar_revision=3,
        calculation_family="standards_based",
        decision="withdraw",
        replacement_grade=None,
        withdrawn_override_reference=selected,
        source_result=source_ref,
        override_revision=3,
        actor=SimpleNamespace(actor_id="teacher-1"),
        rationale=RATIONALE,
    )
    source = SimpleNamespace(source_status="calculated", base_grade=Decimal("87.50"))
    preview = SimpleNamespace(
        selected_override_reference=selected,
        selected_override_decision=prior,
        source=source,
        candidate=candidate,
        history_before=(1, 2),
        candidate_sha256="b" * 64,
    )
    plan = OverrideWithdrawalPlan(
        scope=scope,
        selected_revision=2,
        selected_sha256="a" * 64,
        source_status="calculated",
        source_grade="87.50",
        candidate_revision=3,
        candidate_sha256="b" * 64,
        actor_id="teacher-1",
        rationale=RATIONALE,
        preview=preview,
    )
    previewer = MagicMock(return_value=plan)
    committer = MagicMock(return_value="created")
    return nav, scope, plan, previewer, committer, guard


def execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses=(RATIONALE, "teacher-1", "WITHDRAW", ""),
    mutate=None,
):
    nav, scope, plan, previewer, committer, guard = fixture(tmp_path, monkeypatch)
    if mutate is not None:
        mutate(nav, scope, plan, previewer, committer, guard)
    out = StringIO()
    prompts: list[str] = []
    inp = scripted(*responses)

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return inp(prompt)

    named.run_named_override_withdrawal(
        navigation=nav,
        withdrawal_previewer=previewer,
        withdrawal_committer=committer,
        clock=lambda: datetime(2026, 10, 24),
        input_fn=input_fn,
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return out.getvalue(), prompts, nav, plan, previewer, committer, guard


def test_write_preserves_current_override_and_points_to_separate_use(
    tmp_path, monkeypatch
):
    out, prompts, nav, plan, previewer, committer, guard = execute(
        tmp_path, monkeypatch
    )
    assert "Morgan Reed" in out and "Marking Period 1" in out
    assert "Base Grade: 87.50" in out
    assert "withdrawal version: 3" in out
    assert "prior selected replacement Grade remains current" in out
    assert "option 6" in out
    assert STUDENT not in out and "a" * 64 not in out
    assert "Teacher actor ID: " in prompts
    assert previewer.call_count == 2 and guard.call_count >= 4
    assert previewer.call_args.args[:2] == (tmp_path, plan.scope)
    committer.assert_called_once_with(tmp_path, plan)
    nav.session.select_student.assert_called_once_with(STUDENT)


def test_explicit_confirmation_required(tmp_path, monkeypatch):
    out, _, nav, _, previewer, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", "", "")
    )
    assert "Canceled" in out
    previewer.assert_called_once()
    committer.assert_not_called()
    nav.session.select_student.assert_not_called()


@pytest.mark.parametrize("confirmation", ("withdraw", "SELECT", "USE"))
def test_only_exact_withdraw_confirmation_writes(tmp_path, monkeypatch, confirmation):
    _, _, _, _, _, committer, _ = execute(
        tmp_path,
        monkeypatch,
        responses=(RATIONALE, "teacher-1", confirmation, ""),
    )
    committer.assert_not_called()


def test_required_rationale_and_actor(tmp_path, monkeypatch):
    for answers in (("", ""), (RATIONALE, "", "")):
        _, _, _, _, previewer, committer, _ = execute(
            tmp_path, monkeypatch, responses=answers
        )
        previewer.assert_not_called()
        committer.assert_not_called()


def test_wrong_scope_cannot_be_confirmed(tmp_path, monkeypatch):
    def wrong(_nav, scope, plan, previewer, *_):
        previewer.return_value = replace(plan, scope=replace(scope, class_id="wrong"))

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=wrong
    )
    assert "changed" in out
    committer.assert_not_called()


def test_selected_override_must_be_active(tmp_path, monkeypatch):
    def bad(_nav, _scope, plan, *_):
        plan.preview.selected_override_decision.decision = "withdraw"

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=bad
    )
    assert "changed" in out
    committer.assert_not_called()


def test_candidate_must_be_withdraw_not_override(tmp_path, monkeypatch):
    def bad(_nav, _scope, plan, *_):
        plan.preview.candidate.decision = "override"

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=bad
    )
    assert "changed" in out
    committer.assert_not_called()


def test_canonical_teacher_must_match_saved_attribution(tmp_path, monkeypatch):
    def wrong(_nav, _scope, plan, *_):
        plan.preview.candidate.actor.actor_id = "unreviewed-actor"

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=wrong
    )
    assert "changed" in out
    committer.assert_not_called()


def test_candidate_digest_guard(tmp_path, monkeypatch):
    def changed(_nav, _scope, plan, *_):
        plan.preview.candidate_sha256 = "c" * 64

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=changed
    )
    assert "changed" in out
    committer.assert_not_called()


def test_changed_basis_after_confirmation_aborts(tmp_path, monkeypatch):
    def changed(_nav, _scope, plan, previewer, *_):
        previewer.side_effect = [plan, replace(plan, candidate_revision=4)]

    out, _, _, _, previewer, committer, _ = execute(
        tmp_path, monkeypatch, mutate=changed
    )
    assert "changed" in out and previewer.call_count == 2
    committer.assert_not_called()


def test_stale_roster_aborts_before_domain_read(tmp_path, monkeypatch):
    def changed(_nav, _scope, _plan, _previewer, _committer, guard):
        guard.side_effect = named._ScopeChanged("student removed")

    out, _, _, _, previewer, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=changed
    )
    assert "changed" in out
    previewer.assert_not_called()
    committer.assert_not_called()


def test_no_active_override_cannot_be_withdrawn(tmp_path, monkeypatch):
    def absent(_nav, _scope, _plan, previewer, *_):
        previewer.side_effect = RuntimeError("secret private school file")

    out, _, _, _, _, committer, _ = execute(
        tmp_path, monkeypatch, responses=(RATIONALE, "teacher-1", ""), mutate=absent
    )
    assert "no active override" in out
    assert "secret" not in out
    committer.assert_not_called()


def test_uncertain_commit_does_not_claim_rollback(tmp_path, monkeypatch):
    def fails(_nav, _scope, _plan, _previewer, committer, _guard):
        committer.side_effect = RuntimeError("secret /private student")

    out, _, nav, _, _, committer, _ = execute(tmp_path, monkeypatch, mutate=fails)
    assert committer.call_count == 1
    assert "may have been stored" in out
    assert "secret" not in out
    nav.session.select_student.assert_not_called()


def test_cancel_student_or_family_has_no_domain_work(tmp_path, monkeypatch):
    for operation in ("student", "family"):
        nav, _, _, previewer, committer, _ = fixture(tmp_path, monkeypatch)
        if operation == "student":
            monkeypatch.setattr(named, "select_teacher_choice", lambda **kw: None)
        else:
            monkeypatch.setattr(named, "_family", lambda **kw: None)
        named.run_named_override_withdrawal(
            navigation=nav,
            withdrawal_previewer=previewer,
            withdrawal_committer=committer,
            clock=lambda: datetime(2026, 10, 24),
            input_fn=scripted(),
            output=StringIO(),
            clear_fn=lambda: None,
            class_catalog=MagicMock(),
            period_catalog=MagicMock(),
        )
        previewer.assert_not_called()
        committer.assert_not_called()
        monkeypatch.setattr(
            named,
            "select_teacher_choice",
            lambda **kw: TeacherChoice(identity=(STUDENT,), label="Morgan Reed"),
        )


def test_main_menu_and_quit_unwind(tmp_path, monkeypatch):
    for error in (ReturnToMainMenu, QuitPDS):
        nav, _, _, previewer, committer, _ = fixture(tmp_path, monkeypatch)
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=error))
        with pytest.raises(error):
            named.run_named_override_withdrawal(
                navigation=nav,
                withdrawal_previewer=previewer,
                withdrawal_committer=committer,
                clock=lambda: datetime(2026, 10, 24),
                input_fn=scripted(),
                output=StringIO(),
                clear_fn=lambda: None,
            )
        previewer.assert_not_called()
        committer.assert_not_called()


def test_advanced_routes_and_use_route_preserved() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_overrides.py"
    ).read_text(encoding="utf-8")
    assert "8. Record withdrawal of a selected replacement by student" in source
    assert "run_named_override_withdrawal(" in source
    for expected in (
        "6. Use the latest authored override decision by student",
        "7. Record a replacement Grade decision by student",
        "Advanced: Withdraw the current override",
    ):
        assert expected in source
    assert "_withdraw_override(" in source
