from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from importlib import metadata
from typing import Callable, cast

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from meridian.adapters import (
    MERIDIAN_ADAPTER_INTERFACE_VERSION,
    AdapterCapabilityUnsupportedError,
    AdapterContractViolationError,
    AdapterDescriptor,
    AdapterKey,
    AdapterNotFoundError,
    AdapterProjectionError,
    AdapterProjectionRequest,
    AdapterRegistry,
    AdapterValidationError,
    DuplicateAdapterIdentityError,
    DuplicateAdapterKeyError,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
    adapter_key_from_core,
    resolve_producer_reader_version,
)
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    ProjectionIdentity,
    StudentSubject,
)

MANIFEST_BYTES = b'{"schema_version":"synthetic_manifest_1"}'
NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def registration(
    *,
    module_id: str = "synthetic_producer",
    producer_contract_version: str = "producer_contract_1",
    revision: int = 1,
) -> AcademicWorkRegistration:
    work = ModuleWorkRef(
        module_id=module_id,
        class_id="synthetic_class_2026",
        work_id="synthetic_work_alpha",
    )
    return AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=work,
        registration_revision=revision,
        producer_contract_version=producer_contract_version,
        title="Synthetic Work Alpha",
        work_kind="assignment",
        academic_intent="formative",
        lifecycle="active",
        created_at=NOW,
        updated_at=NOW,
        source_records=(
            ModuleRecordRef(
                module_id=module_id,
                record_kind="assignment",
                record_id="synthetic_work_alpha",
                contract_version=producer_contract_version,
            ),
        ),
    )


def publication(
    *,
    module_id: str = "synthetic_producer",
    publication_kind: str = "academic_result_set",
    manifest_contract_version: str = "manifest_contract_1",
    registration_revision: int | None = 1,
    source_kind: str | None = "assignment",
    source_version: str | None = "producer_contract_1",
    capabilities: tuple[str, ...] = ("points",),
    publication_id: str = "pub_11111111111111111111111111111111",
    manifest_bytes: bytes = MANIFEST_BYTES,
) -> PublicationRecord:
    work = ModuleWorkRef(
        module_id=module_id,
        class_id="synthetic_class_2026",
        work_id="synthetic_work_alpha",
    )
    source = None
    if source_kind is not None:
        source = ModuleRecordRef(
            module_id=module_id,
            record_kind=source_kind,
            record_id="synthetic_work_alpha",
            contract_version=source_version,
        )
    return PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id=publication_id,
        work=work,
        source_record=source,
        publication_kind=cast(object, publication_kind),
        capabilities=cast(object, capabilities),
        record_set_id="synthetic_record_set",
        record_set_revision=1,
        manifest_contract_version=manifest_contract_version,
        manifest_path=(
            "classes/synthetic_class_2026/modules/"
            f"{module_id}/work/synthetic_work_alpha/publications/"
            "synthetic_record_set/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
        published_at=NOW,
        academic_work_registration_revision=registration_revision,
        supersedes_publication_id=None,
    )


def withdrawal(
    publication_id: str = "pub_11111111111111111111111111111111",
) -> PublicationWithdrawal:
    return PublicationWithdrawal(
        schema_version="1",
        record_type="publication_withdrawal",
        publication_id=publication_id,
        withdrawn_at=NOW,
        reason="synthetic correction",
    )


def descriptor(
    *,
    key: AdapterKey | None = None,
    adapter_id: str = "synthetic.points",
    projection_contract_version: str = "projection_1",
    capabilities: frozenset[str] = frozenset({"points"}),
    reader_distribution: str = "synthetic-reader",
    reader_versions: frozenset[str] = frozenset({"1.0.0"}),
    interface_version: str = MERIDIAN_ADAPTER_INTERFACE_VERSION,
) -> AdapterDescriptor:
    if key is None:
        key = adapter_key_from_core(publication(), registration())
    return AdapterDescriptor(
        adapter_id=adapter_id,
        key=key,
        projection_contract_version=projection_contract_version,
        supported_capabilities=cast(object, capabilities),
        producer_reader_distribution=reader_distribution,
        supported_producer_reader_versions=reader_versions,
        adapter_interface_version=interface_version,
    )


def evidence_inventory(
    request: AdapterProjectionRequest,
    adapter_descriptor: AdapterDescriptor,
    *,
    reader_version: str = "1.0.0",
    publication_override: PublicationRecord | None = None,
    registration_override: AcademicWorkRegistration | None | object = ...,
    withdrawal_override: PublicationWithdrawal | None | object = ...,
    projection_override: ProjectionIdentity | None = None,
) -> EvidenceInventory:
    registration_value = (
        request.registration
        if registration_override is ...
        else cast(AcademicWorkRegistration | None, registration_override)
    )
    withdrawal_value = (
        request.withdrawal
        if withdrawal_override is ...
        else cast(PublicationWithdrawal | None, withdrawal_override)
    )
    projection = projection_override or ProjectionIdentity(
        projection_id=adapter_descriptor.adapter_id,
        projection_contract_version=adapter_descriptor.projection_contract_version,
        producer_reader_distribution=adapter_descriptor.producer_reader_distribution,
        producer_reader_version=reader_version,
    )
    provenance = EvidenceProvenance(
        publication=publication_override or request.publication,
        registration=registration_value,
        withdrawal=withdrawal_value,
        projection=projection,
        native=NativeProvenance(
            references=(NativeReference(kind="attempt", identifier="attempt_1"),)
        ),
    )
    return EvidenceInventory(
        (
            EvidenceItem(
                item_id="synthetic_item_1",
                subject=StudentSubject("student_001"),
                target=EvidenceTarget("attempt", target_id="attempt_1"),
                result_kind="attempt_points",
                value=NativePointValue(earned=4, possible=5),
                provenance=provenance,
            ),
        )
    )


class SyntheticAdapter:
    def __init__(
        self,
        adapter_descriptor: AdapterDescriptor,
        project: Callable[[AdapterProjectionRequest], EvidenceInventory] | None = None,
    ) -> None:
        self._descriptor = adapter_descriptor
        self.calls = 0
        self._project = project

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def project(self, request: AdapterProjectionRequest) -> EvidenceInventory:
        self.calls += 1
        if self._project is None:
            return evidence_inventory(request, self.descriptor)
        return self._project(request)


def request(*, include_withdrawal: bool = False) -> AdapterProjectionRequest:
    return AdapterProjectionRequest(
        publication=publication(),
        registration=registration(),
        withdrawal=withdrawal() if include_withdrawal else None,
        manifest_bytes=MANIFEST_BYTES,
    )


def test_adapter_interface_version_is_explicit() -> None:
    assert MERIDIAN_ADAPTER_INTERFACE_VERSION == "1"


def test_academic_key_is_derived_from_exact_core_records() -> None:
    key = adapter_key_from_core(publication(), registration())
    assert key == AdapterKey(
        producer_module_id="synthetic_producer",
        publication_kind="academic_result_set",
        manifest_contract_version="manifest_contract_1",
        producer_contract_version="producer_contract_1",
        source_record_kind="assignment",
        source_record_contract_version="producer_contract_1",
    )


def test_intervention_key_has_no_registration_or_producer_contract() -> None:
    record = publication(
        publication_kind="intervention_record_set",
        registration_revision=None,
        source_kind="intervention_plan",
        source_version="intervention_contract_1",
        capabilities=("intervention_status",),
    )
    key = adapter_key_from_core(record, None)
    assert key.producer_contract_version is None
    assert key.source_record_kind == "intervention_plan"
    assert key.source_record_contract_version == "intervention_contract_1"


def test_missing_source_record_differs_from_unversioned_source_record() -> None:
    missing = adapter_key_from_core(
        publication(source_kind=None, source_version=None), registration()
    )
    unversioned = adapter_key_from_core(
        publication(source_kind="assignment", source_version=None), registration()
    )
    assert missing != unversioned
    assert missing.source_record_kind is None
    assert unversioned.source_record_kind == "assignment"
    assert unversioned.source_record_contract_version is None


@pytest.mark.parametrize(
    ("record", "registration_value", "message"),
    [
        (publication(), None, "require"),
        (
            publication(
                publication_kind="intervention_record_set",
                registration_revision=None,
                capabilities=("intervention_status",),
            ),
            registration(),
            "must not",
        ),
        (publication(registration_revision=2), registration(), "revision"),
        (publication(module_id="other_producer"), registration(), "work"),
    ],
)
def test_invalid_core_context_fails(
    record: PublicationRecord,
    registration_value: AcademicWorkRegistration | None,
    message: str,
) -> None:
    with pytest.raises(AdapterValidationError, match=message):
        adapter_key_from_core(record, registration_value)


def test_adapter_key_rejects_intervention_producer_contract() -> None:
    with pytest.raises(AdapterValidationError, match="must not"):
        AdapterKey(
            producer_module_id="synthetic_producer",
            publication_kind="intervention_record_set",
            manifest_contract_version="manifest_contract_1",
            producer_contract_version="producer_contract_1",
            source_record_kind=None,
            source_record_contract_version=None,
        )


def test_descriptor_rejects_unsupported_interface_version() -> None:
    with pytest.raises(AdapterValidationError, match="unsupported"):
        descriptor(interface_version="2")


def test_projection_request_hides_bytes_and_checks_digest() -> None:
    projection_request = request()
    assert "manifest_bytes" not in repr(projection_request)
    with pytest.raises(AdapterValidationError, match="digest"):
        AdapterProjectionRequest(
            publication=publication(),
            registration=registration(),
            withdrawal=None,
            manifest_bytes=b"different",
        )


def test_projection_request_rejects_mutable_bytes() -> None:
    with pytest.raises(AdapterValidationError, match="immutable bytes"):
        AdapterProjectionRequest(
            publication=publication(),
            registration=registration(),
            withdrawal=None,
            manifest_bytes=cast(bytes, bytearray(MANIFEST_BYTES)),
        )


def test_empty_registry_is_valid_and_immutable() -> None:
    registry = AdapterRegistry()
    assert registry.adapters == ()
    assert registry.keys == ()
    with pytest.raises(FrozenInstanceError):
        registry._bindings = ()  # type: ignore[misc]


def test_registry_copies_and_deterministically_sorts_input() -> None:
    key_a = adapter_key_from_core(
        publication(manifest_contract_version="manifest_a"), registration()
    )
    key_b = adapter_key_from_core(
        publication(manifest_contract_version="manifest_b"), registration()
    )
    adapters = [
        SyntheticAdapter(descriptor(key=key_b, adapter_id="synthetic.b")),
        SyntheticAdapter(descriptor(key=key_a, adapter_id="synthetic.a")),
    ]
    registry = AdapterRegistry(adapters)
    adapters.clear()
    assert tuple(key.manifest_contract_version for key in registry.keys) == (
        "manifest_a",
        "manifest_b",
    )


def test_duplicate_exact_key_fails() -> None:
    first = SyntheticAdapter(descriptor(adapter_id="synthetic.first"))
    second = SyntheticAdapter(descriptor(adapter_id="synthetic.second"))
    with pytest.raises(DuplicateAdapterKeyError) as raised:
        AdapterRegistry((first, second))
    assert raised.value.code == "adapters.duplicate_key"


def test_conflicting_adapter_identity_fails() -> None:
    key_a = adapter_key_from_core(
        publication(manifest_contract_version="manifest_a"), registration()
    )
    key_b = adapter_key_from_core(
        publication(manifest_contract_version="manifest_b"), registration()
    )
    first = SyntheticAdapter(descriptor(key=key_a, adapter_id="synthetic.shared"))
    second = SyntheticAdapter(
        descriptor(
            key=key_b,
            adapter_id="synthetic.shared",
            projection_contract_version="projection_2",
        )
    )
    with pytest.raises(DuplicateAdapterIdentityError) as raised:
        AdapterRegistry((first, second))
    assert raised.value.code == "adapters.duplicate_identity"


def test_same_adapter_identity_can_bind_multiple_exact_keys() -> None:
    key_a = adapter_key_from_core(
        publication(manifest_contract_version="manifest_a"), registration()
    )
    key_b = adapter_key_from_core(
        publication(manifest_contract_version="manifest_b"), registration()
    )
    registry = AdapterRegistry(
        (
            SyntheticAdapter(descriptor(key=key_a, adapter_id="synthetic.shared")),
            SyntheticAdapter(descriptor(key=key_b, adapter_id="synthetic.shared")),
        )
    )
    assert len(registry.bindings) == 2


def test_selection_is_exact_without_nearest_or_producer_fallback() -> None:
    adapter = SyntheticAdapter(descriptor())
    registry = AdapterRegistry((adapter,))
    changed = publication(manifest_contract_version="manifest_contract_2")
    with pytest.raises(AdapterNotFoundError) as raised:
        registry.select(changed, registration())
    assert raised.value.code == "adapters.not_found"
    assert adapter.calls == 0


def test_source_record_version_requires_exact_match() -> None:
    adapter = SyntheticAdapter(descriptor())
    registry = AdapterRegistry((adapter,))
    changed = publication(source_version="producer_contract_2")
    with pytest.raises(AdapterNotFoundError):
        registry.select(changed, registration())


def test_capability_failure_is_distinct_from_missing_adapter() -> None:
    adapter = SyntheticAdapter(descriptor(capabilities=frozenset({"points"})))
    registry = AdapterRegistry((adapter,))
    record = publication(capabilities=("points", "question_evidence"))
    with pytest.raises(AdapterCapabilityUnsupportedError) as raised:
        registry.select(record, registration())
    assert raised.value.code == "adapters.capability_unsupported"
    assert raised.value.unsupported_capabilities == ("question_evidence",)


def test_reader_resolution_accepts_only_exact_declared_version() -> None:
    selected = descriptor(reader_versions=frozenset({"1.0.0", "1.0.1"}))
    assert resolve_producer_reader_version(selected, lambda _: "1.0.1") == "1.0.1"
    with pytest.raises(ProducerReaderVersionUnsupportedError) as raised:
        resolve_producer_reader_version(selected, lambda _: "1.0.2")
    assert raised.value.code == "adapters.reader_version_unsupported"


def test_reader_unavailable_is_explicit() -> None:
    def missing(_: str) -> str:
        raise metadata.PackageNotFoundError("synthetic-reader")

    with pytest.raises(ProducerReaderUnavailableError) as raised:
        resolve_producer_reader_version(descriptor(), missing)
    assert raised.value.code == "adapters.reader_unavailable"


def test_selection_does_not_resolve_or_invoke_reader() -> None:
    adapter = SyntheticAdapter(descriptor())
    registry = AdapterRegistry((adapter,))
    match = registry.select(publication(), registration())
    assert match.adapter is adapter
    assert adapter.calls == 0


def test_conforming_projection_is_returned() -> None:
    adapter = SyntheticAdapter(descriptor())
    registry = AdapterRegistry((adapter,))
    inventory = registry.invoke(request(), lambda _: "1.0.0")
    assert len(inventory.items) == 1
    assert adapter.calls == 1


def test_empty_inventory_is_valid() -> None:
    adapter = SyntheticAdapter(
        descriptor(),
        project=lambda _: EvidenceInventory(()),
    )
    assert AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0").items == ()


def test_wrong_return_type_is_contract_violation() -> None:
    adapter = SyntheticAdapter(
        descriptor(),
        project=cast(
            Callable[[AdapterProjectionRequest], EvidenceInventory],
            lambda _: object(),
        ),
    )
    with pytest.raises(AdapterContractViolationError) as raised:
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")
    assert raised.value.code == "adapters.projection_contract_violation"


def test_wrong_publication_provenance_is_rejected() -> None:
    def project(projection_request: AdapterProjectionRequest) -> EvidenceInventory:
        return evidence_inventory(
            projection_request,
            descriptor(),
            publication_override=publication(
                publication_id="pub_22222222222222222222222222222222"
            ),
        )

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterContractViolationError, match="Publication"):
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")


def test_wrong_registration_provenance_is_rejected() -> None:
    def project(projection_request: AdapterProjectionRequest) -> EvidenceInventory:
        return evidence_inventory(
            projection_request,
            descriptor(),
            registration_override=registration(
                producer_contract_version="producer_contract_2", revision=1
            ),
        )

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterContractViolationError, match="registration"):
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")


def test_wrong_withdrawal_provenance_is_rejected() -> None:
    projection_request = request(include_withdrawal=True)

    def project(value: AdapterProjectionRequest) -> EvidenceInventory:
        return evidence_inventory(value, descriptor(), withdrawal_override=None)

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterContractViolationError, match="withdrawal"):
        AdapterRegistry((adapter,)).invoke(projection_request, lambda _: "1.0.0")


def test_wrong_projection_identity_is_rejected() -> None:
    def project(projection_request: AdapterProjectionRequest) -> EvidenceInventory:
        wrong = ProjectionIdentity(
            projection_id="synthetic.other",
            projection_contract_version="projection_1",
            producer_reader_distribution="synthetic-reader",
            producer_reader_version="1.0.0",
        )
        return evidence_inventory(
            projection_request,
            descriptor(),
            projection_override=wrong,
        )

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterContractViolationError, match="projection identity"):
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")


def test_controlled_projection_failure_is_preserved() -> None:
    def project(_: AdapterProjectionRequest) -> EvidenceInventory:
        raise AdapterProjectionError(
            "Synthetic producer validation failed.",
            adapter_id="synthetic.points",
        )

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterProjectionError, match="Synthetic") as raised:
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")
    assert raised.value.code == "adapters.projection_failed"


def test_unexpected_failure_is_wrapped_without_manifest_bytes() -> None:
    def project(_: AdapterProjectionRequest) -> EvidenceInventory:
        raise RuntimeError(MANIFEST_BYTES.decode())

    adapter = SyntheticAdapter(descriptor(), project)
    with pytest.raises(AdapterProjectionError) as raised:
        AdapterRegistry((adapter,)).invoke(request(), lambda _: "1.0.0")
    assert MANIFEST_BYTES.decode() not in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_descriptor_mutation_after_registration_is_rejected() -> None:
    adapter = SyntheticAdapter(descriptor())
    registry = AdapterRegistry((adapter,))
    adapter._descriptor = descriptor(projection_contract_version="projection_2")
    with pytest.raises(AdapterContractViolationError, match="changed"):
        registry.select(publication(), registration())
