"""Immutable filesystem storage for Meridian v0.3 reporting state.

This module persists only #55-owned reporting definitions and frozen
ReportingSnapshots.  It deliberately does not select a current definition or
snapshot, infer "latest" authority from directory order, or mutate any upstream
Core, producer, Grade, proficiency, policy, or override state.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.reporting_snapshot import (
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
    ReportingDefinitionValidationError,
    ReportingSnapshotReference,
    ReportingSnapshotSerializationError,
    ReportingSnapshotValidationError,
    reporting_definition_reference,
    reporting_definition_revision_from_json_bytes,
    reporting_definition_revision_to_json_bytes,
    validate_reporting_definition_revision,
    validate_reporting_definition_transition,
)
from meridian.reporting_snapshot_record import (
    DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES,
    ReportingSnapshot,
    ReportingSnapshotIntegrityError,
    reporting_snapshot_from_json_bytes,
    reporting_snapshot_reference,
    reporting_snapshot_to_json_bytes,
)

DEFAULT_MAXIMUM_REPORTING_DEFINITION_BYTES: Final[int] = 512 * 1024
DEFAULT_MAXIMUM_REPORTING_DIGEST_BYTES: Final[int] = 128

ReportingStorageWriteDisposition: TypeAlias = Literal["created", "existing"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([1-9]\d*)\.json\.sha256$"
)
_SNAPSHOT_JSON: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z0-9_-]+)\.json$"
)
_SNAPSHOT_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z0-9_-]+)\.json\.sha256$"
)


class ReportingSnapshotStorageError(RuntimeError):
    """Base error for #55 canonical reporting persistence."""

    code: str = "reporting_snapshot.storage_error"


class ReportingSnapshotStorageValidationError(
    ReportingSnapshotStorageError, ValueError
):
    """Raised for invalid storage API arguments."""

    code = "reporting_snapshot.storage_invalid"


class ReportingSnapshotStorageNotFoundError(ReportingSnapshotStorageError):
    """Raised when explicitly requested reporting state is absent."""

    code = "reporting_snapshot.not_found"


class ReportingSnapshotStorageReadError(ReportingSnapshotStorageError):
    """Raised when reporting state cannot be read safely."""

    code = "reporting_snapshot.read_failed"


class ReportingSnapshotStorageWriteError(ReportingSnapshotStorageError):
    """Raised when reporting state cannot be persisted safely."""

    code = "reporting_snapshot.write_failed"


class ReportingSnapshotStorageConflictError(ReportingSnapshotStorageError):
    """Raised for immutable identity/content collisions."""

    code = "reporting_snapshot.conflict"


class ReportingSnapshotStorageLockError(ReportingSnapshotStorageConflictError):
    """Raised when another writer owns one canonical reporting relation."""

    code = "reporting_snapshot.locked"


class ReportingSnapshotStorageIntegrityError(ReportingSnapshotStorageError):
    """Raised when canonical reporting storage fails integrity validation."""

    code = "reporting_snapshot.integrity_failed"


class ReportingSnapshotStorageTooLargeError(ReportingSnapshotStorageReadError):
    """Raised when persisted reporting state exceeds configured read bounds."""

    code = "reporting_snapshot.too_large"


@dataclass(frozen=True, slots=True)
class StoredReportingDefinitionRevision:
    """One verified immutable reporting-definition revision."""

    definition: ReportingDefinitionRevision
    definition_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ReportingDefinitionRevision):
            raise ReportingSnapshotStorageValidationError(
                "definition must be ReportingDefinitionRevision."
            )
        digest = _sha256(self.definition_sha256, "definition_sha256")
        if type(self.content) is not bytes:
            raise ReportingSnapshotStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ReportingSnapshotStorageValidationError(
                "definition_sha256 does not match exact stored bytes."
            )
        try:
            decoded = reporting_definition_revision_from_json_bytes(self.content)
        except (
            ReportingSnapshotSerializationError,
            ReportingDefinitionValidationError,
            ReportingSnapshotValidationError,
        ) as error:
            raise ReportingSnapshotStorageValidationError(
                "content is not a canonical reporting-definition revision."
            ) from error
        if decoded != self.definition:
            raise ReportingSnapshotStorageValidationError(
                "content does not decode to definition."
            )
        expected = reporting_definition_revision_relative_path(
            self.definition.class_id,
            self.definition.definition_id,
            self.definition.definition_revision,
        )
        if self.relative_path != expected:
            raise ReportingSnapshotStorageValidationError(
                "relative_path is not the canonical reporting-definition location."
            )
        if self.path.name != f"{self.definition.definition_revision}.json":
            raise ReportingSnapshotStorageValidationError(
                "path filename does not match reporting-definition revision."
            )
        object.__setattr__(self, "definition_sha256", digest)

    @property
    def reference(self) -> ReportingDefinitionReference:
        """Return the exact digest-bound reference for this stored revision."""

        return ReportingDefinitionReference(
            class_id=self.definition.class_id,
            definition_id=self.definition.definition_id,
            definition_revision=self.definition.definition_revision,
            definition_sha256=self.definition_sha256,
        )


@dataclass(frozen=True, slots=True)
class ReportingDefinitionWriteResult:
    """Result of immutable reporting-definition persistence."""

    disposition: ReportingStorageWriteDisposition
    stored: StoredReportingDefinitionRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ReportingSnapshotStorageValidationError(
                "definition write disposition is invalid."
            )
        if not isinstance(self.stored, StoredReportingDefinitionRevision):
            raise ReportingSnapshotStorageValidationError(
                "stored must be StoredReportingDefinitionRevision."
            )


@dataclass(frozen=True, slots=True)
class StoredReportingSnapshot:
    """One verified immutable ReportingSnapshot and its exact stored bytes."""

    snapshot: ReportingSnapshot
    snapshot_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ReportingSnapshot):
            raise ReportingSnapshotStorageValidationError(
                "snapshot must be ReportingSnapshot."
            )
        digest = _sha256(self.snapshot_sha256, "snapshot_sha256")
        if type(self.content) is not bytes:
            raise ReportingSnapshotStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ReportingSnapshotStorageValidationError(
                "snapshot_sha256 does not match exact stored bytes."
            )
        try:
            decoded = reporting_snapshot_from_json_bytes(self.content)
        except ReportingSnapshotIntegrityError as error:
            raise ReportingSnapshotStorageValidationError(
                "content is not a canonical ReportingSnapshot."
            ) from error
        if decoded != self.snapshot:
            raise ReportingSnapshotStorageValidationError(
                "content does not decode to snapshot."
            )
        expected = reporting_snapshot_relative_path(
            self.snapshot.class_id,
            self.snapshot.snapshot_id,
        )
        if self.relative_path != expected:
            raise ReportingSnapshotStorageValidationError(
                "relative_path is not the canonical ReportingSnapshot location."
            )
        if self.path.name != f"{self.snapshot.snapshot_id}.json":
            raise ReportingSnapshotStorageValidationError(
                "path filename does not match ReportingSnapshot identity."
            )
        object.__setattr__(self, "snapshot_sha256", digest)

    @property
    def reference(self) -> ReportingSnapshotReference:
        """Return the exact digest-bound reference for this stored snapshot."""

        return ReportingSnapshotReference(
            class_id=self.snapshot.class_id,
            snapshot_id=self.snapshot.snapshot_id,
            snapshot_sha256=self.snapshot_sha256,
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotWriteResult:
    """Result of immutable ReportingSnapshot persistence."""

    disposition: ReportingStorageWriteDisposition
    stored: StoredReportingSnapshot

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ReportingSnapshotStorageValidationError(
                "snapshot write disposition is invalid."
            )
        if not isinstance(self.stored, StoredReportingSnapshot):
            raise ReportingSnapshotStorageValidationError(
                "stored must be StoredReportingSnapshot."
            )


def reporting_definitions_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local collection of reporting-definition families."""

    return class_module_dir(
        workspace_root,
        _identifier(class_id, "class_id"),
        "meridian",
    ) / "reporting_definitions"


def reporting_definition_directory(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
) -> Path:
    """Return one reporting-definition family directory."""

    return reporting_definitions_directory(
        workspace_root,
        class_id,
    ) / _identifier(definition_id, "definition_id")


def reporting_definition_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
) -> Path:
    return reporting_definition_directory(
        workspace_root,
        class_id,
        definition_id,
    ) / "revisions"


def reporting_definition_revision_path(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    definition_revision: int,
) -> Path:
    revision = _positive_int(definition_revision, "definition_revision")
    return reporting_definition_revisions_directory(
        workspace_root,
        class_id,
        definition_id,
    ) / f"{revision}.json"


def reporting_definition_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    definition_revision: int,
) -> Path:
    return Path(
        str(
            reporting_definition_revision_path(
                workspace_root,
                class_id,
                definition_id,
                definition_revision,
            )
        )
        + ".sha256"
    )


def reporting_definition_revision_relative_path(
    class_id: str,
    definition_id: str,
    definition_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    definition_value = _identifier(definition_id, "definition_id")
    revision = _positive_int(definition_revision, "definition_revision")
    return (
        f"classes/{class_value}/modules/meridian/reporting_definitions/"
        f"{definition_value}/revisions/{revision}.json"
    )


def reporting_snapshots_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local immutable ReportingSnapshot collection."""

    return class_module_dir(
        workspace_root,
        _identifier(class_id, "class_id"),
        "meridian",
    ) / "reporting_snapshots"


def reporting_snapshot_path(
    workspace_root: str | Path,
    class_id: str,
    snapshot_id: str,
) -> Path:
    return reporting_snapshots_directory(
        workspace_root,
        class_id,
    ) / f"{_identifier(snapshot_id, 'snapshot_id')}.json"


def reporting_snapshot_digest_path(
    workspace_root: str | Path,
    class_id: str,
    snapshot_id: str,
) -> Path:
    return Path(
        str(reporting_snapshot_path(workspace_root, class_id, snapshot_id))
        + ".sha256"
    )


def reporting_snapshot_relative_path(class_id: str, snapshot_id: str) -> str:
    class_value = _identifier(class_id, "class_id")
    snapshot_value = _identifier(snapshot_id, "snapshot_id")
    return (
        f"classes/{class_value}/modules/meridian/reporting_snapshots/"
        f"{snapshot_value}.json"
    )


def write_reporting_definition_revision(
    workspace_root: str | Path,
    definition: ReportingDefinitionRevision,
) -> ReportingDefinitionWriteResult:
    """Persist one immutable definition revision without selecting it."""

    try:
        candidate = validate_reporting_definition_revision(definition)
    except ReportingSnapshotValidationError as error:
        raise ReportingSnapshotStorageValidationError(
            f"reporting definition is invalid: {error}"
        ) from error
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    target = reporting_definition_revision_path(
        root,
        candidate.class_id,
        candidate.definition_id,
        candidate.definition_revision,
    )
    digest_target = reporting_definition_revision_digest_path(
        root,
        candidate.class_id,
        candidate.definition_id,
        candidate.definition_revision,
    )
    relation = reporting_definition_directory(
        root,
        candidate.class_id,
        candidate.definition_id,
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock, "reporting definition")
    try:
        _validate_definition_directory(relation)
        content = reporting_definition_revision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_REPORTING_DEFINITION_BYTES:
            raise ReportingSnapshotStorageWriteError(
                "Reporting-definition revision exceeds the canonical byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()

        if target.exists() or digest_target.exists():
            try:
                stored = load_reporting_definition_revision(
                    root,
                    candidate.class_id,
                    candidate.definition_id,
                    candidate.definition_revision,
                )
            except ReportingSnapshotStorageError as error:
                raise ReportingSnapshotStorageIntegrityError(
                    "Existing reporting-definition identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.definition_sha256 != digest:
                raise ReportingSnapshotStorageConflictError(
                    "Reporting-definition revision identity already exists with "
                    "different content."
                )
            return ReportingDefinitionWriteResult("existing", stored)

        history = list_reporting_definition_revisions(
            root,
            candidate.class_id,
            candidate.definition_id,
        )
        if not history:
            if candidate.definition_revision != 1:
                raise ReportingSnapshotStorageConflictError(
                    "Initial reporting-definition revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.definition_revision != expected:
                raise ReportingSnapshotStorageConflictError(
                    "Reporting-definition revision must be exactly one greater "
                    "than existing history."
                )
            previous = load_reporting_definition_revision(
                root,
                candidate.class_id,
                candidate.definition_id,
                history[-1],
            ).definition
            try:
                validate_reporting_definition_transition(previous, candidate)
            except ReportingDefinitionValidationError as error:
                raise ReportingSnapshotStorageConflictError(str(error)) from error

        _write_pair(target, digest_target, content, digest)
        stored = load_reporting_definition_revision(
            root,
            candidate.class_id,
            candidate.definition_id,
            candidate.definition_revision,
        )
        if stored.content != content or stored.definition_sha256 != digest:
            raise ReportingSnapshotStorageIntegrityError(
                "Persisted reporting-definition revision differs from candidate."
            )
        return ReportingDefinitionWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_reporting_definition_revision(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    definition_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_REPORTING_DEFINITION_BYTES,
) -> StoredReportingDefinitionRevision:
    """Load and verify one exact immutable reporting-definition revision."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    definition_value = _identifier(definition_id, "definition_id")
    revision = _positive_int(definition_revision, "definition_revision")
    maximum = _positive_int(maximum_revision_bytes, "maximum_revision_bytes")
    relation = reporting_definition_directory(
        root,
        class_value,
        definition_value,
    )
    _validate_existing_directory_chain(root, relation)
    _validate_definition_directory(relation)
    path = reporting_definition_revision_path(
        root,
        class_value,
        definition_value,
        revision,
    )
    digest_path = reporting_definition_revision_digest_path(
        root,
        class_value,
        definition_value,
        revision,
    )
    content, digest = _read_pair(
        path,
        digest_path,
        maximum,
        missing_label="Reporting-definition revision",
    )
    try:
        definition = reporting_definition_revision_from_json_bytes(content)
    except (
        ReportingSnapshotSerializationError,
        ReportingDefinitionValidationError,
        ReportingSnapshotValidationError,
    ) as error:
        raise ReportingSnapshotStorageIntegrityError(
            f"Stored reporting-definition revision is invalid: {error}"
        ) from error
    expected_scope = (class_value, definition_value, revision)
    actual_scope = (
        definition.class_id,
        definition.definition_id,
        definition.definition_revision,
    )
    if actual_scope != expected_scope:
        raise ReportingSnapshotStorageIntegrityError(
            "Stored reporting-definition identity does not match its canonical path."
        )
    return StoredReportingDefinitionRevision(
        definition=definition,
        definition_sha256=digest,
        path=path,
        relative_path=reporting_definition_revision_relative_path(
            class_value,
            definition_value,
            revision,
        ),
        content=content,
    )


def list_reporting_definition_revisions(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
) -> tuple[int, ...]:
    """Return verified contiguous revision numbers for one definition family."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    definition_value = _identifier(definition_id, "definition_id")
    relation = reporting_definition_directory(
        root,
        class_value,
        definition_value,
    )
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_definition_directory(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not enumerate reporting-definition revisions."
        ) from error
    for entry in entries:
        _reject_symlink(entry, "reporting-definition revision entry")
        if not entry.is_file():
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting-definition revisions directory contains a non-file."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
            continue
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
            continue
        raise ReportingSnapshotStorageIntegrityError(
            f"Unexpected reporting-definition revision entry: {entry.name}."
        )
    if json_revisions != digest_revisions:
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting-definition JSON/digest pairs are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting-definition revision history is not contiguous."
        )
    previous: ReportingDefinitionRevision | None = None
    for revision in revisions:
        stored = load_reporting_definition_revision(
            root,
            class_value,
            definition_value,
            revision,
        )
        if previous is not None:
            try:
                validate_reporting_definition_transition(
                    previous,
                    stored.definition,
                )
            except ReportingDefinitionValidationError as error:
                raise ReportingSnapshotStorageIntegrityError(
                    f"Stored reporting-definition history is invalid: {error}"
                ) from error
        previous = stored.definition
    return revisions


def list_reporting_definition_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """List canonical definition-family identities deterministically."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = reporting_definitions_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    result: list[str] = []
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not enumerate reporting-definition collection."
        ) from error
    for entry in entries:
        _reject_symlink(entry, "reporting-definition family")
        if not entry.is_dir():
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting-definition collection contains a non-directory entry."
            )
        definition_id = _identifier(entry.name, "definition_id")
        _validate_definition_directory(entry)
        revisions = list_reporting_definition_revisions(
            root,
            class_value,
            definition_id,
        )
        if not revisions:
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting-definition family exists without immutable history."
            )
        result.append(definition_id)
    return tuple(sorted(result))


def write_reporting_snapshot(
    workspace_root: str | Path,
    snapshot: ReportingSnapshot,
) -> ReportingSnapshotWriteResult:
    """Persist one immutable ReportingSnapshot without selecting it."""

    if not isinstance(snapshot, ReportingSnapshot):
        raise ReportingSnapshotStorageValidationError(
            "snapshot must be ReportingSnapshot."
        )
    try:
        content = reporting_snapshot_to_json_bytes(snapshot)
    except ReportingSnapshotIntegrityError as error:
        raise ReportingSnapshotStorageValidationError(
            f"ReportingSnapshot is invalid: {error}"
        ) from error
    if len(content) > DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES:
        raise ReportingSnapshotStorageWriteError(
            "ReportingSnapshot exceeds the canonical storage byte limit."
        )
    root = _root(workspace_root)
    _require_existing_core_class(root, snapshot.class_id)
    _verify_snapshot_dependencies(root, snapshot)
    target = reporting_snapshot_path(
        root,
        snapshot.class_id,
        snapshot.snapshot_id,
    )
    digest_target = reporting_snapshot_digest_path(
        root,
        snapshot.class_id,
        snapshot.snapshot_id,
    )
    collection = reporting_snapshots_directory(root, snapshot.class_id)
    _ensure_directory_chain(root, collection)
    lock = collection / ".write.lock"
    _acquire_lock(lock, "ReportingSnapshot")
    try:
        _validate_snapshots_directory(collection)
        digest = hashlib.sha256(content).hexdigest()
        if target.exists() or digest_target.exists():
            try:
                stored = load_reporting_snapshot(
                    root,
                    snapshot.class_id,
                    snapshot.snapshot_id,
                )
            except ReportingSnapshotStorageError as error:
                raise ReportingSnapshotStorageIntegrityError(
                    "Existing ReportingSnapshot identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.snapshot_sha256 != digest:
                raise ReportingSnapshotStorageConflictError(
                    "ReportingSnapshot identity already exists with different content."
                )
            return ReportingSnapshotWriteResult("existing", stored)

        _write_pair(target, digest_target, content, digest)
        stored = load_reporting_snapshot(
            root,
            snapshot.class_id,
            snapshot.snapshot_id,
        )
        if stored.content != content or stored.snapshot_sha256 != digest:
            raise ReportingSnapshotStorageIntegrityError(
                "Persisted ReportingSnapshot differs from candidate bytes."
            )
        return ReportingSnapshotWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_reporting_snapshot(
    workspace_root: str | Path,
    class_id: str,
    snapshot_id: str,
    *,
    maximum_snapshot_bytes: int = DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES,
) -> StoredReportingSnapshot:
    """Load one exact historical ReportingSnapshot independent of selection."""

    root = _root(workspace_root)
    stored = _load_reporting_snapshot_raw(
        root,
        class_id,
        snapshot_id,
        maximum_snapshot_bytes=maximum_snapshot_bytes,
    )
    _verify_snapshot_dependencies(root, stored.snapshot)
    return stored


def list_reporting_snapshot_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """Return all exact snapshot identities in deterministic lexical order."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = reporting_snapshots_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    _validate_snapshots_directory(collection)
    json_ids: set[str] = set()
    digest_ids: set[str] = set()
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not enumerate ReportingSnapshot collection."
        ) from error
    for entry in entries:
        if entry.name == ".write.lock":
            continue
        _reject_symlink(entry, "ReportingSnapshot collection entry")
        if not entry.is_file():
            raise ReportingSnapshotStorageIntegrityError(
                "ReportingSnapshot collection contains a non-file entry."
            )
        json_match = _SNAPSHOT_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_ids.add(_identifier(json_match.group(1), "snapshot_id"))
            continue
        digest_match = _SNAPSHOT_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_ids.add(_identifier(digest_match.group(1), "snapshot_id"))
            continue
        raise ReportingSnapshotStorageIntegrityError(
            f"Unexpected ReportingSnapshot collection entry: {entry.name}."
        )
    if json_ids != digest_ids:
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot JSON/digest pairs are incomplete."
        )
    ordered = tuple(sorted(json_ids))
    for snapshot_id in ordered:
        load_reporting_snapshot(root, class_value, snapshot_id)
    return ordered


def _load_reporting_snapshot_raw(
    root: Path,
    class_id: str,
    snapshot_id: str,
    *,
    maximum_snapshot_bytes: int = DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES,
) -> StoredReportingSnapshot:
    class_value = _identifier(class_id, "class_id")
    snapshot_value = _identifier(snapshot_id, "snapshot_id")
    maximum = _positive_int(maximum_snapshot_bytes, "maximum_snapshot_bytes")
    collection = reporting_snapshots_directory(root, class_value)
    _validate_existing_directory_chain(root, collection)
    _validate_snapshots_directory(collection)
    path = reporting_snapshot_path(root, class_value, snapshot_value)
    digest_path = reporting_snapshot_digest_path(root, class_value, snapshot_value)
    content, digest = _read_pair(
        path,
        digest_path,
        maximum,
        missing_label="ReportingSnapshot",
    )
    try:
        snapshot = reporting_snapshot_from_json_bytes(
            content,
            maximum_bytes=maximum,
        )
    except ReportingSnapshotIntegrityError as error:
        raise ReportingSnapshotStorageIntegrityError(
            f"Stored ReportingSnapshot is invalid: {error}"
        ) from error
    if snapshot.class_id != class_value or snapshot.snapshot_id != snapshot_value:
        raise ReportingSnapshotStorageIntegrityError(
            "Stored ReportingSnapshot identity does not match its canonical path."
        )
    expected_ref = reporting_snapshot_reference(snapshot)
    if expected_ref.snapshot_sha256 != digest:
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot sidecar digest does not match canonical reference."
        )
    return StoredReportingSnapshot(
        snapshot=snapshot,
        snapshot_sha256=digest,
        path=path,
        relative_path=reporting_snapshot_relative_path(
            class_value,
            snapshot_value,
        ),
        content=content,
    )


def _verify_snapshot_dependencies(root: Path, snapshot: ReportingSnapshot) -> None:
    reference = snapshot.definition_reference
    try:
        stored_definition = load_reporting_definition_revision(
            root,
            reference.class_id,
            reference.definition_id,
            reference.definition_revision,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotStorageIntegrityError(
            "Exact reporting definition required by ReportingSnapshot is unavailable."
        ) from error
    if stored_definition.definition_sha256 != reference.definition_sha256:
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot definition digest does not match stored revision."
        )
    if reporting_definition_reference(stored_definition.definition) != reference:
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot definition reference does not match stored revision."
        )

    predecessor = snapshot.predecessor
    if predecessor is None:
        return
    predecessor_ref = predecessor.snapshot_reference
    if predecessor_ref.snapshot_id == snapshot.snapshot_id:
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot cannot identify itself as its predecessor."
        )
    try:
        stored_predecessor = _load_reporting_snapshot_raw(
            root,
            predecessor_ref.class_id,
            predecessor_ref.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotStorageIntegrityError(
            "Exact predecessor ReportingSnapshot is unavailable."
        ) from error
    if stored_predecessor.snapshot_sha256 != predecessor_ref.snapshot_sha256:
        raise ReportingSnapshotStorageIntegrityError(
            "Predecessor ReportingSnapshot digest does not match stored bytes."
        )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise ReportingSnapshotStorageNotFoundError(
            "Core class workspace must exist before reporting-state creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_definition_directory(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting-definition canonical root is unsafe or not a directory."
        )
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not inspect reporting-definition canonical root."
        ) from error
    for entry in entries:
        if entry.name not in {"revisions", ".write.lock"}:
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting-definition canonical root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise ReportingSnapshotStorageIntegrityError(
                    "Reporting-definition revisions entry must be a real directory."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting-definition lock entry must be a regular file."
            )


def _validate_snapshots_directory(collection: Path) -> None:
    if collection.is_symlink() or not collection.is_dir():
        raise ReportingSnapshotStorageIntegrityError(
            "ReportingSnapshot canonical root is unsafe or not a directory."
        )
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not inspect ReportingSnapshot canonical root."
        ) from error
    for entry in entries:
        if entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise ReportingSnapshotStorageIntegrityError(
                    "ReportingSnapshot lock entry must be a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise ReportingSnapshotStorageIntegrityError(
                "ReportingSnapshot canonical root contains an unsafe entry."
            )
        if (
            _SNAPSHOT_JSON.fullmatch(entry.name) is None
            and _SNAPSHOT_DIGEST.fullmatch(entry.name) is None
        ):
            raise ReportingSnapshotStorageIntegrityError(
                "ReportingSnapshot canonical root contains an unexpected entry."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise ReportingSnapshotStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise ReportingSnapshotStorageNotFoundError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise ReportingSnapshotStorageIntegrityError(
            "Workspace root must be a real directory, not a symlink."
        )
    return root


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ReportingSnapshotStorageIntegrityError(
                    "Reporting storage directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ReportingSnapshotStorageWriteError(
                    "Could not create reporting storage directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise ReportingSnapshotStorageNotFoundError(
                "Required reporting storage directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ReportingSnapshotStorageIntegrityError(
                "Reporting storage directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ReportingSnapshotStorageValidationError(
            "Reporting storage path escapes the supplied workspace root."
        ) from error


def _read_pair(
    path: Path,
    digest_path: Path,
    maximum_bytes: int,
    *,
    missing_label: str,
) -> tuple[bytes, str]:
    content = _read_bounded_regular_file(
        path,
        maximum_bytes,
        missing_message=f"{missing_label} does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_REPORTING_DIGEST_BYTES,
        missing_message=f"{missing_label} digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise ReportingSnapshotStorageIntegrityError(
            f"{missing_label} digest does not match exact JSON bytes."
        )
    return content, expected_digest


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise ReportingSnapshotStorageIntegrityError(
                    "Reporting storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except ReportingSnapshotStorageError:
        raise
    except FileNotFoundError as error:
        raise ReportingSnapshotStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise ReportingSnapshotStorageReadError(
            "Could not read reporting storage file."
        ) from error
    if len(content) > limit:
        raise ReportingSnapshotStorageTooLargeError(
            "Reporting storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "sha256")
    except ReportingSnapshotStorageValidationError as error:
        raise ReportingSnapshotStorageIntegrityError(
            "Reporting SHA-256 sidecar digest is invalid."
        ) from error


def _write_pair(path: Path, digest_path: Path, content: bytes, digest: str) -> None:
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
        raise ReportingSnapshotStorageConflictError(
            "Immutable reporting identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise ReportingSnapshotStorageWriteError(
            "Could not persist canonical reporting JSON and digest."
        ) from error


def _acquire_lock(path: Path, label: str) -> None:
    try:
        with path.open("xb") as output:
            output.write(f"meridian {label} write lock\n".encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise ReportingSnapshotStorageLockError(
            "Another writer owns this canonical reporting relation."
        ) from error
    except OSError as error:
        raise ReportingSnapshotStorageWriteError(
            "Could not acquire reporting write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ReportingSnapshotStorageWriteError(
            "Could not remove reporting write lock."
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


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ReportingSnapshotStorageIntegrityError(
            f"{label} must not be a symlink."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportingSnapshotStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReportingSnapshotStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


__all__ = [
    "DEFAULT_MAXIMUM_REPORTING_DEFINITION_BYTES",
    "DEFAULT_MAXIMUM_REPORTING_DIGEST_BYTES",
    "ReportingDefinitionWriteResult",
    "ReportingSnapshotStorageConflictError",
    "ReportingSnapshotStorageError",
    "ReportingSnapshotStorageIntegrityError",
    "ReportingSnapshotStorageLockError",
    "ReportingSnapshotStorageNotFoundError",
    "ReportingSnapshotStorageReadError",
    "ReportingSnapshotStorageTooLargeError",
    "ReportingSnapshotStorageValidationError",
    "ReportingSnapshotStorageWriteError",
    "ReportingSnapshotWriteResult",
    "ReportingStorageWriteDisposition",
    "StoredReportingDefinitionRevision",
    "StoredReportingSnapshot",
    "list_reporting_definition_ids",
    "list_reporting_definition_revisions",
    "list_reporting_snapshot_ids",
    "load_reporting_definition_revision",
    "load_reporting_snapshot",
    "reporting_definition_directory",
    "reporting_definition_revision_digest_path",
    "reporting_definition_revision_path",
    "reporting_definition_revision_relative_path",
    "reporting_definition_revisions_directory",
    "reporting_definitions_directory",
    "reporting_snapshot_digest_path",
    "reporting_snapshot_path",
    "reporting_snapshot_relative_path",
    "reporting_snapshots_directory",
    "write_reporting_definition_revision",
    "write_reporting_snapshot",
]
