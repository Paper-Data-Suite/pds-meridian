"""#123 Slice 10D: name-based, read-only saved Planning Preview diagnostics."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_diagnostics as named

CLASS = "class_2"
YEAR = "2026-2027"
PREVIEW = "gsp_" + "a" * 64
PREVIEW_SHA = "b" * 64
DERIVATION = "gsd_" + "c" * 64
DERIVATION_SHA = "d" * 64
POLICY_SHA = "e" * 64
REVIEW_SHA = "f" * 64


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


def projection(*, selected=True):
    return SimpleNamespace(
        class_id=CLASS,
        preview_reference=SimpleNamespace(
            class_id=CLASS, preview_id=PREVIEW, preview_sha256=PREVIEW_SHA
        ),
        derivation_reference=SimpleNamespace(
            class_id=CLASS,
            derivation_id=DERIVATION,
            derivation_sha256=DERIVATION_SHA,
        ),
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
        live_currentness=SimpleNamespace(state="current"),
        coverage=SimpleNamespace(
            roster_student_count=29,
            contributing_student_count=25,
            noncontributing_student_count=4,
        ),
        band_summaries=tuple(
            SimpleNamespace(band=i, label=f"Band {i}", student_count=n)
            for i, n in ((1, 11), (2, 10), (3, 4))
        ),
        diagnostics=(
            SimpleNamespace(
                severity="warning", diagnostic_id="diag_1", message="Partial coverage"
            ),
        ),
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
            decision="accepted_for_export" if selected else None,
            applicability=(SimpleNamespace(status="stale") if selected else None),
        ),
    )


def setup(tmp_path, monkeypatch, *, answers=("B",), selected=True):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    chosen_summary = (
        summary()
        if selected
        else summary(selected_review_revision=None, selected_review_sha256=None)
    )
    chosen = chosen_summary.choice()
    catalog = MagicMock()
    catalog.inspect.return_value = chosen_summary
    picker = MagicMock(return_value=chosen)
    reader = MagicMock(return_value=projection(selected=selected))
    monkeypatch.setattr(named, "_class", lambda *a, **k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", picker)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=chosen))
    responses = iter(answers)

    def get_input(prompt=""):
        return next(responses)

    output = StringIO()
    args = dict(
        navigation=navigation,
        diagnostics_projector=reader,
        input_fn=get_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        preview_catalog=catalog,
    )
    return args, output, reader, catalog, navigation, picker


def test_named_preview_explains_without_raw_id_entry(tmp_path, monkeypatch):
    args, output, reader, _, _, picker = setup(tmp_path, monkeypatch)
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_called_once_with(tmp_path, CLASS, "policy_1", PREVIEW, PREVIEW_SHA)
    assert "Reading Progress Groups" in output.getvalue()
    assert "25 contributing" in output.getvalue()
    assert "Partial coverage" in output.getvalue()
    assert "accepted for export" in output.getvalue()
    assert "Review applicability: stale" in output.getvalue()
    assert PREVIEW not in output.getvalue()
    assert PREVIEW_SHA not in output.getvalue()
    assert picker.call_args.kwargs["scope"] == "planning_preview_review"


def test_technical_provenance_is_opt_in(tmp_path, monkeypatch):
    args, output, reader, _, _, _ = setup(tmp_path, monkeypatch, answers=("t", "", "B"))
    named.run_named_planning_preview_diagnostics(**args)
    assert f"preview_sha256: {PREVIEW_SHA}" in output.getvalue()
    assert f"selected_review_sha256: {REVIEW_SHA}" in output.getvalue()
    reader.assert_called_once()


@pytest.mark.parametrize("stage", ("class", "preview"))
def test_cancel_before_projection(tmp_path, monkeypatch, stage):
    args, _, reader, _, _, picker = setup(tmp_path, monkeypatch)
    if stage == "class":
        monkeypatch.setattr(named, "_class", lambda *a, **k: None)
    else:
        picker.return_value = None
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("workspace", Path("/elsewhere")),
        ("class_id", "wrong"),
        ("school_year", "2025-2026"),
    ),
)
def test_class_changed_before_projection_blocks(tmp_path, monkeypatch, field, value):
    args, output, reader, _, nav, _ = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=value if field == "workspace" else tmp_path,
        class_id=value if field == "class_id" else CLASS,
        school_year=value if field == "school_year" else YEAR,
    )
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize(
    "field,value",
    (
        ("preview_sha256", "0" * 64),
        ("selected_review_sha256", "0" * 64),
        ("selected_review_revision", 4),
        ("school_year", "2025-2026"),
    ),
)
def test_selection_change_blocks_before_read(tmp_path, monkeypatch, field, value):
    args, output, reader, catalog, _, _ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(**{field: value})
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize("field", ("derivation_sha256", "policy_sha256"))
def test_nested_provenance_change_is_caught_by_projection(tmp_path, monkeypatch, field):
    args, output, reader, catalog, _, _ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(**{field: "0" * 64})
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_called_once()
    assert "Partial coverage" not in output.getvalue()


@pytest.mark.parametrize(
    "section,field,value",
    (
        ("preview_reference", "preview_sha256", "0" * 64),
        ("preview_reference", "preview_id", "other"),
        ("derivation_reference", "derivation_id", "other"),
        ("derivation_reference", "derivation_sha256", "0" * 64),
        ("policy_reference", "policy_id", "wrong"),
        ("policy_reference", "policy_revision", 4),
        ("policy_reference", "policy_sha256", "0" * 64),
        (None, "policy_title", "Other policy"),
        (None, "school_year", "2025-2026"),
        (None, "period_id", "mp2"),
        (None, "calendar_revision", 3),
        (None, "standard_id", "OTHER"),
        (None, "dimension_id", "different"),
        (None, "band_count", 4),
        ("coverage", "roster_student_count", 30),
        ("coverage", "contributing_student_count", 24),
        ("live_currentness", "state", "invalid"),
        ("review_status", "decision", "unverified"),
        ("review_status", "selected_review_reference", None),
    ),
)
def test_mismatched_projection_never_displays_diagnostics(
    tmp_path, monkeypatch, section, field, value
):
    args, output, reader, _, _, _ = setup(tmp_path, monkeypatch)
    item = reader.return_value
    setattr(getattr(item, section) if section else item, field, value)
    named.run_named_planning_preview_diagnostics(**args)
    assert "Partial coverage" not in output.getvalue()
    assert (
        "could not be verified" in output.getvalue().lower()
        or "changed" in output.getvalue().lower()
    )


def test_inconsistent_band_distribution_blocks(tmp_path, monkeypatch):
    args, output, _, catalog, _, _ = setup(tmp_path, monkeypatch)
    args["diagnostics_projector"].return_value.band_summaries = (
        SimpleNamespace(band=1, label="Band 1", student_count=25),
        SimpleNamespace(band=1, label="Band 1 duplicate", student_count=0),
        SimpleNamespace(band=3, label="Band 3", student_count=0),
    )
    named.run_named_planning_preview_diagnostics(**args)
    assert "Partial coverage" not in output.getvalue()
    catalog.inspect.assert_called()


def test_no_selected_review_is_not_treated_as_approval(tmp_path, monkeypatch):
    args, output, _, _, _, _ = setup(tmp_path, monkeypatch, selected=False)
    named.run_named_planning_preview_diagnostics(**args)
    assert "Selected teacher review: none" in output.getvalue()
    assert "accepted for export" not in output.getvalue()


def test_review_becomes_selected_during_read_blocks(tmp_path, monkeypatch):
    args, output, reader, catalog, _, _ = setup(tmp_path, monkeypatch, selected=False)
    original = summary(selected_review_revision=None, selected_review_sha256=None)
    catalog.inspect.side_effect = [original, original, summary()]
    named.run_named_planning_preview_diagnostics(**args)
    reader.assert_called_once()
    assert "Partial coverage" not in output.getvalue()


def test_class_changed_during_projection_blocks_display(tmp_path, monkeypatch):
    args, output, reader, _, nav, _ = setup(tmp_path, monkeypatch)
    before = nav.current_class.return_value

    def change(*_args):
        nav.current_class.return_value = SimpleNamespace(
            workspace=tmp_path, class_id="another_class", school_year=YEAR
        )
        return projection()

    reader.side_effect = change
    named.run_named_planning_preview_diagnostics(**args)
    assert before.class_id == CLASS
    assert "Partial coverage" not in output.getvalue()


def test_reader_error_redacted(tmp_path, monkeypatch):
    args, output, reader, _, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("confidential student answer marker")
    named.run_named_planning_preview_diagnostics(**args)
    assert "confidential student answer marker" not in output.getvalue()
    assert "could not be verified" in output.getvalue()


@pytest.mark.parametrize("exception", (QuitPDS, ReturnToMainMenu))
def test_navigation_propagates(tmp_path, monkeypatch, exception):
    args, _, _, _, _, _ = setup(tmp_path, monkeypatch)

    def input_fn(prompt=""):
        raise exception

    args["input_fn"] = input_fn
    with pytest.raises(exception):
        named.run_named_planning_preview_diagnostics(**args)


def test_menu_adopts_named_path_without_removing_advanced():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"11. Review Planning Preview diagnostics by name"' in source
    assert "run_named_planning_preview_diagnostics(" in source
    assert '"4. Advanced: Review preview and diagnostics"' in source
    assert '"4. Review preview and diagnostics"' in source
    assert any(
        f'"Please choose 1-{last}, B, M, or Q."' in source for last in range(11, 100)
    )
    assert '"Please choose 1-7, B, M, or Q."' in source


def test_named_controller_does_not_ask_for_technical_identifiers_or_write():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Preview ID',
        'read_choice(input_fn, "Planning preview sha256',
        "commit_planning_signal",
        "write_grouping_signal_preview(",
        "select_grouping_signal_review_revision(",
    ):
        assert forbidden not in source
