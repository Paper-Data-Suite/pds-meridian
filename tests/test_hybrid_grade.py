from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeItemInput,
    ConventionalGradeValidationError,
    calculate_conventional_grade,
    create_conventional_grade_calculation_input,
)
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    HybridGradeConfiguration,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    grade_policy_activation_reference,
)
from meridian.hybrid_grade import (
    HYBRID_GRADE_ALGORITHM_VERSION,
    HybridGradeCalculationInput,
    HybridGradeValidationError,
    calculate_hybrid_grade,
    create_hybrid_grade_calculation_input,
    hybrid_grade_calculation_fingerprint,
    hybrid_grade_calculation_input_sha256,
    hybrid_grade_calculation_input_to_json_bytes,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeCalculationInput,
    StandardsGradeStandardInput,
    StandardsGradeValidationError,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 14, 21, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
STANDARD_ID = "std.a"
SCALE = ProficiencyScaleReference(CLASS_ID, "course_scale", 1, SHA_B)


def treatment(
    *,
    missing: str = "blocking",
    insufficient_evidence: str = "blocking",
) -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence=insufficient_evidence,  # type: ignore[arg-type]
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def conventional_configuration() -> ConventionalGradeConfiguration:
    participation = GradePolicyItemParticipation(
        GradePolicyItemReference(CLASS_ID, "coursework", 1, SHA_A),
        None,
        Decimal("1"),
        None,
    )
    return ConventionalGradeConfiguration(
        "weighted_items",
        (participation,),
        (),
    )


def standards_configuration(
    grade_value: str,
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=SCALE,
        standards=(StandardGradeParticipation(STANDARD_ID, Decimal("1")),),
        conversions=(
            ProficiencyGradeConversion("proficient", Decimal(grade_value)),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )


def policy(
    *,
    conventional_weight: str = "0.7",
    standards_weight: str = "0.3",
    standards_grade_value: str = "88",
    state_treatment: GradeStateTreatment | None = None,
    quantum: str = "0.01",
) -> GradePolicyRevision:
    configuration = HybridGradeConfiguration(
        conventional=conventional_configuration(),
        standards_based=standards_configuration(standards_grade_value),
        conventional_weight=Decimal(conventional_weight),
        standards_weight=Decimal(standards_weight),
    )
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="hybrid_course_grade",
        policy_revision=1,
        supersedes_revision=None,
        title="Hybrid Course Grade",
        calculation_family="hybrid",
        configuration=configuration,
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


def conventional_input(
    value: GradePolicyRevision,
    decision: GradePolicyActivationDecision,
    *,
    earned: str | None = "92",
    state: str = "points",
) -> ConventionalGradeCalculationInput:
    configuration = value.configuration
    assert isinstance(configuration, HybridGradeConfiguration)
    participation = configuration.conventional.items[0]
    item = ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=state,  # type: ignore[arg-type]
        earned=Decimal(earned) if state == "points" and earned is not None else None,
        possible=Decimal("100") if state == "points" else None,
    )
    return ConventionalGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=grade_policy_activation_reference(decision),
        policy_reference=grade_policy_reference(value),
        configuration=configuration.conventional,
        state_treatment=value.state_treatment,
        rounding=value.rounding,
        items=(item,),
    )


def standards_input(
    value: GradePolicyRevision,
    decision: GradePolicyActivationDecision,
    *,
    status: str = "calculated",
) -> StandardsGradeCalculationInput:
    configuration = value.configuration
    assert isinstance(configuration, HybridGradeConfiguration)
    participation = configuration.standards_based.standards[0]
    if status == "calculated":
        standard = StandardsGradeStandardInput(
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
                STANDARD_ID,
                1,
                SHA_C,
            ),
            result_calculation_fingerprint=SHA_D,
            result_algorithm_version="1",
            proficiency_level_id="proficient",
            target_scale=SCALE,
            freshness_status="current",
        )
    else:
        standard = StandardsGradeStandardInput(
            participation=participation,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            status=status,  # type: ignore[arg-type]
            result_reference=None,
            result_calculation_fingerprint=None,
            result_algorithm_version=None,
            proficiency_level_id=None,
            target_scale=None,
            freshness_status=None,
        )
    return StandardsGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=grade_policy_activation_reference(decision),
        policy_reference=grade_policy_reference(value),
        configuration=configuration.standards_based,
        state_treatment=value.state_treatment,
        rounding=value.rounding,
        standards=(standard,),
    )


def hybrid_input(
    value: GradePolicyRevision,
    decision: GradePolicyActivationDecision,
    conventional: ConventionalGradeCalculationInput,
    standards: StandardsGradeCalculationInput,
) -> HybridGradeCalculationInput:
    return create_hybrid_grade_calculation_input(
        policy=value,
        activation=decision,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        conventional=conventional,
        standards_based=standards,
    )


def test_exact_component_weights_combine_unrounded_component_grades() -> None:
    value = policy(standards_grade_value="88")
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="92"),
        standards_input(value, decision),
    )
    outcome = calculate_hybrid_grade(inputs)

    assert outcome.status == "calculated"
    assert outcome.algorithm_version == HYBRID_GRADE_ALGORITHM_VERSION
    assert outcome.conventional_component.unrounded_grade == Decimal("92")
    assert outcome.standards_component.unrounded_grade == Decimal("88")
    assert outcome.conventional_component.weighted_contribution == Decimal("64.4")
    assert outcome.standards_component.weighted_contribution == Decimal("26.4")
    assert outcome.active_weight == Decimal("1.0")
    assert outcome.weighted_numerator == Decimal("90.8")
    assert outcome.unrounded_grade == Decimal("90.8")
    assert outcome.rounded_grade == Decimal("90.80")


def test_repeating_component_contribution_uses_exact_sum_context() -> None:
    value = policy(
        conventional_weight="0.6",
        standards_weight="0.4",
        standards_grade_value="85",
    )
    decision = activation(value)
    conventional = conventional_input(value, decision, earned="1")
    conventional = replace(
        conventional,
        items=(
            replace(
                conventional.items[0],
                possible=Decimal("3"),
            ),
        ),
    )

    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional,
            standards_input(value, decision),
        )
    )

    assert outcome.status == "calculated"
    assert outcome.rounded_grade == Decimal("54.00")
    with localcontext() as context:
        context.prec = 100
        expected_numerator = (
            outcome.conventional_component.weighted_contribution
            + outcome.standards_component.weighted_contribution
        )
    assert outcome.weighted_numerator == expected_numerator


def test_final_rounding_does_not_reuse_component_rounded_grades() -> None:
    value = policy(
        conventional_weight="0.7",
        standards_weight="0.3",
        standards_grade_value="61.5",
        quantum="1",
    )
    decision = activation(value)
    conventional = conventional_input(value, decision, earned="60")
    standards = standards_input(value, decision)

    conventional_outcome = calculate_conventional_grade(conventional)
    standards_outcome = calculate_standards_grade(standards)
    assert conventional_outcome.rounded_grade == Decimal("60")
    assert standards_outcome.rounded_grade == Decimal("62")

    outcome = calculate_hybrid_grade(
        hybrid_input(value, decision, conventional, standards)
    )
    assert outcome.weighted_numerator == Decimal("60.45")
    assert outcome.unrounded_grade == Decimal("60.45")
    assert outcome.rounded_grade == Decimal("60")

    rounded_component_shortcut = Decimal("60") * Decimal("0.7") + Decimal(
        "62"
    ) * Decimal("0.3")
    assert rounded_component_shortcut == Decimal("60.6")
    assert rounded_component_shortcut.quantize(Decimal("1")) != outcome.rounded_grade


def test_insufficient_component_blocks_when_policy_says_blocking() -> None:
    value = policy(
        state_treatment=treatment(
            missing="exclude",
            insufficient_evidence="blocking",
        )
    )
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned="82"),
            standards_input(value, decision, status="missing"),
        )
    )

    assert outcome.status == "blocked"
    assert outcome.rounded_grade is None
    assert outcome.standards_component.source_status == "insufficient"
    assert outcome.standards_component.action == "blocking"
    assert len(outcome.reasons) == 1
    assert outcome.reasons[0].code == "blocking_component"
    assert outcome.reasons[0].component_kind == "standards_based"


def test_explicit_insufficient_exclusion_renormalizes_active_component() -> None:
    value = policy(
        state_treatment=treatment(
            missing="exclude",
            insufficient_evidence="exclude",
        )
    )
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned="82"),
            standards_input(value, decision, status="missing"),
        )
    )

    assert outcome.status == "calculated"
    assert outcome.standards_component.action == "exclude"
    assert outcome.active_weight == Decimal("0.7")
    assert outcome.weighted_numerator == Decimal("57.4")
    assert outcome.unrounded_grade == Decimal("82")
    assert outcome.rounded_grade == Decimal("82.00")


def test_no_active_components_is_insufficient_not_zero() -> None:
    value = policy(
        state_treatment=treatment(
            missing="exclude",
            insufficient_evidence="exclude",
        )
    )
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned=None, state="excused"),
            standards_input(value, decision, status="missing"),
        )
    )

    assert outcome.status == "insufficient"
    assert outcome.active_weight is None
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert tuple(reason.code for reason in outcome.reasons) == (
        "no_calculable_components",
    )


def test_calculated_zero_retains_its_hybrid_component_weight() -> None:
    value = policy(
        conventional_weight="0.5",
        standards_weight="0.5",
        standards_grade_value="100",
        state_treatment=treatment(missing="zero"),
    )
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned=None, state="missing"),
            standards_input(value, decision),
        )
    )

    assert outcome.conventional_component.source_status == "calculated"
    assert outcome.conventional_component.action == "contribute"
    assert outcome.conventional_component.unrounded_grade == Decimal("0")
    assert outcome.conventional_component.weighted_contribution == Decimal("0")
    assert outcome.active_weight == Decimal("1.0")
    assert outcome.rounded_grade == Decimal("50.00")


def test_blocked_component_always_blocks_hybrid() -> None:
    value = policy(state_treatment=treatment(missing="blocking"))
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned=None, state="missing"),
            standards_input(value, decision),
        )
    )

    assert outcome.status == "blocked"
    assert outcome.conventional_component.source_status == "blocked"
    assert outcome.conventional_component.action == "blocking"
    assert outcome.rounded_grade is None


def test_hybrid_grade_is_not_clamped_to_one_hundred() -> None:
    value = policy(
        conventional_weight="0.5",
        standards_weight="0.5",
        standards_grade_value="105",
    )
    decision = activation(value)
    outcome = calculate_hybrid_grade(
        hybrid_input(
            value,
            decision,
            conventional_input(value, decision, earned="120"),
            standards_input(value, decision),
        )
    )

    assert outcome.unrounded_grade == Decimal("112.5")
    assert outcome.rounded_grade == Decimal("112.50")


def test_canonical_basis_sha_and_fingerprint_are_deterministic() -> None:
    value = policy()
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="91"),
        standards_input(value, decision),
    )
    encoded = hybrid_grade_calculation_input_to_json_bytes(inputs)

    assert encoded.endswith(b"\n")
    assert hybrid_grade_calculation_input_to_json_bytes(inputs) == encoded
    assert hybrid_grade_calculation_input_sha256(inputs) == hashlib.sha256(
        encoded
    ).hexdigest()
    fingerprint = hybrid_grade_calculation_fingerprint(inputs)
    assert calculate_hybrid_grade(inputs).calculation_fingerprint == fingerprint

    changed = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="90"),
        standards_input(value, decision),
    )
    assert hybrid_grade_calculation_fingerprint(changed) != fingerprint


def test_hybrid_input_rejects_mixed_component_authority() -> None:
    value = policy()
    decision = activation(value)
    conventional = conventional_input(value, decision)
    standards = standards_input(value, decision)
    foreign_reference = replace(
        grade_policy_reference(value),
        policy_sha256="f" * 64,
    )
    mismatched = replace(standards, policy_reference=foreign_reference)

    with pytest.raises(
        HybridGradeValidationError,
        match="standards_based component must use the exact hybrid Grade policy",
    ):
        hybrid_input(value, decision, conventional, mismatched)


def test_standalone_component_constructors_still_reject_hybrid_policy() -> None:
    value = policy()
    decision = activation(value)
    conventional = conventional_input(value, decision)
    standards = standards_input(value, decision)

    with pytest.raises(ConventionalGradeValidationError):
        create_conventional_grade_calculation_input(
            policy=value,
            activation=decision,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            items=conventional.items,
        )

    with pytest.raises(StandardsGradeValidationError):
        create_standards_grade_calculation_input(
            policy=value,
            activation=decision,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            standards=standards.standards,
        )


def test_hybrid_combination_is_independent_of_ambient_decimal_precision() -> None:
    value = policy(standards_grade_value="61.5", quantum="0.001")
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="60"),
        standards_input(value, decision),
    )

    with localcontext() as context:
        context.prec = 6
        low_precision = calculate_hybrid_grade(inputs)
    with localcontext() as context:
        context.prec = 50
        high_precision = calculate_hybrid_grade(inputs)

    assert low_precision == high_precision
