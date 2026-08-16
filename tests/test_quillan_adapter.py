from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from importlib import metadata

import pytest
from pds_core.routing_models import ModuleRecordRef

from meridian.adapters import (
    AdapterNotFoundError,
    AdapterProjectionError,
    AdapterProjectionRequest,
    AdapterRegistry,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
)
from meridian.evidence import (
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.quillan_adapter import (
    QUILLAN_ADAPTER_DESCRIPTOR,
    QUILLAN_ADAPTER_ID,
    QUILLAN_ADAPTER_KEY,
    QUILLAN_PROJECTION_CONTRACT_VERSION,
    QUILLAN_READER_DISTRIBUTION,
    QUILLAN_READER_VERSION,
    QuillanAcademicResultAdapter,
)
from tests.quillan_test_support import (
    quillan_manifest_bytes,
    quillan_publication,
    quillan_registration,
    quillan_withdrawal,
)


def projection_request(*, withdrawal: bool = False) -> AdapterProjectionRequest:
    manifest = quillan_manifest_bytes()
    return AdapterProjectionRequest(
        quillan_publication(manifest),
        quillan_registration(),
        quillan_withdrawal() if withdrawal else None,
        manifest,
    )


def test_descriptor_is_exact_released_contract() -> None:
    descriptor = QUILLAN_ADAPTER_DESCRIPTOR
    assert QUILLAN_ADAPTER_ID == "quillan.academic_result"
    assert QUILLAN_PROJECTION_CONTRACT_VERSION == "1"
    assert QUILLAN_READER_DISTRIBUTION == "quillan"
    assert QUILLAN_READER_VERSION == "0.9.0"
    assert descriptor.key == QUILLAN_ADAPTER_KEY
    assert descriptor.key.producer_module_id == "quillan"
    assert descriptor.key.publication_kind == "academic_result_set"
    assert descriptor.key.manifest_contract_version == (
        "quillan_academic_result_manifest_v1"
    )
    assert descriptor.key.producer_contract_version == "quillan_academic_work_v1"
    assert descriptor.key.source_record_kind is None
    assert descriptor.key.source_record_contract_version is None
    assert descriptor.supported_capabilities == frozenset({"standards_ratings"})
    assert descriptor.supported_producer_reader_versions == frozenset({"0.9.0"})


def test_import_descriptor_registry_and_selection_are_lazy() -> None:
    code = """
import sys
import meridian.quillan_adapter as adapter
from meridian.adapters import AdapterRegistry
assert not any(n == 'quillan' or n.startswith('quillan.') for n in sys.modules)
from tests.quillan_test_support import quillan_publication, quillan_registration
registry = AdapterRegistry((adapter.QuillanAcademicResultAdapter(),))
registry.select(quillan_publication(b'{}'), quillan_registration())
assert not any(n == 'quillan' or n.startswith('quillan.') for n in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", ["0.8.9", "0.9.1"])
def test_unsupported_reader_versions_fail_before_projection(version: str) -> None:
    registry = AdapterRegistry((QuillanAcademicResultAdapter(),))
    with pytest.raises(ProducerReaderVersionUnsupportedError):
        registry.invoke(projection_request(), lambda _: version)


def test_missing_reader_fails_before_projection() -> None:
    def missing(_: str) -> str:
        raise metadata.PackageNotFoundError("quillan")

    with pytest.raises(ProducerReaderUnavailableError):
        AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
            projection_request(), missing
        )


def test_wrong_exact_contract_keys_are_not_selected() -> None:
    request = projection_request()
    registry = AdapterRegistry((QuillanAcademicResultAdapter(),))
    wrong_producer = quillan_publication(
        request.manifest_bytes, module_id="other_producer"
    )
    wrong_producer_registration = replace(
        request.registration,
        work=wrong_producer.work,
        source_records=(),
    )
    wrong_kind = replace(
        request.publication,
        publication_kind="intervention_record_set",
        capabilities=("intervention_status",),
        academic_work_registration_revision=None,
    )
    variants = (
        (
            replace(request.publication, manifest_contract_version="wrong_v1"),
            request.registration,
        ),
        (
            request.publication,
            replace(request.registration, producer_contract_version="wrong_v1"),
        ),
        (
            replace(
                request.publication,
                source_record=ModuleRecordRef("quillan", "assignment", "native", "2"),
            ),
            request.registration,
        ),
        (wrong_producer, wrong_producer_registration),
        (wrong_kind, None),
    )
    for publication, registration in variants:
        with pytest.raises(AdapterNotFoundError):
            registry.select(publication, registration)


def test_projection_preserves_order_states_scale_and_missingness() -> None:
    request = projection_request(withdrawal=True)
    registry = AdapterRegistry((QuillanAcademicResultAdapter(),))
    first = registry.invoke(request, lambda _: "0.9.0")
    second = registry.invoke(request, lambda _: "0.9.0")
    assert first == second
    assert len(first.items) == 17
    assert len({item.item_id for item in first.items}) == 17
    assert all(item.item_id.startswith("quillan_") for item in first.items)
    assert all("student_synthetic" not in item.item_id for item in first.items)
    assert all(item.eligibility.status == "unevaluated" for item in first.items)
    assert tuple(item.result_kind for item in first.items[:5]) == (
        "review_state",
        "minimum_requirement_status",
        "standard_applicability",
        "standard_observation_rating",
        "standard_applicability",
    )
    assert tuple(item.result_kind for item in first.items[-3:]) == (
        "review_state",
        "review_disposition",
        "minimum_requirement_status",
    )
    assert all(
        item.provenance.publication == request.publication for item in first.items
    )
    assert all(
        item.provenance.registration == request.registration for item in first.items
    )
    assert all(item.provenance.withdrawal == request.withdrawal for item in first.items)

    scaled = [
        item.value for item in first.items if isinstance(item.value, NativeScaledValue)
    ]
    assert [value.value for value in scaled] == [0, 0]
    assert all(
        [level.value for level in value.scale.levels] == [0, 2, 4] for value in scaled
    )
    assert all(value.scale.contract_version is None for value in scaled)
    assert [level.label for level in scaled[0].scale.levels] == [
        "Beginning",
        "Developing",
        "Secure",
    ]
    assert not any(item.result_kind == "percentage" for item in first.items)

    ratings = [
        item
        for item in first.items
        if item.result_kind == "standard_observation_rating"
    ]
    assert [item.value for item in ratings[:3]] == [
        NativeStateValue("unrated"),
        NativeStateValue("unrated"),
        NativeStateValue("unrated"),
    ]
    assert isinstance(ratings[3].value, NativeScaledValue)
    presence = [
        item.value
        for item in first.items
        if item.result_kind == "standard_evidence_presence"
    ]
    assert presence == [
        NativeScalarValue(False),
        NativeScalarValue(True),
        NativeScalarValue(True),
    ]
    applicability = [
        item.value
        for item in first.items
        if item.result_kind == "standard_applicability"
    ]
    assert applicability[0] == NativeScalarValue(False)
    assert type(applicability[0].value) is bool


def test_released_reader_and_adapter_preserve_broad_native_text_exactly() -> None:
    from quillan.academic_result_reader import read_academic_result_manifest

    scale_id = " synthetic / scale "
    unit_id = "Body / 1"
    observation_id = "Observation / A"
    standard_id = " Standard / A "
    label = "Developing / Emerging"
    description = "First line\nSecond line"
    manifest = quillan_manifest_bytes(
        scale_id=scale_id,
        rated_unit_id=unit_id,
        rated_observation_id=observation_id,
        evidence_standard_id=standard_id,
        minimum_scale_label=label,
        minimum_scale_description=description,
    )

    released = read_academic_result_manifest(manifest)
    assert released.assignment.rating_scale.scale_id == scale_id
    request = AdapterProjectionRequest(
        quillan_publication(manifest), quillan_registration(), None, manifest
    )
    inventory = AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
        request, lambda _: "0.9.0"
    )
    observation = next(
        item
        for item in inventory.items
        if item.result_kind == "standard_observation_rating"
        and item.target.target_id == unit_id
    )
    overall = next(
        item
        for item in inventory.items
        if item.result_kind == "overall_standard_rating"
        and item.target.target_id == standard_id
    )

    assert observation.target.target_id == unit_id
    assert observation.target.standard_ids == (standard_id,)
    assert (
        next(
            reference.identifier
            for reference in observation.provenance.native.references
            if reference.kind == "observation"
        )
        == observation_id
    )
    assert isinstance(observation.value, NativeScaledValue)
    assert observation.value.value == 0
    assert observation.value.scale.scale_id == scale_id
    assert observation.value.scale.levels[0].label == label
    assert observation.value.scale.levels[0].description == description
    assert isinstance(overall.value, NativeScaledValue)
    assert overall.value.value == 0
    assert overall.value.scale == observation.value.scale
    assert all(item.item_id.startswith("quillan_") for item in inventory.items)
    assert all(len(item.item_id) == 72 for item in inventory.items)
    assert all("student_synthetic" not in item.item_id for item in inventory.items)
    assert all(item.eligibility.status == "unevaluated" for item in inventory.items)


@pytest.mark.parametrize(
    ("review_state", "minimum_status"),
    [
        ("not_started", "not_checked"),
        ("requirements_checked", "met"),
        ("returned_without_full_review", "returned_without_full_review"),
        ("ratings_complete", "unmet_continue_review"),
        ("exported", "met"),
    ],
)
def test_review_and_minimum_states_remain_exact_nonnumeric_values(
    review_state: str, minimum_status: str
) -> None:
    manifest = quillan_manifest_bytes(
        secondary_review_state=review_state,
        secondary_minimum_status=minimum_status,
    )
    request = AdapterProjectionRequest(
        quillan_publication(manifest), quillan_registration(), None, manifest
    )
    inventory = AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
        request, lambda _: "0.9.0"
    )
    student_items = [
        item
        for item in inventory.items
        if item.subject.student_id == "student_synthetic_002"
    ]
    assert student_items[0].value == NativeStateValue(review_state)
    assert student_items[-1].value == NativeStateValue(minimum_status)
    assert all(isinstance(item.value, NativeStateValue) for item in student_items)
    dispositions = [
        item for item in student_items if item.result_kind == "review_disposition"
    ]
    assert len(dispositions) == (
        1 if review_state == "returned_without_full_review" else 0
    )


def test_targets_and_provenance_preserve_native_semantics_without_text() -> None:
    inventory = AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
        projection_request(), lambda _: "0.9.0"
    )
    observation = next(
        item
        for item in inventory.items
        if item.result_kind == "standard_observation_rating"
        and item.target.target_id == "body_4"
    )
    assert observation.target.target_kind == "review_unit"
    assert observation.target.parent_target is not None
    assert observation.target.parent_target.target_kind == "submission"
    assert observation.target.parent_target.target_id is None
    assert observation.target.standard_ids == ("standard_evidence",)
    assert observation.target.sequence == 4
    native = observation.provenance.native
    assert [artifact.kind for artifact in native.artifacts] == [
        "assignment_source_snapshot",
        "submission_source_snapshot",
        "review_source_snapshot",
    ]
    assert all(
        artifact.path is not None and not artifact.path.startswith(("/", "C:"))
        for artifact in native.artifacts
    )
    assert [timestamp.kind for timestamp in native.timestamps] == [
        "manifest_generated_at",
        "observation_updated_at",
    ]
    assert {reference.kind for reference in native.references} >= {
        "review_unit",
        "review_unit_sequence",
        "observation",
        "standard",
    }
    pds_references = {
        reference.kind for reference in inventory.items[0].provenance.native.references
    }
    assert {"issuance", "generation", "artifact"} <= pds_references
    plain_references = {
        reference.kind for reference in inventory.items[-1].provenance.native.references
    }
    assert not {"issuance", "generation", "artifact"} & plain_references
    rendered = repr(inventory)
    for forbidden in (
        "Synthetic public feedback.",
        "Synthetic prompt text",
        "retained_source_path",
        "routed_evidence_path",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("manifest_kwargs", "publication_kwargs"),
    [
        ({}, {"record_set_id": "wrong_results"}),
        ({}, {"revision": 2}),
        ({}, {"capabilities": ()}),
        ({"work_id": "synthetic_essay_other"}, {}),
        ({"record_set_id": "other_results"}, {}),
        ({"revision": 2}, {}),
    ],
)
def test_cross_contract_mismatches_fail_privately(
    manifest_kwargs: dict[str, object], publication_kwargs: dict[str, object]
) -> None:
    manifest = quillan_manifest_bytes(**manifest_kwargs)
    request = AdapterProjectionRequest(
        quillan_publication(manifest, **publication_kwargs),
        quillan_registration(),
        None,
        manifest,
    )
    with pytest.raises(AdapterProjectionError) as raised:
        AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
            request, lambda _: "0.9.0"
        )
    assert "student_synthetic" not in str(raised.value)
    assert "Synthetic public feedback" not in str(raised.value)


def test_noncanonical_bytes_and_reader_import_failure_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = quillan_manifest_bytes()
    malformed = canonical.rstrip()
    request = AdapterProjectionRequest(
        quillan_publication(malformed), quillan_registration(), None, malformed
    )
    with pytest.raises(AdapterProjectionError) as raised:
        AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
            request, lambda _: "0.9.0"
        )
    assert raised.value.__cause__ is not None
    assert malformed.decode() not in str(raised.value)

    import builtins

    original = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "quillan.academic_result_reader":
            raise ImportError("synthetic unavailable reader")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(AdapterProjectionError) as import_error:
        QuillanAcademicResultAdapter().project(projection_request())
    assert isinstance(import_error.value.__cause__, ImportError)
