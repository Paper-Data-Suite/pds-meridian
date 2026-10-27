"""#123 Slice 9H: named, read-only local report ExportReceipt provenance."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_report_receipt as named

CLASS = "english_12_pd2"
YEAR = "2026-2027"
EXPORT = "export_private"
SNAPSHOT = "mk_" + "a" * 64
PROFILE = "profile_private"
RECEIPT_SHA = "b" * 64
SNAPSHOT_SHA = "c" * 64
PROFILE_SHA = "d" * 64
PREVIEW_SHA = "e" * 64
PAYLOAD_SHA = "f" * 64


def summary(**changes):
    data = dict(
        export_id=EXPORT,
        receipt_sha256=RECEIPT_SHA,
        snapshot_id=SNAPSHOT,
        snapshot_sha256=SNAPSHOT_SHA,
        profile_id=PROFILE,
        profile_revision=2,
        profile_sha256=PROFILE_SHA,
        profile_title="MP1 Standards Report",
        school_year=YEAR,
        period_label="Marking Period 1",
        exported_at="2026-10-26T16:00:00+00:00",
        row_count=29,
        destination_kind="file",
        destination_name="grades.csv",
        actor_id="teacher_private",
        preview_sha256=PREVIEW_SHA,
        payload_sha256=PAYLOAD_SHA,
        payload_byte_length=4567,
    )
    data.update(changes)
    return named.ReportReceiptSummary(**data)


def presentation(**changes):
    s = summary()
    data = dict(
        title="ExportReceipt Provenance",
        lines=(
            f"Export: {s.export_id}",
            f"Snapshot: {s.snapshot_id}",
            f"Export Profile: {s.profile_id} r{s.profile_revision}",
            f"Rows: {s.row_count}",
            "Destination kind: file",
            "Destination file: grades.csv",
            f"Teacher: {s.actor_id}",
            (
                "Scope: local Meridian export provenance; "
                "external acceptance is not claimed."
            ),
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"receipt_sha256: {s.receipt_sha256}",
            f"preview_sha256: {s.preview_sha256}",
            f"payload_sha256: {s.payload_sha256}",
            f"payload_byte_length: {s.payload_byte_length}",
            f"snapshot_sha256: {s.snapshot_sha256}",
            f"profile_sha256: {s.profile_sha256}",
        ),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def setup(tmp_path, monkeypatch, *, choices=("",)):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav = MagicMock()
    nav.current_class.return_value = scope
    catalog = MagicMock()
    catalog.inspect.return_value = summary()
    selected = summary().choice()
    choose = MagicMock(return_value=selected)
    explainer = MagicMock(return_value=presentation())
    monkeypatch.setattr(named, "_class", lambda *a, **k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", choose)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=selected))
    answers = iter(choices)

    def get_input(prompt=""):
        return next(answers, "")

    out = StringIO()
    args = dict(
        navigation=nav,
        report_receipt_explainer=explainer,
        input_fn=get_input,
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        receipt_catalog=catalog,
    )
    return args, out, explainer, catalog, nav, choose


def test_named_explanation_reads_existing_receipt(tmp_path, monkeypatch):
    args, out, read, catalog, _, _ = setup(tmp_path, monkeypatch)
    named.run_named_report_receipt_explanation(**args)
    read.assert_called_once_with(tmp_path, CLASS, EXPORT)
    assert "MP1 Standards Report" in out.getvalue()
    assert "Marking Period 1" in out.getvalue()
    assert "29" in out.getvalue()
    assert "not SIS/LMS acceptance" in out.getvalue()
    assert EXPORT not in out.getvalue()
    assert SNAPSHOT not in out.getvalue()
    assert RECEIPT_SHA not in out.getvalue()
    assert catalog.inspect.call_count >= 2


def test_t_reveals_exact_provenance_only_after_request(tmp_path, monkeypatch):
    args, out, _, _, _, _ = setup(tmp_path, monkeypatch, choices=("t", "", ""))
    named.run_named_report_receipt_explanation(**args)
    displayed = out.getvalue()
    assert "export_id: " + EXPORT in displayed
    assert "receipt_sha256: " + RECEIPT_SHA in displayed
    assert "profile_id: " + PROFILE in displayed
    assert "Local Report ExportReceipt Explanation" in displayed


@pytest.mark.parametrize("step", ("class", "receipt"))
def test_cancel_before_explanation_does_not_read(tmp_path, monkeypatch, step):
    args, _, explainer, _, _, choose = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *a, **k: None)
    else:
        choose.return_value = None
    named.run_named_report_receipt_explanation(**args)
    explainer.assert_not_called()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("workspace", Path("/changed")),
        ("class_id", "other"),
        ("school_year", "2025-2026"),
    ],
)
def test_wrong_verified_class_blocks(tmp_path, monkeypatch, field, bad):
    args, out, read, _, nav, _ = setup(tmp_path, monkeypatch)
    current = nav.current_class.return_value
    nav.current_class.return_value = SimpleNamespace(**(vars(current) | {field: bad}))
    named.run_named_report_receipt_explanation(**args)
    read.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_sha256", "1" * 64),
        ("profile_sha256", "2" * 64),
        ("snapshot_sha256", "3" * 64),
        ("payload_sha256", "4" * 64),
        ("school_year", "2025-2026"),
    ],
)
def test_stale_witness_blocks_before_reader(tmp_path, monkeypatch, field, value):
    args, out, reader, cat, _, _ = setup(tmp_path, monkeypatch)
    cat.inspect.return_value = replace(summary(), **{field: value})
    named.run_named_report_receipt_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Unknown Provenance"},
        {"lines": ("Export: OTHER",) + presentation().lines[1:]},
        {
            "lines": (
                *presentation().lines[:3],
                "Rows: 30",
                *presentation().lines[4:],
            )
        },
        {
            "lines": (
                *presentation().lines[:4],
                "Destination kind: copyable text",
                *presentation().lines[5:],
            )
        },
        {
            "lines": (
                *presentation().lines[:5],
                "Destination file: missing.csv",
                *presentation().lines[6:],
            )
        },
        {
            "lines": (
                *presentation().lines[:6],
                "Teacher: someone_else",
                *presentation().lines[7:],
            )
        },
        {
            "technical_lines": (
                "class_id: WRONG",
                *presentation().technical_lines[1:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:1],
                "receipt_sha256: WRONG",
                *presentation().technical_lines[2:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:2],
                "preview_sha256: WRONG",
                *presentation().technical_lines[3:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:3],
                "payload_sha256: WRONG",
                *presentation().technical_lines[4:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:4],
                "payload_byte_length: 7",
                *presentation().technical_lines[5:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:5],
                "snapshot_sha256: WRONG",
                *presentation().technical_lines[6:],
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines[:6],
                "profile_sha256: WRONG",
            )
        },
        {
            "technical_lines": (
                *presentation().technical_lines,
                "class_id: " + CLASS,
            )
        },
        {"lines": list(presentation().lines)},
    ],
)
def test_wrong_explanation_fails_closed(tmp_path, monkeypatch, change):
    args, out, reader, _, _, _ = setup(tmp_path, monkeypatch)
    reader.return_value = presentation(**change)
    named.run_named_report_receipt_explanation(**args)
    assert "MP1 Standards Report" not in out.getvalue()
    assert "could not be verified" in out.getvalue() or "changed" in out.getvalue()


def test_class_switch_while_explaining_blocks_display(tmp_path, monkeypatch):
    args, out, reader, _, nav, _ = setup(tmp_path, monkeypatch)

    def switch_scope(*_args):
        nav.current_class.return_value = SimpleNamespace(
            workspace=tmp_path, class_id="other", school_year=YEAR
        )
        return presentation()

    reader.side_effect = switch_scope
    named.run_named_report_receipt_explanation(**args)
    assert "MP1 Standards Report" not in out.getvalue()


def test_receipt_changes_while_reading_blocks_display(tmp_path, monkeypatch):
    args, out, reader, catalog, _, _ = setup(tmp_path, monkeypatch)
    call_count = [0]

    def inspect(*_args):
        call_count[0] += 1
        if call_count[0] == 1:
            return summary()
        return replace(summary(), receipt_sha256="0" * 64)

    catalog.inspect.side_effect = inspect
    named.run_named_report_receipt_explanation(**args)
    reader.assert_called_once()
    assert "MP1 Standards Report" not in out.getvalue()


def test_read_error_redacted(tmp_path, monkeypatch):
    args, out, reader, _, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("SECRET /hidden/teacher/roster")
    named.run_named_report_receipt_explanation(**args)
    assert "SECRET" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


@pytest.mark.parametrize("exc", (QuitPDS, ReturnToMainMenu))
def test_navigation_bubbles(tmp_path, monkeypatch, exc):
    args, _, reader, _, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = exc
    with pytest.raises(exc):
        named.run_named_report_receipt_explanation(**args)


def test_choice_provenance_is_bounded_and_hidden():
    choice = summary().choice()
    assert len(choice.witness or "") == 71
    assert EXPORT not in choice.display
    assert SNAPSHOT not in choice.display
    assert RECEIPT_SHA not in choice.display
    assert PROFILE not in choice.display
    assert "MP1 Standards Report" in choice.display


@pytest.mark.parametrize(
    "field,bad",
    [
        ("export_id", "export_other"),
        ("receipt_sha256", "1" * 64),
        ("snapshot_sha256", "2" * 64),
        ("profile_sha256", "3" * 64),
        ("preview_sha256", "4" * 64),
        ("payload_sha256", "5" * 64),
        ("payload_byte_length", 4568),
        ("profile_revision", 3),
    ],
)
def test_witness_changes_with_any_immutable_source(field, bad):
    changed = replace(summary(), **{field: bad}).choice().witness
    assert changed != summary().choice().witness


def storage(
    tmp_path,
    *,
    year=YEAR,
    receipt_sha=RECEIPT_SHA,
    snapshot_mismatch=False,
    profile_mismatch=False,
):
    snapshot_ref = SimpleNamespace(
        class_id=CLASS, snapshot_id=SNAPSHOT, snapshot_sha256=SNAPSHOT_SHA
    )
    profile_ref = SimpleNamespace(
        class_id=CLASS,
        profile_id=PROFILE,
        profile_revision=2,
        profile_sha256=PROFILE_SHA,
    )
    receipt = SimpleNamespace(
        class_id=CLASS,
        export_id=EXPORT,
        snapshot_reference=snapshot_ref,
        profile_reference=profile_ref,
        exported_at=SimpleNamespace(isoformat=lambda: "2026-10-26T16:00:00+00:00"),
        row_count=29,
        destination=SimpleNamespace(kind="file", basename="grades.csv"),
        actor=SimpleNamespace(actor_id="teacher_private"),
        preview_sha256=PREVIEW_SHA,
        payload_sha256=PAYLOAD_SHA,
        payload_byte_length=4567,
    )
    stored = SimpleNamespace(
        receipt=receipt,
        receipt_sha256=receipt_sha,
        reference=SimpleNamespace(
            class_id=CLASS, export_id=EXPORT, receipt_sha256=receipt_sha
        ),
    )
    snapshot = SimpleNamespace(
        reference=snapshot_ref if not snapshot_mismatch else SimpleNamespace(),
        snapshot=SimpleNamespace(
            class_id=CLASS,
            target_period=SimpleNamespace(school_year=year, period_id="mp1"),
            calendar_revision=7,
        ),
    )
    profile = SimpleNamespace(
        reference=profile_ref if not profile_mismatch else SimpleNamespace(),
        profile=SimpleNamespace(class_id=CLASS, title="MP1 Standards Report"),
    )
    readers = named.ReportReceiptReaders(
        lister=MagicMock(return_value=(EXPORT,)),
        receipt_loader=MagicMock(return_value=stored),
        snapshot_loader=MagicMock(return_value=snapshot),
        profile_loader=MagicMock(return_value=profile),
        calendar_loader=MagicMock(return_value=SimpleNamespace()),
        period_lookup=MagicMock(
            return_value=SimpleNamespace(period_id="mp1", label="Marking Period 1")
        ),
    )
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    return named.ReportReceiptChoiceCatalog(nav, readers), readers


def test_catalog_lists_historical_local_exports(tmp_path):
    catalog, readers = storage(tmp_path)
    choices = catalog.options(scope="report_export_receipt", selected={"class": CLASS})
    assert len(choices) == 1
    assert choices[0].identity == (EXPORT,)
    assert "MP1 Standards Report" in choices[0].display
    readers.receipt_loader.assert_called_with(tmp_path, CLASS, EXPORT)


def test_catalog_filters_different_year(tmp_path):
    catalog, _ = storage(tmp_path, year="2025-2026")
    assert (
        catalog.options(scope="report_export_receipt", selected={"class": CLASS}) == ()
    )


@pytest.mark.parametrize(
    "kwargs", [{"snapshot_mismatch": True}, {"profile_mismatch": True}]
)
def test_catalog_rejects_provenance_mismatch(tmp_path, kwargs):
    catalog, _ = storage(tmp_path, **kwargs)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="report_export_receipt", selected={"class": CLASS})


def test_catalog_rejects_duplicate_or_excessive_list(tmp_path):
    catalog, readers = storage(tmp_path)
    readers.lister.return_value = (EXPORT, EXPORT)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="report_export_receipt", selected={"class": CLASS})
    readers.lister.return_value = tuple(str(i) for i in range(201))
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="report_export_receipt", selected={"class": CLASS})


def test_catalog_requires_verified_class(tmp_path):
    catalog, _ = storage(tmp_path)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="report_export_receipt", selected={"class": "other"})
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="not-a-receipt", selected={"class": CLASS})


def test_menu_append_only_and_legacy_preserved():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert '"16. Explain a saved local Report ExportReceipt by name"' in source
    assert "run_named_report_receipt_explanation(" in source
    assert '"15. Explain a saved Planning Export by name"' in source
    assert '"8. Advanced: ExportReceipt provenance"' in source
    assert '"8. ExportReceipt provenance"' in source
    assert any(
        f'"Please choose 1-{last}, B, M, or Q."' in source for last in range(16, 100)
    )
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_controller_has_no_raw_id_input_or_writes():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Export ID',
        'read_choice(input_fn, "SHA',
        "write_export_",
        "commit_report_export(",
        "select_current_",
        "authorize_publication(",
    ):
        assert forbidden not in source
