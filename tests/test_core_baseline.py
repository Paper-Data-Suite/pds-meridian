from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_args

from packaging.version import Version
from pds_core.academic_catalog import (
    ACADEMIC_CATALOG_APPLICATION_ID,
    ACADEMIC_CATALOG_SCHEMA_VERSION,
)
from pds_core.academic_periods import ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION
from pds_core.academic_work_registrations import (
    ACADEMIC_WORK_REGISTRATION_SCHEMA_VERSION,
    academic_work_registration_from_dict,
)
from pds_core.publication_compatibility import (
    CORE_PUBLICATION_COMPATIBILITY_CONTRACT_VERSION,
    PUBLICATION_PRODUCER_ENTRY_POINT_GROUP,
    PublicationContractSupport,
    PublicationProducerProfile,
    SourceRecordContractSupport,
    evaluate_publication_compatibility,
)
from pds_core.publication_records import (
    PUBLICATION_KINDS,
    PUBLICATION_RECORD_SCHEMA_VERSION,
    PUBLICATION_WITHDRAWAL_SCHEMA_VERSION,
    ManifestDigestAlgorithm,
    publication_record_from_dict,
    publication_withdrawal_from_dict,
    validate_publication_withdrawal_relationship,
)
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef


def test_core_version_and_contract_values() -> None:
    version = Version(importlib.metadata.version("pds-core"))
    assert Version("0.6") <= version < Version("0.7")
    assert ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION == "1"
    assert ACADEMIC_WORK_REGISTRATION_SCHEMA_VERSION == "1"
    assert PUBLICATION_RECORD_SCHEMA_VERSION == "1"
    assert PUBLICATION_WITHDRAWAL_SCHEMA_VERSION == "1"
    assert CORE_PUBLICATION_COMPATIBILITY_CONTRACT_VERSION == "1"
    assert ACADEMIC_CATALOG_SCHEMA_VERSION == 1
    assert ACADEMIC_CATALOG_APPLICATION_ID == 0x50445341
    assert get_args(ManifestDigestAlgorithm) == ("sha256",)
    assert PUBLICATION_PRODUCER_ENTRY_POINT_GROUP == (
        "paper_data_suite.publication_producers"
    )
    assert PUBLICATION_KINDS == {
        "academic_result_set",
        "intervention_record_set",
    }


def test_synthetic_registration_publication_and_withdrawal(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    withdrawal = publication_withdrawal_from_dict(
        fixture_loader("core_v0_6/baseline_withdrawal.json")
    )

    expected_work = ModuleWorkRef(
        module_id="synthetic_producer",
        class_id="synthetic_class_2026",
        work_id="synthetic_assignment_alpha",
    )
    expected_source = ModuleRecordRef(
        module_id="synthetic_producer",
        record_kind="assignment",
        record_id="synthetic_assignment_alpha",
        contract_version="fixture_contract_1",
    )
    assert registration.work == expected_work
    assert registration.source_records == (expected_source,)
    assert publication.work == expected_work
    assert publication.source_record == expected_source
    assert publication.academic_work_registration_revision == (
        registration.registration_revision
    )
    assert publication.manifest_digest_algorithm == "sha256"
    assert publication.publication_kind == "academic_result_set"
    assert validate_publication_withdrawal_relationship(
        publication, withdrawal
    ) == withdrawal


def test_synthetic_profile_is_compatible(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    profile = PublicationProducerProfile(
        module_id="synthetic_producer",
        display_name="Synthetic Producer",
        supported_core_publication_schema_versions=frozenset({"1"}),
        supported_academic_work_contract_versions=frozenset(
            {"fixture_contract_1"}
        ),
        publication_contracts=(
            PublicationContractSupport(
                publication_kind="academic_result_set",
                manifest_contract_versions=frozenset({"fixture_manifest_1"}),
                supported_capabilities=frozenset({"points"}),
                source_record_contracts=(
                    SourceRecordContractSupport(
                        record_kind="assignment",
                        contract_versions=frozenset({"fixture_contract_1"}),
                    ),
                ),
                allows_missing_source_record=False,
            ),
        ),
    )
    result = evaluate_publication_compatibility(
        publication, profile, registration
    )
    assert result.compatible
    assert result.codes == ()


def test_core_contract_probes_are_read_only(
    fixture_loader: Callable[[str], dict[str, Any]], tmp_path: Path
) -> None:
    before = list(tmp_path.iterdir())
    academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    publication_withdrawal_from_dict(
        fixture_loader("core_v0_6/baseline_withdrawal.json")
    )
    assert list(tmp_path.iterdir()) == before
