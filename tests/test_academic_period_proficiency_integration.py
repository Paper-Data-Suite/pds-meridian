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
from pds_core.academic_work_registration_storage import (
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    AcademicPeriodProficiencyValidationError,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_aggregation_inputs_sha256,
    academic_period_proficiency_calculation_fingerprint,
    academic_period_proficiency_membership_basis_from_decision,
    assess_academic_period_proficiency_result_freshness,
    build_academic_period_proficiency_aggregation_inputs,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    get_current_academic_period_proficiency_result_revision,
    load_current_academic_period_proficiency_result,
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_membership_storage import (
    load_grade_item_membership_revision,
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
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
    StandardProficiencyResultSnapshot,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    load_standard_proficiency_result_revision,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
STUDENT_ID = "student_001"
STANDARD_ID = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
NOW = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)

GRADE_ITEM_A = "grade_item_a"
GRADE_ITEM_B = "grade_item_b"
WORK_A = ModuleWorkRef("scoreform", CLASS_ID, "synthetic_a")
WORK_B = ModuleWorkRef("quillan", CLASS_ID, "synthetic_b")


def _calendar() -> AcademicPeriodCalendar:
    return AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 24),
                parent_period_id=None,
                sequence=2,
                lifecycle="active",
            ),
        ),
    )


def _workspace(tmp_path: Path) -> tuple[Path, AcademicPeriodCalendar]:
    root = tmp_path / "workspace"
    root.mkdir()
    metadata = ClassMetadata(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        created_at=NOW,
        updated_at=NOW,
        module_details={},
    )
    write_class_metadata(class_metadata_path(root, CLASS_ID), metadata)
    calendar = _calendar()
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )
    _write_registration(root, WORK_A, "Synthetic assessment A")
    _write_registration(root, WORK_B, "Synthetic assessment B")
    return root, calendar


def _write_registration(root: Path, work: ModuleWorkRef, title: str) -> None:
    module_work_dir(root, work).mkdir(parents=True, exist_ok=True)
    write_academic_work_registration(
        root,
        AcademicWorkRegistration(
            schema_version="1",
            record_type="academic_work_registration",
            work=work,
            registration_revision=1,
            producer_contract_version="v1",
            title=title,
            work_kind="assessment",
            academic_intent="summative",
            lifecycle="active",
            created_at=NOW,
            updated_at=NOW,
            source_records=(),
        ),
        expected_current_revision=None,
    )


def _grade_item(grade_item_id: str, title: str) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=1,
        supersedes_revision=None,
        title=title,
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )


def _persist_grade_item_and_membership(
    root: Path,
    grade_item_id: str,
    title: str,
    work: ModuleWorkRef,
    minute: int,
    period_id: str = "mp1",
) -> tuple[GradeItemAggregationBasis, GradeItemMembershipDecision, str]:
    stored_item = write_grade_item_revision(
        root,
        _grade_item(grade_item_id, title),
    ).stored
    basis = GradeItemAggregationBasis(
        CLASS_ID,
        grade_item_id,
        1,
        stored_item.revision_sha256,
    )
    decision = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=1,
        grade_item_revision_sha256=stored_item.revision_sha256,
        work_reference=GradeItemWorkReference(
            work=work,
            registration_revision=1,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(SCHOOL_YEAR, period_id),
            calendar_revision=1,
        ),
        actor_id="teacher_local",
        rationale=None,
        decided_at=NOW + timedelta(minutes=minute),
    )
    stored_membership = write_grade_item_membership_revision(
        root,
        decision,
    ).stored
    selected = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        grade_item_id,
        work,
        1,
        expected_current_membership_revision=None,
    )
    assert selected.disposition == "created"
    return basis, decision, stored_membership.decision_sha256


def _scale() -> ProficiencyScale:
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


def _grade_item_policy(
    target: ProficiencyScale,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="grade_item_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="Grade Item proficiency",
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


def _period_policy(
    target: ProficiencyScale,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="mp1_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="MP1 proficiency",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _source(work: ModuleWorkRef, marker: str) -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work,
        "pub_" + marker * 32,
        marker * 64,
        ("f" if marker != "f" else "e") * 64,
        "item_" + marker,
    )


def _resolved_grade_item_candidate(
    *,
    target: ProficiencyScale,
    basis: GradeItemAggregationBasis,
    work: ModuleWorkRef,
    membership_sha256: str,
    level_id: str,
    membership_revision: int = 1,
    marker: str,
) -> ResolvedStandardAggregationCandidate:
    exact_source = _source(work, marker)
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
            membership_revision,
            membership_sha256,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            ("c" if marker != "c" else "d") * 64,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=StandardEvidenceAssociationReference(
            CLASS_ID,
            basis.grade_item_id,
            exact_source,
            STANDARD_ID,
            1,
            ("9" if marker != "9" else "8") * 64,
        ),
        mapping_outcome=NativeValueMappingOutcome(
            "mapped",
            NativeValueMappingProfileReference(
                CLASS_ID,
                target.scale_id,
                "synthetic_mapping_profile",
                1,
                ("5" if marker != "5" else "6") * 64,
            ),
            proficiency_scale_reference(target),
            proficiency_level_id=level_id,
        ),
    )


def _persist_grade_item_result(
    *,
    root: Path,
    target: ProficiencyScale,
    exact_policy: StandardProficiencyCalculationPolicy,
    basis: GradeItemAggregationBasis,
    work: ModuleWorkRef,
    membership_sha256: str,
    level_id: str,
    membership_revision: int = 1,
    marker: str,
    minute: int,
) -> StandardProficiencyResultSnapshot:
    exact_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target),
        (
            _resolved_grade_item_candidate(
                target=target,
                basis=basis,
                work=work,
                membership_sha256=membership_sha256,
                level_id=level_id,
                marker=marker,
            ),
        ),
    )
    outcome = calculate_standard_proficiency(
        exact_inputs,
        exact_policy,
        target,
    )
    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == level_id
    snapshot = create_standard_proficiency_result_snapshot(
        exact_inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=minute),
    )
    written = write_standard_proficiency_result_revision(root, snapshot)
    assert written.disposition == "created"
    selected = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        basis.grade_item_id,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"
    return snapshot


def test_direct_mp1_end_to_end_aggregation_is_reproducible(
    tmp_path: Path,
) -> None:
    root, calendar = _workspace(tmp_path)
    basis_a, membership_a, membership_a_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Grade Item A",
        WORK_A,
        1,
    )
    basis_b, membership_b, membership_b_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_B,
        "Grade Item B",
        WORK_B,
        2,
    )

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    selected_grade_item_policy = select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected_grade_item_policy.disposition == "created"

    result_a = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis_a,
        work=WORK_A,
        membership_sha256=membership_a_sha,
        level_id="developing",
        marker="a",
        minute=3,
    )
    result_b = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis_b,
        work=WORK_B,
        membership_sha256=membership_b_sha,
        level_id="proficient",
        marker="b",
        minute=4,
    )

    period_policy = write_academic_period_proficiency_policy_revision(
        root,
        _period_policy(target_scale),
    ).stored.policy
    selected_period_policy = select_academic_period_proficiency_policy_revision(
        root,
        CLASS_ID,
        period_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected_period_policy.disposition == "created"

    target_period = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
        calendar.calendar_revision,
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_b,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_b,
                        membership_b_sha,
                    ),
                ),
                result_b,
            ),
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_a,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_a,
                        membership_a_sha,
                    ),
                ),
                result_a,
            ),
        ),
    )
    assert tuple(entry.grade_item.grade_item_id for entry in period_inputs.entries) == (
        GRADE_ITEM_A,
        GRADE_ITEM_B,
    )
    assert tuple(entry.status for entry in period_inputs.entries) == (
        "calculated",
        "calculated",
    )
    inputs_sha256 = academic_period_proficiency_aggregation_inputs_sha256(
        period_inputs
    )
    assert period_inputs.sha256 == inputs_sha256

    outcome = calculate_academic_period_proficiency(
        period_inputs,
        period_policy,
        target_scale,
    )
    assert outcome.status == "calculated"
    assert outcome.proficiency_level_id == "proficient"
    assert outcome.calculated_result_count == 2
    assert outcome.aggregation_inputs_sha256 == inputs_sha256
    assert outcome.calculation_fingerprint == (
        academic_period_proficiency_calculation_fingerprint(
            period_inputs,
            period_policy,
            target_scale,
        )
    )

    snapshot = create_academic_period_proficiency_result_snapshot(
        period_inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=5),
    )
    assert snapshot.inputs_sha256 == inputs_sha256
    assert snapshot.calculation_fingerprint == outcome.calculation_fingerprint
    written = write_academic_period_proficiency_result_revision(root, snapshot)
    assert written.disposition == "created"
    assert (
        get_current_academic_period_proficiency_result_revision(
            root,
            CLASS_ID,
            SCHOOL_YEAR,
            "mp1",
            STUDENT_ID,
            STANDARD_ID,
        )
        is None
    )

    selected = select_academic_period_proficiency_result_revision(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        "mp1",
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"

    current = load_current_academic_period_proficiency_result(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        "mp1",
        STUDENT_ID,
        STANDARD_ID,
    )
    assert current is not None
    assert current.snapshot == snapshot

    reproduced = calculate_academic_period_proficiency(
        current.snapshot.inputs,
        period_policy,
        target_scale,
    )
    assert reproduced == current.snapshot.outcome

    freshness = assess_academic_period_proficiency_result_freshness(
        current.snapshot,
        period_inputs,
        outcome.policy_reference,
        proficiency_scale_reference(target_scale),
        calendar.calendar_revision,
        outcome.algorithm_version,
    )
    assert freshness.status == "current"
    assert freshness.reasons == ()


def test_mixed_sibling_atomic_result_blocks_both_direct_periods(
    tmp_path: Path,
) -> None:
    root, calendar = _workspace(tmp_path)
    basis, membership_a, membership_a_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Mixed-period Grade Item",
        WORK_A,
        1,
        "mp1",
    )
    same_basis, membership_b, membership_b_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Mixed-period Grade Item",
        WORK_B,
        2,
        "mp2",
    )
    assert same_basis == basis

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    selected_grade_item_policy = select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected_grade_item_policy.disposition == "created"

    exact_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=membership_a_sha,
                level_id="developing",
                marker="a",
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=membership_b_sha,
                level_id="proficient",
                marker="b",
            ),
        ),
    )
    grade_item_outcome = calculate_standard_proficiency(
        exact_inputs,
        grade_item_policy,
        target_scale,
    )
    assert grade_item_outcome.status == "calculated"
    assert grade_item_outcome.proficiency_level_id == "proficient"
    grade_item_result = create_standard_proficiency_result_snapshot(
        exact_inputs,
        grade_item_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=3),
    )
    written_result = write_standard_proficiency_result_revision(
        root,
        grade_item_result,
    )
    assert written_result.disposition == "created"
    selected_result = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        basis.grade_item_id,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected_result.disposition == "created"

    memberships = tuple(
        sorted(
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_a,
                    membership_a_sha,
                ),
                academic_period_proficiency_membership_basis_from_decision(
                    membership_b,
                    membership_b_sha,
                ),
            ),
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )
    candidate = ResolvedAcademicPeriodProficiencyCandidate(
        basis,
        memberships,
        grade_item_result,
    )
    period_policy = _period_policy(target_scale)

    for period_id in ("mp1", "mp2"):
        target_period = AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, period_id),
            calendar.calendar_revision,
        )
        period_inputs = build_academic_period_proficiency_aggregation_inputs(
            target_period=target_period,
            calendar=calendar,
            student_id=STUDENT_ID,
            standard_id=STANDARD_ID,
            target_scale=proficiency_scale_reference(target_scale),
            period_membership_scope="direct",
            candidates=(candidate,),
        )
        assert len(period_inputs.entries) == 1
        entry = period_inputs.entries[0]
        assert entry.status == "period_scope_mismatch"
        assert entry.period_scope_mismatch_reason == "mixed_sibling_periods"
        assert entry.result_reference is not None

        period_outcome = calculate_academic_period_proficiency(
            period_inputs,
            period_policy,
            target_scale,
        )
        assert period_outcome.status == "insufficient_evidence"
        assert period_outcome.proficiency_level_id is None
        assert period_outcome.calculated_result_count == 0
        assert period_outcome.period_scope_mismatch_count == 1
        reason_kinds = tuple(
            reason.kind for reason in period_outcome.insufficiency_reasons
        )
        assert reason_kinds == (
            "period_scope_mismatch",
            "no_calculated_results",
        )
        assert period_outcome.explanation_entries[0].status == "period_scope_mismatch"
        assert (
            period_outcome.explanation_entries[0].period_scope_mismatch_reason
            == "mixed_sibling_periods"
        )
        assert period_outcome.explanation_entries[0].result_reference is not None


def test_explicit_mp1_reconciliation_requires_new_atomic_grade_item_result(
    tmp_path: Path,
) -> None:
    root, calendar = _workspace(tmp_path)
    basis, membership_a, membership_a_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Reconciled Grade Item",
        WORK_A,
        1,
        "mp1",
    )
    same_basis, membership_b_v1, membership_b_v1_sha = (
        _persist_grade_item_and_membership(
            root,
            GRADE_ITEM_A,
            "Reconciled Grade Item",
            WORK_B,
            2,
            "mp2",
        )
    )
    assert same_basis == basis
    historical_membership_b = load_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_B,
        1,
    )

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    original_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=membership_a_sha,
                level_id="developing",
                marker="a",
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=membership_b_v1_sha,
                level_id="proficient",
                marker="b",
            ),
        ),
    )
    original_outcome = calculate_standard_proficiency(
        original_inputs,
        grade_item_policy,
        target_scale,
    )
    original_result = create_standard_proficiency_result_snapshot(
        original_inputs,
        original_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=3),
    )
    write_standard_proficiency_result_revision(root, original_result)
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    historical_result = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )

    membership_b_v2 = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_A,
        grade_item_revision=basis.grade_item_revision,
        grade_item_revision_sha256=basis.grade_item_revision_sha256,
        work_reference=membership_b_v1.work_reference,
        membership_revision=2,
        supersedes_revision=1,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
            calendar_revision=calendar.calendar_revision,
        ),
        actor_id="teacher_local",
        rationale="Reconcile the combined judgment to MP1.",
        decided_at=NOW + timedelta(minutes=4),
    )
    stored_membership_b_v2 = write_grade_item_membership_revision(
        root,
        membership_b_v2,
    ).stored
    selected_membership_b_v2 = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_B,
        2,
        expected_current_membership_revision=1,
    )
    assert selected_membership_b_v2.disposition == "updated"

    reconciled_memberships = tuple(
        sorted(
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_a,
                    membership_a_sha,
                ),
                academic_period_proficiency_membership_basis_from_decision(
                    membership_b_v2,
                    stored_membership_b_v2.decision_sha256,
                ),
            ),
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="membership provenance must match the exact #35 membership revision",
    ):
        ResolvedAcademicPeriodProficiencyCandidate(
            basis,
            reconciled_memberships,
            original_result,
        )

    reconciled_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=membership_a_sha,
                level_id="developing",
                marker="a",
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=stored_membership_b_v2.decision_sha256,
                level_id="proficient",
                marker="b",
                membership_revision=2,
            ),
        ),
    )
    reconciled_outcome = calculate_standard_proficiency(
        reconciled_inputs,
        grade_item_policy,
        target_scale,
    )
    reconciled_result = create_standard_proficiency_result_snapshot(
        reconciled_inputs,
        reconciled_outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=5),
    )
    written_reconciled_result = write_standard_proficiency_result_revision(
        root,
        reconciled_result,
    )
    assert written_reconciled_result.disposition == "created"
    selected_reconciled_result = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=1,
    )
    assert selected_reconciled_result.disposition == "updated"

    candidate = ResolvedAcademicPeriodProficiencyCandidate(
        basis,
        reconciled_memberships,
        reconciled_result,
    )
    target_period = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
        calendar.calendar_revision,
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        candidates=(candidate,),
    )
    assert len(period_inputs.entries) == 1
    assert period_inputs.entries[0].status == "calculated"
    assert period_inputs.entries[0].period_scope_mismatch_reason is None
    assert period_inputs.entries[0].result_reference is not None
    assert period_inputs.entries[0].result_reference.result_revision == 2

    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        _period_policy(target_scale),
        target_scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "proficient"

    reloaded_membership_b_v1 = load_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_B,
        1,
    )
    assert reloaded_membership_b_v1.content == historical_membership_b.content
    assert (
        reloaded_membership_b_v1.decision_sha256
        == historical_membership_b.decision_sha256
    )
    reloaded_result_v1 = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert reloaded_result_v1.content == historical_result.content
    assert reloaded_result_v1.result_sha256 == historical_result.result_sha256



def test_explicit_mp2_reconciliation_requires_new_atomic_grade_item_result(
    tmp_path: Path,
) -> None:
    root, calendar = _workspace(tmp_path)
    basis, membership_a_v1, membership_a_v1_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Reconciled Grade Item",
        WORK_A,
        1,
        "mp1",
    )
    same_basis, membership_b, membership_b_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Reconciled Grade Item",
        WORK_B,
        2,
        "mp2",
    )
    assert same_basis == basis
    historical_membership_a = load_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_A,
        1,
    )

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    original_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=membership_a_v1_sha,
                level_id="developing",
                marker="a",
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=membership_b_sha,
                level_id="proficient",
                marker="b",
            ),
        ),
    )
    original_outcome = calculate_standard_proficiency(
        original_inputs,
        grade_item_policy,
        target_scale,
    )
    original_result = create_standard_proficiency_result_snapshot(
        original_inputs,
        original_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=3),
    )
    write_standard_proficiency_result_revision(root, original_result)
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    historical_result = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )

    membership_a_v2 = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_A,
        grade_item_revision=basis.grade_item_revision,
        grade_item_revision_sha256=basis.grade_item_revision_sha256,
        work_reference=membership_a_v1.work_reference,
        membership_revision=2,
        supersedes_revision=1,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(SCHOOL_YEAR, "mp2"),
            calendar_revision=calendar.calendar_revision,
        ),
        actor_id="teacher_local",
        rationale="Reconcile the combined judgment to MP2.",
        decided_at=NOW + timedelta(minutes=4),
    )
    stored_membership_a_v2 = write_grade_item_membership_revision(
        root,
        membership_a_v2,
    ).stored
    selected_membership_a_v2 = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_A,
        2,
        expected_current_membership_revision=1,
    )
    assert selected_membership_a_v2.disposition == "updated"

    reconciled_memberships = tuple(
        sorted(
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_a_v2,
                    stored_membership_a_v2.decision_sha256,
                ),
                academic_period_proficiency_membership_basis_from_decision(
                    membership_b,
                    membership_b_sha,
                ),
            ),
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )
    with pytest.raises(
        AcademicPeriodProficiencyValidationError,
        match="membership provenance must match the exact #35 membership revision",
    ):
        ResolvedAcademicPeriodProficiencyCandidate(
            basis,
            reconciled_memberships,
            original_result,
        )

    reconciled_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=stored_membership_a_v2.decision_sha256,
                level_id="developing",
                marker="a",
                membership_revision=2,
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=membership_b_sha,
                level_id="proficient",
                marker="b",
            ),
        ),
    )
    reconciled_outcome = calculate_standard_proficiency(
        reconciled_inputs,
        grade_item_policy,
        target_scale,
    )
    reconciled_result = create_standard_proficiency_result_snapshot(
        reconciled_inputs,
        reconciled_outcome,
        result_revision=2,
        calculated_at=NOW + timedelta(minutes=5),
    )
    written_reconciled_result = write_standard_proficiency_result_revision(
        root,
        reconciled_result,
    )
    assert written_reconciled_result.disposition == "created"
    selected_reconciled_result = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=1,
    )
    assert selected_reconciled_result.disposition == "updated"

    candidate = ResolvedAcademicPeriodProficiencyCandidate(
        basis,
        reconciled_memberships,
        reconciled_result,
    )
    target_period = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, "mp2"),
        calendar.calendar_revision,
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        candidates=(candidate,),
    )
    assert len(period_inputs.entries) == 1
    assert period_inputs.entries[0].status == "calculated"
    assert period_inputs.entries[0].period_scope_mismatch_reason is None
    assert period_inputs.entries[0].result_reference is not None
    assert period_inputs.entries[0].result_reference.result_revision == 2

    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        _period_policy(target_scale),
        target_scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "proficient"

    reloaded_membership_a_v1 = load_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        WORK_A,
        1,
    )
    assert reloaded_membership_a_v1.content == historical_membership_a.content
    assert (
        reloaded_membership_a_v1.decision_sha256
        == historical_membership_a.decision_sha256
    )
    reloaded_result_v1 = load_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert reloaded_result_v1.content == historical_result.content
    assert reloaded_result_v1.result_sha256 == historical_result.result_sha256


def test_descendants_scope_accepts_target_period_plus_child_membership(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
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
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id="semester_1",
                period_type="semester",
                label="Semester 1",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 24),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id="semester_1",
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 24),
                parent_period_id="semester_1",
                sequence=2,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )
    _write_registration(root, WORK_A, "Synthetic assessment A")
    _write_registration(root, WORK_B, "Synthetic assessment B")

    basis, membership_parent, membership_parent_sha = (
        _persist_grade_item_and_membership(
            root,
            GRADE_ITEM_A,
            "Parent plus child Grade Item",
            WORK_A,
            1,
            "semester_1",
        )
    )
    same_basis, membership_child, membership_child_sha = (
        _persist_grade_item_and_membership(
            root,
            GRADE_ITEM_A,
            "Parent plus child Grade Item",
            WORK_B,
            2,
            "mp1",
        )
    )
    assert same_basis == basis

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    exact_inputs = build_standard_aggregation_inputs(
        basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_A,
                membership_sha256=membership_parent_sha,
                level_id="developing",
                marker="a",
            ),
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis,
                work=WORK_B,
                membership_sha256=membership_child_sha,
                level_id="proficient",
                marker="b",
            ),
        ),
    )
    grade_item_outcome = calculate_standard_proficiency(
        exact_inputs,
        grade_item_policy,
        target_scale,
    )
    assert grade_item_outcome.status == "calculated"
    assert grade_item_outcome.proficiency_level_id == "proficient"
    grade_item_result = create_standard_proficiency_result_snapshot(
        exact_inputs,
        grade_item_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=3),
    )
    write_standard_proficiency_result_revision(root, grade_item_result)
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_A,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    memberships = tuple(
        sorted(
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_parent,
                    membership_parent_sha,
                ),
                academic_period_proficiency_membership_basis_from_decision(
                    membership_child,
                    membership_child_sha,
                ),
            ),
            key=lambda item: (
                item.work_reference.work.module_id,
                item.work_reference.work.work_id,
            ),
        )
    )
    candidate = ResolvedAcademicPeriodProficiencyCandidate(
        basis,
        memberships,
        grade_item_result,
    )
    target_period = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, "semester_1"),
        calendar.calendar_revision,
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="descendants",
        candidates=(candidate,),
    )
    assert len(period_inputs.entries) == 1
    assert period_inputs.entries[0].status == "calculated"
    assert period_inputs.entries[0].period_scope_mismatch_reason is None

    period_policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="semester_1_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="Semester 1 proficiency",
        target_scale=proficiency_scale_reference(target_scale),
        strategy="highest",
        period_membership_scope="descendants",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        period_policy,
        target_scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "proficient"
    assert period_outcome.calculated_result_count == 1
    assert period_outcome.period_scope_mismatch_count == 0


def test_descendants_scope_aggregates_separate_mp1_and_mp2_grade_items(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
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
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id="semester_1",
                period_type="semester",
                label="Semester 1",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 24),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id="semester_1",
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 24),
                parent_period_id="semester_1",
                sequence=2,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )
    _write_registration(root, WORK_A, "Synthetic assessment A")
    _write_registration(root, WORK_B, "Synthetic assessment B")

    basis_a, membership_a, membership_a_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "MP1 Grade Item",
        WORK_A,
        1,
        "mp1",
    )
    basis_b, membership_b, membership_b_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_B,
        "MP2 Grade Item",
        WORK_B,
        2,
        "mp2",
    )

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    result_a = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis_a,
        work=WORK_A,
        membership_sha256=membership_a_sha,
        level_id="developing",
        marker="a",
        minute=3,
    )
    result_b = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis_b,
        work=WORK_B,
        membership_sha256=membership_b_sha,
        level_id="proficient",
        marker="b",
        minute=4,
    )

    target_period = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, "semester_1"),
        calendar.calendar_revision,
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="descendants",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_b,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_b,
                        membership_b_sha,
                    ),
                ),
                result_b,
            ),
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_a,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_a,
                        membership_a_sha,
                    ),
                ),
                result_a,
            ),
        ),
    )
    assert tuple(entry.grade_item.grade_item_id for entry in period_inputs.entries) == (
        GRADE_ITEM_A,
        GRADE_ITEM_B,
    )
    assert tuple(entry.status for entry in period_inputs.entries) == (
        "calculated",
        "calculated",
    )
    assert all(
        entry.period_scope_mismatch_reason is None for entry in period_inputs.entries
    )

    period_policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="semester_1_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="Semester 1 proficiency",
        target_scale=proficiency_scale_reference(target_scale),
        strategy="highest",
        period_membership_scope="descendants",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        period_policy,
        target_scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "proficient"
    assert period_outcome.calculated_result_count == 2
    assert period_outcome.period_scope_mismatch_count == 0

    direct_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=target_period,
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_a,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_a,
                        membership_a_sha,
                    ),
                ),
                result_a,
            ),
            ResolvedAcademicPeriodProficiencyCandidate(
                basis_b,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership_b,
                        membership_b_sha,
                    ),
                ),
                result_b,
            ),
        ),
    )
    assert tuple(entry.status for entry in direct_inputs.entries) == (
        "period_scope_mismatch",
        "period_scope_mismatch",
    )
    assert tuple(
        entry.period_scope_mismatch_reason for entry in direct_inputs.entries
    ) == (
        "outside_target_period",
        "outside_target_period",
    )


def test_descendants_scope_rejects_overlapping_unrelated_root_period(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
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
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id="semester_1",
                period_type="semester",
                label="Semester 1",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 24),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="parallel_root",
                period_type="semester",
                label="Parallel Root",
                start_date=date(2026, 9, 1),
                end_date=date(2027, 1, 24),
                parent_period_id=None,
                sequence=2,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )
    _write_registration(root, WORK_A, "Synthetic assessment A")

    basis, membership, membership_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Parallel-root Grade Item",
        WORK_A,
        1,
        "parallel_root",
    )
    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    result = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis,
        work=WORK_A,
        membership_sha256=membership_sha,
        level_id="proficient",
        marker="a",
        minute=3,
    )

    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, "semester_1"),
            calendar.calendar_revision,
        ),
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="descendants",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                basis,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership,
                        membership_sha,
                    ),
                ),
                result,
            ),
        ),
    )

    assert len(period_inputs.entries) == 1
    entry = period_inputs.entries[0]
    assert entry.status == "period_scope_mismatch"
    assert entry.period_scope_mismatch_reason == "outside_target_period"
    assert entry.result_reference is not None
    assert entry.proficiency_level_id == "proficient"


def test_descendants_scope_rejects_membership_from_prior_calendar_revision(
    tmp_path: Path,
) -> None:
    root, calendar_v1 = _workspace(tmp_path)
    basis, membership, membership_sha = _persist_grade_item_and_membership(
        root,
        GRADE_ITEM_A,
        "Revision-bound Grade Item",
        WORK_A,
        1,
        "mp1",
    )
    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    result = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis,
        work=WORK_A,
        membership_sha256=membership_sha,
        level_id="proficient",
        marker="a",
        minute=3,
    )

    calendar_v2 = AcademicPeriodCalendar(
        schema_version=calendar_v1.schema_version,
        record_type=calendar_v1.record_type,
        school_year=calendar_v1.school_year,
        calendar_revision=2,
        created_at=calendar_v1.created_at,
        updated_at=NOW + timedelta(minutes=10),
        periods=calendar_v1.periods,
    )
    write_academic_period_calendar(
        root,
        calendar_v2,
        expected_current_revision=1,
    )

    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
            calendar_v2.calendar_revision,
        ),
        calendar=calendar_v2,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="descendants",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                basis,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership,
                        membership_sha,
                    ),
                ),
                result,
            ),
        ),
    )

    assert len(period_inputs.entries) == 1
    entry = period_inputs.entries[0]
    assert entry.status == "period_scope_mismatch"
    assert entry.period_scope_mismatch_reason == "calendar_revision_mismatch"
    assert entry.result_reference is not None
    assert entry.proficiency_level_id == "proficient"


def test_noncontributing_missing_and_insufficient_preserve_low_result(
    tmp_path: Path,
) -> None:
    root, calendar = _workspace(tmp_path)
    grade_item_c = "grade_item_c"
    work_c = ModuleWorkRef("synthetic", CLASS_ID, "synthetic_c")
    _write_registration(root, work_c, "Synthetic assessment C")

    basis_low, membership_low, membership_low_sha = (
        _persist_grade_item_and_membership(
            root,
            GRADE_ITEM_A,
            "Low Grade Item",
            WORK_A,
            1,
        )
    )
    basis_missing, membership_missing, membership_missing_sha = (
        _persist_grade_item_and_membership(
            root,
            GRADE_ITEM_B,
            "Missing-result Grade Item",
            WORK_B,
            2,
        )
    )
    basis_insufficient, membership_insufficient, membership_insufficient_sha = (
        _persist_grade_item_and_membership(
            root,
            grade_item_c,
            "Insufficient-result Grade Item",
            work_c,
            3,
        )
    )

    target_scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(target_scale),
    ).stored.policy
    select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    low_result = _persist_grade_item_result(
        root=root,
        target=target_scale,
        exact_policy=grade_item_policy,
        basis=basis_low,
        work=WORK_A,
        membership_sha256=membership_low_sha,
        level_id="beginning",
        marker="a",
        minute=4,
    )

    strict_grade_item_policy = StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="strict_grade_item_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="Strict Grade Item proficiency",
        target_scale=proficiency_scale_reference(target_scale),
        strategy="highest",
        minimum_performance_observations=2,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    strict_grade_item_policy = write_standard_proficiency_policy_revision(
        root,
        strict_grade_item_policy,
    ).stored.policy
    selected_strict_policy = select_standard_proficiency_policy_revision(
        root,
        CLASS_ID,
        strict_grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert selected_strict_policy.disposition == "created"
    strict_inputs = build_standard_aggregation_inputs(
        basis_insufficient,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(target_scale),
        (
            _resolved_grade_item_candidate(
                target=target_scale,
                basis=basis_insufficient,
                work=work_c,
                membership_sha256=membership_insufficient_sha,
                level_id="proficient",
                marker="c",
            ),
        ),
    )
    strict_outcome = calculate_standard_proficiency(
        strict_inputs,
        strict_grade_item_policy,
        target_scale,
    )
    assert strict_outcome.status == "insufficient_evidence"
    assert strict_outcome.proficiency_level_id is None
    insufficient_result = create_standard_proficiency_result_snapshot(
        strict_inputs,
        strict_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=5),
    )
    written_insufficient = write_standard_proficiency_result_revision(
        root,
        insufficient_result,
    )
    assert written_insufficient.disposition == "created"
    selected_insufficient = select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        grade_item_c,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected_insufficient.disposition == "created"

    candidates = (
        ResolvedAcademicPeriodProficiencyCandidate(
            basis_low,
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_low,
                    membership_low_sha,
                ),
            ),
            low_result,
        ),
        ResolvedAcademicPeriodProficiencyCandidate(
            basis_missing,
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_missing,
                    membership_missing_sha,
                ),
            ),
            None,
        ),
        ResolvedAcademicPeriodProficiencyCandidate(
            basis_insufficient,
            (
                academic_period_proficiency_membership_basis_from_decision(
                    membership_insufficient,
                    membership_insufficient_sha,
                ),
            ),
            insufficient_result,
        ),
    )
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
            calendar.calendar_revision,
        ),
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        candidates=candidates,
    )

    assert tuple(entry.status for entry in period_inputs.entries) == (
        "calculated",
        "missing_result",
        "insufficient_evidence",
    )
    assert period_inputs.entries[0].proficiency_level_id == "beginning"
    assert period_inputs.entries[1].result_reference is None
    assert period_inputs.entries[2].result_reference is not None
    assert period_inputs.entries[2].proficiency_level_id is None

    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        _period_policy(target_scale),
        target_scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "beginning"
    assert period_outcome.candidate_count == 3
    assert period_outcome.calculated_result_count == 1
    assert period_outcome.missing_result_count == 1
    assert period_outcome.insufficient_result_count == 1
    assert period_outcome.period_scope_mismatch_count == 0
    assert tuple(item.status for item in period_outcome.explanation_entries) == (
        "calculated",
        "missing_result",
        "insufficient_evidence",
    )
    assert tuple(item.contributed for item in period_outcome.explanation_entries) == (
        True,
        False,
        False,
    )

    blocking_period_policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="mp1_blocking_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="MP1 blocking proficiency",
        target_scale=proficiency_scale_reference(target_scale),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="blocking",
        insufficient_result_handling="blocking",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    blocking_outcome = calculate_academic_period_proficiency(
        period_inputs,
        blocking_period_policy,
        target_scale,
    )
    assert blocking_outcome.status == "insufficient_evidence"
    assert blocking_outcome.proficiency_level_id is None
    assert blocking_outcome.candidate_count == 3
    assert blocking_outcome.calculated_result_count == 1
    assert blocking_outcome.missing_result_count == 1
    assert blocking_outcome.insufficient_result_count == 1
    assert blocking_outcome.period_scope_mismatch_count == 0
    assert tuple(reason.kind for reason in blocking_outcome.insufficiency_reasons) == (
        "blocking_missing_result",
        "blocking_insufficient_result",
    )
    assert blocking_outcome.insufficiency_reasons[0].grade_item_ids == (
        GRADE_ITEM_B,
    )
    assert blocking_outcome.insufficiency_reasons[1].grade_item_ids == (
        grade_item_c,
    )
    assert tuple(item.status for item in blocking_outcome.explanation_entries) == (
        "calculated",
        "missing_result",
        "insufficient_evidence",
    )
    assert blocking_outcome.explanation_entries[0].proficiency_level_id == "beginning"
