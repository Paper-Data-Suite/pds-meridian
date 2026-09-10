"""Canonical immutable storage for Meridian v0.3 Grade-policy revisions."""

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
from pds_core.standards import (
    StandardDefinition,
    StandardsReadError,
    find_standard_definition,
    load_workspace_standards_library,
)

from meridian.grade_item_storage import (
    GradeItemStorageError,
    StoredGradeItemRevision,
    load_grade_item_revision,
)
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyReference,
    GradePolicyRevision,
    GradePolicySerializationError,
    GradePolicyValidationError,
    HybridGradeConfiguration,
    StandardsBasedGradeConfiguration,
    grade_policy_revision_from_json_bytes,
    grade_policy_revision_to_json_bytes,
    validate_grade_policy_revision,
    validate_grade_policy_revision_transition,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    load_proficiency_scale_revision,
)

GRADE_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GRADE_POLICY_CURRENT_RECORD_TYPE: Final[str] = "meridian_grade_policy_current"
DEFAULT_MAXIMUM_GRADE_POLICY_BYTES: Final[int] = 512 * 1024
DEFAULT_MAXIMUM_GRADE_POLICY_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GRADE_POLICY_DIGEST_BYTES: Final[int] = 128

GradePolicyWriteDisposition: TypeAlias = Literal["created", "existing"]
GradePolicySelectDisposition: TypeAlias = Literal["created", "updated", "existing"]

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
        "policy_id",
        "policy_revision",
        "policy_sha256",
    }
)


class GradePolicyStorageError(RuntimeError):
    """Base error for Grade-policy persistence failures."""

    code: str = "grade_policy.storage_error"


class GradePolicyStorageValidationError(GradePolicyStorageError, ValueError):
    """Raised for invalid Grade-policy storage API arguments."""

    code = "grade_policy.storage_invalid"


class GradePolicyStorageNotFoundError(GradePolicyStorageError):
    """Raised when explicitly requested Grade-policy state is absent."""

    code = "grade_policy.not_found"


class GradePolicyStorageReadError(GradePolicyStorageError):
    """Raised when Grade-policy state cannot be read safely."""

    code = "grade_policy.read_failed"


class GradePolicyStorageWriteError(GradePolicyStorageError):
    """Raised when Grade-policy state cannot be persisted safely."""

    code = "grade_policy.write_failed"


class GradePolicyStorageConflictError(GradePolicyStorageError):
    """Raised for stale writes or immutable identity/content collisions."""

    code = "grade_policy.conflict"


class GradePolicyStorageLockError(GradePolicyStorageConflictError):
    """Raised when another writer owns one logical Grade-policy family."""

    code = "grade_policy.locked"


class GradePolicyStorageIntegrityError(GradePolicyStorageError):
    """Raised when canonical Grade-policy state fails integrity validation."""

    code = "grade_policy.integrity_failed"


class GradePolicyStorageTooLargeError(GradePolicyStorageReadError):
    """Raised when persisted Grade-policy state exceeds configured read bounds."""

    code = "grade_policy.too_large"


class GradePolicyDependencyError(GradePolicyStorageConflictError):
    """Raised when exact Grade-policy dependencies cannot be verified."""

    code = "grade_policy.dependency_invalid"


@dataclass(frozen=True, slots=True)
class GradePolicyDependencies:
    """Exact dependencies verified for one Grade-policy revision."""

    grade_items: tuple[StoredGradeItemRevision, ...]
    target_scale: StoredProficiencyScale | None
    standards: tuple[StandardDefinition, ...]


@dataclass(frozen=True, slots=True)
class StoredGradePolicyRevision:
    """One verified immutable Grade-policy revision and its exact stored bytes."""

    policy: GradePolicyRevision
    policy_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, GradePolicyRevision):
            raise GradePolicyStorageValidationError(
                "policy must be a GradePolicyRevision."
            )
        digest = _sha256(self.policy_sha256, "policy_sha256")
        if type(self.content) is not bytes:
            raise GradePolicyStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GradePolicyStorageValidationError(
                "policy_sha256 does not match exact stored bytes."
            )
        try:
            decoded = grade_policy_revision_from_json_bytes(self.content)
        except (GradePolicySerializationError, GradePolicyValidationError) as error:
            raise GradePolicyStorageValidationError(
                "content is not a canonical Grade-policy revision."
            ) from error
        if decoded != self.policy:
            raise GradePolicyStorageValidationError(
                "content does not decode to policy."
            )
        if grade_policy_revision_to_json_bytes(self.policy) != self.content:
            raise GradePolicyStorageValidationError(
                "content is not the canonical policy encoding."
            )
        expected = grade_policy_revision_relative_path(
            self.policy.class_id,
            self.policy.policy_id,
            self.policy.policy_revision,
        )
        if self.relative_path != expected:
            raise GradePolicyStorageValidationError(
                "relative_path is not the canonical policy revision location."
            )
        if self.path.name != f"{self.policy.policy_revision}.json":
            raise GradePolicyStorageValidationError(
                "path filename does not match policy revision identity."
            )
        object.__setattr__(self, "policy_sha256", digest)

    @property
    def reference(self) -> GradePolicyReference:
        """Return the exact digest-bound reference to this stored revision."""
        return GradePolicyReference(
            class_id=self.policy.class_id,
            policy_id=self.policy.policy_id,
            policy_revision=self.policy.policy_revision,
            policy_sha256=self.policy_sha256,
        )


@dataclass(frozen=True, slots=True)
class GradePolicyRevisionWriteResult:
    """Result of immutable Grade-policy revision persistence."""

    disposition: GradePolicyWriteDisposition
    stored: StoredGradePolicyRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise GradePolicyStorageValidationError(
                "write disposition is invalid."
            )
        if not isinstance(self.stored, StoredGradePolicyRevision):
            raise GradePolicyStorageValidationError(
                "stored must be a StoredGradePolicyRevision."
            )


@dataclass(frozen=True, slots=True)
class GradePolicyCurrentSelection:
    """Explicit selected revision inside one Grade-policy family."""

    schema_version: str
    record_type: str
    class_id: str
    policy_id: str
    policy_revision: int
    policy_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_POLICY_CURRENT_SCHEMA_VERSION:
            raise GradePolicyStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != GRADE_POLICY_CURRENT_RECORD_TYPE:
            raise GradePolicyStorageValidationError(
                'current record_type must be "meridian_grade_policy_current".'
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "policy_id",
            _identifier(self.policy_id, "policy_id"),
        )
        object.__setattr__(
            self,
            "policy_revision",
            _positive_int(self.policy_revision, "policy_revision"),
        )
        object.__setattr__(
            self,
            "policy_sha256",
            _sha256(self.policy_sha256, "policy_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GradePolicySelectionResult:
    """Result of explicitly selecting one stored policy revision."""

    disposition: GradePolicySelectDisposition
    selection: GradePolicyCurrentSelection
    stored: StoredGradePolicyRevision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "updated", "existing"}:
            raise GradePolicyStorageValidationError(
                "selection disposition is invalid."
            )
        if not isinstance(self.selection, GradePolicyCurrentSelection):
            raise GradePolicyStorageValidationError(
                "selection must be a GradePolicyCurrentSelection."
            )
        if not isinstance(self.stored, StoredGradePolicyRevision):
            raise GradePolicyStorageValidationError(
                "stored must be a StoredGradePolicyRevision."
            )
        policy = self.stored.policy
        if (
            self.selection.class_id != policy.class_id
            or self.selection.policy_id != policy.policy_id
            or self.selection.policy_revision != policy.policy_revision
        ):
            raise GradePolicyStorageValidationError(
                "selection identity must match stored policy identity."
            )
        if self.selection.policy_sha256 != self.stored.policy_sha256:
            raise GradePolicyStorageValidationError(
                "selection digest must match stored policy digest."
            )


def grade_policies_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local canonical Grade-policy collection."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "grade_policies"
    _require_containment(root, path)
    return path


def grade_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    """Return one logical Grade-policy family's canonical root."""
    policy = _identifier(policy_id, "policy_id")
    return grade_policies_directory(workspace_root, class_id) / policy


def grade_policy_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    """Return the immutable revision collection for one policy family."""
    return grade_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "revisions"


def grade_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> Path:
    """Return the canonical JSON path for one immutable policy revision."""
    revision = _positive_int(policy_revision, "policy_revision")
    return grade_policy_revisions_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / f"{revision}.json"


def grade_policy_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> Path:
    """Return the canonical SHA-256 sidecar path for one policy revision."""
    return Path(
        str(
            grade_policy_revision_path(
                workspace_root,
                class_id,
                policy_id,
                policy_revision,
            )
        )
        + ".sha256"
    )


def grade_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    """Return the explicit family-current selector path."""
    return grade_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "current.json"


def grade_policy_revision_relative_path(
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> str:
    """Return the platform-neutral workspace-relative revision path."""
    class_value = _identifier(class_id, "class_id")
    policy = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    return (
        f"classes/{class_value}/modules/meridian/grade_policies/"
        f"{policy}/revisions/{revision}.json"
    )


def validate_grade_policy_dependencies(
    workspace_root: str | Path,
    policy: GradePolicyRevision,
) -> GradePolicyDependencies:
    """Verify exact Grade Item, scale, and Core-standard dependencies."""
    candidate = validate_grade_policy_revision(policy)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)

    stored_items: list[StoredGradeItemRevision] = []
    conventional = _conventional_configuration(candidate)
    if conventional is not None:
        for participation in conventional.items:
            reference = participation.grade_item
            try:
                stored = load_grade_item_revision(
                    root,
                    reference.class_id,
                    reference.grade_item_id,
                    reference.grade_item_revision,
                )
            except GradeItemStorageError as error:
                raise GradePolicyDependencyError(
                    "Exact Grade Item revision is unavailable for Grade policy."
                ) from error
            if stored.revision_sha256 != reference.grade_item_revision_sha256:
                raise GradePolicyDependencyError(
                    "Exact Grade Item digest does not match Grade-policy provenance."
                )
            if stored.revision.purpose not in {
                "conventional_grade",
                "standards_and_conventional",
            }:
                raise GradePolicyDependencyError(
                    "Grade Item purpose does not permit conventional Grade "
                    "participation."
                )
            stored_items.append(stored)

    stored_scale: StoredProficiencyScale | None = None
    standards: list[StandardDefinition] = []
    standards_configuration = _standards_configuration(candidate)
    if standards_configuration is not None:
        scale_reference = standards_configuration.target_scale
        try:
            stored_scale = load_proficiency_scale_revision(
                root,
                scale_reference.class_id,
                scale_reference.scale_id,
                scale_reference.scale_revision,
            )
        except ProficiencyMappingStorageError as error:
            raise GradePolicyDependencyError(
                "Exact proficiency-scale revision is unavailable for Grade policy."
            ) from error
        if stored_scale.scale_sha256 != scale_reference.scale_sha256:
            raise GradePolicyDependencyError(
                "Exact proficiency-scale digest does not match Grade-policy "
                "provenance."
            )
        expected_levels = {
            level.level_id for level in stored_scale.scale.levels
        }
        conversion_levels = {
            conversion.proficiency_level_id
            for conversion in standards_configuration.conversions
        }
        if conversion_levels != expected_levels:
            raise GradePolicyDependencyError(
                "Proficiency-to-Grade conversions must cover exactly the "
                "referenced scale levels."
            )

        try:
            library = load_workspace_standards_library(root)
        except StandardsReadError as error:
            raise GradePolicyDependencyError(
                "Core standards library is unavailable for Grade policy."
            ) from error
        for standard_participation in standards_configuration.standards:
            try:
                standard = find_standard_definition(
                    library,
                    standard_participation.standard_id,
                )
            except (StandardsReadError, ValueError) as error:
                raise GradePolicyDependencyError(
                    "Grade-policy standard could not be resolved."
                ) from error
            if standard is None:
                raise GradePolicyDependencyError(
                    "Grade-policy standard does not resolve in the Core "
                    "standards library."
                )
            standards.append(standard)

    return GradePolicyDependencies(
        grade_items=tuple(stored_items),
        target_scale=stored_scale,
        standards=tuple(standards),
    )


def write_grade_policy_revision(
    workspace_root: str | Path,
    policy: GradePolicyRevision,
) -> GradePolicyRevisionWriteResult:
    """Persist one immutable policy revision without selecting it."""
    candidate = validate_grade_policy_revision(policy)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    target = grade_policy_revision_path(
        root,
        candidate.class_id,
        candidate.policy_id,
        candidate.policy_revision,
    )
    digest_target = grade_policy_revision_digest_path(
        root,
        candidate.class_id,
        candidate.policy_id,
        candidate.policy_revision,
    )
    relation = grade_policy_directory(
        root,
        candidate.class_id,
        candidate.policy_id,
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_policy_directory(relation)
        content = grade_policy_revision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_GRADE_POLICY_BYTES:
            raise GradePolicyStorageWriteError(
                "Grade-policy revision exceeds the canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()

        if target.exists() or digest_target.exists():
            try:
                stored = load_grade_policy_revision(
                    root,
                    candidate.class_id,
                    candidate.policy_id,
                    candidate.policy_revision,
                )
            except GradePolicyStorageError as error:
                raise GradePolicyStorageIntegrityError(
                    "Existing Grade-policy revision identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.policy_sha256 != digest:
                raise GradePolicyStorageConflictError(
                    "Grade-policy revision identity already exists with "
                    "different content."
                )
            return GradePolicyRevisionWriteResult("existing", stored)

        history = list_grade_policy_revisions(
            root,
            candidate.class_id,
            candidate.policy_id,
        )
        if not history:
            if candidate.policy_revision != 1:
                raise GradePolicyStorageConflictError(
                    "Initial Grade-policy revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.policy_revision != expected:
                raise GradePolicyStorageConflictError(
                    "Grade-policy revision must be exactly one greater than "
                    "current history."
                )
            previous = load_grade_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                history[-1],
            ).policy
            try:
                validate_grade_policy_revision_transition(previous, candidate)
            except GradePolicyValidationError as error:
                raise GradePolicyStorageConflictError(str(error)) from error

        validate_grade_policy_dependencies(root, candidate)
        _write_revision_pair(target, digest_target, content, digest)
        stored = load_grade_policy_revision(
            root,
            candidate.class_id,
            candidate.policy_id,
            candidate.policy_revision,
        )
        if stored.content != content or stored.policy_sha256 != digest:
            raise GradePolicyStorageIntegrityError(
                "Persisted Grade-policy revision differs from candidate bytes."
            )
        return GradePolicyRevisionWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grade_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GRADE_POLICY_BYTES,
) -> StoredGradePolicyRevision:
    """Load and verify one exact immutable policy revision."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    maximum = _positive_int(maximum_revision_bytes, "maximum_revision_bytes")
    relation = grade_policy_directory(root, class_value, policy_value)
    _validate_existing_directory_chain(root, relation)
    _validate_policy_directory(relation)
    path = grade_policy_revision_path(
        root,
        class_value,
        policy_value,
        revision,
    )
    digest_path = grade_policy_revision_digest_path(
        root,
        class_value,
        policy_value,
        revision,
    )
    content = _read_bounded_regular_file(
        path,
        maximum,
        missing_message="Grade-policy revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_GRADE_POLICY_DIGEST_BYTES,
        missing_message="Grade-policy revision digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy revision digest does not match exact JSON bytes."
        )
    try:
        policy = grade_policy_revision_from_json_bytes(content)
    except (GradePolicySerializationError, GradePolicyValidationError) as error:
        raise GradePolicyStorageIntegrityError(
            f"Grade-policy revision is invalid or noncanonical: {error}"
        ) from error
    if policy.class_id != class_value:
        raise GradePolicyStorageIntegrityError(
            "Persisted Grade-policy class_id does not match its canonical path."
        )
    if policy.policy_id != policy_value:
        raise GradePolicyStorageIntegrityError(
            "Persisted Grade-policy identity does not match its canonical path."
        )
    if policy.policy_revision != revision:
        raise GradePolicyStorageIntegrityError(
            "Persisted Grade-policy revision does not match its canonical path."
        )
    return StoredGradePolicyRevision(
        policy=policy,
        policy_sha256=actual_digest,
        path=path,
        relative_path=grade_policy_revision_relative_path(
            class_value,
            policy_value,
            revision,
        ),
        content=content,
    )


def list_grade_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> tuple[int, ...]:
    """List and verify contiguous immutable revisions in numeric order."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = grade_policy_directory(root, class_value, policy_value)
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_policy_directory(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)

    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise GradePolicyStorageReadError(
            "Could not enumerate Grade-policy revision storage."
        ) from error
    for entry in entries:
        if entry.is_symlink():
            raise GradePolicyStorageIntegrityError(
                "Grade-policy revision storage contains a symlink."
            )
        if not entry.is_file():
            raise GradePolicyStorageIntegrityError(
                "Grade-policy revision storage contains a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise GradePolicyStorageIntegrityError(
                "Grade-policy revision storage contains an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy revision JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GradePolicyStorageIntegrityError(
            "Grade-policy revision history is not contiguous from revision 1."
        )
    previous: GradePolicyRevision | None = None
    for number in revisions:
        stored = load_grade_policy_revision(
            root,
            class_value,
            policy_value,
            number,
        )
        if previous is not None:
            try:
                validate_grade_policy_revision_transition(
                    previous,
                    stored.policy,
                )
            except GradePolicyValidationError as error:
                raise GradePolicyStorageIntegrityError(
                    f"Grade-policy revision history is invalid: {error}"
                ) from error
        previous = stored.policy
    return revisions


def list_grade_policy_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """List canonical Grade-policy family identities deterministically."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = grade_policies_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    result: list[str] = []
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise GradePolicyStorageReadError(
            "Could not enumerate Grade-policy collection."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise GradePolicyStorageIntegrityError(
                "Grade-policy collection contains an unexpected non-directory entry."
            )
        policy_id = _identifier(entry.name, "policy_id")
        _validate_policy_directory(entry)
        revisions = list_grade_policy_revisions(
            root,
            class_value,
            policy_id,
        )
        if not revisions:
            raise GradePolicyStorageIntegrityError(
                "Grade-policy directory exists without immutable revision history."
            )
        result.append(policy_id)
    return tuple(sorted(result))


def get_current_grade_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> int | None:
    """Return only the explicitly selected family revision number."""
    selection = _load_current_selection(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    return selection.policy_revision if selection is not None else None


def load_current_grade_policy(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> StoredGradePolicyRevision | None:
    """Load the explicitly selected immutable family revision."""
    selection = _load_current_selection(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    if selection is None:
        return None
    stored = load_grade_policy_revision(
        workspace_root,
        selection.class_id,
        selection.policy_id,
        selection.policy_revision,
    )
    if stored.policy_sha256 != selection.policy_sha256:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer digest does not match selected revision."
        )
    return stored


def select_grade_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_revision: int | None,
) -> GradePolicySelectionResult:
    """Explicitly select one stored family revision using compare-and-swap."""
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    expected = (
        None
        if expected_current_revision is None
        else _positive_int(
            expected_current_revision,
            "expected_current_revision",
        )
    )
    relation = grade_policy_directory(root, class_value, policy_value)
    _validate_existing_directory_chain(root, relation)
    target = load_grade_policy_revision(
        root,
        class_value,
        policy_value,
        revision,
    )
    validate_grade_policy_dependencies(root, target.policy)

    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_policy_directory(relation)
        current = _load_current_selection(
            root,
            class_value,
            policy_value,
            missing_ok=True,
        )
        current_revision = (
            current.policy_revision if current is not None else None
        )
        if current_revision != expected:
            raise GradePolicyStorageConflictError(
                "Expected current Grade-policy revision does not match "
                "stored selection."
            )
        selection = GradePolicyCurrentSelection(
            schema_version=GRADE_POLICY_CURRENT_SCHEMA_VERSION,
            record_type=GRADE_POLICY_CURRENT_RECORD_TYPE,
            class_id=class_value,
            policy_id=policy_value,
            policy_revision=revision,
            policy_sha256=target.policy_sha256,
        )
        if current == selection:
            return GradePolicySelectionResult(
                "existing",
                selection,
                target,
            )
        _publish_current_selection(root, selection)
        verified = _load_current_selection(
            root,
            class_value,
            policy_value,
            missing_ok=False,
        )
        if verified != selection:
            raise GradePolicyStorageIntegrityError(
                "Published Grade-policy selection could not be verified."
            )
        disposition: GradePolicySelectDisposition = (
            "created" if current is None else "updated"
        )
        return GradePolicySelectionResult(
            disposition,
            selection,
            target,
        )
    finally:
        _remove_lock(lock)


def _conventional_configuration(
    policy: GradePolicyRevision,
) -> ConventionalGradeConfiguration | None:
    configuration = policy.configuration
    if isinstance(configuration, ConventionalGradeConfiguration):
        return configuration
    if isinstance(configuration, HybridGradeConfiguration):
        return configuration.conventional
    return None


def _standards_configuration(
    policy: GradePolicyRevision,
) -> StandardsBasedGradeConfiguration | None:
    configuration = policy.configuration
    if isinstance(configuration, StandardsBasedGradeConfiguration):
        return configuration
    if isinstance(configuration, HybridGradeConfiguration):
        return configuration.standards_based
    return None


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    *,
    missing_ok: bool,
) -> GradePolicyCurrentSelection | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = grade_policy_directory(root, class_value, policy_value)
    if not relation.exists():
        if missing_ok:
            return None
        raise GradePolicyStorageNotFoundError(
            "Grade-policy family does not exist."
        )
    _validate_existing_directory_chain(root, relation)
    _validate_policy_directory(relation)
    path = grade_policy_current_path(root, class_value, policy_value)
    if not path.exists():
        if missing_ok:
            return None
        raise GradePolicyStorageNotFoundError(
            "Grade-policy family has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_GRADE_POLICY_POINTER_BYTES,
        missing_message="Grade-policy current pointer does not exist.",
    )
    selection = _current_selection_from_json_bytes(content)
    if (
        selection.class_id != class_value
        or selection.policy_id != policy_value
    ):
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer identity does not match its canonical path."
        )
    return selection


def _current_selection_to_dict(
    value: GradePolicyCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": value.policy_sha256,
    }


def _current_selection_to_json_bytes(
    value: GradePolicyCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(_current_selection_to_dict(value))


def _current_selection_from_json_bytes(
    data: bytes,
) -> GradePolicyCurrentSelection:
    if type(data) is not bytes:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except GradePolicyStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer is not valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer does not use the exact schema."
        )
    try:
        selection = GradePolicyCurrentSelection(
            schema_version=_pointer_str(
                decoded["schema_version"],
                "schema_version",
            ),
            record_type=_pointer_str(
                decoded["record_type"],
                "record_type",
            ),
            class_id=_pointer_str(decoded["class_id"], "class_id"),
            policy_id=_pointer_str(decoded["policy_id"], "policy_id"),
            policy_revision=_positive_int(
                decoded["policy_revision"],
                "policy_revision",
            ),
            policy_sha256=_pointer_str(
                decoded["policy_sha256"],
                "policy_sha256",
            ),
        )
    except GradePolicyStorageValidationError as error:
        raise GradePolicyStorageIntegrityError(
            f"Grade-policy current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer is not canonically encoded."
        )
    return selection


def _publish_current_selection(
    workspace_root: str | Path,
    selection: GradePolicyCurrentSelection,
) -> None:
    path = grade_policy_current_path(
        workspace_root,
        selection.class_id,
        selection.policy_id,
    )
    if path.exists() and path.is_symlink():
        raise GradePolicyStorageIntegrityError(
            "Grade-policy current pointer must not be a symlink."
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
        raise GradePolicyStorageWriteError(
            "Could not publish Grade-policy current selection."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _write_revision_pair(
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
        raise GradePolicyStorageConflictError(
            "Grade-policy revision identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise GradePolicyStorageWriteError(
            "Could not persist Grade-policy revision and digest."
        ) from error


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise GradePolicyStorageNotFoundError(
            "Core class workspace must exist before Grade-policy creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_policy_directory(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise GradePolicyStorageIntegrityError(
            "Grade-policy canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise GradePolicyStorageReadError(
            "Could not inspect Grade-policy canonical root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise GradePolicyStorageIntegrityError(
                "Grade-policy canonical root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GradePolicyStorageIntegrityError(
                    "Grade-policy revisions entry must be a real directory."
                )
        elif entry.name == "current.json":
            if entry.is_symlink() or not entry.is_file():
                raise GradePolicyStorageIntegrityError(
                    "Grade-policy current pointer must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise GradePolicyStorageIntegrityError(
                "Grade-policy lock entry must be a regular file."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise GradePolicyStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise GradePolicyStorageNotFoundError(
            "Workspace root does not exist."
        )
    if root.is_symlink() or not root.is_dir():
        raise GradePolicyStorageIntegrityError(
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
                raise GradePolicyStorageIntegrityError(
                    "Grade-policy directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise GradePolicyStorageWriteError(
                    "Could not create Grade-policy directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise GradePolicyStorageNotFoundError(
                "Required Grade-policy directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise GradePolicyStorageIntegrityError(
                "Grade-policy directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GradePolicyStorageValidationError(
            "Grade-policy path escapes the supplied workspace root."
        ) from error


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise GradePolicyStorageIntegrityError(
            "Grade-policy storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise GradePolicyStorageIntegrityError(
                    "Grade-policy storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except GradePolicyStorageError:
        raise
    except FileNotFoundError as error:
        raise GradePolicyStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise GradePolicyStorageReadError(
            "Could not read Grade-policy storage file."
        ) from error
    if len(content) > limit:
        raise GradePolicyStorageTooLargeError(
            "Grade-policy storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "policy_sha256")
    except GradePolicyStorageValidationError as error:
        raise GradePolicyStorageIntegrityError(
            "Grade-policy SHA-256 sidecar digest is invalid."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian grade policy write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise GradePolicyStorageLockError(
            "A Grade-policy writer already owns this logical family."
        ) from error
    except OSError as error:
        raise GradePolicyStorageWriteError(
            "Could not acquire Grade-policy write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise GradePolicyStorageWriteError(
            "Could not remove Grade-policy write lock."
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
        raise GradePolicyStorageValidationError(
            "Grade-policy current selection cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradePolicyStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise GradePolicyStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradePolicyStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradePolicyStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradePolicyStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyStorageIntegrityError(
            f"Grade-policy pointer {field_name} must be a string."
        )
    return value
