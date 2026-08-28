"Canonical storage for standards-proficiency calculation policies and results."

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

from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_grade_item_revision,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    load_proficiency_scale_revision,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicy,
    StandardProficiencyCalculationPolicyReference,
    StandardProficiencyResultReference,
    StandardProficiencyResultSnapshot,
    StandardProficiencySerializationError,
    StandardProficiencyValidationError,
    standard_proficiency_calculation_policy_from_json_bytes,
    standard_proficiency_calculation_policy_to_json_bytes,
    standard_proficiency_result_snapshot_from_json_bytes,
    standard_proficiency_result_snapshot_to_json_bytes,
    validate_standard_proficiency_calculation_policy,
    validate_standard_proficiency_calculation_policy_transition,
    validate_standard_proficiency_result_transition,
)

STANDARD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
STANDARD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_standard_proficiency_calculation_policy_current"
)
DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POLICY_BYTES: Final[int] = 128 * 1024
DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_DIGEST_BYTES: Final[int] = 128

STANDARD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION: Final[str] = "1"
STANDARD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_standard_proficiency_result_current"
)
DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_RESULT_BYTES: Final[int] = 8 * 1024 * 1024

StandardProficiencyResultWriteDisposition: TypeAlias = Literal[
    "created",
    "existing",
]
StandardProficiencyResultSelectDisposition: TypeAlias = Literal[
    "created",
    "updated",
    "existing",
]

StandardProficiencyWriteDisposition: TypeAlias = Literal["created", "existing"]
StandardProficiencySelectDisposition: TypeAlias = Literal[
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

_RESULT_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "student_id",
        "standard_id",
        "standard_key",
        "result_revision",
        "result_sha256",
    }
)

_HistoryT = TypeVar("_HistoryT")


class StandardProficiencyStorageError(RuntimeError):
    "Base error for standards-proficiency policy persistence failures."

    code: str = "standards_proficiency.storage_error"


class StandardProficiencyStorageValidationError(
    StandardProficiencyStorageError,
    ValueError,
):
    "Raised for invalid policy-storage API arguments."

    code = "standards_proficiency.storage_invalid"


class StandardProficiencyStorageNotFoundError(StandardProficiencyStorageError):
    "Raised when explicitly requested policy state is absent."

    code = "standards_proficiency.not_found"


class StandardProficiencyStorageReadError(StandardProficiencyStorageError):
    "Raised when policy state cannot be read safely."

    code = "standards_proficiency.read_failed"


class StandardProficiencyStorageWriteError(StandardProficiencyStorageError):
    "Raised when policy state cannot be written safely."

    code = "standards_proficiency.write_failed"


class StandardProficiencyStorageConflictError(StandardProficiencyStorageError):
    "Raised for stale writes or identity/content collisions."

    code = "standards_proficiency.conflict"


class StandardProficiencyStorageLockError(
    StandardProficiencyStorageConflictError
):
    "Raised when another writer owns one logical policy history."

    code = "standards_proficiency.locked"


class StandardProficiencyStorageIntegrityError(StandardProficiencyStorageError):
    "Raised when persisted policy state fails integrity validation."

    code = "standards_proficiency.integrity_failed"


class StandardProficiencyStorageTooLargeError(
    StandardProficiencyStorageReadError
):
    "Raised when persisted state exceeds configured read bounds."

    code = "standards_proficiency.too_large"


class StandardProficiencyPolicyDependencyError(
    StandardProficiencyStorageConflictError
):
    "Raised when a policy's exact target scale cannot be verified."

    code = "standards_proficiency.policy_dependency_invalid"


class StandardProficiencyResultDependencyError(
    StandardProficiencyStorageConflictError
):
    "Raised when an exact result dependency cannot be verified for a new write."

    code = "standards_proficiency.result_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredStandardProficiencyCalculationPolicy:
    "Verified immutable calculation-policy revision."

    policy: StandardProficiencyCalculationPolicy
    policy_sha256: str
    path: Path
    relative_path: str
    content: bytes

    @property
    def reference(self) -> StandardProficiencyCalculationPolicyReference:
        return StandardProficiencyCalculationPolicyReference(
            class_id=self.policy.class_id,
            policy_id=self.policy.policy_id,
            policy_revision=self.policy.policy_revision,
            policy_sha256=self.policy_sha256,
        )


@dataclass(frozen=True, slots=True)
class StandardProficiencyPolicyWriteResult:
    disposition: StandardProficiencyWriteDisposition
    stored: StoredStandardProficiencyCalculationPolicy


@dataclass(frozen=True, slots=True)
class StandardProficiencyPolicySelectionResult:
    disposition: StandardProficiencySelectDisposition
    stored: StoredStandardProficiencyCalculationPolicy


@dataclass(frozen=True, slots=True)
class StoredStandardProficiencyResult:
    "Verified immutable standards-proficiency result revision."

    snapshot: StandardProficiencyResultSnapshot
    result_sha256: str
    path: Path
    relative_path: str
    content: bytes

    @property
    def reference(self) -> StandardProficiencyResultReference:
        return StandardProficiencyResultReference(
            class_id=self.snapshot.class_id,
            grade_item_id=self.snapshot.grade_item_id,
            student_id=self.snapshot.student_id,
            standard_id=self.snapshot.standard_id,
            result_revision=self.snapshot.result_revision,
            result_sha256=self.result_sha256,
        )


@dataclass(frozen=True, slots=True)
class StandardProficiencyResultWriteResult:
    disposition: StandardProficiencyResultWriteDisposition
    stored: StoredStandardProficiencyResult


@dataclass(frozen=True, slots=True)
class StandardProficiencyResultSelectionResult:
    disposition: StandardProficiencyResultSelectDisposition
    stored: StoredStandardProficiencyResult


def standards_proficiency_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    "Return the class-local standards-proficiency storage root."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "standards_proficiency"
    )
    _require_containment(root, path)
    return path


def standard_proficiency_policies_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    return standards_proficiency_directory(
        workspace_root,
        class_id,
    ) / "policies"


def standard_proficiency_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    policy = _identifier(policy_id, "policy_id")
    return standard_proficiency_policies_directory(
        workspace_root,
        class_id,
    ) / policy


def standard_proficiency_policy_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return standard_proficiency_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "revisions"


def standard_proficiency_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> Path:
    revision = _positive_int(policy_revision, "policy_revision")
    return standard_proficiency_policy_revisions_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / f"{revision}.json"


def standard_proficiency_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return standard_proficiency_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "current.json"


def standard_proficiency_policy_revision_relative_path(
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    policy = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    return (
        f"classes/{class_value}/modules/meridian/standards_proficiency/"
        f"policies/{policy}/revisions/{revision}.json"
    )


def write_standard_proficiency_policy_revision(
    workspace_root: str | Path,
    policy: StandardProficiencyCalculationPolicy,
) -> StandardProficiencyPolicyWriteResult:
    "Persist one immutable policy revision without selecting it."

    candidate = validate_standard_proficiency_calculation_policy(policy)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)

    target = standard_proficiency_policy_revision_path(
        root,
        candidate.class_id,
        candidate.policy_id,
        candidate.policy_revision,
    )
    relation = standard_proficiency_policy_directory(
        root,
        candidate.class_id,
        candidate.policy_id,
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_policy_directory(relation)
        content = standard_proficiency_calculation_policy_to_json_bytes(
            candidate
        )
        _check_write_size(
            content,
            DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POLICY_BYTES,
            "policy",
        )
        digest = hashlib.sha256(content).hexdigest()
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            stored = _load_existing_policy_for_replay(root, candidate)
            if stored.content != content or stored.policy_sha256 != digest:
                raise StandardProficiencyStorageConflictError(
                    "Calculation-policy revision already exists with "
                    "different content."
                )
            return StandardProficiencyPolicyWriteResult(
                "existing",
                stored,
            )

        _load_target_scale_for_write(root, candidate.target_scale)

        history = list_standard_proficiency_policy_revisions(
            root,
            candidate.class_id,
            candidate.policy_id,
        )
        if not history:
            if candidate.policy_revision != 1:
                raise StandardProficiencyStorageConflictError(
                    "Initial calculation-policy revision must be 1."
                )
        else:
            if candidate.policy_revision != history[-1] + 1:
                raise StandardProficiencyStorageConflictError(
                    "Calculation-policy revision must be contiguous."
                )
            previous = load_standard_proficiency_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                history[-1],
            ).policy
            try:
                validate_standard_proficiency_calculation_policy_transition(
                    previous,
                    candidate,
                )
            except StandardProficiencyValidationError as error:
                raise StandardProficiencyStorageConflictError(
                    str(error)
                ) from error

        _write_revision_pair(
            target,
            digest_target,
            content,
            digest,
        )
        return StandardProficiencyPolicyWriteResult(
            "created",
            load_standard_proficiency_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                candidate.policy_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_standard_proficiency_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> StoredStandardProficiencyCalculationPolicy:
    "Load and verify one exact immutable policy revision."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    relation = standard_proficiency_policy_directory(
        root,
        class_value,
        policy_value,
    )
    _validate_policy_directory(relation)
    path = standard_proficiency_policy_revision_path(
        root,
        class_value,
        policy_value,
        revision,
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POLICY_BYTES,
    )
    try:
        model = standard_proficiency_calculation_policy_from_json_bytes(
            content
        )
    except (
        StandardProficiencySerializationError,
        StandardProficiencyValidationError,
    ) as error:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy revision is invalid or noncanonical: "
            f"{error}"
        ) from error

    if (
        model.class_id != class_value
        or model.policy_id != policy_value
        or model.policy_revision != revision
    ):
        raise StandardProficiencyStorageIntegrityError(
            "Persisted calculation-policy identity does not match "
            "canonical path."
        )

    try:
        _load_target_scale_for_write(root, model.target_scale)
    except StandardProficiencyPolicyDependencyError as error:
        raise StandardProficiencyStorageIntegrityError(
            "Persisted calculation-policy target-scale dependency is "
            "invalid."
        ) from error

    return StoredStandardProficiencyCalculationPolicy(
        policy=model,
        policy_sha256=digest,
        path=path,
        relative_path=standard_proficiency_policy_revision_relative_path(
            class_value,
            policy_value,
            revision,
        ),
        content=content,
    )


def list_standard_proficiency_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> tuple[int, ...]:
    "Return verified contiguous revision numbers for one policy family."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = standard_proficiency_policy_directory(
        root,
        class_value,
        policy_value,
    )
    if not relation.exists():
        return ()
    _validate_policy_directory(relation)
    return _list_history_revisions(
        root,
        relation,
        lambda revision: load_standard_proficiency_policy_revision(
            root,
            class_value,
            policy_value,
            revision,
        ).policy,
        validate_standard_proficiency_calculation_policy_transition,
    )


def list_standard_proficiency_policy_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    "List verified policy IDs without selecting one."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = standard_proficiency_policies_directory(
        root,
        class_value,
    )
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect calculation-policy collection."
        ) from error

    result: list[str] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise StandardProficiencyStorageIntegrityError(
                "Calculation-policy collection contains an unexpected entry."
            )
        policy_id = _identifier(entry.name, "policy_id")
        _validate_policy_directory(entry)
        result.append(policy_id)
    return tuple(sorted(result))


def get_current_standard_proficiency_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> int | None:
    pointer = _load_policy_pointer(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    return (
        None
        if pointer is None
        else cast(int, pointer["policy_revision"])
    )


def load_current_standard_proficiency_policy(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> StoredStandardProficiencyCalculationPolicy | None:
    pointer = _load_policy_pointer(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_standard_proficiency_policy_revision(
        workspace_root,
        class_id,
        policy_id,
        cast(int, pointer["policy_revision"]),
    )
    if stored.policy_sha256 != pointer["policy_sha256"]:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy current pointer digest does not match "
            "selected revision."
        )
    return stored


def select_standard_proficiency_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_policy_revision: int | None,
) -> StandardProficiencyPolicySelectionResult:
    "Select one exact historical/current policy revision with CAS."

    root = _root(workspace_root)
    target = load_standard_proficiency_policy_revision(
        root,
        class_id,
        policy_id,
        policy_revision,
    )
    relation = standard_proficiency_policy_directory(
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
            None
            if current is None
            else cast(int, current["policy_revision"])
        )
        if current_revision != expected_current_policy_revision:
            raise StandardProficiencyStorageConflictError(
                "Expected current calculation-policy revision does not "
                "match stored selection."
            )

        pointer = _policy_pointer(target)
        if current == pointer:
            return StandardProficiencyPolicySelectionResult(
                "existing",
                target,
            )

        _atomic_write_pointer(
            root,
            standard_proficiency_policy_current_path(
                root,
                class_id,
                policy_id,
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: StandardProficiencySelectDisposition = (
            "created" if current is None else "updated"
        )
        return StandardProficiencyPolicySelectionResult(
            disposition,
            target,
        )
    finally:
        _remove_lock(lock)



def standard_proficiency_results_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    "Return the class-local result collection root."

    return standards_proficiency_directory(
        workspace_root,
        class_id,
    ) / "results"


def standard_proficiency_standard_key(standard_id: str) -> str:
    "Return a deterministic path-safe key for one durable Core standard ID."

    standard = _standard_id(standard_id)
    return hashlib.sha256(
        _canonical_json_bytes({"standard_id": standard})
    ).hexdigest()


def standard_proficiency_result_family_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    "Return one logical result family's canonical directory."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard_key = standard_proficiency_standard_key(standard_id)
    path = (
        standard_proficiency_results_directory(root, class_value)
        / "grade_items"
        / grade_item
        / "students"
        / student
        / "standards"
        / standard_key
    )
    _require_containment(root, path)
    return path


def standard_proficiency_result_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    return standard_proficiency_result_family_directory(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
    ) / "revisions"


def standard_proficiency_result_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> Path:
    revision = _positive_int(result_revision, "result_revision")
    return standard_proficiency_result_revisions_directory(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
    ) / f"{revision}.json"


def standard_proficiency_result_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    return standard_proficiency_result_family_directory(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
    ) / "current.json"


def standard_proficiency_result_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard_key = standard_proficiency_standard_key(standard_id)
    revision = _positive_int(result_revision, "result_revision")
    return (
        f"classes/{class_value}/modules/meridian/standards_proficiency/"
        f"results/grade_items/{grade_item}/students/{student}/standards/"
        f"{standard_key}/revisions/{revision}.json"
    )


def write_standard_proficiency_result_revision(
    workspace_root: str | Path,
    snapshot: StandardProficiencyResultSnapshot,
) -> StandardProficiencyResultWriteResult:
    "Persist one immutable result revision without selecting it."

    if not isinstance(snapshot, StandardProficiencyResultSnapshot):
        raise StandardProficiencyStorageValidationError(
            "snapshot must be a StandardProficiencyResultSnapshot."
        )
    try:
        content = standard_proficiency_result_snapshot_to_json_bytes(snapshot)
    except (
        StandardProficiencySerializationError,
        StandardProficiencyValidationError,
    ) as error:
        raise StandardProficiencyStorageValidationError(str(error)) from error

    root = _root(workspace_root)
    _require_existing_core_class(root, snapshot.class_id)
    family = standard_proficiency_result_family_directory(
        root,
        snapshot.class_id,
        snapshot.grade_item_id,
        snapshot.student_id,
        snapshot.standard_id,
    )
    revisions = family / "revisions"
    _ensure_directory_chain(root, revisions)
    _validate_result_ancestor_shape(
        root,
        snapshot.class_id,
        snapshot.grade_item_id,
        snapshot.student_id,
    )

    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_result_family_directory(
            family,
            snapshot.standard_id,
        )
        _check_write_size(
            content,
            DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_RESULT_BYTES,
            "result",
        )
        digest = hashlib.sha256(content).hexdigest()
        target = standard_proficiency_result_revision_path(
            root,
            snapshot.class_id,
            snapshot.grade_item_id,
            snapshot.student_id,
            snapshot.standard_id,
            snapshot.result_revision,
        )
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            try:
                stored = load_standard_proficiency_result_revision(
                    root,
                    snapshot.class_id,
                    snapshot.grade_item_id,
                    snapshot.student_id,
                    snapshot.standard_id,
                    snapshot.result_revision,
                )
            except StandardProficiencyStorageError as error:
                raise StandardProficiencyStorageIntegrityError(
                    "Existing standards-proficiency result revision is "
                    "incomplete or invalid."
                ) from error
            if stored.content != content or stored.result_sha256 != digest:
                raise StandardProficiencyStorageConflictError(
                    "Standards-proficiency result revision already exists "
                    "with different content."
                )
            return StandardProficiencyResultWriteResult(
                "existing",
                stored,
            )

        _validate_result_dependencies_for_write(root, snapshot)

        history = list_standard_proficiency_result_revisions(
            root,
            snapshot.class_id,
            snapshot.grade_item_id,
            snapshot.student_id,
            snapshot.standard_id,
        )
        if not history:
            if snapshot.result_revision != 1:
                raise StandardProficiencyStorageConflictError(
                    "Initial standards-proficiency result revision must be 1."
                )
        else:
            if snapshot.result_revision != history[-1] + 1:
                raise StandardProficiencyStorageConflictError(
                    "Standards-proficiency result revision must be contiguous."
                )
            previous = load_standard_proficiency_result_revision(
                root,
                snapshot.class_id,
                snapshot.grade_item_id,
                snapshot.student_id,
                snapshot.standard_id,
                history[-1],
            ).snapshot
            try:
                validate_standard_proficiency_result_transition(
                    previous,
                    snapshot,
                )
            except StandardProficiencyValidationError as error:
                raise StandardProficiencyStorageConflictError(
                    str(error)
                ) from error

        _write_revision_pair(
            target,
            digest_target,
            content,
            digest,
        )
        stored = load_standard_proficiency_result_revision(
            root,
            snapshot.class_id,
            snapshot.grade_item_id,
            snapshot.student_id,
            snapshot.standard_id,
            snapshot.result_revision,
        )
        if stored.content != content or stored.result_sha256 != digest:
            raise StandardProficiencyStorageIntegrityError(
                "Persisted standards-proficiency result differs from "
                "candidate bytes."
            )
        return StandardProficiencyResultWriteResult(
            "created",
            stored,
        )
    finally:
        _remove_lock(lock)


def load_standard_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> StoredStandardProficiencyResult:
    "Load one exact result revision without resolving mutable current state."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    revision = _positive_int(result_revision, "result_revision")

    family = standard_proficiency_result_family_directory(
        root,
        class_value,
        grade_item,
        student,
        standard,
    )
    _validate_result_ancestor_shape(
        root,
        class_value,
        grade_item,
        student,
    )
    _validate_result_family_directory(family, standard)
    path = standard_proficiency_result_revision_path(
        root,
        class_value,
        grade_item,
        student,
        standard,
        revision,
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_RESULT_BYTES,
    )
    try:
        snapshot = standard_proficiency_result_snapshot_from_json_bytes(
            content
        )
    except (
        StandardProficiencySerializationError,
        StandardProficiencyValidationError,
    ) as error:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency result revision is invalid or "
            f"noncanonical: {error}"
        ) from error

    if (
        snapshot.class_id != class_value
        or snapshot.grade_item_id != grade_item
        or snapshot.student_id != student
        or snapshot.standard_id != standard
        or snapshot.result_revision != revision
    ):
        raise StandardProficiencyStorageIntegrityError(
            "Persisted standards-proficiency result identity does not "
            "match its canonical path."
        )

    expected_key = standard_proficiency_standard_key(snapshot.standard_id)
    if family.name != expected_key:
        raise StandardProficiencyStorageIntegrityError(
            "Persisted standard identity does not match its hashed "
            "canonical path."
        )

    return StoredStandardProficiencyResult(
        snapshot=snapshot,
        result_sha256=digest,
        path=path,
        relative_path=standard_proficiency_result_revision_relative_path(
            class_value,
            grade_item,
            student,
            standard,
            revision,
        ),
        content=content,
    )


def list_standard_proficiency_result_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> tuple[int, ...]:
    "Return verified contiguous revisions for one exact result family."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    family = standard_proficiency_result_family_directory(
        root,
        class_value,
        grade_item,
        student,
        standard,
    )
    if not family.exists():
        return ()
    _validate_result_ancestor_shape(
        root,
        class_value,
        grade_item,
        student,
    )
    _validate_result_family_directory(family, standard)
    return _list_history_revisions(
        root,
        family,
        lambda revision: load_standard_proficiency_result_revision(
            root,
            class_value,
            grade_item,
            student,
            standard,
            revision,
        ).snapshot,
        validate_standard_proficiency_result_transition,
    )


def get_current_standard_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> int | None:
    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
        missing_ok=True,
    )
    return (
        None
        if pointer is None
        else cast(int, pointer["result_revision"])
    )


def load_current_standard_proficiency_result(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> StoredStandardProficiencyResult | None:
    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_standard_proficiency_result_revision(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
        cast(int, pointer["result_revision"]),
    )
    if stored.result_sha256 != pointer["result_sha256"]:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer digest does not "
            "match selected revision."
        )
    return stored


def select_standard_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
    *,
    expected_current_result_revision: int | None,
) -> StandardProficiencyResultSelectionResult:
    "Explicitly select one exact persisted result revision with CAS."

    root = _root(workspace_root)
    target = load_standard_proficiency_result_revision(
        root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
        result_revision,
    )
    family = standard_proficiency_result_family_directory(
        root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
    )
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_result_pointer(
            root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            missing_ok=True,
        )
        current_revision = (
            None
            if current is None
            else cast(int, current["result_revision"])
        )
        if current_revision != expected_current_result_revision:
            raise StandardProficiencyStorageConflictError(
                "Expected current standards-proficiency result revision "
                "does not match stored selection."
            )

        pointer = _result_pointer(target)
        if current == pointer:
            return StandardProficiencyResultSelectionResult(
                "existing",
                target,
            )

        _atomic_write_pointer(
            root,
            standard_proficiency_result_current_path(
                root,
                class_id,
                grade_item_id,
                student_id,
                standard_id,
            ),
            _canonical_json_bytes(pointer),
        )
        verified = _load_result_pointer(
            root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            missing_ok=False,
        )
        if verified != pointer:
            raise StandardProficiencyStorageIntegrityError(
                "Published standards-proficiency result selection could "
                "not be verified."
            )
        disposition: StandardProficiencyResultSelectDisposition = (
            "created" if current is None else "updated"
        )
        return StandardProficiencyResultSelectionResult(
            disposition,
            target,
        )
    finally:
        _remove_lock(lock)


def _validate_result_dependencies_for_write(
    root: Path,
    snapshot: StandardProficiencyResultSnapshot,
) -> None:
    basis = snapshot.inputs.grade_item
    try:
        grade_item = load_grade_item_revision(
            root,
            basis.class_id,
            basis.grade_item_id,
            basis.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise StandardProficiencyResultDependencyError(
            "Exact Grade Item revision is unavailable for result write."
        ) from error
    if grade_item.revision_sha256 != basis.grade_item_revision_sha256:
        raise StandardProficiencyResultDependencyError(
            "Exact Grade Item revision digest does not match result inputs."
        )

    policy_ref = snapshot.policy_reference
    try:
        policy = load_standard_proficiency_policy_revision(
            root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except StandardProficiencyStorageError as error:
        raise StandardProficiencyResultDependencyError(
            "Exact calculation-policy revision is unavailable for result "
            "write."
        ) from error
    if policy.policy_sha256 != policy_ref.policy_sha256:
        raise StandardProficiencyResultDependencyError(
            "Exact calculation-policy digest does not match result "
            "provenance."
        )

    scale_ref = snapshot.target_scale
    try:
        scale = load_proficiency_scale_revision(
            root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise StandardProficiencyResultDependencyError(
            "Exact proficiency-scale revision is unavailable for result "
            "write."
        ) from error
    if scale.scale_sha256 != scale_ref.scale_sha256:
        raise StandardProficiencyResultDependencyError(
            "Exact proficiency-scale digest does not match result "
            "provenance."
        )


def _result_pointer(
    stored: StoredStandardProficiencyResult,
) -> dict[str, object]:
    snapshot = stored.snapshot
    return {
        "schema_version": STANDARD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION,
        "record_type": STANDARD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE,
        "class_id": snapshot.class_id,
        "grade_item_id": snapshot.grade_item_id,
        "student_id": snapshot.student_id,
        "standard_id": snapshot.standard_id,
        "standard_key": standard_proficiency_standard_key(
            snapshot.standard_id
        ),
        "result_revision": snapshot.result_revision,
        "result_sha256": stored.result_sha256,
    }


def _load_result_pointer(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    family = standard_proficiency_result_family_directory(
        root,
        class_value,
        grade_item,
        student,
        standard,
    )
    if not family.exists():
        if missing_ok:
            return None
        raise StandardProficiencyStorageNotFoundError(
            "Standards-proficiency result family does not exist."
        )
    _validate_result_ancestor_shape(
        root,
        class_value,
        grade_item,
        student,
    )
    _validate_result_family_directory(family, standard)
    path = family / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise StandardProficiencyStorageNotFoundError(
            "Standards-proficiency result has no explicit current "
            "selection."
        )

    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POINTER_BYTES,
        missing_message=(
            "Standards-proficiency result current pointer does not exist."
        ),
    )
    try:
        decoded = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as error:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer must be UTF-8."
        ) from error
    except StandardProficiencyStorageIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer JSON is invalid."
        ) from error

    if (
        not isinstance(decoded, dict)
        or frozenset(decoded) != _RESULT_POINTER_KEYS
    ):
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer does not use "
            "its exact schema."
        )
    pointer = cast(dict[str, object], decoded)
    if _canonical_json_bytes(pointer) != content:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer is not "
            "canonically encoded."
        )

    if (
        pointer["schema_version"]
        != STANDARD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION
        or pointer["record_type"]
        != STANDARD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE
        or pointer["class_id"] != class_value
        or pointer["grade_item_id"] != grade_item
        or pointer["student_id"] != student
        or pointer["standard_id"] != standard
    ):
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer identity is "
            "invalid."
        )
    expected_key = standard_proficiency_standard_key(standard)
    if pointer["standard_key"] != expected_key:
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency current-result pointer standard key "
            "is invalid."
        )
    _positive_int(pointer["result_revision"], "result_revision")
    _sha256(pointer["result_sha256"], "result_sha256")
    return pointer


def _validate_result_ancestor_shape(
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
) -> None:
    results = standard_proficiency_results_directory(root, class_id)
    if not results.exists():
        return
    _validate_existing_directory_chain(root, results)

    _require_only_named_directory(
        results,
        "grade_items",
        "standards-proficiency result root",
    )
    grade_items = results / "grade_items"
    if not grade_items.exists():
        return
    _require_real_directory(grade_items, "result Grade Item collection")
    _require_identifier_directory_collection(
        grade_items,
        "grade_item_id",
        "result Grade Item collection",
    )

    grade_item = grade_items / grade_item_id
    if not grade_item.exists():
        return
    _require_real_directory(grade_item, "result Grade Item scope")
    _require_only_named_directory(
        grade_item,
        "students",
        "result Grade Item scope",
    )

    students = grade_item / "students"
    if not students.exists():
        return
    _require_real_directory(students, "result student collection")
    _require_identifier_directory_collection(
        students,
        "student_id",
        "result student collection",
    )

    student = students / student_id
    if not student.exists():
        return
    _require_real_directory(student, "result student scope")
    _require_only_named_directory(
        student,
        "standards",
        "result student scope",
    )

    standards = student / "standards"
    if not standards.exists():
        return
    _require_real_directory(standards, "result standards collection")
    try:
        entries = tuple(standards.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect standards-proficiency result families."
        ) from error
    for entry in entries:
        if (
            _SHA256.fullmatch(entry.name) is None
            or entry.is_symlink()
            or not entry.is_dir()
        ):
            raise StandardProficiencyStorageIntegrityError(
                "Standards-proficiency standards collection contains an "
                "unsafe or unexpected entry."
            )


def _validate_result_family_directory(
    family: Path,
    standard_id: str,
) -> None:
    if not family.exists():
        return
    _require_real_directory(family, "standards-proficiency result family")
    if family.name != standard_proficiency_standard_key(standard_id):
        raise StandardProficiencyStorageIntegrityError(
            "Standards-proficiency result-family key does not match "
            "standard identity."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(family.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect standards-proficiency result family."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise StandardProficiencyStorageIntegrityError(
                "Standards-proficiency result family contains an "
                "unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise StandardProficiencyStorageIntegrityError(
                    "Standards-proficiency result revisions entry must "
                    "be a real directory."
                )
            _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise StandardProficiencyStorageIntegrityError(
                "Standards-proficiency result pointer/lock entry must "
                "be a regular file."
            )


def _require_real_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise StandardProficiencyStorageIntegrityError(
            f"{label} must be a real directory."
        )


def _require_identifier_directory_collection(
    parent: Path,
    field_name: str,
    label: str,
) -> None:
    try:
        entries = tuple(parent.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            f"Could not inspect {label}."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise StandardProficiencyStorageIntegrityError(
                f"{label} contains an unexpected entry."
            )
        _identifier(entry.name, field_name)


def _require_only_named_directory(
    parent: Path,
    expected_name: str,
    label: str,
) -> None:
    try:
        entries = tuple(parent.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            f"Could not inspect {label}."
        ) from error
    for entry in entries:
        if (
            entry.name != expected_name
            or entry.is_symlink()
            or not entry.is_dir()
        ):
            raise StandardProficiencyStorageIntegrityError(
                f"{label} contains an unexpected entry."
            )


def _load_target_scale_for_write(
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
        raise StandardProficiencyPolicyDependencyError(
            "Exact target proficiency-scale revision is unavailable."
        ) from error
    if stored.scale_sha256 != reference.scale_sha256:
        raise StandardProficiencyPolicyDependencyError(
            "Exact target proficiency-scale digest does not match "
            "calculation-policy reference."
        )
    return stored


def _load_existing_policy_for_replay(
    root: Path,
    candidate: StandardProficiencyCalculationPolicy,
) -> StoredStandardProficiencyCalculationPolicy:
    try:
        return load_standard_proficiency_policy_revision(
            root,
            candidate.class_id,
            candidate.policy_id,
            candidate.policy_revision,
        )
    except StandardProficiencyStorageError as error:
        raise StandardProficiencyStorageIntegrityError(
            "Existing calculation-policy revision is incomplete or invalid."
        ) from error


def _policy_pointer(
    stored: StoredStandardProficiencyCalculationPolicy,
) -> dict[str, object]:
    return {
        "schema_version": (
            STANDARD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION
        ),
        "record_type": STANDARD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE,
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
    path = standard_proficiency_policy_current_path(
        root,
        class_value,
        policy_value,
    )
    if not path.exists():
        if missing_ok:
            return None
        raise StandardProficiencyStorageNotFoundError(
            "Calculation-policy current pointer does not exist."
        )

    mapping = _read_pointer(
        root,
        path,
        _POINTER_KEYS,
    )
    if (
        mapping["schema_version"]
        != STANDARD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION
        or mapping["record_type"]
        != STANDARD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE
        or mapping["class_id"] != class_value
        or mapping["policy_id"] != policy_value
    ):
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy current pointer identity is invalid."
        )
    _positive_int(mapping["policy_revision"], "policy_revision")
    _sha256(mapping["policy_sha256"], "policy_sha256")
    return mapping


def _read_pointer(
    root: Path,
    path: Path,
    keys: frozenset[str],
) -> dict[str, object]:
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_POINTER_BYTES,
        missing_message=(
            "Calculation-policy current pointer does not exist."
        ),
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy pointer must be UTF-8."
        ) from error

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except StandardProficiencyStorageIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy pointer JSON is invalid."
        ) from error

    if not isinstance(decoded, dict) or frozenset(decoded) != keys:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy pointer does not use its exact schema."
        )
    mapping = cast(dict[str, object], decoded)
    if _canonical_json_bytes(mapping) != content:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy pointer is not canonically encoded."
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
        raise StandardProficiencyStorageReadError(
            "Could not inspect immutable calculation-policy history."
        ) from error

    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise StandardProficiencyStorageIntegrityError(
                "Calculation-policy history contains an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise StandardProficiencyStorageIntegrityError(
                "Calculation-policy history contains an unexpected file."
            )

    if json_numbers != digest_numbers:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy JSON and digest sidecars are incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy history must be contiguous from 1."
        )
    if not revisions:
        return ()

    previous: _HistoryT | None = None
    for revision in revisions:
        current = loader(revision)
        if previous is not None:
            try:
                transition(previous, current)
            except StandardProficiencyValidationError as error:
                raise StandardProficiencyStorageIntegrityError(
                    "Persisted calculation-policy transition is invalid: "
                    f"{error}"
                ) from error
        previous = current
    return revisions


def _validate_policy_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect calculation-policy canonical root."
        ) from error

    for entry in entries:
        if entry.name not in allowed:
            raise StandardProficiencyStorageIntegrityError(
                "Calculation-policy canonical root contains an "
                "unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise StandardProficiencyStorageIntegrityError(
                    "Calculation-policy revisions entry must be a real "
                    "directory."
                )
            _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise StandardProficiencyStorageIntegrityError(
                "Calculation-policy pointer/lock entry must be a regular "
                "file."
            )


def _validate_revision_directory_shape(path: Path) -> None:
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect immutable calculation-policy revision "
            "directory."
        ) from error

    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise StandardProficiencyStorageIntegrityError(
                "Immutable calculation-policy revision directory contains "
                "an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise StandardProficiencyStorageIntegrityError(
                "Immutable calculation-policy revision directory contains "
                "an unexpected file."
            )
    if json_numbers != digest_numbers:
        raise StandardProficiencyStorageIntegrityError(
            "Immutable calculation-policy JSON/digest pairs are incomplete."
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
        missing_message=(
            "Immutable calculation-policy revision does not exist."
        ),
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_STANDARD_PROFICIENCY_DIGEST_BYTES,
        missing_message=(
            "Immutable calculation-policy digest does not exist."
        ),
    )
    expected = _parse_digest_sidecar(digest_bytes)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise StandardProficiencyStorageIntegrityError(
            "Immutable calculation-policy revision digest does not match "
            "exact JSON bytes."
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
        _exclusive_write(
            digest_path,
            (digest + "\n").encode("ascii"),
        )
        created_digest = True
        _fsync_directory(path.parent)
    except FileExistsError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise StandardProficiencyStorageConflictError(
            "Immutable calculation-policy revision identity already "
            "exists."
        ) from error
    except OSError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise StandardProficiencyStorageWriteError(
            "Could not persist immutable calculation-policy revision."
        ) from error


def _atomic_write_pointer(
    root: Path,
    path: Path,
    content: bytes,
) -> None:
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
            raise StandardProficiencyStorageWriteError(
                "Temporary calculation-policy pointer is unsafe."
            )
        os.replace(temp_path, path)
        temporary = None
        _fsync_directory(path.parent)
    except StandardProficiencyStorageError:
        raise
    except OSError as error:
        raise StandardProficiencyStorageWriteError(
            "Could not publish calculation-policy current pointer "
            "atomically."
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
        raise StandardProficiencyStorageLockError(
            "Another writer already owns this calculation-policy history."
        )
    try:
        _exclusive_write(path, b"locked\n")
    except FileExistsError as error:
        raise StandardProficiencyStorageLockError(
            "Another writer already owns this calculation-policy history."
        ) from error
    except OSError as error:
        raise StandardProficiencyStorageWriteError(
            "Could not acquire calculation-policy write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise StandardProficiencyStorageWriteError(
            "Could not remove calculation-policy write lock."
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
        raise StandardProficiencyStorageNotFoundError(
            "Workspace root must exist before calculation-policy storage "
            "is used."
        )
    if current.is_symlink() or not current.is_dir():
        raise StandardProficiencyStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )

    for component in relative.parts:
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise StandardProficiencyStorageIntegrityError(
                    "Canonical calculation-policy directory chain is unsafe."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise StandardProficiencyStorageWriteError(
                "Could not create canonical calculation-policy directory."
            ) from error


def _validate_existing_directory_chain(
    root: Path,
    target: Path,
) -> None:
    _require_containment(root, target)
    relative = target.relative_to(root)
    current = root
    if current.is_symlink() or not current.is_dir():
        raise StandardProficiencyStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )

    for component in relative.parts:
        current = current / component
        if not current.exists():
            raise StandardProficiencyStorageNotFoundError(
                "Canonical calculation-policy directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise StandardProficiencyStorageIntegrityError(
                "Canonical calculation-policy directory chain is unsafe."
            )


def _read_bounded_regular_file(
    path: Path,
    maximum: int,
    *,
    missing_message: str,
) -> bytes:
    if not path.exists():
        raise StandardProficiencyStorageNotFoundError(missing_message)
    if path.is_symlink() or not path.is_file():
        raise StandardProficiencyStorageIntegrityError(
            "Canonical calculation-policy file is unsafe or not a regular "
            "file."
        )
    try:
        size = path.stat().st_size
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not inspect canonical calculation-policy file."
        ) from error
    if size > maximum:
        raise StandardProficiencyStorageTooLargeError(
            "Canonical calculation-policy file exceeds configured byte "
            "limit."
        )
    try:
        with path.open("rb") as handle:
            content = handle.read(maximum + 1)
    except OSError as error:
        raise StandardProficiencyStorageReadError(
            "Could not read canonical calculation-policy file."
        ) from error
    if len(content) > maximum:
        raise StandardProficiencyStorageTooLargeError(
            "Canonical calculation-policy file exceeds configured byte "
            "limit."
        )
    return content


def _parse_digest_sidecar(content: bytes) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy digest sidecar must use one canonical LF."
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
        raise StandardProficiencyStorageIntegrityError(
            "Calculation-policy pointer cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StandardProficiencyStorageIntegrityError(
                f"Duplicate calculation-policy pointer key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise StandardProficiencyStorageIntegrityError(
        "Non-finite calculation-policy pointer value is invalid: "
        f"{value}"
    )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise StandardProficiencyStorageNotFoundError(
            "Core class workspace must exist before calculation-policy "
            "creation."
        )
    _validate_existing_directory_chain(root, path)


def _check_write_size(
    content: bytes,
    maximum: int,
    label: str,
) -> None:
    if len(content) > maximum:
        raise StandardProficiencyStorageWriteError(
            f"Canonical {label} revision exceeds configured byte limit."
        )


def _root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise StandardProficiencyStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(value)
    if not root.is_absolute():
        root = root.absolute()
    return root


def _standard_id(value: object) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyStorageValidationError(
            "standard_id must be a string."
        )
    normalized = value.strip()
    if not normalized:
        raise StandardProficiencyStorageValidationError(
            "standard_id must not be blank."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise StandardProficiencyStorageValidationError(
            "standard_id must not contain control characters."
        )
    return normalized


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardProficiencyStorageValidationError(
            str(error)
        ) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StandardProficiencyStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardProficiencyStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise StandardProficiencyStorageValidationError(
            "Calculation-policy path escapes workspace root."
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
