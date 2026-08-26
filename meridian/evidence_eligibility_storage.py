"""Canonical persistence and dependency validation for evidence eligibility."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    validate_module_work_ref,
)

from meridian.evidence_eligibility import (
    EvidenceEligibilityDecision,
    EvidenceEligibilitySerializationError,
    EvidenceEligibilityValidationError,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_eligibility_decision_from_json_bytes,
    evidence_eligibility_decision_to_json_bytes,
    evidence_source_key,
    validate_evidence_eligibility_decision,
    validate_evidence_eligibility_transition,
    validate_evidence_source_reference,
)

if TYPE_CHECKING:
    from meridian.evidence import EvidenceItem
    from meridian.grade_item_membership_storage import (
        StoredGradeItemMembershipDecision,
    )
    from meridian.projection_cache import AuthorizedProjectionSnapshot

EVIDENCE_ELIGIBILITY_CURRENT_SCHEMA_VERSION: Final[str] = "1"
EVIDENCE_ELIGIBILITY_CURRENT_RECORD_TYPE: Final[str] = (
    "meridian_evidence_eligibility_current"
)
DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_REVISION_BYTES: Final[int] = 64 * 1024
DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_POINTER_BYTES: Final[int] = 16 * 1024
DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_DIGEST_BYTES: Final[int] = 128

EvidenceEligibilityWriteDisposition: TypeAlias = Literal["created", "existing"]
EvidenceEligibilitySelectionDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
]
EvidenceEligibilityResolutionStatus: TypeAlias = Literal[
    "no_decision",
    "included",
    "included_source_superseded",
    "included_source_withdrawn",
    "excluded",
    "pending",
    "unsupported",
    "superseded",
    "withdrawn",
    "membership_stale",
    "source_unverifiable",
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
        "source_key",
        "eligibility_revision",
        "decision_sha256",
    }
)


class EvidenceEligibilityStorageError(RuntimeError):
    """Base error for canonical evidence-eligibility persistence."""

    code: str = "evidence_eligibility.storage_error"


class EvidenceEligibilityStorageValidationError(
    EvidenceEligibilityStorageError, ValueError
):
    """Raised for invalid storage API arguments."""

    code = "evidence_eligibility.storage_invalid"


class EvidenceEligibilityStorageNotFoundError(EvidenceEligibilityStorageError):
    """Raised when explicitly requested eligibility state is absent."""

    code = "evidence_eligibility.not_found"


class EvidenceEligibilityStorageReadError(EvidenceEligibilityStorageError):
    """Raised when eligibility state cannot be read safely."""

    code = "evidence_eligibility.read_failed"


class EvidenceEligibilityStorageWriteError(EvidenceEligibilityStorageError):
    """Raised when eligibility state cannot be written safely."""

    code = "evidence_eligibility.write_failed"


class EvidenceEligibilityStorageConflictError(EvidenceEligibilityStorageError):
    """Raised for stale writes or identity/content collisions."""

    code = "evidence_eligibility.conflict"


class EvidenceEligibilityStorageLockError(EvidenceEligibilityStorageConflictError):
    """Raised when another writer owns one eligibility relationship."""

    code = "evidence_eligibility.locked"


class EvidenceEligibilityStorageIntegrityError(EvidenceEligibilityStorageError):
    """Raised when paths, bytes, digests, or identities disagree."""

    code = "evidence_eligibility.integrity"


class EvidenceEligibilityStorageTooLargeError(EvidenceEligibilityStorageReadError):
    """Raised before an eligibility file can be read without a finite bound."""

    code = "evidence_eligibility.too_large"


class EvidenceEligibilityDependencyError(EvidenceEligibilityStorageError):
    """Raised when exact source/membership/Core dependencies cannot be validated."""

    code = "evidence_eligibility.dependency_invalid"


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityDependencies:
    """Exact dependencies resolved for one eligibility decision."""

    membership: StoredGradeItemMembershipDecision
    authorized_snapshot: AuthorizedProjectionSnapshot = field(repr=False)
    evidence_item: EvidenceItem = field(repr=False)
    current_source_state: EvidenceSourceStateObservation

    def __post_init__(self) -> None:
        from meridian.evidence import EvidenceItem
        from meridian.grade_item_membership_storage import (
            StoredGradeItemMembershipDecision,
        )
        from meridian.projection_cache import AuthorizedProjectionSnapshot

        if not isinstance(self.membership, StoredGradeItemMembershipDecision):
            raise EvidenceEligibilityStorageValidationError(
                "membership must be a StoredGradeItemMembershipDecision."
            )
        if not isinstance(self.authorized_snapshot, AuthorizedProjectionSnapshot):
            raise EvidenceEligibilityStorageValidationError(
                "authorized_snapshot must be an AuthorizedProjectionSnapshot."
            )
        if not isinstance(self.evidence_item, EvidenceItem):
            raise EvidenceEligibilityStorageValidationError(
                "evidence_item must be an EvidenceItem."
            )
        if not isinstance(self.current_source_state, EvidenceSourceStateObservation):
            raise EvidenceEligibilityStorageValidationError(
                "current_source_state must be an EvidenceSourceStateObservation."
            )


@dataclass(frozen=True, slots=True)
class StoredEvidenceEligibilityDecision:
    """One verified immutable decision and its exact persisted bytes."""

    decision: EvidenceEligibilityDecision
    decision_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, EvidenceEligibilityDecision):
            raise EvidenceEligibilityStorageValidationError(
                "decision must be an EvidenceEligibilityDecision."
            )
        digest = _sha256(self.decision_sha256, "decision_sha256")
        if type(self.content) is not bytes:
            raise EvidenceEligibilityStorageValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise EvidenceEligibilityStorageValidationError(
                "decision_sha256 does not match exact stored bytes."
            )
        try:
            decoded = evidence_eligibility_decision_from_json_bytes(self.content)
        except (
            EvidenceEligibilitySerializationError,
            EvidenceEligibilityValidationError,
        ) as error:
            raise EvidenceEligibilityStorageValidationError(
                "content is not a canonical evidence eligibility decision."
            ) from error
        if decoded != self.decision:
            raise EvidenceEligibilityStorageValidationError(
                "content does not decode to decision."
            )
        expected = evidence_eligibility_revision_relative_path(
            self.decision.class_id,
            self.decision.grade_item_id,
            self.decision.source,
            self.decision.eligibility_revision,
        )
        if self.relative_path != expected:
            raise EvidenceEligibilityStorageValidationError(
                "relative_path is not the canonical eligibility revision location."
            )
        if self.path.name != f"{self.decision.eligibility_revision}.json":
            raise EvidenceEligibilityStorageValidationError(
                "path filename does not match eligibility revision identity."
            )
        object.__setattr__(self, "decision_sha256", digest)


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityRevisionWriteResult:
    disposition: EvidenceEligibilityWriteDisposition
    stored: StoredEvidenceEligibilityDecision

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise EvidenceEligibilityStorageValidationError(
                "write disposition is invalid."
            )
        if not isinstance(self.stored, StoredEvidenceEligibilityDecision):
            raise EvidenceEligibilityStorageValidationError(
                "stored must be a StoredEvidenceEligibilityDecision."
            )


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityCurrentSelection:
    """Explicit mutable selector for one immutable eligibility revision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    source_key: str
    eligibility_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ELIGIBILITY_CURRENT_SCHEMA_VERSION:
            raise EvidenceEligibilityStorageValidationError(
                'current schema_version must be "1".'
            )
        if self.record_type != EVIDENCE_ELIGIBILITY_CURRENT_RECORD_TYPE:
            raise EvidenceEligibilityStorageValidationError(
                'current record_type must be "meridian_evidence_eligibility_current".'
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(self, "source_key", _sha256(self.source_key, "source_key"))
        object.__setattr__(
            self,
            "eligibility_revision",
            _positive_int(self.eligibility_revision, "eligibility_revision"),
        )
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceEligibilitySelectionResult:
    disposition: EvidenceEligibilitySelectionDisposition
    selection: EvidenceEligibilityCurrentSelection
    stored: StoredEvidenceEligibilityDecision
    dependencies: EvidenceEligibilityDependencies


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityResolution:
    """Read-only resolution of selected decision against current authoritative state."""

    status: EvidenceEligibilityResolutionStatus
    selected: StoredEvidenceEligibilityDecision | None
    current_source_state: EvidenceSourceStateObservation | None
    current_membership_revision: int | None
    operative_included: bool

    def __post_init__(self) -> None:
        allowed = {
            "no_decision",
            "included",
            "included_source_superseded",
            "included_source_withdrawn",
            "excluded",
            "pending",
            "unsupported",
            "superseded",
            "withdrawn",
            "membership_stale",
            "source_unverifiable",
        }
        if self.status not in allowed:
            raise EvidenceEligibilityStorageValidationError(
                "resolution status is invalid."
            )
        if not isinstance(self.operative_included, bool):
            raise EvidenceEligibilityStorageValidationError(
                "operative_included must be boolean."
            )


def evidence_eligibility_collection_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> Path:
    """Return the eligibility collection beneath one #28 membership relation."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    if validated_work.class_id != class_value:
        raise EvidenceEligibilityStorageValidationError(
            "work.class_id must match class_id."
        )
    root = _root(workspace_root)
    return (
        class_module_dir(root, class_value, "meridian")
        / "grade_items"
        / item
        / "memberships"
        / validated_work.module_id
        / validated_work.work_id
        / "evidence_eligibility"
    )


def evidence_eligibility_source_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> Path:
    """Return one exact source's canonical eligibility history root."""
    validated = validate_evidence_source_reference(source)
    return evidence_eligibility_collection_directory(
        workspace_root, class_id, grade_item_id, validated.work
    ) / evidence_source_key(validated)


def evidence_eligibility_revisions_directory(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> Path:
    return evidence_eligibility_source_directory(
        workspace_root, class_id, grade_item_id, source
    ) / "revisions"


def evidence_eligibility_revision_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    eligibility_revision: int,
) -> Path:
    revision = _positive_int(eligibility_revision, "eligibility_revision")
    return evidence_eligibility_revisions_directory(
        workspace_root, class_id, grade_item_id, source
    ) / f"{revision}.json"


def evidence_eligibility_revision_digest_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    eligibility_revision: int,
) -> Path:
    return Path(
        str(
            evidence_eligibility_revision_path(
                workspace_root,
                class_id,
                grade_item_id,
                source,
                eligibility_revision,
            )
        )
        + ".sha256"
    )


def evidence_eligibility_current_path(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> Path:
    return evidence_eligibility_source_directory(
        workspace_root, class_id, grade_item_id, source
    ) / "current.json"


def evidence_eligibility_revision_relative_path(
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    eligibility_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated = validate_evidence_source_reference(source)
    if validated.work.class_id != class_value:
        raise EvidenceEligibilityStorageValidationError(
            "source work class_id must match class_id."
        )
    revision = _positive_int(eligibility_revision, "eligibility_revision")
    key = evidence_source_key(validated)
    return (
        f"classes/{class_value}/modules/meridian/grade_items/{item}/memberships/"
        f"{validated.work.module_id}/{validated.work.work_id}/evidence_eligibility/"
        f"{key}/revisions/{revision}.json"
    )


def observe_evidence_source_state(
    workspace_root: str | Path,
    source: EvidenceSourceReference,
) -> EvidenceSourceStateObservation:
    """Observe exact canonical Core publication lifecycle without opening evidence."""
    validated = validate_evidence_source_reference(source)
    root = _root(workspace_root)
    try:
        from pds_core.publication_storage import (
            PublicationStorageError,
            list_publication_record_set,
            load_publication_record,
            load_publication_withdrawal,
        )

        publication = load_publication_record(root, validated.publication_id)
        if publication.work != validated.work:
            raise EvidenceEligibilityDependencyError(
                "Core Publication Record work does not match evidence source work."
            )
        series = list_publication_record_set(
            root,
            publication.work,
            publication.publication_kind,
            publication.record_set_id,
        )
        ids = tuple(item.publication_id for item in series)
        try:
            index = ids.index(publication.publication_id)
        except ValueError as error:
            raise EvidenceEligibilityDependencyError(
                "Exact Publication Record is absent from its validated series."
            ) from error
        head = ids[-1]
        successor = None if index == len(ids) - 1 else ids[index + 1]
        withdrawal = load_publication_withdrawal(root, publication.publication_id)
    except EvidenceEligibilityDependencyError:
        raise
    except PublicationStorageError as error:
        raise EvidenceEligibilityDependencyError(
            f"Core publication lifecycle could not be validated: {error}"
        ) from error

    if successor is None and withdrawal is None:
        state = "current"
    elif successor is not None and withdrawal is None:
        state = "superseded"
    elif successor is None:
        state = "withdrawn"
    else:
        state = "withdrawn_superseded"
    return EvidenceSourceStateObservation(
        state=cast(
            Literal["current", "superseded", "withdrawn", "withdrawn_superseded"],
            state,
        ),
        head_publication_id=head,
        successor_publication_id=successor,
        withdrawn_at=(withdrawal.withdrawn_at if withdrawal is not None else None),
    )


def validate_authorized_evidence_source(
    source: EvidenceSourceReference,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> EvidenceItem:
    """Verify an exact source against a previously authorized immutable snapshot."""
    from meridian.evidence import EvidenceItem
    from meridian.projection_cache import AuthorizedProjectionSnapshot

    validated = validate_evidence_source_reference(source)
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise EvidenceEligibilityDependencyError(
            "Evidence access requires an AuthorizedProjectionSnapshot."
        )
    stored = authorized_snapshot.stored
    snapshot = stored.snapshot
    if stored.cache_key != validated.cache_key:
        raise EvidenceEligibilityDependencyError(
            "Authorized snapshot cache_key does not match evidence source."
        )
    if stored.snapshot_digest != validated.snapshot_digest:
        raise EvidenceEligibilityDependencyError(
            "Authorized snapshot digest does not match evidence source."
        )
    if snapshot.source.publication.publication_id != validated.publication_id:
        raise EvidenceEligibilityDependencyError(
            "Authorized snapshot publication does not match evidence source."
        )
    if snapshot.source.publication.work != validated.work:
        raise EvidenceEligibilityDependencyError(
            "Authorized snapshot work does not match evidence source."
        )
    matches = tuple(
        item for item in snapshot.inventory.items if item.item_id == validated.item_id
    )
    if len(matches) != 1:
        raise EvidenceEligibilityDependencyError(
            "Evidence source item_id must resolve exactly once in authorized snapshot."
        )
    item = matches[0]
    if not isinstance(item, EvidenceItem):
        raise EvidenceEligibilityDependencyError(
            "Authorized snapshot item has an invalid evidence type."
        )
    if (
        item.provenance.publication_id != validated.publication_id
        or item.provenance.work != validated.work
        or item.provenance.projection
        != snapshot.projection.evidence_projection_identity
    ):
        raise EvidenceEligibilityDependencyError(
            "Evidence item provenance does not match exact snapshot source."
        )
    return item


def validate_evidence_eligibility_dependencies(
    workspace_root: str | Path,
    decision: EvidenceEligibilityDecision,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    *,
    require_current_membership: bool,
    require_authored_source_state: bool,
) -> EvidenceEligibilityDependencies:
    """Validate exact membership, authorized evidence, and current source lifecycle."""
    from meridian.grade_item_membership_storage import (
        GradeItemMembershipStorageError,
        get_current_grade_item_membership_revision,
        load_grade_item_membership_revision,
    )

    candidate = validate_evidence_eligibility_decision(decision)
    root = _root(workspace_root)
    evidence_item = validate_authorized_evidence_source(
        candidate.source, authorized_snapshot
    )
    try:
        membership = load_grade_item_membership_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.source.work,
            candidate.membership_revision,
        )
    except GradeItemMembershipStorageError as error:
        raise EvidenceEligibilityDependencyError(
            f"Exact Grade Item membership could not be validated: {error}"
        ) from error
    if membership.decision_sha256 != candidate.membership_revision_sha256:
        raise EvidenceEligibilityDependencyError(
            "Membership revision SHA-256 does not match eligibility decision."
        )
    if membership.decision.decision != "included":
        raise EvidenceEligibilityDependencyError(
            "Evidence eligibility requires an included Grade Item membership."
        )
    if membership.decision.work_reference.work != candidate.source.work:
        raise EvidenceEligibilityDependencyError(
            "Membership work does not match evidence source work."
        )
    if require_current_membership:
        try:
            current_membership = get_current_grade_item_membership_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.source.work,
            )
        except GradeItemMembershipStorageError as error:
            raise EvidenceEligibilityDependencyError(
                f"Current Grade Item membership could not be validated: {error}"
            ) from error
        if current_membership != candidate.membership_revision:
            raise EvidenceEligibilityStorageConflictError(
                "Current Grade Item membership changed since eligibility review."
            )

    current_source_state = observe_evidence_source_state(root, candidate.source)
    if require_authored_source_state and current_source_state != candidate.source_state:
        raise EvidenceEligibilityStorageConflictError(
            "Core source lifecycle changed since eligibility decision was authored."
        )
    if candidate.disposition == "included" and current_source_state.state in {
        "withdrawn",
        "withdrawn_superseded",
    }:
        raise EvidenceEligibilityDependencyError(
            "Withdrawn source evidence cannot be operative as included."
        )
    if (
        candidate.disposition == "superseded"
        and current_source_state.state != "superseded"
    ):
        raise EvidenceEligibilityDependencyError(
            "Superseded disposition no longer matches current source lifecycle."
        )
    if candidate.disposition == "withdrawn" and current_source_state.state not in {
        "withdrawn",
        "withdrawn_superseded",
    }:
        raise EvidenceEligibilityDependencyError(
            "Withdrawn disposition requires current Core withdrawal state."
        )
    return EvidenceEligibilityDependencies(
        membership=membership,
        authorized_snapshot=authorized_snapshot,
        evidence_item=evidence_item,
        current_source_state=current_source_state,
    )


def load_evidence_eligibility_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    eligibility_revision: int,
    *,
    maximum_revision_bytes: int = DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_REVISION_BYTES,
) -> StoredEvidenceEligibilityDecision:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_source = validate_evidence_source_reference(source)
    if validated_source.work.class_id != class_value:
        raise EvidenceEligibilityStorageValidationError(
            "source work class_id must match class_id."
        )
    revision_number = _positive_int(eligibility_revision, "eligibility_revision")
    root = _root(workspace_root)
    path = evidence_eligibility_revision_path(
        root, class_value, item, validated_source, revision_number
    )
    digest_path = evidence_eligibility_revision_digest_path(
        root, class_value, item, validated_source, revision_number
    )
    _validate_existing_directory_chain(root, path.parent)
    content = _read_bounded_regular_file(
        path,
        maximum_revision_bytes,
        missing_message="Evidence eligibility revision does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_DIGEST_BYTES,
        missing_message="Evidence eligibility revision digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise EvidenceEligibilityStorageIntegrityError(
            "Evidence eligibility revision digest does not match exact JSON bytes."
        )
    try:
        decision = evidence_eligibility_decision_from_json_bytes(content)
    except (
        EvidenceEligibilitySerializationError,
        EvidenceEligibilityValidationError,
    ) as error:
        raise EvidenceEligibilityStorageIntegrityError(
            f"Evidence eligibility revision is invalid or noncanonical: {error}"
        ) from error
    if (
        decision.class_id != class_value
        or decision.grade_item_id != item
        or decision.source != validated_source
        or decision.eligibility_revision != revision_number
    ):
        raise EvidenceEligibilityStorageIntegrityError(
            "Persisted eligibility identity does not match its canonical path."
        )
    return StoredEvidenceEligibilityDecision(
        decision=decision,
        decision_sha256=actual_digest,
        path=path,
        relative_path=evidence_eligibility_revision_relative_path(
            class_value, item, validated_source, revision_number
        ),
        content=content,
    )


def list_evidence_eligibility_revisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> tuple[int, ...]:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_source = validate_evidence_source_reference(source)
    root = _root(workspace_root)
    relation = evidence_eligibility_source_directory(
        root, class_value, item, validated_source
    )
    if not relation.exists():
        return ()
    _validate_existing_directory_chain(root, relation)
    _validate_source_directory_entries(relation)
    revisions_dir = relation / "revisions"
    if not revisions_dir.exists():
        return ()
    _validate_existing_directory_chain(root, revisions_dir)
    json_revisions: set[int] = set()
    digest_revisions: set[int] = set()
    try:
        entries = tuple(revisions_dir.iterdir())
    except OSError as error:
        raise EvidenceEligibilityStorageReadError(
            "Could not enumerate evidence eligibility revision storage."
        ) from error
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility revision storage contains a nonregular entry."
            )
        json_match = _REVISION_JSON.fullmatch(entry.name)
        digest_match = _REVISION_DIGEST.fullmatch(entry.name)
        if json_match is not None:
            json_revisions.add(int(json_match.group(1)))
        elif digest_match is not None:
            digest_revisions.add(int(digest_match.group(1)))
        else:
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility revision storage contains an unexpected file."
            )
    if json_revisions != digest_revisions:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility revision JSON and SHA-256 sidecars are incomplete."
        )
    revisions = tuple(sorted(json_revisions))
    if revisions and revisions != tuple(range(1, revisions[-1] + 1)):
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility revision history is not contiguous from revision 1."
        )
    previous: EvidenceEligibilityDecision | None = None
    for number in revisions:
        stored = load_evidence_eligibility_revision(
            root, class_value, item, validated_source, number
        )
        if previous is not None:
            try:
                validate_evidence_eligibility_transition(previous, stored.decision)
            except EvidenceEligibilityValidationError as error:
                raise EvidenceEligibilityStorageIntegrityError(
                    f"Eligibility revision history is invalid: {error}"
                ) from error
        previous = stored.decision
    return revisions


def list_evidence_eligibility_sources(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
) -> tuple[EvidenceSourceReference, ...]:
    """List exact source histories deterministically for one membership relation."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_work = _work(work)
    root = _root(workspace_root)
    collection = evidence_eligibility_collection_directory(
        root, class_value, item, validated_work
    )
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    sources: list[tuple[str, EvidenceSourceReference]] = []
    for source_dir in _visible_directories(collection, "evidence eligibility source"):
        key = _sha256(source_dir.name, "source_key")
        revisions_dir = source_dir / "revisions"
        if not revisions_dir.exists():
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility source exists without immutable revision history."
            )
        revision_one = source_dir / "revisions" / "1.json"
        content = _read_bounded_regular_file(
            revision_one,
            DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_REVISION_BYTES,
            missing_message="Eligibility source revision 1 does not exist.",
        )
        try:
            decision = evidence_eligibility_decision_from_json_bytes(content)
        except (
            EvidenceEligibilitySerializationError,
            EvidenceEligibilityValidationError,
        ) as error:
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility source revision 1 is invalid."
            ) from error
        if evidence_source_key(decision.source) != key:
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility source directory key does not match persisted source."
            )
        list_evidence_eligibility_revisions(
            root, class_value, item, decision.source
        )
        sources.append((key, decision.source))
    return tuple(source for _, source in sorted(sources, key=lambda pair: pair[0]))


def write_evidence_eligibility_revision(
    workspace_root: str | Path,
    decision: EvidenceEligibilityDecision,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> EvidenceEligibilityRevisionWriteResult:
    """Persist one grounded immutable eligibility revision without selecting it."""
    candidate = validate_evidence_eligibility_decision(decision)
    root = _root(workspace_root)
    relation = evidence_eligibility_source_directory(
        root, candidate.class_id, candidate.grade_item_id, candidate.source
    )
    target = evidence_eligibility_revision_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.source,
        candidate.eligibility_revision,
    )
    digest_target = evidence_eligibility_revision_digest_path(
        root,
        candidate.class_id,
        candidate.grade_item_id,
        candidate.source,
        candidate.eligibility_revision,
    )
    content = evidence_eligibility_decision_to_json_bytes(candidate)
    if len(content) > DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_REVISION_BYTES:
        raise EvidenceEligibilityStorageWriteError(
            "Eligibility revision exceeds the canonical storage byte limit."
        )
    digest = hashlib.sha256(content).hexdigest()

    if target.exists() or digest_target.exists():
        try:
            stored = load_evidence_eligibility_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.source,
                candidate.eligibility_revision,
            )
        except EvidenceEligibilityStorageError as error:
            raise EvidenceEligibilityStorageIntegrityError(
                "Existing eligibility revision identity is incomplete or invalid."
            ) from error
        if stored.content != content or stored.decision_sha256 != digest:
            raise EvidenceEligibilityStorageConflictError(
                "Eligibility revision identity already exists with different content."
            )
        return EvidenceEligibilityRevisionWriteResult(
            disposition="existing", stored=stored
        )

    # Validate all external dependencies before creating any #29 storage.
    validate_evidence_eligibility_dependencies(
        root,
        candidate,
        authorized_snapshot,
        require_current_membership=False,
        require_authored_source_state=True,
    )
    revisions_dir = relation / "revisions"
    _ensure_directory_chain(root, revisions_dir)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_source_directory_entries(relation)
        # Another writer may have committed this exact identity while dependencies
        # were being validated. Re-check under the per-source lock.
        if target.exists() or digest_target.exists():
            try:
                stored = load_evidence_eligibility_revision(
                    root,
                    candidate.class_id,
                    candidate.grade_item_id,
                    candidate.source,
                    candidate.eligibility_revision,
                )
            except EvidenceEligibilityStorageError as error:
                raise EvidenceEligibilityStorageIntegrityError(
                    "Existing eligibility revision identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.decision_sha256 != digest:
                raise EvidenceEligibilityStorageConflictError(
                    "Eligibility revision identity already exists with "
                    "different content."
                )
            return EvidenceEligibilityRevisionWriteResult(
                disposition="existing", stored=stored
            )

        history = list_evidence_eligibility_revisions(
            root, candidate.class_id, candidate.grade_item_id, candidate.source
        )
        if not history:
            if candidate.eligibility_revision != 1:
                raise EvidenceEligibilityStorageConflictError(
                    "Initial eligibility revision must be revision 1."
                )
        else:
            expected = history[-1] + 1
            if candidate.eligibility_revision != expected:
                raise EvidenceEligibilityStorageConflictError(
                    "Eligibility revision must be exactly one greater than history."
                )
            previous = load_evidence_eligibility_revision(
                root,
                candidate.class_id,
                candidate.grade_item_id,
                candidate.source,
                history[-1],
            ).decision
            try:
                validate_evidence_eligibility_transition(previous, candidate)
            except EvidenceEligibilityValidationError as error:
                raise EvidenceEligibilityStorageConflictError(str(error)) from error
        _write_revision_pair_exclusively(target, digest_target, content, digest)
        stored = load_evidence_eligibility_revision(
            root,
            candidate.class_id,
            candidate.grade_item_id,
            candidate.source,
            candidate.eligibility_revision,
        )
        return EvidenceEligibilityRevisionWriteResult(
            disposition="created", stored=stored
        )
    finally:
        _remove_lock(lock)


def get_current_evidence_eligibility_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> int | None:
    selection = _load_current_selection(
        workspace_root, class_id, grade_item_id, source, missing_ok=True
    )
    return selection.eligibility_revision if selection is not None else None


def load_current_evidence_eligibility_decision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
) -> StoredEvidenceEligibilityDecision | None:
    selection = _load_current_selection(
        workspace_root, class_id, grade_item_id, source, missing_ok=True
    )
    if selection is None:
        return None
    stored = load_evidence_eligibility_revision(
        workspace_root,
        class_id,
        grade_item_id,
        source,
        selection.eligibility_revision,
    )
    if stored.decision_sha256 != selection.decision_sha256:
        raise EvidenceEligibilityStorageIntegrityError(
            "Current eligibility pointer digest does not match selected revision."
        )
    return stored


def select_evidence_eligibility_revision(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    eligibility_revision: int,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    expected_current_eligibility_revision: int | None,
) -> EvidenceEligibilitySelectionResult:
    """Explicitly select one eligibility revision with dependency/CAS validation."""
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_source = validate_evidence_source_reference(source)
    revision_number = _positive_int(eligibility_revision, "eligibility_revision")
    expected = (
        None
        if expected_current_eligibility_revision is None
        else _positive_int(
            expected_current_eligibility_revision,
            "expected_current_eligibility_revision",
        )
    )
    root = _root(workspace_root)
    relation = evidence_eligibility_source_directory(
        root, class_value, item, validated_source
    )
    _validate_existing_directory_chain(root, relation)
    lock = relation / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_source_directory_entries(relation)
        target = load_evidence_eligibility_revision(
            root, class_value, item, validated_source, revision_number
        )
        dependencies = validate_evidence_eligibility_dependencies(
            root,
            target.decision,
            authorized_snapshot,
            require_current_membership=True,
            require_authored_source_state=False,
        )
        current = _load_current_selection(
            root, class_value, item, validated_source, missing_ok=True
        )
        current_revision = (
            current.eligibility_revision if current is not None else None
        )
        if current_revision != expected:
            raise EvidenceEligibilityStorageConflictError(
                "Expected current eligibility revision does not match stored selection."
            )
        selection = EvidenceEligibilityCurrentSelection(
            schema_version=EVIDENCE_ELIGIBILITY_CURRENT_SCHEMA_VERSION,
            record_type=EVIDENCE_ELIGIBILITY_CURRENT_RECORD_TYPE,
            class_id=class_value,
            grade_item_id=item,
            source_key=evidence_source_key(validated_source),
            eligibility_revision=revision_number,
            decision_sha256=target.decision_sha256,
        )
        if current == selection:
            return EvidenceEligibilitySelectionResult(
                disposition="existing",
                selection=selection,
                stored=target,
                dependencies=dependencies,
            )
        _publish_current_selection(root, validated_source, selection)
        verified = _load_current_selection(
            root, class_value, item, validated_source, missing_ok=False
        )
        if verified != selection:
            raise EvidenceEligibilityStorageIntegrityError(
                "Published eligibility selection could not be verified."
            )
        disposition: EvidenceEligibilitySelectionDisposition = (
            "created" if current is None else "updated"
        )
        return EvidenceEligibilitySelectionResult(
            disposition=disposition,
            selection=selection,
            stored=target,
            dependencies=dependencies,
        )
    finally:
        _remove_lock(lock)


def resolve_current_evidence_eligibility(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> EvidenceEligibilityResolution:
    """Resolve selected eligibility against current membership/source state."""
    from meridian.grade_item_membership_storage import (
        GradeItemMembershipStorageError,
        load_current_grade_item_membership_decision,
    )

    validated_source = validate_evidence_source_reference(source)
    validate_authorized_evidence_source(validated_source, authorized_snapshot)
    selected = load_current_evidence_eligibility_decision(
        workspace_root, class_id, grade_item_id, validated_source
    )
    try:
        current_source = observe_evidence_source_state(
            workspace_root, validated_source
        )
    except EvidenceEligibilityDependencyError:
        return EvidenceEligibilityResolution(
            status="source_unverifiable",
            selected=selected,
            current_source_state=None,
            current_membership_revision=None,
            operative_included=False,
        )
    try:
        current_membership = load_current_grade_item_membership_decision(
            workspace_root,
            class_id,
            grade_item_id,
            validated_source.work,
        )
    except GradeItemMembershipStorageError:
        current_membership = None
    current_membership_revision = (
        current_membership.decision.membership_revision
        if current_membership is not None
        else None
    )
    if selected is None:
        return EvidenceEligibilityResolution(
            status="no_decision",
            selected=None,
            current_source_state=current_source,
            current_membership_revision=current_membership_revision,
            operative_included=False,
        )
    decision = selected.decision
    membership_matches = (
        current_membership is not None
        and current_membership.decision.decision == "included"
        and current_membership.decision.membership_revision
        == decision.membership_revision
        and current_membership.decision_sha256 == decision.membership_revision_sha256
    )
    if not membership_matches:
        status: EvidenceEligibilityResolutionStatus = "membership_stale"
        operative = False
    elif decision.disposition == "included":
        if current_source.state == "current":
            status = "included"
            operative = True
        elif current_source.state == "superseded":
            status = "included_source_superseded"
            operative = True
        else:
            status = "included_source_withdrawn"
            operative = False
    else:
        status = cast(EvidenceEligibilityResolutionStatus, decision.disposition)
        operative = False
    return EvidenceEligibilityResolution(
        status=status,
        selected=selected,
        current_source_state=current_source,
        current_membership_revision=current_membership_revision,
        operative_included=operative,
    )


def _load_current_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    *,
    missing_ok: bool,
) -> EvidenceEligibilityCurrentSelection | None:
    class_value = _identifier(class_id, "class_id")
    item = _identifier(grade_item_id, "grade_item_id")
    validated_source = validate_evidence_source_reference(source)
    root = _root(workspace_root)
    relation = evidence_eligibility_source_directory(
        root, class_value, item, validated_source
    )
    if not relation.exists():
        if missing_ok:
            return None
        raise EvidenceEligibilityStorageNotFoundError(
            "Evidence eligibility source history does not exist."
        )
    _validate_existing_directory_chain(root, relation)
    _validate_source_directory_entries(relation)
    path = relation / "current.json"
    if not path.exists():
        if missing_ok:
            return None
        raise EvidenceEligibilityStorageNotFoundError(
            "Evidence eligibility has no explicit current selection."
        )
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_EVIDENCE_ELIGIBILITY_POINTER_BYTES,
        missing_message="Evidence eligibility current pointer does not exist.",
    )
    selection = _current_selection_from_json_bytes(content)
    if (
        selection.class_id != class_value
        or selection.grade_item_id != item
        or selection.source_key != evidence_source_key(validated_source)
    ):
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer identity does not match canonical path."
        )
    return selection


def _current_selection_to_dict(
    value: EvidenceEligibilityCurrentSelection,
) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "source_key": value.source_key,
        "eligibility_revision": value.eligibility_revision,
        "decision_sha256": value.decision_sha256,
    }


def _current_selection_to_json_bytes(
    value: EvidenceEligibilityCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(_current_selection_to_dict(value))


def _current_selection_from_json_bytes(
    data: bytes,
) -> EvidenceEligibilityCurrentSelection:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except EvidenceEligibilityStorageIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer is not valid JSON."
        ) from error
    if not isinstance(decoded, dict) or frozenset(decoded) != _POINTER_KEYS:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer does not use the exact schema."
        )
    try:
        selection = EvidenceEligibilityCurrentSelection(
            schema_version=_pointer_str(decoded["schema_version"], "schema_version"),
            record_type=_pointer_str(decoded["record_type"], "record_type"),
            class_id=_pointer_str(decoded["class_id"], "class_id"),
            grade_item_id=_pointer_str(decoded["grade_item_id"], "grade_item_id"),
            source_key=_pointer_str(decoded["source_key"], "source_key"),
            eligibility_revision=_positive_int(
                decoded["eligibility_revision"], "eligibility_revision"
            ),
            decision_sha256=_pointer_str(
                decoded["decision_sha256"], "decision_sha256"
            ),
        )
    except EvidenceEligibilityStorageValidationError as error:
        raise EvidenceEligibilityStorageIntegrityError(
            f"Eligibility current pointer is invalid: {error}"
        ) from error
    if _current_selection_to_json_bytes(selection) != data:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer is not canonically encoded."
        )
    return selection


def _publish_current_selection(
    workspace_root: str | Path,
    source: EvidenceSourceReference,
    selection: EvidenceEligibilityCurrentSelection,
) -> None:
    path = evidence_eligibility_current_path(
        workspace_root,
        selection.class_id,
        selection.grade_item_id,
        source,
    )
    if path.exists() and path.is_symlink():
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility current pointer must not be a symlink."
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
        raise EvidenceEligibilityStorageWriteError(
            "Could not publish evidence eligibility current selection."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _validate_source_directory_entries(relation: Path) -> None:
    if relation.is_symlink() or not relation.is_dir():
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility source root is unsafe or not a directory."
        )
    allowed = {"revisions", "current.json", ".write.lock"}
    try:
        entries = tuple(relation.iterdir())
    except OSError as error:
        raise EvidenceEligibilityStorageReadError(
            "Could not inspect eligibility source root."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility source root contains an unexpected entry."
            )
        if entry.name == "revisions":
            if entry.is_symlink() or not entry.is_dir():
                raise EvidenceEligibilityStorageIntegrityError(
                    "Eligibility revisions entry must be a real directory."
                )
        elif entry.name == "current.json":
            if entry.is_symlink() or not entry.is_file():
                raise EvidenceEligibilityStorageIntegrityError(
                    "Eligibility current pointer must be a regular file."
                )
        elif entry.is_symlink() or not entry.is_file():
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility lock entry must be a regular file."
            )


def _visible_directories(root: Path, label: str) -> tuple[Path, ...]:
    try:
        entries = tuple(root.iterdir())
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise EvidenceEligibilityStorageReadError(
            f"Could not enumerate {label} storage."
        ) from error
    result: list[Path] = []
    for entry in sorted(entries, key=lambda item: item.name):
        if entry.name.startswith("."):
            raise EvidenceEligibilityStorageIntegrityError(
                f"Unexpected hidden entry in {label} storage."
            )
        if entry.is_symlink() or not entry.is_dir():
            raise EvidenceEligibilityStorageIntegrityError(
                f"Unexpected non-directory entry in {label} storage."
            )
        result.append(entry)
    return tuple(result)


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
        raise EvidenceEligibilityStorageConflictError(
            "Eligibility revision identity already exists."
        ) from error
    except OSError as error:
        if digest_created:
            _remove_file(digest_path)
        if json_created:
            _remove_file(path)
        raise EvidenceEligibilityStorageWriteError(
            "Could not persist eligibility revision and digest."
        ) from error


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise EvidenceEligibilityStorageValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise EvidenceEligibilityStorageNotFoundError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise EvidenceEligibilityStorageIntegrityError(
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
                raise EvidenceEligibilityStorageIntegrityError(
                    "Eligibility directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise EvidenceEligibilityStorageWriteError(
                    "Could not create eligibility directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise EvidenceEligibilityStorageNotFoundError(
                "Required eligibility directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise EvidenceEligibilityStorageIntegrityError(
                "Eligibility directory chain is unsafe."
            )


def _require_lexical_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise EvidenceEligibilityStorageValidationError(
            "Eligibility path escapes the supplied workspace root."
        ) from error


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise EvidenceEligibilityStorageIntegrityError(
                    "Eligibility storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except EvidenceEligibilityStorageError:
        raise
    except FileNotFoundError as error:
        raise EvidenceEligibilityStorageNotFoundError(missing_message) from error
    except OSError as error:
        raise EvidenceEligibilityStorageReadError(
            "Could not read eligibility storage file."
        ) from error
    if len(content) > limit:
        raise EvidenceEligibilityStorageTooLargeError(
            "Eligibility storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "decision_sha256")
    except EvidenceEligibilityStorageValidationError as error:
        raise EvidenceEligibilityStorageIntegrityError(
            "Eligibility SHA-256 sidecar digest is invalid."
        ) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian evidence eligibility write lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise EvidenceEligibilityStorageLockError(
            "An evidence eligibility writer already owns this relationship."
        ) from error
    except OSError as error:
        raise EvidenceEligibilityStorageWriteError(
            "Could not acquire evidence eligibility write lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise EvidenceEligibilityStorageWriteError(
            "Could not remove evidence eligibility write lock."
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
        raise EvidenceEligibilityStorageValidationError(
            "Eligibility selection cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceEligibilityStorageIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise EvidenceEligibilityStorageIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceEligibilityStorageValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise EvidenceEligibilityStorageValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceEligibilityStorageValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceEligibilityStorageValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise EvidenceEligibilityStorageValidationError(
            "work must be a ModuleWorkRef."
        )
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise EvidenceEligibilityStorageValidationError(
            f"work is invalid: {error}"
        ) from error


def _pointer_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceEligibilityStorageValidationError(
            f"eligibility pointer {field_name} must be a string."
        )
    return value
