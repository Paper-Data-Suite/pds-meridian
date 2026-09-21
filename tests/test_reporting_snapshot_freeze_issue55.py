from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
    ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewCurrentnessConflictError,
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_sha256,
)
from meridian.grade_report_preview import (
    GradeReportPreview,
    GradeReportPreviewRequest,
    GradeReportPreviewRow,
    GradeReportPreviewSummary,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_freeze import (
    ReportingSnapshotCurrentnessConflictError,
    ReportingSnapshotFreezeIntegrityError,
    ReportingSnapshotFreezeValidationError,
    extract_reporting_snapshot_provenance_bindings,
    freeze_reporting_snapshot,
)
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    FrozenGradeReportPreviewRow,
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotWorkEvidenceRequest,
    reporting_snapshot_build_request_from_preview_requests,
)
from meridian.reporting_snapshot_selection import (
    get_current_reporting_snapshot_selection_reference,
)
from meridian.reporting_snapshot_storage import (
    list_reporting_snapshot_ids,
    load_reporting_snapshot,
    write_reporting_definition_revision,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    write_academic_period_calendar(
        root,
        _calendar(),
        expected_current_revision=None,
    )
    return root


def _calendar(*, include_q1: bool = True) -> AcademicPeriodCalendar:
    periods = (
        AcademicPeriod(
            period_id="q1" if include_q1 else "q2",
            period_type="quarter",
            label="Quarter 1" if include_q1 else "Quarter 2",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 11, 6),
            parent_period_id=None,
            sequence=1,
            lifecycle="active",
        ),
    )
    return AcademicPeriodCalendar(
        schema_version=ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
        school_year=PERIOD.school_year,
        calendar_revision=1,
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=10),
        periods=periods,
    )


def _definition() -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title="Quarter Grade Report",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW - timedelta(minutes=10),
    )


def _target(student_id: str = "student_001") -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="standards_based",
    )


def _preview(target: GradePreviewTarget) -> GradeReportPreview:
    return GradeReportPreview(
        (
            GradeReportPreviewRow(
                target=target,
                status="unavailable",
                explanation=None,
                observation=None,
                unavailable_reason="no_selected_grade",
            ),
        )
    )


def _setup_request(root: Path, *, target: GradePreviewTarget | None = None):
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    request = GradeReportPreviewRequest(target or _target(), work_evidence=None)
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", "teacher_local"),
        requested_at=NOW,
        rationale="Freeze reviewed report.",
    )
    return stored_definition, request, build


def test_freeze_commits_exact_report_without_selecting_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    stored_definition, request, build = _setup_request(root)
    report = _preview(request.target)
    calls = 0

    def fake_report(*args: object, **kwargs: object) -> GradeReportPreview:
        nonlocal calls
        calls += 1
        return report

    monkeypatch.setattr(
        "meridian.reporting_snapshot_freeze.explain_grade_report_preview",
        fake_report,
    )

    stored = freeze_reporting_snapshot(
        root,
        snapshot_id="snapshot_001",
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=1),
    )

    assert calls == 2
    assert stored.snapshot.snapshot_id == "snapshot_001"
    assert stored.snapshot.definition_reference == stored_definition.reference
    assert stored.snapshot.report_preview.rows[0].status == "unavailable"
    assert load_reporting_snapshot(root, CLASS_ID, "snapshot_001") == stored
    assert get_current_reporting_snapshot_selection_reference(
        root,
        CLASS_ID,
        "quarter_grade_report",
        PERIOD,
        1,
    ) is None


def test_freeze_rejects_preview_requests_that_do_not_match_build_request(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)
    different = GradeReportPreviewRequest(_target("student_002"), None)

    with pytest.raises(
        ReportingSnapshotFreezeValidationError,
        match="do not match",
    ):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=build,
            preview_requests=(different,),
            created_at=NOW + timedelta(minutes=1),
        )
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ()
    assert request.target.student_id == "student_001"


def test_freeze_rejects_definition_digest_mismatch(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)
    bad_reference = ReportingDefinitionReference(
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=1,
        definition_sha256="f" * 64,
    )
    bad_build = ReportingSnapshotBuildRequest(
        schema_version=build.schema_version,
        definition_reference=bad_reference,
        grade_requests=build.grade_requests,
        actor=build.actor,
        rationale=build.rationale,
        requested_at=build.requested_at,
        predecessor=build.predecessor,
    )

    with pytest.raises(ReportingSnapshotFreezeIntegrityError, match="definition"):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=bad_build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=1),
        )


def test_freeze_requires_period_in_exact_calendar_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    write_academic_period_calendar(
        root,
        _calendar(include_q1=False),
        expected_current_revision=None,
    )
    _, request, build = _setup_request(root)

    with pytest.raises(ReportingSnapshotFreezeIntegrityError, match="absent"):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=1),
        )


def test_whole_report_change_before_commit_fails_without_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)
    reports = iter((_preview(request.target), _preview(_target("student_002"))))

    monkeypatch.setattr(
        "meridian.reporting_snapshot_freeze.explain_grade_report_preview",
        lambda *args, **kwargs: next(reports),
    )

    with pytest.raises(
        ReportingSnapshotCurrentnessConflictError,
        match="changed",
    ):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=1),
        )
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ()


def test_final_row_level_currentness_conflict_becomes_report_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)
    count = 0

    def fake_report(*args: object, **kwargs: object) -> GradeReportPreview:
        nonlocal count
        count += 1
        if count == 2:
            raise GradePreviewCurrentnessConflictError("moved")
        return _preview(request.target)

    monkeypatch.setattr(
        "meridian.reporting_snapshot_freeze.explain_grade_report_preview",
        fake_report,
    )

    with pytest.raises(
        ReportingSnapshotCurrentnessConflictError,
        match="re-observation",
    ):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=1),
        )
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ()


def test_initial_currentness_conflict_is_not_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)

    def fail_report(*args: object, **kwargs: object) -> GradeReportPreview:
        raise GradePreviewCurrentnessConflictError("moved")

    monkeypatch.setattr(
        "meridian.reporting_snapshot_freeze.explain_grade_report_preview",
        fail_report,
    )

    with pytest.raises(
        ReportingSnapshotFreezeIntegrityError,
        match="not coherently observable",
    ):
        freeze_reporting_snapshot(
            root,
            snapshot_id="snapshot_001",
            build_request=build,
            preview_requests=(request,),
            created_at=NOW + timedelta(minutes=1),
        )
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ()


def test_exact_replay_remains_storage_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, request, build = _setup_request(root)
    report = _preview(request.target)
    monkeypatch.setattr(
        "meridian.reporting_snapshot_freeze.explain_grade_report_preview",
        lambda *args, **kwargs: report,
    )
    created = NOW + timedelta(minutes=1)

    first = freeze_reporting_snapshot(
        root,
        snapshot_id="snapshot_001",
        build_request=build,
        preview_requests=(request,),
        created_at=created,
    )
    second = freeze_reporting_snapshot(
        root,
        snapshot_id="snapshot_001",
        build_request=build,
        preview_requests=(request,),
        created_at=created,
    )

    assert first == second
    assert list_reporting_snapshot_ids(root, CLASS_ID) == ("snapshot_001",)


def _available_frozen_preview() -> FrozenGradeReportPreview:
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )
    source = GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id="student_001",
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=1,
            result_sha256=SHA_A,
        ),
    )
    observation = GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=target,
        base_result_reference=source,
        base_result_status="calculated",
        base_grade=Decimal("90"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        algorithm_version="1",
        calculation_fingerprint=SHA_B,
        inputs_sha256=SHA_C,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            1,
            SHA_D,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "course_grade",
            1,
            SHA_E,
        ),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=Decimal("90"),
        effective_source="base",
        basis_entries=(),
    )
    explanation = {
        "common": {},
        "mode": "total_points",
        "items": [
            {
                "grade_item": {
                    "reference": {
                        "class_id": CLASS_ID,
                        "grade_item_id": "unit_test",
                        "grade_item_revision": 1,
                        "grade_item_revision_sha256": "1" * 64,
                    }
                },
                "provenance": [
                    {
                        "kind": "membership",
                        "reference_key": "membership-key",
                        "reference_sha256": "2" * 64,
                    },
                    {
                        "kind": "eligibility",
                        "reference_key": "eligibility-key",
                        "reference_sha256": "3" * 64,
                    },
                ],
            }
        ],
    }
    explanation_json = (
        json.dumps(explanation, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    row = FrozenGradeReportPreviewRow(
        target=target,
        status="available",
        unavailable_reason=None,
        observation=observation,
        observation_sha256=grade_preview_observation_sha256(observation),
        explanation_json=explanation_json,
        explanation_sha256=hashlib.sha256(explanation_json).hexdigest(),
    )
    summary = GradeReportPreviewSummary(
        requested_count=1,
        available_count=1,
        unavailable_count=0,
        base_calculated_count=1,
        base_blocked_count=0,
        base_insufficient_count=0,
        current_count=1,
        stale_count=0,
        effective_numeric_count=1,
        effective_nonnumeric_count=0,
        effective_base_count=1,
        effective_override_count=0,
        effective_none_count=0,
    )
    canonical = b"{}\n"
    return FrozenGradeReportPreview(
        canonical_json=canonical,
        preview_sha256=hashlib.sha256(canonical).hexdigest(),
        summary=summary,
        rows=(row,),
    )


def test_provenance_projection_preserves_typed_available_row_authorities(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )
    # Build the data-only request directly because this unit test is exercising
    # provenance projection rather than live conventional work-evidence resolution.
    build = ReportingSnapshotBuildRequest(
        schema_version="1",
        definition_reference=stored_definition.reference,
        grade_requests=(ReportingSnapshotGradeRequest(target, ()),),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        requested_at=NOW,
        predecessor=None,
    )

    bindings = extract_reporting_snapshot_provenance_bindings(
        build_request=build,
        report_preview=_available_frozen_preview(),
        calendar=_calendar(),
    )
    kinds = {item.authority_kind for item in bindings}

    assert "academic_period_calendar" in kinds
    assert "grade_result" in kinds
    assert "grade_policy_activation" in kinds
    assert "grade_policy_revision" in kinds
    assert "grade_item_revision" in kinds
    assert "grade_item_membership" in kinds
    assert "evidence_eligibility" in kinds



def test_request_side_projection_identity_becomes_core_publication_binding(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    target = GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )
    from pds_core.routing_models import ModuleWorkRef

    build = ReportingSnapshotBuildRequest(
        schema_version="1",
        definition_reference=stored_definition.reference,
        grade_requests=(
            ReportingSnapshotGradeRequest(
                target=target,
                work_evidence=(
                    ReportingSnapshotWorkEvidenceRequest(
                        grade_item_id="unit_test",
                        work=ModuleWorkRef("scoreform", CLASS_ID, "quiz_001"),
                        status="available",
                        projection_snapshots=(
                            ReportingSnapshotProjectionInputReference(
                                publication_id="pub_001",
                                cache_key="4" * 64,
                                snapshot_digest="5" * 64,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        requested_at=NOW,
        predecessor=None,
    )
    preview = _available_frozen_preview()

    bindings = extract_reporting_snapshot_provenance_bindings(
        build_request=build,
        report_preview=preview,
        calendar=_calendar(),
    )

    publication = [
        item
        for item in bindings
        if item.authority_kind == "core_publication"
        and item.reference_kind == "authorized_projection_source"
    ]
    assert len(publication) == 1
    reference = json.loads(publication[0].reference_json)
    assert reference["publication_id"] == "pub_001"


def _standards_nested_frozen_preview() -> FrozenGradeReportPreview:
    target = _target()
    from meridian.standards_grade_result import StandardsGradeResultReference

    observation = GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=target,
        base_result_reference=GradeOverrideSourceResultReference(
            "standards_based",
            StandardsGradeResultReference(
                class_id=CLASS_ID,
                student_id="student_001",
                school_year=PERIOD.school_year,
                period_id=PERIOD.period_id,
                calendar_revision=1,
                result_revision=1,
                result_sha256=SHA_A,
            ),
        ),
        base_result_status="insufficient",
        base_grade=None,
        base_freshness_status="current",
        base_freshness_reasons=(),
        algorithm_version="1",
        calculation_fingerprint=SHA_B,
        inputs_sha256=SHA_C,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID, PERIOD.school_year, PERIOD.period_id, 1, SHA_D
        ),
        policy_reference=GradePolicyReference(CLASS_ID, "course_grade", 1, SHA_E),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=None,
        effective_source="none",
        basis_entries=(),
    )
    source = {
        "work": {
            "module_id": "scoreform",
            "class_id": CLASS_ID,
            "work_id": "quiz_001",
        },
        "publication_id": "pub_001",
        "cache_key": "4" * 64,
        "snapshot_digest": "5" * 64,
        "item_id": "item_001",
    }
    stages = [
        {
            "name": name,
            "status": "verified",
            "revision": index,
            "sha256": str(index) * 64,
            "details": {"scope": name},
        }
        for index, name in enumerate(
            (
                "membership",
                "eligibility",
                "attempt_selection",
                "reassessment",
                "standard_association",
                "mapping_profile",
            ),
            start=1,
        )
    ]
    nested_grade_item = {
        "target": {
            "class_id": CLASS_ID,
            "grade_item_id": "unit_test",
            "student_id": "student_001",
            "standard_id": "RL.CR.11-12.1",
            "result_revision": 1,
            "result_sha256": "6" * 64,
            "selection_state": "historical",
            "current_result_revision": 1,
        },
        "grade_item": {
            "class_id": CLASS_ID,
            "grade_item_id": "unit_test",
            "grade_item_revision": 1,
            "grade_item_revision_sha256": "7" * 64,
        },
        "scale": {
            "scale_id": "course_scale",
            "scale_revision": 1,
            "scale_sha256": "8" * 64,
        },
        "evidence": [{"source": source, "stages": stages}],
    }
    nested_period = {
        "target": {
            "class_id": CLASS_ID,
            "student_id": "student_001",
            "standard_id": "RL.CR.11-12.1",
            "school_year": PERIOD.school_year,
            "period_id": PERIOD.period_id,
            "calendar_revision": 1,
            "result_revision": 1,
            "result_sha256": "9" * 64,
            "selection_state": "historical",
            "current_result_revision": 1,
        },
        "scale": {
            "scale_id": "course_scale",
            "scale_revision": 1,
            "scale_sha256": "8" * 64,
        },
        "grade_items": [
            {
                "grade_item": {
                    "class_id": CLASS_ID,
                    "grade_item_id": "unit_test",
                    "grade_item_revision": 1,
                    "grade_item_revision_sha256": "7" * 64,
                },
                "memberships": [
                    {
                        "module_id": "scoreform",
                        "class_id": CLASS_ID,
                        "work_id": "quiz_001",
                        "registration_revision": 1,
                        "membership_revision": 1,
                        "membership_sha256": "1" * 64,
                        "academic_period": {
                            "school_year": PERIOD.school_year,
                            "period_id": PERIOD.period_id,
                            "calendar_revision": 1,
                        },
                    }
                ],
                "result_reference": {
                    "class_id": CLASS_ID,
                    "grade_item_id": "unit_test",
                    "student_id": "student_001",
                    "standard_id": "RL.CR.11-12.1",
                    "result_revision": 1,
                    "result_sha256": "6" * 64,
                },
                "nested_grade_item_explanation": nested_grade_item,
            }
        ],
    }
    explanation = {
        "common": {},
        "status": "insufficient",
        "target_scale": {
            "class_id": CLASS_ID,
            "scale_id": "course_scale",
            "scale_revision": 1,
            "scale_sha256": "8" * 64,
        },
        "standards": [
            {
                "result_reference": {
                    "class_id": CLASS_ID,
                    "student_id": "student_001",
                    "school_year": PERIOD.school_year,
                    "period_id": PERIOD.period_id,
                    "calendar_revision": 1,
                    "standard_id": "RL.CR.11-12.1",
                    "result_revision": 1,
                    "result_sha256": "9" * 64,
                },
                "target_scale": {
                    "class_id": CLASS_ID,
                    "scale_id": "course_scale",
                    "scale_revision": 1,
                    "scale_sha256": "8" * 64,
                },
                "nested_proficiency_explanation": nested_period,
            }
        ],
    }
    explanation_json = (
        json.dumps(explanation, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    row = FrozenGradeReportPreviewRow(
        target=target,
        status="available",
        unavailable_reason=None,
        observation=observation,
        observation_sha256=grade_preview_observation_sha256(observation),
        explanation_json=explanation_json,
        explanation_sha256=hashlib.sha256(explanation_json).hexdigest(),
    )
    summary = GradeReportPreviewSummary(
        requested_count=1,
        available_count=1,
        unavailable_count=0,
        base_calculated_count=0,
        base_blocked_count=0,
        base_insufficient_count=1,
        current_count=1,
        stale_count=0,
        effective_numeric_count=0,
        effective_nonnumeric_count=1,
        effective_base_count=0,
        effective_override_count=0,
        effective_none_count=1,
    )
    canonical = b"{}\n"
    return FrozenGradeReportPreview(
        canonical_json=canonical,
        preview_sha256=hashlib.sha256(canonical).hexdigest(),
        summary=summary,
        rows=(row,),
    )


def test_nested_standards_provenance_preserves_stage_authority_kinds(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    request = GradeReportPreviewRequest(_target(), None)
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", "teacher_local"),
        requested_at=NOW,
    )

    bindings = extract_reporting_snapshot_provenance_bindings(
        build_request=build,
        report_preview=_standards_nested_frozen_preview(),
        calendar=_calendar(),
    )
    kinds = {item.authority_kind for item in bindings}

    assert {
        "academic_period_proficiency_result",
        "attempt_selection",
        "core_publication",
        "evidence_eligibility",
        "evidence_source",
        "grade_item_membership",
        "grade_item_proficiency_result",
        "grade_item_revision",
        "proficiency_mapping",
        "reassessment",
    } <= kinds


def test_calendar_binding_changes_when_exact_calendar_content_changes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    request = GradeReportPreviewRequest(_target(), None)
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", "teacher_local"),
        requested_at=NOW,
    )
    report = _preview(request.target)
    encoded = json.dumps(
        {
            "summary": {
                "requested_count": 1,
                "available_count": 0,
                "unavailable_count": 1,
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
            },
            "rows": [
                {
                    "target": {
                        "class_id": CLASS_ID,
                        "student_id": "student_001",
                        "target_period": {
                            "school_year": PERIOD.school_year,
                            "period_id": PERIOD.period_id,
                        },
                        "calendar_revision": 1,
                        "calculation_family": "standards_based",
                    },
                    "status": "unavailable",
                    "unavailable_reason": "no_selected_grade",
                    "explanation": None,
                    "observation": None,
                }
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    frozen = frozen_grade_report_preview_from_json_bytes(encoded)
    first = extract_reporting_snapshot_provenance_bindings(
        build_request=build,
        report_preview=frozen,
        calendar=_calendar(),
    )
    changed = AcademicPeriodCalendar(
        schema_version=ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
        school_year=PERIOD.school_year,
        calendar_revision=1,
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=9),
        periods=_calendar().periods,
    )
    second = extract_reporting_snapshot_provenance_bindings(
        build_request=build,
        report_preview=frozen,
        calendar=changed,
    )

    first_calendar = next(
        item for item in first if item.authority_kind == "academic_period_calendar"
    )
    second_calendar = next(
        item for item in second if item.authority_kind == "academic_period_calendar"
    )
    assert first_calendar.reference_sha256 != second_calendar.reference_sha256
    assert report.rows[0].status == "unavailable"
