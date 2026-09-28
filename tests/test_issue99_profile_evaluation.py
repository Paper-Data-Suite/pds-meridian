from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from meridian.grade_policy import (
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
)
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
)
from meridian.standards_grade_profile import (
    ProfileStandardObservation,
    StandardsGradeProfileValidationError,
    evaluate_profile_constraints,
)

NOW = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)
STANDARD_A = "std.a"
STANDARD_B = "std.b"
STANDARD_C = "std.c"
STANDARD_D = "std.d"


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id="synthetic_class_2026",
        scale_id="course_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Course Scale",
        description="Exact ordered proficiency authority.",
        levels=(
            ProficiencyLevel("developing", 1, "Developing", "Developing."),
            ProficiencyLevel("approaching", 2, "Approaching", "Approaching."),
            ProficiencyLevel("meeting", 3, "Meeting", "Meeting."),
            ProficiencyLevel("exceeding", 4, "Exceeding", "Exceeding."),
        ),
        proficiency_threshold_level_id="meeting",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def group() -> ProfileStandardGroup:
    return ProfileStandardGroup(
        "focus",
        (STANDARD_D, STANDARD_B, STANDARD_A, STANDARD_C),
    )


def constraints(
    *predicates: ProfilePredicate,
) -> ProfileConstraintConfiguration:
    return ProfileConstraintConfiguration(
        groups=(group(),),
        bands=(
            ProfileGradeBand(
                "candidate",
                1,
                Decimal("90"),
                Decimal("100"),
                predicates,
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
    )


def observations(
    a: str | None,
    b: str | None,
    c: str | None,
    d: str | None,
) -> tuple[ProfileStandardObservation, ...]:
    return (
        ProfileStandardObservation(STANDARD_D, d),
        ProfileStandardObservation(STANDARD_B, b),
        ProfileStandardObservation(STANDARD_A, a),
        ProfileStandardObservation(STANDARD_C, c),
    )


def evaluation_for(
    predicate: ProfilePredicate,
    values: tuple[ProfileStandardObservation, ...],
):
    result = evaluate_profile_constraints(
        constraints(predicate),
        scale(),
        values,
    )
    return result.bands[0].predicates[0]


def test_all_at_or_above_is_three_valued() -> None:
    predicate = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )

    matched = evaluation_for(
        predicate,
        observations("meeting", "exceeding", "meeting", "exceeding"),
    )
    assert matched.status == "matched"

    failed = evaluation_for(
        predicate,
        observations("approaching", None, "meeting", "meeting"),
    )
    assert failed.status == "not_matched"
    assert failed.below_standard_ids == (STANDARD_A,)
    assert failed.unknown_standard_ids == (STANDARD_B,)

    indeterminate = evaluation_for(
        predicate,
        observations("meeting", None, "meeting", "exceeding"),
    )
    assert indeterminate.status == "indeterminate"
    assert indeterminate.at_or_above_count == 3
    assert indeterminate.unknown_count == 1


def test_count_predicate_uses_known_lower_and_best_case_upper_bounds() -> None:
    predicate = ProfilePredicate(
        "two_meeting",
        "count_at_or_above",
        "focus",
        "meeting",
        minimum_count=2,
    )

    matched = evaluation_for(
        predicate,
        observations("meeting", "exceeding", None, None),
    )
    assert matched.status == "matched"

    indeterminate = evaluation_for(
        predicate,
        observations("meeting", "approaching", "developing", None),
    )
    assert indeterminate.status == "indeterminate"

    failed = evaluation_for(
        predicate,
        observations("meeting", "approaching", "developing", "approaching"),
    )
    assert failed.status == "not_matched"


def test_count_unknown_does_not_become_fabricated_low_proficiency() -> None:
    predicate = ProfilePredicate(
        "all_four",
        "count_at_or_above",
        "focus",
        "meeting",
        minimum_count=4,
    )
    result = evaluation_for(
        predicate,
        observations("meeting", "meeting", "meeting", None),
    )
    assert result.status == "indeterminate"
    assert result.below_count == 0
    assert result.unknown_count == 1


def test_proportion_predicate_bounds_can_resolve_despite_unknowns() -> None:
    predicate = ProfilePredicate(
        "three_quarters",
        "proportion_at_or_above",
        "focus",
        "meeting",
        minimum_proportion=Decimal("0.75"),
    )

    matched = evaluation_for(
        predicate,
        observations("meeting", "meeting", "exceeding", None),
    )
    assert matched.status == "matched"

    failed = evaluation_for(
        predicate,
        observations("meeting", "approaching", "developing", None),
    )
    assert failed.status == "not_matched"

    indeterminate = evaluation_for(
        predicate,
        observations("meeting", "meeting", "approaching", None),
    )
    assert indeterminate.status == "indeterminate"


def test_scale_position_defines_threshold_order() -> None:
    predicate = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )
    result = evaluation_for(
        predicate,
        observations("exceeding", "meeting", "exceeding", "meeting"),
    )
    assert result.status == "matched"
    assert result.at_or_above_standard_ids == (
        STANDARD_A,
        STANDARD_B,
        STANDARD_C,
        STANDARD_D,
    )


def test_band_predicates_are_conjunctive_with_three_valued_precedence() -> None:
    all_meeting = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )
    two_exceeding = ProfilePredicate(
        "two_exceeding",
        "count_at_or_above",
        "focus",
        "exceeding",
        minimum_count=2,
    )

    result = evaluate_profile_constraints(
        constraints(all_meeting, two_exceeding),
        scale(),
        observations("approaching", "exceeding", None, "meeting"),
    )
    candidate, fallback = result.bands

    statuses = {item.predicate_id: item.status for item in candidate.predicates}
    assert statuses == {
        "all_meeting": "not_matched",
        "two_exceeding": "indeterminate",
    }
    assert candidate.status == "not_matched"
    assert fallback.status == "matched"


def test_band_is_indeterminate_when_no_predicate_fails_and_one_is_unknown() -> None:
    all_meeting = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )
    one_exceeding = ProfilePredicate(
        "one_exceeding",
        "count_at_or_above",
        "focus",
        "exceeding",
        minimum_count=1,
    )

    result = evaluate_profile_constraints(
        constraints(all_meeting, one_exceeding),
        scale(),
        observations("meeting", "meeting", "meeting", None),
    )
    assert result.bands[0].status == "indeterminate"
    assert result.bands[1].status == "matched"


def test_evidence_and_band_order_are_deterministic() -> None:
    predicate = ProfilePredicate(
        "two_meeting",
        "count_at_or_above",
        "focus",
        "meeting",
        minimum_count=2,
    )
    result = evaluate_profile_constraints(
        constraints(predicate),
        scale(),
        observations("meeting", "approaching", None, "exceeding"),
    )

    assert tuple(item.priority for item in result.bands) == (1, 2)
    evidence = result.bands[0].predicates[0]
    assert evidence.at_or_above_standard_ids == (STANDARD_A, STANDARD_D)
    assert evidence.below_standard_ids == (STANDARD_B,)
    assert evidence.unknown_standard_ids == (STANDARD_C,)
    assert evidence.group_size == 4
    assert evidence.known_count == 3


def test_observations_must_exactly_match_grouped_standards() -> None:
    predicate = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )
    with pytest.raises(
        StandardsGradeProfileValidationError,
        match="exactly match grouped standards",
    ):
        evaluate_profile_constraints(
            constraints(predicate),
            scale(),
            (
                ProfileStandardObservation(STANDARD_A, "meeting"),
                ProfileStandardObservation(STANDARD_B, "meeting"),
            ),
        )

    with pytest.raises(
        StandardsGradeProfileValidationError,
        match="duplicate standard IDs",
    ):
        evaluate_profile_constraints(
            constraints(predicate),
            scale(),
            (
                ProfileStandardObservation(STANDARD_A, "meeting"),
                ProfileStandardObservation(STANDARD_A, "meeting"),
                ProfileStandardObservation(STANDARD_B, "meeting"),
                ProfileStandardObservation(STANDARD_C, "meeting"),
                ProfileStandardObservation(STANDARD_D, "meeting"),
            ),
        )


def test_unknown_proficiency_level_fails_closed() -> None:
    predicate = ProfilePredicate(
        "all_meeting",
        "all_at_or_above",
        "focus",
        "meeting",
    )
    with pytest.raises(
        StandardsGradeProfileValidationError,
        match="must exist in exact scale",
    ):
        evaluate_profile_constraints(
            constraints(predicate),
            scale(),
            observations("meeting", "not_a_level", "meeting", "meeting"),
        )
