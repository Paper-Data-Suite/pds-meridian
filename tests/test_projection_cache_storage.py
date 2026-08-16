from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_catalog import CatalogPublication
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationProducerRegistry,
)
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

import meridian.ingestion as ingestion
import meridian.projection_cache as cache
from meridian.adapters import AdapterDescriptor, AdapterKey, AdapterRegistry
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    EvidenceTargetIdentity,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    ProjectionIdentity,
    StudentSubject,
)

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
MANIFEST_BYTES = b'{"schema_version":"synthetic_manifest_v1"}\n'
DIGEST = hashlib.sha256(MANIFEST_BYTES).hexdigest()
WORK = ModuleWorkRef("synthetic", "class_2026", "work_1")
PUB_ID = "pub_11111111111111111111111111111111"


def registration(revision: int = 1) -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        revision,
        "assignment_v1",
        "Synthetic Work",
        "assignment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )


def publication() -> PublicationRecord:
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
            "classes/class_2026/modules/synthetic/work/work_1/"
            "exports/manifests/academic_results/1.json"
        ),
        "sha256",
        DIGEST,
        NOW,
        1,
        None,
    )


def catalog_row(pub: PublicationRecord) -> CatalogPublication:
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
        return EvidenceInventory(())


class RecordingAuthorizer:
    def __init__(self, *, deny_read: bool = False, version: str = "1") -> None:
        self.deny_read = deny_read
        self.version = version
        self.requests: list[ingestion.PublicationAuthorizationRequest] = []

    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        self.requests.append(request)
        if self.deny_read and request.operation == "read_projection_cache":
            return ingestion.PublicationAuthorizationDecision(
                False,
                "district_policy",
                self.version,
                ("authorization.cache_denied",),
            )
        return ingestion.PublicationAuthorizationDecision(
            True,
            "district_policy",
            self.version,
            (),
        )


def profile_registry() -> PublicationProducerRegistry:
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
                        frozenset({"synthetic_manifest_v1"}),
                        frozenset({"points"}),
                        (),
                        True,
                    ),
                ),
            ),
        )
    )


def patch_ingestion_context(
    monkeypatch: pytest.MonkeyPatch,
    pub: PublicationRecord,
    reg: AcademicWorkRegistration,
) -> None:
    monkeypatch.setattr(
        ingestion,
        "get_canonical_publication_record",
        lambda root, publication_id: pub,
    )
    monkeypatch.setattr(
        ingestion,
        "load_academic_work_registration_revision",
        lambda root, work, revision: reg,
    )
    monkeypatch.setattr(
        ingestion,
        "load_current_academic_work_registration",
        lambda root, work: reg,
    )
    monkeypatch.setattr(
        ingestion,
        "list_publication_record_set",
        lambda root, work, kind, record_set_id: (pub,),
    )
    monkeypatch.setattr(
        ingestion,
        "get_canonical_publication_withdrawal",
        lambda root, publication_id: None,
    )


def prepared(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[
    ingestion.PreparedPublicationInvocation,
    SyntheticAdapter,
    Path,
]:
    pub = publication()
    reg = registration()
    patch_ingestion_context(monkeypatch, pub, reg)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_BYTES)
    monkeypatch.setattr(
        ingestion,
        "verify_publication_manifest",
        lambda root, value: manifest,
    )
    adapter = SyntheticAdapter()
    authorizer = RecordingAuthorizer()
    result = ingestion.prepare_publication_invocation(
        tmp_path,
        ingestion.PublicationCandidate(catalog_row(pub), 0),
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((adapter,)),
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        distribution_version_resolver=lambda name: "1.0.0",
    )
    return result, adapter, manifest


def one_item(
    value: ingestion.PreparedPublicationInvocation,
    *,
    item_id: str = "evidence_1",
    scalar: int = 1,
) -> EvidenceInventory:
    descriptor = value.adapter_match.descriptor
    projection = ProjectionIdentity(
        descriptor.adapter_id,
        descriptor.projection_contract_version,
        descriptor.producer_reader_distribution,
        value.producer_reader_version,
    )
    provenance = EvidenceProvenance(
        value.canonical_context.publication,
        value.canonical_context.referenced_registration,
        value.canonical_context.withdrawal,
        projection,
        NativeProvenance((NativeReference("attempt", "attempt_1"),)),
    )
    return EvidenceInventory(
        (
            EvidenceItem(
                item_id,
                StudentSubject("student_1"),
                EvidenceTarget("attempt", "attempt_1"),
                "synthetic_result",
                NativeScalarValue(scalar),
                provenance,
            ),
        )
    )


def test_creation_and_exact_replay_do_not_invoke_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, adapter, _ = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    authorizer = RecordingAuthorizer()
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return NOW

    first = cache.cache_projected_inventory(
        tmp_path,
        value,
        EvidenceInventory(()),
        authorizer=authorizer,
        clock=clock,
    )
    second = cache.cache_projected_inventory(
        tmp_path,
        value,
        EvidenceInventory(()),
        authorizer=authorizer,
        clock=clock,
    )
    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.stored.content == second.stored.content
    assert first.stored.snapshot.captured_at == second.stored.snapshot.captured_at
    assert clock_calls == 1
    assert adapter.calls == 0
    assert not (first.stored.path.parent / ".write.lock").exists()
    assert len(list(first.stored.path.parent.glob("*.json"))) == 1


def test_same_identity_with_different_inventory_is_nondeterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, _, _ = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    authorizer = RecordingAuthorizer()
    first = cache.cache_projected_inventory(
        tmp_path,
        value,
        one_item(value, scalar=1),
        authorizer=authorizer,
        clock=lambda: NOW,
    )
    with pytest.raises(cache.ProjectionCacheNondeterminismError):
        cache.cache_projected_inventory(
            tmp_path,
            value,
            one_item(value, scalar=2),
            authorizer=authorizer,
            clock=lambda: pytest.fail("clock must not run during conflict"),
        )
    assert first.stored.path.read_bytes() == first.stored.content
    assert len(list(first.stored.path.parent.glob("*.json"))) == 1


def test_canonical_change_after_projection_prevents_cache_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, _, _ = prepared(monkeypatch, tmp_path)
    changed = replace_context_current_registration(value.canonical_context)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: changed,
    )
    with pytest.raises(cache.ProjectionCacheSourceChangedError):
        cache.cache_projected_inventory(
            tmp_path,
            value,
            EvidenceInventory(()),
            authorizer=RecordingAuthorizer(),
        )
    assert not (tmp_path / "cache").exists()


def replace_context_current_registration(
    context: ingestion.CanonicalPublicationContext,
) -> ingestion.CanonicalPublicationContext:
    changed = registration(2)
    return ingestion.CanonicalPublicationContext(
        context.publication,
        context.referenced_registration,
        changed,
        context.series,
        context.withdrawal,
    )


def test_authorization_denial_occurs_before_cache_file_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, _, manifest = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    created = cache.cache_projected_inventory(
        tmp_path,
        value,
        EvidenceInventory(()),
        authorizer=RecordingAuthorizer(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        cache,
        "verify_publication_manifest",
        lambda root, publication: manifest,
    )
    opened = False
    original = cache._read_bounded

    def tracked(*args: object, **kwargs: object) -> bytes:
        nonlocal opened
        opened = True
        return original(*args, **kwargs)

    monkeypatch.setattr(cache, "_read_bounded", tracked)
    with pytest.raises(cache.ProjectionCacheAuthorizationDeniedError):
        cache.load_authorized_projection_snapshot(
            tmp_path,
            value.canonical_context.publication.publication_id,
            created.stored.cache_key,
            authorizer=RecordingAuthorizer(deny_read=True),
            authorization_purpose_id="grading_import",
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
            distribution_version_resolver=lambda name: "1.0.0",
        )
    assert opened is False


def test_authorized_load_assesses_exact_current_source_as_reusable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, _, manifest = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    created = cache.cache_projected_inventory(
        tmp_path,
        value,
        EvidenceInventory(()),
        authorizer=RecordingAuthorizer(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        cache,
        "verify_publication_manifest",
        lambda root, publication: manifest,
    )
    result = cache.load_authorized_projection_snapshot(
        tmp_path,
        value.canonical_context.publication.publication_id,
        created.stored.cache_key,
        authorizer=RecordingAuthorizer(),
        authorization_purpose_id="grading_import",
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
        distribution_version_resolver=lambda name: "1.0.0",
    )
    assert result.assessment.source_status == "current"
    assert result.assessment.reuse_status == "reusable"
    assert result.assessment.reason_codes == ()
    assert result.assessment.reusable_for_current_use is True
    assert created.stored.path.read_bytes() == created.stored.content


def test_cache_storage_preserves_exact_producer_native_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value, _, manifest = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    target_id = "Body / 1"
    standard_id = " Standard / A "
    reference_id = "Observation / A"
    scale_id = " synthetic / scale "
    label = "Emerging / Developing"
    description = "First line\nSecond line"
    descriptor = value.adapter_match.descriptor
    provenance = EvidenceProvenance(
        value.canonical_context.publication,
        value.canonical_context.referenced_registration,
        value.canonical_context.withdrawal,
        ProjectionIdentity(
            descriptor.adapter_id,
            descriptor.projection_contract_version,
            descriptor.producer_reader_distribution,
            value.producer_reader_version,
        ),
        NativeProvenance((NativeReference("observation", reference_id),)),
    )
    inventory = EvidenceInventory(
        (
            EvidenceItem(
                "evidence_native_text",
                StudentSubject("student_1"),
                EvidenceTarget(
                    "review_unit",
                    target_id,
                    parent_target=EvidenceTargetIdentity(
                        "submission", " Submission / A "
                    ),
                    standard_ids=(standard_id,),
                    sequence=1,
                ),
                "native_rating",
                NativeScaledValue(
                    0,
                    NativeScale(
                        scale_id,
                        (NativeScaleLevel(0, label, description),),
                    ),
                ),
                provenance,
            ),
        )
    )
    created = cache.cache_projected_inventory(
        tmp_path,
        value,
        inventory,
        authorizer=RecordingAuthorizer(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        cache,
        "verify_publication_manifest",
        lambda root, publication: manifest,
    )

    loaded = cache.load_authorized_projection_snapshot(
        tmp_path,
        value.canonical_context.publication.publication_id,
        created.stored.cache_key,
        authorizer=RecordingAuthorizer(),
        authorization_purpose_id="grading_import",
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
        distribution_version_resolver=lambda name: "1.0.0",
    )

    assert loaded.stored.snapshot.inventory == inventory
    restored = loaded.stored.snapshot.inventory.items[0]
    assert restored.target.target_id == target_id
    assert restored.target.standard_ids == (standard_id,)
    assert restored.provenance.native.references[0].identifier == reference_id
    assert isinstance(restored.value, NativeScaledValue)
    assert restored.value.scale.scale_id == scale_id
    assert restored.value.scale.levels[0].label == label
    assert restored.value.scale.levels[0].description == description
