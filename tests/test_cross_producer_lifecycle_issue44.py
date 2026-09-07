from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.ingestion as ingestion
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
    load_current_standard_proficiency_result,
    load_standard_proficiency_policy_revision,
    load_standard_proficiency_result_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_result_revision,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_proficiency_support import GRADE_ITEM_ID, NOW
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import (
    supersede_scoreform,
    withdraw_quillan,
)


def _input_entries_for_module(snapshot: object, module_id: str) -> tuple[object, ...]:
    return tuple(
        entry
        for entry in snapshot.inputs.entries
        if entry.source.work.module_id == module_id
    )


def _trace_rows_for_module(explanation: object, module_id: str) -> tuple[object, ...]:
    return tuple(
        row
        for row in explanation.evidence
        if row.source.work.module_id == module_id
    )


def _historical_target() -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id="synthetic_class_2026",
        grade_item_id=GRADE_ITEM_ID,
        student_id=SHARED_STUDENT_ID,
        standard_id=SHARED_STANDARD_ID,
        selection="revision",
        result_revision=1,
    )


def _current_target() -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id="synthetic_class_2026",
        grade_item_id=GRADE_ITEM_ID,
        student_id=SHARED_STUDENT_ID,
        standard_id=SHARED_STANDARD_ID,
        selection="current",
    )


def test_quillan_withdrawal_is_exclusion_not_low_and_preserves_history(
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

    old_quillan = _input_entries_for_module(original.snapshot, "quillan")
    assert len(old_quillan) == 1
    old_entry = old_quillan[0]
    assert old_entry.status == "performance"
    assert old_entry.proficiency_level_id == "developing"

    withdraw_quillan(workspace.mixed)

    lifecycle = eligibility_storage.observe_evidence_source_state(
        root,
        old_entry.source,
    )
    assert lifecycle.state == "withdrawn"
    assert lifecycle.head_publication_id == old_entry.source.publication_id
    assert lifecycle.successor_publication_id is None
    assert lifecycle.withdrawn_at is not None

    eligibility = eligibility_storage.resolve_current_evidence_eligibility(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        old_entry.source,
        authorized_snapshot=workspace.authorized["quillan"],
    )
    assert eligibility.status == "included_source_withdrawn"
    assert eligibility.operative_included is False
    assert eligibility.current_source_state == lifecycle
    assert eligibility.selected is not None
    assert eligibility.selected.decision.disposition == "included"

    fresh_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        aggregation.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        aggregation.target_scale.reference,
        aggregation.bindings,
        standards_library=aggregation.standard_library,
    )
    fresh_quillan = tuple(
        entry
        for entry in fresh_inputs.entries
        if entry.source == old_entry.source
    )
    assert len(fresh_quillan) == 1
    fresh_entry = fresh_quillan[0]
    assert fresh_entry.status == "excluded"
    assert fresh_entry.exclusion_reason == "eligibility_not_included"
    assert fresh_entry.proficiency_level_id is None
    assert fresh_entry.native_state is None
    assert fresh_entry.eligibility_reference == old_entry.eligibility_reference
    assert fresh_entry.mapping_profile_reference == (
        old_entry.mapping_profile_reference
    )

    policy_ref = original.snapshot.policy_reference
    stored_policy = load_standard_proficiency_policy_revision(
        root,
        policy_ref.class_id,
        policy_ref.policy_id,
        policy_ref.policy_revision,
    )
    assert stored_policy.policy_sha256 == policy_ref.policy_sha256
    fresh_outcome = calculate_standard_proficiency(
        fresh_inputs,
        stored_policy.policy,
        aggregation.target_scale.scale,
    )
    assert fresh_outcome.status == "calculated"
    assert fresh_outcome.proficiency_level_id == "proficient"
    assert fresh_outcome.performance_observation_count == 1
    assert fresh_outcome.native_state_count == 1
    assert fresh_outcome.excluded_count == 3
    assert fresh_inputs.sha256 != original.snapshot.inputs_sha256
    assert fresh_outcome.calculation_fingerprint != (
        original.snapshot.calculation_fingerprint
    )

    revision_two = create_standard_proficiency_result_snapshot(
        fresh_inputs,
        fresh_outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=1),
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

    current = load_current_standard_proficiency_result(
        root,
        revision_two.class_id,
        revision_two.grade_item_id,
        revision_two.student_id,
        revision_two.standard_id,
    )
    assert current is not None
    assert current.reference == written.reference

    reloaded_original = load_standard_proficiency_result_revision(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        original.snapshot.student_id,
        original.snapshot.standard_id,
        1,
    )
    assert reloaded_original.result_sha256 == original.result_sha256
    assert reloaded_original.content == original_content
    assert reloaded_original.snapshot == original.snapshot

    historical_trace = explain_grade_item_proficiency(
        root,
        _historical_target(),
    )
    current_trace = explain_grade_item_proficiency(
        root,
        _current_target(),
    )
    assert historical_trace.result_revision == 1
    assert historical_trace.selection_state == "historical"
    assert historical_trace.current_result_revision == 2
    assert current_trace.result_revision == 2
    assert current_trace.selection_state == "selected_current"
    assert current_trace.current_result_revision == 2

    historical_quillan = _trace_rows_for_module(
        historical_trace,
        "quillan",
    )
    current_quillan = _trace_rows_for_module(current_trace, "quillan")
    assert len(historical_quillan) == len(current_quillan) == 1
    assert historical_quillan[0].source == old_entry.source
    assert historical_quillan[0].aggregation_status == "performance"
    assert historical_quillan[0].proficiency_level_id == "developing"
    assert current_quillan[0].source == old_entry.source
    assert current_quillan[0].aggregation_status == "excluded"
    assert current_quillan[0].exclusion_reason == "eligibility_not_included"
    assert current_quillan[0].proficiency_level_id is None


def test_scoreform_supersession_is_exact_and_does_not_rewrite_old_sources(
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

    old_scoreform = _input_entries_for_module(original.snapshot, "scoreform")
    assert len(old_scoreform) == 2
    old_publication_ids = {
        entry.source.publication_id for entry in old_scoreform
    }
    assert old_publication_ids == {
        workspace.mixed.publications["scoreform"].publication_id
    }

    successor = supersede_scoreform(workspace.mixed)
    rebuild_academic_catalog(root)

    current_candidates = ingestion.discover_publication_candidates(
        root,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="scoreform",
                state="current",
                limit=10,
            )
        ),
    )
    assert tuple(
        candidate.publication_id for candidate in current_candidates.candidates
    ) == (successor.publication_id,)
    assert successor.publication_id not in old_publication_ids

    for entry in old_scoreform:
        lifecycle = eligibility_storage.observe_evidence_source_state(
            root,
            entry.source,
        )
        assert lifecycle.state == "superseded"
        assert lifecycle.head_publication_id == successor.publication_id
        assert lifecycle.successor_publication_id == successor.publication_id
        assert lifecycle.withdrawn_at is None

        eligibility = eligibility_storage.resolve_current_evidence_eligibility(
            root,
            original.snapshot.class_id,
            original.snapshot.grade_item_id,
            entry.source,
            authorized_snapshot=workspace.authorized["scoreform"],
        )
        assert eligibility.status == "included_source_superseded"
        assert eligibility.operative_included is True
        assert eligibility.current_source_state == lifecycle

    reloaded = load_standard_proficiency_result_revision(
        root,
        original.snapshot.class_id,
        original.snapshot.grade_item_id,
        original.snapshot.student_id,
        original.snapshot.standard_id,
        original.snapshot.result_revision,
    )
    assert reloaded.result_sha256 == original.result_sha256
    assert reloaded.content == original_content
    assert reloaded.snapshot == original.snapshot

    trace = explain_grade_item_proficiency(root, _historical_target())
    assert trace.result_revision == 1
    assert trace.selection_state == "selected_current"
    traced_scoreform = _trace_rows_for_module(trace, "scoreform")
    assert len(traced_scoreform) == 2
    assert {
        row.source.publication_id for row in traced_scoreform
    } == old_publication_ids
    assert successor.publication_id not in {
        row.source.publication_id for row in traced_scoreform
    }
