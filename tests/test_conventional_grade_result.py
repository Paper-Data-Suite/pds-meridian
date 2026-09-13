from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import (
    CONVENTIONAL_GRADE_ALGORITHM_VERSION,
    CONVENTIONAL_GRADE_RESULT_RECORD_TYPE,
    ConventionalGradeCalculationInput,
    ConventionalGradeItemInput,
    ConventionalGradeResultSnapshot,
    ConventionalGradeSerializationError,
    ConventionalGradeValidationError,
    assess_conventional_grade_result_freshness,
    calculate_conventional_grade,
    conventional_grade_calculation_input_from_json_bytes,
    conventional_grade_calculation_input_sha256,
    conventional_grade_calculation_input_to_json_bytes,
    conventional_grade_calculation_outcome_from_json_bytes,
    conventional_grade_calculation_outcome_to_json_bytes,
    conventional_grade_result_reference,
    conventional_grade_result_snapshot_from_json_bytes,
    conventional_grade_result_snapshot_to_json_bytes,
    create_conventional_grade_result_snapshot,
    validate_conventional_grade_result_transition,
)
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyReference,
    GradeRoundingPolicy,
    GradeStateTreatment,
)
from meridian.grade_policy_activation import GradePolicyActivationReference

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
OTHER_PERIOD = AcademicPeriodRef("2026-2027", "mp2")
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


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
        invalid="exclude",
        unresolved="blocking",
    )


def _input(
    *,
    period: AcademicPeriodRef = PERIOD,
    calendar_revision: int = 1,
    activation_sha: str = SHA_A,
    policy_sha: str = SHA_B,
    earned: str = "8",
) -> ConventionalGradeCalculationInput:
    item_ref = GradePolicyItemReference(CLASS_ID, "quiz", 1, SHA_C)
    participation = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    item = ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=period,
        calendar_revision=calendar_revision,
        status="points",
        earned=Decimal(earned),
        possible=Decimal("10"),
    )
    return ConventionalGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=period,
        calendar_revision=calendar_revision,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            period.school_year,
            period.period_id,
            1,
            activation_sha,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "grade_policy",
            1,
            policy_sha,
        ),
        configuration=ConventionalGradeConfiguration(
            "total_points",
            (participation,),
            (),
        ),
        state_treatment=_treatment(),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        items=(item,),
    )


def _result(
    *,
    revision: int = 1,
    inputs: ConventionalGradeCalculationInput | None = None,
    calculated_at: datetime = NOW,
) -> ConventionalGradeResultSnapshot:
    basis = inputs or _input()
    return create_conventional_grade_result_snapshot(
        basis,
        calculate_conventional_grade(basis),
        result_revision=revision,
        calculated_at=calculated_at,
    )


def test_calculation_input_and_outcome_round_trip_canonically() -> None:
    inputs = _input()
    input_bytes = conventional_grade_calculation_input_to_json_bytes(inputs)
    assert conventional_grade_calculation_input_from_json_bytes(input_bytes) == inputs
    assert conventional_grade_calculation_input_sha256(inputs) == hashlib.sha256(
        input_bytes
    ).hexdigest()

    outcome = calculate_conventional_grade(inputs)
    outcome_bytes = conventional_grade_calculation_outcome_to_json_bytes(outcome)
    assert (
        conventional_grade_calculation_outcome_from_json_bytes(outcome_bytes)
        == outcome
    )


def test_result_round_trip_reproduces_exact_calculation() -> None:
    result = _result()
    encoded = conventional_grade_result_snapshot_to_json_bytes(result)
    decoded = conventional_grade_result_snapshot_from_json_bytes(encoded)
    assert decoded == result
    assert decoded.record_type == CONVENTIONAL_GRADE_RESULT_RECORD_TYPE
    assert decoded.outcome.rounded_grade == Decimal("80.00")


def test_result_parser_rejects_noncanonical_json() -> None:
    result = _result()
    decoded = json.loads(conventional_grade_result_snapshot_to_json_bytes(result))
    noncanonical = json.dumps(decoded).encode("utf-8")
    with pytest.raises(ConventionalGradeSerializationError):
        conventional_grade_result_snapshot_from_json_bytes(noncanonical)


def test_result_rejects_outcome_that_does_not_reproduce() -> None:
    result = _result()
    bad_outcome = replace(result.outcome, rounded_grade=Decimal("79.99"))
    with pytest.raises(ConventionalGradeValidationError, match="reproduce"):
        replace(result, outcome=bad_outcome)


def test_result_reference_binds_exact_scope_revision_and_digest() -> None:
    result = _result()
    reference = conventional_grade_result_reference(result)
    assert reference.class_id == CLASS_ID
    assert reference.student_id == STUDENT_ID
    assert reference.school_year == PERIOD.school_year
    assert reference.period_id == PERIOD.period_id
    assert reference.calendar_revision == 1
    assert reference.result_revision == 1
    assert len(reference.result_sha256) == 64


def test_result_transition_requires_same_scope_contiguous_history() -> None:
    first = _result()
    second = _result(revision=2, calculated_at=NOW + timedelta(minutes=1))
    assert validate_conventional_grade_result_transition(first, second) == second
    with pytest.raises(ConventionalGradeValidationError, match="logical identity"):
        validate_conventional_grade_result_transition(
            first,
            _result(
                revision=2,
                inputs=_input(period=OTHER_PERIOD),
                calculated_at=NOW + timedelta(minutes=1),
            ),
        )


def test_freshness_current_for_exact_same_basis() -> None:
    result = _result()
    freshness = assess_conventional_grade_result_freshness(result, result.inputs)
    assert freshness.status == "current"
    assert freshness.reasons == ()


@pytest.mark.parametrize(
    ("current", "reason"),
    [
        (_input(period=OTHER_PERIOD), "calendar_scope_changed"),
        (_input(activation_sha=SHA_C), "activation_changed"),
        (_input(policy_sha=SHA_C), "policy_changed"),
        (_input(earned="7"), "inputs_changed"),
    ],
)
def test_freshness_reports_independent_material_changes(
    current: ConventionalGradeCalculationInput,
    reason: str,
) -> None:
    result = _result()
    freshness = assess_conventional_grade_result_freshness(result, current)
    assert freshness.status == "stale"
    assert reason in freshness.reasons


def test_freshness_reports_algorithm_change_without_mutation() -> None:
    result = _result()
    freshness = assess_conventional_grade_result_freshness(
        result,
        result.inputs,
        algorithm_version="2",
    )
    assert freshness.reasons == ("algorithm_changed",)
    assert result.algorithm_version == CONVENTIONAL_GRADE_ALGORITHM_VERSION


def test_calculated_at_does_not_change_academic_fingerprint() -> None:
    first = _result()
    later = _result(calculated_at=NOW + timedelta(days=1))
    assert first.calculation_fingerprint == later.calculation_fingerprint
    assert first.inputs_sha256 == later.inputs_sha256
    assert conventional_grade_result_snapshot_to_json_bytes(first) != (
        conventional_grade_result_snapshot_to_json_bytes(later)
    )
