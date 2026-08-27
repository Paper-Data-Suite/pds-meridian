"""Hardened storage and current resolution for standards-evidence associations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeAlias

from pds_core.class_metadata import (
    ClassMetadata,
    ClassMetadataError,
    load_class_metadata,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_metadata_path
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import (
    StandardDefinition,
    StandardsFrameworkMetadata,
    StandardsLibrary,
    StandardsReadError,
    filter_standards_frameworks,
    find_standard_definition,
    load_workspace_standards_library,
)

from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionStorageError,
    resolve_current_attempt_selection,
)
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    validate_evidence_source_reference,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityDependencyError,
    EvidenceEligibilityStorageError,
    resolve_current_evidence_eligibility,
    validate_authorized_evidence_source,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    StoredGradeItemMembershipDecision,
    grade_item_membership_directory,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    StoredGradeItemRevision,
    load_current_grade_item_revision,
)
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
    map_evidence_item,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_mapping_profile_revision,
    load_proficiency_scale_revision,
)
from meridian.reassessment_storage import (
    ReassessmentStorageError,
    resolve_current_reassessment,
)
from meridian.standards_evidence import (
    MAXIMUM_STANDARD_AGGREGATION_CANDIDATES,
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    ResolvedStandardAggregationCandidate,
    StandardAggregationInputs,
    StandardEvidenceAssociationDecision,
    StandardEvidenceAssociationReference,
    StandardsEvidenceSerializationError,
    StandardsEvidenceValidationError,
    build_standard_aggregation_inputs,
    normalize_standard_id,
    standard_evidence_association_from_json_bytes,
    standard_evidence_association_key,
    standard_evidence_association_to_json_bytes,
    validate_standard_evidence_association_decision,
    validate_standard_evidence_association_transition,
)

if TYPE_CHECKING:
    from meridian.evidence import EvidenceItem
    from meridian.projection_cache import AuthorizedProjectionSnapshot

STANDARD_EVIDENCE_ASSOCIATION_CURRENT_SCHEMA_VERSION: Final[str] = "1"
STANDARD_EVIDENCE_ASSOCIATION_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_standard_evidence_association_current"
)
DEFAULT_MAXIMUM_STANDARD_EVIDENCE_REVISION_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_STANDARD_EVIDENCE_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_STANDARD_EVIDENCE_DIGEST_BYTES: Final[int] = 128

AssociationWriteDisposition: TypeAlias = Literal["created", "existing"]
AssociationSelectionDisposition: TypeAlias = Literal["created", "updated", "existing"]
StandardEvidenceAssociationResolutionStatus: TypeAlias = Literal[
    "no_decision",
    "associated",
    "not_associated",
    "source_unverifiable",
    "standard_unresolved",
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REVISION_JSON: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json$")
_REVISION_DIGEST: Final[re.Pattern[str]] = re.compile(r"^([1-9]\d*)\.json\.sha256$")
_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "association_key",
        "association_revision",
        "decision_sha256",
    }
)


class StandardsEvidenceStorageError(RuntimeError):
    code: str = "standards_evidence.storage_error"


class StandardsEvidenceStorageValidationError(
    StandardsEvidenceStorageError, ValueError
):
    code = "standards_evidence.storage_invalid"


class StandardsEvidenceStorageNotFoundError(StandardsEvidenceStorageError):
    code = "standards_evidence.not_found"


class StandardsEvidenceStorageReadError(StandardsEvidenceStorageError):
    code = "standards_evidence.read_failed"


class StandardsEvidenceStorageWriteError(StandardsEvidenceStorageError):
    code = "standards_evidence.write_failed"


class StandardsEvidenceStorageConflictError(StandardsEvidenceStorageError):
    code = "standards_evidence.conflict"


class StandardsEvidenceStorageLockError(StandardsEvidenceStorageConflictError):
    code = "standards_evidence.locked"


class StandardsEvidenceStorageIntegrityError(StandardsEvidenceStorageError):
    code = "standards_evidence.integrity"


class StandardsEvidenceStorageTooLargeError(StandardsEvidenceStorageReadError):
    code = "standards_evidence.too_large"


class StandardsEvidenceDependencyError(StandardsEvidenceStorageError):
    code = "standards_evidence.dependency_invalid"


@dataclass(frozen=True, slots=True)
class CoreStandardResolution:
    """Current mutable Core diagnostics, excluded from persisted identity."""

    standard: StandardDefinition | None
    frameworks: tuple[StandardsFrameworkMetadata, ...]

    @property
    def resolved(self) -> bool:
        return self.standard is not None

    @property
    def active(self) -> bool | None:
        return self.standard.active if self.standard is not None else None


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationDependencies:
    class_metadata: ClassMetadata
    grade_item: StoredGradeItemRevision
    membership: StoredGradeItemMembershipDecision
    authorized_snapshot: AuthorizedProjectionSnapshot = field(repr=False)
    evidence_item: EvidenceItem = field(repr=False)
    standard_resolution: CoreStandardResolution


@dataclass(frozen=True, slots=True)
class StoredStandardEvidenceAssociationDecision:
    decision: StandardEvidenceAssociationDecision
    decision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, StandardEvidenceAssociationDecision):
            raise StandardsEvidenceStorageValidationError(
                "decision must be a StandardEvidenceAssociationDecision."
            )
        digest = _sha256(self.decision_sha256, "decision_sha256")
        if (
            type(self.content) is not bytes
            or hashlib.sha256(self.content).hexdigest() != digest
        ):
            raise StandardsEvidenceStorageValidationError(
                "decision_sha256 must match exact immutable content."
            )
        try:
            decoded = standard_evidence_association_from_json_bytes(self.content)
        except (
            StandardsEvidenceSerializationError,
            StandardsEvidenceValidationError,
        ) as error:
            raise StandardsEvidenceStorageValidationError(
                "content is not a canonical association decision."
            ) from error
        if decoded != self.decision:
            raise StandardsEvidenceStorageValidationError(
                "association content identity mismatch."
            )
        expected = standard_evidence_association_revision_relative_path(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.source,
            self.decision.standard_id,
            self.decision.association_revision,
        )
        if self.relative_path != expected:
            raise StandardsEvidenceStorageValidationError(
                "relative_path is not the canonical association location."
            )
        object.__setattr__(self, "decision_sha256", digest)

    @property
    def reference(self) -> StandardEvidenceAssociationReference:
        return StandardEvidenceAssociationReference(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.source,
            self.decision.standard_id,
            self.decision.association_revision,
            self.decision_sha256,
        )


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationRevisionWriteResult:
    disposition: AssociationWriteDisposition
    stored: StoredStandardEvidenceAssociationDecision


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationCurrentSelection:
    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    association_key: str
    association_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != STANDARD_EVIDENCE_ASSOCIATION_CURRENT_SCHEMA_VERSION:
            raise StandardsEvidenceStorageValidationError(
                "unsupported association current schema_version."
            )
        if self.record_type != STANDARD_EVIDENCE_ASSOCIATION_CURRENT_RECORD_TYPE:
            raise StandardsEvidenceStorageValidationError(
                "association current record_type is invalid."
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self, "grade_item_id", _identifier(self.grade_item_id, "grade_item_id")
        )
        object.__setattr__(
            self, "association_key", _sha256(self.association_key, "association_key")
        )
        object.__setattr__(
            self,
            "association_revision",
            _positive_int(self.association_revision, "association_revision"),
        )
        object.__setattr__(
            self, "decision_sha256", _sha256(self.decision_sha256, "decision_sha256")
        )


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationSelectionResult:
    disposition: AssociationSelectionDisposition
    selection: StandardEvidenceAssociationCurrentSelection
    stored: StoredStandardEvidenceAssociationDecision


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationResolution:
    status: StandardEvidenceAssociationResolutionStatus
    selected: StoredStandardEvidenceAssociationDecision | None
    reference: StandardEvidenceAssociationReference | None
    basis: Literal["producer_declared", "explicit"] | None
    standard_resolution: CoreStandardResolution
    source_verifiable: bool
    operative_associated: bool

    def __post_init__(self) -> None:
        if self.status not in {
            "no_decision",
            "associated",
            "not_associated",
            "source_unverifiable",
            "standard_unresolved",
        }:
            raise StandardsEvidenceStorageValidationError(
                "association resolution status is invalid."
            )
        if not isinstance(self.standard_resolution, CoreStandardResolution):
            raise StandardsEvidenceStorageValidationError(
                "standard_resolution must be a CoreStandardResolution."
            )
        if type(self.source_verifiable) is not bool:
            raise StandardsEvidenceStorageValidationError(
                "source_verifiable must be a bool."
            )
        if type(self.operative_associated) is not bool:
            raise StandardsEvidenceStorageValidationError(
                "operative_associated must be a bool."
            )
        if self.selected is None:
            if self.reference is not None or self.basis is not None:
                raise StandardsEvidenceStorageValidationError(
                    "unselected resolution must not carry reference or basis."
                )
        else:
            if not isinstance(
                self.selected, StoredStandardEvidenceAssociationDecision
            ):
                raise StandardsEvidenceStorageValidationError(
                    "selected has an invalid type."
                )
            if self.reference != self.selected.reference:
                raise StandardsEvidenceStorageValidationError(
                    "resolution reference must equal selected association reference."
                )
            if self.basis != self.selected.decision.basis:
                raise StandardsEvidenceStorageValidationError(
                    "resolution basis must equal selected association basis."
                )
        if self.status == "no_decision":
            if (
                self.selected is not None
                or not self.source_verifiable
                or not self.standard_resolution.resolved
                or self.operative_associated
            ):
                raise StandardsEvidenceStorageValidationError(
                    "no_decision resolution state is incoherent."
                )
        elif self.status in {"associated", "not_associated"}:
            if (
                self.selected is None
                or self.selected.decision.disposition != self.status
                or not self.source_verifiable
                or not self.standard_resolution.resolved
                or self.operative_associated != (self.status == "associated")
            ):
                raise StandardsEvidenceStorageValidationError(
                    f"{self.status} resolution state is incoherent."
                )
        elif self.status == "source_unverifiable":
            if self.source_verifiable or self.operative_associated:
                raise StandardsEvidenceStorageValidationError(
                    "source_unverifiable resolution state is incoherent."
                )
        elif (
            not self.source_verifiable
            or self.standard_resolution.resolved
            or self.operative_associated
        ):
            raise StandardsEvidenceStorageValidationError(
                "standard_unresolved resolution state is incoherent."
            )


@dataclass(frozen=True, slots=True)
class StandardAggregationCandidateBinding:
    """One explicitly named source and optional exact #32 profile binding."""

    source: EvidenceSourceReference
    authorized_snapshot: AuthorizedProjectionSnapshot = field(repr=False)
    mapping_profile: NativeValueMappingProfileReference | None = None
    attempt: AttemptObservationReference | None = None

    def __post_init__(self) -> None:
        from meridian.projection_cache import AuthorizedProjectionSnapshot

        object.__setattr__(
            self, "source", validate_evidence_source_reference(self.source)
        )
        if not isinstance(self.authorized_snapshot, AuthorizedProjectionSnapshot):
            raise StandardsEvidenceStorageValidationError(
                "authorized_snapshot must be an AuthorizedProjectionSnapshot."
            )
        if self.mapping_profile is not None and not isinstance(
            self.mapping_profile, NativeValueMappingProfileReference
        ):
            raise StandardsEvidenceStorageValidationError(
                "mapping_profile must be an exact mapping-profile reference or None."
            )
        if self.attempt is not None and not isinstance(
            self.attempt, AttemptObservationReference
        ):
            raise StandardsEvidenceStorageValidationError(
                "attempt must be an AttemptObservationReference or None."
            )


def standards_evidence_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        grade_item_membership_directory(
            _root(workspace_root),
            _identifier(class_id, "class_id"),
            _identifier(grade_item_id, "grade_item_id"),
            work,
        )
        / "standards_evidence"
    )


def standard_evidence_associations_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    return (
        standards_evidence_directory(workspace_root, class_id, grade_item_id, work)
        / "associations"
    )


def standard_evidence_association_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> Path:
    validated = validate_evidence_source_reference(source)
    return standard_evidence_associations_directory(
        workspace_root, class_id, grade_item_id, validated.work
    ) / standard_evidence_association_key(
        class_id, grade_item_id, validated, standard_id
    )


def standard_evidence_association_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    association_revision: int,
) -> Path:
    return (
        standard_evidence_association_directory(
            workspace_root, class_id, grade_item_id, source, standard_id
        )
        / "revisions"
        / f"{_positive_int(association_revision, 'association_revision')}.json"
    )


def standard_evidence_association_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> Path:
    return (
        standard_evidence_association_directory(
            workspace_root, class_id, grade_item_id, source, standard_id
        )
        / "current.json"
    )


def standard_evidence_association_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    association_revision: int,
) -> str:
    validated = validate_evidence_source_reference(source)
    key = standard_evidence_association_key(
        class_id, grade_item_id, validated, standard_id
    )
    return (
        f"classes/{_identifier(class_id, 'class_id')}/modules/meridian/grade_items/"
        f"{_identifier(grade_item_id, 'grade_item_id')}/memberships/"
        f"{validated.work.module_id}/{validated.work.work_id}/standards_evidence/"
        f"associations/{key}/revisions/"
        f"{_positive_int(association_revision, 'association_revision')}.json"
    )


def resolve_core_standard(
    library: StandardsLibrary, standard_id: str
) -> CoreStandardResolution:
    """Resolve durable identity only; inactive definitions remain resolved."""
    normalized_standard_id = _standard_id(standard_id)
    try:
        standard = find_standard_definition(library, normalized_standard_id)
        frameworks = (
            filter_standards_frameworks(library, source=standard.source)
            if standard is not None
            else ()
        )
    except ValueError as error:
        raise StandardsEvidenceDependencyError(
            f"Core standards library could not resolve durable standard_id: {error}"
        ) from error
    return CoreStandardResolution(standard, frameworks)


def validate_standard_evidence_association_dependencies(
    workspace_root: str | Path,
    decision: StandardEvidenceAssociationDecision,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    standards_library: StandardsLibrary | None = None,
) -> StandardEvidenceAssociationDependencies:
    """Ground a new association write in exact #27/#28/source/Core state."""
    candidate = validate_standard_evidence_association_decision(decision)
    root = _root(workspace_root)
    try:
        metadata = load_class_metadata(class_metadata_path(root, candidate.class_id))
    except ClassMetadataError as error:
        raise StandardsEvidenceDependencyError(
            f"Core class metadata could not be validated: {error}"
        ) from error
    if metadata.class_id != candidate.class_id:
        raise StandardsEvidenceDependencyError(
            "Core class metadata class_id does not match the requested class path."
        )
    try:
        grade_item = load_current_grade_item_revision(
            root, candidate.class_id, candidate.grade_item_id
        )
    except GradeItemStorageError as error:
        raise StandardsEvidenceDependencyError(
            f"Current Grade Item could not be validated: {error}"
        ) from error
    if grade_item is None:
        raise StandardsEvidenceDependencyError("Current Grade Item does not exist.")
    try:
        membership = load_current_grade_item_membership_decision(
            root, candidate.class_id, candidate.grade_item_id, candidate.source.work
        )
    except GradeItemMembershipStorageError as error:
        raise StandardsEvidenceDependencyError(
            f"Current Grade Item membership could not be validated: {error}"
        ) from error
    if membership is None or membership.decision.decision != "included":
        raise StandardsEvidenceDependencyError(
            "Association requires a selected included exact work membership."
        )
    try:
        evidence_item = validate_authorized_evidence_source(
            candidate.source, authorized_snapshot
        )
    except EvidenceEligibilityDependencyError as error:
        raise StandardsEvidenceDependencyError(str(error)) from error
    if evidence_item.provenance.work != candidate.source.work:
        raise StandardsEvidenceDependencyError(
            "Evidence source work does not match association scope."
        )
    library = standards_library
    if library is None:
        try:
            library = load_workspace_standards_library(root)
        except StandardsReadError as error:
            raise StandardsEvidenceDependencyError(
                f"Core standards library could not be loaded: {error}"
            ) from error
    resolution = resolve_core_standard(library, candidate.standard_id)
    if not resolution.resolved:
        raise StandardsEvidenceDependencyError(
            "Durable standard_id does not resolve in the current Core library."
        )
    if (
        candidate.basis == "producer_declared"
        and candidate.standard_id not in evidence_item.target.standard_ids
    ):
        raise StandardsEvidenceDependencyError(
            "producer_declared basis requires the exact source target standard_id."
        )
    return StandardEvidenceAssociationDependencies(
        metadata,
        grade_item,
        membership,
        authorized_snapshot,
        evidence_item,
        resolution,
    )


def load_standard_evidence_association_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    association_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_STANDARD_EVIDENCE_REVISION_BYTES,
) -> StoredStandardEvidenceAssociationDecision:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated = validate_evidence_source_reference(source)
    standard = _standard_id(standard_id)
    revision = _positive_int(association_revision, "association_revision")
    root = _root(workspace_root)
    _validate_standards_evidence_collections(root, class_value, item, validated.work)
    path = standard_evidence_association_revision_path(
        root, class_value, item, validated, standard, revision
    )
    _validate_existing_directory_chain(root, path.parent)
    content, digest = _read_revision_pair(root, path, maximum_revision_bytes)
    try:
        decision = standard_evidence_association_from_json_bytes(content)
    except (
        StandardsEvidenceSerializationError,
        StandardsEvidenceValidationError,
    ) as error:
        raise StandardsEvidenceStorageIntegrityError(
            "Persisted association revision is invalid or noncanonical."
        ) from error
    if (
        decision.class_id != class_value
        or decision.grade_item_id != item
        or decision.source != validated
        or decision.standard_id != standard
        or decision.association_revision != revision
    ):
        raise StandardsEvidenceStorageIntegrityError(
            "Persisted association identity does not match canonical path."
        )
    expected_key = standard_evidence_association_key(
        class_value, item, validated, standard
    )
    if path.parents[1].name != expected_key:
        raise StandardsEvidenceStorageIntegrityError(
            "Association directory key does not match persisted identity."
        )
    return StoredStandardEvidenceAssociationDecision(
        decision,
        digest,
        path,
        standard_evidence_association_revision_relative_path(
            class_value, item, validated, standard, revision
        ),
        content,
    )


def list_standard_evidence_association_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> tuple[int, ...]:
    root = _root(workspace_root)
    relation = standard_evidence_association_directory(
        root, class_id, grade_item_id, source, standard_id
    )
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_standards_evidence_collections(
        root,
        _identifier(class_id, "class_id"),
        _identifier(grade_item_id, "grade_item_id"),
        validate_evidence_source_reference(source).work,
    )
    _validate_association_history_root(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    jsons: set[int] = set()
    digests: set[int] = set()
    for entry in _directory_entries(revisions_dir, "association revisions"):
        if entry.is_symlink() or not entry.is_file():
            raise StandardsEvidenceStorageIntegrityError(
                "Association revision entry must be a regular file."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        if json_match is not None:
            jsons.add(int(json_match.group(1)))
            continue
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digests.add(int(digest_match.group(1)))
            continue
        raise StandardsEvidenceStorageIntegrityError(
            "Association revisions contain an unexpected filename."
        )
    if jsons != digests:
        raise StandardsEvidenceStorageIntegrityError(
            "Association JSON/digest pairs are incomplete."
        )
    revisions = tuple(sorted(jsons))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise StandardsEvidenceStorageIntegrityError(
            "Association revision history is not contiguous."
        )
    previous: StandardEvidenceAssociationDecision | None = None
    for revision in revisions:
        current = load_standard_evidence_association_revision(
            root, class_id, grade_item_id, source, standard_id, revision
        ).decision
        if previous is not None:
            try:
                validate_standard_evidence_association_transition(previous, current)
            except StandardsEvidenceValidationError as error:
                raise StandardsEvidenceStorageIntegrityError(
                    "Association history transition is invalid."
                ) from error
        previous = current
    return revisions


def write_standard_evidence_association_revision(
    workspace_root: str | Path,
    decision: StandardEvidenceAssociationDecision,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    standards_library: StandardsLibrary | None = None,
) -> StandardEvidenceAssociationRevisionWriteResult:
    """Persist without selecting; exact replay bypasses later dependency drift."""
    candidate = validate_standard_evidence_association_decision(decision)
    root = _root(workspace_root)
    relation = standard_evidence_association_directory(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.source,
        candidate.standard_id,
    )
    target = standard_evidence_association_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.source,
        candidate.standard_id,
        candidate.association_revision,
    )
    digest_path = Path(str(target) + ".sha256")
    content = standard_evidence_association_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_STANDARD_EVIDENCE_REVISION_BYTES:
        raise StandardsEvidenceStorageWriteError(
            "Association revision exceeds the canonical byte limit."
        )
    digest = hashlib.sha256(content).hexdigest()
    if target.exists() or digest_path.exists():
        stored = load_standard_evidence_association_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.source,
            candidate.standard_id,
            candidate.association_revision,
        )
        if stored.content != content or stored.decision_sha256 != digest:
            raise StandardsEvidenceStorageConflictError(
                "Association revision identity exists with different content."
            )
        return StandardEvidenceAssociationRevisionWriteResult("existing", stored)

    validate_standard_evidence_association_dependencies(
        root,
        candidate,
        authorized_snapshot,
        standards_library=standards_library,
    )
    _ensure_directory_chain(root, relation / "revisions")
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_association_history_root(relation)
        if target.exists() or digest_path.exists():
            stored = load_standard_evidence_association_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.source,
                candidate.standard_id,
                candidate.association_revision,
            )
            if stored.content != content or stored.decision_sha256 != digest:
                raise StandardsEvidenceStorageConflictError(
                    "Association revision identity exists with different content."
                )
            return StandardEvidenceAssociationRevisionWriteResult("existing", stored)
        history = list_standard_evidence_association_revisions(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.source,
            candidate.standard_id,
        )
        if not history and candidate.association_revision != 1:
            raise StandardsEvidenceStorageConflictError(
                "Initial association revision must be revision 1."
            )
        if history:
            if candidate.association_revision != history[-1] + 1:
                raise StandardsEvidenceStorageConflictError(
                    "Association revision must be exactly one greater than history."
                )
            previous = load_standard_evidence_association_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.source,
                candidate.standard_id,
                history[-1],
            ).decision
            try:
                validate_standard_evidence_association_transition(previous, candidate)
            except StandardsEvidenceValidationError as error:
                raise StandardsEvidenceStorageConflictError(str(error)) from error
        _write_revision_pair(target, digest_path, content, digest)
        stored = load_standard_evidence_association_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.source,
            candidate.standard_id,
            candidate.association_revision,
        )
        return StandardEvidenceAssociationRevisionWriteResult("created", stored)
    finally:
        _remove_lock(lock)


def load_current_standard_evidence_association_decision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> StoredStandardEvidenceAssociationDecision | None:
    selection = _load_current_selection(
        workspace_root,
        class_id,
        grade_item_id,
        source,
        standard_id,
        missing_ok=True,
    )
    if selection is None:
        return None
    stored = load_standard_evidence_association_revision(
        workspace_root,
        class_id,
        grade_item_id,
        source,
        standard_id,
        selection.association_revision,
    )
    if stored.decision_sha256 != selection.decision_sha256:
        raise StandardsEvidenceStorageIntegrityError(
            "Current association pointer digest does not match revision."
        )
    return stored


def get_current_standard_evidence_association_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> int | None:
    selected = load_current_standard_evidence_association_decision(
        workspace_root, class_id, grade_item_id, source, standard_id
    )
    return selected.decision.association_revision if selected is not None else None


def select_standard_evidence_association_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    association_revision: int,
    *,
    expected_current_association_revision: int | None,
) -> StandardEvidenceAssociationSelectionResult:
    """Select any persisted historical revision with revision-based CAS."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated = validate_evidence_source_reference(source)
    standard = _standard_id(standard_id)
    revision = _positive_int(association_revision, "association_revision")
    expected = (
        None
        if expected_current_association_revision is None
        else _positive_int(
            expected_current_association_revision,
            "expected_current_association_revision",
        )
    )
    root = _root(workspace_root)
    relation = standard_evidence_association_directory(
        root, class_value, item, validated, standard
    )
    _validate_existing_directory_chain(root, relation)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_association_history_root(relation)
        target = load_standard_evidence_association_revision(
            root, class_value, item, validated, standard, revision
        )
        current = _load_current_selection(
            root, class_value, item, validated, standard, missing_ok=True
        )
        current_revision = current.association_revision if current is not None else None
        if current_revision != expected:
            raise StandardsEvidenceStorageConflictError(
                "Expected current association revision does not match selection."
            )
        selection = StandardEvidenceAssociationCurrentSelection(
            STANDARD_EVIDENCE_ASSOCIATION_CURRENT_SCHEMA_VERSION,
            STANDARD_EVIDENCE_ASSOCIATION_CURRENT_RECORD_TYPE,
            class_value,
            item,
            standard_evidence_association_key(class_value, item, validated, standard),
            revision,
            target.decision_sha256,
        )
        if current == selection:
            return StandardEvidenceAssociationSelectionResult(
                "existing", selection, target
            )
        _atomic_write_pointer(
            root,
            standard_evidence_association_current_path(
                root, class_value, item, validated, standard
            ),
            _canonical_json_bytes(_selection_to_dict(selection)),
        )
        published = _load_current_selection(
            root, class_value, item, validated, standard, missing_ok=False
        )
        if published != selection:
            raise StandardsEvidenceStorageIntegrityError(
                "Published current association selection did not verify exactly."
            )
        disposition: AssociationSelectionDisposition = (
            "created" if current is None else "updated"
        )
        return StandardEvidenceAssociationSelectionResult(
            disposition, selection, target
        )
    finally:
        _remove_lock(lock)


def resolve_current_standard_evidence_association(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    standards_library: StandardsLibrary | None = None,
) -> StandardEvidenceAssociationResolution:
    """Resolve selected association against current source and Core metadata."""
    selected = load_current_standard_evidence_association_decision(
        workspace_root, class_id, grade_item_id, source, standard_id
    )
    library = standards_library
    if library is None:
        try:
            library = load_workspace_standards_library(_root(workspace_root))
        except StandardsReadError as error:
            raise StandardsEvidenceDependencyError(
                f"Core standards library could not be loaded: {error}"
            ) from error
    standard_resolution = resolve_core_standard(library, standard_id)
    try:
        validate_authorized_evidence_source(source, authorized_snapshot)
        source_verifiable = True
    except EvidenceEligibilityDependencyError:
        source_verifiable = False
    reference = selected.reference if selected is not None else None
    basis = selected.decision.basis if selected is not None else None
    if not source_verifiable:
        status: StandardEvidenceAssociationResolutionStatus = "source_unverifiable"
        operative = False
    elif not standard_resolution.resolved:
        status = "standard_unresolved"
        operative = False
    elif selected is None:
        status = "no_decision"
        operative = False
    else:
        status = selected.decision.disposition
        operative = status == "associated"
    return StandardEvidenceAssociationResolution(
        status,
        selected,
        reference,
        basis,
        standard_resolution,
        source_verifiable,
        operative,
    )


def resolve_standard_aggregation_candidate(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    binding: StandardAggregationCandidateBinding,
    *,
    standards_library: StandardsLibrary | None = None,
) -> ResolvedStandardAggregationCandidate:
    """Resolve one explicitly named source through #29-#33 and exact #32 mapping."""
    class_value = _identifier(class_id, "class_id")
    item_id = _identifier(grade_item_id, "grade_item_id")
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    if not isinstance(binding, StandardAggregationCandidateBinding):
        raise StandardsEvidenceStorageValidationError(
            "binding must be a StandardAggregationCandidateBinding."
        )
    root = _root(workspace_root)
    source = binding.source
    if source.work.class_id != class_value:
        raise StandardsEvidenceStorageValidationError(
            "candidate source class must match requested class."
        )
    try:
        evidence_item = validate_authorized_evidence_source(
            source, binding.authorized_snapshot
        )
        source_verifiable = True
    except EvidenceEligibilityDependencyError:
        evidence_item = None
        source_verifiable = False

    association = resolve_current_standard_evidence_association(
        root,
        class_value,
        item_id,
        source,
        standard,
        authorized_snapshot=binding.authorized_snapshot,
        standards_library=standards_library,
    )
    association_state = association.status

    membership_reference: AggregationDecisionReference | None = None
    try:
        membership = load_current_grade_item_membership_decision(
            root, class_value, item_id, source.work
        )
    except GradeItemMembershipStorageError:
        membership = None
    if membership is not None:
        membership_reference = AggregationDecisionReference(
            "membership",
            membership.decision.membership_revision,
            membership.decision_sha256,
        )

    eligibility_reference: AggregationDecisionReference | None = None
    try:
        eligibility = resolve_current_evidence_eligibility(
            root,
            class_value,
            item_id,
            source,
            authorized_snapshot=binding.authorized_snapshot,
        )
    except (EvidenceEligibilityStorageError, EvidenceEligibilityDependencyError):
        eligibility = None
    if eligibility is None:
        eligibility_state: Literal["included", "not_included", "unresolved"] = (
            "unresolved"
        )
    else:
        if eligibility.selected is not None:
            eligibility_reference = AggregationDecisionReference(
                "eligibility",
                eligibility.selected.decision.eligibility_revision,
                eligibility.selected.decision_sha256,
            )
        if eligibility.operative_included:
            eligibility_state = "included"
        elif eligibility.status in {
            "no_decision",
            "membership_stale",
            "source_unverifiable",
        }:
            eligibility_state = "unresolved"
        else:
            eligibility_state = "not_included"

    attempt_reference: AggregationDecisionReference | None = None
    reassessment_reference: AggregationDecisionReference | None = None
    resolved_attempt = binding.attempt
    if (
        resolved_attempt is None
        and evidence_item is not None
        and evidence_item.subject is not None
        and evidence_item.subject.student_id == student
    ):
        resolved_attempt = _attempt_observation_from_item(
            evidence_item, source, student
        )
    if (
        binding.attempt is not None
        and evidence_item is not None
        and evidence_item.subject is not None
    ):
        derived_attempt = _attempt_observation_from_item(
            evidence_item, source, evidence_item.subject.student_id
        )
        if derived_attempt != binding.attempt:
            raise StandardsEvidenceDependencyError(
                "Supplied attempt reference does not identify the exact evidence item."
            )

    if resolved_attempt is None:
        attempt_state: Literal[
            "not_applicable", "selected", "not_selected", "unresolved"
        ] = "not_applicable"
        reassessment_state: Literal[
            "not_applicable", "contributing", "noncontributing", "unresolved"
        ] = "not_applicable"
    else:
        try:
            attempt_resolution = resolve_current_attempt_selection(
                root,
                class_value,
                item_id,
                source.work,
                student,
                authorized_snapshot=binding.authorized_snapshot,
            )
        except AttemptSelectionStorageError:
            attempt_resolution = None
        if attempt_resolution is None:
            attempt_state = "unresolved"
        else:
            if attempt_resolution.selected is not None:
                attempt_reference = AggregationDecisionReference(
                    "attempt_selection",
                    attempt_resolution.selected.decision.decision_revision,
                    attempt_resolution.selected.decision_sha256,
                )
            if attempt_resolution.status == "not_applicable":
                attempt_state = "not_applicable"
            elif not attempt_resolution.operative_selection:
                attempt_state = "unresolved"
            elif attempt_resolution.selected is None:
                attempt_state = "unresolved"
            elif (
                resolved_attempt
                in attempt_resolution.selected.decision.selected_attempts
            ):
                attempt_state = "selected"
            else:
                attempt_state = "not_selected"

        if attempt_state != "selected":
            reassessment_state = (
                "not_applicable" if attempt_state == "not_applicable" else "unresolved"
            )
        else:
            try:
                reassessment = resolve_current_reassessment(
                    root,
                    class_value,
                    item_id,
                    source.work,
                    student,
                    authorized_snapshot=binding.authorized_snapshot,
                )
            except ReassessmentStorageError:
                reassessment = None
            if reassessment is None:
                reassessment_state = "unresolved"
            else:
                if reassessment.selected is not None:
                    reassessment_reference = AggregationDecisionReference(
                        "reassessment",
                        reassessment.selected.decision.decision_revision,
                        reassessment.selected.decision_sha256,
                    )
                if reassessment.status == "not_applicable":
                    reassessment_state = "not_applicable"
                elif not reassessment.operative_reassessment:
                    reassessment_state = "unresolved"
                elif resolved_attempt in reassessment.contributing_attempts:
                    reassessment_state = "contributing"
                else:
                    reassessment_state = "noncontributing"

    mapping_outcome = None
    if binding.mapping_profile is not None and evidence_item is not None:
        profile_ref = binding.mapping_profile
        try:
            stored_profile = load_mapping_profile_revision(
                root,
                profile_ref.class_id,
                profile_ref.scale_id,
                profile_ref.profile_id,
                profile_ref.profile_revision,
            )
        except ProficiencyMappingStorageError as error:
            raise StandardsEvidenceDependencyError(
                f"Explicit mapping-profile reference could not be loaded: {error}"
            ) from error
        if stored_profile.profile_sha256 != profile_ref.profile_sha256:
            raise StandardsEvidenceDependencyError(
                "Explicit mapping-profile SHA-256 does not match stored revision."
            )
        scale_ref = stored_profile.profile.target_scale
        try:
            stored_scale = load_proficiency_scale_revision(
                root,
                scale_ref.class_id,
                scale_ref.scale_id,
                scale_ref.scale_revision,
            )
        except ProficiencyMappingStorageError as error:
            raise StandardsEvidenceDependencyError(
                f"Mapping profile target scale could not be loaded: {error}"
            ) from error
        if stored_scale.scale_sha256 != scale_ref.scale_sha256:
            raise StandardsEvidenceDependencyError(
                "Mapping profile target-scale SHA-256 does not match storage."
            )
        mapping_outcome = map_evidence_item(
            evidence_item, stored_profile.profile, stored_scale.scale
        )

    subject_kind: Literal["student", "nonstudent"]
    subject_student_id: str | None
    result_kind = "unverifiable_source"
    target_kind = "unverifiable_source"
    if source_verifiable and evidence_item is not None:
        result_kind = evidence_item.result_kind
        target_kind = evidence_item.target.target_kind
        if evidence_item.subject is None:
            subject_kind = "nonstudent"
            subject_student_id = None
        else:
            subject_kind = "student"
            subject_student_id = evidence_item.subject.student_id
    else:
        subject_kind = "nonstudent"
        subject_student_id = None

    return ResolvedStandardAggregationCandidate(
        source=source,
        standard_id=standard,
        result_kind=result_kind,
        target_kind=target_kind,
        subject_kind=subject_kind,
        subject_student_id=subject_student_id,
        association_state=association_state,
        eligibility_state=eligibility_state,
        attempt_state=attempt_state,
        reassessment_state=reassessment_state,
        membership_reference=membership_reference,
        eligibility_reference=eligibility_reference,
        attempt_selection_reference=attempt_reference,
        reassessment_reference=reassessment_reference,
        association_reference=association.reference,
        mapping_outcome=mapping_outcome,
    )


def resolve_standard_aggregation_inputs(
    workspace_root: str | Path,
    grade_item: GradeItemAggregationBasis,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    bindings: tuple[StandardAggregationCandidateBinding, ...],
    *,
    standards_library: StandardsLibrary | None = None,
) -> StandardAggregationInputs:
    """Resolve caller-supplied bounded bindings, then invoke the pure builder."""
    if not isinstance(grade_item, GradeItemAggregationBasis):
        raise StandardsEvidenceStorageValidationError(
            "grade_item must be a GradeItemAggregationBasis."
        )
    if not isinstance(target_scale, ProficiencyScaleReference):
        raise StandardsEvidenceStorageValidationError(
            "target_scale must be a ProficiencyScaleReference."
        )
    if not isinstance(bindings, tuple) or any(
        not isinstance(binding, StandardAggregationCandidateBinding)
        for binding in bindings
    ):
        raise StandardsEvidenceStorageValidationError(
            "bindings must be a tuple of StandardAggregationCandidateBinding values."
        )
    if len(bindings) > MAXIMUM_STANDARD_AGGREGATION_CANDIDATES:
        raise StandardsEvidenceStorageValidationError(
            "aggregation binding count exceeds the finite maximum."
        )
    root = _root(workspace_root)
    try:
        stored_grade_item = load_current_grade_item_revision(
            root, grade_item.class_id, grade_item.grade_item_id
        )
    except GradeItemStorageError as error:
        raise StandardsEvidenceDependencyError(
            f"Current Grade Item could not be validated: {error}"
        ) from error
    if (
        stored_grade_item is None
        or stored_grade_item.revision.grade_item_revision
        != grade_item.grade_item_revision
        or stored_grade_item.revision_sha256 != grade_item.grade_item_revision_sha256
    ):
        raise StandardsEvidenceDependencyError(
            "Exact Grade Item aggregation basis is not the selected stored revision."
        )
    try:
        stored_scale = load_proficiency_scale_revision(
            root,
            target_scale.class_id,
            target_scale.scale_id,
            target_scale.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise StandardsEvidenceDependencyError(
            f"Exact aggregation target scale could not be loaded: {error}"
        ) from error
    if stored_scale.scale_sha256 != target_scale.scale_sha256:
        raise StandardsEvidenceDependencyError(
            "Aggregation target-scale SHA-256 does not match stored revision."
        )
    candidates = tuple(
        resolve_standard_aggregation_candidate(
            root,
            grade_item.class_id,
            grade_item.grade_item_id,
            student_id,
            standard_id,
            binding,
            standards_library=standards_library,
        )
        for binding in bindings
    )
    return build_standard_aggregation_inputs(
        grade_item, student_id, standard_id, target_scale, candidates
    )


def _attempt_observation_from_item(
    evidence_item: EvidenceItem,
    source: EvidenceSourceReference,
    student_id: str,
) -> AttemptObservationReference | None:
    """Derive only an exact attempt identity already present on one source item."""
    target = evidence_item.target
    if target.target_kind == "attempt":
        attempt_target = AttemptTargetReference(
            "attempt",
            target.target_id,
            target.owning_system,
            target.contract_version,
        )
    elif (
        target.parent_target is not None
        and target.parent_target.target_kind == "attempt"
    ):
        parent = target.parent_target
        attempt_target = AttemptTargetReference(
            "attempt",
            parent.target_id,
            parent.owning_system,
            parent.contract_version,
        )
    else:
        return None
    references = tuple(
        reference
        for reference in evidence_item.provenance.native.references
        if reference.kind == "attempt"
    )
    if len(references) != 1:
        return None
    native = references[0]
    return AttemptObservationReference(
        AttemptProjectionReference(
            source.work,
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
        ),
        student_id,
        attempt_target,
        AttemptNativeIdentity(native.identifier, native.sequence),
    )


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
    *,
    missing_ok: bool,
) -> StandardEvidenceAssociationCurrentSelection | None:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated = validate_evidence_source_reference(source)
    standard = _standard_id(standard_id)
    root = _root(workspace_root)
    path = standard_evidence_association_current_path(
        root, class_value, item, validated, standard
    )
    if not path.exists():
        if missing_ok:
            return None
        raise StandardsEvidenceStorageNotFoundError(
            "Association current pointer not found."
        )
    content = _read_bounded_regular_file(
        path, DEFAULT_MAXIMUM_STANDARD_EVIDENCE_POINTER_BYTES
    )
    try:
        decoded = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except StandardsEvidenceStorageIntegrityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise StandardsEvidenceStorageIntegrityError(
            "Association current pointer JSON is invalid."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise StandardsEvidenceStorageIntegrityError(
            "Association current pointer does not use exact schema."
        )
    if _canonical_json_bytes(decoded) != content:
        raise StandardsEvidenceStorageIntegrityError(
            "Association current pointer is not canonical JSON."
        )
    selection = StandardEvidenceAssociationCurrentSelection(
        _pointer_str(decoded["schema_version"], "schema_version"),
        _pointer_str(decoded["record_type"], "record_type"),
        _pointer_str(decoded["class_id"], "class_id"),
        _pointer_str(decoded["grade_item_id"], "grade_item_id"),
        _pointer_str(decoded["association_key"], "association_key"),
        _pointer_int(decoded["association_revision"], "association_revision"),
        _pointer_str(decoded["decision_sha256"], "decision_sha256"),
    )
    expected_key = standard_evidence_association_key(
        class_value, item, validated, standard
    )
    if (
        selection.class_id != class_value
        or selection.grade_item_id != item
        or selection.association_key != expected_key
    ):
        raise StandardsEvidenceStorageIntegrityError(
            "Association current pointer identity does not match canonical path."
        )
    return selection


def _selection_to_dict(
    selection: StandardEvidenceAssociationCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": selection.schema_version,
        "record_type": selection.record_type,
        "class_id": selection.class_id,
        "grade_item_id": selection.grade_item_id,
        "association_key": selection.association_key,
        "association_revision": selection.association_revision,
        "decision_sha256": selection.decision_sha256,
    }


def _validate_association_history_root(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise StandardsEvidenceStorageIntegrityError(
            "Association history root must be a real directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    for entry in _directory_entries(relation, "association history root"):
        if entry.name not in allowed:
            raise StandardsEvidenceStorageIntegrityError(
                "Association history root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise StandardsEvidenceStorageIntegrityError(
                    "Association revisions path must be a real directory."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise StandardsEvidenceStorageIntegrityError(
                "Association history metadata must be a regular file."
            )


def _validate_standards_evidence_collections(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> None:
    base = standards_evidence_directory(root, class_id, grade_item_id, work)
    if not base.exists():
        return
    _validate_existing_directory_chain(root, base)
    entries = _directory_entries(base, "standards-evidence collection")
    if len(entries) != 1 or entries[0].name != "associations":
        raise StandardsEvidenceStorageIntegrityError(
            "Standards-evidence collection contains an unexpected entry."
        )
    associations = entries[0]
    if associations.is_symlink() or not associations.is_dir():
        raise StandardsEvidenceStorageIntegrityError(
            "Standards-evidence associations must be a real directory."
        )
    for entry in _directory_entries(associations, "association collection"):
        if _SHA256.fullmatch(entry.name) is None:
            raise StandardsEvidenceStorageIntegrityError(
                "Association collection contains an invalid association key."
            )
        if entry.is_symlink() or not entry.is_dir():
            raise StandardsEvidenceStorageIntegrityError(
                "Association collection children must be real directories."
            )
        _validate_association_history_root(entry)


def _read_revision_pair(root: Path, path: Path, maximum: int) -> tuple[bytes, str]:
    digest_path = Path(str(path) + ".sha256")
    if not path.exists() or not digest_path.exists():
        raise StandardsEvidenceStorageNotFoundError(
            "Association revision or digest sidecar is missing."
        )
    content = _read_bounded_regular_file(path, maximum)
    digest_bytes = _read_bounded_regular_file(
        digest_path, DEFAULT_MAXIMUM_STANDARD_EVIDENCE_DIGEST_BYTES
    )
    digest = _parse_digest(digest_bytes)
    if hashlib.sha256(content).hexdigest() != digest:
        raise StandardsEvidenceStorageIntegrityError(
            "Association digest does not match exact revision bytes."
        )
    _require_containment(root, path)
    _require_containment(root, digest_path)
    return content, digest


def _write_revision_pair(
    path: Path, digest_path: Path, content: bytes, digest: str
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
        raise StandardsEvidenceStorageConflictError(
            "Association revision was concurrently created."
        ) from error
    except OSError as error:
        raise StandardsEvidenceStorageWriteError(
            "Could not write immutable association revision."
        ) from error


def _atomic_write_pointer(root: Path, path: Path, content: bytes) -> None:
    _ensure_directory_chain(root, path.parent)
    _require_containment(root, path)
    temp: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".current-", dir=path.parent)
        temp = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        temp = None
        _fsync_directory(path.parent)
    except OSError as error:
        raise StandardsEvidenceStorageWriteError(
            "Could not publish association current pointer."
        ) from error
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(b"locked\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise StandardsEvidenceStorageLockError(
            "Association history is already locked."
        ) from error
    except OSError as error:
        raise StandardsEvidenceStorageWriteError(
            "Could not create association write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
    except OSError as error:
        raise StandardsEvidenceStorageWriteError(
            "Could not remove association write lock."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise StandardsEvidenceStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise StandardsEvidenceStorageIntegrityError(
                    "Canonical association directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except FileExistsError:
                if current.is_symlink() or not current.is_dir():
                    raise StandardsEvidenceStorageIntegrityError(
                        "Canonical association directory chain is unsafe."
                    )
            except OSError as error:
                raise StandardsEvidenceStorageWriteError(
                    "Could not create association directory."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    if not root.exists() or root.is_symlink() or not root.is_dir():
        raise StandardsEvidenceStorageIntegrityError(
            "Workspace root must be a real directory."
        )
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists() or current.is_symlink() or not current.is_dir():
            raise StandardsEvidenceStorageIntegrityError(
                "Canonical association directory chain is unsafe."
            )


def _read_bounded_regular_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise StandardsEvidenceStorageIntegrityError(
            "Association storage entry must be a regular file."
        )
    try:
        size = path.stat().st_size
        if size > maximum:
            raise StandardsEvidenceStorageTooLargeError(
                "Association file exceeds byte limit."
            )
        with path.open("rb") as handle:
            content = handle.read(maximum + 1)
    except StandardsEvidenceStorageTooLargeError:
        raise
    except OSError as error:
        raise StandardsEvidenceStorageReadError(
            "Could not read association storage."
        ) from error
    if len(content) > maximum:
        raise StandardsEvidenceStorageTooLargeError(
            "Association file exceeds byte limit."
        )
    return content


def _parse_digest(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise StandardsEvidenceStorageIntegrityError(
            "Association digest sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or "\r" in text or text.count("\n") != 1:
        raise StandardsEvidenceStorageIntegrityError(
            "Association digest sidecar must use one canonical LF."
        )
    return _sha256(text[:-1], "digest")


def _directory_entries(path: Path, label: str) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise StandardsEvidenceStorageReadError(
            f"Could not inspect {label}."
        ) from error


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True
        )
    except (TypeError, ValueError) as error:
        raise StandardsEvidenceStorageIntegrityError(
            "Association pointer cannot be serialized canonically."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StandardsEvidenceStorageIntegrityError(
                f"Duplicate association pointer key: {key}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise StandardsEvidenceStorageIntegrityError(
        f"Non-finite association pointer value is invalid: {value}"
    )


def _root(value: str | Path) -> Path:
    root = Path(value)
    return root if root.is_absolute() else root.absolute()


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsEvidenceStorageValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardsEvidenceStorageValidationError(str(error)) from error


def _standard_id(value: object) -> str:
    try:
        return normalize_standard_id(value)
    except StandardsEvidenceValidationError as error:
        raise StandardsEvidenceStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StandardsEvidenceStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardsEvidenceStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsEvidenceStorageIntegrityError(
            f"Association pointer {field_name} must be a string."
        )
    return value


def _pointer_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StandardsEvidenceStorageIntegrityError(
            f"Association pointer {field_name} must be an integer."
        )
    return value


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise StandardsEvidenceStorageValidationError(
            "Association path escapes workspace root."
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
