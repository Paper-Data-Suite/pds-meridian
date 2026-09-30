from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from meridian.grade_policy import (
    GradePolicyValidationError,
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
)

STANDARD_A = "https://standards.example/RL:9-10.1?edition=2026"
STANDARD_B = "https://standards.example/W:9-10.2?edition=2026"
STANDARD_C = "https://standards.example/SL:9-10.1?edition=2026"


def group(
    group_id: str = "focus",
    standard_ids: tuple[str, ...] = (STANDARD_A, STANDARD_B, STANDARD_C),
) -> ProfileStandardGroup:
    return ProfileStandardGroup(group_id, standard_ids)


def all_meeting(
    predicate_id: str = "all_focus_meeting",
    group_id: str = "focus",
) -> ProfilePredicate:
    return ProfilePredicate(
        predicate_id=predicate_id,
        kind="all_at_or_above",
        group_id=group_id,
        proficiency_level_id="meeting",
    )


def count_exceeding(
    *,
    predicate_id: str = "three_focus_exceeding",
    group_id: str = "focus",
    minimum_count: int = 3,
) -> ProfilePredicate:
    return ProfilePredicate(
        predicate_id=predicate_id,
        kind="count_at_or_above",
        group_id=group_id,
        proficiency_level_id="exceeding",
        minimum_count=minimum_count,
    )


def proportion_meeting(
    *,
    predicate_id: str = "majority_focus_meeting",
    group_id: str = "focus",
    minimum_proportion: Decimal = Decimal("0.6"),
) -> ProfilePredicate:
    return ProfilePredicate(
        predicate_id=predicate_id,
        kind="proportion_at_or_above",
        group_id=group_id,
        proficiency_level_id="meeting",
        minimum_proportion=minimum_proportion,
    )


def band(
    band_id: str,
    priority: int,
    minimum_grade: str,
    maximum_grade: str,
    predicates: tuple[ProfilePredicate, ...],
) -> ProfileGradeBand:
    return ProfileGradeBand(
        band_id=band_id,
        priority=priority,
        minimum_grade=Decimal(minimum_grade),
        maximum_grade=Decimal(maximum_grade),
        predicates=predicates,
    )


def configuration() -> ProfileConstraintConfiguration:
    return ProfileConstraintConfiguration(
        groups=(group(),),
        bands=(
            band(
                "a",
                1,
                "90",
                "100",
                (count_exceeding(), all_meeting()),
            ),
            band(
                "b",
                2,
                "80",
                "89.99",
                (proportion_meeting(),),
            ),
            band("fallback", 3, "0", "79.99", ()),
        ),
        fallback_band_id="fallback",
    )


def test_profile_contracts_are_frozen_and_canonicalized() -> None:
    value = configuration()

    assert tuple(item.group_id for item in value.groups) == ("focus",)
    assert tuple(item.band_id for item in value.bands) == ("a", "b", "fallback")
    assert value.groups[0].standard_ids == tuple(
        sorted((STANDARD_A, STANDARD_B, STANDARD_C))
    )
    assert tuple(
        item.predicate_id for item in value.bands[0].predicates
    ) == ("all_focus_meeting", "three_focus_exceeding")

    with pytest.raises(FrozenInstanceError):
        value.fallback_band_id = "other"  # type: ignore[misc]


def test_profile_group_rejects_empty_and_duplicate_membership() -> None:
    with pytest.raises(GradePolicyValidationError, match="at least one standard"):
        group(standard_ids=())

    with pytest.raises(GradePolicyValidationError, match="duplicate standards"):
        group(standard_ids=(STANDARD_A, STANDARD_A))


@pytest.mark.parametrize(
    "predicate",
    [
        lambda: ProfilePredicate(
            "bad",
            "all_at_or_above",
            "focus",
            "meeting",
            minimum_count=1,
        ),
        lambda: ProfilePredicate(
            "bad",
            "count_at_or_above",
            "focus",
            "meeting",
        ),
        lambda: ProfilePredicate(
            "bad",
            "count_at_or_above",
            "focus",
            "meeting",
            minimum_count=1,
            minimum_proportion=Decimal("0.5"),
        ),
        lambda: ProfilePredicate(
            "bad",
            "proportion_at_or_above",
            "focus",
            "meeting",
            minimum_count=1,
            minimum_proportion=Decimal("0.5"),
        ),
        lambda: ProfilePredicate(
            "bad",
            "proportion_at_or_above",
            "focus",
            "meeting",
            minimum_proportion=Decimal("1.01"),
        ),
    ],
)
def test_profile_predicate_shapes_fail_closed(predicate: object) -> None:
    with pytest.raises(GradePolicyValidationError):
        predicate()  # type: ignore[operator]


def test_profile_configuration_rejects_unknown_group_reference() -> None:
    with pytest.raises(GradePolicyValidationError, match="configured group"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band(
                    "a",
                    1,
                    "90",
                    "100",
                    (all_meeting(group_id="missing_group"),),
                ),
                band("fallback", 2, "0", "89.99", ()),
            ),
            fallback_band_id="fallback",
        )


def test_profile_count_cannot_exceed_group_size() -> None:
    with pytest.raises(GradePolicyValidationError, match="group size"):
        ProfileConstraintConfiguration(
            groups=(group(standard_ids=(STANDARD_A, STANDARD_B)),),
            bands=(
                band(
                    "a",
                    1,
                    "90",
                    "100",
                    (count_exceeding(minimum_count=3),),
                ),
                band("fallback", 2, "0", "89.99", ()),
            ),
            fallback_band_id="fallback",
        )


def test_profile_band_priority_is_contiguous_and_fallback_is_last() -> None:
    with pytest.raises(GradePolicyValidationError, match="contiguous"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("a", 1, "90", "100", (all_meeting(),)),
                band("fallback", 3, "0", "89.99", ()),
            ),
            fallback_band_id="fallback",
        )

    with pytest.raises(GradePolicyValidationError, match="lowest priority"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("fallback", 1, "0", "79.99", ()),
                band("a", 2, "90", "100", (all_meeting(),)),
            ),
            fallback_band_id="fallback",
        )


def test_profile_fallback_is_the_only_predicateless_band() -> None:
    with pytest.raises(GradePolicyValidationError, match="must not define"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("a", 1, "90", "100", (all_meeting(),)),
                band(
                    "fallback",
                    2,
                    "0",
                    "89.99",
                    (proportion_meeting(),),
                ),
            ),
            fallback_band_id="fallback",
        )

    with pytest.raises(GradePolicyValidationError, match="require profile predicates"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("a", 1, "90", "100", ()),
                band("fallback", 2, "0", "89.99", ()),
            ),
            fallback_band_id="fallback",
        )


def test_profile_predicate_ids_are_unique_across_bands() -> None:
    duplicate = all_meeting(predicate_id="same")
    with pytest.raises(GradePolicyValidationError, match="unique across"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("a", 1, "90", "100", (duplicate,)),
                band(
                    "b",
                    2,
                    "80",
                    "89.99",
                    (
                        proportion_meeting(
                            predicate_id="same",
                        ),
                    ),
                ),
                band("fallback", 3, "0", "79.99", ()),
            ),
            fallback_band_id="fallback",
        )


def test_profile_grade_bands_must_not_overlap() -> None:
    with pytest.raises(GradePolicyValidationError, match="must not overlap"):
        ProfileConstraintConfiguration(
            groups=(group(),),
            bands=(
                band("a", 1, "90", "100", (all_meeting(),)),
                band("b", 2, "80", "90", (proportion_meeting(),)),
                band("fallback", 3, "0", "79.99", ()),
            ),
            fallback_band_id="fallback",
        )
