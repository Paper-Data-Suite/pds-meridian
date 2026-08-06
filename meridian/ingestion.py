"""Bounded Core catalog discovery and canonical publication verification."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Protocol, TypeAlias, runtime_checkable

from pds_core.academic_catalog import (
    AcademicCatalogCompatibilityError,
    AcademicCatalogError,
    AcademicCatalogIntegrityError,
    AcademicCatalogNotFoundError,
    AcademicCatalogReadError,
    CatalogPublication,
    PublicationCatalogQuery,
    query_publication_catalog,
)
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationIntegrityError,
    AcademicWorkRegistrationNotFoundError,
    AcademicWorkRegistrationReadError,
    AcademicWorkRegistrationStorageError,
    load_academic_work_registration_revision,
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.publication_compatibility import (
    PublicationCompatibilityError,
    PublicationCompatibilityResult,
    PublicationProducerProfile,
    PublicationProducerProfileError,
    PublicationProducerRegistry,
    PublicationProducerRegistryError,
    evaluate_publication_compatibility,
)
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.publication_storage import (
    PublicationIntegrityError,
    PublicationManifestError,
    PublicationManifestIntegrityError,
    PublicationManifestNotFoundError,
    PublicationReadError,
    PublicationStorageError,
    list_publication_record_set,
    verify_publication_manifest,
)
from pds_core.registry_services import (
    RegistryServiceError,
    RegistryServiceIntegrityError,
    RegistryServiceNotFoundError,
    RegistryServiceWriteError,
    get_canonical_publication_record,
    get_canonical_publication_withdrawal,
)

from meridian.adapters import (
    AdapterMatch,
    AdapterProjectionRequest,
    AdapterRegistry,
    DistributionVersionResolver,
    installed_distribution_version,
    resolve_producer_reader_version,
)

__all__ = [
    "AuthorizationOperation",
    "CandidateDriftError",
    "CanonicalPublicationError",
    "CanonicalPublicationReadError",
    "CandidateDriftField",
    "CanonicalPublicationContext",
    "CanonicalPublicationState",
    "CanonicalStateChangedError",
    "CurrentRegistrationError",
    "CatalogDiscoveryError",
    "CatalogIncompatibleError",
    "CatalogInvalidError",
    "CatalogMissingError",
    "CatalogReadFailedError",
    "DEFAULT_MAXIMUM_MANIFEST_BYTES",
    "IngestionValidationError",
    "ManifestInvalidError",
    "ManifestPreparationError",
    "ManifestMissingError",
    "ManifestReadFailedError",
    "ManifestTooLargeError",
    "PreparedPublicationInvocation",
    "ProducerProfileError",
    "ProducerProfileEvaluationError",
    "ProducerProfileIncompatibleError",
    "ProducerProfileMissingError",
    "ProducerProfileRegistryError",
    "PublicationAuthorizationDecision",
    "PublicationAuthorizationDeniedError",
    "PublicationAuthorizationError",
    "PublicationAuthorizationRequest",
    "PublicationAuthorizer",
    "PublicationCandidate",
    "PublicationCandidateMissingError",
    "PublicationDiscoveryRequest",
    "PublicationDiscoveryResult",
    "PublicationIngestionError",
    "PublicationRegistrationError",
    "PublicationRegistrationMismatchError",
    "PublicationRegistrationMissingError",
    "PublicationSeriesError",
    "PublicationSeriesMember",
    "PublicationSeriesObservation",
    "PublicationVerificationError",
    "WithdrawalInvalidError",
    "WithdrawalReadError",
    "compare_candidate_to_canonical",
    "discover_publication_candidates",
    "load_canonical_publication_context",
    "prepare_publication_invocation",
]

DEFAULT_MAXIMUM_MANIFEST_BYTES: Final[int] = 16 * 1024 * 1024

CanonicalPublicationState: TypeAlias = Literal[
    "current_selectable",
    "withdrawn_head",
    "historical",
    "withdrawn_historical",
]
AuthorizationOperation: TypeAlias = Literal[
    "project_evidence", "read_projection_cache"
]
CandidateDriftField: TypeAlias = Literal[
    "work",
    "source_record",
    "publication_kind",
    "capabilities",
    "record_set",
    "manifest_contract",
    "manifest_path",
    "manifest_digest",
    "published_at",
    "referenced_registration",
    "current_registration",
    "predecessor",
    "series_head",
    "withdrawal",
    "current_selectable",
]

_REASON_CODE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)


class PublicationIngestionError(RuntimeError):
    """Base error for Meridian publication discovery and verification."""

    code: str = "ingestion.error"

    def __init__(
        self,
        message: str,
        *,
        publication_id: str | None = None,
        producer_module_id: str | None = None,
        record_set_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.publication_id = publication_id
        self.producer_module_id = producer_module_id
        self.record_set_id = record_set_id


class IngestionValidationError(PublicationIngestionError, ValueError):
    """Raised when a Meridian ingestion request is invalid."""

    code = "ingestion.invalid"


class CatalogDiscoveryError(PublicationIngestionError):
    """Base error for typed Core catalog discovery failures."""

    code = "ingestion.catalog_failed"


class CatalogMissingError(CatalogDiscoveryError):
    """Raised when the disposable Core Academic Catalog does not exist."""

    code = "ingestion.catalog_missing"


class CatalogIncompatibleError(CatalogDiscoveryError):
    """Raised when the catalog application or schema is unsupported."""

    code = "ingestion.catalog_incompatible"


class CatalogInvalidError(CatalogDiscoveryError):
    """Raised when the catalog is malformed, corrupt, or contradictory."""

    code = "ingestion.catalog_invalid"


class CatalogReadFailedError(CatalogDiscoveryError):
    """Raised when the catalog cannot be read operationally."""

    code = "ingestion.catalog_read_failed"


class PublicationVerificationError(PublicationIngestionError):
    """Base error for canonical publication verification failures."""

    code = "ingestion.verification_failed"


class PublicationCandidateMissingError(PublicationVerificationError):
    """Raised when a catalog candidate no longer exists canonically."""

    code = "ingestion.candidate_missing"

    def __init__(self, publication_id: str) -> None:
        super().__init__(
            "The catalog candidate no longer exists in canonical Core state.",
            publication_id=publication_id,
        )


class CandidateDriftError(PublicationVerificationError):
    """Raised when a candidate row disagrees with canonical Core state."""

    code = "ingestion.candidate_drift"

    def __init__(
        self,
        publication_id: str,
        drift_fields: tuple[CandidateDriftField, ...],
    ) -> None:
        super().__init__(
            "The catalog candidate differs from canonical Core state.",
            publication_id=publication_id,
        )
        self.drift_fields = drift_fields


class CanonicalPublicationError(PublicationVerificationError):
    """Raised when a canonical Publication Record is invalid or unreadable."""

    code = "ingestion.publication_invalid"


class CanonicalPublicationReadError(CanonicalPublicationError):
    """Raised when canonical Publication Record storage cannot be read."""

    code = "ingestion.publication_read_failed"


class PublicationRegistrationError(PublicationVerificationError):
    """Raised when canonical registration state is invalid."""

    code = "ingestion.registration_invalid"


class PublicationRegistrationMissingError(PublicationRegistrationError):
    """Raised when the exact referenced registration revision is absent."""

    code = "ingestion.registration_missing"


class PublicationRegistrationMismatchError(PublicationRegistrationError):
    """Raised when the referenced registration disagrees with the publication."""

    code = "ingestion.registration_mismatch"


class CurrentRegistrationError(PublicationRegistrationError):
    """Raised when the explicit current registration pointer is invalid."""

    code = "ingestion.registration_current_invalid"


class PublicationSeriesError(PublicationVerificationError):
    """Raised when canonical publication-series state is contradictory."""

    code = "ingestion.series_invalid"


class WithdrawalReadError(PublicationVerificationError):
    """Raised when canonical withdrawal state cannot be read safely."""

    code = "ingestion.withdrawal_read_failed"


class WithdrawalInvalidError(PublicationVerificationError):
    """Raised when canonical withdrawal state is contradictory."""

    code = "ingestion.withdrawal_invalid"


class ProducerProfileError(PublicationIngestionError):
    """Base error for Core producer-profile compatibility failures."""

    code = "ingestion.profile_failed"


class ProducerProfileMissingError(ProducerProfileError):
    """Raised when no exact producer profile is enabled."""

    code = "ingestion.profile_missing"


class ProducerProfileRegistryError(ProducerProfileError):
    """Raised when the supplied Core producer registry is invalid."""

    code = "ingestion.profile_registry_invalid"


class ProducerProfileEvaluationError(ProducerProfileError):
    """Raised when Core compatibility evaluation cannot be completed."""

    code = "ingestion.profile_evaluation_failed"


class ProducerProfileIncompatibleError(ProducerProfileError):
    """Raised when Core reports exact producer-contract incompatibility."""

    code = "ingestion.profile_incompatible"

    def __init__(
        self,
        *,
        publication_id: str,
        producer_module_id: str,
        compatibility_codes: tuple[str, ...],
    ) -> None:
        super().__init__(
            "The canonical publication is incompatible with its producer profile.",
            publication_id=publication_id,
            producer_module_id=producer_module_id,
        )
        self.compatibility_codes = compatibility_codes


class PublicationAuthorizationError(PublicationIngestionError):
    """Base error for deployment-provided authorization failures."""

    code = "ingestion.authorization_invalid"


class PublicationAuthorizationDeniedError(PublicationAuthorizationError):
    """Raised when the deployment denies manifest access."""

    code = "ingestion.authorization_denied"

    def __init__(
        self,
        *,
        publication_id: str,
        reason_codes: tuple[str, ...],
        policy_id: str,
        policy_version: str,
    ) -> None:
        super().__init__(
            "The deployment denied access to the canonical publication manifest.",
            publication_id=publication_id,
        )
        self.reason_codes = reason_codes
        self.policy_id = policy_id
        self.policy_version = policy_version


class ManifestPreparationError(PublicationVerificationError):
    """Base error for canonical manifest verification and byte loading."""

    code = "ingestion.manifest_failed"


class ManifestMissingError(ManifestPreparationError):
    """Raised when the exact canonical manifest is absent."""

    code = "ingestion.manifest_missing"


class ManifestInvalidError(ManifestPreparationError):
    """Raised when canonical path containment or digest verification fails."""

    code = "ingestion.manifest_invalid"


class ManifestReadFailedError(ManifestPreparationError):
    """Raised when verified manifest bytes cannot be read safely."""

    code = "ingestion.manifest_read_failed"


class ManifestTooLargeError(ManifestPreparationError):
    """Raised when a manifest exceeds the configured bounded read limit."""

    code = "ingestion.manifest_too_large"

    def __init__(self, publication_id: str, maximum_manifest_bytes: int) -> None:
        super().__init__(
            "The canonical publication manifest exceeds the configured byte limit.",
            publication_id=publication_id,
        )
        self.maximum_manifest_bytes = maximum_manifest_bytes


class CanonicalStateChangedError(PublicationVerificationError):
    """Raised when canonical state changes during request preparation."""

    code = "ingestion.canonical_state_changed"


@dataclass(frozen=True, slots=True)
class PublicationDiscoveryRequest:
    """One explicit bounded query against Core's disposable catalog."""

    query: PublicationCatalogQuery

    def __post_init__(self) -> None:
        if not isinstance(self.query, PublicationCatalogQuery):
            raise IngestionValidationError(
                "query must be a Core PublicationCatalogQuery."
            )
        if self.query.limit is None:
            raise IngestionValidationError(
                "publication discovery requires an explicit finite query limit."
            )


@dataclass(frozen=True, slots=True)
class PublicationCandidate:
    """One exact typed catalog row retained only as a discovery observation."""

    catalog_publication: CatalogPublication
    ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(self.catalog_publication, CatalogPublication):
            raise IngestionValidationError(
                "catalog_publication must be a Core CatalogPublication."
            )
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            raise IngestionValidationError("ordinal must be an integer.")
        if self.ordinal < 0:
            raise IngestionValidationError("ordinal must be nonnegative.")

    @property
    def publication_id(self) -> str:
        return self.catalog_publication.publication_id


@dataclass(frozen=True, slots=True)
class PublicationDiscoveryResult:
    """Deterministic bounded Core catalog candidates."""

    request: PublicationDiscoveryRequest
    candidates: tuple[PublicationCandidate, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, PublicationDiscoveryRequest):
            raise IngestionValidationError(
                "request must be a PublicationDiscoveryRequest."
            )
        try:
            candidates = tuple(self.candidates)
        except TypeError as error:
            raise IngestionValidationError("candidates must be iterable.") from error
        if any(not isinstance(item, PublicationCandidate) for item in candidates):
            raise IngestionValidationError(
                "candidates must contain PublicationCandidate values."
            )
        object.__setattr__(self, "candidates", candidates)
        expected = tuple(range(len(candidates)))
        actual = tuple(item.ordinal for item in candidates)
        if actual != expected:
            raise IngestionValidationError(
                "candidate ordinals must preserve contiguous catalog result order."
            )
        identifiers = tuple(item.publication_id for item in candidates)
        if len(set(identifiers)) != len(identifiers):
            raise CatalogInvalidError(
                "The Core catalog returned a duplicate publication candidate."
            )


@dataclass(frozen=True, slots=True)
class PublicationSeriesMember:
    """One canonical Publication Record and its optional exact withdrawal."""

    publication: PublicationRecord
    withdrawal: PublicationWithdrawal | None

    def __post_init__(self) -> None:
        if not isinstance(self.publication, PublicationRecord):
            raise IngestionValidationError(
                "publication must be a Core PublicationRecord."
            )
        if self.withdrawal is not None:
            if not isinstance(self.withdrawal, PublicationWithdrawal):
                raise IngestionValidationError(
                    "withdrawal must be a Core PublicationWithdrawal or None."
                )
            if self.withdrawal.publication_id != self.publication.publication_id:
                raise IngestionValidationError(
                    "withdrawal must identify the same publication."
                )


@dataclass(frozen=True, slots=True)
class PublicationSeriesObservation:
    """Validated canonical series order and the target publication's state."""

    members: tuple[PublicationSeriesMember, ...]
    target_publication_id: str
    target_index: int
    head_publication_id: str
    target_state: CanonicalPublicationState
    successor_publication_id: str | None

    def __post_init__(self) -> None:
        try:
            members = tuple(self.members)
        except TypeError as error:
            raise IngestionValidationError(
                "series members must be iterable."
            ) from error
        if not members:
            raise IngestionValidationError("series members must not be empty.")
        if any(not isinstance(item, PublicationSeriesMember) for item in members):
            raise IngestionValidationError(
                "members must contain PublicationSeriesMember values."
            )
        object.__setattr__(self, "members", members)
        if (
            isinstance(self.target_index, bool)
            or not isinstance(self.target_index, int)
            or not 0 <= self.target_index < len(members)
        ):
            raise IngestionValidationError("target_index is outside the series.")
        target = members[self.target_index]
        if target.publication.publication_id != self.target_publication_id:
            raise IngestionValidationError(
                "target_index does not identify target_publication_id."
            )
        if members[-1].publication.publication_id != self.head_publication_id:
            raise IngestionValidationError(
                "head_publication_id must identify the validated series head."
            )
        if self.target_state not in {
            "current_selectable",
            "withdrawn_head",
            "historical",
            "withdrawn_historical",
        }:
            raise IngestionValidationError("target_state is invalid.")
        expected_successor = (
            None
            if self.target_index == len(members) - 1
            else members[self.target_index + 1].publication.publication_id
        )
        if self.successor_publication_id != expected_successor:
            raise IngestionValidationError(
                "successor_publication_id does not match validated series order."
            )
        is_head = self.target_publication_id == self.head_publication_id
        withdrawn = target.withdrawal is not None
        expected_state: CanonicalPublicationState
        if is_head and not withdrawn:
            expected_state = "current_selectable"
        elif is_head:
            expected_state = "withdrawn_head"
        elif withdrawn:
            expected_state = "withdrawn_historical"
        else:
            expected_state = "historical"
        if self.target_state != expected_state:
            raise IngestionValidationError(
                "target_state does not match the target member and series head."
            )

    @property
    def target_member(self) -> PublicationSeriesMember:
        return self.members[self.target_index]

    @property
    def target_is_head(self) -> bool:
        return self.target_publication_id == self.head_publication_id


@dataclass(frozen=True, slots=True)
class CanonicalPublicationContext:
    """One coherent canonical Core publication observation."""

    publication: PublicationRecord
    referenced_registration: AcademicWorkRegistration | None
    current_registration: AcademicWorkRegistration | None
    series: PublicationSeriesObservation
    withdrawal: PublicationWithdrawal | None

    def __post_init__(self) -> None:
        if not isinstance(self.publication, PublicationRecord):
            raise IngestionValidationError(
                "publication must be a Core PublicationRecord."
            )
        if self.publication.publication_kind == "academic_result_set":
            if not isinstance(
                self.referenced_registration, AcademicWorkRegistration
            ):
                raise IngestionValidationError(
                    "academic context requires its referenced registration."
                )
            if (
                self.referenced_registration.work != self.publication.work
                or self.referenced_registration.registration_revision
                != self.publication.academic_work_registration_revision
            ):
                raise IngestionValidationError(
                    "referenced registration must match the publication exactly."
                )
        elif (
            self.referenced_registration is not None
            or self.current_registration is not None
        ):
            raise IngestionValidationError(
                "intervention context must not include registration state."
            )
        if self.current_registration is not None and not isinstance(
            self.current_registration, AcademicWorkRegistration
        ):
            raise IngestionValidationError(
                "current_registration must be an AcademicWorkRegistration or None."
            )
        if not isinstance(self.series, PublicationSeriesObservation):
            raise IngestionValidationError(
                "series must be a PublicationSeriesObservation."
            )
        if self.series.target_publication_id != self.publication.publication_id:
            raise IngestionValidationError(
                "series target must identify the canonical publication."
            )
        if self.series.target_member.publication != self.publication:
            raise IngestionValidationError(
                "series target must preserve the exact canonical publication."
            )
        if self.withdrawal != self.series.target_member.withdrawal:
            raise IngestionValidationError(
                "withdrawal must equal the target member withdrawal."
            )

    @property
    def canonical_state(self) -> CanonicalPublicationState:
        return self.series.target_state


@dataclass(frozen=True, slots=True)
class PublicationAuthorizationRequest:
    """Privacy-minimized canonical context supplied before manifest access."""

    publication: PublicationRecord
    referenced_registration: AcademicWorkRegistration | None
    withdrawal: PublicationWithdrawal | None
    canonical_state: CanonicalPublicationState
    operation: AuthorizationOperation
    purpose_id: str
    requested_student_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.publication, PublicationRecord):
            raise IngestionValidationError(
                "authorization publication must be a PublicationRecord."
            )
        if self.publication.publication_kind == "academic_result_set":
            if not isinstance(
                self.referenced_registration, AcademicWorkRegistration
            ):
                raise IngestionValidationError(
                    "academic authorization requires the referenced registration."
                )
        elif self.referenced_registration is not None:
            raise IngestionValidationError(
                "intervention authorization must not include a registration."
            )
        if (
            self.withdrawal is not None
            and self.withdrawal.publication_id != self.publication.publication_id
        ):
            raise IngestionValidationError(
                "authorization withdrawal must match the publication."
            )
        if self.operation not in {
            "project_evidence",
            "read_projection_cache",
        }:
            raise IngestionValidationError("authorization operation is invalid.")
        object.__setattr__(
            self,
            "purpose_id",
            _identifier(self.purpose_id, "purpose_id"),
        )
        if isinstance(self.requested_student_ids, (str, bytes)):
            raise IngestionValidationError(
                "requested_student_ids must be an iterable of identifiers."
            )
        try:
            raw_students = tuple(self.requested_student_ids)
        except TypeError as error:
            raise IngestionValidationError(
                "requested_student_ids must be iterable."
            ) from error
        students = tuple(
            sorted(_identifier(item, "student_id") for item in raw_students)
        )
        if len(set(students)) != len(students):
            raise IngestionValidationError(
                "requested_student_ids must not contain duplicates."
            )
        object.__setattr__(self, "requested_student_ids", students)


@dataclass(frozen=True, slots=True)
class PublicationAuthorizationDecision:
    """One exact deployment authorization policy decision."""

    allowed: bool
    policy_id: str
    policy_version: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise PublicationAuthorizationError("allowed must be boolean.")
        object.__setattr__(
            self,
            "policy_id",
            _identifier(self.policy_id, "policy_id"),
        )
        object.__setattr__(
            self,
            "policy_version",
            _identifier(self.policy_version, "policy_version"),
        )
        if isinstance(self.reason_codes, (str, bytes)):
            raise PublicationAuthorizationError(
                "reason_codes must be an iterable of stable codes."
            )
        try:
            codes = tuple(sorted(set(self.reason_codes)))
        except TypeError as error:
            raise PublicationAuthorizationError(
                "reason_codes must be iterable."
            ) from error
        if any(
            not isinstance(code, str) or _REASON_CODE.fullmatch(code) is None
            for code in codes
        ):
            raise PublicationAuthorizationError(
                "reason_codes must contain lowercase dotted identifiers."
            )
        if self.allowed and codes:
            raise PublicationAuthorizationError(
                "allowed authorization decisions must not contain reason codes."
            )
        if not self.allowed and not codes:
            raise PublicationAuthorizationError(
                "denied authorization decisions require a reason code."
            )
        object.__setattr__(self, "reason_codes", codes)


@runtime_checkable
class PublicationAuthorizer(Protocol):
    """Deployment boundary for access decisions before manifest reads."""

    def authorize(
        self,
        request: PublicationAuthorizationRequest,
    ) -> PublicationAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class PreparedPublicationInvocation:
    """Verified immutable input ready for later adapter invocation."""

    candidate: PublicationCandidate
    canonical_context: CanonicalPublicationContext
    producer_profile: PublicationProducerProfile
    compatibility: PublicationCompatibilityResult
    adapter_match: AdapterMatch
    producer_reader_version: str
    authorization_request: PublicationAuthorizationRequest
    authorization: PublicationAuthorizationDecision
    projection_request: AdapterProjectionRequest = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, PublicationCandidate):
            raise IngestionValidationError(
                "candidate must be a PublicationCandidate."
            )
        if not isinstance(self.canonical_context, CanonicalPublicationContext):
            raise IngestionValidationError(
                "canonical_context must be a CanonicalPublicationContext."
            )
        if not isinstance(self.producer_profile, PublicationProducerProfile):
            raise IngestionValidationError(
                "producer_profile must be a PublicationProducerProfile."
            )
        if (
            self.candidate.publication_id
            != self.canonical_context.publication.publication_id
        ):
            raise IngestionValidationError(
                "candidate and canonical context must identify one publication."
            )
        if (
            self.producer_profile.module_id
            != self.canonical_context.publication.work.module_id
        ):
            raise IngestionValidationError(
                "producer_profile must match the canonical producer module."
            )
        if not isinstance(self.compatibility, PublicationCompatibilityResult):
            raise IngestionValidationError(
                "compatibility must be a PublicationCompatibilityResult."
            )
        if not self.compatibility.compatible:
            raise IngestionValidationError(
                "prepared invocation requires compatible producer contracts."
            )
        if not isinstance(self.adapter_match, AdapterMatch):
            raise IngestionValidationError(
                "adapter_match must be an AdapterMatch."
            )
        object.__setattr__(
            self,
            "producer_reader_version",
            _single_line(self.producer_reader_version, "producer_reader_version"),
        )
        if not isinstance(
            self.authorization_request, PublicationAuthorizationRequest
        ):
            raise IngestionValidationError(
                "authorization_request must be a PublicationAuthorizationRequest."
            )
        expected_authorization_request = PublicationAuthorizationRequest(
            publication=self.canonical_context.publication,
            referenced_registration=(
                self.canonical_context.referenced_registration
            ),
            withdrawal=self.canonical_context.withdrawal,
            canonical_state=self.canonical_context.canonical_state,
            operation="project_evidence",
            purpose_id=self.authorization_request.purpose_id,
            requested_student_ids=(
                self.authorization_request.requested_student_ids
            ),
        )
        if self.authorization_request != expected_authorization_request:
            raise IngestionValidationError(
                "authorization_request must preserve the canonical context exactly."
            )
        if not isinstance(self.authorization, PublicationAuthorizationDecision):
            raise IngestionValidationError(
                "authorization must be a PublicationAuthorizationDecision."
            )
        if not self.authorization.allowed:
            raise IngestionValidationError(
                "prepared invocation requires an allowed authorization decision."
            )
        if not isinstance(self.projection_request, AdapterProjectionRequest):
            raise IngestionValidationError(
                "projection_request must be an AdapterProjectionRequest."
            )
        if (
            self.projection_request.publication
            != self.canonical_context.publication
            or self.projection_request.registration
            != self.canonical_context.referenced_registration
            or self.projection_request.withdrawal
            != self.canonical_context.withdrawal
        ):
            raise IngestionValidationError(
                "projection_request must preserve the canonical context exactly."
            )


def discover_publication_candidates(
    workspace_root: str | Path,
    request: PublicationDiscoveryRequest,
) -> PublicationDiscoveryResult:
    """Query Core's disposable catalog without promoting rows to authority."""
    if not isinstance(request, PublicationDiscoveryRequest):
        raise IngestionValidationError(
            "request must be a PublicationDiscoveryRequest."
        )
    try:
        rows = query_publication_catalog(workspace_root, request.query)
    except AcademicCatalogNotFoundError as error:
        raise CatalogMissingError(
            "The disposable Core Academic Catalog does not exist."
        ) from error
    except AcademicCatalogCompatibilityError as error:
        raise CatalogIncompatibleError(
            "The Core Academic Catalog application or schema is incompatible."
        ) from error
    except AcademicCatalogIntegrityError as error:
        raise CatalogInvalidError(
            "The Core Academic Catalog is malformed or contradictory."
        ) from error
    except AcademicCatalogReadError as error:
        raise CatalogReadFailedError(
            "The Core Academic Catalog could not be read."
        ) from error
    except AcademicCatalogError as error:
        raise CatalogReadFailedError(
            "Core Academic Catalog discovery failed."
        ) from error
    candidates = tuple(
        PublicationCandidate(catalog_publication=row, ordinal=index)
        for index, row in enumerate(rows)
    )
    identifiers = tuple(item.publication_id for item in candidates)
    if len(set(identifiers)) != len(identifiers):
        raise CatalogInvalidError(
            "The Core Academic Catalog returned duplicate publication IDs."
        )
    return PublicationDiscoveryResult(request=request, candidates=candidates)


def compare_candidate_to_canonical(
    candidate: PublicationCandidate,
    context: CanonicalPublicationContext,
) -> tuple[CandidateDriftField, ...]:
    """Return deterministic fields where a catalog row differs from authority."""
    if not isinstance(candidate, PublicationCandidate):
        raise IngestionValidationError("candidate must be a PublicationCandidate.")
    if not isinstance(context, CanonicalPublicationContext):
        raise IngestionValidationError(
            "context must be a CanonicalPublicationContext."
        )
    row = candidate.catalog_publication
    publication = context.publication
    referenced = context.referenced_registration
    current = context.current_registration
    withdrawal = context.withdrawal
    drift: list[CandidateDriftField] = []
    if row.work != publication.work:
        drift.append("work")
    if row.source_record != publication.source_record:
        drift.append("source_record")
    if row.publication_kind != publication.publication_kind:
        drift.append("publication_kind")
    if row.capabilities != publication.capabilities:
        drift.append("capabilities")
    if (
        row.record_set_id != publication.record_set_id
        or row.record_set_revision != publication.record_set_revision
    ):
        drift.append("record_set")
    if row.manifest_contract_version != publication.manifest_contract_version:
        drift.append("manifest_contract")
    if row.manifest_path != publication.manifest_path:
        drift.append("manifest_path")
    if (
        row.manifest_digest_algorithm != publication.manifest_digest_algorithm
        or row.manifest_digest != publication.manifest_digest
    ):
        drift.append("manifest_digest")
    if _utc(row.published_at) != _utc(publication.published_at):
        drift.append("published_at")
    referenced_revision = (
        None if referenced is None else referenced.registration_revision
    )
    referenced_lifecycle = None if referenced is None else referenced.lifecycle
    if (
        row.academic_work_registration_revision != referenced_revision
        or row.referenced_registration_lifecycle != referenced_lifecycle
    ):
        drift.append("referenced_registration")
    if publication.publication_kind == "academic_result_set":
        current_revision = None if current is None else current.registration_revision
        current_lifecycle = None if current is None else current.lifecycle
        if (
            row.current_registration_revision != current_revision
            or row.current_registration_lifecycle != current_lifecycle
        ):
            drift.append("current_registration")
    if row.supersedes_publication_id != publication.supersedes_publication_id:
        drift.append("predecessor")
    if row.is_series_head != context.series.target_is_head:
        drift.append("series_head")
    expected_withdrawn = withdrawal is not None
    expected_withdrawn_at = (
        None if withdrawal is None else _utc(withdrawal.withdrawn_at)
    )
    row_withdrawn_at = None if row.withdrawn_at is None else _utc(row.withdrawn_at)
    if (
        row.is_withdrawn != expected_withdrawn
        or row_withdrawn_at != expected_withdrawn_at
    ):
        drift.append("withdrawal")
    expected_selectable = context.canonical_state == "current_selectable"
    if row.is_current_selectable != expected_selectable:
        drift.append("current_selectable")
    return tuple(drift)


def prepare_publication_invocation(
    workspace_root: str | Path,
    candidate: PublicationCandidate,
    *,
    producer_registry: PublicationProducerRegistry,
    adapter_registry: AdapterRegistry,
    authorizer: PublicationAuthorizer,
    authorization_purpose_id: str,
    requested_student_ids: Iterable[str] = (),
    distribution_version_resolver: DistributionVersionResolver = (
        installed_distribution_version
    ),
    maximum_manifest_bytes: int = DEFAULT_MAXIMUM_MANIFEST_BYTES,
) -> PreparedPublicationInvocation:
    """Prepare one verified request without invoking a producer adapter."""
    if not isinstance(candidate, PublicationCandidate):
        raise IngestionValidationError("candidate must be a PublicationCandidate.")
    if not isinstance(producer_registry, PublicationProducerRegistry):
        raise ProducerProfileRegistryError(
            "producer_registry must be a Core PublicationProducerRegistry."
        )
    if not isinstance(adapter_registry, AdapterRegistry):
        raise IngestionValidationError(
            "adapter_registry must be a Meridian AdapterRegistry."
        )
    if not isinstance(authorizer, PublicationAuthorizer):
        raise PublicationAuthorizationError(
            "authorizer must satisfy PublicationAuthorizer."
        )
    if (
        isinstance(maximum_manifest_bytes, bool)
        or not isinstance(maximum_manifest_bytes, int)
        or maximum_manifest_bytes <= 0
    ):
        raise IngestionValidationError(
            "maximum_manifest_bytes must be a positive integer."
        )
    purpose_id = _identifier(authorization_purpose_id, "authorization_purpose_id")
    students = _student_ids(requested_student_ids)

    initial_context = load_canonical_publication_context(
        workspace_root, candidate.publication_id
    )
    drift = compare_candidate_to_canonical(candidate, initial_context)
    if drift:
        raise CandidateDriftError(candidate.publication_id, drift)

    profile = _producer_profile(producer_registry, initial_context.publication)
    compatibility = _compatibility(profile, initial_context)
    match = adapter_registry.select(
        initial_context.publication,
        initial_context.referenced_registration,
    )
    reader_version = resolve_producer_reader_version(
        match.descriptor,
        distribution_version_resolver,
    )

    authorization_request = PublicationAuthorizationRequest(
        publication=initial_context.publication,
        referenced_registration=initial_context.referenced_registration,
        withdrawal=initial_context.withdrawal,
        canonical_state=initial_context.canonical_state,
        operation="project_evidence",
        purpose_id=purpose_id,
        requested_student_ids=students,
    )
    try:
        decision = authorizer.authorize(authorization_request)
    except PublicationAuthorizationError:
        raise
    except Exception as error:
        raise PublicationAuthorizationError(
            "The deployment authorizer failed to produce a decision.",
            publication_id=initial_context.publication.publication_id,
        ) from error
    if not isinstance(decision, PublicationAuthorizationDecision):
        raise PublicationAuthorizationError(
            "The deployment authorizer returned an invalid decision.",
            publication_id=initial_context.publication.publication_id,
        )
    if not decision.allowed:
        raise PublicationAuthorizationDeniedError(
            publication_id=initial_context.publication.publication_id,
            reason_codes=decision.reason_codes,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
        )

    manifest_path = _verify_manifest(workspace_root, initial_context.publication)
    manifest_bytes = _read_manifest_bytes(
        manifest_path,
        publication_id=initial_context.publication.publication_id,
        maximum_manifest_bytes=maximum_manifest_bytes,
    )
    try:
        projection_request = AdapterProjectionRequest(
            publication=initial_context.publication,
            registration=initial_context.referenced_registration,
            withdrawal=initial_context.withdrawal,
            manifest_bytes=manifest_bytes,
        )
    except ValueError as error:
        raise ManifestInvalidError(
            "The verified manifest bytes do not match canonical publication identity.",
            publication_id=initial_context.publication.publication_id,
        ) from error

    try:
        final_context = load_canonical_publication_context(
            workspace_root, candidate.publication_id
        )
    except PublicationVerificationError as error:
        raise CanonicalStateChangedError(
            "Canonical Core state could not be reverified after manifest loading.",
            publication_id=candidate.publication_id,
        ) from error
    if final_context != initial_context:
        raise CanonicalStateChangedError(
            "Canonical Core state changed during publication verification.",
            publication_id=candidate.publication_id,
        )

    return PreparedPublicationInvocation(
        candidate=candidate,
        canonical_context=initial_context,
        producer_profile=profile,
        compatibility=compatibility,
        adapter_match=match,
        producer_reader_version=reader_version,
        authorization_request=authorization_request,
        authorization=decision,
        projection_request=projection_request,
    )


def load_canonical_publication_context(
    workspace_root: str | Path,
    publication_id: str,
) -> CanonicalPublicationContext:
    publication = _canonical_publication(workspace_root, publication_id)
    referenced, current = _registrations(workspace_root, publication)
    series = _series_observation(workspace_root, publication)
    return CanonicalPublicationContext(
        publication=publication,
        referenced_registration=referenced,
        current_registration=current,
        series=series,
        withdrawal=series.target_member.withdrawal,
    )


def _load_canonical_context(
    workspace_root: str | Path,
    publication_id: str,
) -> CanonicalPublicationContext:
    """Backward-compatible alias for the public canonical loader."""
    return load_canonical_publication_context(workspace_root, publication_id)


def _canonical_publication(
    workspace_root: str | Path,
    publication_id: str,
) -> PublicationRecord:
    try:
        publication = get_canonical_publication_record(workspace_root, publication_id)
        if publication.publication_id != publication_id:
            raise CanonicalPublicationError(
                "Canonical Publication Record identity does not match the request.",
                publication_id=publication_id,
            )
        return publication
    except RegistryServiceNotFoundError as error:
        raise PublicationCandidateMissingError(publication_id) from error
    except RegistryServiceIntegrityError as error:
        raise CanonicalPublicationError(
            "The canonical Publication Record is invalid.",
            publication_id=publication_id,
        ) from error
    except RegistryServiceWriteError as error:
        raise CanonicalPublicationReadError(
            "The canonical Publication Record could not be read.",
            publication_id=publication_id,
        ) from error
    except RegistryServiceError as error:
        raise CanonicalPublicationReadError(
            "Canonical Publication Record retrieval failed.",
            publication_id=publication_id,
        ) from error


def _registrations(
    workspace_root: str | Path,
    publication: PublicationRecord,
) -> tuple[AcademicWorkRegistration | None, AcademicWorkRegistration | None]:
    if publication.publication_kind == "intervention_record_set":
        return None, None
    revision = publication.academic_work_registration_revision
    if revision is None:
        raise PublicationRegistrationMismatchError(
            "Academic publication does not identify a registration revision.",
            publication_id=publication.publication_id,
        )
    try:
        referenced = load_academic_work_registration_revision(
            workspace_root,
            publication.work,
            revision,
        )
    except AcademicWorkRegistrationNotFoundError as error:
        raise PublicationRegistrationMissingError(
            "The exact referenced Academic Work Registration is missing.",
            publication_id=publication.publication_id,
        ) from error
    except (
        AcademicWorkRegistrationIntegrityError,
        AcademicWorkRegistrationReadError,
        AcademicWorkRegistrationStorageError,
    ) as error:
        raise PublicationRegistrationError(
            "The referenced Academic Work Registration is invalid.",
            publication_id=publication.publication_id,
        ) from error
    if (
        referenced.work != publication.work
        or referenced.registration_revision != revision
    ):
        raise PublicationRegistrationMismatchError(
            "The referenced Academic Work Registration does not match the publication.",
            publication_id=publication.publication_id,
        )
    try:
        current = load_current_academic_work_registration(
            workspace_root,
            publication.work,
        )
    except AcademicWorkRegistrationStorageError as error:
        raise CurrentRegistrationError(
            "The explicit current registration state is invalid.",
            publication_id=publication.publication_id,
        ) from error
    if current is not None and current.work != publication.work:
        raise CurrentRegistrationError(
            "The current registration does not match the publication work.",
            publication_id=publication.publication_id,
        )
    return referenced, current


def _series_observation(
    workspace_root: str | Path,
    publication: PublicationRecord,
) -> PublicationSeriesObservation:
    try:
        records = list_publication_record_set(
            workspace_root,
            publication.work,
            publication.publication_kind,
            publication.record_set_id,
        )
    except (
        PublicationIntegrityError,
        PublicationReadError,
        PublicationStorageError,
    ) as error:
        raise PublicationSeriesError(
            "The canonical publication series is invalid.",
            publication_id=publication.publication_id,
            record_set_id=publication.record_set_id,
        ) from error
    indices = tuple(
        index
        for index, item in enumerate(records)
        if item.publication_id == publication.publication_id
    )
    if len(indices) != 1:
        raise PublicationSeriesError(
            "The target publication is absent or duplicated in its canonical series.",
            publication_id=publication.publication_id,
            record_set_id=publication.record_set_id,
        )
    members = tuple(
        PublicationSeriesMember(
            publication=item,
            withdrawal=_canonical_withdrawal(workspace_root, item),
        )
        for item in records
    )
    target_index = indices[0]
    target = members[target_index]
    is_head = target_index == len(members) - 1
    withdrawn = target.withdrawal is not None
    state: CanonicalPublicationState
    if is_head and not withdrawn:
        state = "current_selectable"
    elif is_head:
        state = "withdrawn_head"
    elif withdrawn:
        state = "withdrawn_historical"
    else:
        state = "historical"
    return PublicationSeriesObservation(
        members=members,
        target_publication_id=publication.publication_id,
        target_index=target_index,
        head_publication_id=members[-1].publication.publication_id,
        target_state=state,
        successor_publication_id=(
            None
            if is_head
            else members[target_index + 1].publication.publication_id
        ),
    )


def _canonical_withdrawal(
    workspace_root: str | Path,
    publication: PublicationRecord,
) -> PublicationWithdrawal | None:
    try:
        return get_canonical_publication_withdrawal(
            workspace_root,
            publication.publication_id,
        )
    except RegistryServiceIntegrityError as error:
        raise WithdrawalInvalidError(
            "The canonical Publication Withdrawal is invalid.",
            publication_id=publication.publication_id,
        ) from error
    except (RegistryServiceNotFoundError, RegistryServiceWriteError) as error:
        raise WithdrawalReadError(
            "The canonical Publication Withdrawal could not be read.",
            publication_id=publication.publication_id,
        ) from error
    except RegistryServiceError as error:
        raise WithdrawalReadError(
            "Canonical Publication Withdrawal retrieval failed.",
            publication_id=publication.publication_id,
        ) from error


def _producer_profile(
    registry: PublicationProducerRegistry,
    publication: PublicationRecord,
) -> PublicationProducerProfile:
    try:
        profile = registry.get(publication.work.module_id)
    except PublicationProducerRegistryError as error:
        raise ProducerProfileRegistryError(
            "The supplied Core producer-profile registry is invalid.",
            publication_id=publication.publication_id,
            producer_module_id=publication.work.module_id,
        ) from error
    except PublicationCompatibilityError as error:
        raise ProducerProfileRegistryError(
            "The supplied Core producer-profile registry could not be queried.",
            publication_id=publication.publication_id,
            producer_module_id=publication.work.module_id,
        ) from error
    if profile is None:
        raise ProducerProfileMissingError(
            "No enabled Core producer profile matches the canonical publication.",
            publication_id=publication.publication_id,
            producer_module_id=publication.work.module_id,
        )
    return profile


def _compatibility(
    profile: PublicationProducerProfile,
    context: CanonicalPublicationContext,
) -> PublicationCompatibilityResult:
    publication = context.publication
    try:
        result = evaluate_publication_compatibility(
            publication,
            profile,
            context.referenced_registration,
        )
    except (PublicationProducerProfileError, PublicationCompatibilityError) as error:
        raise ProducerProfileEvaluationError(
            "Core producer compatibility evaluation failed.",
            publication_id=publication.publication_id,
            producer_module_id=publication.work.module_id,
        ) from error
    if not result.compatible:
        raise ProducerProfileIncompatibleError(
            publication_id=publication.publication_id,
            producer_module_id=publication.work.module_id,
            compatibility_codes=result.codes,
        )
    return result


def _verify_manifest(
    workspace_root: str | Path,
    publication: PublicationRecord,
) -> Path:
    try:
        return verify_publication_manifest(workspace_root, publication)
    except PublicationManifestNotFoundError as error:
        raise ManifestMissingError(
            "The canonical publication manifest is missing.",
            publication_id=publication.publication_id,
        ) from error
    except PublicationManifestIntegrityError as error:
        raise ManifestInvalidError(
            "The canonical publication manifest failed path or digest verification.",
            publication_id=publication.publication_id,
        ) from error
    except PublicationManifestError as error:
        raise ManifestReadFailedError(
            "The canonical publication manifest could not be verified.",
            publication_id=publication.publication_id,
        ) from error


def _read_manifest_bytes(
    path: Path,
    *,
    publication_id: str,
    maximum_manifest_bytes: int,
) -> bytes:
    try:
        with path.open("rb") as source:
            content = source.read(maximum_manifest_bytes + 1)
    except (OSError, ValueError) as error:
        raise ManifestReadFailedError(
            "The verified publication manifest could not be read.",
            publication_id=publication_id,
        ) from error
    if len(content) > maximum_manifest_bytes:
        raise ManifestTooLargeError(publication_id, maximum_manifest_bytes)
    return content


def _single_line(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise IngestionValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise IngestionValidationError(
            f"{field_name} must be a nonempty trimmed string."
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise IngestionValidationError(
            f"{field_name} must be a control-free single-line string."
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise IngestionValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise IngestionValidationError(str(error)) from error


def _student_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise IngestionValidationError(
            "requested_student_ids must be an iterable of identifiers."
        )
    try:
        raw = tuple(values)
    except TypeError as error:
        raise IngestionValidationError(
            "requested_student_ids must be iterable."
        ) from error
    result = tuple(sorted(_identifier(item, "student_id") for item in raw))
    if len(set(result)) != len(result):
        raise IngestionValidationError(
            "requested_student_ids must not contain duplicates."
        )
    return result


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)
