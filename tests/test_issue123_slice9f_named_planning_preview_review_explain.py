"""#123 Slice 9F: named read-only Planning Preview/selected Review explanation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_preview_review as named

CLASS = "english_12_pd2"
PREVIEW = "gsp_" + "a" * 64
PREVIEW_SHA = "b" * 64
DERIVATION = "gsd_" + "c" * 64
DERIVATION_SHA = "d" * 64
POLICY_SHA = "e" * 64
REVIEW_SHA = "f" * 64


def summary(**updates):
    data = dict(
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        title="Reading Progress Groups",
        period_label="Marking Period 1",
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        roster_count=29,
        selected_review_revision=2,
        selected_review_sha256=REVIEW_SHA,
    )
    data.update(updates)
    return named.PlanningPreviewSummary(**data)


def explanation(**updates):
    data = dict(
        title="Planning Preview / Review Explanation",
        lines=(
            "Policy: Reading Progress Groups",
            "Academic Period: 2026-2027 / mp1",
            "Standard: RL.TS.11-12.4",
            "Dimension: readiness",
            "Path state: selected review ready",
            "Live currentness: current",
            "Selected review: accepted for export",
            "Coverage: 22 contributing, 7 noncontributing",
            "Export eligible: yes",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"preview_id: {PREVIEW}",
            f"preview_sha256: {PREVIEW_SHA}",
            f"derivation_id: {DERIVATION}",
            f"derivation_sha256: {DERIVATION_SHA}",
            "policy_id: policy_1",
            "policy_revision: 3",
            f"policy_sha256: {POLICY_SHA}",
            "selected_review_revision: 2",
            f"selected_review_sha256: {REVIEW_SHA}",
        ),
    )
    data.update(updates)
    return SimpleNamespace(**data)


def setup(tmp_path, monkeypatch, *, answers=("",)):
    navigation = MagicMock()
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year="2026-2027")
    navigation.current_class.return_value = scope
    options = MagicMock()
    options.inspect.return_value = summary()
    options.options.return_value = (summary().choice(),)
    class_catalog = MagicMock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **_kw: summary().choice()
    )
    verify = MagicMock()
    monkeypatch.setattr(named, "_current_choice", verify)
    reader = MagicMock(return_value=explanation())
    iterator = iter(answers)

    def read_input(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(iterator)

    output = StringIO()
    args = dict(
        navigation=navigation,
        planning_preview_explainer=reader,
        input_fn=read_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=class_catalog,
        preview_catalog=options,
    )
    return args, navigation, options, reader, verify, output


def test_named_path_reads_once_without_raw_identifiers(tmp_path, monkeypatch):
    args, _, _, reader, _, output = setup(tmp_path, monkeypatch)
    named.run_named_planning_preview_review_explanation(**args)
    text = output.getvalue()
    assert "Reading Progress Groups" in text
    assert "Marking Period 1" in text
    assert "22 contributing" in text
    assert "Export eligible: yes" in text
    assert PREVIEW not in text
    assert PREVIEW_SHA not in text
    assert REVIEW_SHA not in text
    reader.assert_called_once_with(tmp_path, CLASS, PREVIEW)


def test_technical_view_requires_explicit_t(tmp_path, monkeypatch):
    args, _, _, reader, _, output = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_planning_preview_review_explanation(**args)
    assert "selected_review_sha256:" in output.getvalue()
    assert PREVIEW in output.getvalue()
    reader.assert_called_once()


@pytest.mark.parametrize("step", ["class", "preview"])
def test_cancellation_never_calls_reader(tmp_path, monkeypatch, step):
    args, _, _, reader, _, _ = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    else:
        monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: None)
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_not_called()


def test_wrong_verified_class_stops_before_read(tmp_path, monkeypatch):
    args, navigation, _, reader, _, output = setup(tmp_path, monkeypatch)
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="different", school_year="2026-2027"
    )
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_choice_witness_change_stops_before_read(tmp_path, monkeypatch):
    args, _, catalog, reader, _, output = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(preview_sha256="0" * 64)
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_review_pointer_change_stops_before_read(tmp_path, monkeypatch):
    args, _, catalog, reader, _, output = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(selected_review_revision=3)
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_class_change_after_read_blocks_display(tmp_path, monkeypatch):
    args, navigation, _, reader, _, output = setup(tmp_path, monkeypatch)
    current = navigation.current_class.return_value
    navigation.current_class.side_effect = [current, current, None]
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_called_once()
    assert "Coverage: 22" not in output.getvalue()


def test_review_change_after_read_blocks_display(tmp_path, monkeypatch):
    args, _, catalog, reader, _, output = setup(tmp_path, monkeypatch)
    good = summary()
    bad = summary(selected_review_sha256="0" * 64)
    catalog.inspect.side_effect = [good, bad]
    named.run_named_planning_preview_review_explanation(**args)
    reader.assert_called_once()
    assert "Coverage: 22" not in output.getvalue()


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Different"},
        {"lines": ("Policy: Other",)},
        {"lines": ("Student: sensitive",) * 9},
        {"technical_lines": ("class_id: other",)},
        {"technical_lines": ()},
        {
            "technical_lines": tuple(
                "selected_review_revision: 3"
                if s == "selected_review_revision: 2"
                else s
                for s in explanation().technical_lines
            )
        },
        {
            "technical_lines": tuple(
                "preview_sha256: " + "0" * 64
                if s == f"preview_sha256: {PREVIEW_SHA}"
                else s
                for s in explanation().technical_lines
            )
        },
        {"lines": (*explanation().lines[:8], "Export eligible: perhaps")},
    ],
)
def test_wrong_explanation_fails_closed(tmp_path, monkeypatch, change):
    args, _, _, reader, _, output = setup(tmp_path, monkeypatch)
    reader.return_value = explanation(**change)
    named.run_named_planning_preview_review_explanation(**args)
    assert "Coverage: 22" not in output.getvalue()
    assert "changed" in output.getvalue()


def test_no_selected_review_is_a_valid_read_only_state(tmp_path, monkeypatch):
    args, _, catalog, reader, _, output = setup(tmp_path, monkeypatch)
    current = summary(selected_review_revision=None, selected_review_sha256=None)
    catalog.inspect.return_value = current
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: current.choice())
    reader.return_value = explanation(
        lines=(
            *explanation().lines[:6],
            "Selected review: none selected",
            *explanation().lines[7:],
        ),
        technical_lines=tuple(
            "selected_review_revision: none"
            if x == "selected_review_revision: 2"
            else "selected_review_sha256: none"
            if x == f"selected_review_sha256: {REVIEW_SHA}"
            else x
            for x in explanation().technical_lines
        ),
    )
    named.run_named_planning_preview_review_explanation(**args)
    assert "none selected" in output.getvalue()


def test_error_redacts_private_diagnostics(tmp_path, monkeypatch):
    args, _, _, reader, _, output = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("private/path/roster.txt")
    named.run_named_planning_preview_review_explanation(**args)
    assert "private/path" not in output.getvalue()
    assert "could not be verified" in output.getvalue()


@pytest.mark.parametrize("exc", [QuitPDS, ReturnToMainMenu])
def test_navigation_errors_propagate(tmp_path, monkeypatch, exc):
    args, _, _, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = exc
    with pytest.raises(exc):
        named.run_named_planning_preview_review_explanation(**args)


def test_summary_choice_does_not_expose_opaque_identity():
    choice = summary().choice()
    assert choice.identity == (PREVIEW,)
    assert PREVIEW not in choice.display
    assert PREVIEW_SHA not in choice.display
    assert REVIEW_SHA not in choice.display


def test_unselected_summary_has_no_review_hash():
    choice = summary(
        selected_review_revision=None, selected_review_sha256=None
    ).choice()
    assert "no selected review" in choice.display
    assert "none:none" in (choice.witness or "")


def test_catalog_scope_and_limit(tmp_path):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    catalog = named.PlanningPreviewChoiceCatalog(navigation)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="different", selected={"class": CLASS})
    catalog.readers = named.PlanningPreviewReaders(lister=lambda *_a: (PREVIEW,) * 201)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_preview_review", selected={"class": CLASS})


def test_catalog_does_not_guess_another_school_year(tmp_path, monkeypatch):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    catalog = named.PlanningPreviewChoiceCatalog(navigation)
    monkeypatch.setattr(
        named.PlanningPreviewChoiceCatalog,
        "inspect",
        lambda *_a: summary(school_year="2025-2026"),
    )
    catalog.readers = named.PlanningPreviewReaders(lister=lambda *_a: (PREVIEW,))
    assert (
        catalog.options(scope="planning_preview_review", selected={"class": CLASS})
        == ()
    )


def test_preview_storage_and_derivation_witness_in_catalog(tmp_path):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    stored = SimpleNamespace(
        snapshot=SimpleNamespace(
            preview_id=PREVIEW,
            derivation_reference=SimpleNamespace(
                class_id=CLASS,
                derivation_id=DERIVATION,
                derivation_sha256=DERIVATION_SHA,
            ),
            policy_reference=SimpleNamespace(
                policy_id="policy_1", policy_revision=3, policy_sha256=POLICY_SHA
            ),
            roster_basis=SimpleNamespace(student_ids=("s1", "s2")),
            derivation_calculation_fingerprint="z" * 64,
            dimension_id="readiness",
            band_count=4,
            student_rows=("s1", "s2"),
            policy_title="Reading Progress Groups",
            academic_basis=SimpleNamespace(
                target_period=SimpleNamespace(
                    period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
                    calendar_revision=7,
                ),
                standard_id="RL.TS.11-12.4",
            ),
            coverage=SimpleNamespace(roster_student_count=2),
        ),
        reference=SimpleNamespace(
            class_id=CLASS, preview_id=PREVIEW, preview_sha256=PREVIEW_SHA
        ),
        preview_sha256=PREVIEW_SHA,
    )
    derivation = SimpleNamespace(
        reference=stored.snapshot.derivation_reference,
        snapshot=SimpleNamespace(
            policy_reference=stored.snapshot.policy_reference,
            roster_basis=stored.snapshot.roster_basis,
            calculation_fingerprint="z" * 64,
            dimension_id="readiness",
            band_count=4,
            student_derivations=("s1", "s2"),
        ),
    )
    derivation_summary = SimpleNamespace(
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        title="Reading Progress Groups",
        period_label="Marking Period 1",
        school_year="2026-2027",
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        student_count=2,
    )
    deps = named.PlanningPreviewReaders(
        lister=lambda *_a: (PREVIEW,),
        preview_loader=lambda *_a: stored,
        derivation_loader=lambda *_a: derivation,
        selected_review_loader=lambda *_a: None,
    )
    catalog = named.PlanningPreviewChoiceCatalog(navigation, deps, MagicMock())
    catalog.derivation_catalog.inspect.return_value = derivation_summary
    options = catalog.options(
        scope="planning_preview_review", selected={"class": CLASS}
    )
    assert len(options) == 1
    assert options[0].identity == (PREVIEW,)
    assert "Reading Progress Groups" in options[0].display
    assert "no selected review" in options[0].display


def test_review_pointer_witness_in_catalog(tmp_path):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    option = summary().choice()
    assert REVIEW_SHA in (option.witness or "")
    assert REVIEW_SHA not in option.display


def test_new_menu_route_is_append_only():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert '"14. Explain a saved Planning Preview / Review by name"' in source
    assert "run_named_planning_preview_review_explanation(" in source
    assert '"13. Explain a saved Planning Derivation by name"' in source
    assert '"6. Planning preview / review"' in source
    assert '"6. Advanced: Planning preview / review"' in source
    assert any(f'"Please choose 1-{n}, B, M, or Q."' in source for n in range(14, 100))
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_existing_explainer_exposes_selected_review_pointer_provenance():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    part = source.split("def _planning_preview(", 1)[1].split(
        "def _planning_export(", 1
    )[0]
    assert "selected_review_revision:" in part
    assert "selected_review_sha256:" in part


def test_controller_has_no_raw_inputs_or_mutations():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Preview ID',
        'read_choice(input_fn, "Review revision',
        "commit_planning",
        "select_current_",
        "write_grouping_signal",
    ):
        assert forbidden not in source
