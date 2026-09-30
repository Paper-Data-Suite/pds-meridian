"""Pure three-valued proficiency-profile evaluation for standards Grades.

This module evaluates bounded profile predicates against exact proficiency-scale
authority. It does not calculate a numeric Grade, select a profile Grade band,
apply floor/cap constraints, round, override, persist, or write to an SIS.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grade_policy import (
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
)
from meridian.proficiency_mapping import ProficiencyScale
from meridian.standards_evidence import normalize_standard_id

ProfileEvaluationStatus: TypeAlias = Literal[
    "matched",
    "not_matched",
    "indeterminate",
]
ProfileBandSelectionStatus: TypeAlias = Literal["selected", "indeterminate"]

_PROFILE_STATUSES = frozenset({"matched", "not_matched", "indeterminate"})


class StandardsGradeProfileError(ValueError):
    """Base error for pure standards Grade profile evaluation."""


class StandardsGradeProfileValidationError(StandardsGradeProfileError):
    """Raised when profile evaluation inputs violate the exact contract."""


@dataclass(frozen=True, slots=True)
class ProfileStandardObservation:
    """One grouped standard's authoritative proficiency observation, if known."""

    standard_id: str
    proficiency_level_id: str | None

    def __post_init__(self) -> None:
        try:
            standard_id = normalize_standard_id(self.standard_id)
        except ValueError as error:
            raise StandardsGradeProfileValidationError(str(error)) from error
        level_id = self.proficiency_level_id
        if level_id is not None:
            try:
                level_id = validate_identifier(
                    level_id,
                    "proficiency_level_id",
                )
            except IdentifierValidationError as error:
                raise StandardsGradeProfileValidationError(str(error)) from error
        object.__setattr__(self, "standard_id", standard_id)
        object.__setattr__(self, "proficiency_level_id", level_id)


@dataclass(frozen=True, slots=True)
class ProfilePredicateEvaluation:
    """Structured evidence for one three-valued profile predicate."""

    predicate_id: str
    kind: str
    group_id: str
    threshold_level_id: str
    status: ProfileEvaluationStatus
    group_size: int
    known_count: int
    unknown_count: int
    at_or_above_count: int
    below_count: int
    at_or_above_standard_ids: tuple[str, ...]
    below_standard_ids: tuple[str, ...]
    unknown_standard_ids: tuple[str, ...]
    minimum_count: int | None
    minimum_proportion: Decimal | None

    def __post_init__(self) -> None:
        if self.status not in _PROFILE_STATUSES:
            raise StandardsGradeProfileValidationError(
                "profile predicate evaluation status is invalid."
            )
        if self.group_size <= 0:
            raise StandardsGradeProfileValidationError(
                "profile predicate evaluation group_size must be positive."
            )
        for field_name in (
            "known_count",
            "unknown_count",
            "at_or_above_count",
            "below_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise StandardsGradeProfileValidationError(
                    f"{field_name} must be a nonnegative integer."
                )
        if self.known_count + self.unknown_count != self.group_size:
            raise StandardsGradeProfileValidationError(
                "known_count plus unknown_count must equal group_size."
            )
        if self.at_or_above_count + self.below_count != self.known_count:
            raise StandardsGradeProfileValidationError(
                "known profile observations must partition above/below threshold."
            )
        evidence_ids = (
            self.at_or_above_standard_ids
            + self.below_standard_ids
            + self.unknown_standard_ids
        )
        if len(evidence_ids) != self.group_size:
            raise StandardsGradeProfileValidationError(
                "predicate evidence must contain exactly the profile group."
            )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise StandardsGradeProfileValidationError(
                "predicate evidence standard IDs must not contain duplicates."
            )


@dataclass(frozen=True, slots=True)
class ProfileBandEvaluation:
    """Conjunctive three-valued evaluation for one ordered profile Grade band."""

    band_id: str
    priority: int
    status: ProfileEvaluationStatus
    predicates: tuple[ProfilePredicateEvaluation, ...]

    def __post_init__(self) -> None:
        if type(self.priority) is not int or self.priority <= 0:
            raise StandardsGradeProfileValidationError(
                "profile band evaluation priority must be positive."
            )
        if self.status not in _PROFILE_STATUSES:
            raise StandardsGradeProfileValidationError(
                "profile band evaluation status is invalid."
            )
        if any(
            not isinstance(item, ProfilePredicateEvaluation)
            for item in self.predicates
        ):
            raise StandardsGradeProfileValidationError(
                "profile band predicates must be predicate evaluations."
            )


@dataclass(frozen=True, slots=True)
class ProfileConstraintEvaluation:
    """Complete ordered pure evaluation of one profile-constraint authority."""

    bands: tuple[ProfileBandEvaluation, ...]

    def __post_init__(self) -> None:
        if not self.bands:
            raise StandardsGradeProfileValidationError(
                "profile evaluation must contain at least one band."
            )
        if any(not isinstance(item, ProfileBandEvaluation) for item in self.bands):
            raise StandardsGradeProfileValidationError(
                "profile evaluation bands must be ProfileBandEvaluation values."
            )
        priorities = tuple(item.priority for item in self.bands)
        if priorities != tuple(range(1, len(self.bands) + 1)):
            raise StandardsGradeProfileValidationError(
                "profile evaluation bands must be ordered by contiguous priority."
            )



@dataclass(frozen=True, slots=True)
class ProfileBandSelection:
    """Deterministic ordered selection result over evaluated profile bands."""

    status: ProfileBandSelectionStatus
    selected_band_id: str | None
    blocking_band_id: str | None

    def __post_init__(self) -> None:
        if self.status == "selected":
            if self.selected_band_id is None or self.blocking_band_id is not None:
                raise StandardsGradeProfileValidationError(
                    "selected profile band requires selected_band_id only."
                )
        elif self.status == "indeterminate":
            if self.blocking_band_id is None or self.selected_band_id is not None:
                raise StandardsGradeProfileValidationError(
                    "indeterminate profile selection requires blocking_band_id only."
                )
        else:
            raise StandardsGradeProfileValidationError(
                "profile band selection status is invalid."
            )


def select_profile_grade_band(
    evaluation: ProfileConstraintEvaluation,
) -> ProfileBandSelection:
    """Select the first safely eligible band, blocking on earlier uncertainty."""

    if not isinstance(evaluation, ProfileConstraintEvaluation):
        raise StandardsGradeProfileValidationError(
            "evaluation must be ProfileConstraintEvaluation."
        )
    for band in evaluation.bands:
        if band.status == "indeterminate":
            return ProfileBandSelection(
                status="indeterminate",
                selected_band_id=None,
                blocking_band_id=band.band_id,
            )
        if band.status == "matched":
            return ProfileBandSelection(
                status="selected",
                selected_band_id=band.band_id,
                blocking_band_id=None,
            )
    raise StandardsGradeProfileValidationError(
        "profile evaluation contains no selectable or indeterminate band."
    )

def evaluate_profile_constraints(
    constraints: ProfileConstraintConfiguration,
    scale: ProficiencyScale,
    observations: Iterable[ProfileStandardObservation],
) -> ProfileConstraintEvaluation:
    """Evaluate every profile Grade band without selecting or constraining one."""

    if not isinstance(constraints, ProfileConstraintConfiguration):
        raise StandardsGradeProfileValidationError(
            "constraints must be ProfileConstraintConfiguration."
        )
    if not isinstance(scale, ProficiencyScale):
        raise StandardsGradeProfileValidationError(
            "scale must be ProficiencyScale."
        )

    try:
        observation_values = tuple(observations)
    except TypeError as error:
        raise StandardsGradeProfileValidationError(
            "observations must be an iterable of ProfileStandardObservation values."
        ) from error
    if any(
        not isinstance(item, ProfileStandardObservation)
        for item in observation_values
    ):
        raise StandardsGradeProfileValidationError(
            "observations must contain only ProfileStandardObservation values."
        )

    observation_by_standard: dict[str, ProfileStandardObservation] = {}
    for item in observation_values:
        if item.standard_id in observation_by_standard:
            raise StandardsGradeProfileValidationError(
                "profile observations must not contain duplicate standard IDs."
            )
        observation_by_standard[item.standard_id] = item

    required_standard_ids = {
        standard_id
        for group in constraints.groups
        for standard_id in group.standard_ids
    }
    if set(observation_by_standard) != required_standard_ids:
        raise StandardsGradeProfileValidationError(
            "profile observations must exactly match grouped standards."
        )

    positions = {level.level_id: level.position for level in scale.levels}
    for item in observation_values:
        level_id = item.proficiency_level_id
        if level_id is not None and level_id not in positions:
            raise StandardsGradeProfileValidationError(
                "profile observation proficiency level must exist in exact scale."
            )
    for band in constraints.bands:
        for predicate in band.predicates:
            if predicate.proficiency_level_id not in positions:
                raise StandardsGradeProfileValidationError(
                    "profile predicate proficiency level must exist in exact scale."
                )

    groups = {group.group_id: group for group in constraints.groups}
    return ProfileConstraintEvaluation(
        bands=tuple(
            _evaluate_band(
                band,
                groups,
                positions,
                observation_by_standard,
            )
            for band in constraints.bands
        )
    )


def _evaluate_band(
    band: ProfileGradeBand,
    groups: dict[str, ProfileStandardGroup],
    positions: dict[str, int],
    observations: dict[str, ProfileStandardObservation],
) -> ProfileBandEvaluation:
    predicate_results = tuple(
        _evaluate_predicate(
            predicate,
            groups,
            positions,
            observations,
        )
        for predicate in band.predicates
    )
    if not predicate_results:
        status: ProfileEvaluationStatus = "matched"
    elif any(item.status == "not_matched" for item in predicate_results):
        status = "not_matched"
    elif any(item.status == "indeterminate" for item in predicate_results):
        status = "indeterminate"
    else:
        status = "matched"
    return ProfileBandEvaluation(
        band_id=band.band_id,
        priority=band.priority,
        status=status,
        predicates=predicate_results,
    )


def _evaluate_predicate(
    predicate: ProfilePredicate,
    groups: dict[str, ProfileStandardGroup],
    positions: dict[str, int],
    observations: dict[str, ProfileStandardObservation],
) -> ProfilePredicateEvaluation:
    try:
        group = groups[predicate.group_id]
    except KeyError as error:
        raise StandardsGradeProfileValidationError(
            "profile predicate group authority is unavailable."
        ) from error
    standard_ids = group.standard_ids
    threshold_position = positions[predicate.proficiency_level_id]

    above: list[str] = []
    below: list[str] = []
    unknown: list[str] = []
    for standard_id in standard_ids:
        observation = observations[standard_id]
        level_id = observation.proficiency_level_id
        if level_id is None:
            unknown.append(standard_id)
        elif positions[level_id] >= threshold_position:
            above.append(standard_id)
        else:
            below.append(standard_id)

    above_ids = tuple(sorted(above))
    below_ids = tuple(sorted(below))
    unknown_ids = tuple(sorted(unknown))
    group_size = len(standard_ids)

    if predicate.kind == "all_at_or_above":
        if below_ids:
            status: ProfileEvaluationStatus = "not_matched"
        elif unknown_ids:
            status = "indeterminate"
        else:
            status = "matched"
    elif predicate.kind == "count_at_or_above":
        minimum = predicate.minimum_count
        if minimum is None:
            raise StandardsGradeProfileValidationError(
                "count predicate is missing minimum_count."
            )
        if len(above_ids) >= minimum:
            status = "matched"
        elif len(above_ids) + len(unknown_ids) < minimum:
            status = "not_matched"
        else:
            status = "indeterminate"
    elif predicate.kind == "proportion_at_or_above":
        minimum_proportion = predicate.minimum_proportion
        if minimum_proportion is None:
            raise StandardsGradeProfileValidationError(
                "proportion predicate is missing minimum_proportion."
            )
        threshold = minimum_proportion * Decimal(group_size)
        if Decimal(len(above_ids)) >= threshold:
            status = "matched"
        elif Decimal(len(above_ids) + len(unknown_ids)) < threshold:
            status = "not_matched"
        else:
            status = "indeterminate"
    else:
        raise StandardsGradeProfileValidationError(
            "unsupported profile predicate kind."
        )

    return ProfilePredicateEvaluation(
        predicate_id=predicate.predicate_id,
        kind=predicate.kind,
        group_id=predicate.group_id,
        threshold_level_id=predicate.proficiency_level_id,
        status=status,
        group_size=group_size,
        known_count=len(above_ids) + len(below_ids),
        unknown_count=len(unknown_ids),
        at_or_above_count=len(above_ids),
        below_count=len(below_ids),
        at_or_above_standard_ids=above_ids,
        below_standard_ids=below_ids,
        unknown_standard_ids=unknown_ids,
        minimum_count=predicate.minimum_count,
        minimum_proportion=predicate.minimum_proportion,
    )
