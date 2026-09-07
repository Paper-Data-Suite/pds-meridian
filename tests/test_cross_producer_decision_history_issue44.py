from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import meridian.standards_evidence_storage as standards_storage
from meridian.grade_item_proficiency_explanation import (
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
)
from meridian.standards_proficiency import (
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    load_standard_proficiency_policy_revision,
    load_standard_proficiency_result_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_result_revision,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_decision_history_support import (
    revise_scoreform_teacher_choices,
)
from tests.cross_producer_proficiency_support import GRADE_ITEM_ID, NOW
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


def _trace_target(
    selection: str,
    result_revision: int | None = None,
) -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id="synthetic_class_2026",
        grade_item_id=GRADE_ITEM_ID,
        student_id=SHARED_STUDENT_ID,
        standard_id=SHARED_STANDARD_ID,
        selection=selection,
        result_revision=result_revision,
    )


def _scoreform_rows(value: object) -> tuple[object, ...]:
    return tuple(
        row
        for row in value.evidence
        if row.source.work.module_id == "scoreform"
    )


def _stage(row: object, name: str) -> object:
    return next(stage for stage in row.stages if stage.name == name)


def _detail(stage: object, key: str) -> object:
    return next(field.value for field in stage.details if field.key == key)


def test_teacher_attempt_reassessment_change_revises_basis_not_history(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path,
        native_state_handling="noncontributing",
    )
    aggregation = scenario.aggregation
    root = aggregation.workspace.mixed.root
    original = scenario.grade_item_result
    original_content = original.content

    original_scoreform = tuple(
        entry
        for entry in original.snapshot.inputs.entries
        if entry.source.work.module_id == "scoreform"
    )
    assert len(original_scoreform) == 2
    original_sources = {entry.source for entry in original_scoreform}
    original_by_kind = {
        entry.result_kind: entry for entry in original_scoreform
    }
    assert original_by_kind["question_correctness"].status == "excluded"
    assert (
        original_by_kind["question_correctness"].exclusion_reason
        == "reassessment_noncontributing"
    )
    assert original_by_kind["selected_response_state"].status == "native_state"

    reassessment = revise_scoreform_teacher_choices(scenario)
    assert reassessment.status == "resolved"
    assert reassessment.selected is not None
    assert reassessment.selected.decision.mode == "retain"
    assert reassessment.selected.decision.decision_revision == 2
    assert (
        reassessment.attempt_selection.selected is not None
        and reassessment.attempt_selection.selected.decision.decision_revision
        == 2
    )

    fresh_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        aggregation.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        aggregation.target_scale.reference,
        aggregation.bindings,
        standards_library=aggregation.standard_library,
    )
    fresh_scoreform = tuple(
        entry
        for entry in fresh_inputs.entries
        if entry.source.work.module_id == "scoreform"
    )
    assert {entry.source for entry in fresh_scoreform} == original_sources
    assert {
        entry.source.publication_id for entry in fresh_scoreform
    } == {
        entry.source.publication_id for entry in original_scoreform
    }
    assert {
        entry.attempt_selection_reference.revision
        for entry in fresh_scoreform
    } == {2}
    assert {
        entry.reassessment_reference.revision
        for entry in fresh_scoreform
    } == {2}

    fresh_by_kind = {entry.result_kind: entry for entry in fresh_scoreform}
    assert fresh_by_kind["question_correctness"].status == "performance"
    assert (
        fresh_by_kind["question_correctness"].proficiency_level_id
        == "proficient"
    )
    assert fresh_by_kind["question_correctness"].exclusion_reason is None
    assert fresh_by_kind["selected_response_state"].status == "native_state"
    assert fresh_by_kind["selected_response_state"].native_state is not None
    assert (
        fresh_by_kind["selected_response_state"].native_state.code
        == "ambiguous"
    )

    unchanged_old = tuple(
        entry
        for entry in original.snapshot.inputs.entries
        if entry.source.work.module_id != "scoreform"
    )
    unchanged_new = tuple(
        entry
        for entry in fresh_inputs.entries
        if entry.source.work.module_id != "scoreform"
    )
    assert unchanged_new == unchanged_old

    policy_ref = original.snapshot.policy_reference
    stored_policy = load_standard_proficiency_policy_revision(
        root,
        policy_ref.class_id,
        policy_ref.policy_id,
        policy_ref.policy_revision,
    )
    fresh_outcome = calculate_standard_proficiency(
        fresh_inputs,
        stored_policy.policy,
        aggregation.target_scale.scale,
    )
    assert fresh_outcome.status == "calculated"
    assert fresh_outcome.proficiency_level_id == "proficient"
    assert fresh_outcome.performance_observation_count == 3
    assert fresh_outcome.native_state_count == 1
    assert fresh_outcome.excluded_count == 1
    assert fresh_inputs.sha256 != original.snapshot.inputs_sha256
    assert fresh_outcome.calculation_fingerprint != (
        original.snapshot.calculation_fingerprint
    )

    revision_two = create_standard_proficiency_result_snapshot(
        fresh_inputs,
        fresh_outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=4),
    )
    written = write_standard_proficiency_result_revision(
        root,
        revision_two,
    ).stored
    select_standard_proficiency_result_revision(
        root,
        revision_two.class_id,
        revision_two.grade_item_id,
        revision_two.student_id,
        revision_two.standard_id,
        revision_two.result_revision,
        expected_current_result_revision=1,
    )

    historical = load_standard_proficiency_result_revision(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        original.snapshot.student_id,
        original.snapshot.standard_id,
        1,
    )
    assert historical.result_sha256 == original.result_sha256
    assert historical.content == original_content
    assert historical.snapshot == original.snapshot
    assert written.snapshot.result_revision == 2

    historical_trace = explain_grade_item_proficiency(
        root,
        _trace_target("revision", 1),
    )
    current_trace = explain_grade_item_proficiency(
        root,
        _trace_target("current"),
    )
    assert historical_trace.selection_state == "historical"
    assert historical_trace.current_result_revision == 2
    assert current_trace.selection_state == "selected_current"
    assert current_trace.result_revision == 2

    historical_rows = _scoreform_rows(historical_trace)
    current_rows = _scoreform_rows(current_trace)
    assert {row.source for row in historical_rows} == original_sources
    assert {row.source for row in current_rows} == original_sources

    assert {
        _stage(row, "attempt_selection").revision for row in historical_rows
    } == {1}
    assert {
        _stage(row, "reassessment").revision for row in historical_rows
    } == {1}
    assert {
        _stage(row, "attempt_selection").revision for row in current_rows
    } == {2}
    assert {
        _stage(row, "reassessment").revision for row in current_rows
    } == {2}
    assert {
        _detail(_stage(row, "reassessment"), "mode")
        for row in historical_rows
    } == {"replace"}
    assert {
        _detail(_stage(row, "reassessment"), "mode")
        for row in current_rows
    } == {"retain"}

    historical_correctness = next(
        row
        for row in historical_rows
        if row.result_kind == "question_correctness"
    )
    current_correctness = next(
        row
        for row in current_rows
        if row.result_kind == "question_correctness"
    )
    assert historical_correctness.aggregation_status == "excluded"
    assert (
        historical_correctness.exclusion_reason
        == "reassessment_noncontributing"
    )
    assert current_correctness.aggregation_status == "performance"
    assert current_correctness.proficiency_level_id == "proficient"
