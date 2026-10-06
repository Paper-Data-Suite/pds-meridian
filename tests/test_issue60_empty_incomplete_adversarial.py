from __future__ import annotations

from decimal import Decimal

from meridian.conventional_grade import calculate_conventional_grade
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.standards_grade import calculate_standards_grade
from tests import test_conventional_grade as conventional
from tests import test_hybrid_grade as hybrid
from tests import test_issue99_profile_grade_integration as profile
from tests import test_standards_grade as standards


def test_empty_inputs_remain_nonnumeric_across_grade_families() -> None:
    conventional_item = conventional.total_item("issue60_empty", "10")
    conventional_policy = conventional.policy(
        conventional.ConventionalGradeConfiguration(
            "total_points",
            (conventional_item,),
            (),
        )
    )
    conventional_outcome = calculate_conventional_grade(
        conventional.calculation_input(
            conventional_policy,
            conventional.state_input(conventional_item, "excused"),
        )
    )

    standards_config = standards.configuration(
        ("std.issue60.empty", "1"),
        minimum=1,
    )
    standards_policy = standards.policy(
        standards_config,
        state_treatment=standards.treatment(missing="exclude"),
    )
    standards_outcome = calculate_standards_grade(
        standards.calculation_input(
            standards_policy,
            standards.state_input(standards_config.standards[0], "missing"),
        )
    )

    hybrid_policy = hybrid.policy(
        state_treatment=hybrid.treatment(
            missing="exclude",
            insufficient_evidence="exclude",
        )
    )
    hybrid_activation = hybrid.activation(hybrid_policy)
    hybrid_outcome = calculate_hybrid_grade(
        hybrid.hybrid_input(
            hybrid_policy,
            hybrid_activation,
            hybrid.conventional_input(
                hybrid_policy,
                hybrid_activation,
                earned=None,
                state="excused",
            ),
            hybrid.standards_input(
                hybrid_policy,
                hybrid_activation,
                status="missing",
            ),
        )
    )

    assert conventional_outcome.status == "insufficient"
    assert conventional_outcome.unrounded_grade is None
    assert conventional_outcome.rounded_grade is None
    assert tuple(reason.code for reason in conventional_outcome.reasons) == (
        "no_calculable_items",
    )

    assert standards_outcome.status == "insufficient"
    assert standards_outcome.actual_calculated_result_count == 0
    assert standards_outcome.unrounded_grade is None
    assert standards_outcome.rounded_grade is None
    assert standards_outcome.standard_results[0].source_state == "missing"
    assert standards_outcome.standard_results[0].action == "exclude"

    assert hybrid_outcome.status == "insufficient"
    assert hybrid_outcome.active_weight is None
    assert hybrid_outcome.unrounded_grade is None
    assert hybrid_outcome.rounded_grade is None
    assert hybrid_outcome.conventional_component.action == "exclude"
    assert hybrid_outcome.standards_component.action == "exclude"
    assert tuple(reason.code for reason in hybrid_outcome.reasons) == (
        "no_calculable_components",
    )


def test_conventional_incomplete_state_keeps_policy_consequence_separate() -> None:
    observed = conventional.total_item("issue60_observed", "10")
    incomplete = conventional.total_item("issue60_incomplete", "100")
    configuration = conventional.ConventionalGradeConfiguration(
        "total_points",
        (observed, incomplete),
        (),
    )

    def calculate(consequence: str):
        value = conventional.policy(
            configuration,
            state_treatment=conventional.treatment(
                incomplete=consequence,
            ),
        )
        return calculate_conventional_grade(
            conventional.calculation_input(
                value,
                conventional.point_input(observed, "10", "10"),
                conventional.state_input(incomplete, "incomplete"),
            )
        )

    blocking = calculate("blocking")
    zero = calculate("zero")
    excluded = calculate("exclude")

    blocking_by_id = {
        item.grade_item.grade_item_id: item for item in blocking.item_results
    }
    zero_by_id = {
        item.grade_item.grade_item_id: item for item in zero.item_results
    }
    excluded_by_id = {
        item.grade_item.grade_item_id: item for item in excluded.item_results
    }

    assert blocking.status == "blocked"
    assert blocking.rounded_grade is None
    assert blocking_by_id["issue60_incomplete"].source_state == "incomplete"
    assert blocking_by_id["issue60_incomplete"].action == "blocking"

    assert zero.status == "calculated"
    assert zero.rounded_grade == Decimal("9.09")
    assert zero_by_id["issue60_incomplete"].source_state == "incomplete"
    assert zero_by_id["issue60_incomplete"].action == "zero"
    assert zero_by_id["issue60_incomplete"].possible == Decimal("100")

    assert excluded.status == "calculated"
    assert excluded.rounded_grade == Decimal("100.00")
    assert excluded_by_id["issue60_incomplete"].source_state == "incomplete"
    assert excluded_by_id["issue60_incomplete"].action == "exclude"


def test_standards_incomplete_state_keeps_policy_consequence_separate() -> None:
    configuration = standards.configuration(
        ("std.issue60.observed", "0.5"),
        ("std.issue60.incomplete", "0.5"),
        minimum=1,
    )

    participation_by_standard = {
        item.standard_id: item for item in configuration.standards
    }

    def calculate(consequence: str):
        value = standards.policy(
            configuration,
            state_treatment=standards.treatment(
                incomplete=consequence,
            ),
        )
        return calculate_standards_grade(
            standards.calculation_input(
                value,
                standards.calculated(
                    participation_by_standard["std.issue60.observed"],
                    "advanced",
                ),
                standards.state_input(
                    participation_by_standard["std.issue60.incomplete"],
                    "incomplete",
                ),
            )
        )

    blocking = calculate("blocking")
    zero = calculate("zero")
    excluded = calculate("exclude")

    blocking_by_standard = {
        item.standard_id: item for item in blocking.standard_results
    }
    zero_by_standard = {
        item.standard_id: item for item in zero.standard_results
    }
    excluded_by_standard = {
        item.standard_id: item for item in excluded.standard_results
    }

    assert blocking.status == "blocked"
    assert blocking.rounded_grade is None
    assert (
        blocking_by_standard["std.issue60.incomplete"].source_state
        == "incomplete"
    )
    assert blocking_by_standard["std.issue60.incomplete"].action == "blocking"

    assert zero.status == "calculated"
    assert zero.actual_calculated_result_count == 1
    assert zero.rounded_grade == Decimal("52.50")
    assert zero_by_standard["std.issue60.incomplete"].source_state == "incomplete"
    assert zero_by_standard["std.issue60.incomplete"].action == "zero"
    assert (
        zero_by_standard["std.issue60.incomplete"].calculation_value
        == Decimal("0")
    )

    assert excluded.status == "calculated"
    assert excluded.actual_calculated_result_count == 1
    assert excluded.rounded_grade == Decimal("105.00")
    assert (
        excluded_by_standard["std.issue60.incomplete"].source_state
        == "incomplete"
    )
    assert excluded_by_standard["std.issue60.incomplete"].action == "exclude"


def test_profile_unknown_remains_indeterminate_instead_of_low_proficiency() -> None:
    configuration = profile.profile_config(
        conversions=(("meeting", "87"),),
        high_predicate=profile.all_meeting(),
    )
    outcome = profile.calculate(
        configuration,
        profile.standard(configuration.standards[0], "meeting"),
        profile.standard(
            configuration.standards[1],
            None,
            status="missing",
        ),
    )

    assert outcome.status == "insufficient"
    assert outcome.base_unrounded_grade == Decimal("87")
    assert outcome.profile_evaluation is not None
    high_band, fallback_band = outcome.profile_evaluation.bands
    assert high_band.status == "indeterminate"
    assert fallback_band.status == "matched"
    assert outcome.selected_profile_band_id is None
    assert outcome.profile_adjustment is None
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert tuple(reason.code for reason in outcome.reasons) == (
        "profile_band_indeterminate",
    )


def test_hybrid_insufficient_component_consequence_is_policy_owned() -> None:
    def calculate(consequence: str):
        value = hybrid.policy(
            state_treatment=hybrid.treatment(
                missing="exclude",
                insufficient_evidence=consequence,
            )
        )
        decision = hybrid.activation(value)
        return calculate_hybrid_grade(
            hybrid.hybrid_input(
                value,
                decision,
                hybrid.conventional_input(value, decision, earned="82"),
                hybrid.standards_input(
                    value,
                    decision,
                    status="missing",
                ),
            )
        )

    blocking = calculate("blocking")
    excluded = calculate("exclude")

    assert blocking.standards_component.source_status == "insufficient"
    assert blocking.standards_component.action == "blocking"
    assert blocking.status == "blocked"
    assert blocking.rounded_grade is None

    assert excluded.standards_component.source_status == "insufficient"
    assert excluded.standards_component.action == "exclude"
    assert excluded.status == "calculated"
    assert excluded.active_weight == Decimal("0.7")
    assert excluded.unrounded_grade == Decimal("82")
    assert excluded.rounded_grade == Decimal("82.00")
