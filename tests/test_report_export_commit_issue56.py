from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from meridian.export_profile import ExportColumn
from meridian.report_export_commit import (
    ReportExportArtifactConflictError,
    ReportExportArtifactIntegrityError,
    ReportExportArtifactWriteError,
    ReportExportCommitReceiptError,
    ReportExportCurrentnessConflictError,
    commit_report_export,
    copyable_text_destination,
    file_export_destination,
)
from meridian.report_export_preview import ReportExportPreviewSourceError
from meridian.report_export_receipt import (
    ReportExportActor,
    ReportExportDestinationReceipt,
    export_receipt_from_preview,
    load_export_receipt,
    report_export_receipt_path,
    write_export_receipt,
)
from tests import test_report_export_preview_issue56 as preview_support

CLASS_ID = preview_support.CLASS_ID
NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _snapshot_only_built(*, utf8_bom: bool = False):
    profile = preview_support._profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("row.status", "status"),
            ExportColumn("grade.effective_grade", "grade"),
        ),
        utf8_bom=utf8_bom,
    )
    return preview_support._compose(
        profile,
        preview_support._unavailable_preview(),
    )


def _roster_built(name: str):
    profile = preview_support._profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("roster.display_name", "student_name"),
        )
    )
    roster = preview_support._roster_observation(
        ("roster.display_name",),
        (name,),
    )
    return preview_support._compose(
        profile,
        preview_support._unavailable_preview(),
        roster,
    )


def _patch_rebuild(monkeypatch: pytest.MonkeyPatch, built) -> None:
    monkeypatch.setattr(
        "meridian.report_export_commit.build_export_preview",
        lambda workspace_root, snapshot_reference, profile_reference: built,
    )


def test_copyable_commit_revalidates_then_records_receipt_and_exact_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)

    committed = commit_report_export(
        root,
        export_id="copy_export_001",
        approved_preview=built.preview,
        destination=copyable_text_destination(),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Copy exact text for approved workflow.",
        exported_at=NOW,
    )

    assert committed.artifact_disposition == "copyable"
    assert committed.destination_path is None
    assert committed.copyable_text == built.payload.decode("utf-8")
    assert committed.receipt.receipt.destination.kind == "copyable_text"
    assert committed.receipt.receipt.destination.basename is None
    assert committed.receipt.receipt.payload_sha256 == built.preview.payload_sha256
    assert load_export_receipt(
        root,
        CLASS_ID,
        "copy_export_001",
    ).reference == committed.receipt.reference


def test_copyable_commit_preserves_requested_utf8_bom_in_exact_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built(utf8_bom=True)
    _patch_rebuild(monkeypatch, built)

    committed = commit_report_export(
        root,
        export_id="copy_bom_001",
        approved_preview=built.preview,
        destination=copyable_text_destination(),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale=None,
        exported_at=NOW,
    )

    assert built.payload.startswith(b"\xef\xbb\xbf")
    assert committed.copyable_text is not None
    assert committed.copyable_text.startswith("\ufeff")


def test_file_commit_creates_exact_artifact_then_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = tmp_path / "exports" / "grades.csv"
    destination.parent.mkdir()

    committed = commit_report_export(
        root,
        export_id="file_export_001",
        approved_preview=built.preview,
        destination=file_export_destination(destination),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Write approved local file.",
        exported_at=NOW,
    )

    assert committed.artifact_disposition == "created"
    assert destination.read_bytes() == built.payload
    assert committed.receipt.receipt.destination == ReportExportDestinationReceipt(
        "file",
        "grades.csv",
    )
    encoded_receipt = committed.receipt.content
    assert str(destination).encode("utf-8") not in encoded_receipt
    assert b"grades.csv" in encoded_receipt


def test_exact_file_and_receipt_replay_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = tmp_path / "grades.csv"
    kwargs = {
        "export_id": "file_replay_001",
        "approved_preview": built.preview,
        "destination": file_export_destination(destination),
        "actor": ReportExportActor("teacher", "teacher_local"),
        "rationale": "Exact replay.",
        "exported_at": NOW,
    }

    first = commit_report_export(root, **kwargs)
    second = commit_report_export(root, **kwargs)

    assert first.artifact_disposition == "created"
    assert second.artifact_disposition == "existing"
    assert second.receipt.reference == first.receipt.reference
    assert destination.read_bytes() == built.payload


def test_exact_artifact_without_receipt_recovers_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = tmp_path / "grades.csv"
    destination.write_bytes(built.payload)

    committed = commit_report_export(
        root,
        export_id="recovery_001",
        approved_preview=built.preview,
        destination=file_export_destination(destination),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Recover exact artifact without receipt.",
        exported_at=NOW,
    )

    assert committed.artifact_disposition == "existing"
    assert report_export_receipt_path(root, CLASS_ID, "recovery_001").is_file()


def test_conflicting_existing_artifact_fails_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = tmp_path / "grades.csv"
    destination.write_bytes(b"different\n")

    with pytest.raises(
        ReportExportArtifactConflictError,
        match="different bytes",
    ):
        commit_report_export(
            root,
            export_id="artifact_conflict_001",
            approved_preview=built.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )

    assert not report_export_receipt_path(
        root,
        CLASS_ID,
        "artifact_conflict_001",
    ).exists()


def test_existing_receipt_with_missing_file_fails_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    receipt = export_receipt_from_preview(
        export_id="missing_file_001",
        preview=built.preview,
        roster_observation=built.roster_observation,
        destination=ReportExportDestinationReceipt("file", "grades.csv"),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Synthetic interrupted state.",
        exported_at=NOW,
    )
    write_export_receipt(root, receipt)

    with pytest.raises(ReportExportArtifactIntegrityError):
        commit_report_export(
            root,
            export_id="missing_file_001",
            approved_preview=built.preview,
            destination=file_export_destination(tmp_path / "grades.csv"),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale="Synthetic interrupted state.",
            exported_at=NOW,
        )


def test_material_roster_change_stales_approved_preview_before_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    approved = _roster_built("Alex Rivera")
    rebuilt = _roster_built("Alexis Rivera")
    _patch_rebuild(monkeypatch, rebuilt)
    destination = tmp_path / "grades.csv"

    with pytest.raises(
        ReportExportCurrentnessConflictError,
        match="no longer matches",
    ):
        commit_report_export(
            root,
            export_id="stale_001",
            approved_preview=approved.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )

    assert not destination.exists()
    assert not report_export_receipt_path(root, CLASS_ID, "stale_001").exists()


def test_source_revalidation_failure_fails_before_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()

    def fail(*args, **kwargs):
        raise ReportExportPreviewSourceError("source unavailable")

    monkeypatch.setattr(
        "meridian.report_export_commit.build_export_preview",
        fail,
    )
    destination = tmp_path / "grades.csv"

    with pytest.raises(ReportExportCurrentnessConflictError, match="revalidated"):
        commit_report_export(
            root,
            export_id="source_failure_001",
            approved_preview=built.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )

    assert not destination.exists()


def test_same_export_identity_with_changed_teacher_decision_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = copyable_text_destination()

    commit_report_export(
        root,
        export_id="decision_conflict_001",
        approved_preview=built.preview,
        destination=destination,
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="First decision.",
        exported_at=NOW,
    )

    with pytest.raises(ReportExportCommitReceiptError, match="different"):
        commit_report_export(
            root,
            export_id="decision_conflict_001",
            approved_preview=built.preview,
            destination=destination,
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale="Changed decision.",
            exported_at=NOW,
        )


def test_missing_destination_parent_fails_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    destination = tmp_path / "missing" / "grades.csv"

    with pytest.raises(ReportExportArtifactWriteError, match="does not exist"):
        commit_report_export(
            root,
            export_id="missing_parent_001",
            approved_preview=built.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )

    assert not report_export_receipt_path(
        root,
        CLASS_ID,
        "missing_parent_001",
    ).exists()


def test_file_destination_symlink_is_rejected_when_platform_supports_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    built = _snapshot_only_built()
    _patch_rebuild(monkeypatch, built)
    real = tmp_path / "real.csv"
    real.write_bytes(built.payload)
    link = tmp_path / "linked.csv"
    try:
        link.symlink_to(real)
    except OSError as error:
        pytest.skip(f"symlink creation is not permitted on this platform: {error}")

    with pytest.raises(ReportExportArtifactIntegrityError, match="symlink"):
        commit_report_export(
            root,
            export_id="symlink_001",
            approved_preview=built.preview,
            destination=file_export_destination(link),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )
