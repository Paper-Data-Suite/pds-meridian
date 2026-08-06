from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pytest
from pds_core.academic_catalog import (
    AcademicCatalogCompatibilityError,
    AcademicCatalogIntegrityError,
    AcademicCatalogNotFoundError,
    AcademicCatalogReadError,
    CatalogPublication,
    PublicationCatalogQuery,
    rebuild_academic_catalog,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationProducerRegistry,
)
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleWorkRef

import meridian.ingestion as ingestion
from meridian.adapters import (
    AdapterDescriptor,
    AdapterKey,
    AdapterRegistry,
    ProducerReaderUnavailableError,
)
from meridian.evidence import EvidenceInventory

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)
MANIFEST_BYTES = b'{"schema_version":"synthetic_manifest_v1"}\n'
DIGEST = hashlib.sha256(MANIFEST_BYTES).hexdigest()
WORK = ModuleWorkRef("synthetic", "class_2026", "work_1")
PUB_ID = "pub_11111111111111111111111111111111"


def registration(
    revision: int = 1, lifecycle: str = "active"
) -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        revision,
        "assignment_v1",
        "Synthetic Work",
        "assignment",
        "summative",
        lifecycle,
        NOW,
        NOW,
        (),
    )


def publication(
    *,
    publication_id: str = PUB_ID,
    revision: int = 1,
    predecessor: str | None = None,
    digest: str = DIGEST,
) -> PublicationRecord:
    return PublicationRecord(
        "1",
        "publication_record",
        publication_id,
        WORK,
        None,
        "academic_result_set",
        ("points",),
        "academic_results",
        revision,
        "synthetic_manifest_v1",
        (
            "classes/class_2026/modules/synthetic/work/work_1/"
            f"exports/manifests/academic_results/{revision}.json"
        ),
        "sha256",
        digest,
        NOW,
        1,
        predecessor,
    )


def withdrawal(pub: PublicationRecord) -> PublicationWithdrawal:
    return PublicationWithdrawal(
        "1", "publication_withdrawal", pub.publication_id, NOW, "Synthetic withdrawal"
    )


def catalog_row(
    pub: PublicationRecord | None = None,
    *,
    is_head: bool = True,
    withdrawn: PublicationWithdrawal | None = None,
    current_revision: int | None = 1,
    current_lifecycle: str | None = "active",
) -> CatalogPublication:
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
        "active" if pub.publication_kind == "academic_result_set" else None,
        (
            current_revision
            if pub.publication_kind == "academic_result_set"
            else None
        ),
        (
            current_lifecycle
            if pub.publication_kind == "academic_result_set"
            else None
        ),
        pub.supersedes_publication_id,
        is_head,
        withdrawn is not None,
        None if withdrawn is None else withdrawn.withdrawn_at,
        is_head and withdrawn is None,
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


class AllowAuthorizer:
    def __init__(self) -> None:
        self.requests: list[ingestion.PublicationAuthorizationRequest] = []

    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        self.requests.append(request)
        return ingestion.PublicationAuthorizationDecision(
            True, "district_policy", "1", ()
        )


class DenyAuthorizer:
    def authorize(
        self, request: ingestion.PublicationAuthorizationRequest
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            False,
            "district_policy",
            "1",
            ("authorization.scope_denied",),
        )


def profile_registry() -> PublicationProducerRegistry:
    profile = PublicationProducerProfile(
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
    )
    return PublicationProducerRegistry((profile,))


def candidate(pub: PublicationRecord | None = None) -> ingestion.PublicationCandidate:
    return ingestion.PublicationCandidate(catalog_row(pub), 0)


def patch_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pub: PublicationRecord | None = None,
    referenced: AcademicWorkRegistration | None = None,
    current: AcademicWorkRegistration | None = None,
    records: tuple[PublicationRecord, ...] | None = None,
    withdrawals: dict[str, PublicationWithdrawal] | None = None,
) -> None:
    pub = publication() if pub is None else pub
    referenced = registration() if referenced is None else referenced
    current = referenced if current is None else current
    records = (pub,) if records is None else records
    withdrawals = {} if withdrawals is None else withdrawals
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_record", lambda root, value: pub
    )
    monkeypatch.setattr(
        ingestion,
        "load_academic_work_registration_revision",
        lambda root, work, revision: referenced,
    )
    monkeypatch.setattr(
        ingestion,
        "load_current_academic_work_registration",
        lambda root, work: current,
    )
    monkeypatch.setattr(
        ingestion,
        "list_publication_record_set",
        lambda root, work, kind, record_set_id: records,
    )
    monkeypatch.setattr(
        ingestion,
        "get_canonical_publication_withdrawal",
        lambda root, value: withdrawals.get(value),
    )


def test_discovery_requires_explicit_limit() -> None:
    with pytest.raises(ingestion.IngestionValidationError):
        ingestion.PublicationDiscoveryRequest(PublicationCatalogQuery())


def test_discovery_preserves_catalog_order(monkeypatch: pytest.MonkeyPatch) -> None:
    first = publication()
    second = publication(
        publication_id="pub_22222222222222222222222222222222", revision=2
    )
    monkeypatch.setattr(
        ingestion,
        "query_publication_catalog",
        lambda root, query: (catalog_row(first), catalog_row(second)),
    )
    request = ingestion.PublicationDiscoveryRequest(
        PublicationCatalogQuery(limit=2, state="all")
    )
    result = ingestion.discover_publication_candidates("workspace", request)
    assert [item.publication_id for item in result.candidates] == [
        first.publication_id,
        second.publication_id,
    ]
    assert [item.ordinal for item in result.candidates] == [0, 1]


@pytest.mark.parametrize(
    ("core_error", "expected"),
    [
        (AcademicCatalogNotFoundError("missing"), ingestion.CatalogMissingError),
        (
            AcademicCatalogCompatibilityError("bad version"),
            ingestion.CatalogIncompatibleError,
        ),
        (AcademicCatalogIntegrityError("corrupt"), ingestion.CatalogInvalidError),
        (AcademicCatalogReadError("locked"), ingestion.CatalogReadFailedError),
    ],
)
def test_catalog_failures_remain_distinct(
    monkeypatch: pytest.MonkeyPatch,
    core_error: Exception,
    expected: type[Exception],
) -> None:
    def fail(root: object, query: object) -> tuple[CatalogPublication, ...]:
        raise core_error

    monkeypatch.setattr(ingestion, "query_publication_catalog", fail)
    request = ingestion.PublicationDiscoveryRequest(PublicationCatalogQuery(limit=1))
    with pytest.raises(expected):
        ingestion.discover_publication_candidates("workspace", request)


def test_candidate_drift_reports_deterministic_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    patch_context(monkeypatch, pub=pub)
    context = ingestion._load_canonical_context("workspace", pub.publication_id)
    stale_row = replace(
        catalog_row(pub),
        manifest_digest="f" * 64,
        is_series_head=False,
        is_current_selectable=False,
    )
    fields = ingestion.compare_candidate_to_canonical(
        ingestion.PublicationCandidate(stale_row, 0), context
    )
    assert fields == ("manifest_digest", "series_head", "current_selectable")


def test_referenced_and_current_registrations_remain_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    referenced = registration(1, "active")
    current = registration(2, "closed")
    patch_context(monkeypatch, referenced=referenced, current=current)
    context = ingestion._load_canonical_context("workspace", PUB_ID)
    assert context.referenced_registration == referenced
    assert context.current_registration == current


def test_series_observation_marks_historical_and_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = publication()
    second = publication(
        publication_id="pub_22222222222222222222222222222222",
        revision=2,
        predecessor=first.publication_id,
    )
    patch_context(monkeypatch, pub=first, records=(first, second))
    context = ingestion._load_canonical_context("workspace", first.publication_id)
    assert context.canonical_state == "historical"
    assert context.series.head_publication_id == second.publication_id
    assert context.series.successor_publication_id == second.publication_id


def test_series_observation_marks_withdrawn_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    withdrawn = withdrawal(pub)
    patch_context(monkeypatch, pub=pub, withdrawals={pub.publication_id: withdrawn})
    context = ingestion._load_canonical_context("workspace", pub.publication_id)
    assert context.canonical_state == "withdrawn_head"
    assert context.withdrawal == withdrawn


def test_authorization_decision_invariants() -> None:
    with pytest.raises(ingestion.PublicationAuthorizationError):
        ingestion.PublicationAuthorizationDecision(
            True, "district_policy", "1", ("authorization.denied",)
        )
    with pytest.raises(ingestion.PublicationAuthorizationError):
        ingestion.PublicationAuthorizationDecision(
            False, "district_policy", "1", ()
        )


def test_authorization_request_sorts_students() -> None:
    request = ingestion.PublicationAuthorizationRequest(
        publication(),
        registration(),
        None,
        "current_selectable",
        "project_evidence",
        "grading_import",
        ("student_b", "student_a"),
    )
    assert request.requested_student_ids == ("student_a", "student_b")


def test_denied_authorization_prevents_manifest_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_context(monkeypatch)
    called = False

    def verify(root: object, pub: object) -> Path:
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(ingestion, "verify_publication_manifest", verify)
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.PublicationAuthorizationDeniedError):
        ingestion.prepare_publication_invocation(
            "workspace",
            candidate(),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=DenyAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )
    assert called is False
    assert adapter.calls == 0


def test_prepare_returns_request_without_invoking_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pub = publication()
    patch_context(monkeypatch, pub=pub)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_BYTES)
    monkeypatch.setattr(
        ingestion, "verify_publication_manifest", lambda root, value: manifest
    )
    adapter = SyntheticAdapter()
    authorizer = AllowAuthorizer()
    result = ingestion.prepare_publication_invocation(
        tmp_path,
        candidate(pub),
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((adapter,)),
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=("student_2", "student_1"),
        distribution_version_resolver=lambda name: "1.0.0",
    )
    assert result.projection_request.manifest_bytes == MANIFEST_BYTES
    assert result.producer_reader_version == "1.0.0"
    assert result.compatibility.compatible is True
    assert result.authorization.allowed is True
    assert authorizer.requests[0].requested_student_ids == (
        "student_1",
        "student_2",
    )
    assert adapter.calls == 0
    assert str(tmp_path) not in repr(result)
    assert MANIFEST_BYTES.decode() not in repr(result)


def test_manifest_size_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pub = publication(digest=hashlib.sha256(b"12345").hexdigest())
    patch_context(monkeypatch, pub=pub)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"12345")
    monkeypatch.setattr(
        ingestion, "verify_publication_manifest", lambda root, value: manifest
    )
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.ManifestTooLargeError):
        ingestion.prepare_publication_invocation(
            tmp_path,
            candidate(pub),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
            maximum_manifest_bytes=4,
        )


def test_in_memory_digest_race_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pub = publication()
    patch_context(monkeypatch, pub=pub)
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"changed after verification")
    monkeypatch.setattr(
        ingestion, "verify_publication_manifest", lambda root, value: manifest
    )
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.ManifestInvalidError):
        ingestion.prepare_publication_invocation(
            tmp_path,
            candidate(pub),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )


def test_candidate_drift_stops_before_profile_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    patch_context(monkeypatch, pub=pub)
    stale = replace(catalog_row(pub), manifest_path=(
            "classes/class_2026/modules/synthetic/work/work_1/"
            "exports/manifests/academic_results/stale.json"
        ))
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.CandidateDriftError) as caught:
        ingestion.prepare_publication_invocation(
            "workspace",
            ingestion.PublicationCandidate(stale, 0),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )
    assert caught.value.drift_fields == ("manifest_path",)


def test_missing_profile_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_context(monkeypatch)
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.ProducerProfileMissingError):
        ingestion.prepare_publication_invocation(
            "workspace",
            candidate(),
            producer_registry=PublicationProducerRegistry(()),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )


def test_incompatible_profile_preserves_core_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_context(monkeypatch)
    bad_profile = PublicationProducerProfile(
        "synthetic",
        "Synthetic Producer",
        frozenset({"1"}),
        frozenset({"assignment_v2"}),
        (
            PublicationContractSupport(
                "academic_result_set",
                frozenset({"other_manifest"}),
                frozenset({"points"}),
            ),
        ),
    )
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.ProducerProfileIncompatibleError) as caught:
        ingestion.prepare_publication_invocation(
            "workspace",
            candidate(),
            producer_registry=PublicationProducerRegistry((bad_profile,)),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )
    assert caught.value.compatibility_codes == (
        "contracts.manifest_version_incompatible",
        "contracts.registration_version_incompatible",
    )


def test_state_change_after_manifest_loading_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pub = publication()
    referenced = registration()
    calls = 0

    def load(root: object, value: str) -> PublicationRecord:
        nonlocal calls
        calls += 1
        if calls == 1:
            return pub
        raise ingestion.RegistryServiceNotFoundError("gone")

    monkeypatch.setattr(ingestion, "get_canonical_publication_record", load)
    monkeypatch.setattr(
        ingestion,
        "load_academic_work_registration_revision",
        lambda root, work, revision: referenced,
    )
    monkeypatch.setattr(
        ingestion,
        "load_current_academic_work_registration",
        lambda root, work: referenced,
    )
    monkeypatch.setattr(
        ingestion,
        "list_publication_record_set",
        lambda root, work, kind, record_set_id: (pub,),
    )
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_withdrawal", lambda root, value: None
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_BYTES)
    monkeypatch.setattr(
        ingestion, "verify_publication_manifest", lambda root, value: manifest
    )
    adapter = SyntheticAdapter()
    with pytest.raises(ingestion.CanonicalStateChangedError):
        ingestion.prepare_publication_invocation(
            tmp_path,
            candidate(pub),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((adapter,)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )


def test_intervention_context_never_loads_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = PublicationRecord(
        "1",
        "publication_record",
        PUB_ID,
        WORK,
        None,
        "intervention_record_set",
        ("intervention_status",),
        "interventions",
        1,
        "intervention_manifest_v1",
        (
            "classes/class_2026/modules/synthetic/work/work_1/"
            "exports/manifests/interventions/1.json"
        ),
        "sha256",
        DIGEST,
        NOW,
        None,
        None,
    )
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_record", lambda root, value: pub
    )
    monkeypatch.setattr(
        ingestion,
        "load_academic_work_registration_revision",
        lambda *args: pytest.fail("registration revision must not be loaded"),
    )
    monkeypatch.setattr(
        ingestion,
        "load_current_academic_work_registration",
        lambda *args: pytest.fail("current registration must not be loaded"),
    )
    monkeypatch.setattr(
        ingestion,
        "list_publication_record_set",
        lambda root, work, kind, record_set_id: (pub,),
    )
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_withdrawal", lambda root, value: None
    )
    context = ingestion._load_canonical_context("workspace", pub.publication_id)
    assert context.referenced_registration is None
    assert context.current_registration is None


def test_duplicate_catalog_candidates_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    row = catalog_row()
    monkeypatch.setattr(
        ingestion, "query_publication_catalog", lambda root, query: (row, row)
    )
    request = ingestion.PublicationDiscoveryRequest(PublicationCatalogQuery(limit=2))
    with pytest.raises(ingestion.CatalogInvalidError):
        ingestion.discover_publication_candidates("workspace", request)


def test_missing_referenced_registration_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_record", lambda root, value: pub
    )

    def missing(root: object, work: object, revision: int) -> AcademicWorkRegistration:
        raise ingestion.AcademicWorkRegistrationNotFoundError("missing")

    monkeypatch.setattr(
        ingestion, "load_academic_work_registration_revision", missing
    )
    with pytest.raises(ingestion.PublicationRegistrationMissingError):
        ingestion._load_canonical_context("workspace", pub.publication_id)


def test_referenced_registration_mismatch_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    patch_context(monkeypatch, pub=pub, referenced=registration(2))
    with pytest.raises(ingestion.PublicationRegistrationMismatchError):
        ingestion._load_canonical_context("workspace", pub.publication_id)


def test_current_registration_drift_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = publication()
    current = registration(2, "closed")
    patch_context(monkeypatch, pub=pub, current=current)
    context = ingestion._load_canonical_context("workspace", pub.publication_id)
    fields = ingestion.compare_candidate_to_canonical(candidate(pub), context)
    assert fields == ("current_registration",)


def test_reader_readiness_failure_precedes_authorization_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_context(monkeypatch)
    authorizer = AllowAuthorizer()
    manifest_called = False

    def verify(root: object, pub: object) -> Path:
        nonlocal manifest_called
        manifest_called = True
        raise AssertionError

    def unavailable(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(ingestion, "verify_publication_manifest", verify)
    with pytest.raises(ProducerReaderUnavailableError):
        ingestion.prepare_publication_invocation(
            "workspace",
            candidate(),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
            authorizer=authorizer,
            authorization_purpose_id="grading_import",
            distribution_version_resolver=unavailable,
        )
    assert authorizer.requests == []
    assert manifest_called is False


@pytest.mark.parametrize(
    ("core_error", "expected"),
    [
        (
            ingestion.PublicationManifestNotFoundError("missing"),
            ingestion.ManifestMissingError,
        ),
        (
            ingestion.PublicationManifestIntegrityError("digest"),
            ingestion.ManifestInvalidError,
        ),
        (
            ingestion.PublicationManifestError("read"),
            ingestion.ManifestReadFailedError,
        ),
    ],
)
def test_manifest_core_failures_remain_distinct(
    monkeypatch: pytest.MonkeyPatch,
    core_error: Exception,
    expected: type[Exception],
) -> None:
    def fail(root: object, pub: object) -> Path:
        raise core_error

    monkeypatch.setattr(ingestion, "verify_publication_manifest", fail)
    with pytest.raises(expected):
        ingestion._verify_manifest("workspace", publication())


def test_withdrawal_added_during_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pub = publication()
    referenced = registration()
    withdrawal_calls = 0
    added = withdrawal(pub)
    monkeypatch.setattr(
        ingestion, "get_canonical_publication_record", lambda root, value: pub
    )
    monkeypatch.setattr(
        ingestion,
        "load_academic_work_registration_revision",
        lambda root, work, revision: referenced,
    )
    monkeypatch.setattr(
        ingestion,
        "load_current_academic_work_registration",
        lambda root, work: referenced,
    )
    monkeypatch.setattr(
        ingestion,
        "list_publication_record_set",
        lambda root, work, kind, record_set_id: (pub,),
    )

    def load_withdrawal(root: object, value: str) -> PublicationWithdrawal | None:
        nonlocal withdrawal_calls
        withdrawal_calls += 1
        return None if withdrawal_calls == 1 else added

    monkeypatch.setattr(
        ingestion, "get_canonical_publication_withdrawal", load_withdrawal
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(MANIFEST_BYTES)
    monkeypatch.setattr(
        ingestion, "verify_publication_manifest", lambda root, value: manifest
    )
    with pytest.raises(ingestion.CanonicalStateChangedError):
        ingestion.prepare_publication_invocation(
            tmp_path,
            candidate(pub),
            producer_registry=profile_registry(),
            adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
            authorizer=AllowAuthorizer(),
            authorization_purpose_id="grading_import",
            distribution_version_resolver=lambda name: "1.0.0",
        )


def test_duplicate_student_scope_is_rejected() -> None:
    with pytest.raises(ingestion.IngestionValidationError):
        ingestion.PublicationAuthorizationRequest(
            publication(),
            registration(),
            None,
            "current_selectable",
            "project_evidence",
            "grading_import",
            ("student_1", "student_1"),
        )


def test_core_catalog_and_canonical_preparation_integration(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    work_root = module_work_dir(workspace, WORK)
    work_root.mkdir(parents=True)
    registration_result = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=WORK,
            producer_contract_version="assignment_v1",
            title="Synthetic Work",
            work_kind="assignment",
            academic_intent="summative",
            lifecycle="active",
            source_records=(),
        ),
    )
    assert registration_result.registration.registration_revision == 1

    manifest_relative = (
        "classes/class_2026/modules/synthetic/work/work_1/"
        "exports/manifests/academic_results/1.json"
    )
    manifest = workspace.joinpath(*manifest_relative.split("/"))
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(MANIFEST_BYTES)
    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=WORK,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=("points",),
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="synthetic_manifest_v1",
            manifest_path=manifest_relative,
            academic_work_registration_revision=1,
            expected_manifest_digest=DIGEST,
        ),
    )
    rebuild_academic_catalog(workspace)

    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="synthetic",
                state="current",
                limit=10,
            )
        ),
    )
    assert len(discovered.candidates) == 1
    assert (
        discovered.candidates[0].publication_id
        == published.publication.publication_id
    )

    adapter = SyntheticAdapter()
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        discovered.candidates[0],
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((adapter,)),
        authorizer=AllowAuthorizer(),
        authorization_purpose_id="grading_import",
        distribution_version_resolver=lambda name: "1.0.0",
    )
    assert prepared.projection_request.manifest_bytes == MANIFEST_BYTES
    assert prepared.canonical_context.canonical_state == "current_selectable"
    assert adapter.calls == 0
