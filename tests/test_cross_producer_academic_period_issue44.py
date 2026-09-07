from __future__ import annotations

from pathlib import Path

from tests.cross_producer_academic_period_support import (
    prepare_period_scenario,
    rebuild_period_preview,
)
from tests.cross_producer_proficiency_support import PERIOD_ID, SCHOOL_YEAR


def test_selected_mixed_grade_item_result_flows_through_exact_period_basis(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path,
        native_state_handling="noncontributing",
    )
    preview = scenario.preview
    inputs = preview.inputs
    outcome = preview.calculation.outcome

    assert scenario.grade_item_result.snapshot.outcome.status == "calculated"
    assert scenario.grade_item_result.snapshot.outcome.proficiency_level_id == (
        "proficient"
    )
    assert preview.calculation.school_year == SCHOOL_YEAR
    assert preview.calculation.period_id == PERIOD_ID
    assert preview.calculation.calendar_revision == 1
    assert preview.calculation.period_membership_scope == "direct"

    assert len(inputs.entries) == 1
    entry = inputs.entries[0]
    assert entry.status == "calculated"
    assert entry.proficiency_level_id == "proficient"
    assert entry.result_reference == scenario.grade_item_result.reference
    assert tuple(
        membership.work_reference.work.module_id
        for membership in entry.memberships
    ) == ("concord", "quillan", "scoreform")

    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.candidate_count == 1
    assert outcome.calculated_result_count == 1
    assert outcome.insufficient_result_count == 0
    assert outcome.missing_result_count == 0
    assert outcome.period_scope_mismatch_count == 0
    assert outcome.explanation_entries[0].contributed is True
    assert outcome.explanation_entries[0].result_reference == (
        scenario.grade_item_result.reference
    )


def test_period_calculation_is_deterministic_across_membership_input_order(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path,
        native_state_handling="noncontributing",
    )
    reordered = rebuild_period_preview(
        scenario,
        reverse_memberships=True,
    )

    assert scenario.preview.inputs == reordered.inputs
    assert scenario.preview.calculation.inputs_sha256 == (
        reordered.calculation.inputs_sha256
    )
    assert scenario.preview.calculation.calculation_fingerprint == (
        reordered.calculation.calculation_fingerprint
    )
    assert scenario.preview.calculation.outcome == reordered.calculation.outcome


def test_insufficient_mixed_grade_item_result_never_becomes_low_period_level(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path,
        native_state_handling="blocking",
    )
    grade_item_outcome = scenario.grade_item_result.snapshot.outcome
    period_outcome = scenario.preview.calculation.outcome
    entry = scenario.preview.inputs.entries[0]

    assert grade_item_outcome.status == "insufficient_evidence"
    assert grade_item_outcome.proficiency_level_id is None
    assert tuple(
        reason.kind for reason in grade_item_outcome.insufficiency_reasons
    ) == ("blocking_native_state",)

    assert entry.status == "insufficient_evidence"
    assert entry.proficiency_level_id is None
    assert entry.result_reference == scenario.grade_item_result.reference

    assert period_outcome.status == "insufficient_evidence"
    assert period_outcome.proficiency_level_id is None
    assert period_outcome.calculated_result_count == 0
    assert period_outcome.insufficient_result_count == 1
    assert tuple(
        reason.kind for reason in period_outcome.insufficiency_reasons
    ) == ("no_calculated_results",)
    explanation = period_outcome.explanation_entries[0]
    assert explanation.status == "insufficient_evidence"
    assert explanation.contributed is False
    assert explanation.proficiency_level_id is None
