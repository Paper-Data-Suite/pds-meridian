"""Class-local immutable storage and explicit current selection for Export Profiles.

Issue #56 keeps immutable profile revisions separate from the mutable convenience
selector for one profile family. Writing a revision never selects it; selecting
one revision never mutates its canonical bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.export_profile import (
    ExportProfileActor,
    ExportProfileReference,
    ExportProfileRevision,
    ExportProfileSerializationError,
    ExportProfileValidationError,
    export_profile_reference,
    export_profile_reference_from_dict,
    export_profile_reference_to_dict,
    export_profile_revision_from_json_bytes,
    export_profile_revision_to_json_bytes,
    validate_export_profile_revision,
    validate_export_profile_transition,
)

EXPORT_PROFILE_SELECTION_SCHEMA_VERSION: Final[str] = "1"
EXPORT_PROFILE_SELECTION_RECORD_TYPE: Final[str] = (
    "meridian_export_profile_current_selection"
)
DEFAULT_MAXIMUM_EXPORT_PROFILE_BYTES: Final[int] = 512 * 1024
DEFAULT_MAXIMUM_EXPORT_PROFILE_SELECTION_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_EXPORT_PROFILE_DIGEST_BYTES: Final[int] = 128
MAXIMUM_EXPORT_PROFILE_SELECTION_RATIONALE_LENGTH: Final[int] = 2000

ExportProfileWriteDisposition: TypeAlias = Literal["created", "existing"]
ExportProfileSelectionDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([1-9]\d*)\.json\.sha256$"
)
_SELECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "profile_id",
        "selection_revision",
        "profile_reference",
        "actor",
        "rationale",
        "decided_at",
        "previous_selection",
    }
)
_SELECTION_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "profile_id",
        "selection_revision",
        "selection_sha256",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})


class ExportProfileStorageError(RuntimeError):
    """Base error for Export Profile persistence and selection."""

    code: str = "export_profile.storage_error"


class ExportProfileStorageValidationError(ExportProfileStorageError, ValueError):
    """Raised for invalid storage API arguments or selector models."""

    code = "export_profile.storage_invalid"


class ExportProfileStorageNotFoundError(ExportProfileStorageError):
    """Raised when explicitly requested Export Profile state is absent."""

    code = "export_profile.not_found"


class ExportProfileStorageReadError(ExportProfileStorageError):
    """Raised when Export Profile state cannot be read safely."""

    code = "export_profile.read_failed"


class ExportProfileStorageWriteError(ExportProfileStorageError):
    """Raised when Export Profile state cannot be persisted safely."""

    code = "export_profile.write_failed"


class ExportProfileStorageConflictError(ExportProfileStorageError):
    """Raised for immutable identity/content conflicts."""

    code = "export_profile.conflict"


class ExportProfileSelectionConflictError(ExportProfileStorageConflictError):
    """Raised when digest-bound selector compare-and-swap state is stale."""

    code = "export_profile.selection_conflict"


class ExportProfileStorageLockError(ExportProfileStorageConflictError):
    """Raised when another writer owns one Export Profile family."""

    code = "export_profile.locked"


class ExportProfileStorageIntegrityError(ExportProfileStorageError):
    """Raised when persisted Export Profile state fails closed validation."""

    code = "export_profile.integrity_failed"


class ExportProfileStorageTooLargeError(ExportProfileStorageReadError):
    """Raised when persisted Export Profile state exceeds configured bounds."""

    code = "export_profile.too_large"


@dataclass(frozen=True, slots=True)
class StoredExportProfileRevision:
    """One verified immutable Export Profile revision and exact bytes."""

    profile: ExportProfileRevision
    profile_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.profile, ExportProfileRevision):
            raise ExportProfileStorageValidationError(
                "profile must be an ExportProfileRevision."
            )
        digest = _sha256(self.profile_sha256, "profile_sha256")
        if type(self.content) is not bytes:
            raise ExportProfileStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ExportProfileStorageValidationError(
                "profile_sha256 does not match exact stored bytes."
            )
        try:
            decoded = export_profile_revision_from_json_bytes(self.content)
        except (ExportProfileSerializationError, ExportProfileValidationError) as error:
            raise ExportProfileStorageValidationError(
                "content is not a canonical Export Profile revision."
            ) from error
        if decoded != self.profile:
            raise ExportProfileStorageValidationError(
                "content does not decode to profile."
            )
        expected = export_profile_revision_relative_path(
            self.profile.class_id,
            self.profile.profile_id,
            self.profile.profile_revision,
        )
        if self.relative_path != expected:
            raise ExportProfileStorageValidationError(
                "relative_path is not the canonical Export Profile location."
            )
        if self.path.name != f"{self.profile.profile_revision}.json":
            raise ExportProfileStorageValidationError(
                "path filename does not match profile revision identity."
            )
        object.__setattr__(self, "profile_sha256", digest)

    @property
    def reference(self) -> ExportProfileReference:
        """Return the exact digest-bound reference for this stored revision."""

        return ExportProfileReference(
            class_id=self.profile.class_id,
            profile_id=self.profile.profile_id,
            profile_revision=self.profile.profile_revision,
            profile_sha256=self.profile_sha256,
        )


@dataclass(frozen=True, slots=True)
class ExportProfileRevisionWriteResult:
    """Result of immutable Export Profile revision persistence."""

    disposition: ExportProfileWriteDisposition
    stored: StoredExportProfileRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ExportProfileStorageValidationError(
                "write disposition is invalid."
            )
        if not isinstance(self.stored, StoredExportProfileRevision):
            raise ExportProfileStorageValidationError(
                "stored must be StoredExportProfileRevision."
            )


@dataclass(frozen=True, slots=True)
class ExportProfileSelectionReference:
    """Exact digest-bound identity for one observed current-selector state."""

    class_id: str
    profile_id: str
    selection_revision: int
    selection_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id, "profile_id"),
        )
        object.__setattr__(
            self,
            "selection_revision",
            _positive_int(self.selection_revision, "selection_revision"),
        )
        object.__setattr__(
            self,
            "selection_sha256",
            _sha256(self.selection_sha256, "selection_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ExportProfileCurrentSelection:
    """One explicit current revision selection inside an Export Profile family."""

    schema_version: str
    record_type: str
    class_id: str
    profile_id: str
    selection_revision: int
    profile_reference: ExportProfileReference
    actor: ExportProfileActor
    rationale: str | None
    decided_at: datetime
    previous_selection: ExportProfileSelectionReference | None

    def __post_init__(self) -> None:
        if self.schema_version != EXPORT_PROFILE_SELECTION_SCHEMA_VERSION:
            raise ExportProfileStorageValidationError(
                'selection schema_version must be "1".'
            )
        if self.record_type != EXPORT_PROFILE_SELECTION_RECORD_TYPE:
            raise ExportProfileStorageValidationError(
                "selection record_type must be "
                '"meridian_export_profile_current_selection".'
            )
        class_id = _identifier(self.class_id, "class_id")
        profile_id = _identifier(self.profile_id, "profile_id")
        selection_revision = _positive_int(
            self.selection_revision,
            "selection_revision",
        )
        if not isinstance(self.profile_reference, ExportProfileReference):
            raise ExportProfileStorageValidationError(
                "profile_reference must be ExportProfileReference."
            )
        profile_reference = ExportProfileReference(
            class_id=self.profile_reference.class_id,
            profile_id=self.profile_reference.profile_id,
            profile_revision=self.profile_reference.profile_revision,
            profile_sha256=self.profile_reference.profile_sha256,
        )
        if (
            profile_reference.class_id != class_id
            or profile_reference.profile_id != profile_id
        ):
            raise ExportProfileStorageValidationError(
                "selected profile reference must match selector family."
            )
        if not isinstance(self.actor, ExportProfileActor):
            raise ExportProfileStorageValidationError(
                "actor must be ExportProfileActor."
            )
        actor = ExportProfileActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_EXPORT_PROFILE_SELECTION_RATIONALE_LENGTH,
        )
        decided_at = _aware_utc_datetime(self.decided_at, "decided_at")
        previous = self.previous_selection
        if selection_revision == 1:
            if previous is not None:
                raise ExportProfileStorageValidationError(
                    "initial selection revision must not identify prior state."
                )
        else:
            if not isinstance(previous, ExportProfileSelectionReference):
                raise ExportProfileStorageValidationError(
                    "later selection revision requires exact prior selection."
                )
            previous = ExportProfileSelectionReference(
                class_id=previous.class_id,
                profile_id=previous.profile_id,
                selection_revision=previous.selection_revision,
                selection_sha256=previous.selection_sha256,
            )
            if (
                previous.class_id != class_id
                or previous.profile_id != profile_id
            ):
                raise ExportProfileStorageValidationError(
                    "prior selection family must match current selection."
                )
            if previous.selection_revision != selection_revision - 1:
                raise ExportProfileStorageValidationError(
                    "prior selection revision must immediately precede current."
                )

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "selection_revision", selection_revision)
        object.__setattr__(self, "profile_reference", profile_reference)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", decided_at)
        object.__setattr__(self, "previous_selection", previous)


@dataclass(frozen=True, slots=True)
class StoredExportProfileSelection:
    """One verified canonical current selector and exact bytes."""

    selection: ExportProfileCurrentSelection
    selection_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, ExportProfileCurrentSelection):
            raise ExportProfileStorageValidationError(
                "selection must be ExportProfileCurrentSelection."
            )
        digest = _sha256(self.selection_sha256, "selection_sha256")
        if type(self.content) is not bytes:
            raise ExportProfileStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ExportProfileStorageValidationError(
                "selection_sha256 does not match exact selector bytes."
            )
        try:
            decoded = export_profile_selection_from_json_bytes(self.content)
        except ExportProfileStorageError as error:
            raise ExportProfileStorageValidationError(
                "content is not a canonical current selector."
            ) from error
        if decoded != self.selection:
            raise ExportProfileStorageValidationError(
                "content does not decode to selection."
            )
        expected = export_profile_selection_relative_path(
            self.selection.class_id,
            self.selection.profile_id,
        )
        if self.relative_path != expected:
            raise ExportProfileStorageValidationError(
                "relative_path is not the canonical selector location."
            )
        if self.path.name != "current.json":
            raise ExportProfileStorageValidationError(
                "selector filename must be current.json."
            )
        object.__setattr__(self, "selection_sha256", digest)

    @property
    def reference(self) -> ExportProfileSelectionReference:
        """Return the exact digest-bound current-selector state."""

        return ExportProfileSelectionReference(
            class_id=self.selection.class_id,
            profile_id=self.selection.profile_id,
            selection_revision=self.selection.selection_revision,
            selection_sha256=self.selection_sha256,
        )


@dataclass(frozen=True, slots=True)
class ExportProfileSelectionResult:
    """Result of one explicit digest-bound profile selection."""

    disposition: ExportProfileSelectionDisposition
    selection: StoredExportProfileSelection
    profile: StoredExportProfileRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "updated", "existing"}:
            raise ExportProfileStorageValidationError(
                "selection disposition is invalid."
            )
        if not isinstance(self.selection, StoredExportProfileSelection):
            raise ExportProfileStorageValidationError(
                "selection must be StoredExportProfileSelection."
            )
        if not isinstance(self.profile, StoredExportProfileRevision):
            raise ExportProfileStorageValidationError(
                "profile must be StoredExportProfileRevision."
            )
        if self.selection.selection.profile_reference != self.profile.reference:
            raise ExportProfileStorageValidationError(
                "selection must identify the returned exact profile revision."
            )


def export_profiles_directory(workspace_root: str | Path, class_id: str) -> Path:
    """Return the class-local Export Profile collection."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "export_profiles"
    _require_containment(root, path)
    return path


def export_profile_directory(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> Path:
    return export_profiles_directory(workspace_root, class_id) / _identifier(
        profile_id,
        "profile_id",
    )


def export_profile_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> Path:
    return export_profile_directory(workspace_root, class_id, profile_id) / "revisions"


def export_profile_revision_path(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
    profile_revision: int,
) -> Path:
    revision = _positive_int(profile_revision, "profile_revision")
    return export_profile_revisions_directory(
        workspace_root,
        class_id,
        profile_id,
    ) / f"{revision}.json"


def export_profile_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
    profile_revision: int,
) -> Path:
    return Path(
        str(
            export_profile_revision_path(
                workspace_root,
                class_id,
                profile_id,
                profile_revision,
            )
        )
        + ".sha256"
    )


def export_profile_current_path(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> Path:
    return (
        export_profile_directory(workspace_root, class_id, profile_id)
        / "current.json"
    )


def export_profile_revision_relative_path(
    class_id: str,
    profile_id: str,
    profile_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    profile_value = _identifier(profile_id, "profile_id")
    revision = _positive_int(profile_revision, "profile_revision")
    return (
        f"classes/{class_value}/modules/meridian/export_profiles/"
        f"{profile_value}/revisions/{revision}.json"
    )


def export_profile_selection_relative_path(class_id: str, profile_id: str) -> str:
    class_value = _identifier(class_id, "class_id")
    profile_value = _identifier(profile_id, "profile_id")
    return (
        f"classes/{class_value}/modules/meridian/export_profiles/"
        f"{profile_value}/current.json"
    )


def write_export_profile_revision(
    workspace_root: str | Path,
    profile: ExportProfileRevision,
) -> ExportProfileRevisionWriteResult:
    """Persist one immutable revision without selecting it."""

    candidate = validate_export_profile_revision(profile)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    family = export_profile_directory(root, candidate.class_id, candidate.profile_id)
    target = export_profile_revision_path(
        root,
        candidate.class_id,
        candidate.profile_id,
        candidate.profile_revision,
    )
    digest_target = export_profile_revision_digest_path(
        root,
        candidate.class_id,
        candidate.profile_id,
        candidate.profile_revision,
    )
    _ensure_directory_chain(root, target.parent)
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_profile_family_directory(family)
        content = export_profile_revision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_EXPORT_PROFILE_BYTES:
            raise ExportProfileStorageWriteError(
                "Export Profile revision exceeds canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()

        if target.exists() or digest_target.exists():
            try:
                stored = load_export_profile_revision(
                    root,
                    candidate.class_id,
                    candidate.profile_id,
                    candidate.profile_revision,
                )
            except ExportProfileStorageError as error:
                raise ExportProfileStorageIntegrityError(
                    "Existing Export Profile identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.profile_sha256 != digest:
                raise ExportProfileStorageConflictError(
                    "Export Profile revision identity already has different content."
                )
            return ExportProfileRevisionWriteResult("existing", stored)

        if candidate.profile_revision > 1:
            try:
                previous = load_export_profile_revision(
                    root,
                    candidate.class_id,
                    candidate.profile_id,
                    candidate.profile_revision - 1,
                )
            except ExportProfileStorageNotFoundError as error:
                raise ExportProfileStorageConflictError(
                    "Previous Export Profile revision must exist before successor."
                ) from error
            try:
                validate_export_profile_transition(previous.profile, candidate)
            except ExportProfileValidationError as error:
                raise ExportProfileStorageConflictError(
                    "Export Profile revision does not validly follow prior revision."
                ) from error

        _write_pair(target, digest_target, content, digest)
        stored = load_export_profile_revision(
            root,
            candidate.class_id,
            candidate.profile_id,
            candidate.profile_revision,
        )
        return ExportProfileRevisionWriteResult("created", stored)
    finally:
        _release_lock(lock)


def load_export_profile_revision(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
    profile_revision: int,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_EXPORT_PROFILE_BYTES,
) -> StoredExportProfileRevision:
    """Load and strictly verify one exact immutable Export Profile revision."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    profile_value = _identifier(profile_id, "profile_id")
    revision = _positive_int(profile_revision, "profile_revision")
    family = export_profile_directory(root, class_value, profile_value)
    _validate_existing_directory_chain(root, family)
    _validate_profile_family_directory(family)
    path = export_profile_revision_path(root, class_value, profile_value, revision)
    digest_path = export_profile_revision_digest_path(
        root,
        class_value,
        profile_value,
        revision,
    )
    content, digest = _read_pair(path, digest_path, maximum_bytes)
    try:
        profile = export_profile_revision_from_json_bytes(content)
    except (ExportProfileSerializationError, ExportProfileValidationError) as error:
        raise ExportProfileStorageIntegrityError(
            f"Stored Export Profile revision is invalid: {error}"
        ) from error
    if (
        profile.class_id != class_value
        or profile.profile_id != profile_value
        or profile.profile_revision != revision
    ):
        raise ExportProfileStorageIntegrityError(
            "Stored Export Profile identity does not match canonical path."
        )
    if export_profile_reference(profile).profile_sha256 != digest:
        raise ExportProfileStorageIntegrityError(
            "Export Profile sidecar digest does not match canonical reference."
        )
    stored = StoredExportProfileRevision(
        profile=profile,
        profile_sha256=digest,
        path=path,
        relative_path=export_profile_revision_relative_path(
            class_value,
            profile_value,
            revision,
        ),
        content=content,
    )
    if revision > 1:
        try:
            previous = load_export_profile_revision(
                root,
                class_value,
                profile_value,
                revision - 1,
                maximum_bytes=maximum_bytes,
            )
            validate_export_profile_transition(previous.profile, profile)
        except ExportProfileStorageNotFoundError as error:
            raise ExportProfileStorageIntegrityError(
                "Stored Export Profile predecessor revision is unavailable."
            ) from error
        except ExportProfileValidationError as error:
            raise ExportProfileStorageIntegrityError(
                "Stored Export Profile revision chain is invalid."
            ) from error
    return stored


def load_export_profile_reference(
    workspace_root: str | Path,
    reference: ExportProfileReference,
) -> StoredExportProfileRevision:
    """Load one exact profile and require its digest-bound reference."""

    if not isinstance(reference, ExportProfileReference):
        raise ExportProfileStorageValidationError(
            "reference must be ExportProfileReference."
        )
    stored = load_export_profile_revision(
        workspace_root,
        reference.class_id,
        reference.profile_id,
        reference.profile_revision,
    )
    if stored.reference != reference:
        raise ExportProfileStorageIntegrityError(
            "Requested Export Profile digest does not match stored revision."
        )
    return stored


def list_export_profile_revisions(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> tuple[int, ...]:
    """List exact immutable revision numbers in deterministic numeric order."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    profile_value = _identifier(profile_id, "profile_id")
    revisions = export_profile_revisions_directory(root, class_value, profile_value)
    if not revisions.exists():
        return ()
    _validate_existing_directory_chain(root, revisions)
    family = export_profile_directory(root, class_value, profile_value)
    _validate_profile_family_directory(family)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions.iterdir())
    except OSError as error:
        raise ExportProfileStorageReadError(
            "Could not enumerate Export Profile revisions."
        ) from error
    for entry in entries:
        _reject_symlink(entry, "Export Profile revision entry")
        if not entry.is_file():
            raise ExportProfileStorageIntegrityError(
                "Export Profile revisions contain a non-file entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
            continue
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
            continue
        raise ExportProfileStorageIntegrityError(
            f"Unexpected Export Profile revision entry: {entry.name}."
        )
    if json_revisions != digest_revisions:
        raise ExportProfileStorageIntegrityError(
            "Export Profile JSON/digest pairs are incomplete."
        )
    ordered = tuple(sorted(json_revisions))
    if ordered and ordered != tuple(range(1, ordered[-1] + 1)):
        raise ExportProfileStorageIntegrityError(
            "Export Profile revision history contains a gap."
        )
    for revision in ordered:
        load_export_profile_revision(root, class_value, profile_value, revision)
    return ordered


def list_export_profile_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """List verified class-local Export Profile families deterministically."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = export_profiles_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    result: list[str] = []
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ExportProfileStorageReadError(
            "Could not enumerate Export Profile collection."
        ) from error
    for entry in entries:
        _reject_symlink(entry, "Export Profile family")
        if not entry.is_dir():
            raise ExportProfileStorageIntegrityError(
                "Export Profile collection contains a non-directory entry."
            )
        profile_id = _identifier(entry.name, "profile_id")
        _validate_profile_family_directory(entry)
        revisions = list_export_profile_revisions(
            root,
            class_value,
            profile_id,
        )
        if not revisions:
            raise ExportProfileStorageIntegrityError(
                "Export Profile family exists without immutable history."
            )
        result.append(profile_id)
    return tuple(sorted(result))


def export_profile_selection_reference_to_dict(
    value: ExportProfileSelectionReference,
) -> dict[str, object]:
    if not isinstance(value, ExportProfileSelectionReference):
        raise ExportProfileStorageValidationError(
            "value must be ExportProfileSelectionReference."
        )
    return {
        "class_id": value.class_id,
        "profile_id": value.profile_id,
        "selection_revision": value.selection_revision,
        "selection_sha256": value.selection_sha256,
    }


def export_profile_selection_reference_from_dict(
    data: object,
) -> ExportProfileSelectionReference:
    mapping = _exact_mapping(
        data,
        _SELECTION_REFERENCE_KEYS,
        "selection reference",
    )
    return ExportProfileSelectionReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        selection_revision=_require_int(
            mapping["selection_revision"],
            "selection_revision",
        ),
        selection_sha256=_require_str(
            mapping["selection_sha256"],
            "selection_sha256",
        ),
    )


def export_profile_selection_to_dict(
    value: ExportProfileCurrentSelection,
) -> dict[str, object]:
    if not isinstance(value, ExportProfileCurrentSelection):
        raise ExportProfileStorageValidationError(
            "value must be ExportProfileCurrentSelection."
        )
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "profile_id": value.profile_id,
        "selection_revision": value.selection_revision,
        "profile_reference": export_profile_reference_to_dict(value.profile_reference),
        "actor": {"kind": value.actor.kind, "actor_id": value.actor.actor_id},
        "rationale": value.rationale,
        "decided_at": value.decided_at.astimezone(UTC).isoformat(),
        "previous_selection": (
            None
            if value.previous_selection is None
            else export_profile_selection_reference_to_dict(value.previous_selection)
        ),
    }


def export_profile_selection_from_dict(data: object) -> ExportProfileCurrentSelection:
    mapping = _exact_mapping(data, _SELECTION_KEYS, "current profile selector")
    try:
        profile_reference = export_profile_reference_from_dict(
            mapping["profile_reference"]
        )
    except ExportProfileValidationError as error:
        raise ExportProfileStorageValidationError(
            f"current selector contains invalid profile reference: {error}"
        ) from error
    actor_data = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "selection actor")
    actor_kind = _require_str(actor_data["kind"], "actor.kind")
    if actor_kind != "teacher":
        raise ExportProfileStorageValidationError(
            "selection actor kind must be teacher."
        )
    previous_data = mapping["previous_selection"]
    previous = (
        None
        if previous_data is None
        else export_profile_selection_reference_from_dict(previous_data)
    )
    rationale = mapping["rationale"]
    if rationale is not None and not isinstance(rationale, str):
        raise ExportProfileStorageValidationError(
            "rationale must be a string or null."
        )
    return ExportProfileCurrentSelection(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        selection_revision=_require_int(
            mapping["selection_revision"],
            "selection_revision",
        ),
        profile_reference=profile_reference,
        actor=ExportProfileActor(
            "teacher",
            _require_str(actor_data["actor_id"], "actor.actor_id"),
        ),
        rationale=rationale,
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
        previous_selection=previous,
    )


def export_profile_selection_to_json_bytes(
    value: ExportProfileCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(export_profile_selection_to_dict(value))


def export_profile_selection_from_json_bytes(
    data: bytes,
) -> ExportProfileCurrentSelection:
    decoded = _decode_json(data, "Export Profile current selector")
    selection = export_profile_selection_from_dict(decoded)
    if export_profile_selection_to_json_bytes(selection) != data:
        raise ExportProfileStorageIntegrityError(
            "Export Profile current selector bytes are not canonical."
        )
    return selection


def export_profile_selection_sha256(value: ExportProfileCurrentSelection) -> str:
    return hashlib.sha256(export_profile_selection_to_json_bytes(value)).hexdigest()


def get_current_export_profile_selection_reference(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> ExportProfileSelectionReference | None:
    stored = load_current_export_profile_selection(
        workspace_root,
        class_id,
        profile_id,
    )
    return None if stored is None else stored.reference


def load_current_export_profile_selection(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_EXPORT_PROFILE_SELECTION_BYTES,
) -> StoredExportProfileSelection | None:
    """Load the explicit current selector, or None when none has been created."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    profile_value = _identifier(profile_id, "profile_id")
    family = export_profile_directory(root, class_value, profile_value)
    if not family.exists():
        return None
    _validate_existing_directory_chain(root, family)
    _validate_profile_family_directory(family)
    path = export_profile_current_path(root, class_value, profile_value)
    if not path.exists():
        return None
    content = _read_bounded_regular_file(
        path,
        maximum_bytes,
        missing_message="Export Profile current selector does not exist.",
    )
    try:
        selection = export_profile_selection_from_json_bytes(content)
    except ExportProfileStorageError:
        raise
    except Exception as error:
        raise ExportProfileStorageIntegrityError(
            "Stored Export Profile current selector is invalid."
        ) from error
    if selection.class_id != class_value or selection.profile_id != profile_value:
        raise ExportProfileStorageIntegrityError(
            "Stored Export Profile selector identity does not match canonical path."
        )
    digest = hashlib.sha256(content).hexdigest()
    stored = StoredExportProfileSelection(
        selection=selection,
        selection_sha256=digest,
        path=path,
        relative_path=export_profile_selection_relative_path(
            class_value,
            profile_value,
        ),
        content=content,
    )
    try:
        selected_profile = load_export_profile_reference(
            root,
            selection.profile_reference,
        )
    except ExportProfileStorageError as error:
        raise ExportProfileStorageIntegrityError(
            "Selected Export Profile revision is unavailable or invalid."
        ) from error
    if selection.decided_at < selected_profile.profile.revised_at:
        raise ExportProfileStorageIntegrityError(
            "Export Profile selection predates selected profile revision."
        )
    return stored


def load_current_export_profile(
    workspace_root: str | Path,
    class_id: str,
    profile_id: str,
) -> StoredExportProfileRevision | None:
    selection = load_current_export_profile_selection(
        workspace_root,
        class_id,
        profile_id,
    )
    if selection is None:
        return None
    return load_export_profile_reference(
        workspace_root,
        selection.selection.profile_reference,
    )


def select_export_profile(
    workspace_root: str | Path,
    profile_reference: ExportProfileReference,
    *,
    actor: ExportProfileActor,
    rationale: str | None,
    decided_at: datetime,
    expected_current: ExportProfileSelectionReference | None,
) -> ExportProfileSelectionResult:
    """Explicitly select one stored profile revision with compare-and-swap guard."""

    if not isinstance(profile_reference, ExportProfileReference):
        raise ExportProfileStorageValidationError(
            "profile_reference must be ExportProfileReference."
        )
    if not isinstance(actor, ExportProfileActor):
        raise ExportProfileStorageValidationError(
            "actor must be ExportProfileActor."
        )
    if expected_current is not None and not isinstance(
        expected_current,
        ExportProfileSelectionReference,
    ):
        raise ExportProfileStorageValidationError(
            "expected_current must be ExportProfileSelectionReference or None."
        )
    selected = load_export_profile_reference(workspace_root, profile_reference)
    decision_time = _aware_utc_datetime(decided_at, "decided_at")
    if decision_time < selected.profile.revised_at:
        raise ExportProfileStorageValidationError(
            "selection decided_at must not be earlier than selected profile revision."
        )
    clean_rationale = _optional_bounded_text(
        rationale,
        "rationale",
        MAXIMUM_EXPORT_PROFILE_SELECTION_RATIONALE_LENGTH,
    )
    clean_actor = ExportProfileActor(actor.kind, actor.actor_id)

    root = _root(workspace_root)
    family = export_profile_directory(
        root,
        profile_reference.class_id,
        profile_reference.profile_id,
    )
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        current = load_current_export_profile_selection(
            root,
            profile_reference.class_id,
            profile_reference.profile_id,
        )
        actual_reference = None if current is None else current.reference
        if actual_reference != expected_current:
            raise ExportProfileSelectionConflictError(
                "Export Profile current selection changed before commit."
            )
        if (
            current is not None
            and current.selection.profile_reference == profile_reference
        ):
            return ExportProfileSelectionResult("existing", current, selected)

        selection_revision = (
            1
            if current is None
            else current.selection.selection_revision + 1
        )
        candidate = ExportProfileCurrentSelection(
            schema_version=EXPORT_PROFILE_SELECTION_SCHEMA_VERSION,
            record_type=EXPORT_PROFILE_SELECTION_RECORD_TYPE,
            class_id=profile_reference.class_id,
            profile_id=profile_reference.profile_id,
            selection_revision=selection_revision,
            profile_reference=profile_reference,
            actor=clean_actor,
            rationale=clean_rationale,
            decided_at=decision_time,
            previous_selection=None if current is None else current.reference,
        )
        content = export_profile_selection_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_EXPORT_PROFILE_SELECTION_BYTES:
            raise ExportProfileStorageWriteError(
                "Export Profile selector exceeds canonical storage byte limit."
            )
        path = export_profile_current_path(
            root,
            profile_reference.class_id,
            profile_reference.profile_id,
        )
        _atomic_replace(path, content)
        stored = load_current_export_profile_selection(
            root,
            profile_reference.class_id,
            profile_reference.profile_id,
        )
        if stored is None or stored.selection != candidate:
            raise ExportProfileStorageIntegrityError(
                "Export Profile selector readback does not match committed state."
            )
        return ExportProfileSelectionResult(
            "created" if current is None else "updated",
            stored,
            selected,
        )
    finally:
        _release_lock(lock)


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise ExportProfileStorageNotFoundError(
            "Core class workspace must exist before Export Profile creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_profile_family_directory(family: Path) -> None:
    if family.is_symlink() or not family.is_dir():
        raise ExportProfileStorageIntegrityError(
            "Export Profile family root is unsafe or not a directory."
        )
    try:
        entries = tuple(family.iterdir())
    except OSError as error:
        raise ExportProfileStorageReadError(
            "Could not inspect Export Profile family root."
        ) from error
    for entry in entries:
        if entry.name not in {"revisions", "current.json", ".write.lock"}:
            raise ExportProfileStorageIntegrityError(
                "Export Profile family root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise ExportProfileStorageIntegrityError(
                    "Export Profile revisions entry must be a real directory."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise ExportProfileStorageIntegrityError(
                "Export Profile selector/lock entry must be a regular file."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise ExportProfileStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise ExportProfileStorageNotFoundError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise ExportProfileStorageIntegrityError(
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
                raise ExportProfileStorageIntegrityError(
                    "Export Profile storage directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ExportProfileStorageWriteError(
                    "Could not create Export Profile storage directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise ExportProfileStorageNotFoundError(
                "Required Export Profile storage directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ExportProfileStorageIntegrityError(
                "Export Profile storage directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ExportProfileStorageValidationError(
            "Export Profile storage path escapes supplied workspace root."
        ) from error


def _read_pair(
    path: Path,
    digest_path: Path,
    maximum_bytes: int,
) -> tuple[bytes, str]:
    content = _read_bounded_regular_file(
        path,
        maximum_bytes,
        missing_message="Export Profile revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_EXPORT_PROFILE_DIGEST_BYTES,
        missing_message="Export Profile revision digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise ExportProfileStorageIntegrityError(
            "Export Profile digest does not match exact JSON bytes."
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
        raise ExportProfileStorageIntegrityError(
            "Export Profile storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise ExportProfileStorageIntegrityError(
                    "Export Profile storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except ExportProfileStorageError:
        raise
    except FileNotFoundError as error:
        raise ExportProfileStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise ExportProfileStorageReadError(
            "Could not read Export Profile storage file."
        ) from error
    if len(content) > limit:
        raise ExportProfileStorageTooLargeError(
            "Export Profile storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ExportProfileStorageIntegrityError(
            "Export Profile SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ExportProfileStorageIntegrityError(
            "Export Profile SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "sha256")
    except ExportProfileStorageValidationError as error:
        raise ExportProfileStorageIntegrityError(
            "Export Profile SHA-256 sidecar digest is invalid."
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
            digest_path.unlink(missing_ok=True)
        if json_created:
            path.unlink(missing_ok=True)
        raise ExportProfileStorageConflictError(
            "Export Profile revision appeared concurrently."
        ) from error
    except OSError as error:
        if digest_created:
            digest_path.unlink(missing_ok=True)
        if json_created:
            path.unlink(missing_ok=True)
        raise ExportProfileStorageWriteError(
            "Could not write immutable Export Profile revision."
        ) from error


def _atomic_replace(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise ExportProfileStorageIntegrityError(
            "Export Profile current selector must not be a symlink."
        )
    parent = path.parent
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as output:
            temp_path = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, path)
        temp_path = None
        _fsync_directory_if_supported(parent)
    except OSError as error:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ExportProfileStorageWriteError(
            "Could not persist Export Profile current selector."
        ) from error


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise ExportProfileStorageIntegrityError(
            "Export Profile lock path must not be a symlink."
        )
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ExportProfileStorageLockError(
            "Export Profile family is locked by another writer."
        ) from error
    except OSError as error:
        raise ExportProfileStorageWriteError(
            "Could not acquire Export Profile family lock."
        ) from error
    try:
        os.write(descriptor, b"locked\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _release_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise ExportProfileStorageWriteError(
            "Could not release Export Profile family lock."
        ) from error


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ExportProfileStorageIntegrityError(f"{label} must not be a symlink.")


def _fsync_directory_if_supported(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
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
        raise ExportProfileStorageIntegrityError(
            "selector cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ExportProfileStorageIntegrityError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExportProfileStorageIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ExportProfileStorageError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ExportProfileStorageIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExportProfileStorageIntegrityError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ExportProfileStorageIntegrityError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ExportProfileStorageValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ExportProfileStorageValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ExportProfileStorageValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ExportProfileStorageValidationError(str(error)) from error


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise ExportProfileStorageValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ExportProfileStorageValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be single-line and free of control characters."
        )
    return value


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, maximum)


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise ExportProfileStorageValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExportProfileStorageValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be a string."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExportProfileStorageValidationError(
            f"{field_name} must be an integer."
        )
    return value


__all__ = [
    "DEFAULT_MAXIMUM_EXPORT_PROFILE_BYTES",
    "DEFAULT_MAXIMUM_EXPORT_PROFILE_DIGEST_BYTES",
    "DEFAULT_MAXIMUM_EXPORT_PROFILE_SELECTION_BYTES",
    "EXPORT_PROFILE_SELECTION_RECORD_TYPE",
    "EXPORT_PROFILE_SELECTION_SCHEMA_VERSION",
    "ExportProfileCurrentSelection",
    "ExportProfileRevisionWriteResult",
    "ExportProfileSelectionConflictError",
    "ExportProfileSelectionDisposition",
    "ExportProfileSelectionReference",
    "ExportProfileSelectionResult",
    "ExportProfileStorageConflictError",
    "ExportProfileStorageError",
    "ExportProfileStorageIntegrityError",
    "ExportProfileStorageLockError",
    "ExportProfileStorageNotFoundError",
    "ExportProfileStorageReadError",
    "ExportProfileStorageTooLargeError",
    "ExportProfileStorageValidationError",
    "ExportProfileStorageWriteError",
    "ExportProfileWriteDisposition",
    "StoredExportProfileRevision",
    "StoredExportProfileSelection",
    "export_profile_current_path",
    "export_profile_directory",
    "export_profile_revision_digest_path",
    "export_profile_revision_path",
    "export_profile_revision_relative_path",
    "export_profile_revisions_directory",
    "export_profile_selection_from_dict",
    "export_profile_selection_from_json_bytes",
    "export_profile_selection_reference_from_dict",
    "export_profile_selection_reference_to_dict",
    "export_profile_selection_relative_path",
    "export_profile_selection_sha256",
    "export_profile_selection_to_dict",
    "export_profile_selection_to_json_bytes",
    "export_profiles_directory",
    "get_current_export_profile_selection_reference",
    "list_export_profile_ids",
    "list_export_profile_revisions",
    "load_current_export_profile",
    "load_current_export_profile_selection",
    "load_export_profile_reference",
    "load_export_profile_revision",
    "select_export_profile",
    "write_export_profile_revision",
]
