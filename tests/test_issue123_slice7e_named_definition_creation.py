"""#123 Slice 7E: teacher-first creation of new immutable report definitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_definition_create as named
from meridian.menu_snapshots import ReportingDefinitionPlan
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
    reporting_definition_reference,
)

CLASS = "canonical-class"
YEAR = "2026-2027"
PERIOD = "mp1"
DID = "report-" + "a" * 32
WHEN = datetime(2026, 10, 25, tzinfo=UTC)


def answers(*values: str):
    prompts: list[str] = []
    stream = iter(values)

    def read(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(stream)

    return read, prompts


def definition_plan(
    *,
    class_id: str = CLASS,
    definition_id: str = DID,
    title: str = "Course Report",
    purpose: str = "End of marking period review",
    period: AcademicPeriodRef | None = None,
    actor: str = "saved-teacher",
    rationale: str | None = "for conferences",
    revised_at: datetime = WHEN,
) -> ReportingDefinitionPlan:
    ref = period or AcademicPeriodRef(YEAR, PERIOD)
    candidate = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=class_id,
        definition_id=definition_id,
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose=purpose,
        title=title,
        target_period=ref,
        intended_audience="teacher",
        actor=ReportingActor("teacher", actor),
        rationale=rationale,
        revised_at=revised_at,
    )
    digest = reporting_definition_reference(candidate).definition_sha256
    return ReportingDefinitionPlan(
        class_id=class_id,
        definition_id=definition_id,
        definition_revision=1,
        definition_sha256=digest,
        title=title,
        purpose=purpose,
        school_year=ref.school_year,
        period_id=ref.period_id,
        actor_id=actor,
        rationale=rationale,
        candidate=candidate,
    )


def latest(plan: ReportingDefinitionPlan) -> named.NamedDefinitionItem:
    return named.NamedDefinitionItem(
        definition_id=plan.definition_id,
        revision=plan.definition_revision,
        sha256=plan.definition_sha256,
        title=plan.title,
        purpose=plan.purpose,
        school_year=plan.school_year,
        period_id=plan.period_id,
        revised_at=WHEN.isoformat(),
    )


def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, typed=None):
    chosen = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
    )
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=1,
        label="Marking Period One",
    )
    choice = SimpleNamespace(identity=(PERIOD,), label=period.label)
    nav = MagicMock()
    nav.current_class.return_value = chosen
    nav.current_period.return_value = period
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "_marking_period", lambda *_a, **_k: (period, choice))
    monkeypatch.setattr(named, "load_teacher_choices", lambda *_a, **_k: (choice,))
    read, prompts = answers(
        *(
            typed
            if typed is not None
            else (
                "Course Report",
                "End of marking period review",
                "for conferences",
                "saved-teacher",
                "WRITE",
                "",
            )
        )
    )
    plan = definition_plan()
    state: list[named.NamedDefinitionItem] = []
    lister = MagicMock(side_effect=lambda *_a: tuple(state))
    previewer = MagicMock(return_value=plan)

    def write(_root: Path, proposed: ReportingDefinitionPlan) -> str:
        state.append(latest(proposed))
        return "created"

    committer = MagicMock(side_effect=write)
    out = StringIO()
    opts = dict(
        navigation=nav,
        definition_previewer=previewer,
        definition_committer=committer,
        clock=lambda: WHEN,
        input_fn=read,
        output=out,
        clear_fn=lambda: None,
        definition_lister=lister,
        identity_factory=lambda: DID,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return opts, out, prompts, nav, lister, previewer, committer, state, plan, period


def run(tmp_path, monkeypatch, *, change=None, typed=None):
    values = setup(tmp_path, monkeypatch, typed=typed)
    opts, out, *_ = values
    if change is not None:
        change(*values)
    named.run_named_definition_creation(**opts)
    return out.getvalue(), values


def test_creates_first_revision_without_typing_identifier(tmp_path, monkeypatch):
    text, values = run(tmp_path, monkeypatch)
    _, _, prompts, nav, lister, previewer, committer, state, _, _ = values
    assert "New Reporting Definition created" in text
    assert "No ReportingSnapshot was frozen or selected" in text
    assert DID not in text
    assert not any("definition id" in prompt.casefold() for prompt in prompts)
    assert not any("class id" in prompt.casefold() for prompt in prompts)
    assert len(state) == 1 and state[0].revision == 1
    assert previewer.call_count == 2
    assert committer.call_count == 1
    assert lister.call_count >= 4
    nav.session.select_student.assert_not_called()


def test_uses_exact_period_and_teacher_identity(tmp_path, monkeypatch):
    _, values = run(tmp_path, monkeypatch)
    _, _, _, _, _, previewer, committer, *_ = values
    args = previewer.call_args.args
    assert args[1:5] == (CLASS, DID, "Course Report", "End of marking period review")
    assert args[5] == AcademicPeriodRef(YEAR, PERIOD)
    assert args[6:] == ("saved-teacher", "for conferences", WHEN)
    committer.assert_called_once()


def test_blank_title_cancels_without_write(tmp_path, monkeypatch):
    out, values = run(tmp_path, monkeypatch, typed=("",))
    assert "created" not in out
    values[6].assert_not_called()
    values[5].assert_not_called()


def test_blank_purpose_cancels_without_write(tmp_path, monkeypatch):
    out, values = run(tmp_path, monkeypatch, typed=("Some Title", ""))
    assert "created" not in out
    values[6].assert_not_called()


def test_blank_actor_stops_without_write(tmp_path, monkeypatch):
    out, values = run(
        tmp_path,
        monkeypatch,
        typed=("Course Report", "End of marking period review", "", "", ""),
    )
    assert "Teacher attribution unavailable" in out
    values[6].assert_not_called()


def test_cancel_after_review_never_commits(tmp_path, monkeypatch):
    out, values = run(
        tmp_path,
        monkeypatch,
        typed=(
            "Course Report",
            "End of marking period review",
            "for conferences",
            "saved-teacher",
            "",
            "",
        ),
    )
    assert "Canceled" in out
    values[6].assert_not_called()


def test_invalid_generated_id_blocks_preview(tmp_path, monkeypatch):
    def change(opts, *_):
        opts["identity_factory"] = lambda: "unsafe/relative-path"

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[5].assert_not_called()


def test_generated_identity_collision_blocks_preview(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, _commit, state, plan, *_):
        state.append(latest(plan))

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[5].assert_not_called()


def test_duplicate_report_title_same_period_blocks_preview(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, _commit, state, plan, *_):
        state.append(replace(latest(plan), definition_id="other-family"))

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[5].assert_not_called()


def test_same_title_other_period_does_not_block(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, _commit, state, plan, *_):
        state.append(
            replace(latest(plan), definition_id="other-family", period_id="mp2")
        )

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "New Reporting Definition created" in out
    values[6].assert_called_once()


@pytest.mark.parametrize(
    "field,new",
    [
        ("definition_id", "wrong-family"),
        ("definition_revision", 2),
        ("title", "Different Title"),
        ("purpose", "Different Purpose"),
        ("definition_sha256", "0" * 64),
    ],
)
def test_bad_preview_rejected_before_commit(tmp_path, monkeypatch, field, new):
    def change(opts, _out, _prompts, _nav, _lister, previewer, *_):
        previewer.return_value = replace(previewer.return_value, **{field: new})

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[6].assert_not_called()


def test_scope_change_blocks_before_commit(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, nav, *_):
        original = nav.current_period.return_value
        nav.current_period.side_effect = [original, original, original, None]

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[6].assert_not_called()


def test_preview_changed_after_confirmation_blocks(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, previewer, *_):
        original = previewer.return_value
        previewer.side_effect = [original, replace(original, title="Altered")]

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[6].assert_not_called()


def test_write_exception_has_uncertain_status(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, committer, *_):
        committer.side_effect = RuntimeError("private /student/path")

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "may be stored" in out
    assert "/student/" not in out
    values[6].assert_called_once()


def test_disposition_existing_reports_uncertain(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, committer, *_):
        committer.side_effect = lambda *_a: "existing"

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "uncertain" in out
    values[6].assert_called_once()


def test_unverified_write_reports_uncertain(tmp_path, monkeypatch):
    def change(opts, _out, _prompts, _nav, _lister, _prev, committer, *_):
        committer.side_effect = lambda *_a: "created"

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "uncertain" in out
    values[6].assert_called_once()


def test_catalog_too_large_blocks(tmp_path, monkeypatch):
    def change(opts, *_):
        opts["definition_lister"] = lambda *_a: (object(),) * 201

    out, values = run(tmp_path, monkeypatch, change=change)
    assert "No definition write was attempted" in out
    values[6].assert_not_called()


@pytest.mark.parametrize("navigation_exception", [ReturnToMainMenu, QuitPDS])
def test_navigation_exceptions_propagate(tmp_path, monkeypatch, navigation_exception):
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=navigation_exception))
    nav = MagicMock()
    with pytest.raises(navigation_exception):
        named.run_named_definition_creation(
            navigation=nav,
            definition_previewer=MagicMock(),
            definition_committer=MagicMock(),
            clock=lambda: WHEN,
            input_fn=lambda _prompt: "",
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_no_new_literal_raw_identifier_prompt_sites():
    source = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Teacher actor ID:' not in source
    assert 'read_choice(input_fn, "Definition ID:' not in source
    assert "select_reporting_snapshot(" not in source
    assert "write_reporting_definition_revision(" not in source
