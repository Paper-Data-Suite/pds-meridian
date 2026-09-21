from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import tests.test_issue50_cross_producer_acceptance as issue50
import tests.test_issue51_cross_producer_acceptance as issue51
import tests.test_issue52_cross_producer_acceptance as issue52
from meridian.conventional_grade import create_conventional_grade_result_snapshot
from meridian.conventional_grade_assembly import (
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_storage import (
    get_current_conventional_grade_result_revision,
    select_conventional_grade_result_revision,
    write_conventional_grade_result_revision,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
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
from meridian.hybrid_grade_assembly import assemble_hybrid_grade_calculation
from meridian.hybrid_grade_result import create_hybrid_grade_result_snapshot
from meridian.hybrid_grade_storage import (
    get_current_hybrid_grade_result_revision,
    select_hybrid_grade_result_revision,
    write_hybrid_grade_result_revision,
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
    get_current_standards_grade_result_revision,
    select_standards_grade_result_revision,
    write_standards_grade_result_revision,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_attempts_support import prepare_attempt_workspace
from tests.cross_producer_proficiency_support import ACTOR_ID
from tests.cross_producer_test_support import SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import CLASS_ID, SCOREFORM_WORK

NOW = datetime(2026, 9, 20, 22, 0, tzinfo=UTC)
SECOND_GRADE_ITEM_ID = "issue55_conventional_second"
TWO_ITEM_POLICY_ID = "issue55_conventional_two_item"


def _target(family: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=SHARED_STUDENT_ID,
        target_period=issue50.PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _freeze_family(
    root: Path,
    family: str,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None,
):
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=f"issue55_{family}_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="issue55_grade_family_acceptance",
        title=f"Issue 55 {family} report",
        target_period=issue50.PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", ACTOR_ID),
        rationale="Issue #55 BA/BB/BC source-level qualification.",
        revised_at=NOW,
    )
    stored_definition = write_reporting_definition_revision(root, definition).stored
    request = GradeReportPreviewRequest(
        _target(family),
        work_evidence=work_evidence,
    )
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", ACTOR_ID),
        requested_at=NOW + timedelta(minutes=1),
        rationale="Freeze exact family-specific Grade report.",
    )
    stored = freeze_reporting_snapshot(
        root,
        snapshot_id=f"issue55_{family}_snapshot",
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=2),
    )
    reloaded = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert reloaded.reference == stored.reference
    assert reloaded.content == stored.content
    row = reloaded.snapshot.report_preview.rows[0]
    assert row.status == "available"
    assert row.observation is not None
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json)
    assert isinstance(explanation, dict)
    return stored, reloaded, row, explanation, request


def _install_two_item_conventional_policy(
    root: Path,
    first_sha256: str,
    second_sha256: str,
) -> None:
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=TWO_ITEM_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 55 two-item conventional Grade policy",
        calculation_family="conventional",
        configuration=ConventionalGradeConfiguration(
            mode="total_points",
            items=(
                GradePolicyItemParticipation(
                    grade_item=GradePolicyItemReference(
                        CLASS_ID,
                        issue50.GRADE_ITEM_ID,
                        1,
                        first_sha256,
                    ),
                    category_id=None,
                    weight=None,
                    possible_points=Decimal("3"),
                ),
                GradePolicyItemParticipation(
                    grade_item=GradePolicyItemReference(
                        CLASS_ID,
                        SECOND_GRADE_ITEM_ID,
                        1,
                        second_sha256,
                    ),
                    category_id=None,
                    weight=None,
                    possible_points=Decimal("3"),
                ),
            ),
            categories=(),
        ),
        state_treatment=issue50._state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #55 BA literal multiple-Grade-Item qualification.",
        revised_at=issue50.RESULT_TIME,
    )
    stored_policy = write_grade_policy_revision(root, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=issue50.PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Activate the exact two-item conventional policy.",
        decided_at=issue50.RESULT_TIME,
    )
    write_grade_policy_activation_revision(root, activation)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue50.PERIOD,
        1,
        expected_current_revision=None,
    )


def _setup_conventional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture_root = tmp_path / "issue55_conventional"
    fixture_root.mkdir(parents=True, exist_ok=True)
    scenario = prepare_attempt_workspace(fixture_root)
    root = scenario.mixed.root

    first_item, first_sha256 = issue50._install_conventional_grade_item(root)
    first_membership, first_membership_sha256 = issue50._install_membership(
        root,
        first_item,
        first_sha256,
    )
    issue50._install_eligibility(
        root,
        scenario,
        first_membership,
        first_membership_sha256,
    )
    issue50._install_attempt_and_reassessment(
        root,
        scenario,
        first_membership_sha256,
    )

    with monkeypatch.context() as context:
        context.setattr(issue50, "GRADE_ITEM_ID", SECOND_GRADE_ITEM_ID)
        second_item, second_sha256 = issue50._install_conventional_grade_item(root)
        second_membership, second_membership_sha256 = issue50._install_membership(
            root,
            second_item,
            second_sha256,
        )
        issue50._install_eligibility(
            root,
            scenario,
            second_membership,
            second_membership_sha256,
        )
        issue50._install_attempt_and_reassessment(
            root,
            scenario,
            second_membership_sha256,
        )

    _install_two_item_conventional_policy(root, first_sha256, second_sha256)
    evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(scenario.authorized["scoreform"],),
        ),
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=SECOND_GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(scenario.authorized["scoreform"],),
        ),
    )
    assembly = assemble_conventional_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        1,
        evidence,
    )
    assert assembly.outcome.status == "calculated"
    assert len(assembly.inputs.items) == 2
    snapshot = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue50.RESULT_TIME,
    )
    write_conventional_grade_result_revision(
        root,
        snapshot,
        work_evidence=evidence,
    )
    select_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    return scenario, root, evidence, assembly


def test_conventional_snapshot_preserves_two_item_authority_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, root, evidence, assembly = _setup_conventional(tmp_path, monkeypatch)
    producer_before = {
        module_id: issue50._tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }

    stored, _, row, explanation, request = _freeze_family(
        root,
        "conventional",
        work_evidence=evidence,
    )

    assert explanation["mode"] == "total_points"
    items = explanation["items"]
    assert isinstance(items, list)
    assert len(items) == 2
    item_ids = {
        item["grade_item"]["reference"]["grade_item_id"] for item in items
    }
    assert item_ids == {issue50.GRADE_ITEM_ID, SECOND_GRADE_ITEM_ID}
    for item in items:
        kinds = {entry["kind"] for entry in item["provenance"]}
        assert {
            "source",
            "membership",
            "eligibility",
            "attempt_selection",
            "reassessment",
        }.issubset(kinds)

    authority_kinds = {
        binding.authority_kind for binding in stored.snapshot.provenance_bindings
    }
    assert {
        "academic_period_calendar",
        "core_publication",
        "core_publication_state",
        "grade_item_revision",
        "grade_item_membership",
        "evidence_source",
        "evidence_eligibility",
        "attempt_selection",
        "reassessment",
        "grade_policy_activation",
        "grade_policy_revision",
        "grade_result",
    }.issubset(authority_kinds)
    assert producer_before == {
        module_id: issue50._tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }

    frozen_content = stored.content
    frozen_digest = stored.snapshot_sha256
    second_result = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=2,
        calculated_at=issue50.RESULT_TIME + timedelta(minutes=1),
    )
    write_conventional_grade_result_revision(
        root,
        second_result,
        work_evidence=evidence,
    )
    select_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        1,
        2,
        expected_current_result_revision=1,
    )

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert historical.content == frozen_content
    assert historical.snapshot_sha256 == frozen_digest
    assert historical.snapshot.report_preview.rows[0].observation == row.observation

    current = explain_grade_report_preview(root, (request,))
    assert current.rows[0].observation is not None
    assert current.rows[0].observation.base_result_reference != (
        row.observation.base_result_reference
    )


def _setup_standards(tmp_path: Path):
    scenario = prepare_period_scenario(
        tmp_path / "issue55_standards",
        native_state_handling="noncontributing",
    )
    root = scenario.aggregation.workspace.mixed.root
    issue51._persist_selected_period_result(scenario)
    issue51._install_standards_grade_policy(scenario)
    assembly = assemble_standards_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
    )
    snapshot = create_standards_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue51.RESULT_TIME,
    )
    write_standards_grade_result_revision(root, snapshot)
    select_standards_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    return scenario, root


def test_standards_snapshot_survives_later_policy_activation(
    tmp_path: Path,
) -> None:
    _, root = _setup_standards(tmp_path)
    stored, _, row, explanation, request = _freeze_family(
        root,
        "standards_based",
        work_evidence=None,
    )

    assert explanation["status"] == "calculated"
    standards = explanation["standards"]
    assert isinstance(standards, list)
    assert len(standards) == 1
    assert standards[0]["result_reference"] is not None
    assert explanation["target_scale"]["scale_id"]
    assert row.observation is not None
    frozen_policy = row.observation.policy_reference
    frozen_content = stored.content
    frozen_digest = stored.snapshot_sha256

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
        title="Issue 51 standards Grade policy revision 2",
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
        rationale="Activate later policy after snapshot freeze.",
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

    historical = load_reporting_snapshot(root, CLASS_ID, stored.snapshot.snapshot_id)
    assert historical.content == frozen_content
    assert historical.snapshot_sha256 == frozen_digest
    historical_row = historical.snapshot.report_preview.rows[0]
    assert historical_row.observation is not None
    assert historical_row.observation.policy_reference == frozen_policy

    current = explain_grade_report_preview(root, (request,))
    assert current.rows[0].observation is not None
    assert current.rows[0].observation.policy_reference == frozen_policy
    assert current.rows[0].observation.base_freshness_status == "stale"
    assert current.rows[0].observation.base_freshness_reasons


def _setup_hybrid(tmp_path: Path):
    scenario = prepare_period_scenario(
        tmp_path / "issue55_hybrid",
        native_state_handling="noncontributing",
    )
    aggregation = scenario.aggregation
    attempt_workspace = aggregation.workspace
    root = attempt_workspace.mixed.root
    issue51._persist_selected_period_result(scenario)

    item, item_sha256 = issue50._install_conventional_grade_item(root)
    membership, membership_sha256 = issue50._install_membership(
        root,
        item,
        item_sha256,
    )
    issue50._install_eligibility(
        root,
        attempt_workspace,
        membership,
        membership_sha256,
    )
    issue50._install_attempt_and_reassessment(
        root,
        attempt_workspace,
        membership_sha256,
    )
    issue52._install_hybrid_policy(scenario, item_sha256)
    evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(attempt_workspace.authorized["scoreform"],),
        ),
    )
    assembly = assemble_hybrid_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue52.PERIOD,
        1,
        evidence,
    )
    snapshot = create_hybrid_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue52.RESULT_TIME,
    )
    write_hybrid_grade_result_revision(
        root,
        snapshot,
        work_evidence=evidence,
    )
    select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue52.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    return attempt_workspace, root, evidence


def test_hybrid_snapshot_preserves_embedded_components_without_standalone_results(
    tmp_path: Path,
) -> None:
    _, root, evidence = _setup_hybrid(tmp_path)
    assert (
        get_current_standards_grade_result_revision(
            root,
            CLASS_ID,
            SHARED_STUDENT_ID,
            issue52.PERIOD,
            1,
        )
        is None
    )
    assert get_current_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue52.PERIOD,
        1,
    ) is None
    assert get_current_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue52.PERIOD,
        1,
    ) == 1

    stored, reloaded, row, explanation, _ = _freeze_family(
        root,
        "hybrid",
        work_evidence=evidence,
    )

    assert explanation["status"] == "calculated"
    conventional = explanation["conventional_component"]
    standards = explanation["standards_component"]
    assert conventional["component_kind"] == "conventional"
    assert standards["component_kind"] == "standards_based"
    assert conventional["configured_weight"] == "0.6"
    assert standards["configured_weight"] == "0.4"
    assert conventional["breakdown"]["mode"] == "total_points"
    assert standards["breakdown"]["status"] == "calculated"
    assert row.observation is not None
    assert any(
        entry.dimension == "evidence" and entry.key == "hybrid_component_basis"
        for entry in row.observation.basis_entries
    )
    assert reloaded.content == stored.content
    assert reloaded.snapshot_sha256 == stored.snapshot_sha256

    assert get_current_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue52.PERIOD,
        1,
    ) is None
    assert (
        get_current_standards_grade_result_revision(
            root,
            CLASS_ID,
            SHARED_STUDENT_ID,
            issue52.PERIOD,
            1,
        )
        is None
    )
