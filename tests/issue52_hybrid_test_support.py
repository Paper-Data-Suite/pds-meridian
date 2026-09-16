from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeItemInput,
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
    HybridGradeCalculationInput,
    create_hybrid_grade_calculation_input,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeCalculationInput,
    StandardsGradeStandardInput,
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
