from __future__ import annotations

from pathlib import Path

import meridian.standards_evidence_storage as standards_storage
from meridian.evidence_eligibility import evidence_source_key
from meridian.standards_evidence import (
    StandardAggregationInputs,
    standard_aggregation_inputs_sha256,
    standard_aggregation_inputs_to_json_bytes,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    NativeStateHandling,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
)
from tests.cross_producer_aggregation_support import (
    Issue44AggregationScenario,
    prepare_aggregation_scenario,
)
from tests.cross_producer_proficiency_support import ACTOR_ID, NOW
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


def _resolved_inputs(
    tmp_path: Path,
) -> tuple[Issue44AggregationScenario, StandardAggregationInputs]:
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
    return scenario, inputs


def _policy(
    scenario: Issue44AggregationScenario,
    *,
    policy_id: str,
    native_state_handling: NativeStateHandling,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=scenario.grade_item.class_id,
        policy_id=policy_id,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 44 mixed producer policy",
        target_scale=scenario.target_scale.reference,
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(),
        native_state_handling=native_state_handling,
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #44 exact mixed-producer policy acceptance.",
        revised_at=NOW,
    )


def test_identical_mixed_basis_replays_canonically_and_deterministically(
    tmp_path: Path,
) -> None:
    scenario, first_inputs = _resolved_inputs(tmp_path)
    second_inputs = standards_storage.resolve_standard_aggregation_inputs(
        scenario.workspace.mixed.root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )

    assert first_inputs == second_inputs
    assert standard_aggregation_inputs_to_json_bytes(first_inputs) == (
        standard_aggregation_inputs_to_json_bytes(second_inputs)
    )
    assert standard_aggregation_inputs_sha256(first_inputs) == (
        standard_aggregation_inputs_sha256(second_inputs)
    )
    assert tuple(entry.source for entry in first_inputs.entries) == tuple(
        entry.source for entry in second_inputs.entries
    )

    policy = _policy(
        scenario,
        policy_id="issue44_replay_nonblocking",
        native_state_handling="noncontributing",
    )
    first_outcome = calculate_standard_proficiency(
        first_inputs,
        policy,
        scenario.target_scale.scale,
    )
    second_outcome = calculate_standard_proficiency(
        second_inputs,
        policy,
        scenario.target_scale.scale,
    )
    assert first_outcome == second_outcome
    assert first_outcome.calculation_fingerprint == (
        second_outcome.calculation_fingerprint
    )
    assert first_outcome.status == "calculated"
    assert first_outcome.proficiency_level_id == "proficient"


def test_native_state_blocking_makes_mixed_result_insufficient_not_low(
    tmp_path: Path,
) -> None:
    scenario, inputs = _resolved_inputs(tmp_path)
    policy = _policy(
        scenario,
        policy_id="issue44_block_native_state",
        native_state_handling="blocking",
    )
    outcome = calculate_standard_proficiency(
        inputs,
        policy,
        scenario.target_scale.scale,
    )

    assert outcome.status == "insufficient_evidence"
    assert outcome.proficiency_level_id is None
    assert outcome.performance_observation_count == 2
    assert outcome.native_state_count == 1
    assert outcome.excluded_count == 2
    assert tuple(reason.kind for reason in outcome.insufficiency_reasons) == (
        "blocking_native_state",
    )

    ambiguous_source = next(
        binding.source
        for binding in scenario.bindings
        if binding.source.item_id == scenario.scoreform_second_ambiguous.item_id
    )
    reason = outcome.insufficiency_reasons[0]
    assert reason.source_keys == (evidence_source_key(ambiguous_source),)

    explanations = {entry.source_key: entry for entry in outcome.explanation_entries}
    ambiguous_explanation = explanations[evidence_source_key(ambiguous_source)]
    assert ambiguous_explanation.status == "native_state"
    assert ambiguous_explanation.native_state_code == "ambiguous"
    assert ambiguous_explanation.proficiency_level_id is None
