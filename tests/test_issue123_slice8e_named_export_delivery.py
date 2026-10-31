"""#123 Slice 8E: guarded explicit named local export and receipt readback."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_export_delivery as named

CLASS = "opaque-class"
SNAPSHOT = "opaque-frozen-report"
PROFILE = "opaque-profile"
SHA1 = "a" * 64
SHA2 = "b" * 64
EXPORT = "export-" + "1" * 32
NOW = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
STUDENT_PAYLOAD = "SECRET_STUDENT_ROW"


def snapshot(**changes):
    row = dict(
        snapshot_id=SNAPSHOT,
        snapshot_sha256=SHA1,
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        definition_id="hidden",
        definition_revision=1,
        row_count=29,
        created_at="2026-10-25T15:00:00+00:00",
    )
    row.update(changes)
    return SimpleNamespace(**row)


def profile_row(**changes):
    row = dict(
        profile_id=PROFILE, title="Grade Copy", latest_revision=4, current_revision=3
    )
    row.update(changes)
    return SimpleNamespace(**row)


def profile(**changes):
    row = dict(
        class_id=CLASS,
        profile_id=PROFILE,
        revision=3,
        profile_sha256=SHA2,
        format="csv",
        columns=(("roster.display_name", "Student"), ("grade.base_grade", "Grade")),
    )
    row.update(changes)
    return SimpleNamespace(**row)


def preview(**changes):
    row = dict(
        class_id=CLASS,
        snapshot_id=SNAPSHOT,
        snapshot_sha256=SHA1,
        profile_id=PROFILE,
        profile_revision=3,
        profile_sha256=SHA2,
        format="csv",
        row_count=29,
        payload_byte_length=1400,
        payload_sha256="c" * 64,
        preview_sha256="d" * 64,
        diagnostic_lines=(),
        payload_text=STUDENT_PAYLOAD,
        built=object(),
    )
    row.update(changes)
    return SimpleNamespace(**row)


def result(**changes):
    row = dict(
        export_id=EXPORT,
        receipt_sha256="e" * 64,
        artifact_disposition="created",
        destination_kind="file",
        destination_name="grades.csv",
        copyable_text=None,
    )
    row.update(changes)
    return SimpleNamespace(**row)


def receipt(**changes):
    row = dict(
        export_id=EXPORT,
        receipt_sha256="e" * 64,
        snapshot_id=SNAPSHOT,
        profile_id=PROFILE,
        profile_revision=3,
        row_count=29,
        payload_sha256="c" * 64,
        destination_kind="file",
        destination_name="grades.csv",
        actor_id="teacher",
        exported_at=NOW.isoformat(),
    )
    row.update(changes)
    return SimpleNamespace(**row)


def prepare(
    tmp_path,
    monkeypatch,
    *,
    choice="1",
    confirmation="EXPORT",
    choices=("frozen_snapshot", "export_profile"),
):
    nav = MagicMock()
    verified = SimpleNamespace(
        class_id=CLASS, workspace=tmp_path, school_year="2026-2027"
    )
    period = SimpleNamespace(
        school_year="2026-2027", period_id="mp1", calendar_revision=4, label="MP1"
    )
    period_choice = SimpleNamespace(identity=("mp1",), label="MP1")
    nav.current_class.return_value = verified
    nav.current_period.return_value = period
    snapshots = MagicMock(return_value=(snapshot(),))
    profiles = MagicMock(return_value=(profile_row(),))
    profile_loader = MagicMock(return_value=profile())
    builder = MagicMock(return_value=preview())
    committer = MagicMock(return_value=result())
    loader = MagicMock(return_value=receipt())
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_k: (period, period_choice)
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda *_a, **_k: (period_choice,)
    )
    monkeypatch.setattr(named, "_snapshot_revalidate", MagicMock())
    monkeypatch.setattr(named, "_profile_revalidate", MagicMock())
    chosen = iter(choices)

    def select(*, scope, **kwargs):
        assert scope == next(chosen)
        return (
            SimpleNamespace(identity=(SNAPSHOT,), label="Semester Report")
            if scope == "frozen_snapshot"
            else SimpleNamespace(identity=(PROFILE,), label="Grade Copy")
        )

    monkeypatch.setattr(named, "select_teacher_choice", select)
    path = str(tmp_path / "grades.csv")
    answers = iter(
        (
            [choice]
            + ([path] if choice == "1" else [])
            + (
                ["teacher", "local grade review", confirmation]
                if choice in {"1", "2"}
                else []
            )
        )
    )
    out = StringIO()

    def scripted_input(prompt: str = "") -> str:
        if prompt == "Press Enter to continue...":
            return ""
        return next(answers)

    args = dict(
        navigation=nav,
        snapshot_lister=snapshots,
        profile_lister=profiles,
        profile_loader=profile_loader,
        preview_builder=builder,
        export_committer=committer,
        receipt_loader=loader,
        clock=lambda: NOW,
        export_id_factory=lambda: EXPORT,
        input_fn=scripted_input,
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
        snapshot_catalog=MagicMock(),
        profile_catalog=MagicMock(),
    )
    return (
        args,
        nav,
        snapshots,
        profiles,
        profile_loader,
        builder,
        committer,
        loader,
        out,
    )


def test_explicit_file_delivery_verifies_receipt_no_student_terminal_rows(
    tmp_path, monkeypatch
):
    args, _, _, _, _, builder, committer, loader, out = prepare(tmp_path, monkeypatch)
    named.run_named_report_export_delivery(**args)
    message = out.getvalue()
    assert "Exact local ExportReceipt verified" in message
    assert STUDENT_PAYLOAD not in message
    assert "No district/SIS/LMS import" in message
    assert builder.call_count == 4
    committer.assert_called_once_with(
        tmp_path,
        builder.return_value,
        EXPORT,
        "teacher",
        "local grade review",
        "file",
        str(tmp_path / "grades.csv"),
        NOW,
    )
    loader.assert_called_once_with(tmp_path, CLASS, EXPORT)


def test_copyable_text_only_after_receipt_verified(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, loader, out = prepare(
        tmp_path, monkeypatch, choice="2"
    )
    committer.return_value = result(
        destination_kind="copyable_text",
        destination_name=None,
        artifact_disposition="copyable",
        copyable_text=STUDENT_PAYLOAD,
    )
    loader.return_value = receipt(
        destination_kind="copyable_text", destination_name=None
    )
    named.run_named_report_export_delivery(**args)
    assert "Exact local ExportReceipt verified" in out.getvalue()
    assert STUDENT_PAYLOAD in out.getvalue()
    assert committer.call_args.args[5:7] == ("copyable_text", None)


@pytest.mark.parametrize(
    "choice,confirmation", [("3", ""), ("", ""), ("1", ""), ("2", "CANCEL")]
)
def test_cancel_never_calls_committer_or_receipt(
    tmp_path, monkeypatch, choice, confirmation
):
    args, _, _, _, _, _, committer, loader, out = prepare(
        tmp_path, monkeypatch, choice=choice, confirmation=confirmation
    )
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()
    loader.assert_not_called()
    assert STUDENT_PAYLOAD not in out.getvalue()


@pytest.mark.parametrize(
    "changed",
    [
        dict(snapshot_sha256=SHA2),
        dict(snapshot_id="other"),
        dict(profile_sha256=SHA1),
        dict(profile_revision=1),
        dict(payload_sha256="invalid"),
        dict(row_count=-1),
        dict(class_id="other"),
        dict(preview_sha256="x" * 64),
    ],
)
def test_bad_source_preview_blocks_export(tmp_path, monkeypatch, changed):
    args, _, _, _, _, builder, committer, loader, out = prepare(tmp_path, monkeypatch)
    builder.return_value = preview(**changed)
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()
    loader.assert_not_called()
    assert STUDENT_PAYLOAD not in out.getvalue()


def test_changed_preview_between_precommit_reads_blocks_write(tmp_path, monkeypatch):
    args, _, _, _, _, builder, committer, _, out = prepare(tmp_path, monkeypatch)
    builder.side_effect = [
        preview(),
        preview(),
        preview(),
        preview(payload_sha256="a" * 64),
    ]
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()
    assert "No export was attempted" in out.getvalue()


def test_stale_selected_profile_blocks_export(tmp_path, monkeypatch):
    args, _, _, profiles, _, _, committer, _, _ = prepare(tmp_path, monkeypatch)
    profiles.return_value = (profile_row(current_revision=None),)
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()


def test_wrong_snapshot_period_blocks_export(tmp_path, monkeypatch):
    args, _, snapshots, _, _, _, committer, _, _ = prepare(tmp_path, monkeypatch)
    snapshots.return_value = (snapshot(period_id="mp2"),)
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()


@pytest.mark.parametrize(
    "changed",
    [
        dict(export_id="wrong"),
        dict(receipt_sha256="bad"),
        dict(destination_name="bad.csv"),
        dict(artifact_disposition="copyable"),
        dict(copyable_text="no"),
    ],
)
def test_invalid_result_is_uncertain_and_not_claimed(tmp_path, monkeypatch, changed):
    args, _, _, _, _, _, committer, loader, out = prepare(tmp_path, monkeypatch)
    committer.return_value = result(**changed)
    named.run_named_report_export_delivery(**args)
    assert "uncertain" in out.getvalue().lower()
    assert "verified" not in out.getvalue()
    assert STUDENT_PAYLOAD not in out.getvalue()
    loader.assert_not_called()


@pytest.mark.parametrize(
    "changed",
    [
        dict(receipt_sha256="0" * 64),
        dict(snapshot_id="wrong"),
        dict(profile_revision=2),
        dict(row_count=15),
        dict(actor_id="wrong"),
    ],
)
def test_bad_receipt_is_uncertain(tmp_path, monkeypatch, changed):
    args, _, _, _, _, _, committer, loader, out = prepare(tmp_path, monkeypatch)
    loader.return_value = receipt(**changed)
    named.run_named_report_export_delivery(**args)
    committer.assert_called_once()
    assert "uncertain" in out.getvalue().lower()
    assert STUDENT_PAYLOAD not in out.getvalue()


def test_exception_during_commit_is_uncertain_and_redacted(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, _, out = prepare(tmp_path, monkeypatch)
    committer.side_effect = RuntimeError("secret path /student/records")
    named.run_named_report_export_delivery(**args)
    assert "could not be verified" in out.getvalue()
    assert "/student/" not in out.getvalue()


def test_generator_failure_no_commit(tmp_path, monkeypatch):
    args, _, _, _, _, _, committer, _, out = prepare(tmp_path, monkeypatch)
    args["export_id_factory"] = lambda: "garbage"
    named.run_named_report_export_delivery(**args)
    committer.assert_not_called()
    assert "No export was attempted" in out.getvalue()


def test_file_destination_requires_absolute_path(tmp_path):
    with pytest.raises(named._PreviewChanged):
        named._destination(
            kind="file", input_fn=lambda _: "relative.csv", output=StringIO()
        )


@pytest.mark.parametrize("signal", (ReturnToMainMenu, QuitPDS))
def test_core_navigation_unwinds(tmp_path, monkeypatch, signal):
    args, _, _, _, _, _, committer, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))
    with pytest.raises(signal):
        named.run_named_report_export_delivery(**args)
    committer.assert_not_called()


def test_new_route_contains_no_teacher_entered_export_identifier():
    code = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Export ID: ")' not in code
    assert 'read_choice(input_fn, "Class ID: ")' not in code
    assert 'read_choice(input_fn, "ReportingSnapshot sha256: ")' not in code
    assert "commit_report_export(" not in code
    assert "select_export_profile(" not in code


def test_new_route_does_not_claim_external_import(tmp_path, monkeypatch):
    args, _, _, _, _, _, _, _, out = prepare(tmp_path, monkeypatch)
    named.run_named_report_export_delivery(**args)
    assert "No district/SIS/LMS import" in out.getvalue()
