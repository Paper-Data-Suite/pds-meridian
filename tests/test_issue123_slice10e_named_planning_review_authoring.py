"""#123 Slice 10E: named, deliberate, immutable Planning Review authoring."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_review_authoring as named

CLASS = "class_2"
YEAR = "2026-2027"
PREVIEW = "gsp_" + "a" * 64
PREVIEW_SHA = "b" * 64
DERIVATION = "gsd_" + "c" * 64
DERIVATION_SHA = "d" * 64
POLICY_SHA = "e" * 64
REVIEW_SHA = "f" * 64
WHEN = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def summary(**changes):
    values = dict(
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        title="Reading Progress Groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=3,
        roster_count=29,
        selected_review_revision=2,
        selected_review_sha256=REVIEW_SHA,
    )
    values.update(changes)
    return named.PlanningPreviewSummary(**values)


def projection(*, selected=True, state="current", warnings=True, blocking=False):
    derivation_ref = SimpleNamespace(
        class_id=CLASS,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
    )
    diagnostics = []
    if warnings:
        diagnostics.append(
            SimpleNamespace(
                severity="warning", diagnostic_id="warn_1", message="Partial coverage"
            )
        )
    if blocking:
        diagnostics.append(
            SimpleNamespace(
                severity="blocking",
                diagnostic_id="block_1",
                message="No eligible result",
            )
        )
    return SimpleNamespace(
        class_id=CLASS,
        preview_reference=SimpleNamespace(
            class_id=CLASS, preview_id=PREVIEW, preview_sha256=PREVIEW_SHA
        ),
        derivation_reference=derivation_ref,
        policy_reference=SimpleNamespace(
            class_id=CLASS,
            policy_id="policy_1",
            policy_revision=3,
            policy_sha256=POLICY_SHA,
        ),
        policy_title="Reading Progress Groups",
        school_year=YEAR,
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=3,
        live_currentness=SimpleNamespace(
            state=state,
            current_derivation_reference=(
                derivation_ref if state == "current" else None
            ),
        ),
        coverage=SimpleNamespace(
            roster_student_count=29,
            contributing_student_count=25,
            noncontributing_student_count=4,
        ),
        band_summaries=tuple(
            SimpleNamespace(band=i, label=f"Band {i}", student_count=n)
            for i, n in ((1, 11), (2, 10), (3, 4))
        ),
        diagnostics=tuple(diagnostics),
        review_status=SimpleNamespace(
            selected_review_reference=(
                SimpleNamespace(
                    class_id=CLASS,
                    derivation_id=DERIVATION,
                    review_revision=2,
                    review_sha256=REVIEW_SHA,
                )
                if selected
                else None
            ),
            decision="rejected" if selected else None,
            applicability=(SimpleNamespace(status="current") if selected else None),
        ),
    )


def plan(proj, decision="accepted_for_export", acknowledgments=("warn_1",), **changes):
    candidate = SimpleNamespace(
        class_id=CLASS,
        preview_reference=proj.preview_reference,
        derivation_reference=proj.derivation_reference,
        decision=decision,
        acknowledged_warning_ids=acknowledgments,
        review_revision=3,
        supersedes_revision=2,
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_1"),
        reviewed_at=WHEN,
    )
    values = dict(
        projection=proj,
        candidate=candidate,
        class_id=CLASS,
        derivation_id=DERIVATION,
        review_revision=3,
        decision=decision,
        acknowledged_warning_ids=acknowledgments,
        actor_id="teacher_1",
        reviewed_at=WHEN,
        expected_current_review_revision=2,
        blocking_diagnostic_ids=tuple(
            sorted(
                d.diagnostic_id for d in proj.diagnostics if d.severity == "blocking"
            )
        ),
        warning_diagnostic_ids=tuple(
            sorted(d.diagnostic_id for d in proj.diagnostics if d.severity == "warning")
        ),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def result(authoring, **changes):
    values = dict(
        preview=authoring,
        review_revision=authoring.review_revision,
        decision=authoring.decision,
        write_disposition="created",
        review_sha256="9" * 64,
        selection_changed_during_write=False,
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def setup(
    tmp_path,
    monkeypatch,
    *,
    answers=("2", "teacher_1", "B"),
    selected=True,
    state="current",
    warnings=True,
    blocking=False,
):
    current = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav = MagicMock()
    nav.current_class.return_value = current
    item = (
        summary()
        if selected
        else summary(selected_review_revision=None, selected_review_sha256=None)
    )
    chosen = item.choice()
    catalog = MagicMock()
    catalog.inspect.return_value = item
    picker = MagicMock(return_value=chosen)
    project = projection(
        selected=selected, state=state, warnings=warnings, blocking=blocking
    )
    projector = MagicMock(return_value=project)
    preparer = MagicMock(side_effect=lambda *a: plan(project, a[5], a[6]))
    committer = MagicMock(side_effect=lambda root, p: result(p))
    monkeypatch.setattr(named, "_class", lambda *a, **k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", picker)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=chosen))
    answers_iter = iter(answers)
    prompts = []

    def input_fn(prompt=""):
        prompts.append(prompt)
        return next(answers_iter, "")

    output = StringIO()
    args = dict(
        navigation=nav,
        diagnostics_projector=projector,
        authoring_previewer=preparer,
        authoring_committer=committer,
        clock=lambda: WHEN,
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        preview_catalog=catalog,
    )
    return args, output, projector, preparer, committer, catalog, nav, picker, prompts


def run(args):
    named.run_named_planning_review_authoring(**args)


def test_accept_warnings_requires_ack_and_write(tmp_path, monkeypatch):
    args, output, projector, preparer, committer, _, _, picker, prompts = setup(
        tmp_path,
        monkeypatch,
        answers=("1", "ACK", "teacher_1", "WRITE", ""),
    )
    run(args)
    projector.assert_called_once_with(tmp_path, CLASS, "policy_1", PREVIEW, PREVIEW_SHA)
    assert preparer.call_args.args[5:9] == (
        "accepted_for_export",
        ("warn_1",),
        "teacher_1",
        WHEN,
    )
    committer.assert_called_once()
    assert "Planning Review Saved" in output.getvalue()
    assert "Saving did not select this review" in output.getvalue()
    assert "Teacher actor ID: " in prompts
    assert "Derivation ID: " not in prompts
    assert picker.call_args.kwargs["scope"] == "planning_preview_review"
    assert PREVIEW_SHA not in output.getvalue()


def test_reject_requires_no_warning_ack(tmp_path, monkeypatch):
    args, output, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("2", "teacher_1", "WRITE", "")
    )
    run(args)
    assert preparer.call_args.args[5:7] == ("rejected", ())
    committer.assert_called_once()
    assert "Warning acknowledgment:" not in output.getvalue()


def test_accept_without_warnings_skips_ack(tmp_path, monkeypatch):
    args, _, _, preparer, committer, *_ = setup(
        tmp_path,
        monkeypatch,
        answers=("1", "teacher_1", "WRITE", ""),
        warnings=False,
    )
    run(args)
    assert preparer.call_args.args[6] == ()
    committer.assert_called_once()


@pytest.mark.parametrize("answer", ("", "B", "3", "accept", "WRITE"))
def test_invalid_or_cancelled_decision_no_write(tmp_path, monkeypatch, answer):
    responses = (answer, "") if answer else (answer,)
    args, _, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=responses
    )
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize("ack", ("B", "no", "yes", "ack", ""))
def test_missing_explicit_warning_ack_never_prepares(tmp_path, monkeypatch, ack):
    args, _, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", ack)
    )
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize("state", ("stale", "blocked"))
def test_noncurrent_preview_cannot_be_accepted(tmp_path, monkeypatch, state):
    args, output, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, state=state, answers=("1", "")
    )
    run(args)
    assert "cannot currently be accepted" in output.getvalue()
    preparer.assert_not_called()
    committer.assert_not_called()


def test_blocking_diagnostic_blocks_accept(tmp_path, monkeypatch):
    args, _, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, blocking=True, answers=("1", "")
    )
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


def test_blocking_diagnostic_does_not_block_rejection(tmp_path, monkeypatch):
    args, _, _, preparer, committer, *_ = setup(
        tmp_path,
        monkeypatch,
        blocking=True,
        answers=("2", "teacher_1", "WRITE", ""),
    )
    run(args)
    assert preparer.call_args.args[5] == "rejected"
    committer.assert_called_once()


@pytest.mark.parametrize("answer", ("", "B", "write", "YES", "1", "ACK"))
def test_nonexact_write_confirmation_never_commits(tmp_path, monkeypatch, answer):
    responses = ("2", "teacher_1", answer) + (("",) if answer not in ("", "B") else ())
    args, output, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=responses
    )
    run(args)
    preparer.assert_called_once()
    committer.assert_not_called()
    assert "No teacher review was authored" in output.getvalue()


def test_technical_details_are_opt_in(tmp_path, monkeypatch):
    args, output, _, _, committer, *_ = setup(
        tmp_path,
        monkeypatch,
        answers=("2", "teacher_1", "T", "", "B"),
    )
    run(args)
    assert "preview_sha256:" in output.getvalue()
    assert "review_revision:" in output.getvalue()
    committer.assert_not_called()


@pytest.mark.parametrize("cancel", ("choice", "class"))
def test_cancel_before_read_no_action(tmp_path, monkeypatch, cancel):
    args, _, projector, preparer, committer, _, _, picker, _ = setup(
        tmp_path, monkeypatch
    )
    if cancel == "choice":
        picker.return_value = None
    else:
        monkeypatch.setattr(named, "_class", lambda *a, **kw: None)
    run(args)
    projector.assert_not_called()
    preparer.assert_not_called()
    committer.assert_not_called()


def test_class_changes_before_projection(tmp_path, monkeypatch):
    args, output, projector, preparer, committer, _, nav, *_ = setup(
        tmp_path, monkeypatch
    )
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="other_class", school_year=YEAR
    )
    run(args)
    assert "changed" in output.getvalue()
    projector.assert_not_called()
    preparer.assert_not_called()
    committer.assert_not_called()


def test_preview_changed_before_preparation(tmp_path, monkeypatch):
    args, output, _, preparer, committer, catalog, *_ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(preview_sha256="0" * 64)
    run(args)
    assert "changed" in output.getvalue()
    preparer.assert_not_called()
    committer.assert_not_called()


def test_selected_review_change_is_detected(tmp_path, monkeypatch):
    args, output, _, preparer, committer, catalog, *_ = setup(tmp_path, monkeypatch)
    catalog.inspect.side_effect = [
        summary(),
        summary(),
        summary(selected_review_revision=3, selected_review_sha256="1" * 64),
    ]
    run(args)
    assert "changed" in output.getvalue()
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("class_id", "other"),
        ("school_year", "2025-2026"),
        ("policy_title", "Wrong"),
        ("band_count", 4),
    ),
)
def test_injected_wrong_projection_never_previews(tmp_path, monkeypatch, field, value):
    args, output, projector, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    data = projection()
    setattr(data, field, value)
    projector.return_value = data
    run(args)
    assert "could not be saved" in output.getvalue() or "changed" in output.getvalue()
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("class_id", "other"),
        ("decision", "rejected"),
        ("review_revision", 4),
        ("expected_current_review_revision", 3),
        ("actor_id", "other"),
        ("acknowledged_warning_ids", ()),
        ("blocking_diagnostic_ids", ("block_1",)),
    ),
)
def test_bad_authoring_candidate_blocks_commit(tmp_path, monkeypatch, field, value):
    args, output, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "ACK", "teacher_1")
    )
    actual = preparer.side_effect
    preparer.side_effect = lambda *a: replace_preview(actual(*a), field, value)
    run(args)
    committer.assert_not_called()
    assert "could not be saved" in output.getvalue() or "changed" in output.getvalue()


def replace_preview(p, field, value):
    setattr(p, field, value)
    return p


def test_candidate_wrong_bound_reference_blocks(tmp_path, monkeypatch):
    args, _, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "ACK", "teacher_1")
    )
    initial = preparer.side_effect

    def corrupt(*a):
        p = initial(*a)
        p.candidate.preview_reference = SimpleNamespace(
            class_id=CLASS, preview_id="wrong", preview_sha256=PREVIEW_SHA
        )
        return p

    preparer.side_effect = corrupt
    run(args)
    committer.assert_not_called()


def test_class_changes_during_authoring_blocks_write(tmp_path, monkeypatch):
    args, _, _, preparer, committer, _, nav, *_ = setup(
        tmp_path, monkeypatch, answers=("2", "teacher_1")
    )
    saved = nav.current_class.return_value
    nav.current_class.side_effect = [saved] * 4 + [
        SimpleNamespace(workspace=tmp_path, class_id="other", school_year=YEAR)
    ]
    run(args)
    preparer.assert_called_once()
    committer.assert_not_called()


def test_authoring_error_redacted(tmp_path, monkeypatch):
    args, output, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("2", "teacher_1")
    )
    preparer.side_effect = RuntimeError("PRIVATE STUDENT SECRET")
    run(args)
    assert "PRIVATE STUDENT SECRET" not in output.getvalue()
    committer.assert_not_called()


def test_commit_failure_warns_about_possible_persist(tmp_path, monkeypatch):
    args, output, _, _, committer, *_ = setup(
        tmp_path,
        monkeypatch,
        answers=("2", "teacher_1", "WRITE"),
    )
    committer.side_effect = RuntimeError("PRIVATE DETAILS")
    run(args)
    assert "may have completed" in output.getvalue()
    assert "PRIVATE DETAILS" not in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    (
        ("review_revision", 7),
        ("decision", "rejected"),
        ("review_sha256", "BAD"),
        ("write_disposition", "bad"),
        ("selection_changed_during_write", True),
        ("review_selection_action", "selected"),
    ),
)
def test_result_mismatch_never_claims_success(tmp_path, monkeypatch, field, value):
    args, output, _, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "ACK", "teacher_1", "WRITE")
    )
    committer.side_effect = lambda root, p: result(p, **{field: value})
    run(args)
    assert "Planning Review Saved" not in output.getvalue()
    assert (
        "may have completed" in output.getvalue()
        or "review history" in output.getvalue()
    )


@pytest.mark.parametrize("error", (QuitPDS, ReturnToMainMenu))
def test_navigation_exceptions_propagate(tmp_path, monkeypatch, error):
    args, _, _, preparer, committer, *_ = setup(tmp_path, monkeypatch)

    def user_input(prompt=""):
        raise error

    args["input_fn"] = user_input
    with pytest.raises(error):
        run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


def test_menu_option_preserves_exact_legacy_route():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"12. Author Planning Review by preview name"' in source
    assert '"5. Advanced: Write teacher review"' in source
    assert '"5. Write teacher review"' in source
    assert "run_named_planning_review_authoring(" in source
    assert any(f'"Please choose 1-{i}, B, M, or Q."' in source for i in range(12, 100))
    assert '"Please choose 1-7, B, M, or Q."' in source


def test_controller_does_not_prompt_for_ids_or_write_side_effects():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for bad in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Planning preview ID',
        'read_choice(input_fn, "Planning preview sha256',
        'read_choice(input_fn, "Review revision',
        "write_grouping_signal_review(",
        "select_grouping_signal_review_revision(",
        "commit_planning_signal_core_export(",
    ):
        assert bad not in source
