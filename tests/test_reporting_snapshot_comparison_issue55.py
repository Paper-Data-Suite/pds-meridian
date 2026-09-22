from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewBasisEntry,
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_sha256,
)
from meridian.grade_report_preview import GradeReportPreviewSummary
from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
    ReportingSnapshotReference,
)
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonIntegrityError,
    ReportingSnapshotComparisonNotFoundError,
    ReportingSnapshotComparisonValidationError,
    compare_reporting_snapshot_to_current_observations,
    load_reporting_snapshot_for_comparison,
    reporting_snapshot_prior_grade_bases,
    reporting_snapshot_prior_grade_basis,
)
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    FrozenGradeReportPreviewRow,
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    compose_reporting_snapshot,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_storage import (
    write_reporting_definition_revision,
    write_reporting_snapshot,
)
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideReference,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 19, 30, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _target(student_id: str = "student_001") -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )


def _basis() -> tuple[GradePreviewBasisEntry, ...]:
    return (
        GradePreviewBasisEntry("activation", "selected_activation", "1" * 64),
        GradePreviewBasisEntry("policy", "grade_policy", "2" * 64),
        GradePreviewBasisEntry("formula", "conventional_formula", "3" * 64),
        GradePreviewBasisEntry(
            "participation", "conventional_participation", "4" * 64
        ),
        GradePreviewBasisEntry("evidence", "conventional_evidence_basis", "5" * 64),
        GradePreviewBasisEntry("weighting", "conventional_weighting", "6" * 64),
    )


def _observation(student_id: str = "student_001") -> GradePreviewObservation:
    target = _target(student_id)
    source = GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id=student_id,
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=1,
            result_sha256=SHA_A,
        ),
    )
    return GradePreviewObservation(
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
            CLASS_ID, PERIOD.school_year, PERIOD.period_id, 1, SHA_D
        ),
        policy_reference=GradePolicyReference(CLASS_ID, "course_grade", 1, SHA_E),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=Decimal("90"),
        effective_source="base",
        basis_entries=_basis(),
    )


def _definition_ref() -> ReportingDefinitionReference:
    return ReportingDefinitionReference(
        CLASS_ID, "quarter_grade_report", 1, "9" * 64
    )


def _build_request(*targets: GradePreviewTarget) -> ReportingSnapshotBuildRequest:
    return ReportingSnapshotBuildRequest(
        schema_version="1",
        definition_reference=_definition_ref(),
        grade_requests=tuple(
            ReportingSnapshotGradeRequest(item, ()) for item in targets
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        requested_at=NOW,
        predecessor=None,
    )


def _snapshot(*observations: GradePreviewObservation):
    ordered = tuple(sorted(observations, key=lambda item: item.target.student_id))
    rows = tuple(
        FrozenGradeReportPreviewRow(
            target=item.target,
            status="available",
            unavailable_reason=None,
            observation=item,
            observation_sha256=grade_preview_observation_sha256(item),
            explanation_json=b"{}\n",
            explanation_sha256=(
                "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
            ),
        )
        for item in ordered
    )
    summary = GradeReportPreviewSummary(
        requested_count=len(rows),
        available_count=len(rows),
        unavailable_count=0,
        base_calculated_count=len(rows),
        base_blocked_count=0,
        base_insufficient_count=0,
        current_count=len(rows),
        stale_count=0,
        effective_numeric_count=len(rows),
        effective_nonnumeric_count=0,
        effective_base_count=len(rows),
        effective_override_count=0,
        effective_none_count=0,
    )
    preview = FrozenGradeReportPreview(
        canonical_json=b"{}\n",
        preview_sha256=(
            "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
        ),
        summary=summary,
        rows=rows,
    )
    return compose_reporting_snapshot(
        snapshot_id="snapshot_001",
        build_request=_build_request(*(item.target for item in ordered)),
        report_preview=preview,
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": PERIOD.school_year,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=NOW,
    )


def _replace_basis(
    observation: GradePreviewObservation,
    dimension: str,
    digest: str,
) -> GradePreviewObservation:
    entries = tuple(
        replace(item, sha256=digest) if item.dimension == dimension else item
        for item in observation.basis_entries
    )
    return replace(observation, basis_entries=entries)


def test_snapshot_extracts_real_prior_basis_without_manufacturing_one() -> None:
    observation = _observation()
    snapshot = _snapshot(observation)

    bases = reporting_snapshot_prior_grade_bases(snapshot)

    assert len(bases) == 1
    assert bases[0].observation == observation
    assert (
        reporting_snapshot_prior_grade_basis(snapshot, observation.target)
        == bases[0]
    )


def test_exact_target_absence_is_not_an_unavailable_row() -> None:
    with pytest.raises(ReportingSnapshotComparisonNotFoundError):
        reporting_snapshot_prior_grade_basis(
            _snapshot(_observation()), _target("student_002")
        )


def test_unchanged_observation_delegates_to_issue54_comparison() -> None:
    observation = _observation()
    result = compare_reporting_snapshot_to_current_observations(
        _snapshot(observation), (observation,)
    )
    assert len(result) == 1
    assert result[0].relationship == "comparable"
    assert result[0].changed is False
    assert result[0].reasons == ()
    assert result[0].effective_grade_delta == Decimal("0")


def test_effective_grade_delta_remains_exact_decimal() -> None:
    prior = _observation()
    current = replace(
        prior,
        base_grade=Decimal("91.25"),
        effective_grade=Decimal("91.25"),
    )
    result = compare_reporting_snapshot_to_current_observations(
        _snapshot(prior), (current,)
    )[0]
    assert "base_grade_changed" in result.reasons
    assert "effective_grade_changed" in result.reasons
    assert result.effective_grade_delta == Decimal("1.25")


@pytest.mark.parametrize(
    ("dimension", "reason"),
    [
        ("policy", "policy_changed"),
        ("weighting", "weighting_changed"),
        ("evidence", "evidence_or_proficiency_basis_changed"),
    ],
)
def test_semantic_basis_changes_use_issue54_reason_codes(
    dimension: str,
    reason: str,
) -> None:
    prior = _observation()
    current = _replace_basis(prior, dimension, "f" * 64)
    result = compare_reporting_snapshot_to_current_observations(
        _snapshot(prior), (current,)
    )[0]
    assert reason in result.reasons


def test_override_change_uses_issue54_precedence_comparison() -> None:
    prior = _observation()
    reference = TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id="student_001",
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        override_sha256="7" * 64,
    )
    current = replace(
        prior,
        selected_override_reference=reference,
        override_applicability="applicable",
        override_replacement_grade=Decimal("95"),
        effective_grade=Decimal("95"),
        effective_source="override",
    )
    result = compare_reporting_snapshot_to_current_observations(
        _snapshot(prior), (current,)
    )[0]
    assert "override_changed" in result.reasons
    assert "override_applicability_changed" in result.reasons
    assert "effective_source_changed" in result.reasons


def test_freshness_change_is_preserved_without_recalculating() -> None:
    prior = _observation()
    current = replace(
        prior,
        base_freshness_status="stale",
        base_freshness_reasons=("inputs_changed",),
        effective_grade=None,
        effective_source="none",
    )
    result = compare_reporting_snapshot_to_current_observations(
        _snapshot(prior), (current,)
    )[0]
    assert "freshness_changed" in result.reasons
    assert "effective_source_changed" in result.reasons


def test_new_and_removed_targets_are_deterministic() -> None:
    prior = _observation("student_001")
    current = _observation("student_002")
    results = compare_reporting_snapshot_to_current_observations(
        _snapshot(prior), (current,)
    )
    assert tuple(item.relationship for item in results) == ("removed", "new")
    assert results[0].prior_target == prior.target
    assert results[1].current_target == current.target


def test_current_observation_outside_snapshot_scope_is_rejected() -> None:
    prior = _observation()
    bad_target = replace(_target(), calendar_revision=2)
    bad_source = GradeOverrideSourceResultReference(
        "conventional",
        replace(prior.base_result_reference.reference, calendar_revision=2),
    )
    current = replace(
        prior,
        target=bad_target,
        base_result_reference=bad_source,
    )
    with pytest.raises(ReportingSnapshotComparisonValidationError, match="outside"):
        compare_reporting_snapshot_to_current_observations(
            _snapshot(prior), (current,)
        )


def test_duplicate_current_exact_target_is_rejected() -> None:
    prior = _observation()
    with pytest.raises(ReportingSnapshotComparisonValidationError, match="duplicate"):
        compare_reporting_snapshot_to_current_observations(
            _snapshot(prior), (prior, prior)
        )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _persisted_unavailable_snapshot(root: Path):
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    definition = ReportingDefinitionRevision(
        schema_version="1",
        record_type="meridian_reporting_definition",
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="Quarter Grade review",
        title="Quarter 1 Grade Report",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    stored_definition = write_reporting_definition_revision(root, definition).stored
    target = _target()
    report = {
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
                    "calculation_family": "conventional",
                },
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
        ],
    }
    preview = frozen_grade_report_preview_from_json_bytes(_canonical_json(report))
    request = ReportingSnapshotBuildRequest(
        schema_version="1",
        definition_reference=stored_definition.reference,
        grade_requests=(ReportingSnapshotGradeRequest(target, ()),),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        requested_at=NOW,
        predecessor=None,
    )
    snapshot = compose_reporting_snapshot(
        snapshot_id="snapshot_001",
        build_request=request,
        report_preview=preview,
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": PERIOD.school_year,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=NOW,
    )
    return write_reporting_snapshot(root, snapshot).stored


def test_exact_reference_load_is_digest_bound(tmp_path: Path) -> None:
    stored = _persisted_unavailable_snapshot(tmp_path)
    loaded = load_reporting_snapshot_for_comparison(tmp_path, stored.reference)
    assert loaded == stored

    wrong = ReportingSnapshotReference(
        stored.reference.class_id,
        stored.reference.snapshot_id,
        "0" * 64,
    )
    with pytest.raises(ReportingSnapshotComparisonIntegrityError, match="digest"):
        load_reporting_snapshot_for_comparison(tmp_path, wrong)
