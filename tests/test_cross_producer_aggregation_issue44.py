from __future__ import annotations

from pathlib import Path

import meridian.standards_evidence_storage as standards_storage
from meridian.evidence_eligibility import evidence_source_key
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
)
from tests.cross_producer_aggregation_support import prepare_aggregation_scenario
from tests.cross_producer_proficiency_support import ACTOR_ID, GRADE_ITEM_ID, NOW
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


def _inputs_by_item_id(inputs: object) -> dict[str, object]:
    entries = getattr(inputs, "entries")
    return {entry.source.item_id: entry for entry in entries}


def test_real_cross_producer_resolution_preserves_closed_semantics(
    tmp_path: Path,
) -> None:
    scenario = prepare_aggregation_scenario(tmp_path)
    inputs = standards_storage.resolve_standard_aggregation_inputs(
        scenario.workspace.mixed.root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )
    by_item = _inputs_by_item_id(inputs)

    first = by_item[scenario.scoreform_first_correctness.item_id]
    assert first.status == "excluded"
    assert first.exclusion_reason == "reassessment_noncontributing"
    assert first.mapping_status == "mapped"
    assert first.proficiency_level_id is None
    assert first.reassessment_reference is not None

    ambiguous = by_item[scenario.scoreform_second_ambiguous.item_id]
    assert ambiguous.status == "native_state"
    assert ambiguous.native_state is not None
    assert ambiguous.native_state.code == "ambiguous"
    assert ambiguous.mapping_status == "native_state"
    assert ambiguous.reassessment_reference is not None

    quillan = by_item[scenario.quillan_overall.item_id]
    assert quillan.status == "performance"
    assert quillan.proficiency_level_id == "developing"
    assert quillan.attempt_selection_reference is None
    assert quillan.reassessment_reference is None

    concord = by_item[scenario.concord_student.item_id]
    assert concord.status == "performance"
    assert concord.proficiency_level_id == "proficient"

    group = by_item[scenario.concord_group.item_id]
    assert group.status == "excluded"
    assert group.exclusion_reason == "nonstudent_target"
    assert group.mapping_status == "mapped"
    assert group.proficiency_level_id is None

    assert sorted(entry.status for entry in inputs.entries) == [
        "excluded",
        "excluded",
        "native_state",
        "performance",
        "performance",
    ]


def test_bounded_proficiency_uses_only_contributing_student_performance(
    tmp_path: Path,
) -> None:
    scenario = prepare_aggregation_scenario(tmp_path)
    inputs = standards_storage.resolve_standard_aggregation_inputs(
        scenario.workspace.mixed.root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )
    policy = StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=scenario.grade_item.class_id,
        policy_id="issue44_cross_producer_highest",
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 44 cross-producer proficiency",
        target_scale=scenario.target_scale.reference,
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(
            "association_unresolved",
            "eligibility_unresolved",
            "attempt_selection_unresolved",
            "reassessment_unresolved",
            "mapping_not_supplied",
            "mapping_unmapped",
            "mapping_unsupported",
            "scale_mismatch",
            "source_unverifiable",
            "standard_unresolved",
        ),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #44 accepts only resolved contributing performance.",
        revised_at=NOW,
    )
    outcome = calculate_standard_proficiency(
        inputs,
        policy,
        scenario.target_scale.scale,
    )

    assert inputs.grade_item.grade_item_id == GRADE_ITEM_ID
    assert inputs.student_id == SHARED_STUDENT_ID
    assert inputs.standard_id == SHARED_STANDARD_ID
    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.performance_observation_count == 2
    assert outcome.native_state_count == 1
    assert outcome.excluded_count == 2

    explanations = {entry.source_key: entry for entry in outcome.explanation_entries}
    ambiguous_source = next(
        binding.source
        for binding in scenario.bindings
        if binding.source.item_id == scenario.scoreform_second_ambiguous.item_id
    )
    first_source = next(
        binding.source
        for binding in scenario.bindings
        if binding.source.item_id == scenario.scoreform_first_correctness.item_id
    )
    group_source = next(
        binding.source
        for binding in scenario.bindings
        if binding.source.item_id == scenario.concord_group.item_id
    )
    assert explanations[evidence_source_key(ambiguous_source)].status == "native_state"
    assert (
        explanations[evidence_source_key(ambiguous_source)].native_state_code
        == "ambiguous"
    )
    assert (
        explanations[evidence_source_key(first_source)].exclusion_reason
        == "reassessment_noncontributing"
    )
    assert (
        explanations[evidence_source_key(group_source)].exclusion_reason
        == "nonstudent_target"
    )
