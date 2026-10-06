from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.class_metadata import (
    create_class_metadata,
    write_class_metadata_for_class,
)
from pds_core.classes import write_class_roster
from pds_core.module_operations import (
    ModuleOperationsRequest,
    invoke_module_attention,
    invoke_module_readiness,
)
from pds_core.rosters import create_roster
from pds_core.workspace import ensure_workspace_root

import meridian.grade_report_attention as grade_report_attention
import meridian.standards_evidence_storage as standards_storage
import meridian.standards_grade_storage as grade_storage
from meridian.pds_operations import get_module_operations_profile
from meridian.standards_grade_result import (
    assess_standards_grade_result_freshness,
    create_standards_grade_result_snapshot,
)
from meridian.standards_grade_storage import (
    load_current_standards_grade_result,
    select_standards_grade_result_revision,
    write_standards_grade_result_revision,
)
from meridian.standards_proficiency import calculate_standard_proficiency
from meridian.standards_proficiency_storage import (
    load_standard_proficiency_policy_revision,
)
from tests import test_standards_grade as standards
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import (
    supersede_scoreform,
    withdraw_quillan,
)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _make_ready_grade_class(root: Path) -> None:
    ensure_workspace_root(root)
    write_class_metadata_for_class(
        root,
        create_class_metadata(
            standards.CLASS_ID,
            standards.PERIOD.school_year,
            created_at=standards.NOW,
        ),
    )
    write_class_roster(
        root,
        create_roster(
            standards.CLASS_ID,
            (
                {
                    "student_id": standards.STUDENT_ID,
                    "last_name": "Synthetic",
                    "first_name": "Student",
                    "period": "1",
                },
            ),
        ),
    )


def _persist_selected_standards_grade(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str,
):
    if status == "blocked":
        configuration = standards.configuration(
            ("std.issue60.a", "0.5"),
            ("std.issue60.b", "0.5"),
            minimum=1,
        )
        value = standards.policy(configuration)
        inputs = standards.calculation_input(
            value,
            standards.calculated(configuration.standards[0], "advanced"),
            standards.state_input(configuration.standards[1], "missing"),
        )
    elif status == "insufficient":
        configuration = standards.configuration(
            ("std.issue60.only", "1"),
            minimum=1,
        )
        value = standards.policy(configuration)
        inputs = standards.calculation_input(
            value,
            standards.state_input(configuration.standards[0], "excused"),
        )
    elif status == "calculated":
        configuration = standards.configuration(
            ("std.issue60.only", "1"),
            minimum=1,
        )
        value = standards.policy(configuration)
        inputs = standards.calculation_input(
            value,
            standards.calculated(configuration.standards[0], "advanced"),
        )
    else:
        raise AssertionError(status)

    outcome = standards.calculate_standards_grade(inputs)
    assert outcome.status == status

    snapshot = create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=standards.NOW,
    )

    # This Slice 7 fixture is about downstream result/readiness semantics,
    # not requalifying standards Grade assembly. Mirror the established
    # storage-test seam: present the exact already-constructed snapshot
    # basis as current and keep historical dependency validation out of
    # this fixture-only setup.
    monkeypatch.setattr(
        grade_storage,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=snapshot.inputs,
            outcome=snapshot.outcome,
        ),
    )
    monkeypatch.setattr(
        grade_storage,
        "_validate_historical_dependencies",
        lambda *args: None,
    )

    written = write_standards_grade_result_revision(root, snapshot).stored
    selected = select_standards_grade_result_revision(
        root,
        standards.CLASS_ID,
        standards.STUDENT_ID,
        standards.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    assert selected.stored.reference == written.reference

    current = load_current_standards_grade_result(
        root,
        standards.CLASS_ID,
        standards.STUDENT_ID,
        standards.PERIOD,
        1,
    )
    assert current is not None
    assert current.reference == written.reference
    assert current.snapshot.outcome.status == status
    return current


def test_simultaneous_source_adversities_preserve_distinct_authorities(
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

    old_scoreform_publication = workspace.mixed.publications[
        "scoreform"
    ].publication_id
    successor = supersede_scoreform(workspace.mixed)
    withdraw_quillan(workspace.mixed)

    fresh_inputs = standards_storage.resolve_standard_aggregation_inputs(
        root,
        aggregation.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        aggregation.target_scale.reference,
        aggregation.bindings,
        standards_library=aggregation.standard_library,
    )
    by_item = {entry.source.item_id: entry for entry in fresh_inputs.entries}

    first = by_item[aggregation.scoreform_first_correctness.item_id]
    second = by_item[aggregation.scoreform_second_ambiguous.item_id]
    quillan = by_item[aggregation.quillan_overall.item_id]
    concord_student = by_item[aggregation.concord_student.item_id]
    concord_group = by_item[aggregation.concord_group.item_id]

    # Supersession remains Core publication lifecycle authority. It neither
    # invents a new reassessment decision nor auto-substitutes the successor
    # publication into this explicit historical aggregation basis.
    assert successor.publication_id != old_scoreform_publication
    assert first.source.publication_id == old_scoreform_publication
    assert second.source.publication_id == old_scoreform_publication
    assert successor.publication_id not in {
        entry.source.publication_id for entry in fresh_inputs.entries
    }
    assert first.status == "excluded"
    assert first.exclusion_reason == "reassessment_noncontributing"
    assert second.status == "native_state"
    assert second.native_state is not None
    assert second.native_state.code == "ambiguous"

    # Withdrawal removes Quillan from operative contribution without fabricating
    # zero or low proficiency.
    assert quillan.status == "excluded"
    assert quillan.exclusion_reason == "eligibility_not_included"
    assert quillan.proficiency_level_id is None

    # Concord group evidence remains nonstudent even while other source
    # lifecycle changes occur at the same time.
    assert concord_group.target_kind == "concord_group"
    assert concord_group.status == "excluded"
    assert concord_group.exclusion_reason == "nonstudent_target"
    assert concord_group.proficiency_level_id is None
    assert concord_student.status == "performance"
    assert concord_student.proficiency_level_id == "proficient"

    policy_ref = original.snapshot.policy_reference
    stored_policy = load_standard_proficiency_policy_revision(
        root,
        policy_ref.class_id,
        policy_ref.policy_id,
        policy_ref.policy_revision,
    )
    outcome = calculate_standard_proficiency(
        fresh_inputs,
        stored_policy.policy,
        aggregation.target_scale.scale,
    )

    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.performance_observation_count == 1
    assert outcome.native_state_count == 1
    assert outcome.excluded_count == 3
    assert fresh_inputs.sha256 != original.snapshot.inputs_sha256


@pytest.mark.parametrize("status", ("blocked", "insufficient"))
def test_structurally_ready_class_does_not_treat_grade_status_as_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    root = tmp_path / status
    _make_ready_grade_class(root)
    selected = _persist_selected_standards_grade(
        root,
        monkeypatch,
        status=status,
    )
    before = _tree_bytes(root)

    result = invoke_module_readiness(
        get_module_operations_profile(),
        ModuleOperationsRequest(
            workspace_root=root,
            class_id=standards.CLASS_ID,
            active_school_year=standards.PERIOD.school_year,
        ),
    )

    assert selected.snapshot.outcome.status == status
    assert result.code == "module_operations.evaluated"
    assert result.report is not None
    assert result.report.evaluation == "evaluated"
    assert result.report.ready is True
    assert result.report.notices == ()
    assert _tree_bytes(root) == before


def test_ready_and_stale_grade_attention_are_valid_simultaneously(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "stale"
    _make_ready_grade_class(root)
    selected = _persist_selected_standards_grade(
        root,
        monkeypatch,
        status="calculated",
    )

    changed_inputs = replace(
        selected.snapshot.inputs,
        policy_reference=replace(
            selected.snapshot.inputs.policy_reference,
            policy_revision=2,
        ),
    )
    freshness = assess_standards_grade_result_freshness(
        selected.snapshot,
        changed_inputs,
    )
    assert freshness.status == "stale"
    assert freshness.reasons == ("policy_changed",)

    # Keep the real selected-result discovery, freshness comparison, attention
    # vocabulary, Core adapter, and owner action. Only substitute the explicit
    # current assembly basis so the test can isolate readiness from academic
    # currentness without installing a second Grade-policy revision.
    monkeypatch.setattr(
        grade_report_attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=changed_inputs),
    )

    request = ModuleOperationsRequest(
        workspace_root=root,
        class_id=standards.CLASS_ID,
        active_school_year=standards.PERIOD.school_year,
    )
    profile = get_module_operations_profile()
    before = _tree_bytes(root)

    readiness = invoke_module_readiness(profile, request)
    attention = invoke_module_attention(profile, request)

    assert readiness.code == "module_operations.evaluated"
    assert readiness.report is not None
    assert readiness.report.ready is True
    assert readiness.report.notices == ()

    assert attention.code == "module_operations.evaluated"
    assert attention.report is not None
    assert attention.report.evaluation == "evaluated"
    assert tuple(summary.code for summary in attention.report.summaries) == (
        "meridian_grade_result_stale",
    )
    assert attention.report.summaries[0].count == 1
    assert attention.report.summaries[0].class_id == standards.CLASS_ID
    assert attention.report.summaries[0].action is not None
    assert (
        attention.report.summaries[0].action.action_id
        == "open_preview_grades"
    )

    # Both operations remain read-only. Structural readiness and academic
    # attention are simultaneous, independent facts.
    assert _tree_bytes(root) == before
