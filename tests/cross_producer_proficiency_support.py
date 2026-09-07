"""Reusable mixed-producer proficiency acceptance support for Meridian issue #44."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from pds_core.academic_periods import AcademicPeriodRef

from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScale,
    NativeScaledValue,
)
from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_eligibility_decision_to_json_bytes,
)
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
    grade_item_membership_decision_to_json_bytes,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemWorkReference,
    grade_item_revision_to_json_bytes,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    MappingKind,
    MappingRule,
    NativeValueMappingProfile,
    PointRangeMappingRule,
    ProficiencyLevel,
    ProficiencyScale,
    ScaledLevelMappingRule,
    native_value_source_signature_from_item,
    proficiency_scale_reference,
)
from meridian.standards_evidence import (
    STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
    STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
    AggregationDecisionReference,
    StandardEvidenceActor,
    StandardEvidenceAssociationBasis,
    StandardEvidenceAssociationDecision,
    StandardEvidenceAssociationReference,
    standard_evidence_association_reference,
)
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)
from tests.cross_producer_workspace_support import (
    CLASS_ID,
    CONCORD_WORK,
    QUILLAN_WORK,
    SCOREFORM_WORK,
    CachedProjection,
)

GRADE_ITEM_ID = "cross_producer_proficiency"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "period_q1"
NOW = datetime(2026, 9, 6, 22, 0, tzinfo=UTC)
ACTOR_ID = "teacher_local"
ELIGIBILITY_POLICY_ID = "issue44_cross_producer"
ELIGIBILITY_POLICY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class RepresentativeProducerItems:
    """Exact projected values used across issue #44 acceptance scenarios."""

    scoreform_points: EvidenceItem
    quillan_overall: EvidenceItem
    concord_student: EvidenceItem
    concord_group_current: EvidenceItem


@dataclass(frozen=True, slots=True)
class RepresentativeMappingProfiles:
    """Explicit source-scoped mapping profiles for representative producer values."""

    scoreform_points: NativeValueMappingProfile
    quillan_overall: NativeValueMappingProfile
    concord_student: NativeValueMappingProfile
    concord_group_current: NativeValueMappingProfile


def cross_producer_grade_item() -> GradeItemRevision:
    """Return one Grade Item intended to hold evidence from all three producers."""
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Cross-producer proficiency",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )


def grade_item_sha256(item: GradeItemRevision | None = None) -> str:
    """Return the canonical digest used by downstream issue #44 decisions."""
    exact = item or cross_producer_grade_item()
    return hashlib.sha256(grade_item_revision_to_json_bytes(exact)).hexdigest()


def cross_producer_memberships(
    item: GradeItemRevision | None = None,
) -> tuple[GradeItemMembershipDecision, ...]:
    """Explicitly include ScoreForm, Quillan, and Concord in one Grade Item."""
    exact = item or cross_producer_grade_item()
    digest = grade_item_sha256(exact)
    assignment = GradeItemAcademicPeriodAssignment(
        period=AcademicPeriodRef(
            school_year=SCHOOL_YEAR,
            period_id=PERIOD_ID,
        ),
        calendar_revision=1,
    )
    works = (SCOREFORM_WORK, QUILLAN_WORK, CONCORD_WORK)
    return tuple(
        GradeItemMembershipDecision(
            schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
            record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=exact.grade_item_revision,
            grade_item_revision_sha256=digest,
            work_reference=GradeItemWorkReference(
                work=work,
                registration_revision=1,
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=assignment,
            actor_id=ACTOR_ID,
            rationale="Explicit issue #44 mixed-producer membership.",
            decided_at=NOW,
        )
        for work in works
    )


def membership_for_module(
    memberships: tuple[GradeItemMembershipDecision, ...],
    module_id: str,
) -> GradeItemMembershipDecision:
    """Return the exact membership decision for one producer module."""
    return next(
        decision
        for decision in memberships
        if decision.work_reference.work.module_id == module_id
    )


def membership_reference(
    decision: GradeItemMembershipDecision,
) -> AggregationDecisionReference:
    """Bind aggregation provenance to exact canonical membership bytes."""
    digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(decision)
    ).hexdigest()
    return AggregationDecisionReference(
        "membership",
        decision.membership_revision,
        digest,
    )


def cross_producer_scale() -> ProficiencyScale:
    """Return one teacher-owned Meridian target scale for issue #44."""
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="issue44_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Issue 44 proficiency",
        description="Synthetic criterion-referenced cross-producer target scale.",
        levels=(
            ProficiencyLevel(
                "beginning",
                1,
                "Beginning",
                "Initial evidence.",
            ),
            ProficiencyLevel(
                "developing",
                2,
                "Developing",
                "Partial evidence.",
            ),
            ProficiencyLevel(
                "proficient",
                3,
                "Proficient",
                "Meets the criterion.",
            ),
            ProficiencyLevel(
                "advanced",
                4,
                "Advanced",
                "Extends the criterion.",
            ),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Issue #44 acceptance scale.",
        revised_at=NOW,
    )


def _reference_codes(item: EvidenceItem, kind: str) -> tuple[str, ...]:
    return tuple(
        reference.identifier
        for reference in item.provenance.native.references
        if reference.kind == kind and reference.identifier is not None
    )


def representative_items(
    projected: dict[str, CachedProjection],
) -> RepresentativeProducerItems:
    """Select exact representative values without changing producer semantics."""
    scoreform = projected["scoreform"].inventory
    quillan = projected["quillan"].inventory
    concord = projected["concord"].inventory

    scoreform_points = next(
        item
        for item in scoreform.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "attempt_points"
        and isinstance(item.value, NativePointValue)
        and item.value.earned == 2
        and item.value.possible == 3
    )
    quillan_overall = next(
        item
        for item in quillan.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "overall_standard_rating"
        and SHARED_STANDARD_ID in item.target.standard_ids
        and isinstance(item.value, NativeScaledValue)
        and item.value.value == 2
    )
    concord_student = next(
        item
        for item in concord.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "standard_backed_score"
        and SHARED_STANDARD_ID in item.target.standard_ids
        and isinstance(item.value, NativeScaledValue)
        and item.value.value == 2
    )
    concord_group_current = next(
        item
        for item in concord.items
        if item.subject is None
        and item.result_kind == "local_score"
        and isinstance(item.value, NativeScaledValue)
        and _reference_codes(item, "score_current_state") == ("current",)
    )
    return RepresentativeProducerItems(
        scoreform_points=scoreform_points,
        quillan_overall=quillan_overall,
        concord_student=concord_student,
        concord_group_current=concord_group_current,
    )


def _mapping_profile(
    *,
    item: EvidenceItem,
    scale: ProficiencyScale,
    profile_id: str,
    mapping_kind: MappingKind,
    native_scale: NativeScale | None,
    points_possible: int | float | None,
    mapping_rules: tuple[MappingRule, ...],
) -> NativeValueMappingProfile:
    return NativeValueMappingProfile(
        schema_version=NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        record_type=NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id=scale.scale_id,
        profile_id=profile_id,
        profile_revision=1,
        supersedes_revision=None,
        target_scale=proficiency_scale_reference(scale),
        source_signature=native_value_source_signature_from_item(item),
        mapping_kind=mapping_kind,
        native_scale=native_scale,
        points_possible=points_possible,
        mapping_rules=mapping_rules,
        actor=MappingActor("teacher", ACTOR_ID),
        rationale="Explicit issue #44 source-scoped mapping.",
        revised_at=NOW,
    )


def representative_mapping_profiles(
    items: RepresentativeProducerItems,
    scale: ProficiencyScale,
) -> RepresentativeMappingProfiles:
    """Build mappings that deliberately bind exact signatures/scales/denominators."""
    scoreform_value = items.scoreform_points.value
    quillan_value = items.quillan_overall.value
    concord_value = items.concord_student.value
    group_value = items.concord_group_current.value
    assert isinstance(scoreform_value, NativePointValue)
    assert isinstance(quillan_value, NativeScaledValue)
    assert isinstance(concord_value, NativeScaledValue)
    assert isinstance(group_value, NativeScaledValue)

    return RepresentativeMappingProfiles(
        scoreform_points=_mapping_profile(
            item=items.scoreform_points,
            scale=scale,
            profile_id="scoreform_attempt_points",
            mapping_kind="raw_points",
            native_scale=None,
            points_possible=scoreform_value.possible,
            mapping_rules=(
                PointRangeMappingRule(
                    minimum_earned=scoreform_value.earned,
                    minimum_inclusive=True,
                    maximum_earned=scoreform_value.earned,
                    maximum_inclusive=True,
                    proficiency_level_id="proficient",
                ),
            ),
        ),
        quillan_overall=_mapping_profile(
            item=items.quillan_overall,
            scale=scale,
            profile_id="quillan_overall_rating",
            mapping_kind="exact_native_scale",
            native_scale=quillan_value.scale,
            points_possible=None,
            mapping_rules=(
                ScaledLevelMappingRule(
                    native_value=quillan_value.value,
                    proficiency_level_id="developing",
                ),
            ),
        ),
        concord_student=_mapping_profile(
            item=items.concord_student,
            scale=scale,
            profile_id="concord_student_score",
            mapping_kind="exact_native_scale",
            native_scale=concord_value.scale,
            points_possible=None,
            mapping_rules=(
                ScaledLevelMappingRule(
                    native_value=concord_value.value,
                    proficiency_level_id="proficient",
                ),
            ),
        ),
        concord_group_current=_mapping_profile(
            item=items.concord_group_current,
            scale=scale,
            profile_id="concord_group_score",
            mapping_kind="exact_native_scale",
            native_scale=group_value.scale,
            points_possible=None,
            mapping_rules=(
                ScaledLevelMappingRule(
                    native_value=group_value.value,
                    proficiency_level_id="advanced",
                ),
            ),
        ),
    )


def source_reference(
    projection: CachedProjection,
    item: EvidenceItem,
) -> EvidenceSourceReference:
    """Bind one projected item to the exact stored projection snapshot."""
    stored = projection.cached.stored
    cached_publication_id = stored.snapshot.source.publication.publication_id
    if item.provenance.publication_id != cached_publication_id:
        raise AssertionError("item and cached projection publication must agree")
    return EvidenceSourceReference(
        work=item.provenance.work,
        publication_id=item.provenance.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        item_id=item.item_id,
    )


def included_eligibility(
    source: EvidenceSourceReference,
    membership: GradeItemMembershipDecision,
) -> EvidenceEligibilityDecision:
    """Create one exact included eligibility decision against a current source."""
    membership_digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(membership)
    ).hexdigest()
    return EvidenceEligibilityDecision(
        schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
        record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        membership_revision=membership.membership_revision,
        membership_revision_sha256=membership_digest,
        eligibility_revision=1,
        supersedes_revision=None,
        disposition="included",
        actor=EvidenceDecisionActor("teacher", ACTOR_ID),
        policy=EvidenceEligibilityPolicyReference(
            ELIGIBILITY_POLICY_ID,
            ELIGIBILITY_POLICY_VERSION,
        ),
        reason_codes=(),
        rationale="Explicit issue #44 inclusion.",
        source_state=EvidenceSourceStateObservation(
            state="current",
            head_publication_id=source.publication_id,
            successor_publication_id=None,
            withdrawn_at=None,
        ),
        decided_at=NOW,
    )


def eligibility_reference(
    decision: EvidenceEligibilityDecision,
) -> AggregationDecisionReference:
    """Bind aggregation provenance to exact canonical eligibility bytes."""
    digest = hashlib.sha256(
        evidence_eligibility_decision_to_json_bytes(decision)
    ).hexdigest()
    return AggregationDecisionReference(
        "eligibility",
        decision.eligibility_revision,
        digest,
    )


def associated_standard(
    source: EvidenceSourceReference,
    *,
    basis: StandardEvidenceAssociationBasis = "explicit",
) -> StandardEvidenceAssociationDecision:
    """Associate one exact source to the shared Standard without inference."""
    return StandardEvidenceAssociationDecision(
        schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
        record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=source,
        standard_id=SHARED_STANDARD_ID,
        association_revision=1,
        supersedes_revision=None,
        disposition="associated",
        basis=basis,
        actor=StandardEvidenceActor("teacher", ACTOR_ID),
        rationale="Explicit issue #44 association.",
        decided_at=NOW,
    )


def association_reference(
    decision: StandardEvidenceAssociationDecision,
) -> StandardEvidenceAssociationReference:
    """Return the canonical association reference used by aggregation."""
    return standard_evidence_association_reference(decision)
