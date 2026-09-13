"""Canonical immutable persistence for conventional Grade calculation results.

A stored conventional Grade result is advisory Meridian calculation history. It
is not an override, Grade preview, ReportingSnapshot, export, or official Grade.
Writing one immutable result revision never selects it as current.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import AcademicPeriodRef, validate_academic_period_ref
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.conventional_grade import (
    ConventionalGradeResultReference,
    ConventionalGradeResultSnapshot,
    ConventionalGradeSerializationError,
    ConventionalGradeValidationError,
    conventional_grade_result_snapshot_from_json_bytes,
    conventional_grade_result_snapshot_to_json_bytes,
    validate_conventional_grade_result_transition,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeAssemblyError,
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.grade_item_storage import GradeItemStorageError, load_grade_item_revision
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationStorageError,
    load_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    load_grade_policy_revision,
)

CONVENTIONAL_GRADE_RESULT_CURRENT_SCHEMA_VERSION: Final[str] = "1"
CONVENTIONAL_GRADE_RESULT_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_conventional_grade_result_current"
)
DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_RESULT_BYTES: Final[int] = 8 * 1024 * 1024
DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_DIGEST_BYTES: Final[int] = 128

ConventionalGradeResultWriteDisposition: TypeAlias = Literal["created", "existing"]
ConventionalGradeResultSelectDisposition: TypeAlias = Literal[
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
        "student_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "subject_key",
        "result_revision",
        "result_sha256",
    }
)


class ConventionalGradeStorageError(RuntimeError):
    """Base error for conventional Grade result persistence."""

    code: str = "conventional_grade.storage_error"


class ConventionalGradeStorageValidationError(
    ConventionalGradeStorageError,
    ValueError,
):
    code = "conventional_grade.storage_invalid"


class ConventionalGradeStorageNotFoundError(ConventionalGradeStorageError):
    code = "conventional_grade.not_found"


class ConventionalGradeStorageReadError(ConventionalGradeStorageError):
    code = "conventional_grade.read_failed"


class ConventionalGradeStorageWriteError(ConventionalGradeStorageError):
    code = "conventional_grade.write_failed"


class ConventionalGradeStorageConflictError(ConventionalGradeStorageError):
    code = "conventional_grade.conflict"


class ConventionalGradeStorageLockError(ConventionalGradeStorageConflictError):
    code = "conventional_grade.locked"


class ConventionalGradeStorageIntegrityError(ConventionalGradeStorageError):
    code = "conventional_grade.integrity"


class ConventionalGradeStorageTooLargeError(ConventionalGradeStorageReadError):
    code = "conventional_grade.too_large"


class ConventionalGradeResultDependencyError(
    ConventionalGradeStorageConflictError
):
    code = "conventional_grade.result_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredConventionalGradeResult:
    """One verified immutable conventional Grade result revision."""

    snapshot: ConventionalGradeResultSnapshot
    result_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ConventionalGradeResultSnapshot):
            raise ConventionalGradeStorageValidationError(
                "snapshot must be ConventionalGradeResultSnapshot."
            )
        digest = _sha256(self.result_sha256, "result_sha256")
        if type(self.content) is not bytes:
            raise ConventionalGradeStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ConventionalGradeStorageValidationError(
                "result_sha256 must match exact immutable content."
            )
        try:
            decoded = conventional_grade_result_snapshot_from_json_bytes(
                self.content
            )
        except (
            ConventionalGradeSerializationError,
            ConventionalGradeValidationError,
        ) as error:
            raise ConventionalGradeStorageValidationError(
                "content is not a canonical conventional Grade result."
            ) from error
        if decoded != self.snapshot:
            raise ConventionalGradeStorageValidationError(
                "content does not decode to snapshot."
            )
        expected = conventional_grade_result_revision_relative_path(
            self.snapshot.class_id,
            self.snapshot.student_id,
            self.snapshot.target_period,
            self.snapshot.calendar_revision,
            self.snapshot.result_revision,
        )
        if self.relative_path != expected:
            raise ConventionalGradeStorageValidationError(
                "relative_path is not the canonical result revision location."
            )
        if self.path.name != f"{self.snapshot.result_revision}.json":
            raise ConventionalGradeStorageValidationError(
                "path filename does not match result revision identity."
            )
        object.__setattr__(self, "result_sha256", digest)

    @property
    def reference(self) -> ConventionalGradeResultReference:
        value = self.snapshot
        return ConventionalGradeResultReference(
            class_id=value.class_id,
            student_id=value.student_id,
            school_year=value.target_period.school_year,
            period_id=value.target_period.period_id,
            calendar_revision=value.calendar_revision,
            result_revision=value.result_revision,
            result_sha256=self.result_sha256,
        )


@dataclass(frozen=True, slots=True)
class ConventionalGradeResultWriteResult:
    disposition: ConventionalGradeResultWriteDisposition
    stored: StoredConventionalGradeResult


@dataclass(frozen=True, slots=True)
class ConventionalGradeResultSelectionResult:
    disposition: ConventionalGradeResultSelectDisposition
    stored: StoredConventionalGradeResult


def conventional_grades_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "conventional_grades"
    _require_containment(root, path)
    return path


def conventional_grade_subject_key(
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    payload = {
        "class_id": class_value,
        "student_id": student,
        "target_period": {
            "school_year": period.school_year,
            "period_id": period.period_id,
        },
        "calendar_revision": calendar,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def conventional_grade_result_family_directory(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    subject_key = conventional_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    path = (
        conventional_grades_directory(root, class_value)
        / "periods"
        / period.school_year
        / period.period_id
        / "students"
        / subject_key
    )
    _require_containment(root, path)
    return path


def conventional_grade_result_revision_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
) -> Path:
    revision = _positive_int(result_revision, "result_revision")
    return (
        conventional_grade_result_family_directory(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
        )
        / "revisions"
        / f"{revision}.json"
    )


def conventional_grade_result_current_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> Path:
    return conventional_grade_result_family_directory(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
    ) / "current.json"


def conventional_grade_result_revision_relative_path(
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    revision = _positive_int(result_revision, "result_revision")
    subject_key = conventional_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    return (
        f"classes/{class_value}/modules/meridian/conventional_grades/"
        f"periods/{period.school_year}/{period.period_id}/students/"
        f"{subject_key}/revisions/{revision}.json"
    )


def write_conventional_grade_result_revision(
    workspace_root: str | Path,
    snapshot: ConventionalGradeResultSnapshot,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> ConventionalGradeResultWriteResult:
    """Persist one exact result revision without selecting it.

    New writes reassemble the same caller-bounded authorized evidence set before
    commit. Exact retries of an existing immutable revision remain idempotent.
    """

    if not isinstance(snapshot, ConventionalGradeResultSnapshot):
        raise ConventionalGradeStorageValidationError(
            "snapshot must be ConventionalGradeResultSnapshot."
        )
    try:
        content = conventional_grade_result_snapshot_to_json_bytes(snapshot)
    except (
        ConventionalGradeSerializationError,
        ConventionalGradeValidationError,
    ) as error:
        raise ConventionalGradeStorageValidationError(str(error)) from error
    if len(content) > DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_RESULT_BYTES:
        raise ConventionalGradeStorageWriteError(
            "Conventional Grade result exceeds the canonical byte limit."
        )

    root = _root(workspace_root)
    _require_existing_core_class(root, snapshot.class_id)
    family = conventional_grade_result_family_directory(
        root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    revisions = family / "revisions"
    _ensure_directory_chain(root, revisions)
    _validate_result_ancestor_shape(root, snapshot)
    target = conventional_grade_result_revision_path(
        root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
        snapshot.result_revision,
    )
    digest_target = Path(str(target) + ".sha256")
    digest = hashlib.sha256(content).hexdigest()

    if target.exists() or digest_target.exists():
        stored = _load_existing_for_replay(root, snapshot)
        if stored.content != content or stored.result_sha256 != digest:
            raise ConventionalGradeStorageConflictError(
                "Conventional Grade result revision already exists with "
                "different content."
            )
        return ConventionalGradeResultWriteResult("existing", stored)

    _refresh_assembly_or_conflict(root, snapshot, work_evidence)

    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_result_family_directory(family)
        if target.exists() or digest_target.exists():
            stored = _load_existing_for_replay(root, snapshot)
            if stored.content != content or stored.result_sha256 != digest:
                raise ConventionalGradeStorageConflictError(
                    "Conventional Grade result revision already exists with "
                    "different content."
                )
            return ConventionalGradeResultWriteResult("existing", stored)

        _refresh_assembly_or_conflict(root, snapshot, work_evidence)
        history = list_conventional_grade_result_revisions(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
        )
        if not history:
            if snapshot.result_revision != 1:
                raise ConventionalGradeStorageConflictError(
                    "Initial conventional Grade result revision must be 1."
                )
        else:
            if snapshot.result_revision != history[-1] + 1:
                raise ConventionalGradeStorageConflictError(
                    "Conventional Grade result revision must be contiguous."
                )
            previous = load_conventional_grade_result_revision(
                root,
                snapshot.class_id,
                snapshot.student_id,
                snapshot.target_period,
                snapshot.calendar_revision,
                history[-1],
            ).snapshot
            try:
                validate_conventional_grade_result_transition(previous, snapshot)
            except ConventionalGradeValidationError as error:
                raise ConventionalGradeStorageConflictError(str(error)) from error

        _write_revision_pair(target, digest_target, content, digest)
        stored = load_conventional_grade_result_revision(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            snapshot.result_revision,
        )
        if stored.content != content or stored.result_sha256 != digest:
            raise ConventionalGradeStorageIntegrityError(
                "Persisted conventional Grade result differs from candidate bytes."
            )
        return ConventionalGradeResultWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_conventional_grade_result_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
) -> StoredConventionalGradeResult:
    """Load one exact immutable result without consulting current selectors."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    revision = _positive_int(result_revision, "result_revision")
    family = conventional_grade_result_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    _validate_result_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    _validate_result_family_directory(family)
    path = conventional_grade_result_revision_path(
        root,
        class_value,
        student,
        period,
        calendar,
        revision,
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_RESULT_BYTES,
    )
    try:
        snapshot = conventional_grade_result_snapshot_from_json_bytes(content)
    except (
        ConventionalGradeSerializationError,
        ConventionalGradeValidationError,
    ) as error:
        raise ConventionalGradeStorageIntegrityError(
            f"Conventional Grade result is invalid or noncanonical: {error}"
        ) from error
    if (
        snapshot.class_id != class_value
        or snapshot.student_id != student
        or snapshot.target_period != period
        or snapshot.calendar_revision != calendar
        or snapshot.result_revision != revision
    ):
        raise ConventionalGradeStorageIntegrityError(
            "Persisted conventional Grade result identity does not match path."
        )
    expected_subject = conventional_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    if family.name != expected_subject:
        raise ConventionalGradeStorageIntegrityError(
            "Persisted student scope does not match hashed canonical path."
        )
    return StoredConventionalGradeResult(
        snapshot=snapshot,
        result_sha256=digest,
        path=path,
        relative_path=conventional_grade_result_revision_relative_path(
            class_value,
            student,
            period,
            calendar,
            revision,
        ),
        content=content,
    )


def list_conventional_grade_result_revisions(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> tuple[int, ...]:
    """Return verified contiguous immutable revisions for one result family."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = conventional_grade_result_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    if not family.exists():
        return ()
    _validate_result_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    _validate_result_family_directory(family)
    revisions_dir = family / "revisions"
    if not revisions_dir.exists():
        return ()
    json_revisions, digest_revisions = _revision_sets(revisions_dir)
    if json_revisions != digest_revisions:
        raise ConventionalGradeStorageIntegrityError(
            "Result JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise ConventionalGradeStorageIntegrityError(
            "Conventional Grade result history is not contiguous from revision 1."
        )
    previous: ConventionalGradeResultSnapshot | None = None
    for revision in revisions:
        stored = load_conventional_grade_result_revision(
            root,
            class_value,
            student,
            period,
            calendar,
            revision,
        )
        if previous is not None:
            try:
                validate_conventional_grade_result_transition(
                    previous,
                    stored.snapshot,
                )
            except ConventionalGradeValidationError as error:
                raise ConventionalGradeStorageIntegrityError(
                    f"Conventional Grade result history is invalid: {error}"
                ) from error
        previous = stored.snapshot
    return revisions


def get_current_conventional_grade_result_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> int | None:
    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        missing_ok=True,
    )
    return None if pointer is None else cast(int, pointer["result_revision"])


def load_current_conventional_grade_result(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> StoredConventionalGradeResult | None:
    pointer = _load_result_pointer(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        missing_ok=True,
    )
    if pointer is None:
        return None
    stored = load_conventional_grade_result_revision(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        cast(int, pointer["result_revision"]),
    )
    if stored.result_sha256 != pointer["result_sha256"]:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer digest does not match selected revision."
        )
    return stored


def select_conventional_grade_result_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
    *,
    expected_current_result_revision: int | None,
) -> ConventionalGradeResultSelectionResult:
    """Explicitly select one exact result revision using compare-and-swap."""

    root = _root(workspace_root)
    target = load_conventional_grade_result_revision(
        root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        result_revision,
    )
    _validate_historical_dependencies(root, target.snapshot)
    family = conventional_grade_result_family_directory(
        root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
    )
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_result_family_directory(family)
        _validate_historical_dependencies(root, target.snapshot)
        current = _load_result_pointer(
            root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            missing_ok=True,
        )
        current_revision = (
            None if current is None else cast(int, current["result_revision"])
        )
        if current_revision != expected_current_result_revision:
            raise ConventionalGradeStorageConflictError(
                "Expected current conventional Grade result revision does not "
                "match stored selection."
            )
        pointer = _result_pointer(target)
        if current == pointer:
            return ConventionalGradeResultSelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            conventional_grade_result_current_path(
                root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            ),
            _canonical_json_bytes(pointer),
        )
        verified = _load_result_pointer(
            root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            missing_ok=False,
        )
        if verified != pointer:
            raise ConventionalGradeStorageIntegrityError(
                "Published conventional Grade result selection was not verified."
            )
        disposition: ConventionalGradeResultSelectDisposition = (
            "created" if current is None else "updated"
        )
        return ConventionalGradeResultSelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def _refresh_assembly_or_conflict(
    root: Path,
    snapshot: ConventionalGradeResultSnapshot,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> None:
    try:
        refreshed = assemble_conventional_grade_calculation(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            work_evidence,
        )
    except ConventionalGradeAssemblyError as error:
        raise ConventionalGradeResultDependencyError(
            f"Exact calculation basis changed before result commit: {error}"
        ) from error
    if refreshed.inputs != snapshot.inputs or refreshed.outcome != snapshot.outcome:
        raise ConventionalGradeStorageConflictError(
            "Exact calculation inputs changed before result commit."
        )


def _validate_historical_dependencies(
    root: Path,
    snapshot: ConventionalGradeResultSnapshot,
) -> None:
    activation_ref = snapshot.activation_reference
    try:
        activation = load_grade_policy_activation_revision(
            root,
            snapshot.class_id,
            snapshot.target_period,
            activation_ref.activation_revision,
        )
    except GradePolicyActivationStorageError as error:
        raise ConventionalGradeResultDependencyError(
            "Exact activation revision is unavailable for result selection."
        ) from error
    if activation.activation_sha256 != activation_ref.activation_sha256:
        raise ConventionalGradeResultDependencyError(
            "Exact activation digest does not match result provenance."
        )
    if (
        activation.decision.decision != "activate"
        or activation.decision.calendar_revision != snapshot.calendar_revision
        or activation.decision.policy_reference != snapshot.policy_reference
    ):
        raise ConventionalGradeResultDependencyError(
            "Exact activation semantics do not match result provenance."
        )
    policy_ref = snapshot.policy_reference
    try:
        policy = load_grade_policy_revision(
            root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except GradePolicyStorageError as error:
        raise ConventionalGradeResultDependencyError(
            "Exact Grade-policy revision is unavailable for result selection."
        ) from error
    if policy.policy_sha256 != policy_ref.policy_sha256:
        raise ConventionalGradeResultDependencyError(
            "Exact Grade-policy digest does not match result provenance."
        )
    for participation in snapshot.inputs.configuration.items:
        item_ref = participation.grade_item
        try:
            grade_item = load_grade_item_revision(
                root,
                item_ref.class_id,
                item_ref.grade_item_id,
                item_ref.grade_item_revision,
            )
        except GradeItemStorageError as error:
            raise ConventionalGradeResultDependencyError(
                "Exact Grade Item revision is unavailable for result selection."
            ) from error
        if grade_item.revision_sha256 != item_ref.grade_item_revision_sha256:
            raise ConventionalGradeResultDependencyError(
                "Exact Grade Item digest does not match result provenance."
            )


def _result_pointer(stored: StoredConventionalGradeResult) -> dict[str, object]:
    value = stored.snapshot
    return {
        "schema_version": CONVENTIONAL_GRADE_RESULT_CURRENT_SCHEMA_VERSION,
        "record_type": CONVENTIONAL_GRADE_RESULT_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "student_id": value.student_id,
        "school_year": value.target_period.school_year,
        "period_id": value.target_period.period_id,
        "calendar_revision": value.calendar_revision,
        "subject_key": conventional_grade_subject_key(
            value.class_id,
            value.student_id,
            value.target_period,
            value.calendar_revision,
        ),
        "result_revision": value.result_revision,
        "result_sha256": stored.result_sha256,
    }


def _load_result_pointer(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    *,
    missing_ok: bool,
) -> dict[str, object] | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = conventional_grade_result_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    if not family.exists():
        if missing_ok:
            return None
        raise ConventionalGradeStorageNotFoundError(
            "Conventional Grade result family does not exist."
        )
    _validate_result_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    _validate_result_family_directory(family)
    path = family / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise ConventionalGradeStorageNotFoundError(
            "Conventional Grade result has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_POINTER_BYTES,
        missing_message="Conventional Grade result current pointer is absent.",
    )
    decoded = _decode_pointer(content)
    expected = {
        "class_id": class_value,
        "student_id": student,
        "school_year": period.school_year,
        "period_id": period.period_id,
        "calendar_revision": calendar,
        "subject_key": conventional_grade_subject_key(
            class_value,
            student,
            period,
            calendar,
        ),
    }
    for key, value in expected.items():
        if decoded[key] != value:
            raise ConventionalGradeStorageIntegrityError(
                "Current result pointer identity does not match canonical path."
            )
    return decoded


def _decode_pointer(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer must be valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except ConventionalGradeStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer must be valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer does not use the exact schema."
        )
    if decoded["schema_version"] != CONVENTIONAL_GRADE_RESULT_CURRENT_SCHEMA_VERSION:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer schema_version is unsupported."
        )
    if decoded["record_type"] != CONVENTIONAL_GRADE_RESULT_CURRENT_RECORD_TYPE:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer record_type is invalid."
        )
    for key in ("class_id", "student_id", "school_year", "period_id"):
        decoded[key] = _identifier(decoded[key], key)
    decoded["calendar_revision"] = _positive_int(
        decoded["calendar_revision"],
        "calendar_revision",
    )
    decoded["subject_key"] = _sha256(decoded["subject_key"], "subject_key")
    decoded["result_revision"] = _positive_int(
        decoded["result_revision"],
        "result_revision",
    )
    decoded["result_sha256"] = _sha256(
        decoded["result_sha256"],
        "result_sha256",
    )
    if _canonical_json_bytes(decoded) != data:
        raise ConventionalGradeStorageIntegrityError(
            "Current result pointer is not canonically encoded."
        )
    return cast(dict[str, object], decoded)


def _load_existing_for_replay(
    root: Path,
    snapshot: ConventionalGradeResultSnapshot,
) -> StoredConventionalGradeResult:
    try:
        return load_conventional_grade_result_revision(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            snapshot.result_revision,
        )
    except ConventionalGradeStorageError as error:
        raise ConventionalGradeStorageIntegrityError(
            "Existing conventional Grade result identity is incomplete or invalid."
        ) from error


def _validate_result_ancestor_shape(
    root: Path,
    snapshot: ConventionalGradeResultSnapshot,
) -> None:
    _validate_result_ancestor_shape_values(
        root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )


def _validate_result_ancestor_shape_values(
    root: Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> None:
    family = conventional_grade_result_family_directory(
        root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
    )
    _validate_existing_directory_chain(root, family)
    students = family.parent
    try:
        entries = tuple(students.iterdir())
    except OSError as error:
        raise ConventionalGradeStorageReadError(
            "Could not inspect conventional Grade student result collection."
        ) from error
    for entry in entries:
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or _SHA256.fullmatch(entry.name) is None
        ):
            raise ConventionalGradeStorageIntegrityError(
                "Student result collection contains an unexpected entry."
            )


def _validate_result_family_directory(family: Path) -> None:
    if not family.exists():
        raise ConventionalGradeStorageNotFoundError(
            "Conventional Grade result family does not exist."
        )
    if family.is_symlink() or not family.is_dir():
        raise ConventionalGradeStorageIntegrityError(
            "Conventional Grade result family is not a regular directory."
        )
    allowed = {"current.json", "revisions", ".write.lock"}
    try:
        entries = tuple(family.iterdir())
    except OSError as error:
        raise ConventionalGradeStorageReadError(
            "Could not inspect conventional Grade result family."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise ConventionalGradeStorageIntegrityError(
                "Conventional Grade result family contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise ConventionalGradeStorageIntegrityError(
                    "Result revisions entry must be a regular directory."
                )
        elif entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise ConventionalGradeStorageIntegrityError(
                    "Result write lock must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise ConventionalGradeStorageIntegrityError(
                "Current result pointer must be a regular file."
            )
    revisions = family / "revisions"
    if revisions.exists():
        _revision_sets(revisions)


def _revision_sets(revisions_dir: Path) -> tuple[set[int], set[int]]:
    if revisions_dir.is_symlink() or not revisions_dir.is_dir():
        raise ConventionalGradeStorageIntegrityError(
            "Result revisions path must be a regular directory."
        )
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise ConventionalGradeStorageReadError(
            "Could not inspect conventional Grade result revisions."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise ConventionalGradeStorageIntegrityError(
                "Result revisions contain a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise ConventionalGradeStorageIntegrityError(
                "Result revisions contain an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise ConventionalGradeStorageIntegrityError(
            "Result JSON and SHA-256 sidecars are incomplete."
        )
    return json_revisions, digest_revisions


def _read_revision_pair(
    root: Path,
    path: Path,
    maximum_bytes: int,
) -> tuple[bytes, str]:
    content = _read_bounded_regular_file(
        path,
        maximum_bytes,
        missing_message="Conventional Grade result revision does not exist.",
    )
    digest_data = _read_bounded_regular_file(
        Path(str(path) + ".sha256"),
        DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_DIGEST_BYTES,
        missing_message="Conventional Grade result digest does not exist.",
    )
    try:
        digest_text = digest_data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ConventionalGradeStorageIntegrityError(
            "Result digest sidecar must be ASCII."
        ) from error
    if (
        len(digest_text) != 65
        or not digest_text.endswith("\n")
        or digest_text.count("\n") != 1
        or _SHA256.fullmatch(digest_text[:-1]) is None
    ):
        raise ConventionalGradeStorageIntegrityError(
            "Result digest sidecar must contain exactly lowercase SHA-256 "
            "text and one trailing LF."
        )
    digest = digest_text[:-1]
    if hashlib.sha256(content).hexdigest() != digest:
        raise ConventionalGradeStorageIntegrityError(
            "Result digest does not match exact JSON bytes."
        )
    _require_containment(root, path)
    return content, digest


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    if not path.exists():
        raise ConventionalGradeStorageNotFoundError(missing_message)
    if path.is_symlink():
        raise ConventionalGradeStorageIntegrityError(
            "Canonical conventional Grade state must not be symlinked."
        )
    try:
        info = path.stat()
    except OSError as error:
        raise ConventionalGradeStorageReadError(
            "Could not stat conventional Grade state."
        ) from error
    if not stat.S_ISREG(info.st_mode):
        raise ConventionalGradeStorageIntegrityError(
            "Canonical conventional Grade state must be a regular file."
        )
    if info.st_size > maximum_bytes:
        raise ConventionalGradeStorageTooLargeError(
            "Conventional Grade state exceeds the configured read bound."
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise ConventionalGradeStorageReadError(
            "Could not read conventional Grade state."
        ) from error


def _write_revision_pair(
    target: Path,
    digest_target: Path,
    content: bytes,
    digest: str,
) -> None:
    if target.exists() or digest_target.exists():
        raise ConventionalGradeStorageConflictError(
            "Result revision identity already exists."
        )
    created_target = False
    created_digest = False
    try:
        with target.open("xb") as handle:
            created_target = True
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        with digest_target.open("x", encoding="ascii", newline="\n") as handle:
            created_digest = True
            handle.write(digest + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        if created_digest:
            digest_target.unlink(missing_ok=True)
        if created_target:
            target.unlink(missing_ok=True)
        raise ConventionalGradeStorageConflictError(
            "Concurrent writer created the result revision identity."
        ) from error
    except OSError as error:
        if created_digest:
            digest_target.unlink(missing_ok=True)
        if created_target:
            target.unlink(missing_ok=True)
        raise ConventionalGradeStorageWriteError(
            "Could not persist conventional Grade result revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _require_containment(root, path)
    _ensure_directory_chain(root, path.parent)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".current.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise ConventionalGradeStorageWriteError(
            "Could not atomically publish current result selection."
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise ConventionalGradeStorageIntegrityError(
            "Conventional Grade result lock path must not be a symlink."
        )
    if path.exists():
        raise ConventionalGradeStorageLockError(
            "Conventional Grade result history is locked by another writer."
        )
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as error:
        raise ConventionalGradeStorageLockError(
            "Conventional Grade result history is locked by another writer."
        ) from error
    except OSError as error:
        raise ConventionalGradeStorageWriteError(
            "Could not acquire conventional Grade result lock."
        ) from error
    os.close(descriptor)


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise ConventionalGradeStorageWriteError(
            "Could not release conventional Grade result lock."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise ConventionalGradeStorageValidationError(
            "Target path escapes workspace root."
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ConventionalGradeStorageIntegrityError(
                    "Canonical directory chain contains a non-directory or symlink."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ConventionalGradeStorageWriteError(
                    "Could not create conventional Grade storage directory."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if not target.exists():
        raise ConventionalGradeStorageNotFoundError(
            "Expected conventional Grade storage directory does not exist."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ConventionalGradeStorageIntegrityError(
                "Canonical directory chain contains a non-directory or symlink."
            )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, _identifier(class_id, "class_id"))
    _require_containment(root, path)
    if not path.exists() or path.is_symlink() or not path.is_dir():
        raise ConventionalGradeResultDependencyError(
            "Exact Core class directory is unavailable."
        )


def _root(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ConventionalGradeStorageValidationError(
            "workspace_root must identify an existing directory."
        ) from error
    if not resolved.is_dir():
        raise ConventionalGradeStorageValidationError(
            "workspace_root must identify a directory."
        )
    return resolved


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ConventionalGradeStorageValidationError(
            "Canonical conventional Grade path escapes workspace root."
        ) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConventionalGradeStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ConventionalGradeStorageValidationError(str(error)) from error


def _period(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise ConventionalGradeStorageValidationError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except ValueError as error:
        raise ConventionalGradeStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConventionalGradeStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ConventionalGradeStorageValidationError(
            f"{field_name} must be lowercase SHA-256 text."
        )
    return value


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
        raise ConventionalGradeStorageValidationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConventionalGradeStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ConventionalGradeStorageIntegrityError(
        f"Nonfinite JSON constant is invalid: {value}."
    )
