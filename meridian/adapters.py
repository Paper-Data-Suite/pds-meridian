"""Typed consumer-side producer adapter interface and exact registry."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import metadata
from typing import Final, Protocol, cast, runtime_checkable

from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    validate_academic_work_registration,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.publication_records import (
    PublicationCapability,
    PublicationKind,
    PublicationRecord,
    PublicationWithdrawal,
    is_publication_capability,
    is_publication_kind,
    validate_publication_record,
    validate_publication_withdrawal,
    validate_publication_withdrawal_relationship,
)

from meridian.evidence import EvidenceInventory, ProjectionIdentity

__all__ = [
    "AdapterBinding",
    "AdapterCapabilityUnsupportedError",
    "AdapterContractViolationError",
    "AdapterDescriptor",
    "AdapterError",
    "AdapterKey",
    "AdapterMatch",
    "AdapterNotFoundError",
    "AdapterProjectionError",
    "AdapterProjectionRequest",
    "AdapterRegistry",
    "AdapterRegistryError",
    "AdapterSelectionError",
    "AdapterValidationError",
    "DistributionVersionResolver",
    "DuplicateAdapterIdentityError",
    "DuplicateAdapterKeyError",
    "MERIDIAN_ADAPTER_INTERFACE_VERSION",
    "ProducerAdapter",
    "ProducerReaderUnavailableError",
    "ProducerReaderVersionUnsupportedError",
    "adapter_key_from_core",
    "installed_distribution_version",
    "projection_identity_from_descriptor",
    "resolve_producer_reader_version",
    "validate_projected_inventory",
]

MERIDIAN_ADAPTER_INTERFACE_VERSION: Final[str] = "1"

_CONTRACT_CODE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_DISTRIBUTION_NAME: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$"
)
_OPAQUE_IDENTIFIER: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:+-]*$"
)


class AdapterError(RuntimeError):
    """Base error for Meridian adapter and registry failures."""

    code: str = "adapters.error"

    def __init__(
        self,
        message: str,
        *,
        adapter_id: str | None = None,
        publication_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.adapter_id = adapter_id
        self.publication_id = publication_id


class AdapterValidationError(AdapterError, ValueError):
    """Raised when adapter configuration or a projection request is invalid."""

    code = "adapters.invalid"


class AdapterRegistryError(AdapterError):
    """Raised when adapters cannot form one unambiguous immutable registry."""

    code = "adapters.registry_invalid"


class DuplicateAdapterKeyError(AdapterRegistryError):
    """Raised when two adapters claim the same exact compatibility key."""

    code = "adapters.duplicate_key"

    def __init__(self, key: AdapterKey) -> None:
        super().__init__(f"Duplicate adapter key: {key!r}.")
        self.key = key


class DuplicateAdapterIdentityError(AdapterRegistryError):
    """Raised when one adapter ID is assigned conflicting meanings."""

    code = "adapters.duplicate_identity"

    def __init__(self, adapter_id: str) -> None:
        super().__init__(
            f"Adapter ID {adapter_id!r} has conflicting descriptor identity.",
            adapter_id=adapter_id,
        )


class AdapterSelectionError(AdapterError):
    """Base error for exact adapter selection failures."""

    code = "adapters.selection_failed"


class AdapterNotFoundError(AdapterSelectionError):
    """Raised when no adapter is registered for one exact key."""

    code = "adapters.not_found"

    def __init__(self, key: AdapterKey, publication_id: str) -> None:
        super().__init__(
            "No Meridian adapter is registered for the exact publication contracts.",
            publication_id=publication_id,
        )
        self.key = key


class AdapterCapabilityUnsupportedError(AdapterSelectionError):
    """Raised when an exact adapter lacks claimed publication capabilities."""

    code = "adapters.capability_unsupported"

    def __init__(
        self,
        *,
        adapter_id: str,
        publication_id: str,
        unsupported_capabilities: tuple[PublicationCapability, ...],
    ) -> None:
        names = ", ".join(unsupported_capabilities)
        super().__init__(
            f"Adapter {adapter_id!r} does not support capabilities: {names}.",
            adapter_id=adapter_id,
            publication_id=publication_id,
        )
        self.unsupported_capabilities = unsupported_capabilities


class ProducerReaderUnavailableError(AdapterError):
    """Raised when the selected adapter's producer-reader distribution is absent."""

    code = "adapters.reader_unavailable"

    def __init__(self, *, adapter_id: str, distribution_name: str) -> None:
        super().__init__(
            f"Producer reader distribution {distribution_name!r} is not installed.",
            adapter_id=adapter_id,
        )
        self.distribution_name = distribution_name


class ProducerReaderVersionUnsupportedError(AdapterError):
    """Raised when an installed producer-reader version was not declared supported."""

    code = "adapters.reader_version_unsupported"

    def __init__(
        self,
        *,
        adapter_id: str,
        distribution_name: str,
        installed_version: str,
        supported_versions: tuple[str, ...],
    ) -> None:
        super().__init__(
            f"Producer reader {distribution_name!r} version {installed_version!r} "
            "is not supported by the selected adapter.",
            adapter_id=adapter_id,
        )
        self.distribution_name = distribution_name
        self.installed_version = installed_version
        self.supported_versions = supported_versions


class AdapterProjectionError(AdapterError):
    """A controlled or safely wrapped producer-reader projection failure."""

    code = "adapters.projection_failed"


class AdapterContractViolationError(AdapterError):
    """Raised when an adapter violates the Meridian projection contract."""

    code = "adapters.projection_contract_violation"


def _single_line(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AdapterValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise AdapterValidationError(
            f"{field_name} must be a nonempty string without surrounding whitespace."
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise AdapterValidationError(
            f"{field_name} must be a control-free single-line string."
        )
    return value


def _core_identifier(value: object, field_name: str, *, lowercase: bool = False) -> str:
    if not isinstance(value, str):
        raise AdapterValidationError(f"{field_name} must be a string.")
    try:
        result = validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AdapterValidationError(str(error)) from error
    if lowercase and result != result.lower():
        raise AdapterValidationError(f"{field_name} must be lowercase.")
    return result


def _contract_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _CONTRACT_CODE.fullmatch(value) is None:
        raise AdapterValidationError(
            f"{field_name} must be a lowercase dotted contract identifier."
        )
    return value


def _opaque_identifier(value: object, field_name: str) -> str:
    text = _single_line(value, field_name)
    if _OPAQUE_IDENTIFIER.fullmatch(text) is None:
        raise AdapterValidationError(
            f"{field_name} must be an opaque identifier without path separators."
        )
    return text


def _distribution_name(value: object) -> str:
    text = _single_line(value, "producer_reader_distribution")
    if _DISTRIBUTION_NAME.fullmatch(text) is None:
        raise AdapterValidationError(
            "producer_reader_distribution must be a valid distribution name."
        )
    return text


def _exact_versions(value: object) -> frozenset[str]:
    if isinstance(value, (str, bytes)):
        raise AdapterValidationError(
            "supported_producer_reader_versions must be an iterable of versions."
        )
    try:
        versions = frozenset(
            _single_line(item, "producer_reader_version")
            for item in cast(Iterable[object], value)
        )
    except TypeError as error:
        raise AdapterValidationError(
            "supported_producer_reader_versions must be iterable."
        ) from error
    if not versions:
        raise AdapterValidationError(
            "supported_producer_reader_versions must not be empty."
        )
    return versions


def _capabilities(value: object) -> frozenset[PublicationCapability]:
    if isinstance(value, (str, bytes)):
        raise AdapterValidationError("supported_capabilities must be an iterable.")
    try:
        raw = frozenset(cast(Iterable[object], value))
    except TypeError as error:
        raise AdapterValidationError(
            "supported_capabilities must be iterable."
        ) from error
    if any(not is_publication_capability(item) for item in raw):
        raise AdapterValidationError(
            "supported_capabilities contains an invalid Core capability."
        )
    return cast(frozenset[PublicationCapability], raw)


@dataclass(frozen=True, slots=True)
class AdapterKey:
    """One exact producer and contract combination supported by an adapter."""

    producer_module_id: str
    publication_kind: PublicationKind
    manifest_contract_version: str
    producer_contract_version: str | None
    source_record_kind: str | None
    source_record_contract_version: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "producer_module_id",
            _core_identifier(
                self.producer_module_id,
                "producer_module_id",
                lowercase=True,
            ),
        )
        if not is_publication_kind(self.publication_kind):
            raise AdapterValidationError("publication_kind is invalid.")
        object.__setattr__(
            self,
            "manifest_contract_version",
            _core_identifier(
                self.manifest_contract_version,
                "manifest_contract_version",
            ),
        )
        if self.publication_kind == "academic_result_set":
            if self.producer_contract_version is None:
                raise AdapterValidationError(
                    "academic adapter keys require producer_contract_version."
                )
            object.__setattr__(
                self,
                "producer_contract_version",
                _core_identifier(
                    self.producer_contract_version,
                    "producer_contract_version",
                ),
            )
        elif self.producer_contract_version is not None:
            raise AdapterValidationError(
                "intervention adapter keys must not claim producer_contract_version."
            )
        if self.source_record_kind is None:
            if self.source_record_contract_version is not None:
                raise AdapterValidationError(
                    "source_record_contract_version requires source_record_kind."
                )
        else:
            object.__setattr__(
                self,
                "source_record_kind",
                _core_identifier(
                    self.source_record_kind,
                    "source_record_kind",
                    lowercase=True,
                ),
            )
            if self.source_record_contract_version is not None:
                object.__setattr__(
                    self,
                    "source_record_contract_version",
                    _core_identifier(
                        self.source_record_contract_version,
                        "source_record_contract_version",
                    ),
                )

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, str]:
        """Return a deterministic key that preserves missing versus unversioned."""
        return (
            self.producer_module_id,
            self.publication_kind,
            self.manifest_contract_version,
            self.producer_contract_version or "",
            self.source_record_kind or "",
            self.source_record_contract_version or "",
        )


def _validated_core_context(
    publication: PublicationRecord,
    registration: AcademicWorkRegistration | None,
) -> tuple[PublicationRecord, AcademicWorkRegistration | None]:
    try:
        checked_publication = validate_publication_record(publication)
    except ValueError as error:
        raise AdapterValidationError(f"publication is invalid: {error}") from error
    checked_registration: AcademicWorkRegistration | None = None
    if registration is not None:
        try:
            checked_registration = validate_academic_work_registration(registration)
        except ValueError as error:
            raise AdapterValidationError(f"registration is invalid: {error}") from error
    if checked_publication.publication_kind == "academic_result_set":
        if checked_registration is None:
            raise AdapterValidationError(
                "academic publications require the exact referenced registration."
            )
        if checked_registration.work != checked_publication.work:
            raise AdapterValidationError(
                "registration work must match publication work."
            )
        if (
            checked_publication.academic_work_registration_revision
            != checked_registration.registration_revision
        ):
            raise AdapterValidationError(
                "registration revision must match the publication reference."
            )
    elif checked_registration is not None:
        raise AdapterValidationError(
            "intervention publications must not supply a registration."
        )
    return checked_publication, checked_registration


def adapter_key_from_core(
    publication: PublicationRecord,
    registration: AcademicWorkRegistration | None,
) -> AdapterKey:
    """Derive one exact adapter key from validated Core public models."""
    checked_publication, checked_registration = _validated_core_context(
        publication, registration
    )
    source = checked_publication.source_record
    return AdapterKey(
        producer_module_id=checked_publication.work.module_id,
        publication_kind=checked_publication.publication_kind,
        manifest_contract_version=checked_publication.manifest_contract_version,
        producer_contract_version=(
            checked_registration.producer_contract_version
            if checked_registration is not None
            else None
        ),
        source_record_kind=source.record_kind if source is not None else None,
        source_record_contract_version=(
            source.contract_version if source is not None else None
        ),
    )


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    """Immutable compatibility and reader metadata for one adapter binding."""

    adapter_id: str
    key: AdapterKey
    projection_contract_version: str
    supported_capabilities: frozenset[PublicationCapability]
    producer_reader_distribution: str
    supported_producer_reader_versions: frozenset[str]
    adapter_interface_version: str = MERIDIAN_ADAPTER_INTERFACE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "adapter_id",
            _contract_code(self.adapter_id, "adapter_id"),
        )
        if not isinstance(self.key, AdapterKey):
            raise AdapterValidationError("key must be an AdapterKey.")
        object.__setattr__(
            self,
            "projection_contract_version",
            _opaque_identifier(
                self.projection_contract_version,
                "projection_contract_version",
            ),
        )
        object.__setattr__(
            self,
            "supported_capabilities",
            _capabilities(self.supported_capabilities),
        )
        object.__setattr__(
            self,
            "producer_reader_distribution",
            _distribution_name(self.producer_reader_distribution),
        )
        object.__setattr__(
            self,
            "supported_producer_reader_versions",
            _exact_versions(self.supported_producer_reader_versions),
        )
        interface_version = _opaque_identifier(
            self.adapter_interface_version,
            "adapter_interface_version",
        )
        if interface_version != MERIDIAN_ADAPTER_INTERFACE_VERSION:
            raise AdapterValidationError(
                "adapter_interface_version is unsupported by this Meridian release."
            )
        object.__setattr__(self, "adapter_interface_version", interface_version)

    @property
    def identity_signature(
        self,
    ) -> tuple[str, str, str, frozenset[str], frozenset[PublicationCapability]]:
        """Return fields that must remain stable for one adapter ID."""
        return (
            self.adapter_interface_version,
            self.projection_contract_version,
            self.producer_reader_distribution,
            self.supported_producer_reader_versions,
            self.supported_capabilities,
        )


@dataclass(frozen=True, slots=True)
class AdapterProjectionRequest:
    """Verified immutable manifest bytes and exact Core projection context."""

    publication: PublicationRecord
    registration: AcademicWorkRegistration | None
    withdrawal: PublicationWithdrawal | None
    manifest_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        publication, registration = _validated_core_context(
            self.publication, self.registration
        )
        withdrawal: PublicationWithdrawal | None = None
        if self.withdrawal is not None:
            try:
                withdrawal = validate_publication_withdrawal(self.withdrawal)
                validate_publication_withdrawal_relationship(publication, withdrawal)
            except ValueError as error:
                raise AdapterValidationError(
                    f"withdrawal is invalid for publication: {error}"
                ) from error
        if type(self.manifest_bytes) is not bytes:
            raise AdapterValidationError("manifest_bytes must be immutable bytes.")
        if publication.manifest_digest_algorithm == "sha256":
            actual = hashlib.sha256(self.manifest_bytes).hexdigest()
            if actual != publication.manifest_digest:
                raise AdapterValidationError(
                    "manifest_bytes do not match the Publication Record digest."
                )
        object.__setattr__(self, "publication", publication)
        object.__setattr__(self, "registration", registration)
        object.__setattr__(self, "withdrawal", withdrawal)

    @property
    def adapter_key(self) -> AdapterKey:
        """Return the exact selection key for this verified context."""
        return adapter_key_from_core(self.publication, self.registration)

    @property
    def producer_module_id(self) -> str:
        return self.publication.work.module_id

    @property
    def publication_kind(self) -> PublicationKind:
        return self.publication.publication_kind

    @property
    def producer_contract_version(self) -> str | None:
        if self.registration is None:
            return None
        return self.registration.producer_contract_version

    @property
    def manifest_path(self) -> str:
        return self.publication.manifest_path

    @property
    def manifest_digest_algorithm(self) -> str:
        return self.publication.manifest_digest_algorithm

    @property
    def manifest_digest(self) -> str:
        return self.publication.manifest_digest


@runtime_checkable
class ProducerAdapter(Protocol):
    """Consumer-side adapter from verified producer bytes to evidence inventory."""

    @property
    def descriptor(self) -> AdapterDescriptor: ...

    def project(self, request: AdapterProjectionRequest) -> EvidenceInventory: ...


@runtime_checkable
class DistributionVersionResolver(Protocol):
    """Resolve one installed distribution version without importing its package."""

    def __call__(self, distribution_name: str) -> str: ...


def installed_distribution_version(distribution_name: str) -> str:
    """Return an installed distribution version using import metadata only."""
    return metadata.version(distribution_name)


def resolve_producer_reader_version(
    descriptor: AdapterDescriptor,
    resolver: DistributionVersionResolver = installed_distribution_version,
) -> str:
    """Require one exact installed reader version declared by the adapter."""
    if not isinstance(descriptor, AdapterDescriptor):
        raise AdapterValidationError("descriptor must be an AdapterDescriptor.")
    try:
        version = resolver(descriptor.producer_reader_distribution)
    except metadata.PackageNotFoundError as error:
        raise ProducerReaderUnavailableError(
            adapter_id=descriptor.adapter_id,
            distribution_name=descriptor.producer_reader_distribution,
        ) from error
    version = _single_line(version, "installed producer reader version")
    if version not in descriptor.supported_producer_reader_versions:
        raise ProducerReaderVersionUnsupportedError(
            adapter_id=descriptor.adapter_id,
            distribution_name=descriptor.producer_reader_distribution,
            installed_version=version,
            supported_versions=tuple(
                sorted(descriptor.supported_producer_reader_versions)
            ),
        )
    return version


def projection_identity_from_descriptor(
    descriptor: AdapterDescriptor,
    producer_reader_version: str,
) -> ProjectionIdentity:
    """Return the exact evidence projection identity for one reader version."""
    if not isinstance(descriptor, AdapterDescriptor):
        raise AdapterValidationError("descriptor must be an AdapterDescriptor.")
    version = _single_line(
        producer_reader_version, "producer_reader_version"
    )
    return ProjectionIdentity(
        projection_id=descriptor.adapter_id,
        projection_contract_version=descriptor.projection_contract_version,
        producer_reader_distribution=descriptor.producer_reader_distribution,
        producer_reader_version=version,
    )


def validate_projected_inventory(
    inventory: EvidenceInventory,
    request: AdapterProjectionRequest,
    descriptor: AdapterDescriptor,
    producer_reader_version: str,
) -> EvidenceInventory:
    """Require exact Core and projection provenance on every inventory item."""
    if not isinstance(inventory, EvidenceInventory):
        raise AdapterContractViolationError(
            "adapter project must return an EvidenceInventory.",
            adapter_id=(
                descriptor.adapter_id
                if isinstance(descriptor, AdapterDescriptor)
                else None
            ),
            publication_id=(
                request.publication.publication_id
                if isinstance(request, AdapterProjectionRequest)
                else None
            ),
        )
    if not isinstance(request, AdapterProjectionRequest):
        raise AdapterValidationError(
            "request must be an AdapterProjectionRequest."
        )
    expected_projection = projection_identity_from_descriptor(
        descriptor, producer_reader_version
    )
    for item in inventory.items:
        provenance = item.provenance
        if provenance.publication != request.publication:
            raise AdapterContractViolationError(
                "projected evidence uses a different Publication Record.",
                adapter_id=descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            )
        if provenance.registration != request.registration:
            raise AdapterContractViolationError(
                "projected evidence uses a different registration revision.",
                adapter_id=descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            )
        if provenance.withdrawal != request.withdrawal:
            raise AdapterContractViolationError(
                "projected evidence uses different withdrawal provenance.",
                adapter_id=descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            )
        if provenance.projection != expected_projection:
            raise AdapterContractViolationError(
                "projected evidence uses the wrong projection identity.",
                adapter_id=descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            )
    return inventory


def _validated_adapter(value: object) -> ProducerAdapter:
    if not isinstance(value, ProducerAdapter):
        raise AdapterRegistryError(
            "registry values must satisfy the ProducerAdapter protocol."
        )
    descriptor = value.descriptor
    if not isinstance(descriptor, AdapterDescriptor):
        raise AdapterRegistryError(
            "adapter descriptor must be an AdapterDescriptor."
        )
    if not callable(value.project):
        raise AdapterRegistryError("adapter project must be callable.")
    return value


@dataclass(frozen=True, slots=True)
class AdapterBinding:
    """One immutable captured descriptor and its adapter implementation."""

    descriptor: AdapterDescriptor
    adapter: ProducerAdapter

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, AdapterDescriptor):
            raise AdapterRegistryError("descriptor must be an AdapterDescriptor.")
        adapter = _validated_adapter(self.adapter)
        if adapter.descriptor != self.descriptor:
            raise AdapterRegistryError(
                "binding descriptor must equal the adapter descriptor."
            )


@dataclass(frozen=True, slots=True)
class AdapterMatch:
    """The exact adapter selected for one canonical publication context."""

    key: AdapterKey
    descriptor: AdapterDescriptor
    adapter: ProducerAdapter


@dataclass(frozen=True, slots=True, init=False)
class AdapterRegistry:
    """Immutable deterministic registry of exact producer adapter bindings."""

    _bindings: tuple[AdapterBinding, ...]

    def __init__(self, adapters: Iterable[ProducerAdapter] = ()) -> None:
        if isinstance(adapters, (str, bytes)):
            raise AdapterRegistryError("adapters must be an iterable.")
        try:
            raw = tuple(cast(Iterable[object], adapters))
        except TypeError as error:
            raise AdapterRegistryError("adapters must be iterable.") from error
        bindings: list[AdapterBinding] = []
        keys: set[AdapterKey] = set()
        identities: dict[
            str,
            tuple[
                str,
                str,
                str,
                frozenset[str],
                frozenset[PublicationCapability],
            ],
        ] = {}
        for value in raw:
            adapter = _validated_adapter(value)
            descriptor = adapter.descriptor
            key = descriptor.key
            if key in keys:
                raise DuplicateAdapterKeyError(key)
            keys.add(key)
            existing = identities.get(descriptor.adapter_id)
            if existing is not None and existing != descriptor.identity_signature:
                raise DuplicateAdapterIdentityError(descriptor.adapter_id)
            identities[descriptor.adapter_id] = descriptor.identity_signature
            bindings.append(AdapterBinding(descriptor=descriptor, adapter=adapter))
        ordered = tuple(
            sorted(
                bindings,
                key=lambda binding: (
                    binding.descriptor.key.sort_key,
                    binding.descriptor.adapter_id,
                ),
            )
        )
        object.__setattr__(self, "_bindings", ordered)

    @property
    def bindings(self) -> tuple[AdapterBinding, ...]:
        return self._bindings

    @property
    def adapters(self) -> tuple[ProducerAdapter, ...]:
        return tuple(binding.adapter for binding in self._bindings)

    @property
    def keys(self) -> tuple[AdapterKey, ...]:
        return tuple(binding.descriptor.key for binding in self._bindings)

    def get_exact(self, key: AdapterKey) -> AdapterBinding | None:
        """Return the binding for one exact key without fallback."""
        if not isinstance(key, AdapterKey):
            raise AdapterValidationError("key must be an AdapterKey.")
        return next(
            (
                binding
                for binding in self._bindings
                if binding.descriptor.key == key
            ),
            None,
        )

    def select(
        self,
        publication: PublicationRecord,
        registration: AcademicWorkRegistration | None,
    ) -> AdapterMatch:
        """Select exactly one adapter and verify its capability declaration."""
        checked_publication, checked_registration = _validated_core_context(
            publication, registration
        )
        key = adapter_key_from_core(checked_publication, checked_registration)
        binding = self.get_exact(key)
        if binding is None:
            raise AdapterNotFoundError(key, checked_publication.publication_id)
        current = _validated_adapter(binding.adapter).descriptor
        if current != binding.descriptor:
            raise AdapterContractViolationError(
                "adapter descriptor changed after registry construction.",
                adapter_id=binding.descriptor.adapter_id,
                publication_id=checked_publication.publication_id,
            )
        unsupported = tuple(
            sorted(
                set(checked_publication.capabilities)
                - set(binding.descriptor.supported_capabilities)
            )
        )
        if unsupported:
            raise AdapterCapabilityUnsupportedError(
                adapter_id=binding.descriptor.adapter_id,
                publication_id=checked_publication.publication_id,
                unsupported_capabilities=unsupported,
            )
        return AdapterMatch(
            key=key,
            descriptor=binding.descriptor,
            adapter=binding.adapter,
        )

    def invoke(
        self,
        request: AdapterProjectionRequest,
        resolver: DistributionVersionResolver = installed_distribution_version,
    ) -> EvidenceInventory:
        """Select, check reader availability, project, and enforce the contract."""
        if not isinstance(request, AdapterProjectionRequest):
            raise AdapterValidationError(
                "request must be an AdapterProjectionRequest."
            )
        match = self.select(request.publication, request.registration)
        reader_version = resolve_producer_reader_version(match.descriptor, resolver)
        try:
            inventory = match.adapter.project(request)
        except AdapterProjectionError:
            raise
        except Exception as error:
            raise AdapterProjectionError(
                "The selected adapter failed while projecting producer evidence.",
                adapter_id=match.descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            ) from error
        if not isinstance(inventory, EvidenceInventory):
            raise AdapterContractViolationError(
                "adapter project must return an EvidenceInventory.",
                adapter_id=match.descriptor.adapter_id,
                publication_id=request.publication.publication_id,
            )
        return validate_projected_inventory(
            inventory,
            request,
            match.descriptor,
            reader_version,
        )

    @staticmethod
    def _validate_inventory(
        *,
        inventory: EvidenceInventory,
        request: AdapterProjectionRequest,
        descriptor: AdapterDescriptor,
        reader_version: str,
    ) -> None:
        expected_projection = ProjectionIdentity(
            projection_id=descriptor.adapter_id,
            projection_contract_version=descriptor.projection_contract_version,
            producer_reader_distribution=descriptor.producer_reader_distribution,
            producer_reader_version=reader_version,
        )
        for item in inventory.items:
            provenance = item.provenance
            if provenance.publication != request.publication:
                raise AdapterContractViolationError(
                    "projected evidence uses a different Publication Record.",
                    adapter_id=descriptor.adapter_id,
                    publication_id=request.publication.publication_id,
                )
            if provenance.registration != request.registration:
                raise AdapterContractViolationError(
                    "projected evidence uses a different registration revision.",
                    adapter_id=descriptor.adapter_id,
                    publication_id=request.publication.publication_id,
                )
            if provenance.withdrawal != request.withdrawal:
                raise AdapterContractViolationError(
                    "projected evidence uses different withdrawal provenance.",
                    adapter_id=descriptor.adapter_id,
                    publication_id=request.publication.publication_id,
                )
            if provenance.projection != expected_projection:
                raise AdapterContractViolationError(
                    "projected evidence uses the wrong projection identity.",
                    adapter_id=descriptor.adapter_id,
                    publication_id=request.publication.publication_id,
                )
