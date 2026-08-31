"""Immutable content-addressed storage for #38 grouping-signal derivations.

This module persists exact Meridian derivation snapshots. It has no current or
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

from meridian.grouping_signal_derivation import (
    MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES,
    GroupingSignalDerivationReference,
    GroupingSignalDerivationSerializationError,
    GroupingSignalDerivationSnapshot,
    GroupingSignalDerivationValidationError,
    grouping_signal_derivation_reference,
    grouping_signal_derivation_snapshot_from_json_bytes,
    grouping_signal_derivation_snapshot_to_json_bytes,
)

DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES: Final[int] = (
    MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_DIGEST_BYTES: Final[int] = 128

GroupingSignalDerivationWriteDisposition: TypeAlias = Literal["created", "existing"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DERIVATION_JSON: Final[re.Pattern[str]] = re.compile(
    r"^(gsd_[0-9a-f]{64})\.json$"
)
_DERIVATION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^(gsd_[0-9a-f]{64})\.json\.sha256$"
)


class GroupingSignalDerivationStorageError(RuntimeError):
    """Base error for immutable #38 derivation persistence."""

    code: str = "grouping_signal_derivation.storage_error"


class GroupingSignalDerivationStorageValidationError(
    GroupingSignalDerivationStorageError,
    ValueError,
):
    """Raised for invalid derivation-storage API arguments."""

    code = "grouping_signal_derivation.storage_invalid"


class GroupingSignalDerivationStorageNotFoundError(
    GroupingSignalDerivationStorageError
):
    """Raised when one explicitly requested derivation does not exist."""

    code = "grouping_signal_derivation.not_found"


class GroupingSignalDerivationStorageReadError(GroupingSignalDerivationStorageError):
    """Raised when derivation state cannot be read safely."""

    code = "grouping_signal_derivation.read_failed"


class GroupingSignalDerivationStorageWriteError(GroupingSignalDerivationStorageError):
    """Raised when derivation state cannot be persisted safely."""

    code = "grouping_signal_derivation.write_failed"


class GroupingSignalDerivationStorageConflictError(
    GroupingSignalDerivationStorageError
):
    """Raised for immutable identity/content collisions."""

    code = "grouping_signal_derivation.conflict"


class GroupingSignalDerivationStorageLockError(
    GroupingSignalDerivationStorageConflictError
):
    """Raised when another writer owns the class derivation collection."""

    code = "grouping_signal_derivation.locked"


class GroupingSignalDerivationStorageIntegrityError(
    GroupingSignalDerivationStorageError
):
    """Raised when persisted derivation state fails integrity checks."""

    code = "grouping_signal_derivation.integrity_failed"


class GroupingSignalDerivationStorageTooLargeError(
    GroupingSignalDerivationStorageReadError
):
    """Raised when persisted derivation state exceeds bounded read limits."""

    code = "grouping_signal_derivation.too_large"


@dataclass(frozen=True, slots=True)
class StoredGroupingSignalDerivation:
    """One verified exact immutable #38 derivation snapshot."""

    snapshot: GroupingSignalDerivationSnapshot
    derivation_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, GroupingSignalDerivationSnapshot):
            raise GroupingSignalDerivationStorageValidationError(
                "snapshot must be a GroupingSignalDerivationSnapshot."
            )
        digest = _sha256(self.derivation_sha256, "derivation_sha256")
        if type(self.content) is not bytes:
            raise GroupingSignalDerivationStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GroupingSignalDerivationStorageValidationError(
                "derivation_sha256 does not match exact immutable content."
            )
        try:
            decoded = grouping_signal_derivation_snapshot_from_json_bytes(
                self.content
            )
        except (
            GroupingSignalDerivationSerializationError,
            GroupingSignalDerivationValidationError,
        ) as error:
            raise GroupingSignalDerivationStorageValidationError(
                "content is not a canonical grouping-signal derivation."
            ) from error
        if decoded != self.snapshot:
            raise GroupingSignalDerivationStorageValidationError(
                "content does not decode to the stored derivation snapshot."
            )
        expected = grouping_signal_derivation_relative_path(
            self.snapshot.class_id,
            self.snapshot.derivation_id,
        )
        if self.relative_path != expected:
            raise GroupingSignalDerivationStorageValidationError(
                "relative_path is not the canonical derivation location."
            )
        if self.path.name != f"{self.snapshot.derivation_id}.json":
            raise GroupingSignalDerivationStorageValidationError(
                "path filename does not match derivation identity."
            )
        object.__setattr__(self, "derivation_sha256", digest)

    @property
    def reference(self) -> GroupingSignalDerivationReference:
        """Return exact class/identity/digest provenance for this stored snapshot."""
        return GroupingSignalDerivationReference(
            class_id=self.snapshot.class_id,
            derivation_id=self.snapshot.derivation_id,
            derivation_sha256=self.derivation_sha256,
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalDerivationWriteResult:
    """Result of an immutable content-addressed derivation write."""

    disposition: GroupingSignalDerivationWriteDisposition
    stored: StoredGroupingSignalDerivation


def grouping_signal_derivations_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local Meridian #38 derivation collection path."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "grouping_signal_derivations"
    )
    _require_containment(root, path)
    return path


def grouping_signal_derivation_path(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> Path:
    """Return the canonical JSON path for one exact derivation identity."""
    derivation = _derivation_id(derivation_id)
    return grouping_signal_derivations_directory(
        workspace_root,
        class_id,
    ) / f"{derivation}.json"


def grouping_signal_derivation_relative_path(
    class_id: str,
    derivation_id: str,
) -> str:
    """Return the canonical workspace-relative path for one derivation."""
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    return (
        f"classes/{class_value}/modules/meridian/grouping_signal_derivations/"
        f"{derivation}.json"
    )


def write_grouping_signal_derivation(
    workspace_root: str | Path,
    snapshot: GroupingSignalDerivationSnapshot,
) -> GroupingSignalDerivationWriteResult:
    """Persist one immutable content-addressed derivation snapshot."""
    if not isinstance(snapshot, GroupingSignalDerivationSnapshot):
        raise GroupingSignalDerivationStorageValidationError(
            "snapshot must be a GroupingSignalDerivationSnapshot."
        )
    try:
        content = grouping_signal_derivation_snapshot_to_json_bytes(snapshot)
        expected_reference = grouping_signal_derivation_reference(snapshot)
    except (
        GroupingSignalDerivationSerializationError,
        GroupingSignalDerivationValidationError,
    ) as error:
        raise GroupingSignalDerivationStorageValidationError(str(error)) from error

    root = _root(workspace_root)
    collection = grouping_signal_derivations_directory(root, snapshot.class_id)
    _ensure_directory_chain(root, collection)
    lock = collection / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_derivation_collection(collection, allow_lock=True)
        target = grouping_signal_derivation_path(
            root,
            snapshot.class_id,
            snapshot.derivation_id,
        )
        digest_target = Path(str(target) + ".sha256")
        digest = expected_reference.derivation_sha256

        if target.exists() or digest_target.exists():
            try:
                stored = load_grouping_signal_derivation(
                    root,
                    snapshot.class_id,
                    snapshot.derivation_id,
                )
            except GroupingSignalDerivationStorageError as error:
                raise GroupingSignalDerivationStorageIntegrityError(
                    "Existing derivation identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.derivation_sha256 != digest:
                raise GroupingSignalDerivationStorageConflictError(
                    "Derivation identity already exists with different content."
                )
            return GroupingSignalDerivationWriteResult("existing", stored)

        _write_pair(root, target, digest_target, content, digest)
        stored = load_grouping_signal_derivation(
            root,
            snapshot.class_id,
            snapshot.derivation_id,
        )
        if stored.content != content or stored.derivation_sha256 != digest:
            raise GroupingSignalDerivationStorageIntegrityError(
                "Persisted derivation differs from candidate canonical bytes."
            )
        return GroupingSignalDerivationWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grouping_signal_derivation(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    *,
    maximum_derivation_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES,
) -> StoredGroupingSignalDerivation:
    """Load and verify one exact immutable derivation by identity."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    derivation = _derivation_id(derivation_id)
    maximum = _positive_int(maximum_derivation_bytes, "maximum_derivation_bytes")
    collection = grouping_signal_derivations_directory(root, class_value)
    if not collection.exists():
        raise GroupingSignalDerivationStorageNotFoundError(
            "Grouping-signal derivation collection does not exist."
        )
    _validate_derivation_collection(collection, allow_lock=True)
    path = grouping_signal_derivation_path(root, class_value, derivation)
    content, digest = _read_pair(root, path, maximum)
    try:
        model = grouping_signal_derivation_snapshot_from_json_bytes(content)
    except (
        GroupingSignalDerivationSerializationError,
        GroupingSignalDerivationValidationError,
    ) as error:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Grouping-signal derivation is invalid or noncanonical."
        ) from error
    if model.class_id != class_value or model.derivation_id != derivation:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Persisted derivation identity does not match its canonical path."
        )
    return StoredGroupingSignalDerivation(
        snapshot=model,
        derivation_sha256=digest,
        path=path,
        relative_path=grouping_signal_derivation_relative_path(
            class_value,
            derivation,
        ),
        content=content,
    )


def load_grouping_signal_derivation_reference(
    workspace_root: str | Path,
    reference: GroupingSignalDerivationReference,
    *,
    maximum_derivation_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES,
) -> StoredGroupingSignalDerivation:
    """Load one exact derivation and require the requested canonical digest."""
    if not isinstance(reference, GroupingSignalDerivationReference):
        raise GroupingSignalDerivationStorageValidationError(
            "reference must be a GroupingSignalDerivationReference."
        )
    reference.__post_init__()
    stored = load_grouping_signal_derivation(
        workspace_root,
        reference.class_id,
        reference.derivation_id,
        maximum_derivation_bytes=maximum_derivation_bytes,
    )
    if stored.derivation_sha256 != reference.derivation_sha256:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Stored derivation digest does not match the requested exact reference."
        )
    return stored


def list_grouping_signal_derivation_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """Return verified derivation IDs in deterministic lexical order."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = grouping_signal_derivations_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_derivation_collection(collection, allow_lock=True)
    ids = _collection_ids(collection)
    for derivation_id in ids:
        load_grouping_signal_derivation(root, class_value, derivation_id)
    return ids


def _collection_ids(collection: Path) -> tuple[str, ...]:
    json_ids: set[str] = set()
    digest_ids: set[str] = set()
    for entry in _directory_entries(collection):
        if entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise GroupingSignalDerivationStorageIntegrityError(
                    "Derivation write lock is not a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalDerivationStorageIntegrityError(
                "Derivation collection contains an unexpected non-file entry."
            )
        json_match = _DERIVATION_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_ids.add(_derivation_id(json_match.group(1)))
            continue
        digest_match = _DERIVATION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_ids.add(_derivation_id(digest_match.group(1)))
            continue
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation collection contains an unexpected visible entry."
        )
    if json_ids != digest_ids:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation JSON and SHA-256 sidecars must form complete pairs."
        )
    return tuple(sorted(json_ids))


def _validate_derivation_collection(collection: Path, *, allow_lock: bool) -> None:
    if collection.is_symlink():
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation collection must not be a symlink."
        )
    if not collection.is_dir():
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation collection must be a directory."
        )
    for entry in _directory_entries(collection):
        if entry.name == ".write.lock" and allow_lock:
            if entry.is_symlink() or not entry.is_file():
                raise GroupingSignalDerivationStorageIntegrityError(
                    "Derivation write lock is not a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalDerivationStorageIntegrityError(
                "Derivation collection contains an unexpected non-file entry."
            )
        if (
            _DERIVATION_JSON.fullmatch(entry.name) is None
            and _DERIVATION_DIGEST.fullmatch(entry.name) is None
        ):
            raise GroupingSignalDerivationStorageIntegrityError(
                "Derivation collection contains an unexpected visible entry."
            )


def _read_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() and not digest_path.exists():
        raise GroupingSignalDerivationStorageNotFoundError(
            "Requested grouping-signal derivation does not exist."
        )
    if not path.exists() or not digest_path.exists():
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation JSON and SHA-256 sidecar must both exist."
        )
    content = _bounded_read(root, path, maximum, "derivation JSON")
    digest_bytes = _bounded_read(
        root,
        digest_path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_DIGEST_BYTES,
        "derivation SHA-256 sidecar",
    )
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation SHA-256 sidecar must be ASCII."
        ) from error
    if not digest_text.endswith("\n") or digest_text.count("\n") != 1:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation SHA-256 sidecar must contain one canonical line."
        )
    digest = digest_text[:-1]
    if _SHA256.fullmatch(digest) is None:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation SHA-256 sidecar contains an invalid digest."
        )
    if digest_bytes != f"{digest}\n".encode("ascii"):
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation SHA-256 sidecar is not canonical."
        )
    actual = hashlib.sha256(content).hexdigest()
    if actual != digest:
        raise GroupingSignalDerivationStorageIntegrityError(
            "Derivation SHA-256 sidecar does not match JSON bytes."
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
    if len(content) > DEFAULT_MAXIMUM_GROUPING_SIGNAL_DERIVATION_BYTES:
        raise GroupingSignalDerivationStorageWriteError(
            "Derivation canonical JSON exceeds the bounded storage maximum."
        )
    digest_content = f"{_sha256(digest, 'derivation_sha256')}\n".encode("ascii")
    json_temp = _temporary_path(target)
    digest_temp = _temporary_path(digest_target)
    try:
        _write_new_file(json_temp, content)
        _write_new_file(digest_temp, digest_content)
        os.replace(json_temp, target)
        os.replace(digest_temp, digest_target)
    except OSError as error:
        raise GroupingSignalDerivationStorageWriteError(
            "Could not atomically persist derivation JSON/SHA-256 pair."
        ) from error
    finally:
        _unlink_if_exists(json_temp)
        _unlink_if_exists(digest_temp)


def _bounded_read(root: Path, path: Path, maximum: int, label: str) -> bytes:
    _require_containment(root, path)
    _validate_existing_directory_chain(root, path.parent)
    if path.is_symlink():
        raise GroupingSignalDerivationStorageIntegrityError(
            f"{label} must not be a symlink."
        )
    try:
        stat = path.stat()
    except OSError as error:
        raise GroupingSignalDerivationStorageReadError(
            f"Could not inspect {label}."
        ) from error
    if not path.is_file():
        raise GroupingSignalDerivationStorageIntegrityError(
            f"{label} must be a regular file."
        )
    if stat.st_size > maximum:
        raise GroupingSignalDerivationStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GroupingSignalDerivationStorageReadError(
            f"Could not read {label}."
        ) from error
    if len(data) > maximum:
        raise GroupingSignalDerivationStorageTooLargeError(
            f"{label} exceeds the bounded read maximum."
        )
    return data


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise GroupingSignalDerivationStorageLockError(
            "Derivation write lock path is a symlink."
        )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise GroupingSignalDerivationStorageLockError(
            "Another writer owns the grouping-signal derivation collection."
        ) from error
    except OSError as error:
        raise GroupingSignalDerivationStorageWriteError(
            "Could not acquire grouping-signal derivation write lock."
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
        raise GroupingSignalDerivationStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise GroupingSignalDerivationStorageIntegrityError(
                    "Derivation storage directory chain contains an unsafe entry."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise GroupingSignalDerivationStorageWriteError(
                "Could not create derivation storage directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalDerivationStorageIntegrityError(
            "workspace_root must be an existing non-symlink directory."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise GroupingSignalDerivationStorageIntegrityError(
                "Derivation storage directory chain contains an unsafe entry."
            )


def _directory_entries(path: Path) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GroupingSignalDerivationStorageReadError(
            "Could not enumerate grouping-signal derivation storage."
        ) from error


def _root(value: str | Path) -> Path:
    try:
        root = Path(os.path.abspath(os.fspath(value)))
    except (TypeError, ValueError, OSError) as error:
        raise GroupingSignalDerivationStorageValidationError(
            "workspace_root must be a valid filesystem path."
        ) from error
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise GroupingSignalDerivationStorageValidationError(
            "workspace_root must be an existing non-symlink directory."
        )
    return root


def _require_containment(root: Path, path: Path) -> None:
    try:
        common = Path(os.path.commonpath((root, path)))
    except ValueError as error:
        raise GroupingSignalDerivationStorageValidationError(
            "Storage path must remain inside workspace_root."
        ) from error
    if common != root:
        raise GroupingSignalDerivationStorageValidationError(
            "Storage path must remain inside workspace_root."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalDerivationStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalDerivationStorageValidationError(str(error)) from error


def _derivation_id(value: object) -> str:
    derivation = _identifier(value, "derivation_id")
    if _DERIVATION_JSON.fullmatch(f"{derivation}.json") is None:
        raise GroupingSignalDerivationStorageValidationError(
            "derivation_id must be gsd_ followed by a lowercase SHA-256 digest."
        )
    return derivation


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise GroupingSignalDerivationStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalDerivationStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
