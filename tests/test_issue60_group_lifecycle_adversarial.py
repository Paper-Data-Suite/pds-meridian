from __future__ import annotations

from pathlib import Path

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.reassessment_storage as reassessment_storage
import meridian.standards_evidence_storage as standards_storage
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_ALGORITHM_VERSION,
    assess_standard_proficiency_result_freshness,
    calculate_standard_proficiency,
)
from meridian.standards_proficiency_storage import (
    load_current_standard_proficiency_result,
)
from tests.cross_producer_academic_period_support import (
    _grade_item_policy,
    prepare_period_scenario,
)
from tests.cross_producer_aggregation_support import prepare_aggregation_scenario
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import (
    supersede_scoreform,
    withdraw_quillan,
)


def _reference_ids(item: object, kind: str) -> tuple[str, ...]:
    return tuple(
        reference.identifier
        for reference in item.provenance.native.references
        if reference.kind == kind and reference.identifier is not None
    )


def test_concord_group_evidence_never_becomes_individual_student_evidence(
    tmp_path: Path,
) -> None:
    scenario = prepare_aggregation_scenario(tmp_path)
    root = scenario.workspace.mixed.root
    group = scenario.concord_group

    assert group.subject is None
    assert group.target.target_kind == "concord_group"
    assert SHARED_STUDENT_ID in _reference_ids(group, "score_link_subject_id")
    assert SHARED_STUDENT_ID in _reference_ids(group, "moderation_subject_id")

    student_inventory = scenario.workspace.projected["concord"].inventory.for_student(
        SHARED_STUDENT_ID
    )
    assert group not in student_inventory

    all_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )
    group_entry = next(
        entry
        for entry in all_inputs.entries
        if entry.source.item_id == group.item_id
    )
    assert group_entry.target_kind == "concord_group"
    assert group_entry.mapping_status == "mapped"
    assert group_entry.status == "excluded"
    assert group_entry.exclusion_reason == "nonstudent_target"
    assert group_entry.proficiency_level_id is None

    without_group_bindings = tuple(
        binding
        for binding in scenario.bindings
        if binding.source.item_id != group.item_id
    )
    without_group_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        without_group_bindings,
        standards_library=scenario.standard_library,
    )

    policy = _grade_item_policy(
        scenario,
        policy_id="issue60_group_nonstudent",
        native_state_handling="noncontributing",
    )
    with_group = calculate_standard_proficiency(
        all_inputs,
        policy,
        scenario.target_scale.scale,
    )
    without_group = calculate_standard_proficiency(
        without_group_inputs,
        policy,
        scenario.target_scale.scale,
    )

    assert with_group.status == without_group.status == "calculated"
    assert with_group.proficiency_level_id == without_group.proficiency_level_id
    assert (
        with_group.performance_observation_count
        == without_group.performance_observation_count
    )
    assert with_group.excluded_count == without_group.excluded_count + 1


def test_publication_withdrawal_changes_basis_without_authoring_new_result(
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

    old_quillan = next(
        entry
        for entry in original.snapshot.inputs.entries
        if entry.source.work.module_id == "quillan"
    )
    assert old_quillan.status == "performance"
    assert old_quillan.proficiency_level_id == "developing"

    withdraw_quillan(workspace.mixed)

    lifecycle = eligibility_storage.observe_evidence_source_state(
        root,
        old_quillan.source,
    )
    assert lifecycle.state == "withdrawn"
    assert lifecycle.successor_publication_id is None

    fresh_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        aggregation.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        aggregation.target_scale.reference,
        aggregation.bindings,
        standards_library=aggregation.standard_library,
    )
    fresh_quillan = next(
        entry
        for entry in fresh_inputs.entries
        if entry.source == old_quillan.source
    )
    assert fresh_quillan.status == "excluded"
    assert fresh_quillan.exclusion_reason == "eligibility_not_included"
    assert fresh_quillan.proficiency_level_id is None

    freshness = assess_standard_proficiency_result_freshness(
        original.snapshot,
        fresh_inputs,
        original.snapshot.policy_reference,
        original.snapshot.target_scale,
        STANDARD_PROFICIENCY_ALGORITHM_VERSION,
    )
    assert freshness.status == "stale"
    assert freshness.reasons == ("inputs_changed",)

    still_selected = load_current_standard_proficiency_result(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        original.snapshot.student_id,
        original.snapshot.standard_id,
    )
    assert still_selected is not None
    assert still_selected.reference == original.reference
    assert still_selected.result_sha256 == original.result_sha256
    assert still_selected.content == original_content
    assert still_selected.snapshot == original.snapshot


def test_publication_supersession_does_not_author_reassessment_or_select_new_result(
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
    assert old_publication_ids == {
        workspace.mixed.publications["scoreform"].publication_id
    }

    work = workspace.mixed.publications["scoreform"].work
    before_reassessment = reassessment_storage.resolve_current_reassessment(
        root,
        work.class_id,
        aggregation.grade_item.grade_item_id,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=workspace.authorized["scoreform"],
    )
    assert before_reassessment.status == "resolved"
    assert before_reassessment.selected is not None

    successor = supersede_scoreform(workspace.mixed)
    assert successor.publication_id not in old_publication_ids

    for entry in old_scoreform:
        lifecycle = eligibility_storage.observe_evidence_source_state(
            root,
            entry.source,
        )
        assert lifecycle.state == "superseded"
        assert lifecycle.head_publication_id == successor.publication_id
        assert lifecycle.successor_publication_id == successor.publication_id

    after_reassessment = reassessment_storage.resolve_current_reassessment(
        root,
        work.class_id,
        aggregation.grade_item.grade_item_id,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=workspace.authorized["scoreform"],
    )
    assert after_reassessment.status == "resolved"
    assert after_reassessment.selected is not None
    assert (
        after_reassessment.selected.decision.decision_revision
        == before_reassessment.selected.decision.decision_revision
        == 1
    )
    assert (
        after_reassessment.selected.decision_sha256
        == before_reassessment.selected.decision_sha256
    )
    assert (
        after_reassessment.selected.decision
        == before_reassessment.selected.decision
    )

    still_selected = load_current_standard_proficiency_result(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        original.snapshot.student_id,
        original.snapshot.standard_id,
    )
    assert still_selected is not None
    assert still_selected.reference == original.reference
    assert still_selected.result_sha256 == original.result_sha256
    assert still_selected.content == original_content
    assert still_selected.snapshot == original.snapshot
    assert still_selected.snapshot.result_revision == 1
