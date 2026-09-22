from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreviewRequest
from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingDefinitionReference,
    ReportingSnapshotPredecessor,
    ReportingSnapshotReference,
)
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM,
    REPORTING_SNAPSHOT_RECORD_TYPE,
    REPORTING_SNAPSHOT_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    ReportingSnapshotIntegrityError,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotProvenanceBinding,
    ReportingSnapshotRequestValidationError,
    ReportingSnapshotWorkEvidenceRequest,
    compose_reporting_snapshot,
    reporting_snapshot_build_request_from_json_bytes,
    reporting_snapshot_build_request_from_preview_requests,
    reporting_snapshot_build_request_sha256,
    reporting_snapshot_build_request_to_json_bytes,
    reporting_snapshot_from_dict,
    reporting_snapshot_from_json_bytes,
    reporting_snapshot_provenance_binding,
    reporting_snapshot_provenance_binding_from_dict,
    reporting_snapshot_provenance_binding_to_dict,
    reporting_snapshot_reference,
    reporting_snapshot_to_dict,
    reporting_snapshot_to_json_bytes,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 4, 30, tzinfo=UTC)


def _definition_ref(*, class_id: str = CLASS_ID) -> ReportingDefinitionReference:
    return ReportingDefinitionReference(
        class_id=class_id,
        definition_id="quarter_grade_report",
        definition_revision=1,
        definition_sha256="a" * 64,
    )


def _target(
    student_id: str = "student_001",
    *,
    family: str = "standards_based",
    class_id: str = CLASS_ID,
    period: AcademicPeriodRef = PERIOD,
    calendar_revision: int = 1,
) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=class_id,
        student_id=student_id,
        target_period=period,
        calendar_revision=calendar_revision,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _grade_request(
    student_id: str = "student_001",
    *,
    family: str = "standards_based",
    calendar_revision: int = 1,
) -> ReportingSnapshotGradeRequest:
    target = _target(
        student_id,
        family=family,
        calendar_revision=calendar_revision,
    )
    return ReportingSnapshotGradeRequest(
        target=target,
        work_evidence=() if family in {"conventional", "hybrid"} else None,
    )


def _build_request(
    *requests: ReportingSnapshotGradeRequest,
    definition: ReportingDefinitionReference | None = None,
    requested_at: datetime = NOW,
    predecessor: ReportingSnapshotPredecessor | None = None,
) -> ReportingSnapshotBuildRequest:
    if not requests:
        requests = (_grade_request(),)
    return ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition or _definition_ref(),
        grade_requests=tuple(requests),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze reviewed Quarter 1 Grade report.",
        requested_at=requested_at,
        predecessor=predecessor,
    )


def _summary(*, requested: int, available: int) -> dict[str, int]:
    unavailable = requested - available
    return {
        "requested_count": requested,
        "available_count": available,
        "unavailable_count": unavailable,
        "base_calculated_count": 0,
        "base_blocked_count": 0,
        "base_insufficient_count": 0,
        "current_count": 0,
        "stale_count": 0,
        "effective_numeric_count": 0,
        "effective_nonnumeric_count": 0,
        "effective_base_count": 0,
        "effective_override_count": 0,
        "effective_none_count": 0,
    }


def _target_dict(target: GradePreviewTarget) -> dict[str, object]:
    return {
        "class_id": target.class_id,
        "student_id": target.student_id,
        "target_period": {
            "school_year": target.target_period.school_year,
            "period_id": target.target_period.period_id,
        },
        "calendar_revision": target.calendar_revision,
        "calculation_family": target.calculation_family,
    }


def _unavailable_preview(*targets: GradePreviewTarget):
    ordered = tuple(
        sorted(
            targets,
            key=lambda value: (
                value.class_id,
                value.student_id,
                value.target_period.school_year,
                value.target_period.period_id,
                value.calendar_revision,
                value.calculation_family,
            ),
        )
    )
    data = {
        "summary": _summary(requested=len(ordered), available=0),
        "rows": [
            {
                "target": _target_dict(target),
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
            for target in ordered
        ],
    }
    encoded = (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return frozen_grade_report_preview_from_json_bytes(encoded)


def _calendar_binding(*, revision: int = 1) -> ReportingSnapshotProvenanceBinding:
    return reporting_snapshot_provenance_binding(
        authority_kind="academic_period_calendar",
        reference_kind="academic_period_calendar_reference",
        reference={
            "school_year": PERIOD.school_year,
            "calendar_revision": revision,
        },
    )


def _policy_binding() -> ReportingSnapshotProvenanceBinding:
    return reporting_snapshot_provenance_binding(
        authority_kind="grade_policy_revision",
        reference_kind="grade_policy_reference",
        reference={
            "class_id": CLASS_ID,
            "policy_id": "course_grade",
            "policy_revision": 1,
            "policy_sha256": "b" * 64,
        },
    )


def _snapshot(
    *,
    snapshot_id: str = "snapshot_001",
    request: ReportingSnapshotBuildRequest | None = None,
    created_at: datetime | None = None,
    bindings: tuple[ReportingSnapshotProvenanceBinding, ...] | None = None,
):
    exact_request = request or _build_request()
    preview = _unavailable_preview(
        *(item.target for item in exact_request.grade_requests)
    )
    return compose_reporting_snapshot(
        snapshot_id=snapshot_id,
        build_request=exact_request,
        report_preview=preview,
        provenance_bindings=bindings or (_calendar_binding(), _policy_binding()),
        created_at=created_at or exact_request.requested_at,
    )


def test_build_request_adapter_preserves_explicit_standards_target() -> None:
    target = _target()
    request = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=_definition_ref(),
        requests=(GradeReportPreviewRequest(target),),
        actor=ReportingActor("teacher", "teacher_local"),
        requested_at=NOW,
        rationale=None,
    )

    assert request.grade_requests == (
        ReportingSnapshotGradeRequest(target=target, work_evidence=None),
    )
    assert request.target_period == PERIOD
    assert request.calendar_revision == 1


def test_build_request_is_canonically_sorted_and_digest_stable() -> None:
    first = _grade_request("student_001")
    second = _grade_request("student_002")

    a = _build_request(second, first)
    b = _build_request(first, second)

    assert a == b
    assert tuple(item.target.student_id for item in a.grade_requests) == (
        "student_001",
        "student_002",
    )
    assert reporting_snapshot_build_request_to_json_bytes(a) == (
        reporting_snapshot_build_request_to_json_bytes(b)
    )
    assert reporting_snapshot_build_request_sha256(a) == (
        reporting_snapshot_build_request_sha256(b)
    )


def test_build_request_rejects_duplicate_or_mixed_scope() -> None:
    first = _grade_request()
    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="duplicate exact Grade targets",
    ):
        _build_request(first, first)

    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="calendar revision",
    ):
        _build_request(first, _grade_request("student_002", calendar_revision=2))

    other_period = ReportingSnapshotGradeRequest(
        target=_target(
            "student_002",
            period=AcademicPeriodRef("2026-2027", "q2"),
        ),
        work_evidence=None,
    )
    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="one exact Academic Period",
    ):
        _build_request(first, other_period)


def test_build_request_rejects_definition_or_predecessor_class_mismatch() -> None:
    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="definition class",
    ):
        _build_request(definition=_definition_ref(class_id="different_class"))

    predecessor = ReportingSnapshotPredecessor(
        "supersedes",
        ReportingSnapshotReference("different_class", "snapshot_old", "c" * 64),
    )
    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="predecessor snapshot class",
    ):
        _build_request(predecessor=predecessor)


def test_request_component_contracts_preserve_exact_projection_identity() -> None:
    first = ReportingSnapshotProjectionInputReference(
        "pub_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "1" * 64,
        "2" * 64,
    )
    second = ReportingSnapshotProjectionInputReference(
        "pub_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "3" * 64,
        "4" * 64,
    )
    evidence = ReportingSnapshotWorkEvidenceRequest(
        grade_item_id="quiz_1",
        work=ModuleWorkRef("scoreform", CLASS_ID, "quiz_1"),
        status="available",
        projection_snapshots=(second, first),
    )

    assert evidence.projection_snapshots == (first, second)

    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="must not carry projections",
    ):
        ReportingSnapshotWorkEvidenceRequest(
            grade_item_id="quiz_1",
            work=ModuleWorkRef("scoreform", CLASS_ID, "quiz_1"),
            status="missing",
            projection_snapshots=(first,),
        )


def test_family_specific_request_evidence_boundary_is_explicit() -> None:
    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="conventional request requires work_evidence",
    ):
        ReportingSnapshotGradeRequest(
            target=_target(family="conventional"),
            work_evidence=None,
        )

    with pytest.raises(
        ReportingSnapshotRequestValidationError,
        match="standards-based request must not carry",
    ):
        ReportingSnapshotGradeRequest(
            target=_target(),
            work_evidence=(),
        )


def test_build_request_round_trips_canonically_and_rejects_alternate_bytes() -> None:
    request = _build_request()
    encoded = reporting_snapshot_build_request_to_json_bytes(request)

    assert reporting_snapshot_build_request_from_json_bytes(encoded) == request
    assert encoded.endswith(b"\n")

    altered = encoded[:-1] + b" \n"
    with pytest.raises(
        Exception,
        match="canonical encoding",
    ):
        reporting_snapshot_build_request_from_json_bytes(altered)


def test_provenance_binding_is_typed_canonical_and_digest_bound() -> None:
    binding = _calendar_binding()
    data = reporting_snapshot_provenance_binding_to_dict(binding)

    assert data["authority_kind"] == "academic_period_calendar"
    assert hashlib.sha256(binding.reference_json).hexdigest() == (
        binding.reference_sha256
    )
    assert reporting_snapshot_provenance_binding_from_dict(data) == binding


def test_provenance_binding_rejects_unknown_kind_noncanonical_bytes_and_bad_digest(
) -> None:
    canonical = b'{\n  "calendar_revision": 1\n}\n'
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="unsupported",
    ):
        ReportingSnapshotProvenanceBinding(
            authority_kind="unknown",  # type: ignore[arg-type]
            reference_kind="calendar",
            reference_json=canonical,
            reference_sha256=hashlib.sha256(canonical).hexdigest(),
        )

    compact = b'{"calendar_revision":1}\n'
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="not canonical",
    ):
        ReportingSnapshotProvenanceBinding(
            authority_kind="academic_period_calendar",
            reference_kind="calendar",
            reference_json=compact,
            reference_sha256=hashlib.sha256(compact).hexdigest(),
        )

    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="digest does not match",
    ):
        ReportingSnapshotProvenanceBinding(
            authority_kind="academic_period_calendar",
            reference_kind="calendar",
            reference_json=canonical,
            reference_sha256="f" * 64,
        )


def test_snapshot_compose_binds_request_preview_scope_and_integrity() -> None:
    value = _snapshot()

    assert value.schema_version == REPORTING_SNAPSHOT_SCHEMA_VERSION
    assert value.record_type == REPORTING_SNAPSHOT_RECORD_TYPE
    assert value.integrity_algorithm == REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM
    assert value.class_id == CLASS_ID
    assert value.target_period == PERIOD
    assert value.calendar_revision == 1
    assert value.build_request_sha256 == reporting_snapshot_build_request_sha256(
        value.build_request
    )
    assert value.report_preview_sha256 == value.report_preview.preview_sha256


def test_snapshot_requires_deep_calendar_provenance() -> None:
    request = _build_request()
    preview = _unavailable_preview(request.grade_requests[0].target)

    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="requires exact provenance bindings",
    ):
        compose_reporting_snapshot(
            snapshot_id="snapshot_001",
            build_request=request,
            report_preview=preview,
            provenance_bindings=(),
            created_at=NOW,
        )

    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="Academic Period calendar provenance",
    ):
        compose_reporting_snapshot(
            snapshot_id="snapshot_001",
            build_request=request,
            report_preview=preview,
            provenance_bindings=(_policy_binding(),),
            created_at=NOW,
        )


def test_snapshot_rejects_report_targets_that_do_not_match_request() -> None:
    request = _build_request()
    preview = _unavailable_preview(_target("student_999"))

    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="report targets do not match",
    ):
        compose_reporting_snapshot(
            snapshot_id="snapshot_001",
            build_request=request,
            report_preview=preview,
            provenance_bindings=(_calendar_binding(),),
            created_at=NOW,
        )


def test_snapshot_created_at_cannot_precede_request() -> None:
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="must not be earlier",
    ):
        _snapshot(created_at=NOW - timedelta(seconds=1))


def test_snapshot_round_trips_canonically_with_nested_digest_verification() -> None:
    value = _snapshot()
    encoded = reporting_snapshot_to_json_bytes(value)
    loaded = reporting_snapshot_from_json_bytes(encoded)

    assert loaded == value
    assert reporting_snapshot_to_json_bytes(loaded) == encoded
    assert encoded.endswith(b"\n")


def test_snapshot_reference_uses_outer_canonical_snapshot_bytes() -> None:
    value = _snapshot()
    reference = reporting_snapshot_reference(value)

    assert reference.class_id == value.class_id
    assert reference.snapshot_id == value.snapshot_id
    assert reference.snapshot_sha256 == hashlib.sha256(
        reporting_snapshot_to_json_bytes(value)
    ).hexdigest()

    data = reporting_snapshot_to_dict(value)
    integrity = data.pop("integrity")
    assert isinstance(integrity, dict)
    payload_bytes = (
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    assert value.payload_sha256 == hashlib.sha256(payload_bytes).hexdigest()


def test_snapshot_id_is_not_derived_from_content_digest() -> None:
    first = _snapshot(snapshot_id="snapshot_001")
    second = _snapshot(snapshot_id="snapshot_002")

    assert first.snapshot_id != second.snapshot_id
    assert first.payload_sha256 != second.payload_sha256
    assert reporting_snapshot_reference(first).snapshot_sha256 != (
        reporting_snapshot_reference(second).snapshot_sha256
    )


def test_snapshot_rejects_payload_request_and_preview_digest_tampering() -> None:
    value = _snapshot()

    changed_payload = reporting_snapshot_to_dict(value)
    changed_payload["snapshot_id"] = "snapshot_999"
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="payload digest",
    ):
        reporting_snapshot_from_dict(changed_payload)

    changed_request = reporting_snapshot_to_dict(value)
    changed_request["build_request_sha256"] = "0" * 64
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="build request digest",
    ):
        reporting_snapshot_from_dict(changed_request)

    changed_preview = reporting_snapshot_to_dict(value)
    changed_preview["report_preview_sha256"] = "0" * 64
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="report preview digest",
    ):
        reporting_snapshot_from_dict(changed_preview)


def test_snapshot_predecessor_is_exactly_the_requested_relationship() -> None:
    predecessor = ReportingSnapshotPredecessor(
        "corrects",
        ReportingSnapshotReference(CLASS_ID, "snapshot_old", "d" * 64),
    )
    request = _build_request(predecessor=predecessor)
    value = _snapshot(request=request)
    assert value.predecessor == predecessor

    data = reporting_snapshot_to_dict(value)
    data["predecessor"] = None
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="predecessor must match",
    ):
        reporting_snapshot_from_dict(data)


def test_provenance_bindings_are_canonically_sorted_not_filesystem_ordered() -> None:
    value = _snapshot(bindings=(_policy_binding(), _calendar_binding()))

    assert tuple(item.authority_kind for item in value.provenance_bindings) == (
        "academic_period_calendar",
        "grade_policy_revision",
    )


def test_snapshot_exact_schema_noncanonical_and_size_guards_fail_closed() -> None:
    value = _snapshot()
    data = reporting_snapshot_to_dict(value)
    data["unknown"] = True
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="exact schema",
    ):
        reporting_snapshot_from_dict(data)

    encoded = reporting_snapshot_to_json_bytes(value)
    altered = encoded[:-1] + b" \n"
    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="canonical encoding",
    ):
        reporting_snapshot_from_json_bytes(altered)

    with pytest.raises(
        ReportingSnapshotIntegrityError,
        match="maximum byte size",
    ):
        reporting_snapshot_from_json_bytes(
            encoded,
            maximum_bytes=len(encoded) - 1,
        )


def test_snapshot_contract_is_frozen_and_slotted() -> None:
    value = _snapshot()

    with pytest.raises(FrozenInstanceError):
        value.snapshot_id = "changed"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")
