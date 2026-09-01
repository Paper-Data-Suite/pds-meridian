"""Immutable class-local storage for #40 grouping-signal export receipts."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.grouping_signal_storage import (
    GroupingSignalStorageError,
    load_grouping_signal,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_export_receipt import (
    MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES,
    GroupingSignalExportReceipt,
    GroupingSignalExportReceiptReference,
    GroupingSignalExportReceiptSerializationError,
    GroupingSignalExportReceiptValidationError,
    grouping_signal_export_receipt_from_json_bytes,
    grouping_signal_export_receipt_reference,
    grouping_signal_export_receipt_to_json_bytes,
    validate_grouping_signal_export_receipt,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    load_grouping_signal_review_revision,
)

DEFAULT_MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES: Final[int] = (
    MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_BYTES: Final[int] = 128

GroupingSignalExportReceiptWriteDisposition: TypeAlias = Literal[
    "created",
    "existing",
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class GroupingSignalExportReceiptStorageError(RuntimeError):
    """Base error for immutable #40 receipt persistence."""


class GroupingSignalExportReceiptStorageValidationError(
    GroupingSignalExportReceiptStorageError,
    ValueError,
):
    """Raised for invalid receipt-storage API arguments."""


class GroupingSignalExportReceiptStorageNotFoundError(
    GroupingSignalExportReceiptStorageError
):
    """Raised when one explicitly requested receipt is absent."""


class GroupingSignalExportReceiptStorageReadError(
    GroupingSignalExportReceiptStorageError
):
    """Raised when receipt state cannot be read safely."""


class GroupingSignalExportReceiptStorageWriteError(
    GroupingSignalExportReceiptStorageError
):
    """Raised when receipt state cannot be persisted safely."""


class GroupingSignalExportReceiptStorageConflictError(
    GroupingSignalExportReceiptStorageError
):
    """Raised when immutable receipt identity collides with different bytes."""


class GroupingSignalExportReceiptStorageIntegrityError(
    GroupingSignalExportReceiptStorageError
):
    """Raised when receipt bytes, paths, or exact dependencies disagree."""


class GroupingSignalExportReceiptStorageLockError(
    GroupingSignalExportReceiptStorageConflictError
):
    """Raised when another writer owns the class receipt collection."""


class GroupingSignalExportReceiptStorageTooLargeError(
    GroupingSignalExportReceiptStorageReadError
):
    """Raised when receipt state exceeds bounded read limits."""


@dataclass(frozen=True, slots=True)
class StoredGroupingSignalExportReceipt:
    receipt: GroupingSignalExportReceipt
    receipt_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, GroupingSignalExportReceipt):
            raise GroupingSignalExportReceiptStorageValidationError(
                "receipt must be a GroupingSignalExportReceipt."
            )
        digest = _sha256(self.receipt_sha256, "receipt_sha256")
        if type(self.content) is not bytes:
            raise GroupingSignalExportReceiptStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GroupingSignalExportReceiptStorageValidationError(
                "receipt_sha256 does not match exact immutable content."
            )
        try:
            decoded = grouping_signal_export_receipt_from_json_bytes(
                self.content
            )
        except (
            GroupingSignalExportReceiptSerializationError,
            GroupingSignalExportReceiptValidationError,
        ) as error:
            raise GroupingSignalExportReceiptStorageValidationError(
                "content is not a canonical grouping-signal export receipt."
            ) from error
        if decoded != self.receipt:
            raise GroupingSignalExportReceiptStorageValidationError(
                "content does not decode to the stored receipt."
            )
        expected = grouping_signal_export_receipt_relative_path(
            self.receipt.class_id,
            self.receipt.signal_set_id,
        )
        if self.relative_path != expected:
            raise GroupingSignalExportReceiptStorageValidationError(
                "relative_path is not the canonical receipt location."
            )
        if self.path.name != f"{self.receipt.signal_set_id}.json":
            raise GroupingSignalExportReceiptStorageValidationError(
                "receipt path filename does not match signal identity."
            )
        object.__setattr__(self, "receipt_sha256", digest)

    @property
    def reference(self) -> GroupingSignalExportReceiptReference:
        return GroupingSignalExportReceiptReference(
            self.receipt.class_id,
            self.receipt.signal_set_id,
            self.receipt_sha256,
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalExportReceiptWriteResult:
    disposition: GroupingSignalExportReceiptWriteDisposition
    stored: StoredGroupingSignalExportReceipt


def grouping_signal_export_receipts_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "grouping_signal_exports"
    )
    _require_containment(root, path)
    return path


def grouping_signal_export_receipt_path(
    workspace_root: str | Path,
    class_id: str,
    signal_set_id: str,
) -> Path:
    signal = _identifier(signal_set_id, "signal_set_id")
    return grouping_signal_export_receipts_directory(
        workspace_root,
        class_id,
    ) / f"{signal}.json"


def grouping_signal_export_receipt_relative_path(
    class_id: str,
    signal_set_id: str,
) -> str:
    class_value = _identifier(class_id, "class_id")
    signal = _identifier(signal_set_id, "signal_set_id")
    return (
        f"classes/{class_value}/modules/meridian/grouping_signal_exports/"
        f"{signal}.json"
    )


def write_grouping_signal_export_receipt(
    workspace_root: str | Path,
    receipt: GroupingSignalExportReceipt,
) -> GroupingSignalExportReceiptWriteResult:
    candidate = validate_grouping_signal_export_receipt(receipt)
    content = grouping_signal_export_receipt_to_json_bytes(candidate)
    expected_reference = grouping_signal_export_receipt_reference(candidate)

    root = _root(workspace_root)
    _validate_receipt_dependencies(root, candidate)
    collection = grouping_signal_export_receipts_directory(
        root,
        candidate.class_id,
    )
    _ensure_directory_chain(root, collection)
    lock = collection / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_collection(collection, allow_lock=True)
        target = grouping_signal_export_receipt_path(
            root,
            candidate.class_id,
            candidate.signal_set_id,
        )
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            try:
                stored = load_grouping_signal_export_receipt(
                    root,
                    candidate.class_id,
                    candidate.signal_set_id,
                )
            except GroupingSignalExportReceiptStorageError as error:
                raise GroupingSignalExportReceiptStorageIntegrityError(
                    "Existing export receipt is incomplete or invalid."
                ) from error
            if (
                stored.content != content
                or stored.receipt_sha256
                != expected_reference.receipt_sha256
            ):
                raise GroupingSignalExportReceiptStorageConflictError(
                    "Export receipt identity already exists with different content."
                )
            return GroupingSignalExportReceiptWriteResult(
                "existing",
                stored,
            )

        _write_pair(
            root,
            target,
            digest_target,
            content,
            expected_reference.receipt_sha256,
        )
        stored = load_grouping_signal_export_receipt(
            root,
            candidate.class_id,
            candidate.signal_set_id,
        )
        if (
            stored.content != content
            or stored.receipt_sha256
            != expected_reference.receipt_sha256
        ):
            raise GroupingSignalExportReceiptStorageIntegrityError(
                "Persisted export receipt differs from candidate canonical bytes."
            )
        return GroupingSignalExportReceiptWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grouping_signal_export_receipt(
    workspace_root: str | Path,
    class_id: str,
    signal_set_id: str,
    *,
    maximum_receipt_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES,
) -> StoredGroupingSignalExportReceipt:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    signal = _identifier(signal_set_id, "signal_set_id")
    maximum = _positive_int(maximum_receipt_bytes, "maximum_receipt_bytes")

    collection = grouping_signal_export_receipts_directory(root, class_value)
    if not collection.exists():
        raise GroupingSignalExportReceiptStorageNotFoundError(
            "Grouping-signal export receipt collection does not exist."
        )
    _validate_collection(collection, allow_lock=True)

    path = grouping_signal_export_receipt_path(
        root,
        class_value,
        signal,
    )
    content, digest = _read_pair(root, path, maximum)
    try:
        receipt = grouping_signal_export_receipt_from_json_bytes(content)
    except (
        GroupingSignalExportReceiptSerializationError,
        GroupingSignalExportReceiptValidationError,
    ) as error:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Grouping-signal export receipt is invalid or noncanonical."
        ) from error
    if receipt.class_id != class_value or receipt.signal_set_id != signal:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Persisted export receipt identity does not match its canonical path."
        )

    _validate_receipt_dependencies(root, receipt)
    return StoredGroupingSignalExportReceipt(
        receipt=receipt,
        receipt_sha256=digest,
        path=path,
        relative_path=grouping_signal_export_receipt_relative_path(
            class_value,
            signal,
        ),
        content=content,
    )


def load_grouping_signal_export_receipt_reference(
    workspace_root: str | Path,
    reference: GroupingSignalExportReceiptReference,
) -> StoredGroupingSignalExportReceipt:
    if not isinstance(reference, GroupingSignalExportReceiptReference):
        raise GroupingSignalExportReceiptStorageValidationError(
            "reference must be a GroupingSignalExportReceiptReference."
        )
    reference.__post_init__()
    stored = load_grouping_signal_export_receipt(
        workspace_root,
        reference.class_id,
        reference.signal_set_id,
    )
    if stored.receipt_sha256 != reference.receipt_sha256:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Stored export receipt digest does not match exact reference."
        )
    return stored


def _validate_receipt_dependencies(
    root: Path,
    receipt: GroupingSignalExportReceipt,
) -> None:
    try:
        derivation = load_grouping_signal_derivation_reference(
            root,
            receipt.derivation_reference,
        )
        preview = load_grouping_signal_preview_reference(
            root,
            receipt.preview_reference,
        )
        review = load_grouping_signal_review_revision(
            root,
            receipt.review_reference.class_id,
            receipt.review_reference.derivation_id,
            receipt.review_reference.review_revision,
        )
        core = load_grouping_signal(
            root,
            receipt.class_id,
            receipt.signal_set_id,
        )
    except (
        GroupingSignalDerivationStorageError,
        GroupingSignalPreviewStorageError,
        GroupingSignalReviewStorageError,
        GroupingSignalStorageError,
    ) as error:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Exact export-receipt dependency is unavailable or invalid."
        ) from error

    if preview.snapshot.derivation_reference != derivation.reference:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Receipt preview does not bind the exact receipt derivation."
        )
    if review.reference != receipt.review_reference:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Receipt review digest does not match the exact review revision."
        )
    if (
        review.review.derivation_reference != derivation.reference
        or review.review.preview_reference != preview.reference
    ):
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Receipt review does not bind the exact derivation/preview."
        )
    if core.digest_algorithm != receipt.core_digest_algorithm:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Core signal digest algorithm does not match the receipt."
        )
    if core.digest != receipt.core_signal_digest:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Core signal digest does not match the receipt."
        )
    signal = core.signal
    if signal.created_at != receipt.created_at:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Core signal created_at does not match the receipt."
        )
    if (
        signal.source.kind != "module_generated"
        or signal.source.module_id != "meridian"
        or signal.source.snapshot_id != derivation.reference.derivation_id
        or signal.source.snapshot_digest_algorithm != "sha256"
        or signal.source.snapshot_digest
        != derivation.reference.derivation_sha256
    ):
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Core signal source does not bind the receipt #38 derivation."
        )


def _read_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() and not digest_path.exists():
        raise GroupingSignalExportReceiptStorageNotFoundError(
            "Requested grouping-signal export receipt does not exist."
        )
    if not path.exists() or not digest_path.exists():
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Receipt JSON and SHA-256 sidecar must both exist."
        )
    content = _bounded_read(root, path, maximum, "export receipt JSON")
    digest_bytes = _bounded_read(
        root,
        digest_path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_BYTES,
        "export receipt SHA-256 sidecar",
    )
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt SHA-256 sidecar must be ASCII."
        ) from error
    if not digest_text.endswith("\n") or digest_text.count("\n") != 1:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt SHA-256 sidecar must contain one canonical line."
        )
    digest = digest_text[:-1]
    if _SHA256.fullmatch(digest) is None:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt SHA-256 sidecar contains an invalid digest."
        )
    if hashlib.sha256(content).hexdigest() != digest:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt SHA-256 sidecar does not match JSON bytes."
        )
    return content, digest


def _write_pair(
    root: Path,
    target: Path,
    digest_target: Path,
    content: bytes,
    digest: str,
) -> None:
    _require_containment(root, target)
    _require_containment(root, digest_target)
    if len(content) > DEFAULT_MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES:
        raise GroupingSignalExportReceiptStorageWriteError(
            "Export receipt exceeds the bounded storage maximum."
        )
    digest_content = f"{_sha256(digest, 'receipt_sha256')}\n".encode("ascii")
    json_temp = _temporary_path(target)
    digest_temp = _temporary_path(digest_target)
    try:
        _write_new_file(json_temp, content)
        _write_new_file(digest_temp, digest_content)
        os.replace(json_temp, target)
        os.replace(digest_temp, digest_target)
    except OSError as error:
        raise GroupingSignalExportReceiptStorageWriteError(
            "Could not atomically persist export receipt JSON/SHA-256 pair."
        ) from error
    finally:
        _unlink_if_exists(json_temp)
        _unlink_if_exists(digest_temp)


def _validate_collection(collection: Path, *, allow_lock: bool) -> None:
    if collection.is_symlink() or not collection.is_dir():
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt collection must be a real directory."
        )
    json_ids: set[str] = set()
    digest_ids: set[str] = set()
    for entry in _directory_entries(collection):
        if entry.name == ".write.lock" and allow_lock:
            if entry.is_symlink() or not entry.is_file():
                raise GroupingSignalExportReceiptStorageIntegrityError(
                    "Export receipt lock must be a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalExportReceiptStorageIntegrityError(
                "Export receipt collection contains an unsafe entry."
            )
        if entry.name.endswith(".json.sha256"):
            identifier = entry.name[: -len(".json.sha256")]
            digest_ids.add(_identifier(identifier, "signal_set_id"))
        elif entry.name.endswith(".json"):
            identifier = entry.name[: -len(".json")]
            json_ids.add(_identifier(identifier, "signal_set_id"))
        else:
            raise GroupingSignalExportReceiptStorageIntegrityError(
                "Export receipt collection contains an unexpected visible entry."
            )
    if json_ids != digest_ids:
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "Export receipt JSON/SHA-256 sidecars must form complete pairs."
        )


def _bounded_read(root: Path, path: Path, maximum: int, label: str) -> bytes:
    _require_containment(root, path)
    _validate_existing_directory_chain(root, path.parent)
    if path.is_symlink():
        raise GroupingSignalExportReceiptStorageIntegrityError(
            f"{label} must not be a symlink."
        )
    try:
        stat = path.stat()
    except OSError as error:
        raise GroupingSignalExportReceiptStorageReadError(
            f"Could not inspect {label}."
        ) from error
    if not path.is_file():
        raise GroupingSignalExportReceiptStorageIntegrityError(
            f"{label} must be a regular file."
        )
    if stat.st_size > maximum:
        raise GroupingSignalExportReceiptStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    try:
        content = path.read_bytes()
    except OSError as error:
        raise GroupingSignalExportReceiptStorageReadError(
            f"Could not read {label}."
        ) from error
    if len(content) > maximum:
        raise GroupingSignalExportReceiptStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    return content


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise GroupingSignalExportReceiptStorageLockError(
            "Export receipt lock path is a symlink."
        )
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as error:
        raise GroupingSignalExportReceiptStorageLockError(
            "Another writer owns the grouping-signal export receipt collection."
        ) from error
    except OSError as error:
        raise GroupingSignalExportReceiptStorageWriteError(
            "Could not acquire export receipt write lock."
        ) from error
    try:
        os.write(descriptor, b"locked\n")
    finally:
        os.close(descriptor)


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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


def _temporary_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalExportReceiptStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise GroupingSignalExportReceiptStorageIntegrityError(
                    "Export receipt directory chain contains an unsafe entry."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise GroupingSignalExportReceiptStorageWriteError(
                "Could not create export receipt storage directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalExportReceiptStorageIntegrityError(
            "workspace_root must be an existing non-symlink directory."
        )
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise GroupingSignalExportReceiptStorageIntegrityError(
                "Export receipt directory chain contains an unsafe entry."
            )


def _directory_entries(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GroupingSignalExportReceiptStorageReadError(
            "Could not enumerate export receipt storage."
        ) from error


def _root(value: str | Path) -> Path:
    try:
        root = Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise GroupingSignalExportReceiptStorageValidationError(
            "workspace_root must be a valid filesystem path."
        ) from error
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise GroupingSignalExportReceiptStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    return root


def _require_containment(root: Path, path: Path) -> None:
    try:
        common = Path(os.path.commonpath((root, path)))
    except ValueError as error:
        raise GroupingSignalExportReceiptStorageValidationError(
            "Storage path must remain inside workspace_root."
        ) from error
    if common != root:
        raise GroupingSignalExportReceiptStorageValidationError(
            "Storage path must remain inside workspace_root."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalExportReceiptStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalExportReceiptStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise GroupingSignalExportReceiptStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalExportReceiptStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
