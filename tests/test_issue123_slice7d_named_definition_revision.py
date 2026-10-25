"""#123 Slice 7D: teacher-named immutable reporting-definition revisions."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_definition_revision as named
from meridian.menu_snapshots import ReportingDefinitionPlan
from meridian.menu_teacher_named_definitions import NamedDefinitionItem
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
    reporting_definition_reference,
)

CLASS = "class-exact"
DEFINITION = "definition-exact"
PERIOD = "mp1"
YEAR = "2026-2027"
BEFORE = "a" * 64
WHEN = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)


def original(**changes):
    source = dict(
        definition_id=DEFINITION,
        revision=3,
        sha256=BEFORE,
        title="Existing Progress Report",
        purpose="Current classroom evidence",
        school_year=YEAR,
        period_id=PERIOD,
        revised_at="2026-10-23T17:00:00+00:00",
    )
    source.update(changes)
    return NamedDefinitionItem(**source)


def make_plan(
    title="Revised Progress Report",
    purpose="New assessment focus",
    actor="teacher-7",
    rationale="review",
    when=WHEN,
    *,
    revision=4,
):
    candidate = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS,
        definition_id=DEFINITION,
        definition_revision=revision,
        supersedes_revision=revision - 1,
        report_kind="grade_report",
        purpose=purpose,
        title=title,
        target_period=AcademicPeriodRef(YEAR, PERIOD),
        intended_audience="teacher",
        actor=ReportingActor("teacher", actor),
        rationale=rationale,
        revised_at=when,
    )
    return ReportingDefinitionPlan(
        class_id=CLASS,
        definition_id=DEFINITION,
        definition_revision=revision,
        definition_sha256=reporting_definition_reference(candidate).definition_sha256,
        title=title,
        purpose=purpose,
        school_year=YEAR,
        period_id=PERIOD,
        actor_id=actor,
        rationale=rationale,
        candidate=candidate,
    )


def inputs(*values):
    iterator = iter(values)
    return lambda _prompt="": next(iterator)


def setup(tmp_path, monkeypatch, *, responses=None, target=True):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=2,
        label="Marking Period One",
    )
    nav.current_period.return_value = period
    period_choice = SimpleNamespace(identity=(PERIOD,), label="Marking Period One")
    lister = MagicMock(return_value=(original(),))
    previewer = MagicMock(return_value=make_plan())
    committer = MagicMock()

    def write(_root, plan):
        lister.return_value = (
            original(
                revision=plan.definition_revision,
                sha256=plan.definition_sha256,
                title=plan.title,
                purpose=plan.purpose,
            ),
        )
        return "created"

    committer.side_effect = write
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_k: (period, period_choice)
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda _cat, *, scope, selected: (period_choice,)
    )
    chooser = MagicMock(
        side_effect=lambda **kw: (
            kw["catalog"].options(scope="report_definition", selected={"class": CLASS})[
                0
            ]
            if target
            else None
        )
    )
    monkeypatch.setattr(named, "select_teacher_choice", chooser)
    out = StringIO()
    opts = dict(
        navigation=nav,
        definition_previewer=previewer,
        definition_committer=committer,
        clock=lambda: WHEN,
        input_fn=inputs(
            *(
                responses
                or (
                    "Revised Progress Report",
                    "New assessment focus",
                    "review",
                    "teacher-7",
                    "WRITE",
                    "",
                )
            )
        ),
        output=out,
        clear_fn=lambda: None,
        definition_lister=lister,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return opts, nav, lister, previewer, committer, chooser, out


def execute(tmp_path, monkeypatch, *, responses=None, target=True, mutate=None):
    opts, nav, lister, previewer, committer, chooser, out = setup(
        tmp_path, monkeypatch, responses=responses, target=target
    )
    if mutate is not None:
        mutate(opts, nav, lister, previewer, committer, chooser)
    named.run_named_definition_revision(**opts)
    return out.getvalue(), (nav, lister, previewer, committer, chooser)


def test_success_writes_one_revision_without_freezing_or_selecting(
    tmp_path, monkeypatch
):
    text, (nav, lister, preview, commit, _) = execute(tmp_path, monkeypatch)
    assert "revision recorded (created)" in text
    assert "No ReportingSnapshot was frozen or selected" in text
    assert "No official district/SIS Grade" in text
    assert DEFINITION not in text and BEFORE not in text
    assert commit.call_count == 1
    assert preview.call_count == 2
    assert preview.call_args.args[0:3] == (tmp_path, CLASS, DEFINITION)
    assert preview.call_args.args[5] == AcademicPeriodRef(YEAR, PERIOD)
    nav.session.select_student.assert_not_called()


def test_blank_title_keeps_existing_while_changing_purpose(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        previewer.return_value = make_plan(
            title="Existing Progress Report", purpose="New assessment focus"
        )

    out, st = execute(
        tmp_path,
        monkeypatch,
        responses=("", "New assessment focus", "review", "teacher-7", "WRITE", ""),
        mutate=change,
    )
    assert "revision recorded" in out
    assert st[2].call_args.args[3] == "Existing Progress Report"


def test_blank_purpose_keeps_existing_while_changing_title(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        previewer.return_value = make_plan(
            title="Revised Progress Report", purpose="Current classroom evidence"
        )

    out, st = execute(
        tmp_path,
        monkeypatch,
        responses=("Revised Progress Report", "", "review", "teacher-7", "WRITE", ""),
        mutate=change,
    )
    assert "revision recorded" in out
    assert st[2].call_args.args[4] == "Current classroom evidence"


def test_both_blanks_do_not_author_a_pointless_revision(tmp_path, monkeypatch):
    out, (_, _, preview, commit, _) = execute(
        tmp_path, monkeypatch, responses=("", "", "")
    )
    assert "No title or purpose change" in out
    preview.assert_not_called()
    commit.assert_not_called()


def test_cancel_at_write_preserves_immutable_history(tmp_path, monkeypatch):
    out, (_, _, preview, commit, _) = execute(
        tmp_path,
        monkeypatch,
        responses=(
            "Revised Progress Report",
            "New assessment focus",
            "review",
            "teacher-7",
            "",
            "",
        ),
    )
    assert "Canceled" in out
    assert preview.call_count == 1
    commit.assert_not_called()


def test_missing_teacher_attribution_fails_closed(tmp_path, monkeypatch):
    out, (_, _, preview, commit, _) = execute(
        tmp_path,
        monkeypatch,
        responses=("Revised Progress Report", "New assessment focus", "review", "", ""),
    )
    assert "Teacher attribution is unavailable" in out
    preview.assert_not_called()
    commit.assert_not_called()


def test_cancel_definition_selection_never_previews(tmp_path, monkeypatch):
    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, target=False)
    assert out == ""
    preview.assert_not_called()
    commit.assert_not_called()


def test_wrong_period_definition_is_not_available(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        lister.return_value = (original(period_id="mp2"),)
        chooser.side_effect = lambda **kw: kw["catalog"].options(
            scope="report_definition", selected={"class": CLASS}
        )[0]

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "could not be prepared safely" in out
    preview.assert_not_called()
    commit.assert_not_called()


def test_stale_class_blocks_before_preview(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        nav.current_class.return_value = SimpleNamespace(
            workspace=tmp_path, class_id="different", school_year=YEAR
        )

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    preview.assert_not_called()
    commit.assert_not_called()


def test_stale_period_blocks_before_preview(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        nav.current_period.return_value = None

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    preview.assert_not_called()
    commit.assert_not_called()


def test_stale_definition_change_at_input_blocks_write(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        reads = 0

        def value(_root, _cid):
            nonlocal reads
            reads += 1
            return (original(revision=4),) if reads >= 4 else (original(),)

        lister.side_effect = value

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_candidate_wrong_revision_is_rejected(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        previewer.return_value = make_plan(revision=5)

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_candidate_wrong_teacher_is_rejected(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        previewer.return_value = make_plan(actor="different-actor")

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_candidate_wrong_period_is_rejected(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        plan = make_plan()
        plan = replace(plan, period_id="mp2")
        previewer.return_value = plan

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_candidate_sha_mismatch_is_rejected(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        plan = make_plan()
        plan = replace(plan, definition_sha256="0" * 64)
        previewer.return_value = plan

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_preview_change_after_confirmation_stops_before_write(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        first = make_plan()
        alternate = make_plan(when=WHEN.replace(minute=1))
        previewer.side_effect = [first, alternate]

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "changed" in out.lower()
    commit.assert_not_called()


def test_commit_failure_reports_uncertain_without_internal_path(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        committer.side_effect = RuntimeError("/private/roster/data")

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "write outcome could not be verified" in out
    assert "/private/" not in out
    commit.assert_called_once()


def test_postcommit_read_failure_reports_uncertain(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        committer.side_effect = lambda *_args: "created"

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "write outcome is uncertain" in out
    commit.assert_called_once()


def test_unknown_committer_disposition_is_uncertain(tmp_path, monkeypatch):
    def change(opts, nav, lister, previewer, committer, chooser):
        committer.side_effect = lambda *_args: "unknown"

    out, (_, _, preview, commit, _) = execute(tmp_path, monkeypatch, mutate=change)
    assert "write outcome is uncertain" in out
    commit.assert_called_once()


@pytest.mark.parametrize("signal", (ReturnToMainMenu, QuitPDS))
def test_core_navigation_exceptions_propagate(tmp_path, monkeypatch, signal):
    def change(opts, nav, lister, previewer, committer, chooser):
        monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))

    opts, nav, lister, preview, commit, chooser, out = setup(tmp_path, monkeypatch)
    change(opts, nav, lister, preview, commit, chooser)
    with pytest.raises(signal):
        named.run_named_definition_revision(**opts)
    commit.assert_not_called()


def test_no_raw_id_prompt_sites_and_no_selection_or_freeze_calls():
    text = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Teacher actor ID: ")' not in text
    assert "select_reporting_snapshot(" not in text
    assert "commit_reporting_snapshot_freeze_preview(" not in text
    assert "write_reporting_definition_revision(" not in text


def test_existing_advanced_and_named_routes_not_renumbered():
    source = Path(__file__).resolve().parents[1] / "meridian/menu_snapshots.py"
    text = source.read_text(encoding="utf-8")
    assert "9. Browse reporting definitions by name" in text
    assert "10. Revise an existing reporting definition by name" in text
    assert "Advanced: Freeze a ReportingSnapshot (build-request JSON)" in text
    match = re.search(r"Please choose 1-(\d+), B, M, or Q\.", text)
    assert match is not None and int(match.group(1)) >= 10
    assert "Please choose 1-6, B, M, or Q." in text
