from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from meridian.conventional_grade import calculate_conventional_grade
from meridian.grade_policy import (
    GradePolicyValidationError,
    GradeStateTreatment,
    ProfilePredicate,
)
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.standards_grade import calculate_standards_grade
from tests import test_conventional_grade as conventional
from tests import test_hybrid_grade as hybrid
from tests import test_issue99_profile_grade_integration as profile
from tests import test_standards_grade as standards

NON_GRADE_STATES = (
    "missing",
    "pending",
    "incomplete",
    "excused",
    "excluded",
    "not_applicable",
    "insufficient_evidence",
    "unavailable",
    "withdrawn",
    "invalid",
    "unresolved",
)
ZERO_CAPABLE_STATES = ("missing", "incomplete")
ZERO_FORBIDDEN_STATES = tuple(
    state for state in NON_GRADE_STATES if state not in ZERO_CAPABLE_STATES
)


def _all_exclude_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="exclude",
        pending="exclude",
        incomplete="exclude",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="exclude",
        unavailable="exclude",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="exclude",
    )


def test_issue61_zero_consequence_is_closed_to_missing_and_incomplete() -> None:
    baseline = _all_exclude_treatment()

    for state in ZERO_CAPABLE_STATES:
        treatment = replace(baseline, **{state: "zero"})
        assert getattr(treatment, state) == "zero"

    for state in ZERO_FORBIDDEN_STATES:
        with pytest.raises(GradePolicyValidationError):
            replace(baseline, **{state: "zero"})


def test_issue61_conventional_non_grade_states_do_not_become_numeric_zero() -> None:
    participation = conventional.total_item("issue61_state_item", "10")
    value = conventional.policy(
        conventional.ConventionalGradeConfiguration(
            "total_points",
            (participation,),
            (),
        ),
        state_treatment=_all_exclude_treatment(),
    )

    for state in NON_GRADE_STATES:
        outcome = calculate_conventional_grade(
            conventional.calculation_input(
                value,
                conventional.state_input(participation, state),
            )
        )
        result = outcome.item_results[0]

        assert result.source_state == state
        assert result.action == "exclude"
        assert result.earned is None
        assert result.possible is None
        assert result.percentage is None
        assert result.contribution is None

        assert outcome.status == "insufficient"
        assert outcome.total_earned is None
        assert outcome.total_possible is None
        assert outcome.final_fraction is None
        assert outcome.unrounded_grade is None
        assert outcome.rounded_grade is None


def test_issue61_conventional_zero_requires_explicit_policy() -> None:
    participation = conventional.total_item("issue61_zero_item", "10")
    configuration = conventional.ConventionalGradeConfiguration(
        "total_points",
        (participation,),
        (),
    )

    for state in ZERO_CAPABLE_STATES:
        treatment = replace(_all_exclude_treatment(), **{state: "zero"})
        value = conventional.policy(
            configuration,
            state_treatment=treatment,
        )
        outcome = calculate_conventional_grade(
            conventional.calculation_input(
                value,
                conventional.state_input(participation, state),
            )
        )
        result = outcome.item_results[0]

        assert result.source_state == state
        assert result.action == "zero"
        assert result.earned == Decimal("0")
        assert result.possible == Decimal("10")
        assert result.percentage == Decimal("0")

        assert outcome.status == "calculated"
        assert outcome.total_earned == Decimal("0")
        assert outcome.total_possible == Decimal("10")
        assert outcome.final_fraction == Decimal("0")
        assert outcome.unrounded_grade == Decimal("0")
        assert outcome.rounded_grade == Decimal("0.00")


def test_issue61_standards_non_grade_states_do_not_become_numeric_zero() -> None:
    configuration = standards.configuration(("std.issue61.state", "1"), minimum=1)
    participation = configuration.standards[0]
    value = standards.policy(
        configuration,
        state_treatment=_all_exclude_treatment(),
    )

    for state in NON_GRADE_STATES:
        outcome = calculate_standards_grade(
            standards.calculation_input(
                value,
                standards.state_input(participation, state),
            )
        )
        result = outcome.standard_results[0]

        assert result.source_state == state
        assert result.action == "exclude"
        assert result.proficiency_level_id is None
        assert result.converted_grade_value is None
        assert result.calculation_value is None
        assert result.weighted_contribution is None

        assert outcome.status == "insufficient"
        assert outcome.actual_calculated_result_count == 0
        assert outcome.active_weight is None
        assert outcome.weighted_numerator is None
        assert outcome.unrounded_grade is None
        assert outcome.rounded_grade is None


def test_issue61_standards_policy_zero_is_not_real_calculated_evidence() -> None:
    configuration = standards.configuration(("std.issue61.zero", "1"), minimum=1)
    participation = configuration.standards[0]

    for state in ZERO_CAPABLE_STATES:
        treatment = replace(_all_exclude_treatment(), **{state: "zero"})
        value = standards.policy(
            configuration,
            state_treatment=treatment,
        )
        outcome = calculate_standards_grade(
            standards.calculation_input(
                value,
                standards.state_input(participation, state),
            )
        )
        result = outcome.standard_results[0]

        assert result.source_state == state
        assert result.action == "zero"
        assert result.proficiency_level_id is None
        assert result.converted_grade_value is None
        assert result.calculation_value == Decimal("0")
        assert result.weighted_contribution == Decimal("0")

        assert outcome.actual_calculated_result_count == 0
        assert outcome.status == "insufficient"
        assert outcome.active_weight is None
        assert outcome.unrounded_grade is None
        assert outcome.rounded_grade is None


def test_issue61_profile_zero_never_fabricates_proficiency_or_fallback() -> None:
    predicate = ProfilePredicate(
        "two_meeting",
        "count_at_or_above",
        "focus",
        "meeting",
        minimum_count=2,
    )
    configuration = profile.profile_config(
        conversions=(("meeting", "87"),),
        high_predicate=predicate,
    )
    outcome = profile.calculate(
        configuration,
        profile.standard(configuration.standards[0], "meeting"),
        profile.standard(
            configuration.standards[1],
            None,
            status="missing",
        ),
        state_treatment=profile.treatment(missing="zero"),
    )

    assert outcome.actual_calculated_result_count == 1
    assert outcome.base_unrounded_grade == Decimal("43.5")
    assert outcome.profile_evaluation is not None

    high_band, fallback_band = outcome.profile_evaluation.bands
    high_predicate = high_band.predicates[0]
    assert high_band.status == "indeterminate"
    assert high_predicate.at_or_above_count == 1
    assert high_predicate.unknown_count == 1
    assert high_predicate.unknown_standard_ids == (profile.STD_B,)
    assert fallback_band.status == "matched"

    assert outcome.status == "insufficient"
    assert outcome.selected_profile_band_id is None
    assert outcome.profile_adjustment is None
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None


def test_issue61_hybrid_distinguishes_zero_from_insufficient() -> None:
    explicit_zero_policy = hybrid.policy(
        conventional_weight="0.5",
        standards_weight="0.5",
        standards_grade_value="100",
        state_treatment=hybrid.treatment(
            missing="zero",
            insufficient_evidence="exclude",
        ),
    )
    explicit_zero_activation = hybrid.activation(explicit_zero_policy)
    explicit_zero = calculate_hybrid_grade(
        hybrid.hybrid_input(
            explicit_zero_policy,
            explicit_zero_activation,
            hybrid.conventional_input(
                explicit_zero_policy,
                explicit_zero_activation,
                earned=None,
                state="missing",
            ),
            hybrid.standards_input(
                explicit_zero_policy,
                explicit_zero_activation,
            ),
        )
    )

    assert explicit_zero.conventional_component.source_status == "calculated"
    assert explicit_zero.conventional_component.action == "contribute"
    assert explicit_zero.conventional_component.unrounded_grade == Decimal("0")
    assert explicit_zero.conventional_component.weighted_contribution == Decimal("0")
    assert explicit_zero.active_weight == Decimal("1.0")
    assert explicit_zero.rounded_grade == Decimal("50.00")

    excluded_policy = hybrid.policy(
        conventional_weight="0.5",
        standards_weight="0.5",
        standards_grade_value="100",
        state_treatment=hybrid.treatment(
            missing="exclude",
            insufficient_evidence="exclude",
        ),
    )
    excluded_activation = hybrid.activation(excluded_policy)
    excluded = calculate_hybrid_grade(
        hybrid.hybrid_input(
            excluded_policy,
            excluded_activation,
            hybrid.conventional_input(
                excluded_policy,
                excluded_activation,
                earned=None,
                state="missing",
            ),
            hybrid.standards_input(
                excluded_policy,
                excluded_activation,
            ),
        )
    )

    assert excluded.conventional_component.source_status == "insufficient"
    assert excluded.conventional_component.action == "exclude"
    assert excluded.conventional_component.unrounded_grade is None
    assert excluded.conventional_component.weighted_contribution is None
    assert excluded.active_weight == Decimal("0.5")
    assert excluded.unrounded_grade == Decimal("100")
    assert excluded.rounded_grade == Decimal("100.00")
