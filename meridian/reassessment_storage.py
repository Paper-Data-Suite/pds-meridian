"""Canonical persistence and current-use resolution for reassessment state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    validate_module_work_ref,
)

from meridian.attempt_selection import AttemptObservationReference
from meridian.attempt_selection_storage import (
    AttemptSelectionResolution,
    AttemptSelectionStorageError,
    attempt_selection_directory,
    load_attempt_selection_decision_revision,
    resolve_current_attempt_selection,
)
from meridian.reassessment import (
    ReassessmentCombination,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentSerializationError,
    ReassessmentValidationError,
    ReplacementRelationship,
    reassessment_decision_from_json_bytes,
    reassessment_decision_to_json_bytes,
    reassessment_policy_from_json_bytes,
    reassessment_policy_to_json_bytes,
    reassessment_subject_key,
    validate_reassessment_decision,
    validate_reassessment_decision_transition,
    validate_reassessment_policy,
    validate_reassessment_policy_transition,
)

if TYPE_CHECKING:
    from meridian.projection_cache import AuthorizedProjectionSnapshot

REASSESSMENT_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
REASSESSMENT_POLICY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_reassessment_policy_current"
)
REASSESSMENT_DECISION_CURRENT_SCHEMA_VERSION: Final[str] = "1"
REASSESSMENT_DECISION_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_reassessment_decision_current"
)
DEFAULT_MAXIMUM_REASSESSMENT_POLICY_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_REASSESSMENT_DECISION_BYTES: Final[int] = 256 * 1024
DEFAULT_MAXIMUM_REASSESSMENT_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_REASSESSMENT_DIGEST_BYTES: Final[int] = 128

ReassessmentWriteDisposition: TypeAlias = Literal["created", "existing"]
ReassessmentSelectDisposition: TypeAlias = Literal["created", "updated", "existing"]
ReassessmentResolutionStatus: TypeAlias = Literal[
    "not_applicable",
    "attempt_selection_unresolved",
    "selected_none",
    "single_selected",
    "no_decision",
    "resolved",
    "attempt_selection_stale",
    "policy_stale",
]

_HistoryT = TypeVar("_HistoryT")

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json\.sha256$")
_POLICY_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "module_id",
        "work_id",
        "policy_id",
        "policy_revision",
        "policy_sha256",
    }
)
_DECISION_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "module_id",
        "work_id",
        "subject_key",
        "decision_revision",
        "decision_sha256",
    }
)


class ReassessmentStorageError(RuntimeError):
    """Base error for reassessment storage and resolution."""

    code: str = "reassessment.storage_error"


class ReassessmentStorageValidationError(ReassessmentStorageError, ValueError):
    code = "reassessment.storage_invalid"


class ReassessmentStorageNotFoundError(ReassessmentStorageError):
    code = "reassessment.not_found"


class ReassessmentStorageReadError(ReassessmentStorageError):
    code = "reassessment.read_failed"


class ReassessmentStorageWriteError(ReassessmentStorageError):
    code = "reassessment.write_failed"


class ReassessmentStorageConflictError(ReassessmentStorageError):
    code = "reassessment.conflict"


class ReassessmentStorageLockError(ReassessmentStorageConflictError):
    code = "reassessment.locked"


class ReassessmentStorageIntegrityError(ReassessmentStorageError):
    code = "reassessment.integrity"


class ReassessmentStorageTooLargeError(ReassessmentStorageReadError):
    code = "reassessment.too_large"


class ReassessmentDependencyError(ReassessmentStorageError):
    code = "reassessment.dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredReassessmentPolicy:
    policy: ReassessmentPolicy
    policy_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, ReassessmentPolicy):
            raise ReassessmentStorageValidationError("policy has an invalid type.")
        digest = _sha256(self.policy_sha256, "policy_sha256")
        if (
            type(self.content) is not bytes
            or hashlib.sha256(self.content).hexdigest() != digest
        ):
            raise ReassessmentStorageValidationError(
                "policy_sha256 must match exact immutable content."
            )
        try:
            decoded = reassessment_policy_from_json_bytes(self.content)
        except (ReassessmentSerializationError, ReassessmentValidationError) as error:
            raise ReassessmentStorageValidationError(
                "content is not a canonical reassessment policy."
            ) from error
        if decoded != self.policy:
            raise ReassessmentStorageValidationError(
                "policy content identity mismatch."
            )
        expected = reassessment_policy_revision_relative_path(
            self.policy.class_id,
            self.policy.grade_item_id,
            self.policy.work,
            self.policy.policy_id,
            self.policy.policy_revision,
        )
        if self.relative_path != expected:
            raise ReassessmentStorageValidationError(
                "relative_path is not the canonical reassessment policy location."
            )
        if self.path.name != f"{self.policy.policy_revision}.json":
            raise ReassessmentStorageValidationError(
                "policy path filename does not match policy revision."
            )
        object.__setattr__(self, "policy_sha256", digest)


@dataclass(frozen=True, slots=True)
class StoredReassessmentDecision:
    decision: ReassessmentDecision
    decision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ReassessmentDecision):
            raise ReassessmentStorageValidationError("decision has an invalid type.")
        digest = _sha256(self.decision_sha256, "decision_sha256")
        if (
            type(self.content) is not bytes
            or hashlib.sha256(self.content).hexdigest() != digest
        ):
            raise ReassessmentStorageValidationError(
                "decision_sha256 must match exact immutable content."
            )
        try:
            decoded = reassessment_decision_from_json_bytes(self.content)
        except (ReassessmentSerializationError, ReassessmentValidationError) as error:
            raise ReassessmentStorageValidationError(
                "content is not a canonical reassessment decision."
            ) from error
        if decoded != self.decision:
            raise ReassessmentStorageValidationError(
                "decision content identity mismatch."
            )
        expected = reassessment_decision_revision_relative_path(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.work,
            self.decision.student_id,
            self.decision.decision_revision,
        )
        if self.relative_path != expected:
            raise ReassessmentStorageValidationError(
                "relative_path is not the canonical reassessment decision location."
            )
        if self.path.name != f"{self.decision.decision_revision}.json":
            raise ReassessmentStorageValidationError(
                "decision path filename does not match decision revision."
            )
        object.__setattr__(self, "decision_sha256", digest)


@dataclass(frozen=True, slots=True)
class ReassessmentPolicyWriteResult:
    disposition: ReassessmentWriteDisposition
    stored: StoredReassessmentPolicy


@dataclass(frozen=True, slots=True)
class ReassessmentDecisionWriteResult:
    disposition: ReassessmentWriteDisposition
    stored: StoredReassessmentDecision


@dataclass(frozen=True, slots=True)
class ReassessmentPolicySelectionResult:
    disposition: ReassessmentSelectDisposition
    stored: StoredReassessmentPolicy


@dataclass(frozen=True, slots=True)
class ReassessmentDecisionSelectionResult:
    disposition: ReassessmentSelectDisposition
    stored: StoredReassessmentDecision
    attempt_selection: AttemptSelectionResolution


@dataclass(frozen=True, slots=True)
class ReassessmentResolution:
    status: ReassessmentResolutionStatus
    attempt_selection: AttemptSelectionResolution
    selected: StoredReassessmentDecision | None
    current_policy: StoredReassessmentPolicy | None
    contributing_attempts: tuple[AttemptObservationReference, ...]
    replacement_relationships: tuple[ReplacementRelationship, ...]
    combinations: tuple[ReassessmentCombination, ...]
    recency_order: tuple[AttemptObservationReference, ...]
    operative_reassessment: bool

    def __post_init__(self) -> None:
        if self.status not in {
            "not_applicable",
            "attempt_selection_unresolved",
            "selected_none",
            "single_selected",
            "no_decision",
            "resolved",
            "attempt_selection_stale",
            "policy_stale",
        }:
            raise ReassessmentStorageValidationError(
                "reassessment resolution status is invalid."
            )
        if not isinstance(self.attempt_selection, AttemptSelectionResolution):
            raise ReassessmentStorageValidationError(
                "attempt_selection must be an AttemptSelectionResolution."
            )
        if not isinstance(self.operative_reassessment, bool):
            raise ReassessmentStorageValidationError(
                "operative_reassessment must be boolean."
            )


def reassessment_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return attempt_selection_directory(
        _root(workspace_root),
        _identifier(class_id, "class_id"),
        _identifier(grade_item_id, "grade_item_id"),
        _work(work),
    ) / "reassessment"


def reassessment_policies_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        reassessment_directory(workspace_root, class_id, grade_item_id, work)
        / "policies"
    )


def reassessment_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> Path:
    return reassessment_policies_directory(
        workspace_root, class_id, grade_item_id, work
    ) / _identifier(policy_id, "policy_id")


def reassessment_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> Path:
    return reassessment_policy_directory(
        workspace_root, class_id, grade_item_id, work, policy_id
    ) / "revisions" / f"{_positive_int(policy_revision, 'policy_revision')}.json"


def reassessment_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> Path:
    return reassessment_policy_directory(
        workspace_root, class_id, grade_item_id, work, policy_id
    ) / "current.json"


def reassessment_students_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        reassessment_directory(workspace_root, class_id, grade_item_id, work)
        / "students"
    )


def reassessment_subject_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> Path:
    validated_work = _work(work)
    return reassessment_students_directory(
        workspace_root, class_id, grade_item_id, validated_work
    ) / reassessment_subject_key(
        _identifier(class_id, "class_id"),
        _identifier(grade_item_id, "grade_item_id"),
        validated_work,
        _identifier(student_id, "student_id"),
    )


def reassessment_decision_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> Path:
    return reassessment_subject_directory(
        workspace_root, class_id, grade_item_id, work, student_id
    ) / "revisions" / f"{_positive_int(decision_revision, 'decision_revision')}.json"


def reassessment_decision_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> Path:
    return reassessment_subject_directory(
        workspace_root, class_id, grade_item_id, work, student_id
    ) / "current.json"


def reassessment_policy_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> str:
    path = reassessment_policy_revision_path(
        Path("."), class_id, grade_item_id, work, policy_id, policy_revision
    )
    return path.as_posix().removeprefix("./")


def reassessment_decision_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> str:
    path = reassessment_decision_revision_path(
        Path("."), class_id, grade_item_id, work, student_id, decision_revision
    )
    return path.as_posix().removeprefix("./")


def write_reassessment_policy_revision(
    workspace_root: str | Path,
    policy: ReassessmentPolicy,
) -> ReassessmentPolicyWriteResult:
    candidate = validate_reassessment_policy(policy)
    root = _root(workspace_root)
    _require_attempt_selection_root(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    _validate_reassessment_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    target = reassessment_policy_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.policy_id,
        candidate.policy_revision,
    )
    digest_path = Path(str(target) + ".sha256")
    content = reassessment_policy_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_REASSESSMENT_POLICY_BYTES:
        raise ReassessmentStorageWriteError("Reassessment policy exceeds byte limit.")
    digest = hashlib.sha256(content).hexdigest()
    if target.exists() or digest_path.exists():
        stored = load_reassessment_policy_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy_id,
            candidate.policy_revision,
        )
        if stored.content != content or stored.policy_sha256 != digest:
            raise ReassessmentStorageConflictError(
                "Reassessment policy revision already exists with different content."
            )
        return ReassessmentPolicyWriteResult("existing", stored)
    relation = target.parent.parent
    _ensure_directory_chain(root, target.parent)
    _validate_reassessment_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        if target.exists() or digest_path.exists():
            stored = load_reassessment_policy_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.policy_id,
                candidate.policy_revision,
            )
            if stored.content != content or stored.policy_sha256 != digest:
                raise ReassessmentStorageConflictError(
                    "Reassessment policy revision already exists with "
                    "different content."
                )
            return ReassessmentPolicyWriteResult("existing", stored)
        revisions = list_reassessment_policy_revisions(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy_id,
        )
        if revisions:
            if candidate.policy_revision != revisions[-1] + 1:
                raise ReassessmentStorageConflictError(
                    "Policy revision must be exactly one greater than history."
                )
            previous = load_reassessment_policy_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.policy_id,
                revisions[-1],
            ).policy
            try:
                validate_reassessment_policy_transition(previous, candidate)
            except ReassessmentValidationError as error:
                raise ReassessmentStorageConflictError(str(error)) from error
        elif candidate.policy_revision != 1:
            raise ReassessmentStorageConflictError(
                "Initial reassessment policy revision must be 1."
            )
        _write_revision_pair(target, digest_path, content, digest)
        return ReassessmentPolicyWriteResult(
            "created",
            load_reassessment_policy_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.policy_id,
                candidate.policy_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_reassessment_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> StoredReassessmentPolicy:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    _validate_reassessment_collections(root, class_value, item, validated_work)
    path = reassessment_policy_revision_path(
        root, class_value, item, validated_work, policy_value, revision
    )
    content, digest = _read_revision_pair(
        root, path, DEFAULT_MAXIMUM_REASSESSMENT_POLICY_BYTES
    )
    try:
        policy = reassessment_policy_from_json_bytes(content)
    except (ReassessmentSerializationError, ReassessmentValidationError) as error:
        raise ReassessmentStorageIntegrityError(
            f"Reassessment policy is invalid or noncanonical: {error}"
        ) from error
    if (
        policy.class_id != class_value
        or policy.grade_item_id != item
        or policy.work != validated_work
        or policy.policy_id != policy_value
        or policy.policy_revision != revision
    ):
        raise ReassessmentStorageIntegrityError(
            "Persisted reassessment policy identity does not match canonical path."
        )
    return StoredReassessmentPolicy(
        policy=policy,
        policy_sha256=digest,
        path=path,
        relative_path=reassessment_policy_revision_relative_path(
            class_value, item, validated_work, policy_value, revision
        ),
        content=content,
    )


def list_reassessment_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    _validate_reassessment_collections(root, class_id, grade_item_id, work)
    relation = reassessment_policy_directory(
        root, class_id, grade_item_id, work, policy_id
    )
    return _list_history_revisions(
        root,
        relation,
        lambda number: load_reassessment_policy_revision(
            root, class_id, grade_item_id, work, policy_id, number
        ).policy,
        validate_reassessment_policy_transition,
    )


def get_current_reassessment_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> int | None:
    pointer = _load_policy_pointer(
        workspace_root, class_id, grade_item_id, work, policy_id, missing_ok=True
    )
    return None if pointer is None else cast(int, pointer["policy_revision"])


def load_current_reassessment_policy(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> StoredReassessmentPolicy | None:
    pointer = _load_policy_pointer(
        workspace_root, class_id, grade_item_id, work, policy_id, missing_ok=True
    )
    if pointer is None:
        return None
    stored = load_reassessment_policy_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
        cast(int, pointer["policy_revision"]),
    )
    if stored.policy_sha256 != pointer["policy_sha256"]:
        raise ReassessmentStorageIntegrityError(
            "Policy current pointer digest does not match selected revision."
        )
    return stored


def select_reassessment_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_policy_revision: int | None,
) -> ReassessmentPolicySelectionResult:
    root = _root(workspace_root)
    target = load_reassessment_policy_revision(
        root, class_id, grade_item_id, work, policy_id, policy_revision
    )
    relation = reassessment_policy_directory(
        root, class_id, grade_item_id, work, policy_id
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        current = _load_policy_pointer(
            root, class_id, grade_item_id, work, policy_id, missing_ok=True
        )
        current_revision = (
            None if current is None else cast(int, current["policy_revision"])
        )
        if current_revision != expected_current_policy_revision:
            raise ReassessmentStorageConflictError(
                "Expected current policy revision does not match stored selection."
            )
        pointer = _policy_pointer(target)
        if current == pointer:
            return ReassessmentPolicySelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            reassessment_policy_current_path(
                root, class_id, grade_item_id, work, policy_id
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: ReassessmentSelectDisposition = (
            "created" if current is None else "updated"
        )
        return ReassessmentPolicySelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def write_reassessment_decision_revision(
    workspace_root: str | Path,
    decision: ReassessmentDecision,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> ReassessmentDecisionWriteResult:
    candidate = validate_reassessment_decision(decision)
    root = _root(workspace_root)
    _validate_reassessment_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    target = reassessment_decision_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.student_id,
        candidate.decision_revision,
    )
    digest_path = Path(str(target) + ".sha256")
    content = reassessment_decision_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_REASSESSMENT_DECISION_BYTES:
        raise ReassessmentStorageWriteError(
            "Reassessment decision exceeds byte limit."
        )
    digest = hashlib.sha256(content).hexdigest()

    # Exact immutable replay remains valid after later dependency drift.
    if target.exists() or digest_path.exists():
        stored = load_reassessment_decision_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
            candidate.decision_revision,
        )
        if stored.content != content or stored.decision_sha256 != digest:
            raise ReassessmentStorageConflictError(
                "Reassessment decision revision already exists with different content."
            )
        return ReassessmentDecisionWriteResult("existing", stored)

    _validate_decision_dependencies(
        root, candidate, authorized_snapshot, require_current_policy=True
    )
    relation = target.parent.parent
    _ensure_directory_chain(root, target.parent)
    _validate_reassessment_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        if target.exists() or digest_path.exists():
            stored = load_reassessment_decision_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                candidate.decision_revision,
            )
            if stored.content != content or stored.decision_sha256 != digest:
                raise ReassessmentStorageConflictError(
                    "Reassessment decision revision already exists with "
                    "different content."
                )
            return ReassessmentDecisionWriteResult("existing", stored)
        _validate_decision_dependencies(
            root, candidate, authorized_snapshot, require_current_policy=True
        )
        revisions = list_reassessment_decision_revisions(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
        )
        if revisions:
            if candidate.decision_revision != revisions[-1] + 1:
                raise ReassessmentStorageConflictError(
                    "Decision revision must be exactly one greater than history."
                )
            previous = load_reassessment_decision_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                revisions[-1],
            ).decision
            try:
                validate_reassessment_decision_transition(previous, candidate)
            except ReassessmentValidationError as error:
                raise ReassessmentStorageConflictError(str(error)) from error
        elif candidate.decision_revision != 1:
            raise ReassessmentStorageConflictError(
                "Initial reassessment decision revision must be 1."
            )
        _write_revision_pair(target, digest_path, content, digest)
        return ReassessmentDecisionWriteResult(
            "created",
            load_reassessment_decision_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                candidate.decision_revision,
            ),
        )
    finally:
        _remove_lock(lock)


def load_reassessment_decision_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> StoredReassessmentDecision:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    student = _identifier(student_id, "student_id")
    revision = _positive_int(decision_revision, "decision_revision")
    _validate_reassessment_collections(root, class_value, item, validated_work)
    path = reassessment_decision_revision_path(
        root, class_value, item, validated_work, student, revision
    )
    content, digest = _read_revision_pair(
        root, path, DEFAULT_MAXIMUM_REASSESSMENT_DECISION_BYTES
    )
    try:
        decision = reassessment_decision_from_json_bytes(content)
    except (ReassessmentSerializationError, ReassessmentValidationError) as error:
        raise ReassessmentStorageIntegrityError(
            f"Reassessment decision is invalid or noncanonical: {error}"
        ) from error
    if (
        decision.class_id != class_value
        or decision.grade_item_id != item
        or decision.work != validated_work
        or decision.student_id != student
        or decision.decision_revision != revision
    ):
        raise ReassessmentStorageIntegrityError(
            "Persisted reassessment decision identity does not match canonical path."
        )
    return StoredReassessmentDecision(
        decision=decision,
        decision_sha256=digest,
        path=path,
        relative_path=reassessment_decision_revision_relative_path(
            class_value, item, validated_work, student, revision
        ),
        content=content,
    )


def list_reassessment_decision_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    _validate_reassessment_collections(root, class_id, grade_item_id, work)
    relation = reassessment_subject_directory(
        root, class_id, grade_item_id, work, student_id
    )
    return _list_history_revisions(
        root,
        relation,
        lambda number: load_reassessment_decision_revision(
            root, class_id, grade_item_id, work, student_id, number
        ).decision,
        validate_reassessment_decision_transition,
    )


def get_current_reassessment_decision_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> int | None:
    pointer = _load_decision_pointer(
        workspace_root, class_id, grade_item_id, work, student_id, missing_ok=True
    )
    return None if pointer is None else cast(int, pointer["decision_revision"])


def load_current_reassessment_decision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> StoredReassessmentDecision | None:
    pointer = _load_decision_pointer(
        workspace_root, class_id, grade_item_id, work, student_id, missing_ok=True
    )
    if pointer is None:
        return None
    stored = load_reassessment_decision_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
        cast(int, pointer["decision_revision"]),
    )
    if stored.decision_sha256 != pointer["decision_sha256"]:
        raise ReassessmentStorageIntegrityError(
            "Decision current pointer digest does not match selected revision."
        )
    return stored


def select_reassessment_decision_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    expected_current_decision_revision: int | None,
) -> ReassessmentDecisionSelectionResult:
    root = _root(workspace_root)
    target = load_reassessment_decision_revision(
        root, class_id, grade_item_id, work, student_id, decision_revision
    )
    relation = reassessment_subject_directory(
        root, class_id, grade_item_id, work, student_id
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        attempt_selection = _validate_decision_dependencies(
            root, target.decision, authorized_snapshot, require_current_policy=True
        )
        current = _load_decision_pointer(
            root, class_id, grade_item_id, work, student_id, missing_ok=True
        )
        current_revision = (
            None if current is None else cast(int, current["decision_revision"])
        )
        if current_revision != expected_current_decision_revision:
            raise ReassessmentStorageConflictError(
                "Expected current decision revision does not match stored selection."
            )
        pointer = _decision_pointer(target)
        if current == pointer:
            return ReassessmentDecisionSelectionResult(
                "existing", target, attempt_selection
            )
        _atomic_write_pointer(
            root,
            reassessment_decision_current_path(
                root, class_id, grade_item_id, work, student_id
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: ReassessmentSelectDisposition = (
            "created" if current is None else "updated"
        )
        return ReassessmentDecisionSelectionResult(
            disposition, target, attempt_selection
        )
    finally:
        _remove_lock(lock)


def resolve_current_reassessment(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> ReassessmentResolution:
    root = _root(workspace_root)
    selected = load_current_reassessment_decision(
        root, class_id, grade_item_id, work, student_id
    )
    try:
        upstream = resolve_current_attempt_selection(
            root,
            class_id,
            grade_item_id,
            work,
            student_id,
            authorized_snapshot=authorized_snapshot,
        )
    except AttemptSelectionStorageError as error:
        raise ReassessmentDependencyError(
            f"Attempt-selection resolution failed: {error}"
        ) from error

    if upstream.status == "not_applicable":
        return _resolution("not_applicable", upstream, selected)
    if upstream.status == "no_decision":
        status: ReassessmentResolutionStatus = (
            "attempt_selection_unresolved"
            if selected is None
            else "attempt_selection_stale"
        )
        return _resolution(status, upstream, selected)
    if (
        upstream.status not in {"selected", "selected_none"}
        or not upstream.operative_selection
    ):
        return _resolution("attempt_selection_stale", upstream, selected)
    upstream_stored = upstream.selected
    if selected is not None:
        decision = selected.decision
        if (
            upstream_stored is None
            or upstream_stored.decision.decision_revision
            != decision.attempt_selection.decision_revision
            or upstream_stored.decision_sha256
            != decision.attempt_selection.decision_sha256
        ):
            return _resolution("attempt_selection_stale", upstream, selected)
    if upstream.status == "selected_none":
        return _resolution("selected_none", upstream, selected)
    upstream_selected = _upstream_selected_attempts(upstream)
    if len(upstream_selected) == 1:
        return ReassessmentResolution(
            status="single_selected",
            attempt_selection=upstream,
            selected=selected,
            current_policy=None,
            contributing_attempts=upstream_selected,
            replacement_relationships=(),
            combinations=(),
            recency_order=(),
            operative_reassessment=True,
        )
    if selected is None:
        return _resolution("no_decision", upstream, None)
    decision = selected.decision
    try:
        current_policy = load_current_reassessment_policy(
            root, class_id, grade_item_id, work, decision.policy.policy_id
        )
    except ReassessmentStorageError:
        current_policy = None
    if (
        current_policy is None
        or current_policy.policy.policy_revision != decision.policy.policy_revision
        or current_policy.policy_sha256 != decision.policy.policy_revision_sha256
    ):
        return ReassessmentResolution(
            status="policy_stale",
            attempt_selection=upstream,
            selected=selected,
            current_policy=current_policy,
            contributing_attempts=(),
            replacement_relationships=(),
            combinations=(),
            recency_order=(),
            operative_reassessment=False,
        )
    try:
        _validate_relationships_against_selected(decision, upstream_selected)
    except ReassessmentDependencyError:
        return ReassessmentResolution(
            status="attempt_selection_stale",
            attempt_selection=upstream,
            selected=selected,
            current_policy=current_policy,
            contributing_attempts=(),
            replacement_relationships=(),
            combinations=(),
            recency_order=(),
            operative_reassessment=False,
        )
    return ReassessmentResolution(
        status="resolved",
        attempt_selection=upstream,
        selected=selected,
        current_policy=current_policy,
        contributing_attempts=decision.contributing_attempts,
        replacement_relationships=decision.replacement_relationships,
        combinations=decision.combinations,
        recency_order=decision.recency_order,
        operative_reassessment=True,
    )


def _validate_decision_dependencies(
    root: Path,
    decision: ReassessmentDecision,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    require_current_policy: bool,
) -> AttemptSelectionResolution:
    candidate = validate_reassessment_decision(decision)
    try:
        exact_upstream = load_attempt_selection_decision_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
            candidate.attempt_selection.decision_revision,
        )
    except AttemptSelectionStorageError as error:
        raise ReassessmentDependencyError(
            f"Exact attempt-selection decision could not be loaded: {error}"
        ) from error
    if exact_upstream.decision_sha256 != candidate.attempt_selection.decision_sha256:
        raise ReassessmentDependencyError(
            "Attempt-selection decision digest does not match reassessment reference."
        )
    if len(exact_upstream.decision.selected_attempts) < 2:
        raise ReassessmentDependencyError(
            "Persisted reassessment decisions require at least two selected attempts."
        )
    try:
        upstream = resolve_current_attempt_selection(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
            authorized_snapshot=authorized_snapshot,
        )
    except AttemptSelectionStorageError as error:
        raise ReassessmentDependencyError(
            f"Attempt-selection resolution failed: {error}"
        ) from error
    if (
        upstream.status != "selected"
        or not upstream.operative_selection
        or upstream.selected is None
        or upstream.selected.decision.decision_revision
        != candidate.attempt_selection.decision_revision
        or upstream.selected.decision_sha256
        != candidate.attempt_selection.decision_sha256
    ):
        raise ReassessmentStorageConflictError(
            "Current attempt selection changed or is not operative."
        )
    upstream_selected = _upstream_selected_attempts(upstream)
    if len(upstream_selected) < 2:
        raise ReassessmentStorageConflictError(
            "Current attempt selection no longer has multiple selected attempts."
        )
    try:
        policy = load_reassessment_policy_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy.policy_id,
            candidate.policy.policy_revision,
        )
    except ReassessmentStorageError as error:
        raise ReassessmentDependencyError(
            f"Exact reassessment policy could not be loaded: {error}"
        ) from error
    if policy.policy_sha256 != candidate.policy.policy_revision_sha256:
        raise ReassessmentDependencyError(
            "Reassessment policy digest does not match decision reference."
        )
    if candidate.mode not in policy.policy.allowed_modes:
        raise ReassessmentDependencyError(
            "Decision mode is not allowed by the exact reassessment policy."
        )
    if require_current_policy:
        current_policy = load_current_reassessment_policy(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy.policy_id,
        )
        if (
            current_policy is None
            or current_policy.policy_sha256 != policy.policy_sha256
        ):
            raise ReassessmentStorageConflictError(
                "Current reassessment policy changed since decision review."
            )
    _validate_relationships_against_selected(candidate, upstream_selected)
    return upstream


def _validate_relationships_against_selected(
    decision: ReassessmentDecision,
    selected: tuple[AttemptObservationReference, ...],
) -> None:
    selected_set = set(selected)
    if len(selected_set) != len(selected):
        raise ReassessmentDependencyError(
            "Attempt-selection decision contains duplicate selected attempts."
        )
    if decision.mode == "retain":
        if decision.contributing_attempts != selected:
            raise ReassessmentDependencyError(
                "retain mode must preserve the exact selected-attempt order."
            )
        return
    if decision.mode == "replace":
        relationships = decision.replacement_relationships
        related = tuple(
            attempt
            for relationship in relationships
            for attempt in (
                relationship.replacement_attempt,
                *relationship.replaced_attempts,
            )
        )
        if any(attempt not in selected_set for attempt in related):
            raise ReassessmentDependencyError(
                "replacement relationships may reference only exact selected attempts."
            )
        replaced = {
            attempt
            for relationship in relationships
            for attempt in relationship.replaced_attempts
        }
        expected = tuple(attempt for attempt in selected if attempt not in replaced)
        if decision.contributing_attempts != expected:
            raise ReassessmentDependencyError(
                "replace contributing_attempts must equal selected attempts minus "
                "explicitly replaced attempts."
            )
        return
    if decision.mode == "combine":
        members = tuple(
            attempt
            for combination in decision.combinations
            for attempt in combination.members
        )
        if any(attempt not in selected_set for attempt in members):
            raise ReassessmentDependencyError(
                "combination groups may reference only exact selected attempts."
            )
        if decision.contributing_attempts != selected:
            raise ReassessmentDependencyError(
                "combine mode must preserve all exact selected attempts as "
                "contributors."
            )
        return
    if (
        len(decision.recency_order) != len(selected)
        or set(decision.recency_order) != selected_set
    ):
        raise ReassessmentDependencyError(
            "recency_order must contain every exact selected attempt exactly once."
        )


def _upstream_selected_attempts(
    resolution: AttemptSelectionResolution,
) -> tuple[AttemptObservationReference, ...]:
    if resolution.selected is None:
        return ()
    return resolution.selected.decision.selected_attempts


def _resolution(
    status: ReassessmentResolutionStatus,
    upstream: AttemptSelectionResolution,
    selected: StoredReassessmentDecision | None,
) -> ReassessmentResolution:
    return ReassessmentResolution(
        status=status,
        attempt_selection=upstream,
        selected=selected,
        current_policy=None,
        contributing_attempts=(),
        replacement_relationships=(),
        combinations=(),
        recency_order=(),
        operative_reassessment=False,
    )


def _require_attempt_selection_root(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> None:
    base = attempt_selection_directory(root, class_id, grade_item_id, work)
    if not base.exists():
        raise ReassessmentStorageNotFoundError(
            "Attempt-selection storage must exist before reassessment policy."
        )
    _validate_existing_directory_chain(root, base)


def _policy_pointer(stored: StoredReassessmentPolicy) -> dict[str, object]:
    value = stored.policy
    return {
        "schema_version": REASSESSMENT_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": REASSESSMENT_POLICY_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "module_id": value.work.module_id,
        "work_id": value.work.work_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": stored.policy_sha256,
    }


def _decision_pointer(stored: StoredReassessmentDecision) -> dict[str, object]:
    value = stored.decision
    return {
        "schema_version": REASSESSMENT_DECISION_CURRENT_SCHEMA_VERSION,
        "record_type": REASSESSMENT_DECISION_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "module_id": value.work.module_id,
        "work_id": value.work.work_id,
        "subject_key": reassessment_subject_key(
            value.class_id, value.grade_item_id, value.work, value.student_id
        ),
        "decision_revision": value.decision_revision,
        "decision_sha256": stored.decision_sha256,
    }


def _load_policy_pointer(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    policy_value = _identifier(policy_id, "policy_id")
    _validate_reassessment_collections(root, class_value, item, validated_work)
    path = reassessment_policy_current_path(
        root, class_value, item, validated_work, policy_value
    )
    if not path.exists():
        if missing_ok:
            return None
        raise ReassessmentStorageNotFoundError("Reassessment policy pointer not found.")
    pointer = _read_pointer(path, root, _POLICY_POINTER_KEYS)
    if (
        pointer["schema_version"] != REASSESSMENT_POLICY_CURRENT_SCHEMA_VERSION
        or pointer["record_type"] != REASSESSMENT_POLICY_CURRENT_RECORD_TYPE
        or pointer["class_id"] != class_value
        or pointer["grade_item_id"] != item
        or pointer["module_id"] != validated_work.module_id
        or pointer["work_id"] != validated_work.work_id
        or pointer["policy_id"] != policy_value
    ):
        raise ReassessmentStorageIntegrityError(
            "Reassessment policy pointer identity does not match canonical path."
        )
    _positive_int(pointer["policy_revision"], "policy_revision")
    _sha256(pointer["policy_sha256"], "policy_sha256")
    return pointer


def _load_decision_pointer(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    student = _identifier(student_id, "student_id")
    subject_key = reassessment_subject_key(class_value, item, validated_work, student)
    _validate_reassessment_collections(root, class_value, item, validated_work)
    path = reassessment_decision_current_path(
        root, class_value, item, validated_work, student
    )
    if not path.exists():
        if missing_ok:
            return None
        raise ReassessmentStorageNotFoundError(
            "Reassessment decision pointer not found."
        )
    pointer = _read_pointer(path, root, _DECISION_POINTER_KEYS)
    if (
        pointer["schema_version"] != REASSESSMENT_DECISION_CURRENT_SCHEMA_VERSION
        or pointer["record_type"] != REASSESSMENT_DECISION_CURRENT_RECORD_TYPE
        or pointer["class_id"] != class_value
        or pointer["grade_item_id"] != item
        or pointer["module_id"] != validated_work.module_id
        or pointer["work_id"] != validated_work.work_id
        or pointer["subject_key"] != subject_key
    ):
        raise ReassessmentStorageIntegrityError(
            "Reassessment decision pointer identity does not match canonical path."
        )
    _positive_int(pointer["decision_revision"], "decision_revision")
    _sha256(pointer["decision_sha256"], "decision_sha256")
    return pointer


def _read_pointer(
    path: Path,
    root: Path,
    keys: frozenset[str],
) -> dict[str, object]:
    content = _read_bounded_regular_file(
        path, DEFAULT_MAXIMUM_REASSESSMENT_POINTER_BYTES
    )
    try:
        decoded = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except ReassessmentStorageIntegrityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ReassessmentStorageIntegrityError(
            "Reassessment pointer JSON is invalid."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != keys:
        raise ReassessmentStorageIntegrityError(
            "Reassessment pointer does not use exact schema."
        )
    if _canonical_json_bytes(decoded) != content:
        raise ReassessmentStorageIntegrityError(
            "Reassessment pointer is not canonically encoded."
        )
    _require_containment(root, path)
    return cast(dict[str, object], decoded)


def _validate_reassessment_collections(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> None:
    base = reassessment_directory(root, class_id, grade_item_id, work)
    if not base.exists():
        return
    _validate_existing_directory_chain(root, base)
    try:
        entries = tuple(base.iterdir())
    except OSError as error:
        raise ReassessmentStorageReadError(
            "Could not inspect reassessment collection root."
        ) from error
    allowed = {"policies", "students"}
    for entry in entries:
        if entry.name not in allowed:
            raise ReassessmentStorageIntegrityError(
                "Reassessment collection root has unexpected entry."
            )
        if entry.is_symlink() or not entry.is_dir():
            raise ReassessmentStorageIntegrityError(
                "Reassessment collection children must be real directories."
            )
    policies = base / "policies"
    if policies.exists():
        for entry in _directory_entries(policies, "reassessment policy collection"):
            if entry.is_symlink() or not entry.is_dir():
                raise ReassessmentStorageIntegrityError(
                    "Reassessment policy collection contains a non-directory entry."
                )
            try:
                validate_identifier(entry.name, "persisted policy_id")
            except IdentifierValidationError as error:
                raise ReassessmentStorageIntegrityError(
                    "Reassessment policy collection contains an invalid policy ID."
                ) from error
    students = base / "students"
    if students.exists():
        for entry in _directory_entries(students, "reassessment student collection"):
            if entry.is_symlink() or not entry.is_dir():
                raise ReassessmentStorageIntegrityError(
                    "Reassessment student collection contains a non-directory entry."
                )
            if _SHA256.fullmatch(entry.name) is None:
                raise ReassessmentStorageIntegrityError(
                    "Reassessment student collection contains an invalid subject key."
                )


def _directory_entries(path: Path, label: str) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise ReassessmentStorageReadError(f"Could not inspect {label}.") from error


def _list_history_revisions(
    root: Path,
    relation: Path,
    loader: Callable[[int], _HistoryT],
    transition: Callable[[_HistoryT, _HistoryT], _HistoryT],
) -> tuple[int, ...]:
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_history_root(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    jsons: set[int] = set()
    digests: set[int] = set()
    for entry in _directory_entries(revisions_dir, "reassessment revisions directory"):
        if entry.is_symlink() or not entry.is_file():
            raise ReassessmentStorageIntegrityError(
                "Reassessment revisions contain a nonregular entry."
            )
        match = _REVISION_JSON.fullmatch(entry.name)
        if match is not None:
            jsons.add(int(match.group(1)))
            continue
        match = _REVISION_DIGEST.fullmatch(entry.name)
        if match is not None:
            digests.add(int(match.group(1)))
            continue
        raise ReassessmentStorageIntegrityError(
            "Reassessment revisions contain an unexpected filename."
        )
    if jsons != digests:
        raise ReassessmentStorageIntegrityError(
            "Reassessment revision JSON/digest pairs are incomplete."
        )
    revisions = tuple(sorted(jsons))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise ReassessmentStorageIntegrityError(
            "Reassessment revision history is not contiguous."
        )
    previous: _HistoryT | None = None
    for revision in revisions:
        current = loader(revision)
        if previous is not None:
            try:
                transition(previous, current)
            except ReassessmentValidationError as error:
                raise ReassessmentStorageIntegrityError(
                    "Reassessment revision transition is invalid."
                ) from error
        previous = current
    return revisions


def _validate_history_root(relation: Path) -> None:
    if not relation.exists():
        return
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise ReassessmentStorageReadError(
            "Could not inspect reassessment history root."
        ) from error
    allowed = {"revisions", "current.json", ".write.lock"}
    for entry in entries:
        if entry.name not in allowed:
            raise ReassessmentStorageIntegrityError(
                "Reassessment history root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise ReassessmentStorageIntegrityError(
                    "Reassessment revisions path must be a real directory."
                )
        elif entry.exists() and (entry.is_symlink() or not entry.is_file()):
            raise ReassessmentStorageIntegrityError(
                "Reassessment history metadata must be a regular file."
            )


def _read_revision_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() or not digest_path.exists():
        raise ReassessmentStorageNotFoundError("Reassessment revision not found.")
    content = _read_bounded_regular_file(path, maximum)
    digest_bytes = _read_bounded_regular_file(
        digest_path, DEFAULT_MAXIMUM_REASSESSMENT_DIGEST_BYTES
    )
    digest = _parse_digest(digest_bytes)
    if hashlib.sha256(content).hexdigest() != digest:
        raise ReassessmentStorageIntegrityError(
            "Reassessment revision digest does not match exact bytes."
        )
    _require_containment(root, path)
    _require_containment(root, digest_path)
    return content, digest


def _write_revision_pair(
    path: Path,
    digest_path: Path,
    content: bytes,
    digest: str,
) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        with digest_path.open("xb") as handle:
            handle.write((digest + "\n").encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except FileExistsError as error:
        raise ReassessmentStorageConflictError(
            "Reassessment revision was concurrently created."
        ) from error
    except OSError as error:
        raise ReassessmentStorageWriteError(
            "Could not write immutable reassessment revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _ensure_directory_chain(root, path.parent)
    _require_containment(root, path)
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".current-", dir=path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            _fsync_directory(path.parent)
        finally:
            if temp.exists():
                temp.unlink()
    except OSError as error:
        raise ReassessmentStorageWriteError(
            "Could not publish reassessment current pointer."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(b"locked\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise ReassessmentStorageLockError(
            "Reassessment history is already locked."
        ) from error
    except OSError as error:
        raise ReassessmentStorageWriteError(
            "Could not create reassessment write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
    except OSError as error:
        raise ReassessmentStorageWriteError(
            "Could not remove reassessment write lock."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    relative = target.relative_to(root)
    current = root
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ReassessmentStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ReassessmentStorageIntegrityError(
                    "Canonical reassessment directory chain is unsafe."
                )
            continue
        try:
            current.mkdir()
        except FileExistsError:
            if current.is_symlink() or not current.is_dir():
                raise ReassessmentStorageIntegrityError(
                    "Canonical reassessment directory chain is unsafe."
                )
        except OSError as error:
            raise ReassessmentStorageWriteError(
                "Could not create reassessment directory."
            ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise ReassessmentStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists() or current.is_symlink() or not current.is_dir():
            raise ReassessmentStorageIntegrityError(
                "Canonical reassessment directory chain is unsafe."
            )


def _read_bounded_regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReassessmentStorageIntegrityError(
            "Reassessment storage entry must be a regular file."
        )
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ReassessmentStorageReadError(
            "Could not inspect reassessment file."
        ) from error
    if size > maximum:
        raise ReassessmentStorageTooLargeError("Reassessment file exceeds byte limit.")
    try:
        with path.open("rb") as handle:
            data = handle.read(maximum + 1)
    except OSError as error:
        raise ReassessmentStorageReadError(
            "Could not read reassessment file."
        ) from error
    if len(data) > maximum:
        raise ReassessmentStorageTooLargeError("Reassessment file exceeds byte limit.")
    return data


def _parse_digest(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReassessmentStorageIntegrityError(
            "Reassessment digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or "\r" in text or text.count("\n") != 1:
        raise ReassessmentStorageIntegrityError(
            "Reassessment digest sidecar must use one canonical LF."
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
        raise ReassessmentStorageIntegrityError(
            "Reassessment pointer cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReassessmentStorageIntegrityError(
                f"Duplicate reassessment pointer key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ReassessmentStorageIntegrityError(
        f"Non-finite reassessment pointer value is invalid: {value}"
    )


def _root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        root = root.absolute()
    return root


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise ReassessmentStorageValidationError("work must be a Core ModuleWorkRef.")
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise ReassessmentStorageValidationError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReassessmentStorageValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReassessmentStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ReassessmentStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReassessmentStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ReassessmentStorageValidationError(
            "Reassessment path escapes workspace root."
        ) from error


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
