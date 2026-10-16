from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationReaderSupport,
)

from meridian.adapters import (
    AdapterValidationError,
    ProducerReaderVersionUnsupportedError,
    declared_reader_support_for_descriptor,
    resolve_producer_reader_version,
)
from meridian.scoreform_adapter import SCOREFORM_ADAPTER_DESCRIPTOR
from scripts.verify_core_wheel import (
    EXPECTED_CORE_VERSION,
    EXPECTED_CORE_WHEEL_FILENAME,
    EXPECTED_CORE_WHEEL_SHA256,
)

ROOT = Path(__file__).resolve().parents[1]


def _scoreform_profile(
    *, reader: bool, module_id: str = "scoreform"
) -> PublicationProducerProfile:
    reader_support = (
        (
            PublicationReaderSupport(
                manifest_contract_version="scoreform_academic_result_manifest_v1",
                distribution_name="scoreform",
                reader_contract_version="scoreform_academic_result_reader_v1",
            ),
        )
        if reader
        else ()
    )
    return PublicationProducerProfile(
        module_id=module_id,
        display_name="Synthetic ScoreForm",
        supported_core_publication_schema_versions=frozenset({"1"}),
        supported_academic_work_contract_versions=frozenset(
            {"scoreform_academic_work_v1"}
        ),
        publication_contracts=(
            PublicationContractSupport(
                publication_kind="academic_result_set",
                manifest_contract_versions=frozenset(
                    {"scoreform_academic_result_manifest_v1"}
                ),
                supported_capabilities=frozenset(
                    {"points", "question_evidence", "multiple_attempts"}
                ),
                reader_support=reader_support,
            ),
        ),
    )


def test_issue111_slice2_uses_released_core_065_as_active_floor() -> None:
    with (ROOT / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]

    assert project["dependencies"] == ["pds-core>=0.6.5,<0.7"]
    assert EXPECTED_CORE_VERSION == "0.6.6"
    assert EXPECTED_CORE_WHEEL_FILENAME == "pds_core-0.6.6-py3-none-any.whl"
    assert EXPECTED_CORE_WHEEL_SHA256 == (
        "d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301"
    )


def test_issue111_slice2_observes_exact_core_reader_metadata() -> None:
    support = declared_reader_support_for_descriptor(
        _scoreform_profile(reader=True),
        SCOREFORM_ADAPTER_DESCRIPTOR,
    )

    assert support == PublicationReaderSupport(
        manifest_contract_version="scoreform_academic_result_manifest_v1",
        distribution_name="scoreform",
        reader_contract_version="scoreform_academic_result_reader_v1",
    )


def test_issue111_slice2_preserves_absent_metadata_as_absent() -> None:
    assert (
        declared_reader_support_for_descriptor(
            _scoreform_profile(reader=False),
            SCOREFORM_ADAPTER_DESCRIPTOR,
        )
        is None
    )


def test_issue111_slice2_rejects_profile_module_mismatch() -> None:
    with pytest.raises(
        AdapterValidationError,
        match="profile module_id does not match",
    ):
        declared_reader_support_for_descriptor(
            _scoreform_profile(reader=True, module_id="otherproducer"),
            SCOREFORM_ADAPTER_DESCRIPTOR,
        )


def test_issue111_slice2_does_not_broaden_runtime_reader_acceptance_yet() -> None:
    with pytest.raises(ProducerReaderVersionUnsupportedError):
        resolve_producer_reader_version(
            SCOREFORM_ADAPTER_DESCRIPTOR,
            resolver=lambda _distribution: "0.13.0",
        )

    assert SCOREFORM_ADAPTER_DESCRIPTOR.legacy_exact_reader_versions == (
        frozenset({"0.12.1"})
    )


def test_issue111_slice2_current_environment_exposes_core_reader_api() -> None:
    assert metadata.version("pds-core") == "0.6.6"

    document = (
        ROOT / "docs/architecture/producer-reader-contract-compatibility.md"
    ).read_text(encoding="utf-8")
    for token in (
        "PublicationReaderSupport",
        "lookup_publication_reader_support",
        "scoreform 0.13.0",
        "quillan 0.10.6",
        "pds-concord 0.3.2",
        "scoreform_academic_result_reader_v1",
        "quillan_academic_result_reader_v1",
        "concord_academic_result_reader_v1",
    ):
        assert token in document
