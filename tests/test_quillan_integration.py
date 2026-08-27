from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef
from quillan.pds_publication import get_publication_producer_profile

import meridian.ingestion as ingestion
from meridian.adapters import AdapterRegistry
from meridian.projection_cache import cache_projected_inventory
from meridian.quillan_adapter import QuillanAcademicResultAdapter
from tests.quillan_test_support import WORK, quillan_manifest_bytes


class AllowSyntheticProjection:
    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True, "synthetic_policy", "1", ()
        )


def test_real_reader_core_ingestion_projection_and_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    module_work_dir(workspace, WORK).mkdir(parents=True)
    registered = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=WORK,
            producer_contract_version="quillan_academic_work_v1",
            title="Synthetic Essay Alpha",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(
                ModuleRecordRef("quillan", "assignment", WORK.work_id, "2"),
            ),
        ),
    )
    assert registered.registration.source_records[0].contract_version == "2"

    manifest_bytes = quillan_manifest_bytes()
    manifest_relative = (
        "classes/synthetic_class_2026/modules/quillan/work/"
        "synthetic_essay_alpha/publications/academic_results/1.json"
    )
    manifest_path = workspace.joinpath(*manifest_relative.split("/"))
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest_bytes)
    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=WORK,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=("standards_ratings",),
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="quillan_academic_result_manifest_v1",
            manifest_path=manifest_relative,
            academic_work_registration_revision=1,
        ),
    )
    rebuild_academic_catalog(workspace)

    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(module_id="quillan", state="current", limit=10)
        ),
    )
    assert [candidate.publication_id for candidate in discovered.candidates] == [
        published.publication.publication_id
    ]
    registry = AdapterRegistry((QuillanAcademicResultAdapter(),))
    producer_registry = PublicationProducerRegistry(
        (get_publication_producer_profile(),)
    )
    authorizer = AllowSyntheticProjection()
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        discovered.candidates[0],
        producer_registry=producer_registry,
        adapter_registry=registry,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
    )
    assert prepared.producer_reader_version == "0.10.0"
    assert prepared.projection_request.manifest_bytes == manifest_bytes

    inventory = registry.invoke(prepared.projection_request)
    assert len(inventory.items) == 17
    assert {item.subject.student_id for item in inventory.items} == {
        "student_synthetic_001",
        "student_synthetic_002",
    }
    cached = cache_projected_inventory(
        workspace,
        prepared,
        inventory,
        authorizer=authorizer,
        clock=lambda: datetime(2026, 8, 16, 18, tzinfo=UTC),
    )
    snapshot = cached.stored.snapshot
    assert snapshot.inventory == inventory
    assert snapshot.projection.adapter_id == "quillan.academic_result"
    assert snapshot.projection.projection_contract_version == "1"
    assert snapshot.projection.producer_reader_distribution == "quillan"
    assert snapshot.projection.producer_reader_version == "0.10.0"
