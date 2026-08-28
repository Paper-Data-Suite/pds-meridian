from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pds_core.routes import class_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingOutcome,
    NativeValueMappingProfileReference,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_evidence import (
    AggregationDecisionReference,
    GradeItemAggregationBasis,
    ResolvedStandardAggregationCandidate,
    StandardEvidenceAssociationReference,
    build_standard_aggregation_inputs,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    assess_standard_proficiency_result_freshness,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    get_current_standard_proficiency_policy_revision,
    get_current_standard_proficiency_result_revision,
    load_current_standard_proficiency_result,
    load_standard_proficiency_result_revision,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
NOW = datetime(2026, 8, 28, 2, 0, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", CLASS_ID, "synthetic_assessment")
DECISION_SHA = "a" * 64


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    class_dir(root, CLASS_ID).mkdir(parents=True)
    return root


def grade_item() -> GradeItemRevision:
    return GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Synthetic Unit 1 assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Synthetic criterion-referenced proficiency scale.",
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
                "Meets criterion.",
            ),
            ProficiencyLevel(
                "advanced",
                4,
                "Advanced",
                "Extends criterion.",
            ),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def policy(target: ProficiencyScale) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course proficiency policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def source(item_id: str) -> EvidenceSourceReference:
    return EvidenceSourceReference(
        WORK,
        "pub_" + "1" * 32,
        "2" * 64,
        "3" * 64,
        item_id,
    )


def candidate(
    target: ProficiencyScale,
    item_id: str,
    level_id: str,
) -> ResolvedStandardAggregationCandidate:
    exact_source = source(item_id)
    scale_reference = proficiency_scale_reference(target)
    return ResolvedStandardAggregationCandidate(
        source=exact_source,
        standard_id=STANDARD_ID,
        result_kind="question_correctness",
        target_kind="question",
        subject_kind="student",
        subject_student_id=STUDENT_ID,
        association_state="associated",
        eligibility_state="included",
        attempt_state="not_applicable",
        reassessment_state="not_applicable",
        membership_reference=AggregationDecisionReference(
            "membership",
            1,
            DECISION_SHA,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            DECISION_SHA,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=StandardEvidenceAssociationReference(
            CLASS_ID,
            GRADE_ITEM_ID,
            exact_source,
            STANDARD_ID,
            1,
            "8" * 64,
        ),
        mapping_outcome=NativeValueMappingOutcome(
            "mapped",
            NativeValueMappingProfileReference(
                CLASS_ID,
                target.scale_id,
                "synthetic_mapping_profile",
                1,
                "5" * 64,
            ),
            scale_reference,
            proficiency_level_id=level_id,
        ),
    )


def persisted_dependencies(
    root: Path,
) -> tuple[
    GradeItemAggregationBasis,
    ProficiencyScale,
    StandardProficiencyCalculationPolicy,
]:
    stored_item = write_grade_item_revision(root, grade_item()).stored
    stored_scale = write_proficiency_scale_revision(root, scale()).stored.scale
    stored_policy = write_standard_proficiency_policy_revision(
        root,
        policy(stored_scale),
    ).stored.policy
    selected = select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        stored_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected.disposition == "created"
    assert (
        get_current_standard_proficiency_policy_revision(
            root,
            CLASS_ID,
            stored_policy.policy_id,
        )
        == 1
    )
    return (
        GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            stored_item.revision_sha256,
        ),
        stored_scale,
        stored_policy,
    )


def test_full_grade_item_standard_proficiency_workflow_is_reproducible(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    basis, target, exact_policy = persisted_dependencies(root)
    target_reference = proficiency_scale_reference(target)
    first = candidate(target, "item_1", "developing")
    second = candidate(target, "item_2", "proficient")

    exact_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        target_reference,
        (second, first),
    )
    assert tuple(entry.status for entry in exact_inputs.entries) == (
        "performance",
        "performance",
    )

    outcome = calculate_standard_proficiency(
        exact_inputs,
        exact_policy,
        target,
    )
    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.performance_observation_count == 2

    snapshot = create_standard_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    written = write_standard_proficiency_result_revision(root, snapshot)
    assert written.disposition == "created"
    assert (
        get_current_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
        )
        is None
    )

    selected = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"

    current = load_current_standard_proficiency_result(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    assert current is not None
    assert current.snapshot == snapshot

    reproduced = calculate_standard_proficiency(
        current.snapshot.inputs,
        exact_policy,
        target,
    )
    assert reproduced == current.snapshot.outcome

    freshness = assess_standard_proficiency_result_freshness(
        current.snapshot,
        exact_inputs,
        outcome.policy_reference,
        target_reference,
        outcome.algorithm_version,
    )
    assert freshness.status == "current"
    assert freshness.reasons == ()

    historical_bytes = current.content
    changed_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        target_reference,
        (
            first,
            second,
            candidate(target, "item_3", "advanced"),
        ),
    )
    stale = assess_standard_proficiency_result_freshness(
        current.snapshot,
        changed_inputs,
        outcome.policy_reference,
        target_reference,
        outcome.algorithm_version,
    )
    assert stale.status == "stale"
    assert stale.reasons == ("inputs_changed",)
    assert (
        load_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        ).content
        == historical_bytes
    )


def test_zero_performance_persists_as_insufficient_not_lowest(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    basis, target, exact_policy = persisted_dependencies(root)
    target_reference = proficiency_scale_reference(target)
    exact_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        target_reference,
        (),
    )

    outcome = calculate_standard_proficiency(
        exact_inputs,
        exact_policy,
        target,
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.proficiency_level_id is None
    assert tuple(reason.kind for reason in outcome.insufficiency_reasons) == (
        "no_performance_evidence",
    )

    snapshot = create_standard_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    stored = write_standard_proficiency_result_revision(root, snapshot).stored
    reloaded = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert reloaded.snapshot == snapshot
    assert reloaded.result_sha256 == stored.result_sha256
    assert reloaded.snapshot.outcome.proficiency_level_id is None
