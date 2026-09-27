from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
)
from meridian.grade_policy_activation import GradePolicyActivationDecision
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    StandardsGradeStandardInput,
    StandardsGradeValidationError,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
    standards_grade_calculation_input_to_json_bytes,
)
from meridian.standards_grade_result import (
    STANDARDS_GRADE_RESULT_SCHEMA_VERSION,
    standards_grade_calculation_input_from_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 27, 4, 0, tzinfo=UTC)
SHA = "a" * 64
STANDARD_A = "std.a"


def scale(*, description: str = "Exact ordered scale.") -> ProficiencyScale:
    return ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id=CLASS_ID,
        scale_id="course_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Course Scale",
        description=description,
        levels=(
            ProficiencyLevel("developing", 1, "Developing", "Developing."),
            ProficiencyLevel("meeting", 2, "Meeting", "Meeting."),
            ProficiencyLevel("exceeding", 3, "Exceeding", "Exceeding."),
        ),
        proficiency_threshold_level_id="meeting",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def treatment() -> GradeStateTreatment:
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


def profile_configuration(
    exact_scale: ProficiencyScale,
    *,
    predicate_level: str = "meeting",
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(exact_scale),
        standards=(StandardGradeParticipation(STANDARD_A, Decimal("1")),),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("65")),
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="profile_constrained_mean",
        minimum_calculated_results=1,
        profile_constraints=ProfileConstraintConfiguration(
            groups=(ProfileStandardGroup("focus", (STANDARD_A,)),),
            bands=(
                ProfileGradeBand(
                    "top",
                    1,
                    Decimal("90"),
                    Decimal("100"),
                    (
                        ProfilePredicate(
                            "all_focus_threshold",
                            "all_at_or_above",
                            "focus",
                            predicate_level,
                        ),
                    ),
                ),
                ProfileGradeBand(
                    "fallback",
                    2,
                    Decimal("0"),
                    Decimal("89.99"),
                    (),
                ),
            ),
            fallback_band_id="fallback",
        ),
    )


def weighted_configuration(
    exact_scale: ProficiencyScale,
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(exact_scale),
        standards=(StandardGradeParticipation(STANDARD_A, Decimal("1")),),
        conversions=(ProficiencyGradeConversion("meeting", Decimal("87")),),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )


def policy(
    configuration: StandardsBasedGradeConfiguration,
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course Grade Policy",
        calculation_family="standards_based",
        configuration=configuration,
        state_treatment=treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
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


def standard_input(
    configuration: StandardsBasedGradeConfiguration,
    level_id: str = "meeting",
) -> StandardsGradeStandardInput:
    participation = configuration.standards[0]
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
            STANDARD_A,
            1,
            SHA,
        ),
        result_calculation_fingerprint=SHA,
        result_algorithm_version="1",
        proficiency_level_id=level_id,
        target_scale=configuration.target_scale,
        freshness_status="current",
    )


def test_issue99_versions_standards_grade_algorithm_and_result_schema() -> None:
    assert STANDARDS_GRADE_ALGORITHM_VERSION == "2"
    assert STANDARDS_GRADE_RESULT_SCHEMA_VERSION == "2"


def test_profile_strategy_requires_exact_ordered_scale_authority() -> None:
    exact_scale = scale()
    configuration = profile_configuration(exact_scale)
    grade_policy = policy(configuration)

    with pytest.raises(
        StandardsGradeValidationError,
        match="requires exact target_scale_definition",
    ):
        create_standards_grade_calculation_input(
            policy=grade_policy,
            activation=activation(grade_policy),
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            standards=(standard_input(configuration),),
        )


def test_exact_scale_definition_must_match_policy_reference() -> None:
    exact_scale = scale()
    configuration = profile_configuration(exact_scale)
    grade_policy = policy(configuration)

    with pytest.raises(
        StandardsGradeValidationError,
        match="match exact policy target_scale",
    ):
        create_standards_grade_calculation_input(
            policy=grade_policy,
            activation=activation(grade_policy),
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            standards=(standard_input(configuration),),
            target_scale_definition=scale(description="Different canonical bytes."),
        )


def test_profile_predicate_level_must_exist_in_exact_scale() -> None:
    exact_scale = scale()
    configuration = profile_configuration(
        exact_scale,
        predicate_level="not_a_real_level",
    )
    grade_policy = policy(configuration)

    with pytest.raises(
        StandardsGradeValidationError,
        match="profile predicate proficiency level",
    ):
        create_standards_grade_calculation_input(
            policy=grade_policy,
            activation=activation(grade_policy),
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            standards=(standard_input(configuration),),
            target_scale_definition=exact_scale,
        )


def test_profile_input_round_trip_binds_scale_and_full_policy_authority() -> None:
    exact_scale = scale()
    configuration = profile_configuration(exact_scale)
    grade_policy = policy(configuration)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(standard_input(configuration),),
        target_scale_definition=exact_scale,
    )

    payload = standards_grade_calculation_input_to_json_bytes(inputs)
    assert b'"target_scale_definition": {' in payload
    assert b'"profile_constraints": {' in payload
    assert b'"profile_constrained_mean"' in payload
    assert standards_grade_calculation_input_from_json_bytes(payload) == inputs


def test_weighted_mean_remains_valid_without_full_scale_definition() -> None:
    exact_scale = scale()
    configuration = weighted_configuration(exact_scale)
    grade_policy = policy(configuration)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(standard_input(configuration),),
    )

    assert inputs.target_scale_definition is None
    outcome = calculate_standards_grade(inputs)
    assert outcome.algorithm_version == STANDARDS_GRADE_ALGORITHM_VERSION
    assert outcome.rounded_grade == Decimal("87.00")
