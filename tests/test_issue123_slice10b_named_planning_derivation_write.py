"""#123 Slice 10B: exact named policy -> reviewed #38 derivation write."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_derivation_write as named

CLASS = "english_12_pd2"
POLICY = "private_policy_1"
YEAR = "2026-2027"
DIGEST = "a" * 64
FINGERPRINT = "b" * 64
DERIVATION = "gsd_" + "c" * 64


def summary(**changes):
    values = dict(
        policy_id=POLICY,
        policy_revision=3,
        policy_sha256=DIGEST,
        title="Reading progress groups",
        school_year=YEAR,
        period_label="Marking Period 1",
        period_id="mp1",
        calendar_revision=4,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        revised_at="2026-10-26T16:00:00+00:00",
    )
    values.update(changes)
    return named.PlanningReadinessPolicySummary(**values)


def readiness(**changes):
    values = dict(
        class_id=CLASS,
        policy_id=POLICY,
        policy=SimpleNamespace(
            reference=SimpleNamespace(
                class_id=CLASS,
                policy_id=POLICY,
                policy_revision=3,
                policy_sha256=DIGEST,
            ),
            title=summary().title,
            target_period=SimpleNamespace(
                period=SimpleNamespace(school_year=YEAR, period_id="mp1"),
                calendar_revision=4,
            ),
            standard_id=summary().standard_id,
            dimension_id="readiness",
            band_count=4,
        ),
        generation_status="generated",
        blocker_codes=(),
        roster_student_count=29,
        contributing_student_count=25,
        noncontributing_student_count=4,
        ready_for_derivation_persistence=True,
        candidate_derivation_id=DERIVATION,
        candidate_calculation_fingerprint=FINGERPRINT,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def preview(**changes):
    r = readiness()
    candidate = SimpleNamespace(
        class_id=CLASS,
        policy_reference=r.policy.reference,
        derivation_id=DERIVATION,
        calculation_fingerprint=FINGERPRINT,
    )
    values = dict(
        readiness=r,
        candidate=candidate,
        class_id=CLASS,
        policy_id=POLICY,
        derivation_id=DERIVATION,
        calculation_fingerprint=FINGERPRINT,
        roster_student_count=29,
        contributing_student_count=25,
        noncontributing_student_count=4,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def setup(tmp_path, monkeypatch, *, answers=("B",), ready=True):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav = MagicMock()
    nav.current_class.return_value = scope
    catalog = MagicMock()
    catalog.inspect.return_value = summary()
    selected = summary().choice()
    picker = MagicMock(return_value=selected)
    proj = readiness(
        ready_for_derivation_persistence=ready,
        generation_status="generated" if ready else "blocked",
        blocker_codes=() if ready else ("missing_selected_results",),
    )
    reader = MagicMock(return_value=proj)
    p = preview(
        readiness=proj,
        candidate=SimpleNamespace(
            class_id=CLASS,
            policy_reference=proj.policy.reference,
            derivation_id=DERIVATION,
            calculation_fingerprint=FINGERPRINT,
        ),
    )
    previewer = MagicMock(return_value=p)
    committer = MagicMock(
        return_value=SimpleNamespace(
            preview=p,
            derivation_id=DERIVATION,
            calculation_fingerprint=FINGERPRINT,
            write_disposition="created",
        )
    )
    monkeypatch.setattr(named, "_class", lambda *args, **kwargs: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", picker)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=selected))
    output = StringIO()
    requests = iter(answers)

    def input_fn(prompt=""):
        return next(requests)

    args = dict(
        navigation=nav,
        readiness_projector=reader,
        derivation_previewer=previewer,
        derivation_committer=committer,
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        policy_catalog=catalog,
    )
    return args, output, reader, previewer, committer, nav, catalog, picker


def test_write_requires_deliberate_confirmation(tmp_path, monkeypatch):
    args, output, reader, previewer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    named.run_named_planning_derivation_write(**args)
    reader.assert_called_once_with(tmp_path, CLASS, POLICY)
    previewer.assert_called_once()
    committer.assert_called_once()
    assert committer.call_args.args[0] == tmp_path
    assert "Save outcome: created" in output.getvalue()
    assert "Reading progress groups" in output.getvalue()
    assert "No Planning Preview, review, selection" in output.getvalue()
    assert DERIVATION not in output.getvalue()
    assert DIGEST not in output.getvalue()


@pytest.mark.parametrize("answer", ["", "B", "CANCEL", "write", "Y", "1", "SAVE", "NO"])
def test_no_write_without_exact_confirmation(tmp_path, monkeypatch, answer):
    args, _, reader, previewer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=(answer, "")
    )
    named.run_named_planning_derivation_write(**args)
    reader.assert_called_once()
    previewer.assert_called_once()
    committer.assert_not_called()


def test_technical_details_explicit_and_confirmation_remains_required(
    tmp_path, monkeypatch
):
    args, output, _, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("T", "", "B")
    )
    named.run_named_planning_derivation_write(**args)
    assert f"policy_sha256: {DIGEST}" in output.getvalue()
    assert f"derivation_id: {DERIVATION}" in output.getvalue()
    committer.assert_not_called()


@pytest.mark.parametrize("step", ["class", "policy"])
def test_cancel_before_readiness_does_not_prepare_write(tmp_path, monkeypatch, step):
    args, _, reader, previewer, committer, _, _, picker = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *a, **k: None)
    else:
        picker.return_value = None
    named.run_named_planning_derivation_write(**args)
    reader.assert_not_called()
    previewer.assert_not_called()
    committer.assert_not_called()


def test_blocked_readiness_never_previews_or_writes(tmp_path, monkeypatch):
    args, output, reader, previewer, committer, *_ = setup(
        tmp_path, monkeypatch, ready=False, answers=("",)
    )
    named.run_named_planning_derivation_write(**args)
    reader.assert_called_once()
    previewer.assert_not_called()
    committer.assert_not_called()
    assert "missing selected results" in output.getvalue()
    assert "Not Ready" in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "other"),
        ("policy_id", "other"),
        ("generation_status", "blocked"),
    ],
)
def test_wrong_readiness_never_previews(tmp_path, monkeypatch, field, value):
    args, output, _, previewer, committer, _, _, _ = setup(tmp_path, monkeypatch)
    args["readiness_projector"].return_value = readiness(**{field: value})
    named.run_named_planning_derivation_write(**args)
    previewer.assert_not_called()
    committer.assert_not_called()
    assert (
        "Reading progress groups" not in output.getvalue()
        or "changed" in output.getvalue()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "other"),
        ("policy_id", "other"),
        ("derivation_id", "other"),
        ("calculation_fingerprint", "other"),
        ("roster_student_count", 27),
        ("contributing_student_count", 30),
        ("noncontributing_student_count", -1),
    ],
)
def test_wrong_preview_blocks_confirmation(tmp_path, monkeypatch, field, value):
    args, _, _, previewer, committer, *_ = setup(tmp_path, monkeypatch)
    current = previewer.return_value
    setattr(current, field, value)
    named.run_named_planning_derivation_write(**args)
    committer.assert_not_called()


def test_wrong_candidate_policy_blocks_write(tmp_path, monkeypatch):
    args, _, _, previewer, committer, *_ = setup(tmp_path, monkeypatch)
    previewer.return_value.candidate.policy_reference = SimpleNamespace(policy_id="x")
    named.run_named_planning_derivation_write(**args)
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "other"),
        ("school_year", "2025-2026"),
    ],
)
def test_scope_change_before_readiness_blocks(tmp_path, monkeypatch, field, value):
    args, _, reader, _, committer, nav, _, _ = setup(tmp_path, monkeypatch)
    scope = nav.current_class.return_value
    nav.current_class.side_effect = [SimpleNamespace(**{**vars(scope), field: value})]
    named.run_named_planning_derivation_write(**args)
    reader.assert_not_called()
    committer.assert_not_called()


def test_scope_change_after_readiness_blocks_preview(tmp_path, monkeypatch):
    args, _, reader, previewer, committer, nav, *_ = setup(tmp_path, monkeypatch)
    scope = nav.current_class.return_value
    nav.current_class.side_effect = [
        scope,
        scope,
        SimpleNamespace(workspace=tmp_path, class_id="different", school_year=YEAR),
    ]
    named.run_named_planning_derivation_write(**args)
    reader.assert_called_once()
    previewer.assert_not_called()
    committer.assert_not_called()


def test_policy_witness_change_during_confirmation_blocks_commit(tmp_path, monkeypatch):
    args, _, _, _, committer, _, catalog, _ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    catalog.inspect.side_effect = [
        summary(),
        summary(),
        summary(),
        summary(policy_revision=4),
    ]
    named.run_named_planning_derivation_write(**args)
    committer.assert_not_called()


def test_commit_failure_does_not_show_success_or_exception(tmp_path, monkeypatch):
    args, output, _, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    committer.side_effect = RuntimeError("C:\\private\\student\\notes.pdf")
    named.run_named_planning_derivation_write(**args)
    assert "C:\\private" not in output.getvalue()
    assert "Save outcome" not in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("derivation_id", "different"),
        ("calculation_fingerprint", "bad"),
        ("write_disposition", "unknown"),
    ],
)
def test_result_mismatch_never_claims_saved(tmp_path, monkeypatch, field, value):
    args, output, _, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    setattr(committer.return_value, field, value)
    named.run_named_planning_derivation_write(**args)
    assert "Save outcome" not in output.getvalue()


@pytest.mark.parametrize("exception", [QuitPDS, ReturnToMainMenu])
def test_main_and_quit_propagate(tmp_path, monkeypatch, exception):
    args, _, _, _, committer, *_ = setup(tmp_path, monkeypatch)
    args["input_fn"] = MagicMock(side_effect=exception)
    with pytest.raises(exception):
        named.run_named_planning_derivation_write(**args)
    committer.assert_not_called()


def test_teacher_menu_additive_and_advanced_routes_preserved():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"8. Review Planning Signal readiness by policy name"' in source
    assert '"9. Save Planning Derivation by policy name"' in source
    assert "run_named_planning_derivation_write(" in source
    assert '"2. Advanced: Write exact derivation"' in source
    assert '"2. Write exact derivation"' in source
    assert any(f'"Please choose 1-{n}, B, M, or Q."' in source for n in range(9, 100))
    assert '"Please choose 1-7, B, M, or Q."' in source


def test_no_new_raw_id_prompts_or_ui_side_writes():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Grouping-signal policy ID',
        'read_choice(input_fn, "Derivation ID',
        "write_grouping_signal_derivation(",
        "select_grouping_signal_policy_revision(",
        "commit_planning_signal_core_export(",
    ):
        assert forbidden not in source
