from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import PublicationRecord

import meridian.diagnostics as diagnostics
from meridian.adapters import AdapterRegistry
from meridian.evidence import (
    EvidenceEligibility,
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    ProjectionIdentity,
    StudentSubject,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    expand_grade_item_evidence_detail,
    explain_grade_item_proficiency,
    grade_item_proficiency_explanation_to_dict,
    render_grade_item_proficiency_explanation_text,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheAuthorizationDeniedError,
)
from tests.test_grade_item_proficiency_explanation_provenance import (
    STUDENT_ID,
    _prepared,
    _target,
)

NOW = datetime(2026, 9, 4, 18, tzinfo=UTC)


def _dependencies(*, authorizer: object | None) -> diagnostics.DiagnosticsDependencies:
    return diagnostics.DiagnosticsDependencies(
        producer_registry=PublicationProducerRegistry(()),
        adapter_registry=AdapterRegistry(()),
        authorizer=cast(object, authorizer),  # type: ignore[arg-type]
        distribution_version_resolver=lambda name: "1.0.0",
    )


def _detail_item(source: EvidenceSourceReference) -> EvidenceItem:
    work = source.work
    publication_id = source.publication_id
    registration = AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        work,
        1,
        "synthetic_academic_work_v1",
        "Synthetic Work",
        "assignment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )
    publication = PublicationRecord(
        "1",
        "publication_record",
        publication_id,
        work,
        None,
        "academic_result_set",
        ("standards_ratings",),
        "synthetic_results",
        1,
        "synthetic_manifest_v1",
        (
            f"classes/{work.class_id}/modules/{work.module_id}/work/"
            f"{work.work_id}/exports/manifest.json"
        ),
        "sha256",
        "a" * 64,
        NOW,
        1,
        None,
    )
    provenance = EvidenceProvenance(
        publication,
        registration,
        None,
        ProjectionIdentity(
            "synthetic.adapter",
            "1",
            "synthetic-reader",
            "1.0.0",
        ),
        NativeProvenance((NativeReference("record", "native_rating_1"),)),
    )
    return EvidenceItem(
        item_id=source.item_id,
        subject=StudentSubject(STUDENT_ID),
        target=EvidenceTarget(
            "standard",
            "synthetic_standard_rating",
            standard_ids=(_target().standard_id,),
        ),
        result_kind="overall_standard_rating",
        value=NativeScalarValue(3),
        provenance=provenance,
        eligibility=EvidenceEligibility.unevaluated(),
    )


def _authorized(
    source: EvidenceSourceReference,
    item: EvidenceItem,
) -> AuthorizedProjectionSnapshot:
    snapshot = SimpleNamespace(
        source=SimpleNamespace(publication=item.provenance.publication),
        inventory=EvidenceInventory((item,)),
    )
    stored = SimpleNamespace(
        snapshot=snapshot,
        cache_key=source.cache_key,
        snapshot_digest=source.snapshot_digest,
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(stored=stored),
    )


def test_default_trace_marks_protected_detail_not_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())
    row = next(
        item
        for item in explanation.evidence
        if item.source.item_id == performance_source.item_id
    )

    assert row.authorized_detail.status == "not_requested"
    assert row.authorized_detail.reason_code is None
    assert row.authorized_detail.item is None
    payload = grade_item_proficiency_explanation_to_dict(explanation)
    payload_row = next(
        item
        for item in cast(list[dict[str, object]], payload["evidence"])
        if cast(dict[str, object], item["source"])["item_id"]
        == performance_source.item_id
    )
    assert payload_row["authorized_detail"] == {
        "status": "not_requested",
        "reason_code": None,
        "item": None,
    }
    assert "authorized_detail: not_requested" in (
        render_grade_item_proficiency_explanation_text(explanation)
    )


def test_missing_authorizer_marks_detail_unavailable_before_cache_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())
    row = next(
        item
        for item in explanation.evidence
        if item.source.item_id == performance_source.item_id
    )
    called = False

    def forbidden_loader(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("cache must not open without an authorizer")

    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        forbidden_loader,
    )
    expanded = expand_grade_item_evidence_detail(
        root,
        explanation,
        row.source_key,
        authorization_purpose_id="teacher_trace_detail",
        requested_student_ids=(STUDENT_ID,),
        dependencies=_dependencies(authorizer=None),
    )
    expanded_row = next(
        item for item in expanded.evidence if item.source_key == row.source_key
    )

    assert called is False
    assert expanded_row.aggregation_status == row.aggregation_status
    assert expanded_row.authorized_detail.status == "unavailable"
    assert (
        expanded_row.authorized_detail.reason_code
        == "diagnostics.authorization_provider_required"
    )
    assert expanded_row.authorized_detail.item is None


def test_authorized_detail_uses_existing_diagnostic_cache_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())
    row = next(
        item
        for item in explanation.evidence
        if item.source.item_id == performance_source.item_id
    )
    detail_item = _detail_item(row.source)
    authorized = _authorized(row.source, detail_item)
    observed: dict[str, object] = {}

    def loader(*args: object, **kwargs: object) -> AuthorizedProjectionSnapshot:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return authorized

    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        loader,
    )
    expanded = expand_grade_item_evidence_detail(
        root,
        explanation,
        row.source_key,
        authorization_purpose_id="teacher_trace_detail",
        requested_student_ids=(STUDENT_ID,),
        dependencies=_dependencies(authorizer=object()),
    )
    expanded_row = next(
        item for item in expanded.evidence if item.source_key == row.source_key
    )

    kwargs = cast(dict[str, object], observed["kwargs"])
    assert kwargs["authorization_purpose_id"] == "teacher_trace_detail"
    assert kwargs["requested_student_ids"] == (STUDENT_ID,)
    assert kwargs["authorizer"] is not None
    assert expanded_row.authorized_detail.status == "available"
    detail = expanded_row.authorized_detail.item
    assert detail is not None
    assert detail.item_id == performance_source.item_id
    assert detail.student_id == STUDENT_ID
    assert detail.target_kind == "standard"
    assert detail.result_kind == "overall_standard_rating"
    assert detail.value_kind == "scalar"
    assert detail.value_fields[0].key == "scalar_type"
    assert detail.value_fields[0].value == "integer"
    assert detail.value_fields[1].value == 3
    assert detail.eligibility_status == "unevaluated"

    payload = grade_item_proficiency_explanation_to_dict(expanded)
    payload_row = next(
        item
        for item in cast(list[dict[str, object]], payload["evidence"])
        if cast(dict[str, object], item["source"])["item_id"]
        == performance_source.item_id
    )
    authorized_payload = cast(dict[str, object], payload_row["authorized_detail"])
    assert authorized_payload["status"] == "available"
    assert cast(dict[str, object], authorized_payload["item"])["value_fields"] == {
        "scalar_type": "integer",
        "value": 3,
    }


def test_authorization_denial_does_not_become_academic_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())
    row = next(
        item
        for item in explanation.evidence
        if item.source.item_id == performance_source.item_id
    )

    def denied(*args: object, **kwargs: object) -> object:
        raise ProjectionCacheAuthorizationDeniedError(
            publication_id=row.source.publication_id,
            policy_id="district_trace_policy",
            policy_version="1",
            reason_codes=("authorization.denied",),
        )

    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        denied,
    )
    expanded = expand_grade_item_evidence_detail(
        root,
        explanation,
        row.source_key,
        authorization_purpose_id="teacher_trace_detail",
        requested_student_ids=(STUDENT_ID,),
        dependencies=_dependencies(authorizer=object()),
    )
    expanded_row = next(
        item for item in expanded.evidence if item.source_key == row.source_key
    )

    assert expanded_row.aggregation_status == "performance"
    assert expanded_row.proficiency_level_id == "proficient"
    assert expanded_row.authorized_detail.status == "denied"
    assert expanded_row.authorized_detail.reason_code == "cache.authorization_denied"
    assert expanded_row.authorized_detail.item is None


def test_authorized_snapshot_digest_mismatch_is_trace_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())
    row = next(
        item
        for item in explanation.evidence
        if item.source.item_id == performance_source.item_id
    )
    detail_item = _detail_item(row.source)
    authorized = _authorized(row.source, detail_item)
    authorized = cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(
            stored=SimpleNamespace(
                snapshot=authorized.stored.snapshot,
                cache_key=row.source.cache_key,
                snapshot_digest="f" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        lambda *args, **kwargs: authorized,
    )

    with pytest.raises(ExplanationTraceIntegrityError):
        expand_grade_item_evidence_detail(
            root,
            explanation,
            row.source_key,
            authorization_purpose_id="teacher_trace_detail",
            requested_student_ids=(STUDENT_ID,),
            dependencies=_dependencies(authorizer=object()),
        )
