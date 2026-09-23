from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from meridian.export_profile import ExportColumn
from meridian.report_export_receipt import (
    REPORT_EXPORT_RECEIPT_RECORD_TYPE,
    REPORT_EXPORT_RECEIPT_SCHEMA_VERSION,
    ExportReceipt,
    ReportExportActor,
    ReportExportDestinationReceipt,
    ReportExportReceiptConflictError,
    ReportExportReceiptIntegrityError,
    ReportExportReceiptSerializationError,
    ReportExportReceiptValidationError,
    export_receipt_from_json_bytes,
    export_receipt_from_preview,
    export_receipt_sha256,
    export_receipt_to_dict,
    export_receipt_to_json_bytes,
    list_export_receipt_ids,
    load_export_receipt,
    report_export_receipt_digest_path,
    report_export_receipt_path,
    report_export_receipt_relative_path,
    write_export_receipt,
)
from tests import test_report_export_preview_issue56 as preview_support

CLASS_ID = preview_support.CLASS_ID
NOW = datetime(2026, 9, 22, 3, 30, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _snapshot_only_built():
    profile = preview_support._profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("row.status", "status"),
            ExportColumn("grade.effective_grade", "grade"),
        )
    )
    return preview_support._compose(
        profile,
        preview_support._unavailable_preview(),
    )


def _roster_built():
    profile = preview_support._profile(
        (
            ExportColumn("target.student_id", "student_id"),
            ExportColumn("roster.display_name", "student_name"),
        ),
        format="tsv",
    )
    roster = preview_support._roster_observation(
        ("roster.display_name",),
        ("Alex Rivera",),
    )
    return preview_support._compose(
        profile,
        preview_support._unavailable_preview(),
        roster,
    )


def _receipt(
    *,
    built=None,
    export_id: str = "export_001",
    destination: ReportExportDestinationReceipt | None = None,
) -> ExportReceipt:
    value = built or _snapshot_only_built()
    return export_receipt_from_preview(
        export_id=export_id,
        preview=value.preview,
        roster_observation=value.roster_observation,
        destination=destination
        or ReportExportDestinationReceipt("file", "grades.csv"),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Teacher approved exact export.",
        exported_at=NOW,
    )


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def test_receipt_error_codes_are_stable() -> None:
    assert ReportExportReceiptValidationError.code == "report_export.receipt_invalid"
    assert (
        ReportExportReceiptSerializationError.code
        == "report_export.receipt_integrity_failed"
    )
    assert ReportExportReceiptConflictError.code == "report_export.receipt_conflict"
    assert (
        ReportExportReceiptIntegrityError.code
        == "report_export.receipt_integrity_failed"
    )


def test_receipt_is_frozen_and_binds_exact_preview_fields() -> None:
    built = _snapshot_only_built()
    receipt = _receipt(built=built)

    assert receipt.schema_version == REPORT_EXPORT_RECEIPT_SCHEMA_VERSION
    assert receipt.record_type == REPORT_EXPORT_RECEIPT_RECORD_TYPE
    assert receipt.snapshot_reference == built.preview.snapshot_reference
    assert receipt.profile_reference == built.preview.profile_reference
    assert receipt.preview_sha256 == built.preview.preview_sha256
    assert receipt.payload_sha256 == built.preview.payload_sha256
    assert receipt.payload_byte_length == len(built.payload)
    assert receipt.row_count == built.preview.row_count
    assert receipt.roster_observation is None
    assert receipt.roster_observation_sha256 is None
    with pytest.raises(FrozenInstanceError):
        receipt.export_id = "changed"  # type: ignore[misc]


def test_roster_backed_receipt_retains_exact_bounded_observation() -> None:
    built = _roster_built()
    receipt = _receipt(built=built)

    assert receipt.roster_observation == built.roster_observation
    assert receipt.roster_observation is not None
    assert receipt.roster_observation.source_fields == ("roster.display_name",)
    assert receipt.roster_observation_sha256 == (
        built.preview.roster_observation_reference.observation_sha256
    )
    with pytest.raises(
        ReportExportReceiptValidationError,
        match="digest does not match",
    ):
        replace(receipt, roster_observation_sha256="f" * 64)
    encoded = export_receipt_to_json_bytes(receipt)
    assert b"Alex Rivera" in encoded
    assert b"roster.csv" not in encoded
    assert b"source_path" not in encoded


def test_roster_observation_must_match_preview_reference() -> None:
    built = _roster_built()
    wrong = preview_support._roster_observation(
        ("roster.display_name",),
        ("Changed Name",),
    )

    with pytest.raises(
        ReportExportReceiptValidationError,
        match="does not match preview",
    ):
        export_receipt_from_preview(
            export_id="export_001",
            preview=built.preview,
            roster_observation=wrong,
            destination=ReportExportDestinationReceipt("file", "grades.tsv"),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )


def test_snapshot_native_receipt_rejects_unnecessary_roster_observation() -> None:
    built = _snapshot_only_built()
    roster = preview_support._roster_observation(
        ("roster.display_name",),
        ("Alex Rivera",),
    )

    with pytest.raises(
        ReportExportReceiptValidationError,
        match="must not retain",
    ):
        export_receipt_from_preview(
            export_id="export_001",
            preview=built.preview,
            roster_observation=roster,
            destination=ReportExportDestinationReceipt("file", "grades.csv"),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=NOW,
        )


def test_destination_receipt_retains_only_safe_basename() -> None:
    destination = ReportExportDestinationReceipt("file", "grades.csv")
    assert destination.basename == "grades.csv"

    for unsafe in ("../grades.csv", "folder/grades.csv", r"folder\grades.csv"):
        with pytest.raises(ReportExportReceiptValidationError):
            ReportExportDestinationReceipt("file", unsafe)

    assert ReportExportDestinationReceipt("copyable_text", None).basename is None
    with pytest.raises(ReportExportReceiptValidationError):
        ReportExportDestinationReceipt("copyable_text", "clipboard.txt")


def test_receipt_round_trips_canonically_and_digest_binds_exact_bytes() -> None:
    receipt = _receipt(built=_roster_built())
    encoded = export_receipt_to_json_bytes(receipt)

    assert encoded.endswith(b"\n")
    assert export_receipt_from_json_bytes(encoded) == receipt
    assert export_receipt_sha256(receipt) == hashlib.sha256(encoded).hexdigest()


def test_receipt_exact_schema_rejects_unknown_fields() -> None:
    data = export_receipt_to_dict(_receipt())
    data["external_system_accepted"] = True

    with pytest.raises(ReportExportReceiptSerializationError, match="exact schema"):
        export_receipt_from_json_bytes(_canonical_json_bytes(data))


def test_receipt_rejects_noncanonical_json_and_duplicate_keys() -> None:
    receipt = _receipt()
    data = export_receipt_to_dict(receipt)
    noncanonical = json.dumps(data, sort_keys=True).encode("utf-8")
    with pytest.raises(ReportExportReceiptSerializationError, match="not canonical"):
        export_receipt_from_json_bytes(noncanonical)

    canonical = export_receipt_to_json_bytes(receipt).decode("utf-8")
    duplicate = canonical.replace(
        '  "class_id": "english_12",',
        '  "class_id": "english_12",\n  "class_id": "english_12",',
        1,
    ).encode("utf-8")
    with pytest.raises(
        ReportExportReceiptSerializationError,
        match="duplicate JSON object key",
    ):
        export_receipt_from_json_bytes(duplicate)


def test_receipt_storage_create_load_exact_replay_and_list(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    receipt = _receipt()

    first = write_export_receipt(root, receipt)
    second = write_export_receipt(root, receipt)
    loaded = load_export_receipt(root, CLASS_ID, receipt.export_id)

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.reference == second.stored.reference == loaded.reference
    assert first.stored.content == export_receipt_to_json_bytes(receipt)
    assert list_export_receipt_ids(root, CLASS_ID) == ("export_001",)
    assert first.stored.relative_path == report_export_receipt_relative_path(
        CLASS_ID,
        "export_001",
    )


def test_receipt_storage_conflicts_on_same_identity_different_content(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    receipt = _receipt()
    write_export_receipt(root, receipt)

    changed = replace(receipt, rationale="Different immutable decision.")
    with pytest.raises(ReportExportReceiptConflictError, match="different content"):
        write_export_receipt(root, changed)


def test_receipt_storage_detects_digest_and_noncanonical_content_tamper(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    receipt = _receipt()
    write_export_receipt(root, receipt)
    path = report_export_receipt_path(root, CLASS_ID, receipt.export_id)
    digest_path = report_export_receipt_digest_path(root, CLASS_ID, receipt.export_id)

    digest_path.write_bytes(("f" * 64 + "\n").encode("ascii"))
    with pytest.raises(ReportExportReceiptIntegrityError, match="digest"):
        load_export_receipt(root, CLASS_ID, receipt.export_id)

    data = json.loads(export_receipt_to_json_bytes(receipt))
    alternate = json.dumps(data, sort_keys=True).encode("utf-8")
    path.write_bytes(alternate)
    digest_path.write_bytes(
        (hashlib.sha256(alternate).hexdigest() + "\n").encode("ascii")
    )
    with pytest.raises(ReportExportReceiptIntegrityError, match="invalid"):
        load_export_receipt(root, CLASS_ID, receipt.export_id)


def test_receipt_storage_rejects_noncanonical_sidecar_line_endings(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    receipt = _receipt()
    write_export_receipt(root, receipt)
    digest_path = report_export_receipt_digest_path(root, CLASS_ID, receipt.export_id)
    digest = export_receipt_sha256(receipt)
    digest_path.write_bytes((digest + "\r\n").encode("ascii"))

    with pytest.raises(ReportExportReceiptIntegrityError, match="canonical"):
        load_export_receipt(root, CLASS_ID, receipt.export_id)


def test_receipt_storage_paths_are_class_local_and_contained(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    path = report_export_receipt_path(root, CLASS_ID, "export_001")

    assert path == (
        root
        / "classes"
        / CLASS_ID
        / "modules"
        / "meridian"
        / "reporting_exports"
        / "export_001.json"
    )
    with pytest.raises(ReportExportReceiptValidationError):
        report_export_receipt_path(root, CLASS_ID, "../escape")
