"""Immutable digest-bound snapshots of exact Meridian evidence projections."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final, Literal, Protocol, TypeAlias, cast, runtime_checkable

from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    academic_work_registration_from_dict,
    academic_work_registration_to_dict,
    validate_academic_work_registration,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.publication_compatibility import (
    PublicationCompatibilityError,
    PublicationProducerProfileError,
    PublicationProducerRegistry,
    PublicationProducerRegistryError,
    evaluate_publication_compatibility,
)
from pds_core.publication_records import (
    PublicationKind,
    PublicationRecord,
    PublicationWithdrawal,
    publication_record_from_dict,
    publication_record_to_dict,
    publication_withdrawal_from_dict,
    publication_withdrawal_to_dict,
    validate_publication_record,
    validate_publication_withdrawal,
    validate_publication_withdrawal_relationship,
)
from pds_core.publication_storage import (
    PublicationManifestError,
    PublicationManifestIntegrityError,
    PublicationManifestNotFoundError,
    verify_publication_manifest,
)

from meridian.adapters import (
    AdapterCapabilityUnsupportedError,
    AdapterDescriptor,
    AdapterKey,
    AdapterMatch,
    AdapterNotFoundError,
    AdapterRegistry,
    DistributionVersionResolver,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
    installed_distribution_version,
    resolve_producer_reader_version,
    validate_projected_inventory,
)
from meridian.evidence import EvidenceInventory, ProjectionIdentity
from meridian.evidence_serialization import (
    EvidenceSerializationError,
    evidence_inventory_from_dict,
    evidence_inventory_to_dict,
)
from meridian.ingestion import (
    CanonicalPublicationContext,
    CanonicalPublicationState,
    PreparedPublicationInvocation,
    PublicationAuthorizationDecision,
    PublicationAuthorizationError,
    PublicationAuthorizationRequest,
    PublicationAuthorizer,
    PublicationIngestionError,
    load_canonical_publication_context,
)

__all__ = [
    "AuthorizedProjectionSnapshot",
    "Clock",
    "DEFAULT_MAXIMUM_PROJECTION_SNAPSHOT_BYTES",
    "PROJECTION_SNAPSHOT_RECORD_TYPE",
    "PROJECTION_SNAPSHOT_SCHEMA_VERSION",
    "ProjectionAuthorizationObservation",
    "ProjectionCacheAssessment",
    "ProjectionCacheAuthorizationDeniedError",
    "ProjectionCacheAuthorizationError",
    "ProjectionCacheConflictError",
    "ProjectionCacheDisposition",
    "ProjectionCacheDurableState",
    "ProjectionCacheError",
    "ProjectionCacheIdentity",
    "ProjectionCacheIntegrityError",
    "ProjectionCacheLockError",
    "ProjectionCacheNondeterminismError",
    "ProjectionCacheNotFoundError",
    "ProjectionCachePartialSuccessError",
    "ProjectionCacheReadError",
    "ProjectionCacheSourceChangedError",
    "ProjectionCacheTooLargeError",
    "ProjectionCacheValidationError",
    "ProjectionCacheWriteError",
    "ProjectionCacheWriteResult",
    "ProjectionExecutionIdentity",
    "ProjectionReuseStatus",
    "ProjectionSnapshot",
    "ProjectionSourceObservation",
    "ProjectionSourceStatus",
    "StoredProjectionSnapshot",
    "assess_projection_snapshot",
    "cache_projected_inventory",
    "load_authorized_projection_snapshot",
    "projection_cache_directory",
    "projection_cache_key",
    "projection_cache_path",
    "projection_cache_relative_path",
    "projection_snapshot_from_dict",
    "projection_snapshot_from_json_bytes",
    "projection_snapshot_to_dict",
    "projection_snapshot_to_json_bytes",
    "utc_now",
]

PROJECTION_SNAPSHOT_SCHEMA_VERSION: Final[str] = "1"
PROJECTION_SNAPSHOT_RECORD_TYPE: Final[str] = "meridian_projection_snapshot"
DEFAULT_MAXIMUM_PROJECTION_SNAPSHOT_BYTES: Final[int] = 64 * 1024 * 1024

ProjectionCacheDisposition: TypeAlias = Literal["created", "existing"]
ProjectionSourceStatus: TypeAlias = Literal[
    "current",
    "superseded",
    "withdrawn",
    "withdrawn_superseded",
    "unverifiable",
]
ProjectionReuseStatus: TypeAlias = Literal[
    "reusable",
    "reprojection_required",
    "historical_only",
    "unverifiable",
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REASON_ORDER: Final[tuple[str, ...]] = (
    "cache.canonical_unverifiable",
    "cache.manifest_unverifiable",
    "cache.source_superseded",
    "cache.source_withdrawn",
    "cache.current_registration_changed",
    "cache.series_changed",
    "cache.profile_missing",
    "cache.profile_incompatible",
    "cache.profile_evaluation_failed",
    "cache.adapter_missing",
    "cache.adapter_changed",
    "cache.adapter_capability_changed",
    "cache.reader_unavailable",
    "cache.reader_version_changed",
    "cache.projection_authorization_denied",
    "cache.projection_authorization_changed",
)

_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "publication",
        "referenced_registration",
        "current_registration",
        "withdrawal",
        "series_publication_ids",
        "target_index",
        "head_publication_id",
        "successor_publication_id",
        "canonical_state",
    }
)
_ADAPTER_KEY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "producer_module_id",
        "publication_kind",
        "manifest_contract_version",
        "producer_contract_version",
        "source_record_kind",
        "source_record_contract_version",
    }
)
_EXECUTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "adapter_key",
        "adapter_id",
        "adapter_interface_version",
        "projection_contract_version",
        "producer_reader_distribution",
        "producer_reader_version",
    }
)
_AUTHORIZATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "operation",
        "purpose_id",
        "requested_student_ids",
        "policy_id",
        "policy_version",
    }
)
_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "source", "projection", "authorization"}
)
_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "cache_key",
        "captured_at",
        "source",
        "projection",
        "authorization",
        "inventory",
    }
)


class ProjectionCacheError(RuntimeError):
    """Base error for projection snapshot and cache failures."""

    code: str = "cache.error"

    def __init__(
        self,
        message: str,
        *,
        publication_id: str | None = None,
        cache_key: str | None = None,
        snapshot_digest: str | None = None,
        relative_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.publication_id = publication_id
        self.cache_key = cache_key
        self.snapshot_digest = snapshot_digest
        self.relative_path = relative_path


class ProjectionCacheValidationError(ProjectionCacheError, ValueError):
    code = "cache.invalid"


class ProjectionCacheNotFoundError(ProjectionCacheError):
    code = "cache.not_found"


class ProjectionCacheReadError(ProjectionCacheError):
    code = "cache.read_failed"


class ProjectionCacheTooLargeError(ProjectionCacheReadError):
    code = "cache.too_large"

    def __init__(
        self,
        publication_id: str,
        cache_key: str,
        maximum_snapshot_bytes: int,
    ) -> None:
        super().__init__(
            "The projection snapshot exceeds the configured byte limit.",
            publication_id=publication_id,
            cache_key=cache_key,
        )
        self.maximum_snapshot_bytes = maximum_snapshot_bytes


class ProjectionCacheIntegrityError(ProjectionCacheError):
    code = "cache.integrity"


class ProjectionCacheConflictError(ProjectionCacheError):
    code = "cache.conflict"


class ProjectionCacheLockError(ProjectionCacheConflictError):
    code = "cache.locked"


class ProjectionCacheSourceChangedError(ProjectionCacheConflictError):
    code = "cache.source_changed"


class ProjectionCacheAuthorizationError(ProjectionCacheError):
    code = "cache.authorization_invalid"


class ProjectionCacheAuthorizationDeniedError(ProjectionCacheAuthorizationError):
    code = "cache.authorization_denied"

    def __init__(
        self,
        *,
        publication_id: str,
        policy_id: str,
        policy_version: str,
        reason_codes: tuple[str, ...],
    ) -> None:
        super().__init__(
            "The deployment denied access to the projection cache.",
            publication_id=publication_id,
        )
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.reason_codes = reason_codes


class ProjectionCacheNondeterminismError(ProjectionCacheConflictError):
    code = "cache.projection_nondeterministic"


class ProjectionCacheWriteError(ProjectionCacheError):
    code = "cache.write_failed"


@dataclass(frozen=True, slots=True)
class ProjectionCacheDurableState:
    operation: str
    publication_id: str
    cache_key: str
    snapshot_digest: str | None
    relative_path: str | None
    durable_file: bool
    cleanup_failure: str | None = None


class ProjectionCachePartialSuccessError(ProjectionCacheWriteError):
    code = "cache.partial_success"

    def __init__(self, message: str, state: ProjectionCacheDurableState) -> None:
        super().__init__(
            message,
            publication_id=state.publication_id,
            cache_key=state.cache_key,
            snapshot_digest=state.snapshot_digest,
            relative_path=state.relative_path,
        )
        self.state = state


@runtime_checkable
class Clock(Protocol):
    def __call__(self) -> datetime: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def _mapping(value: object, keys: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionCacheValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise ProjectionCacheValidationError(f"{label} keys must be strings.")
    mapping = cast(Mapping[str, object], value)
    actual = frozenset(mapping)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ProjectionCacheValidationError(
            f"{label} has an invalid key set; missing={missing!r}, unknown={unknown!r}."
        )
    return mapping


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ProjectionCacheValidationError(f"{label} must be a string.")
    if not value or value != value.strip():
        raise ProjectionCacheValidationError(
            f"{label} must be nonempty and have no surrounding whitespace."
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise ProjectionCacheValidationError(
            f"{label} must be a control-free single-line string."
        )
    return value


def _identifier(value: object, label: str) -> str:
    text = _string(value, label)
    try:
        return validate_identifier(text, label)
    except IdentifierValidationError as error:
        raise ProjectionCacheValidationError(str(error)) from error


def _sha256(value: object, label: str) -> str:
    text = _string(value, label)
    if _SHA256.fullmatch(text) is None:
        raise ProjectionCacheValidationError(
            f"{label} must contain 64 lowercase hexadecimal characters."
        )
    return text


def _positive_limit(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProjectionCacheValidationError(f"{label} must be a positive integer.")
    return value


def _aware_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ProjectionCacheValidationError(f"{label} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProjectionCacheValidationError(f"{label} must be timezone-aware.")
    return value


def _datetime_from_text(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as error:
        raise ProjectionCacheValidationError(
            f"{label} is not a valid datetime."
        ) from error
    return _aware_datetime(result, label)


def _student_ids(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ProjectionCacheValidationError("requested_student_ids must be a list.")
    try:
        raw = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise ProjectionCacheValidationError(
            "requested_student_ids must be iterable."
        ) from error
    result = tuple(sorted(_identifier(item, "student_id") for item in raw))
    if len(set(result)) != len(result):
        raise ProjectionCacheValidationError(
            "requested_student_ids must not contain duplicates."
        )
    return result


def _optional_registration(data: object) -> AcademicWorkRegistration | None:
    if data is None:
        return None
    try:
        return academic_work_registration_from_dict(data)
    except ValueError as error:
        raise ProjectionCacheValidationError("registration is invalid.") from error


def _optional_withdrawal(data: object) -> PublicationWithdrawal | None:
    if data is None:
        return None
    try:
        return publication_withdrawal_from_dict(data)
    except ValueError as error:
        raise ProjectionCacheValidationError("withdrawal is invalid.") from error


@dataclass(frozen=True, slots=True)
class ProjectionSourceObservation:
    publication: PublicationRecord
    referenced_registration: AcademicWorkRegistration | None
    current_registration: AcademicWorkRegistration | None
    withdrawal: PublicationWithdrawal | None
    series_publication_ids: tuple[str, ...]
    target_index: int
    head_publication_id: str
    successor_publication_id: str | None
    canonical_state: CanonicalPublicationState

    def __post_init__(self) -> None:
        try:
            publication = validate_publication_record(self.publication)
        except ValueError as error:
            raise ProjectionCacheValidationError("publication is invalid.") from error
        referenced: AcademicWorkRegistration | None = None
        if self.referenced_registration is not None:
            try:
                referenced = validate_academic_work_registration(
                    self.referenced_registration
                )
            except ValueError as error:
                raise ProjectionCacheValidationError(
                    "referenced_registration is invalid."
                ) from error
        current: AcademicWorkRegistration | None = None
        if self.current_registration is not None:
            try:
                current = validate_academic_work_registration(
                    self.current_registration
                )
            except ValueError as error:
                raise ProjectionCacheValidationError(
                    "current_registration is invalid."
                ) from error
        withdrawal: PublicationWithdrawal | None = None
        if self.withdrawal is not None:
            try:
                withdrawal = validate_publication_withdrawal(self.withdrawal)
                validate_publication_withdrawal_relationship(publication, withdrawal)
            except ValueError as error:
                raise ProjectionCacheValidationError(
                    "withdrawal is invalid."
                ) from error
        if publication.publication_kind == "academic_result_set":
            if referenced is None:
                raise ProjectionCacheValidationError(
                    "academic source requires the referenced registration."
                )
            if (
                referenced.work != publication.work
                or referenced.registration_revision
                != publication.academic_work_registration_revision
            ):
                raise ProjectionCacheValidationError(
                    "referenced registration must match the publication exactly."
                )
            if current is not None and current.work != publication.work:
                raise ProjectionCacheValidationError(
                    "current registration must match the publication work."
                )
        elif referenced is not None or current is not None:
            raise ProjectionCacheValidationError(
                "intervention source must not include registration state."
            )
        ids = tuple(
            _identifier(item, "series publication ID")
            for item in self.series_publication_ids
        )
        if not ids:
            raise ProjectionCacheValidationError(
                "series_publication_ids must not be empty."
            )
        if len(set(ids)) != len(ids):
            raise ProjectionCacheValidationError(
                "series_publication_ids must not contain duplicates."
            )
        if (
            isinstance(self.target_index, bool)
            or not isinstance(self.target_index, int)
            or not 0 <= self.target_index < len(ids)
        ):
            raise ProjectionCacheValidationError("target_index is outside the series.")
        if ids[self.target_index] != publication.publication_id:
            raise ProjectionCacheValidationError(
                "target_index must identify the source publication."
            )
        head = _identifier(self.head_publication_id, "head_publication_id")
        if ids[-1] != head:
            raise ProjectionCacheValidationError(
                "head_publication_id must identify the final series member."
            )
        expected_successor = (
            None if self.target_index == len(ids) - 1 else ids[self.target_index + 1]
        )
        if self.successor_publication_id != expected_successor:
            raise ProjectionCacheValidationError(
                "successor_publication_id does not match series order."
            )
        if self.canonical_state not in {
            "current_selectable",
            "withdrawn_head",
            "historical",
            "withdrawn_historical",
        }:
            raise ProjectionCacheValidationError("canonical_state is invalid.")
        is_head = self.target_index == len(ids) - 1
        withdrawn = withdrawal is not None
        expected: CanonicalPublicationState
        if is_head and not withdrawn:
            expected = "current_selectable"
        elif is_head:
            expected = "withdrawn_head"
        elif withdrawn:
            expected = "withdrawn_historical"
        else:
            expected = "historical"
        if self.canonical_state != expected:
            raise ProjectionCacheValidationError(
                "canonical_state contradicts series and withdrawal state."
            )
        object.__setattr__(self, "publication", publication)
        object.__setattr__(self, "referenced_registration", referenced)
        object.__setattr__(self, "current_registration", current)
        object.__setattr__(self, "withdrawal", withdrawal)
        object.__setattr__(self, "series_publication_ids", ids)
        object.__setattr__(self, "head_publication_id", head)

    @classmethod
    def from_context(
        cls, context: CanonicalPublicationContext
    ) -> ProjectionSourceObservation:
        if not isinstance(context, CanonicalPublicationContext):
            raise ProjectionCacheValidationError(
                "context must be a CanonicalPublicationContext."
            )
        return cls(
            publication=context.publication,
            referenced_registration=context.referenced_registration,
            current_registration=context.current_registration,
            withdrawal=context.withdrawal,
            series_publication_ids=tuple(
                member.publication.publication_id for member in context.series.members
            ),
            target_index=context.series.target_index,
            head_publication_id=context.series.head_publication_id,
            successor_publication_id=context.series.successor_publication_id,
            canonical_state=context.canonical_state,
        )

    @property
    def current_registration_revision(self) -> int | None:
        if self.current_registration is None:
            return None
        return self.current_registration.registration_revision


@dataclass(frozen=True, slots=True)
class ProjectionExecutionIdentity:
    adapter_key: AdapterKey
    adapter_id: str
    adapter_interface_version: str
    projection_contract_version: str
    producer_reader_distribution: str
    producer_reader_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_key, AdapterKey):
            raise ProjectionCacheValidationError("adapter_key must be an AdapterKey.")
        object.__setattr__(self, "adapter_id", _string(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "adapter_interface_version",
            _string(self.adapter_interface_version, "adapter_interface_version"),
        )
        object.__setattr__(
            self,
            "projection_contract_version",
            _string(self.projection_contract_version, "projection_contract_version"),
        )
        object.__setattr__(
            self,
            "producer_reader_distribution",
            _string(self.producer_reader_distribution, "producer_reader_distribution"),
        )
        object.__setattr__(
            self,
            "producer_reader_version",
            _string(self.producer_reader_version, "producer_reader_version"),
        )

    @classmethod
    def from_match(
        cls, match: AdapterMatch, producer_reader_version: str
    ) -> ProjectionExecutionIdentity:
        if not isinstance(match, AdapterMatch):
            raise ProjectionCacheValidationError("match must be an AdapterMatch.")
        descriptor = match.descriptor
        return cls(
            adapter_key=match.key,
            adapter_id=descriptor.adapter_id,
            adapter_interface_version=descriptor.adapter_interface_version,
            projection_contract_version=descriptor.projection_contract_version,
            producer_reader_distribution=descriptor.producer_reader_distribution,
            producer_reader_version=producer_reader_version,
        )

    @property
    def evidence_projection_identity(self) -> ProjectionIdentity:
        return ProjectionIdentity(
            projection_id=self.adapter_id,
            projection_contract_version=self.projection_contract_version,
            producer_reader_distribution=self.producer_reader_distribution,
            producer_reader_version=self.producer_reader_version,
        )


@dataclass(frozen=True, slots=True)
class ProjectionAuthorizationObservation:
    operation: Literal["project_evidence"]
    purpose_id: str
    requested_student_ids: tuple[str, ...] = field(repr=False)
    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        if self.operation != "project_evidence":
            raise ProjectionCacheValidationError(
                "snapshot authorization operation must be project_evidence."
            )
        object.__setattr__(
            self, "purpose_id", _identifier(self.purpose_id, "purpose_id")
        )
        object.__setattr__(
            self, "requested_student_ids", _student_ids(self.requested_student_ids)
        )
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self, "policy_version", _identifier(self.policy_version, "policy_version")
        )

    @classmethod
    def from_prepared(
        cls, prepared: PreparedPublicationInvocation
    ) -> ProjectionAuthorizationObservation:
        request = prepared.authorization_request
        decision = prepared.authorization
        if request.operation != "project_evidence" or not decision.allowed:
            raise ProjectionCacheValidationError(
                "prepared invocation lacks an allowed projection authorization."
            )
        return cls(
            operation="project_evidence",
            purpose_id=request.purpose_id,
            requested_student_ids=request.requested_student_ids,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
        )


@dataclass(frozen=True, slots=True)
class ProjectionCacheIdentity:
    schema_version: str
    source: ProjectionSourceObservation
    projection: ProjectionExecutionIdentity
    authorization: ProjectionAuthorizationObservation

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SNAPSHOT_SCHEMA_VERSION:
            raise ProjectionCacheValidationError('schema_version must be "1".')
        if not isinstance(self.source, ProjectionSourceObservation):
            raise ProjectionCacheValidationError(
                "source must be a ProjectionSourceObservation."
            )
        if not isinstance(self.projection, ProjectionExecutionIdentity):
            raise ProjectionCacheValidationError(
                "projection must be a ProjectionExecutionIdentity."
            )
        if not isinstance(self.authorization, ProjectionAuthorizationObservation):
            raise ProjectionCacheValidationError(
                "authorization must be a ProjectionAuthorizationObservation."
            )
        if self.projection.adapter_key != _adapter_key_for_source(self.source):
            raise ProjectionCacheValidationError(
                "projection adapter key does not match the source contracts."
            )


@dataclass(frozen=True, slots=True)
class ProjectionSnapshot:
    schema_version: str
    record_type: str
    cache_key: str
    captured_at: datetime
    source: ProjectionSourceObservation
    projection: ProjectionExecutionIdentity
    authorization: ProjectionAuthorizationObservation = field(repr=False)
    inventory: EvidenceInventory = field(repr=False)

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SNAPSHOT_SCHEMA_VERSION:
            raise ProjectionCacheValidationError('schema_version must be "1".')
        if self.record_type != PROJECTION_SNAPSHOT_RECORD_TYPE:
            raise ProjectionCacheValidationError(
                'record_type must be "meridian_projection_snapshot".'
            )
        key = _sha256(self.cache_key, "cache_key")
        captured = _aware_datetime(self.captured_at, "captured_at")
        if not isinstance(self.source, ProjectionSourceObservation):
            raise ProjectionCacheValidationError(
                "source must be a ProjectionSourceObservation."
            )
        if not isinstance(self.projection, ProjectionExecutionIdentity):
            raise ProjectionCacheValidationError(
                "projection must be a ProjectionExecutionIdentity."
            )
        if not isinstance(self.authorization, ProjectionAuthorizationObservation):
            raise ProjectionCacheValidationError(
                "authorization must be a ProjectionAuthorizationObservation."
            )
        if not isinstance(self.inventory, EvidenceInventory):
            raise ProjectionCacheValidationError(
                "inventory must be an EvidenceInventory."
            )
        identity = ProjectionCacheIdentity(
            schema_version=self.schema_version,
            source=self.source,
            projection=self.projection,
            authorization=self.authorization,
        )
        if key != projection_cache_key(identity):
            raise ProjectionCacheValidationError(
                "cache_key does not match the exact projection identity."
            )
        _validate_snapshot_inventory(
            self.inventory,
            self.source,
            self.projection,
            self.authorization,
        )
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(self, "captured_at", captured)

    @property
    def identity(self) -> ProjectionCacheIdentity:
        return ProjectionCacheIdentity(
            schema_version=self.schema_version,
            source=self.source,
            projection=self.projection,
            authorization=self.authorization,
        )


@dataclass(frozen=True, slots=True)
class StoredProjectionSnapshot:
    snapshot: ProjectionSnapshot = field(repr=False)
    cache_key: str
    snapshot_digest: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, ProjectionSnapshot):
            raise ProjectionCacheValidationError(
                "snapshot must be a ProjectionSnapshot."
            )
        key = _sha256(self.cache_key, "cache_key")
        digest = _sha256(self.snapshot_digest, "snapshot_digest")
        if key != self.snapshot.cache_key:
            raise ProjectionCacheValidationError(
                "stored cache key must equal the snapshot cache key."
            )
        if type(self.content) is not bytes:
            raise ProjectionCacheValidationError("content must be immutable bytes.")
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ProjectionCacheValidationError(
                "snapshot_digest does not match exact stored bytes."
            )
        if projection_snapshot_from_json_bytes(self.content) != self.snapshot:
            raise ProjectionCacheValidationError(
                "stored content does not decode to the stored snapshot."
            )
        if projection_snapshot_to_json_bytes(self.snapshot) != self.content:
            raise ProjectionCacheValidationError(
                "stored content is not the canonical snapshot encoding."
            )
        expected_relative = projection_cache_relative_path(
            self.snapshot.source.publication.publication_id,
            key,
            digest,
        )
        if self.relative_path != expected_relative:
            raise ProjectionCacheValidationError(
                "relative_path is not the canonical cache location."
            )
        if self.path.name != f"{digest}.json":
            raise ProjectionCacheValidationError(
                "snapshot filename does not match snapshot_digest."
            )
        object.__setattr__(self, "cache_key", key)
        object.__setattr__(self, "snapshot_digest", digest)


@dataclass(frozen=True, slots=True)
class ProjectionCacheWriteResult:
    disposition: ProjectionCacheDisposition
    stored: StoredProjectionSnapshot

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ProjectionCacheValidationError("disposition is invalid.")
        if not isinstance(self.stored, StoredProjectionSnapshot):
            raise ProjectionCacheValidationError(
                "stored must be a StoredProjectionSnapshot."
            )


@dataclass(frozen=True, slots=True)
class ProjectionCacheAssessment:
    source_status: ProjectionSourceStatus
    reuse_status: ProjectionReuseStatus
    reason_codes: tuple[str, ...]
    observed_canonical_state: CanonicalPublicationState
    current_canonical_state: CanonicalPublicationState | None
    observed_head_publication_id: str
    current_head_publication_id: str | None
    observed_current_registration_revision: int | None
    current_registration_revision: int | None

    def __post_init__(self) -> None:
        if self.source_status not in {
            "current",
            "superseded",
            "withdrawn",
            "withdrawn_superseded",
            "unverifiable",
        }:
            raise ProjectionCacheValidationError("source_status is invalid.")
        if self.reuse_status not in {
            "reusable",
            "reprojection_required",
            "historical_only",
            "unverifiable",
        }:
            raise ProjectionCacheValidationError("reuse_status is invalid.")
        reasons = tuple(self.reason_codes)
        if reasons != _ordered_reasons(reasons):
            raise ProjectionCacheValidationError(
                "reason_codes are not in deterministic cache reason order."
            )
        if len(set(reasons)) != len(reasons):
            raise ProjectionCacheValidationError(
                "reason_codes must not contain duplicates."
            )
        object.__setattr__(self, "reason_codes", reasons)

    @property
    def reusable_for_current_use(self) -> bool:
        return (
            self.source_status == "current"
            and self.reuse_status == "reusable"
            and not self.reason_codes
        )


@dataclass(frozen=True, slots=True)
class AuthorizedProjectionSnapshot:
    stored: StoredProjectionSnapshot = field(repr=False)
    current_context: CanonicalPublicationContext
    cache_read_authorization: PublicationAuthorizationDecision
    current_projection_authorization: PublicationAuthorizationDecision
    assessment: ProjectionCacheAssessment

    def __post_init__(self) -> None:
        if not isinstance(self.stored, StoredProjectionSnapshot):
            raise ProjectionCacheValidationError(
                "stored must be a StoredProjectionSnapshot."
            )
        if not isinstance(self.current_context, CanonicalPublicationContext):
            raise ProjectionCacheValidationError(
                "current_context must be a CanonicalPublicationContext."
            )
        if not self.cache_read_authorization.allowed:
            raise ProjectionCacheValidationError(
                "cache_read_authorization must be allowed."
            )
        if not isinstance(self.assessment, ProjectionCacheAssessment):
            raise ProjectionCacheValidationError(
                "assessment must be a ProjectionCacheAssessment."
            )


def _adapter_key_for_source(source: ProjectionSourceObservation) -> AdapterKey:
    publication = source.publication
    registration = source.referenced_registration
    source_record = publication.source_record
    return AdapterKey(
        producer_module_id=publication.work.module_id,
        publication_kind=publication.publication_kind,
        manifest_contract_version=publication.manifest_contract_version,
        producer_contract_version=(
            registration.producer_contract_version if registration is not None else None
        ),
        source_record_kind=(
            source_record.record_kind if source_record is not None else None
        ),
        source_record_contract_version=(
            source_record.contract_version if source_record is not None else None
        ),
    )


def _validate_snapshot_inventory(
    inventory: EvidenceInventory,
    source: ProjectionSourceObservation,
    projection: ProjectionExecutionIdentity,
    authorization: ProjectionAuthorizationObservation,
) -> None:
    expected_projection = projection.evidence_projection_identity
    allowed_students = set(authorization.requested_student_ids)
    for item in inventory.items:
        provenance = item.provenance
        if provenance.publication != source.publication:
            raise ProjectionCacheValidationError(
                "inventory item uses a different Publication Record."
            )
        if provenance.registration != source.referenced_registration:
            raise ProjectionCacheValidationError(
                "inventory item uses a different registration revision."
            )
        if provenance.withdrawal != source.withdrawal:
            raise ProjectionCacheValidationError(
                "inventory item uses different withdrawal provenance."
            )
        if provenance.projection != expected_projection:
            raise ProjectionCacheValidationError(
                "inventory item uses a different projection identity."
            )
        if allowed_students and (
            item.subject is None
            or item.subject.student_id not in allowed_students
        ):
            raise ProjectionCacheValidationError(
                "inventory contains evidence outside the authorized student scope."
            )


def _source_to_dict(value: ProjectionSourceObservation) -> dict[str, object]:
    return {
        "publication": publication_record_to_dict(value.publication),
        "referenced_registration": (
            academic_work_registration_to_dict(value.referenced_registration)
            if value.referenced_registration is not None
            else None
        ),
        "current_registration": (
            academic_work_registration_to_dict(value.current_registration)
            if value.current_registration is not None
            else None
        ),
        "withdrawal": (
            publication_withdrawal_to_dict(value.withdrawal)
            if value.withdrawal is not None
            else None
        ),
        "series_publication_ids": list(value.series_publication_ids),
        "target_index": value.target_index,
        "head_publication_id": value.head_publication_id,
        "successor_publication_id": value.successor_publication_id,
        "canonical_state": value.canonical_state,
    }


def _source_from_dict(data: object) -> ProjectionSourceObservation:
    mapping = _mapping(data, _SOURCE_KEYS, "projection source")
    try:
        publication = publication_record_from_dict(mapping["publication"])
    except ValueError as error:
        raise ProjectionCacheValidationError("publication is invalid.") from error
    ids = mapping["series_publication_ids"]
    if not isinstance(ids, list):
        raise ProjectionCacheValidationError(
            "series_publication_ids must be a list."
        )
    target_index = mapping["target_index"]
    if isinstance(target_index, bool) or not isinstance(target_index, int):
        raise ProjectionCacheValidationError("target_index must be an integer.")
    successor = mapping["successor_publication_id"]
    if successor is not None and not isinstance(successor, str):
        raise ProjectionCacheValidationError(
            "successor_publication_id must be a string or null."
        )
    return ProjectionSourceObservation(
        publication=publication,
        referenced_registration=_optional_registration(
            mapping["referenced_registration"]
        ),
        current_registration=_optional_registration(mapping["current_registration"]),
        withdrawal=_optional_withdrawal(mapping["withdrawal"]),
        series_publication_ids=tuple(_string(item, "publication_id") for item in ids),
        target_index=target_index,
        head_publication_id=_string(
            mapping["head_publication_id"], "head_publication_id"
        ),
        successor_publication_id=successor,
        canonical_state=cast(
            CanonicalPublicationState,
            _string(mapping["canonical_state"], "canonical_state"),
        ),
    )


def _adapter_key_to_dict(value: AdapterKey) -> dict[str, object]:
    return {
        "producer_module_id": value.producer_module_id,
        "publication_kind": value.publication_kind,
        "manifest_contract_version": value.manifest_contract_version,
        "producer_contract_version": value.producer_contract_version,
        "source_record_kind": value.source_record_kind,
        "source_record_contract_version": value.source_record_contract_version,
    }


def _adapter_key_from_dict(data: object) -> AdapterKey:
    mapping = _mapping(data, _ADAPTER_KEY_KEYS, "adapter key")
    return AdapterKey(
        producer_module_id=_string(
            mapping["producer_module_id"], "producer_module_id"
        ),
        publication_kind=cast(
            PublicationKind,
            _string(mapping["publication_kind"], "publication_kind"),
        ),
        manifest_contract_version=_string(
            mapping["manifest_contract_version"], "manifest_contract_version"
        ),
        producer_contract_version=cast(
            str | None, mapping["producer_contract_version"]
        ),
        source_record_kind=cast(str | None, mapping["source_record_kind"]),
        source_record_contract_version=cast(
            str | None, mapping["source_record_contract_version"]
        ),
    )


def _execution_to_dict(value: ProjectionExecutionIdentity) -> dict[str, object]:
    return {
        "adapter_key": _adapter_key_to_dict(value.adapter_key),
        "adapter_id": value.adapter_id,
        "adapter_interface_version": value.adapter_interface_version,
        "projection_contract_version": value.projection_contract_version,
        "producer_reader_distribution": value.producer_reader_distribution,
        "producer_reader_version": value.producer_reader_version,
    }


def _execution_from_dict(data: object) -> ProjectionExecutionIdentity:
    mapping = _mapping(data, _EXECUTION_KEYS, "projection execution")
    return ProjectionExecutionIdentity(
        adapter_key=_adapter_key_from_dict(mapping["adapter_key"]),
        adapter_id=_string(mapping["adapter_id"], "adapter_id"),
        adapter_interface_version=_string(
            mapping["adapter_interface_version"], "adapter_interface_version"
        ),
        projection_contract_version=_string(
            mapping["projection_contract_version"],
            "projection_contract_version",
        ),
        producer_reader_distribution=_string(
            mapping["producer_reader_distribution"],
            "producer_reader_distribution",
        ),
        producer_reader_version=_string(
            mapping["producer_reader_version"], "producer_reader_version"
        ),
    )


def _authorization_to_dict(
    value: ProjectionAuthorizationObservation,
) -> dict[str, object]:
    return {
        "operation": value.operation,
        "purpose_id": value.purpose_id,
        "requested_student_ids": list(value.requested_student_ids),
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
    }


def _authorization_from_dict(data: object) -> ProjectionAuthorizationObservation:
    mapping = _mapping(data, _AUTHORIZATION_KEYS, "projection authorization")
    students = mapping["requested_student_ids"]
    if not isinstance(students, list):
        raise ProjectionCacheValidationError(
            "requested_student_ids must be a list."
        )
    return ProjectionAuthorizationObservation(
        operation=cast(
            Literal["project_evidence"],
            _string(mapping["operation"], "operation"),
        ),
        purpose_id=_string(mapping["purpose_id"], "purpose_id"),
        requested_student_ids=tuple(
            _string(item, "student_id") for item in students
        ),
        policy_id=_string(mapping["policy_id"], "policy_id"),
        policy_version=_string(mapping["policy_version"], "policy_version"),
    )


def _identity_to_dict(value: ProjectionCacheIdentity) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "source": _source_to_dict(value.source),
        "projection": _execution_to_dict(value.projection),
        "authorization": _authorization_to_dict(value.authorization),
    }


def projection_cache_key(identity: ProjectionCacheIdentity) -> str:
    if not isinstance(identity, ProjectionCacheIdentity):
        raise ProjectionCacheValidationError(
            "identity must be a ProjectionCacheIdentity."
        )
    return hashlib.sha256(
        _canonical_json_bytes(_identity_to_dict(identity))
    ).hexdigest()


def projection_snapshot_to_dict(snapshot: ProjectionSnapshot) -> dict[str, object]:
    if not isinstance(snapshot, ProjectionSnapshot):
        raise ProjectionCacheValidationError(
            "snapshot must be a ProjectionSnapshot."
        )
    return {
        "schema_version": snapshot.schema_version,
        "record_type": snapshot.record_type,
        "cache_key": snapshot.cache_key,
        "captured_at": snapshot.captured_at.astimezone(UTC).isoformat(),
        "source": _source_to_dict(snapshot.source),
        "projection": _execution_to_dict(snapshot.projection),
        "authorization": _authorization_to_dict(snapshot.authorization),
        "inventory": evidence_inventory_to_dict(snapshot.inventory),
    }


def projection_snapshot_from_dict(data: object) -> ProjectionSnapshot:
    mapping = _mapping(data, _SNAPSHOT_KEYS, "projection snapshot")
    try:
        inventory = evidence_inventory_from_dict(mapping["inventory"])
    except EvidenceSerializationError as error:
        raise ProjectionCacheValidationError("inventory is invalid.") from error
    return ProjectionSnapshot(
        schema_version=_string(mapping["schema_version"], "schema_version"),
        record_type=_string(mapping["record_type"], "record_type"),
        cache_key=_string(mapping["cache_key"], "cache_key"),
        captured_at=_datetime_from_text(mapping["captured_at"], "captured_at"),
        source=_source_from_dict(mapping["source"]),
        projection=_execution_from_dict(mapping["projection"]),
        authorization=_authorization_from_dict(mapping["authorization"]),
        inventory=inventory,
    )


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
        raise ProjectionCacheValidationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def projection_snapshot_to_json_bytes(snapshot: ProjectionSnapshot) -> bytes:
    return _canonical_json_bytes(projection_snapshot_to_dict(snapshot))


def _canonical_inventory_bytes(inventory: EvidenceInventory) -> bytes:
    """Return the exact canonical persistence bytes used for replay comparison."""
    if not isinstance(inventory, EvidenceInventory):
        raise ProjectionCacheValidationError(
            "inventory must be an EvidenceInventory."
        )
    return _canonical_json_bytes(evidence_inventory_to_dict(inventory))


def _reject_constant(value: str) -> object:
    raise ProjectionCacheValidationError(f"nonfinite JSON number is invalid: {value}.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectionCacheValidationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def projection_snapshot_from_json_bytes(data: bytes) -> ProjectionSnapshot:
    if type(data) is not bytes:
        raise ProjectionCacheValidationError("snapshot data must be immutable bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectionCacheValidationError(
            "projection snapshot is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ProjectionCacheValidationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ProjectionCacheValidationError(
            "projection snapshot is not valid JSON."
        ) from error
    snapshot = projection_snapshot_from_dict(decoded)
    if projection_snapshot_to_json_bytes(snapshot) != data:
        raise ProjectionCacheIntegrityError(
            "projection snapshot bytes are not the canonical encoding.",
            publication_id=snapshot.source.publication.publication_id,
            cache_key=snapshot.cache_key,
        )
    return snapshot


def projection_cache_directory(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
) -> Path:
    publication = _publication_id(publication_id)
    key = _sha256(cache_key, "cache_key")
    return (
        Path(workspace_root)
        / "cache"
        / "meridian"
        / "projections"
        / publication
        / key
    )


def projection_cache_relative_path(
    publication_id: str,
    cache_key: str,
    snapshot_digest: str,
) -> str:
    publication = _publication_id(publication_id)
    key = _sha256(cache_key, "cache_key")
    digest = _sha256(snapshot_digest, "snapshot_digest")
    relative = f"cache/meridian/projections/{publication}/{key}/{digest}.json"
    _validate_relative_path(relative)
    return relative


def projection_cache_path(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
    snapshot_digest: str,
) -> Path:
    relative = projection_cache_relative_path(
        publication_id, cache_key, snapshot_digest
    )
    root = Path(workspace_root)
    result = root.joinpath(*relative.split("/"))
    _require_lexical_containment(root, result)
    return result


def _publication_id(value: object) -> str:
    text = _identifier(value, "publication_id")
    if re.fullmatch(r"pub_[0-9a-f]{32}", text) is None:
        raise ProjectionCacheValidationError(
            "publication_id must use the Core Publication Record identity format."
        )
    return text


def _validate_relative_path(value: str) -> None:
    if "\\" in value:
        raise ProjectionCacheValidationError(
            "cache paths must use forward slashes only."
        )
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if (
        value.startswith("/")
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
    ):
        raise ProjectionCacheValidationError("cache path must be workspace-relative.")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ProjectionCacheValidationError(
            "cache path must not contain empty, dot, or traversal components."
        )


def _require_lexical_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ProjectionCacheValidationError(
            "cache path escapes the supplied workspace root."
        ) from error


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    if current.exists() and current.is_symlink():
        raise ProjectionCacheIntegrityError("workspace root must not be a symlink.")
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ProjectionCacheIntegrityError(
                    "projection cache directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ProjectionCacheWriteError(
                    "projection cache directory could not be created."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_lexical_containment(root, target)
    current = root
    if not current.exists() or current.is_symlink() or not current.is_dir():
        raise ProjectionCacheIntegrityError(
            "workspace root is missing or unsafe."
        )
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise ProjectionCacheNotFoundError(
                "The exact projection cache directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ProjectionCacheIntegrityError(
                "projection cache directory chain is unsafe."
            )


def _inspect_cache_directory(directory: Path) -> tuple[Path | None, Path]:
    lock = directory / ".write.lock"
    snapshot: Path | None = None
    try:
        entries = tuple(directory.iterdir())
    except OSError as error:
        raise ProjectionCacheReadError(
            "projection cache directory could not be inspected."
        ) from error
    for entry in entries:
        if entry.name == ".write.lock":
            continue
        if entry.is_symlink():
            raise ProjectionCacheIntegrityError(
                "projection cache contains a symlinked entry."
            )
        if entry.is_dir():
            raise ProjectionCacheIntegrityError(
                "projection cache contains an unexpected nested directory."
            )
        if not entry.is_file():
            raise ProjectionCacheIntegrityError(
                "projection cache contains a nonregular entry."
            )
        match = re.fullmatch(r"([0-9a-f]{64})\.json", entry.name)
        if match is None:
            raise ProjectionCacheIntegrityError(
                "projection cache contains an unexpected file."
            )
        if snapshot is not None:
            raise ProjectionCacheIntegrityError(
                "projection cache contains multiple completed snapshots."
            )
        snapshot = entry
    return snapshot, lock


def _acquire_lock(lock: Path, publication_id: str, cache_key: str) -> None:
    try:
        with lock.open("xb") as stream:
            stream.write(b"meridian projection cache write lock\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProjectionCacheLockError(
            "A projection cache writer already owns this exact cache key.",
            publication_id=publication_id,
            cache_key=cache_key,
        ) from error
    except OSError as error:
        raise ProjectionCacheWriteError(
            "The projection cache write lock could not be created.",
            publication_id=publication_id,
            cache_key=cache_key,
        ) from error


def _remove_lock(lock: Path) -> str | None:
    try:
        lock.unlink()
    except OSError as error:
        return f"{type(error).__name__}: write-lock cleanup failed"
    return None


def _read_bounded(
    path: Path,
    *,
    publication_id: str,
    cache_key: str,
    maximum_snapshot_bytes: int,
) -> bytes:
    limit = _positive_limit(maximum_snapshot_bytes, "maximum_snapshot_bytes")
    if path.is_symlink():
        raise ProjectionCacheIntegrityError(
            "projection snapshot file must not be a symlink.",
            publication_id=publication_id,
            cache_key=cache_key,
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise ProjectionCacheIntegrityError(
                    "projection snapshot must be a regular file.",
                    publication_id=publication_id,
                    cache_key=cache_key,
                )
            content = source.read(limit + 1)
    except ProjectionCacheError:
        raise
    except FileNotFoundError as error:
        raise ProjectionCacheNotFoundError(
            "The exact projection snapshot no longer exists.",
            publication_id=publication_id,
            cache_key=cache_key,
        ) from error
    except OSError as error:
        raise ProjectionCacheReadError(
            "The projection snapshot could not be read.",
            publication_id=publication_id,
            cache_key=cache_key,
        ) from error
    if len(content) > limit:
        raise ProjectionCacheTooLargeError(publication_id, cache_key, limit)
    return content


def _stored_from_path(
    workspace_root: str | Path,
    path: Path,
    *,
    publication_id: str,
    cache_key: str,
    maximum_snapshot_bytes: int,
) -> StoredProjectionSnapshot:
    content = _read_bounded(
        path,
        publication_id=publication_id,
        cache_key=cache_key,
        maximum_snapshot_bytes=maximum_snapshot_bytes,
    )
    digest = hashlib.sha256(content).hexdigest()
    if path.name != f"{digest}.json":
        raise ProjectionCacheIntegrityError(
            "projection snapshot filename does not match exact bytes.",
            publication_id=publication_id,
            cache_key=cache_key,
            snapshot_digest=digest,
        )
    try:
        snapshot = projection_snapshot_from_json_bytes(content)
    except ProjectionCacheError:
        raise
    except ValueError as error:
        raise ProjectionCacheIntegrityError(
            "projection snapshot content is invalid.",
            publication_id=publication_id,
            cache_key=cache_key,
            snapshot_digest=digest,
        ) from error
    if snapshot.source.publication.publication_id != publication_id:
        raise ProjectionCacheIntegrityError(
            "projection snapshot is stored under the wrong publication.",
            publication_id=publication_id,
            cache_key=cache_key,
            snapshot_digest=digest,
        )
    if snapshot.cache_key != cache_key:
        raise ProjectionCacheIntegrityError(
            "projection snapshot is stored under the wrong cache key.",
            publication_id=publication_id,
            cache_key=cache_key,
            snapshot_digest=digest,
        )
    root = Path(workspace_root)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise ProjectionCacheIntegrityError(
            "projection snapshot path escapes the workspace root."
        ) from error
    return StoredProjectionSnapshot(
        snapshot=snapshot,
        cache_key=cache_key,
        snapshot_digest=digest,
        path=path,
        relative_path=relative,
        content=content,
    )


def _scoped_inventory(
    inventory: EvidenceInventory,
    student_ids: tuple[str, ...],
) -> EvidenceInventory:
    if not student_ids:
        return inventory
    allowed = set(student_ids)
    return EvidenceInventory(
        tuple(
            item
            for item in inventory.items
            if item.subject is not None
            and item.subject.student_id in allowed
        )
    )


def _authorize(
    authorizer: PublicationAuthorizer,
    request: PublicationAuthorizationRequest,
    *,
    cache_read: bool,
) -> PublicationAuthorizationDecision:
    if not isinstance(authorizer, PublicationAuthorizer):
        raise ProjectionCacheAuthorizationError(
            "authorizer must satisfy PublicationAuthorizer."
        )
    try:
        decision = authorizer.authorize(request)
    except ProjectionCacheAuthorizationError:
        raise
    except PublicationAuthorizationError as error:
        raise ProjectionCacheAuthorizationError(
            "The deployment authorizer failed to produce a valid decision.",
            publication_id=request.publication.publication_id,
        ) from error
    except Exception as error:
        raise ProjectionCacheAuthorizationError(
            "The deployment authorizer failed to produce a decision.",
            publication_id=request.publication.publication_id,
        ) from error
    if not isinstance(decision, PublicationAuthorizationDecision):
        raise ProjectionCacheAuthorizationError(
            "The deployment authorizer returned an invalid decision.",
            publication_id=request.publication.publication_id,
        )
    if cache_read and not decision.allowed:
        raise ProjectionCacheAuthorizationDeniedError(
            publication_id=request.publication.publication_id,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            reason_codes=decision.reason_codes,
        )
    return decision


def _authorization_request(
    context: CanonicalPublicationContext,
    *,
    operation: Literal["project_evidence", "read_projection_cache"],
    purpose_id: str,
    student_ids: tuple[str, ...],
) -> PublicationAuthorizationRequest:
    return PublicationAuthorizationRequest(
        publication=context.publication,
        referenced_registration=context.referenced_registration,
        withdrawal=context.withdrawal,
        canonical_state=context.canonical_state,
        operation=operation,
        purpose_id=purpose_id,
        requested_student_ids=student_ids,
    )


def cache_projected_inventory(
    workspace_root: str | Path,
    prepared: PreparedPublicationInvocation,
    inventory: EvidenceInventory,
    *,
    authorizer: PublicationAuthorizer,
    clock: Clock = utc_now,
    maximum_snapshot_bytes: int = DEFAULT_MAXIMUM_PROJECTION_SNAPSHOT_BYTES,
) -> ProjectionCacheWriteResult:
    if not isinstance(prepared, PreparedPublicationInvocation):
        raise ProjectionCacheValidationError(
            "prepared must be a PreparedPublicationInvocation."
        )
    if not isinstance(inventory, EvidenceInventory):
        raise ProjectionCacheValidationError(
            "inventory must be an EvidenceInventory."
        )
    limit = _positive_limit(maximum_snapshot_bytes, "maximum_snapshot_bytes")
    validate_projected_inventory(
        inventory,
        prepared.projection_request,
        prepared.adapter_match.descriptor,
        prepared.producer_reader_version,
    )
    scoped = _scoped_inventory(
        inventory, prepared.authorization_request.requested_student_ids
    )
    try:
        current = load_canonical_publication_context(
            workspace_root,
            prepared.canonical_context.publication.publication_id,
        )
    except PublicationIngestionError as error:
        raise ProjectionCacheSourceChangedError(
            "Canonical publication state could not be reverified after projection.",
            publication_id=prepared.canonical_context.publication.publication_id,
        ) from error
    if current != prepared.canonical_context:
        raise ProjectionCacheSourceChangedError(
            "Canonical publication state changed after evidence projection.",
            publication_id=current.publication.publication_id,
        )
    repeated_request = _authorization_request(
        current,
        operation="project_evidence",
        purpose_id=prepared.authorization_request.purpose_id,
        student_ids=prepared.authorization_request.requested_student_ids,
    )
    repeated_decision = _authorize(
        authorizer, repeated_request, cache_read=False
    )
    if not repeated_decision.allowed:
        raise ProjectionCacheAuthorizationDeniedError(
            publication_id=current.publication.publication_id,
            policy_id=repeated_decision.policy_id,
            policy_version=repeated_decision.policy_version,
            reason_codes=repeated_decision.reason_codes,
        )
    if (
        repeated_decision.policy_id != prepared.authorization.policy_id
        or repeated_decision.policy_version != prepared.authorization.policy_version
    ):
        raise ProjectionCacheSourceChangedError(
            "Projection authorization policy changed after evidence projection.",
            publication_id=current.publication.publication_id,
        )
    source = ProjectionSourceObservation.from_context(current)
    execution = ProjectionExecutionIdentity.from_match(
        prepared.adapter_match, prepared.producer_reader_version
    )
    authorization = ProjectionAuthorizationObservation.from_prepared(prepared)
    identity = ProjectionCacheIdentity(
        schema_version=PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        source=source,
        projection=execution,
        authorization=authorization,
    )
    key = projection_cache_key(identity)
    publication_id = source.publication.publication_id
    root = Path(workspace_root)
    directory = projection_cache_directory(root, publication_id, key)
    _ensure_directory_chain(root, directory)
    existing, lock = _inspect_cache_directory(directory)
    if lock.exists():
        raise ProjectionCacheLockError(
            "A projection cache writer already owns this exact cache key.",
            publication_id=publication_id,
            cache_key=key,
        )
    _acquire_lock(lock, publication_id, key)
    durable = False
    digest: str | None = None
    relative: str | None = None
    created_path: Path | None = None
    result: ProjectionCacheWriteResult | None = None
    active_error: BaseException | None = None
    try:
        existing, _ = _inspect_cache_directory(directory)
        if existing is not None:
            stored = _stored_from_path(
                root,
                existing,
                publication_id=publication_id,
                cache_key=key,
                maximum_snapshot_bytes=limit,
            )
            if stored.snapshot.identity != identity:
                raise ProjectionCacheIntegrityError(
                    "existing snapshot identity disagrees with its cache directory.",
                    publication_id=publication_id,
                    cache_key=key,
                )
            if _canonical_inventory_bytes(stored.snapshot.inventory) != (
                _canonical_inventory_bytes(scoped)
            ):
                raise ProjectionCacheNondeterminismError(
                    "Identical projection inputs produced different evidence output.",
                    publication_id=publication_id,
                    cache_key=key,
                    snapshot_digest=stored.snapshot_digest,
                    relative_path=stored.relative_path,
                )
            result = ProjectionCacheWriteResult("existing", stored)
        else:
            captured = _aware_datetime(clock(), "captured_at").astimezone(UTC)
            snapshot = ProjectionSnapshot(
                schema_version=PROJECTION_SNAPSHOT_SCHEMA_VERSION,
                record_type=PROJECTION_SNAPSHOT_RECORD_TYPE,
                cache_key=key,
                captured_at=captured,
                source=source,
                projection=execution,
                authorization=authorization,
                inventory=scoped,
            )
            content = projection_snapshot_to_json_bytes(snapshot)
            if len(content) > limit:
                raise ProjectionCacheTooLargeError(publication_id, key, limit)
            digest = hashlib.sha256(content).hexdigest()
            relative = projection_cache_relative_path(publication_id, key, digest)
            target = projection_cache_path(root, publication_id, key, digest)
            created_path = target
            try:
                with target.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                durable = True
            except FileExistsError as error:
                raise ProjectionCacheConflictError(
                    "The exact projection snapshot target already exists.",
                    publication_id=publication_id,
                    cache_key=key,
                    snapshot_digest=digest,
                    relative_path=relative,
                ) from error
            except OSError as error:
                raise ProjectionCacheWriteError(
                    "The projection snapshot could not be written durably.",
                    publication_id=publication_id,
                    cache_key=key,
                    snapshot_digest=digest,
                    relative_path=relative,
                ) from error
            stored = _stored_from_path(
                root,
                target,
                publication_id=publication_id,
                cache_key=key,
                maximum_snapshot_bytes=limit,
            )
            result = ProjectionCacheWriteResult("created", stored)
    except BaseException as error:
        active_error = error
        if durable:
            raise ProjectionCachePartialSuccessError(
                "Projection snapshot is durable but post-write validation failed.",
                ProjectionCacheDurableState(
                    operation="cache_projected_inventory",
                    publication_id=publication_id,
                    cache_key=key,
                    snapshot_digest=digest,
                    relative_path=relative,
                    durable_file=True,
                ),
            ) from error
        if created_path is not None and created_path.exists():
            try:
                created_path.unlink()
            except OSError as cleanup_error:
                raise ProjectionCachePartialSuccessError(
                    (
                        "Projection cache creation failed and incomplete-file "
                        "cleanup also failed."
                    ),
                    ProjectionCacheDurableState(
                        operation="cache_projected_inventory",
                        publication_id=publication_id,
                        cache_key=key,
                        snapshot_digest=digest,
                        relative_path=relative,
                        durable_file=False,
                        cleanup_failure=(
                            (
                                f"{type(cleanup_error).__name__}: "
                                "incomplete-file cleanup failed"
                            )
                        ),
                    ),
                ) from error
        raise
    finally:
        cleanup_failure = _remove_lock(lock)
        if cleanup_failure is not None:
            state = ProjectionCacheDurableState(
                operation="cache_projected_inventory",
                publication_id=publication_id,
                cache_key=key,
                snapshot_digest=(
                    result.stored.snapshot_digest if result is not None else digest
                ),
                relative_path=(
                    result.stored.relative_path if result is not None else relative
                ),
                durable_file=durable or result is not None,
                cleanup_failure=cleanup_failure,
            )
            message = (
                "Projection cache operation completed but write-lock cleanup failed."
                if active_error is None
                else (
                    "Projection cache operation failed and write-lock cleanup "
                    "also failed."
                )
            )
            if active_error is None:
                raise ProjectionCachePartialSuccessError(message, state)
            raise ProjectionCachePartialSuccessError(message, state) from active_error
    if result is None:  # pragma: no cover - defensive totality
        raise ProjectionCacheWriteError(
            "Projection cache operation produced no result.",
            publication_id=publication_id,
            cache_key=key,
        )
    return result


def _find_snapshot_path(directory: Path, publication_id: str, key: str) -> Path:
    if not directory.exists():
        raise ProjectionCacheNotFoundError(
            "No projection cache exists for the exact key.",
            publication_id=publication_id,
            cache_key=key,
        )
    if directory.is_symlink() or not directory.is_dir():
        raise ProjectionCacheIntegrityError(
            "Projection cache-key path is unsafe.",
            publication_id=publication_id,
            cache_key=key,
        )
    snapshot, lock = _inspect_cache_directory(directory)
    if lock.exists():
        raise ProjectionCacheLockError(
            "Projection cache entry is currently being written.",
            publication_id=publication_id,
            cache_key=key,
        )
    if snapshot is None:
        raise ProjectionCacheNotFoundError(
            "No completed projection snapshot exists for the exact key.",
            publication_id=publication_id,
            cache_key=key,
        )
    return snapshot


def load_authorized_projection_snapshot(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
    *,
    authorizer: PublicationAuthorizer,
    authorization_purpose_id: str,
    requested_student_ids: Iterable[str] = (),
    producer_registry: PublicationProducerRegistry,
    adapter_registry: AdapterRegistry,
    distribution_version_resolver: DistributionVersionResolver = (
        installed_distribution_version
    ),
    maximum_snapshot_bytes: int = DEFAULT_MAXIMUM_PROJECTION_SNAPSHOT_BYTES,
) -> AuthorizedProjectionSnapshot:
    publication = _publication_id(publication_id)
    key = _sha256(cache_key, "cache_key")
    purpose = _identifier(authorization_purpose_id, "authorization_purpose_id")
    students = _student_ids(requested_student_ids)
    limit = _positive_limit(maximum_snapshot_bytes, "maximum_snapshot_bytes")
    try:
        context = load_canonical_publication_context(workspace_root, publication)
    except PublicationIngestionError as error:
        raise ProjectionCacheSourceChangedError(
            "Current canonical source state cannot be loaded for cache access.",
            publication_id=publication,
            cache_key=key,
        ) from error
    read_request = _authorization_request(
        context,
        operation="read_projection_cache",
        purpose_id=purpose,
        student_ids=students,
    )
    read_decision = _authorize(authorizer, read_request, cache_read=True)
    directory = projection_cache_directory(workspace_root, publication, key)
    _validate_existing_directory_chain(Path(workspace_root), directory)
    path = _find_snapshot_path(directory, publication, key)
    stored = _stored_from_path(
        workspace_root,
        path,
        publication_id=publication,
        cache_key=key,
        maximum_snapshot_bytes=limit,
    )
    if stored.snapshot.authorization.purpose_id != purpose:
        raise ProjectionCacheAuthorizationError(
            "Requested purpose does not match the projection snapshot purpose.",
            publication_id=publication,
            cache_key=key,
        )
    if stored.snapshot.authorization.requested_student_ids != students:
        raise ProjectionCacheAuthorizationError(
            "Requested student scope does not match the projection snapshot scope.",
            publication_id=publication,
            cache_key=key,
        )
    project_request = _authorization_request(
        context,
        operation="project_evidence",
        purpose_id=purpose,
        student_ids=students,
    )
    project_decision = _authorize(authorizer, project_request, cache_read=False)
    assessment = assess_projection_snapshot(
        workspace_root,
        stored.snapshot,
        current_context=context,
        current_projection_authorization=project_decision,
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        distribution_version_resolver=distribution_version_resolver,
    )
    return AuthorizedProjectionSnapshot(
        stored=stored,
        current_context=context,
        cache_read_authorization=read_decision,
        current_projection_authorization=project_decision,
        assessment=assessment,
    )


def assess_projection_snapshot(
    workspace_root: str | Path,
    snapshot: ProjectionSnapshot,
    *,
    current_context: CanonicalPublicationContext | None,
    current_projection_authorization: PublicationAuthorizationDecision,
    producer_registry: PublicationProducerRegistry,
    adapter_registry: AdapterRegistry,
    distribution_version_resolver: DistributionVersionResolver = (
        installed_distribution_version
    ),
) -> ProjectionCacheAssessment:
    if not isinstance(snapshot, ProjectionSnapshot):
        raise ProjectionCacheValidationError(
            "snapshot must be a ProjectionSnapshot."
        )
    observed = snapshot.source
    reasons: set[str] = set()
    if current_context is None:
        try:
            current_context = load_canonical_publication_context(
                workspace_root, observed.publication.publication_id
            )
        except PublicationIngestionError:
            reasons.add("cache.canonical_unverifiable")
            return _assessment(
                observed,
                None,
                "unverifiable",
                "unverifiable",
                reasons,
            )
    if current_context.publication != observed.publication:
        reasons.add("cache.canonical_unverifiable")
    current_source = ProjectionSourceObservation.from_context(current_context)
    source_status: ProjectionSourceStatus
    if reasons:
        source_status = "unverifiable"
    elif current_source.canonical_state == "current_selectable":
        source_status = "current"
    elif current_source.canonical_state == "historical":
        source_status = "superseded"
        reasons.add("cache.source_superseded")
    elif current_source.canonical_state == "withdrawn_head":
        source_status = "withdrawn"
        reasons.add("cache.source_withdrawn")
    else:
        source_status = "withdrawn_superseded"
        reasons.update({"cache.source_superseded", "cache.source_withdrawn"})
    if current_source.series_publication_ids != observed.series_publication_ids:
        reasons.add("cache.series_changed")
    if current_source.current_registration != observed.current_registration:
        reasons.add("cache.current_registration_changed")
    try:
        verify_publication_manifest(workspace_root, observed.publication)
    except (
        PublicationManifestNotFoundError,
        PublicationManifestIntegrityError,
        PublicationManifestError,
    ):
        reasons.add("cache.manifest_unverifiable")
        source_status = "unverifiable"
    descriptor: AdapterDescriptor | None = None
    try:
        profile = producer_registry.get(observed.publication.work.module_id)
    except (PublicationProducerRegistryError, PublicationCompatibilityError):
        profile = None
        reasons.add("cache.profile_evaluation_failed")
    if profile is None:
        if "cache.profile_evaluation_failed" not in reasons:
            reasons.add("cache.profile_missing")
    else:
        try:
            compatibility = evaluate_publication_compatibility(
                current_context.publication,
                profile,
                current_context.referenced_registration,
            )
        except (PublicationProducerProfileError, PublicationCompatibilityError):
            reasons.add("cache.profile_evaluation_failed")
        else:
            if not compatibility.compatible:
                reasons.add("cache.profile_incompatible")
    try:
        match = adapter_registry.select(
            current_context.publication,
            current_context.referenced_registration,
        )
        descriptor = match.descriptor
    except AdapterNotFoundError:
        reasons.add("cache.adapter_missing")
    except AdapterCapabilityUnsupportedError:
        reasons.add("cache.adapter_capability_changed")
    if descriptor is not None and match is not None:
        expected = snapshot.projection
        current_execution = ProjectionExecutionIdentity.from_match(
            match, expected.producer_reader_version
        )
        if (
            current_execution.adapter_key != expected.adapter_key
            or current_execution.adapter_id != expected.adapter_id
            or current_execution.adapter_interface_version
            != expected.adapter_interface_version
            or current_execution.projection_contract_version
            != expected.projection_contract_version
            or current_execution.producer_reader_distribution
            != expected.producer_reader_distribution
        ):
            reasons.add("cache.adapter_changed")
        try:
            reader_version = resolve_producer_reader_version(
                descriptor, distribution_version_resolver
            )
        except ProducerReaderUnavailableError:
            reasons.add("cache.reader_unavailable")
        except ProducerReaderVersionUnsupportedError:
            reasons.add("cache.reader_version_changed")
        else:
            if reader_version != expected.producer_reader_version:
                reasons.add("cache.reader_version_changed")
    if not isinstance(
        current_projection_authorization, PublicationAuthorizationDecision
    ):
        raise ProjectionCacheAuthorizationError(
            "current_projection_authorization is invalid.",
            publication_id=observed.publication.publication_id,
            cache_key=snapshot.cache_key,
        )
    if not current_projection_authorization.allowed:
        reasons.add("cache.projection_authorization_denied")
    elif (
        current_projection_authorization.policy_id
        != snapshot.authorization.policy_id
        or current_projection_authorization.policy_version
        != snapshot.authorization.policy_version
    ):
        reasons.add("cache.projection_authorization_changed")
    if source_status == "unverifiable":
        reuse_status: ProjectionReuseStatus = "unverifiable"
    elif source_status != "current":
        reuse_status = "historical_only"
    elif reasons:
        reuse_status = "reprojection_required"
    else:
        reuse_status = "reusable"
    return _assessment(observed, current_source, source_status, reuse_status, reasons)


def _assessment(
    observed: ProjectionSourceObservation,
    current: ProjectionSourceObservation | None,
    source_status: ProjectionSourceStatus,
    reuse_status: ProjectionReuseStatus,
    reasons: Iterable[str],
) -> ProjectionCacheAssessment:
    return ProjectionCacheAssessment(
        source_status=source_status,
        reuse_status=reuse_status,
        reason_codes=_ordered_reasons(reasons),
        observed_canonical_state=observed.canonical_state,
        current_canonical_state=(current.canonical_state if current else None),
        observed_head_publication_id=observed.head_publication_id,
        current_head_publication_id=(current.head_publication_id if current else None),
        observed_current_registration_revision=(
            observed.current_registration_revision
        ),
        current_registration_revision=(
            current.current_registration_revision if current else None
        ),
    )


def _ordered_reasons(values: Iterable[str]) -> tuple[str, ...]:
    unique = set(values)
    unknown = unique - set(_REASON_ORDER)
    if unknown:
        raise ProjectionCacheValidationError(
            f"unknown projection cache reason codes: {sorted(unknown)!r}."
        )
    return tuple(reason for reason in _REASON_ORDER if reason in unique)
