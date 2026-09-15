"""Canonical immutable persistence for bounded hybrid Grade results.

A stored hybrid Grade result is advisory Meridian calculation history. It is not
an override, Grade preview, ReportingSnapshot, export, or official Grade.
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

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    load_academic_period_proficiency_result_revision,
)
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.grade_item_storage import GradeItemStorageError, load_grade_item_revision
from meridian.grade_policy import HybridGradeConfiguration
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationStorageError,
    load_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    load_grade_policy_revision,
)
from meridian.hybrid_grade_assembly import (
    HybridGradeAssemblyError,
    assemble_hybrid_grade_calculation,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    HybridGradeResultSerializationError,
    HybridGradeResultSnapshot,
    HybridGradeResultValidationError,
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
    validate_hybrid_grade_result_transition,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)

HYBRID_GRADE_RESULT_CURRENT_SCHEMA_VERSION: Final[str] = "1"
HYBRID_GRADE_RESULT_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_hybrid_grade_result_current"
)
DEFAULT_MAXIMUM_HYBRID_GRADE_RESULT_BYTES: Final[int] = 16 * 1024 * 1024
DEFAULT_MAXIMUM_HYBRID_GRADE_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_HYBRID_GRADE_DIGEST_BYTES: Final[int] = 128

HybridGradeResultWriteDisposition: TypeAlias = Literal["created", "existing"]
HybridGradeResultSelectDisposition: TypeAlias = Literal[
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


class HybridGradeStorageError(RuntimeError):
    """Base error for hybrid Grade result persistence."""

    code: str = "hybrid_grade.storage_error"


class HybridGradeStorageValidationError(HybridGradeStorageError, ValueError):
    code = "hybrid_grade.storage_invalid"


class HybridGradeStorageNotFoundError(HybridGradeStorageError):
    code = "hybrid_grade.not_found"


class HybridGradeStorageReadError(HybridGradeStorageError):
    code = "hybrid_grade.read_failed"


class HybridGradeStorageWriteError(HybridGradeStorageError):
    code = "hybrid_grade.write_failed"


class HybridGradeStorageConflictError(HybridGradeStorageError):
    code = "hybrid_grade.conflict"


class HybridGradeStorageLockError(HybridGradeStorageConflictError):
    code = "hybrid_grade.locked"


class HybridGradeStorageIntegrityError(HybridGradeStorageError):
    code = "hybrid_grade.integrity"


class HybridGradeStorageTooLargeError(HybridGradeStorageReadError):
    code = "hybrid_grade.too_large"


class HybridGradeResultDependencyError(HybridGradeStorageConflictError):
    code = "hybrid_grade.result_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StoredHybridGradeResult:
    """One verified immutable hybrid Grade result revision."""

    snapshot: HybridGradeResultSnapshot
    result_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, HybridGradeResultSnapshot):
            raise HybridGradeStorageValidationError(
                "snapshot must be HybridGradeResultSnapshot."
            )
        digest = _sha256(self.result_sha256, "result_sha256")
        if type(self.content) is not bytes:
            raise HybridGradeStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise HybridGradeStorageValidationError(
                "result_sha256 must match exact immutable content."
            )
        try:
            decoded = hybrid_grade_result_snapshot_from_json_bytes(self.content)
        except (
            HybridGradeResultSerializationError,
            HybridGradeResultValidationError,
        ) as error:
            raise HybridGradeStorageValidationError(
                "content is not a canonical hybrid Grade result."
            ) from error
        if decoded != self.snapshot:
            raise HybridGradeStorageValidationError(
                "content does not decode to snapshot."
            )
        expected = hybrid_grade_result_revision_relative_path(
            self.snapshot.class_id,
            self.snapshot.student_id,
            self.snapshot.target_period,
            self.snapshot.calendar_revision,
            self.snapshot.result_revision,
        )
        if self.relative_path != expected:
            raise HybridGradeStorageValidationError(
                "relative_path is not the canonical result revision location."
            )
        if self.path.name != f"{self.snapshot.result_revision}.json":
            raise HybridGradeStorageValidationError(
                "path filename does not match result revision identity."
            )
        object.__setattr__(self, "result_sha256", digest)

    @property
    def reference(self) -> HybridGradeResultReference:
        value = self.snapshot
        return HybridGradeResultReference(
            class_id=value.class_id,
            student_id=value.student_id,
            school_year=value.target_period.school_year,
            period_id=value.target_period.period_id,
            calendar_revision=value.calendar_revision,
            result_revision=value.result_revision,
            result_sha256=self.result_sha256,
        )


@dataclass(frozen=True, slots=True)
class HybridGradeResultWriteResult:
    disposition: HybridGradeResultWriteDisposition
    stored: StoredHybridGradeResult


@dataclass(frozen=True, slots=True)
class HybridGradeResultSelectionResult:
    disposition: HybridGradeResultSelectDisposition
    stored: StoredHybridGradeResult


def hybrid_grades_directory(workspace_root: str | Path, class_id: str) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "hybrid_grades"
    _require_containment(root, path)
    return path


def hybrid_grade_subject_key(
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


def hybrid_grade_result_family_directory(
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
    subject_key = hybrid_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    path = (
        hybrid_grades_directory(root, class_value)
        / "periods"
        / period.school_year
        / period.period_id
        / "students"
        / subject_key
    )
    _require_containment(root, path)
    return path


def hybrid_grade_result_revision_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
) -> Path:
    revision = _positive_int(result_revision, "result_revision")
    return (
        hybrid_grade_result_family_directory(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
        )
        / "revisions"
        / f"{revision}.json"
    )


def hybrid_grade_result_current_path(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> Path:
    return hybrid_grade_result_family_directory(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
    ) / "current.json"


def hybrid_grade_result_revision_relative_path(
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
    subject_key = hybrid_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    return (
        f"classes/{class_value}/modules/meridian/hybrid_grades/"
        f"periods/{period.school_year}/{period.period_id}/students/"
        f"{subject_key}/revisions/{revision}.json"
    )


def write_hybrid_grade_result_revision(
    workspace_root: str | Path,
    snapshot: HybridGradeResultSnapshot,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> HybridGradeResultWriteResult:
    """Persist one exact hybrid result revision without selecting it."""

    if not isinstance(snapshot, HybridGradeResultSnapshot):
        raise HybridGradeStorageValidationError(
            "snapshot must be HybridGradeResultSnapshot."
        )
    try:
        content = hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    except (
        HybridGradeResultSerializationError,
        HybridGradeResultValidationError,
    ) as error:
        raise HybridGradeStorageValidationError(str(error)) from error
    if len(content) > DEFAULT_MAXIMUM_HYBRID_GRADE_RESULT_BYTES:
        raise HybridGradeStorageWriteError(
            "Hybrid Grade result exceeds the canonical byte limit."
        )

    root = _root(workspace_root)
    _require_existing_core_class(root, snapshot.class_id)
    family = hybrid_grade_result_family_directory(
        root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    revisions = family / "revisions"
    _ensure_directory_chain(root, revisions)
    _validate_result_ancestor_shape_values(
        root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    target = hybrid_grade_result_revision_path(
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
            raise HybridGradeStorageConflictError(
                "Hybrid Grade result revision already exists with different content."
            )
        return HybridGradeResultWriteResult("existing", stored)

    _refresh_assembly_or_conflict(root, snapshot, work_evidence)

    lock = family / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_result_family_directory(family)
        if target.exists() or digest_target.exists():
            stored = _load_existing_for_replay(root, snapshot)
            if stored.content != content or stored.result_sha256 != digest:
                raise HybridGradeStorageConflictError(
                    "Hybrid Grade result revision already exists with "
                    "different content."
                )
            return HybridGradeResultWriteResult("existing", stored)

        _refresh_assembly_or_conflict(root, snapshot, work_evidence)
        history = list_hybrid_grade_result_revisions(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
        )
        if not history:
            if snapshot.result_revision != 1:
                raise HybridGradeStorageConflictError(
                    "Initial hybrid Grade result revision must be 1."
                )
        else:
            if snapshot.result_revision != history[-1] + 1:
                raise HybridGradeStorageConflictError(
                    "Hybrid Grade result revision must be contiguous."
                )
            previous = load_hybrid_grade_result_revision(
                root,
                snapshot.class_id,
                snapshot.student_id,
                snapshot.target_period,
                snapshot.calendar_revision,
                history[-1],
            ).snapshot
            try:
                validate_hybrid_grade_result_transition(previous, snapshot)
            except HybridGradeResultValidationError as error:
                raise HybridGradeStorageConflictError(str(error)) from error

        _write_revision_pair(target, digest_target, content, digest)
        stored = load_hybrid_grade_result_revision(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            snapshot.result_revision,
        )
        if stored.content != content or stored.result_sha256 != digest:
            raise HybridGradeStorageIntegrityError(
                "Persisted hybrid Grade result differs from candidate bytes."
            )
        return HybridGradeResultWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_hybrid_grade_result_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
) -> StoredHybridGradeResult:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    revision = _positive_int(result_revision, "result_revision")
    family = hybrid_grade_result_family_directory(
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
    path = hybrid_grade_result_revision_path(
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
        DEFAULT_MAXIMUM_HYBRID_GRADE_RESULT_BYTES,
    )
    try:
        snapshot = hybrid_grade_result_snapshot_from_json_bytes(content)
    except (
        HybridGradeResultSerializationError,
        HybridGradeResultValidationError,
    ) as error:
        raise HybridGradeStorageIntegrityError(
            f"Hybrid Grade result is invalid or noncanonical: {error}"
        ) from error
    if (
        snapshot.class_id != class_value
        or snapshot.student_id != student
        or snapshot.target_period != period
        or snapshot.calendar_revision != calendar
        or snapshot.result_revision != revision
    ):
        raise HybridGradeStorageIntegrityError(
            "Persisted hybrid Grade result identity does not match path."
        )
    expected_subject = hybrid_grade_subject_key(
        class_value,
        student,
        period,
        calendar,
    )
    if family.name != expected_subject:
        raise HybridGradeStorageIntegrityError(
            "Persisted student scope does not match hashed canonical path."
        )
    return StoredHybridGradeResult(
        snapshot=snapshot,
        result_sha256=digest,
        path=path,
        relative_path=hybrid_grade_result_revision_relative_path(
            class_value,
            student,
            period,
            calendar,
            revision,
        ),
        content=content,
    )


def list_hybrid_grade_result_revisions(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    student = _identifier(student_id, "student_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    family = hybrid_grade_result_family_directory(
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
        raise HybridGradeStorageIntegrityError(
            "Result JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise HybridGradeStorageIntegrityError(
            "Hybrid Grade result history is not contiguous from revision 1."
        )
    previous: HybridGradeResultSnapshot | None = None
    for revision in revisions:
        stored = load_hybrid_grade_result_revision(
            root,
            class_value,
            student,
            period,
            calendar,
            revision,
        )
        if previous is not None:
            try:
                validate_hybrid_grade_result_transition(previous, stored.snapshot)
            except HybridGradeResultValidationError as error:
                raise HybridGradeStorageIntegrityError(
                    f"Hybrid Grade result history is invalid: {error}"
                ) from error
        previous = stored.snapshot
    return revisions


def get_current_hybrid_grade_result_revision(
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


def load_current_hybrid_grade_result(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> StoredHybridGradeResult | None:
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
    stored = load_hybrid_grade_result_revision(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        cast(int, pointer["result_revision"]),
    )
    if stored.result_sha256 != pointer["result_sha256"]:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer digest does not match selected revision."
        )
    return stored


def select_hybrid_grade_result_revision(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    result_revision: int,
    *,
    expected_current_result_revision: int | None,
) -> HybridGradeResultSelectionResult:
    """Explicitly select one exact hybrid result revision using CAS."""

    root = _root(workspace_root)
    target = load_hybrid_grade_result_revision(
        root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        result_revision,
    )
    _validate_historical_dependencies(root, target.snapshot)
    family = hybrid_grade_result_family_directory(
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
            raise HybridGradeStorageConflictError(
                "Expected current hybrid Grade result revision does not match "
                "stored selection."
            )
        pointer = _result_pointer(target)
        if current == pointer:
            return HybridGradeResultSelectionResult("existing", target)
        _atomic_write_pointer(
            root,
            hybrid_grade_result_current_path(
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
            raise HybridGradeStorageIntegrityError(
                "Published hybrid Grade result selection was not verified."
            )
        disposition: HybridGradeResultSelectDisposition = (
            "created" if current is None else "updated"
        )
        return HybridGradeResultSelectionResult(disposition, target)
    finally:
        _remove_lock(lock)


def _refresh_assembly_or_conflict(
    root: Path,
    snapshot: HybridGradeResultSnapshot,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...],
) -> None:
    try:
        refreshed = assemble_hybrid_grade_calculation(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            work_evidence,
        )
    except HybridGradeAssemblyError as error:
        raise HybridGradeResultDependencyError(
            f"Exact hybrid calculation basis changed before result commit: {error}"
        ) from error
    if refreshed.inputs != snapshot.inputs or refreshed.outcome != snapshot.outcome:
        raise HybridGradeStorageConflictError(
            "Exact hybrid Grade calculation inputs changed before result commit."
        )


def _validate_historical_dependencies(
    root: Path,
    snapshot: HybridGradeResultSnapshot,
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
        raise HybridGradeResultDependencyError(
            "Exact activation revision is unavailable for result selection."
        ) from error
    if activation.activation_sha256 != activation_ref.activation_sha256:
        raise HybridGradeResultDependencyError(
            "Exact activation digest does not match result provenance."
        )
    if (
        activation.decision.decision != "activate"
        or activation.decision.calendar_revision != snapshot.calendar_revision
        or activation.decision.policy_reference != snapshot.policy_reference
    ):
        raise HybridGradeResultDependencyError(
            "Exact activation semantics do not match result provenance."
        )

    policy_ref = snapshot.policy_reference
    try:
        stored_policy = load_grade_policy_revision(
            root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except GradePolicyStorageError as error:
        raise HybridGradeResultDependencyError(
            "Exact hybrid Grade-policy revision is unavailable for result selection."
        ) from error
    if stored_policy.policy_sha256 != policy_ref.policy_sha256:
        raise HybridGradeResultDependencyError(
            "Exact hybrid Grade-policy digest does not match result provenance."
        )
    if (
        stored_policy.policy.calculation_family != "hybrid"
        or not isinstance(stored_policy.policy.configuration, HybridGradeConfiguration)
        or stored_policy.policy.configuration != snapshot.inputs.configuration
    ):
        raise HybridGradeResultDependencyError(
            "Exact stored policy no longer reproduces hybrid result authority."
        )

    for participation in snapshot.inputs.configuration.conventional.items:
        item_ref = participation.grade_item
        try:
            grade_item = load_grade_item_revision(
                root,
                item_ref.class_id,
                item_ref.grade_item_id,
                item_ref.grade_item_revision,
            )
        except GradeItemStorageError as error:
            raise HybridGradeResultDependencyError(
                "Exact conventional Grade Item revision is unavailable for "
                "hybrid result selection."
            ) from error
        if grade_item.revision_sha256 != item_ref.grade_item_revision_sha256:
            raise HybridGradeResultDependencyError(
                "Exact conventional Grade Item digest does not match hybrid "
                "result provenance."
            )

    scale_ref = snapshot.inputs.configuration.standards_based.target_scale
    try:
        scale = load_proficiency_scale_revision(
            root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise HybridGradeResultDependencyError(
            "Exact proficiency-scale revision is unavailable for hybrid selection."
        ) from error
    if scale.scale_sha256 != scale_ref.scale_sha256:
        raise HybridGradeResultDependencyError(
            "Exact proficiency-scale digest does not match hybrid provenance."
        )

    for item in snapshot.inputs.standards_based.standards:
        reference = item.result_reference
        if reference is None:
            continue
        try:
            result = load_academic_period_proficiency_result_revision(
                root,
                reference.class_id,
                reference.school_year,
                reference.period_id,
                reference.student_id,
                reference.standard_id,
                reference.result_revision,
            )
        except AcademicPeriodProficiencyStorageError as error:
            raise HybridGradeResultDependencyError(
                "Exact Academic Period proficiency result is unavailable for "
                "hybrid result selection."
            ) from error
        if result.result_sha256 != reference.result_sha256:
            raise HybridGradeResultDependencyError(
                "Exact Academic Period proficiency result digest does not match "
                "hybrid provenance."
            )


def _result_pointer(stored: StoredHybridGradeResult) -> dict[str, object]:
    value = stored.snapshot
    return {
        "schema_version": HYBRID_GRADE_RESULT_CURRENT_SCHEMA_VERSION,
        "record_type": HYBRID_GRADE_RESULT_CURRENT_RECORD_TYPE,
        "class_id": value.class_id,
        "student_id": value.student_id,
        "school_year": value.target_period.school_year,
        "period_id": value.target_period.period_id,
        "calendar_revision": value.calendar_revision,
        "subject_key": hybrid_grade_subject_key(
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
    family = hybrid_grade_result_family_directory(
        root,
        class_value,
        student,
        period,
        calendar,
    )
    if not family.exists():
        if missing_ok:
            return None
        raise HybridGradeStorageNotFoundError(
            "Hybrid Grade result family does not exist."
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
        raise HybridGradeStorageNotFoundError(
            "Hybrid Grade result has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_HYBRID_GRADE_POINTER_BYTES,
        missing_message="Hybrid Grade result current pointer is absent.",
    )
    decoded = _decode_pointer(content)
    expected = {
        "class_id": class_value,
        "student_id": student,
        "school_year": period.school_year,
        "period_id": period.period_id,
        "calendar_revision": calendar,
        "subject_key": hybrid_grade_subject_key(
            class_value,
            student,
            period,
            calendar,
        ),
    }
    for key, value in expected.items():
        if decoded[key] != value:
            raise HybridGradeStorageIntegrityError(
                "Current result pointer identity does not match canonical path."
            )
    return decoded


def _decode_pointer(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer must be valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except HybridGradeStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer must be valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer does not use the exact schema."
        )
    if decoded["schema_version"] != HYBRID_GRADE_RESULT_CURRENT_SCHEMA_VERSION:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer schema_version is unsupported."
        )
    if decoded["record_type"] != HYBRID_GRADE_RESULT_CURRENT_RECORD_TYPE:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer record_type is invalid."
        )
    try:
        for key in ("class_id", "student_id", "school_year", "period_id"):
            decoded[key] = _identifier(decoded[key], key)
        decoded["calendar_revision"] = _positive_int(
            decoded["calendar_revision"], "calendar_revision"
        )
        decoded["subject_key"] = _sha256(decoded["subject_key"], "subject_key")
        decoded["result_revision"] = _positive_int(
            decoded["result_revision"], "result_revision"
        )
        decoded["result_sha256"] = _sha256(
            decoded["result_sha256"], "result_sha256"
        )
    except HybridGradeStorageValidationError as error:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer contains invalid persisted field values."
        ) from error
    if _canonical_json_bytes(decoded) != data:
        raise HybridGradeStorageIntegrityError(
            "Current result pointer is not canonically encoded."
        )
    return cast(dict[str, object], decoded)


def _load_existing_for_replay(
    root: Path,
    snapshot: HybridGradeResultSnapshot,
) -> StoredHybridGradeResult:
    try:
        return load_hybrid_grade_result_revision(
            root,
            snapshot.class_id,
            snapshot.student_id,
            snapshot.target_period,
            snapshot.calendar_revision,
            snapshot.result_revision,
        )
    except HybridGradeStorageError as error:
        raise HybridGradeStorageIntegrityError(
            "Existing hybrid Grade result identity is incomplete or invalid."
        ) from error


def _validate_result_ancestor_shape_values(
    root: Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> None:
    family = hybrid_grade_result_family_directory(
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
        raise HybridGradeStorageReadError(
            "Could not inspect hybrid Grade student result collection."
        ) from error
    for entry in entries:
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or _SHA256.fullmatch(entry.name) is None
        ):
            raise HybridGradeStorageIntegrityError(
                "Student result collection contains an unexpected entry."
            )


def _validate_result_family_directory(family: Path) -> None:
    if not family.exists():
        raise HybridGradeStorageNotFoundError(
            "Hybrid Grade result family does not exist."
        )
    if family.is_symlink() or not family.is_dir():
        raise HybridGradeStorageIntegrityError(
            "Hybrid Grade result family is not a regular directory."
        )
    allowed = {"current.json", "revisions", ".write.lock"}
    try:
        entries = tuple(family.iterdir())
    except OSError as error:
        raise HybridGradeStorageReadError(
            "Could not inspect hybrid Grade result family."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise HybridGradeStorageIntegrityError(
                "Hybrid Grade result family contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise HybridGradeStorageIntegrityError(
                    "Result revisions entry must be a regular directory."
                )
        elif entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise HybridGradeStorageIntegrityError(
                    "Result write lock must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise HybridGradeStorageIntegrityError(
                "Current result pointer must be a regular file."
            )
    revisions = family / "revisions"
    if revisions.exists():
        _revision_sets(revisions)


def _revision_sets(revisions_dir: Path) -> tuple[set[int], set[int]]:
    if revisions_dir.is_symlink() or not revisions_dir.is_dir():
        raise HybridGradeStorageIntegrityError(
            "Result revisions path must be a regular directory."
        )
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise HybridGradeStorageReadError(
            "Could not inspect hybrid Grade result revisions."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise HybridGradeStorageIntegrityError(
                "Result revisions contain a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise HybridGradeStorageIntegrityError(
                "Result revisions contain an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise HybridGradeStorageIntegrityError(
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
        missing_message="Hybrid Grade result revision does not exist.",
    )
    digest_data = _read_bounded_regular_file(
        Path(str(path) + ".sha256"),
        DEFAULT_MAXIMUM_HYBRID_GRADE_DIGEST_BYTES,
        missing_message="Hybrid Grade result digest does not exist.",
    )
    try:
        digest_text = digest_data.decode("ascii")
    except UnicodeDecodeError as error:
        raise HybridGradeStorageIntegrityError(
            "Result digest sidecar must be ASCII."
        ) from error
    if (
        len(digest_text) != 65
        or not digest_text.endswith("\n")
        or digest_text.count("\n") != 1
        or _SHA256.fullmatch(digest_text[:-1]) is None
    ):
        raise HybridGradeStorageIntegrityError(
            "Result digest sidecar must contain exactly lowercase SHA-256 text "
            "and one trailing LF."
        )
    digest = digest_text[:-1]
    if hashlib.sha256(content).hexdigest() != digest:
        raise HybridGradeStorageIntegrityError(
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
        raise HybridGradeStorageNotFoundError(missing_message)
    if path.is_symlink():
        raise HybridGradeStorageIntegrityError(
            "Canonical hybrid Grade state must not be symlinked."
        )
    try:
        info = path.stat()
    except OSError as error:
        raise HybridGradeStorageReadError(
            "Could not stat hybrid Grade state."
        ) from error
    if not stat.S_ISREG(info.st_mode):
        raise HybridGradeStorageIntegrityError(
            "Canonical hybrid Grade state must be a regular file."
        )
    if info.st_size > maximum_bytes:
        raise HybridGradeStorageTooLargeError(
            "Hybrid Grade state exceeds the configured read bound."
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise HybridGradeStorageReadError(
            "Could not read hybrid Grade state."
        ) from error


def _write_revision_pair(
    target: Path,
    digest_target: Path,
    content: bytes,
    digest: str,
) -> None:
    if target.exists() or digest_target.exists():
        raise HybridGradeStorageConflictError(
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
        raise HybridGradeStorageConflictError(
            "Concurrent writer created the result revision identity."
        ) from error
    except OSError as error:
        if created_digest:
            digest_target.unlink(missing_ok=True)
        if created_target:
            target.unlink(missing_ok=True)
        raise HybridGradeStorageWriteError(
            "Could not persist hybrid Grade result revision."
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
        raise HybridGradeStorageWriteError(
            "Could not atomically publish current result selection."
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _acquire_lock(path: Path) -> None:
    if path.is_symlink():
        raise HybridGradeStorageIntegrityError(
            "Hybrid Grade result lock path must not be a symlink."
        )
    if path.exists():
        raise HybridGradeStorageLockError(
            "Hybrid Grade result history is locked by another writer."
        )
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise HybridGradeStorageLockError(
            "Hybrid Grade result history is locked by another writer."
        ) from error
    except OSError as error:
        raise HybridGradeStorageWriteError(
            "Could not acquire hybrid Grade result lock."
        ) from error
    os.close(descriptor)


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise HybridGradeStorageWriteError(
            "Could not release hybrid Grade result lock."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    try:
        relative = target.relative_to(root)
    except ValueError as error:
        raise HybridGradeStorageValidationError(
            "Target path escapes workspace root."
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise HybridGradeStorageIntegrityError(
                    "Canonical directory chain contains a non-directory or symlink."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise HybridGradeStorageWriteError(
                    "Could not create hybrid Grade storage directory."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if not target.exists():
        raise HybridGradeStorageNotFoundError(
            "Expected hybrid Grade storage directory does not exist."
        )
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise HybridGradeStorageIntegrityError(
                "Canonical directory chain contains a non-directory or symlink."
            )


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, _identifier(class_id, "class_id"))
    _require_containment(root, path)
    if not path.exists() or path.is_symlink() or not path.is_dir():
        raise HybridGradeResultDependencyError(
            "Exact Core class directory is unavailable."
        )


def _root(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise HybridGradeStorageValidationError(
            "workspace_root must identify an existing directory."
        ) from error
    if not resolved.is_dir():
        raise HybridGradeStorageValidationError(
            "workspace_root must identify a directory."
        )
    return resolved


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise HybridGradeStorageValidationError(
            "Canonical hybrid Grade path escapes workspace root."
        ) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise HybridGradeStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise HybridGradeStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridGradeStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _period(value: AcademicPeriodRef) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise HybridGradeStorageValidationError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except ValueError as error:
        raise HybridGradeStorageValidationError(str(error)) from error


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HybridGradeStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
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
        raise HybridGradeStorageValidationError(
            "Value cannot be encoded as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HybridGradeStorageIntegrityError(
                f"Current result pointer contains duplicate key: {key}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise HybridGradeStorageIntegrityError(
        f"Current result pointer contains invalid JSON constant: {value}."
    )


__all__ = [
    "DEFAULT_MAXIMUM_HYBRID_GRADE_DIGEST_BYTES",
    "DEFAULT_MAXIMUM_HYBRID_GRADE_POINTER_BYTES",
    "DEFAULT_MAXIMUM_HYBRID_GRADE_RESULT_BYTES",
    "HYBRID_GRADE_RESULT_CURRENT_RECORD_TYPE",
    "HYBRID_GRADE_RESULT_CURRENT_SCHEMA_VERSION",
    "HybridGradeResultDependencyError",
    "HybridGradeResultSelectionResult",
    "HybridGradeResultWriteResult",
    "HybridGradeStorageConflictError",
    "HybridGradeStorageError",
    "HybridGradeStorageIntegrityError",
    "HybridGradeStorageLockError",
    "HybridGradeStorageNotFoundError",
    "HybridGradeStorageReadError",
    "HybridGradeStorageTooLargeError",
    "HybridGradeStorageValidationError",
    "HybridGradeStorageWriteError",
    "StoredHybridGradeResult",
    "get_current_hybrid_grade_result_revision",
    "hybrid_grade_result_current_path",
    "hybrid_grade_result_family_directory",
    "hybrid_grade_result_revision_path",
    "hybrid_grade_result_revision_relative_path",
    "hybrid_grade_subject_key",
    "hybrid_grades_directory",
    "list_hybrid_grade_result_revisions",
    "load_current_hybrid_grade_result",
    "load_hybrid_grade_result_revision",
    "select_hybrid_grade_result_revision",
    "write_hybrid_grade_result_revision",
]
