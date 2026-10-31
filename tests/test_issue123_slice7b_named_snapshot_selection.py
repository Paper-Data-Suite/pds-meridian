"""Issue #123 Slice 7B: guided exact-CAS ReportingSnapshot selection."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_snapshot_selection as named

CLASS = "class-canonical"
SNAPSHOT = "opaque-snapshot"
DIGEST = "a" * 64
PERIOD = "mp1"
YEAR = "2026-2027"
DECIDED = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Reference:
    class_id: str = CLASS
    snapshot_id: str = SNAPSHOT
    snapshot_sha256: str = DIGEST


@dataclass(frozen=True)
class Current:
    class_id: str = CLASS
    definition_id: str = "opaque-definition"
    target_period: object = None
    calendar_revision: int = 3
    selection_revision: int = 1


@dataclass(frozen=True)
class Plan:
    class_id: str = CLASS
    snapshot_id: str = SNAPSHOT
    snapshot_sha256: str = DIGEST
    definition_id: str = "opaque-definition"
    school_year: str = YEAR
    period_id: str = PERIOD
    calendar_revision: int = 3
    row_count: int = 18
    actor_id: str = "saved-teacher"
    rationale: str | None = "Reviewed checkpoint"
    decided_at: datetime = DECIDED
    current_snapshot_id: str | None = None
    current_selection_revision: int | None = None
    target_reference: Reference = Reference()
    expected_current: Current | None = None


def scripted(*responses):
    seq = iter(responses)
    return lambda _prompt: next(seq)


def item(**changes):
    data = dict(
        snapshot_id=SNAPSHOT,
        definition_id="opaque-definition",
        definition_revision=2,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        row_count=18,
        created_at="2026-10-20T14:33:00+00:00",
        snapshot_sha256=DIGEST,
    )
    data.update(changes)
    return SimpleNamespace(**data)


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):
    nav = MagicMock()
    current_class = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=3,
        label="Term One",
    )
    nav.current_class.return_value = current_class
    nav.current_period.return_value = period
    choice_period = SimpleNamespace(identity=(PERIOD,), label="Term One")
    lister = MagicMock(return_value=(item(),))
    inspector = MagicMock(
        return_value=SimpleNamespace(item=item(), current_for_scope=False)
    )
    plan = Plan()
    previewer = MagicMock(return_value=plan)

    def commit(_root, _plan):
        inspector.return_value = SimpleNamespace(item=item(), current_for_scope=True)
        return "created"

    committer = MagicMock(side_effect=commit)
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_kw: (period, choice_period)
    )
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **kw: kw["catalog"].options(
            scope="frozen_snapshot", selected={"class": CLASS}
        )[0],
    )
    monkeypatch.setattr(
        named,
        "load_teacher_choices",
        lambda catalog, *, scope, selected: (choice_period,),
    )
    # Class attribute default is a function; the synthetic definition loader
    # supplies a verified record.
    monkeypatch.setattr(
        __import__(
            "meridian.menu_teacher_named_snapshots", fromlist=["_definition_title"]
        ),
        "load_reporting_definition_revision",
        lambda *_a: SimpleNamespace(
            definition=SimpleNamespace(
                class_id=CLASS,
                definition_id="opaque-definition",
                definition_revision=2,
                title="Marking Period Grade Report",
            )
        ),
    )
    output = StringIO()
    args = dict(
        navigation=nav,
        lister=lister,
        inspector=inspector,
        selection_previewer=previewer,
        selection_committer=committer,
        clock=lambda: DECIDED,
        input_fn=scripted(
            *kwargs.get("answers", ("Reviewed checkpoint", "saved-teacher", "USE", ""))
        ),
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return args, nav, lister, inspector, previewer, committer, plan, period


def execute(tmp_path, monkeypatch, mutate=None, **kwargs):
    state = setup(tmp_path, monkeypatch, **kwargs)
    args, nav, lister, inspector, previewer, committer, plan, period = state
    if mutate:
        mutate(*state)
    named.run_named_snapshot_selection(**args)
    return args["output"].getvalue(), state


def test_success_exact_selection_and_no_sis(tmp_path, monkeypatch):
    out, st = execute(tmp_path, monkeypatch)
    args, nav, lister, inspector, previewer, committer, plan, period = st
    assert "Marking Period Grade Report" in out and "Term One" in out
    assert "selected for local reporting use (created)" in out
    assert "No district/SIS Grade" in out
    assert SNAPSHOT not in out and DIGEST not in out
    assert previewer.call_count == 2
    previewer.assert_called_with(
        tmp_path, CLASS, SNAPSHOT, "saved-teacher", "Reviewed checkpoint", DECIDED
    )
    committer.assert_called_once_with(tmp_path, plan)


def test_cancel_confirmation_never_commits(tmp_path, monkeypatch):
    out, st = execute(
        tmp_path, monkeypatch, answers=("Reviewed checkpoint", "saved-teacher", "", "")
    )
    assert "Canceled" in out
    st[5].assert_not_called()


def test_missing_actor_never_previews_or_commits(tmp_path, monkeypatch):
    out, st = execute(tmp_path, monkeypatch, answers=("reason", "", ""))
    assert "attribution unavailable" in out
    st[4].assert_not_called()
    st[5].assert_not_called()


def test_missing_period_no_authority(tmp_path, monkeypatch):
    def modify(*st):
        monkeypatch.setattr(named, "_marking_period", lambda *_a, **_k: None)

    out, st = execute(tmp_path, monkeypatch, mutate=modify, answers=())
    assert out == ""
    st[4].assert_not_called()


def test_wrong_snapshot_period_is_never_selected(tmp_path, monkeypatch):
    def modify(args, nav, lister, *_):
        lister.return_value = (item(period_id="mp2"),)

    out, st = execute(tmp_path, monkeypatch, mutate=modify, answers=("",))
    assert "could not be verified" in out
    st[5].assert_not_called()


def test_wrong_class_stops_before_catalog(tmp_path, monkeypatch):
    def modify(args, nav, *_):
        nav.current_class.return_value = SimpleNamespace(
            workspace=tmp_path, class_id="other", school_year=YEAR
        )

    out, st = execute(tmp_path, monkeypatch, mutate=modify, answers=("",))
    assert "changed" in out
    st[4].assert_not_called()


def test_digest_changed_before_preview_stops(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, *_):
        inspector.return_value = SimpleNamespace(
            item=item(snapshot_sha256="b" * 64), current_for_scope=False
        )

    out, st = execute(tmp_path, monkeypatch, mutate=modify, answers=("",))
    assert "changed" in out
    st[4].assert_not_called()


def test_already_current_does_not_author_again(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, *_):
        inspector.return_value = SimpleNamespace(item=item(), current_for_scope=True)

    out, st = execute(tmp_path, monkeypatch, mutate=modify, answers=("",))
    assert "already current" in out
    st[4].assert_not_called()
    st[5].assert_not_called()


def test_preview_wrong_class_is_blocked(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        previewer.return_value = replace(Plan(), class_id="other")

    out, st = execute(
        tmp_path, monkeypatch, mutate=modify, answers=("reason", "actor", "")
    )
    assert "changed" in out
    st[5].assert_not_called()


def test_preview_wrong_digest_is_blocked(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        previewer.return_value = replace(
            Plan(), target_reference=replace(Reference(), snapshot_sha256="b" * 64)
        )

    out, st = execute(
        tmp_path, monkeypatch, mutate=modify, answers=("reason", "actor", "")
    )
    assert "changed" in out
    st[5].assert_not_called()


def test_preview_wrong_rationale_is_blocked(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        previewer.return_value = replace(Plan(), rationale="other")

    out, st = execute(
        tmp_path, monkeypatch, mutate=modify, answers=("reason", "actor", "")
    )
    assert "changed" in out
    st[5].assert_not_called()


def test_repreview_changed_state_blocks_commit(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        previewer.side_effect = [Plan(), replace(Plan(), row_count=19)]

    out, st = execute(tmp_path, monkeypatch, mutate=modify)
    assert "changed" in out
    st[5].assert_not_called()


def test_inspection_changes_after_confirmation(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, *_):
        inspector.side_effect = [
            SimpleNamespace(item=item(), current_for_scope=False),
            SimpleNamespace(item=item(), current_for_scope=True),
        ]

    out, st = execute(tmp_path, monkeypatch, mutate=modify)
    assert "changed" in out
    st[5].assert_not_called()


def test_stale_period_blocks_before_commit(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        orig = previewer.return_value

        def stale(*_a, **_kw):
            nav.current_period.return_value = None
            return orig

        previewer.side_effect = stale

    out, st = execute(
        tmp_path, monkeypatch, mutate=modify, answers=("reason", "actor", "")
    )
    assert "changed" in out
    st[5].assert_not_called()


def test_commit_exception_reports_uncertain(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, committer, *_):
        committer.side_effect = RuntimeError("private student data /secret")

    out, st = execute(tmp_path, monkeypatch, mutate=modify)
    assert "outcome could not be verified" in out
    assert "/secret" not in out
    st[5].assert_called_once()


def test_unrecognized_disposition_reports_uncertain(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, committer, *_):
        committer.side_effect = lambda *_a: "unrecognized"

    out, st = execute(tmp_path, monkeypatch, mutate=modify)
    assert "outcome is uncertain" in out
    st[5].assert_called_once()


def test_postcommit_read_not_current_reports_uncertain(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, committer, *_):
        committer.side_effect = lambda *_a: "updated"

    out, st = execute(tmp_path, monkeypatch, mutate=modify)
    assert "outcome is uncertain" in out
    st[5].assert_called_once()


def test_preview_exception_is_redacted_no_write(tmp_path, monkeypatch):
    def modify(args, nav, lister, inspector, previewer, *_):
        previewer.side_effect = RuntimeError("private student /secret")

    out, st = execute(
        tmp_path, monkeypatch, mutate=modify, answers=("reason", "actor", "")
    )
    assert "/secret" not in out
    assert "No selection was attempted" in out
    st[5].assert_not_called()


@pytest.mark.parametrize("signal", (ReturnToMainMenu, QuitPDS))
def test_main_quit_unwind_before_select(tmp_path, monkeypatch, signal):
    args, nav, lister, inspector, previewer, committer, plan, period = setup(
        tmp_path, monkeypatch
    )
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))
    with pytest.raises(signal):
        named.run_named_snapshot_selection(**args)
    committer.assert_not_called()


def test_menu_keeps_advanced_and_new_route() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "meridian/menu_snapshots.py"
    ).read_text(encoding="utf-8")
    assert "8. Use a frozen reporting checkpoint by name" in text
    assert "run_named_snapshot_selection(" in text
    assert "Advanced: Freeze a ReportingSnapshot (build-request JSON)" in text
    prompt = re.search(r"Please choose 1-(\d+), B, M, or Q\.", text)
    assert prompt is not None and int(prompt.group(1)) >= 8
    assert "Please choose 1-6, B, M, or Q." in text
