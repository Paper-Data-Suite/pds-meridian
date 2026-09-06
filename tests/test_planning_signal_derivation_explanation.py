from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_dir, class_metadata_path
from pds_core.routing_models import ModuleWorkRef

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.grade_item_membership_storage as membership_storage
import meridian.grouping_signal_policy_storage as grouping_policy_storage
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
from meridian.academic_period_proficiency_storage import (
    academic_period_proficiency_result_revision_path,
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
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.grouping_signal_policy_storage import (
    grouping_signal_policy_revision_path,
    write_grouping_signal_policy_revision,
)
from meridian.planning_signal_derivation_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
    PlanningSignalDerivationTraceTarget,
    explain_planning_signal_derivation,
    planning_signal_derivation_explanation_to_json_bytes,
    render_planning_signal_derivation_explanation_text,
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
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STANDARD_ID = "urn:state:ELA/9-10:RL.1?edition=2026"
WORK = ModuleWorkRef("quillan", CLASS_ID, "essay_1")
NOW = datetime(2026, 9, 4, 15, tzinfo=UTC)


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
        rationale="Course scale.",
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
        rationale="Map producer rubric levels to course proficiency.",
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
        rationale="Temporary instructional grouping context.",
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
        rationale="Use this evidence.",
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
        rationale="Teacher confirmed this Standard association.",
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
    monkeypatch: pytest.MonkeyPatch,
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

    monkeypatch.setattr(
        membership_storage,
        "validate_grade_item_membership_dependencies",
        lambda *args, **kwargs: object(),
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
    monkeypatch: pytest.MonkeyPatch,
    scale: ProficiencyScale,
    profile: StoredNativeValueMappingProfile,
    grade_item: GradeItemAggregationBasis,
    membership: AcademicPeriodProficiencyMembershipBasis,
) -> StoredStandardProficiencyResult:
    source = _source()
    monkeypatch.setattr(
        eligibility_storage,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: object(),
    )
    eligibility = eligibility_storage.write_evidence_eligibility_revision(
        root,
        _eligibility(source, membership.membership_sha256),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored

    monkeypatch.setattr(
        association_storage,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: object(),
    )
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
):
    child_snapshot = child.snapshot
    status = child_snapshot.outcome.status
    entry = AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item,
        memberships=(membership,),
        status=status,
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


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "workspace"
    _core_workspace(root)
    scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    profile = write_mapping_profile_revision(
        root,
        _mapping_profile(scale),
    ).stored
    write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(scale),
    )
    period_policy = write_academic_period_proficiency_policy_revision(
        root,
        _period_policy(scale),
    ).stored.policy
    grade_item, membership = _grade_item_and_membership(root, monkeypatch)
    calculated_child = _write_calculated_grade_item_result(
        root,
        monkeypatch,
        scale,
        profile,
        grade_item,
        membership,
    )
    insufficient_child = _write_insufficient_grade_item_result(
        root,
        scale,
        grade_item,
    )
    student_1_rev1 = _write_period_result(
        root,
        scale,
        grade_item,
        membership,
        calculated_child,
        student_id="student_1",
        result_revision=1,
    )
    student_2_rev1 = _write_period_result(
        root,
        scale,
        grade_item,
        membership,
        insufficient_child,
        student_id="student_2",
        result_revision=1,
    )

    policy_candidate = _grouping_policy(scale, period_policy)
    monkeypatch.setattr(
        grouping_policy_storage,
        "validate_grouping_signal_policy_dependencies",
        lambda *args, **kwargs: object(),
    )
    grouping_policy = write_grouping_signal_policy_revision(
        root,
        policy_candidate,
    ).stored
    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_3", "student_1", "student_2"),
    )
    snapshot = derive_grouping_signal_snapshot(
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
    derivation = write_grouping_signal_derivation(root, snapshot).stored

    _write_period_result(
        root,
        scale,
        grade_item,
        membership,
        calculated_child,
        student_id="student_1",
        result_revision=2,
    )
    select_academic_period_proficiency_result_revision(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        "student_1",
        STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )
    select_academic_period_proficiency_result_revision(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        "student_2",
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    return root, derivation


def _target(derivation_id: str) -> PlanningSignalDerivationTraceTarget:
    return PlanningSignalDerivationTraceTarget(
        class_id=CLASS_ID,
        derivation_id=derivation_id,
    )


def test_target_requires_exact_content_addressed_derivation_id() -> None:
    with pytest.raises(ExplanationTraceTargetError):
        _target("latest")
    with pytest.raises(ExplanationTraceTargetError):
        _target("gsd_" + "A" * 64)


def test_missing_exact_derivation_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(ExplanationTraceNotFoundError):
        explain_planning_signal_derivation(
            tmp_path,
            _target("gsd_" + "0" * 64),
        )


def test_exact_derivation_projects_policy_roster_and_band_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    explanation = explain_planning_signal_derivation(
        root,
        _target(derivation.snapshot.derivation_id),
    )

    assert explanation.derivation_sha256 == derivation.derivation_sha256
    assert explanation.policy.policy_id == "reading_planning_signal"
    assert explanation.policy.target_period.label == "Marking Period 1"
    assert explanation.policy.band_count == 3
    assert tuple(
        (item.band, item.minimum_scale_position, item.maximum_scale_position)
        for item in explanation.policy.band_definitions
    ) == ((1, 1, 1), (2, 2, 3), (3, 4, 4))
    assert explanation.roster.student_ids == (
        "student_1",
        "student_2",
        "student_3",
    )

    rows = {item.student_id: item for item in explanation.students}
    calculated = rows["student_1"]
    assert calculated.source_state == "calculated"
    assert calculated.disposition == "contributing"
    assert calculated.proficiency_level_id == "proficient"
    assert calculated.scale_position == 3
    assert calculated.band == 2
    assert calculated.matching_band_definition is not None
    assert calculated.matching_band_definition.minimum_scale_position == 2
    assert calculated.matching_band_definition.maximum_scale_position == 3

    insufficient = rows["student_2"]
    assert insufficient.source_state == "insufficient_evidence"
    assert insufficient.band is None
    assert insufficient.noncontribution_reason == "insufficient_evidence"
    assert insufficient.policy_handling == "noncontributing"

    missing = rows["student_3"]
    assert missing.source_state == "missing"
    assert missing.source_result is None
    assert missing.band is None
    assert missing.noncontribution_reason == "missing_result"
    assert missing.policy_handling == "noncontributing"


def test_nested_academic_period_trace_keeps_exact_historical_source_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    explanation = explain_planning_signal_derivation(
        root,
        _target(derivation.snapshot.derivation_id),
    )
    row = next(item for item in explanation.students if item.student_id == "student_1")
    nested = row.nested_academic_period_explanation
    assert row.source_result is not None
    assert row.source_result.result_revision == 1
    assert nested is not None
    assert nested.result_revision == 1
    assert nested.selection_state == "historical"
    assert nested.current_result_revision == 2


def test_missing_exact_policy_dependency_is_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    reference = derivation.snapshot.policy_reference
    path = grouping_signal_policy_revision_path(
        root,
        reference.class_id,
        reference.policy_id,
        reference.policy_revision,
    )
    path.unlink()
    Path(str(path) + ".sha256").unlink()

    with pytest.raises(ExplanationTraceIntegrityError, match="#37"):
        explain_planning_signal_derivation(
            root,
            _target(derivation.snapshot.derivation_id),
        )


def test_missing_exact_source_result_is_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    source = next(
        item.source_result
        for item in derivation.snapshot.student_derivations
        if item.student_id == "student_1"
    )
    assert source is not None
    path = academic_period_proficiency_result_revision_path(
        root,
        source.class_id,
        source.school_year,
        source.period_id,
        source.student_id,
        source.standard_id,
        source.result_revision,
    )
    path.unlink()
    Path(str(path) + ".sha256").unlink()

    with pytest.raises(ExplanationTraceIntegrityError, match="#35"):
        explain_planning_signal_derivation(
            root,
            _target(derivation.snapshot.derivation_id),
        )


def test_json_and_text_make_band_mapping_and_absence_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    explanation = explain_planning_signal_derivation(
        root,
        _target(derivation.snapshot.derivation_id),
    )
    payload = planning_signal_derivation_explanation_to_json_bytes(explanation)
    text = render_planning_signal_derivation_explanation_text(explanation)

    assert payload.endswith(b"\n")
    assert b'"noncontribution_reason": "missing_result"' in payload
    assert b'"result_revision": 1' in payload
    assert (
        "level=proficient -> scale_position=3 -> band_range=2-3 -> band=2"
        in text
    )
    assert "band: none reason=missing_result policy_handling=noncontributing" in text
    assert "#35_drill_down: revision=1 selection_state=historical" in text
