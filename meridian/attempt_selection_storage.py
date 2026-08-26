"""Canonical persistence, candidate derivation, and resolution for attempt selection."""

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

from meridian.attempt_selection import (
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionSerializationError,
    AttemptSelectionValidationError,
    AttemptTargetReference,
    attempt_selection_decision_from_json_bytes,
    attempt_selection_decision_to_json_bytes,
    attempt_selection_policy_from_json_bytes,
    attempt_selection_policy_to_json_bytes,
    attempt_subject_key,
    selection_cardinality_allows,
    validate_attempt_selection_decision,
    validate_attempt_selection_decision_transition,
    validate_attempt_selection_policy,
    validate_attempt_selection_policy_transition,
)
from meridian.evidence_eligibility import EvidenceSourceReference, evidence_source_key
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityStorageError,
    resolve_current_evidence_eligibility,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    grade_item_membership_directory,
    load_current_grade_item_membership_decision,
    load_grade_item_membership_revision,
)

if TYPE_CHECKING:
    from meridian.evidence import EvidenceItem
    from meridian.projection_cache import AuthorizedProjectionSnapshot

ATTEMPT_SELECTION_POLICY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
ATTEMPT_SELECTION_POLICY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_attempt_selection_policy_current"
)
ATTEMPT_SELECTION_DECISION_CURRENT_SCHEMA_VERSION: Final[str] = "1"
ATTEMPT_SELECTION_DECISION_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_attempt_selection_decision_current"
)
DEFAULT_MAXIMUM_ATTEMPT_SELECTION_POLICY_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_ATTEMPT_SELECTION_DECISION_BYTES: Final[int] = 256 * 1024
DEFAULT_MAXIMUM_ATTEMPT_SELECTION_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_ATTEMPT_SELECTION_DIGEST_BYTES: Final[int] = 128

_HistoryT = TypeVar("_HistoryT")

AttemptSelectionWriteDisposition: TypeAlias = Literal["created", "existing"]
AttemptSelectionSelectDisposition: TypeAlias = Literal["created", "updated", "existing"]
AttemptCandidateDerivationStatus: TypeAlias = Literal[
    "applicable",
    "not_applicable",
    "unsupported_attempt_shape",
    "membership_stale",
    "source_unverifiable",
]
AttemptSelectionResolutionStatus: TypeAlias = Literal[
    "not_applicable",
    "no_decision",
    "selected_none",
    "selected",
    "policy_stale",
    "membership_stale",
    "eligibility_stale",
    "candidate_set_stale",
    "source_unverifiable",
    "unsupported_attempt_shape",
]

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


class AttemptSelectionStorageError(RuntimeError):
    """Base error for canonical attempt-selection storage and resolution."""

    code: str = "attempt_selection.storage_error"


class AttemptSelectionStorageValidationError(AttemptSelectionStorageError, ValueError):
    code = "attempt_selection.storage_invalid"


class AttemptSelectionStorageNotFoundError(AttemptSelectionStorageError):
    code = "attempt_selection.not_found"


class AttemptSelectionStorageReadError(AttemptSelectionStorageError):
    code = "attempt_selection.read_failed"


class AttemptSelectionStorageWriteError(AttemptSelectionStorageError):
    code = "attempt_selection.write_failed"


class AttemptSelectionStorageConflictError(AttemptSelectionStorageError):
    code = "attempt_selection.conflict"


class AttemptSelectionStorageLockError(AttemptSelectionStorageConflictError):
    code = "attempt_selection.locked"


class AttemptSelectionStorageIntegrityError(AttemptSelectionStorageError):
    code = "attempt_selection.integrity"


class AttemptSelectionStorageTooLargeError(AttemptSelectionStorageReadError):
    code = "attempt_selection.too_large"


class AttemptSelectionDependencyError(AttemptSelectionStorageError):
    code = "attempt_selection.dependency_invalid"


@dataclass(frozen=True, slots=True)
class AttemptCandidateDerivation:
    status: AttemptCandidateDerivationStatus
    source_snapshot: AttemptProjectionReference
    student_id: str
    candidates: tuple[AttemptCandidate, ...]

    def __post_init__(self) -> None:
        if self.status not in {
            "applicable",
            "not_applicable",
            "unsupported_attempt_shape",
            "membership_stale",
            "source_unverifiable",
        }:
            raise AttemptSelectionStorageValidationError(
                "candidate derivation status is invalid."
            )
        if not isinstance(self.source_snapshot, AttemptProjectionReference):
            raise AttemptSelectionStorageValidationError(
                "source_snapshot must be an AttemptProjectionReference."
            )
        object.__setattr__(
            self, "student_id", _identifier(self.student_id, "student_id")
        )
        try:
            candidates = tuple(self.candidates)
        except TypeError as error:
            raise AttemptSelectionStorageValidationError(
                "candidates must be an iterable of AttemptCandidate values."
            ) from error
        if any(not isinstance(candidate, AttemptCandidate) for candidate in candidates):
            raise AttemptSelectionStorageValidationError(
                "candidates must contain only AttemptCandidate values."
            )
        object.__setattr__(self, "candidates", candidates)
        if self.status != "applicable" and candidates:
            raise AttemptSelectionStorageValidationError(
                "non-applicable or blocked derivation must not carry candidates."
            )


@dataclass(frozen=True, slots=True)
class StoredAttemptSelectionPolicy:
    policy: AttemptSelectionPolicy
    policy_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.policy, AttemptSelectionPolicy):
            raise AttemptSelectionStorageValidationError("policy has an invalid type.")
        digest = _sha256(self.policy_sha256, "policy_sha256")
        if (
            type(self.content) is not bytes
            or hashlib.sha256(self.content).hexdigest() != digest
        ):
            raise AttemptSelectionStorageValidationError(
                "policy_sha256 must match exact immutable content."
            )
        try:
            decoded = attempt_selection_policy_from_json_bytes(self.content)
        except (
            AttemptSelectionSerializationError,
            AttemptSelectionValidationError,
        ) as error:
            raise AttemptSelectionStorageValidationError(
                "content is not a canonical attempt-selection policy."
            ) from error
        if decoded != self.policy:
            raise AttemptSelectionStorageValidationError(
                "policy content identity mismatch."
            )
        expected_relative = attempt_selection_policy_revision_relative_path(
            self.policy.class_id,
            self.policy.grade_item_id,
            self.policy.work,
            self.policy.policy_id,
            self.policy.policy_revision,
        )
        if self.relative_path != expected_relative:
            raise AttemptSelectionStorageValidationError(
                "relative_path is not the canonical policy revision location."
            )
        if self.path.name != f"{self.policy.policy_revision}.json":
            raise AttemptSelectionStorageValidationError(
                "policy path filename does not match policy revision identity."
            )
        object.__setattr__(self, "policy_sha256", digest)


@dataclass(frozen=True, slots=True)
class StoredAttemptSelectionDecision:
    decision: AttemptSelectionDecision
    decision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, AttemptSelectionDecision):
            raise AttemptSelectionStorageValidationError(
                "decision has an invalid type."
            )
        digest = _sha256(self.decision_sha256, "decision_sha256")
        if (
            type(self.content) is not bytes
            or hashlib.sha256(self.content).hexdigest() != digest
        ):
            raise AttemptSelectionStorageValidationError(
                "decision_sha256 must match exact immutable content."
            )
        try:
            decoded = attempt_selection_decision_from_json_bytes(self.content)
        except (
            AttemptSelectionSerializationError,
            AttemptSelectionValidationError,
        ) as error:
            raise AttemptSelectionStorageValidationError(
                "content is not a canonical attempt-selection decision."
            ) from error
        if decoded != self.decision:
            raise AttemptSelectionStorageValidationError(
                "decision content identity mismatch."
            )
        expected_relative = attempt_selection_decision_revision_relative_path(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.work,
            self.decision.student_id,
            self.decision.decision_revision,
        )
        if self.relative_path != expected_relative:
            raise AttemptSelectionStorageValidationError(
                "relative_path is not the canonical decision revision location."
            )
        if self.path.name != f"{self.decision.decision_revision}.json":
            raise AttemptSelectionStorageValidationError(
                "decision path filename does not match decision revision identity."
            )
        object.__setattr__(self, "decision_sha256", digest)


@dataclass(frozen=True, slots=True)
class AttemptSelectionPolicyWriteResult:
    disposition: AttemptSelectionWriteDisposition
    stored: StoredAttemptSelectionPolicy


@dataclass(frozen=True, slots=True)
class AttemptSelectionDecisionWriteResult:
    disposition: AttemptSelectionWriteDisposition
    stored: StoredAttemptSelectionDecision


@dataclass(frozen=True, slots=True)
class AttemptSelectionPolicySelectionResult:
    disposition: AttemptSelectionSelectDisposition
    stored: StoredAttemptSelectionPolicy


@dataclass(frozen=True, slots=True)
class AttemptSelectionDecisionSelectionResult:
    disposition: AttemptSelectionSelectDisposition
    stored: StoredAttemptSelectionDecision
    derivation: AttemptCandidateDerivation


@dataclass(frozen=True, slots=True)
class AttemptSelectionResolution:
    status: AttemptSelectionResolutionStatus
    selected: StoredAttemptSelectionDecision | None
    current_policy: StoredAttemptSelectionPolicy | None
    current_candidates: tuple[AttemptCandidate, ...]
    operative_selection: bool

    def __post_init__(self) -> None:
        if self.status not in {
            "not_applicable",
            "no_decision",
            "selected_none",
            "selected",
            "policy_stale",
            "membership_stale",
            "eligibility_stale",
            "candidate_set_stale",
            "source_unverifiable",
            "unsupported_attempt_shape",
        }:
            raise AttemptSelectionStorageValidationError(
                "attempt-selection resolution status is invalid."
            )
        if not isinstance(self.operative_selection, bool):
            raise AttemptSelectionStorageValidationError(
                "operative_selection must be boolean."
            )


def attempt_selection_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return grade_item_membership_directory(
        _root(workspace_root),
        _identifier(class_id, "class_id"),
        _identifier(grade_item_id, "grade_item_id"),
        _work(work),
    ) / "attempt_selection"


def attempt_selection_policies_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        attempt_selection_directory(workspace_root, class_id, grade_item_id, work)
        / "policies"
    )


def attempt_selection_policy_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> Path:
    return attempt_selection_policies_directory(
        workspace_root, class_id, grade_item_id, work
    ) / _identifier(policy_id, "policy_id")


def attempt_selection_policy_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> Path:
    revision = _positive_int(policy_revision, "policy_revision")
    return attempt_selection_policy_directory(
        workspace_root, class_id, grade_item_id, work, policy_id
    ) / "revisions" / f"{revision}.json"


def attempt_selection_policy_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> Path:
    return attempt_selection_policy_directory(
        workspace_root, class_id, grade_item_id, work, policy_id
    ) / "current.json"


def attempt_selection_students_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        attempt_selection_directory(workspace_root, class_id, grade_item_id, work)
        / "students"
    )


def attempt_selection_subject_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> Path:
    validated_work = _work(work)
    key = attempt_subject_key(class_id, grade_item_id, validated_work, student_id)
    return attempt_selection_students_directory(
        workspace_root, class_id, grade_item_id, validated_work
    ) / key


def attempt_selection_decision_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> Path:
    revision = _positive_int(decision_revision, "decision_revision")
    return attempt_selection_subject_directory(
        workspace_root, class_id, grade_item_id, work, student_id
    ) / "revisions" / f"{revision}.json"


def attempt_selection_decision_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> Path:
    return attempt_selection_subject_directory(
        workspace_root, class_id, grade_item_id, work, student_id
    ) / "current.json"


def attempt_selection_policy_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise AttemptSelectionStorageValidationError(
            "work.class_id must match class_id."
        )
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    return (
        f"classes/{class_value}/modules/meridian/grade_items/{item}/memberships/"
        f"{validated_work.module_id}/{validated_work.work_id}/attempt_selection/"
        f"policies/{policy_value}/revisions/{revision}.json"
    )


def attempt_selection_decision_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise AttemptSelectionStorageValidationError(
            "work.class_id must match class_id."
        )
    student = _identifier(student_id, "student_id")
    revision = _positive_int(decision_revision, "decision_revision")
    key = attempt_subject_key(class_value, item, validated_work, student)
    return (
        f"classes/{class_value}/modules/meridian/grade_items/{item}/memberships/"
        f"{validated_work.module_id}/{validated_work.work_id}/attempt_selection/"
        f"students/{key}/revisions/{revision}.json"
    )


def derive_attempt_candidates(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptCandidateDerivation:
    """Derive exact attempt candidates solely from explicit shape and #29 state."""
    from meridian.projection_cache import AuthorizedProjectionSnapshot

    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise AttemptSelectionDependencyError(
            "Attempt candidate derivation requires an AuthorizedProjectionSnapshot."
        )
    class_value = _identifier(class_id, "class_id")
    grade_item = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    stored = authorized_snapshot.stored
    snapshot = stored.snapshot
    publication = snapshot.source.publication
    source_snapshot = AttemptProjectionReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
    )
    if publication.work.class_id != class_value:
        raise AttemptSelectionDependencyError(
            "Authorized projection class does not match attempt-selection class."
        )
    if "multiple_attempts" not in publication.capabilities:
        return AttemptCandidateDerivation(
            status="not_applicable",
            source_snapshot=source_snapshot,
            student_id=student,
            candidates=(),
        )

    grouped: dict[AttemptObservationReference, list[AttemptEligibilityBasis]] = {}
    target_to_native: dict[AttemptTargetReference, AttemptNativeIdentity] = {}
    native_to_target: dict[AttemptNativeIdentity, AttemptTargetReference] = {}

    for item in snapshot.inventory.items:
        if item.subject is None or item.subject.student_id != student:
            continue
        source = EvidenceSourceReference(
            work=publication.work,
            publication_id=publication.publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=item.item_id,
        )
        try:
            resolution = resolve_current_evidence_eligibility(
                workspace_root,
                class_value,
                grade_item,
                source,
                authorized_snapshot=authorized_snapshot,
            )
        except EvidenceEligibilityStorageError:
            return AttemptCandidateDerivation(
                status="source_unverifiable",
                source_snapshot=source_snapshot,
                student_id=student,
                candidates=(),
            )
        if resolution.status == "membership_stale":
            return AttemptCandidateDerivation(
                status="membership_stale",
                source_snapshot=source_snapshot,
                student_id=student,
                candidates=(),
            )
        if resolution.status == "source_unverifiable":
            return AttemptCandidateDerivation(
                status="source_unverifiable",
                source_snapshot=source_snapshot,
                student_id=student,
                candidates=(),
            )
        if not resolution.operative_included:
            continue
        selected = resolution.selected
        if selected is None:
            raise AttemptSelectionStorageIntegrityError(
                "Operative eligibility resolution is missing its selected decision."
            )
        attempt = _attempt_from_item(item, source_snapshot, student)
        if attempt is None:
            return AttemptCandidateDerivation(
                status="unsupported_attempt_shape",
                source_snapshot=source_snapshot,
                student_id=student,
                candidates=(),
            )
        prior_native = target_to_native.get(attempt.target)
        prior_target = native_to_target.get(attempt.native)
        if (prior_native is not None and prior_native != attempt.native) or (
            prior_target is not None and prior_target != attempt.target
        ):
            return AttemptCandidateDerivation(
                status="unsupported_attempt_shape",
                source_snapshot=source_snapshot,
                student_id=student,
                candidates=(),
            )
        target_to_native[attempt.target] = attempt.native
        native_to_target[attempt.native] = attempt.target
        grouped.setdefault(attempt, []).append(
            AttemptEligibilityBasis(
                source=source,
                eligibility_revision=selected.decision.eligibility_revision,
                eligibility_decision_sha256=selected.decision_sha256,
            )
        )

    candidates = tuple(
        AttemptCandidate(
            attempt=attempt,
            eligible_evidence=tuple(
                sorted(bases, key=lambda value: evidence_source_key(value.source))
            ),
        )
        for attempt, bases in sorted(
            grouped.items(), key=lambda pair: _attempt_sort_key(pair[0])
        )
    )
    return AttemptCandidateDerivation(
        status="applicable",
        source_snapshot=source_snapshot,
        student_id=student,
        candidates=candidates,
    )


def write_attempt_selection_policy_revision(
    workspace_root: str | Path,
    policy: AttemptSelectionPolicy,
) -> AttemptSelectionPolicyWriteResult:
    candidate = validate_attempt_selection_policy(policy)
    root = _root(workspace_root)
    _validate_attempt_selection_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    _require_membership_history(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    target = attempt_selection_policy_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.policy_id,
        candidate.policy_revision,
    )
    digest_path = Path(str(target) + ".sha256")
    content = attempt_selection_policy_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_ATTEMPT_SELECTION_POLICY_BYTES:
        raise AttemptSelectionStorageWriteError(
            "Attempt-selection policy exceeds byte limit."
        )
    digest = hashlib.sha256(content).hexdigest()
    if target.exists() or digest_path.exists():
        stored = load_attempt_selection_policy_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy_id,
            candidate.policy_revision,
        )
        if stored.content != content:
            raise AttemptSelectionStorageConflictError(
                "Attempt-selection policy revision already exists with "
                "different content."
            )
        return AttemptSelectionPolicyWriteResult("existing", stored)
    relation = target.parent.parent
    _ensure_directory_chain(root, target.parent)
    _validate_attempt_selection_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        if target.exists() or digest_path.exists():
            stored = load_attempt_selection_policy_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.policy_id,
                candidate.policy_revision,
            )
            if stored.content != content:
                raise AttemptSelectionStorageConflictError(
                    "Attempt-selection policy revision already exists with "
                "different content."
                )
            return AttemptSelectionPolicyWriteResult("existing", stored)
        revisions = list_attempt_selection_policy_revisions(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy_id,
        )
        if revisions:
            expected = revisions[-1] + 1
            if candidate.policy_revision != expected:
                raise AttemptSelectionStorageConflictError(
                    "Policy revision must be exactly one greater than history."
                )
            previous = load_attempt_selection_policy_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.policy_id,
                revisions[-1],
            ).policy
            try:
                validate_attempt_selection_policy_transition(previous, candidate)
            except AttemptSelectionValidationError as error:
                raise AttemptSelectionStorageConflictError(str(error)) from error
        elif candidate.policy_revision != 1:
            raise AttemptSelectionStorageConflictError(
                "Initial policy revision must be 1."
            )
        _write_revision_pair(target, digest_path, content, digest)
        return AttemptSelectionPolicyWriteResult(
            "created",
            load_attempt_selection_policy_revision(
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


def load_attempt_selection_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
) -> StoredAttemptSelectionPolicy:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    _validate_attempt_selection_collections(
        root, class_value, item, validated_work
    )
    policy_value = _identifier(policy_id, "policy_id")
    revision = _positive_int(policy_revision, "policy_revision")
    path = attempt_selection_policy_revision_path(
        root, class_value, item, validated_work, policy_value, revision
    )
    content, digest = _read_revision_pair(
        root, path, DEFAULT_MAXIMUM_ATTEMPT_SELECTION_POLICY_BYTES
    )
    try:
        policy = attempt_selection_policy_from_json_bytes(content)
    except (
        AttemptSelectionSerializationError,
        AttemptSelectionValidationError,
    ) as error:
        raise AttemptSelectionStorageIntegrityError(
            f"Attempt-selection policy is invalid or noncanonical: {error}"
        ) from error
    if (
        policy.class_id != class_value
        or policy.grade_item_id != item
        or policy.work != validated_work
        or policy.policy_id != policy_value
        or policy.policy_revision != revision
    ):
        raise AttemptSelectionStorageIntegrityError(
            "Persisted policy identity does not match canonical path."
        )
    return StoredAttemptSelectionPolicy(
        policy=policy,
        policy_sha256=digest,
        path=path,
        relative_path=attempt_selection_policy_revision_relative_path(
            class_value, item, validated_work, policy_value, revision
        ),
        content=content,
    )


def list_attempt_selection_policy_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    _validate_attempt_selection_collections(
        root, class_id, grade_item_id, work
    )
    relation = attempt_selection_policy_directory(
        root, class_id, grade_item_id, work, policy_id
    )
    return _list_history_revisions(
        root,
        relation,
        lambda number: load_attempt_selection_policy_revision(
            root, class_id, grade_item_id, work, policy_id, number
        ).policy,
        validate_attempt_selection_policy_transition,
    )


def get_current_attempt_selection_policy_revision(
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


def load_current_attempt_selection_policy(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
) -> StoredAttemptSelectionPolicy | None:
    pointer = _load_policy_pointer(
        workspace_root, class_id, grade_item_id, work, policy_id, missing_ok=True
    )
    if pointer is None:
        return None
    stored = load_attempt_selection_policy_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
        cast(int, pointer["policy_revision"]),
    )
    if stored.policy_sha256 != pointer["policy_sha256"]:
        raise AttemptSelectionStorageIntegrityError(
            "Policy current pointer digest does not match selected revision."
        )
    return stored


def select_attempt_selection_policy_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    policy_id: str,
    policy_revision: int,
    *,
    expected_current_policy_revision: int | None,
) -> AttemptSelectionPolicySelectionResult:
    root = _root(workspace_root)
    target = load_attempt_selection_policy_revision(
        root, class_id, grade_item_id, work, policy_id, policy_revision
    )
    relation = attempt_selection_policy_directory(
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
            raise AttemptSelectionStorageConflictError(
                "Expected current policy revision does not match stored selection."
            )
        pointer = _policy_pointer(target)
        if current == pointer:
            return AttemptSelectionPolicySelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            attempt_selection_policy_current_path(
                root, class_id, grade_item_id, work, policy_id
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: AttemptSelectionSelectDisposition = (
            "created" if current is None else "updated"
        )
        return AttemptSelectionPolicySelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def write_attempt_selection_decision_revision(
    workspace_root: str | Path,
    decision: AttemptSelectionDecision,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptSelectionDecisionWriteResult:
    candidate = validate_attempt_selection_decision(decision)
    root = _root(workspace_root)
    _validate_attempt_selection_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    target = attempt_selection_decision_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.student_id,
        candidate.decision_revision,
    )
    digest_path = Path(str(target) + ".sha256")
    content = attempt_selection_decision_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_ATTEMPT_SELECTION_DECISION_BYTES:
        raise AttemptSelectionStorageWriteError(
            "Attempt-selection decision exceeds byte limit."
        )
    digest = hashlib.sha256(content).hexdigest()

    # Exact immutable retry is valid even if current policy/eligibility later changed.
    if target.exists() or digest_path.exists():
        stored = load_attempt_selection_decision_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
            candidate.decision_revision,
        )
        if stored.content != content or stored.decision_sha256 != digest:
            raise AttemptSelectionStorageConflictError(
                "Attempt-selection decision revision already exists with "
                "different content."
            )
        return AttemptSelectionDecisionWriteResult("existing", stored)

    # Validate dependencies before creating any #30 decision storage.
    derivation = _validate_decision_dependencies(
        root, candidate, authorized_snapshot, require_current_policy=True
    )
    if derivation.candidates != candidate.candidates:
        raise AttemptSelectionStorageConflictError(
            "Attempt candidate or eligibility basis changed before decision write."
        )

    relation = target.parent.parent
    _ensure_directory_chain(root, target.parent)
    _validate_attempt_selection_collections(
        root, candidate.class_id, candidate.grade_item_id, candidate.work
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        # A concurrent writer may have committed this exact immutable revision.
        if target.exists() or digest_path.exists():
            stored = load_attempt_selection_decision_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                candidate.decision_revision,
            )
            if stored.content != content or stored.decision_sha256 != digest:
                raise AttemptSelectionStorageConflictError(
                    "Attempt-selection decision revision already exists with "
                    "different content."
                )
            return AttemptSelectionDecisionWriteResult("existing", stored)

        # Revalidate mutable dependencies under the per-student lock.
        derivation = _validate_decision_dependencies(
            root, candidate, authorized_snapshot, require_current_policy=True
        )
        if derivation.candidates != candidate.candidates:
            raise AttemptSelectionStorageConflictError(
                "Attempt candidate or eligibility basis changed before decision write."
            )
        revisions = list_attempt_selection_decision_revisions(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.student_id,
        )
        if revisions:
            expected = revisions[-1] + 1
            if candidate.decision_revision != expected:
                raise AttemptSelectionStorageConflictError(
                    "Decision revision must be exactly one greater than history."
                )
            previous = load_attempt_selection_decision_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.work,
                candidate.student_id,
                revisions[-1],
            ).decision
            try:
                validate_attempt_selection_decision_transition(previous, candidate)
            except AttemptSelectionValidationError as error:
                raise AttemptSelectionStorageConflictError(str(error)) from error
        elif candidate.decision_revision != 1:
            raise AttemptSelectionStorageConflictError(
                "Initial decision revision must be 1."
            )
        _write_revision_pair(target, digest_path, content, digest)
        return AttemptSelectionDecisionWriteResult(
            "created",
            load_attempt_selection_decision_revision(
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

def load_attempt_selection_decision_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
) -> StoredAttemptSelectionDecision:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    _validate_attempt_selection_collections(
        root, class_value, item, validated_work
    )
    student = _identifier(student_id, "student_id")
    revision = _positive_int(decision_revision, "decision_revision")
    path = attempt_selection_decision_revision_path(
        root, class_value, item, validated_work, student, revision
    )
    content, digest = _read_revision_pair(
        root, path, DEFAULT_MAXIMUM_ATTEMPT_SELECTION_DECISION_BYTES
    )
    try:
        decision = attempt_selection_decision_from_json_bytes(content)
    except (
        AttemptSelectionSerializationError,
        AttemptSelectionValidationError,
    ) as error:
        raise AttemptSelectionStorageIntegrityError(
            f"Attempt-selection decision is invalid or noncanonical: {error}"
        ) from error
    if (
        decision.class_id != class_value
        or decision.grade_item_id != item
        or decision.work != validated_work
        or decision.student_id != student
        or decision.decision_revision != revision
    ):
        raise AttemptSelectionStorageIntegrityError(
            "Persisted attempt-selection decision identity does not match "
            "canonical path."
        )
    return StoredAttemptSelectionDecision(
        decision=decision,
        decision_sha256=digest,
        path=path,
        relative_path=attempt_selection_decision_revision_relative_path(
            class_value, item, validated_work, student, revision
        ),
        content=content,
    )


def list_attempt_selection_decision_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    _validate_attempt_selection_collections(
        root, class_id, grade_item_id, work
    )
    relation = attempt_selection_subject_directory(
        root, class_id, grade_item_id, work, student_id
    )
    return _list_history_revisions(
        root,
        relation,
        lambda number: load_attempt_selection_decision_revision(
            root, class_id, grade_item_id, work, student_id, number
        ).decision,
        validate_attempt_selection_decision_transition,
    )


def get_current_attempt_selection_decision_revision(
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


def load_current_attempt_selection_decision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> StoredAttemptSelectionDecision | None:
    pointer = _load_decision_pointer(
        workspace_root, class_id, grade_item_id, work, student_id, missing_ok=True
    )
    if pointer is None:
        return None
    stored = load_attempt_selection_decision_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
        cast(int, pointer["decision_revision"]),
    )
    if stored.decision_sha256 != pointer["decision_sha256"]:
        raise AttemptSelectionStorageIntegrityError(
            "Decision current pointer digest does not match selected revision."
        )
    return stored


def select_attempt_selection_decision_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    decision_revision: int,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    expected_current_decision_revision: int | None,
) -> AttemptSelectionDecisionSelectionResult:
    root = _root(workspace_root)
    target = load_attempt_selection_decision_revision(
        root, class_id, grade_item_id, work, student_id, decision_revision
    )
    relation = attempt_selection_subject_directory(
        root, class_id, grade_item_id, work, student_id
    )
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_history_root(relation)
        # Candidate, membership, policy, and eligibility state are mutable selectors;
        # validate them while this student's decision selection is locked.
        derivation = _validate_decision_dependencies(
            root, target.decision, authorized_snapshot, require_current_policy=True
        )
        if derivation.candidates != target.decision.candidates:
            raise AttemptSelectionStorageConflictError(
                "Current candidate or eligibility basis differs from selected decision."
            )
        current = _load_decision_pointer(
            root, class_id, grade_item_id, work, student_id, missing_ok=True
        )
        current_revision = (
            None if current is None else cast(int, current["decision_revision"])
        )
        if current_revision != expected_current_decision_revision:
            raise AttemptSelectionStorageConflictError(
                "Expected current decision revision does not match stored selection."
            )
        pointer = _decision_pointer(target)
        if current == pointer:
            return AttemptSelectionDecisionSelectionResult(
                "existing", target, derivation
            )
        _atomic_write_pointer(
            root,
            attempt_selection_decision_current_path(
                root, class_id, grade_item_id, work, student_id
            ),
            _canonical_json_bytes(pointer),
        )
        disposition: AttemptSelectionSelectDisposition = (
            "created" if current is None else "updated"
        )
        return AttemptSelectionDecisionSelectionResult(
            disposition, target, derivation
        )
    finally:
        _remove_lock(lock)

def resolve_current_attempt_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptSelectionResolution:
    root = _root(workspace_root)
    selected = load_current_attempt_selection_decision(
        root, class_id, grade_item_id, work, student_id
    )
    derivation = derive_attempt_candidates(
        root, class_id, grade_item_id, student_id, authorized_snapshot
    )
    if derivation.status == "not_applicable":
        return AttemptSelectionResolution("not_applicable", selected, None, (), False)
    if derivation.status == "unsupported_attempt_shape":
        return AttemptSelectionResolution(
            "unsupported_attempt_shape", selected, None, (), False
        )
    if derivation.status == "source_unverifiable":
        return AttemptSelectionResolution(
            "source_unverifiable", selected, None, (), False
        )
    if derivation.status == "membership_stale":
        return AttemptSelectionResolution("membership_stale", selected, None, (), False)
    if selected is None:
        return AttemptSelectionResolution(
            "no_decision", None, None, derivation.candidates, False
        )
    decision = selected.decision
    if decision.source_snapshot != derivation.source_snapshot:
        return AttemptSelectionResolution(
            "candidate_set_stale", selected, None, derivation.candidates, False
        )
    try:
        membership = load_current_grade_item_membership_decision(
            root, class_id, grade_item_id, work
        )
    except GradeItemMembershipStorageError:
        membership = None
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision != decision.membership_revision
        or membership.decision_sha256 != decision.membership_revision_sha256
    ):
        return AttemptSelectionResolution(
            "membership_stale", selected, None, derivation.candidates, False
        )
    current_policy = load_current_attempt_selection_policy(
        root, class_id, grade_item_id, work, decision.policy.policy_id
    )
    if (
        current_policy is None
        or current_policy.policy.policy_revision != decision.policy.policy_revision
        or current_policy.policy_sha256 != decision.policy.policy_revision_sha256
    ):
        return AttemptSelectionResolution(
            "policy_stale", selected, current_policy, derivation.candidates, False
        )
    old_attempts = tuple(candidate.attempt for candidate in decision.candidates)
    new_attempts = tuple(candidate.attempt for candidate in derivation.candidates)
    if old_attempts != new_attempts:
        return AttemptSelectionResolution(
            "candidate_set_stale",
            selected,
            current_policy,
            derivation.candidates,
            False,
        )
    if decision.candidates != derivation.candidates:
        return AttemptSelectionResolution(
            "eligibility_stale", selected, current_policy, derivation.candidates, False
        )
    status: AttemptSelectionResolutionStatus = (
        "selected_none" if not decision.selected_attempts else "selected"
    )
    return AttemptSelectionResolution(
        status, selected, current_policy, derivation.candidates, True
    )


def _validate_decision_dependencies(
    workspace_root: Path,
    decision: AttemptSelectionDecision,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    require_current_policy: bool,
) -> AttemptCandidateDerivation:
    from meridian.projection_cache import AuthorizedProjectionSnapshot

    candidate = validate_attempt_selection_decision(decision)
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise AttemptSelectionDependencyError(
            "Attempt-selection dependencies require an AuthorizedProjectionSnapshot."
        )
    stored_snapshot = authorized_snapshot.stored
    snapshot_ref = AttemptProjectionReference(
        work=stored_snapshot.snapshot.source.publication.work,
        publication_id=stored_snapshot.snapshot.source.publication.publication_id,
        cache_key=stored_snapshot.cache_key,
        snapshot_digest=stored_snapshot.snapshot_digest,
    )
    if snapshot_ref != candidate.source_snapshot:
        raise AttemptSelectionDependencyError(
            "Authorized projection snapshot does not match decision source_snapshot."
        )
    try:
        membership = load_grade_item_membership_revision(
            workspace_root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.membership_revision,
        )
        current_membership = load_current_grade_item_membership_decision(
            workspace_root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
        )
    except GradeItemMembershipStorageError as error:
        raise AttemptSelectionDependencyError(
            f"Exact Grade Item membership could not be validated: {error}"
        ) from error
    if (
        membership.decision_sha256 != candidate.membership_revision_sha256
        or membership.decision.decision != "included"
        or membership.decision.work_reference.work != candidate.work
    ):
        raise AttemptSelectionDependencyError(
            "Attempt-selection decision membership basis is invalid."
        )
    if (
        current_membership is None
        or current_membership.decision.membership_revision
        != candidate.membership_revision
        or current_membership.decision_sha256 != candidate.membership_revision_sha256
        or current_membership.decision.decision != "included"
    ):
        raise AttemptSelectionStorageConflictError(
            "Current Grade Item membership changed since attempt review."
        )
    policy = load_attempt_selection_policy_revision(
        workspace_root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.work,
        candidate.policy.policy_id,
        candidate.policy.policy_revision,
    )
    if policy.policy_sha256 != candidate.policy.policy_revision_sha256:
        raise AttemptSelectionDependencyError(
            "Attempt-selection policy digest does not match decision reference."
        )
    if require_current_policy:
        current_policy = load_current_attempt_selection_policy(
            workspace_root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.work,
            candidate.policy.policy_id,
        )
        if (
            current_policy is None
            or current_policy.policy_sha256 != policy.policy_sha256
        ):
            raise AttemptSelectionStorageConflictError(
                "Current attempt-selection policy changed since decision review."
            )
    if not selection_cardinality_allows(
        policy.policy, len(candidate.selected_attempts)
    ):
        raise AttemptSelectionDependencyError(
            "Selected attempt count violates the exact policy cardinality."
        )
    derivation = derive_attempt_candidates(
        workspace_root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.student_id,
        authorized_snapshot,
    )
    if derivation.status != "applicable":
        raise AttemptSelectionDependencyError(
            f"Attempt selection is not currently applicable: {derivation.status}."
        )
    return derivation


def _attempt_from_item(
    item: EvidenceItem,
    source_snapshot: AttemptProjectionReference,
    student_id: str,
) -> AttemptObservationReference | None:
    target = item.target
    if target.target_kind == "attempt":
        attempt_target = AttemptTargetReference(
            target_kind="attempt",
            target_id=target.target_id,
            owning_system=target.owning_system,
            contract_version=target.contract_version,
        )
    elif (
        target.parent_target is not None
        and target.parent_target.target_kind == "attempt"
    ):
        parent = target.parent_target
        attempt_target = AttemptTargetReference(
            target_kind="attempt",
            target_id=parent.target_id,
            owning_system=parent.owning_system,
            contract_version=parent.contract_version,
        )
    else:
        return None
    references = tuple(
        ref for ref in item.provenance.native.references if ref.kind == "attempt"
    )
    if len(references) != 1:
        return None
    native_ref = references[0]
    native = AttemptNativeIdentity(
        identifier=native_ref.identifier,
        sequence=native_ref.sequence,
    )
    return AttemptObservationReference(
        source_snapshot=source_snapshot,
        student_id=student_id,
        target=attempt_target,
        native=native,
    )


def _attempt_sort_key(value: AttemptObservationReference) -> tuple[object, ...]:
    sequence = value.native.sequence
    return (
        sequence is None,
        0 if sequence is None else sequence,
        "" if value.native.identifier is None else value.native.identifier,
        "" if value.target.target_id is None else value.target.target_id,
        "" if value.target.owning_system is None else value.target.owning_system,
        "" if value.target.contract_version is None else value.target.contract_version,
    )


def _require_membership_history(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> None:
    relation = grade_item_membership_directory(root, class_id, grade_item_id, work)
    if not relation.exists():
        raise AttemptSelectionStorageNotFoundError(
            "Grade Item membership must exist before attempt-selection policy."
        )
    _validate_existing_directory_chain(root, relation)
    try:
        from meridian.grade_item_membership_storage import (
            list_grade_item_membership_revisions,
        )

        revisions = list_grade_item_membership_revisions(
            root, class_id, grade_item_id, work
        )
    except GradeItemMembershipStorageError as error:
        raise AttemptSelectionStorageIntegrityError(
            f"Grade Item membership history could not be validated: {error}"
        ) from error
    if not revisions:
        raise AttemptSelectionStorageIntegrityError(
            "Grade Item membership exists without immutable history."
        )


def _policy_pointer(stored: StoredAttemptSelectionPolicy) -> dict[str, object]:
    value = stored.policy
    return {
        "schema_version": ATTEMPT_SELECTION_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": ATTEMPT_SELECTION_POLICY_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "module_id": value.work.module_id,
        "work_id": value.work.work_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": stored.policy_sha256,
    }


def _decision_pointer(stored: StoredAttemptSelectionDecision) -> dict[str, object]:
    value = stored.decision
    return {
        "schema_version": ATTEMPT_SELECTION_DECISION_CURRENT_SCHEMA_VERSION,
        "record_type": ATTEMPT_SELECTION_DECISION_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "module_id": value.work.module_id,
        "work_id": value.work.work_id,
        "subject_key": attempt_subject_key(
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
    _validate_attempt_selection_collections(root, class_id, grade_item_id, work)
    path = attempt_selection_policy_current_path(
        root, class_id, grade_item_id, work, policy_id
    )
    if not path.exists():
        if missing_ok:
            return None
        raise AttemptSelectionStorageNotFoundError(
            "Attempt-selection policy has no current pointer."
        )
    data = _read_pointer(path, root, _POLICY_POINTER_KEYS)
    expected = {
        "schema_version": ATTEMPT_SELECTION_POLICY_CURRENT_SCHEMA_VERSION,
        "record_type": ATTEMPT_SELECTION_POLICY_CURRENT_RECORD_TYPE,
        "class_id": _identifier(class_id, "class_id"),
        "grade_item_id": _identifier(grade_item_id, "grade_item_id"),
        "module_id": _work(work).module_id,
        "work_id": _work(work).work_id,
        "policy_id": _identifier(policy_id, "policy_id"),
    }
    for key, value in expected.items():
        if data[key] != value:
            raise AttemptSelectionStorageIntegrityError(
                "Policy current pointer identity mismatch."
            )
    _positive_int(data["policy_revision"], "policy_revision")
    _sha256(data["policy_sha256"], "policy_sha256")
    return data


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
    _validate_attempt_selection_collections(root, class_id, grade_item_id, work)
    path = attempt_selection_decision_current_path(
        root, class_id, grade_item_id, work, student_id
    )
    if not path.exists():
        if missing_ok:
            return None
        raise AttemptSelectionStorageNotFoundError(
            "Attempt-selection decision has no current pointer."
        )
    data = _read_pointer(path, root, _DECISION_POINTER_KEYS)
    validated_work = _work(work)
    expected = {
        "schema_version": ATTEMPT_SELECTION_DECISION_CURRENT_SCHEMA_VERSION,
        "record_type": ATTEMPT_SELECTION_DECISION_CURRENT_RECORD_TYPE,
        "class_id": _identifier(class_id, "class_id"),
        "grade_item_id": _identifier(grade_item_id, "grade_item_id"),
        "module_id": validated_work.module_id,
        "work_id": validated_work.work_id,
        "subject_key": attempt_subject_key(
            class_id, grade_item_id, validated_work, student_id
        ),
    }
    for key, value in expected.items():
        if data[key] != value:
            raise AttemptSelectionStorageIntegrityError(
                "Decision current pointer identity mismatch."
            )
    _positive_int(data["decision_revision"], "decision_revision")
    _sha256(data["decision_sha256"], "decision_sha256")
    return data


def _read_pointer(path: Path, root: Path, keys: frozenset[str]) -> dict[str, object]:
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path, DEFAULT_MAXIMUM_ATTEMPT_SELECTION_POINTER_BYTES
    )
    try:
        decoded = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        AttemptSelectionStorageIntegrityError,
    ) as error:
        if isinstance(error, AttemptSelectionStorageIntegrityError):
            raise
        raise AttemptSelectionStorageIntegrityError(
            "Attempt-selection pointer is invalid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != keys:
        raise AttemptSelectionStorageIntegrityError(
            "Attempt-selection pointer does not use exact schema."
        )
    if _canonical_json_bytes(decoded) != content:
        raise AttemptSelectionStorageIntegrityError(
            "Attempt-selection pointer is not canonically encoded."
        )
    return cast(dict[str, object], decoded)


def _validate_attempt_selection_collections(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> None:
    """Fail closed on unexpected/symlinked #30 collection entries."""
    base = attempt_selection_directory(root, class_id, grade_item_id, work)
    if not base.exists():
        return
    _validate_existing_directory_chain(root, base)
    try:
        entries = tuple(base.iterdir())
    except OSError as error:
        raise AttemptSelectionStorageReadError(
            "Could not inspect attempt-selection collection root."
        ) from error
    allowed = {"policies", "students"}
    for entry in entries:
        if entry.name not in allowed:
            raise AttemptSelectionStorageIntegrityError(
                "Attempt-selection collection root has unexpected entry."
            )
        if entry.is_symlink() or not entry.is_dir():
            raise AttemptSelectionStorageIntegrityError(
                "Attempt-selection collection children must be real directories."
            )

    policies = base / "policies"
    if policies.exists():
        try:
            policy_entries = tuple(policies.iterdir())
        except OSError as error:
            raise AttemptSelectionStorageReadError(
                "Could not inspect attempt-selection policy collection."
            ) from error
        for entry in policy_entries:
            if entry.is_symlink() or not entry.is_dir():
                raise AttemptSelectionStorageIntegrityError(
                    "Attempt-selection policy collection contains a "
                    "non-directory entry."
                )
            try:
                validate_identifier(entry.name, "persisted policy_id")
            except IdentifierValidationError as error:
                raise AttemptSelectionStorageIntegrityError(
                    "Attempt-selection policy collection contains an invalid policy ID."
                ) from error

    students = base / "students"
    if students.exists():
        try:
            student_entries = tuple(students.iterdir())
        except OSError as error:
            raise AttemptSelectionStorageReadError(
                "Could not inspect attempt-selection student collection."
            ) from error
        for entry in student_entries:
            if entry.is_symlink() or not entry.is_dir():
                raise AttemptSelectionStorageIntegrityError(
                    "Attempt-selection student collection contains a "
                    "non-directory entry."
                )
            if _SHA256.fullmatch(entry.name) is None:
                raise AttemptSelectionStorageIntegrityError(
                    "Attempt-selection student collection contains an invalid "
                    "subject key."
                )


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
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise AttemptSelectionStorageReadError(
            "Could not enumerate attempt-selection revisions."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise AttemptSelectionStorageIntegrityError(
                "Revision storage contains nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match:
            jsons.add(int(json_match.group(1)))
        elif digest_match:
            digests.add(int(digest_match.group(1)))
        else:
            raise AttemptSelectionStorageIntegrityError(
                "Revision storage contains unexpected file."
            )
    if jsons != digests:
        raise AttemptSelectionStorageIntegrityError(
            "Revision JSON and digest sidecars are incomplete."
        )
    revisions = tuple(sorted(jsons))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise AttemptSelectionStorageIntegrityError(
            "Revision history is not contiguous from 1."
        )
    previous: _HistoryT | None = None
    for number in revisions:
        current = loader(number)
        if previous is not None:
            try:
                transition(previous, current)
            except AttemptSelectionValidationError as error:
                raise AttemptSelectionStorageIntegrityError(
                    f"Attempt-selection revision history is invalid: {error}"
                ) from error
        previous = current
    return revisions


def _validate_history_root(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise AttemptSelectionStorageIntegrityError(
            "Attempt-selection history root is unsafe."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise AttemptSelectionStorageReadError(
            "Could not inspect attempt-selection history root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise AttemptSelectionStorageIntegrityError(
                "Attempt-selection history root has unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise AttemptSelectionStorageIntegrityError(
                    "Revisions entry must be a real directory."
                )
        else:
            if entry.is_symlink() or not entry.is_file():
                raise AttemptSelectionStorageIntegrityError(
                    "Pointer/lock entry must be regular file."
                )


def _read_revision_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(path, maximum)
    digest_content = _read_bounded_regular_file(
        Path(str(path) + ".sha256"), DEFAULT_MAXIMUM_ATTEMPT_SELECTION_DIGEST_BYTES
    )
    digest = _parse_digest(digest_content)
    if hashlib.sha256(content).hexdigest() != digest:
        raise AttemptSelectionStorageIntegrityError(
            "Revision digest does not match exact JSON bytes."
        )
    return content, digest


def _write_revision_pair(
    path: Path, digest_path: Path, content: bytes, digest: str
) -> None:
    try:
        with path.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        with digest_path.open("xb") as output:
            output.write((digest + "\n").encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise AttemptSelectionStorageConflictError(
            "Attempt-selection revision already exists."
        ) from error
    except OSError as error:
        try:
            if path.exists() and not digest_path.exists():
                path.unlink()
        except OSError:
            pass
        raise AttemptSelectionStorageWriteError(
            "Could not persist attempt-selection revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _ensure_directory_chain(root, path.parent)
    try:
        handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, path)
            _fsync_directory(path.parent)
        finally:
            if temp.exists():
                temp.unlink()
    except OSError as error:
        raise AttemptSelectionStorageWriteError(
            "Could not atomically publish current pointer."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian attempt-selection write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise AttemptSelectionStorageLockError(
            "Attempt-selection relationship is locked."
        ) from error
    except OSError as error:
        raise AttemptSelectionStorageWriteError(
            "Attempt-selection lock could not be created."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise AttemptSelectionStorageWriteError(
            "Attempt-selection lock cleanup failed."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    if current.exists() and (current.is_symlink() or not current.is_dir()):
        raise AttemptSelectionStorageIntegrityError("Workspace root is unsafe.")
    if not current.exists():
        current.mkdir(parents=True)
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise AttemptSelectionStorageIntegrityError(
                    "Directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise AttemptSelectionStorageWriteError(
                    "Could not create attempt-selection directory."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    if not current.exists() or current.is_symlink() or not current.is_dir():
        raise AttemptSelectionStorageIntegrityError(
            "Workspace root is missing or unsafe."
        )
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise AttemptSelectionStorageNotFoundError(
                "Attempt-selection directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise AttemptSelectionStorageIntegrityError(
                "Attempt-selection directory chain is unsafe."
            )


def _read_bounded_regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink():
        raise AttemptSelectionStorageIntegrityError(
            "Attempt-selection file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise AttemptSelectionStorageIntegrityError(
                    "Attempt-selection path must be a regular file."
                )
            data = source.read(maximum + 1)
    except FileNotFoundError as error:
        raise AttemptSelectionStorageNotFoundError(
            "Attempt-selection file does not exist."
        ) from error
    except OSError as error:
        raise AttemptSelectionStorageReadError(
            "Could not read attempt-selection file."
        ) from error
    if len(data) > maximum:
        raise AttemptSelectionStorageTooLargeError(
            "Attempt-selection file exceeds byte limit."
        )
    return data


def _parse_digest(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise AttemptSelectionStorageIntegrityError(
            "Digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise AttemptSelectionStorageIntegrityError(
            "Digest sidecar is not canonical LF text."
        )
    return _sha256(text[:-1], "digest")


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
        raise AttemptSelectionStorageValidationError(
            "Pointer cannot be represented as JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AttemptSelectionStorageIntegrityError(
                "Duplicate JSON pointer key is invalid."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise AttemptSelectionStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = path.resolve()
    return path


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise AttemptSelectionStorageValidationError(
            "work must be a Core ModuleWorkRef."
        )
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise AttemptSelectionStorageValidationError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AttemptSelectionStorageValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AttemptSelectionStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AttemptSelectionStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AttemptSelectionStorageValidationError(
            f"{field_name} must contain 64 lowercase hexadecimal characters."
        )
    return value



def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise AttemptSelectionStorageValidationError(
            "Attempt-selection path escapes workspace root."
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
    finally:
        os.close(descriptor)
