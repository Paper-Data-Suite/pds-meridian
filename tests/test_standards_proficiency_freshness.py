from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    StandardProficiencyResultFreshness,
    StandardProficiencyResultSnapshot,
    StandardProficiencyValidationError,
    assess_standard_proficiency_result_freshness,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
    standard_proficiency_result_snapshot_to_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "grade_item_1"
STUDENT_ID = "student_1"
STANDARD_ID = "https://standards.example/RL:9-10.1?edition=2026"
NOW = datetime(2026, 8, 28, 1, 15, tzinfo=UTC)


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=(
            ProficiencyLevel("early", 1, "Early", "Early evidence."),
            ProficiencyLevel("secure", 2, "Secure", "Meets criterion."),
            ProficiencyLevel(
                "extended",
                3,
                "Extended",
                "Extends criterion.",
            ),
        ),
        proficiency_threshold_level_id="secure",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def policy(target: ProficiencyScale) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course proficiency policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("mapping_not_supplied",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def inputs(target: ProficiencyScale) -> StandardAggregationInputs:
    return StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            2,
            "6" * 64,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target),
        entries=(),
    )


def snapshot() -> StandardProficiencyResultSnapshot:
    target = scale()
    exact_inputs = inputs(target)
    outcome = calculate_standard_proficiency(
        exact_inputs,
        policy(target),
        target,
    )
    return create_standard_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )


def assess_current(
    value: StandardProficiencyResultSnapshot,
) -> StandardProficiencyResultFreshness:
    return assess_standard_proficiency_result_freshness(
        value,
        value.inputs,
        value.policy_reference,
        value.target_scale,
        value.algorithm_version,
    )


def test_identical_dependencies_are_current_and_do_not_mutate_result() -> None:
    value = snapshot()
    before = standard_proficiency_result_snapshot_to_json_bytes(value)

    freshness = assess_current(value)

    assert freshness.status == "current"
    assert freshness.reasons == ()
    assert standard_proficiency_result_snapshot_to_json_bytes(value) == before
    assert not hasattr(freshness, "__dict__")
    with pytest.raises(FrozenInstanceError):
        freshness.status = "stale"  # type: ignore[misc]


def test_changed_inputs_are_reported_without_recalculation() -> None:
    value = snapshot()
    changed_grade_item = replace(
        value.inputs.grade_item,
        grade_item_revision=3,
        grade_item_revision_sha256="7" * 64,
    )
    changed_inputs = replace(
        value.inputs,
        grade_item=changed_grade_item,
    )

    freshness = assess_standard_proficiency_result_freshness(
        value,
        changed_inputs,
        value.policy_reference,
        value.target_scale,
        value.algorithm_version,
    )

    assert freshness.status == "stale"
    assert freshness.reasons == ("inputs_changed",)


def test_changed_policy_reference_is_reported_independently() -> None:
    value = snapshot()
    changed_policy = replace(
        value.policy_reference,
        policy_revision=2,
        policy_sha256="7" * 64,
    )

    freshness = assess_standard_proficiency_result_freshness(
        value,
        value.inputs,
        changed_policy,
        value.target_scale,
        value.algorithm_version,
    )

    assert freshness.status == "stale"
    assert freshness.reasons == ("policy_changed",)


def test_changed_scale_reference_is_reported_independently() -> None:
    value = snapshot()
    changed_scale = replace(
        value.target_scale,
        scale_revision=2,
        scale_sha256="7" * 64,
    )

    freshness = assess_standard_proficiency_result_freshness(
        value,
        value.inputs,
        value.policy_reference,
        changed_scale,
        value.algorithm_version,
    )

    assert freshness.status == "stale"
    assert freshness.reasons == ("scale_changed",)


def test_changed_algorithm_version_is_reported_independently() -> None:
    value = snapshot()

    freshness = assess_standard_proficiency_result_freshness(
        value,
        value.inputs,
        value.policy_reference,
        value.target_scale,
        "2",
    )

    assert freshness.status == "stale"
    assert freshness.reasons == ("algorithm_changed",)


def test_multiple_changes_use_deterministic_reason_order() -> None:
    value = snapshot()
    changed_inputs = replace(
        value.inputs,
        grade_item=replace(
            value.inputs.grade_item,
            grade_item_revision=3,
            grade_item_revision_sha256="7" * 64,
        ),
    )
    changed_policy = replace(
        value.policy_reference,
        policy_revision=2,
        policy_sha256="7" * 64,
    )
    changed_scale = replace(
        value.target_scale,
        scale_revision=2,
        scale_sha256="7" * 64,
    )

    freshness = assess_standard_proficiency_result_freshness(
        value,
        changed_inputs,
        changed_policy,
        changed_scale,
        "2",
    )

    assert freshness.status == "stale"
    assert freshness.reasons == (
        "inputs_changed",
        "policy_changed",
        "scale_changed",
        "algorithm_changed",
    )


def test_cross_family_inputs_are_invalid_not_stale() -> None:
    value = snapshot()
    other_student_inputs = replace(
        value.inputs,
        student_id="student_2",
    )

    with pytest.raises(
        StandardProficiencyValidationError,
        match="logical identity",
    ):
        assess_standard_proficiency_result_freshness(
            value,
            other_student_inputs,
            value.policy_reference,
            value.target_scale,
            value.algorithm_version,
        )


def test_cross_class_policy_or_scale_reference_is_invalid() -> None:
    value = snapshot()
    other_policy = replace(
        value.policy_reference,
        class_id="other_class",
    )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="policy reference",
    ):
        assess_standard_proficiency_result_freshness(
            value,
            value.inputs,
            other_policy,
            value.target_scale,
            value.algorithm_version,
        )

    other_scale = replace(
        value.target_scale,
        class_id="other_class",
    )
    with pytest.raises(
        StandardProficiencyValidationError,
        match="scale reference",
    ):
        assess_standard_proficiency_result_freshness(
            value,
            value.inputs,
            value.policy_reference,
            other_scale,
            value.algorithm_version,
        )
