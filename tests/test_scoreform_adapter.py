from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from importlib import metadata

import pytest
from pds_core.routing_models import ModuleRecordRef

from meridian.adapters import (
    MERIDIAN_ADAPTER_INTERFACE_VERSION,
    AdapterNotFoundError,
    AdapterProjectionError,
    AdapterProjectionRequest,
    AdapterRegistry,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
)
from meridian.evidence import NativePointValue, NativeScalarValue, NativeStateValue
from meridian.scoreform_adapter import (
    SCOREFORM_ADAPTER_DESCRIPTOR,
    SCOREFORM_ADAPTER_ID,
    SCOREFORM_ADAPTER_KEY,
    SCOREFORM_PROJECTION_CONTRACT_VERSION,
    SCOREFORM_READER_DISTRIBUTION,
    SCOREFORM_READER_VERSION,
    ScoreFormAcademicResultAdapter,
)
from tests.scoreform_test_support import (
    scoreform_manifest_bytes,
    scoreform_publication,
    scoreform_registration,
    scoreform_withdrawal,
)


def projection_request(*, withdrawal: bool = False) -> AdapterProjectionRequest:
    manifest = scoreform_manifest_bytes()
    return AdapterProjectionRequest(
        scoreform_publication(manifest),
        scoreform_registration(),
        scoreform_withdrawal() if withdrawal else None,
        manifest,
    )


def test_descriptor_is_the_exact_released_contract() -> None:
    descriptor = SCOREFORM_ADAPTER_DESCRIPTOR
    assert SCOREFORM_ADAPTER_ID == "scoreform.academic_result"
    assert SCOREFORM_PROJECTION_CONTRACT_VERSION == "1"
    assert SCOREFORM_READER_DISTRIBUTION == "scoreform"
    assert SCOREFORM_READER_VERSION == "0.11.0"
    assert descriptor.adapter_id == SCOREFORM_ADAPTER_ID
    assert descriptor.adapter_interface_version == MERIDIAN_ADAPTER_INTERFACE_VERSION
    assert descriptor.projection_contract_version == "1"
    assert descriptor.key == SCOREFORM_ADAPTER_KEY
    assert descriptor.key.source_record_kind is None
    assert descriptor.key.source_record_contract_version is None
    assert descriptor.supported_capabilities == frozenset(
        {"points", "question_evidence", "multiple_attempts"}
    )
    assert descriptor.supported_producer_reader_versions == frozenset({"0.11.0"})


def test_import_descriptor_registry_and_selection_are_lazy() -> None:
    code = """
import sys
before = set(sys.modules)
import meridian.scoreform_adapter as adapter
from meridian.adapters import AdapterRegistry
assert not any(n == 'scoreform' or n.startswith('scoreform.') for n in sys.modules)
registry = AdapterRegistry((adapter.ScoreFormAcademicResultAdapter(),))
from tests.scoreform_test_support import scoreform_publication, scoreform_registration
record = scoreform_publication(b'{}')
registry.select(record, scoreform_registration())
assert not any(n == 'scoreform' or n.startswith('scoreform.') for n in sys.modules)
assert set(sys.modules) >= before
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("version", ["0.10.0", "0.11.1"])
def test_unsupported_reader_versions_fail_before_projection(version: str) -> None:
    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    with pytest.raises(ProducerReaderVersionUnsupportedError):
        registry.invoke(projection_request(), lambda _: version)


def test_missing_reader_fails_before_projection() -> None:
    def missing(_: str) -> str:
        raise metadata.PackageNotFoundError("scoreform")

    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    with pytest.raises(ProducerReaderUnavailableError):
        registry.invoke(projection_request(), missing)


def test_wrong_exact_contract_keys_are_not_selected() -> None:
    request = projection_request()
    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    wrong_manifest = replace(
        request.publication,
        manifest_contract_version="scoreform_academic_result_manifest_v2",
    )
    wrong_registration = replace(
        request.registration,
        producer_contract_version="scoreform_academic_work_v2",
    )
    present_source = replace(
        request.publication,
        source_record=ModuleRecordRef(
            "scoreform",
            "assignment",
            "synthetic_quiz_alpha",
            "scoreform_academic_work_v1",
        ),
    )
    wrong_producer = scoreform_publication(
        request.manifest_bytes, module_id="other_producer"
    )
    wrong_producer_registration = replace(
        request.registration,
        work=wrong_producer.work,
        source_records=(),
    )
    intervention = replace(
        request.publication,
        source_record=ModuleRecordRef(
            "scoreform",
            "intervention_plan",
            "synthetic_quiz_alpha",
            "intervention_contract_v1",
        ),
        publication_kind="intervention_record_set",
        capabilities=("intervention_status",),
        academic_work_registration_revision=None,
    )
    for publication, registration in (
        (wrong_manifest, request.registration),
        (request.publication, wrong_registration),
        (present_source, request.registration),
        (wrong_producer, wrong_producer_registration),
        (intervention, None),
    ):
        with pytest.raises(AdapterNotFoundError):
            registry.select(publication, registration)


def test_projection_preserves_every_student_attempt_response_and_order() -> None:
    request = projection_request(withdrawal=True)
    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    first = registry.invoke(request, lambda _: "0.11.0")
    second = registry.invoke(request, lambda _: "0.11.0")
    assert first == second
    assert len(first.items) == 24
    assert len({item.item_id for item in first.items}) == 24
    assert all(item.item_id.startswith("scoreform_") for item in first.items)
    assert all(len(item.item_id) == 74 for item in first.items)
    assert tuple(item.subject.student_id for item in first.items[:16]) == (
        "student_synthetic_001",
    ) * 16
    assert tuple(item.result_kind for item in first.items[:10]) == (
        "attempt_points",
        "result_origin",
        "selected_response",
        "question_correctness",
        "selected_response",
        "question_correctness",
        "selected_response_state",
        "question_correctness",
        "attempt_points",
        "result_origin",
    )
    points = [item for item in first.items if item.result_kind == "attempt_points"]
    assert [item.value for item in points] == [
        NativePointValue(2, 3),
        NativePointValue(1, 3),
        NativePointValue(1, 3),
    ]
    assert [item.target.target_id for item in points] == [
        "attempt_1",
        "attempt_2",
        "attempt_1",
    ]
    origins = [
        item.value for item in first.items if item.result_kind == "result_origin"
    ]
    assert origins == [
        NativeScalarValue("pds2_scan"),
        NativeScalarValue("plain_paper_manual"),
        NativeScalarValue("scan_review_manual"),
    ]
    states = [
        item.value
        for item in first.items
        if item.result_kind == "selected_response_state"
    ]
    assert NativeStateValue("blank") in states
    assert NativeStateValue("ambiguous") in states
    correctness = [
        item.value for item in first.items if item.result_kind == "question_correctness"
    ]
    assert all(type(value.value) is bool for value in correctness)
    assert not any("rating" in item.result_kind for item in first.items)
    assert all(item.eligibility.status == "unevaluated" for item in first.items)
    assert all(
        item.provenance.publication == request.publication for item in first.items
    )
    assert all(
        item.provenance.registration == request.registration for item in first.items
    )
    assert all(item.provenance.withdrawal == request.withdrawal for item in first.items)


def test_projection_preserves_ordered_alignment_and_native_provenance() -> None:
    inventory = AdapterRegistry((ScoreFormAcademicResultAdapter(),)).invoke(
        projection_request(), lambda _: "0.11.0"
    )
    question = next(
        item
        for item in inventory.items
        if item.subject.student_id == "student_synthetic_001"
        and item.target.target_id == "question_1"
    )
    assert question.target.standard_ids == (
        "standard_reading_1",
        "standard_close_reading",
    )
    assert [timestamp.kind for timestamp in question.provenance.native.timestamps] == [
        "manifest_generated_at",
        "recorded_at",
    ]
    pds = inventory.items[0].provenance.native
    assert [artifact.kind for artifact in pds.artifacts] == [
        "assignment_source_snapshot",
        "results_history_source_snapshot",
        "retained_source",
    ]
    assert pds.artifacts[0].digest == "1" * 64
    assert pds.artifacts[1].digest == "2" * 64
    assert pds.artifacts[2].path == "scans/source/2026-08-08/synthetic_scan.pdf"
    assert pds.artifacts[2].digest == "3" * 64
    assert [reference.kind for reference in pds.references] == [
        "attempt",
        "issuance",
        "generation",
        "artifact",
        "source_scan",
        "page",
        "route",
        "logical_page",
        "source_page",
    ]
    manual = inventory.items[8].provenance.native
    assert [reference.kind for reference in manual.references] == ["attempt"]
    assert all(artifact.kind != "retained_source" for artifact in manual.artifacts)
    review = inventory.items[16].provenance.native
    assert [reference.kind for reference in review.references] == [
        "attempt",
        "review_failure",
    ]
    question_refs = inventory.items[2].provenance.native.references
    assert question_refs[0].sequence == 1
    assert question_refs[1].kind == "question"
    assert question_refs[1].sequence == 1


@pytest.mark.parametrize(
    "change",
    [
        "record_set",
        "revision",
        "capabilities",
        "manifest_work",
        "manifest_revision",
    ],
)
def test_cross_contract_mismatches_fail_privately(change: str) -> None:
    manifest_kwargs: dict[str, object] = {}
    publication_kwargs: dict[str, object] = {}
    if change == "record_set":
        publication_kwargs["record_set_id"] = "wrong_results"
    elif change == "revision":
        publication_kwargs["revision"] = 2
    elif change == "capabilities":
        publication_kwargs["capabilities"] = ("points", "question_evidence")
    elif change == "manifest_work":
        manifest_kwargs["work_id"] = "synthetic_quiz_other"
    else:
        manifest_kwargs["revision"] = 2
    manifest = scoreform_manifest_bytes(**manifest_kwargs)
    request = AdapterProjectionRequest(
        scoreform_publication(manifest, **publication_kwargs),
        scoreform_registration(),
        None,
        manifest,
    )
    with pytest.raises(AdapterProjectionError) as raised:
        AdapterRegistry((ScoreFormAcademicResultAdapter(),)).invoke(
            request, lambda _: "0.11.0"
        )
    text = str(raised.value)
    assert "student_synthetic" not in text
    assert "selected" not in text
    assert manifest.decode() not in text


def test_noncanonical_manifest_and_reader_import_failure_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = scoreform_manifest_bytes()
    malformed = canonical.rstrip()
    malformed_request = AdapterProjectionRequest(
        scoreform_publication(malformed), scoreform_registration(), None, malformed
    )
    registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
    with pytest.raises(AdapterProjectionError) as raised:
        registry.invoke(malformed_request, lambda _: "0.11.0")
    assert raised.value.__cause__ is not None
    assert malformed.decode() not in str(raised.value)

    import builtins

    original = builtins.__import__

    def blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "scoreform.academic_result_reader":
            raise ImportError("synthetic unavailable reader")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(AdapterProjectionError) as import_error:
        ScoreFormAcademicResultAdapter().project(projection_request())
    assert isinstance(import_error.value.__cause__, ImportError)
