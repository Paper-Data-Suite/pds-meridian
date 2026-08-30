"""Canonical immutable storage for grouping-signal derivation policies.

This module persists and explicitly selects Meridian-owned #37 policy revisions.
It does not resolve student proficiency results, assign bands, create Core
GroupingSignalSet records, preview distributions, export files, or invoke Concord.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_period_queries import (
    AcademicPeriodLookupError,
    get_academic_period,
)
from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.academic_periods import AcademicPeriod
from pds_core.class_metadata import (
    ClassMetadata,
    ClassMetadataError,
    load_class_metadata,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_metadata_path, class_module_dir
from pds_core.standards import (
    StandardDefinition,
    StandardsReadError,
    find_standard_definition,
    load_workspace_standards_library,
)

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyAggregationPolicy,
    load_academic_period_proficiency_policy_revision,
)
from meridian.grouping_signal_policy import (
    GroupingSignalDerivationPolicy,
    GroupingSignalDerivationPolicyReference,
    GroupingSignalPolicySerializationError,
    GroupingSignalPolicyValidationError,
    grouping_signal_derivation_policy_from_json_bytes,
    grouping_signal_derivation_policy_reference,
    grouping_signal_derivation_policy_to_json_bytes,
    validate_grouping_signal_derivation_policy,
    validate_grouping_signal_derivation_policy_dependencies,
    validate_grouping_signal_derivation_policy_transition,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    load_proficiency_scale_revision,
)

GROUPING_SIGNAL_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_POLICY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_grouping_signal_derivation_policy_current"
)
DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES: Final[int] = 256 * 1024
DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_DIGEST_BYTES: Final[int] = 128

GroupingSignalPolicyWriteDisposition: TypeAlias = Literal["created", "existing"]
GroupingSignalPolicySelectDisposition: TypeAlias = Literal[
    "created",
    "updated",
    "existing",
]

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


class GroupingSignalPolicyStorageError(RuntimeError):
    """Base error for grouping-signal policy persistence failures."""

    code: str = "grouping_signal_policy.storage_error"


class GroupingSignalPolicyStorageValidationError(
    GroupingSignalPolicyStorageError,
    ValueError,
):
    """Raised for invalid grouping-signal storage API arguments."""

    code = "grouping_signal_policy.storage_invalid"


class GroupingSignalPolicyStorageNotFoundError(GroupingSignalPolicyStorageError):
    """Raised when explicitly requested grouping-signal policy state is absent."""

    code = "grouping_signal_policy.not_found"


class GroupingSignalPolicyStorageReadError(GroupingSignalPolicyStorageError):
    """Raised when grouping-signal policy state cannot be read safely."""

    code = "grouping_signal_policy.read_failed"


class GroupingSignalPolicyStorageWriteError(GroupingSignalPolicyStorageError):
    """Raised when grouping-signal policy state cannot be persisted safely."""

    code = "grouping_signal_policy.write_failed"


class GroupingSignalPolicyStorageConflictError(GroupingSignalPolicyStorageError):
    """Raised for stale writes or immutable identity/content collisions."""

    code = "grouping_signal_policy.conflict"


class GroupingSignalPolicyStorageLockError(
    GroupingSignalPolicyStorageConflictError
):
    """Raised when another writer owns one logical policy family."""

    code = "grouping_signal_policy.locked"


class GroupingSignalPolicyStorageIntegrityError(GroupingSignalPolicyStorageError):
    """Raised when persisted grouping-signal policy state fails validation."""

    code = "grouping_signal_policy.integrity_failed"


class GroupingSignalPolicyStorageTooLargeError(
    GroupingSignalPolicyStorageReadError
):
    """Raised when persisted grouping-signal policy state exceeds read bounds."""

    code = "grouping_signal_policy.too_large"


class GroupingSignalPolicyDependencyError(
    GroupingSignalPolicyStorageConflictError
):
    """Raised when exact academic dependencies cannot be verified."""

    code = "grouping_signal_policy.dependency_invalid"


@dataclass(frozen=True, slots=True)
class GroupingSignalPolicyDependencies:
    """Verified dependencies for one #37 policy write or selection."""

    class_metadata: ClassMetadata
    target_period: AcademicPeriod
    standard: StandardDefinition
    source_policy: StoredAcademicPeriodProficiencyAggregationPolicy
    target_scale: StoredProficiencyScale


@dataclass(frozen=True, slots=True)
class StoredGroupingSignalDerivationPolicy:
    """One verified immutable grouping-signal derivation-policy revision."""

    policy: GroupingSignalDerivationPolicy
    policy_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, GroupingSignalDerivationPolicy):
            raise GroupingSignalPolicyStorageValidationError(
                "policy must be a GroupingSignalDerivationPolicy."
            )
        digest = _sha256(self.policy_sha256, "policy_sha256")
        if type(self.content) is not bytes:
            raise GroupingSignalPolicyStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GroupingSignalPolicyStorageValidationError(
                "policy_sha256 does not match exact immutable content."
            )
        try:
            decoded = grouping_signal_derivation_policy_from_json_bytes(
                self.content
            )
        except (
            GroupingSignalPolicySerializationError,
            GroupingSignalPolicyValidationError,
        ) as error:
            raise GroupingSignalPolicyStorageValidationError(
                "content is not a canonical grouping-signal derivation policy."
            ) from error
        if decoded != self.policy:
            raise GroupingSignalPolicyStorageValidationError(
                "content does not decode to the stored policy."
            )
        expected = grouping_signal_policy_revision_relative_path(
            self.policy.class_id,
            self.policy.policy_id,
            self.policy.policy_revision,
        )
        if self.relative_path != expected:
            raise GroupingSignalPolicyStorageValidationError(
                "relative_path is not the canonical policy revision location."
            )
        if self.path.name != f"{self.policy.policy_revision}.json":
            raise GroupingSignalPolicyStorageValidationError(
                "path filename does not match policy revision identity."
            )
        object.__setattr__(self, "policy_sha256", digest)

    @property
    def reference(self) -> GroupingSignalDerivationPolicyReference:
        return GroupingSignalDerivationPolicyReference(
            class_id=self.policy.class_id,
            policy_id=self.policy.policy_id,
            policy_revision=self.policy.policy_revision,
            policy_sha256=self.policy_sha256,
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalPolicyWriteResult:
    disposition: GroupingSignalPolicyWriteDisposition
    stored: StoredGroupingSignalDerivationPolicy


@dataclass(frozen=True, slots=True)
class GroupingSignalPolicySelectionResult:
    disposition: GroupingSignalPolicySelectDisposition
    stored: StoredGroupingSignalDerivationPolicy


def grouping_signal_policies_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local Meridian grouping-signal policy collection."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "grouping_signal_policies"
    _require_containment(root, path)
    return path


def grouping_signal_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    policy = _identifier(policy_id, "policy_id")
    return grouping_signal_policies_directory(workspace_root, class_id) / policy


def grouping_signal_policy_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return grouping_signal_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "revisions"


def grouping_signal_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> Path:
    revision = _positive_int(policy_revision, "policy_revision")
    return grouping_signal_policy_revisions_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / f"{revision}.json"


def grouping_signal_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return grouping_signal_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "current.json"


def grouping_signal_policy_revision_relative_path(
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    policy = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    return (
        f"classes/{class_value}/modules/meridian/grouping_signal_policies/"
        f"{policy}/revisions/{revision}.json"
    )


def validate_grouping_signal_policy_dependencies(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
) -> GroupingSignalPolicyDependencies:
    """Verify the exact Core/#35/scale state bound by one #37 policy."""

    candidate = validate_grouping_signal_derivation_policy(policy)
    root = _root(workspace_root)
    basis = candidate.academic_basis
    period_ref = basis.target_period.period

    try:
        metadata = load_class_metadata(
            class_metadata_path(root, candidate.class_id)
        )
    except ClassMetadataError as error:
        raise GroupingSignalPolicyDependencyError(
            "Exact Core class metadata is unavailable for grouping-signal policy."
        ) from error
    if (
        metadata.class_id != candidate.class_id
        or metadata.school_year != period_ref.school_year
    ):
        raise GroupingSignalPolicyDependencyError(
            "Core class metadata does not match policy class/school-year scope."
        )

    try:
        calendar = load_academic_period_calendar_revision(
            root,
            period_ref.school_year,
            basis.target_period.calendar_revision,
        )
        target_period = get_academic_period(calendar, period_ref.period_id)
    except (
        AcademicPeriodCalendarStorageError,
        AcademicPeriodLookupError,
    ) as error:
        raise GroupingSignalPolicyDependencyError(
            "Exact Core Academic Period Calendar/target period is unavailable."
        ) from error

    try:
        library = load_workspace_standards_library(root)
        standard = find_standard_definition(library, basis.standard_id)
    except (StandardsReadError, ValueError) as error:
        raise GroupingSignalPolicyDependencyError(
            "Core standards library could not resolve the policy standard_id."
        ) from error
    if standard is None:
        raise GroupingSignalPolicyDependencyError(
            "Policy standard_id does not resolve in the current Core library."
        )

    source_ref = basis.source_policy
    try:
        source_policy = load_academic_period_proficiency_policy_revision(
            root,
            source_ref.class_id,
            source_ref.policy_id,
            source_ref.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise GroupingSignalPolicyDependencyError(
            "Exact #35 Academic Period proficiency policy revision is unavailable."
        ) from error
    if source_policy.policy_sha256 != source_ref.policy_sha256:
        raise GroupingSignalPolicyDependencyError(
            "Exact #35 policy digest does not match grouping policy provenance."
        )

    scale_ref = basis.target_scale
    try:
        target_scale = load_proficiency_scale_revision(
            root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise GroupingSignalPolicyDependencyError(
            "Exact proficiency-scale revision is unavailable."
        ) from error
    if target_scale.scale_sha256 != scale_ref.scale_sha256:
        raise GroupingSignalPolicyDependencyError(
            "Exact proficiency-scale digest does not match grouping policy provenance."
        )

    try:
        validate_grouping_signal_derivation_policy_dependencies(
            candidate,
            source_policy.policy,
            target_scale.scale,
        )
    except GroupingSignalPolicyValidationError as error:
        raise GroupingSignalPolicyDependencyError(str(error)) from error

    return GroupingSignalPolicyDependencies(
        class_metadata=metadata,
        target_period=target_period,
        standard=standard,
        source_policy=source_policy,
        target_scale=target_scale,
    )


def write_grouping_signal_policy_revision(
    workspace_root: str | Path,
    policy: GroupingSignalDerivationPolicy,
) -> GroupingSignalPolicyWriteResult:
    """Persist one immutable #37 policy revision without selecting it."""

    candidate = validate_grouping_signal_derivation_policy(policy)
    root = _root(workspace_root)
    target = grouping_signal_policy_revision_path(
        root,
        candidate.class_id,
        candidate.policy_id,
        candidate.policy_revision,
    )
    relation = grouping_signal_policy_directory(
        root,
        candidate.class_id,
        candidate.policy_id,
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_policy_directory(relation)
        content = grouping_signal_derivation_policy_to_json_bytes(candidate)
        _check_write_size(
            content,
            DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES,
            "policy",
        )
        digest = hashlib.sha256(content).hexdigest()
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            try:
                stored = load_grouping_signal_policy_revision(
                    root,
                    candidate.class_id,
                    candidate.policy_id,
                    candidate.policy_revision,
                )
            except GroupingSignalPolicyStorageError as error:
                raise GroupingSignalPolicyStorageIntegrityError(
                    "Existing grouping-signal policy revision is incomplete or invalid."
                ) from error
            if stored.content != content or stored.policy_sha256 != digest:
                raise GroupingSignalPolicyStorageConflictError(
                    "Grouping-signal policy revision already exists with "
                    "different content."
                )
            return GroupingSignalPolicyWriteResult("existing", stored)

        validate_grouping_signal_policy_dependencies(root, candidate)

        history = list_grouping_signal_policy_revisions(
            root,
            candidate.class_id,
            candidate.policy_id,
        )
        if not history:
            if candidate.policy_revision != 1:
                raise GroupingSignalPolicyStorageConflictError(
                    "Initial grouping-signal policy revision must be 1."
                )
        else:
            if candidate.policy_revision != history[-1] + 1:
                raise GroupingSignalPolicyStorageConflictError(
                    "Grouping-signal policy revision must be contiguous."
                )
            previous = load_grouping_signal_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                history[-1],
            ).policy
            try:
                validate_grouping_signal_derivation_policy_transition(
                    previous,
                    candidate,
                )
            except GroupingSignalPolicyValidationError as error:
                raise GroupingSignalPolicyStorageConflictError(str(error)) from error

        _write_revision_pair(target, digest_target, content, digest)
        stored = load_grouping_signal_policy_revision(
            root,
            candidate.class_id,
            candidate.policy_id,
            candidate.policy_revision,
        )
        if stored.content != content or stored.policy_sha256 != digest:
            raise GroupingSignalPolicyStorageIntegrityError(
                "Persisted grouping-signal policy differs from candidate bytes."
            )
        return GroupingSignalPolicyWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grouping_signal_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES,
) -> StoredGroupingSignalDerivationPolicy:
    """Load and verify one exact immutable #37 policy revision."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    maximum = _positive_int(maximum_revision_bytes, "maximum_revision_bytes")
    relation = grouping_signal_policy_directory(
        root,
        class_value,
        policy_value,
    )
    _validate_policy_directory(relation)
    path = grouping_signal_policy_revision_path(
        root,
        class_value,
        policy_value,
        revision,
    )
    content, digest = _read_revision_pair(root, path, maximum)
    try:
        model = grouping_signal_derivation_policy_from_json_bytes(content)
    except (
        GroupingSignalPolicySerializationError,
        GroupingSignalPolicyValidationError,
    ) as error:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy revision is invalid or noncanonical."
        ) from error
    if (
        model.class_id != class_value
        or model.policy_id != policy_value
        or model.policy_revision != revision
    ):
        raise GroupingSignalPolicyStorageIntegrityError(
            "Persisted grouping-signal policy identity does not match canonical path."
        )
    return StoredGroupingSignalDerivationPolicy(
        policy=model,
        policy_sha256=digest,
        path=path,
        relative_path=grouping_signal_policy_revision_relative_path(
            class_value,
            policy_value,
            revision,
        ),
        content=content,
    )


def list_grouping_signal_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> tuple[int, ...]:
    """Return verified contiguous revisions for one policy family."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = grouping_signal_policy_directory(
        root,
        class_value,
        policy_value,
    )
    if not relation.exists():
        return ()
    _validate_policy_directory(relation)
    revisions = _revision_numbers(relation)
    previous: GroupingSignalDerivationPolicy | None = None
    for revision in revisions:
        current = load_grouping_signal_policy_revision(
            root,
            class_value,
            policy_value,
            revision,
        ).policy
        if previous is not None:
            try:
                validate_grouping_signal_derivation_policy_transition(
                    previous,
                    current,
                )
            except GroupingSignalPolicyValidationError as error:
                raise GroupingSignalPolicyStorageIntegrityError(
                    "Persisted grouping-signal policy transition is invalid."
                ) from error
        previous = current
    return revisions


def list_grouping_signal_policy_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """List verified policy IDs without selecting one."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = grouping_signal_policies_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    result: list[str] = []
    for entry in _directory_entries(collection, "grouping-signal policy collection"):
        if entry.is_symlink() or not entry.is_dir():
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy collection contains an unexpected entry."
            )
        policy_id = _identifier(entry.name, "policy_id")
        _validate_policy_directory(entry)
        result.append(policy_id)
    return tuple(sorted(result))


def get_current_grouping_signal_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> int | None:
    """Return the explicitly selected policy revision, if one exists."""

    pointer = _load_policy_pointer(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    return None if pointer is None else cast(int, pointer["policy_revision"])


def load_current_grouping_signal_policy(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> StoredGroupingSignalDerivationPolicy | None:
    """Load the explicitly selected policy revision, if configured."""

    pointer = _load_policy_pointer(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_grouping_signal_policy_revision(
        workspace_root,
        class_id,
        policy_id,
        cast(int, pointer["policy_revision"]),
    )
    if stored.policy_sha256 != pointer["policy_sha256"]:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal current pointer digest does not match selected revision."
        )
    return stored


def select_grouping_signal_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_policy_revision: int | None,
) -> GroupingSignalPolicySelectionResult:
    """Explicitly select one exact policy revision with compare-and-swap."""

    root = _root(workspace_root)
    target = load_grouping_signal_policy_revision(
        root,
        class_id,
        policy_id,
        policy_revision,
    )
    # Historical reselection is allowed only while exact dependencies remain valid.
    validate_grouping_signal_policy_dependencies(root, target.policy)
    relation = grouping_signal_policy_directory(
        root,
        class_id,
        policy_id,
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_policy_pointer(
            root,
            class_id,
            policy_id,
            missing_ok=True,
        )
        current_revision = (
            None if current is None else cast(int, current["policy_revision"])
        )
        if current_revision != expected_current_policy_revision:
            raise GroupingSignalPolicyStorageConflictError(
                "Expected current grouping-signal policy revision does not match "
                "stored selection."
            )

        pointer = _policy_pointer(target)
        if current == pointer:
            return GroupingSignalPolicySelectionResult("existing", target)

        _atomic_write_pointer(
            root,
            grouping_signal_policy_current_path(
                root,
                class_id,
                policy_id,
            ),
            _canonical_json_bytes(pointer),
        )
        verified = _load_policy_pointer(
            root,
            class_id,
            policy_id,
            missing_ok=False,
        )
        if verified != pointer:
            raise GroupingSignalPolicyStorageIntegrityError(
                "Published grouping-signal policy selection could not be verified."
            )
        disposition: GroupingSignalPolicySelectDisposition = (
            "created" if current is None else "updated"
        )
        return GroupingSignalPolicySelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def _policy_pointer(
    stored: StoredGroupingSignalDerivationPolicy,
) -> dict[str, object]:
    reference = grouping_signal_derivation_policy_reference(stored.policy)
    if reference.policy_sha256 != stored.policy_sha256:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Stored policy digest does not match canonical policy reference."
        )
    return {
        "schema_version": GROUPING_SIGNAL_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": GROUPING_SIGNAL_POLICY_CURRENT_RECORD_TYPE,
        "class_id": stored.policy.class_id,
        "policy_id": stored.policy.policy_id,
        "policy_revision": stored.policy.policy_revision,
        "policy_sha256": stored.policy_sha256,
    }


def _load_policy_pointer(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = grouping_signal_policy_directory(root, class_value, policy_value)
    if relation.exists():
        _validate_policy_directory(relation)
    path = grouping_signal_policy_current_path(root, class_value, policy_value)
    if not path.exists():
        if missing_ok:
            return None
        raise GroupingSignalPolicyStorageNotFoundError(
            "Grouping-signal current policy pointer does not exist."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_POINTER_BYTES,
        missing_message="Grouping-signal current policy pointer does not exist.",
    )
    data = _parse_json_object(content, "grouping-signal current policy pointer")
    if content != _canonical_json_bytes(data):
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal current policy pointer is not canonical JSON."
        )
    if set(data) != _POINTER_KEYS:
        missing = sorted(_POINTER_KEYS - set(data))
        unknown = sorted(set(data) - _POINTER_KEYS)
        detail: list[str] = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if unknown:
            detail.append("unknown: " + ", ".join(unknown))
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal current policy pointer fields are invalid"
            + (": " + "; ".join(detail) if detail else ".")
        )
    if data["schema_version"] != GROUPING_SIGNAL_POLICY_CURRENT_SCHEMA_VERSION:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Unsupported grouping-signal current pointer schema_version."
        )
    if data["record_type"] != GROUPING_SIGNAL_POLICY_CURRENT_RECORD_TYPE:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Invalid grouping-signal current pointer record_type."
        )
    pointer_class = _pointer_identifier(data["class_id"], "class_id")
    pointer_policy = _pointer_identifier(data["policy_id"], "policy_id")
    pointer_revision = _pointer_positive_int(
        data["policy_revision"],
        "policy_revision",
    )
    pointer_digest = _pointer_sha256(data["policy_sha256"], "policy_sha256")
    if pointer_class != class_value or pointer_policy != policy_value:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal current pointer identity does not match canonical path."
        )
    return {
        "schema_version": GROUPING_SIGNAL_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": GROUPING_SIGNAL_POLICY_CURRENT_RECORD_TYPE,
        "class_id": pointer_class,
        "policy_id": pointer_policy,
        "policy_revision": pointer_revision,
        "policy_sha256": pointer_digest,
    }


def _validate_policy_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy family must be a real directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    for entry in _directory_entries(path, "grouping-signal policy family"):
        if entry.name not in allowed:
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy family contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GroupingSignalPolicyStorageIntegrityError(
                    "Grouping-signal policy revisions entry must be a real directory."
                )
            _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy pointer/lock entry must be a regular file."
            )


def _revision_numbers(relation: Path) -> tuple[int, ...]:
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_revision_directory_shape(revisions_dir)
    json_numbers, digest_numbers = _revision_number_sets(revisions_dir)
    if json_numbers != digest_numbers:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy JSON/digest pairs are incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy revision history must be contiguous from 1."
        )
    return revisions


def _validate_revision_directory_shape(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy revisions entry must be a real directory."
        )
    json_numbers, digest_numbers = _revision_number_sets(path)
    if json_numbers != digest_numbers:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy JSON/digest pairs are incomplete."
        )


def _revision_number_sets(path: Path) -> tuple[set[int], set[int]]:
    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in _directory_entries(path, "grouping-signal policy revisions"):
        if entry.is_symlink() or not entry.is_file():
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy revisions contain an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy revisions contain an unexpected filename."
            )
    return json_numbers, digest_numbers


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
        missing_message="Immutable grouping-signal policy revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_GROUPING_SIGNAL_POLICY_DIGEST_BYTES,
        missing_message="Immutable grouping-signal policy digest does not exist.",
    )
    expected = _parse_digest_sidecar(digest_bytes)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Immutable grouping-signal policy digest does not match exact JSON bytes."
        )
    return content, expected


def _parse_digest_sidecar(content: bytes) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal policy digest sidecar must use one canonical LF."
        )
    return _pointer_sha256(text[:-1], "policy digest")


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
        raise GroupingSignalPolicyStorageConflictError(
            "Immutable grouping-signal policy revision identity already exists."
        ) from error
    except OSError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise GroupingSignalPolicyStorageWriteError(
            "Could not persist immutable grouping-signal policy revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _require_containment(root, path)
    _ensure_directory_chain(root, path.parent)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise GroupingSignalPolicyStorageIntegrityError(
            "Grouping-signal current pointer must be a regular file."
        )
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".current.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    except OSError as error:
        raise GroupingSignalPolicyStorageWriteError(
            "Could not publish grouping-signal current policy pointer."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _acquire_lock(path: Path) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"grouping-signal-policy-write\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise GroupingSignalPolicyStorageLockError(
            "Grouping-signal policy family is locked by another writer."
        ) from error
    except OSError as error:
        raise GroupingSignalPolicyStorageWriteError(
            "Could not acquire grouping-signal policy write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise GroupingSignalPolicyStorageWriteError(
            "Could not remove grouping-signal policy write lock."
        ) from error


def _exclusive_write(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _read_bounded_regular_file(
    path: Path,
    maximum: int,
    *,
    missing_message: str,
) -> bytes:
    if not path.exists():
        raise GroupingSignalPolicyStorageNotFoundError(missing_message)
    if path.is_symlink() or not path.is_file():
        raise GroupingSignalPolicyStorageIntegrityError(
            "Persisted grouping-signal policy state must be a regular file."
        )
    try:
        size = path.stat().st_size
    except OSError as error:
        raise GroupingSignalPolicyStorageReadError(
            "Could not inspect persisted grouping-signal policy state."
        ) from error
    if size > maximum:
        raise GroupingSignalPolicyStorageTooLargeError(
            "Persisted grouping-signal policy state exceeds configured read bound."
        )
    try:
        content = path.read_bytes()
    except OSError as error:
        raise GroupingSignalPolicyStorageReadError(
            "Could not read persisted grouping-signal policy state."
        ) from error
    if len(content) > maximum:
        raise GroupingSignalPolicyStorageTooLargeError(
            "Persisted grouping-signal policy state exceeds configured read bound."
        )
    return content


def _check_write_size(content: bytes, maximum: int, label: str) -> None:
    if len(content) > maximum:
        raise GroupingSignalPolicyStorageValidationError(
            f"Canonical {label} bytes exceed the configured storage bound."
        )


def _directory_entries(path: Path, label: str) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GroupingSignalPolicyStorageReadError(
            f"Could not inspect {label}."
        ) from error


def _ensure_directory_chain(root: Path, path: Path) -> None:
    _require_containment(root, path)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise GroupingSignalPolicyStorageWriteError(
            "Could not initialize grouping-signal policy workspace path."
        ) from error
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalPolicyStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise GroupingSignalPolicyStorageIntegrityError(
                    "Grouping-signal policy directory chain contains an unsafe entry."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise GroupingSignalPolicyStorageWriteError(
                "Could not create grouping-signal policy directory."
            ) from error


def _validate_existing_directory_chain(root: Path, path: Path) -> None:
    _require_containment(root, path)
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise GroupingSignalPolicyStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if not current.exists():
            return
        if current.is_symlink() or not current.is_dir():
            raise GroupingSignalPolicyStorageIntegrityError(
                "Grouping-signal policy directory chain contains an unsafe entry."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GroupingSignalPolicyStorageValidationError(
            "Grouping-signal policy path escapes workspace root."
        ) from error


def _root(value: str | Path) -> Path:
    if isinstance(value, Path):
        root = value
    elif isinstance(value, str):
        if not value.strip():
            raise GroupingSignalPolicyStorageValidationError(
                "workspace_root must not be blank."
            )
        root = Path(value)
    else:
        raise GroupingSignalPolicyStorageValidationError(
            "workspace_root must be a string or Path."
        )
    return root.expanduser().absolute()


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPolicyStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalPolicyStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GroupingSignalPolicyStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalPolicyStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 hex digest."
        )
    return value


def _pointer_identifier(value: object, field_name: str) -> str:
    try:
        return _identifier(value, field_name)
    except GroupingSignalPolicyStorageValidationError as error:
        raise GroupingSignalPolicyStorageIntegrityError(str(error)) from error


def _pointer_positive_int(value: object, field_name: str) -> int:
    try:
        return _positive_int(value, field_name)
    except GroupingSignalPolicyStorageValidationError as error:
        raise GroupingSignalPolicyStorageIntegrityError(str(error)) from error


def _pointer_sha256(value: object, field_name: str) -> str:
    try:
        return _sha256(value, field_name)
    except GroupingSignalPolicyStorageValidationError as error:
        raise GroupingSignalPolicyStorageIntegrityError(str(error)) from error


def _parse_json_object(content: bytes, label: str) -> dict[str, object]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalPolicyStorageIntegrityError(
            f"{label} must be UTF-8 JSON."
        ) from error

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GroupingSignalPolicyStorageIntegrityError(
                    f"{label} contains duplicate JSON object key: {key}."
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise GroupingSignalPolicyStorageIntegrityError(
            f"{label} contains non-standard JSON numeric constant: {value}."
        )

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except GroupingSignalPolicyStorageIntegrityError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise GroupingSignalPolicyStorageIntegrityError(
            f"{label} is invalid JSON."
        ) from error
    if not isinstance(parsed, dict):
        raise GroupingSignalPolicyStorageIntegrityError(
            f"{label} must be a JSON object."
        )
    if not all(isinstance(key, str) for key in parsed):
        raise GroupingSignalPolicyStorageIntegrityError(
            f"{label} keys must be strings."
        )
    return cast(dict[str, object], parsed)


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
        raise GroupingSignalPolicyStorageValidationError(
            "Grouping-signal pointer cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")
