"""Immutable content-addressed storage for #39 grouping-signal previews.

This module persists exact Meridian preview snapshots. It has no current or
latest pointer, does not resolve academic source state, does not create Core
GroupingSignalSet records, does not export CSV, and does not invoke Concord.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.grouping_signal_preview import (
    MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES,
    GroupingSignalPreviewReference,
    GroupingSignalPreviewSerializationError,
    GroupingSignalPreviewSnapshot,
    GroupingSignalPreviewValidationError,
    grouping_signal_preview_reference,
    grouping_signal_preview_snapshot_from_json_bytes,
    grouping_signal_preview_snapshot_to_json_bytes,
)

DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES: Final[int] = (
    MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_DIGEST_BYTES: Final[int] = 128

GroupingSignalPreviewWriteDisposition: TypeAlias = Literal["created", "existing"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_PREVIEW_JSON: Final[re.Pattern[str]] = re.compile(
    r"^(gsp_[0-9a-f]{64})\.json$"
)
_PREVIEW_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^(gsp_[0-9a-f]{64})\.json\.sha256$"
)


class GroupingSignalPreviewStorageError(RuntimeError):
    """Base error for immutable #39 preview persistence."""

    code: str = "grouping_signal_preview.storage_error"


class GroupingSignalPreviewStorageValidationError(
    GroupingSignalPreviewStorageError,
    ValueError,
):
    """Raised for invalid preview-storage API arguments."""

    code = "grouping_signal_preview.storage_invalid"


class GroupingSignalPreviewStorageNotFoundError(
    GroupingSignalPreviewStorageError
):
    """Raised when one explicitly requested preview does not exist."""

    code = "grouping_signal_preview.not_found"


class GroupingSignalPreviewStorageReadError(GroupingSignalPreviewStorageError):
    """Raised when preview state cannot be read safely."""

    code = "grouping_signal_preview.read_failed"


class GroupingSignalPreviewStorageWriteError(GroupingSignalPreviewStorageError):
    """Raised when preview state cannot be persisted safely."""

    code = "grouping_signal_preview.write_failed"


class GroupingSignalPreviewStorageConflictError(
    GroupingSignalPreviewStorageError
):
    """Raised for immutable identity/content collisions."""

    code = "grouping_signal_preview.conflict"


class GroupingSignalPreviewStorageLockError(
    GroupingSignalPreviewStorageConflictError
):
    """Raised when another writer owns the class preview collection."""

    code = "grouping_signal_preview.locked"


class GroupingSignalPreviewStorageIntegrityError(
    GroupingSignalPreviewStorageError
):
    """Raised when persisted preview state fails integrity checks."""

    code = "grouping_signal_preview.integrity_failed"


class GroupingSignalPreviewStorageTooLargeError(
    GroupingSignalPreviewStorageReadError
):
    """Raised when persisted preview state exceeds bounded read limits."""

    code = "grouping_signal_preview.too_large"


@dataclass(frozen=True, slots=True)
class StoredGroupingSignalPreview:
    """One verified exact immutable #39 preview snapshot."""

    snapshot: GroupingSignalPreviewSnapshot
    preview_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, GroupingSignalPreviewSnapshot):
            raise GroupingSignalPreviewStorageValidationError(
                "snapshot must be a GroupingSignalPreviewSnapshot."
            )
        digest = _sha256(self.preview_sha256, "preview_sha256")
        if type(self.content) is not bytes:
            raise GroupingSignalPreviewStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GroupingSignalPreviewStorageValidationError(
                "preview_sha256 does not match exact immutable content."
            )
        try:
            decoded = grouping_signal_preview_snapshot_from_json_bytes(
                self.content
            )
        except (
            GroupingSignalPreviewSerializationError,
            GroupingSignalPreviewValidationError,
        ) as error:
            raise GroupingSignalPreviewStorageValidationError(
                "content is not a canonical grouping-signal preview."
            ) from error
        if decoded != self.snapshot:
            raise GroupingSignalPreviewStorageValidationError(
                "content does not decode to the stored preview snapshot."
            )
        expected = grouping_signal_preview_relative_path(
            self.snapshot.derivation_reference.class_id,
            self.snapshot.preview_id,
        )
        if self.relative_path != expected:
            raise GroupingSignalPreviewStorageValidationError(
                "relative_path is not the canonical preview location."
            )
        if self.path.name != f"{self.snapshot.preview_id}.json":
            raise GroupingSignalPreviewStorageValidationError(
                "path filename does not match preview identity."
            )
        object.__setattr__(self, "preview_sha256", digest)

    @property
    def reference(self) -> GroupingSignalPreviewReference:
        """Return exact class/identity/digest provenance for this stored snapshot."""
        return GroupingSignalPreviewReference(
            class_id=self.snapshot.derivation_reference.class_id,
            preview_id=self.snapshot.preview_id,
            preview_sha256=self.preview_sha256,
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewWriteResult:
    """Result of an immutable content-addressed preview write."""

    disposition: GroupingSignalPreviewWriteDisposition
    stored: StoredGroupingSignalPreview


def grouping_signal_previews_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local Meridian #39 preview collection path."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "grouping_signal_previews"
    )
    _require_containment(root, path)
    return path


def grouping_signal_preview_path(
    workspace_root: str | Path,
    class_id: str,
    preview_id: str,
) -> Path:
    """Return the canonical JSON path for one exact preview identity."""
    preview = _preview_id(preview_id)
    return grouping_signal_previews_directory(
        workspace_root,
        class_id,
    ) / f"{preview}.json"


def grouping_signal_preview_relative_path(
    class_id: str,
    preview_id: str,
) -> str:
    """Return the canonical workspace-relative path for one preview."""
    class_value = _identifier(class_id, "class_id")
    preview = _preview_id(preview_id)
    return (
        f"classes/{class_value}/modules/meridian/grouping_signal_previews/"
        f"{preview}.json"
    )


def write_grouping_signal_preview(
    workspace_root: str | Path,
    snapshot: GroupingSignalPreviewSnapshot,
) -> GroupingSignalPreviewWriteResult:
    """Persist one immutable content-addressed preview snapshot."""
    if not isinstance(snapshot, GroupingSignalPreviewSnapshot):
        raise GroupingSignalPreviewStorageValidationError(
            "snapshot must be a GroupingSignalPreviewSnapshot."
        )
    try:
        content = grouping_signal_preview_snapshot_to_json_bytes(snapshot)
        expected_reference = grouping_signal_preview_reference(snapshot)
    except (
        GroupingSignalPreviewSerializationError,
        GroupingSignalPreviewValidationError,
    ) as error:
        raise GroupingSignalPreviewStorageValidationError(str(error)) from error

    root = _root(workspace_root)
    collection = grouping_signal_previews_directory(
        root,
        snapshot.derivation_reference.class_id,
    )
    _ensure_directory_chain(root, collection)
    lock = collection / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_preview_collection(collection, allow_lock=True)
        target = grouping_signal_preview_path(
            root,
            snapshot.derivation_reference.class_id,
            snapshot.preview_id,
        )
        digest_target = Path(str(target) + ".sha256")
        digest = expected_reference.preview_sha256

        if target.exists() or digest_target.exists():
            try:
                stored = load_grouping_signal_preview(
                    root,
                    snapshot.derivation_reference.class_id,
                    snapshot.preview_id,
                )
            except GroupingSignalPreviewStorageError as error:
                raise GroupingSignalPreviewStorageIntegrityError(
                    "Existing preview identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.preview_sha256 != digest:
                raise GroupingSignalPreviewStorageConflictError(
                    "Preview identity already exists with different content."
                )
            return GroupingSignalPreviewWriteResult("existing", stored)

        _write_pair(root, target, digest_target, content, digest)
        stored = load_grouping_signal_preview(
            root,
            snapshot.derivation_reference.class_id,
            snapshot.preview_id,
        )
        if stored.content != content or stored.preview_sha256 != digest:
            raise GroupingSignalPreviewStorageIntegrityError(
                "Persisted preview differs from candidate canonical bytes."
            )
        return GroupingSignalPreviewWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grouping_signal_preview(
    workspace_root: str | Path,
    class_id: str,
    preview_id: str,
    *,
    maximum_preview_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES,
) -> StoredGroupingSignalPreview:
    """Load and verify one exact immutable preview by identity."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    preview = _preview_id(preview_id)
    maximum = _positive_int(maximum_preview_bytes, "maximum_preview_bytes")
    collection = grouping_signal_previews_directory(root, class_value)
    if not collection.exists():
        raise GroupingSignalPreviewStorageNotFoundError(
            "Grouping-signal preview collection does not exist."
        )
    _validate_preview_collection(collection, allow_lock=True)
    path = grouping_signal_preview_path(root, class_value, preview)
    content, digest = _read_pair(root, path, maximum)
    try:
        model = grouping_signal_preview_snapshot_from_json_bytes(content)
    except (
        GroupingSignalPreviewSerializationError,
        GroupingSignalPreviewValidationError,
    ) as error:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Grouping-signal preview is invalid or noncanonical."
        ) from error
    if (
        model.derivation_reference.class_id != class_value
        or model.preview_id != preview
    ):
        raise GroupingSignalPreviewStorageIntegrityError(
            "Persisted preview identity does not match its canonical path."
        )
    return StoredGroupingSignalPreview(
        snapshot=model,
        preview_sha256=digest,
        path=path,
        relative_path=grouping_signal_preview_relative_path(
            class_value,
            preview,
        ),
        content=content,
    )


def load_grouping_signal_preview_reference(
    workspace_root: str | Path,
    reference: GroupingSignalPreviewReference,
    *,
    maximum_preview_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES,
) -> StoredGroupingSignalPreview:
    """Load one exact preview and require the requested canonical digest."""
    if not isinstance(reference, GroupingSignalPreviewReference):
        raise GroupingSignalPreviewStorageValidationError(
            "reference must be a GroupingSignalPreviewReference."
        )
    reference.__post_init__()
    stored = load_grouping_signal_preview(
        workspace_root,
        reference.class_id,
        reference.preview_id,
        maximum_preview_bytes=maximum_preview_bytes,
    )
    if stored.preview_sha256 != reference.preview_sha256:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Stored preview digest does not match the requested exact reference."
        )
    return stored


def list_grouping_signal_preview_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """Return verified preview IDs in deterministic lexical order."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = grouping_signal_previews_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_preview_collection(collection, allow_lock=True)
    ids = _collection_ids(collection)
    for preview_id in ids:
        load_grouping_signal_preview(root, class_value, preview_id)
    return ids


def _collection_ids(collection: Path) -> tuple[str, ...]:
    json_ids: set[str] = set()
    digest_ids: set[str] = set()
    for entry in _directory_entries(collection):
        if entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise GroupingSignalPreviewStorageIntegrityError(
                    "Preview write lock is not a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalPreviewStorageIntegrityError(
                "Preview collection contains an unexpected non-file entry."
            )
        json_match = _PREVIEW_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_ids.add(_preview_id(json_match.group(1)))
            continue
        digest_match = _PREVIEW_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_ids.add(_preview_id(digest_match.group(1)))
            continue
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview collection contains an unexpected visible entry."
        )
    if json_ids != digest_ids:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview JSON and SHA-256 sidecars must form complete pairs."
        )
    return tuple(sorted(json_ids))


def _validate_preview_collection(collection: Path, *, allow_lock: bool) -> None:
    if collection.is_symlink():
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview collection must not be a symlink."
        )
    if not collection.is_dir():
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview collection must be a directory."
        )
    for entry in _directory_entries(collection):
        if entry.name == ".write.lock" and allow_lock:
            if entry.is_symlink() or not entry.is_file():
                raise GroupingSignalPreviewStorageIntegrityError(
                    "Preview write lock is not a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalPreviewStorageIntegrityError(
                "Preview collection contains an unexpected non-file entry."
            )
        if (
            _PREVIEW_JSON.fullmatch(entry.name) is None
            and _PREVIEW_DIGEST.fullmatch(entry.name) is None
        ):
            raise GroupingSignalPreviewStorageIntegrityError(
                "Preview collection contains an unexpected visible entry."
            )


def _read_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() and not digest_path.exists():
        raise GroupingSignalPreviewStorageNotFoundError(
            "Requested grouping-signal preview does not exist."
        )
    if not path.exists() or not digest_path.exists():
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview JSON and SHA-256 sidecar must both exist."
        )
    content = _bounded_read(root, path, maximum, "preview JSON")
    digest_bytes = _bounded_read(
        root,
        digest_path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_DIGEST_BYTES,
        "preview SHA-256 sidecar",
    )
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview SHA-256 sidecar must be ASCII."
        ) from error
    if not digest_text.endswith("\n") or digest_text.count("\n") != 1:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview SHA-256 sidecar must contain one canonical line."
        )
    digest = digest_text[:-1]
    if _SHA256.fullmatch(digest) is None:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview SHA-256 sidecar contains an invalid digest."
        )
    if digest_bytes != f"{digest}\n".encode("ascii"):
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview SHA-256 sidecar is not canonical."
        )
    actual = hashlib.sha256(content).hexdigest()
    if actual != digest:
        raise GroupingSignalPreviewStorageIntegrityError(
            "Preview SHA-256 sidecar does not match JSON bytes."
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
    if len(content) > DEFAULT_MAXIMUM_GROUPING_SIGNAL_PREVIEW_BYTES:
        raise GroupingSignalPreviewStorageWriteError(
            "Preview canonical JSON exceeds the bounded storage maximum."
        )
    digest_content = f"{_sha256(digest, 'preview_sha256')}\n".encode("ascii")
    json_temp = _temporary_path(target)
    digest_temp = _temporary_path(digest_target)
    try:
        _write_new_file(json_temp, content)
        _write_new_file(digest_temp, digest_content)
        os.replace(json_temp, target)
        os.replace(digest_temp, digest_target)
    except OSError as error:
        raise GroupingSignalPreviewStorageWriteError(
            "Could not atomically persist preview JSON/SHA-256 pair."
        ) from error
    finally:
        _unlink_if_exists(json_temp)
        _unlink_if_exists(digest_temp)


def _bounded_read(root: Path, path: Path, maximum: int, label: str) -> bytes:
    _require_containment(root, path)
    _validate_existing_directory_chain(root, path.parent)
    if path.is_symlink():
        raise GroupingSignalPreviewStorageIntegrityError(
            f"{label} must not be a symlink."
        )
    try:
        stat = path.stat()
    except OSError as error:
        raise GroupingSignalPreviewStorageReadError(
            f"Could not inspect {label}."
        ) from error
    if not path.is_file():
        raise GroupingSignalPreviewStorageIntegrityError(
            f"{label} must be a regular file."
        )
    if stat.st_size > maximum:
        raise GroupingSignalPreviewStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GroupingSignalPreviewStorageReadError(
            f"Could not read {label}."
        ) from error
    if len(data) > maximum:
        raise GroupingSignalPreviewStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    return data


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise GroupingSignalPreviewStorageLockError(
            "Preview write lock path is a symlink."
        )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise GroupingSignalPreviewStorageLockError(
            "Another writer owns the grouping-signal preview collection."
        ) from error
    except OSError as error:
        raise GroupingSignalPreviewStorageWriteError(
            "Could not acquire grouping-signal preview write lock."
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
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
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
        raise GroupingSignalPreviewStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise GroupingSignalPreviewStorageIntegrityError(
                    "Preview storage directory chain contains an unsafe entry."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise GroupingSignalPreviewStorageWriteError(
                "Could not create preview storage directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalPreviewStorageIntegrityError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise GroupingSignalPreviewStorageIntegrityError(
                "Preview storage directory chain contains an unsafe entry."
            )


def _directory_entries(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GroupingSignalPreviewStorageReadError(
            "Could not enumerate grouping-signal preview storage."
        ) from error


def _root(value: str | Path) -> Path:
    try:
        root = Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise GroupingSignalPreviewStorageValidationError(
            "workspace_root must be a valid filesystem path."
        ) from error
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise GroupingSignalPreviewStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    return root


def _require_containment(root: Path, path: Path) -> None:
    try:
        common = Path(os.path.commonpath((root, path)))
    except ValueError as error:
        raise GroupingSignalPreviewStorageValidationError(
            "Storage path must remain inside workspace_root."
        ) from error
    if common != root:
        raise GroupingSignalPreviewStorageValidationError(
            "Storage path must remain inside workspace_root."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPreviewStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalPreviewStorageValidationError(str(error)) from error


def _preview_id(value: object) -> str:
    preview = _identifier(value, "preview_id")
    if _PREVIEW_JSON.fullmatch(f"{preview}.json") is None:
        raise GroupingSignalPreviewStorageValidationError(
            "preview_id must be gsp_ followed by a lowercase SHA-256 digest."
        )
    return preview


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise GroupingSignalPreviewStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalPreviewStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
