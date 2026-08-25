"""Canonical storage and Core-backed validation for Grade Item membership."""

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
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    load_academic_work_registration_revision,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import (
    ClassMetadata,
    ClassMetadataError,
    load_class_metadata,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_metadata_path
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    module_work_ref_from_dict,
    module_work_ref_to_dict,
    validate_module_work_ref,
)

from meridian.grade_item_memberships import (
    GradeItemMembershipDecision,
    GradeItemMembershipSerializationError,
    GradeItemMembershipValidationError,
    grade_item_membership_decision_from_json_bytes,
    grade_item_membership_decision_to_json_bytes,
    validate_grade_item_membership_decision,
    validate_grade_item_membership_transition,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    StoredGradeItemRevision,
    grade_item_directory,
    list_grade_item_revisions,
    load_grade_item_revision,
)

GRADE_ITEM_MEMBERSHIP_CURRENT_SCHEMA_VERSION: Final[str] = "1"
GRADE_ITEM_MEMBERSHIP_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_grade_item_membership_current"
)
DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_REVISION_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_DIGEST_BYTES: Final[int] = 128

GradeItemMembershipWriteDisposition: TypeAlias = Literal["created", "existing"]
GradeItemMembershipSelectionDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
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
        "grade_item_id",
        "work",
        "membership_revision",
        "decision_sha256",
    }
)


class GradeItemMembershipStorageError(RuntimeError):
    """Base error for Grade Item membership persistence failures."""

    code: str = "grade_item_memberships.storage_error"


class GradeItemMembershipStorageValidationError(
    GradeItemMembershipStorageError, ValueError
):
    """Raised for invalid membership storage API arguments."""

    code = "grade_item_memberships.storage_invalid"


class GradeItemMembershipStorageNotFoundError(GradeItemMembershipStorageError):
    """Raised when explicitly requested membership state is absent."""

    code = "grade_item_memberships.not_found"


class GradeItemMembershipStorageReadError(GradeItemMembershipStorageError):
    """Raised when membership state cannot be read safely."""

    code = "grade_item_memberships.read_failed"


class GradeItemMembershipStorageWriteError(GradeItemMembershipStorageError):
    """Raised when membership state cannot be written safely."""

    code = "grade_item_memberships.write_failed"


class GradeItemMembershipStorageConflictError(GradeItemMembershipStorageError):
    """Raised for stale writes or identity/content collisions."""

    code = "grade_item_memberships.conflict"


class GradeItemMembershipStorageLockError(GradeItemMembershipStorageConflictError):
    """Raised when another writer owns one membership relationship."""

    code = "grade_item_memberships.locked"


class GradeItemMembershipStorageIntegrityError(GradeItemMembershipStorageError):
    """Raised when canonical paths, bytes, digests, or identities disagree."""

    code = "grade_item_memberships.integrity"


class GradeItemMembershipStorageTooLargeError(GradeItemMembershipStorageReadError):
    """Raised before a membership file can be read without a finite bound."""

    code = "grade_item_memberships.too_large"


class GradeItemMembershipDependencyError(GradeItemMembershipStorageError):
    """Raised when an exact Grade Item/Core dependency cannot be validated."""

    code = "grade_item_memberships.dependency_invalid"


@dataclass(frozen=True, slots=True)
class GradeItemMembershipDependencies:
    """Exact authoritative dependencies resolved for one membership decision."""

    grade_item: StoredGradeItemRevision
    class_metadata: ClassMetadata
    registration: AcademicWorkRegistration
    calendar: AcademicPeriodCalendar | None
    period: AcademicPeriod | None

    def __post_init__(self) -> None:
        if self.registration.work.class_id != self.class_metadata.class_id:
            raise GradeItemMembershipStorageValidationError(
                "registration and class metadata identities must agree."
            )
        if (self.calendar is None) != (self.period is None):
            raise GradeItemMembershipStorageValidationError(
                "calendar and period must either both be present or both be absent."
            )


@dataclass(frozen=True, slots=True)
class StoredGradeItemMembershipDecision:
    """One verified immutable membership decision and its exact stored bytes."""

    decision: GradeItemMembershipDecision
    decision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, GradeItemMembershipDecision):
            raise GradeItemMembershipStorageValidationError(
                "decision must be a GradeItemMembershipDecision."
            )
        digest = _sha256(self.decision_sha256, "decision_sha256")
        if type(self.content) is not bytes:
            raise GradeItemMembershipStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise GradeItemMembershipStorageValidationError(
                "decision_sha256 does not match exact stored bytes."
            )
        try:
            decoded = grade_item_membership_decision_from_json_bytes(self.content)
        except (
            GradeItemMembershipSerializationError,
            GradeItemMembershipValidationError,
        ) as error:
            raise GradeItemMembershipStorageValidationError(
                "content is not a canonical membership decision."
            ) from error
        if decoded != self.decision:
            raise GradeItemMembershipStorageValidationError(
                "content does not decode to decision."
            )
        if grade_item_membership_decision_to_json_bytes(self.decision) != self.content:
            raise GradeItemMembershipStorageValidationError(
                "content is not the canonical encoding of decision."
            )
        expected = grade_item_membership_revision_relative_path(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.work_reference.work,
            self.decision.membership_revision,
        )
        if self.relative_path != expected:
            raise GradeItemMembershipStorageValidationError(
                "relative_path is not the canonical membership revision location."
            )
        if self.path.name != f"{self.decision.membership_revision}.json":
            raise GradeItemMembershipStorageValidationError(
                "path filename does not match membership revision identity."
            )
        object.__setattr__(self, "decision_sha256", digest)


@dataclass(frozen=True, slots=True)
class GradeItemMembershipRevisionWriteResult:
    """Result of immutable membership-revision persistence."""

    disposition: GradeItemMembershipWriteDisposition
    stored: StoredGradeItemMembershipDecision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise GradeItemMembershipStorageValidationError(
                "write disposition is invalid."
            )
        if not isinstance(self.stored, StoredGradeItemMembershipDecision):
            raise GradeItemMembershipStorageValidationError(
                "stored must be a StoredGradeItemMembershipDecision."
            )


@dataclass(frozen=True, slots=True)
class GradeItemMembershipCurrentSelection:
    """Explicit mutable selector for one persisted membership decision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    membership_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_ITEM_MEMBERSHIP_CURRENT_SCHEMA_VERSION:
            raise GradeItemMembershipStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != GRADE_ITEM_MEMBERSHIP_CURRENT_RECORD_TYPE:
            raise GradeItemMembershipStorageValidationError(
                'current record_type must be "meridian_grade_item_membership_current".'
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(self, "work", _work(self.work))
        if self.work.class_id != class_id:
            raise GradeItemMembershipStorageValidationError(
                "current work.class_id must match class_id."
            )
        object.__setattr__(
            self,
            "membership_revision",
            _positive_int(self.membership_revision, "membership_revision"),
        )
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GradeItemMembershipSelectionResult:
    """Result of explicit membership-revision selection."""

    disposition: GradeItemMembershipSelectionDisposition
    selection: GradeItemMembershipCurrentSelection
    stored: StoredGradeItemMembershipDecision
    dependencies: GradeItemMembershipDependencies

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "updated", "existing"}:
            raise GradeItemMembershipStorageValidationError(
                "selection disposition is invalid."
            )
        if not isinstance(self.selection, GradeItemMembershipCurrentSelection):
            raise GradeItemMembershipStorageValidationError(
                "selection must be a GradeItemMembershipCurrentSelection."
            )
        if not isinstance(self.stored, StoredGradeItemMembershipDecision):
            raise GradeItemMembershipStorageValidationError(
                "stored must be a StoredGradeItemMembershipDecision."
            )
        decision = self.stored.decision
        if (
            self.selection.class_id != decision.class_id
            or self.selection.grade_item_id != decision.grade_item_id
            or self.selection.work != decision.work_reference.work
            or self.selection.membership_revision != decision.membership_revision
        ):
            raise GradeItemMembershipStorageValidationError(
                "selection identity must match stored membership identity."
            )
        if self.selection.decision_sha256 != self.stored.decision_sha256:
            raise GradeItemMembershipStorageValidationError(
                "selection digest must match stored decision digest."
            )


def grade_item_memberships_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> Path:
    """Return one Grade Item's canonical membership collection."""
    return grade_item_directory(
        _root(workspace_root),
        _identifier(class_id, "class_id"),
        _identifier(grade_item_id, "grade_item_id"),
    ) / "memberships"


def grade_item_membership_module_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    module_id: str,
) -> Path:
    """Return one producer module's membership collection for a Grade Item."""
    module = _identifier(module_id, "module_id")
    if module != module.lower():
        raise GradeItemMembershipStorageValidationError(
            "module_id must be lowercase."
        )
    return grade_item_memberships_directory(
        workspace_root, class_id, grade_item_id
    ) / module


def grade_item_membership_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    """Return one logical Grade Item/work membership relationship root."""
    validated = _work(work)
    class_value = _identifier(class_id, "class_id")
    if validated.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    return grade_item_membership_module_directory(
        workspace_root,
        class_value,
        grade_item_id,
        validated.module_id,
    ) / validated.work_id


def grade_item_membership_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    """Return one membership relationship's immutable revision collection."""
    return grade_item_membership_directory(
        workspace_root, class_id, grade_item_id, work
    ) / "revisions"


def grade_item_membership_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
) -> Path:
    """Return the canonical JSON path for one membership revision."""
    revision = _positive_int(membership_revision, "membership_revision")
    return grade_item_membership_revisions_directory(
        workspace_root, class_id, grade_item_id, work
    ) / f"{revision}.json"


def grade_item_membership_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
) -> Path:
    """Return the exact SHA-256 sidecar path for a membership revision."""
    return Path(
        str(
            grade_item_membership_revision_path(
                workspace_root,
                class_id,
                grade_item_id,
                work,
                membership_revision,
            )
        )
        + ".sha256"
    )


def grade_item_membership_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    """Return one membership relationship's explicit current pointer path."""
    return grade_item_membership_directory(
        workspace_root, class_id, grade_item_id, work
    ) / "current.json"


def grade_item_membership_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
) -> str:
    """Return the workspace-relative canonical membership revision path."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated = _work(work)
    if validated.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    revision = _positive_int(membership_revision, "membership_revision")
    return (
        f"classes/{class_value}/modules/meridian/grade_items/{item}/memberships/"
        f"{validated.module_id}/{validated.work_id}/revisions/{revision}.json"
    )


def validate_grade_item_membership_dependencies(
    workspace_root: str | Path,
    decision: GradeItemMembershipDecision,
) -> GradeItemMembershipDependencies:
    """Resolve and validate every exact Core/Grade Item dependency."""
    candidate = validate_grade_item_membership_decision(decision)
    root = _root(workspace_root)
    try:
        grade_item = load_grade_item_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise GradeItemMembershipDependencyError(
            f"Exact Grade Item revision could not be validated: {error}"
        ) from error
    if grade_item.revision_sha256 != candidate.grade_item_revision_sha256:
        raise GradeItemMembershipDependencyError(
            "Grade Item revision SHA-256 does not match the membership decision."
        )
    if candidate.decision == "included" and grade_item.revision.status == "archived":
        raise GradeItemMembershipDependencyError(
            "An included membership cannot target an archived Grade Item revision."
        )

    metadata_path = class_metadata_path(root, candidate.class_id)
    try:
        metadata = load_class_metadata(metadata_path)
    except ClassMetadataError as error:
        raise GradeItemMembershipDependencyError(
            f"Core class metadata could not be validated: {error}"
        ) from error
    if metadata.class_id != candidate.class_id:
        raise GradeItemMembershipDependencyError(
            "Core class metadata identity does not match membership class_id."
        )

    work_reference = candidate.work_reference
    try:
        registration = load_academic_work_registration_revision(
            root,
            work_reference.work,
            work_reference.registration_revision,
        )
    except AcademicWorkRegistrationStorageError as error:
        raise GradeItemMembershipDependencyError(
            f"Exact Academic Work Registration could not be validated: {error}"
        ) from error
    if (
        registration.work != work_reference.work
        or registration.registration_revision != work_reference.registration_revision
    ):
        raise GradeItemMembershipDependencyError(
            "Academic Work Registration identity does not match membership reference."
        )
    if registration.work.class_id != candidate.class_id:
        raise GradeItemMembershipDependencyError(
            "Academic Work Registration class does not match membership class."
        )
    if candidate.decision == "included" and registration.lifecycle == "cancelled":
        raise GradeItemMembershipDependencyError(
            "An included membership cannot target a cancelled registration revision."
        )

    calendar: AcademicPeriodCalendar | None = None
    period: AcademicPeriod | None = None
    if candidate.decision == "included":
        assignment = candidate.academic_period
        if assignment is None:  # defensive; model validation already enforces this.
            raise GradeItemMembershipDependencyError(
                "Included membership requires an Academic Period assignment."
            )
        if assignment.period.school_year != metadata.school_year:
            raise GradeItemMembershipDependencyError(
                "Academic Period school_year does not match the Core class school_year."
            )
        try:
            calendar = load_academic_period_calendar_revision(
                root,
                assignment.period.school_year,
                assignment.calendar_revision,
            )
        except AcademicPeriodCalendarStorageError as error:
            raise GradeItemMembershipDependencyError(
                "Exact Academic Period Calendar revision could not be validated: "
                f"{error}"
            ) from error
        if calendar.school_year != assignment.period.school_year:
            raise GradeItemMembershipDependencyError(
                "Academic Period Calendar school_year does not match assignment."
            )
        try:
            period = get_academic_period(calendar, assignment.period.period_id)
        except AcademicPeriodLookupError as error:
            raise GradeItemMembershipDependencyError(
                "Academic Period does not exist in the referenced calendar revision."
            ) from error
        if period.lifecycle == "cancelled":
            raise GradeItemMembershipDependencyError(
                "An included membership cannot target a cancelled Academic Period."
            )

    return GradeItemMembershipDependencies(
        grade_item=grade_item,
        class_metadata=metadata,
        registration=registration,
        calendar=calendar,
        period=period,
    )


def load_grade_item_membership_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_REVISION_BYTES,
) -> StoredGradeItemMembershipDecision:
    """Load and verify one exact immutable membership revision."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    revision_number = _positive_int(membership_revision, "membership_revision")
    root = _root(workspace_root)
    path = grade_item_membership_revision_path(
        root, class_value, item, validated_work, revision_number
    )
    digest_path = grade_item_membership_revision_digest_path(
        root, class_value, item, validated_work, revision_number
    )
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path,
        maximum_revision_bytes,
        missing_message="Grade Item membership revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_DIGEST_BYTES,
        missing_message="Grade Item membership revision digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership revision digest does not match exact JSON bytes."
        )
    try:
        decision = grade_item_membership_decision_from_json_bytes(content)
    except (
        GradeItemMembershipSerializationError,
        GradeItemMembershipValidationError,
    ) as error:
        raise GradeItemMembershipStorageIntegrityError(
            f"Membership revision is invalid or noncanonical: {error}"
        ) from error
    if decision.class_id != class_value:
        raise GradeItemMembershipStorageIntegrityError(
            "Persisted membership class_id does not match its canonical path."
        )
    if decision.grade_item_id != item:
        raise GradeItemMembershipStorageIntegrityError(
            "Persisted membership Grade Item identity does not match its "
            "canonical path."
        )
    if decision.work_reference.work != validated_work:
        raise GradeItemMembershipStorageIntegrityError(
            "Persisted membership work identity does not match its canonical path."
        )
    if decision.membership_revision != revision_number:
        raise GradeItemMembershipStorageIntegrityError(
            "Persisted membership revision does not match its canonical path."
        )
    return StoredGradeItemMembershipDecision(
        decision=decision,
        decision_sha256=actual_digest,
        path=path,
        relative_path=grade_item_membership_revision_relative_path(
            class_value, item, validated_work, revision_number
        ),
        content=content,
    )


def list_grade_item_membership_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> tuple[int, ...]:
    """List and verify contiguous membership revisions in numeric order."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    root = _root(workspace_root)
    relation = grade_item_membership_directory(
        root, class_value, item, validated_work
    )
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_membership_directory_entries(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise GradeItemMembershipStorageReadError(
            "Could not enumerate membership revision storage."
        ) from error
    for entry in entries:
        if entry.is_symlink():
            raise GradeItemMembershipStorageIntegrityError(
                "Membership revision storage contains a symlink."
            )
        if not entry.is_file():
            raise GradeItemMembershipStorageIntegrityError(
                "Membership revision storage contains a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise GradeItemMembershipStorageIntegrityError(
                "Membership revision storage contains an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership revision JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise GradeItemMembershipStorageIntegrityError(
            "Membership revision history is not contiguous from revision 1."
        )
    previous: GradeItemMembershipDecision | None = None
    for number in revisions:
        stored = load_grade_item_membership_revision(
            root, class_value, item, validated_work, number
        )
        if previous is not None:
            try:
                validate_grade_item_membership_transition(previous, stored.decision)
            except GradeItemMembershipValidationError as error:
                raise GradeItemMembershipStorageIntegrityError(
                    f"Membership revision history is invalid: {error}"
                ) from error
        previous = stored.decision
    return revisions


def list_grade_item_membership_work_refs(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> tuple[ModuleWorkRef, ...]:
    """List all logical Grade Item/work relationships deterministically."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    root = _root(workspace_root)
    collection = grade_item_memberships_directory(root, class_value, item)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    refs: list[ModuleWorkRef] = []
    for module_entry in _visible_directories(collection, "membership module"):
        try:
            module_id = _identifier(module_entry.name, "module_id")
        except GradeItemMembershipStorageValidationError as error:
            raise GradeItemMembershipStorageIntegrityError(
                "Membership module directory identity is invalid."
            ) from error
        if module_id != module_id.lower():
            raise GradeItemMembershipStorageIntegrityError(
                "Membership module directory must use lowercase module_id."
            )
        for work_entry in _visible_directories(module_entry, "membership work"):
            try:
                work_id = _identifier(work_entry.name, "work_id")
                work = _work(
                    ModuleWorkRef(
                        module_id=module_id,
                        class_id=class_value,
                        work_id=work_id,
                    )
                )
            except GradeItemMembershipStorageValidationError as error:
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership work directory identity is invalid."
                ) from error
            _validate_membership_directory_entries(work_entry)
            revisions = list_grade_item_membership_revisions(
                root, class_value, item, work
            )
            if not revisions:
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership relationship exists without immutable revision history."
                )
            refs.append(work)
    return tuple(
        sorted(refs, key=lambda value: (value.module_id, value.work_id))
    )


def write_grade_item_membership_revision(
    workspace_root: str | Path,
    decision: GradeItemMembershipDecision,
) -> GradeItemMembershipRevisionWriteResult:
    """Persist one immutable membership revision without selecting it."""
    candidate = validate_grade_item_membership_decision(decision)
    root = _root(workspace_root)
    _require_existing_grade_item(root, candidate.class_id, candidate.grade_item_id)
    validated_work = candidate.work_reference.work
    validate_grade_item_membership_dependencies(root, candidate)
    relation = grade_item_membership_directory(
        root, candidate.class_id, candidate.grade_item_id, validated_work
    )
    revisions_dir = relation / "revisions"
    _ensure_directory_chain(root, revisions_dir)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_membership_directory_entries(relation)
        content = grade_item_membership_decision_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_REVISION_BYTES:
            raise GradeItemMembershipStorageWriteError(
                "Membership revision exceeds the canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()
        target = grade_item_membership_revision_path(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            validated_work,
            candidate.membership_revision,
        )
        digest_target = grade_item_membership_revision_digest_path(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            validated_work,
            candidate.membership_revision,
        )
        if target.exists() or digest_target.exists():
            try:
                stored = load_grade_item_membership_revision(
                    root,
                    candidate.class_id,
                    candidate.grade_item_id,
                    validated_work,
                    candidate.membership_revision,
                )
            except GradeItemMembershipStorageError as error:
                raise GradeItemMembershipStorageIntegrityError(
                    "Existing membership revision identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.decision_sha256 != digest:
                raise GradeItemMembershipStorageConflictError(
                    "Membership revision identity already exists with different "
                    "content."
                )
            return GradeItemMembershipRevisionWriteResult(
                disposition="existing",
                stored=stored,
            )

        history = list_grade_item_membership_revisions(
            root, candidate.class_id, candidate.grade_item_id, validated_work
        )
        if not history:
            if candidate.membership_revision != 1:
                raise GradeItemMembershipStorageConflictError(
                    "Initial membership revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.membership_revision != expected:
                raise GradeItemMembershipStorageConflictError(
                    "Membership revision must be exactly one greater than current "
                    "history."
                )
            previous = load_grade_item_membership_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                validated_work,
                history[-1],
            ).decision
            try:
                validate_grade_item_membership_transition(previous, candidate)
            except GradeItemMembershipValidationError as error:
                raise GradeItemMembershipStorageConflictError(str(error)) from error

        _write_revision_pair_exclusively(target, digest_target, content, digest)
        stored = load_grade_item_membership_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            validated_work,
            candidate.membership_revision,
        )
        if stored.content != content or stored.decision_sha256 != digest:
            raise GradeItemMembershipStorageIntegrityError(
                "Persisted membership revision differs from candidate bytes."
            )
        return GradeItemMembershipRevisionWriteResult(
            disposition="created", stored=stored
        )
    finally:
        _remove_lock(lock)


def get_current_grade_item_membership_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> int | None:
    """Return only the explicitly selected membership revision number."""
    selection = _load_current_selection(
        workspace_root, class_id, grade_item_id, work, missing_ok=True
    )
    return selection.membership_revision if selection is not None else None


def load_current_grade_item_membership_decision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> StoredGradeItemMembershipDecision | None:
    """Load the explicitly selected membership revision and verify its digest."""
    selection = _load_current_selection(
        workspace_root, class_id, grade_item_id, work, missing_ok=True
    )
    if selection is None:
        return None
    stored = load_grade_item_membership_revision(
        workspace_root,
        selection.class_id,
        selection.grade_item_id,
        selection.work,
        selection.membership_revision,
    )
    if stored.decision_sha256 != selection.decision_sha256:
        raise GradeItemMembershipStorageIntegrityError(
            "Current membership pointer digest does not match selected revision."
        )
    return stored


def select_grade_item_membership_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    membership_revision: int,
    *,
    expected_current_membership_revision: int | None,
) -> GradeItemMembershipSelectionResult:
    """Explicitly select one persisted membership revision with CAS protection."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    revision_number = _positive_int(membership_revision, "membership_revision")
    expected = (
        None
        if expected_current_membership_revision is None
        else _positive_int(
            expected_current_membership_revision,
            "expected_current_membership_revision",
        )
    )
    root = _root(workspace_root)
    relation = grade_item_membership_directory(
        root, class_value, item, validated_work
    )
    _validate_existing_directory_chain(root, relation)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_membership_directory_entries(relation)
        target = load_grade_item_membership_revision(
            root, class_value, item, validated_work, revision_number
        )
        dependencies = validate_grade_item_membership_dependencies(
            root, target.decision
        )
        current = _load_current_selection(
            root, class_value, item, validated_work, missing_ok=True
        )
        current_revision = (
            current.membership_revision if current is not None else None
        )
        if current_revision != expected:
            raise GradeItemMembershipStorageConflictError(
                "Expected current membership revision does not match stored selection."
            )
        selection = GradeItemMembershipCurrentSelection(
            schema_version=GRADE_ITEM_MEMBERSHIP_CURRENT_SCHEMA_VERSION,
            record_type=GRADE_ITEM_MEMBERSHIP_CURRENT_RECORD_TYPE,
            class_id=class_value,
            grade_item_id=item,
            work=validated_work,
            membership_revision=revision_number,
            decision_sha256=target.decision_sha256,
        )
        if current == selection:
            return GradeItemMembershipSelectionResult(
                disposition="existing",
                selection=selection,
                stored=target,
                dependencies=dependencies,
            )
        _publish_current_selection(root, selection)
        verified = _load_current_selection(
            root, class_value, item, validated_work, missing_ok=False
        )
        if verified != selection:
            raise GradeItemMembershipStorageIntegrityError(
                "Published membership selection could not be verified."
            )
        disposition: GradeItemMembershipSelectionDisposition = (
            "created" if current is None else "updated"
        )
        return GradeItemMembershipSelectionResult(
            disposition=disposition,
            selection=selection,
            stored=target,
            dependencies=dependencies,
        )
    finally:
        _remove_lock(lock)


def list_selected_included_grade_item_memberships(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> tuple[StoredGradeItemMembershipDecision, ...]:
    """Return explicitly selected included relationships in deterministic order."""
    included: list[StoredGradeItemMembershipDecision] = []
    for work in list_grade_item_membership_work_refs(
        workspace_root, class_id, grade_item_id
    ):
        stored = load_current_grade_item_membership_decision(
            workspace_root, class_id, grade_item_id, work
        )
        if stored is not None and stored.decision.decision == "included":
            included.append(stored)
    return tuple(
        sorted(
            included,
            key=lambda value: (
                value.decision.work_reference.work.module_id,
                value.decision.work_reference.work.work_id,
            ),
        )
    )


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    *,
    missing_ok: bool,
) -> GradeItemMembershipCurrentSelection | None:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise GradeItemMembershipStorageValidationError(
            "work.class_id must match class_id."
        )
    root = _root(workspace_root)
    relation = grade_item_membership_directory(
        root, class_value, item, validated_work
    )
    if not relation.exists():
        if missing_ok:
            return None
        raise GradeItemMembershipStorageNotFoundError(
            "Grade Item membership relationship does not exist."
        )
    _validate_existing_directory_chain(root, relation)
    _validate_membership_directory_entries(relation)
    path = relation / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise GradeItemMembershipStorageNotFoundError(
            "Membership relationship has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_GRADE_ITEM_MEMBERSHIP_POINTER_BYTES,
        missing_message="Membership current pointer does not exist.",
    )
    selection = _current_selection_from_json_bytes(content)
    if (
        selection.class_id != class_value
        or selection.grade_item_id != item
        or selection.work != validated_work
    ):
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer identity does not match its canonical path."
        )
    return selection


def _current_selection_to_dict(
    value: GradeItemMembershipCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "work": module_work_ref_to_dict(value.work),
        "membership_revision": value.membership_revision,
        "decision_sha256": value.decision_sha256,
    }


def _current_selection_to_json_bytes(
    value: GradeItemMembershipCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(_current_selection_to_dict(value))


def _current_selection_from_json_bytes(
    data: bytes,
) -> GradeItemMembershipCurrentSelection:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except GradeItemMembershipStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer is not valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer does not use the exact schema."
        )
    try:
        work = module_work_ref_from_dict(decoded["work"])
    except RoutingModelError as error:
        raise GradeItemMembershipStorageIntegrityError(
            f"Membership current pointer work is invalid: {error}"
        ) from error
    try:
        selection = GradeItemMembershipCurrentSelection(
            schema_version=_pointer_str(decoded["schema_version"], "schema_version"),
            record_type=_pointer_str(decoded["record_type"], "record_type"),
            class_id=_pointer_str(decoded["class_id"], "class_id"),
            grade_item_id=_pointer_str(decoded["grade_item_id"], "grade_item_id"),
            work=work,
            membership_revision=_positive_int(
                decoded["membership_revision"], "membership_revision"
            ),
            decision_sha256=_pointer_str(
                decoded["decision_sha256"], "decision_sha256"
            ),
        )
    except GradeItemMembershipStorageValidationError as error:
        raise GradeItemMembershipStorageIntegrityError(
            f"Membership current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer is not canonically encoded."
        )
    return selection


def _publish_current_selection(
    workspace_root: str | Path,
    selection: GradeItemMembershipCurrentSelection,
) -> None:
    path = grade_item_membership_current_path(
        workspace_root,
        selection.class_id,
        selection.grade_item_id,
        selection.work,
    )
    if path.exists() and path.is_symlink():
        raise GradeItemMembershipStorageIntegrityError(
            "Membership current pointer must not be a symlink."
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
        raise GradeItemMembershipStorageWriteError(
            "Could not publish membership current selection."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _write_revision_pair_exclusively(
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
        raise GradeItemMembershipStorageConflictError(
            "Membership revision identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise GradeItemMembershipStorageWriteError(
            "Could not persist membership revision and digest."
        ) from error


def _require_existing_grade_item(root: Path, class_id: str, grade_item_id: str) -> None:
    item = grade_item_directory(root, class_id, grade_item_id)
    if not item.exists():
        raise GradeItemMembershipStorageNotFoundError(
            "Grade Item must exist before membership creation."
        )
    _validate_existing_directory_chain(root, item)
    try:
        revisions = list_grade_item_revisions(root, class_id, grade_item_id)
    except GradeItemStorageError as error:
        raise GradeItemMembershipStorageIntegrityError(
            f"Grade Item history could not be validated: {error}"
        ) from error
    if not revisions:
        raise GradeItemMembershipStorageIntegrityError(
            "Grade Item exists without immutable revision history."
        )


def _validate_membership_directory_entries(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise GradeItemMembershipStorageIntegrityError(
            "Membership relationship root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise GradeItemMembershipStorageReadError(
            "Could not inspect membership relationship root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise GradeItemMembershipStorageIntegrityError(
                "Membership relationship root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership revisions entry must be a real directory."
                )
        elif entry.name == "current.json":
            if entry.is_symlink() or not entry.is_file():
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership current pointer must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise GradeItemMembershipStorageIntegrityError(
                "Membership lock entry must be a regular file."
            )


def _visible_directories(root: Path, label: str) -> tuple[Path, ...]:
    try:
        entries = tuple(root.iterdir())
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise GradeItemMembershipStorageReadError(
            f"Could not enumerate {label} storage."
        ) from error
    result: list[Path] = []
    for entry in sorted(entries, key=lambda item: item.name):
        if entry.name.startswith("."):
            raise GradeItemMembershipStorageIntegrityError(
                f"Unexpected hidden entry in {label} storage."
            )
        if entry.is_symlink() or not entry.is_dir():
            raise GradeItemMembershipStorageIntegrityError(
                f"Unexpected non-directory entry in {label} storage."
            )
        result.append(entry)
    return tuple(result)


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise GradeItemMembershipStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise GradeItemMembershipStorageNotFoundError(
            "Workspace root does not exist."
        )
    if root.is_symlink() or not root.is_dir():
        raise GradeItemMembershipStorageIntegrityError(
            "Workspace root must be a real directory, not a symlink."
        )
    return root


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise GradeItemMembershipStorageWriteError(
                    "Could not create membership directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise GradeItemMembershipStorageNotFoundError(
                "Required membership directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise GradeItemMembershipStorageIntegrityError(
                "Membership directory chain is unsafe."
            )


def _require_lexical_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise GradeItemMembershipStorageValidationError(
            "Membership path escapes the supplied workspace root."
        ) from error


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise GradeItemMembershipStorageIntegrityError(
            "Membership storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise GradeItemMembershipStorageIntegrityError(
                    "Membership storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except GradeItemMembershipStorageError:
        raise
    except FileNotFoundError as error:
        raise GradeItemMembershipStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise GradeItemMembershipStorageReadError(
            "Could not read membership storage file."
        ) from error
    if len(content) > limit:
        raise GradeItemMembershipStorageTooLargeError(
            "Membership storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "decision_sha256")
    except GradeItemMembershipStorageValidationError as error:
        raise GradeItemMembershipStorageIntegrityError(
            "Membership SHA-256 sidecar digest is invalid."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian grade item membership write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise GradeItemMembershipStorageLockError(
            "A membership writer already owns this relationship."
        ) from error
    except OSError as error:
        raise GradeItemMembershipStorageWriteError(
            "Could not acquire membership write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise GradeItemMembershipStorageWriteError(
            "Could not remove membership write lock."
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
        raise GradeItemMembershipStorageValidationError(
            "Membership selection cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradeItemMembershipStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise GradeItemMembershipStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemMembershipStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradeItemMembershipStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeItemMembershipStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradeItemMembershipStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise GradeItemMembershipStorageValidationError(
            "work must be a ModuleWorkRef."
        )
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise GradeItemMembershipStorageValidationError(
            f"work is invalid: {error}"
        ) from error


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemMembershipStorageIntegrityError(
            f"Membership pointer {field_name} must be a string."
        )
    return value
