"""Installed Issue #60 cross-policy adversarial composition."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import timedelta
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_profile_constrained_grade as profile99  # type: ignore
from concord.academic_result_manifest import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
    AcademicResultManifest,
    ActivityContextProjection,
    CriterionProjection,
    CriterionSetProjection,
    ManifestProjection,
    ManifestRecordSet,
    PrivacyProjection,
    PublicActor,
    ScaleLevelProjection,
    ScoreProjection,
    ScoringScaleProjection,
    TargetReferenceProjection,
    academic_result_manifest_to_bytes,
    derive_manifest_capabilities,
    with_semantic_projection_digest,
)
from concord.pds_publication import (
    get_publication_producer_profile as concord_profile,
)
from pds_core.academic_catalog import (
    PublicationCatalogQuery,
    rebuild_academic_catalog,
)
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

import meridian.ingestion as ingestion
from meridian.adapters import AdapterRegistry
from meridian.concord_adapter import ConcordAcademicResultAdapter
from meridian.conventional_grade_storage import (
    load_current_conventional_grade_result,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreviewRequest
from meridian.hybrid_grade_storage import load_current_hybrid_grade_result
from meridian.projection_cache import cache_projected_inventory
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
    StoredReportingSnapshot,
    write_reporting_definition_revision,
)
from meridian.standards_grade_storage import load_current_standards_grade_result
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    commit_teacher_grade_override_withdrawal_preview,
    preview_teacher_grade_override_selection,
    preview_teacher_grade_override_withdrawal,
)
from meridian.teacher_grade_override_storage import (
    load_current_teacher_grade_override,
)

BASELINE_NAME = "issue60-cross-policy-installed-baseline.json"
SNAPSHOT_ID = "issue60_installed_hybrid_snapshot"
DEFINITION_ID = "issue60_installed_hybrid_report"
CONCORD_WORK_ID = "issue60_group_activity"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _verify_installed() -> None:
    issue54._verify_installed_composition()
    expected = {
        "pds-core": "0.6.4",
        "scoreform": "0.12.0",
        "quillan": "0.10.5",
        "pds-concord": "0.3.0",
    }
    for distribution, version in expected.items():
        _require(
            metadata.version(distribution) == version,
            f"Issue #60 installed dependency mismatch: {distribution}.",
        )
    for module_name in (
        "meridian.conventional_grade",
        "meridian.standards_grade",
        "meridian.standards_grade_profile",
        "meridian.hybrid_grade",
        "meridian.teacher_grade_override",
        "meridian.reporting_snapshot",
        "meridian.concord_adapter",
    ):
        issue54._installed_origin(module_name)


def _selected_grade_baseline(stored: Any) -> dict[str, object]:
    return {
        "revision": stored.snapshot.result_revision,
        "sha256": stored.reference.result_sha256,
        "rounded_grade": str(stored.snapshot.outcome.rounded_grade),
        "fingerprint": stored.snapshot.calculation_fingerprint,
    }


def _withdraw_conventional_override(
    workspace: Path,
    work_evidence: tuple[Any, ...],
) -> dict[str, object]:
    current = load_current_teacher_grade_override(
        workspace,
        issue54.issue50.CLASS_ID,
        issue54.issue50.STUDENT_ID,
        issue54.issue50.PERIOD,
        1,
        "conventional",
    )
    _require(current is not None, "Issue #60 active conventional override is missing.")
    assert current is not None
    _require(current.decision.decision == "override", "Expected active override.")
    active_reference = current.reference

    withdrawal = commit_teacher_grade_override_withdrawal_preview(
        workspace,
        preview_teacher_grade_override_withdrawal(
            workspace,
            issue54.issue50.CLASS_ID,
            issue54.issue50.STUDENT_ID,
            issue54.issue50.PERIOD,
            1,
            "conventional",
            actor_id=issue54.issue50.ACTOR_ID,
            rationale="Issue #60 installed override withdrawal.",
            decided_at=issue54.issue50.NOW + timedelta(hours=2),
        ),
    )
    still_selected = load_current_teacher_grade_override(
        workspace,
        issue54.issue50.CLASS_ID,
        issue54.issue50.STUDENT_ID,
        issue54.issue50.PERIOD,
        1,
        "conventional",
    )
    _require(
        still_selected is not None and still_selected.reference == active_reference,
        "Writing Issue #60 withdrawal silently changed override selection.",
    )
    commit_teacher_grade_override_selection_preview(
        workspace,
        preview_teacher_grade_override_selection(
            workspace,
            withdrawal.stored_reference,
        ),
    )
    selected = load_current_teacher_grade_override(
        workspace,
        issue54.issue50.CLASS_ID,
        issue54.issue50.STUDENT_ID,
        issue54.issue50.PERIOD,
        1,
        "conventional",
    )
    _require(selected is not None, "Issue #60 withdrawal did not select.")
    assert selected is not None
    _require(
        selected.decision.decision == "withdraw",
        "Issue #60 selected override state is not withdrawal.",
    )

    target = GradePreviewTarget(
        issue54.issue50.CLASS_ID,
        issue54.issue50.STUDENT_ID,
        issue54.issue50.PERIOD,
        1,
        "conventional",
    )
    preview = issue54.explain_current_grade_preview(
        workspace,
        target,
        work_evidence=work_evidence,
    )
    observation = issue54.conventional_grade_observation(preview)
    _require(
        observation.effective_source == "base"
        and observation.effective_grade == observation.base_grade,
        "Selected withdrawal did not restore exact base Grade precedence.",
    )
    return {
        "active_revision": active_reference.override_revision,
        "active_sha256": active_reference.override_sha256,
        "withdrawal_revision": selected.reference.override_revision,
        "withdrawal_sha256": selected.reference.override_sha256,
    }


def _profile_state(workspace: Path) -> dict[str, object]:
    base = profile99.base
    scope = {
        "class_id": base.CLASS_ID,
        "student_id": base.STUDENT_ID,
        "school_year": base.PERIOD.school_year,
        "period_id": base.PERIOD.period_id,
        "calendar_revision": base.CALENDAR_REVISION,
    }
    calendar = base._seed_core(workspace)
    scale = base._persist_scale(workspace)
    standard_policy = base._persist_standard_policy(workspace, scale)
    scoreform = base._persist_grade_item_result(
        workspace,
        base.SCOREFORM_WORK,
        "proficient",
        scale,
        standard_policy,
    )
    quillan = base._persist_grade_item_result(
        workspace,
        base.QUILLAN_WORK,
        "proficient",
        scale,
        standard_policy,
    )
    base._persist_period_result(
        workspace,
        calendar,
        scale,
        (scoreform, quillan),
        expected_level_id="proficient",
    )
    upstream = base._upstream_snapshot(workspace)
    profile99._install_policy(workspace, scale)
    result = cast(dict[str, object], profile99._calculate(workspace))
    _require(
        base._upstream_snapshot(workspace) == upstream,
        "Issue #60 profile Grade mutated producer/proficiency source state.",
    )
    return {
        **scope,
        "result": result,
    }


def _freeze_hybrid_snapshot(
    workspace: Path,
    work_evidence: tuple[Any, ...],
) -> StoredReportingSnapshot:
    target = GradePreviewTarget(
        issue54.issue52.CLASS_ID,
        issue54.issue52.STUDENT_ID,
        issue54.issue52.PERIOD,
        issue54.issue52.CALENDAR_REVISION,
        "hybrid",
    )
    request = GradeReportPreviewRequest(target, work_evidence=work_evidence)
    actor = ReportingActor("teacher", issue54.issue50.ACTOR_ID)
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=issue54.issue52.CLASS_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="issue60_installed_cross_policy_acceptance",
        title="Issue 60 installed cross-policy report",
        target_period=issue54.issue52.PERIOD,
        intended_audience="teacher",
        actor=actor,
        rationale="Freeze Issue #60 installed hybrid state.",
        revised_at=issue54.issue52.NOW + timedelta(hours=4),
    )
    stored_definition = write_reporting_definition_revision(
        workspace,
        definition,
    ).stored
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=actor,
        requested_at=issue54.issue52.NOW + timedelta(hours=5),
        rationale="Issue #60 installed ReportingSnapshot.",
    )
    return freeze_reporting_snapshot(
        workspace,
        snapshot_id=SNAPSHOT_ID,
        build_request=build,
        preview_requests=(request,),
        created_at=issue54.issue52.NOW + timedelta(hours=6),
    )


def _concord_manifest(
    work: ModuleWorkRef,
    source: ModuleRecordRef,
) -> AcademicResultManifest:
    teacher = PublicActor(
        actor_kind="authorized_adult",
        actor_id="teacher_local",
        owning_system="concord",
    )
    system = PublicActor(
        actor_kind="system",
        actor_id="projection_service",
        owning_system="concord",
    )
    scale = ScoringScaleProjection(
        scoring_scale_id="issue60_scale",
        lineage_id="issue60_scale_lineage",
        name="Issue 60 group rubric",
        revision=1,
        scale_type="ordinal",
        levels=(
            ScaleLevelProjection(
                value=0,
                label="Beginning",
                meaning="Initial evidence.",
                position=1,
                description="Initial.",
            ),
            ScaleLevelProjection(
                value=4,
                label="Secure",
                meaning="Consistent evidence.",
                position=2,
                description="Secure.",
            ),
        ),
        status="active",
        supersedes_scoring_scale_id=None,
    )
    criterion_set = CriterionSetProjection(
        criterion_set_id="issue60_criteria",
        lineage_id="issue60_criteria_lineage",
        revision=1,
        criterion_set_kind="local",
        scope="activity_specific",
        criterion_ids=("issue60_collaboration",),
        status="active",
        supersedes_criterion_set_id=None,
        standards_profile_id=None,
    )
    criterion = CriterionProjection(
        criterion_id="issue60_collaboration",
        criterion_set_id="issue60_criteria",
        key="collaboration",
        label="Collaboration",
        definition="Synthetic installed group evidence.",
        criterion_kind="local",
        supported_target_kinds=("concord_group",),
        status="active",
        standard_id=None,
        alignment_standard_ids=(),
        default_scoring_scale_id="issue60_scale",
    )
    score = ScoreProjection(
        score_record_id="issue60_group_score",
        activity_id=work.work_id,
        session_id=None,
        target_reference=TargetReferenceProjection(
            target_kind="concord_group",
            target_id="issue60_group",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
        criterion_id=criterion.criterion_id,
        score_kind="local",
        standard_id=None,
        scoring_scale_id=scale.scoring_scale_id,
        disposition="scored",
        value=4,
        basis="professional_judgment",
        scorer=teacher,
        scored_at=issue54.issue50.NOW + timedelta(hours=3),
        moderation_complete=True,
        status_reason=None,
        supersedes_score_record_id=None,
        current_state="current",
    )
    value = AcademicResultManifest(
        record_type=ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
        contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        producer_module_id="concord",
        generated_at=issue54.issue50.NOW + timedelta(hours=3),
        record_set=ManifestRecordSet("academic_results", 1),
        work=work,
        source_activity=source,
        projection=ManifestProjection(
            source_snapshot_revision=1,
            projection_digest_algorithm="sha256",
            projection_digest="0" * 64,
            generated_by=system,
            revision_reason="initial",
        ),
        activity_context=ActivityContextProjection(
            activity_id=work.work_id,
            class_id=work.class_id,
            title="Issue 60 installed group activity",
            scoring_orientation="local_criteria_only",
            standards_profile_id=None,
            focus_standard_ids=(),
            criterion_set_ids=(criterion_set.criterion_set_id,),
        ),
        criterion_sets=(criterion_set,),
        criteria=(criterion,),
        scoring_scales=(scale,),
        scores=(score,),
        score_evidence_links=(),
        moderation_records=(),
        standards_result_projection=(),
        privacy=PrivacyProjection(
            classification="teacher_restricted",
            audience_references=(),
            policy_reference=None,
            inherited_from=None,
        ),
    )
    return with_semantic_projection_digest(value)


def _concord_state(workspace: Path) -> dict[str, object]:
    issue54.issue50._seed_core_context(workspace)
    work = ModuleWorkRef("concord", issue54.issue50.CLASS_ID, CONCORD_WORK_ID)
    source = ModuleRecordRef(
        "concord",
        "activity",
        CONCORD_WORK_ID,
        "concord_activity_v1",
    )
    module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
    registration = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version="concord_academic_work_v1",
            title="Issue 60 installed group activity",
            work_kind="collaborative_activity",
            academic_intent="formative",
            lifecycle="active",
            source_records=(source,),
        ),
    )
    manifest = _concord_manifest(work, source)
    content = academic_result_manifest_to_bytes(manifest)
    relative = (
        f"classes/{work.class_id}/modules/{work.module_id}/work/{work.work_id}/"
        "publications/academic_results/1.json"
    )
    path = workspace.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=work,
            source_record=source,
            publication_kind="academic_result_set",
            capabilities=tuple(derive_manifest_capabilities(manifest)),
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="concord_academic_result_manifest_v1",
            manifest_path=relative,
            academic_work_registration_revision=(
                registration.registration.registration_revision
            ),
            expected_manifest_digest=hashlib.sha256(content).hexdigest(),
        ),
    )
    rebuild_academic_catalog(workspace)
    discovered = ingestion.discover_publication_candidates(
        workspace,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(module_id="concord", state="current", limit=10)
        ),
    )
    _require(len(discovered.candidates) == 1, "Concord discovery was not singular.")
    candidate = discovered.candidates[0]
    _require(
        candidate.publication_id == published.publication.publication_id,
        "Concord publication identity changed during discovery.",
    )
    producer_registry = PublicationProducerRegistry((concord_profile(),))
    adapter_registry = AdapterRegistry((ConcordAcademicResultAdapter(),))
    authorizer = issue54.issue45.AllowInstalledProjection()
    prepared = ingestion.prepare_publication_invocation(
        workspace,
        candidate,
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(issue54.issue50.STUDENT_ID,),
        distribution_version_resolver=issue54.issue45.installed_distribution_version,
    )
    inventory = adapter_registry.invoke(
        prepared.projection_request,
        issue54.issue45.installed_distribution_version,
    )
    groups = tuple(
        item for item in inventory.items if item.target.target_kind == "concord_group"
    )
    _require(len(groups) == 1, "Installed Concord group evidence was not singular.")
    group = groups[0]
    _require(group.subject is None, "Concord group evidence became student evidence.")
    _require(
        getattr(group.value, "value", None) == 4,
        "Concord installed group value changed.",
    )
    cached = cache_projected_inventory(
        workspace,
        prepared,
        inventory,
        authorizer=authorizer,
    )
    return {
        "class_id": work.class_id,
        "student_id": issue54.issue50.STUDENT_ID,
        "publication_id": published.publication.publication_id,
        "cache_key": cached.stored.cache_key,
        "snapshot_digest": cached.stored.snapshot_digest,
        "manifest_path": relative,
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "group_item_id": group.item_id,
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_cross_policy_adversarial.py <root>")
    _verify_installed()
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)

    conventional_workspace = root / "conventional"
    weighted_workspace = root / "weighted"
    profile_workspace = root / "profile"
    hybrid_workspace = root / "hybrid"
    concord_workspace = root / "concord"

    conventional_producer, conventional_evidence, conventional_descriptor = (
        issue54._conventional_state(conventional_workspace)
    )
    conventional_result = load_current_conventional_grade_result(
        conventional_workspace,
        issue54.issue50.CLASS_ID,
        issue54.issue50.STUDENT_ID,
        issue54.issue50.PERIOD,
        1,
    )
    _require(conventional_result is not None, "Conventional result is not selected.")
    assert conventional_result is not None
    override = _withdraw_conventional_override(
        conventional_workspace,
        conventional_evidence,
    )
    issue54.issue50._assert_unchanged(conventional_producer)

    # Issue #54's weighted helper deliberately rewrites shared Issue #51
    # module globals. Run the self-contained Issue #99 profile fixture first
    # and retain its exact scope before invoking that helper.
    profile_state = _profile_state(profile_workspace)
    profile_result = load_current_standards_grade_result(
        profile_workspace,
        cast(str, profile_state["class_id"]),
        cast(str, profile_state["student_id"]),
        profile99.base.AcademicPeriodRef(
            cast(str, profile_state["school_year"]),
            cast(str, profile_state["period_id"]),
        ),
        cast(int, profile_state["calendar_revision"]),
    )
    _require(profile_result is not None, "Profile standards result is not selected.")
    assert profile_result is not None

    weighted_target = issue54._standards_state(weighted_workspace)
    weighted_result = load_current_standards_grade_result(
        weighted_workspace,
        weighted_target.class_id,
        weighted_target.student_id,
        weighted_target.target_period,
        weighted_target.calendar_revision,
    )
    _require(
        weighted_result is not None,
        "Weighted standards result is not selected.",
    )
    assert weighted_result is not None
    _require(
        weighted_result.snapshot.inputs.configuration.aggregation_strategy
        == "weighted_mean",
        "Issue #60 weighted standards strategy changed.",
    )

    hybrid_producer, hybrid_evidence, hybrid_descriptor = issue54._hybrid_state(
        hybrid_workspace
    )
    hybrid_result = load_current_hybrid_grade_result(
        hybrid_workspace,
        issue54.issue52.CLASS_ID,
        issue54.issue52.STUDENT_ID,
        issue54.issue52.PERIOD,
        issue54.issue52.CALENDAR_REVISION,
    )
    _require(hybrid_result is not None, "Hybrid result is not selected.")
    assert hybrid_result is not None
    snapshot = _freeze_hybrid_snapshot(hybrid_workspace, hybrid_evidence)
    issue54.issue50._assert_unchanged(hybrid_producer)

    concord = _concord_state(concord_workspace)

    baseline = {
        "schema_version": "1",
        "conventional": {
            "workspace": conventional_workspace.name,
            "class_id": issue54.issue50.CLASS_ID,
            "student_id": issue54.issue50.STUDENT_ID,
            "school_year": issue54.issue50.PERIOD.school_year,
            "period_id": issue54.issue50.PERIOD.period_id,
            "calendar_revision": 1,
            "result": _selected_grade_baseline(conventional_result),
            "override": override,
            "evidence": conventional_descriptor,
        },
        "weighted": {
            "workspace": weighted_workspace.name,
            "class_id": weighted_target.class_id,
            "student_id": weighted_target.student_id,
            "school_year": weighted_target.target_period.school_year,
            "period_id": weighted_target.target_period.period_id,
            "calendar_revision": weighted_target.calendar_revision,
            "result": _selected_grade_baseline(weighted_result),
        },
        "profile": {
            "workspace": profile_workspace.name,
            "class_id": profile_state["class_id"],
            "student_id": profile_state["student_id"],
            "school_year": profile_state["school_year"],
            "period_id": profile_state["period_id"],
            "calendar_revision": profile_state["calendar_revision"],
            "result": _selected_grade_baseline(profile_result),
            "profile_result": profile_state["result"],
        },
        "hybrid": {
            "workspace": hybrid_workspace.name,
            "class_id": issue54.issue52.CLASS_ID,
            "student_id": issue54.issue52.STUDENT_ID,
            "school_year": issue54.issue52.PERIOD.school_year,
            "period_id": issue54.issue52.PERIOD.period_id,
            "calendar_revision": issue54.issue52.CALENDAR_REVISION,
            "result": _selected_grade_baseline(hybrid_result),
            "evidence": hybrid_descriptor,
            "snapshot": {
                "snapshot_id": SNAPSHOT_ID,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "payload_sha256": snapshot.snapshot.payload_sha256,
                "report_preview_sha256": snapshot.snapshot.report_preview_sha256,
            },
        },
        "concord": {
            "workspace": concord_workspace.name,
            **concord,
        },
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #60 installed cross-policy adversarial composition passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
