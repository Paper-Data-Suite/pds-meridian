from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
)
from meridian.grade_policy_activation import GradePolicyActivationDecision
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeStandardInput,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from meridian.standards_grade_result import (
    STANDARDS_GRADE_RESULT_RECORD_TYPE,
    STANDARDS_GRADE_RESULT_SCHEMA_VERSION,
    StandardsGradeResultValidationError,
    assess_standards_grade_result_freshness,
    create_standards_grade_result_snapshot,
    standards_grade_calculation_input_from_json_bytes,
    standards_grade_calculation_outcome_from_json_bytes,
    standards_grade_calculation_outcome_to_json_bytes,
    standards_grade_result_reference,
    standards_grade_result_snapshot_from_json_bytes,
    standards_grade_result_snapshot_to_json_bytes,
    validate_standards_grade_result_transition,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 13, 19, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SCALE = ProficiencyScaleReference(CLASS_ID, "course_scale", 1, SHA_A)


def _treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="blocking",
        unresolved="blocking",
    )


def _configuration() -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=SCALE,
        standards=(
            StandardGradeParticipation("std.a", Decimal("0.6")),
            StandardGradeParticipation("std.b", Decimal("0.4")),
        ),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("75")),
            ProficiencyGradeConversion("proficient", Decimal("88")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=2,
    )


def _policy() -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="standards_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Standards Grade Policy",
        calculation_family="standards_based",
        configuration=_configuration(),
        state_treatment=_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _activation(policy: GradePolicyRevision) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version="1",
        record_type="meridian_grade_policy_activation",
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(policy),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )


def _standard_input(
    participation: StandardGradeParticipation,
    level: str,
    *,
    revision: int = 1,
    digest: str = SHA_B,
) -> StandardsGradeStandardInput:
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="calculated",
        result_reference=AcademicPeriodProficiencyResultReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            STUDENT_ID,
            participation.standard_id,
            revision,
            digest,
        ),
        result_calculation_fingerprint=SHA_C,
        result_algorithm_version="1",
        proficiency_level_id=level,
        target_scale=SCALE,
        freshness_status="current",
    )


def _basis():
    policy = _policy()
    configuration = policy.configuration
    assert isinstance(configuration, StandardsBasedGradeConfiguration)
    inputs = create_standards_grade_calculation_input(
        policy=policy,
        activation=_activation(policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(
            _standard_input(configuration.standards[0], "proficient"),
            _standard_input(configuration.standards[1], "developing"),
        ),
    )
    outcome = calculate_standards_grade(inputs)
    return inputs, outcome


def test_result_snapshot_round_trip_reproduces_exact_calculation() -> None:
    inputs, outcome = _basis()
    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    assert snapshot.schema_version == STANDARDS_GRADE_RESULT_SCHEMA_VERSION
    assert snapshot.record_type == STANDARDS_GRADE_RESULT_RECORD_TYPE
    assert snapshot.inputs == inputs
    assert snapshot.outcome == outcome

    payload = standards_grade_result_snapshot_to_json_bytes(snapshot)
    assert payload.endswith(b"\n")
    assert standards_grade_result_snapshot_from_json_bytes(payload) == snapshot
    assert standards_grade_result_snapshot_to_json_bytes(snapshot) == payload


def test_input_and_outcome_canonical_round_trip() -> None:
    inputs, outcome = _basis()
    from meridian.standards_grade import standards_grade_calculation_input_to_json_bytes

    input_payload = standards_grade_calculation_input_to_json_bytes(inputs)
    assert standards_grade_calculation_input_from_json_bytes(input_payload) == inputs

    outcome_payload = standards_grade_calculation_outcome_to_json_bytes(outcome)
    assert (
        standards_grade_calculation_outcome_from_json_bytes(outcome_payload)
        == outcome
    )


def test_snapshot_rejects_tampered_outcome_and_input_digest() -> None:
    inputs, outcome = _basis()
    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    with pytest.raises(StandardsGradeResultValidationError, match="inputs_sha256"):
        replace(snapshot, inputs_sha256="d" * 64)
    with pytest.raises(StandardsGradeResultValidationError, match="reproduce"):
        replace(
            snapshot,
            outcome=replace(outcome, rounded_grade=Decimal("1.00")),
        )


def test_result_reference_binds_exact_snapshot_bytes() -> None:
    inputs, outcome = _basis()
    first = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    later_time = replace(first, calculated_at=NOW + timedelta(seconds=1))
    assert standards_grade_result_reference(first).result_sha256 != (
        standards_grade_result_reference(later_time).result_sha256
    )
    assert first.calculation_fingerprint == later_time.calculation_fingerprint


def test_transition_requires_contiguous_revision_and_nondecreasing_time() -> None:
    inputs, outcome = _basis()
    first = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    second = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(seconds=1),
    )
    assert validate_standards_grade_result_transition(first, second) == second

    with pytest.raises(StandardsGradeResultValidationError, match="nondecreasing"):
        validate_standards_grade_result_transition(
            first,
            replace(second, calculated_at=NOW - timedelta(seconds=1)),
        )


def test_freshness_detects_selected_proficiency_change() -> None:
    inputs, outcome = _basis()
    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    changed_standard = replace(
        inputs.standards[0],
        result_reference=replace(
            inputs.standards[0].result_reference,
            result_revision=2,
            result_sha256="e" * 64,
        ),
    )
    current = replace(inputs, standards=(changed_standard, inputs.standards[1]))
    freshness = assess_standards_grade_result_freshness(snapshot, current)
    assert freshness.status == "stale"
    assert freshness.reasons == ("proficiency_results_changed",)


def test_freshness_reasons_are_independent_and_deterministically_ordered() -> None:
    inputs, outcome = _basis()
    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    changed_period = AcademicPeriodRef("2026-2027", "mp2")
    changed_standards = tuple(
        replace(
            item,
            target_period=changed_period,
            result_reference=(
                None
                if item.result_reference is None
                else replace(item.result_reference, period_id="mp2")
            ),
        )
        for item in inputs.standards
    )
    changed = replace(
        inputs,
        target_period=changed_period,
        activation_reference=replace(inputs.activation_reference, period_id="mp2"),
        policy_reference=replace(inputs.policy_reference, policy_revision=2),
        standards=changed_standards,
    )
    freshness = assess_standards_grade_result_freshness(
        snapshot,
        changed,
        algorithm_version="2",
    )
    assert freshness.reasons == (
        "calendar_scope_changed",
        "activation_changed",
        "policy_changed",
        "proficiency_results_changed",
        "algorithm_changed",
    )


def test_unchanged_basis_is_current() -> None:
    inputs, outcome = _basis()
    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    freshness = assess_standards_grade_result_freshness(snapshot, inputs)
    assert freshness.status == "current"
    assert freshness.reasons == ()
