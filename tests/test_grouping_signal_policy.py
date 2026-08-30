from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
    GroupingSignalPolicySerializationError,
    GroupingSignalPolicyValidationError,
    grouping_signal_derivation_policy_from_dict,
    grouping_signal_derivation_policy_from_json_bytes,
    grouping_signal_derivation_policy_reference,
    grouping_signal_derivation_policy_reference_from_dict,
    grouping_signal_derivation_policy_reference_to_dict,
    grouping_signal_derivation_policy_sha256,
    grouping_signal_derivation_policy_to_dict,
    grouping_signal_derivation_policy_to_json_bytes,
    is_grouping_signal_academic_basis_kind,
    is_grouping_signal_result_handling,
    is_grouping_signal_tie_handling,
    validate_grouping_signal_derivation_policy_against_scale,
    validate_grouping_signal_derivation_policy_dependencies,
    validate_grouping_signal_derivation_policy_transition,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_proficiency import StandardProficiencyActor

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "njsls-ela:RL.CR.9-10.1"
NOW = datetime(2026, 8, 30, 18, tzinfo=UTC)


def scale(*, revision: int = 1) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Teacher proficiency scale",
        description="Criterion-referenced scale used for standards proficiency.",
        levels=(
            ProficiencyLevel("level_1", 1, "Beginning", "Beginning evidence."),
            ProficiencyLevel("level_2", 2, "Developing", "Developing evidence."),
            ProficiencyLevel("level_3", 3, "Proficient", "Proficient evidence."),
            ProficiencyLevel("level_4", 4, "Extending", "Extending evidence."),
        ),
        proficiency_threshold_level_id="level_3",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def source_policy(
    *,
    target_scale: ProficiencyScale | None = None,
) -> AcademicPeriodProficiencyAggregationPolicy:
    exact_scale = target_scale or scale()
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_proficiency_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Academic Period proficiency",
        target_scale=proficiency_scale_reference(exact_scale),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def basis(
    *,
    exact_scale: ProficiencyScale | None = None,
    exact_source_policy: AcademicPeriodProficiencyAggregationPolicy | None = None,
) -> GroupingSignalAcademicBasis:
    selected_scale = exact_scale or scale()
    selected_policy = exact_source_policy or source_policy(target_scale=selected_scale)
    return GroupingSignalAcademicBasis(
        basis_kind="academic_period_proficiency",
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef("2026-2027", "mp1"),
            2,
        ),
        standard_id=STANDARD_ID,
        source_policy=academic_period_proficiency_aggregation_policy_reference(
            selected_policy
        ),
        target_scale=proficiency_scale_reference(selected_scale),
    )


def bands_three() -> tuple[GroupingSignalBandDefinition, ...]:
    return (
        GroupingSignalBandDefinition(1, 1, 1),
        GroupingSignalBandDefinition(2, 2, 3),
        GroupingSignalBandDefinition(3, 4, 4),
    )


def policy(
    *,
    revision: int = 1,
    academic_basis: GroupingSignalAcademicBasis | None = None,
    band_count: int = 3,
    band_definitions: tuple[GroupingSignalBandDefinition, ...] | None = None,
    tie_handling: str = "same_level_same_band",
    missing: str = "noncontributing",
    insufficient: str = "blocking",
    actor_kind: str = "teacher",
    revised_at: datetime | None = None,
) -> GroupingSignalDerivationPolicy:
    if band_definitions is None:
        band_definitions = bands_three()
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="reading_planning_signal",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Reading planning signal",
        academic_basis=academic_basis or basis(),
        dimension_id="reading_planning",
        band_count=band_count,
        band_definitions=band_definitions,
        tie_handling=tie_handling,  # type: ignore[arg-type]
        missing_result_handling=missing,  # type: ignore[arg-type]
        insufficient_result_handling=insufficient,  # type: ignore[arg-type]
        actor=GroupingSignalPolicyActor(  # type: ignore[arg-type]
            actor_kind,
            "teacher_local",
        ),
        rationale="Temporary contextual planning support.",
        revised_at=revised_at or NOW + timedelta(minutes=revision - 1),
    )


def test_policy_model_is_frozen_slotted_and_preserves_v1_identity() -> None:
    value = policy()
    assert value.schema_version == "1"
    assert value.record_type == "meridian_grouping_signal_derivation_policy"
    assert value.academic_basis.basis_kind == "academic_period_proficiency"
    assert value.academic_basis.target_period.calendar_revision == 2
    assert value.academic_basis.standard_id == STANDARD_ID
    assert value.dimension_id == "reading_planning"
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.title = "changed"  # type: ignore[misc]


def test_supported_closed_v1_values_are_explicit() -> None:
    assert is_grouping_signal_academic_basis_kind("academic_period_proficiency")
    assert not is_grouping_signal_academic_basis_kind("grade_item_proficiency")
    assert is_grouping_signal_tie_handling("same_level_same_band")
    assert not is_grouping_signal_tie_handling("split_equal_population")
    assert is_grouping_signal_result_handling("noncontributing")
    assert is_grouping_signal_result_handling("blocking")
    assert not is_grouping_signal_result_handling("lowest_band")


def test_academic_basis_requires_exact_matching_class_references() -> None:
    exact_scale = scale()
    exact_source = source_policy(target_scale=exact_scale)
    value = basis(exact_scale=exact_scale, exact_source_policy=exact_source)
    assert value.class_id == CLASS_ID

    wrong_scale_reference = replace(
        proficiency_scale_reference(exact_scale),
        class_id="other_class",
    )
    with pytest.raises(GroupingSignalPolicyValidationError, match="class_id"):
        replace(value, target_scale=wrong_scale_reference)

    with pytest.raises(GroupingSignalPolicyValidationError, match="basis kind"):
        replace(value, basis_kind="grade_item_proficiency")  # type: ignore[arg-type]


def test_dimension_id_is_explicit_path_safe_and_separate_from_standard() -> None:
    value = policy()
    assert value.dimension_id != value.academic_basis.standard_id
    with pytest.raises(GroupingSignalPolicyValidationError, match="dimension_id"):
        replace(value, dimension_id="Reading Planning / Current")


def test_three_band_partition_over_four_level_scale_is_valid() -> None:
    exact_scale = scale()
    exact_source = source_policy(target_scale=exact_scale)
    value = policy(
        academic_basis=basis(
            exact_scale=exact_scale,
            exact_source_policy=exact_source,
        )
    )
    assert (
        validate_grouping_signal_derivation_policy_dependencies(
            value,
            exact_source,
            exact_scale,
        )
        == value
    )
    assert tuple(item.band for item in value.band_definitions) == (1, 2, 3)
    assert value.band_definitions[1].minimum_scale_position == 2
    assert value.band_definitions[1].maximum_scale_position == 3


def test_band_definitions_are_canonicalized_by_band_number() -> None:
    value = policy(band_definitions=tuple(reversed(bands_three())))
    assert value.band_definitions == bands_three()


@pytest.mark.parametrize(
    "definitions",
    [
        (
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(1, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        (
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(3, 2, 3),
            GroupingSignalBandDefinition(4, 4, 4),
        ),
        (
            GroupingSignalBandDefinition(1, 1, 2),
            GroupingSignalBandDefinition(2, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        (
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 3, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
    ],
)
def test_invalid_band_numbering_overlap_and_gaps_are_rejected(
    definitions: tuple[GroupingSignalBandDefinition, ...],
) -> None:
    with pytest.raises(GroupingSignalPolicyValidationError):
        policy(band_definitions=definitions)


def test_band_zero_reversed_range_and_count_one_are_rejected() -> None:
    with pytest.raises(GroupingSignalPolicyValidationError, match="positive integer"):
        GroupingSignalBandDefinition(0, 1, 1)
    with pytest.raises(GroupingSignalPolicyValidationError, match="must not exceed"):
        GroupingSignalBandDefinition(1, 2, 1)
    with pytest.raises(GroupingSignalPolicyValidationError, match="at least 2"):
        policy(
            band_count=1,
            band_definitions=(GroupingSignalBandDefinition(1, 1, 4),),
        )


def test_scale_dependent_validation_requires_complete_exact_partition() -> None:
    exact_scale = scale()
    exact_source = source_policy(target_scale=exact_scale)
    exact_basis = basis(
        exact_scale=exact_scale,
        exact_source_policy=exact_source,
    )
    incomplete = policy(
        academic_basis=exact_basis,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 2, 2),
            GroupingSignalBandDefinition(3, 3, 3),
        ),
    )
    with pytest.raises(GroupingSignalPolicyValidationError, match="complete partition"):
        validate_grouping_signal_derivation_policy_against_scale(
            incomplete,
            exact_scale,
        )

    too_many = policy(
        academic_basis=exact_basis,
        band_count=5,
        band_definitions=tuple(
            GroupingSignalBandDefinition(index, index, index)
            for index in range(1, 6)
        ),
    )
    with pytest.raises(GroupingSignalPolicyValidationError, match="must not exceed"):
        validate_grouping_signal_derivation_policy_against_scale(
            too_many,
            exact_scale,
        )


def test_exact_dependency_validation_rejects_scale_or_source_policy_drift() -> None:
    exact_scale = scale()
    exact_source = source_policy(target_scale=exact_scale)
    value = policy(
        academic_basis=basis(
            exact_scale=exact_scale,
            exact_source_policy=exact_source,
        )
    )

    changed_scale = replace(
        exact_scale,
        scale_revision=2,
        supersedes_revision=1,
        revised_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(GroupingSignalPolicyValidationError, match="exact"):
        validate_grouping_signal_derivation_policy_dependencies(
            value,
            exact_source,
            changed_scale,
        )

    changed_source = replace(
        exact_source,
        policy_revision=2,
        supersedes_revision=1,
        revised_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(GroupingSignalPolicyValidationError, match="exact #35"):
        validate_grouping_signal_derivation_policy_dependencies(
            value,
            changed_source,
            exact_scale,
        )


def test_tie_and_missing_insufficient_semantics_are_closed_and_independent() -> None:
    value = policy(missing="blocking", insufficient="noncontributing")
    assert value.missing_result_handling == "blocking"
    assert value.insufficient_result_handling == "noncontributing"
    with pytest.raises(GroupingSignalPolicyValidationError, match="tie_handling"):
        policy(tie_handling="split_by_student_id")
    with pytest.raises(
        GroupingSignalPolicyValidationError,
        match="missing_result_handling",
    ):
        policy(missing="lowest_band")
    with pytest.raises(
        GroupingSignalPolicyValidationError,
        match="insufficient_result_handling",
    ):
        policy(insufficient="lowest_band")


def test_actor_text_and_timestamp_validation_follow_policy_conventions() -> None:
    assert policy(actor_kind="teacher").actor.kind == "teacher"
    assert policy(actor_kind="policy").actor.kind == "policy"
    with pytest.raises(GroupingSignalPolicyValidationError, match="actor kind"):
        policy(actor_kind="system")
    with pytest.raises(GroupingSignalPolicyValidationError, match="actor_id"):
        replace(
            policy(),
            actor=GroupingSignalPolicyActor("teacher", "x" * 257),
        )
    with pytest.raises(GroupingSignalPolicyValidationError, match="rationale"):
        replace(policy(), rationale="x" * 2001)
    with pytest.raises(GroupingSignalPolicyValidationError, match="timezone-aware"):
        replace(policy(), revised_at=datetime(2026, 8, 30, 18))

    local = datetime(
        2026,
        8,
        30,
        14,
        tzinfo=timezone(timedelta(hours=-4)),
    )
    assert replace(policy(), revised_at=local).revised_at == NOW


def test_revision_shape_and_transition_are_contiguous_and_explicit() -> None:
    first = policy()
    second = policy(revision=2)
    assert (
        validate_grouping_signal_derivation_policy_transition(first, second)
        == second
    )

    with pytest.raises(GroupingSignalPolicyValidationError, match="contiguous"):
        validate_grouping_signal_derivation_policy_transition(
            first,
            policy(revision=3),
        )
    with pytest.raises(GroupingSignalPolicyValidationError, match="logical identity"):
        validate_grouping_signal_derivation_policy_transition(
            first,
            replace(second, policy_id="another_policy"),
        )
    with pytest.raises(GroupingSignalPolicyValidationError, match="nondecreasing"):
        validate_grouping_signal_derivation_policy_transition(
            first,
            policy(revision=2, revised_at=NOW - timedelta(seconds=1)),
        )


def test_policy_mapping_json_and_reference_round_trip_are_exact() -> None:
    value = policy(missing="blocking", insufficient="noncontributing")
    mapping = grouping_signal_derivation_policy_to_dict(value)
    assert set(mapping) == {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "title",
        "academic_basis",
        "dimension_id",
        "band_count",
        "band_definitions",
        "tie_handling",
        "missing_result_handling",
        "insufficient_result_handling",
        "actor",
        "rationale",
        "revised_at",
    }
    assert grouping_signal_derivation_policy_from_dict(mapping) == value

    payload = grouping_signal_derivation_policy_to_json_bytes(value)
    assert payload.endswith(b"\n")
    assert grouping_signal_derivation_policy_from_json_bytes(payload) == value
    assert grouping_signal_derivation_policy_to_json_bytes(value) == payload

    reference = grouping_signal_derivation_policy_reference(value)
    assert reference.policy_sha256 == grouping_signal_derivation_policy_sha256(value)
    reference_mapping = grouping_signal_derivation_policy_reference_to_dict(reference)
    assert (
        grouping_signal_derivation_policy_reference_from_dict(reference_mapping)
        == reference
    )


def test_mapping_and_json_reject_missing_unknown_duplicate_and_noncanonical() -> None:
    mapping = grouping_signal_derivation_policy_to_dict(policy())
    missing = dict(mapping)
    missing.pop("dimension_id")
    with pytest.raises(GroupingSignalPolicyValidationError, match="missing"):
        grouping_signal_derivation_policy_from_dict(missing)

    unknown = dict(mapping)
    unknown["target_group_count"] = 4
    with pytest.raises(GroupingSignalPolicyValidationError, match="unknown"):
        grouping_signal_derivation_policy_from_dict(unknown)

    with pytest.raises(GroupingSignalPolicySerializationError, match="duplicate"):
        grouping_signal_derivation_policy_from_json_bytes(
            b'{"schema_version":"1","schema_version":"1"}'
        )
    with pytest.raises(
        GroupingSignalPolicySerializationError,
        match="numeric constant",
    ):
        grouping_signal_derivation_policy_from_json_bytes(b'{"value":NaN}')
    with pytest.raises(GroupingSignalPolicySerializationError, match="UTF-8"):
        grouping_signal_derivation_policy_from_json_bytes(b"\xff")

    canonical = grouping_signal_derivation_policy_to_json_bytes(policy())
    noncanonical = canonical.replace(b'  "actor"', b'    "actor"', 1)
    with pytest.raises(GroupingSignalPolicySerializationError, match="not canonical"):
        grouping_signal_derivation_policy_from_json_bytes(noncanonical)
