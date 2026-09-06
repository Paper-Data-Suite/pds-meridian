from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import patch

from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.academic_work_registration_storage import (
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.grouping_signal_storage import write_grouping_signal
from pds_core.grouping_signals import GroupingSignalSet, grouping_signal_set_to_dict
from pds_core.routes import class_dir, class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    write_workspace_standards_library,
)

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.grade_item_membership_storage as membership_storage
import meridian.standards_evidence_storage as association_storage
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    academic_period_proficiency_explanation_to_json_bytes,
    explain_academic_period_proficiency,
    render_academic_period_proficiency_explanation_text,
)
from meridian.academic_period_proficiency_storage import (
    StoredAcademicPeriodProficiencyResult,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence import NativeScale, NativeScaleLevel
from meridian.evidence_eligibility import (
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_proficiency_explanation import (
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
    grade_item_proficiency_explanation_to_json_bytes,
    render_grade_item_proficiency_explanation_text,
)
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.grouping_signal_derivation import (
    GroupingSignalResolvedStudentResult,
    derive_grouping_signal_snapshot,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    write_grouping_signal_derivation,
)
from meridian.grouping_signal_export import build_grouping_signal_export_candidate
from meridian.grouping_signal_export_receipt import (
    create_grouping_signal_export_receipt,
)
from meridian.grouping_signal_export_storage import (
    write_grouping_signal_export_receipt,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.grouping_signal_policy_storage import (
    write_grouping_signal_policy_revision,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    build_grouping_signal_preview_snapshot,
)
from meridian.grouping_signal_preview_storage import write_grouping_signal_preview
from meridian.grouping_signal_review import create_grouping_signal_review_decision
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
    write_grouping_signal_review_revision,
)
from meridian.planning_signal_derivation_explanation import (
    PlanningSignalDerivationTraceTarget,
    explain_planning_signal_derivation,
    planning_signal_derivation_explanation_to_json_bytes,
    render_planning_signal_derivation_explanation_text,
)
from meridian.planning_signal_export_explanation import (
    PlanningSignalExportTraceTarget,
    explain_planning_signal_export,
    planning_signal_export_explanation_to_json_bytes,
    render_planning_signal_export_explanation_text,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    NativeValueSourceSignature,
    ProficiencyLevel,
    ProficiencyScale,
    ScaledLevelMappingRule,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import (
    StoredNativeValueMappingProfile,
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    StandardAggregationInputEntry,
    StandardAggregationInputs,
    StandardEvidenceActor,
    StandardEvidenceAssociationDecision,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
    standard_proficiency_result_reference,
)
from meridian.standards_proficiency_storage import (
    StoredStandardProficiencyResult,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STANDARD_ID = "urn:state:ELA/9-10:RL.1?edition=2026"
WORK = ModuleWorkRef("quillan", CLASS_ID, "essay_1")
SIGNAL_SET_ID = "reading_mp1_trace_smoke"
TARGETS_FILE = "issue42_trace_targets.json"
NOW = datetime(2026, 9, 5, 18, tzinfo=UTC)


def _tree_state(root: Path) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        values.append((relative, digest))
    return tuple(sorted(values))


def _scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale="Synthetic installed-wheel scale.",
        revised_at=NOW,
    )


def _mapping_profile(target: ProficiencyScale) -> NativeValueMappingProfile:
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=target.scale_id,
        profile_id="quillan_024",
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(target),
        source_signature=NativeValueSourceSignature(
            producer_module_id="quillan",
            publication_kind="academic_result_set",
            manifest_contract_version="quillan_academic_result_manifest_v1",
            producer_contract_version="quillan_academic_work_v1",
            projection_id="quillan.academic_result",
            projection_contract_version="1",
            producer_reader_distribution="quillan",
            producer_reader_version="0.10.0",
            result_kind="overall_standard_rating",
            target_kind="standard",
        ),
        mapping_kind="exact_native_scale",
        native_scale=NativeScale(
            "rubric_024",
            (
                NativeScaleLevel(0, "Low", "Limited"),
                NativeScaleLevel(2, "Middle", "Developing"),
                NativeScaleLevel(4, "High", "Strong"),
            ),
        ),
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "beginning"),
            ScaledLevelMappingRule(2, "proficient"),
            ScaledLevelMappingRule(4, "advanced"),
        ),
        actor=MappingActor("teacher", "teacher_local"),
        rationale="Synthetic installed-wheel mapping.",
        revised_at=NOW,
    )


def _grade_item_policy(
    target: ProficiencyScale,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="grade_item_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Grade Item policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale="Use the highest mapped observation.",
        revised_at=NOW,
    )


def _period_policy(
    target: ProficiencyScale,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Academic Period policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale="Aggregate Grade Item proficiency for planning.",
        revised_at=NOW,
    )


def _grouping_policy(
    target: ProficiencyScale,
    source_policy: AcademicPeriodProficiencyAggregationPolicy,
) -> GroupingSignalDerivationPolicy:
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="reading_planning_signal",
        policy_revision=1,
        supersedes_revision=None,
        title="Reading planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=AcademicPeriodProficiencyTarget(
                AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
                1,
            ),
            standard_id=STANDARD_ID,
            source_policy=(
                academic_period_proficiency_aggregation_policy_reference(
                    source_policy
                )
            ),
            target_scale=proficiency_scale_reference(target),
        ),
        dimension_id="reading_planning",
        band_count=3,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale="Temporary synthetic instructional grouping context.",
        revised_at=NOW,
    )


def _source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id="pub_" + "1" * 32,
        cache_key="2" * 64,
        snapshot_digest="3" * 64,
        item_id="essay_standard_rating",
    )


def _eligibility(
    source: EvidenceSourceReference,
    membership_sha256: str,
) -> EvidenceEligibilityDecision:
    return EvidenceEligibilityDecision(
        schema_version="1",
        record_type="meridian_evidence_eligibility_decision",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        membership_revision=1,
        membership_revision_sha256=membership_sha256,
        eligibility_revision=1,
        supersedes_revision=None,
        disposition="included",
        actor=EvidenceDecisionActor("teacher", "teacher_local"),
        policy=EvidenceEligibilityPolicyReference("teacher_local", "1"),
        reason_codes=(),
        rationale="Use this synthetic evidence.",
        source_state=EvidenceSourceStateObservation(
            state="current",
            head_publication_id=source.publication_id,
            successor_publication_id=None,
            withdrawn_at=None,
        ),
        decided_at=NOW,
    )


def _association(
    source: EvidenceSourceReference,
) -> StandardEvidenceAssociationDecision:
    return StandardEvidenceAssociationDecision(
        schema_version="1",
        record_type="meridian_standard_evidence_association",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        standard_id=STANDARD_ID,
        association_revision=1,
        supersedes_revision=None,
        disposition="associated",
        basis="explicit",
        actor=StandardEvidenceActor("teacher", "teacher_local"),
        rationale="Synthetic Standard association.",
        decided_at=NOW,
    )


def _core_workspace(root: Path) -> None:
    class_dir(root, CLASS_ID).mkdir(parents=True)
    write_class_metadata(
        class_metadata_path(root, CLASS_ID),
        ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    module_work_dir(root, WORK).mkdir(parents=True, exist_ok=True)
    write_academic_work_registration(
        root,
        AcademicWorkRegistration(
            schema_version="1",
            record_type="academic_work_registration",
            work=WORK,
            registration_revision=1,
            producer_contract_version="quillan_academic_work_v1",
            title="Synthetic essay",
            work_kind="essay",
            academic_intent="summative",
            lifecycle="active",
            created_at=NOW,
            updated_at=NOW,
            source_records=(),
        ),
        expected_current_revision=None,
    )
    write_workspace_standards_library(
        root,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_ID,
                    code="RL.1",
                    source="SYNTHETIC-2026",
                    short_name="Textual evidence",
                    description="Synthetic standard for installed trace smoke.",
                    subject="ELA",
                    grade_band="9-10",
                    active=True,
                    available_modules=("meridian",),
                ),
            )
        ),
    )
    write_academic_period_calendar(
        root,
        AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=SCHOOL_YEAR,
            calendar_revision=1,
            created_at=NOW,
            updated_at=NOW,
            periods=(
                AcademicPeriod(
                    period_id=PERIOD_ID,
                    period_type="marking_period",
                    label="Marking Period 1",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 8),
                    parent_period_id=None,
                    sequence=1,
                    lifecycle="active",
                ),
            ),
        ),
        expected_current_revision=None,
    )


def _grade_item_and_membership(
    root: Path,
) -> tuple[GradeItemAggregationBasis, AcademicPeriodProficiencyMembershipBasis]:
    grade_item = write_grade_item_revision(
        root,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Unit 1 Assessment",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    basis = GradeItemAggregationBasis(
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
        grade_item.revision_sha256,
    )

    membership = membership_storage.write_grade_item_membership_revision(
        root,
        GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=1,
            grade_item_revision_sha256=grade_item.revision_sha256,
            work_reference=GradeItemWorkReference(
                work=WORK,
                registration_revision=1,
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
                calendar_revision=1,
            ),
            actor_id="teacher_local",
            rationale="This work belongs to the Grade Item.",
            decided_at=NOW,
        ),
    ).stored

    period_membership = AcademicPeriodProficiencyMembershipBasis(
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        grade_item_revision_sha256=grade_item.revision_sha256,
        work_reference=membership.decision.work_reference,
        membership_revision=1,
        membership_sha256=membership.decision_sha256,
        academic_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
            1,
        ),
    )
    return basis, period_membership


def _write_calculated_grade_item_result(
    root: Path,
    scale: ProficiencyScale,
    profile: StoredNativeValueMappingProfile,
    grade_item: GradeItemAggregationBasis,
    membership: AcademicPeriodProficiencyMembershipBasis,
) -> StoredStandardProficiencyResult:
    source = _source()
    with patch.object(
        eligibility_storage,
        "validate_evidence_eligibility_dependencies",
        return_value=object(),
    ):
        eligibility = eligibility_storage.write_evidence_eligibility_revision(
            root,
            _eligibility(source, membership.membership_sha256),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        ).stored

    with patch.object(
        association_storage,
        "validate_standard_evidence_association_dependencies",
        return_value=object(),
    ):
        association = association_storage.write_standard_evidence_association_revision(
            root,
            _association(source),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        ).stored

    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=grade_item,
        student_id="student_1",
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        entries=(
            StandardAggregationInputEntry(
                source=source,
                result_kind="overall_standard_rating",
                target_kind="standard",
                status="performance",
                exclusion_reason=None,
                membership_reference=AggregationDecisionReference(
                    "membership",
                    1,
                    membership.membership_sha256,
                ),
                eligibility_reference=AggregationDecisionReference(
                    "eligibility",
                    1,
                    eligibility.decision_sha256,
                ),
                attempt_selection_reference=None,
                reassessment_reference=None,
                association_reference=association.reference,
                mapping_profile_reference=profile.reference,
                mapping_status="mapped",
                proficiency_level_id="proficient",
                native_state=None,
            ),
        ),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        _grade_item_policy(scale),
        scale,
    )
    snapshot = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    return write_standard_proficiency_result_revision(root, snapshot).stored


def _write_insufficient_grade_item_result(
    root: Path,
    scale: ProficiencyScale,
    grade_item: GradeItemAggregationBasis,
) -> StoredStandardProficiencyResult:
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=grade_item,
        student_id="student_2",
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        entries=(),
    )
    outcome = calculate_standard_proficiency(
        inputs,
        _grade_item_policy(scale),
        scale,
    )
    snapshot = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    return write_standard_proficiency_result_revision(root, snapshot).stored


def _write_period_result(
    root: Path,
    scale: ProficiencyScale,
    grade_item: GradeItemAggregationBasis,
    membership: AcademicPeriodProficiencyMembershipBasis,
    child: StoredStandardProficiencyResult,
    *,
    student_id: str,
    result_revision: int,
) -> StoredAcademicPeriodProficiencyResult:
    child_snapshot = child.snapshot
    entry = AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item,
        memberships=(membership,),
        status=child_snapshot.outcome.status,
        period_scope_mismatch_reason=None,
        result_reference=standard_proficiency_result_reference(child_snapshot),
        result_algorithm_version=child_snapshot.algorithm_version,
        result_calculation_fingerprint=child_snapshot.calculation_fingerprint,
        result_status=child_snapshot.outcome.status,
        proficiency_level_id=child_snapshot.outcome.proficiency_level_id,
        result_insufficiency_reasons=child_snapshot.outcome.insufficiency_reasons,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
            1,
        ),
        student_id=student_id,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        entries=(entry,),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        _period_policy(scale),
        scale,
    )
    snapshot = create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=result_revision,
        calculated_at=NOW + timedelta(minutes=result_revision - 1),
    )
    return write_academic_period_proficiency_result_revision(root, snapshot).stored


def _assert_core_signal_is_minimal(signal: GroupingSignalSet) -> None:
    payload = grouping_signal_set_to_dict(signal)
    assert set(payload) == {
        "schema_version",
        "record_type",
        "signal_set_id",
        "class_id",
        "created_at",
        "source",
        "dimensions",
        "student_bands",
    }
    source = cast(dict[str, object], payload["source"])
    assert set(source) == {
        "kind",
        "module_id",
        "snapshot_id",
        "snapshot_digest_algorithm",
        "snapshot_digest",
    }
    dimensions = cast(list[dict[str, object]], payload["dimensions"])
    assert all(set(item) == {"dimension_id", "band_count"} for item in dimensions)
    student_bands = cast(list[dict[str, object]], payload["student_bands"])
    assert all(
        set(item) == {"student_id", "dimension_id", "band"}
        for item in student_bands
    )


def _run_acceptance(root: Path) -> dict[str, str]:
    workspace = root / "workspace"
    _core_workspace(workspace)
    scale = write_proficiency_scale_revision(workspace, _scale()).stored.scale
    profile = write_mapping_profile_revision(
        workspace,
        _mapping_profile(scale),
    ).stored
    write_standard_proficiency_policy_revision(
        workspace,
        _grade_item_policy(scale),
    )
    period_policy = write_academic_period_proficiency_policy_revision(
        workspace,
        _period_policy(scale),
    ).stored.policy

    grade_item, membership = _grade_item_and_membership(workspace)
    calculated_child = _write_calculated_grade_item_result(
        workspace,
        scale,
        profile,
        grade_item,
        membership,
    )
    insufficient_child = _write_insufficient_grade_item_result(
        workspace,
        scale,
        grade_item,
    )
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_2",
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    student_1_rev1 = _write_period_result(
        workspace,
        scale,
        grade_item,
        membership,
        calculated_child,
        student_id="student_1",
        result_revision=1,
    )
    student_2_rev1 = _write_period_result(
        workspace,
        scale,
        grade_item,
        membership,
        insufficient_child,
        student_id="student_2",
        result_revision=1,
    )

    grouping_policy = write_grouping_signal_policy_revision(
        workspace,
        _grouping_policy(scale, period_policy),
    ).stored

    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_3", "student_1", "student_2"),
    )
    derivation_snapshot = derive_grouping_signal_snapshot(
        grouping_policy.policy,
        grouping_policy.reference,
        scale,
        roster,
        (
            GroupingSignalResolvedStudentResult(
                "student_1",
                student_1_rev1.snapshot,
            ),
            GroupingSignalResolvedStudentResult(
                "student_2",
                student_2_rev1.snapshot,
            ),
            GroupingSignalResolvedStudentResult("student_3", None),
        ),
    )
    derivation = write_grouping_signal_derivation(
        workspace,
        derivation_snapshot,
    ).stored

    preview_snapshot = build_grouping_signal_preview_snapshot(
        derivation.snapshot,
        grouping_policy.policy,
        scale,
        GroupingSignalPreviewCurrentness(
            "current",
            (),
            derivation.reference,
        ),
    )
    preview = write_grouping_signal_preview(workspace, preview_snapshot).stored
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )
    review_candidate = create_grouping_signal_review_decision(
        preview.snapshot,
        preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id="teacher_local",
        reviewed_at=NOW + timedelta(minutes=2),
    )
    review = write_grouping_signal_review_revision(
        workspace,
        review_candidate,
    ).stored
    select_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        1,
        expected_current_review_revision=None,
    )

    candidate = build_grouping_signal_export_candidate(
        derivation.snapshot,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW + timedelta(minutes=3),
    )
    core = write_grouping_signal(workspace, candidate).stored
    receipt_candidate = create_grouping_signal_export_receipt(
        derivation_reference=derivation.reference,
        preview_reference=preview.reference,
        review_reference=review.reference,
        signal=core.signal,
        core_signal_digest=core.digest,
    )
    write_grouping_signal_export_receipt(workspace, receipt_candidate)
    _assert_core_signal_is_minimal(core.signal)

    grade_item_rev2 = create_standard_proficiency_result_snapshot(
        calculated_child.snapshot.inputs,
        calculated_child.snapshot.outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=4),
    )
    write_standard_proficiency_result_revision(workspace, grade_item_rev2)
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        STANDARD_ID,
        2,
        expected_current_result_revision=1,
    )

    _write_period_result(
        workspace,
        scale,
        grade_item,
        membership,
        calculated_child,
        student_id="student_1",
        result_revision=2,
    )
    select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        "student_1",
        STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )
    select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        "student_2",
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    before_trace = _tree_state(workspace)

    grade = explain_grade_item_proficiency(
        workspace,
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            "student_1",
            STANDARD_ID,
            "revision",
            1,
        ),
    )
    assert grade.result_revision == 1
    assert grade.selection_state == "historical"
    assert grade.current_result_revision == 2
    assert grade.evidence[0].authorized_detail.status == "not_requested"
    grade_json = grade_item_proficiency_explanation_to_json_bytes(grade)
    assert grade_json == grade_item_proficiency_explanation_to_json_bytes(grade)
    grade_text = render_grade_item_proficiency_explanation_text(grade)
    assert grade_text == render_grade_item_proficiency_explanation_text(grade)
    assert b'"authorized_detail": {' in grade_json
    assert b'"status": "not_requested"' in grade_json

    period = explain_academic_period_proficiency(
        workspace,
        AcademicPeriodProficiencyTraceTarget(
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            "student_1",
            STANDARD_ID,
            "revision",
            1,
        ),
    )
    assert period.result_revision == 1
    assert period.selection_state == "historical"
    assert period.current_result_revision == 2
    period_row = period.grade_items[0]
    assert period_row.nested_grade_item_explanation is not None
    assert period_row.nested_grade_item_explanation.result_revision == 1
    period_json = academic_period_proficiency_explanation_to_json_bytes(period)
    assert period_json == academic_period_proficiency_explanation_to_json_bytes(
        period
    )
    period_text = render_academic_period_proficiency_explanation_text(period)
    assert period_text == render_academic_period_proficiency_explanation_text(period)

    planning = explain_planning_signal_derivation(
        workspace,
        PlanningSignalDerivationTraceTarget(
            CLASS_ID,
            derivation.snapshot.derivation_id,
        ),
    )
    planning_rows = {item.student_id: item for item in planning.students}
    contributor = planning_rows["student_1"]
    assert contributor.band == 2
    assert contributor.proficiency_level_id == "proficient"
    assert contributor.scale_position == 3
    assert contributor.nested_academic_period_explanation is not None
    assert contributor.nested_academic_period_explanation.result_revision == 1
    assert contributor.nested_academic_period_explanation.selection_state == (
        "historical"
    )
    assert planning_rows["student_2"].noncontribution_reason == (
        "insufficient_evidence"
    )
    assert planning_rows["student_3"].noncontribution_reason == "missing_result"
    planning_json = planning_signal_derivation_explanation_to_json_bytes(planning)
    assert planning_json == planning_signal_derivation_explanation_to_json_bytes(
        planning
    )
    planning_text = render_planning_signal_derivation_explanation_text(planning)
    assert planning_text == render_planning_signal_derivation_explanation_text(
        planning
    )

    exported = explain_planning_signal_export(
        workspace,
        PlanningSignalExportTraceTarget(CLASS_ID, SIGNAL_SET_ID),
    )
    exported_rows = {item.student_id: item for item in exported.students}
    assert exported_rows["student_1"].exported is True
    assert exported_rows["student_1"].core_band == 2
    assert exported_rows["student_1"].meridian_band == 2
    assert exported_rows["student_2"].exported is False
    assert exported_rows["student_2"].noncontribution_reason == (
        "insufficient_evidence"
    )
    assert exported_rows["student_3"].noncontribution_reason == "missing_result"
    export_json = planning_signal_export_explanation_to_json_bytes(exported)
    assert export_json == planning_signal_export_explanation_to_json_bytes(exported)
    export_text = render_planning_signal_export_explanation_text(exported)
    assert export_text == render_planning_signal_export_explanation_text(exported)

    after_trace = _tree_state(workspace)
    assert after_trace == before_trace

    return {
        "class_id": CLASS_ID,
        "grade_item_id": GRADE_ITEM_ID,
        "school_year": SCHOOL_YEAR,
        "period_id": PERIOD_ID,
        "standard_id": STANDARD_ID,
        "student_id": "student_1",
        "derivation_id": derivation.snapshot.derivation_id,
        "signal_set_id": SIGNAL_SET_ID,
    }


def main() -> None:
    for distribution in (
        "scoreform",
        "quillan",
        "concord",
        "portia",
        "vitrine",
        "paper_data_suite",
    ):
        assert importlib.util.find_spec(distribution) is None

    package_root = Path(sys.prefix).resolve()
    import meridian

    assert Path(meridian.__file__).resolve().is_relative_to(package_root)
    root = Path(".").resolve()
    targets = _run_acceptance(root)
    (root / TARGETS_FILE).write_text(
        json.dumps(targets, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    for distribution in (
        "scoreform",
        "quillan",
        "concord",
        "portia",
        "vitrine",
        "paper_data_suite",
    ):
        assert importlib.util.find_spec(distribution) is None

    print("Installed #42 explanation-trace API smoke passed.")


if __name__ == "__main__":
    main()
