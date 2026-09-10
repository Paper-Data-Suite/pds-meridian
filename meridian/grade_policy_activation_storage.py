"""Canonical storage for exact Academic-Period Grade-policy activation decisions."""

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
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
    GradePolicyActivationSerializationError,
    GradePolicyActivationValidationError,
    grade_policy_activation_decision_from_json_bytes,
    grade_policy_activation_decision_to_json_bytes,
    validate_grade_policy_activation_decision,
    validate_grade_policy_activation_transition,
)
from meridian.grade_policy_storage import (
    GradePolicyDependencyError,
    GradePolicyStorageError,
    StoredGradePolicyRevision,
    load_grade_policy_revision,
    validate_grade_policy_dependencies,
)

GRADE_POLICY_ACTIVATION_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GRADE_POLICY_ACTIVATION_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_grade_policy_activation_current"
)
DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_BYTES: Final[int] = 128 * 1024
DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_DIGEST_BYTES: Final[int] = 128

GradePolicyActivationWriteDisposition: TypeAlias = Literal["created", "existing"]
GradePolicyActivationSelectDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
]
GradePolicyActivationResolutionStatus: TypeAlias = Literal[
    "unconfigured", "deactivated", "activated"
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
        "target_period",
        "activation_revision",
        "activation_sha256",
    }
)


class GradePolicyActivationStorageError(RuntimeError):
    """Base error for Grade-policy activation persistence failures."""

    code: str = "grade_policy_activation.storage_error"


class GradePolicyActivationStorageValidationError(
    GradePolicyActivationStorageError, ValueError
):
    """Raised for invalid activation-storage API arguments."""

    code = "grade_policy_activation.storage_invalid"


class GradePolicyActivationStorageNotFoundError(GradePolicyActivationStorageError):
    """Raised when explicitly requested activation state is absent."""

    code = "grade_policy_activation.not_found"


class GradePolicyActivationStorageReadError(GradePolicyActivationStorageError):
    """Raised when activation state cannot be read safely."""

    code = "grade_policy_activation.read_failed"


class GradePolicyActivationStorageWriteError(GradePolicyActivationStorageError):
    """Raised when activation state cannot be written safely."""

    code = "grade_policy_activation.write_failed"


class GradePolicyActivationStorageConflictError(GradePolicyActivationStorageError):
    """Raised for stale writes or identity/content collisions."""

    code = "grade_policy_activation.conflict"


class GradePolicyActivationStorageLockError(
    GradePolicyActivationStorageConflictError
):
    """Raised when another writer owns one logical activation history."""

    code = "grade_policy_activation.locked"


class GradePolicyActivationStorageIntegrityError(GradePolicyActivationStorageError):
    """Raised when persisted activation state fails integrity validation."""

    code = "grade_policy_activation.integrity_failed"


class GradePolicyActivationStorageTooLargeError(
    GradePolicyActivationStorageReadError
):
    """Raised when persisted state exceeds configured read bounds."""

    code = "grade_policy_activation.too_large"


class GradePolicyActivationDependencyError(
    GradePolicyActivationStorageConflictError
):
    """Raised when exact Core/policy dependencies cannot be verified."""

    code = "grade_policy_activation.dependency_invalid"


@dataclass(frozen=True, slots=True)
class GradePolicyActivationDependencies:
    """Exact dependencies verified for one activation decision."""

    calendar: AcademicPeriodCalendar
    period: AcademicPeriod
    policy: StoredGradePolicyRevision | None

    def __post_init__(self) -> None:
        if self.policy is not None and not isinstance(
            self.policy, StoredGradePolicyRevision
        ):
            raise GradePolicyActivationStorageValidationError(
                "policy must be StoredGradePolicyRevision or None."
            )


@dataclass(frozen=True, slots=True)
class StoredGradePolicyActivationDecision:
    """One verified immutable activation decision and exact stored bytes."""

    decision: GradePolicyActivationDecision
    activation_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, GradePolicyActivationDecision):
            raise GradePolicyActivationStorageValidationError(
                "decision must be GradePolicyActivationDecision."
            )
        digest = _sha256(self.activation_sha256, "activation_sha256")
        if type(self.content) is not bytes:
            raise GradePolicyActivationStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GradePolicyActivationStorageValidationError(
                "activation_sha256 does not match exact stored bytes."
            )
        try:
            decoded = grade_policy_activation_decision_from_json_bytes(self.content)
        except (
            GradePolicyActivationSerializationError,
            GradePolicyActivationValidationError,
        ) as error:
            raise GradePolicyActivationStorageValidationError(
                "content is not a canonical activation decision."
            ) from error
        if decoded != self.decision:
            raise GradePolicyActivationStorageValidationError(
                "content does not decode to decision."
            )
        if (
            grade_policy_activation_decision_to_json_bytes(self.decision)
            != self.content
        ):
            raise GradePolicyActivationStorageValidationError(
                "content is not the canonical encoding of decision."
            )
        expected = grade_policy_activation_revision_relative_path(
            self.decision.class_id,
            self.decision.target_period,
            self.decision.activation_revision,
        )
        if self.relative_path != expected:
            raise GradePolicyActivationStorageValidationError(
                "relative_path is not the canonical activation revision location."
            )
        if self.path.name != f"{self.decision.activation_revision}.json":
            raise GradePolicyActivationStorageValidationError(
                "path filename does not match activation revision identity."
            )
        object.__setattr__(self, "activation_sha256", digest)

    @property
    def reference(self) -> GradePolicyActivationReference:
        return GradePolicyActivationReference(
            class_id=self.decision.class_id,
            school_year=self.decision.target_period.school_year,
            period_id=self.decision.target_period.period_id,
            activation_revision=self.decision.activation_revision,
            activation_sha256=self.activation_sha256,
        )


@dataclass(frozen=True, slots=True)
class GradePolicyActivationWriteResult:
    disposition: GradePolicyActivationWriteDisposition
    stored: StoredGradePolicyActivationDecision


@dataclass(frozen=True, slots=True)
class GradePolicyActivationCurrentSelection:
    """Explicit selector for one persisted activation decision."""

    schema_version: str
    record_type: str
    class_id: str
    target_period: AcademicPeriodRef
    activation_revision: int
    activation_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_POLICY_ACTIVATION_CURRENT_SCHEMA_VERSION:
            raise GradePolicyActivationStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != GRADE_POLICY_ACTIVATION_CURRENT_RECORD_TYPE:
            raise GradePolicyActivationStorageValidationError(
                'current record_type must be '
                '"meridian_grade_policy_activation_current".'
            )
        class_id = _identifier(self.class_id, "class_id")
        try:
            target = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise GradePolicyActivationStorageValidationError(
                f"target_period is invalid: {error}"
            ) from error
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "target_period", target)
        object.__setattr__(
            self,
            "activation_revision",
            _positive_int(self.activation_revision, "activation_revision"),
        )
        object.__setattr__(
            self,
            "activation_sha256",
            _sha256(self.activation_sha256, "activation_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GradePolicyActivationSelectionResult:
    disposition: GradePolicyActivationSelectDisposition
    selection: GradePolicyActivationCurrentSelection
    stored: StoredGradePolicyActivationDecision


@dataclass(frozen=True, slots=True)
class GradePolicyActivationResolution:
    """Resolved current activation state without fallback or inheritance."""

    status: GradePolicyActivationResolutionStatus
    activation: StoredGradePolicyActivationDecision | None
    policy_reference: GradePolicyReference | None

    def __post_init__(self) -> None:
        if self.status == "unconfigured":
            if self.activation is not None or self.policy_reference is not None:
                raise GradePolicyActivationStorageValidationError(
                    "unconfigured resolution must not carry activation or policy."
                )
        elif self.status == "deactivated":
            if self.activation is None or self.policy_reference is not None:
                raise GradePolicyActivationStorageValidationError(
                    "deactivated resolution requires activation and no policy."
                )
            if self.activation.decision.decision != "deactivate":
                raise GradePolicyActivationStorageValidationError(
                    "deactivated resolution must carry a deactivate decision."
                )
        elif self.status == "activated":
            if self.activation is None or self.policy_reference is None:
                raise GradePolicyActivationStorageValidationError(
                    "activated resolution requires activation and policy reference."
                )
            if self.activation.decision.decision != "activate":
                raise GradePolicyActivationStorageValidationError(
                    "activated resolution must carry an activate decision."
                )
            if self.activation.decision.policy_reference != self.policy_reference:
                raise GradePolicyActivationStorageValidationError(
                    "resolution policy_reference must match activation decision."
                )
        else:
            raise GradePolicyActivationStorageValidationError(
                "resolution status is invalid."
            )


def grade_policy_activations_directory(
    workspace_root: str | Path, class_id: str
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = (
        class_module_dir(root, class_value, "meridian")
        / "grade_policy_activations"
    )
    _require_containment(root, path)
    return path


def grade_policy_activation_directory(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> Path:
    period = _period_ref(target_period)
    return (
        grade_policy_activations_directory(workspace_root, class_id)
        / period.school_year
        / period.period_id
    )


def grade_policy_activation_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> Path:
    return grade_policy_activation_directory(
        workspace_root, class_id, target_period
    ) / "revisions"


def grade_policy_activation_revision_path(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
    activation_revision: int,
) -> Path:
    revision = _positive_int(activation_revision, "activation_revision")
    return grade_policy_activation_revisions_directory(
        workspace_root, class_id, target_period
    ) / f"{revision}.json"


def grade_policy_activation_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
    activation_revision: int,
) -> Path:
    return Path(
        str(
            grade_policy_activation_revision_path(
                workspace_root,
                class_id,
                target_period,
                activation_revision,
            )
        )
        + ".sha256"
    )


def grade_policy_activation_current_path(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> Path:
    return grade_policy_activation_directory(
        workspace_root, class_id, target_period
    ) / "current.json"


def grade_policy_activation_revision_relative_path(
    class_id: str,
    target_period: AcademicPeriodRef,
    activation_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(target_period)
    revision = _positive_int(activation_revision, "activation_revision")
    return (
        f"classes/{class_value}/modules/meridian/grade_policy_activations/"
        f"{period.school_year}/{period.period_id}/revisions/{revision}.json"
    )


def validate_grade_policy_activation_dependencies(
    workspace_root: str | Path,
    decision: GradePolicyActivationDecision,
) -> GradePolicyActivationDependencies:
    """Verify exact Core period/calendar and exact Grade-policy dependencies."""

    candidate = validate_grade_policy_activation_decision(decision)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)

    try:
        calendar = load_academic_period_calendar_revision(
            root,
            candidate.target_period.school_year,
            candidate.calendar_revision,
        )
        period = get_academic_period(calendar, candidate.target_period.period_id)
    except (AcademicPeriodCalendarStorageError, AcademicPeriodLookupError) as error:
        raise GradePolicyActivationDependencyError(
            "Exact Academic Period/calendar revision is unavailable for activation."
        ) from error

    stored_policy: StoredGradePolicyRevision | None = None
    if candidate.decision == "activate":
        reference = candidate.policy_reference
        if reference is None:
            raise GradePolicyActivationDependencyError(
                "Activate decision is missing its exact Grade-policy reference."
            )
        try:
            stored_policy = load_grade_policy_revision(
                root,
                reference.class_id,
                reference.policy_id,
                reference.policy_revision,
            )
        except GradePolicyStorageError as error:
            raise GradePolicyActivationDependencyError(
                "Exact Grade-policy revision is unavailable for activation."
            ) from error
        if stored_policy.policy_sha256 != reference.policy_sha256:
            raise GradePolicyActivationDependencyError(
                "Exact Grade-policy digest does not match activation provenance."
            )
        if stored_policy.policy.class_id != candidate.class_id:
            raise GradePolicyActivationDependencyError(
                "Activated Grade policy belongs to a different class."
            )
        try:
            validate_grade_policy_dependencies(root, stored_policy.policy)
        except GradePolicyDependencyError as error:
            raise GradePolicyActivationDependencyError(
                "Activated Grade-policy dependencies are not currently verifiable."
            ) from error

    return GradePolicyActivationDependencies(
        calendar=calendar,
        period=period,
        policy=stored_policy,
    )


def write_grade_policy_activation_revision(
    workspace_root: str | Path,
    decision: GradePolicyActivationDecision,
) -> GradePolicyActivationWriteResult:
    """Persist one immutable activation revision without selecting it."""

    candidate = validate_grade_policy_activation_decision(decision)
    root = _root(workspace_root)
    validate_grade_policy_activation_dependencies(root, candidate)

    relation = grade_policy_activation_directory(
        root, candidate.class_id, candidate.target_period
    )
    revisions_dir = relation / "revisions"
    _ensure_directory_chain(root, revisions_dir)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_activation_directory(relation)
        content = grade_policy_activation_decision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_BYTES:
            raise GradePolicyActivationStorageWriteError(
                "Activation decision exceeds the canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()
        target = grade_policy_activation_revision_path(
            root,
            candidate.class_id,
            candidate.target_period,
            candidate.activation_revision,
        )
        digest_target = grade_policy_activation_revision_digest_path(
            root,
            candidate.class_id,
            candidate.target_period,
            candidate.activation_revision,
        )
        if target.exists() or digest_target.exists():
            try:
                stored = load_grade_policy_activation_revision(
                    root,
                    candidate.class_id,
                    candidate.target_period,
                    candidate.activation_revision,
                )
            except GradePolicyActivationStorageError as error:
                raise GradePolicyActivationStorageIntegrityError(
                    "Existing activation revision identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.activation_sha256 != digest:
                raise GradePolicyActivationStorageConflictError(
                    "Activation revision identity already exists with "
                    "different content."
                )
            return GradePolicyActivationWriteResult("existing", stored)

        history = list_grade_policy_activation_revisions(
            root, candidate.class_id, candidate.target_period
        )
        if not history:
            if candidate.activation_revision != 1:
                raise GradePolicyActivationStorageConflictError(
                    "Initial activation revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.activation_revision != expected:
                raise GradePolicyActivationStorageConflictError(
                    "Activation revision must be exactly one greater than history."
                )
            previous = load_grade_policy_activation_revision(
                root,
                candidate.class_id,
                candidate.target_period,
                history[-1],
            ).decision
            try:
                validate_grade_policy_activation_transition(previous, candidate)
            except GradePolicyActivationValidationError as error:
                raise GradePolicyActivationStorageConflictError(str(error)) from error

        _write_revision_pair(target, digest_target, content, digest)
        stored = load_grade_policy_activation_revision(
            root,
            candidate.class_id,
            candidate.target_period,
            candidate.activation_revision,
        )
        if stored.content != content or stored.activation_sha256 != digest:
            raise GradePolicyActivationStorageIntegrityError(
                "Persisted activation revision differs from candidate bytes."
            )
        return GradePolicyActivationWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_grade_policy_activation_revision(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
    activation_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_BYTES,
) -> StoredGradePolicyActivationDecision:
    """Load and verify one exact immutable activation revision."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(target_period)
    revision = _positive_int(activation_revision, "activation_revision")
    path = grade_policy_activation_revision_path(
        root, class_value, period, revision
    )
    digest_path = grade_policy_activation_revision_digest_path(
        root, class_value, period, revision
    )
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path,
        maximum_revision_bytes,
        missing_message="Grade-policy activation revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_DIGEST_BYTES,
        missing_message="Grade-policy activation digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation revision digest does not match exact JSON bytes."
        )
    try:
        decision = grade_policy_activation_decision_from_json_bytes(content)
    except (
        GradePolicyActivationSerializationError,
        GradePolicyActivationValidationError,
    ) as error:
        raise GradePolicyActivationStorageIntegrityError(
            f"Activation revision is invalid or noncanonical: {error}"
        ) from error
    if decision.class_id != class_value or decision.target_period != period:
        raise GradePolicyActivationStorageIntegrityError(
            "Persisted activation identity does not match canonical path."
        )
    if decision.activation_revision != revision:
        raise GradePolicyActivationStorageIntegrityError(
            "Persisted activation revision does not match canonical path."
        )
    return StoredGradePolicyActivationDecision(
        decision=decision,
        activation_sha256=actual_digest,
        path=path,
        relative_path=grade_policy_activation_revision_relative_path(
            class_value, period, revision
        ),
        content=content,
    )


def list_grade_policy_activation_revisions(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> tuple[int, ...]:
    """List and verify contiguous immutable activation history."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(target_period)
    relation = grade_policy_activation_directory(root, class_value, period)
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_activation_directory(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise GradePolicyActivationStorageReadError(
            "Could not enumerate activation revision storage."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise GradePolicyActivationStorageIntegrityError(
                "Activation revision storage contains a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise GradePolicyActivationStorageIntegrityError(
                "Activation revision storage contains an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GradePolicyActivationStorageIntegrityError(
            "Activation history is not contiguous from revision 1."
        )
    previous: GradePolicyActivationDecision | None = None
    for revision in revisions:
        stored = load_grade_policy_activation_revision(
            root, class_value, period, revision
        )
        if previous is not None:
            try:
                validate_grade_policy_activation_transition(
                    previous, stored.decision
                )
            except GradePolicyActivationValidationError as error:
                raise GradePolicyActivationStorageIntegrityError(
                    f"Activation history is invalid: {error}"
                ) from error
        previous = stored.decision
    return revisions


def get_current_grade_policy_activation_revision(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> int | None:
    selection = _load_current_selection(
        workspace_root, class_id, target_period, missing_ok=True
    )
    return (
        selection.activation_revision
        if selection is not None
        else None
    )


def load_current_grade_policy_activation(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> StoredGradePolicyActivationDecision | None:
    selection = _load_current_selection(
        workspace_root, class_id, target_period, missing_ok=True
    )
    if selection is None:
        return None
    stored = load_grade_policy_activation_revision(
        workspace_root,
        selection.class_id,
        selection.target_period,
        selection.activation_revision,
    )
    if stored.activation_sha256 != selection.activation_sha256:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current-pointer digest does not match selected revision."
        )
    return stored


def select_grade_policy_activation_revision(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
    activation_revision: int,
    *,
    expected_current_revision: int | None,
) -> GradePolicyActivationSelectionResult:
    """Explicitly select one persisted activation revision with CAS semantics."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(target_period)
    revision = _positive_int(activation_revision, "activation_revision")
    expected = (
        None
        if expected_current_revision is None
        else _positive_int(expected_current_revision, "expected_current_revision")
    )
    relation = grade_policy_activation_directory(root, class_value, period)
    _validate_existing_directory_chain(root, relation)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_activation_directory(relation)
        target = load_grade_policy_activation_revision(
            root, class_value, period, revision
        )
        validate_grade_policy_activation_dependencies(root, target.decision)
        current = _load_current_selection(
            root, class_value, period, missing_ok=True
        )
        current_revision = (
            current.activation_revision if current is not None else None
        )
        if current_revision != expected:
            raise GradePolicyActivationStorageConflictError(
                "Expected current activation revision does not match stored selection."
            )
        selection = GradePolicyActivationCurrentSelection(
            schema_version=GRADE_POLICY_ACTIVATION_CURRENT_SCHEMA_VERSION,
            record_type=GRADE_POLICY_ACTIVATION_CURRENT_RECORD_TYPE,
            class_id=class_value,
            target_period=period,
            activation_revision=revision,
            activation_sha256=target.activation_sha256,
        )
        if current == selection:
            return GradePolicyActivationSelectionResult(
                "existing", selection, target
            )
        _publish_current_selection(root, selection)
        verified = _load_current_selection(
            root, class_value, period, missing_ok=False
        )
        if verified != selection:
            raise GradePolicyActivationStorageIntegrityError(
                "Published activation selection could not be verified."
            )
        disposition: GradePolicyActivationSelectDisposition = (
            "created" if current is None else "updated"
        )
        return GradePolicyActivationSelectionResult(
            disposition, selection, target
        )
    finally:
        _remove_lock(lock)


def resolve_grade_policy_activation(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
) -> GradePolicyActivationResolution:
    """Resolve exactly one period's explicit activation without inheritance."""

    stored = load_current_grade_policy_activation(
        workspace_root, class_id, target_period
    )
    if stored is None:
        return GradePolicyActivationResolution("unconfigured", None, None)
    if stored.decision.decision == "deactivate":
        validate_grade_policy_activation_dependencies(
            workspace_root, stored.decision
        )
        return GradePolicyActivationResolution("deactivated", stored, None)

    dependencies = validate_grade_policy_activation_dependencies(
        workspace_root, stored.decision
    )
    if dependencies.policy is None or stored.decision.policy_reference is None:
        raise GradePolicyActivationStorageIntegrityError(
            "Activated state does not resolve an exact Grade policy."
        )
    return GradePolicyActivationResolution(
        "activated",
        stored,
        stored.decision.policy_reference,
    )


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    target_period: AcademicPeriodRef,
    *,
    missing_ok: bool,
) -> GradePolicyActivationCurrentSelection | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    period = _period_ref(target_period)
    relation = grade_policy_activation_directory(root, class_value, period)
    if not relation.exists():
        if missing_ok:
            return None
        raise GradePolicyActivationStorageNotFoundError(
            "Grade-policy activation history does not exist."
        )
    _validate_existing_directory_chain(root, relation)
    _validate_activation_directory(relation)
    path = relation / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise GradePolicyActivationStorageNotFoundError(
            "Grade-policy activation has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_GRADE_POLICY_ACTIVATION_POINTER_BYTES,
        missing_message="Grade-policy activation current pointer does not exist.",
    )
    selection = _current_selection_from_json_bytes(content)
    if selection.class_id != class_value or selection.target_period != period:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current-pointer identity does not match canonical path."
        )
    return selection


def _current_selection_to_dict(
    value: GradePolicyActivationCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "activation_revision": value.activation_revision,
        "activation_sha256": value.activation_sha256,
    }


def _current_selection_to_json_bytes(
    value: GradePolicyActivationCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(_current_selection_to_dict(value))


def _current_selection_from_json_bytes(
    data: bytes,
) -> GradePolicyActivationCurrentSelection:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current pointer is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except GradePolicyActivationStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current pointer is not valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current pointer does not use the exact schema."
        )
    try:
        selection = GradePolicyActivationCurrentSelection(
            schema_version=_pointer_str(
                decoded["schema_version"], "schema_version"
            ),
            record_type=_pointer_str(decoded["record_type"], "record_type"),
            class_id=_pointer_str(decoded["class_id"], "class_id"),
            target_period=academic_period_ref_from_dict(decoded["target_period"]),
            activation_revision=_positive_int(
                decoded["activation_revision"], "activation_revision"
            ),
            activation_sha256=_pointer_str(
                decoded["activation_sha256"], "activation_sha256"
            ),
        )
    except (
        GradePolicyActivationStorageValidationError,
        AcademicPeriodValidationError,
    ) as error:
        raise GradePolicyActivationStorageIntegrityError(
            f"Activation current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current pointer is not canonically encoded."
        )
    return selection


def _publish_current_selection(
    workspace_root: str | Path,
    selection: GradePolicyActivationCurrentSelection,
) -> None:
    path = grade_policy_activation_current_path(
        workspace_root, selection.class_id, selection.target_period
    )
    if path.exists() and path.is_symlink():
        raise GradePolicyActivationStorageIntegrityError(
            "Activation current pointer must not be a symlink."
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
        raise GradePolicyActivationStorageWriteError(
            "Could not publish activation current selection."
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
        raise GradePolicyActivationStorageConflictError(
            "Activation revision identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise GradePolicyActivationStorageWriteError(
            "Could not persist activation revision and digest."
        ) from error


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise GradePolicyActivationStorageNotFoundError(
            "Core class workspace must exist before activation creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_activation_directory(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise GradePolicyActivationStorageIntegrityError(
            "Activation canonical root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise GradePolicyActivationStorageReadError(
            "Could not inspect activation canonical root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise GradePolicyActivationStorageIntegrityError(
                "Activation canonical root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GradePolicyActivationStorageIntegrityError(
                    "Activation revisions entry must be a real directory."
                )
        elif entry.name == "current.json":
            if entry.is_symlink() or not entry.is_file():
                raise GradePolicyActivationStorageIntegrityError(
                    "Activation current pointer must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise GradePolicyActivationStorageIntegrityError(
                "Activation lock entry must be a regular file."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise GradePolicyActivationStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise GradePolicyActivationStorageNotFoundError(
            "Workspace root does not exist."
        )
    if root.is_symlink() or not root.is_dir():
        raise GradePolicyActivationStorageIntegrityError(
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
                raise GradePolicyActivationStorageIntegrityError(
                    "Activation directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise GradePolicyActivationStorageWriteError(
                    "Could not create activation directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise GradePolicyActivationStorageNotFoundError(
                "Required activation directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise GradePolicyActivationStorageIntegrityError(
                "Activation directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GradePolicyActivationStorageValidationError(
            "Activation path escapes supplied workspace root."
        ) from error


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise GradePolicyActivationStorageIntegrityError(
            "Activation storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise GradePolicyActivationStorageIntegrityError(
                    "Activation storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except GradePolicyActivationStorageError:
        raise
    except FileNotFoundError as error:
        raise GradePolicyActivationStorageNotFoundError(
            missing_message
        ) from error
    except OSError as error:
        raise GradePolicyActivationStorageReadError(
            "Could not read activation storage file."
        ) from error
    if len(content) > limit:
        raise GradePolicyActivationStorageTooLargeError(
            "Activation storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "activation_sha256")
    except GradePolicyActivationStorageValidationError as error:
        raise GradePolicyActivationStorageIntegrityError(
            "Activation SHA-256 sidecar digest is invalid."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian grade policy activation write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise GradePolicyActivationStorageLockError(
            "An activation writer already owns this logical period."
        ) from error
    except OSError as error:
        raise GradePolicyActivationStorageWriteError(
            "Could not acquire activation write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise GradePolicyActivationStorageWriteError(
            "Could not remove activation write lock."
        ) from error


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except (FileNotFoundError, OSError):
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
        raise GradePolicyActivationStorageValidationError(
            "Activation selection cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradePolicyActivationStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise GradePolicyActivationStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyActivationStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradePolicyActivationStorageValidationError(str(error)) from error


def _period_ref(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise GradePolicyActivationStorageValidationError(
            "target_period must be an AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise GradePolicyActivationStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradePolicyActivationStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradePolicyActivationStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyActivationStorageIntegrityError(
            f"Activation pointer {field_name} must be a string."
        )
    return value
