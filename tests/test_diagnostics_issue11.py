from __future__ import annotations

from datetime import UTC, datetime
from importlib import metadata

import pytest
from pds_core.academic_catalog import CatalogPublication, PublicationCatalogQuery
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationProducerRegistry,
)
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

import meridian.diagnostics as diagnostics
from meridian.adapters import AdapterDescriptor, AdapterKey, AdapterRegistry
from meridian.evidence import EvidenceInventory
from meridian.ingestion import (
    CanonicalPublicationContext,
    PublicationCandidate,
    PublicationCandidateMissingError,
    PublicationDiscoveryRequest,
    PublicationDiscoveryResult,
    PublicationSeriesMember,
    PublicationSeriesObservation,
)

NOW = datetime(2026, 8, 16, 18, tzinfo=UTC)
WORK = ModuleWorkRef("synthetic", "class_2026", "work_1")
PUB_ID = "pub_11111111111111111111111111111111"
DIGEST = "a" * 64


def registration() -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "assignment_v1",
        "Synthetic Work",
        "assignment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )


def publication(*, digest: str = DIGEST) -> PublicationRecord:
    return PublicationRecord(
        "1",
        "publication_record",
        PUB_ID,
        WORK,
        None,
        "academic_result_set",
        ("points",),
        "academic_results",
        1,
        "synthetic_manifest_v1",
        (
            "classes/class_2026/modules/synthetic/work/work_1/exports/"
            "manifests/academic_results/1.json"
        ),
        "sha256",
        digest,
        NOW,
        1,
        None,
    )


def context(pub: PublicationRecord | None = None) -> CanonicalPublicationContext:
    pub = publication() if pub is None else pub
    reg = registration()
    series = PublicationSeriesObservation(
        members=(PublicationSeriesMember(pub, None),),
        target_publication_id=pub.publication_id,
        target_index=0,
        head_publication_id=pub.publication_id,
        target_state="current_selectable",
        successor_publication_id=None,
    )
    return CanonicalPublicationContext(pub, reg, reg, series, None)


def catalog_row(pub: PublicationRecord | None = None) -> CatalogPublication:
    pub = publication() if pub is None else pub
    return CatalogPublication(
        None,
        pub.publication_id,
        pub.work,
        pub.source_record,
        pub.publication_kind,
        pub.capabilities,
        pub.record_set_id,
        pub.record_set_revision,
        pub.manifest_contract_version,
        pub.manifest_path,
        pub.manifest_digest_algorithm,
        pub.manifest_digest,
        pub.published_at,
        pub.academic_work_registration_revision,
        "active",
        1,
        "active",
        pub.supersedes_publication_id,
        True,
        False,
        None,
        True,
    )


class SyntheticAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._descriptor = AdapterDescriptor(
            adapter_id="synthetic.adapter",
            key=AdapterKey(
                "synthetic",
                "academic_result_set",
                "synthetic_manifest_v1",
                "assignment_v1",
                None,
                None,
            ),
            projection_contract_version="1",
            supported_capabilities=frozenset({"points"}),
            producer_reader_distribution="synthetic-reader",
            supported_producer_reader_versions=frozenset({"1.0.0"}),
        )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._descriptor

    def project(self, request: object) -> EvidenceInventory:
        self.calls += 1
        raise AssertionError("metadata diagnostics must not invoke adapter projection")


def producer_registry(
    *, manifest_version: str = "synthetic_manifest_v1"
) -> PublicationProducerRegistry:
    return PublicationProducerRegistry(
        (
            PublicationProducerProfile(
                "synthetic",
                "Synthetic Producer",
                frozenset({"1"}),
                frozenset({"assignment_v1"}),
                (
                    PublicationContractSupport(
                        "academic_result_set",
                        frozenset({manifest_version}),
                        frozenset({"points"}),
                        (),
                        True,
                    ),
                ),
            ),
        )
    )


def dependencies(
    adapter: SyntheticAdapter,
    *,
    registry: PublicationProducerRegistry | None = None,
    resolver: object | None = None,
) -> diagnostics.DiagnosticsDependencies:
    def exact_version(name: str) -> str:
        assert name == "synthetic-reader"
        return "1.0.0"

    return diagnostics.DiagnosticsDependencies(
        producer_registry=producer_registry() if registry is None else registry,
        adapter_registry=AdapterRegistry((adapter,)),
        distribution_version_resolver=(exact_version if resolver is None else resolver),
    )


def test_support_diagnostics_are_metadata_only() -> None:
    adapter = SyntheticAdapter()
    result = diagnostics.diagnose_publication_support(context(), dependencies(adapter))
    assert result.overall_state == "support_ready"
    assert result.profile_state == "available"
    assert result.compatibility_state == "compatible"
    assert result.adapter_state == "supported"
    assert result.adapter_id == "synthetic.adapter"
    assert result.reader_state == "ready"
    assert result.installed_reader_version == "1.0.0"
    assert result.reason_codes == ()
    assert adapter.calls == 0


def test_reader_unavailable_is_distinct_from_unsupported_contract() -> None:
    adapter = SyntheticAdapter()

    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    result = diagnostics.diagnose_publication_support(
        context(), dependencies(adapter, resolver=missing)
    )
    assert result.reader_state == "unavailable"
    assert result.overall_state == "support_unavailable"
    assert result.reason_codes == ("adapters.reader_unavailable",)
    assert adapter.calls == 0


def test_reader_wrong_version_is_reported_without_fallback() -> None:
    adapter = SyntheticAdapter()

    def wrong(name: str) -> str:
        return "2.0.0"

    result = diagnostics.diagnose_publication_support(
        context(), dependencies(adapter, resolver=wrong)
    )
    assert result.reader_state == "version_unsupported"
    assert result.installed_reader_version == "2.0.0"
    assert result.supported_reader_versions == ("1.0.0",)
    assert result.overall_state == "support_unsupported"
    assert result.reason_codes == ("adapters.reader_version_unsupported",)


def test_profile_incompatibility_preserves_core_contract_codes() -> None:
    adapter = SyntheticAdapter()
    result = diagnostics.diagnose_publication_support(
        context(),
        dependencies(
            adapter,
            registry=producer_registry(manifest_version="other_manifest_v1"),
        ),
    )
    assert result.profile_state == "available"
    assert result.compatibility_state == "incompatible"
    assert result.compatibility_codes == ("contracts.manifest_version_incompatible",)
    assert result.overall_state == "support_unsupported"
    assert result.reason_codes == (
        "contracts.manifest_version_incompatible",
        "ingestion.profile_incompatible",
    )


def test_listing_preserves_candidate_drift_and_still_reports_canonical_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SyntheticAdapter()
    canonical = context()
    drifted = publication(digest="f" * 64)
    candidate = PublicationCandidate(catalog_row(drifted), 0)
    request = PublicationDiscoveryRequest(PublicationCatalogQuery(limit=1, state="all"))
    discovery = PublicationDiscoveryResult(request, (candidate,))

    monkeypatch.setattr(
        diagnostics, "discover_publication_candidates", lambda root, value: discovery
    )
    monkeypatch.setattr(
        diagnostics,
        "load_canonical_publication_context",
        lambda root, publication_id: canonical,
    )

    result = diagnostics.list_publication_diagnostics(
        "workspace", request, dependencies(adapter)
    )
    observation = result.observations[0]
    assert observation.canonical_context == canonical
    assert observation.canonical_error_code == "ingestion.candidate_drift"
    assert observation.drift_fields == ("manifest_digest",)
    assert observation.support is not None
    assert observation.support.overall_state == "support_ready"
    assert adapter.calls == 0


def test_listing_reports_candidate_disappearance_as_a_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SyntheticAdapter()
    candidate = PublicationCandidate(catalog_row(), 0)
    request = PublicationDiscoveryRequest(PublicationCatalogQuery(limit=1))
    discovery = PublicationDiscoveryResult(request, (candidate,))
    monkeypatch.setattr(
        diagnostics, "discover_publication_candidates", lambda root, value: discovery
    )

    def missing(root: str, publication_id: str) -> CanonicalPublicationContext:
        raise PublicationCandidateMissingError(publication_id)

    monkeypatch.setattr(diagnostics, "load_canonical_publication_context", missing)
    result = diagnostics.list_publication_diagnostics(
        "workspace", request, dependencies(adapter)
    )
    observation = result.observations[0]
    assert observation.canonical_context is None
    assert observation.canonical_error_code == "ingestion.candidate_missing"
    assert observation.support is None


def test_exact_verification_does_not_consult_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SyntheticAdapter()
    canonical = context()
    monkeypatch.setattr(
        diagnostics,
        "load_canonical_publication_context",
        lambda root, publication_id: canonical,
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("exact verification must not consult the catalog")

    monkeypatch.setattr(diagnostics, "discover_publication_candidates", forbidden)
    result = diagnostics.verify_publication_diagnostic(
        "workspace", PUB_ID, dependencies(adapter)
    )
    assert result.context == canonical
    assert result.support.overall_state == "support_ready"
    assert adapter.calls == 0


def test_builtin_registry_is_explicit_academic_producers() -> None:
    registry = diagnostics.build_builtin_adapter_registry()
    assert tuple(binding.descriptor.adapter_id for binding in registry.bindings) == (
        "concord.academic_result",
        "quillan.academic_result",
        "scoreform.academic_result",
    )
