"Canonical storage for Academic Period proficiency policies and results."

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

from pds_core.academic_period_queries import (
    AcademicPeriodLookupError,
    get_academic_period,
)
from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    validate_academic_period_ref,
)
from pds_core.class_metadata import ClassMetadataError, load_class_metadata
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_metadata_path, class_module_dir

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyResultReference,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencySerializationError,
    AcademicPeriodProficiencyValidationError,
    academic_period_proficiency_aggregation_policy_from_json_bytes,
    academic_period_proficiency_aggregation_policy_to_json_bytes,
    academic_period_proficiency_result_snapshot_from_json_bytes,
    academic_period_proficiency_result_snapshot_to_json_bytes,
    validate_academic_period_proficiency_aggregation_policy,
    validate_academic_period_proficiency_aggregation_policy_transition,
    validate_academic_period_proficiency_result_transition,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    load_grade_item_membership_revision,
)
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
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    load_standard_proficiency_result_revision,
)

ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_academic_period_proficiency_aggregation_policy_current"
)
DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POLICY_BYTES: Final[int] = 128 * 1024
DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_DIGEST_BYTES: Final[int] = 128
DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULT_BYTES: Final[int] = (
    8 * 1024 * 1024
)
ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION: Final[str] = "1"
ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_academic_period_proficiency_result_current"
)

AcademicPeriodProficiencyWriteDisposition: TypeAlias = Literal["created", "existing"]
AcademicPeriodProficiencySelectDisposition: TypeAlias = Literal[
    "created",
    "updated",
    "existing",
]
AcademicPeriodProficiencyResultWriteDisposition: TypeAlias = Literal[
    "created",
    "existing",
]
AcademicPeriodProficiencyResultSelectDisposition: TypeAlias = Literal[
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
        "school_year",
        "period_id",
        "student_id",
        "standard_id",
        "standard_key",
        "result_revision",
        "result_sha256",
    }
)

_HistoryT = TypeVar("_HistoryT")


class AcademicPeriodProficiencyStorageError(RuntimeError):
    "Base error for Academic Period proficiency persistence failures."

    code: str = "academic_period_proficiency.storage_error"


class AcademicPeriodProficiencyStorageValidationError(
    AcademicPeriodProficiencyStorageError,
    ValueError,
):
    "Raised for invalid Academic Period proficiency storage API arguments."

    code = "academic_period_proficiency.storage_invalid"


class AcademicPeriodProficiencyStorageNotFoundError(
    AcademicPeriodProficiencyStorageError
):
    "Raised when explicitly requested Academic Period proficiency state is absent."

    code = "academic_period_proficiency.not_found"


class AcademicPeriodProficiencyStorageReadError(AcademicPeriodProficiencyStorageError):
    "Raised when Academic Period proficiency state cannot be read safely."

    code = "academic_period_proficiency.read_failed"


class AcademicPeriodProficiencyStorageWriteError(AcademicPeriodProficiencyStorageError):
    "Raised when policy state cannot be written safely."

    code = "academic_period_proficiency.write_failed"


class AcademicPeriodProficiencyStorageConflictError(
    AcademicPeriodProficiencyStorageError
):
    "Raised for stale writes or identity/content collisions."

    code = "academic_period_proficiency.conflict"


class AcademicPeriodProficiencyStorageLockError(
    AcademicPeriodProficiencyStorageConflictError
):
    "Raised when another writer owns one logical policy history."

    code = "academic_period_proficiency.locked"


class AcademicPeriodProficiencyStorageIntegrityError(
    AcademicPeriodProficiencyStorageError
):
    "Raised when persisted Academic Period proficiency state fails validation."

    code = "academic_period_proficiency.integrity_failed"


class AcademicPeriodProficiencyStorageTooLargeError(
    AcademicPeriodProficiencyStorageReadError
):
    "Raised when persisted state exceeds configured read bounds."

    code = "academic_period_proficiency.too_large"


class AcademicPeriodProficiencyPolicyDependencyError(
    AcademicPeriodProficiencyStorageConflictError
):
    "Raised when a policy's exact target scale cannot be verified."

    code = "academic_period_proficiency.policy_dependency_invalid"


class AcademicPeriodProficiencyResultDependencyError(
    AcademicPeriodProficiencyStorageConflictError
):
    "Raised when an exact dependency cannot be verified for a new result write."

    code = "academic_period_proficiency.result_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredAcademicPeriodProficiencyAggregationPolicy:
    "Verified immutable Academic Period proficiency aggregation-policy revision."

    policy: AcademicPeriodProficiencyAggregationPolicy
    policy_sha256: str
    path: Path
    relative_path: str
    content: bytes

    @property
    def reference(self) -> AcademicPeriodProficiencyAggregationPolicyReference:
        return AcademicPeriodProficiencyAggregationPolicyReference(
            class_id=self.policy.class_id,
            policy_id=self.policy.policy_id,
            policy_revision=self.policy.policy_revision,
            policy_sha256=self.policy_sha256,
        )


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyPolicyWriteResult:
    disposition: AcademicPeriodProficiencyWriteDisposition
    stored: StoredAcademicPeriodProficiencyAggregationPolicy


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyPolicySelectionResult:
    disposition: AcademicPeriodProficiencySelectDisposition
    stored: StoredAcademicPeriodProficiencyAggregationPolicy


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyResultWriteResult:
    disposition: AcademicPeriodProficiencyResultWriteDisposition
    stored: "StoredAcademicPeriodProficiencyResult"


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyResultSelectionResult:
    disposition: AcademicPeriodProficiencyResultSelectDisposition
    stored: "StoredAcademicPeriodProficiencyResult"


@dataclass(frozen=True, slots=True)
class StoredAcademicPeriodProficiencyResult:
    """One verified immutable #35 Academic Period proficiency result revision."""

    snapshot: AcademicPeriodProficiencyResultSnapshot
    result_sha256: str
    path: Path
    relative_path: str
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AcademicPeriodProficiencyResultSnapshot):
            raise AcademicPeriodProficiencyStorageValidationError(
                "snapshot must be an AcademicPeriodProficiencyResultSnapshot."
            )
        digest = _sha256(self.result_sha256, "result_sha256")
        if type(self.content) is not bytes:
            raise AcademicPeriodProficiencyStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise AcademicPeriodProficiencyStorageValidationError(
                "result_sha256 does not match exact stored result bytes."
            )
        try:
            decoded = academic_period_proficiency_result_snapshot_from_json_bytes(
                self.content
            )
        except (
            AcademicPeriodProficiencySerializationError,
            AcademicPeriodProficiencyValidationError,
        ) as error:
            raise AcademicPeriodProficiencyStorageValidationError(
                "content is not a canonical Academic Period proficiency result."
            ) from error
        if decoded != self.snapshot:
            raise AcademicPeriodProficiencyStorageValidationError(
                "content does not decode to snapshot."
            )
        expected = academic_period_proficiency_result_revision_relative_path(
            self.snapshot.class_id,
            self.snapshot.target_period.period.school_year,
            self.snapshot.target_period.period.period_id,
            self.snapshot.student_id,
            self.snapshot.standard_id,
            self.snapshot.result_revision,
        )
        if self.relative_path != expected:
            raise AcademicPeriodProficiencyStorageValidationError(
                "relative_path is not the canonical result revision location."
            )
        if self.path.name != f"{self.snapshot.result_revision}.json":
            raise AcademicPeriodProficiencyStorageValidationError(
                "path filename does not match result revision identity."
            )
        object.__setattr__(self, "result_sha256", digest)

    @property
    def reference(self) -> AcademicPeriodProficiencyResultReference:
        snapshot = self.snapshot
        return AcademicPeriodProficiencyResultReference(
            class_id=snapshot.class_id,
            school_year=snapshot.target_period.period.school_year,
            period_id=snapshot.target_period.period.period_id,
            student_id=snapshot.student_id,
            standard_id=snapshot.standard_id,
            result_revision=snapshot.result_revision,
            result_sha256=self.result_sha256,
        )


def academic_period_proficiency_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    "Return the class-local Academic Period proficiency storage root."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "academic_period_proficiency"
    )
    _require_containment(root, path)
    return path


def academic_period_proficiency_policies_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    return academic_period_proficiency_directory(
        workspace_root,
        class_id,
    ) / "policies"


def academic_period_proficiency_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    policy = _identifier(policy_id, "policy_id")
    return academic_period_proficiency_policies_directory(
        workspace_root,
        class_id,
    ) / policy


def academic_period_proficiency_policy_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return academic_period_proficiency_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "revisions"


def academic_period_proficiency_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> Path:
    revision = _positive_int(policy_revision, "policy_revision")
    return academic_period_proficiency_policy_revisions_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / f"{revision}.json"


def academic_period_proficiency_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> Path:
    return academic_period_proficiency_policy_directory(
        workspace_root,
        class_id,
        policy_id,
    ) / "current.json"


def academic_period_proficiency_policy_revision_relative_path(
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    policy = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    return (
        f"classes/{class_value}/modules/meridian/academic_period_proficiency/"
        f"policies/{policy}/revisions/{revision}.json"
    )


def write_academic_period_proficiency_policy_revision(
    workspace_root: str | Path,
    policy: AcademicPeriodProficiencyAggregationPolicy,
) -> AcademicPeriodProficiencyPolicyWriteResult:
    "Persist one immutable policy revision without selecting it."

    candidate = validate_academic_period_proficiency_aggregation_policy(policy)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)

    target = academic_period_proficiency_policy_revision_path(
        root,
        candidate.class_id,
        candidate.policy_id,
        candidate.policy_revision,
    )
    relation = academic_period_proficiency_policy_directory(
        root,
        candidate.class_id,
        candidate.policy_id,
    )
    _ensure_directory_chain(root, target.parent)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_policy_directory(relation)
        content = academic_period_proficiency_aggregation_policy_to_json_bytes(
            candidate
        )
        _check_write_size(
            content,
            DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POLICY_BYTES,
            "policy",
        )
        digest = hashlib.sha256(content).hexdigest()
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            stored = _load_existing_policy_for_replay(root, candidate)
            if stored.content != content or stored.policy_sha256 != digest:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Academic Period proficiency policy revision already exists with "
                    "different content."
                )
            return AcademicPeriodProficiencyPolicyWriteResult(
                "existing",
                stored,
            )

        _load_target_scale_for_write(root, candidate.target_scale)

        history = list_academic_period_proficiency_policy_revisions(
            root,
            candidate.class_id,
            candidate.policy_id,
        )
        if not history:
            if candidate.policy_revision != 1:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Initial Academic Period proficiency policy revision must be 1."
                )
        else:
            if candidate.policy_revision != history[-1] + 1:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Academic Period proficiency policy revision must be contiguous."
                )
            previous = load_academic_period_proficiency_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                history[-1],
            ).policy
            try:
                validate_academic_period_proficiency_aggregation_policy_transition(
                    previous,
                    candidate,
                )
            except AcademicPeriodProficiencyValidationError as error:
                raise AcademicPeriodProficiencyStorageConflictError(
                    str(error)
                ) from error

        _write_revision_pair(
            target,
            digest_target,
            content,
            digest,
        )
        return AcademicPeriodProficiencyPolicyWriteResult(
            "created",
            load_academic_period_proficiency_policy_revision(
                root,
                candidate.class_id,
                candidate.policy_id,
                candidate.policy_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_academic_period_proficiency_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
) -> StoredAcademicPeriodProficiencyAggregationPolicy:
    "Load and verify one exact immutable policy revision."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    relation = academic_period_proficiency_policy_directory(
        root,
        class_value,
        policy_value,
    )
    _validate_policy_directory(relation)
    path = academic_period_proficiency_policy_revision_path(
        root,
        class_value,
        policy_value,
        revision,
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POLICY_BYTES,
    )
    try:
        model = academic_period_proficiency_aggregation_policy_from_json_bytes(
            content
        )
    except (
        AcademicPeriodProficiencySerializationError,
        AcademicPeriodProficiencyValidationError,
    ) as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy revision is invalid or noncanonical: "
            f"{error}"
        ) from error

    if (
        model.class_id != class_value
        or model.policy_id != policy_value
        or model.policy_revision != revision
    ):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Persisted Academic Period proficiency policy identity does not match "
            "canonical path."
        )

    try:
        _load_target_scale_for_write(root, model.target_scale)
    except AcademicPeriodProficiencyPolicyDependencyError as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Persisted Academic Period proficiency policy target-scale dependency is "
            "invalid."
        ) from error

    return StoredAcademicPeriodProficiencyAggregationPolicy(
        policy=model,
        policy_sha256=digest,
        path=path,
        relative_path=academic_period_proficiency_policy_revision_relative_path(
            class_value,
            policy_value,
            revision,
        ),
        content=content,
    )


def list_academic_period_proficiency_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> tuple[int, ...]:
    "Return verified contiguous revision numbers for one policy family."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    policy_value = _identifier(policy_id, "policy_id")
    relation = academic_period_proficiency_policy_directory(
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
        lambda revision: load_academic_period_proficiency_policy_revision(
            root,
            class_value,
            policy_value,
            revision,
        ).policy,
        validate_academic_period_proficiency_aggregation_policy_transition,
    )


def list_academic_period_proficiency_policy_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    "List verified policy IDs without selecting one."

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = academic_period_proficiency_policies_directory(
        root,
        class_value,
    )
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect Academic Period proficiency policy collection."
        ) from error

    result: list[str] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency policy collection contains an "
                "unexpected entry."
            )
        policy_id = _identifier(entry.name, "policy_id")
        _validate_policy_directory(entry)
        result.append(policy_id)
    return tuple(sorted(result))


def get_current_academic_period_proficiency_policy_revision(
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


def load_current_academic_period_proficiency_policy(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
) -> StoredAcademicPeriodProficiencyAggregationPolicy | None:
    pointer = _load_policy_pointer(
        workspace_root,
        class_id,
        policy_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_academic_period_proficiency_policy_revision(
        workspace_root,
        class_id,
        policy_id,
        cast(int, pointer["policy_revision"]),
    )
    if stored.policy_sha256 != pointer["policy_sha256"]:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy current pointer digest does not match "
            "selected revision."
        )
    return stored


def select_academic_period_proficiency_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_policy_revision: int | None,
) -> AcademicPeriodProficiencyPolicySelectionResult:
    "Select one exact historical/current policy revision with CAS."

    root = _root(workspace_root)
    target = load_academic_period_proficiency_policy_revision(
        root,
        class_id,
        policy_id,
        policy_revision,
    )
    relation = academic_period_proficiency_policy_directory(
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
            raise AcademicPeriodProficiencyStorageConflictError(
                "Expected current Academic Period proficiency policy revision does not "
                "match stored selection."
            )

        pointer = _policy_pointer(target)
        if current == pointer:
            return AcademicPeriodProficiencyPolicySelectionResult(
                "existing",
                target,
            )

        _atomic_write_pointer(
            root,
            academic_period_proficiency_policy_current_path(
                root,
                class_id,
                policy_id,
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: AcademicPeriodProficiencySelectDisposition = (
            "created" if current is None else "updated"
        )
        return AcademicPeriodProficiencyPolicySelectionResult(
            disposition,
            target,
        )
    finally:
        _remove_lock(lock)


def academic_period_proficiency_results_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    """Return the class-local #35 Academic Period result collection root."""

    return academic_period_proficiency_directory(
        workspace_root,
        class_id,
    ) / "results"


def academic_period_proficiency_standard_key(standard_id: str) -> str:
    """Return a deterministic path-safe key for one durable Core standard ID."""

    standard = _standard_id(standard_id)
    return hashlib.sha256(
        _canonical_json_bytes({"standard_id": standard})
    ).hexdigest()


def academic_period_proficiency_result_family_directory(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    """Return one durable class/period/student/standard result-family directory."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(school_year, period_id)
    student = _identifier(student_id, "student_id")
    standard_key = academic_period_proficiency_standard_key(standard_id)
    path = (
        academic_period_proficiency_results_directory(root, class_value)
        / "school_years"
        / period.school_year
        / "periods"
        / period.period_id
        / "students"
        / student
        / "standards"
        / standard_key
    )
    _require_containment(root, path)
    return path


def academic_period_proficiency_result_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    return academic_period_proficiency_result_family_directory(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
    ) / "revisions"


def academic_period_proficiency_result_revision_path(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> Path:
    revision = _positive_int(result_revision, "result_revision")
    return academic_period_proficiency_result_revisions_directory(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
    ) / f"{revision}.json"


def academic_period_proficiency_result_current_path(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> Path:
    """Return one durable #35 result family's explicit current pointer path."""

    return academic_period_proficiency_result_family_directory(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
    ) / "current.json"


def academic_period_proficiency_result_revision_relative_path(
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(school_year, period_id)
    student = _identifier(student_id, "student_id")
    standard_key = academic_period_proficiency_standard_key(standard_id)
    revision = _positive_int(result_revision, "result_revision")
    return (
        f"classes/{class_value}/modules/meridian/academic_period_proficiency/"
        f"results/school_years/{period.school_year}/periods/{period.period_id}/"
        f"students/{student}/standards/{standard_key}/revisions/{revision}.json"
    )


def write_academic_period_proficiency_result_revision(
    workspace_root: str | Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> AcademicPeriodProficiencyResultWriteResult:
    """Persist one immutable #35 result revision without selecting it."""

    if not isinstance(snapshot, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyStorageValidationError(
            "snapshot must be an AcademicPeriodProficiencyResultSnapshot."
        )
    try:
        content = academic_period_proficiency_result_snapshot_to_json_bytes(
            snapshot
        )
    except (
        AcademicPeriodProficiencySerializationError,
        AcademicPeriodProficiencyValidationError,
    ) as error:
        raise AcademicPeriodProficiencyStorageValidationError(str(error)) from error

    root = _root(workspace_root)
    _require_existing_core_class(root, snapshot.class_id)
    period = snapshot.target_period.period
    family = academic_period_proficiency_result_family_directory(
        root,
        snapshot.class_id,
        period.school_year,
        period.period_id,
        snapshot.student_id,
        snapshot.standard_id,
    )
    revisions = family / "revisions"
    _ensure_directory_chain(root, revisions)
    _validate_result_ancestor_shape(
        root,
        snapshot.class_id,
        period.school_year,
        period.period_id,
        snapshot.student_id,
    )

    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_result_family_directory(family, snapshot.standard_id)
        _check_write_size(
            content,
            DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULT_BYTES,
            "result",
        )
        digest = hashlib.sha256(content).hexdigest()
        target = academic_period_proficiency_result_revision_path(
            root,
            snapshot.class_id,
            period.school_year,
            period.period_id,
            snapshot.student_id,
            snapshot.standard_id,
            snapshot.result_revision,
        )
        digest_target = Path(str(target) + ".sha256")

        if target.exists() or digest_target.exists():
            try:
                stored = load_academic_period_proficiency_result_revision(
                    root,
                    snapshot.class_id,
                    period.school_year,
                    period.period_id,
                    snapshot.student_id,
                    snapshot.standard_id,
                    snapshot.result_revision,
                )
            except AcademicPeriodProficiencyStorageError as error:
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Existing Academic Period proficiency result revision is "
                    "incomplete or invalid."
                ) from error
            if stored.content != content or stored.result_sha256 != digest:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Academic Period proficiency result revision already exists "
                    "with different content."
                )
            return AcademicPeriodProficiencyResultWriteResult(
                "existing",
                stored,
            )

        _validate_result_dependencies_for_write(root, snapshot)

        history = list_academic_period_proficiency_result_revisions(
            root,
            snapshot.class_id,
            period.school_year,
            period.period_id,
            snapshot.student_id,
            snapshot.standard_id,
        )
        if not history:
            if snapshot.result_revision != 1:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Initial Academic Period proficiency result revision must be 1."
                )
        else:
            if snapshot.result_revision != history[-1] + 1:
                raise AcademicPeriodProficiencyStorageConflictError(
                    "Academic Period proficiency result revision must be contiguous."
                )
            previous = load_academic_period_proficiency_result_revision(
                root,
                snapshot.class_id,
                period.school_year,
                period.period_id,
                snapshot.student_id,
                snapshot.standard_id,
                history[-1],
            ).snapshot
            try:
                validate_academic_period_proficiency_result_transition(
                    previous,
                    snapshot,
                )
            except AcademicPeriodProficiencyValidationError as error:
                raise AcademicPeriodProficiencyStorageConflictError(
                    str(error)
                ) from error

        _write_result_revision_pair(
            target,
            digest_target,
            content,
            digest,
        )
        stored = load_academic_period_proficiency_result_revision(
            root,
            snapshot.class_id,
            period.school_year,
            period.period_id,
            snapshot.student_id,
            snapshot.standard_id,
            snapshot.result_revision,
        )
        if stored.content != content or stored.result_sha256 != digest:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Persisted Academic Period proficiency result differs from "
                "candidate bytes."
            )
        return AcademicPeriodProficiencyResultWriteResult(
            "created",
            stored,
        )
    finally:
        _remove_lock(lock)


def load_academic_period_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> StoredAcademicPeriodProficiencyResult:
    """Load one exact immutable #35 result revision without resolving current state."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(school_year, period_id)
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    revision = _positive_int(result_revision, "result_revision")
    family = academic_period_proficiency_result_family_directory(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
        standard,
    )
    _validate_result_ancestor_shape(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
    )
    _validate_result_family_directory(family, standard)
    path = academic_period_proficiency_result_revision_path(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
        standard,
        revision,
    )
    content, digest = _read_result_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULT_BYTES,
    )
    try:
        snapshot = academic_period_proficiency_result_snapshot_from_json_bytes(
            content
        )
    except (
        AcademicPeriodProficiencySerializationError,
        AcademicPeriodProficiencyValidationError,
    ) as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result revision is invalid or "
            f"noncanonical: {error}"
        ) from error

    snapshot_period = snapshot.target_period.period
    if (
        snapshot.class_id != class_value
        or snapshot_period.school_year != period.school_year
        or snapshot_period.period_id != period.period_id
        or snapshot.student_id != student
        or snapshot.standard_id != standard
        or snapshot.result_revision != revision
    ):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Persisted Academic Period proficiency result identity does not "
            "match its canonical path."
        )

    expected_key = academic_period_proficiency_standard_key(snapshot.standard_id)
    if family.name != expected_key:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Persisted standard identity does not match its hashed canonical path."
        )

    return StoredAcademicPeriodProficiencyResult(
        snapshot=snapshot,
        result_sha256=digest,
        path=path,
        relative_path=academic_period_proficiency_result_revision_relative_path(
            class_value,
            period.school_year,
            period.period_id,
            student,
            standard,
            revision,
        ),
        content=content,
    )


def list_academic_period_proficiency_result_revisions(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> tuple[int, ...]:
    """Return verified contiguous revisions for one durable #35 result family."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(school_year, period_id)
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    family = academic_period_proficiency_result_family_directory(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
        standard,
    )
    if not family.exists():
        return ()
    _validate_result_ancestor_shape(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
    )
    _validate_result_family_directory(family, standard)
    revisions = _result_revision_numbers(family)
    previous: AcademicPeriodProficiencyResultSnapshot | None = None
    for revision in revisions:
        current = load_academic_period_proficiency_result_revision(
            root,
            class_value,
            period.school_year,
            period.period_id,
            student,
            standard,
            revision,
        ).snapshot
        if previous is not None:
            try:
                validate_academic_period_proficiency_result_transition(
                    previous,
                    current,
                )
            except AcademicPeriodProficiencyValidationError as error:
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Persisted Academic Period proficiency result transition is "
                    f"invalid: {error}"
                ) from error
        previous = current
    return revisions


def get_current_academic_period_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> int | None:
    """Return the explicitly selected #35 result revision, if any."""

    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
        missing_ok=True,
    )
    return None if pointer is None else cast(int, pointer["result_revision"])


def load_current_academic_period_proficiency_result(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> StoredAcademicPeriodProficiencyResult | None:
    """Load the explicitly selected #35 result revision, if configured."""

    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_academic_period_proficiency_result_revision(
        workspace_root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
        cast(int, pointer["result_revision"]),
    )
    if stored.result_sha256 != pointer["result_sha256"]:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency current-result pointer digest does "
            "not match selected revision."
        )
    return stored


def select_academic_period_proficiency_result_revision(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
    *,
    expected_current_result_revision: int | None,
) -> AcademicPeriodProficiencyResultSelectionResult:
    """Explicitly select one exact persisted #35 result revision with CAS."""

    root = _root(workspace_root)
    target = load_academic_period_proficiency_result_revision(
        root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
        result_revision,
    )
    family = academic_period_proficiency_result_family_directory(
        root,
        class_id,
        school_year,
        period_id,
        student_id,
        standard_id,
    )
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_result_pointer(
            root,
            class_id,
            school_year,
            period_id,
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
            raise AcademicPeriodProficiencyStorageConflictError(
                "Expected current Academic Period proficiency result revision "
                "does not match stored selection."
            )

        pointer = _result_pointer(target)
        if current == pointer:
            return AcademicPeriodProficiencyResultSelectionResult(
                "existing",
                target,
            )

        _atomic_write_pointer(
            root,
            academic_period_proficiency_result_current_path(
                root,
                class_id,
                school_year,
                period_id,
                student_id,
                standard_id,
            ),
            _canonical_json_bytes(pointer),
        )
        verified = _load_result_pointer(
            root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
            missing_ok=False,
        )
        if verified != pointer:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Published Academic Period proficiency result selection could "
                "not be verified."
            )
        disposition: AcademicPeriodProficiencyResultSelectDisposition = (
            "created" if current is None else "updated"
        )
        return AcademicPeriodProficiencyResultSelectionResult(
            disposition,
            target,
        )
    finally:
        _remove_lock(lock)


def _validate_result_dependencies_for_write(
    root: Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
) -> None:
    period = snapshot.target_period.period
    metadata_path = class_metadata_path(root, snapshot.class_id)
    try:
        metadata = load_class_metadata(metadata_path)
    except ClassMetadataError as error:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact Core class metadata is unavailable for result write."
        ) from error
    if (
        metadata.class_id != snapshot.class_id
        or metadata.school_year != period.school_year
    ):
        raise AcademicPeriodProficiencyResultDependencyError(
            "Core class metadata does not match the result class/school-year scope."
        )

    try:
        calendar = load_academic_period_calendar_revision(
            root,
            period.school_year,
            snapshot.target_period.calendar_revision,
        )
        get_academic_period(calendar, period.period_id)
    except (
        AcademicPeriodCalendarStorageError,
        AcademicPeriodLookupError,
    ) as error:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact Core Academic Period Calendar/target period is unavailable."
        ) from error

    policy_ref = snapshot.policy_reference
    try:
        policy = load_academic_period_proficiency_policy_revision(
            root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact #35 aggregation-policy revision is unavailable."
        ) from error
    if policy.policy_sha256 != policy_ref.policy_sha256:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact #35 aggregation-policy digest does not match result provenance."
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
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact proficiency-scale revision is unavailable."
        ) from error
    if scale.scale_sha256 != scale_ref.scale_sha256:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact proficiency-scale digest does not match result provenance."
        )

    for entry in snapshot.inputs.entries:
        _validate_result_entry_dependencies(root, snapshot, entry)


def _validate_result_entry_dependencies(
    root: Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    entry: AcademicPeriodProficiencyAggregationInputEntry,
) -> None:
    # The input model has already type-validated each entry; keeping this helper
    # structural avoids reopening #35 calculation decisions.
    grade_item = entry.grade_item
    try:
        stored_grade_item = load_grade_item_revision(
            root,
            grade_item.class_id,
            grade_item.grade_item_id,
            grade_item.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact Grade Item revision is unavailable for result write."
        ) from error
    if (
        stored_grade_item.revision_sha256
        != grade_item.grade_item_revision_sha256
    ):
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact Grade Item revision digest does not match result inputs."
        )

    for membership in entry.memberships:
        try:
            stored_membership = load_grade_item_membership_revision(
                root,
                snapshot.class_id,
                membership.grade_item_id,
                membership.work_reference.work,
                membership.membership_revision,
            )
        except GradeItemMembershipStorageError as error:
            raise AcademicPeriodProficiencyResultDependencyError(
                "Exact Grade Item membership revision is unavailable."
            ) from error
        decision = stored_membership.decision
        if stored_membership.decision_sha256 != membership.membership_sha256:
            raise AcademicPeriodProficiencyResultDependencyError(
                "Exact Grade Item membership digest does not match result inputs."
            )
        assignment = decision.academic_period
        if (
            decision.decision != "included"
            or assignment is None
            or decision.grade_item_revision != membership.grade_item_revision
            or decision.grade_item_revision_sha256
            != membership.grade_item_revision_sha256
            or decision.work_reference != membership.work_reference
            or assignment.period != membership.academic_period.period
            or assignment.calendar_revision
            != membership.academic_period.calendar_revision
        ):
            raise AcademicPeriodProficiencyResultDependencyError(
                "Exact Grade Item membership does not match result inputs."
            )

    reference = entry.result_reference
    if reference is None:
        return
    try:
        stored_result = load_standard_proficiency_result_revision(
            root,
            reference.class_id,
            reference.grade_item_id,
            reference.student_id,
            reference.standard_id,
            reference.result_revision,
        )
    except StandardProficiencyStorageError as error:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact #34 standards-proficiency result revision is unavailable."
        ) from error
    if stored_result.result_sha256 != reference.result_sha256:
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact #34 result digest does not match result inputs."
        )
    child = stored_result.snapshot
    if (
        child.inputs.grade_item != entry.grade_item
        or child.student_id != snapshot.student_id
        or child.standard_id != snapshot.standard_id
        or child.target_scale != snapshot.target_scale
        or child.algorithm_version != entry.result_algorithm_version
        or child.calculation_fingerprint
        != entry.result_calculation_fingerprint
        or child.outcome.status != entry.result_status
        or child.outcome.proficiency_level_id != entry.proficiency_level_id
        or child.outcome.insufficiency_reasons
        != entry.result_insufficiency_reasons
    ):
        raise AcademicPeriodProficiencyResultDependencyError(
            "Exact #34 result does not match normalized #35 inputs."
        )


def _write_result_revision_pair(
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
        raise AcademicPeriodProficiencyStorageConflictError(
            "Immutable Academic Period proficiency result revision identity "
            "already exists."
        ) from error
    except OSError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise AcademicPeriodProficiencyStorageWriteError(
            "Could not persist immutable Academic Period proficiency result "
            "revision."
        ) from error


def _validate_result_ancestor_shape(
    root: Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
) -> None:
    results = academic_period_proficiency_results_directory(root, class_id)
    if not results.exists():
        return
    _validate_existing_directory_chain(root, results)

    school_years = _require_only_named_directory(
        results,
        "school_years",
        "Academic Period proficiency result root",
    )
    if school_years is None:
        return
    _require_real_directory(school_years, "result school-year collection")
    _require_school_year_directory_collection(
        school_years,
        "result school-year collection",
    )

    school_year_path = school_years / school_year
    if not school_year_path.exists():
        return
    _require_real_directory(school_year_path, "result school-year scope")
    periods = _require_only_named_directory(
        school_year_path,
        "periods",
        "result school-year scope",
    )
    if periods is None:
        return
    _require_real_directory(periods, "result period collection")
    _require_identifier_directory_collection(
        periods,
        "period_id",
        "result period collection",
    )

    period_path = periods / period_id
    if not period_path.exists():
        return
    _require_real_directory(period_path, "result period scope")
    students = _require_only_named_directory(
        period_path,
        "students",
        "result period scope",
    )
    if students is None:
        return
    _require_real_directory(students, "result student collection")
    _require_identifier_directory_collection(
        students,
        "student_id",
        "result student collection",
    )

    student_path = students / student_id
    if not student_path.exists():
        return
    _require_real_directory(student_path, "result student scope")
    standards = _require_only_named_directory(
        student_path,
        "standards",
        "result student scope",
    )
    if standards is None:
        return
    _require_real_directory(standards, "result standards collection")
    try:
        entries = tuple(standards.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect Academic Period proficiency result families."
        ) from error
    for entry in entries:
        if (
            _SHA256.fullmatch(entry.name) is None
            or entry.is_symlink()
            or not entry.is_dir()
        ):
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency standards collection contains an "
                "unsafe or unexpected entry."
            )


def _validate_result_family_directory(
    family: Path,
    standard_id: str,
) -> None:
    if not family.exists():
        return
    _require_real_directory(family, "Academic Period proficiency result family")
    if family.name != academic_period_proficiency_standard_key(standard_id):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result-family key does not match "
            "standard identity."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(family.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect Academic Period proficiency result family."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency result family contains an "
                "unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Academic Period proficiency result revisions entry must be a "
                    "real directory."
                )
            _validate_result_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency result pointer/lock entry must be "
                "a regular file."
            )


def _result_revision_numbers(family: Path) -> tuple[int, ...]:
    revisions_dir = family / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_result_revision_directory_shape(revisions_dir)
    json_numbers, digest_numbers = _result_revision_number_sets(revisions_dir)
    if json_numbers != digest_numbers:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result JSON and digest sidecars are "
            "incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result history must be contiguous from 1."
        )
    return revisions


def _validate_result_revision_directory_shape(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result revisions entry must be a real "
            "directory."
        )
    json_numbers, digest_numbers = _result_revision_number_sets(path)
    if json_numbers != digest_numbers:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result JSON/digest pairs are incomplete."
        )


def _result_revision_number_sets(path: Path) -> tuple[set[int], set[int]]:
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect immutable Academic Period proficiency result "
            "revision directory."
        ) from error
    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Immutable Academic Period proficiency result revision directory "
                "contains an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Immutable Academic Period proficiency result revision directory "
                "contains an unexpected file."
            )
    return json_numbers, digest_numbers


def _read_result_revision_pair(
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
            "Immutable Academic Period proficiency result revision does not exist."
        ),
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_DIGEST_BYTES,
        missing_message=(
            "Immutable Academic Period proficiency result digest does not exist."
        ),
    )
    expected = _parse_result_digest_sidecar(digest_bytes)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Immutable Academic Period proficiency result revision digest does not "
            "match exact JSON bytes."
        )
    return content, expected


def _parse_result_digest_sidecar(content: bytes) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency result digest sidecar must use one "
            "canonical LF."
        )
    return _sha256(text[:-1], "result digest")


def _require_real_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise AcademicPeriodProficiencyStorageIntegrityError(
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
        raise AcademicPeriodProficiencyStorageReadError(
            f"Could not inspect {label}."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                f"{label} contains an unexpected entry."
            )
        _identifier(entry.name, field_name)


def _require_school_year_directory_collection(parent: Path, label: str) -> None:
    try:
        entries = tuple(parent.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            f"Could not inspect {label}."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                f"{label} contains an unexpected entry."
            )
        _period_ref(entry.name, "period_placeholder")


def _require_only_named_directory(
    parent: Path,
    expected_name: str,
    label: str,
) -> Path | None:
    try:
        entries = tuple(parent.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            f"Could not inspect {label}."
        ) from error
    if not entries:
        return None
    if len(entries) != 1:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            f"{label} contains an unexpected entry."
        )
    entry = entries[0]
    if (
        entry.name != expected_name
        or entry.is_symlink()
        or not entry.is_dir()
    ):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            f"{label} contains an unexpected entry."
        )
    return entry


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
        raise AcademicPeriodProficiencyPolicyDependencyError(
            "Exact target proficiency-scale revision is unavailable."
        ) from error
    if stored.scale_sha256 != reference.scale_sha256:
        raise AcademicPeriodProficiencyPolicyDependencyError(
            "Exact target proficiency-scale digest does not match "
            "Academic Period proficiency policy reference."
        )
    return stored


def _load_existing_policy_for_replay(
    root: Path,
    candidate: AcademicPeriodProficiencyAggregationPolicy,
) -> StoredAcademicPeriodProficiencyAggregationPolicy:
    try:
        return load_academic_period_proficiency_policy_revision(
            root,
            candidate.class_id,
            candidate.policy_id,
            candidate.policy_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Existing Academic Period proficiency policy revision is incomplete "
            "or invalid."
        ) from error


def _result_pointer(
    stored: StoredAcademicPeriodProficiencyResult,
) -> dict[str, object]:
    snapshot = stored.snapshot
    period = snapshot.target_period.period
    return {
        "schema_version": ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION,
        "record_type": ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE,
        "class_id": snapshot.class_id,
        "school_year": period.school_year,
        "period_id": period.period_id,
        "student_id": snapshot.student_id,
        "standard_id": snapshot.standard_id,
        "standard_key": academic_period_proficiency_standard_key(
            snapshot.standard_id
        ),
        "result_revision": snapshot.result_revision,
        "result_sha256": stored.result_sha256,
    }


def _load_result_pointer(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(school_year, period_id)
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    family = academic_period_proficiency_result_family_directory(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
        standard,
    )
    if not family.exists():
        if missing_ok:
            return None
        raise AcademicPeriodProficiencyStorageNotFoundError(
            "Academic Period proficiency result family does not exist."
        )
    _validate_result_ancestor_shape(
        root,
        class_value,
        period.school_year,
        period.period_id,
        student,
    )
    _validate_result_family_directory(family, standard)
    path = family / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise AcademicPeriodProficiencyStorageNotFoundError(
            "Academic Period proficiency result has no explicit current "
            "selection."
        )

    mapping = _read_pointer(root, path, _RESULT_POINTER_KEYS)
    if (
        mapping["schema_version"]
        != ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_SCHEMA_VERSION
        or mapping["record_type"]
        != ACADEMIC_PERIOD_PROFICIENCY_RESULT_CURRENT_RECORD_TYPE
        or mapping["class_id"] != class_value
        or mapping["school_year"] != period.school_year
        or mapping["period_id"] != period.period_id
        or mapping["student_id"] != student
        or mapping["standard_id"] != standard
    ):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency current-result pointer identity is "
            "invalid."
        )
    expected_key = academic_period_proficiency_standard_key(standard)
    if mapping["standard_key"] != expected_key:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency current-result pointer standard key "
            "is invalid."
        )
    _positive_int(mapping["result_revision"], "result_revision")
    _sha256(mapping["result_sha256"], "result_sha256")
    return mapping


def _policy_pointer(
    stored: StoredAcademicPeriodProficiencyAggregationPolicy,
) -> dict[str, object]:
    return {
        "schema_version": (
            ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION
        ),
        "record_type": ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE,
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
    path = academic_period_proficiency_policy_current_path(
        root,
        class_value,
        policy_value,
    )
    if not path.exists():
        if missing_ok:
            return None
        raise AcademicPeriodProficiencyStorageNotFoundError(
            "Academic Period proficiency policy current pointer does not exist."
        )

    mapping = _read_pointer(
        root,
        path,
        _POINTER_KEYS,
    )
    if (
        mapping["schema_version"]
        != ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_SCHEMA_VERSION
        or mapping["record_type"]
        != ACADEMIC_PERIOD_PROFICIENCY_POLICY_CURRENT_RECORD_TYPE
        or mapping["class_id"] != class_value
        or mapping["policy_id"] != policy_value
    ):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy current pointer identity is invalid."
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
        DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POINTER_BYTES,
        missing_message=(
            "Academic Period proficiency policy current pointer does not exist."
        ),
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy pointer must be UTF-8."
        ) from error

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except AcademicPeriodProficiencyStorageIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy pointer JSON is invalid."
        ) from error

    if not isinstance(decoded, dict) or frozenset(decoded) != keys:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy pointer does not use its exact schema."
        )
    mapping = cast(dict[str, object], decoded)
    if _canonical_json_bytes(mapping) != content:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy pointer is not canonically encoded."
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
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect immutable Academic Period proficiency policy history."
        ) from error

    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency policy history contains an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency policy history contains an "
                "unexpected file."
            )

    if json_numbers != digest_numbers:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy JSON and digest sidecars are "
            "incomplete."
        )
    revisions = tuple(sorted(json_numbers))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy history must be contiguous from 1."
        )
    if not revisions:
        return ()

    previous: _HistoryT | None = None
    for revision in revisions:
        current = loader(revision)
        if previous is not None:
            try:
                transition(previous, current)
            except AcademicPeriodProficiencyValidationError as error:
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Persisted Academic Period proficiency policy transition is "
                    "invalid: "
                    f"{error}"
                ) from error
        previous = current
    return revisions


def _validate_policy_directory(path: Path) -> None:
    if not path.exists():
        return
    if path.is_symlink() or not path.is_dir():
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy canonical root is unsafe or not "
            "a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect Academic Period proficiency policy canonical root."
        ) from error

    for entry in entries:
        if entry.name not in allowed:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency policy canonical root contains an "
                "unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Academic Period proficiency policy revisions entry must be a real "
                    "directory."
                )
            _validate_revision_directory_shape(entry)
        elif entry.is_symlink() or not entry.is_file():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Academic Period proficiency policy pointer/lock entry must be a "
                "regular "
                "file."
            )


def _validate_revision_directory_shape(path: Path) -> None:
    try:
        entries = tuple(path.iterdir())
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect immutable Academic Period proficiency policy revision "
            "directory."
        ) from error

    json_numbers: set[int] = set()
    digest_numbers: set[int] = set()
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Immutable Academic Period proficiency policy revision directory "
                "contains "
                "an unsafe entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_numbers.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_numbers.add(int(digest_match.group(1)))
        else:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Immutable Academic Period proficiency policy revision directory "
                "contains "
                "an unexpected file."
            )
    if json_numbers != digest_numbers:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Immutable Academic Period proficiency policy JSON/digest pairs are "
            "incomplete."
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
            "Immutable Academic Period proficiency policy revision does not exist."
        ),
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_DIGEST_BYTES,
        missing_message=(
            "Immutable Academic Period proficiency policy digest does not exist."
        ),
    )
    expected = _parse_digest_sidecar(digest_bytes)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Immutable Academic Period proficiency policy revision digest does not "
            "match "
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
        raise AcademicPeriodProficiencyStorageConflictError(
            "Immutable Academic Period proficiency policy revision identity already "
            "exists."
        ) from error
    except OSError as error:
        if created_digest:
            _remove_file(digest_path)
        if created_json:
            _remove_file(path)
        raise AcademicPeriodProficiencyStorageWriteError(
            "Could not persist immutable Academic Period proficiency policy revision."
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
            raise AcademicPeriodProficiencyStorageWriteError(
                "Temporary Academic Period proficiency policy pointer is unsafe."
            )
        os.replace(temp_path, path)
        temporary = None
        _fsync_directory(path.parent)
    except AcademicPeriodProficiencyStorageError:
        raise
    except OSError as error:
        raise AcademicPeriodProficiencyStorageWriteError(
            "Could not publish Academic Period proficiency policy current pointer "
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
        raise AcademicPeriodProficiencyStorageLockError(
            "Another writer already owns this Academic Period proficiency policy "
            "history."
        )
    try:
        _exclusive_write(path, b"locked\n")
    except FileExistsError as error:
        raise AcademicPeriodProficiencyStorageLockError(
            "Another writer already owns this Academic Period proficiency policy "
            "history."
        ) from error
    except OSError as error:
        raise AcademicPeriodProficiencyStorageWriteError(
            "Could not acquire Academic Period proficiency policy write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise AcademicPeriodProficiencyStorageWriteError(
            "Could not remove Academic Period proficiency policy write lock."
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
        raise AcademicPeriodProficiencyStorageNotFoundError(
            "Workspace root must exist before Academic Period proficiency policy "
            "storage "
            "is used."
        )
    if current.is_symlink() or not current.is_dir():
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )

    for component in relative.parts:
        current = current / component
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise AcademicPeriodProficiencyStorageIntegrityError(
                    "Canonical Academic Period proficiency policy directory chain "
                    "is unsafe."
                )
            continue
        try:
            current.mkdir()
        except OSError as error:
            raise AcademicPeriodProficiencyStorageWriteError(
                "Could not create canonical Academic Period proficiency policy "
                "directory."
            ) from error


def _validate_existing_directory_chain(
    root: Path,
    target: Path,
) -> None:
    _require_containment(root, target)
    relative = target.relative_to(root)
    current = root
    if current.is_symlink() or not current.is_dir():
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Workspace root is unsafe or not a directory."
        )

    for component in relative.parts:
        current = current / component
        if not current.exists():
            raise AcademicPeriodProficiencyStorageNotFoundError(
                "Canonical Academic Period proficiency policy directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise AcademicPeriodProficiencyStorageIntegrityError(
                "Canonical Academic Period proficiency policy directory chain is "
                "unsafe."
            )


def _read_bounded_regular_file(
    path: Path,
    maximum: int,
    *,
    missing_message: str,
) -> bytes:
    if not path.exists():
        raise AcademicPeriodProficiencyStorageNotFoundError(missing_message)
    if path.is_symlink() or not path.is_file():
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Canonical Academic Period proficiency policy file is unsafe or not a "
            "regular "
            "file."
        )
    try:
        size = path.stat().st_size
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not inspect canonical Academic Period proficiency policy file."
        ) from error
    if size > maximum:
        raise AcademicPeriodProficiencyStorageTooLargeError(
            "Canonical Academic Period proficiency policy file exceeds configured byte "
            "limit."
        )
    try:
        with path.open("rb") as handle:
            content = handle.read(maximum + 1)
    except OSError as error:
        raise AcademicPeriodProficiencyStorageReadError(
            "Could not read canonical Academic Period proficiency policy file."
        ) from error
    if len(content) > maximum:
        raise AcademicPeriodProficiencyStorageTooLargeError(
            "Canonical Academic Period proficiency policy file exceeds configured byte "
            "limit."
        )
    return content


def _parse_digest_sidecar(content: bytes) -> str:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1:
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy digest sidecar must use one "
            "canonical LF."
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
        raise AcademicPeriodProficiencyStorageIntegrityError(
            "Academic Period proficiency policy pointer cannot be canonically "
            "serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AcademicPeriodProficiencyStorageIntegrityError(
                f"Duplicate Academic Period proficiency policy pointer key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise AcademicPeriodProficiencyStorageIntegrityError(
        "Non-finite Academic Period proficiency policy pointer value is invalid: "
        f"{value}"
    )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise AcademicPeriodProficiencyStorageNotFoundError(
            "Core class workspace must exist before Academic Period proficiency policy "
            "creation."
        )
    _validate_existing_directory_chain(root, path)


def _check_write_size(
    content: bytes,
    maximum: int,
    label: str,
) -> None:
    if len(content) > maximum:
        raise AcademicPeriodProficiencyStorageWriteError(
            f"Canonical {label} revision exceeds configured byte limit."
        )


def _root(value: str | Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise AcademicPeriodProficiencyStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(value)
    if not root.is_absolute():
        root = root.absolute()
    return root


def _period_ref(school_year: object, period_id: object) -> AcademicPeriodRef:
    if not isinstance(school_year, str) or not isinstance(period_id, str):
        raise AcademicPeriodProficiencyStorageValidationError(
            "school_year and period_id must be strings."
        )
    try:
        return validate_academic_period_ref(
            AcademicPeriodRef(school_year, period_id)
        )
    except AcademicPeriodValidationError as error:
        raise AcademicPeriodProficiencyStorageValidationError(str(error)) from error


def _standard_id(value: object) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodProficiencyStorageValidationError(
            "standard_id must be a string."
        )
    normalized = value.strip()
    if not normalized:
        raise AcademicPeriodProficiencyStorageValidationError(
            "standard_id must not be blank."
        )
    if any(
        ord(character) < 32 or ord(character) == 127
        for character in normalized
    ):
        raise AcademicPeriodProficiencyStorageValidationError(
            "standard_id must not contain control characters."
        )
    return normalized


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodProficiencyStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AcademicPeriodProficiencyStorageValidationError(
            str(error)
        ) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AcademicPeriodProficiencyStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AcademicPeriodProficiencyStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise AcademicPeriodProficiencyStorageValidationError(
            "Academic Period proficiency policy path escapes workspace root."
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
