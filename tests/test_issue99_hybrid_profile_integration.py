from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GradePolicyRevision,
    HybridGradeConfiguration,
    ProficiencyGradeConversion,
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_activation import grade_policy_activation_reference
from meridian.hybrid_grade import (
    HYBRID_GRADE_ALGORITHM_VERSION,
    calculate_hybrid_grade,
)
from meridian.hybrid_grade_result import (
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    StandardsGradeCalculationInput,
    StandardsGradeStandardInput,
    calculate_standards_grade,
)
from tests.issue52_hybrid_test_support import (
    CLASS_ID,
    NOW,
    PERIOD,
    STUDENT_ID,
    activation,
    conventional_input,
    hybrid_input,
    policy,
    treatment,
)


def profile_scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id=CLASS_ID,
        scale_id="profile_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Profile Scale",
        description="Synthetic exact scale for Issue 99 hybrid integration.",
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


def profile_policy(
    scale: ProficiencyScale,
    *,
    insufficient_evidence: str,
) -> GradePolicyRevision:
    state_treatment = treatment(
        missing="exclude",
        insufficient_evidence=insufficient_evidence,
    )
    base = policy(
        conventional_weight="0.7",
        standards_weight="0.3",
        state_treatment=state_treatment,
    )
    base_configuration = base.configuration
    assert isinstance(base_configuration, HybridGradeConfiguration)

    standards = (
        StandardGradeParticipation("std.a", Decimal("0.5")),
        StandardGradeParticipation("std.b", Decimal("0.5")),
    )
    constraints = ProfileConstraintConfiguration(
        groups=(
            ProfileStandardGroup(
                group_id="focus",
                standard_ids=("std.a", "std.b"),
            ),
        ),
        bands=(
            ProfileGradeBand(
                band_id="high",
                priority=1,
                minimum_grade=Decimal("90"),
                maximum_grade=Decimal("100"),
                predicates=(
                    ProfilePredicate(
                        predicate_id="all_focus_meeting",
                        kind="all_at_or_above",
                        group_id="focus",
                        proficiency_level_id="meeting",
                    ),
                ),
            ),
            ProfileGradeBand(
                band_id="fallback",
                priority=2,
                minimum_grade=Decimal("0"),
                maximum_grade=Decimal("89.99"),
                predicates=(),
            ),
        ),
        fallback_band_id="fallback",
    )
    profile_configuration = StandardsBasedGradeConfiguration(
        target_scale=proficiency_scale_reference(scale),
        standards=standards,
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("65")),
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="profile_constrained_mean",
        minimum_calculated_results=1,
        profile_constraints=constraints,
    )
    return replace(
        base,
        configuration=HybridGradeConfiguration(
            conventional=base_configuration.conventional,
            standards_based=profile_configuration,
            conventional_weight=base_configuration.conventional_weight,
            standards_weight=base_configuration.standards_weight,
        ),
    )


def profile_standards_input(
    value: GradePolicyRevision,
    decision,
    scale: ProficiencyScale,
    levels: tuple[str | None, str | None],
) -> StandardsGradeCalculationInput:
    configuration = value.configuration
    assert isinstance(configuration, HybridGradeConfiguration)

    selected: list[StandardsGradeStandardInput] = []
    for index, (participation, level) in enumerate(
        zip(configuration.standards_based.standards, levels, strict=True),
        start=1,
    ):
        if level is None:
            selected.append(
                StandardsGradeStandardInput(
                    participation=participation,
                    student_id=STUDENT_ID,
                    target_period=PERIOD,
                    calendar_revision=1,
                    status="missing",
                    result_reference=None,
                    result_calculation_fingerprint=None,
                    result_algorithm_version=None,
                    proficiency_level_id=None,
                    target_scale=None,
                    freshness_status=None,
                )
            )
            continue

        selected.append(
            StandardsGradeStandardInput(
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
                    1,
                    str(index) * 64,
                ),
                result_calculation_fingerprint=str(index + 2) * 64,
                result_algorithm_version="1",
                proficiency_level_id=level,
                target_scale=configuration.standards_based.target_scale,
                freshness_status="current",
            )
        )

    return StandardsGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=grade_policy_activation_reference(decision),
        policy_reference=decision.policy_reference,
        configuration=configuration.standards_based,
        state_treatment=value.state_treatment,
        rounding=value.rounding,
        standards=tuple(selected),
        target_scale_definition=scale,
    )


def test_profile_adjusted_standards_grade_is_the_hybrid_component_value() -> None:
    scale = profile_scale()
    value = profile_policy(scale, insufficient_evidence="exclude")
    decision = activation(value)
    standards = profile_standards_input(
        value,
        decision,
        scale,
        ("meeting", "meeting"),
    )
    standards_outcome = calculate_standards_grade(standards)

    assert standards_outcome.status == "calculated"
    assert standards_outcome.base_unrounded_grade == Decimal("87")
    assert standards_outcome.selected_profile_band_id == "high"
    assert standards_outcome.profile_adjustment == "floor"
    assert standards_outcome.unrounded_grade == Decimal("90")

    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="80"),
        standards,
    )
    outcome = calculate_hybrid_grade(inputs)

    assert HYBRID_GRADE_ALGORITHM_VERSION == "2"
    assert outcome.algorithm_version == "2"
    assert outcome.status == "calculated"
    assert outcome.standards_component.component_algorithm_version == (
        STANDARDS_GRADE_ALGORITHM_VERSION
    )
    assert outcome.standards_component.component_calculation_fingerprint == (
        standards_outcome.calculation_fingerprint
    )
    assert outcome.standards_component.unrounded_grade == Decimal("90")
    assert outcome.standards_component.weighted_contribution == Decimal("27")
    assert outcome.weighted_numerator == Decimal("83")
    assert outcome.unrounded_grade == Decimal("83")
    assert outcome.rounded_grade == Decimal("83.00")


def test_profile_indeterminate_standards_component_can_be_excluded() -> None:
    scale = profile_scale()
    value = profile_policy(scale, insufficient_evidence="exclude")
    decision = activation(value)
    standards = profile_standards_input(
        value,
        decision,
        scale,
        ("meeting", None),
    )
    standards_outcome = calculate_standards_grade(standards)

    assert standards_outcome.status == "insufficient"
    assert standards_outcome.base_unrounded_grade == Decimal("87")
    assert standards_outcome.unrounded_grade is None
    assert tuple(reason.code for reason in standards_outcome.reasons) == (
        "profile_band_indeterminate",
    )

    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned="80"),
            standards,
        )
    )

    assert outcome.status == "calculated"
    assert outcome.standards_component.source_status == "insufficient"
    assert outcome.standards_component.action == "exclude"
    assert outcome.standards_component.reason_codes == (
        "profile_band_indeterminate",
    )
    assert outcome.active_weight == Decimal("0.7")
    assert outcome.unrounded_grade == Decimal("80")
    assert outcome.rounded_grade == Decimal("80.00")


def test_profile_indeterminate_standards_component_can_block_hybrid() -> None:
    scale = profile_scale()
    value = profile_policy(scale, insufficient_evidence="blocking")
    decision = activation(value)
    standards = profile_standards_input(
        value,
        decision,
        scale,
        ("meeting", None),
    )

    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned="80"),
            standards,
        )
    )

    assert outcome.status == "blocked"
    assert outcome.standards_component.source_status == "insufficient"
    assert outcome.standards_component.action == "blocking"
    assert outcome.standards_component.reason_codes == (
        "profile_band_indeterminate",
    )
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert tuple(
        (reason.code, reason.component_kind) for reason in outcome.reasons
    ) == (("blocking_component", "standards_based"),)


def test_profile_hybrid_result_round_trip_reproduces_exact_component() -> None:
    scale = profile_scale()
    value = profile_policy(scale, insufficient_evidence="exclude")
    decision = activation(value)
    standards = profile_standards_input(
        value,
        decision,
        scale,
        ("meeting", "meeting"),
    )
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="80"),
        standards,
    )
    outcome = calculate_hybrid_grade(inputs)
    snapshot = create_hybrid_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )

    payload = hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    restored = hybrid_grade_result_snapshot_from_json_bytes(payload)

    assert restored == snapshot
    assert restored.inputs.standards_based.target_scale_definition == scale
    assert restored.outcome.standards_component.unrounded_grade == Decimal("90")
    assert restored.outcome.standards_component.component_calculation_fingerprint == (
        calculate_standards_grade(
            restored.inputs.standards_based
        ).calculation_fingerprint
    )
