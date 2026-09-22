"""Teacher-initiated report-export commit workflow for Meridian v0.3.

Issue #56 requires a final exact source revalidation immediately before export.
This module rebuilds the deterministic preview from its exact snapshot/profile
references, rejects any material source drift, writes an optional local file with
non-overwrite semantics, and only then records an immutable ExportReceipt.

The copyable-text path returns exact text for teacher copying; it performs no OS
clipboard automation and makes no claim that any external system accepted data.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.report_export_preview import (
    BuiltExportPreview,
    ExportPreview,
    ReportExportPreviewError,
    build_export_preview,
    export_preview_to_json_bytes,
    validate_export_preview,
)
from meridian.report_export_receipt import (
    ExportReceipt,
    ReportExportActor,
    ReportExportDestinationReceipt,
    ReportExportReceiptError,
    ReportExportReceiptNotFoundError,
    StoredExportReceipt,
    export_receipt_from_preview,
    load_export_receipt,
    write_export_receipt,
)

ReportExportCommitDestinationKind: TypeAlias = Literal["file", "copyable_text"]
ReportExportArtifactDisposition: TypeAlias = Literal[
    "created",
    "existing",
    "copyable",
]


class ReportExportCommitError(RuntimeError):
    """Base error for final report-export commit workflow."""

    code = "report_export.commit_error"


class ReportExportCommitValidationError(ReportExportCommitError, ValueError):
    """Raised for invalid commit arguments or destination configuration."""

    code = "report_export.commit_invalid"


class ReportExportCurrentnessConflictError(ReportExportCommitError):
    """Raised when final exact preview rebuild no longer matches teacher preview."""

    code = "report_export.currentness_conflict"


class ReportExportArtifactConflictError(ReportExportCommitError):
    """Raised when a destination file already contains different bytes."""

    code = "report_export.artifact_conflict"


class ReportExportArtifactIntegrityError(ReportExportCommitError):
    """Raised when a destination artifact cannot be trusted or verified."""

    code = "report_export.artifact_integrity_failed"


class ReportExportArtifactWriteError(ReportExportCommitError):
    """Raised when a local export artifact cannot be written safely."""

    code = "report_export.artifact_write_failed"


class ReportExportCommitReceiptError(ReportExportCommitError):
    """Raised when immutable receipt persistence fails during commit."""

    code = "report_export.receipt_failed"


@dataclass(frozen=True, slots=True)
class ReportExportCommitDestination:
    """Runtime-only export destination; absolute paths never enter the receipt."""

    kind: ReportExportCommitDestinationKind
    path: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.kind == "file":
            if not isinstance(self.path, Path):
                raise ReportExportCommitValidationError(
                    "file destination requires a Path."
                )
            if not self.path.name:
                raise ReportExportCommitValidationError(
                    "file destination must identify a filename."
                )
        elif self.kind == "copyable_text":
            if self.path is not None:
                raise ReportExportCommitValidationError(
                    "copyable_text destination must not carry a path."
                )
        else:
            raise ReportExportCommitValidationError(
                "destination kind must be file or copyable_text."
            )


@dataclass(frozen=True, slots=True)
class CommittedReportExport:
    """Verified result of one explicit teacher export commit."""

    receipt: StoredExportReceipt
    preview: BuiltExportPreview
    artifact_disposition: ReportExportArtifactDisposition
    destination_path: Path | None = field(default=None, repr=False)
    copyable_text: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, StoredExportReceipt):
            raise ReportExportCommitValidationError(
                "receipt must be StoredExportReceipt."
            )
        if not isinstance(self.preview, BuiltExportPreview):
            raise ReportExportCommitValidationError(
                "preview must be BuiltExportPreview."
            )
        if self.receipt.receipt.preview_sha256 != self.preview.preview.preview_sha256:
            raise ReportExportCommitValidationError(
                "receipt must identify the returned exact preview."
            )
        if self.receipt.receipt.payload_sha256 != self.preview.preview.payload_sha256:
            raise ReportExportCommitValidationError(
                "receipt must identify the returned exact payload."
            )
        if self.artifact_disposition in {"created", "existing"}:
            if not isinstance(self.destination_path, Path):
                raise ReportExportCommitValidationError(
                    "file artifact disposition requires destination_path."
                )
            if self.copyable_text is not None:
                raise ReportExportCommitValidationError(
                    "file export must not carry copyable_text."
                )
        elif self.artifact_disposition == "copyable":
            if self.destination_path is not None or not isinstance(
                self.copyable_text,
                str,
            ):
                raise ReportExportCommitValidationError(
                    "copyable export requires exact text and no destination path."
                )
        else:
            raise ReportExportCommitValidationError(
                "artifact disposition is invalid."
            )


def file_export_destination(path: str | Path) -> ReportExportCommitDestination:
    """Create one runtime file destination without retaining it in provenance."""

    if not isinstance(path, (str, Path)):
        raise ReportExportCommitValidationError(
            "file export path must be a string or Path."
        )
    return ReportExportCommitDestination("file", Path(path))


def copyable_text_destination() -> ReportExportCommitDestination:
    """Create one no-clipboard copyable-text destination."""

    return ReportExportCommitDestination("copyable_text", None)


def commit_report_export(
    workspace_root: str | Path,
    *,
    export_id: str,
    approved_preview: ExportPreview,
    destination: ReportExportCommitDestination,
    actor: ReportExportActor,
    rationale: str | None,
    exported_at: datetime,
) -> CommittedReportExport:
    """Revalidate exact sources, deliver payload, and record immutable receipt.

    The approved preview is a teacher-visible commitment boundary.  Final commit
    rebuilds it from its exact snapshot/profile references.  Any digest-level
    difference, including selected roster-value drift, fails before delivery.
    """

    preview = validate_export_preview(approved_preview)
    if not isinstance(destination, ReportExportCommitDestination):
        raise ReportExportCommitValidationError(
            "destination must be ReportExportCommitDestination."
        )
    if not isinstance(actor, ReportExportActor):
        raise ReportExportCommitValidationError(
            "actor must be ReportExportActor."
        )

    try:
        rebuilt = build_export_preview(
            workspace_root,
            preview.snapshot_reference,
            preview.profile_reference,
        )
    except ReportExportPreviewError as error:
        raise ReportExportCurrentnessConflictError(
            "Exact export sources could not be revalidated at commit."
        ) from error
    if export_preview_to_json_bytes(rebuilt.preview) != (
        export_preview_to_json_bytes(preview)
    ):
        raise ReportExportCurrentnessConflictError(
            "Final export preview no longer matches the teacher-approved preview."
        )

    destination_receipt = _destination_receipt(destination)
    receipt_value = export_receipt_from_preview(
        export_id=export_id,
        preview=rebuilt.preview,
        roster_observation=rebuilt.roster_observation,
        destination=destination_receipt,
        actor=actor,
        rationale=rationale,
        exported_at=exported_at,
    )

    existing_receipt = _load_existing_receipt_if_any(
        workspace_root,
        receipt_value,
    )
    if existing_receipt is not None:
        return _replay_existing_receipt(
            existing_receipt,
            rebuilt,
            destination,
        )

    if destination.kind == "file":
        assert destination.path is not None
        disposition = _write_or_verify_file(destination.path, rebuilt.payload)
        try:
            stored = write_export_receipt(workspace_root, receipt_value).stored
        except ReportExportReceiptError as error:
            raise ReportExportCommitReceiptError(
                "Export artifact is exact, but receipt persistence failed."
            ) from error
        return CommittedReportExport(
            receipt=stored,
            preview=rebuilt,
            artifact_disposition=disposition,
            destination_path=_absolute_path(destination.path),
            copyable_text=None,
        )

    copyable_text = _payload_text(rebuilt.payload)
    try:
        stored = write_export_receipt(workspace_root, receipt_value).stored
    except ReportExportReceiptError as error:
        raise ReportExportCommitReceiptError(
            "Copyable payload is exact, but receipt persistence failed."
        ) from error
    return CommittedReportExport(
        receipt=stored,
        preview=rebuilt,
        artifact_disposition="copyable",
        destination_path=None,
        copyable_text=copyable_text,
    )


def _load_existing_receipt_if_any(
    workspace_root: str | Path,
    expected: ExportReceipt,
) -> StoredExportReceipt | None:
    try:
        stored = load_export_receipt(
            workspace_root,
            expected.class_id,
            expected.export_id,
        )
    except ReportExportReceiptNotFoundError:
        return None
    except ReportExportReceiptError as error:
        raise ReportExportCommitReceiptError(
            "Existing ExportReceipt state is unavailable or invalid."
        ) from error
    if stored.receipt != expected:
        raise ReportExportCommitReceiptError(
            "Export identity already has a different immutable receipt."
        )
    return stored


def _replay_existing_receipt(
    stored: StoredExportReceipt,
    rebuilt: BuiltExportPreview,
    destination: ReportExportCommitDestination,
) -> CommittedReportExport:
    receipt = stored.receipt
    if destination.kind == "file":
        assert destination.path is not None
        path = _absolute_path(destination.path)
        if receipt.destination.basename != path.name:
            raise ReportExportCommitReceiptError(
                "Existing receipt destination basename differs from requested file."
            )
        _verify_existing_file(path, rebuilt.payload)
        return CommittedReportExport(
            receipt=stored,
            preview=rebuilt,
            artifact_disposition="existing",
            destination_path=path,
            copyable_text=None,
        )
    if receipt.destination.kind != "copyable_text":
        raise ReportExportCommitReceiptError(
            "Existing receipt destination kind differs from requested replay."
        )
    return CommittedReportExport(
        receipt=stored,
        preview=rebuilt,
        artifact_disposition="copyable",
        destination_path=None,
        copyable_text=_payload_text(rebuilt.payload),
    )


def _destination_receipt(
    destination: ReportExportCommitDestination,
) -> ReportExportDestinationReceipt:
    if destination.kind == "file":
        assert destination.path is not None
        path = _absolute_path(destination.path)
        return ReportExportDestinationReceipt("file", path.name)
    return ReportExportDestinationReceipt("copyable_text", None)


def _write_or_verify_file(path: Path, payload: bytes) -> Literal["created", "existing"]:
    target = _absolute_path(path)
    _validate_destination_parent(target.parent)
    if target.is_symlink():
        raise ReportExportArtifactIntegrityError(
            "Export destination must not be a symlink."
        )
    if target.exists():
        _verify_existing_file(target, payload)
        return "existing"

    descriptor: int | None = None
    try:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(target, flags, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("zero-byte write while creating export artifact")
            written += count
        os.fsync(descriptor)
    except FileExistsError:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        _verify_existing_file(target, payload)
        return "existing"
    except OSError as error:
        raise ReportExportArtifactWriteError(
            "Could not create export destination file."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)

    _fsync_directory_if_supported(target.parent)
    _verify_existing_file(target, payload)
    return "created"


def _verify_existing_file(path: Path, payload: bytes) -> None:
    target = _absolute_path(path)
    _validate_destination_parent(target.parent)
    if target.is_symlink():
        raise ReportExportArtifactIntegrityError(
            "Export destination must not be a symlink."
        )
    try:
        if not target.is_file():
            raise ReportExportArtifactIntegrityError(
                "Export destination must be a regular file."
            )
        content = target.read_bytes()
    except ReportExportCommitError:
        raise
    except FileNotFoundError as error:
        raise ReportExportArtifactIntegrityError(
            "Receipt identifies a file export, but destination file is missing."
        ) from error
    except OSError as error:
        raise ReportExportArtifactIntegrityError(
            "Could not verify export destination file."
        ) from error
    if len(content) != len(payload):
        raise ReportExportArtifactConflictError(
            "Export destination already contains different bytes."
        )
    if hashlib.sha256(content).hexdigest() != hashlib.sha256(payload).hexdigest():
        raise ReportExportArtifactConflictError(
            "Export destination already contains different bytes."
        )
    if content != payload:
        raise ReportExportArtifactConflictError(
            "Export destination already contains different bytes."
        )


def _validate_destination_parent(parent: Path) -> None:
    path = _absolute_path(parent)
    if not path.exists():
        raise ReportExportArtifactWriteError(
            "Export destination parent directory does not exist."
        )
    if path.is_symlink() or not path.is_dir():
        raise ReportExportArtifactIntegrityError(
            "Export destination parent must be a real directory."
        )
    current = path
    while True:
        if current.is_symlink():
            raise ReportExportArtifactIntegrityError(
                "Export destination directory chain must not contain symlinks."
            )
        parent_path = current.parent
        if parent_path == current:
            break
        current = parent_path


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError, OSError) as error:
        raise ReportExportCommitValidationError(
            "Export destination path is invalid."
        ) from error


def _payload_text(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise ReportExportCommitValidationError(
            "export payload must be immutable bytes."
        )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportExportArtifactIntegrityError(
            "Copyable export payload is not valid UTF-8 text."
        ) from error


def _fsync_directory_if_supported(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


__all__ = [
    "CommittedReportExport",
    "ReportExportArtifactConflictError",
    "ReportExportArtifactDisposition",
    "ReportExportArtifactIntegrityError",
    "ReportExportArtifactWriteError",
    "ReportExportCommitDestination",
    "ReportExportCommitDestinationKind",
    "ReportExportCommitError",
    "ReportExportCommitReceiptError",
    "ReportExportCommitValidationError",
    "ReportExportCurrentnessConflictError",
    "commit_report_export",
    "copyable_text_destination",
    "file_export_destination",
]
