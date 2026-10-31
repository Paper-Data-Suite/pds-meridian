"""#123 Slice 10C: named saved derivation -> deliberate exact #39 preview write."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_preview_write as named

CLASS = "english_12_pd2"
YEAR = "2026-2027"
POLICY = "private_policy_1"
POLICY_SHA = "a" * 64
DERIVATION = "gsd_" + "b" * 64
DERIVATION_SHA = "c" * 64
FINGERPRINT = "d" * 64
PREVIEW = "gsp_" + "e" * 64
PREVIEW_SHA = "f" * 64


def summary(**updates):
    values = dict(
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        title="Reading progress groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        student_count=29,
        policy_id=POLICY,
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        calculation_fingerprint=FINGERPRINT,
        revised_at="2026-10-26T16:00:00+00:00",
    )
    values.update(updates)
    return named.PlanningDerivationSummary(**values)


def preview(**updates):
    derivation_ref = SimpleNamespace(
        class_id=CLASS,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
    )
    policy_ref = SimpleNamespace(
        class_id=CLASS,
        policy_id=POLICY,
        policy_revision=3,
        policy_sha256=POLICY_SHA,
    )
    stored = SimpleNamespace(
        reference=derivation_ref,
        snapshot=SimpleNamespace(policy_reference=policy_ref),
    )
    values = dict(
        class_id=CLASS,
        policy_id=POLICY,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        derivation_reference=derivation_ref,
        policy_reference=policy_ref,
        calculation_fingerprint=FINGERPRINT,
        stored_derivation=stored,
        roster_student_count=29,
        contributing_student_count=25,
        noncontributing_student_count=4,
    )
    values.update(updates)
    return SimpleNamespace(**values)


def result(p, **updates):
    values = dict(
        preview=p,
        generation=SimpleNamespace(derivation_reference=p.derivation_reference),
        write_disposition="created",
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        preview_fingerprint="1" * 64,
        roster_student_count=29,
        contributing_student_count=25,
        noncontributing_student_count=4,
        currentness_state="current",
        warning_diagnostic_ids=(),
        blocking_diagnostic_ids=(),
        review_write_action="not_performed",
        review_selection_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )
    values.update(updates)
    return SimpleNamespace(**values)


def setup(tmp_path, monkeypatch, *, answers=("B",)):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    catalog = MagicMock()
    catalog.inspect.return_value = summary()
    chosen = summary().choice()
    picker = MagicMock(return_value=chosen)
    preparer = MagicMock(return_value=preview())
    committer = MagicMock(return_value=result(preparer.return_value))
    monkeypatch.setattr(named, "_class", lambda *a, **k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", picker)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=chosen))
    output = StringIO()
    values = iter(answers)

    def input_fn(prompt=""):
        return next(values)

    args = dict(
        navigation=navigation,
        preview_preparer=preparer,
        preview_committer=committer,
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        derivation_catalog=catalog,
    )
    return args, output, preparer, committer, navigation, catalog, picker


def test_named_preview_write_requires_exact_write(tmp_path, monkeypatch):
    args, output, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    named.run_named_planning_preview_write(**args)
    preparer.assert_called_once_with(
        tmp_path, CLASS, POLICY, DERIVATION, DERIVATION_SHA
    )
    committer.assert_called_once()
    assert committer.call_args.args[0] == tmp_path
    assert "Save outcome: created" in output.getvalue()
    assert "Reading progress groups" in output.getvalue()
    assert "No teacher review, selection, Core export" in output.getvalue()
    assert DERIVATION not in output.getvalue()
    assert DERIVATION_SHA not in output.getvalue()


@pytest.mark.parametrize("answer", ["", "B", "CANCEL", "write", "Y", "1", "SAVE", "NO"])
def test_confirmation_never_implicit(tmp_path, monkeypatch, answer):
    args, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=(answer, "")
    )
    named.run_named_planning_preview_write(**args)
    preparer.assert_called_once()
    committer.assert_not_called()


def test_technical_details_opt_in_does_not_write(tmp_path, monkeypatch):
    args, output, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("T", "", "B")
    )
    named.run_named_planning_preview_write(**args)
    assert f"derivation_sha256: {DERIVATION_SHA}" in output.getvalue()
    assert f"policy_sha256: {POLICY_SHA}" in output.getvalue()
    committer.assert_not_called()


@pytest.mark.parametrize("step", ["class", "derivation"])
def test_cancellation_before_prepare(tmp_path, monkeypatch, step):
    args, _, preparer, committer, _, _, picker = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *a, **k: None)
    else:
        picker.return_value = None
    named.run_named_planning_preview_write(**args)
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "different"),
        ("policy_id", "different"),
        ("derivation_id", "other"),
        ("derivation_sha256", "0" * 64),
        ("calculation_fingerprint", "bad"),
        ("roster_student_count", 32),
        ("contributing_student_count", 30),
        ("noncontributing_student_count", -1),
        ("noncontributing_student_count", True),
    ],
)
def test_wrong_prepared_preview_blocks_write(tmp_path, monkeypatch, field, value):
    args, _, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    setattr(preparer.return_value, field, value)
    named.run_named_planning_preview_write(**args)
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("derivation_id", "other"),
        ("derivation_sha256", "9" * 64),
        ("class_id", "other"),
    ],
)
def test_wrong_reference_blocks_write(tmp_path, monkeypatch, field, value):
    args, _, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    setattr(preparer.return_value.derivation_reference, field, value)
    named.run_named_planning_preview_write(**args)
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_id", "different"),
        ("policy_revision", 99),
        ("policy_sha256", "0" * 64),
    ],
)
def test_wrong_policy_provenance_blocks_write(tmp_path, monkeypatch, field, value):
    args, _, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    setattr(preparer.return_value.policy_reference, field, value)
    named.run_named_planning_preview_write(**args)
    committer.assert_not_called()


def test_changed_class_before_prepare(tmp_path, monkeypatch):
    args, _, preparer, committer, navigation, *_ = setup(tmp_path, monkeypatch)
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="other", school_year=YEAR
    )
    named.run_named_planning_preview_write(**args)
    preparer.assert_not_called()
    committer.assert_not_called()


def test_selected_derivation_changed_before_commit(tmp_path, monkeypatch):
    args, output, _, committer, _, catalog, _ = setup(
        tmp_path, monkeypatch, answers=("WRITE", "")
    )
    catalog.inspect.side_effect = [
        summary(),
        summary(),
        summary(),
        summary(derivation_sha256="8" * 64),
    ]
    named.run_named_planning_preview_write(**args)
    committer.assert_not_called()
    assert "changed" in output.getvalue()


def test_selection_changes_after_preparer_blocks_confirmation(tmp_path, monkeypatch):
    args, _, preparer, committer, _, catalog, _ = setup(tmp_path, monkeypatch)
    catalog.inspect.side_effect = [summary(), summary(policy_revision=4)]
    named.run_named_planning_preview_write(**args)
    preparer.assert_called_once()
    committer.assert_not_called()


def test_preparer_error_redacted_and_no_write_claim(tmp_path, monkeypatch):
    args, output, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    preparer.side_effect = RuntimeError("C:\\private\\student\\record.pdf")
    named.run_named_planning_preview_write(**args)
    committer.assert_not_called()
    assert "C:\\private" not in output.getvalue()
    assert "Save outcome" not in output.getvalue()
    assert "No save was requested" in output.getvalue()


def test_committer_error_acknowledges_possible_write(tmp_path, monkeypatch):
    args, output, _, committer, *_ = setup(tmp_path, monkeypatch, answers=("WRITE", ""))
    committer.side_effect = RuntimeError("C:\\private\\student\\record.pdf")
    named.run_named_planning_preview_write(**args)
    assert "C:\\private" not in output.getvalue()
    assert "may have completed" in output.getvalue()
    assert "Save outcome" not in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("write_disposition", "unknown"),
        ("preview_id", "x"),
        ("preview_sha256", "wrong"),
        ("preview_fingerprint", "bad"),
        ("contributing_student_count", 30),
        ("review_write_action", "done"),
        ("core_export_action", "created"),
    ],
)
def test_inconsistent_save_result_never_reports_success(
    tmp_path, monkeypatch, field, value
):
    args, output, _, committer, *_ = setup(tmp_path, monkeypatch, answers=("WRITE", ""))
    setattr(committer.return_value, field, value)
    named.run_named_planning_preview_write(**args)
    assert "Save outcome" not in output.getvalue()
    assert "Check saved previews" in output.getvalue()


@pytest.mark.parametrize("error", [QuitPDS, ReturnToMainMenu])
def test_core_navigation_propagates(tmp_path, monkeypatch, error):
    args, _, _, committer, *_ = setup(tmp_path, monkeypatch)
    args["input_fn"] = MagicMock(side_effect=error)
    with pytest.raises(error):
        named.run_named_planning_preview_write(**args)
    committer.assert_not_called()


def test_menu_append_and_old_routes_preserved():
    text = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"10. Save Planning Preview by derivation name"' in text
    assert "run_named_planning_preview_write(" in text
    assert '"9. Save Planning Derivation by policy name"' in text
    assert '"3. Advanced: Write planning preview"' in text
    assert '"3. Write planning preview"' in text
    assert any(f'"Please choose 1-{n}, B, M, or Q."' in text for n in range(10, 100))
    assert '"Please choose 1-7, B, M, or Q."' in text


def test_no_raw_prompts_or_ui_side_persistence():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for token in (
        'read_choice(input_fn, "Derivation ID',
        'read_choice(input_fn, "Planning preview sha256',
        'read_choice(input_fn, "Class ID',
        "write_grouping_signal_preview(",
        "generate_planning_signal_preview(",
        "select_grouping_signal_review_revision(",
        "commit_planning_signal_core_export(",
    ):
        assert token not in source
