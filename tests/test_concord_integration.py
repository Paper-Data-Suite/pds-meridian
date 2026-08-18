from __future__ import annotations

from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from concord.academic_result_manifest import derive_manifest_capabilities
from concord.academic_result_reader import read_academic_result_manifest
from concord.pds_publication import get_publication_producer_profile
from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.routes import module_work_dir

import meridian.diagnostics as diagnostics
import meridian.ingestion as ingestion
from meridian.adapters import AdapterRegistry
from meridian.concord_adapter import ConcordAcademicResultAdapter
from meridian.projection_cache import (
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
from tests.concord_test_support import SOURCE, WORK, concord_manifest_bytes


class AllowSyntheticProjection:
    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True,
            "synthetic_policy",
            "1",
            (),
        )


def _exact_version(name: str) -> str:
    assert name == "pds-concord"
    return "0.2.0"


def test_released_concord_core_handoff_projection_cache_and_diagnostics(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    module_work_dir(workspace, WORK).mkdir(parents=True)

    registered = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=WORK,
            producer_contract_version="concord_academic_work_v1",
            title="Synthetic Collaborative Activity",
            work_kind="collaborative_activity",
            academic_intent="formative",
            lifecycle="active",
            source_records=(SOURCE,),
        ),
    )
    assert registered.registration.source_records == (SOURCE,)

    manifest_bytes = concord_manifest_bytes()
    manifest = read_academic_result_manifest(manifest_bytes)
    capabilities = derive_manifest_capabilities(manifest)
    assert capabilities == (
        "criterion_scores",
        "standards_ratings",
        "moderated_scores",
    )

    manifest_relative = (
        "classes/class_2026/modules/concord/work/activity_1/"
        "publications/academic_results/1.json"
    )
    manifest_path = workspace.joinpath(*manifest_relative.split("/"))
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest_bytes)

    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=WORK,
            source_record=SOURCE,
            publication_kind="academic_result_set",
            capabilities=capabilities,
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="concord_academic_result_manifest_v1",
            manifest_path=manifest_relative,
            academic_work_registration_revision=1,
        ),
    )
    rebuild_academic_catalog(workspace)

    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="concord",
                state="current",
                limit=10,
            )
        ),
    )
    assert [candidate.publication_id for candidate in discovered.candidates] == [
        published.publication.publication_id
    ]

    producer_registry = PublicationProducerRegistry(
        (get_publication_producer_profile(),)
    )
    adapter_registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    authorizer = AllowSyntheticProjection()
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        discovered.candidates[0],
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        distribution_version_resolver=_exact_version,
    )
    assert prepared.producer_reader_version == "0.2.0"
    assert prepared.projection_request.manifest_bytes == manifest_bytes
    assert prepared.projection_request.publication.source_record == SOURCE

    inventory = adapter_registry.invoke(
        prepared.projection_request,
        _exact_version,
    )
    assert len(inventory.items) == 4
    predecessor, current, standard, absent = inventory.items
    assert predecessor.subject is None
    assert current.subject is None
    assert current.target.target_kind == "concord_group"
    assert current.target.target_id == "group_1"
    assert standard.subject is not None
    assert standard.subject.student_id == "student_1"
    assert absent.subject is not None
    assert absent.subject.student_id == "student_2"

    cached = cache_projected_inventory(
        workspace,
        prepared,
        inventory,
        authorizer=authorizer,
        clock=lambda: datetime(2026, 8, 18, 2, tzinfo=UTC),
    )
    assert cached.stored.snapshot.inventory == inventory

    authorized = load_authorized_projection_snapshot(
        workspace,
        published.publication.publication_id,
        cached.stored.cache_key,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        distribution_version_resolver=_exact_version,
    )
    assert authorized.stored.snapshot.inventory == inventory
    assert authorized.assessment.source_status == "current"
    assert authorized.assessment.reuse_status == "reusable"
    assert authorized.assessment.reason_codes == ()

    changed_reader = load_authorized_projection_snapshot(
        workspace,
        published.publication.publication_id,
        cached.stored.cache_key,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        distribution_version_resolver=lambda _: "0.2.1",
    )
    assert changed_reader.assessment.reuse_status == "reprojection_required"
    assert "cache.reader_version_changed" in changed_reader.assessment.reason_codes

    ready_dependencies = diagnostics.DiagnosticsDependencies(
        producer_registry=producer_registry,
        adapter_registry=diagnostics.build_builtin_adapter_registry(),
        distribution_version_resolver=_exact_version,
    )
    ready = diagnostics.verify_publication_diagnostic(
        workspace,
        published.publication.publication_id,
        ready_dependencies,
    ).support
    assert ready.overall_state == "support_ready"
    assert ready.compatibility_state == "compatible"
    assert ready.adapter_state == "supported"
    assert ready.adapter_id == "concord.academic_result"
    assert ready.adapter_key is not None
    assert ready.adapter_key.source_record_kind == "activity"
    assert ready.adapter_key.source_record_contract_version == (
        "concord_activity_v1"
    )
    assert ready.reader_state == "ready"
    assert ready.reader_distribution == "pds-concord"
    assert ready.installed_reader_version == "0.2.0"

    adapter_absent = diagnostics.DiagnosticsDependencies(
        producer_registry=producer_registry,
        adapter_registry=AdapterRegistry(),
        distribution_version_resolver=_exact_version,
    )
    unsupported = diagnostics.verify_publication_diagnostic(
        workspace,
        published.publication.publication_id,
        adapter_absent,
    ).support
    assert unsupported.compatibility_state == "compatible"
    assert unsupported.adapter_state == "missing"
    assert unsupported.overall_state == "support_unsupported"

    def missing_reader(name: str) -> str:
        assert name == "pds-concord"
        raise metadata.PackageNotFoundError(name)

    unavailable_dependencies = diagnostics.DiagnosticsDependencies(
        producer_registry=producer_registry,
        adapter_registry=diagnostics.build_builtin_adapter_registry(),
        distribution_version_resolver=missing_reader,
    )
    unavailable = diagnostics.verify_publication_diagnostic(
        workspace,
        published.publication.publication_id,
        unavailable_dependencies,
    ).support
    assert unavailable.adapter_state == "supported"
    assert unavailable.reader_state == "unavailable"
    assert unavailable.overall_state == "support_unavailable"

    wrong_version_dependencies = diagnostics.DiagnosticsDependencies(
        producer_registry=producer_registry,
        adapter_registry=diagnostics.build_builtin_adapter_registry(),
        distribution_version_resolver=lambda _: "0.2.1",
    )
    wrong = diagnostics.verify_publication_diagnostic(
        workspace,
        published.publication.publication_id,
        wrong_version_dependencies,
    ).support
    assert wrong.reader_state == "version_unsupported"
    assert wrong.installed_reader_version == "0.2.1"
    assert wrong.supported_reader_versions == ("0.2.0",)
    assert wrong.overall_state == "support_unsupported"
