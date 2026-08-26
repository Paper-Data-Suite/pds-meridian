"""Canonical storage for proficiency scales and native-value mapping profiles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.proficiency_mapping import (
    NativeValueMappingProfile,
    NativeValueMappingProfileReference,
    ProficiencyMappingSerializationError,
    ProficiencyMappingValidationError,
    ProficiencyScale,
    ProficiencyScaleReference,
    native_value_mapping_profile_from_json_bytes,
    native_value_mapping_profile_to_json_bytes,
    proficiency_scale_from_json_bytes,
    proficiency_scale_to_json_bytes,
    validate_native_value_mapping_profile,
    validate_native_value_mapping_profile_against_scale,
    validate_native_value_mapping_profile_transition,
    validate_proficiency_scale,
    validate_proficiency_scale_transition,
)

PROFICIENCY_SCALE_CURRENT_SCHEMA_VERSION: Final[str] = "1"
PROFICIENCY_SCALE_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_proficiency_scale_current"
)
MAPPING_PROFILE_CURRENT_SCHEMA_VERSION: Final[str] = "1"
MAPPING_PROFILE_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_native_value_mapping_profile_current"
)
DEFAULT_MAXIMUM_PROFICIENCY_SCALE_BYTES: Final[int] = 128 * 1024
DEFAULT_MAXIMUM_MAPPING_PROFILE_BYTES: Final[int] = 256 * 1024
DEFAULT_MAXIMUM_MAPPING_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_MAPPING_DIGEST_BYTES: Final[int] = 128

MappingWriteDisposition: TypeAlias = Literal["created", "existing"]
MappingSelectDisposition: TypeAlias = Literal["created", "updated", "existing"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([1-9]\d*)\.json\.sha256$"
)
_SCALE_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "scale_id",
        "scale_revision",
        "scale_sha256",
    }
)
_PROFILE_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "scale_id",
        "profile_id",
        "profile_revision",
        "profile_sha256",
    }
)

_HistoryT = TypeVar("_HistoryT")


class ProficiencyMappingStorageError(RuntimeError):
    """Base error for proficiency mapping persistence failures."""

    code: str = "proficiency_mapping.storage_error"


class ProficiencyMappingStorageValidationError(
    ProficiencyMappingStorageError, ValueError
):
    """Raised for invalid storage API arguments."""

    code = "proficiency_mapping.storage_invalid"


class ProficiencyMappingStorageNotFoundError(ProficiencyMappingStorageError):
    """Raised when explicitly requested mapping state is absent."""

    code = "proficiency_mapping.not_found"


class ProficiencyMappingStorageReadError(ProficiencyMappingStorageError):
    """Raised when mapping state cannot be read safely."""

    code = "proficiency_mapping.read_failed"


class ProficiencyMappingStorageWriteError(ProficiencyMappingStorageError):
    """Raised when mapping state cannot be written safely."""

    code = "proficiency_mapping.write_failed"


class ProficiencyMappingStorageConflictError(ProficiencyMappingStorageError):
    """Raised for stale writes or identity/content collisions."""

    code = "proficiency_mapping.conflict"


class ProficiencyMappingStorageLockError(ProficiencyMappingStorageConflictError):
    """Raised when another writer owns one logical mapping history."""

    code = "proficiency_mapping.locked"


class ProficiencyMappingStorageIntegrityError(ProficiencyMappingStorageError):
    """Raised when persisted mapping state fails integrity validation."""

    code = "proficiency_mapping.integrity_failed"


class ProficiencyMappingStorageTooLargeError(ProficiencyMappingStorageReadError):
    """Raised when persisted state exceeds the configured read bound."""

    code = "proficiency_mapping.too_large"


class ProficiencyMappingDependencyError(ProficiencyMappingStorageConflictError):
    """Raised when a mapping profile's exact target scale cannot be verified."""

    code = "proficiency_mapping.dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredProficiencyScale:
    """Verified immutable proficiency-scale revision."""

    scale: ProficiencyScale
    scale_sha256: str
    path: Path
    relative_path: str
    content: bytes

    @property
    def reference(self) -> ProficiencyScaleReference:
        return ProficiencyScaleReference(
            class_id=self.scale.class_id,
            scale_id=self.scale.scale_id,
            scale_revision=self.scale.scale_revision,
            scale_sha256=self.scale_sha256,
        )


@dataclass(frozen=True, slots=True)
class StoredNativeValueMappingProfile:
    """Verified immutable native-value mapping-profile revision."""

    profile: NativeValueMappingProfile
    profile_sha256: str
    path: Path
    relative_path: str
    content: bytes

    @property
    def reference(self) -> NativeValueMappingProfileReference:
        return NativeValueMappingProfileReference(
            class_id=self.profile.class_id,
            scale_id=self.profile.scale_id,
            profile_id=self.profile.profile_id,
            profile_revision=self.profile.profile_revision,
            profile_sha256=self.profile_sha256,
        )


@dataclass(frozen=True, slots=True)
class ProficiencyScaleWriteResult:
    disposition: MappingWriteDisposition
    stored: StoredProficiencyScale


@dataclass(frozen=True, slots=True)
class MappingProfileWriteResult:
    disposition: MappingWriteDisposition
    stored: StoredNativeValueMappingProfile


@dataclass(frozen=True, slots=True)
class ProficiencyScaleSelectionResult:
    disposition: MappingSelectDisposition
    stored: StoredProficiencyScale


@dataclass(frozen=True, slots=True)
class MappingProfileSelectionResult:
    disposition: MappingSelectDisposition
    stored: StoredNativeValueMappingProfile


def proficiency_scales_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local Meridian proficiency-scale collection."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "proficiency_scales"
    _require_containment(root, path)
    return path


def proficiency_scale_directory(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> Path:
    scale = _identifier(scale_id, "scale_id")
    return proficiency_scales_directory(workspace_root, class_id) / scale


def proficiency_scale_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> Path:
    return proficiency_scale_directory(workspace_root, class_id, scale_id) / "revisions"


def proficiency_scale_revision_path(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    scale_revision: int,
) -> Path:
    revision = _positive_int(scale_revision, "scale_revision")
    return proficiency_scale_revisions_directory(
        workspace_root, class_id, scale_id
    ) / f"{revision}.json"


def proficiency_scale_current_path(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> Path:
    return proficiency_scale_directory(
        workspace_root, class_id, scale_id
    ) / "current.json"


def mapping_profiles_directory(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> Path:
    return proficiency_scale_directory(
        workspace_root, class_id, scale_id
    ) / "mapping_profiles"


def mapping_profile_directory(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> Path:
    profile = _identifier(profile_id, "profile_id")
    return mapping_profiles_directory(
        workspace_root, class_id, scale_id
    ) / profile


def mapping_profile_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> Path:
    return mapping_profile_directory(
        workspace_root, class_id, scale_id, profile_id
    ) / "revisions"


def mapping_profile_revision_path(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
    profile_revision: int,
) -> Path:
    revision = _positive_int(profile_revision, "profile_revision")
    return mapping_profile_revisions_directory(
        workspace_root, class_id, scale_id, profile_id
    ) / f"{revision}.json"


def mapping_profile_current_path(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> Path:
    return mapping_profile_directory(
        workspace_root, class_id, scale_id, profile_id
    ) / "current.json"


def proficiency_scale_revision_relative_path(
    class_id: str,
    scale_id: str,
    scale_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    revision = _positive_int(scale_revision, "scale_revision")
    return (
        f"classes/{class_value}/modules/meridian/proficiency_scales/"
        f"{scale}/revisions/{revision}.json"
    )


def mapping_profile_revision_relative_path(
    class_id: str,
    scale_id: str,
    profile_id: str,
    profile_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    profile = _identifier(profile_id, "profile_id")
    revision = _positive_int(profile_revision, "profile_revision")
    return (
        f"classes/{class_value}/modules/meridian/proficiency_scales/{scale}/"
        f"mapping_profiles/{profile}/revisions/{revision}.json"
    )


def write_proficiency_scale_revision(
    workspace_root: str | Path,
    scale: ProficiencyScale,
) -> ProficiencyScaleWriteResult:
    candidate = validate_proficiency_scale(scale)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    target = proficiency_scale_revision_path(
        root,
        candidate.class_id,
        candidate.scale_id,
        candidate.scale_revision,
    )
    relation = proficiency_scale_directory(root, candidate.class_id, candidate.scale_id)
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_scale_directory(relation)
        content = proficiency_scale_to_json_bytes(candidate)
        _check_write_size(content, DEFAULT_MAXIMUM_PROFICIENCY_SCALE_BYTES, "scale")
        digest = hashlib.sha256(content).hexdigest()
        digest_target = Path(str(target) + ".sha256")
        if target.exists() or digest_target.exists():
            stored = _load_existing_scale_for_replay(root, candidate)
            if stored.content != content or stored.scale_sha256 != digest:
                raise ProficiencyMappingStorageConflictError(
                    "Proficiency-scale revision already exists with different content."
                )
            return ProficiencyScaleWriteResult("existing", stored)
        history = list_proficiency_scale_revisions(
            root, candidate.class_id, candidate.scale_id
        )
        if not history:
            if candidate.scale_revision != 1:
                raise ProficiencyMappingStorageConflictError(
                    "Initial proficiency-scale revision must be 1."
                )
        else:
            if candidate.scale_revision != history[-1] + 1:
                raise ProficiencyMappingStorageConflictError(
                    "Proficiency-scale revision must be contiguous."
                )
            previous = load_proficiency_scale_revision(
                root,
                candidate.class_id,
                candidate.scale_id,
                history[-1],
            ).scale
            try:
                validate_proficiency_scale_transition(previous, candidate)
            except ProficiencyMappingValidationError as error:
                raise ProficiencyMappingStorageConflictError(str(error)) from error
        _write_revision_pair(target, digest_target, content, digest)
        return ProficiencyScaleWriteResult(
            "created",
            load_proficiency_scale_revision(
                root,
                candidate.class_id,
                candidate.scale_id,
                candidate.scale_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_proficiency_scale_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    scale_revision: int,
) -> StoredProficiencyScale:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    revision = _positive_int(scale_revision, "scale_revision")
    relation = proficiency_scale_directory(root, class_value, scale)
    _validate_scale_directory(relation)
    path = proficiency_scale_revision_path(root, class_value, scale, revision)
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_PROFICIENCY_SCALE_BYTES,
    )
    try:
        model = proficiency_scale_from_json_bytes(content)
    except (
        ProficiencyMappingSerializationError,
        ProficiencyMappingValidationError,
    ) as error:
        raise ProficiencyMappingStorageIntegrityError(
            f"Proficiency-scale revision is invalid or noncanonical: {error}"
        ) from error
    if (
        model.class_id != class_value
        or model.scale_id != scale
        or model.scale_revision != revision
    ):
        raise ProficiencyMappingStorageIntegrityError(
            "Persisted proficiency-scale identity does not match canonical path."
        )
    return StoredProficiencyScale(
        scale=model,
        scale_sha256=digest,
        path=path,
        relative_path=proficiency_scale_revision_relative_path(
            class_value, scale, revision
        ),
        content=content,
    )


def list_proficiency_scale_revisions(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    relation = proficiency_scale_directory(root, class_value, scale)
    if not relation.exists():
        return ()
    _validate_scale_directory(relation)
    return _list_history_revisions(
        root,
        relation,
        lambda revision: load_proficiency_scale_revision(
            root, class_value, scale, revision
        ).scale,
        validate_proficiency_scale_transition,
    )


def list_proficiency_scale_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = proficiency_scales_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect proficiency-scale collection."
        ) from error
    result: list[str] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise ProficiencyMappingStorageIntegrityError(
                "Proficiency-scale collection contains an unexpected entry."
            )
        scale_id = _identifier(entry.name, "scale_id")
        _validate_scale_directory(entry)
        result.append(scale_id)
    return tuple(sorted(result))


def get_current_proficiency_scale_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> int | None:
    pointer = _load_scale_pointer(
        workspace_root, class_id, scale_id, missing_ok=True
    )
    return None if pointer is None else cast(int, pointer["scale_revision"])


def load_current_proficiency_scale(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> StoredProficiencyScale | None:
    pointer = _load_scale_pointer(
        workspace_root, class_id, scale_id, missing_ok=True
    )
    if pointer is None:
        return None
    stored = load_proficiency_scale_revision(
        workspace_root,
        class_id,
        scale_id,
        cast(int, pointer["scale_revision"]),
    )
    if stored.scale_sha256 != pointer["scale_sha256"]:
        raise ProficiencyMappingStorageIntegrityError(
            "Scale current pointer digest does not match selected revision."
        )
    return stored


def select_proficiency_scale_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    scale_revision: int,
    *,
    expected_current_scale_revision: int | None,
) -> ProficiencyScaleSelectionResult:
    root = _root(workspace_root)
    target = load_proficiency_scale_revision(
        root, class_id, scale_id, scale_revision
    )
    relation = proficiency_scale_directory(root, class_id, scale_id)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_scale_pointer(root, class_id, scale_id, missing_ok=True)
        current_revision = (
            None if current is None else cast(int, current["scale_revision"])
        )
        if current_revision != expected_current_scale_revision:
            raise ProficiencyMappingStorageConflictError(
                "Expected current scale revision does not match stored selection."
            )
        pointer = _scale_pointer(target)
        if current == pointer:
            return ProficiencyScaleSelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            proficiency_scale_current_path(root, class_id, scale_id),
            _canonical_json_bytes(pointer),
        )
        disposition: MappingSelectDisposition = (
            "created" if current is None else "updated"
        )
        return ProficiencyScaleSelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def write_mapping_profile_revision(
    workspace_root: str | Path,
    profile: NativeValueMappingProfile,
) -> MappingProfileWriteResult:
    candidate = validate_native_value_mapping_profile(profile)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    target_scale = _load_target_scale(root, candidate.target_scale)
    try:
        validate_native_value_mapping_profile_against_scale(
            candidate, target_scale.scale
        )
    except ProficiencyMappingValidationError as error:
        raise ProficiencyMappingDependencyError(str(error)) from error
    target = mapping_profile_revision_path(
        root,
        candidate.class_id,
        candidate.scale_id,
        candidate.profile_id,
        candidate.profile_revision,
    )
    relation = mapping_profile_directory(
        root, candidate.class_id, candidate.scale_id, candidate.profile_id
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_scale_directory(
            proficiency_scale_directory(root, candidate.class_id, candidate.scale_id)
        )
        _validate_profile_directory(relation)
        content = native_value_mapping_profile_to_json_bytes(candidate)
        _check_write_size(content, DEFAULT_MAXIMUM_MAPPING_PROFILE_BYTES, "profile")
        digest = hashlib.sha256(content).hexdigest()
        digest_target = Path(str(target) + ".sha256")
        if target.exists() or digest_target.exists():
            stored = _load_existing_profile_for_replay(root, candidate)
            if stored.content != content or stored.profile_sha256 != digest:
                raise ProficiencyMappingStorageConflictError(
                    "Mapping-profile revision already exists with different content."
                )
            return MappingProfileWriteResult("existing", stored)
        history = list_mapping_profile_revisions(
            root,
            candidate.class_id,
            candidate.scale_id,
            candidate.profile_id,
        )
        if not history:
            if candidate.profile_revision != 1:
                raise ProficiencyMappingStorageConflictError(
                    "Initial mapping-profile revision must be 1."
                )
        else:
            if candidate.profile_revision != history[-1] + 1:
                raise ProficiencyMappingStorageConflictError(
                    "Mapping-profile revision must be contiguous."
                )
            previous = load_mapping_profile_revision(
                root,
                candidate.class_id,
                candidate.scale_id,
                candidate.profile_id,
                history[-1],
            ).profile
            try:
                validate_native_value_mapping_profile_transition(
                    previous, candidate
                )
            except ProficiencyMappingValidationError as error:
                raise ProficiencyMappingStorageConflictError(str(error)) from error
        _write_revision_pair(target, digest_target, content, digest)
        return MappingProfileWriteResult(
            "created",
            load_mapping_profile_revision(
                root,
                candidate.class_id,
                candidate.scale_id,
                candidate.profile_id,
                candidate.profile_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_mapping_profile_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
    profile_revision: int,
) -> StoredNativeValueMappingProfile:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    profile = _identifier(profile_id, "profile_id")
    revision = _positive_int(profile_revision, "profile_revision")
    relation = mapping_profile_directory(
        root, class_value, scale, profile
    )
    _validate_profile_directory(relation)
    path = mapping_profile_revision_path(
        root, class_value, scale, profile, revision
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_MAPPING_PROFILE_BYTES,
    )
    try:
        model = native_value_mapping_profile_from_json_bytes(content)
    except (
        ProficiencyMappingSerializationError,
        ProficiencyMappingValidationError,
    ) as error:
        raise ProficiencyMappingStorageIntegrityError(
            f"Mapping-profile revision is invalid or noncanonical: {error}"
        ) from error
    if (
        model.class_id != class_value
        or model.scale_id != scale
        or model.profile_id != profile
        or model.profile_revision != revision
    ):
        raise ProficiencyMappingStorageIntegrityError(
            "Persisted mapping-profile identity does not match canonical path."
        )
    target_scale = _load_target_scale(root, model.target_scale)
    try:
        validate_native_value_mapping_profile_against_scale(
            model, target_scale.scale
        )
    except ProficiencyMappingValidationError as error:
        raise ProficiencyMappingStorageIntegrityError(
            f"Persisted mapping-profile target-scale dependency is invalid: {error}"
        ) from error
    return StoredNativeValueMappingProfile(
        profile=model,
        profile_sha256=digest,
        path=path,
        relative_path=mapping_profile_revision_relative_path(
            class_value, scale, profile, revision
        ),
        content=content,
    )


def list_mapping_profile_revisions(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    profile = _identifier(profile_id, "profile_id")
    relation = mapping_profile_directory(root, class_value, scale, profile)
    if not relation.exists():
        return ()
    _validate_profile_directory(relation)
    return _list_history_revisions(
        root,
        relation,
        lambda revision: load_mapping_profile_revision(
            root, class_value, scale, profile, revision
        ).profile,
        validate_native_value_mapping_profile_transition,
    )


def list_mapping_profile_ids(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
) -> tuple[str, ...]:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    collection = mapping_profiles_directory(root, class_value, scale)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect mapping-profile collection."
        ) from error
    result: list[str] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise ProficiencyMappingStorageIntegrityError(
                "Mapping-profile collection contains an unexpected entry."
            )
        profile_id = _identifier(entry.name, "profile_id")
        _validate_profile_directory(entry)
        result.append(profile_id)
    return tuple(sorted(result))


def get_current_mapping_profile_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> int | None:
    pointer = _load_profile_pointer(
        workspace_root,
        class_id,
        scale_id,
        profile_id,
        missing_ok=True,
    )
    return None if pointer is None else cast(int, pointer["profile_revision"])


def load_current_mapping_profile(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
) -> StoredNativeValueMappingProfile | None:
    pointer = _load_profile_pointer(
        workspace_root,
        class_id,
        scale_id,
        profile_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_mapping_profile_revision(
        workspace_root,
        class_id,
        scale_id,
        profile_id,
        cast(int, pointer["profile_revision"]),
    )
    if stored.profile_sha256 != pointer["profile_sha256"]:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping-profile current pointer digest does not match selected revision."
        )
    return stored


def select_mapping_profile_revision(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
    profile_revision: int,
    *,
    expected_current_profile_revision: int | None,
) -> MappingProfileSelectionResult:
    root = _root(workspace_root)
    target = load_mapping_profile_revision(
        root, class_id, scale_id, profile_id, profile_revision
    )
    relation = mapping_profile_directory(root, class_id, scale_id, profile_id)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_profile_pointer(
            root, class_id, scale_id, profile_id, missing_ok=True
        )
        current_revision = (
            None if current is None else cast(int, current["profile_revision"])
        )
        if current_revision != expected_current_profile_revision:
            raise ProficiencyMappingStorageConflictError(
                "Expected current profile revision does not match stored selection."
            )
        pointer = _profile_pointer(target)
        if current == pointer:
            return MappingProfileSelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            mapping_profile_current_path(root, class_id, scale_id, profile_id),
            _canonical_json_bytes(pointer),
        )
        disposition: MappingSelectDisposition = (
            "created" if current is None else "updated"
        )
        return MappingProfileSelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def _load_target_scale(
    root: Path,
    reference: ProficiencyScaleReference,
) -> StoredProficiencyScale:
    try:
        stored = load_proficiency_scale_revision(
            root,
            reference.class_id,
            reference.scale_id,
            reference.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ProficiencyMappingDependencyError(
            "Exact target proficiency-scale revision is unavailable."
        ) from error
    if stored.scale_sha256 != reference.scale_sha256:
        raise ProficiencyMappingDependencyError(
            "Exact target proficiency-scale digest does not match profile reference."
        )
    return stored


def _load_existing_scale_for_replay(
    root: Path,
    candidate: ProficiencyScale,
) -> StoredProficiencyScale:
    try:
        return load_proficiency_scale_revision(
            root,
            candidate.class_id,
            candidate.scale_id,
            candidate.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Existing proficiency-scale revision is incomplete or invalid."
        ) from error


def _load_existing_profile_for_replay(
    root: Path,
    candidate: NativeValueMappingProfile,
) -> StoredNativeValueMappingProfile:
    try:
        return load_mapping_profile_revision(
            root,
            candidate.class_id,
            candidate.scale_id,
            candidate.profile_id,
            candidate.profile_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Existing mapping-profile revision is incomplete or invalid."
        ) from error


def _scale_pointer(stored: StoredProficiencyScale) -> dict[str, object]:
    return {
        "schema_version": PROFICIENCY_SCALE_CURRENT_SCHEMA_VERSION,
        "record_type": PROFICIENCY_SCALE_CURRENT_RECORD_TYPE,
        "class_id": stored.scale.class_id,
        "scale_id": stored.scale.scale_id,
        "scale_revision": stored.scale.scale_revision,
        "scale_sha256": stored.scale_sha256,
    }


def _profile_pointer(
    stored: StoredNativeValueMappingProfile,
) -> dict[str, object]:
    return {
        "schema_version": MAPPING_PROFILE_CURRENT_SCHEMA_VERSION,
        "record_type": MAPPING_PROFILE_CURRENT_RECORD_TYPE,
        "class_id": stored.profile.class_id,
        "scale_id": stored.profile.scale_id,
        "profile_id": stored.profile.profile_id,
        "profile_revision": stored.profile.profile_revision,
        "profile_sha256": stored.profile_sha256,
    }


def _load_scale_pointer(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    path = proficiency_scale_current_path(root, class_value, scale)
    if not path.exists():
        if missing_ok:
            return None
        raise ProficiencyMappingStorageNotFoundError(
            "Proficiency-scale current pointer does not exist."
        )
    mapping = _read_pointer(root, path, _SCALE_POINTER_KEYS, "scale")
    if (
        mapping["schema_version"] != PROFICIENCY_SCALE_CURRENT_SCHEMA_VERSION
        or mapping["record_type"] != PROFICIENCY_SCALE_CURRENT_RECORD_TYPE
        or mapping["class_id"] != class_value
        or mapping["scale_id"] != scale
    ):
        raise ProficiencyMappingStorageIntegrityError(
            "Proficiency-scale current pointer identity is invalid."
        )
    _positive_int(mapping["scale_revision"], "scale_revision")
    _sha256(mapping["scale_sha256"], "scale_sha256")
    return mapping


def _load_profile_pointer(
    workspace_root: str | Path,
    class_id: str,
    scale_id: str,
    profile_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    scale = _identifier(scale_id, "scale_id")
    profile = _identifier(profile_id, "profile_id")
    path = mapping_profile_current_path(root, class_value, scale, profile)
    if not path.exists():
        if missing_ok:
            return None
        raise ProficiencyMappingStorageNotFoundError(
            "Mapping-profile current pointer does not exist."
        )
    mapping = _read_pointer(root, path, _PROFILE_POINTER_KEYS, "profile")
    if (
        mapping["schema_version"] != MAPPING_PROFILE_CURRENT_SCHEMA_VERSION
        or mapping["record_type"] != MAPPING_PROFILE_CURRENT_RECORD_TYPE
        or mapping["class_id"] != class_value
        or mapping["scale_id"] != scale
        or mapping["profile_id"] != profile
    ):
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping-profile current pointer identity is invalid."
        )
    _positive_int(mapping["profile_revision"], "profile_revision")
    _sha256(mapping["profile_sha256"], "profile_sha256")
    return mapping


def _read_pointer(
    root: Path,
    path: Path,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_MAPPING_POINTER_BYTES,
        missing_message=f"{label} current pointer does not exist.",
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping pointer must be UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except ProficiencyMappingStorageIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping pointer JSON is invalid."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != keys:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping pointer does not use its exact schema."
        )
    mapping = cast(dict[str, object], decoded)
    if _canonical_json_bytes(mapping) != content:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping pointer is not canonically encoded."
        )
    _require_containment(root, path)
    return mapping


def _list_history_revisions(
    root: Path,
    relation: Path,
    loader: Callable[[int], _HistoryT],
    transition: Callable[[_HistoryT, _HistoryT], _HistoryT],
) -> tuple[int, ...]:
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect immutable revision history."
        ) from error
    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ProficiencyMappingStorageIntegrityError(
                "Revision history contains an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise ProficiencyMappingStorageIntegrityError(
                "Revision history contains an unexpected file."
            )
    if json_numbers != digest_numbers:
        raise ProficiencyMappingStorageIntegrityError(
            "Revision JSON and digest sidecars are incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise ProficiencyMappingStorageIntegrityError(
            "Immutable revision history must be contiguous from 1."
        )
    if not revisions:
        return ()
    previous: _HistoryT | None = None
    for revision in revisions:
        current = loader(revision)
        if previous is not None:
            try:
                transition(previous, current)
            except ProficiencyMappingValidationError as error:
                raise ProficiencyMappingStorageIntegrityError(
                    f"Persisted revision transition is invalid: {error}"
                ) from error
        previous = current
    return revisions


def _validate_scale_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise ProficiencyMappingStorageIntegrityError(
            "Proficiency-scale canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock", "mapping_profiles"}
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect proficiency-scale canonical root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise ProficiencyMappingStorageIntegrityError(
                "Proficiency-scale canonical root contains an unexpected entry."
            )
        if entry.name in {"revisions", "mapping_profiles"}:
            if entry.is_symlink() or not entry.is_dir():
                raise ProficiencyMappingStorageIntegrityError(
                    "Proficiency-scale collection entry must be a real directory."
                )
            if entry.name == "revisions":
                _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise ProficiencyMappingStorageIntegrityError(
                "Proficiency-scale pointer/lock entry must be a regular file."
            )
    profiles = path / "mapping_profiles"
    if profiles.exists():
        try:
            profile_entries = tuple(profiles.iterdir())
        except OSError as error:
            raise ProficiencyMappingStorageReadError(
                "Could not inspect mapping-profile collection."
            ) from error
        for entry in profile_entries:
            if entry.is_symlink() or not entry.is_dir():
                raise ProficiencyMappingStorageIntegrityError(
                    "Mapping-profile collection contains an unsafe entry."
                )
            _identifier(entry.name, "profile_id")
            _validate_profile_directory(entry)


def _validate_profile_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping-profile canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect mapping-profile canonical root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise ProficiencyMappingStorageIntegrityError(
                "Mapping-profile canonical root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise ProficiencyMappingStorageIntegrityError(
                    "Mapping-profile revisions entry must be a real directory."
                )
            _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise ProficiencyMappingStorageIntegrityError(
                "Mapping-profile pointer/lock entry must be a regular file."
            )


def _validate_revision_directory_shape(path: Path) -> None:
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect immutable mapping revision directory."
        ) from error
    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ProficiencyMappingStorageIntegrityError(
                "Immutable mapping revision directory contains an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise ProficiencyMappingStorageIntegrityError(
                "Immutable mapping revision directory contains an unexpected file."
            )
    if json_numbers != digest_numbers:
        raise ProficiencyMappingStorageIntegrityError(
            "Immutable mapping revision JSON/digest pairs are incomplete."
        )


def _read_revision_pair(
    root: Path,
    path: Path,
    maximum: int,
) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path,
        maximum,
        missing_message="Immutable mapping revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_MAPPING_DIGEST_BYTES,
        missing_message="Immutable mapping digest does not exist.",
    )
    expected = _parse_digest_sidecar(digest_bytes)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ProficiencyMappingStorageIntegrityError(
            "Immutable mapping revision digest does not match exact JSON bytes."
        )
    return content, expected


def _write_revision_pair(
    path: Path,
    digest_path: Path,
    content: bytes,
    digest: str,
) -> None:
    created_json = False
    created_digest = False
    try:
        _exclusive_write(path, content)
        created_json = True
        _exclusive_write(digest_path, (digest + "\n").encode("ascii"))
        created_digest = True
        _fsync_directory(path.parent)
    except FileExistsError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise ProficiencyMappingStorageConflictError(
            "Immutable mapping revision identity already exists."
        ) from error
    except OSError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise ProficiencyMappingStorageWriteError(
            "Could not persist immutable mapping revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _require_containment(root, path)
    _ensure_directory_chain(root, path.parent)
    descriptor: int | None = None
    temporary: str | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = temp_name
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path = Path(temp_name)
        if temp_path.is_symlink() or not temp_path.is_file():
            raise ProficiencyMappingStorageWriteError(
                "Temporary mapping pointer is unsafe."
            )
        os.replace(temp_path, path)
        temporary = None
        _fsync_directory(path.parent)
    except ProficiencyMappingStorageError:
        raise
    except OSError as error:
        raise ProficiencyMappingStorageWriteError(
            "Could not publish mapping current pointer atomically."
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None:
            _remove_file(Path(temporary))


def _exclusive_write(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= cast(int, getattr(os, "O_BINARY"))
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        _remove_file(path)
        raise


def _acquire_lock(path: Path) -> None:
    if path.exists():
        raise ProficiencyMappingStorageLockError(
            "Another writer already owns this mapping history."
        )
    try:
        _exclusive_write(path, b"locked\n")
    except FileExistsError as error:
        raise ProficiencyMappingStorageLockError(
            "Another writer already owns this mapping history."
        ) from error
    except OSError as error:
        raise ProficiencyMappingStorageWriteError(
            "Could not acquire mapping write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise ProficiencyMappingStorageWriteError(
            "Could not remove mapping write lock."
        ) from error


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    relative = target.relative_to(root)
    current = root
    if not current.exists():
        raise ProficiencyMappingStorageNotFoundError(
            "Workspace root must exist before mapping storage is used."
        )
    if current.is_symlink() or not current.is_dir():
        raise ProficiencyMappingStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )
    for component in relative.parts:
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ProficiencyMappingStorageIntegrityError(
                    "Canonical mapping directory chain is unsafe."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise ProficiencyMappingStorageWriteError(
                "Could not create canonical mapping directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    relative = target.relative_to(root)
    current = root
    if current.is_symlink() or not current.is_dir():
        raise ProficiencyMappingStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )
    for component in relative.parts:
        current = current / component
        if not current.exists():
            raise ProficiencyMappingStorageNotFoundError(
                "Canonical mapping directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ProficiencyMappingStorageIntegrityError(
                "Canonical mapping directory chain is unsafe."
            )


def _read_bounded_regular_file(
    path: Path,
    maximum: int,
    *,
    missing_message: str,
) -> bytes:
    if not path.exists():
        raise ProficiencyMappingStorageNotFoundError(missing_message)
    if path.is_symlink() or not path.is_file():
        raise ProficiencyMappingStorageIntegrityError(
            "Canonical mapping file is unsafe or not a regular file."
        )
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not inspect canonical mapping file."
        ) from error
    if size > maximum:
        raise ProficiencyMappingStorageTooLargeError(
            "Canonical mapping file exceeds configured byte limit."
        )
    try:
        with path.open("rb") as handle:
            content = handle.read(maximum + 1)
    except OSError as error:
        raise ProficiencyMappingStorageReadError(
            "Could not read canonical mapping file."
        ) from error
    if len(content) > maximum:
        raise ProficiencyMappingStorageTooLargeError(
            "Canonical mapping file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(content: bytes) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping digest sidecar must use one canonical LF."
        )
    return _sha256(text[:-1], "digest")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ProficiencyMappingStorageIntegrityError(
            "Mapping pointer cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProficiencyMappingStorageIntegrityError(
                f"Duplicate mapping pointer key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ProficiencyMappingStorageIntegrityError(
        f"Non-finite mapping pointer value is invalid: {value}"
    )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise ProficiencyMappingStorageNotFoundError(
            "Core class workspace must exist before proficiency policy creation."
        )
    _validate_existing_directory_chain(root, path)


def _check_write_size(content: bytes, maximum: int, label: str) -> None:
    if len(content) > maximum:
        raise ProficiencyMappingStorageWriteError(
            f"Canonical {label} revision exceeds configured byte limit."
        )


def _root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ProficiencyMappingStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(value)
    if not root.is_absolute():
        root = root.absolute()
    return root


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProficiencyMappingStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ProficiencyMappingStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProficiencyMappingStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProficiencyMappingStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ProficiencyMappingStorageValidationError(
            "Proficiency mapping path escapes workspace root."
        ) from error


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
