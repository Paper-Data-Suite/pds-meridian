"""Optional Core-native CSV export for one exact Meridian-exported signal.

CSV is a secondary teacher-local representation. The authoritative shared state
remains the immutable Core ``grouping_signal_set_v1`` plus Meridian's exact
export receipt.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.grouping_signal_csv import (
    GroupingSignalCsvError,
    grouping_signal_csv_to_signal_set,
    grouping_signal_set_to_csv_bytes,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signal_storage import (
    GroupingSignalStorageError,
    load_grouping_signal,
)
from pds_core.grouping_signals import grouping_signal_set_to_json_bytes

from meridian.grouping_signal_export_storage import (
    GroupingSignalExportReceiptStorageError,
    load_grouping_signal_export_receipt,
)

GroupingSignalCsvExportDisposition: TypeAlias = Literal["created", "existing"]


class GroupingSignalCsvExportError(RuntimeError):
    """Base error for optional #40 CSV file export."""


class GroupingSignalCsvExportIntegrityError(GroupingSignalCsvExportError):
    """Exact Core/receipt/CSV round-trip state could not be verified."""

    code = "csv_integrity_failed"


class GroupingSignalCsvExportConflictError(GroupingSignalCsvExportError):
    """Destination already exists with different bytes or unsupported type."""

    code = "csv_destination_conflict"


class GroupingSignalCsvExportWriteError(GroupingSignalCsvExportError):
    """Exact CSV bytes could not be written safely."""

    code = "csv_write_failed"


@dataclass(frozen=True, slots=True)
class GroupingSignalCsvExportResult:
    """Result of one explicit non-overwriting CSV file export."""

    class_id: str
    signal_set_id: str
    destination: Path
    disposition: GroupingSignalCsvExportDisposition
    byte_length: int
    csv_sha256: str

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise GroupingSignalCsvExportIntegrityError(
                "CSV disposition must be created or existing."
            )
        if not isinstance(self.destination, Path):
            raise GroupingSignalCsvExportIntegrityError(
                "destination must be a pathlib.Path."
            )
        if self.byte_length < 1:
            raise GroupingSignalCsvExportIntegrityError(
                "CSV byte_length must be positive."
            )
        if (
            not isinstance(self.csv_sha256, str)
            or len(self.csv_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.csv_sha256)
        ):
            raise GroupingSignalCsvExportIntegrityError(
                "csv_sha256 must be a lowercase SHA-256 digest."
            )


def export_grouping_signal_csv(
    workspace_root: str | Path,
    class_id: str,
    signal_set_id: str,
    destination: str | Path,
) -> GroupingSignalCsvExportResult:
    """Write Core's exact complete-signal CSV to one explicit destination.

    The Core signal and its Meridian export receipt must already exist and
    verify exactly. This operation never mutates Core or receipt state.
    """

    try:
        receipt = load_grouping_signal_export_receipt(
            workspace_root,
            class_id,
            signal_set_id,
        )
        stored = load_grouping_signal(
            workspace_root,
            class_id,
            signal_set_id,
        )
    except (
        GroupingSignalExportReceiptStorageError,
        GroupingSignalStorageError,
    ) as error:
        raise GroupingSignalCsvExportIntegrityError(
            "Exact Meridian receipt/Core signal state is unavailable or invalid."
        ) from error

    if (
        receipt.receipt.core_signal_digest != stored.digest
        or receipt.receipt.core_digest_algorithm != stored.digest_algorithm
    ):
        raise GroupingSignalCsvExportIntegrityError(
            "Meridian receipt does not bind the exact Core signal digest."
        )

    signal = stored.signal
    if len(signal.dimensions) != 1:
        raise GroupingSignalCsvExportIntegrityError(
            "Issue #40 CSV export requires exactly one Core signal dimension."
        )
    dimension_id = signal.dimensions[0].dimension_id

    try:
        csv_bytes = grouping_signal_set_to_csv_bytes(signal, dimension_id)
        document = parse_grouping_signal_csv(csv_bytes)
        if document.representation_scope != "complete_signal":
            raise GroupingSignalCsvExportIntegrityError(
                "One-dimension Meridian export must produce complete_signal CSV."
            )
        reconstructed = grouping_signal_csv_to_signal_set(document)
    except GroupingSignalCsvError as error:
        raise GroupingSignalCsvExportIntegrityError(
            "Core CSV serialization/parse round-trip failed."
        ) from error

    if reconstructed != signal:
        raise GroupingSignalCsvExportIntegrityError(
            "Core CSV round-trip does not reproduce the exact stored signal."
        )
    if (
        grouping_signal_set_to_json_bytes(reconstructed)
        != grouping_signal_set_to_json_bytes(signal)
    ):
        raise GroupingSignalCsvExportIntegrityError(
            "Core CSV round-trip changed canonical grouping-signal JSON bytes."
        )

    target = _destination(destination)
    disposition = _write_exact_bytes(target, csv_bytes)
    return GroupingSignalCsvExportResult(
        class_id=signal.class_id,
        signal_set_id=signal.signal_set_id,
        destination=target,
        disposition=disposition,
        byte_length=len(csv_bytes),
        csv_sha256=hashlib.sha256(csv_bytes).hexdigest(),
    )


def _destination(value: str | Path) -> Path:
    try:
        path = Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise GroupingSignalCsvExportConflictError(
            "CSV destination must be a valid explicit filesystem path."
        ) from error
    parent = path.parent
    if not parent.exists() or parent.is_symlink() or not parent.is_dir():
        raise GroupingSignalCsvExportConflictError(
            "CSV destination parent must be an existing non-symlink directory."
        )
    if path.is_symlink():
        raise GroupingSignalCsvExportConflictError(
            "CSV destination must not be a symlink."
        )
    return path


def _write_exact_bytes(
    path: Path,
    content: bytes,
) -> GroupingSignalCsvExportDisposition:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise GroupingSignalCsvExportConflictError(
                "CSV destination already exists but is not a regular file."
            )
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise GroupingSignalCsvExportWriteError(
                "Could not read existing CSV destination."
            ) from error
        if existing == content:
            return "existing"
        raise GroupingSignalCsvExportConflictError(
            "CSV destination already exists with different bytes."
        )

    try:
        _write_new_file(path, content)
    except FileExistsError:
        return _reconcile_concurrent_destination(path, content)
    except OSError as error:
        _remove_partial_exact_file(path, content)
        raise GroupingSignalCsvExportWriteError(
            "Could not write exact Core grouping-signal CSV bytes."
        ) from error

    try:
        verified = path.read_bytes()
    except OSError as error:
        _remove_partial_exact_file(path, content)
        raise GroupingSignalCsvExportWriteError(
            "Could not verify newly written grouping-signal CSV."
        ) from error
    if verified != content:
        _remove_partial_exact_file(path, content)
        raise GroupingSignalCsvExportWriteError(
            "New grouping-signal CSV differs from the exact Core bytes."
        )
    return "created"


def _write_new_file(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _reconcile_concurrent_destination(
    path: Path,
    content: bytes,
) -> GroupingSignalCsvExportDisposition:
    if path.is_symlink() or not path.is_file():
        raise GroupingSignalCsvExportConflictError(
            "CSV destination appeared concurrently as an unsupported entry."
        )
    try:
        existing = path.read_bytes()
    except OSError as error:
        raise GroupingSignalCsvExportWriteError(
            "Could not verify concurrently created CSV destination."
        ) from error
    if existing == content:
        return "existing"
    raise GroupingSignalCsvExportConflictError(
        "CSV destination appeared concurrently with different bytes."
    )


def _remove_partial_exact_file(path: Path, expected: bytes) -> None:
    try:
        if (
            path.exists()
            and not path.is_symlink()
            and path.is_file()
            and path.read_bytes() == expected
        ):
            path.unlink()
    except OSError:
        pass
