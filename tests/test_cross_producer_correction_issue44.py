from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import meridian.evidence_eligibility_storage as eligibility_storage
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
from tests.cross_producer_correction_support import prepare_corrected_scoreform
from tests.cross_producer_proficiency_support import GRADE_ITEM_ID, NOW
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


def _target(selection: str, revision: int | None = None) -> object:
    return GradeItemProficiencyTraceTarget(
        class_id="synthetic_class_2026",
        grade_item_id=GRADE_ITEM_ID,
        student_id=SHARED_STUDENT_ID,
        standard_id=SHARED_STANDARD_ID,
        selection=selection,
        result_revision=revision,
    )


def _module_rows(value: object, module_id: str) -> tuple[object, ...]:
    return tuple(
        row
        for row in value.evidence
        if row.source.work.module_id == module_id
    )


def test_fresh_scoreform_interpretation_binds_exact_core_correction(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path,
        native_state_handling="noncontributing",
    )
    aggregation = scenario.aggregation
    workspace = aggregation.workspace
    root = workspace.mixed.root
    original = scenario.grade_item_result
    original_content = original.content

    old_scoreform = tuple(
        entry
        for entry in original.snapshot.inputs.entries
        if entry.source.work.module_id == "scoreform"
    )
    assert len(old_scoreform) == 2
    old_publication_ids = {
        entry.source.publication_id for entry in old_scoreform
    }
    assert len(old_publication_ids) == 1

    corrected = prepare_corrected_scoreform(scenario)
    successor_id = corrected.successor.publication_id
    assert corrected.successor.record_set_revision == 2
    assert successor_id not in old_publication_ids

    new_sources = {
        binding.source
        for binding in corrected.bindings
        if binding.source.work.module_id == "scoreform"
    }
    assert len(new_sources) == 2
    assert {source.publication_id for source in new_sources} == {successor_id}

    for source in new_sources:
        lifecycle = eligibility_storage.observe_evidence_source_state(
            root,
            source,
        )
        assert lifecycle.state == "current"
        assert lifecycle.head_publication_id == successor_id
        assert lifecycle.successor_publication_id is None
        assert lifecycle.withdrawn_at is None

        eligibility = eligibility_storage.resolve_current_evidence_eligibility(
            root,
            original.snapshot.class_id,
            original.snapshot.grade_item_id,
            source,
            authorized_snapshot=corrected.authorized,
        )
        assert eligibility.status == "included"
        assert eligibility.operative_included is True

    fresh_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        aggregation.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        aggregation.target_scale.reference,
        corrected.bindings,
        standards_library=aggregation.standard_library,
    )
    fresh_scoreform = tuple(
        entry
        for entry in fresh_inputs.entries
        if entry.source.work.module_id == "scoreform"
    )
    assert len(fresh_scoreform) == 2
    assert {entry.source.publication_id for entry in fresh_scoreform} == {
        successor_id
    }
    attempt_revisions = {
        entry.attempt_selection_reference.revision
        for entry in fresh_scoreform
    }
    assert attempt_revisions == {2}
    assert {entry.reassessment_reference.revision for entry in fresh_scoreform} == {
        2
    }
    by_kind = {entry.result_kind: entry for entry in fresh_scoreform}
    assert by_kind["question_correctness"].status == "excluded"
    assert (
        by_kind["question_correctness"].exclusion_reason
        == "reassessment_noncontributing"
    )
    assert by_kind["selected_response_state"].status == "native_state"
    assert by_kind["selected_response_state"].native_state is not None
    assert by_kind["selected_response_state"].native_state.code == "ambiguous"

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
    assert fresh_outcome.status == original.snapshot.outcome.status
    assert (
        fresh_outcome.proficiency_level_id
        == original.snapshot.outcome.proficiency_level_id
    )
    assert fresh_inputs.sha256 != original.snapshot.inputs_sha256
    assert fresh_outcome.calculation_fingerprint != (
        original.snapshot.calculation_fingerprint
    )

    revision_two = create_standard_proficiency_result_snapshot(
        fresh_inputs,
        fresh_outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=3),
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
        _target("revision", 1),
    )
    current_trace = explain_grade_item_proficiency(
        root,
        _target("current"),
    )
    assert historical_trace.selection_state == "historical"
    assert historical_trace.current_result_revision == 2
    assert current_trace.selection_state == "selected_current"
    assert current_trace.result_revision == 2

    historical_scoreform = _module_rows(historical_trace, "scoreform")
    current_scoreform = _module_rows(current_trace, "scoreform")
    assert {row.source.publication_id for row in historical_scoreform} == (
        old_publication_ids
    )
    assert {row.source.publication_id for row in current_scoreform} == {
        successor_id
    }
    assert successor_id not in {
        row.source.publication_id for row in historical_scoreform
    }
    assert not old_publication_ids.intersection(
        {row.source.publication_id for row in current_scoreform}
    )

    current_attempt_revisions = {
        stage.revision
        for row in current_scoreform
        for stage in row.stages
        if stage.name == "attempt_selection"
    }
    current_reassessment_revisions = {
        stage.revision
        for row in current_scoreform
        for stage in row.stages
        if stage.name == "reassessment"
    }
    assert current_attempt_revisions == {2}
    assert current_reassessment_revisions == {2}
