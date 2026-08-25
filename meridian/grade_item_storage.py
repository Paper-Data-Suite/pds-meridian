"""Canonical immutable storage for Meridian Grade Item revisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.grade_items import (
    GradeItemRevision,
    GradeItemSerializationError,
    GradeItemValidationError,
    grade_item_revision_from_json_bytes,
    grade_item_revision_to_json_bytes,
    validate_grade_item_revision,
    validate_grade_item_revision_transition,
)

GRADE_ITEM_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GRADE_ITEM_CURRENT_RECORD_TYPE: Final[str] = "meridian_grade_item_current"
DEFAULT_MAXIMUM_GRADE_ITEM_REVISION_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_GRADE_ITEM_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GRADE_ITEM_DIGEST_BYTES: Final[int] = 128

GradeItemWriteDisposition: TypeAlias = Literal["created", "existing"]
GradeItemSelectionDisposition: TypeAlias = Literal["created", "updated", "existing"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([1-9]\d*)\.json\.sha256$"
)
_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "revision_sha256",
    }
)


class GradeItemStorageError(RuntimeError):
    """Base error for Grade Item persistence failures."""

    code: str = "grade_items.storage_error"


class GradeItemStorageValidationError(GradeItemStorageError, ValueError):
    """Raised for invalid storage API arguments."""

    code = "grade_items.storage_invalid"


class GradeItemStorageNotFoundError(GradeItemStorageError):
    """Raised when explicitly requested Grade Item state is absent."""

    code = "grade_items.not_found"


class GradeItemStorageReadError(GradeItemStorageError):
    """Raised when Grade Item state cannot be read safely."""

    code = "grade_items.read_failed"


class GradeItemStorageWriteError(GradeItemStorageError):
    """Raised when Grade Item state cannot be written safely."""

    code = "grade_items.write_failed"


class GradeItemStorageConflictError(GradeItemStorageError):
    """Raised for stale writes or identity/content collisions."""

    code = "grade_items.conflict"


class GradeItemStorageLockError(GradeItemStorageConflictError):
    """Raised when another writer owns one logical Grade Item."""

    code = "grade_items.locked"


class GradeItemStorageIntegrityError(GradeItemStorageError):
    """Raised when canonical paths, bytes, digests, or identities disagree."""

    code = "grade_items.integrity"


class GradeItemStorageTooLargeError(GradeItemStorageReadError):
    """Raised before a Grade Item file can be read without a finite bound."""

    code = "grade_items.too_large"


@dataclass(frozen=True, slots=True)
class StoredGradeItemRevision:
    """One verified immutable Grade Item revision and its exact stored bytes."""

    revision: GradeItemRevision
    revision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.revision, GradeItemRevision):
            raise GradeItemStorageValidationError(
                "revision must be a GradeItemRevision."
            )
        digest = _sha256(self.revision_sha256, "revision_sha256")
        if type(self.content) is not bytes:
            raise GradeItemStorageValidationError("content must be immutable bytes.")
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GradeItemStorageValidationError(
                "revision_sha256 does not match exact stored bytes."
            )
        try:
            decoded = grade_item_revision_from_json_bytes(self.content)
        except (GradeItemSerializationError, GradeItemValidationError) as error:
            raise GradeItemStorageValidationError(
                "content is not a canonical Grade Item revision."
            ) from error
        if decoded != self.revision:
            raise GradeItemStorageValidationError(
                "content does not decode to revision."
            )
        if grade_item_revision_to_json_bytes(self.revision) != self.content:
            raise GradeItemStorageValidationError(
                "content is not the canonical encoding of revision."
            )
        expected = grade_item_revision_relative_path(
            self.revision.class_id,
            self.revision.grade_item_id,
            self.revision.grade_item_revision,
        )
        if self.relative_path != expected:
            raise GradeItemStorageValidationError(
                "relative_path is not the canonical revision location."
            )
        if self.path.name != f"{self.revision.grade_item_revision}.json":
            raise GradeItemStorageValidationError(
                "path filename does not match revision identity."
            )
        object.__setattr__(self, "revision_sha256", digest)


@dataclass(frozen=True, slots=True)
class GradeItemRevisionWriteResult:
    """Result of immutable Grade Item revision persistence."""

    disposition: GradeItemWriteDisposition
    stored: StoredGradeItemRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise GradeItemStorageValidationError("write disposition is invalid.")
        if not isinstance(self.stored, StoredGradeItemRevision):
            raise GradeItemStorageValidationError(
                "stored must be a StoredGradeItemRevision."
            )


@dataclass(frozen=True, slots=True)
class GradeItemCurrentSelection:
    """Explicit mutable selector for one already-persisted immutable revision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    grade_item_revision: int
    revision_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_ITEM_CURRENT_SCHEMA_VERSION:
            raise GradeItemStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != GRADE_ITEM_CURRENT_RECORD_TYPE:
            raise GradeItemStorageValidationError(
                'current record_type must be "meridian_grade_item_current".'
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "grade_item_revision",
            _positive_int(self.grade_item_revision, "grade_item_revision"),
        )
        object.__setattr__(
            self,
            "revision_sha256",
            _sha256(self.revision_sha256, "revision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GradeItemSelectionResult:
    """Result of explicit current-revision selection."""

    disposition: GradeItemSelectionDisposition
    selection: GradeItemCurrentSelection
    stored: StoredGradeItemRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "updated", "existing"}:
            raise GradeItemStorageValidationError(
                "selection disposition is invalid."
            )
        if not isinstance(self.selection, GradeItemCurrentSelection):
            raise GradeItemStorageValidationError(
                "selection must be a GradeItemCurrentSelection."
            )
        if not isinstance(self.stored, StoredGradeItemRevision):
            raise GradeItemStorageValidationError(
                "stored must be a StoredGradeItemRevision."
            )
        revision = self.stored.revision
        if (
            self.selection.class_id != revision.class_id
            or self.selection.grade_item_id != revision.grade_item_id
            or self.selection.grade_item_revision != revision.grade_item_revision
        ):
            raise GradeItemStorageValidationError(
                "selection identity must match stored revision identity."
            )
        if self.selection.revision_sha256 != self.stored.revision_sha256:
            raise GradeItemStorageValidationError(
                "selection digest must match stored revision digest."
            )


def grade_items_directory(workspace_root: str | Path, class_id: str) -> Path:
    """Return the canonical collection root for one class's Grade Items."""
    class_value = _identifier(class_id, "class_id")
    root = _root(workspace_root)
    path = class_module_dir(root, class_value, "meridian") / "grade_items"
    _require_lexical_containment(root, path)
    return path


def grade_item_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> Path:
    """Return one logical Grade Item's canonical storage root."""
    item = _identifier(grade_item_id, "grade_item_id")
    return grade_items_directory(workspace_root, class_id) / item


def grade_item_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> Path:
    """Return the immutable revision collection for one logical Grade Item."""
    return grade_item_directory(workspace_root, class_id, grade_item_id) / "revisions"


def grade_item_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
) -> Path:
    """Return the exact canonical JSON path for one immutable revision."""
    revision = _positive_int(grade_item_revision, "grade_item_revision")
    return grade_item_revisions_directory(
        workspace_root, class_id, grade_item_id
    ) / f"{revision}.json"


def grade_item_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
) -> Path:
    """Return the exact SHA-256 sidecar path for one immutable revision."""
    return Path(
        str(
            grade_item_revision_path(
                workspace_root,
                class_id,
                grade_item_id,
                grade_item_revision,
            )
        )
        + ".sha256"
    )


def grade_item_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> Path:
    """Return the explicit selected-revision pointer path."""
    return (
        grade_item_directory(workspace_root, class_id, grade_item_id)
        / "current.json"
    )


def grade_item_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
) -> str:
    """Return the workspace-relative canonical revision path."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    revision = _positive_int(grade_item_revision, "grade_item_revision")
    return (
        f"classes/{class_value}/modules/meridian/grade_items/"
        f"{item}/revisions/{revision}.json"
    )


def load_grade_item_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GRADE_ITEM_REVISION_BYTES,
) -> StoredGradeItemRevision:
    """Load and verify one exact immutable Grade Item revision."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    revision_number = _positive_int(grade_item_revision, "grade_item_revision")
    root = _root(workspace_root)
    path = grade_item_revision_path(root, class_value, item, revision_number)
    digest_path = grade_item_revision_digest_path(
        root, class_value, item, revision_number
    )
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path,
        maximum_revision_bytes,
        missing_message="Grade Item revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_GRADE_ITEM_DIGEST_BYTES,
        missing_message="Grade Item revision digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise GradeItemStorageIntegrityError(
            "Grade Item revision digest does not match exact JSON bytes."
        )
    try:
        revision = grade_item_revision_from_json_bytes(content)
    except (GradeItemSerializationError, GradeItemValidationError) as error:
        raise GradeItemStorageIntegrityError(
            f"Grade Item revision is invalid or noncanonical: {error}"
        ) from error
    if revision.class_id != class_value:
        raise GradeItemStorageIntegrityError(
            "Persisted Grade Item class_id does not match its canonical path."
        )
    if revision.grade_item_id != item:
        raise GradeItemStorageIntegrityError(
            "Persisted Grade Item identity does not match its canonical path."
        )
    if revision.grade_item_revision != revision_number:
        raise GradeItemStorageIntegrityError(
            "Persisted Grade Item revision does not match its canonical path."
        )
    return StoredGradeItemRevision(
        revision=revision,
        revision_sha256=actual_digest,
        path=path,
        relative_path=grade_item_revision_relative_path(
            class_value, item, revision_number
        ),
        content=content,
    )


def list_grade_item_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> tuple[int, ...]:
    """List and fully verify contiguous immutable revisions in numeric order."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    root = _root(workspace_root)
    item_dir = grade_item_directory(root, class_value, item)
    if not item_dir.exists():
        return ()
    _validate_existing_directory_chain(root, item_dir)
    _validate_item_directory_entries(item_dir)
    revisions_dir = item_dir / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise GradeItemStorageReadError(
            "Could not enumerate Grade Item revision storage."
        ) from error
    for entry in entries:
        if entry.is_symlink():
            raise GradeItemStorageIntegrityError(
                "Grade Item revision storage contains a symlink."
            )
        if not entry.is_file():
            raise GradeItemStorageIntegrityError(
                "Grade Item revision storage contains a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise GradeItemStorageIntegrityError(
                "Grade Item revision storage contains an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise GradeItemStorageIntegrityError(
            "Grade Item revision JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GradeItemStorageIntegrityError(
            "Grade Item revision history is not contiguous from revision 1."
        )
    previous: GradeItemRevision | None = None
    for number in revisions:
        stored = load_grade_item_revision(root, class_value, item, number)
        if previous is not None:
            try:
                validate_grade_item_revision_transition(previous, stored.revision)
            except GradeItemValidationError as error:
                raise GradeItemStorageIntegrityError(
                    f"Grade Item revision history is invalid: {error}"
                ) from error
        previous = stored.revision
    return revisions


def list_grade_item_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """List canonical Grade Item logical identities deterministically."""
    class_value = _identifier(class_id, "class_id")
    root = _root(workspace_root)
    collection = grade_items_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    ids: list[str] = []
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise GradeItemStorageReadError(
            "Could not enumerate Grade Item collection."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise GradeItemStorageIntegrityError(
                "Grade Item collection contains an unexpected non-directory entry."
            )
        item = _identifier(entry.name, "grade_item_id")
        _validate_item_directory_entries(entry)
        revisions = list_grade_item_revisions(root, class_value, item)
        if not revisions:
            raise GradeItemStorageIntegrityError(
                "Grade Item directory exists without immutable revision history."
            )
        ids.append(item)
    return tuple(sorted(ids))


def write_grade_item_revision(
    workspace_root: str | Path,
    revision: GradeItemRevision,
) -> GradeItemRevisionWriteResult:
    """Persist one new immutable revision without changing current selection."""
    try:
        candidate = validate_grade_item_revision(revision)
    except GradeItemValidationError:
        raise
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    item_dir = grade_item_directory(root, candidate.class_id, candidate.grade_item_id)
    revisions_dir = item_dir / "revisions"
    _ensure_directory_chain(root, revisions_dir)
    lock = item_dir / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_item_directory_entries(item_dir)
        content = grade_item_revision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_GRADE_ITEM_REVISION_BYTES:
            raise GradeItemStorageWriteError(
                "Grade Item revision exceeds the canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()
        target = grade_item_revision_path(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.grade_item_revision,
        )
        digest_target = grade_item_revision_digest_path(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.grade_item_revision,
        )
        if target.exists() or digest_target.exists():
            try:
                stored = load_grade_item_revision(
                    root,
                    candidate.class_id,
                    candidate.grade_item_id,
                    candidate.grade_item_revision,
                )
            except GradeItemStorageError as error:
                raise GradeItemStorageIntegrityError(
                    "Existing Grade Item revision identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.revision_sha256 != digest:
                raise GradeItemStorageConflictError(
                    "Grade Item revision identity already exists with "
                    "different content."
                )
            return GradeItemRevisionWriteResult(
                disposition="existing",
                stored=stored,
            )
        history = list_grade_item_revisions(
            root, candidate.class_id, candidate.grade_item_id
        )
        if not history:
            if candidate.grade_item_revision != 1:
                raise GradeItemStorageConflictError(
                    "Initial Grade Item revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.grade_item_revision != expected:
                raise GradeItemStorageConflictError(
                    "Grade Item revision must be exactly one greater than "
                    "current history."
                )
            previous = load_grade_item_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                history[-1],
            ).revision
            try:
                validate_grade_item_revision_transition(previous, candidate)
            except GradeItemValidationError as error:
                raise GradeItemStorageConflictError(str(error)) from error
        _write_revision_pair_exclusively(target, digest_target, content, digest)
        stored = load_grade_item_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.grade_item_revision,
        )
        if stored.content != content or stored.revision_sha256 != digest:
            raise GradeItemStorageIntegrityError(
                "Persisted Grade Item revision differs from candidate bytes."
            )
        return GradeItemRevisionWriteResult(disposition="created", stored=stored)
    finally:
        _remove_lock(lock)


def get_current_grade_item_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> int | None:
    """Return only the explicitly selected revision number, if any."""
    selection = _load_current_selection(
        workspace_root,
        class_id,
        grade_item_id,
        missing_ok=True,
    )
    return selection.grade_item_revision if selection is not None else None


def load_current_grade_item_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> StoredGradeItemRevision | None:
    """Load the explicitly selected immutable revision and verify its digest."""
    selection = _load_current_selection(
        workspace_root,
        class_id,
        grade_item_id,
        missing_ok=True,
    )
    if selection is None:
        return None
    stored = load_grade_item_revision(
        workspace_root,
        selection.class_id,
        selection.grade_item_id,
        selection.grade_item_revision,
    )
    if stored.revision_sha256 != selection.revision_sha256:
        raise GradeItemStorageIntegrityError(
            "Current Grade Item pointer digest does not match selected revision."
        )
    return stored


def select_grade_item_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    grade_item_revision: int,
    *,
    expected_current_revision: int | None,
) -> GradeItemSelectionResult:
    """Explicitly select one persisted revision using compare-and-swap semantics."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    revision_number = _positive_int(grade_item_revision, "grade_item_revision")
    expected = (
        None
        if expected_current_revision is None
        else _positive_int(expected_current_revision, "expected_current_revision")
    )
    root = _root(workspace_root)
    item_dir = grade_item_directory(root, class_value, item)
    _validate_existing_directory_chain(root, item_dir)
    lock = item_dir / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_item_directory_entries(item_dir)
        target = load_grade_item_revision(
            root, class_value, item, revision_number
        )
        current = _load_current_selection(
            root, class_value, item, missing_ok=True
        )
        current_revision = (
            current.grade_item_revision if current is not None else None
        )
        if current_revision != expected:
            raise GradeItemStorageConflictError(
                "Expected current Grade Item revision does not match stored selection."
            )
        selection = GradeItemCurrentSelection(
            schema_version=GRADE_ITEM_CURRENT_SCHEMA_VERSION,
            record_type=GRADE_ITEM_CURRENT_RECORD_TYPE,
            class_id=class_value,
            grade_item_id=item,
            grade_item_revision=revision_number,
            revision_sha256=target.revision_sha256,
        )
        if current == selection:
            return GradeItemSelectionResult(
                disposition="existing",
                selection=selection,
                stored=target,
            )
        _publish_current_selection(root, selection)
        verified = _load_current_selection(root, class_value, item, missing_ok=False)
        if verified != selection:
            raise GradeItemStorageIntegrityError(
                "Published Grade Item selection could not be verified."
            )
        disposition: GradeItemSelectionDisposition = (
            "created" if current is None else "updated"
        )
        return GradeItemSelectionResult(
            disposition=disposition,
            selection=selection,
            stored=target,
        )
    finally:
        _remove_lock(lock)


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    *,
    missing_ok: bool,
) -> GradeItemCurrentSelection | None:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    root = _root(workspace_root)
    item_dir = grade_item_directory(root, class_value, item)
    if not item_dir.exists():
        if missing_ok:
            return None
        raise GradeItemStorageNotFoundError("Grade Item does not exist.")
    _validate_existing_directory_chain(root, item_dir)
    _validate_item_directory_entries(item_dir)
    path = item_dir / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise GradeItemStorageNotFoundError(
            "Grade Item has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_GRADE_ITEM_POINTER_BYTES,
        missing_message="Grade Item current pointer does not exist.",
    )
    selection = _current_selection_from_json_bytes(content)
    if selection.class_id != class_value or selection.grade_item_id != item:
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer identity does not match its canonical path."
        )
    return selection


def _current_selection_to_dict(
    value: GradeItemCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "revision_sha256": value.revision_sha256,
    }


def _current_selection_to_json_bytes(value: GradeItemCurrentSelection) -> bytes:
    return _canonical_json_bytes(_current_selection_to_dict(value))


def _current_selection_from_json_bytes(data: bytes) -> GradeItemCurrentSelection:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except GradeItemStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer is not valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer does not use the exact schema."
        )
    revision_value = decoded["grade_item_revision"]
    try:
        selection = GradeItemCurrentSelection(
            schema_version=_pointer_str(
                decoded["schema_version"], "schema_version"
            ),
            record_type=_pointer_str(decoded["record_type"], "record_type"),
            class_id=_pointer_str(decoded["class_id"], "class_id"),
            grade_item_id=_pointer_str(
                decoded["grade_item_id"], "grade_item_id"
            ),
            grade_item_revision=_positive_int(
                revision_value, "grade_item_revision"
            ),
            revision_sha256=_pointer_str(
                decoded["revision_sha256"], "revision_sha256"
            ),
        )
    except GradeItemStorageValidationError as error:
        raise GradeItemStorageIntegrityError(
            f"Grade Item current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer is not canonically encoded."
        )
    return selection


def _publish_current_selection(
    workspace_root: str | Path,
    selection: GradeItemCurrentSelection,
) -> None:
    path = grade_item_current_path(
        workspace_root,
        selection.class_id,
        selection.grade_item_id,
    )
    if path.exists() and path.is_symlink():
        raise GradeItemStorageIntegrityError(
            "Grade Item current pointer must not be a symlink."
        )
    content = _current_selection_to_json_bytes(selection)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_directory_if_supported(path.parent)
    except OSError as error:
        raise GradeItemStorageWriteError(
            "Could not publish Grade Item current selection."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _write_revision_pair_exclusively(
    path: Path,
    digest_path: Path,
    content: bytes,
    digest: str,
) -> None:
    json_created = False
    digest_created = False
    try:
        with path.open("xb") as output:
            json_created = True
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        with digest_path.open("xb") as output:
            digest_created = True
            output.write((digest + "\n").encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory_if_supported(path.parent)
    except FileExistsError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise GradeItemStorageConflictError(
            "Grade Item revision identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise GradeItemStorageWriteError(
            "Could not persist Grade Item revision and digest."
        ) from error


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise GradeItemStorageNotFoundError(
            "Core class workspace must exist before Grade Item creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_item_directory_entries(item_dir: Path) -> None:
    if item_dir.is_symlink() or not item_dir.is_dir():
        raise GradeItemStorageIntegrityError(
            "Grade Item canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(item_dir.iterdir())
    except OSError as error:
        raise GradeItemStorageReadError(
            "Could not inspect Grade Item canonical root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise GradeItemStorageIntegrityError(
                "Grade Item canonical root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GradeItemStorageIntegrityError(
                    "Grade Item revisions entry must be a real directory."
                )
        elif entry.name == "current.json":
            if entry.is_symlink() or not entry.is_file():
                raise GradeItemStorageIntegrityError(
                    "Grade Item current pointer must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise GradeItemStorageIntegrityError(
                "Grade Item lock entry must be a regular file."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise GradeItemStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise GradeItemStorageNotFoundError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise GradeItemStorageIntegrityError(
            "Workspace root must be a real directory, not a symlink."
        )
    return root


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise GradeItemStorageIntegrityError(
                    "Grade Item directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise GradeItemStorageWriteError(
                    "Could not create Grade Item directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise GradeItemStorageNotFoundError(
                "Required Grade Item directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise GradeItemStorageIntegrityError(
                "Grade Item directory chain is unsafe."
            )


def _require_lexical_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GradeItemStorageValidationError(
            "Grade Item path escapes the supplied workspace root."
        ) from error


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise GradeItemStorageIntegrityError(
            "Grade Item storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise GradeItemStorageIntegrityError(
                    "Grade Item storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except GradeItemStorageError:
        raise
    except FileNotFoundError as error:
        raise GradeItemStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise GradeItemStorageReadError(
            "Could not read Grade Item storage file."
        ) from error
    if len(content) > limit:
        raise GradeItemStorageTooLargeError(
            "Grade Item storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise GradeItemStorageIntegrityError(
            "Grade Item SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise GradeItemStorageIntegrityError(
            "Grade Item SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "revision_sha256")
    except GradeItemStorageValidationError as error:
        raise GradeItemStorageIntegrityError(
            "Grade Item SHA-256 sidecar digest is invalid."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian grade item write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise GradeItemStorageLockError(
            "A Grade Item writer already owns this logical item."
        ) from error
    except OSError as error:
        raise GradeItemStorageWriteError(
            "Could not acquire Grade Item write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise GradeItemStorageWriteError(
            "Could not remove Grade Item write lock."
        ) from error


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _fsync_directory_if_supported(path: Path) -> None:
    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= cast(int, getattr(os, "O_DIRECTORY"))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise GradeItemStorageValidationError(
            "Grade Item selection cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradeItemStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise GradeItemStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemStorageValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradeItemStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeItemStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradeItemStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemStorageIntegrityError(
            f"Grade Item pointer {field_name} must be a string."
        )
    return value
