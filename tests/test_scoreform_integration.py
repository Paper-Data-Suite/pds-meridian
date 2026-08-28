from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationProducerRegistry,
)
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef

import meridian.ingestion as ingestion
from meridian.adapters import AdapterRegistry
from meridian.projection_cache import cache_projected_inventory
from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter
from tests.scoreform_test_support import WORK, scoreform_manifest_bytes


class AllowSyntheticProjection:
    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True, "synthetic_policy", "1", ()
        )


def scoreform_profile_registry() -> PublicationProducerRegistry:
    return PublicationProducerRegistry(
        (
            PublicationProducerProfile(
                "scoreform",
                "ScoreForm",
                frozenset({"1"}),
                frozenset({"scoreform_academic_work_v1"}),
                (
                    PublicationContractSupport(
                        "academic_result_set",
                        frozenset({"scoreform_academic_result_manifest_v1"}),
                        frozenset(
                            {"points", "question_evidence", "multiple_attempts"}
                        ),
                        (),
                        True,
                    ),
                ),
            ),
        )
    )


def test_real_reader_core_ingestion_projection_and_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    module_work_dir(workspace, WORK).mkdir(parents=True)
    registered = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=WORK,
            producer_contract_version="scoreform_academic_work_v1",
            title="Synthetic Quiz Alpha",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(
                ModuleRecordRef(
                    "scoreform",
                    "assignment",
                    WORK.work_id,
                    None,
                ),
            ),
        ),
    )
    assert registered.registration.registration_revision == 1

    manifest_bytes = scoreform_manifest_bytes()
    manifest_relative = (
        "classes/synthetic_class_2026/modules/scoreform/work/"
        "synthetic_quiz_alpha/publications/academic_results/1.json"
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
            capabilities=("points", "question_evidence", "multiple_attempts"),
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="scoreform_academic_result_manifest_v1",
            manifest_path=manifest_relative,
            academic_work_registration_revision=1,
        ),
    )
    rebuild_academic_catalog(workspace)

    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(module_id="scoreform", state="current", limit=10)
        ),
    )
    assert [candidate.publication_id for candidate in discovered.candidates] == [
        published.publication.publication_id
    ]
    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    authorizer = AllowSyntheticProjection()
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        discovered.candidates[0],
        producer_registry=scoreform_profile_registry(),
        adapter_registry=registry,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
    )
    assert prepared.producer_reader_version == "0.11.0"
    assert prepared.projection_request.manifest_bytes == manifest_bytes

    inventory = registry.invoke(prepared.projection_request)
    assert len(inventory.items) == 24
    assert {item.subject.student_id for item in inventory.items} == {
        "student_synthetic_001",
        "student_synthetic_002",
    }
    cached = cache_projected_inventory(
        workspace,
        prepared,
        inventory,
        authorizer=authorizer,
        clock=lambda: datetime(2026, 8, 9, 18, tzinfo=UTC),
    )
    snapshot = cached.stored.snapshot
    assert snapshot.inventory == inventory
    assert snapshot.projection.adapter_id == "scoreform.academic_result"
    assert snapshot.projection.projection_contract_version == "1"
    assert snapshot.projection.producer_reader_distribution == "scoreform"
    assert snapshot.projection.producer_reader_version == "0.11.0"
