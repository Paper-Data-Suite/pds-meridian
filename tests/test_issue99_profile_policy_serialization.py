from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    GradePolicyActor,
    GradePolicyRevision,
    GradePolicyValidationError,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
    grade_policy_revision_from_dict,
    grade_policy_revision_from_json_bytes,
    grade_policy_revision_to_dict,
    grade_policy_revision_to_json_bytes,
)
from meridian.proficiency_mapping import ProficiencyScaleReference

CLASS_ID = "synthetic_class_2026"
STANDARD_A = "https://standards.example/RL:9-10.1?edition=2026"
STANDARD_B = "https://standards.example/W:9-10.2?edition=2026"
STANDARD_C = "https://standards.example/SL:9-10.1?edition=2026"
SHA = "a" * 64
NOW = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)


def scale_ref() -> ProficiencyScaleReference:
    return ProficiencyScaleReference(CLASS_ID, "course_scale", 2, SHA)


def constraints() -> ProfileConstraintConfiguration:
    return ProfileConstraintConfiguration(
        groups=(ProfileStandardGroup("focus", (STANDARD_B, STANDARD_A)),),
        bands=(
            ProfileGradeBand(
                "a",
                1,
                Decimal("90"),
                Decimal("100"),
                (
                    ProfilePredicate(
                        "all_focus_meeting",
                        "all_at_or_above",
                        "focus",
                        "meeting",
                    ),
                    ProfilePredicate(
                        "one_focus_exceeding",
                        "count_at_or_above",
                        "focus",
                        "exceeding",
                        minimum_count=1,
                    ),
                ),
            ),
            ProfileGradeBand("fallback", 2, Decimal("0"), Decimal("89.99"), ()),
        ),
        fallback_band_id="fallback",
    )


def weighted_mean() -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=scale_ref(),
        standards=(
            StandardGradeParticipation(STANDARD_A, Decimal("0.5")),
            StandardGradeParticipation(STANDARD_B, Decimal("0.5")),
        ),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("65")),
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )


def profile_mean() -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=scale_ref(),
        standards=(
            StandardGradeParticipation(STANDARD_A, Decimal("0.5")),
            StandardGradeParticipation(STANDARD_B, Decimal("0.5")),
        ),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("65")),
            ProficiencyGradeConversion("meeting", Decimal("87")),
            ProficiencyGradeConversion("exceeding", Decimal("97")),
        ),
        aggregation_strategy="profile_constrained_mean",
        minimum_calculated_results=1,
        profile_constraints=constraints(),
    )


def treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def policy(configuration: StandardsBasedGradeConfiguration) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="standards_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Standards Policy",
        calculation_family="standards_based",
        configuration=configuration,
        state_treatment=treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def test_issue99_bumps_grade_policy_schema_to_v2() -> None:
    assert GRADE_POLICY_SCHEMA_VERSION == "2"
    data = grade_policy_revision_to_dict(policy(weighted_mean()))
    assert data["schema_version"] == "2"
    old = dict(data)
    old["schema_version"] = "1"
    with pytest.raises(GradePolicyValidationError, match='schema_version must be "2"'):
        grade_policy_revision_from_dict(old)


def test_weighted_mean_has_explicit_null_profile_constraints() -> None:
    value = policy(weighted_mean())
    data = grade_policy_revision_to_dict(value)
    configuration = data["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["aggregation_strategy"] == "weighted_mean"
    assert configuration["profile_constraints"] is None
    encoded = grade_policy_revision_to_json_bytes(value)
    assert b'"profile_constraints": null' in encoded
    assert grade_policy_revision_from_json_bytes(encoded) == value


def test_profile_constrained_mean_round_trips_canonically() -> None:
    value = policy(profile_mean())
    encoded = grade_policy_revision_to_json_bytes(value)
    decoded = grade_policy_revision_from_json_bytes(encoded)
    assert decoded == value
    assert b'"aggregation_strategy": "profile_constrained_mean"' in encoded
    assert b'"minimum_proportion": null' in encoded
    assert b'"minimum_count": 1' in encoded
    assert b'"minimum_grade": "90"' in encoded
    assert b'"maximum_grade": "100"' in encoded
    reference = grade_policy_reference(value)
    assert reference.policy_sha256 == hashlib.sha256(encoded).hexdigest()



def test_profile_band_zero_bounds_round_trip_canonically() -> None:
    value = ProfileGradeBand(
        "zero_band",
        1,
        Decimal("0"),
        Decimal("0"),
        (),
    )

    from meridian.grade_policy import (
        _profile_band_from_dict,
        _profile_band_to_dict,
    )

    encoded = _profile_band_to_dict(value)
    assert encoded["minimum_grade"] == "0"
    assert encoded["maximum_grade"] == "0"
    assert _profile_band_from_dict(encoded) == value

def test_profile_policy_canonicalizes_group_and_predicate_order() -> None:
    first = policy(profile_mean())
    reversed_constraints = ProfileConstraintConfiguration(
        groups=(ProfileStandardGroup("focus", (STANDARD_A, STANDARD_B)),),
        bands=(
            ProfileGradeBand(
                "a",
                1,
                Decimal("90.00"),
                Decimal("100.0"),
                (
                    ProfilePredicate(
                        "one_focus_exceeding",
                        "count_at_or_above",
                        "focus",
                        "exceeding",
                        minimum_count=1,
                    ),
                    ProfilePredicate(
                        "all_focus_meeting",
                        "all_at_or_above",
                        "focus",
                        "meeting",
                    ),
                ),
            ),
            ProfileGradeBand("fallback", 2, Decimal("0.0"), Decimal("89.990"), ()),
        ),
        fallback_band_id="fallback",
    )
    original = profile_mean()
    second = policy(
        StandardsBasedGradeConfiguration(
            target_scale=original.target_scale,
            standards=tuple(reversed(original.standards)),
            conversions=tuple(reversed(original.conversions)),
            aggregation_strategy="profile_constrained_mean",
            minimum_calculated_results=1,
            profile_constraints=reversed_constraints,
        )
    )
    assert grade_policy_revision_to_json_bytes(first) == (
        grade_policy_revision_to_json_bytes(second)
    )
    assert grade_policy_reference(first) == grade_policy_reference(second)


def test_strategy_and_profile_authority_are_mutually_bounded() -> None:
    base = weighted_mean()
    with pytest.raises(
        GradePolicyValidationError,
        match="weighted_mean must not define",
    ):
        StandardsBasedGradeConfiguration(
            target_scale=base.target_scale,
            standards=base.standards,
            conversions=base.conversions,
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
            profile_constraints=constraints(),
        )
    with pytest.raises(
        GradePolicyValidationError,
        match="requires profile_constraints",
    ):
        StandardsBasedGradeConfiguration(
            target_scale=base.target_scale,
            standards=base.standards,
            conversions=base.conversions,
            aggregation_strategy="profile_constrained_mean",
            minimum_calculated_results=1,
        )


def test_profile_groups_may_only_reference_participating_standards() -> None:
    base = weighted_mean()
    bad_constraints = ProfileConstraintConfiguration(
        groups=(ProfileStandardGroup("focus", (STANDARD_C,)),),
        bands=(
            ProfileGradeBand(
                "a",
                1,
                Decimal("90"),
                Decimal("100"),
                (
                    ProfilePredicate(
                        "all_focus_meeting",
                        "all_at_or_above",
                        "focus",
                        "meeting",
                    ),
                ),
            ),
            ProfileGradeBand("fallback", 2, Decimal("0"), Decimal("89.99"), ()),
        ),
        fallback_band_id="fallback",
    )
    with pytest.raises(GradePolicyValidationError, match="must participate"):
        StandardsBasedGradeConfiguration(
            target_scale=base.target_scale,
            standards=base.standards,
            conversions=base.conversions,
            aggregation_strategy="profile_constrained_mean",
            minimum_calculated_results=1,
            profile_constraints=bad_constraints,
        )


def test_profile_serialization_rejects_missing_or_unknown_shape() -> None:
    data = grade_policy_revision_to_dict(policy(profile_mean()))
    configuration = dict(data["configuration"])  # type: ignore[arg-type]
    missing = dict(configuration)
    del missing["profile_constraints"]
    data_missing = dict(data)
    data_missing["configuration"] = missing
    with pytest.raises(GradePolicyValidationError, match="exact schema"):
        grade_policy_revision_from_dict(data_missing)

    constraints_data = dict(configuration["profile_constraints"])  # type: ignore[arg-type]
    constraints_data["expression"] = "eval(student)"
    bad = dict(configuration)
    bad["profile_constraints"] = constraints_data
    data_bad = dict(data)
    data_bad["configuration"] = bad
    with pytest.raises(GradePolicyValidationError, match="exact schema"):
        grade_policy_revision_from_dict(data_bad)


def test_material_profile_changes_change_policy_digest() -> None:
    first = policy(profile_mean())
    original = profile_mean()
    profile = original.profile_constraints
    assert profile is not None
    changed_constraints = ProfileConstraintConfiguration(
        groups=profile.groups,
        bands=(
            ProfileGradeBand(
                "a",
                1,
                Decimal("91"),
                Decimal("100"),
                profile.bands[0].predicates,
            ),
            profile.bands[1],
        ),
        fallback_band_id="fallback",
    )
    changed = policy(
        StandardsBasedGradeConfiguration(
            target_scale=original.target_scale,
            standards=original.standards,
            conversions=original.conversions,
            aggregation_strategy="profile_constrained_mean",
            minimum_calculated_results=1,
            profile_constraints=changed_constraints,
        )
    )
    assert grade_policy_reference(first) != grade_policy_reference(changed)
