"""Issue #111 Slice 2: Core reader metadata shape before runtime migration."""

from __future__ import annotations

import pds_core.publication_compatibility as compatibility
import pytest


def _profile(
    *, reader_support: object = None
) -> compatibility.PublicationProducerProfile:
    options = {}
    if reader_support is not None:
        options["reader_support"] = reader_support
    return compatibility.PublicationProducerProfile(
        module_id="fixture_producer",
        display_name="Fixture Producer",
        supported_core_publication_schema_versions=frozenset({"1"}),
        supported_academic_work_contract_versions=frozenset({"fixture_work_v1"}),
        publication_contracts=(
            compatibility.PublicationContractSupport(
                publication_kind="academic_result_set",
                manifest_contract_versions=frozenset({"fixture_manifest_v1"}),
                supported_capabilities=frozenset({"standards_ratings"}),
                **options,
            ),
        ),
    )


def test_legacy_core_producer_profile_remains_valid() -> None:
    profile = _profile()
    checked = compatibility.validate_publication_producer_profile(profile)
    assert checked == profile
    assert getattr(checked.publication_contracts[0], "reader_support", ()) == ()


def test_new_core_metadata_survives_validation_and_discovery_boundary() -> None:
    if not hasattr(compatibility, "PublicationReaderSupport"):
        pytest.skip("Core reader-support metadata prerequisite not installed")

    reader = compatibility.PublicationReaderSupport(
        manifest_contract_version="fixture_manifest_v1",
        distribution_name="pds-fixture",
        reader_contract_version="fixture_academic_result_reader_v1",
    )
    profile = _profile(reader_support=(reader,))
    checked = compatibility.validate_publication_producer_profile(profile)
    registry = compatibility.build_publication_producer_registry(
        explicit_profiles=(checked,), discover_installed=False
    )
    assert registry.get("fixture_producer") == checked
    assert checked.publication_contracts[0].reader_support == (reader,)
    assert checked.publication_contracts[0].reader_support[0].distribution_name == (
        "pds-fixture"
    )


def test_reader_contract_does_not_replace_manifest_contract() -> None:
    if not hasattr(compatibility, "PublicationReaderSupport"):
        pytest.skip("Core reader-support metadata prerequisite not installed")
    reader = compatibility.PublicationReaderSupport(
        manifest_contract_version="fixture_manifest_v1",
        distribution_name="pds-fixture",
        reader_contract_version="fixture_academic_result_reader_v1",
    )
    row = _profile(reader_support=(reader,)).publication_contracts[0]
    assert row.manifest_contract_versions == frozenset({"fixture_manifest_v1"})
    assert row.reader_support[0].reader_contract_version not in (
        row.manifest_contract_versions
    )
