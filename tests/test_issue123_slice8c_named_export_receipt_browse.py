"""#123 Slice 8C: read-only named local ExportReceipt inspection."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_export_receipts as named
from meridian.teacher_navigation_choices import (
    TeacherChoiceUnavailable,
    load_teacher_choices,
)

CLASS = "opaque-class"
RECEIPT = "opaque-export-id"
DIGEST = "a" * 64


def receipt(**changes):
    values = dict(
        export_id=RECEIPT,
        receipt_sha256=DIGEST,
        payload_sha256="b" * 64,
        snapshot_id="opaque-snapshot",
        profile_id="opaque-profile",
        profile_revision=3,
        row_count=29,
        destination_kind="file",
        destination_name="period-grades.csv",
        actor_id="teacher-identity",
        exported_at="2026-10-25T14:00:00+00:00",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def make(tmp_path, monkeypatch, *, chosen=True):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    lister = MagicMock(return_value=(RECEIPT,))
    loader = MagicMock(return_value=receipt())
    cat = named.NamedExportReceiptCatalog(nav, lister, loader)
    choice = load_teacher_choices(
        cat, scope="export_receipt", selected={"class": CLASS}
    )[0]
    loader.reset_mock()
    lister.reset_mock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "select_teacher_choice", lambda **_k: choice if chosen else None
    )
    out = StringIO()
    args = dict(
        navigation=nav,
        receipt_lister=lister,
        receipt_loader=loader,
        input_fn=lambda _prompt: "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        receipt_catalog=cat,
    )
    return args, nav, lister, loader, cat, choice, out


def test_named_receipt_catalog_hides_exact_ids(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    choice = load_teacher_choices(
        named.NamedExportReceiptCatalog(
            nav, lambda *_a: (RECEIPT,), lambda *_a: receipt()
        ),
        scope="export_receipt",
        selected={"class": CLASS},
    )[0]
    assert "period-grades.csv" in choice.display
    assert "29 rows" in choice.display
    assert "2026-10-25" in choice.display
    assert "not proof of external import" in choice.display
    assert RECEIPT not in choice.display
    assert DIGEST not in choice.display
    assert choice.identity == (RECEIPT,)
    assert choice.witness == DIGEST


def test_display_of_local_file_does_not_claim_sis_import(tmp_path, monkeypatch):
    args, nav, _, loader, _, _, out = make(tmp_path, monkeypatch)
    named.run_named_export_receipt_browse(**args)
    text = out.getvalue()
    assert "period-grades.csv" in text
    assert "Rows: 29" in text
    assert "Profile version: 3" in text
    assert "teacher-identity" in text
    assert "does not prove a district/SIS accepted" in text
    assert "no file, receipt, or selection was changed" in text
    assert RECEIPT not in text and DIGEST not in text
    assert loader.call_count >= 2
    nav.session.select_student.assert_not_called()


def test_copyable_text_is_not_described_as_file(tmp_path, monkeypatch):
    args, _, _, loader, cat, _, out = make(tmp_path, monkeypatch)
    loader.return_value = receipt(
        destination_kind="copyable_text", destination_name=None
    )
    choice = load_teacher_choices(
        cat, scope="export_receipt", selected={"class": CLASS}
    )[0]
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: choice)
    named.run_named_export_receipt_browse(**args)
    text = out.getvalue()
    assert "Copyable report text" in text
    assert "period-grades.csv" not in text


def test_canceled_choice_loads_no_receipt(tmp_path, monkeypatch):
    args, _, lister, loader, _, _, out = make(tmp_path, monkeypatch, chosen=False)
    named.run_named_export_receipt_browse(**args)
    assert out.getvalue() == ""
    loader.assert_not_called()
    lister.assert_not_called()


def test_empty_receipt_inventory_is_valid(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    loader = MagicMock()
    catalog = named.NamedExportReceiptCatalog(nav, lambda *_a: (), loader)
    assert (
        load_teacher_choices(catalog, scope="export_receipt", selected={"class": CLASS})
        == ()
    )
    loader.assert_not_called()


@pytest.mark.parametrize("ids", [tuple(["x"] * 2), tuple(str(x) for x in range(201))])
def test_duplicate_or_unbounded_receipts_fail_before_loader(tmp_path, ids):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    loader = MagicMock()
    catalog = named.NamedExportReceiptCatalog(nav, lambda *_a: ids, loader)
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(catalog, scope="export_receipt", selected={"class": CLASS})
    loader.assert_not_called()


@pytest.mark.parametrize(
    "scope,cls", [("unexpected", CLASS), ("export_receipt", "other")]
)
def test_wrong_catalog_scope_or_class_rejected(tmp_path, scope, cls):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    cat = named.NamedExportReceiptCatalog(nav, lambda *_a: (), lambda *_a: None)
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(cat, scope=scope, selected={"class": cls})


@pytest.mark.parametrize(
    "changes",
    [
        dict(export_id="wrong"),
        dict(receipt_sha256="INVALID"),
        dict(payload_sha256="bad"),
        dict(snapshot_id=""),
        dict(profile_id=""),
        dict(profile_revision=0),
        dict(profile_revision=True),
        dict(row_count=-1),
        dict(row_count=True),
        dict(destination_kind="sis"),
        dict(destination_kind="file", destination_name=None),
        dict(destination_kind="copyable_text", destination_name="grades.csv"),
        dict(exported_at="2026-10-25T08:00:00"),
    ],
)
def test_mismatched_or_corrupt_receipt_fails_closed(tmp_path, changes):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year="2026-2027"
    )
    cat = named.NamedExportReceiptCatalog(
        nav, lambda *_a: (RECEIPT,), lambda *_a: receipt(**changes)
    )
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(cat, scope="export_receipt", selected={"class": CLASS})


@pytest.mark.parametrize(
    "changes",
    [
        dict(receipt_sha256="c" * 64),
        dict(row_count=30),
        dict(exported_at="2026-10-26T14:00:00+00:00"),
    ],
)
def test_changed_receipt_after_selection_blocks_inspection(
    tmp_path, monkeypatch, changes
):
    args, _, _, loader, _, _, out = make(tmp_path, monkeypatch)
    loader.return_value = receipt(**changes)
    named.run_named_export_receipt_browse(**args)
    text = out.getvalue()
    assert "could not be verified" in text or "changed" in text
    assert "Rows: 29" not in text


def test_class_change_rejects_selected_receipt(tmp_path, monkeypatch):
    args, nav, _, _, _, _, out = make(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="another", school_year="2026-2027"
    )
    named.run_named_export_receipt_browse(**args)
    assert "changed" in out.getvalue().lower()
    assert "Rows: 29" not in out.getvalue()


def test_second_verified_read_detects_in_place_receipt_change(tmp_path, monkeypatch):
    args, _, _, loader, _, _, out = make(tmp_path, monkeypatch)
    counter = 0

    def changed(*_a):
        nonlocal counter
        counter += 1
        return receipt(row_count=30) if counter > 3 else receipt()

    loader.side_effect = changed
    named.run_named_export_receipt_browse(**args)
    assert "Rows: 29" not in out.getvalue()


def test_internal_error_is_redacted(tmp_path, monkeypatch):
    args, _, _, loader, _, _, out = make(tmp_path, monkeypatch)
    loader.side_effect = RuntimeError("private /student/secret/location")
    named.run_named_export_receipt_browse(**args)
    assert "/student/" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


@pytest.mark.parametrize("signal", [ReturnToMainMenu, QuitPDS])
def test_core_navigation_unwinds_without_side_effects(tmp_path, monkeypatch, signal):
    args, _, _, loader, _, _, _ = make(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))
    with pytest.raises(signal):
        named.run_named_export_receipt_browse(**args)
    loader.assert_not_called()


def test_no_new_raw_id_prompts_or_export_writers():
    source = Path(named.__file__).read_text(encoding="utf-8")
    assert "read_choice(" not in source
    assert "commit_report_export(" not in source
    assert "select_export_profile(" not in source
    assert "write_export_profile_revision(" not in source


def test_local_export_and_receipt_are_distinct_from_external_acceptance(
    tmp_path, monkeypatch
):
    args, _, _, _, _, _, out = make(tmp_path, monkeypatch)
    named.run_named_export_receipt_browse(**args)
    text = out.getvalue()
    assert "local Meridian export only" in text
    assert "exported file still exists" in text
    assert "district/SIS accepted" in text
