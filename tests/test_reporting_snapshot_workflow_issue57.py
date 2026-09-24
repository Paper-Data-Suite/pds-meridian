from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingDefinitionReference,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotWorkEvidenceRequest,
    reporting_snapshot_build_request_to_json_bytes,
)
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotProjectionAuthorization,
    ReportingSnapshotWorkflowAuthorizationError,
    ReportingSnapshotWorkflowInputError,
    load_reporting_snapshot_build_request_file,
    required_projection_authorizations,
)


def _request(*, protected: bool) -> ReportingSnapshotBuildRequest:
    period = AcademicPeriodRef("2026-2027", "mp1")
    target = GradePreviewTarget(
        class_id="class_1",
        student_id="student_1",
        target_period=period,
        calendar_revision=4,
        calculation_family="conventional" if protected else "standards_based",
    )
    evidence = None
    if protected:
        evidence = (
            ReportingSnapshotWorkEvidenceRequest(
                grade_item_id="essay_1",
                work=ModuleWorkRef(
                    module_id="quillan",
                    class_id="class_1",
                    work_id="essay_1",
                ),
                status="available",
                projection_snapshots=(
                    ReportingSnapshotProjectionInputReference(
                        publication_id="publication_1",
                        cache_key="a" * 64,
                        snapshot_digest="b" * 64,
                    ),
                ),
            ),
        )
    return ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=ReportingDefinitionReference(
            class_id="class_1",
            definition_id="report_1",
            definition_revision=2,
            definition_sha256="c" * 64,
        ),
        grade_requests=(
            ReportingSnapshotGradeRequest(
                target=target,
                work_evidence=evidence,
            ),
        ),
        actor=ReportingActor("teacher", "teacher_1"),
        rationale="Quarterly reporting",
        requested_at=datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        predecessor=None,
    )


def test_build_request_file_loader_accepts_only_canonical_bytes(
    tmp_path: Path,
) -> None:
    request = _request(protected=False)
    path = tmp_path / "request.json"
    path.write_bytes(reporting_snapshot_build_request_to_json_bytes(request))

    loaded = load_reporting_snapshot_build_request_file(path)

    assert loaded == request


def test_build_request_file_loader_rejects_noncanonical_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "request.json"
    path.write_text('{"not":"a canonical request"}', encoding="utf-8")

    with pytest.raises(ReportingSnapshotWorkflowInputError):
        load_reporting_snapshot_build_request_file(path)


def test_required_projection_authorizations_are_exact_and_bounded() -> None:
    request = _request(protected=True)

    values = required_projection_authorizations(request)

    assert len(values) == 1
    assert values[0].publication_id == "publication_1"
    assert values[0].cache_key == "a" * 64
    assert values[0].snapshot_digest == "b" * 64


def test_projection_authorization_normalizes_student_order() -> None:
    value = ReportingSnapshotProjectionAuthorization(
        publication_id="publication_1",
        cache_key="a" * 64,
        purpose_id="teacher_reporting",
        student_ids=("student_2", "student_1"),
    )

    assert value.student_ids == ("student_1", "student_2")


def test_projection_authorization_rejects_duplicate_students() -> None:
    with pytest.raises(ReportingSnapshotWorkflowInputError):
        ReportingSnapshotProjectionAuthorization(
            publication_id="publication_1",
            cache_key="a" * 64,
            purpose_id="teacher_reporting",
            student_ids=("student_1", "student_1"),
        )


def test_missing_protected_authorization_fails_before_projection_access() -> None:
    request = _request(protected=True)

    from meridian.reporting_snapshot_workflow import _authorization_map

    with pytest.raises(ReportingSnapshotWorkflowAuthorizationError):
        _authorization_map(request, ())
