from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog
from pds_core.academic_period_storage import (
    load_current_academic_period_calendar,
    write_academic_period_calendar,
)
from pds_core.registry_services import (
    PublicationWithdrawalRequest,
    withdraw_publication,
)

import meridian.ingestion as ingestion
import tests.test_issue50_cross_producer_acceptance as issue50
import tests.test_issue51_cross_producer_acceptance as issue51
import tests.test_reporting_snapshot_grade_families_issue55 as families
from meridian.conventional_grade import create_conventional_grade_result_snapshot
from meridian.conventional_grade_assembly import (
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_storage import (
    select_conventional_grade_result_revision,
    write_conventional_grade_result_revision,
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
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_to_grade_report_preview,
)
from meridian.reporting_snapshot_freeze import freeze_reporting_snapshot
from meridian.reporting_snapshot_record import (
    ReportingSnapshot,
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
from tests.cross_producer_attempts_support import prepare_attempt_workspace
from tests.cross_producer_test_support import (
    SHARED_STUDENT_ID,
    exact_reader_version,
)
from tests.cross_producer_workspace_support import (
    CLASS_ID,
    SCOREFORM_WORK,
    supersede_scoreform,
)

NOW = datetime(2026, 9, 21, 13, 0, tzinfo=UTC)


def _target(
    family: str,
    *,
    calendar_revision: int = 1,
) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=SHARED_STUDENT_ID,
        target_period=issue50.PERIOD,
        calendar_revision=calendar_revision,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _write_definition(
    root: Path,
    definition_id: str,
) -> ReportingDefinitionReference:
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=definition_id,
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="issue55_historical_movement_acceptance",
        title=f"Issue 55 {definition_id}",
        target_period=issue50.PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", issue50.ACTOR_ID),
        rationale="Issue #55 BM-BP historical movement qualification.",
        revised_at=NOW,
    )
    return write_reporting_definition_revision(root, definition).stored.reference


def _freeze(
    root: Path,
    *,
    definition_reference: ReportingDefinitionReference,
    snapshot_id: str,
    request: GradeReportPreviewRequest,
    offset_minutes: int,
):
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=definition_reference,
        requests=(request,),
        actor=ReportingActor("teacher", issue50.ACTOR_ID),
        requested_at=NOW + timedelta(minutes=offset_minutes),
        rationale="Freeze exact historical-movement Grade report.",
    )
    return freeze_reporting_snapshot(
        root,
        snapshot_id=snapshot_id,
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=offset_minutes + 1),
    )


def _core_publication_records(snapshot: ReportingSnapshot) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for binding in snapshot.provenance_bindings:
        if (
            binding.authority_kind != "core_publication"
            or binding.reference_kind != "core_publication_record"
        ):
            continue
        decoded = json.loads(binding.reference_json)
        assert isinstance(decoded, dict)
        records.append(decoded)
    return records


def _core_publication_states(snapshot: ReportingSnapshot) -> list[dict[str, object]]:
    states: list[dict[str, object]] = []
    for binding in snapshot.provenance_bindings:
        if (
            binding.authority_kind != "core_publication_state"
            or binding.reference_kind != "core_publication_observation"
        ):
            continue
        decoded = json.loads(binding.reference_json)
        assert isinstance(decoded, dict)
        states.append(decoded)
    return states


def _calendar_bindings(snapshot: ReportingSnapshot) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for binding in snapshot.provenance_bindings:
        if binding.authority_kind != "academic_period_calendar":
            continue
        decoded = json.loads(binding.reference_json)
        assert isinstance(decoded, dict)
        values.append(decoded)
    return values


def _setup_conventional(tmp_path: Path):
    fixture_root = tmp_path / "issue55_history_conventional"
    fixture_root.mkdir(parents=True, exist_ok=True)
    scenario = prepare_attempt_workspace(fixture_root)
    root = scenario.mixed.root
    item, item_sha256 = issue50._install_conventional_grade_item(root)
    membership, membership_sha256 = issue50._install_membership(
        root,
        item,
        item_sha256,
    )
    issue50._install_eligibility(
        root,
        scenario,
        membership,
        membership_sha256,
    )
    issue50._install_attempt_and_reassessment(root, scenario, membership_sha256)
    issue50._install_grade_policy(root, item_sha256)
    evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
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
    result = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue50.RESULT_TIME,
    )
    write_conventional_grade_result_revision(
        root,
        result,
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
    return scenario, root, evidence


def _current_scoreform_projection(
    scenario: object,
    *,
    expected_publication_id: str,
) -> AuthorizedProjectionSnapshot:
    mixed = scenario.mixed  # type: ignore[attr-defined]
    rebuild_academic_catalog(mixed.root)
    discovered = ingestion.discover_publication_candidates(
        mixed.root,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="scoreform",
                state="current",
                limit=10,
            )
        ),
    )
    candidates = tuple(
        item
        for item in discovered.candidates
        if item.publication_id == expected_publication_id
    )
    assert len(candidates) == 1
    prepared = ingestion.prepare_publication_invocation(
        mixed.root,
        candidates[0],
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        distribution_version_resolver=exact_reader_version,
    )
    inventory = mixed.adapter_registry.invoke(
        prepared.projection_request,
        exact_reader_version,
    )
    cached = cache_projected_inventory(
        mixed.root,
        prepared,
        inventory,
        authorizer=mixed.authorizer,
    )
    return load_authorized_projection_snapshot(
        mixed.root,
        expected_publication_id,
        cached.stored.cache_key,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        distribution_version_resolver=exact_reader_version,
    )


def _reload_scoreform_projection(
    scenario: object,
    authorized: AuthorizedProjectionSnapshot,
) -> AuthorizedProjectionSnapshot:
    mixed = scenario.mixed  # type: ignore[attr-defined]
    stored = authorized.stored
    publication_id = stored.snapshot.source.publication.publication_id
    return load_authorized_projection_snapshot(
        mixed.root,
        publication_id,
        stored.cache_key,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        distribution_version_resolver=exact_reader_version,
    )


def test_source_publication_supersession_preserves_a_and_freezes_material_b(
    tmp_path: Path,
) -> None:
    scenario, root, evidence_a = _setup_conventional(tmp_path)
    definition = _write_definition(root, "issue55_bm_report")
    request_a = GradeReportPreviewRequest(
        _target("conventional"),
        work_evidence=evidence_a,
    )
    snapshot_a = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bm_snapshot_a",
        request=request_a,
        offset_minutes=1,
    )
    a_content = snapshot_a.content
    a_digest = snapshot_a.snapshot_sha256
    old_publication_id = scenario.mixed.publications["scoreform"].publication_id
    assert any(
        record["publication"]["publication_id"] == old_publication_id
        for record in _core_publication_records(snapshot_a.snapshot)
    )

    new_publication = supersede_scoreform(scenario.mixed)
    assert new_publication.publication_id != old_publication_id
    current_projection = _current_scoreform_projection(
        scenario,
        expected_publication_id=new_publication.publication_id,
    )
    assert current_projection.assessment.source_status == "current"
    evidence_b = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(current_projection,),
        ),
    )
    assembly_b = assemble_conventional_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        1,
        evidence_b,
    )
    assert assembly_b.outcome.status == "blocked"
    result_b = create_conventional_grade_result_snapshot(
        assembly_b.inputs,
        assembly_b.outcome,
        result_revision=2,
        calculated_at=issue50.RESULT_TIME + timedelta(minutes=10),
    )
    write_conventional_grade_result_revision(
        root,
        result_b,
        work_evidence=evidence_b,
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
    request_b = GradeReportPreviewRequest(
        _target("conventional"),
        work_evidence=evidence_b,
    )
    live_b = explain_grade_report_preview(root, (request_b,))
    assert live_b.rows[0].status == "available"
    assert live_b.rows[0].observation is not None
    assert live_b.rows[0].observation.base_result_status == "blocked"
    snapshot_b = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bm_snapshot_b",
        request=request_b,
        offset_minutes=4,
    )

    historical_a = load_reporting_snapshot(root, CLASS_ID, "issue55_bm_snapshot_a")
    assert historical_a.content == a_content
    assert historical_a.snapshot_sha256 == a_digest
    assert any(
        record["publication"]["publication_id"] == old_publication_id
        for record in _core_publication_records(historical_a.snapshot)
    )
    assert any(
        record["publication"]["publication_id"] == new_publication.publication_id
        for record in _core_publication_records(snapshot_b.snapshot)
    )

    comparisons = compare_reporting_snapshot_to_grade_report_preview(
        historical_a.snapshot,
        live_b,
    )
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.relationship == "comparable"
    assert comparison.changed
    assert "base_result_changed" in comparison.reasons
    assert "base_status_changed" in comparison.reasons
    assert "effective_grade_changed" in comparison.reasons


def test_publication_withdrawal_keeps_historical_relationship_and_stales_live(
    tmp_path: Path,
) -> None:
    scenario, root, evidence = _setup_conventional(tmp_path)
    definition = _write_definition(root, "issue55_bn_report")
    request = GradeReportPreviewRequest(
        _target("conventional"),
        work_evidence=evidence,
    )
    snapshot_a = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bn_snapshot_a",
        request=request,
        offset_minutes=10,
    )
    frozen_content = snapshot_a.content
    frozen_digest = snapshot_a.snapshot_sha256
    publication_id = scenario.mixed.publications["scoreform"].publication_id
    frozen_states = [
        state
        for state in _core_publication_states(snapshot_a.snapshot)
        if state["publication_id"] == publication_id
    ]
    assert len(frozen_states) == 1
    assert frozen_states[0]["observed_canonical_state"] == "current_selectable"
    assert frozen_states[0]["source_status"] == "current"

    withdraw_publication(
        root,
        PublicationWithdrawalRequest(
            publication_id,
            "Issue #55 BN synthetic withdrawal after snapshot freeze.",
        ),
    )
    withdrawn_projection = _reload_scoreform_projection(
        scenario,
        evidence[0].authorized_snapshots[0],
    )
    assert withdrawn_projection.assessment.source_status == "withdrawn"
    withdrawn_evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(withdrawn_projection,),
        ),
    )
    live = explain_grade_report_preview(
        root,
        (
            GradeReportPreviewRequest(
                _target("conventional"),
                work_evidence=withdrawn_evidence,
            ),
        ),
    )
    assert live.rows[0].status == "available"
    assert live.rows[0].observation is not None
    assert live.rows[0].observation.base_freshness_status == "stale"
    assert live.rows[0].observation.base_freshness_reasons
    assert live.rows[0].observation.effective_grade is None

    historical = load_reporting_snapshot(root, CLASS_ID, "issue55_bn_snapshot_a")
    assert historical.content == frozen_content
    assert historical.snapshot_sha256 == frozen_digest
    historical_states = [
        state
        for state in _core_publication_states(historical.snapshot)
        if state["publication_id"] == publication_id
    ]
    assert historical_states == frozen_states


def test_calendar_revision_movement_does_not_reinterpret_snapshot(
    tmp_path: Path,
) -> None:
    _, root = families._setup_standards(tmp_path)
    definition = _write_definition(root, "issue55_bo_report")
    request = GradeReportPreviewRequest(_target("standards_based"))
    snapshot_a = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bo_snapshot_a",
        request=request,
        offset_minutes=20,
    )
    frozen_content = snapshot_a.content
    frozen_digest = snapshot_a.snapshot_sha256

    first = load_current_academic_period_calendar(root, issue50.PERIOD.school_year)
    assert first is not None
    assert first.calendar_revision == 1
    second = replace(
        first,
        calendar_revision=2,
        updated_at=first.updated_at + timedelta(days=1),
    )
    write_academic_period_calendar(
        root,
        second,
        expected_current_revision=1,
    )
    current = load_current_academic_period_calendar(root, issue50.PERIOD.school_year)
    assert current is not None
    assert current.calendar_revision == 2

    historical = load_reporting_snapshot(root, CLASS_ID, "issue55_bo_snapshot_a")
    assert historical.content == frozen_content
    assert historical.snapshot_sha256 == frozen_digest
    assert historical.snapshot.calendar_revision == 1
    assert historical.snapshot.build_request.calendar_revision == 1
    calendar_bindings = _calendar_bindings(historical.snapshot)
    assert len(calendar_bindings) == 1
    assert calendar_bindings[0]["calendar_revision"] == 1


def test_policy_revision_movement_keeps_a_and_allows_exact_b(
    tmp_path: Path,
) -> None:
    _, root = families._setup_standards(tmp_path)
    definition = _write_definition(root, "issue55_bp_report")
    request = GradeReportPreviewRequest(_target("standards_based"))
    snapshot_a = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bp_snapshot_a",
        request=request,
        offset_minutes=30,
    )
    a_content = snapshot_a.content
    a_digest = snapshot_a.snapshot_sha256
    a_row = snapshot_a.snapshot.report_preview.rows[0]
    assert a_row.observation is not None
    policy_a = a_row.observation.policy_reference

    first_policy = load_grade_policy_revision(
        root,
        CLASS_ID,
        issue51.GRADE_POLICY_ID,
        1,
    )
    policy_b_value = replace(
        first_policy.policy,
        policy_revision=2,
        supersedes_revision=1,
        title="Issue 55 BP standards policy revision 2",
        revised_at=issue51.RESULT_TIME + timedelta(days=2),
    )
    policy_b = write_grade_policy_revision(root, policy_b_value).stored
    first_activation = load_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue51.PERIOD,
        1,
    )
    activation_b = replace(
        first_activation.decision,
        activation_revision=2,
        supersedes_revision=1,
        policy_reference=policy_b.reference,
        rationale="Issue #55 BP activate policy B.",
        decided_at=issue51.RESULT_TIME + timedelta(days=2, minutes=1),
    )
    write_grade_policy_activation_revision(root, activation_b)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        issue51.PERIOD,
        2,
        expected_current_revision=1,
    )
    assembly_b = assemble_standards_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
    )
    assert assembly_b.policy.reference == policy_b.reference
    assert assembly_b.outcome.status == "calculated"
    result_b = create_standards_grade_result_snapshot(
        assembly_b.inputs,
        assembly_b.outcome,
        result_revision=2,
        calculated_at=issue51.RESULT_TIME + timedelta(days=2, minutes=2),
    )
    write_standards_grade_result_revision(root, result_b)
    select_standards_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        issue51.PERIOD,
        1,
        2,
        expected_current_result_revision=1,
    )

    live_b = explain_grade_report_preview(root, (request,))
    assert live_b.rows[0].status == "available"
    assert live_b.rows[0].observation is not None
    assert live_b.rows[0].observation.policy_reference == policy_b.reference
    snapshot_b = _freeze(
        root,
        definition_reference=definition,
        snapshot_id="issue55_bp_snapshot_b",
        request=request,
        offset_minutes=34,
    )

    historical_a = load_reporting_snapshot(root, CLASS_ID, "issue55_bp_snapshot_a")
    assert historical_a.content == a_content
    assert historical_a.snapshot_sha256 == a_digest
    historical_row = historical_a.snapshot.report_preview.rows[0]
    assert historical_row.observation is not None
    assert historical_row.observation.policy_reference == policy_a
    b_row = snapshot_b.snapshot.report_preview.rows[0]
    assert b_row.observation is not None
    assert b_row.observation.policy_reference == policy_b.reference

    comparisons = compare_reporting_snapshot_to_grade_report_preview(
        historical_a.snapshot,
        live_b,
    )
    assert len(comparisons) == 1
    assert comparisons[0].changed
    assert "policy_changed" in comparisons[0].reasons
