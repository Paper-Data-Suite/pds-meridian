"""#123 Slice 9G: named read-only historical Core Planning Export explanation."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_export as named

CLASS = "english_12_pd2"
YEAR = "2026-2027"
SIGNAL = "signal_hidden"
DERIVATION = "gsd_" + "1" * 64
PREVIEW = "gsp_" + "2" * 64
CORE_SHA = "a" * 64
RECEIPT_SHA = "b" * 64
DERIVATION_SHA = "c" * 64
PREVIEW_SHA = "d" * 64
REVIEW_SHA = "e" * 64


def summary(**updates):
    data = dict(
        signal_set_id=SIGNAL,
        core_signal_digest=CORE_SHA,
        receipt_sha256=RECEIPT_SHA,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        review_revision=2,
        review_sha256=REVIEW_SHA,
        title="MP1 Readiness Groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        exported_count=22,
        omitted_count=7,
        review_decision="accepted_for_export",
        preview_currentness="current",
        created_at="2026-10-26T11:00:00+00:00",
    )
    data.update(updates)
    return named.PlanningExportSummary(**data)


def explanation(**updates):
    initial = dict(
        title="Planning Export Explanation",
        lines=(
            f"Signal set: {SIGNAL}",
            "Dimension: readiness",
            "Bands: 4",
            "Students exported: 22",
            "Students omitted: 7",
            "Review decision: accepted for export",
            "Preview currentness: current",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            "core_contract: grouping_signal_set_v1",
            f"core_signal_digest: {CORE_SHA}",
            f"receipt_sha256: {RECEIPT_SHA}",
            f"derivation_id: {DERIVATION}",
            f"derivation_sha256: {DERIVATION_SHA}",
            f"preview_id: {PREVIEW}",
            f"preview_sha256: {PREVIEW_SHA}",
            "review_revision: 2",
            f"review_sha256: {REVIEW_SHA}",
        ),
    )
    initial.update(updates)
    return SimpleNamespace(**initial)


def setup(tmp_path, monkeypatch, *, answers=("",)):
    navigation = MagicMock()
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation.current_class.return_value = verified
    catalog = MagicMock()
    chosen = summary().choice()
    catalog.inspect.return_value = summary()
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: chosen)
    monkeypatch.setattr(named, "_current_choice", MagicMock())
    reader = MagicMock(return_value=explanation())
    answers_iter = iter(answers)

    def read_input(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(answers_iter)

    output = StringIO()
    args = dict(
        navigation=navigation,
        planning_export_explainer=reader,
        input_fn=read_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        export_catalog=catalog,
    )
    return args, output, reader, catalog, navigation


def test_read_only_named_export_uses_exact_reader(tmp_path, monkeypatch):
    args, output, reader, _, _ = setup(tmp_path, monkeypatch)
    named.run_named_planning_export_explanation(**args)
    reader.assert_called_once_with(tmp_path, CLASS, SIGNAL)
    text = output.getvalue()
    assert "MP1 Readiness Groups" in text
    assert "Marking Period 1" in text
    assert "22 exported" not in text  # Counts remain teacher-readable.
    assert "Students exported: 22" in text
    assert "Students omitted: 7" in text
    assert "Review decision: accepted for export" in text
    assert SIGNAL not in text
    assert CORE_SHA not in text
    assert "historical export" in text


def test_technical_details_only_with_t(tmp_path, monkeypatch):
    args, output, _, _, _ = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_planning_export_explanation(**args)
    text = output.getvalue()
    assert f"signal_set_id: {SIGNAL}" in text
    assert f"receipt_sha256: {RECEIPT_SHA}" in text
    assert f"review_sha256: {REVIEW_SHA}" in text


def test_back_before_selection_never_loads_export(tmp_path, monkeypatch):
    args, _, reader, _, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: None)
    named.run_named_planning_export_explanation(**args)
    reader.assert_not_called()


def test_back_at_class_never_loads_export(tmp_path, monkeypatch):
    args, _, reader, _, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    named.run_named_planning_export_explanation(**args)
    reader.assert_not_called()


@pytest.mark.parametrize("field", ["workspace", "class_id", "school_year"])
def test_class_changed_before_read_blocks(tmp_path, monkeypatch, field):
    args, output, reader, _, navigation = setup(tmp_path, monkeypatch)
    change = dict(
        workspace=Path("/tmp/other"), class_id="other", school_year="2000-2001"
    )
    scope = vars(navigation.current_class.return_value).copy()
    scope[field] = change[field]
    navigation.current_class.return_value = SimpleNamespace(**scope)
    named.run_named_planning_export_explanation(**args)
    reader.assert_not_called()
    assert "saved Planning Export changed" in output.getvalue()


@pytest.mark.parametrize(
    "field",
    [
        "receipt_sha256",
        "core_signal_digest",
        "review_sha256",
        "review_revision",
        "school_year",
    ],
)
def test_catalog_witness_change_blocks_before_read(tmp_path, monkeypatch, field):
    args, output, reader, catalog, _ = setup(tmp_path, monkeypatch)
    change = "f" * 64 if field.endswith("sha256") or field.endswith("digest") else 9
    if field == "school_year":
        change = "2025-2026"
    catalog.inspect.return_value = summary(**{field: change})
    named.run_named_planning_export_explanation(**args)
    reader.assert_not_called()
    assert "saved Planning Export changed" in output.getvalue()


@pytest.mark.parametrize(
    "mutate",
    [
        {"title": "Wrong Explanation"},
        {"lines": ("Signal set: OTHER",) + explanation().lines[1:]},
        {
            "lines": (
                *explanation().lines[:3],
                "Students exported: 23",
                *explanation().lines[4:],
            )
        },
        {
            "lines": (
                *explanation().lines[:4],
                "Students omitted: 8",
                *explanation().lines[5:],
            )
        },
        {
            "lines": (
                *explanation().lines[:5],
                "Review decision: rejected",
                *explanation().lines[6:],
            )
        },
        {"technical_lines": ("class_id: wrong",) + explanation().technical_lines[1:]},
        {
            "technical_lines": (
                *explanation().technical_lines[:2],
                "core_signal_digest: BAD",
                *explanation().technical_lines[3:],
            )
        },
        {
            "technical_lines": (
                *explanation().technical_lines[:3],
                "receipt_sha256: BAD",
                *explanation().technical_lines[4:],
            )
        },
        {
            "technical_lines": (
                *explanation().technical_lines[:6],
                "preview_id: BAD",
                *explanation().technical_lines[7:],
            )
        },
        {
            "technical_lines": (
                *explanation().technical_lines[:-1],
                "review_sha256: BAD",
            )
        },
        {"technical_lines": explanation().technical_lines + (f"class_id: {CLASS}",)},
        {"lines": list(explanation().lines)},
    ],
)
def test_wrong_explanation_never_displays_result(tmp_path, monkeypatch, mutate):
    args, output, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.return_value = explanation(**mutate)
    named.run_named_planning_export_explanation(**args)
    assert (
        "could not be verified safely" in output.getvalue()
        or "changed" in output.getvalue()
    )
    assert "Students exported: 22" not in output.getvalue()


def test_class_changes_during_read_blocks_display(tmp_path, monkeypatch):
    args, output, reader, _, navigation = setup(tmp_path, monkeypatch)
    initial = navigation.current_class.return_value
    navigation.current_class.side_effect = [initial, initial, None]
    named.run_named_planning_export_explanation(**args)
    reader.assert_called_once()
    assert "Students exported: 22" not in output.getvalue()


def test_export_changes_after_reader_blocks_display(tmp_path, monkeypatch):
    args, output, reader, catalog, _ = setup(tmp_path, monkeypatch)
    baseline = summary()
    catalog.inspect.side_effect = [baseline, replace(baseline, receipt_sha256="f" * 64)]
    named.run_named_planning_export_explanation(**args)
    reader.assert_called_once()
    assert "Students exported: 22" not in output.getvalue()


def test_reader_error_does_not_expose_private_diagnostics(tmp_path, monkeypatch):
    args, output, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("C:\\SECRET\\roster\\private.pdf")
    named.run_named_planning_export_explanation(**args)
    assert "SECRET" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


@pytest.mark.parametrize("error", (QuitPDS, ReturnToMainMenu))
def test_core_navigation_propagates(tmp_path, monkeypatch, error):
    args, _, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = error
    with pytest.raises(error):
        named.run_named_planning_export_explanation(**args)


def test_human_choice_omits_opaque_id_and_hash():
    choice = summary().choice()
    assert choice.label == "MP1 Readiness Groups"
    assert "Marking Period 1" in choice.display
    assert SIGNAL not in choice.display
    assert CORE_SHA not in choice.display
    assert choice.witness is not None
    assert choice.witness.startswith("sha256:")
    assert len(choice.witness) == 71
    assert CORE_SHA not in choice.witness
    assert RECEIPT_SHA not in choice.witness


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("signal_set_id", "different_signal"),
        ("core_signal_digest", "1" * 64),
        ("receipt_sha256", "2" * 64),
        ("derivation_sha256", "3" * 64),
        ("preview_sha256", "4" * 64),
        ("review_revision", 3),
        ("review_sha256", "5" * 64),
    ],
)
def test_compact_witness_binds_every_exact_dependency(field, replacement):
    original = summary().choice().witness
    updated = summary(**{field: replacement}).choice().witness
    assert original is not None
    assert updated is not None
    assert updated.startswith("sha256:")
    assert len(updated) == 71
    assert original != updated


def test_wrong_scope_or_class_fails_before_inventory(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    readers = named.PlanningExportReaders(lister=MagicMock(return_value=()))
    catalog = named.PlanningExportChoiceCatalog(nav, readers)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="other", selected={"class": CLASS})
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_export", selected={"class": "wrong"})
    readers.lister.assert_not_called()


def test_more_than_200_fails_closed(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    readers = named.PlanningExportReaders(
        lister=lambda _r, _c: tuple(f"id{i}" for i in range(201))
    )
    catalog = named.PlanningExportChoiceCatalog(nav, readers)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_export", selected={"class": CLASS})


def test_other_producer_signal_is_not_a_meridian_export(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    source = SimpleNamespace(kind="teacher_authored", module_id=None)
    core = SimpleNamespace(signal=SimpleNamespace(source=source))
    reader = named.PlanningExportReaders(
        lister=lambda _r, _c: (SIGNAL,), signal_loader=MagicMock(return_value=core)
    )
    cat = named.PlanningExportChoiceCatalog(nav, reader)
    assert cat.options(scope="planning_export", selected={"class": CLASS}) == ()


def test_malformed_meridian_export_blocks_inventory(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    source = SimpleNamespace(kind="module_generated", module_id="meridian")
    core = SimpleNamespace(signal=SimpleNamespace(source=source))
    readers = named.PlanningExportReaders(
        lister=lambda _r, _c: (SIGNAL,), signal_loader=MagicMock(return_value=core)
    )
    cat = named.PlanningExportChoiceCatalog(nav, readers)
    with pytest.raises(named.TeacherChoiceUnavailable):
        cat.options(scope="planning_export", selected={"class": CLASS})


def storage_fixtures(tmp_path):
    """Inject complete synthetic verified reads without touching academic state."""
    from datetime import UTC, datetime

    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav = MagicMock()
    nav.current_class.return_value = scope
    derivation_ref = SimpleNamespace(
        derivation_id=DERIVATION, derivation_sha256=DERIVATION_SHA
    )
    preview_ref = SimpleNamespace(preview_id=PREVIEW, preview_sha256=PREVIEW_SHA)
    review_ref = SimpleNamespace(
        class_id=CLASS,
        derivation_id=DERIVATION,
        review_revision=2,
        review_sha256=REVIEW_SHA,
    )
    source = SimpleNamespace(
        kind="module_generated",
        module_id="meridian",
        snapshot_id=DERIVATION,
        snapshot_digest_algorithm="sha256",
        snapshot_digest=DERIVATION_SHA,
    )
    signal = SimpleNamespace(
        class_id=CLASS,
        signal_set_id=SIGNAL,
        source=source,
        student_bands=tuple(object() for _ in range(22)),
        created_at=datetime(2026, 10, 26, 11, 0, tzinfo=UTC),
    )
    core = SimpleNamespace(signal=signal, digest_algorithm="sha256", digest=CORE_SHA)
    receipt = SimpleNamespace(
        class_id=CLASS,
        signal_set_id=SIGNAL,
        core_contract="grouping_signal_set_v1",
        core_digest_algorithm="sha256",
        core_signal_digest=CORE_SHA,
        derivation_reference=derivation_ref,
        preview_reference=preview_ref,
        review_reference=review_ref,
    )
    stored_receipt = SimpleNamespace(
        receipt=receipt,
        receipt_sha256=RECEIPT_SHA,
        reference=SimpleNamespace(
            class_id=CLASS, signal_set_id=SIGNAL, receipt_sha256=RECEIPT_SHA
        ),
    )
    derived = SimpleNamespace(
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        school_year=YEAR,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256="f" * 64,
        dimension_id="readiness",
        band_count=4,
        student_count=29,
        title="MP1 Readiness Groups",
        period_label="Marking Period 1",
        standard_id="RL.TS.11-12.4",
    )
    preview = SimpleNamespace(
        reference=preview_ref,
        snapshot=SimpleNamespace(
            derivation_reference=derivation_ref,
            policy_reference=SimpleNamespace(
                policy_id="policy_1", policy_revision=3, policy_sha256="f" * 64
            ),
            dimension_id="readiness",
            band_count=4,
            student_rows=tuple(object() for _ in range(29)),
            currentness=SimpleNamespace(state="current"),
        ),
    )
    review = SimpleNamespace(
        reference=SimpleNamespace(
            class_id=CLASS,
            derivation_id=DERIVATION,
            review_revision=2,
            review_sha256=REVIEW_SHA,
        ),
        review=SimpleNamespace(
            derivation_reference=derivation_ref,
            preview_reference=preview_ref,
            decision="accepted_for_export",
        ),
    )
    readers = named.PlanningExportReaders(
        lister=MagicMock(return_value=(SIGNAL,)),
        signal_loader=MagicMock(return_value=core),
        receipt_loader=MagicMock(return_value=stored_receipt),
        preview_loader=MagicMock(return_value=preview),
        review_loader=MagicMock(return_value=review),
    )
    derived_catalog = MagicMock()
    derived_catalog.inspect.return_value = derived
    catalog = named.PlanningExportChoiceCatalog(nav, readers, derived_catalog)
    return catalog, readers, derived_catalog, nav


def test_catalog_binds_core_receipt_review_by_exact_revision(tmp_path):
    catalog, readers, _, _ = storage_fixtures(tmp_path)
    result = catalog.inspect(tmp_path, CLASS, SIGNAL)
    assert result == summary()
    readers.review_loader.assert_called_once_with(tmp_path, CLASS, DERIVATION, 2)
    assert readers.receipt_loader.call_count == 1


def test_catalog_lists_verified_meridian_exports(tmp_path):
    catalog, _, _, _ = storage_fixtures(tmp_path)
    choices = catalog.options(scope="planning_export", selected={"class": CLASS})
    assert len(choices) == 1
    assert choices[0] == summary().choice()


@pytest.mark.parametrize(
    "target, field, mismatch",
    [
        ("core", "digest", "f" * 64),
        ("core_source", "snapshot_digest", "f" * 64),
        ("core_source", "module_id", "other"),
        ("receipt", "core_signal_digest", "f" * 64),
        ("receipt", "core_contract", "other"),
        ("stored_receipt", "receipt_sha256", "f" * 64),
        ("derived", "derivation_sha256", "f" * 64),
        ("preview_snapshot", "band_count", 8),
        ("preview_snapshot", "dimension_id", "unrelated"),
        ("review_ref", "review_sha256", "f" * 64),
        ("review", "preview_reference", SimpleNamespace(preview_id="wrong")),
    ],
)
def test_catalog_rejects_changed_exact_dependency(tmp_path, target, field, mismatch):
    catalog, readers, derived_catalog, _ = storage_fixtures(tmp_path)
    targets = {
        "core": readers.signal_loader.return_value,
        "core_source": readers.signal_loader.return_value.signal.source,
        "receipt": readers.receipt_loader.return_value.receipt,
        "stored_receipt": readers.receipt_loader.return_value,
        "derived": derived_catalog.inspect.return_value,
        "preview_snapshot": readers.preview_loader.return_value.snapshot,
        "review_ref": readers.review_loader.return_value.reference,
        "review": readers.review_loader.return_value.review,
    }
    setattr(targets[target], field, mismatch)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.inspect(tmp_path, CLASS, SIGNAL)


def test_catalog_rejects_cohort_mismatch(tmp_path):
    catalog, readers, _, _ = storage_fixtures(tmp_path)
    readers.signal_loader.return_value.signal.student_bands = tuple(range(30))
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.inspect(tmp_path, CLASS, SIGNAL)


def test_catalog_never_uses_a_newly_selected_review(tmp_path):
    catalog, readers, _, _ = storage_fixtures(tmp_path)
    catalog.inspect(tmp_path, CLASS, SIGNAL)
    readers.review_loader.assert_called_once_with(tmp_path, CLASS, DERIVATION, 2)
    assert "load_current_grouping_signal_review" not in Path(named.__file__).read_text()


def test_route_additive_and_legacy_routes_preserved():
    code = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text()
    assert '"15. Explain a saved Planning Export by name"' in code
    assert "run_named_planning_export_explanation(" in code
    assert '"14. Explain a saved Planning Preview / Review by name"' in code
    assert '"13. Explain a saved Planning Derivation by name"' in code
    assert '"7. Advanced: Planning export"' in code
    assert '"7. Planning export"' in code
    assert any(f'"Please choose 1-{i}, B, M, or Q."' in code for i in range(15, 100))
    assert '"Please choose 1-8, B, M, or Q."' in code


def test_no_raw_id_prompts_or_writes():
    source = Path(named.__file__).read_text()
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Signal Set ID',
        'read_choice(input_fn, "Export ID',
        "commit_planning",
        "write_grouping_signal",
        "select_grouping_signal",
        "get_current_grouping_signal_review",
    ):
        assert forbidden not in source
