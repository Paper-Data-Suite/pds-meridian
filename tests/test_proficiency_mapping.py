from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from meridian.evidence import (
    NativePointValue,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    NativeValueSourceSignature,
    PointRangeMappingRule,
    ProficiencyLevel,
    ProficiencyMappingSerializationError,
    ProficiencyMappingValidationError,
    ProficiencyScale,
    ScalarMappingRule,
    ScaledLevelMappingRule,
    map_native_value,
    native_value_mapping_profile_from_json_bytes,
    native_value_mapping_profile_to_json_bytes,
    proficiency_scale_from_json_bytes,
    proficiency_scale_reference,
    proficiency_scale_to_json_bytes,
    validate_native_value_mapping_profile_against_scale,
    validate_native_value_mapping_profile_transition,
    validate_proficiency_scale_transition,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 26, 17, tzinfo=UTC)


def actor() -> MappingActor:
    return MappingActor("teacher", "teacher_local")


def levels() -> tuple[ProficiencyLevel, ...]:
    return (
        ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
        ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
        ProficiencyLevel("proficient", 3, "Proficient", "Meets the criterion."),
        ProficiencyLevel("advanced", 4, "Advanced", "Extends the criterion."),
    )


def scale(*, revision: int = 1) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=levels(),
        proficiency_threshold_level_id="proficient",
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def signature(
    *,
    producer: str = "scoreform",
    result_kind: str = "question_correctness",
    target_kind: str = "question",
) -> NativeValueSourceSignature:
    return NativeValueSourceSignature(
        producer_module_id=producer,
        publication_kind="academic_result_set",
        manifest_contract_version=f"{producer}_academic_result_manifest_v1",
        producer_contract_version=f"{producer}_academic_work_v1",
        projection_id=f"{producer}.academic_result",
        projection_contract_version="1",
        producer_reader_distribution=(
            "pds-concord" if producer == "concord" else producer
        ),
        producer_reader_version="1.0.0",
        result_kind=result_kind,
        target_kind=target_kind,
    )


def native_scale(*, ordered: bool = True) -> NativeScale:
    return NativeScale(
        scale_id="rubric_024",
        levels=(
            NativeScaleLevel(0, "Low", "Limited"),
            NativeScaleLevel(2, "Middle", "Developing"),
            NativeScaleLevel(4, "High", "Strong"),
        ),
        order_is_meaningful=ordered,
    )


def scalar_profile(
    *, revision: int = 1, target_scale: ProficiencyScale | None = None
) -> NativeValueMappingProfile:
    target = target_scale or scale()
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="correctness_map",
        profile_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        target_scale=proficiency_scale_reference(target),
        source_signature=signature(),
        mapping_kind="exact_scalar",
        native_scale=None,
        points_possible=None,
        mapping_rules=(
            ScalarMappingRule(False, "beginning"),
            ScalarMappingRule(True, "proficient"),
        ),
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def test_scale_is_ordered_criterion_policy_not_numeric_score() -> None:
    value = scale()
    assert tuple(level.position for level in value.levels) == (1, 2, 3, 4)
    assert value.proficiency_threshold_level_id == "proficient"
    assert not hasattr(value.levels[0], "score")
    with pytest.raises(ProficiencyMappingValidationError, match="contiguous"):
        replace(
            value,
            levels=(
                ProficiencyLevel("low", 1, "Low", "Low criterion evidence."),
                ProficiencyLevel("high", 3, "High", "High criterion evidence."),
            ),
            proficiency_threshold_level_id="high",
        )


def test_scale_supports_non_four_level_policy_and_explicit_threshold() -> None:
    value = replace(
        scale(),
        levels=(
            ProficiencyLevel("emerging", 1, "Emerging", "Emerging evidence."),
            ProficiencyLevel("secure", 2, "Secure", "Meets the criterion."),
            ProficiencyLevel("extending", 3, "Extending", "Extends the criterion."),
        ),
        proficiency_threshold_level_id="secure",
    )
    assert len(value.levels) == 3
    assert value.proficiency_threshold_level_id == "secure"


def test_scale_and_profile_are_frozen_slotted_and_revisioned() -> None:
    value = scale()
    with pytest.raises(FrozenInstanceError):
        value.scale_id = "other"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")
    validate_proficiency_scale_transition(scale(), scale(revision=2))
    with pytest.raises(ProficiencyMappingValidationError, match="contiguous"):
        validate_proficiency_scale_transition(
            scale(),
            replace(scale(revision=2), scale_revision=3, supersedes_revision=2),
        )


def test_exact_scalar_mapping_preserves_native_type() -> None:
    target = scale()
    profile = scalar_profile(target_scale=target)
    mapped = map_native_value(NativeScalarValue(True), signature(), profile, target)
    assert mapped.status == "mapped"
    assert mapped.proficiency_level_id == "proficient"
    unmapped = map_native_value(NativeScalarValue(1), signature(), profile, target)
    assert unmapped.status == "unmapped"
    with pytest.raises(ProficiencyMappingValidationError, match="duplicate"):
        replace(
            profile,
            mapping_rules=(
                ScalarMappingRule(True, "proficient"),
                ScalarMappingRule(True, "advanced"),
            ),
        )


def test_source_signature_mismatch_is_unsupported_not_fallback() -> None:
    target = scale()
    profile = scalar_profile(target_scale=target)
    result = map_native_value(
        NativeScalarValue(True),
        signature(result_kind="selected_response"),
        profile,
        target,
    )
    assert result.status == "unsupported"
    assert result.unsupported_reason == "source_signature_mismatch"


def test_native_scale_mapping_is_exact_partial_and_noninterpolating() -> None:
    target = scale()
    source = native_scale()
    profile = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="quillan_024",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=signature(
            producer="quillan",
            result_kind="overall_standard_rating",
            target_kind="standard",
        ),
        mapping_kind="exact_native_scale",
        native_scale=source,
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "beginning"),
            ScaledLevelMappingRule(4, "advanced"),
        ),
        actor=actor(),
        rationale=None,
        revised_at=NOW,
    )
    validate_native_value_mapping_profile_against_scale(profile, target)
    sig = profile.source_signature
    assert (
        map_native_value(NativeScaledValue(0, source), sig, profile, target).status
        == "mapped"
    )
    assert (
        map_native_value(NativeScaledValue(2, source), sig, profile, target).status
        == "unmapped"
    )
    changed = NativeScale(
        scale_id=source.scale_id,
        levels=(
            NativeScaleLevel(0, "LOW", "Different meaning"),
            source.levels[1],
            source.levels[2],
        ),
    )
    unsupported = map_native_value(NativeScaledValue(0, changed), sig, profile, target)
    assert unsupported.status == "unsupported"
    assert unsupported.unsupported_reason == "native_scale_mismatch"


def test_ordered_native_scale_rejects_inversion_but_unordered_does_not() -> None:
    target = scale()
    source = native_scale()
    inverted = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="inverted",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=signature(
            producer="quillan",
            result_kind="overall_standard_rating",
            target_kind="standard",
        ),
        mapping_kind="exact_native_scale",
        native_scale=source,
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "advanced"),
            ScaledLevelMappingRule(4, "beginning"),
        ),
        actor=actor(),
        rationale=None,
        revised_at=NOW,
    )
    with pytest.raises(ProficiencyMappingValidationError, match="invert"):
        validate_native_value_mapping_profile_against_scale(inverted, target)
    validate_native_value_mapping_profile_against_scale(
        replace(inverted, native_scale=native_scale(ordered=False)), target
    )


def test_raw_points_bind_exact_possible_without_percentage_normalization() -> None:
    target = scale()
    profile = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="points_10",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=signature(result_kind="attempt_points", target_kind="attempt"),
        mapping_kind="raw_points",
        native_scale=None,
        points_possible=10,
        mapping_rules=(
            PointRangeMappingRule(None, False, 6, False, "beginning"),
            PointRangeMappingRule(6, True, 8, False, "developing"),
            PointRangeMappingRule(8, True, 9, False, "proficient"),
            PointRangeMappingRule(9, True, None, False, "advanced"),
        ),
        actor=actor(),
        rationale=None,
        revised_at=NOW,
    )
    validate_native_value_mapping_profile_against_scale(profile, target)
    sig = profile.source_signature
    eight_of_ten = map_native_value(NativePointValue(8, 10), sig, profile, target)
    assert eight_of_ten.status == "mapped"
    assert eight_of_ten.proficiency_level_id == "proficient"
    eight_of_twelve = map_native_value(NativePointValue(8, 12), sig, profile, target)
    assert eight_of_twelve.status == "unsupported"
    assert eight_of_twelve.unsupported_reason == "points_possible_mismatch"


def test_raw_point_ranges_may_have_gaps_but_not_overlap() -> None:
    target = scale()
    base = NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="gapped",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=signature(result_kind="attempt_points", target_kind="attempt"),
        mapping_kind="raw_points",
        native_scale=None,
        points_possible=10,
        mapping_rules=(
            PointRangeMappingRule(0, True, 4, True, "beginning"),
            PointRangeMappingRule(6, True, 10, True, "proficient"),
        ),
        actor=actor(),
        rationale=None,
        revised_at=NOW,
    )
    assert (
        map_native_value(
            NativePointValue(5, 10), base.source_signature, base, target
        ).status
        == "unmapped"
    )
    with pytest.raises(ProficiencyMappingValidationError, match="overlap"):
        replace(
            base,
            mapping_rules=(
                PointRangeMappingRule(0, True, 6, True, "beginning"),
                PointRangeMappingRule(6, True, 10, True, "proficient"),
            ),
        )


def test_native_state_never_becomes_low_proficiency() -> None:
    target = scale()
    profile = scalar_profile(target_scale=target)
    result = map_native_value(
        NativeStateValue("unrated"), signature(), profile, target
    )
    assert result.status == "native_state"
    assert result.native_state == NativeStateValue("unrated")
    assert result.proficiency_level_id is None


def test_profile_transition_preserves_logical_identity() -> None:
    first = scalar_profile()
    second = scalar_profile(revision=2)
    validate_native_value_mapping_profile_transition(first, second)
    with pytest.raises(ProficiencyMappingValidationError, match="logical identity"):
        validate_native_value_mapping_profile_transition(
            first, replace(second, profile_id="other_profile")
        )


def test_scale_and_profile_json_round_trip_are_exact() -> None:
    scale_value = scale()
    scale_bytes = proficiency_scale_to_json_bytes(scale_value)
    assert proficiency_scale_from_json_bytes(scale_bytes) == scale_value
    profile = scalar_profile(target_scale=scale_value)
    profile_bytes = native_value_mapping_profile_to_json_bytes(profile)
    assert native_value_mapping_profile_from_json_bytes(profile_bytes) == profile
    noncanonical = json.dumps(json.loads(scale_bytes), sort_keys=True).encode("utf-8")
    with pytest.raises(ProficiencyMappingSerializationError, match="canonical"):
        proficiency_scale_from_json_bytes(noncanonical)


def test_duplicate_json_keys_fail_closed() -> None:
    payload = proficiency_scale_to_json_bytes(scale()).decode("utf-8")
    duplicate = payload.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n  "class_id": "synthetic_class_2026",',
        1,
    ).encode("utf-8")
    with pytest.raises(ProficiencyMappingSerializationError, match="duplicate"):
        proficiency_scale_from_json_bytes(duplicate)
