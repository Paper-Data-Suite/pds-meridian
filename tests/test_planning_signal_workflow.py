from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.planning_signal_workflow as workflow

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"


def policy_store(revision: int = 2) -> object:
    reference = SimpleNamespace(
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy_revision=revision,
        policy_sha256="a" * 64,
    )
    target_period = SimpleNamespace(
        period=SimpleNamespace(
            school_year="2026-2027",
            period_id="mp1",
        ),
        calendar_revision=4,
    )
    policy = SimpleNamespace(
        title="Reading support bands",
        academic_basis=SimpleNamespace(
            target_period=target_period,
            standard_id="NJSLSA.R1",
            source_policy=SimpleNamespace(
                class_id=CLASS_ID,
                policy_id="period_proficiency",
                policy_revision=3,
                policy_sha256="b" * 64,
            ),
            target_scale=SimpleNamespace(
                class_id=CLASS_ID,
                scale_id="four_level",
                scale_revision=2,
                scale_sha256="c" * 64,
            ),
        ),
        dimension_id="reading_support",
        band_count=3,
        band_definitions=(
            SimpleNamespace(
                band=1,
                minimum_scale_position=1,
                maximum_scale_position=1,
            ),
            SimpleNamespace(
                band=2,
                minimum_scale_position=2,
                maximum_scale_position=3,
            ),
            SimpleNamespace(
                band=3,
                minimum_scale_position=4,
                maximum_scale_position=4,
            ),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_42"),
        rationale="Instructional planning only.",
        revised_at=datetime(2026, 9, 3, 3, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        policy=policy,
        reference=reference,
        policy_sha256=reference.policy_sha256,
    )


def generated_candidate(reference: object) -> object:
    student_derivations = (
        SimpleNamespace(
            student_id="student_001",
            disposition="contributing",
        ),
        SimpleNamespace(
            student_id="student_002",
            disposition="noncontributing",
        ),
    )
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        policy_reference=reference,
        derivation_id="gsd_" + "d" * 64,
        calculation_fingerprint="e" * 64,
        roster_basis=SimpleNamespace(
            student_ids=("student_001", "student_002"),
        ),
        student_derivations=student_derivations,
    )
    return SimpleNamespace(
        status="generated",
        blockers=(),
        snapshot=snapshot,
    )


def blocked_candidate(code: str) -> object:
    return SimpleNamespace(
        status="blocked",
        blockers=(
            SimpleNamespace(
                code=code,
                student_id=(
                    None if code == "no_selected_policy" else "student_001"
                ),
                source_result=None,
                freshness_reasons=(),
            ),
        ),
        snapshot=None,
    )


def install_projection_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "GroupingSignalGenerationCandidate",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "GroupingSignalDerivationPolicyReference",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodProficiencyTarget",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodProficiencyAggregationPolicyReference",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "ProficiencyScaleReference",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "GroupingSignalBandDefinition",
        SimpleNamespace,
    )


def test_no_selected_policy_projects_blocker_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    calls = iter((None, None))
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: blocked_candidate("no_selected_policy"),
    )

    projection = workflow.project_planning_signal_readiness(
        "workspace",
        CLASS_ID,
        POLICY_ID,
    )

    assert projection.policy is None
    assert projection.generation_status == "blocked"
    assert projection.blocker_codes == ("no_selected_policy",)
    assert projection.ready_for_derivation_persistence is False
    assert projection.candidate_derivation_id is None
    assert projection.derivation_write_action == "not_performed"
    assert projection.preview_write_action == "not_performed"
    assert projection.review_write_action == "not_performed"
    assert projection.review_selection_action == "not_performed"
    assert projection.core_export_action == "not_performed"
    assert projection.csv_export_action == "not_performed"


def test_selected_policy_and_generated_candidate_are_projected_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    selected = policy_store()
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: generated_candidate(selected.reference),
    )

    projection = workflow.project_planning_signal_readiness(
        "workspace",
        CLASS_ID,
        POLICY_ID,
    )

    assert projection.policy is not None
    assert projection.policy.reference is selected.reference
    assert projection.policy.title == "Reading support bands"
    assert projection.policy.target_period.period.period_id == "mp1"
    assert projection.policy.standard_id == "NJSLSA.R1"
    assert projection.policy.dimension_id == "reading_support"
    assert projection.policy.band_count == 3
    assert projection.policy.tie_handling == "same_level_same_band"
    assert projection.policy.missing_result_handling == "noncontributing"
    assert projection.policy.insufficient_result_handling == "blocking"
    assert projection.policy.actor_id == "teacher_42"
    assert projection.generation_status == "generated"
    assert projection.blocker_codes == ()
    assert projection.ready_for_derivation_persistence is True
    assert projection.candidate_derivation_id == "gsd_" + "d" * 64
    assert projection.candidate_calculation_fingerprint == "e" * 64
    assert projection.roster_student_count == 2
    assert projection.contributing_student_count == 1
    assert projection.noncontributing_student_count == 1


def test_selected_policy_projects_current_result_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    selected = policy_store()
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: blocked_candidate("stale_result"),
    )

    projection = workflow.project_planning_signal_readiness(
        "workspace",
        CLASS_ID,
        POLICY_ID,
    )

    assert projection.policy is not None
    assert projection.generation_status == "blocked"
    assert projection.blocker_codes == ("stale_result",)
    assert projection.ready_for_derivation_persistence is False


def test_selected_policy_change_during_projection_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    before = policy_store(2)
    after = policy_store(3)
    calls = iter((before, after))
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: blocked_candidate("stale_result"),
    )

    with pytest.raises(
        workflow.PlanningSignalWorkflowStaleError,
        match="policy changed",
    ):
        workflow.project_planning_signal_readiness(
            "workspace",
            CLASS_ID,
            POLICY_ID,
        )


def test_generated_candidate_must_bind_stable_selected_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    selected = policy_store(2)
    wrong = policy_store(3)
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: generated_candidate(wrong.reference),
    )

    with pytest.raises(
        workflow.PlanningSignalWorkflowStaleError,
        match="does not bind",
    ):
        workflow.project_planning_signal_readiness(
            "workspace",
            CLASS_ID,
            POLICY_ID,
        )


def test_generation_read_error_is_teacher_workflow_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_projection_types(monkeypatch)
    selected = policy_store()
    monkeypatch.setattr(
        workflow,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            workflow.GroupingSignalGenerationError("cannot rebuild #35")
        ),
    )

    with pytest.raises(
        workflow.PlanningSignalWorkflowDependencyError,
        match="cannot rebuild",
    ):
        workflow.project_planning_signal_readiness(
            "workspace",
            CLASS_ID,
            POLICY_ID,
        )
