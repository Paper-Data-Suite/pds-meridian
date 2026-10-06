from __future__ import annotations

from decimal import Decimal, localcontext

from meridian.conventional_grade import calculate_conventional_grade
from meridian.grade_policy import ConventionalGradeConfiguration, GradePolicyCategory
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.standards_grade import calculate_standards_grade
from tests import test_conventional_grade as conventional_support
from tests import test_hybrid_grade as hybrid_support
from tests import test_standards_grade as standards_support


def _repeating_total_points_outcome():
    item = conventional_support.total_item("issue61_repeat", "3")
    value = conventional_support.policy(
        ConventionalGradeConfiguration("total_points", (item,), ())
    )
    return calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(item, "2", "3"),
        )
    )


def _repeating_weighted_category_outcome():
    practice = conventional_support.category_item(
        "issue61_practice",
        "practice",
        "3",
    )
    assessment = conventional_support.category_item(
        "issue61_assessment",
        "assessment",
        "7",
    )
    value = conventional_support.policy(
        ConventionalGradeConfiguration(
            "weighted_categories",
            (practice, assessment),
            (
                GradePolicyCategory(
                    "practice",
                    "Practice",
                    Decimal("0.4"),
                ),
                GradePolicyCategory(
                    "assessment",
                    "Assessment",
                    Decimal("0.6"),
                ),
            ),
        )
    )
    return calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(practice, "2", "3"),
            conventional_support.point_input(assessment, "5", "7"),
        )
    )


def test_issue61_conventional_arithmetic_ignores_ambient_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 6
        low_precision = _repeating_total_points_outcome()

    with localcontext() as context:
        context.prec = 80
        high_precision = _repeating_total_points_outcome()

    assert low_precision == high_precision
    assert low_precision.final_fraction == high_precision.final_fraction
    assert low_precision.unrounded_grade == high_precision.unrounded_grade
    assert low_precision.rounded_grade == Decimal("66.67")


def test_issue61_weighted_category_arithmetic_ignores_ambient_precision() -> None:
    with localcontext() as context:
        context.prec = 7
        low_precision = _repeating_weighted_category_outcome()

    with localcontext() as context:
        context.prec = 90
        high_precision = _repeating_weighted_category_outcome()

    assert low_precision == high_precision
    assert low_precision.category_results == high_precision.category_results
    assert low_precision.unrounded_grade == high_precision.unrounded_grade
    assert low_precision.rounded_grade == high_precision.rounded_grade


def test_issue61_conventional_exclusion_does_not_silently_renormalize() -> None:
    first = conventional_support.weighted_item("issue61_a", "0.6")
    second = conventional_support.weighted_item("issue61_b", "0.4")
    value = conventional_support.policy(
        ConventionalGradeConfiguration("weighted_items", (first, second), ())
    )

    outcome = calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(first, "9", "10"),
            conventional_support.state_input(second, "excused"),
        )
    )

    assert outcome.final_fraction == Decimal("0.54")
    assert outcome.unrounded_grade == Decimal("54")
    assert outcome.rounded_grade == Decimal("54.00")


def test_issue61_explicit_conventional_zero_retains_policy_denominator() -> None:
    small = conventional_support.total_item("issue61_small", "10")
    large = conventional_support.total_item("issue61_large", "100")
    value = conventional_support.policy(
        ConventionalGradeConfiguration("total_points", (small, large), ()),
        state_treatment=conventional_support.treatment(missing="zero"),
    )

    outcome = calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(small, "10", "10"),
            conventional_support.state_input(large, "missing"),
        )
    )

    assert outcome.total_earned == Decimal("10")
    assert outcome.total_possible == Decimal("110")
    assert outcome.rounded_grade == Decimal("9.09")


def test_issue61_standards_exclusion_renormalizes_only_from_policy_exclude() -> None:
    config = standards_support.configuration(
        ("std.issue61.a", "0.6"),
        ("std.issue61.b", "0.4"),
        minimum=1,
    )
    value = standards_support.policy(
        config,
        state_treatment=standards_support.treatment(missing="exclude"),
    )

    outcome = calculate_standards_grade(
        standards_support.calculation_input(
            value,
            standards_support.calculated(
                config.standards[0],
                "advanced",
            ),
            standards_support.state_input(
                config.standards[1],
                "missing",
            ),
        )
    )

    assert outcome.active_weight == Decimal("0.6")
    assert outcome.weighted_numerator == Decimal("63.0")
    assert outcome.unrounded_grade == Decimal("105")
    assert outcome.rounded_grade == Decimal("105.00")


def test_issue61_standards_policy_zero_retains_configured_weight() -> None:
    config = standards_support.configuration(
        ("std.issue61.a", "0.6"),
        ("std.issue61.b", "0.4"),
        minimum=1,
    )
    value = standards_support.policy(
        config,
        state_treatment=standards_support.treatment(missing="zero"),
    )

    outcome = calculate_standards_grade(
        standards_support.calculation_input(
            value,
            standards_support.calculated(
                config.standards[0],
                "proficient",
            ),
            standards_support.state_input(
                config.standards[1],
                "missing",
            ),
        )
    )

    assert outcome.active_weight == Decimal("1.0")
    assert outcome.weighted_numerator == Decimal("52.8")
    assert outcome.rounded_grade == Decimal("52.80")


def test_issue61_hybrid_exclusion_renormalizes_explicitly_and_uses_unrounded() -> None:
    value = hybrid_support.policy(
        conventional_weight="0.7",
        standards_weight="0.3",
        state_treatment=hybrid_support.treatment(
            insufficient_evidence="exclude"
        ),
    )
    decision = hybrid_support.activation(value)
    conventional = hybrid_support.conventional_input(
        value,
        decision,
        earned="82.345",
    )
    standards = hybrid_support.standards_input(
        value,
        decision,
        status="insufficient_evidence",
    )

    outcome = calculate_hybrid_grade(
        hybrid_support.hybrid_input(
            value,
            decision,
            conventional,
            standards,
        )
    )

    assert outcome.standards_component.action == "exclude"
    assert outcome.active_weight == Decimal("0.7")
    assert outcome.conventional_component.unrounded_grade == Decimal("82.345")
    assert outcome.weighted_numerator == Decimal("57.6415")
    assert outcome.unrounded_grade == Decimal("82.345")
    assert outcome.rounded_grade == Decimal("82.35")


def test_issue61_no_universal_grade_clamp() -> None:
    item = conventional_support.total_item("issue61_extra_credit", "10")
    value = conventional_support.policy(
        ConventionalGradeConfiguration("total_points", (item,), ())
    )

    above = calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(item, "12", "10"),
        )
    )
    below = calculate_conventional_grade(
        conventional_support.calculation_input(
            value,
            conventional_support.point_input(item, "-2", "10"),
        )
    )

    assert above.rounded_grade == Decimal("120.00")
    assert below.rounded_grade == Decimal("-20.00")
