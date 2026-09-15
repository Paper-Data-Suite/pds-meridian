from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

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
    STANDARDS_GRADE_ALGORITHM_VERSION,
    StandardsGradeStandardInput,
    StandardsGradeValidationError,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
    standards_grade_calculation_fingerprint,
    standards_grade_calculation_input_sha256,
    standards_grade_calculation_input_to_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 13, 19, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SCALE = ProficiencyScaleReference(CLASS_ID, "course_scale", 1, SHA_A)


def treatment(
    *,
    missing: str = "blocking",
    incomplete: str = "blocking",
    insufficient_evidence: str = "blocking",
    invalid: str = "blocking",
    unresolved: str = "blocking",
) -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="blocking",
        incomplete=incomplete,  # type: ignore[arg-type]
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence=insufficient_evidence,  # type: ignore[arg-type]
        unavailable="blocking",
        withdrawn="exclude",
        invalid=invalid,  # type: ignore[arg-type]
        unresolved=unresolved,  # type: ignore[arg-type]
    )


def configuration(
    *standards: tuple[str, str],
    minimum: int = 1,
    scale: ProficiencyScaleReference = SCALE,
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=scale,
        standards=tuple(
            StandardGradeParticipation(standard_id, Decimal(weight))
            for standard_id, weight in standards
        ),
        conversions=(
            ProficiencyGradeConversion("beginning", Decimal("60")),
            ProficiencyGradeConversion("developing", Decimal("75")),
            ProficiencyGradeConversion("proficient", Decimal("88")),
            ProficiencyGradeConversion("advanced", Decimal("105")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=minimum,
    )


def policy(
    config: StandardsBasedGradeConfiguration,
    *,
    state_treatment: GradeStateTreatment | None = None,
    quantum: str = "0.01",
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="standards_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Standards Grade Policy",
        calculation_family="standards_based",
        configuration=config,
        state_treatment=state_treatment or treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal(quantum), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def activation(value: GradePolicyRevision) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version="1",
        record_type="meridian_grade_policy_activation",
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(value),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )


def result_ref(standard_id: str, revision: int = 1, digest: str = SHA_B):
    return AcademicPeriodProficiencyResultReference(
        CLASS_ID,
        PERIOD.school_year,
        PERIOD.period_id,
        STUDENT_ID,
        standard_id,
        revision,
        digest,
    )


def calculated(
    participation: StandardGradeParticipation,
    level_id: str,
    *,
    scale: ProficiencyScaleReference = SCALE,
    freshness: str = "current",
    freshness_reasons: tuple[str, ...] = (),
    revision: int = 1,
    digest: str = SHA_B,
) -> StandardsGradeStandardInput:
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="calculated",
        result_reference=result_ref(participation.standard_id, revision, digest),
        result_calculation_fingerprint=SHA_C,
        result_algorithm_version="1",
        proficiency_level_id=level_id,
        target_scale=scale,
        freshness_status=freshness,  # type: ignore[arg-type]
        freshness_reasons=freshness_reasons,
    )


def state_input(
    participation: StandardGradeParticipation,
    status: str,
    *,
    with_result: bool = False,
) -> StandardsGradeStandardInput:
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=status,  # type: ignore[arg-type]
        result_reference=(
            result_ref(participation.standard_id) if with_result else None
        ),
        result_calculation_fingerprint=SHA_C if with_result else None,
        result_algorithm_version="1" if with_result else None,
        proficiency_level_id=None,
        target_scale=SCALE if with_result else None,
        freshness_status="current" if with_result else None,
    )


def calculation_input(
    value: GradePolicyRevision,
    *standards: StandardsGradeStandardInput,
):
    return create_standards_grade_calculation_input(
        policy=value,
        activation=activation(value),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=tuple(standards),
    )


def test_exact_conversion_and_equal_weight_mean() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=2)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "proficient"),
            calculated(config.standards[1], "developing"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.algorithm_version == STANDARDS_GRADE_ALGORITHM_VERSION
    assert outcome.weighted_numerator == Decimal("81.5")
    assert outcome.active_weight == Decimal("1.0")
    assert outcome.unrounded_grade == Decimal("81.5")
    assert outcome.rounded_grade == Decimal("81.50")
    assert outcome.actual_calculated_result_count == 2


def test_unequal_weights_drive_weighted_mean() -> None:
    config = configuration(("std.a", "0.75"), ("std.b", "0.25"), minimum=2)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "advanced"),
            calculated(config.standards[1], "beginning"),
        )
    )
    assert outcome.weighted_numerator == Decimal("93.75")
    assert outcome.rounded_grade == Decimal("93.75")


def test_exclusion_removes_weight_and_renormalizes_active_mean() -> None:
    config = configuration(("std.a", "0.6"), ("std.b", "0.4"), minimum=1)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "proficient"),
            state_input(config.standards[1], "excused"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.weighted_numerator == Decimal("52.8")
    assert outcome.active_weight == Decimal("0.6")
    assert outcome.rounded_grade == Decimal("88.00")
    assert outcome.standard_results[1].action == "exclude"


def test_explicit_missing_zero_retains_configured_weight() -> None:
    config = configuration(("std.a", "0.6"), ("std.b", "0.4"), minimum=1)
    value = policy(config, state_treatment=treatment(missing="zero"))
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "proficient"),
            state_input(config.standards[1], "missing"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.active_weight == Decimal("1.0")
    assert outcome.weighted_numerator == Decimal("52.8")
    assert outcome.rounded_grade == Decimal("52.80")
    missing = outcome.standard_results[1]
    assert missing.source_state == "missing"
    assert missing.action == "zero"
    assert missing.converted_grade_value is None
    assert missing.calculation_value == Decimal("0")


def test_policy_zero_does_not_satisfy_minimum_actual_results() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=2)
    value = policy(config, state_treatment=treatment(missing="zero"))
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "advanced"),
            state_input(config.standards[1], "missing"),
        )
    )
    assert outcome.status == "insufficient"
    assert outcome.actual_calculated_result_count == 1
    assert outcome.rounded_grade is None
    assert len(outcome.reasons) == 1
    assert outcome.reasons[0].code == "below_minimum_calculated_results"
    assert outcome.reasons[0].required_results == 2
    assert outcome.reasons[0].actual_results == 1


def test_blocking_state_prevents_numeric_grade() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=1)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "advanced"),
            state_input(config.standards[1], "missing"),
        )
    )
    assert outcome.status == "blocked"
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert tuple(reason.code for reason in outcome.reasons) == ("blocking_standard",)
    assert outcome.reasons[0].standard_id == "std.b"


def test_insufficient_upstream_result_obeys_state_treatment() -> None:
    config = configuration(("std.a", "0.6"), ("std.b", "0.4"), minimum=1)
    value = policy(
        config,
        state_treatment=treatment(insufficient_evidence="exclude"),
    )
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "developing"),
            state_input(config.standards[1], "insufficient_evidence", with_result=True),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.rounded_grade == Decimal("75.00")
    assert outcome.standard_results[1].source_state == "insufficient_evidence"
    assert outcome.standard_results[1].action == "exclude"


def test_missing_selected_result_is_missing_not_implicit_latest() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config, state_treatment=treatment(missing="exclude"))
    outcome = calculate_standards_grade(
        calculation_input(value, state_input(config.standards[0], "missing"))
    )
    assert outcome.status == "insufficient"
    assert outcome.standard_results[0].source_state == "missing"
    assert outcome.standard_results[0].result_reference is None


def test_stale_selected_result_fails_closed_as_unresolved() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    stale = calculated(
        config.standards[0],
        "advanced",
        freshness="stale",
        freshness_reasons=("inputs_changed",),
    )
    outcome = calculate_standards_grade(calculation_input(value, stale))
    assert outcome.status == "blocked"
    result = outcome.standard_results[0]
    assert result.source_state == "unresolved"
    assert result.action == "blocking"
    assert "upstream_result_stale" in result.reason_codes
    assert result.converted_grade_value is None


def test_exact_scale_mismatch_fails_closed() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    other_scale = ProficiencyScaleReference(CLASS_ID, "course_scale", 2, SHA_B)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "advanced", scale=other_scale),
        )
    )
    assert outcome.status == "blocked"
    result = outcome.standard_results[0]
    assert result.source_state == "unresolved"
    assert "proficiency_scale_mismatch" in result.reason_codes


def test_unknown_level_does_not_fall_back_by_label_or_position() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "not_a_policy_level"),
        )
    )
    assert outcome.status == "blocked"
    result = outcome.standard_results[0]
    assert result.source_state == "invalid"
    assert "proficiency_level_not_in_conversion" in result.reason_codes


def test_all_excluded_is_insufficient_not_zero() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(value, state_input(config.standards[0], "excused"))
    )
    assert outcome.status == "insufficient"
    assert outcome.rounded_grade is None


def test_explicit_conversion_above_100_is_not_clamped() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    outcome = calculate_standards_grade(
        calculation_input(value, calculated(config.standards[0], "advanced"))
    )
    assert outcome.unrounded_grade == Decimal("105")
    assert outcome.rounded_grade == Decimal("105.00")


def test_final_rounding_happens_after_weighted_mean() -> None:
    config = StandardsBasedGradeConfiguration(
        target_scale=SCALE,
        standards=(
            StandardGradeParticipation("std.a", Decimal("0.333")),
            StandardGradeParticipation("std.b", Decimal("0.667")),
        ),
        conversions=(
            ProficiencyGradeConversion("low", Decimal("82.555")),
            ProficiencyGradeConversion("high", Decimal("91.445")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=2,
    )
    value = policy(config, quantum="0.01")
    outcome = calculate_standards_grade(
        calculation_input(
            value,
            calculated(config.standards[0], "low"),
            calculated(config.standards[1], "high"),
        )
    )
    expected = (
        Decimal("82.555") * Decimal("0.333")
        + Decimal("91.445") * Decimal("0.667")
    )
    assert outcome.weighted_numerator == expected
    assert outcome.unrounded_grade == expected
    assert outcome.rounded_grade == expected.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def test_canonical_input_bytes_are_order_independent() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=2)
    value = policy(config)
    a = calculated(config.standards[0], "proficient")
    b = calculated(config.standards[1], "developing")
    first = calculation_input(value, a, b)
    second = calculation_input(value, b, a)
    assert standards_grade_calculation_input_to_json_bytes(
        first
    ) == standards_grade_calculation_input_to_json_bytes(second)
    assert standards_grade_calculation_input_sha256(
        first
    ) == standards_grade_calculation_input_sha256(second)


def test_fingerprint_is_order_independent_but_result_sensitive() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=2)
    value = policy(config)
    a = calculated(config.standards[0], "proficient")
    b = calculated(config.standards[1], "developing")
    first = calculation_input(value, a, b)
    second = calculation_input(value, b, a)
    assert standards_grade_calculation_fingerprint(
        first
    ) == standards_grade_calculation_fingerprint(second)

    changed = calculation_input(
        value,
        replace(a, proficiency_level_id="advanced"),
        b,
    )
    assert standards_grade_calculation_fingerprint(
        first
    ) != standards_grade_calculation_fingerprint(changed)


def test_calculation_input_requires_exact_policy_participation() -> None:
    config = configuration(("std.a", "0.5"), ("std.b", "0.5"), minimum=1)
    value = policy(config)
    with pytest.raises(StandardsGradeValidationError, match="exactly match"):
        calculation_input(value, calculated(config.standards[0], "proficient"))


def test_activation_must_match_exact_policy() -> None:
    config = configuration(("std.a", "1"), minimum=1)
    value = policy(config)
    wrong_policy = replace(value, policy_id="other_policy")
    with pytest.raises(StandardsGradeValidationError, match="exact supplied"):
        create_standards_grade_calculation_input(
            policy=wrong_policy,
            activation=activation(value),
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            standards=(calculated(config.standards[0], "advanced"),),
        )
