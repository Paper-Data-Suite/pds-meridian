from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routes import class_dir
from pds_core.routing_models import ModuleWorkRef

import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.grade_item_membership_storage as membership_storage
import meridian.standards_evidence_storage as association_storage
from meridian.evidence import NativeScale, NativeScaleLevel
from meridian.evidence_eligibility import (
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_source_key,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
    grade_item_proficiency_explanation_to_json_bytes,
    render_grade_item_proficiency_explanation_text,
)
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
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
)
from meridian.standards_proficiency_storage import (
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "urn:state:ELA/9-10:RL.1?edition=2026"
SCHOOL_YEAR = "2026-2027"
WORK = ModuleWorkRef("quillan", CLASS_ID, "essay_1")
NOW = datetime(2026, 9, 4, 13, tzinfo=UTC)


def _source(item_id: str, publication_digit: str) -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id="pub_" + publication_digit * 32,
        cache_key=(str(int(publication_digit) + 1) * 64),
        snapshot_digest=(str(int(publication_digit) + 2) * 64),
        item_id=item_id,
    )


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


def _profile(target: ProficiencyScale) -> NativeValueMappingProfile:
    native = NativeScale(
        "rubric_024",
        (
            NativeScaleLevel(0, "Low", "Limited"),
            NativeScaleLevel(2, "Middle", "Developing"),
            NativeScaleLevel(4, "High", "Strong"),
        ),
    )
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
        native_scale=native,
        points_possible=None,
        mapping_rules=(
            ScaledLevelMappingRule(0, "beginning"),
            ScaledLevelMappingRule(2, "proficient"),
            ScaledLevelMappingRule(4, "advanced"),
        ),
        actor=MappingActor("teacher", "teacher_local"),
        rationale="Map Quillan rubric levels to course proficiency.",
        revised_at=NOW,
    )


def _policy(target: ProficiencyScale) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course policy",
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
        policy=EvidenceEligibilityPolicyReference(
            "teacher_local_eligibility",
            "1",
        ),
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


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, EvidenceSourceReference, EvidenceSourceReference, Path]:
    root = tmp_path / "workspace"
    class_dir(root, CLASS_ID).mkdir(parents=True)

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
                period=AcademicPeriodRef(
                    school_year=SCHOOL_YEAR,
                    period_id="mp1",
                ),
                calendar_revision=1,
            ),
            actor_id="teacher_local",
            rationale="This essay belongs to the Grade Item.",
            decided_at=NOW,
        ),
    ).stored

    performance_source = _source("essay_standard_rating", "1")
    excluded_source = _source("essay_unmapped_rating", "4")

    monkeypatch.setattr(
        eligibility_storage,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: object(),
    )
    performance_eligibility = eligibility_storage.write_evidence_eligibility_revision(
        root,
        _eligibility(performance_source, membership.decision_sha256),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored
    excluded_eligibility = eligibility_storage.write_evidence_eligibility_revision(
        root,
        _eligibility(excluded_source, membership.decision_sha256),
        authorized_snapshot=object(),  # type: ignore[arg-type]
    ).stored

    monkeypatch.setattr(
        association_storage,
        "validate_standard_evidence_association_dependencies",
        lambda *args, **kwargs: object(),
    )
    performance_association = (
        association_storage.write_standard_evidence_association_revision(
            root,
            _association(performance_source),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        ).stored
    )
    excluded_association = (
        association_storage.write_standard_evidence_association_revision(
            root,
            _association(excluded_source),
            authorized_snapshot=object(),  # type: ignore[arg-type]
        ).stored
    )

    scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    profile = write_mapping_profile_revision(root, _profile(scale)).stored
    policy = write_standard_proficiency_policy_revision(
        root,
        _policy(scale),
    ).stored.policy

    membership_ref = AggregationDecisionReference(
        "membership",
        1,
        membership.decision_sha256,
    )
    entries = (
        StandardAggregationInputEntry(
            source=performance_source,
            result_kind="overall_standard_rating",
            target_kind="standard",
            status="performance",
            exclusion_reason=None,
            membership_reference=membership_ref,
            eligibility_reference=AggregationDecisionReference(
                "eligibility",
                1,
                performance_eligibility.decision_sha256,
            ),
            attempt_selection_reference=None,
            reassessment_reference=None,
            association_reference=performance_association.reference,
            mapping_profile_reference=profile.reference,
            mapping_status="mapped",
            proficiency_level_id="proficient",
            native_state=None,
        ),
        StandardAggregationInputEntry(
            source=excluded_source,
            result_kind="overall_standard_rating",
            target_kind="standard",
            status="excluded",
            exclusion_reason="mapping_not_supplied",
            membership_reference=membership_ref,
            eligibility_reference=AggregationDecisionReference(
                "eligibility",
                1,
                excluded_eligibility.decision_sha256,
            ),
            attempt_selection_reference=None,
            reassessment_reference=None,
            association_reference=excluded_association.reference,
            mapping_profile_reference=None,
            mapping_status=None,
            proficiency_level_id=None,
            native_state=None,
        ),
    )
    ordered_entries = tuple(
        sorted(entries, key=lambda item: evidence_source_key(item.source))
    )
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            grade_item.revision_sha256,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        entries=ordered_entries,
    )
    outcome = calculate_standard_proficiency(inputs, policy, scale)
    result = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    write_standard_proficiency_result_revision(root, result)

    return root, performance_source, excluded_source, excluded_eligibility.path


def _target() -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        selection="revision",
        result_revision=1,
    )


def test_real_exact_evidence_chain_resolves_applicable_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, performance_source, excluded_source, _ = _prepared(tmp_path, monkeypatch)

    explanation = explain_grade_item_proficiency(root, _target())
    rows = {row.source.item_id: row for row in explanation.evidence}

    performance = rows[performance_source.item_id]
    assert performance.aggregation_status == "performance"
    assert performance.proficiency_level_id == "proficient"
    assert [stage.status for stage in performance.stages] == [
        "verified",
        "verified",
        "not_applicable",
        "not_applicable",
        "verified",
        "verified",
    ]

    excluded = rows[excluded_source.item_id]
    assert excluded.aggregation_status == "excluded"
    assert excluded.exclusion_reason == "mapping_not_supplied"
    mapping = {stage.name: stage for stage in excluded.stages}["mapping_profile"]
    assert mapping.status == "not_supplied"

    assert explanation.calculation.status == "calculated"
    assert explanation.calculation.proficiency_level_id == "proficient"
    assert explanation.calculation.performance_observation_count == 1
    assert explanation.calculation.excluded_count == 1


def test_exact_evidence_dependency_digest_tamper_fails_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, excluded_source, eligibility_path = _prepared(tmp_path, monkeypatch)
    digest_path = Path(str(eligibility_path) + ".sha256")
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")

    with pytest.raises(ExplanationTraceIntegrityError, match="eligibility"):
        explain_grade_item_proficiency(root, _target())

    assert excluded_source.item_id == "essay_unmapped_rating"


def test_renderers_show_what_happened_and_why(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, _ = _prepared(tmp_path, monkeypatch)
    explanation = explain_grade_item_proficiency(root, _target())

    payload = grade_item_proficiency_explanation_to_json_bytes(explanation)
    text = render_grade_item_proficiency_explanation_text(explanation)

    assert b'"aggregation_status": "performance"' in payload
    assert b'"exclusion_reason": "mapping_not_supplied"' in payload
    assert b'"name": "eligibility"' in payload
    assert b'"status": "verified"' in payload

    assert "aggregation=performance" in text
    assert "mapping=mapped" in text
    assert "mapping_not_supplied" in text
    assert "standard_association: verified" in text
    assert "mapping_profile: not_supplied" in text
