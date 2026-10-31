"""#123 Slice 6B2: named immutable override authoring never applies selection."""

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

import meridian.menu_teacher_named_override_authoring as named
from meridian.menu_overrides import OverrideAuthoringPlan, OverrideScope
from meridian.teacher_navigation_choices import TeacherChoice

CLASS = "english-12"
STUDENT = "private-student-id"
YEAR = "2026-2027"
PERIOD = "mp1"


def scripted(*responses: str):
    it = iter(responses)
    return lambda _prompt: next(it)


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
    choice = TeacherChoice(identity=(PERIOD,), label="Marking Period 1")
    student = TeacherChoice(identity=(STUDENT,), label="Morgan Reed")
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "_marking_period", lambda *_a, **_kw: (period, choice))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: student)
    monkeypatch.setattr(named, "_family", lambda **_kw: "standards_based")
    guard = MagicMock()
    monkeypatch.setattr(named, "_revalidate", guard)
    candidate = SimpleNamespace(
        class_id=CLASS,
        student_id=STUDENT,
        target_period=scope.period,
        calendar_revision=3,
        calculation_family="standards_based",
        decision="override",
        replacement_grade=Decimal("0.00"),
        actor=SimpleNamespace(actor_id="teacher-1"),
        rationale="Individual documented exception",
        override_revision=2,
    )
    source = SimpleNamespace(
        source_status="calculated",
        base_grade=Decimal("87.50"),
        freshness_status="current",
    )
    preview = SimpleNamespace(
        candidate=candidate, candidate_sha256="a" * 64, source=source
    )
    plan = OverrideAuthoringPlan(
        scope=scope,
        replacement_grade="0.00",
        source_status="calculated",
        source_grade="87.50",
        source_freshness="current",
        candidate_revision=2,
        candidate_sha256="a" * 64,
        actor_id="teacher-1",
        rationale="Individual documented exception",
        preview=preview,
    )
    author = MagicMock(return_value=plan)
    commit = MagicMock(return_value="created")
    return nav, scope, plan, author, commit, guard


def execute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses=("0.00", "Individual documented exception", "teacher-1", "WRITE", ""),
    mutate=None,
):
    nav, scope, plan, author, commit, guard = fixture(tmp_path, monkeypatch)
    if mutate is not None:
        mutate(nav, scope, plan, author, commit, guard)
    out = StringIO()
    prompts: list[str] = []
    inp = scripted(*responses)

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return inp(prompt)

    named.run_named_override_authoring(
        navigation=nav,
        authoring_previewer=author,
        authoring_committer=commit,
        clock=lambda: __import__("datetime").datetime(2026, 10, 23),
        input_fn=input_fn,
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return out.getvalue(), prompts, nav, plan, author, commit, guard


def test_write_does_not_activate_override(tmp_path, monkeypatch):
    out, prompts, nav, plan, author, commit, guard = execute(tmp_path, monkeypatch)
    assert "Morgan Reed" in out and "Marking Period 1" in out
    assert "Replacement Grade to record: 0.00" in out
    assert "Base Grade: 87.50" in out
    assert "NOT the current override" in out
    assert "option 6" in out
    assert STUDENT not in out and "a" * 64 not in out
    assert "Teacher actor ID: " in prompts
    assert author.call_count == 2 and guard.call_count >= 4
    assert author.call_args.args[:2] == (tmp_path, plan.scope)
    commit.assert_called_once_with(tmp_path, plan)
    nav.session.select_student.assert_called_once_with(STUDENT)


def test_confirmation_cancel_never_writes(tmp_path, monkeypatch):
    out, _, nav, _, author, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", "", ""),
    )
    assert "Canceled" in out
    author.assert_called_once()
    commit.assert_not_called()
    nav.session.select_student.assert_not_called()


@pytest.mark.parametrize("bad", ("nan", "Infinity", "-Infinity", "not-a-grade"))
def test_invalid_or_nonfinite_grade_fails_before_authoring(tmp_path, monkeypatch, bad):
    out, _, _, _, author, commit, _ = execute(
        tmp_path, monkeypatch, responses=(bad, "")
    )
    assert "Nothing" in out or "nothing" in out
    author.assert_not_called()
    commit.assert_not_called()


def test_blank_grade_cancels_without_authoring(tmp_path, monkeypatch):
    _, _, _, _, author, commit, _ = execute(tmp_path, monkeypatch, responses=("",))
    author.assert_not_called()
    commit.assert_not_called()


def test_rationale_and_attribution_are_required(tmp_path, monkeypatch):
    for answer in (
        ("0.00", "", ""),
        ("0.00", "Individual documented exception", "", ""),
    ):
        out, _, _, _, author, commit, _ = execute(
            tmp_path, monkeypatch, responses=answer
        )
        assert "nothing" in out
        author.assert_not_called()
        commit.assert_not_called()


def test_scope_mismatch_rejected_before_confirmation(tmp_path, monkeypatch):
    def wrong(_nav, scope, plan, author, *_):
        author.return_value = replace(plan, scope=replace(scope, class_id="wrong"))

    out, _, _, _, _, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", ""),
        mutate=wrong,
    )
    assert "changed" in out
    commit.assert_not_called()


def test_canonical_actor_mismatch_rejected(tmp_path, monkeypatch):
    def wrong(_nav, _scope, plan, _author, *_):
        plan.preview.candidate.actor.actor_id = "unreviewed-actor"

    out, _, _, _, _, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", ""),
        mutate=wrong,
    )
    assert "changed" in out
    commit.assert_not_called()


def test_preview_digest_mismatch_rejected(tmp_path, monkeypatch):
    def wrong(_nav, _scope, plan, _author, *_):
        plan.preview.candidate_sha256 = "b" * 64

    out, _, _, _, _, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", ""),
        mutate=wrong,
    )
    assert "changed" in out
    commit.assert_not_called()


def test_history_changed_after_confirmation_aborts_write(tmp_path, monkeypatch):
    def changed(_nav, _scope, plan, author, *_):
        author.side_effect = [plan, replace(plan, candidate_revision=3)]

    out, _, _, _, author, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", "WRITE", ""),
        mutate=changed,
    )
    assert author.call_count == 2
    assert "changed" in out
    commit.assert_not_called()


def test_uncertain_write_preserves_durability_warning(tmp_path, monkeypatch):
    def failed(_nav, _scope, _plan, _author, commit, _guard):
        commit.side_effect = RuntimeError("secret account path /private")

    out, _, nav, _, _, commit, _ = execute(tmp_path, monkeypatch, mutate=failed)
    assert commit.call_count == 1
    assert "may have been stored" in out
    assert "secret" not in out and "/private" not in out
    nav.session.select_student.assert_not_called()


def test_stale_roster_aborts_before_authoring(tmp_path, monkeypatch):
    def stale(_nav, _scope, _plan, _author, _commit, guard):
        guard.side_effect = named._ScopeChanged("student removed")

    out, _, _, _, author, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", ""),
        mutate=stale,
    )
    assert "changed" in out
    author.assert_not_called()
    commit.assert_not_called()


def test_missing_domain_evidence_is_redacted(tmp_path, monkeypatch):
    def missing(_nav, _scope, _plan, author, _commit, _guard):
        author.side_effect = RuntimeError("secret student grade input")

    out, _, _, _, _, commit, _ = execute(
        tmp_path,
        monkeypatch,
        responses=("0.00", "Individual documented exception", "teacher-1", ""),
        mutate=missing,
    )
    assert "could not be prepared safely" in out
    assert "secret" not in out
    commit.assert_not_called()


def test_student_or_family_cancel_is_write_free(tmp_path, monkeypatch):
    for which in ("student", "family"):
        nav, _scope, _plan, author, commit, _guard = fixture(tmp_path, monkeypatch)
        if which == "student":
            monkeypatch.setattr(named, "select_teacher_choice", lambda **kw: None)
        else:
            monkeypatch.setattr(named, "_family", lambda **kw: None)
        named.run_named_override_authoring(
            navigation=nav,
            authoring_previewer=author,
            authoring_committer=commit,
            clock=lambda: __import__("datetime").datetime(2026, 10, 23),
            input_fn=scripted(),
            output=StringIO(),
            clear_fn=lambda: None,
            class_catalog=MagicMock(),
            period_catalog=MagicMock(),
        )
        author.assert_not_called()
        commit.assert_not_called()
        monkeypatch.setattr(
            named,
            "select_teacher_choice",
            lambda **kw: TeacherChoice(identity=(STUDENT,), label="Morgan Reed"),
        )


def test_m_q_navigation_unwinds(tmp_path, monkeypatch):
    for raised in (ReturnToMainMenu, QuitPDS):
        nav, _, _, author, commit, _ = fixture(tmp_path, monkeypatch)
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=raised))
        with pytest.raises(raised):
            named.run_named_override_authoring(
                navigation=nav,
                authoring_previewer=author,
                authoring_committer=commit,
                clock=lambda: __import__("datetime").datetime(2026, 10, 23),
                input_fn=scripted(),
                output=StringIO(),
                clear_fn=lambda: None,
                class_catalog=MagicMock(),
                period_catalog=MagicMock(),
            )
        author.assert_not_called()
        commit.assert_not_called()


def test_existing_advanced_and_use_routes_remain() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_overrides.py"
    ).read_text(encoding="utf-8")
    assert '"7. Record a replacement Grade decision by student"' in source
    assert "run_named_override_authoring(" in source
    assert '"6. Use the latest authored override decision by student"' in source
    assert "Advanced: Author a new override revision" in source
    assert "Advanced: Withdraw the current override" in source
    assert "_author_override(" in source and "_withdraw_override(" in source
