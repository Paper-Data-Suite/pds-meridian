from __future__ import annotations

import builtins
import hashlib
import subprocess
import sys
from dataclasses import replace
from importlib import metadata

import pytest
from concord.academic_result_manifest import derive_manifest_capabilities
from concord.academic_result_reader import read_academic_result_manifest
from pds_core.publication_records import PublicationRecordValidationError
from pds_core.routing_models import ModuleRecordRef

from meridian.adapters import (
    AdapterCapabilityUnsupportedError,
    AdapterNotFoundError,
    AdapterProjectionError,
    AdapterProjectionRequest,
    AdapterRegistry,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
)
from meridian.concord_adapter import (
    CONCORD_ADAPTER_DESCRIPTOR,
    CONCORD_ADAPTER_ID,
    CONCORD_ADAPTER_KEY,
    CONCORD_PROJECTION_CONTRACT_VERSION,
    CONCORD_READER_DISTRIBUTION,
    CONCORD_READER_VERSION,
    ConcordAcademicResultAdapter,
)
from meridian.evidence import NativeScaledValue, NativeStateValue
from tests.concord_test_support import (
    NOW,
    concord_manifest_bytes,
    concord_publication,
    concord_registration,
    concord_withdrawal,
)


def projection_request(
    *,
    local_only: bool = False,
    standard_only: bool = False,
    rejected_moderation: bool = False,
    withdrawal: bool = False,
) -> AdapterProjectionRequest:
    manifest = concord_manifest_bytes(
        local_only=local_only,
        standard_only=standard_only,
        rejected_moderation=rejected_moderation,
    )
    return AdapterProjectionRequest(
        concord_publication(manifest),
        concord_registration(),
        concord_withdrawal() if withdrawal else None,
        manifest,
    )


def test_descriptor_is_exact_released_contract() -> None:
    descriptor = CONCORD_ADAPTER_DESCRIPTOR
    assert CONCORD_ADAPTER_ID == "concord.academic_result"
    assert CONCORD_PROJECTION_CONTRACT_VERSION == "1"
    assert CONCORD_READER_DISTRIBUTION == "pds-concord"
    assert CONCORD_READER_VERSION == "0.2.0"
    assert descriptor.key == CONCORD_ADAPTER_KEY
    assert descriptor.key.producer_module_id == "concord"
    assert descriptor.key.publication_kind == "academic_result_set"
    assert descriptor.key.manifest_contract_version == (
        "concord_academic_result_manifest_v1"
    )
    assert descriptor.key.producer_contract_version == (
        "concord_academic_work_v1"
    )
    assert descriptor.key.source_record_kind == "activity"
    assert descriptor.key.source_record_contract_version == (
        "concord_activity_v1"
    )
    assert descriptor.supported_capabilities == frozenset(
        {"criterion_scores", "moderated_scores", "standards_ratings"}
    )
    assert descriptor.supported_producer_reader_versions == frozenset(
        {"0.2.0"}
    )


def test_import_registry_selection_and_group_help_dependencies_are_lazy() -> None:
    code = r"""
import sys
from datetime import UTC, datetime
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import (
    PublicationContractSupport,
    PublicationProducerProfile,
    PublicationProducerRegistry,
    SourceRecordContractSupport,
)
from pds_core.publication_records import (
    PublicationRecord,
    PublicationRecordValidationError,
)
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef
import meridian.concord_adapter as adapter
import meridian.diagnostics as diagnostics
from meridian.ingestion import (
    CanonicalPublicationContext,
    PublicationSeriesMember,
    PublicationSeriesObservation,
)

assert not any(n == "concord" or n.startswith("concord.") for n in sys.modules)
work = ModuleWorkRef("concord", "class_2026", "activity_1")
source = ModuleRecordRef(
    "concord", "activity", "activity_1", "concord_activity_v1"
)
now = datetime(2026, 8, 17, tzinfo=UTC)
registration = AcademicWorkRegistration(
    "1",
    "academic_work_registration",
    work,
    1,
    "concord_academic_work_v1",
    "Synthetic",
    "collaborative_activity",
    "formative",
    "active",
    now,
    now,
    (source,),
)
publication = PublicationRecord(
    "1",
    "publication_record",
    "pub_44444444444444444444444444444444",
    work,
    source,
    "academic_result_set",
    ("criterion_scores",),
    "academic_results",
    1,
    "concord_academic_result_manifest_v1",
    (
        "classes/class_2026/modules/concord/work/activity_1/"
        "publications/academic_results/1.json"
    ),
    "sha256",
    "a" * 64,
    now,
    1,
    None,
)
registry = diagnostics.build_builtin_adapter_registry()
registry.select(publication, registration)
assert "concord.academic_result" in {
    binding.descriptor.adapter_id for binding in registry.bindings
}
profile = PublicationProducerProfile(
    "concord",
    "Concord",
    frozenset({"1"}),
    frozenset({"concord_academic_work_v1"}),
    (
        PublicationContractSupport(
            "academic_result_set",
            frozenset({"concord_academic_result_manifest_v1"}),
            frozenset(
                {
                    "criterion_scores",
                    "moderated_scores",
                    "standards_ratings",
                }
            ),
            (
                SourceRecordContractSupport(
                    "activity",
                    frozenset({"concord_activity_v1"}),
                    False,
                ),
            ),
            False,
        ),
    ),
)
series = PublicationSeriesObservation(
    (PublicationSeriesMember(publication, None),),
    publication.publication_id,
    0,
    publication.publication_id,
    "current_selectable",
    None,
)
context = CanonicalPublicationContext(
    publication,
    registration,
    registration,
    series,
    None,
)
dependencies = diagnostics.DiagnosticsDependencies(
    producer_registry=PublicationProducerRegistry((profile,)),
    adapter_registry=registry,
    distribution_version_resolver=lambda name: "0.2.0",
)
support = diagnostics.diagnose_publication_support(context, dependencies)
assert support.overall_state == "support_ready"
assert support.reader_distribution == "pds-concord"
assert not any(n == "concord" or n.startswith("concord.") for n in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", ["0.1.9", "0.2.1"])
def test_unsupported_reader_versions_fail_before_projection(
    version: str,
) -> None:
    registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    with pytest.raises(ProducerReaderVersionUnsupportedError):
        registry.invoke(projection_request(), lambda _: version)


def test_missing_reader_fails_before_projection() -> None:
    def missing(_: str) -> str:
        raise metadata.PackageNotFoundError("pds-concord")

    registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    with pytest.raises(ProducerReaderUnavailableError):
        registry.invoke(projection_request(), missing)


def test_wrong_exact_contract_keys_are_not_selected() -> None:
    request = projection_request()
    registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    variants = (
        (
            replace(
                request.publication,
                manifest_contract_version="other_manifest_v1",
            ),
            request.registration,
        ),
        (
            request.publication,
            replace(
                request.registration,
                producer_contract_version="other_contract_v1",
            ),
        ),
        (
            replace(
                request.publication,
                source_record=ModuleRecordRef(
                    "concord",
                    "session",
                    "activity_1",
                    "concord_activity_v1",
                ),
            ),
            request.registration,
        ),
        (
            replace(
                request.publication,
                source_record=ModuleRecordRef(
                    "concord",
                    "activity",
                    "activity_1",
                    "other_activity_v1",
                ),
            ),
            request.registration,
        ),
    )
    for publication, registration in variants:
        with pytest.raises(AdapterNotFoundError):
            registry.select(publication, registration)

    missing_source = replace(request.publication, source_record=None)
    with pytest.raises(AdapterNotFoundError):
        registry.select(missing_source, request.registration)

    unsupported_capability = replace(
        request.publication,
        capabilities=(
            "criterion_scores",
            "standards_ratings",
            "moderated_scores",
            "points",
        ),
    )
    with pytest.raises(AdapterCapabilityUnsupportedError):
        registry.select(unsupported_capability, request.registration)


def test_projection_preserves_group_history_scale_states_and_moderation() -> None:
    request = projection_request(withdrawal=True)
    registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    first = registry.invoke(request, lambda _: "0.2.0")
    second = registry.invoke(request, lambda _: "0.2.0")

    assert first == second
    assert len(first.items) == 4
    assert len({item.item_id for item in first.items}) == 4
    assert all(item.item_id.startswith("concord_") for item in first.items)
    assert all(len(item.item_id) == 72 for item in first.items)
    assert all("group_1" not in item.item_id for item in first.items)
    assert all(item.eligibility.status == "unevaluated" for item in first.items)
    assert all(
        item.provenance.publication == request.publication
        for item in first.items
    )
    assert all(
        item.provenance.registration == request.registration
        for item in first.items
    )
    assert all(
        item.provenance.withdrawal == request.withdrawal
        for item in first.items
    )

    predecessor, current, standard, absent = first.items
    assert predecessor.subject is None
    assert current.subject is None
    assert standard.subject is not None
    assert standard.subject.student_id == "student_1"
    assert absent.subject is not None
    assert absent.subject.student_id == "student_2"

    assert predecessor.target.target_kind == "concord_group"
    assert predecessor.target.target_id == "group_1"
    assert predecessor.target.owning_system == "concord"
    assert predecessor.target.contract_version == "concord_group_v1"
    assert current.target == predecessor.target
    assert standard.target.target_kind == "core_student"
    assert standard.target.owning_system == "core"
    assert standard.target.standard_ids == ("standard_ela_1",)
    assert absent.target.target_kind == "core_student"
    assert absent.target.owning_system == "core"
    assert absent.target.standard_ids == ("standard_ela_1",)

    assert [item.result_kind for item in first.items] == [
        "local_score",
        "local_score",
        "standard_backed_score",
        "standard_backed_score",
    ]
    assert isinstance(predecessor.value, NativeScaledValue)
    assert predecessor.value.value == 0
    assert isinstance(current.value, NativeScaledValue)
    assert current.value.value == 4
    assert isinstance(standard.value, NativeScaledValue)
    assert standard.value.value == 2
    assert absent.value == NativeStateValue("absent")

    scale = current.value.scale
    assert scale.scale_id == "scale_2"
    assert scale.lineage_id == "scale_lineage_1"
    assert scale.name == "Synthetic collaboration rubric"
    assert scale.revision == 2
    assert scale.scale_type == "ordinal"
    assert scale.status == "active"
    assert scale.supersedes_scale_id == "scale_1"
    assert scale.order_is_meaningful
    assert [level.value for level in scale.levels] == [0, 2, 4]
    assert [level.position for level in scale.levels] == [1, 3, 7]
    assert [level.meaning for level in scale.levels] == [
        "Initial evidence.",
        "Partial command.",
        "Consistent command.",
    ]

    predecessor_refs = predecessor.provenance.native.references
    current_refs = current.provenance.native.references
    assert any(
        ref.kind == "score_current_state"
        and ref.identifier == "superseded"
        for ref in predecessor_refs
    )
    assert any(
        ref.kind == "score_supersedes"
        and ref.identifier == "score_001"
        for ref in current_refs
    )
    assert any(
        ref.kind == "score_evidence_link"
        and ref.identifier == "link_002"
        for ref in current_refs
    )
    assert any(
        ref.kind == "moderation_status"
        and ref.identifier == "accepted_with_qualification"
        for ref in current_refs
    )
    assert any(
        ref.kind == "moderation_permitted_use"
        and ref.identifier == "support_group_score"
        for ref in current_refs
    )
    moderation_subject_ids = {
        ref.identifier
        for ref in current_refs
        if ref.kind == "moderation_subject_id"
    }
    assert moderation_subject_ids == {"student_1", "student_2"}
    assert current.subject is None
    assert current.provenance.native.artifacts == ()

    standard_refs = standard.provenance.native.references
    assert any(
        ref.kind == "criterion" and ref.identifier == "criterion_standard"
        for ref in standard_refs
    )
    assert any(
        ref.kind == "score_basis"
        and ref.identifier == "professional_judgment"
        for ref in standard_refs
    )
    assert any(
        ref.kind == "score_current_state" and ref.identifier == "current"
        for ref in standard_refs
    )
    assert standard.provenance.native.timestamps[1].value == NOW.replace(
        minute=10
    )

    absent_refs = absent.provenance.native.references
    assert any(
        ref.kind == "score_status_reason"
        and ref.identifier == "absent"
        for ref in absent_refs
    )
    assert [stamp.kind for stamp in absent.provenance.native.timestamps] == [
        "manifest_generated_at",
        "score_scored_at",
        "score_status_recorded_at",
    ]


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("local", ("criterion_scores",)),
        ("standard", ("criterion_scores", "standards_ratings")),
        (
            "moderated",
            ("criterion_scores", "standards_ratings", "moderated_scores"),
        ),
    ],
)
def test_content_dependent_capability_sets_are_exact(
    mode: str,
    expected: tuple[str, ...],
) -> None:
    manifest_bytes = concord_manifest_bytes(
        local_only=mode == "local",
        standard_only=mode == "standard",
    )
    manifest = read_academic_result_manifest(manifest_bytes)
    assert derive_manifest_capabilities(manifest) == expected
    publication = concord_publication(manifest_bytes)
    assert frozenset(publication.capabilities) == frozenset(expected)

    request = AdapterProjectionRequest(
        publication,
        concord_registration(),
        None,
        manifest_bytes,
    )
    inventory = AdapterRegistry((ConcordAcademicResultAdapter(),)).invoke(
        request,
        lambda _: "0.2.0",
    )
    assert inventory.items
    assert all(
        item.eligibility.status == "unevaluated" for item in inventory.items
    )
    if mode == "local":
        assert len(inventory.items) == 1
        assert inventory.items[0].subject is None
        assert isinstance(inventory.items[0].value, NativeScaledValue)
        assert inventory.items[0].value.value == 0


def test_rejected_moderation_is_preserved_without_policy_inference() -> None:
    request = projection_request(rejected_moderation=True)
    inventory = AdapterRegistry((ConcordAcademicResultAdapter(),)).invoke(
        request,
        lambda _: "0.2.0",
    )
    current = inventory.items[1]
    assert current.subject is None
    assert isinstance(current.value, NativeScaledValue)
    assert current.value.value == 4
    assert current.eligibility.status == "unevaluated"
    references = current.provenance.native.references
    assert any(
        ref.kind == "moderation_status" and ref.identifier == "rejected"
        for ref in references
    )
    assert any(
        ref.kind == "moderation_permitted_use"
        and ref.identifier == "not_be_used_for_scoring"
        for ref in references
    )


def test_core_rejects_source_record_module_mismatch_before_adapter() -> None:
    request = projection_request()
    with pytest.raises(
        PublicationRecordValidationError,
        match="source_record.module_id must match work.module_id",
    ):
        replace(
            request.publication,
            source_record=ModuleRecordRef(
                "other",
                "activity",
                "activity_1",
                "concord_activity_v1",
            ),
        )


@pytest.mark.parametrize(
    ("publication_change", "registration_change"),
    [
        ("capabilities", None),
        ("revision", None),
        ("source_record", None),
        (None, "work_kind"),
        (None, "source_records"),
    ],
)
def test_cross_contract_mismatches_fail_privately(
    publication_change: str | None,
    registration_change: str | None,
) -> None:
    request = projection_request()
    publication = request.publication
    registration = request.registration
    assert registration is not None

    if publication_change == "capabilities":
        publication = replace(
            publication,
            capabilities=("criterion_scores",),
        )
    elif publication_change == "revision":
        publication = replace(
            publication,
            record_set_revision=2,
        )
    elif publication_change == "source_record":
        publication = replace(
            publication,
            source_record=ModuleRecordRef(
                "concord",
                "activity",
                "activity_other",
                "concord_activity_v1",
            ),
        )
    if registration_change == "work_kind":
        registration = replace(registration, work_kind="assignment")
    elif registration_change == "source_records":
        registration = replace(registration, source_records=())

    changed = AdapterProjectionRequest(
        publication,
        registration,
        None,
        request.manifest_bytes,
    )
    with pytest.raises(AdapterProjectionError) as raised:
        AdapterRegistry((ConcordAcademicResultAdapter(),)).invoke(
            changed,
            lambda _: "0.2.0",
        )
    message = str(raised.value)
    assert "group_1" not in message
    assert "student_1" not in message
    assert "Moderated evidence" not in message


def test_noncanonical_bytes_reader_import_failure_and_artifact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_request = projection_request()
    malformed = canonical_request.manifest_bytes.rstrip()
    publication = replace(
        canonical_request.publication,
        manifest_digest=hashlib.sha256(malformed).hexdigest(),
    )
    malformed_request = AdapterProjectionRequest(
        publication,
        canonical_request.registration,
        None,
        malformed,
    )
    with pytest.raises(AdapterProjectionError) as malformed_error:
        AdapterRegistry((ConcordAcademicResultAdapter(),)).invoke(
            malformed_request,
            lambda _: "0.2.0",
        )
    assert malformed_error.value.__cause__ is not None
    assert malformed.decode() not in str(malformed_error.value)

    original = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "concord.academic_result_reader":
            raise ImportError("synthetic unavailable reader")
        if name.startswith("concord.academic_result_artifacts"):
            raise AssertionError("Artifact reader must never be imported")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(AdapterProjectionError) as import_error:
        ConcordAcademicResultAdapter().project(canonical_request)
    assert isinstance(import_error.value.__cause__, ImportError)

    monkeypatch.setattr(builtins, "__import__", original)
    inventory = ConcordAcademicResultAdapter().project(canonical_request)
    assert len(inventory.items) == 4
    assert not any(
        name.startswith("concord.academic_result_artifacts")
        for name in sys.modules
    )
