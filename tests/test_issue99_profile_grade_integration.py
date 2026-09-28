from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
    StandardsGradeStandardInput,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from meridian.standards_grade_result import (
    standards_grade_calculation_outcome_from_json_bytes,
    standards_grade_calculation_outcome_to_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)
SHA = "a" * 64
STD_A = "std.a"
STD_B = "std.b"


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id=CLASS_ID,
        scale_id="course_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Course Scale",
        description="Exact ordered scale.",
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


def treatment(*, missing: str = "exclude") -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="exclude",
        unavailable="exclude",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="exclude",
    )


def profile_config(
    *,
    conversions: tuple[tuple[str, str], ...],
    high_predicate: ProfilePredicate,
) -> StandardsBasedGradeConfiguration:
    exact_scale = scale()
    return StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(exact_scale),
        standards=(
            StandardGradeParticipation(STD_A, Decimal("0.5")),
            StandardGradeParticipation(STD_B, Decimal("0.5")),
        ),
        conversions=tuple(
            ProficiencyGradeConversion(level, Decimal(value))
            for level, value in conversions
        ),
        aggregation_strategy="profile_constrained_mean",
        minimum_calculated_results=1,
        profile_constraints=ProfileConstraintConfiguration(
            groups=(ProfileStandardGroup("focus", (STD_A, STD_B)),),
            bands=(
                ProfileGradeBand(
                    "high",
                    1,
                    Decimal("90"),
                    Decimal("100"),
                    (high_predicate,),
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


def policy(
    configuration: StandardsBasedGradeConfiguration,
    *,
    state_treatment: GradeStateTreatment | None = None,
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
        state_treatment=state_treatment or treatment(),
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


def standard(
    participation: StandardGradeParticipation,
    level: str | None,
    *,
    status: str = "calculated",
) -> StandardsGradeStandardInput:
    has_result = status == "calculated"
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=status,  # type: ignore[arg-type]
        result_reference=(
            AcademicPeriodProficiencyResultReference(
                CLASS_ID,
                PERIOD.school_year,
                PERIOD.period_id,
                STUDENT_ID,
                participation.standard_id,
                1,
                SHA,
            )
            if has_result
            else None
        ),
        result_calculation_fingerprint=SHA if has_result else None,
        result_algorithm_version="1" if has_result else None,
        proficiency_level_id=level if has_result else None,
        target_scale=proficiency_scale_reference(scale()) if has_result else None,
        freshness_status="current" if has_result else None,
    )


def calculate(
    configuration: StandardsBasedGradeConfiguration,
    first: StandardsGradeStandardInput,
    second: StandardsGradeStandardInput,
    *,
    state_treatment: GradeStateTreatment | None = None,
):
    grade_policy = policy(configuration, state_treatment=state_treatment)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(first, second),
        target_scale_definition=scale(),
    )
    return calculate_standards_grade(inputs)


def all_meeting() -> ProfilePredicate:
    return ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )


def all_exceeding() -> ProfilePredicate:
    return ProfilePredicate(
        "all_exceeding",
        "all_at_or_above",
        "focus",
        "exceeding",
    )


def test_profile_floor_preserves_base_mean_and_rounds_after_constraint() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"), ("exceeding", "97")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.status == "calculated"
    assert outcome.base_unrounded_grade == Decimal("87")
    assert outcome.selected_profile_band_id == "high"
    assert outcome.profile_adjustment == "floor"
    assert outcome.unrounded_grade == Decimal("90")
    assert outcome.rounded_grade == Decimal("90.00")


def test_profile_cap_applies_when_fallback_selected() -> None:
    configuration = profile_config(
        conversions=(("meeting", "97"), ("exceeding", "105")),
        high_predicate=all_exceeding(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.base_unrounded_grade == Decimal("97")
    assert outcome.selected_profile_band_id == "fallback"
    assert outcome.profile_adjustment == "cap"
    assert outcome.unrounded_grade == Decimal("89.99")
    assert outcome.rounded_grade == Decimal("89.99")


def test_profile_grade_inside_selected_band_is_unchanged() -> None:
    configuration = profile_config(
        conversions=(("meeting", "95"), ("exceeding", "98")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.base_unrounded_grade == Decimal("95")
    assert outcome.profile_adjustment == "none"
    assert outcome.unrounded_grade == Decimal("95")


def test_higher_indeterminate_band_blocks_lower_fallback() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"),),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], None, status="missing"),
    )
    assert outcome.status == "insufficient"
    assert outcome.base_unrounded_grade == Decimal("87")
    assert outcome.profile_evaluation is not None
    assert outcome.profile_evaluation.bands[0].status == "indeterminate"
    assert outcome.profile_evaluation.bands[1].status == "matched"
    assert outcome.selected_profile_band_id is None
    assert outcome.unrounded_grade is None
    assert tuple(reason.code for reason in outcome.reasons) == (
        "profile_band_indeterminate",
    )


def test_definitively_failed_higher_band_allows_fallback() -> None:
    configuration = profile_config(
        conversions=(("developing", "80"), ("meeting", "97")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "developing"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.status == "calculated"
    assert outcome.profile_evaluation is not None
    assert outcome.profile_evaluation.bands[0].status == "not_matched"
    assert outcome.selected_profile_band_id == "fallback"


def test_zero_numeric_consequence_does_not_fabricate_profile_level() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"),),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], None, status="missing"),
        state_treatment=treatment(missing="zero"),
    )
    assert outcome.status == "insufficient"
    assert outcome.base_unrounded_grade == Decimal("43.5")
    assert outcome.profile_evaluation is not None
    predicate = outcome.profile_evaluation.bands[0].predicates[0]
    assert predicate.unknown_standard_ids == (STD_B,)
    assert predicate.below_standard_ids == ()


def test_profile_outcome_round_trips_with_structured_evidence() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"), ("exceeding", "97")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "exceeding"),
    )
    payload = standards_grade_calculation_outcome_to_json_bytes(outcome)
    restored = standards_grade_calculation_outcome_from_json_bytes(payload)
    assert restored == outcome
    assert b'"base_unrounded_grade": "92"' in payload
    assert b'"selected_profile_band_id": "high"' in payload
    assert b'"profile_adjustment": "none"' in payload


def test_weighted_mean_retains_base_equal_to_final_and_no_profile_data() -> None:
    exact_scale = scale()
    configuration = StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(exact_scale),
        standards=(
            StandardGradeParticipation(STD_A, Decimal("0.5")),
            StandardGradeParticipation(STD_B, Decimal("0.5")),
        ),
        conversions=(
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    grade_policy = policy(configuration)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(
            standard(configuration.standards[0], "meeting"),
            standard(configuration.standards[1], "exceeding"),
        ),
    )
    outcome = calculate_standards_grade(inputs)
    assert outcome.base_unrounded_grade == Decimal("92")
    assert outcome.unrounded_grade == Decimal("92")
    assert outcome.profile_evaluation is None
    assert outcome.selected_profile_band_id is None
    assert outcome.profile_adjustment is None

# Issue #99 Slice 5 selected-band bound provenance regressions.

def test_selected_profile_band_bounds_are_preserved_for_floor() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"), ("exceeding", "97")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.selected_profile_band_id == "high"
    assert outcome.selected_profile_band_minimum_grade == Decimal("90")
    assert outcome.selected_profile_band_maximum_grade == Decimal("100")
    assert outcome.profile_adjustment == "floor"


def test_selected_profile_band_bounds_are_preserved_for_cap() -> None:
    configuration = profile_config(
        conversions=(("meeting", "97"), ("exceeding", "105")),
        high_predicate=all_exceeding(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "meeting"),
    )
    assert outcome.selected_profile_band_id == "fallback"
    assert outcome.selected_profile_band_minimum_grade == Decimal("0")
    assert outcome.selected_profile_band_maximum_grade == Decimal("89.99")
    assert outcome.profile_adjustment == "cap"


def test_indeterminate_profile_has_no_selected_band_bounds() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"),),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], None, status="missing"),
    )
    assert outcome.status == "insufficient"
    assert outcome.selected_profile_band_id is None
    assert outcome.selected_profile_band_minimum_grade is None
    assert outcome.selected_profile_band_maximum_grade is None
    assert outcome.profile_adjustment is None


def test_selected_profile_band_bounds_round_trip_in_outcome_json() -> None:
    configuration = profile_config(
        conversions=(("meeting", "87"), ("exceeding", "97")),
        high_predicate=all_meeting(),
    )
    outcome = calculate(
        configuration,
        standard(configuration.standards[0], "meeting"),
        standard(configuration.standards[1], "exceeding"),
    )
    payload = standards_grade_calculation_outcome_to_json_bytes(outcome)
    restored = standards_grade_calculation_outcome_from_json_bytes(payload)
    assert restored == outcome
    assert restored.selected_profile_band_minimum_grade == Decimal("90")
    assert restored.selected_profile_band_maximum_grade == Decimal("100")
    assert b'"selected_profile_band_minimum_grade": "90"' in payload
    assert b'"selected_profile_band_maximum_grade": "100"' in payload


def test_weighted_mean_has_no_selected_profile_band_bounds() -> None:
    exact_scale = scale()
    configuration = StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(exact_scale),
        standards=(
            StandardGradeParticipation(STD_A, Decimal("0.5")),
            StandardGradeParticipation(STD_B, Decimal("0.5")),
        ),
        conversions=(
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    grade_policy = policy(configuration)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(
            standard(configuration.standards[0], "meeting"),
            standard(configuration.standards[1], "exceeding"),
        ),
    )
    outcome = calculate_standards_grade(inputs)
    assert outcome.selected_profile_band_id is None
    assert outcome.selected_profile_band_minimum_grade is None
    assert outcome.selected_profile_band_maximum_grade is None
    assert outcome.profile_adjustment is None
