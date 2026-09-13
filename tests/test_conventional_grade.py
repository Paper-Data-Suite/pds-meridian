from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import (
    CONVENTIONAL_GRADE_ALGORITHM_VERSION,
    ConventionalGradeItemInput,
    ConventionalGradeProvenanceReference,
    ConventionalGradeValidationError,
    calculate_conventional_grade,
    conventional_grade_calculation_fingerprint,
    conventional_grade_calculation_input_to_json_bytes,
    create_conventional_grade_calculation_input,
    resolve_conventional_grade_item_input,
)
from meridian.evidence import NativePointValue
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyCategory,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    grade_policy_reference,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
SHA = "a" * 64


def item_ref(item_id: str) -> GradePolicyItemReference:
    return GradePolicyItemReference(CLASS_ID, item_id, 1, SHA)


def total_item(item_id: str, possible: str) -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        item_ref(item_id),
        None,
        None,
        Decimal(possible),
    )


def weighted_item(item_id: str, weight: str) -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        item_ref(item_id),
        None,
        Decimal(weight),
        None,
    )


def category_item(
    item_id: str,
    category_id: str,
    possible: str,
) -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        item_ref(item_id),
        category_id,
        None,
        Decimal(possible),
    )


def treatment(
    *,
    missing: str = "blocking",
    incomplete: str = "blocking",
    unresolved: str = "blocking",
) -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="blocking",
        incomplete=incomplete,  # type: ignore[arg-type]
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved=unresolved,  # type: ignore[arg-type]
    )


def policy(
    configuration: ConventionalGradeConfiguration,
    *,
    state_treatment: GradeStateTreatment | None = None,
    quantum: str = "0.01",
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course Grade Policy",
        calculation_family="conventional",
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


def point_input(
    participation: GradePolicyItemParticipation,
    earned: str,
    possible: str,
) -> ConventionalGradeItemInput:
    return ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="points",
        earned=Decimal(earned),
        possible=Decimal(possible),
    )


def state_input(
    participation: GradePolicyItemParticipation,
    status: str,
) -> ConventionalGradeItemInput:
    return ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=status,  # type: ignore[arg-type]
        earned=None,
        possible=None,
    )


def calculation_input(
    value: GradePolicyRevision,
    *items: ConventionalGradeItemInput,
):
    return create_conventional_grade_calculation_input(
        policy=value,
        activation=activation(value),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        items=tuple(items),
    )


def test_total_points_exact_arithmetic_and_final_only_rounding() -> None:
    a = total_item("quiz", "10")
    b = total_item("essay", "20")
    value = policy(ConventionalGradeConfiguration("total_points", (a, b), ()))
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(a, "10", "10"),
            point_input(b, "15", "20"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.total_earned == Decimal("25")
    assert outcome.total_possible == Decimal("30")
    assert outcome.final_fraction == Decimal("25") / Decimal("30")
    assert outcome.unrounded_grade == Decimal("25") / Decimal("30") * Decimal("100")
    assert outcome.rounded_grade == Decimal("83.33")
    assert outcome.algorithm_version == CONVENTIONAL_GRADE_ALGORITHM_VERSION


def test_total_points_missing_zero_uses_policy_denominator() -> None:
    small = total_item("small", "10")
    large = total_item("large", "100")
    value = policy(
        ConventionalGradeConfiguration("total_points", (small, large), ()),
        state_treatment=treatment(missing="zero"),
    )
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(small, "10", "10"),
            state_input(large, "missing"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.total_earned == Decimal("10")
    assert outcome.total_possible == Decimal("110")
    results = {
        result.grade_item.grade_item_id: result for result in outcome.item_results
    }
    assert results["large"].action == "zero"
    assert results["large"].possible == Decimal("100")


def test_excluded_total_points_item_removes_numerator_and_denominator() -> None:
    a = total_item("a", "10")
    b = total_item("b", "100")
    value = policy(ConventionalGradeConfiguration("total_points", (a, b), ()))
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(a, "9", "10"),
            state_input(b, "excused"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.total_earned == Decimal("9")
    assert outcome.total_possible == Decimal("10")
    assert outcome.rounded_grade == Decimal("90.00")


def test_blocking_item_prevents_numeric_final_grade() -> None:
    a = total_item("a", "10")
    b = total_item("b", "20")
    value = policy(ConventionalGradeConfiguration("total_points", (a, b), ()))
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(a, "10", "10"),
            state_input(b, "missing"),
        )
    )
    assert outcome.status == "blocked"
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert outcome.reasons[0].code == "blocking_item"
    assert outcome.reasons[0].grade_item == b.grade_item


def test_no_calculable_denominator_is_insufficient_not_zero() -> None:
    a = total_item("a", "10")
    value = policy(ConventionalGradeConfiguration("total_points", (a,), ()))
    outcome = calculate_conventional_grade(
        calculation_input(value, state_input(a, "excused"))
    )
    assert outcome.status == "insufficient"
    assert outcome.rounded_grade is None
    assert tuple(reason.code for reason in outcome.reasons) == (
        "no_calculable_items",
    )


def test_possible_points_mismatch_is_unresolved_without_rescaling() -> None:
    a = total_item("a", "10")
    value = policy(ConventionalGradeConfiguration("total_points", (a,), ()))
    resolved = resolve_conventional_grade_item_input(
        participation=a,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        point_observations=(NativePointValue(9, 20),),
        no_point_state="missing",
    )
    assert resolved.status == "unresolved"
    assert resolved.earned is None
    assert resolved.possible is None
    assert resolved.reason_codes == ("possible_points_mismatch",)
    outcome = calculate_conventional_grade(calculation_input(value, resolved))
    assert outcome.status == "blocked"
    assert outcome.item_results[0].source_state == "unresolved"


def test_direct_mismatched_points_input_also_fails_closed() -> None:
    a = total_item("a", "10")
    value = policy(ConventionalGradeConfiguration("total_points", (a,), ()))
    outcome = calculate_conventional_grade(
        calculation_input(value, point_input(a, "9", "20"))
    )
    assert outcome.status == "blocked"
    assert outcome.item_results[0].source_state == "unresolved"
    assert "possible_points_mismatch" in outcome.item_results[0].reason_codes


def test_extra_credit_is_not_clamped_to_one_hundred() -> None:
    a = total_item("a", "10")
    value = policy(ConventionalGradeConfiguration("total_points", (a,), ()))
    outcome = calculate_conventional_grade(
        calculation_input(value, point_input(a, "12", "10"))
    )
    assert outcome.unrounded_grade == Decimal("120")
    assert outcome.rounded_grade == Decimal("120.00")


def test_weighted_items_use_exact_weights_without_exclusion_renormalization() -> None:
    a = weighted_item("a", "0.6")
    b = weighted_item("b", "0.4")
    value = policy(ConventionalGradeConfiguration("weighted_items", (a, b), ()))
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(a, "9", "10"),
            state_input(b, "excused"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.item_results[0].percentage == Decimal("90")
    assert outcome.item_results[0].contribution == Decimal("0.54")
    assert outcome.final_fraction == Decimal("0.54")
    assert outcome.rounded_grade == Decimal("54.00")


def test_weighted_items_explicit_missing_zero_keeps_item_weight() -> None:
    a = weighted_item("a", "0.6")
    b = weighted_item("b", "0.4")
    value = policy(
        ConventionalGradeConfiguration("weighted_items", (a, b), ()),
        state_treatment=treatment(missing="zero"),
    )
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(a, "10", "10"),
            state_input(b, "missing"),
        )
    )
    assert outcome.status == "calculated"
    assert outcome.item_results[1].action == "zero"
    assert outcome.item_results[1].contribution == Decimal("0")
    assert outcome.rounded_grade == Decimal("60.00")


def test_weighted_categories_sum_points_within_category_then_apply_weight() -> None:
    q1 = category_item("q1", "practice", "10")
    q2 = category_item("q2", "practice", "20")
    test = category_item("test", "assessment", "100")
    configuration = ConventionalGradeConfiguration(
        "weighted_categories",
        (q1, q2, test),
        (
            GradePolicyCategory("practice", "Practice", Decimal("0.4")),
            GradePolicyCategory("assessment", "Assessments", Decimal("0.6")),
        ),
    )
    value = policy(configuration)
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            point_input(q1, "10", "10"),
            point_input(q2, "15", "20"),
            point_input(test, "80", "100"),
        )
    )
    assert outcome.status == "calculated"
    categories = {
        category.category_id: category for category in outcome.category_results
    }
    assert categories["practice"].earned == Decimal("25")
    assert categories["practice"].possible == Decimal("30")
    assert categories["practice"].contribution == (
        Decimal("25") / Decimal("30") * Decimal("0.4")
    )
    assert categories["assessment"].contribution == Decimal("0.48")
    expected = (
        Decimal("25") / Decimal("30") * Decimal("0.4") + Decimal("0.48")
    ) * Decimal("100")
    assert outcome.unrounded_grade == expected
    assert outcome.rounded_grade == Decimal("81.33")


def test_noncalculable_category_is_explicit_and_not_renormalized() -> None:
    q = category_item("q", "practice", "10")
    test = category_item("test", "assessment", "100")
    value = policy(
        ConventionalGradeConfiguration(
            "weighted_categories",
            (q, test),
            (
                GradePolicyCategory("practice", "Practice", Decimal("0.4")),
                GradePolicyCategory("assessment", "Assessments", Decimal("0.6")),
            ),
        )
    )
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            state_input(q, "excused"),
            point_input(test, "90", "100"),
        )
    )
    categories = {
        category.category_id: category for category in outcome.category_results
    }
    assert categories["practice"].status == "noncalculable"
    assert categories["practice"].contribution is None
    assert categories["assessment"].contribution == Decimal("0.54")
    assert outcome.status == "calculated"
    assert outcome.rounded_grade == Decimal("54.00")


def test_weighted_category_missing_zero_uses_policy_denominator() -> None:
    q = category_item("q", "practice", "10")
    test = category_item("test", "assessment", "100")
    value = policy(
        ConventionalGradeConfiguration(
            "weighted_categories",
            (q, test),
            (
                GradePolicyCategory("practice", "Practice", Decimal("0.4")),
                GradePolicyCategory("assessment", "Assessments", Decimal("0.6")),
            ),
        ),
        state_treatment=treatment(missing="zero"),
    )
    outcome = calculate_conventional_grade(
        calculation_input(
            value,
            state_input(q, "missing"),
            point_input(test, "100", "100"),
        )
    )
    categories = {
        category.category_id: category for category in outcome.category_results
    }
    assert categories["practice"].earned == Decimal("0")
    assert categories["practice"].possible == Decimal("10")
    assert categories["practice"].contribution == Decimal("0.0")
    assert outcome.rounded_grade == Decimal("60.00")


def test_two_operative_point_observations_are_unresolved_not_reduced() -> None:
    a = total_item("a", "10")
    resolved = resolve_conventional_grade_item_input(
        participation=a,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        point_observations=(NativePointValue(8, 10), NativePointValue(10, 10)),
        no_point_state="missing",
    )
    assert resolved.status == "unresolved"
    assert resolved.reason_codes == ("multiple_point_observations",)
    assert resolved.earned is None
    assert resolved.possible is None


def test_zero_observations_require_explicit_nonpoint_state() -> None:
    a = total_item("a", "10")
    resolved = resolve_conventional_grade_item_input(
        participation=a,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        point_observations=(),
        no_point_state="pending",
    )
    assert resolved.status == "pending"
    with pytest.raises(ConventionalGradeValidationError):
        resolve_conventional_grade_item_input(
            participation=a,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            point_observations=(),
            no_point_state="points",
        )


def test_native_integer_and_float_denominators_compare_by_decimal_meaning() -> None:
    a = total_item("a", "20")
    integer = resolve_conventional_grade_item_input(
        participation=a,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        point_observations=(NativePointValue(15, 20),),
        no_point_state="missing",
    )
    floating = resolve_conventional_grade_item_input(
        participation=a,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        point_observations=(NativePointValue(15.0, 20.0),),
        no_point_state="missing",
    )
    assert integer.status == floating.status == "points"
    assert integer.possible == floating.possible == Decimal("20")


def test_rounding_quantum_is_applied_only_to_final_grade() -> None:
    a = total_item("a", "3")
    value = policy(
        ConventionalGradeConfiguration("total_points", (a,), ()),
        quantum="0.01",
    )
    outcome = calculate_conventional_grade(
        calculation_input(value, point_input(a, "2", "3"))
    )
    assert outcome.item_results[0].percentage == (
        Decimal("2") / Decimal("3") * Decimal("100")
    )
    assert outcome.unrounded_grade == Decimal("2") / Decimal("3") * Decimal("100")
    assert outcome.rounded_grade == Decimal("66.67")


def test_fingerprint_is_deterministic_and_changes_with_material_basis() -> None:
    a = total_item("a", "10")
    b = total_item("b", "20")
    value = policy(ConventionalGradeConfiguration("total_points", (a, b), ()))
    provenance_a = ConventionalGradeProvenanceReference(
        "source", "publication:a", "1" * 64
    )
    provenance_b = ConventionalGradeProvenanceReference(
        "membership", "membership:b", "2" * 64
    )
    first_a = replace(
        point_input(a, "10", "10"),
        provenance=(provenance_b, provenance_a),
    )
    first_b = point_input(b, "15", "20")
    basis1 = calculation_input(value, first_b, first_a)
    basis2 = calculation_input(value, first_a, first_b)
    assert conventional_grade_calculation_fingerprint(basis1) == (
        conventional_grade_calculation_fingerprint(basis2)
    )
    assert conventional_grade_calculation_input_to_json_bytes(basis1) == (
        conventional_grade_calculation_input_to_json_bytes(basis2)
    )

    changed = calculation_input(
        value,
        replace(first_a, earned=Decimal("9")),
        first_b,
    )
    assert conventional_grade_calculation_fingerprint(changed) != (
        conventional_grade_calculation_fingerprint(basis1)
    )


def test_calculation_requires_exact_activated_policy_revision() -> None:
    a = total_item("a", "10")
    value = policy(ConventionalGradeConfiguration("total_points", (a,), ()))
    wrong = replace(
        activation(value),
        policy_reference=replace(
            grade_policy_reference(value),
            policy_sha256="0" * 64,
        ),
    )
    with pytest.raises(
        ConventionalGradeValidationError,
        match="exact supplied Grade-policy revision",
    ):
        create_conventional_grade_calculation_input(
            policy=value,
            activation=wrong,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            items=(point_input(a, "10", "10"),),
        )


def test_calculation_input_requires_exact_policy_participation_set() -> None:
    a = total_item("a", "10")
    b = total_item("b", "20")
    value = policy(ConventionalGradeConfiguration("total_points", (a, b), ()))
    with pytest.raises(
        ConventionalGradeValidationError,
        match="exactly match policy-participating",
    ):
        calculation_input(value, point_input(a, "10", "10"))
