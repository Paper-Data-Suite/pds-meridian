from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

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
    standard_aggregation_inputs_sha256,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
    STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    StandardProficiencyResultSnapshot,
    StandardProficiencySerializationError,
    StandardProficiencyValidationError,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
    standard_proficiency_result_reference,
    standard_proficiency_result_snapshot_from_json_bytes,
    standard_proficiency_result_snapshot_to_json_bytes,
    validate_standard_proficiency_result_transition,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "grade_item_1"
STUDENT_ID = "student_1"
STANDARD_ID = "https://standards.example/RL:9-10.1?edition=2026"
NOW = datetime(2026, 8, 28, 0, 30, tzinfo=UTC)


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
            ProficiencyLevel("extended", 3, "Extended", "Extends criterion."),
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


def inputs(
    target: ProficiencyScale,
    *,
    student_id: str = STUDENT_ID,
) -> StandardAggregationInputs:
    target_ref = proficiency_scale_reference(target)
    return StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            2,
            "6" * 64,
        ),
        student_id=student_id,
        standard_id=STANDARD_ID,
        target_scale=target_ref,
        entries=(),
    )


def snapshot(
    *,
    revision: int = 1,
    calculated_at: datetime = NOW,
    student_id: str = STUDENT_ID,
) -> StandardProficiencyResultSnapshot:
    target = scale()
    exact_inputs = inputs(target, student_id=student_id)
    outcome = calculate_standard_proficiency(
        exact_inputs,
        policy(target),
        target,
    )
    return create_standard_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=revision,
        calculated_at=calculated_at,
    )


def test_result_snapshot_is_frozen_slotted_and_preserves_exact_inputs() -> None:
    value = snapshot()
    assert value.schema_version == STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION
    assert value.record_type == STANDARD_PROFICIENCY_RESULT_RECORD_TYPE
    assert value.inputs_sha256 == standard_aggregation_inputs_sha256(value.inputs)
    assert value.inputs.standard_id == STANDARD_ID
    assert value.outcome.status == "insufficient_evidence"
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.student_id = "changed"  # type: ignore[misc]


def test_result_scope_must_match_embedded_inputs() -> None:
    value = snapshot()
    with pytest.raises(StandardProficiencyValidationError, match="scope"):
        replace(value, class_id="other_class")
    with pytest.raises(StandardProficiencyValidationError, match="scope"):
        replace(value, grade_item_id="other_item")
    with pytest.raises(StandardProficiencyValidationError, match="scope"):
        replace(value, student_id="student_2")
    with pytest.raises(StandardProficiencyValidationError, match="scope"):
        replace(value, standard_id="urn:standard:other")


def test_result_metadata_must_match_embedded_inputs_and_pure_outcome() -> None:
    value = snapshot()
    with pytest.raises(StandardProficiencyValidationError, match="inputs_sha256"):
        replace(value, inputs_sha256="0" * 64)
    with pytest.raises(StandardProficiencyValidationError, match="metadata"):
        replace(value, calculation_fingerprint="0" * 64)
    with pytest.raises(StandardProficiencyValidationError, match="target_scale"):
        replace(
            value,
            target_scale=replace(value.target_scale, scale_sha256="0" * 64),
        )


def test_result_revision_pair_and_transition_are_explicit() -> None:
    first = snapshot()
    second = snapshot(revision=2, calculated_at=NOW + timedelta(minutes=1))
    assert second.supersedes_revision == 1
    assert validate_standard_proficiency_result_transition(first, second) == second

    other_student = snapshot(
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
        student_id="student_2",
    )
    with pytest.raises(StandardProficiencyValidationError, match="logical identity"):
        validate_standard_proficiency_result_transition(
            first,
            other_student,
        )
    with pytest.raises(StandardProficiencyValidationError, match="contiguous"):
        validate_standard_proficiency_result_transition(
            first,
            replace(second, result_revision=3, supersedes_revision=2),
        )


def test_result_json_round_trip_is_canonical_and_preserves_full_input_body() -> None:
    value = snapshot()
    encoded = standard_proficiency_result_snapshot_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert b"\r" not in encoded
    assert b'"entries": []' in encoded
    assert STANDARD_ID.encode("utf-8") in encoded
    assert standard_proficiency_result_snapshot_from_json_bytes(encoded) == value


def test_result_json_rejects_duplicate_unknown_missing_and_noncanonical() -> None:
    encoded = standard_proficiency_result_snapshot_to_json_bytes(snapshot())

    duplicate = encoded.replace(
        b'{\n  "algorithm_version":',
        b'{\n  "class_id": "duplicate",\n  "algorithm_version":',
        1,
    )
    with pytest.raises(StandardProficiencySerializationError, match="duplicate"):
        standard_proficiency_result_snapshot_from_json_bytes(duplicate)

    unknown = encoded.replace(
        b"{\n",
        b'{\n  "unexpected": true,\n',
        1,
    )
    with pytest.raises(StandardProficiencySerializationError, match="unknown"):
        standard_proficiency_result_snapshot_from_json_bytes(unknown)

    missing = encoded.replace(
        b'  "algorithm_version": "1",\n',
        b"",
        1,
    )
    with pytest.raises(StandardProficiencySerializationError, match="missing"):
        standard_proficiency_result_snapshot_from_json_bytes(missing)

    with pytest.raises(StandardProficiencySerializationError, match="canonical"):
        standard_proficiency_result_snapshot_from_json_bytes(
            encoded.replace(b"\n", b"\r\n")
        )


def test_result_reference_binds_scope_revision_and_exact_snapshot_bytes() -> None:
    value = snapshot()
    reference = standard_proficiency_result_reference(value)
    assert reference.class_id == CLASS_ID
    assert reference.grade_item_id == GRADE_ITEM_ID
    assert reference.student_id == STUDENT_ID
    assert reference.standard_id == STANDARD_ID
    assert reference.result_revision == 1
    assert len(reference.result_sha256) == 64


def test_calculated_at_is_audit_metadata_not_pure_academic_input() -> None:
    first = snapshot(calculated_at=NOW)
    second = snapshot(calculated_at=NOW + timedelta(hours=1))
    assert first.outcome == second.outcome
    assert first.calculation_fingerprint == second.calculation_fingerprint
    assert first.inputs_sha256 == second.inputs_sha256
    assert standard_proficiency_result_reference(first) != (
        standard_proficiency_result_reference(second)
    )


def test_calculated_at_requires_timezone_and_canonicalizes_to_utc() -> None:
    value = snapshot()
    with pytest.raises(StandardProficiencyValidationError, match="timezone-aware"):
        replace(value, calculated_at=datetime(2026, 8, 28, 0, 30))

    offset = NOW.astimezone(timezone(timedelta(hours=-4)))
    assert replace(value, calculated_at=offset).calculated_at == NOW
