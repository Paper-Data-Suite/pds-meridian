from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal

import pytest

from meridian.conventional_grade import calculate_conventional_grade
from meridian.grade_policy import (
    GradeRoundingPolicy,
    HybridGradeConfiguration,
    ProficiencyGradeConversion,
)
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.standards_grade import (
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from tests import issue52_hybrid_test_support as hybrid
from tests import test_conventional_grade as conventional
from tests import test_issue99_hybrid_profile_integration as profile_hybrid
from tests import test_issue99_profile_grade_integration as profile
from tests import test_standards_grade as standards


def _rounding(mode: str) -> GradeRoundingPolicy:
    return GradeRoundingPolicy(Decimal("0.01"), mode, "final")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("half_up", Decimal("82.35")),
        ("half_even", Decimal("82.34")),
    ),
)
def test_half_tie_rounding_is_final_and_consistent_across_grade_families(
    mode: str,
    expected: Decimal,
) -> None:
    # Conventional: exact 82.345 survives to the final policy rounding boundary.
    item = conventional.total_item("issue60_rounding", "100")
    conventional_policy = conventional.policy(
        conventional.ConventionalGradeConfiguration(
            "total_points",
            (item,),
            (),
        )
    )
    conventional_policy = replace(
        conventional_policy,
        rounding=_rounding(mode),
    )
    conventional_outcome = calculate_conventional_grade(
        conventional.calculation_input(
            conventional_policy,
            conventional.point_input(item, "82.345", "100"),
        )
    )
    assert conventional_outcome.unrounded_grade == Decimal("82.345")
    assert conventional_outcome.rounded_grade == expected

    # Standards: exact conversion value survives the weighted mean unchanged.
    standards_config = standards.StandardsBasedGradeConfiguration(
        target_scale=standards.SCALE,
        standards=(
            standards.StandardGradeParticipation(
                "std.issue60.rounding",
                Decimal("1"),
            ),
        ),
        conversions=(
            standards.ProficiencyGradeConversion(
                "tie",
                Decimal("82.345"),
            ),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    standards_policy = standards.policy(standards_config)
    standards_policy = replace(
        standards_policy,
        rounding=_rounding(mode),
    )
    standards_outcome = calculate_standards_grade(
        standards.calculation_input(
            standards_policy,
            standards.calculated(
                standards_config.standards[0],
                "tie",
            ),
        )
    )
    assert standards_outcome.weighted_numerator == Decimal("82.345")
    assert standards_outcome.unrounded_grade == Decimal("82.345")
    assert standards_outcome.rounded_grade == expected

    # Hybrid: both exact component values remain 82.345 and only the final
    # hybrid Grade is rounded according to the same policy.
    hybrid_value = hybrid.policy(
        conventional_weight="0.5",
        standards_weight="0.5",
        standards_grade_value="82.345",
    )
    hybrid_value = replace(
        hybrid_value,
        rounding=_rounding(mode),
    )
    hybrid_decision = hybrid.activation(hybrid_value)
    hybrid_outcome = calculate_hybrid_grade(
        hybrid.hybrid_input(
            hybrid_value,
            hybrid_decision,
            hybrid.conventional_input(
                hybrid_value,
                hybrid_decision,
                earned="82.345",
            ),
            hybrid.standards_input(hybrid_value, hybrid_decision),
        )
    )
    assert hybrid_outcome.conventional_component.unrounded_grade == Decimal(
        "82.345"
    )
    assert hybrid_outcome.standards_component.unrounded_grade == Decimal(
        "82.345"
    )
    assert hybrid_outcome.weighted_numerator == Decimal("82.3450")
    assert hybrid_outcome.active_weight == Decimal("1.0")
    assert hybrid_outcome.unrounded_grade == Decimal("82.345")
    assert hybrid_outcome.rounded_grade == expected


def test_hybrid_combines_unrounded_components_not_component_display_grades() -> None:
    value = hybrid.policy(
        conventional_weight="0.7",
        standards_weight="0.3",
        standards_grade_value="82.3153",
    )
    decision = hybrid.activation(value)
    conventional_inputs = hybrid.conventional_input(
        value,
        decision,
        earned="82.3",
    )
    standards_inputs = hybrid.standards_input(value, decision)
    conventional_outcome = calculate_conventional_grade(conventional_inputs)
    standards_outcome = calculate_standards_grade(standards_inputs)
    outcome = calculate_hybrid_grade(
        hybrid.hybrid_input(
            value,
            decision,
            conventional_inputs,
            standards_inputs,
        )
    )

    assert conventional_outcome.unrounded_grade == Decimal("82.3")
    assert conventional_outcome.rounded_grade == Decimal("82.30")
    assert standards_outcome.unrounded_grade == Decimal("82.3153")
    assert standards_outcome.rounded_grade == Decimal("82.32")

    assert outcome.conventional_component.unrounded_grade == Decimal("82.3")
    assert outcome.standards_component.unrounded_grade == Decimal("82.3153")
    assert (
        outcome.conventional_component.component_calculation_fingerprint
        == conventional_outcome.calculation_fingerprint
    )
    assert (
        outcome.standards_component.component_calculation_fingerprint
        == standards_outcome.calculation_fingerprint
    )

    exact = (
        Decimal("82.3") * Decimal("0.7")
        + Decimal("82.3153") * Decimal("0.3")
    )
    prematurely_rounded = (
        Decimal("82.30") * Decimal("0.7")
        + Decimal("82.32") * Decimal("0.3")
    )
    assert exact == Decimal("82.30459")
    assert prematurely_rounded == Decimal("82.306")
    assert outcome.weighted_numerator == exact
    assert outcome.unrounded_grade == exact
    assert outcome.rounded_grade == Decimal("82.30")
    assert prematurely_rounded.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    ) == Decimal("82.31")


@pytest.mark.parametrize(
    (
        "levels",
        "conversions",
        "expected_base",
        "expected_band",
        "expected_adjustment",
        "expected_component",
    ),
    (
        (
            ("meeting", "meeting"),
            (("developing", "65"), ("meeting", "87"), ("exceeding", "97")),
            Decimal("87"),
            "high",
            "floor",
            Decimal("90"),
        ),
        (
            ("developing", "meeting"),
            (("developing", "95"), ("meeting", "97"), ("exceeding", "105")),
            Decimal("96"),
            "fallback",
            "cap",
            Decimal("89.99"),
        ),
        (
            ("meeting", "exceeding"),
            (("developing", "65"), ("meeting", "92"), ("exceeding", "98")),
            Decimal("95"),
            "high",
            "none",
            Decimal("95"),
        ),
    ),
    ids=("floor", "cap", "none"),
)
def test_profile_adjustment_is_resolved_once_then_consumed_by_hybrid(
    levels: tuple[str, str],
    conversions: tuple[tuple[str, str], ...],
    expected_base: Decimal,
    expected_band: str,
    expected_adjustment: str,
    expected_component: Decimal,
) -> None:
    exact_scale = profile_hybrid.profile_scale()
    value = profile_hybrid.profile_policy(
        exact_scale,
        insufficient_evidence="exclude",
    )
    configuration = value.configuration
    assert isinstance(configuration, HybridGradeConfiguration)

    standards_configuration = replace(
        configuration.standards_based,
        conversions=tuple(
            ProficiencyGradeConversion(level, Decimal(grade))
            for level, grade in conversions
        ),
    )
    value = replace(
        value,
        configuration=replace(
            configuration,
            standards_based=standards_configuration,
        ),
    )
    decision = profile_hybrid.activation(value)
    standards_input = profile_hybrid.profile_standards_input(
        value,
        decision,
        exact_scale,
        levels,
    )
    direct = calculate_standards_grade(standards_input)

    assert direct.status == "calculated"
    assert direct.base_unrounded_grade == expected_base
    assert direct.selected_profile_band_id == expected_band
    assert direct.profile_adjustment == expected_adjustment
    assert direct.unrounded_grade == expected_component

    outcome = calculate_hybrid_grade(
        profile_hybrid.hybrid_input(
            value,
            decision,
            profile_hybrid.conventional_input(
                value,
                decision,
                earned="80",
            ),
            standards_input,
        )
    )

    expected_hybrid = (
        Decimal("80") * Decimal("0.7")
        + expected_component * Decimal("0.3")
    )
    assert outcome.status == "calculated"
    assert outcome.standards_component.component_calculation_fingerprint == (
        direct.calculation_fingerprint
    )
    assert outcome.standards_component.unrounded_grade == expected_component
    assert outcome.standards_component.weighted_contribution == (
        expected_component * Decimal("0.3")
    )
    assert outcome.weighted_numerator == expected_hybrid
    assert outcome.unrounded_grade == expected_hybrid
    assert outcome.rounded_grade == expected_hybrid.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("half_up", Decimal("92.35")),
        ("half_even", Decimal("92.34")),
    ),
)
def test_profile_no_adjustment_rounds_only_after_exact_profile_mean(
    mode: str,
    expected: Decimal,
) -> None:
    configuration = profile.profile_config(
        conversions=(("meeting", "87.345"), ("exceeding", "97.345")),
        high_predicate=profile.all_meeting(),
    )
    value = profile.policy(configuration)
    value = replace(value, rounding=_rounding(mode))
    inputs = create_standards_grade_calculation_input(
        policy=value,
        activation=profile.activation(value),
        student_id=profile.STUDENT_ID,
        target_period=profile.PERIOD,
        calendar_revision=1,
        standards=(
            profile.standard(configuration.standards[0], "meeting"),
            profile.standard(configuration.standards[1], "exceeding"),
        ),
        target_scale_definition=profile.scale(),
    )
    outcome = calculate_standards_grade(inputs)

    assert outcome.base_unrounded_grade == Decimal("92.345")
    assert outcome.selected_profile_band_id == "high"
    assert outcome.profile_adjustment == "none"
    assert outcome.unrounded_grade == Decimal("92.345")
    assert outcome.rounded_grade == expected
