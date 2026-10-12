from __future__ import annotations

import pytest
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationReaderSupport,
)

from meridian.adapters import (
    AdapterDescriptor,
    AdapterValidationError,
    ProducerReaderContractIdentity,
    ProducerReaderContractUnsupportedError,
    ProducerReaderRuntimeIdentity,
    projection_identity_from_descriptor,
    resolve_producer_reader_compatibility,
    resolve_producer_reader_version,
)
from meridian.concord_adapter import CONCORD_ADAPTER_DESCRIPTOR
from meridian.quillan_adapter import QUILLAN_ADAPTER_DESCRIPTOR
from meridian.scoreform_adapter import SCOREFORM_ADAPTER_DESCRIPTOR

BUILTINS = (
    (
        SCOREFORM_ADAPTER_DESCRIPTOR,
        "scoreform_academic_result_reader_v1",
        "0.13.0",
    ),
    (
        QUILLAN_ADAPTER_DESCRIPTOR,
        "quillan_academic_result_reader_v1",
        "0.10.6",
    ),
    (
        CONCORD_ADAPTER_DESCRIPTOR,
        "concord_academic_result_reader_v1",
        "0.3.2",
    ),
)


def _profile(
    descriptor: AdapterDescriptor,
    *,
    reader_contract: str | None,
    distribution_name: str | None = None,
) -> PublicationProducerProfile:
    reader_support = (
        ()
        if reader_contract is None
        else (
            PublicationReaderSupport(
                manifest_contract_version=(
                    descriptor.key.manifest_contract_version
                ),
                distribution_name=(
                    descriptor.producer_reader_distribution
                    if distribution_name is None
                    else distribution_name
                ),
                reader_contract_version=reader_contract,
            ),
        )
    )
    academic_work_versions = (
        frozenset()
        if descriptor.key.producer_contract_version is None
        else frozenset({descriptor.key.producer_contract_version})
    )
    return PublicationProducerProfile(
        module_id=descriptor.key.producer_module_id,
        display_name="Synthetic Contract Producer",
        supported_core_publication_schema_versions=frozenset({"1"}),
        supported_academic_work_contract_versions=academic_work_versions,
        publication_contracts=(
            PublicationContractSupport(
                publication_kind=descriptor.key.publication_kind,
                manifest_contract_versions=frozenset(
                    {descriptor.key.manifest_contract_version}
                ),
                supported_capabilities=descriptor.supported_capabilities,
                reader_support=reader_support,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("descriptor", "reader_contract", "released_version"),
    BUILTINS,
)
def test_released_contract_advertising_versions_are_supported_by_contract(
    descriptor: AdapterDescriptor,
    reader_contract: str,
    released_version: str,
) -> None:
    profile = _profile(descriptor, reader_contract=reader_contract)

    result = resolve_producer_reader_compatibility(
        profile,
        descriptor,
        lambda _distribution: released_version,
    )

    assert result.mode == "contract"
    assert result.support_state == "supported"
    assert result.reason_code == "reader.contract_supported"
    assert result.runtime_identity == ProducerReaderRuntimeIdentity(
        distribution_name=descriptor.producer_reader_distribution,
        installed_distribution_version=released_version,
    )
    assert result.contract_identity == ProducerReaderContractIdentity(
        manifest_contract_version=descriptor.key.manifest_contract_version,
        reader_contract_version=reader_contract,
    )
    assert released_version not in descriptor.legacy_exact_reader_versions


@pytest.mark.parametrize(
    ("descriptor", "reader_contract", "_released_version"),
    BUILTINS,
)
def test_same_supported_contract_accepts_different_package_versions(
    descriptor: AdapterDescriptor,
    reader_contract: str,
    _released_version: str,
) -> None:
    profile = _profile(descriptor, reader_contract=reader_contract)

    first = resolve_producer_reader_version(
        descriptor,
        lambda _distribution: "100.0.1",
        producer_profile=profile,
    )
    second = resolve_producer_reader_version(
        descriptor,
        lambda _distribution: "100.0.2",
        producer_profile=profile,
    )

    assert first == "100.0.1"
    assert second == "100.0.2"

    first_projection = projection_identity_from_descriptor(descriptor, first)
    second_projection = projection_identity_from_descriptor(descriptor, second)
    assert first_projection != second_projection
    assert first_projection.producer_reader_version == "100.0.1"
    assert second_projection.producer_reader_version == "100.0.2"


def test_explicit_unsupported_contract_wins_over_legacy_exact_version() -> None:
    descriptor = SCOREFORM_ADAPTER_DESCRIPTOR
    profile = _profile(
        descriptor,
        reader_contract="scoreform_academic_result_reader_v2",
    )
    called = False

    def resolver(_: str) -> str:
        nonlocal called
        called = True
        return "0.12.1"

    result = resolve_producer_reader_compatibility(
        profile,
        descriptor,
        resolver,
    )

    assert result.mode == "unsupported"
    assert result.reason_code == "reader.contract_unsupported"
    assert result.runtime_identity is None
    assert result.contract_identity == ProducerReaderContractIdentity(
        manifest_contract_version="scoreform_academic_result_manifest_v1",
        reader_contract_version="scoreform_academic_result_reader_v2",
    )
    assert called is False

    with pytest.raises(ProducerReaderContractUnsupportedError):
        resolve_producer_reader_version(
            descriptor,
            resolver,
            producer_profile=profile,
        )
    assert called is False


def test_explicit_distribution_mismatch_fails_closed_without_legacy_fallback() -> None:
    descriptor = SCOREFORM_ADAPTER_DESCRIPTOR
    profile = _profile(
        descriptor,
        reader_contract="scoreform_academic_result_reader_v1",
        distribution_name="other-scoreform-reader",
    )
    called = False

    def resolver(_: str) -> str:
        nonlocal called
        called = True
        return "0.12.1"

    result = resolve_producer_reader_compatibility(
        profile,
        descriptor,
        resolver,
    )

    assert result.mode == "unsupported"
    assert result.reason_code == "reader.contract_unsupported"
    assert called is False


def test_invalid_explicit_reader_metadata_fails_closed() -> None:
    descriptor = SCOREFORM_ADAPTER_DESCRIPTOR
    profile = _profile(
        descriptor,
        reader_contract="scoreform_academic_result_reader_v1",
    )
    support = profile.publication_contracts[0]
    object.__setattr__(support, "reader_support", ("invalid",))

    result = resolve_producer_reader_compatibility(
        profile,
        descriptor,
        lambda _distribution: "0.12.1",
    )

    assert result.mode == "unsupported"
    assert result.reason_code == "reader.metadata_invalid"

    with pytest.raises(
        AdapterValidationError,
        match="reader metadata is invalid",
    ):
        resolve_producer_reader_version(
            descriptor,
            lambda _distribution: "0.12.1",
            producer_profile=profile,
        )


def test_contract_unavailable_retains_declared_contract_identity() -> None:
    from importlib import metadata

    descriptor = SCOREFORM_ADAPTER_DESCRIPTOR
    profile = _profile(
        descriptor,
        reader_contract="scoreform_academic_result_reader_v1",
    )

    def unavailable(distribution_name: str) -> str:
        raise metadata.PackageNotFoundError(distribution_name)

    result = resolve_producer_reader_compatibility(
        profile,
        descriptor,
        unavailable,
    )

    assert result.mode == "unavailable"
    assert result.runtime_identity is None
    assert result.contract_identity == ProducerReaderContractIdentity(
        manifest_contract_version="scoreform_academic_result_manifest_v1",
        reader_contract_version="scoreform_academic_result_reader_v1",
    )
