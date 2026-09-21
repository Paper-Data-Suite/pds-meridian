from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.standards import write_workspace_standards_library

import tests.test_issue51_cross_producer_acceptance as issue51
import tests.test_reporting_snapshot_grade_families_issue55 as family55
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_policy_activation_storage import (
    load_grade_policy_activation_revision,
    select_grade_policy_activation_revision,
    write_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import (
    load_grade_policy_revision,
    write_grade_policy_revision,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_freeze import freeze_reporting_snapshot
from meridian.reporting_snapshot_record import (
    reporting_snapshot_build_request_from_preview_requests,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_snapshot,
    write_reporting_definition_revision,
)
from meridian.standards_grade_assembly import assemble_standards_grade_calculation
from meridian.standards_grade_result import create_standards_grade_result_snapshot
from meridian.standards_grade_storage import (
    select_standards_grade_result_revision,
    write_standards_grade_result_revision,
)
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    commit_teacher_grade_override_withdrawal_preview,
    preview_teacher_grade_override_selection,
    preview_teacher_grade_override_withdrawal,
)
from meridian.teacher_grade_override_workflow import (
    commit_teacher_grade_override_authoring_preview,
    preview_teacher_grade_override_authoring,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_proficiency_support import ACTOR_ID
from tests.cross_producer_test_support import (
    SECONDARY_STUDENT_ID,
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import CLASS_ID

NOW = datetime(2026, 9, 20, 23, 0, tzinfo=UTC)
REPLACEMENT_GRADE = Decimal("91.25")


def _target(student_id: str, family: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=issue51.PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _freeze(
    root: Path,
    *,
    suffix: str,
    target: GradePreviewTarget,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
):
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=f"issue55_{suffix}_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="issue55_override_state_acceptance",
        title=f"Issue 55 {suffix} report",
        target_period=target.target_period,
        intended_audience="teacher",
        actor=ReportingActor("teacher", ACTOR_ID),
        rationale="Issue #55 BD-BH qualification.",
        revised_at=NOW,
    )
    stored_definition = write_reporting_definition_revision(root, definition).stored
    request = GradeReportPreviewRequest(
        target,
        work_evidence=work_evidence,
    )
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", ACTOR_ID),
        requested_at=NOW + timedelta(minutes=1),
        rationale="Freeze exact override/state Grade report.",
    )
    stored = freeze_reporting_snapshot(
        root,
        snapshot_id=f"issue55_{suffix}_snapshot",
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=2),
    )
    reloaded = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert reloaded.reference == stored.reference
    assert reloaded.content == stored.content
    return stored, reloaded, reloaded.snapshot.report_preview.rows[0], request


def test_applicable_override_freezes_exact_precedence_and_survives_withdrawal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, root, evidence, assembly = family55._setup_conventional(tmp_path, monkeypatch)
    target = _target(SHARED_STUDENT_ID, "conventional")

    authoring = preview_teacher_grade_override_authoring(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
        "conventional",
        replacement_grade=REPLACEMENT_GRADE,
        actor_id=ACTOR_ID,
        rationale="Issue #55 applicable override before reporting freeze.",
        decided_at=NOW,
        work_evidence=evidence,
    )
    authored = commit_teacher_grade_override_authoring_preview(root, authoring)
    selection = preview_teacher_grade_override_selection(
        root,
        authored.stored_reference,
    )
    commit_teacher_grade_override_selection_preview(root, selection)

    stored, _, row, _ = _freeze(
        root,
        suffix="applicable_override",
        target=target,
        work_evidence=evidence,
    )
    assert row.status == "available"
    assert row.observation is not None
    observation = row.observation
    assert observation.base_grade == assembly.outcome.rounded_grade
    assert observation.selected_override_reference == authored.stored_reference
    assert observation.override_applicability == "applicable"
    assert observation.override_replacement_grade == REPLACEMENT_GRADE
    assert observation.effective_grade == REPLACEMENT_GRADE
    assert observation.effective_source == "override"
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json)
    selected_override = explanation["common"]["selected_override"]
    assert selected_override["replacement_grade"] == str(REPLACEMENT_GRADE)
    assert explanation["common"]["base_grade"] == str(assembly.outcome.rounded_grade)
    assert explanation["common"]["effective_grade"] == str(REPLACEMENT_GRADE)

    frozen_bytes = stored.content
    frozen_digest = stored.snapshot_sha256
    frozen_override_reference = observation.selected_override_reference

    withdrawal_preview = preview_teacher_grade_override_withdrawal(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
        "conventional",
        actor_id=ACTOR_ID,
        rationale="Issue #55 withdraw override after reporting freeze.",
        decided_at=NOW + timedelta(minutes=10),
    )
    withdrawn = commit_teacher_grade_override_withdrawal_preview(
        root,
        withdrawal_preview,
    )
    withdrawal_selection = preview_teacher_grade_override_selection(
        root,
        withdrawn.stored_reference,
    )
    commit_teacher_grade_override_selection_preview(root, withdrawal_selection)

    current = explain_grade_report_preview(
        root,
        (GradeReportPreviewRequest(target, work_evidence=evidence),),
    )
    current_observation = current.rows[0].observation
    assert current_observation is not None
    assert current_observation.override_applicability == "withdrawn"
    assert current_observation.selected_override_reference == withdrawn.stored_reference
    assert current_observation.override_replacement_grade is None
    assert current_observation.effective_grade == assembly.outcome.rounded_grade
    assert current_observation.effective_source == "base"

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert historical.content == frozen_bytes
    assert historical.snapshot_sha256 == frozen_digest
    historical_observation = historical.snapshot.report_preview.rows[0].observation
    assert historical_observation is not None
    assert (
        historical_observation.selected_override_reference
        == frozen_override_reference
    )
    assert historical_observation.override_applicability == "applicable"
    assert historical_observation.override_replacement_grade == REPLACEMENT_GRADE
    assert historical_observation.effective_grade == REPLACEMENT_GRADE


def _activate_later_standards_policy(root: Path) -> None:
    first_policy = load_grade_policy_revision(
        root,
        CLASS_ID,
        issue51.GRADE_POLICY_ID,
        1,
    )
    second_policy_value = replace(
        first_policy.policy,
        policy_revision=2,
        supersedes_revision=1,
        title="Issue 55 later standards policy",
        revised_at=issue51.RESULT_TIME + timedelta(days=1),
    )
    second_policy = write_grade_policy_revision(root, second_policy_value).stored
    first_activation = load_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue51.PERIOD,
        1,
    )
    second_activation = replace(
        first_activation.decision,
        activation_revision=2,
        supersedes_revision=1,
        policy_reference=second_policy.reference,
        rationale="Issue #55 later activation makes selected Grade stale.",
        decided_at=issue51.RESULT_TIME + timedelta(days=1, minutes=1),
    )
    write_grade_policy_activation_revision(root, second_activation)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue51.PERIOD,
        2,
        expected_current_revision=1,
    )


def test_stale_grade_freezes_exact_staleness_without_effective_authority(
    tmp_path: Path,
) -> None:
    _, root = family55._setup_standards(tmp_path)
    _activate_later_standards_policy(root)
    target = _target(SHARED_STUDENT_ID, "standards_based")

    stored, reloaded, row, _ = _freeze(
        root,
        suffix="stale_grade",
        target=target,
    )
    assert row.status == "available"
    assert row.observation is not None
    observation = row.observation
    assert observation.base_result_status == "calculated"
    assert observation.base_grade is not None
    assert observation.base_freshness_status == "stale"
    assert observation.base_freshness_reasons
    assert observation.effective_grade is None
    assert observation.effective_source == "none"
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json)
    assert explanation["common"]["base_freshness_status"] == "stale"
    assert explanation["common"]["base_freshness_reasons"]
    assert explanation["common"]["effective_grade"] is None

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert historical.content == stored.content == reloaded.content
    assert historical.snapshot_sha256 == stored.snapshot_sha256
    historical_observation = historical.snapshot.report_preview.rows[0].observation
    assert historical_observation == observation


def _install_secondary_state_grade(root: Path, scenario: object, status: str) -> None:
    aggregation = scenario.aggregation  # type: ignore[attr-defined]
    write_workspace_standards_library(root, aggregation.standard_library)
    scale = aggregation.target_scale
    missing_treatment = "blocking" if status == "blocked" else "exclude"
    state_treatment = replace(issue51._state_treatment(), missing=missing_treatment)
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=f"issue55_{status}_grade",
        policy_revision=1,
        supersedes_revision=None,
        title=f"Issue 55 {status} Grade policy",
        calculation_family="standards_based",
        configuration=StandardsBasedGradeConfiguration(
            target_scale=scale.reference,
            standards=(
                StandardGradeParticipation(
                    standard_id=SHARED_STANDARD_ID,
                    weight=Decimal("1"),
                ),
            ),
            conversions=tuple(
                ProficiencyGradeConversion(level_id, grade_value)
                for level_id, grade_value in issue51.CONVERSIONS.items()
            ),
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
        ),
        state_treatment=state_treatment,
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale=f"Issue #55 real {status} nonnumeric Grade state.",
        revised_at=NOW,
    )
    stored_policy = write_grade_policy_revision(root, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=issue51.PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale=f"Activate issue #55 {status} Grade policy.",
        decided_at=NOW,
    )
    write_grade_policy_activation_revision(root, activation)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue51.PERIOD,
        1,
        expected_current_revision=None,
    )

    assembly = assemble_standards_grade_calculation(
        root,
        CLASS_ID,
        SECONDARY_STUDENT_ID,
        issue51.PERIOD,
        1,
    )
    assert assembly.outcome.status == status
    assert assembly.outcome.unrounded_grade is None
    assert assembly.outcome.rounded_grade is None
    snapshot = create_standards_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=1),
    )
    write_standards_grade_result_revision(root, snapshot)
    select_standards_grade_result_revision(
        root,
        CLASS_ID,
        SECONDARY_STUDENT_ID,
        issue51.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )


@pytest.mark.parametrize(
    ("status", "expected_action"),
    (("blocked", "blocking"), ("insufficient", "exclude")),
)
def test_nonnumeric_grade_states_freeze_without_silent_zero(
    tmp_path: Path,
    status: str,
    expected_action: str,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path / f"issue55_{status}",
        native_state_handling="noncontributing",
    )
    root = scenario.aggregation.workspace.mixed.root
    issue51._persist_selected_period_result(scenario)
    _install_secondary_state_grade(root, scenario, status)

    stored, _, row, _ = _freeze(
        root,
        suffix=f"{status}_grade",
        target=_target(SECONDARY_STUDENT_ID, "standards_based"),
    )
    assert row.status == "available"
    assert row.observation is not None
    observation = row.observation
    assert observation.base_result_status == status
    assert observation.base_grade is None
    assert observation.effective_grade is None
    assert observation.effective_source == "none"
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json)
    assert explanation["status"] == status
    assert explanation["common"]["base_grade"] is None
    assert explanation["common"]["effective_grade"] is None
    assert explanation["formula"]["unrounded_grade"] is None
    assert explanation["formula"]["rounded_grade"] is None
    standard = explanation["standards"][0]
    assert standard["source_state"] == "missing"
    assert standard["action"] == expected_action
    assert standard["converted_grade_value"] is None
    assert standard["calculation_value"] is None
    assert standard["weighted_contribution"] is None

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    historical_observation = historical.snapshot.report_preview.rows[0].observation
    assert historical_observation is not None
    assert historical_observation.base_grade is None
    assert historical_observation.effective_grade is None


def test_no_selected_grade_freezes_as_unavailable_not_zero(tmp_path: Path) -> None:
    _, root = family55._setup_standards(tmp_path)
    target = _target(SECONDARY_STUDENT_ID, "standards_based")

    stored, _, row, _ = _freeze(
        root,
        suffix="no_selected_grade",
        target=target,
    )
    assert row.status == "unavailable"
    assert row.unavailable_reason == "no_selected_grade"
    assert row.observation is None
    assert row.observation_sha256 is None
    assert row.explanation_json is None
    assert row.explanation_sha256 is None
    assert stored.snapshot.report_preview.summary.requested_count == 1
    assert stored.snapshot.report_preview.summary.available_count == 0
    assert stored.snapshot.report_preview.summary.unavailable_count == 1

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    historical_row = historical.snapshot.report_preview.rows[0]
    assert historical_row.status == "unavailable"
    assert historical_row.unavailable_reason == "no_selected_grade"
    assert historical_row.observation is None
