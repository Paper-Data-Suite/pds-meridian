from __future__ import annotations

from importlib import metadata

import pytest

from meridian.adapters import (
    AdapterValidationError,
    ProducerReaderCompatibility,
    ProducerReaderContractIdentity,
    ProducerReaderRuntimeIdentity,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
    resolve_legacy_producer_reader_compatibility,
    resolve_producer_reader_version,
)
from meridian.concord_adapter import CONCORD_ADAPTER_DESCRIPTOR
from meridian.quillan_adapter import QUILLAN_ADAPTER_DESCRIPTOR
from meridian.scoreform_adapter import SCOREFORM_ADAPTER_DESCRIPTOR

BUILTINS = (
    (
        SCOREFORM_ADAPTER_DESCRIPTOR,
        "scoreform_academic_result_reader_v1",
        "0.12.1",
        "0.13.0",
    ),
    (
        QUILLAN_ADAPTER_DESCRIPTOR,
        "quillan_academic_result_reader_v1",
        "0.10.5",
        "0.10.6",
    ),
    (
        CONCORD_ADAPTER_DESCRIPTOR,
        "concord_academic_result_reader_v1",
        "0.3.0",
        "0.3.2",
    ),
)


@pytest.mark.parametrize(
    ("descriptor", "reader_contract", "legacy_version", "_released_version"),
    BUILTINS,
)
def test_slice3_descriptors_separate_contract_and_legacy_identity(
    descriptor,
    reader_contract: str,
    legacy_version: str,
    _released_version: str,
) -> None:
    assert descriptor.supported_producer_reader_contracts == frozenset(
        {reader_contract}
    )
    assert descriptor.legacy_exact_reader_versions == frozenset({legacy_version})
    assert descriptor.supported_producer_reader_versions == (
        descriptor.legacy_exact_reader_versions
    )


def test_slice3_runtime_and_contract_identity_are_distinct_models() -> None:
    runtime = ProducerReaderRuntimeIdentity(
        distribution_name="scoreform",
        installed_distribution_version="0.13.0",
    )
    contract = ProducerReaderContractIdentity(
        manifest_contract_version="scoreform_academic_result_manifest_v1",
        reader_contract_version="scoreform_academic_result_reader_v1",
    )
    assert runtime.installed_distribution_version == "0.13.0"
    assert contract.reader_contract_version == (
        "scoreform_academic_result_reader_v1"
    )


@pytest.mark.parametrize(
    ("descriptor", "_reader_contract", "legacy_version", "_released_version"),
    BUILTINS,
)
def test_slice3_bounded_legacy_versions_resolve_as_legacy_exact(
    descriptor,
    _reader_contract: str,
    legacy_version: str,
    _released_version: str,
) -> None:
    result = resolve_legacy_producer_reader_compatibility(
        descriptor,
        lambda _distribution: legacy_version,
    )
    assert result == ProducerReaderCompatibility(
        mode="legacy_exact",
        support_state="supported",
        reason_code="reader.metadata_absent_legacy_exact_supported",
        runtime_identity=ProducerReaderRuntimeIdentity(
            distribution_name=descriptor.producer_reader_distribution,
            installed_distribution_version=legacy_version,
        ),
    )
    assert result.contract_identity is None
    assert resolve_producer_reader_version(
        descriptor,
        lambda _distribution: legacy_version,
    ) == legacy_version


@pytest.mark.parametrize(
    ("descriptor", "_reader_contract", "_legacy_version", "released_version"),
    BUILTINS,
)
def test_slice3_contract_advertising_releases_are_not_accepted_early(
    descriptor,
    _reader_contract: str,
    _legacy_version: str,
    released_version: str,
) -> None:
    result = resolve_legacy_producer_reader_compatibility(
        descriptor,
        lambda _distribution: released_version,
    )
    assert result.mode == "unsupported"
    assert result.support_state == "unsupported"
    assert result.reason_code == (
        "reader.metadata_absent_legacy_exact_unsupported"
    )
    assert result.contract_identity is None
    with pytest.raises(ProducerReaderVersionUnsupportedError):
        resolve_producer_reader_version(
            descriptor,
            lambda _distribution: released_version,
        )


@pytest.mark.parametrize(
    ("descriptor", "unknown_version"),
    (
        (SCOREFORM_ADAPTER_DESCRIPTOR, "0.12.2"),
        (QUILLAN_ADAPTER_DESCRIPTOR, "0.10.4"),
        (CONCORD_ADAPTER_DESCRIPTOR, "0.3.1"),
    ),
)
def test_slice3_nearby_versions_are_not_inferred(
    descriptor,
    unknown_version: str,
) -> None:
    result = resolve_legacy_producer_reader_compatibility(
        descriptor,
        lambda _distribution: unknown_version,
    )
    assert result.mode == "unsupported"
    assert result.reason_code == (
        "reader.metadata_absent_legacy_exact_unsupported"
    )


def test_slice3_unavailable_distribution_has_stable_result_and_old_exception() -> None:
    def missing(distribution_name: str) -> str:
        raise metadata.PackageNotFoundError(distribution_name)

    result = resolve_legacy_producer_reader_compatibility(
        SCOREFORM_ADAPTER_DESCRIPTOR,
        missing,
    )
    assert result == ProducerReaderCompatibility(
        mode="unavailable",
        support_state="unavailable",
        reason_code="reader.distribution_unavailable",
    )
    with pytest.raises(ProducerReaderUnavailableError):
        resolve_producer_reader_version(
            SCOREFORM_ADAPTER_DESCRIPTOR,
            missing,
        )


def test_slice3_model_rejects_incoherent_legacy_result() -> None:
    with pytest.raises(AdapterValidationError, match="legacy_exact compatibility"):
        ProducerReaderCompatibility(
            mode="legacy_exact",
            support_state="supported",
            reason_code="reader.metadata_absent_legacy_exact_supported",
        )
