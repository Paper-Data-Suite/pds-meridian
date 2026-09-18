"""Canonical immutable persistence for teacher final-Grade override decisions.

Storage is intentionally narrower than override authoring/applicability policy. It
persists structurally valid immutable decisions, validates contiguous history and
withdrawal provenance inside that history, and manages one explicit digest-bound
current selector. Exact source Grade-result currentness is verified by the
higher-level authoring/applicability service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.grade_policy import GradeCalculationFamily
from meridian.teacher_grade_override import (
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    TeacherGradeOverrideSerializationError,
    TeacherGradeOverrideValidationError,
    teacher_grade_override_decision_from_json_bytes,
    teacher_grade_override_decision_to_json_bytes,
    validate_teacher_grade_override_decision,
    validate_teacher_grade_override_transition,
)

TEACHER_GRADE_OVERRIDE_CURRENT_SCHEMA_VERSION: Final[str] = "1"
TEACHER_GRADE_OVERRIDE_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_teacher_grade_override_current"
)
DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_BYTES: Final[int] = 256 * 1024
DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_DIGEST_BYTES: Final[int] = 128

TeacherGradeOverrideWriteDisposition: TypeAlias = Literal["created", "existing"]
TeacherGradeOverrideSelectDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
]

_FAMILIES: Final[frozenset[str]] = frozenset(
    {"conventional", "standards_based", "hybrid"}
)
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
        "calculation_family",
        "subject_key",
        "override_revision",
        "override_sha256",
    }
)


class TeacherGradeOverrideStorageError(RuntimeError):
    """Base error for teacher Grade override persistence failures."""

    code: str = "teacher_grade_override.storage_error"


class TeacherGradeOverrideStorageValidationError(
    TeacherGradeOverrideStorageError, ValueError
):
    code = "teacher_grade_override.storage_invalid"


class TeacherGradeOverrideStorageNotFoundError(TeacherGradeOverrideStorageError):
    code = "teacher_grade_override.not_found"


class TeacherGradeOverrideStorageReadError(TeacherGradeOverrideStorageError):
    code = "teacher_grade_override.read_failed"


class TeacherGradeOverrideStorageWriteError(TeacherGradeOverrideStorageError):
    code = "teacher_grade_override.write_failed"


class TeacherGradeOverrideStorageConflictError(TeacherGradeOverrideStorageError):
    code = "teacher_grade_override.conflict"


class TeacherGradeOverrideStorageLockError(
    TeacherGradeOverrideStorageConflictError
):
    code = "teacher_grade_override.locked"


class TeacherGradeOverrideStorageIntegrityError(TeacherGradeOverrideStorageError):
    code = "teacher_grade_override.integrity_failed"


class TeacherGradeOverrideStorageTooLargeError(
    TeacherGradeOverrideStorageReadError
):
    code = "teacher_grade_override.too_large"


@dataclass(frozen=True, slots=True)
class StoredTeacherGradeOverrideDecision:
    """One verified immutable teacher override decision revision."""

    decision: TeacherGradeOverrideDecision
    override_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, TeacherGradeOverrideDecision):
            raise TeacherGradeOverrideStorageValidationError(
                "decision must be TeacherGradeOverrideDecision."
            )
        digest = _sha256(self.override_sha256, "override_sha256")
        if type(self.content) is not bytes:
            raise TeacherGradeOverrideStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise TeacherGradeOverrideStorageValidationError(
                "override_sha256 must match exact immutable content."
            )
        try:
            decoded = teacher_grade_override_decision_from_json_bytes(self.content)
        except (
            TeacherGradeOverrideSerializationError,
            TeacherGradeOverrideValidationError,
        ) as error:
            raise TeacherGradeOverrideStorageValidationError(
                "content is not a canonical teacher Grade override decision."
            ) from error
        if decoded != self.decision:
            raise TeacherGradeOverrideStorageValidationError(
                "content does not decode to decision."
            )
        expected = teacher_grade_override_revision_relative_path(
            self.decision.class_id,
            self.decision.student_id,
            self.decision.target_period,
            self.decision.calendar_revision,
            self.decision.calculation_family,
            self.decision.override_revision,
        )
        if self.relative_path != expected:
            raise TeacherGradeOverrideStorageValidationError(
                "relative_path is not the canonical override revision location."
            )
        if self.path.name != f"{self.decision.override_revision}.json":
            raise TeacherGradeOverrideStorageValidationError(
                "path filename does not match override revision identity."
            )
        object.__setattr__(self, "override_sha256", digest)

    @property
    def reference(self) -> TeacherGradeOverrideReference:
        return TeacherGradeOverrideReference(
            class_id=self.decision.class_id,
            student_id=self.decision.student_id,
            school_year=self.decision.target_period.school_year,
            period_id=self.decision.target_period.period_id,
            calendar_revision=self.decision.calendar_revision,
            calculation_family=self.decision.calculation_family,
            override_revision=self.decision.override_revision,
            override_sha256=self.override_sha256,
        )


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideWriteResult:
    disposition: TeacherGradeOverrideWriteDisposition
    stored: StoredTeacherGradeOverrideDecision


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideCurrentSelection:
    """Exact digest-bound current selector for one override family."""

    schema_version: str
    record_type: str
    class_id: str
    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    calculation_family: GradeCalculationFamily
    subject_key: str
    override_revision: int
    override_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != TEACHER_GRADE_OVERRIDE_CURRENT_SCHEMA_VERSION:
            raise TeacherGradeOverrideStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != TEACHER_GRADE_OVERRIDE_CURRENT_RECORD_TYPE:
            raise TeacherGradeOverrideStorageValidationError(
                'current record_type must be "meridian_teacher_grade_override_current".'
            )
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        try:
            period = AcademicPeriodRef(self.school_year, self.period_id)
        except AcademicPeriodValidationError as error:
            raise TeacherGradeOverrideStorageValidationError(
                f"current Academic Period is invalid: {error}"
            ) from error
        calendar_revision = _positive_int(
            self.calendar_revision, "calendar_revision"
        )
        family = _family(self.calculation_family)
        expected_subject = teacher_grade_override_subject_key(
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
        )
        if self.subject_key != expected_subject:
            raise TeacherGradeOverrideStorageValidationError(
                "current subject_key does not match exact override scope."
            )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "school_year", period.school_year)
        object.__setattr__(self, "period_id", period.period_id)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "calculation_family", family)
        object.__setattr__(
            self,
            "subject_key",
            _sha256(self.subject_key, "subject_key"),
        )
        object.__setattr__(
            self,
            "override_revision",
            _positive_int(self.override_revision, "override_revision"),
        )
        object.__setattr__(
            self,
            "override_sha256",
            _sha256(self.override_sha256, "override_sha256"),
        )

    @property
    def reference(self) -> TeacherGradeOverrideReference:
        return TeacherGradeOverrideReference(
            class_id=self.class_id,
            student_id=self.student_id,
            school_year=self.school_year,
            period_id=self.period_id,
            calendar_revision=self.calendar_revision,
            calculation_family=self.calculation_family,
            override_revision=self.override_revision,
            override_sha256=self.override_sha256,
        )


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideSelectionResult:
    disposition: TeacherGradeOverrideSelectDisposition
    selection: TeacherGradeOverrideCurrentSelection
    stored: StoredTeacherGradeOverrideDecision


def teacher_grade_overrides_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "grade_overrides"
    _require_containment(root, path)
    return path


def teacher_grade_override_subject_key(
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> str:
    """Return the privacy-minimized deterministic key for one override family."""

    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = _family(calculation_family)
    payload = {
        "class_id": class_value,
        "student_id": student,
        "target_period": {
            "school_year": period.school_year,
            "period_id": period.period_id,
        },
        "calendar_revision": calendar,
        "calculation_family": family,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def teacher_grade_override_family_directory(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = _family(calculation_family)
    subject_key = teacher_grade_override_subject_key(
        class_value,
        student,
        period,
        calendar,
        family,
    )
    path = (
        teacher_grade_overrides_directory(root, class_value)
        / "periods"
        / period.school_year
        / period.period_id
        / "students"
        / subject_key
        / family
    )
    _require_containment(root, path)
    return path


def teacher_grade_override_revision_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    override_revision: int,
) -> Path:
    revision = _positive_int(override_revision, "override_revision")
    return (
        teacher_grade_override_family_directory(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
        )
        / "revisions"
        / f"{revision}.json"
    )


def teacher_grade_override_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    override_revision: int,
) -> Path:
    return Path(
        str(
            teacher_grade_override_revision_path(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
                calculation_family,
                override_revision,
            )
        )
        + ".sha256"
    )


def teacher_grade_override_current_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> Path:
    return teacher_grade_override_family_directory(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
    ) / "current.json"


def teacher_grade_override_revision_relative_path(
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    override_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = _family(calculation_family)
    revision = _positive_int(override_revision, "override_revision")
    subject_key = teacher_grade_override_subject_key(
        class_value,
        student,
        period,
        calendar,
        family,
    )
    return (
        f"classes/{class_value}/modules/meridian/grade_overrides/"
        f"periods/{period.school_year}/{period.period_id}/students/"
        f"{subject_key}/{family}/revisions/{revision}.json"
    )


def write_teacher_grade_override_revision(
    workspace_root: str | Path,
    decision: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideWriteResult:
    """Persist one immutable override revision without selecting it."""

    try:
        candidate = validate_teacher_grade_override_decision(decision)
        content = teacher_grade_override_decision_to_json_bytes(candidate)
    except (
        TeacherGradeOverrideSerializationError,
        TeacherGradeOverrideValidationError,
    ) as error:
        raise TeacherGradeOverrideStorageValidationError(str(error)) from error
    if len(content) > DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_BYTES:
        raise TeacherGradeOverrideStorageWriteError(
            "Teacher Grade override exceeds the canonical byte limit."
        )

    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    family = teacher_grade_override_family_directory(
        root,
        candidate.class_id,
        candidate.student_id,
        candidate.target_period,
        candidate.calendar_revision,
        candidate.calculation_family,
    )
    revisions = family / "revisions"
    _ensure_directory_chain(root, revisions)
    _validate_override_ancestor_shape(root, candidate)
    target = teacher_grade_override_revision_path(
        root,
        candidate.class_id,
        candidate.student_id,
        candidate.target_period,
        candidate.calendar_revision,
        candidate.calculation_family,
        candidate.override_revision,
    )
    digest_target = Path(str(target) + ".sha256")
    digest = hashlib.sha256(content).hexdigest()

    if target.exists() or digest_target.exists():
        stored = _load_existing_for_replay(root, candidate)
        if stored.content != content or stored.override_sha256 != digest:
            raise TeacherGradeOverrideStorageConflictError(
                "Teacher Grade override revision already exists with different content."
            )
        return TeacherGradeOverrideWriteResult("existing", stored)

    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_override_family_directory(family)
        if target.exists() or digest_target.exists():
            stored = _load_existing_for_replay(root, candidate)
            if stored.content != content or stored.override_sha256 != digest:
                raise TeacherGradeOverrideStorageConflictError(
                    "Teacher Grade override revision already exists with "
                    "different content."
                )
            return TeacherGradeOverrideWriteResult("existing", stored)

        history = list_teacher_grade_override_revisions(
            root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
        )
        if not history:
            if candidate.override_revision != 1:
                raise TeacherGradeOverrideStorageConflictError(
                    "Initial teacher Grade override revision must be 1."
                )
        else:
            if candidate.override_revision != history[-1] + 1:
                raise TeacherGradeOverrideStorageConflictError(
                    "Teacher Grade override revision must be contiguous."
                )
            previous = load_teacher_grade_override_revision(
                root,
                candidate.class_id,
                candidate.student_id,
                candidate.target_period,
                candidate.calendar_revision,
                candidate.calculation_family,
                history[-1],
            ).decision
            try:
                validate_teacher_grade_override_transition(previous, candidate)
            except TeacherGradeOverrideValidationError as error:
                raise TeacherGradeOverrideStorageConflictError(str(error)) from error

        _validate_withdrawal_reference(root, candidate)
        _write_revision_pair(target, digest_target, content, digest)
        stored = load_teacher_grade_override_revision(
            root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
            candidate.override_revision,
        )
        if stored.content != content or stored.override_sha256 != digest:
            raise TeacherGradeOverrideStorageIntegrityError(
                "Persisted teacher Grade override differs from candidate bytes."
            )
        return TeacherGradeOverrideWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_teacher_grade_override_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    override_revision: int,
) -> StoredTeacherGradeOverrideDecision:
    """Load one exact immutable override revision without consulting current."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family_name = _family(calculation_family)
    revision = _positive_int(override_revision, "override_revision")
    family = teacher_grade_override_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
    )
    _validate_override_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
    )
    _validate_override_family_directory(family)
    path = teacher_grade_override_revision_path(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
        revision,
    )
    content, digest = _read_revision_pair(
        root,
        path,
        DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_BYTES,
    )
    try:
        decision = teacher_grade_override_decision_from_json_bytes(content)
    except (
        TeacherGradeOverrideSerializationError,
        TeacherGradeOverrideValidationError,
    ) as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            f"Stored teacher Grade override is invalid: {error}"
        ) from error
    expected_scope = (
        class_value,
        student,
        period,
        calendar,
        family_name,
        revision,
    )
    actual_scope = (
        decision.class_id,
        decision.student_id,
        decision.target_period,
        decision.calendar_revision,
        decision.calculation_family,
        decision.override_revision,
    )
    if actual_scope != expected_scope:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Stored teacher Grade override identity does not match its path."
        )
    return StoredTeacherGradeOverrideDecision(
        decision=decision,
        override_sha256=digest,
        path=path,
        relative_path=teacher_grade_override_revision_relative_path(
            class_value,
            student,
            period,
            calendar,
            family_name,
            revision,
        ),
        content=content,
    )


def list_teacher_grade_override_revisions(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> tuple[int, ...]:
    """Return verified contiguous revision numbers for one override family."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family_name = _family(calculation_family)
    family = teacher_grade_override_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
    )
    _validate_override_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
        allow_missing_family=True,
    )
    if not family.exists():
        return ()
    _validate_override_family_directory(family)
    revisions_dir = family / "revisions"
    if not revisions_dir.exists():
        return ()
    _require_safe_directory(root, revisions_dir)

    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    for entry in revisions_dir.iterdir():
        _reject_symlink(entry)
        if not entry.is_file():
            raise TeacherGradeOverrideStorageIntegrityError(
                "Override revisions directory contains a non-file entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
            continue
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
            continue
        raise TeacherGradeOverrideStorageIntegrityError(
            f"Unexpected teacher Grade override revision entry: {entry.name}."
        )
    if json_revisions != digest_revisions:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override revision JSON/digest pairs are incomplete."
        )
    ordered = tuple(sorted(json_revisions))
    if ordered and ordered != tuple(range(1, ordered[-1] + 1)):
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override revision history is not contiguous."
        )

    previous: TeacherGradeOverrideDecision | None = None
    for revision in ordered:
        current = load_teacher_grade_override_revision(
            root,
            class_value,
            student,
            period,
            calendar,
            family_name,
            revision,
        ).decision
        if previous is not None:
            try:
                validate_teacher_grade_override_transition(previous, current)
            except TeacherGradeOverrideValidationError as error:
                raise TeacherGradeOverrideStorageIntegrityError(
                    f"Stored teacher Grade override history is invalid: {error}"
                ) from error
        _validate_withdrawal_reference(root, current)
        previous = current
    return ordered


def get_current_teacher_grade_override_reference(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> TeacherGradeOverrideReference | None:
    """Return the exact selected override reference, or None if unselected."""

    selection = _load_current_selection(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
    )
    return selection.reference if selection is not None else None


def load_current_teacher_grade_override(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> StoredTeacherGradeOverrideDecision | None:
    """Load the exact selected override revision, or None if unselected."""

    selection = _load_current_selection(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
    )
    if selection is None:
        return None
    stored = load_teacher_grade_override_revision(
        workspace_root,
        selection.class_id,
        selection.student_id,
        AcademicPeriodRef(selection.school_year, selection.period_id),
        selection.calendar_revision,
        selection.calculation_family,
        selection.override_revision,
    )
    if stored.override_sha256 != selection.override_sha256:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Current override pointer digest does not match selected revision."
        )
    return stored


def select_teacher_grade_override_revision(
    workspace_root: str | Path,
    reference: TeacherGradeOverrideReference,
    *,
    expected_current: TeacherGradeOverrideReference | None,
) -> TeacherGradeOverrideSelectionResult:
    """Explicitly select one exact stored override revision using digest-bound CAS."""

    if not isinstance(reference, TeacherGradeOverrideReference):
        raise TeacherGradeOverrideStorageValidationError(
            "reference must be TeacherGradeOverrideReference."
        )
    target_ref = TeacherGradeOverrideReference(
        class_id=reference.class_id,
        student_id=reference.student_id,
        school_year=reference.school_year,
        period_id=reference.period_id,
        calendar_revision=reference.calendar_revision,
        calculation_family=reference.calculation_family,
        override_revision=reference.override_revision,
        override_sha256=reference.override_sha256,
    )
    if expected_current is not None:
        if not isinstance(expected_current, TeacherGradeOverrideReference):
            raise TeacherGradeOverrideStorageValidationError(
                "expected_current must be TeacherGradeOverrideReference or None."
            )
        expected_ref = TeacherGradeOverrideReference(
            class_id=expected_current.class_id,
            student_id=expected_current.student_id,
            school_year=expected_current.school_year,
            period_id=expected_current.period_id,
            calendar_revision=expected_current.calendar_revision,
            calculation_family=expected_current.calculation_family,
            override_revision=expected_current.override_revision,
            override_sha256=expected_current.override_sha256,
        )
        _require_same_reference_family(target_ref, expected_ref)
    else:
        expected_ref = None

    period = AcademicPeriodRef(target_ref.school_year, target_ref.period_id)
    root = _root(workspace_root)
    stored = load_teacher_grade_override_revision(
        root,
        target_ref.class_id,
        target_ref.student_id,
        period,
        target_ref.calendar_revision,
        target_ref.calculation_family,
        target_ref.override_revision,
    )
    if stored.override_sha256 != target_ref.override_sha256:
        raise TeacherGradeOverrideStorageConflictError(
            "Selected override reference digest does not match stored revision."
        )

    family = teacher_grade_override_family_directory(
        root,
        target_ref.class_id,
        target_ref.student_id,
        period,
        target_ref.calendar_revision,
        target_ref.calculation_family,
    )
    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_override_family_directory(family)
        current = _load_current_selection(
            root,
            target_ref.class_id,
            target_ref.student_id,
            period,
            target_ref.calendar_revision,
            target_ref.calculation_family,
        )
        if current is not None and current.reference == target_ref:
            return TeacherGradeOverrideSelectionResult(
                "existing", current, stored
            )
        actual_ref = current.reference if current is not None else None
        if actual_ref != expected_ref:
            raise TeacherGradeOverrideStorageConflictError(
                "Current teacher Grade override changed before selection."
            )

        selection = _selection_from_reference(target_ref)
        pointer = teacher_grade_override_current_path(
            root,
            target_ref.class_id,
            target_ref.student_id,
            period,
            target_ref.calendar_revision,
            target_ref.calculation_family,
        )
        existed = pointer.exists()
        _atomic_replace_file(pointer, _current_selection_to_json_bytes(selection))
        reloaded = _load_current_selection(
            root,
            target_ref.class_id,
            target_ref.student_id,
            period,
            target_ref.calendar_revision,
            target_ref.calculation_family,
        )
        if reloaded != selection:
            raise TeacherGradeOverrideStorageIntegrityError(
                "Persisted current override pointer differs from selected reference."
            )
        return TeacherGradeOverrideSelectionResult(
            "updated" if existed else "created",
            selection,
            stored,
        )
    finally:
        _remove_lock(lock)


def _selection_from_reference(
    reference: TeacherGradeOverrideReference,
) -> TeacherGradeOverrideCurrentSelection:
    period = AcademicPeriodRef(reference.school_year, reference.period_id)
    return TeacherGradeOverrideCurrentSelection(
        schema_version=TEACHER_GRADE_OVERRIDE_CURRENT_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_CURRENT_RECORD_TYPE,
        class_id=reference.class_id,
        student_id=reference.student_id,
        school_year=reference.school_year,
        period_id=reference.period_id,
        calendar_revision=reference.calendar_revision,
        calculation_family=reference.calculation_family,
        subject_key=teacher_grade_override_subject_key(
            reference.class_id,
            reference.student_id,
            period,
            reference.calendar_revision,
            reference.calculation_family,
        ),
        override_revision=reference.override_revision,
        override_sha256=reference.override_sha256,
    )


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> TeacherGradeOverrideCurrentSelection | None:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family_name = _family(calculation_family)
    _validate_override_ancestor_shape_values(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
        allow_missing_family=True,
    )
    pointer = teacher_grade_override_current_path(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
    )
    _reject_symlink(pointer)
    if not pointer.exists():
        return None
    content = _read_bounded_file(
        pointer,
        DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_POINTER_BYTES,
        "teacher Grade override current pointer",
    )
    selection = _current_selection_from_json_bytes(content)
    expected_scope = (
        class_value,
        student,
        period.school_year,
        period.period_id,
        calendar,
        family_name,
        teacher_grade_override_subject_key(
            class_value,
            student,
            period,
            calendar,
            family_name,
        ),
    )
    actual_scope = (
        selection.class_id,
        selection.student_id,
        selection.school_year,
        selection.period_id,
        selection.calendar_revision,
        selection.calculation_family,
        selection.subject_key,
    )
    if actual_scope != expected_scope:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Current override pointer scope does not match its path."
        )
    stored = load_teacher_grade_override_revision(
        root,
        class_value,
        student,
        period,
        calendar,
        family_name,
        selection.override_revision,
    )
    if stored.override_sha256 != selection.override_sha256:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Current override pointer digest does not match selected revision."
        )
    return selection


def _validate_withdrawal_reference(
    root: Path,
    candidate: TeacherGradeOverrideDecision,
) -> None:
    if candidate.decision != "withdraw":
        return
    reference = candidate.withdrawn_override_reference
    if reference is None:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Withdrawal is missing its exact override reference."
        )
    period = AcademicPeriodRef(reference.school_year, reference.period_id)
    try:
        withdrawn = load_teacher_grade_override_revision(
            root,
            reference.class_id,
            reference.student_id,
            period,
            reference.calendar_revision,
            reference.calculation_family,
            reference.override_revision,
        )
    except TeacherGradeOverrideStorageNotFoundError as error:
        raise TeacherGradeOverrideStorageConflictError(
            "Withdrawal references an unavailable override revision."
        ) from error
    if withdrawn.override_sha256 != reference.override_sha256:
        raise TeacherGradeOverrideStorageConflictError(
            "Withdrawal reference digest does not match the stored override."
        )
    if withdrawn.decision.decision != "override":
        raise TeacherGradeOverrideStorageConflictError(
            "Withdrawal must reference an override decision, not another withdrawal."
        )
    if withdrawn.decision.source_result != candidate.source_result:
        raise TeacherGradeOverrideStorageConflictError(
            "Withdrawal source_result must exactly match the withdrawn override."
        )


def _load_existing_for_replay(
    root: Path,
    candidate: TeacherGradeOverrideDecision,
) -> StoredTeacherGradeOverrideDecision:
    try:
        return load_teacher_grade_override_revision(
            root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
            candidate.override_revision,
        )
    except TeacherGradeOverrideStorageNotFoundError as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Override revision pair is incomplete."
        ) from error


def _validate_override_ancestor_shape(
    root: Path,
    decision: TeacherGradeOverrideDecision,
) -> None:
    _validate_override_ancestor_shape_values(
        root,
        decision.class_id,
        decision.student_id,
        decision.target_period,
        decision.calendar_revision,
        decision.calculation_family,
    )


def _validate_override_ancestor_shape_values(
    root: Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    *,
    allow_missing_family: bool = False,
) -> None:
    _require_existing_core_class(root, class_id)
    family = teacher_grade_override_family_directory(
        root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
    )
    cursor = family
    chain: list[Path] = []
    while cursor != root:
        chain.append(cursor)
        cursor = cursor.parent
    for path in reversed(chain):
        if not path.exists():
            if allow_missing_family:
                return
            continue
        _require_safe_directory(root, path)


def _validate_override_family_directory(family: Path) -> None:
    if not family.exists():
        return
    _reject_symlink(family)
    if not family.is_dir():
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override family path is not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    for entry in family.iterdir():
        _reject_symlink(entry)
        if entry.name not in allowed:
            raise TeacherGradeOverrideStorageIntegrityError(
                f"Unexpected teacher Grade override family entry: {entry.name}."
            )
        if entry.name == "revisions" and not entry.is_dir():
            raise TeacherGradeOverrideStorageIntegrityError(
                "Teacher Grade override revisions entry is not a directory."
            )
        if entry.name != "revisions" and not entry.is_file():
            raise TeacherGradeOverrideStorageIntegrityError(
                "Teacher Grade override family contains a non-file control entry."
            )


def _write_revision_pair(
    target: Path,
    digest_target: Path,
    content: bytes,
    digest: str,
) -> None:
    if target.exists() or digest_target.exists():
        raise TeacherGradeOverrideStorageConflictError(
            "Teacher Grade override revision already exists."
        )
    _atomic_create_file(target, content)
    try:
        _atomic_create_file(digest_target, (digest + "\n").encode("ascii"))
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise


def _read_revision_pair(
    root: Path,
    path: Path,
    maximum_bytes: int,
) -> tuple[bytes, str]:
    _require_containment(root, path)
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() and not digest_path.exists():
        raise TeacherGradeOverrideStorageNotFoundError(
            "Teacher Grade override revision does not exist."
        )
    if not path.exists() or not digest_path.exists():
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override revision JSON/digest pair is incomplete."
        )
    content = _read_bounded_file(
        path,
        maximum_bytes,
        "teacher Grade override revision",
    )
    digest_bytes = _read_bounded_file(
        digest_path,
        DEFAULT_MAXIMUM_TEACHER_GRADE_OVERRIDE_DIGEST_BYTES,
        "teacher Grade override digest",
    )
    try:
        digest_text = digest_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override digest is not ASCII."
        ) from error
    if not digest_text.endswith("\n") or digest_text.count("\n") != 1:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override digest sidecar is not canonical."
        )
    digest = digest_text[:-1]
    try:
        _sha256(digest, "stored override digest")
    except TeacherGradeOverrideStorageValidationError as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override digest sidecar is invalid."
        ) from error
    actual = hashlib.sha256(content).hexdigest()
    if actual != digest:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override content digest does not match sidecar."
        )
    return content, digest


def _current_selection_to_json_bytes(
    selection: TeacherGradeOverrideCurrentSelection,
) -> bytes:
    data = {
        "schema_version": selection.schema_version,
        "record_type": selection.record_type,
        "class_id": selection.class_id,
        "student_id": selection.student_id,
        "school_year": selection.school_year,
        "period_id": selection.period_id,
        "calendar_revision": selection.calendar_revision,
        "calculation_family": selection.calculation_family,
        "subject_key": selection.subject_key,
        "override_revision": selection.override_revision,
        "override_sha256": selection.override_sha256,
    }
    return _canonical_json_bytes(data)


def _current_selection_from_json_bytes(
    data: bytes,
) -> TeacherGradeOverrideCurrentSelection:
    decoded = _decode_json(data, "teacher Grade override current pointer")
    mapping = _exact_mapping(
        decoded,
        _POINTER_KEYS,
        "teacher Grade override current pointer",
    )
    try:
        selection = TeacherGradeOverrideCurrentSelection(
            schema_version=_required_str(
                mapping["schema_version"], "schema_version"
            ),
            record_type=_required_str(mapping["record_type"], "record_type"),
            class_id=_required_str(mapping["class_id"], "class_id"),
            student_id=_required_str(mapping["student_id"], "student_id"),
            school_year=_required_str(mapping["school_year"], "school_year"),
            period_id=_required_str(mapping["period_id"], "period_id"),
            calendar_revision=_required_int(
                mapping["calendar_revision"], "calendar_revision"
            ),
            calculation_family=_family(mapping["calculation_family"]),
            subject_key=_required_str(mapping["subject_key"], "subject_key"),
            override_revision=_required_int(
                mapping["override_revision"], "override_revision"
            ),
            override_sha256=_required_str(
                mapping["override_sha256"], "override_sha256"
            ),
        )
    except TeacherGradeOverrideStorageValidationError as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            f"Teacher Grade override current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise TeacherGradeOverrideStorageIntegrityError(
            "Teacher Grade override current pointer is not canonical JSON."
        )
    return selection


def _require_same_reference_family(
    target: TeacherGradeOverrideReference,
    expected: TeacherGradeOverrideReference,
) -> None:
    target_family = (
        target.class_id,
        target.student_id,
        target.school_year,
        target.period_id,
        target.calendar_revision,
        target.calculation_family,
    )
    expected_family = (
        expected.class_id,
        expected.student_id,
        expected.school_year,
        expected.period_id,
        expected.calendar_revision,
        expected.calculation_family,
    )
    if target_family != expected_family:
        raise TeacherGradeOverrideStorageValidationError(
            "expected_current must belong to the same override family."
        )


def _root(value: str | Path) -> Path:
    root = Path(value).resolve()
    if not root.exists() or not root.is_dir():
        raise TeacherGradeOverrideStorageValidationError(
            "workspace_root must identify an existing directory."
        )
    _reject_symlink(Path(value))
    return root


def _require_existing_core_class(root: Path, class_id: str) -> Path:
    path = class_dir(root, _identifier(class_id, "class_id"))
    _require_containment(root, path)
    if not path.exists():
        raise TeacherGradeOverrideStorageValidationError(
            "class_id does not identify an existing Core class directory."
        )
    _require_safe_directory(root, path)
    return path


def _ensure_directory_chain(root: Path, path: Path) -> None:
    _require_containment(root, path)
    relative = path.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.exists():
            _require_safe_directory(root, cursor)
            continue
        try:
            cursor.mkdir()
        except FileExistsError:
            pass
        except OSError as error:
            raise TeacherGradeOverrideStorageWriteError(
                f"Unable to create teacher Grade override directory: {cursor}."
            ) from error
        _require_safe_directory(root, cursor)


def _require_safe_directory(root: Path, path: Path) -> None:
    _require_containment(root, path)
    _reject_symlink(path)
    if not path.is_dir():
        raise TeacherGradeOverrideStorageIntegrityError(
            f"Expected directory is not a directory: {path}."
        )


def _reject_symlink(path: Path) -> None:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise TeacherGradeOverrideStorageReadError(
            f"Unable to inspect path safely: {path}."
        ) from error
    if stat.S_ISLNK(mode):
        raise TeacherGradeOverrideStorageIntegrityError(
            f"Symbolic links are not permitted in override storage: {path}."
        )


def _require_containment(root: Path, path: Path) -> None:
    try:
        common = os.path.commonpath((str(root), str(path.absolute())))
    except ValueError as error:
        raise TeacherGradeOverrideStorageValidationError(
            "Override storage path is outside workspace_root."
        ) from error
    if common != str(root):
        raise TeacherGradeOverrideStorageValidationError(
            "Override storage path is outside workspace_root."
        )


def _read_bounded_file(path: Path, maximum: int, label: str) -> bytes:
    _reject_symlink(path)
    try:
        info = path.stat()
    except FileNotFoundError as error:
        raise TeacherGradeOverrideStorageNotFoundError(
            f"{label} does not exist."
        ) from error
    except OSError as error:
        raise TeacherGradeOverrideStorageReadError(
            f"Unable to stat {label}."
        ) from error
    if not stat.S_ISREG(info.st_mode):
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} is not a regular file."
        )
    if info.st_size > maximum:
        raise TeacherGradeOverrideStorageTooLargeError(
            f"{label} exceeds the configured byte limit."
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise TeacherGradeOverrideStorageReadError(
            f"Unable to read {label}."
        ) from error
    if len(data) > maximum:
        raise TeacherGradeOverrideStorageTooLargeError(
            f"{label} exceeds the configured byte limit."
        )
    return data


def _atomic_create_file(path: Path, data: bytes) -> None:
    _reject_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise TeacherGradeOverrideStorageConflictError(
                f"Immutable teacher Grade override path already exists: {path.name}."
            )
        os.replace(temporary, path)
        temporary = None
    except TeacherGradeOverrideStorageError:
        raise
    except OSError as error:
        raise TeacherGradeOverrideStorageWriteError(
            f"Unable to create immutable teacher Grade override file: {path}."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _atomic_replace_file(path: Path, data: bytes) -> None:
    _reject_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise TeacherGradeOverrideStorageWriteError(
            f"Unable to replace teacher Grade override current pointer: {path}."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _acquire_lock(path: Path) -> None:
    _reject_symlink(path)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise TeacherGradeOverrideStorageLockError(
            "Teacher Grade override history is locked by another writer."
        ) from error
    except OSError as error:
        raise TeacherGradeOverrideStorageWriteError(
            "Unable to acquire teacher Grade override write lock."
        ) from error
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
    finally:
        os.close(descriptor)


def _remove_lock(path: Path) -> None:
    try:
        _reject_symlink(path)
        path.unlink(missing_ok=True)
    except TeacherGradeOverrideStorageError:
        raise
    except OSError as error:
        raise TeacherGradeOverrideStorageWriteError(
            "Unable to release teacher Grade override write lock."
        ) from error


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
        raise TeacherGradeOverrideStorageValidationError(
            "Value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except TeacherGradeOverrideStorageError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TeacherGradeOverrideStorageIntegrityError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise TeacherGradeOverrideStorageIntegrityError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} must be an object."
        )
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise TeacherGradeOverrideStorageIntegrityError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherGradeOverrideStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise TeacherGradeOverrideStorageValidationError(str(error)) from error


def _period(value: object) -> AcademicPeriodRef:
    if not isinstance(value, (AcademicPeriodRef, Mapping)):
        raise TeacherGradeOverrideStorageValidationError(
            "target_period must be AcademicPeriodRef or a mapping."
        )
    try:
        return validate_academic_period_ref(value)
    except (AcademicPeriodValidationError, TypeError) as error:
        raise TeacherGradeOverrideStorageValidationError(
            f"target_period is invalid: {error}"
        ) from error


def _family(value: object) -> GradeCalculationFamily:
    if not isinstance(value, str) or value not in _FAMILIES:
        raise TeacherGradeOverrideStorageValidationError(
            "calculation_family must be one of: conventional, hybrid, standards_based."
        )
    return cast(GradeCalculationFamily, value)


def _positive_int(value: object, field_name: str) -> int:
    integer = _required_int(value, field_name)
    if integer <= 0:
        raise TeacherGradeOverrideStorageValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeacherGradeOverrideStorageValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherGradeOverrideStorageValidationError(
            f"{field_name} must be a string."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TeacherGradeOverrideStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value
