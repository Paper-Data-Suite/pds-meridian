from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pds_core.academic_period_storage import (
    load_academic_period_calendar_revision,
    write_academic_period_calendar,
)
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
from pds_core.grouping_signal_csv import (
    grouping_signal_csv_to_signal_set,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signal_storage import (
    list_grouping_signal_ids,
    load_grouping_signal,
)
from pds_core.grouping_signals import grouping_signal_set_to_json_bytes
from pds_core.rosters import create_roster, write_roster
from pds_core.routes import (
    class_dir,
    class_metadata_path,
    class_roster_path,
    module_work_dir,
)
from pds_core.routing_models import ModuleWorkRef
from pds_core.standards import (
    StandardDefinition,
    StandardsLibrary,
    write_workspace_standards_library,
)

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    ResolvedAcademicPeriodProficiencyCandidate,
    academic_period_proficiency_membership_basis_from_decision,
    build_academic_period_proficiency_aggregation_inputs,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_membership_storage import (
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.grouping_signal_csv_export import export_grouping_signal_csv
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
)
from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_export_receipt_workflow import export_grouping_signal
from meridian.grouping_signal_export_storage import (
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_generation import (
    generate_grouping_signal_derivation,
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
    select_grouping_signal_policy_revision,
    write_grouping_signal_policy_revision,
)
from meridian.grouping_signal_preview_generation import (
    generate_grouping_signal_preview,
)
from meridian.grouping_signal_preview_projection import (
    build_grouping_signal_teacher_projection,
    format_grouping_signal_teacher_projection,
)
from meridian.grouping_signal_preview_storage import (
    list_grouping_signal_preview_ids,
)
from meridian.grouping_signal_review_storage import (
    get_current_grouping_signal_review_revision,
    list_grouping_signal_review_revisions,
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import (
    record_grouping_signal_review,
)
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
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    load_current_standard_proficiency_result,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
STUDENT_ID = "student_001"
PERIOD_ID = "mp1"
STANDARD_ID = "urn:njsls:ela:RL.CR.9-10.1"
GRADE_ITEM_ID = "grade_item_a"
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


def _seed_workspace(tmp_path: Path) -> tuple[Path, ProficiencyScale]:
    workspace = tmp_path / "workspace"
    class_dir(workspace, CLASS_ID).mkdir(parents=True)
    write_class_metadata(
        class_metadata_path(workspace, CLASS_ID),
        ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    roster = create_roster(
        CLASS_ID,
        (
            {
                "student_id": STUDENT_ID,
                "last_name": "Student",
                "first_name": "Synthetic",
                "period": "1",
            },
        ),
    )
    write_roster(class_roster_path(workspace, CLASS_ID), roster)

    calendar = AcademicPeriodCalendar(
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
    )
    write_academic_period_calendar(
        workspace,
        calendar,
        expected_current_revision=None,
    )
    assert load_academic_period_calendar_revision(workspace, SCHOOL_YEAR, 1) == calendar

    write_workspace_standards_library(
        workspace,
        StandardsLibrary(
            standards=(
                StandardDefinition(
                    standard_id=STANDARD_ID,
                    code="RL.CR.9-10.1",
                    source="NJSLS-ELA-2023",
                    short_name="Textual evidence",
                    description="Synthetic standard for deterministic generation.",
                    subject="ELA",
                    grade_band="9-10",
                    active=True,
                    available_modules=("meridian",),
                ),
            )
        ),
    )

    scale = ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Synthetic criterion-referenced scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    stored_scale = write_proficiency_scale_revision(workspace, scale).stored.scale
    return workspace, stored_scale


def _seed_current_grade_item_result(
    workspace: Path,
    scale: ProficiencyScale,
) -> tuple[GradeItemAggregationBasis, GradeItemMembershipDecision, str]:
    work = ModuleWorkRef("syntheticproducer", CLASS_ID, "synthetic_a")
    module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
    write_academic_work_registration(
        workspace,
        AcademicWorkRegistration(
            schema_version="1",
            record_type="academic_work_registration",
            work=work,
            registration_revision=1,
            producer_contract_version="v1",
            title="Synthetic assessment",
            work_kind="assessment",
            academic_intent="summative",
            lifecycle="active",
            created_at=NOW,
            updated_at=NOW,
            source_records=(),
        ),
        expected_current_revision=None,
    )

    stored_item = write_grade_item_revision(
        workspace,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Synthetic Grade Item",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    select_grade_item_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
        expected_current_revision=None,
    )
    grade_item_basis = GradeItemAggregationBasis(
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
        stored_item.revision_sha256,
    )

    membership = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        grade_item_revision_sha256=stored_item.revision_sha256,
        work_reference=GradeItemWorkReference(work=work, registration_revision=1),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
            calendar_revision=1,
        ),
        actor_id="teacher_local",
        rationale=None,
        decided_at=NOW + timedelta(minutes=1),
    )
    stored_membership = write_grade_item_membership_revision(
        workspace,
        membership,
    ).stored
    select_grade_item_membership_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        work,
        1,
        expected_current_membership_revision=None,
    )

    grade_item_policy = StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="grade_item_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="Grade Item proficiency",
        target_scale=proficiency_scale_reference(scale),
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
    write_standard_proficiency_policy_revision(workspace, grade_item_policy)
    select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        grade_item_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    source = EvidenceSourceReference(
        work,
        "pub_" + "a" * 32,
        "a" * 64,
        "f" * 64,
        "item_a",
    )
    mapped = NativeValueMappingOutcome(
        "mapped",
        NativeValueMappingProfileReference(
            CLASS_ID,
            scale.scale_id,
            "synthetic_mapping_profile",
            1,
            "5" * 64,
        ),
        proficiency_scale_reference(scale),
        proficiency_level_id="proficient",
    )
    resolved = ResolvedStandardAggregationCandidate(
        source=source,
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
            stored_membership.decision_sha256,
        ),
        eligibility_reference=AggregationDecisionReference(
            "eligibility",
            1,
            "c" * 64,
        ),
        attempt_selection_reference=None,
        reassessment_reference=None,
        association_reference=StandardEvidenceAssociationReference(
            CLASS_ID,
            GRADE_ITEM_ID,
            source,
            STANDARD_ID,
            1,
            "9" * 64,
        ),
        mapping_outcome=mapped,
    )
    grade_item_inputs = build_standard_aggregation_inputs(
        grade_item_basis,
        STUDENT_ID,
        STANDARD_ID,
        proficiency_scale_reference(scale),
        (resolved,),
    )
    grade_item_outcome = calculate_standard_proficiency(
        grade_item_inputs,
        grade_item_policy,
        scale,
    )
    assert grade_item_outcome.status == "calculated"
    assert grade_item_outcome.proficiency_level_id == "proficient"
    grade_item_result = create_standard_proficiency_result_snapshot(
        grade_item_inputs,
        grade_item_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=2),
    )
    write_standard_proficiency_result_revision(workspace, grade_item_result)
    select_standard_proficiency_result_revision(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    return grade_item_basis, membership, stored_membership.decision_sha256


def _seed_period_result_and_grouping_policy(
    workspace: Path,
    scale: ProficiencyScale,
    grade_item_basis: GradeItemAggregationBasis,
    membership: GradeItemMembershipDecision,
    membership_sha256: str,
) -> str:
    period_policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="mp1_proficiency",
        policy_revision=1,
        supersedes_revision=None,
        title="MP1 proficiency",
        target_scale=proficiency_scale_reference(scale),
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
    period_policy_write = write_academic_period_proficiency_policy_revision(
        workspace,
        period_policy,
    )
    exact_period_policy = period_policy_write.stored.policy
    select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        exact_period_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    selected_grade_item_result = load_current_standard_proficiency_result(
        workspace,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    assert selected_grade_item_result is not None
    calendar = load_academic_period_calendar_revision(workspace, SCHOOL_YEAR, 1)
    period_inputs = build_academic_period_proficiency_aggregation_inputs(
        target_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
            1,
        ),
        calendar=calendar,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        candidates=(
            ResolvedAcademicPeriodProficiencyCandidate(
                grade_item_basis,
                (
                    academic_period_proficiency_membership_basis_from_decision(
                        membership,
                        membership_sha256,
                    ),
                ),
                selected_grade_item_result.snapshot,
            ),
        ),
    )
    period_outcome = calculate_academic_period_proficiency(
        period_inputs,
        exact_period_policy,
        scale,
    )
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id == "proficient"
    period_result = create_academic_period_proficiency_result_snapshot(
        period_inputs,
        period_outcome,
        result_revision=1,
        calculated_at=NOW + timedelta(minutes=3),
    )
    write_academic_period_proficiency_result_revision(workspace, period_result)
    select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    grouping_policy = GroupingSignalDerivationPolicy(
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
            source_policy=period_result.policy_reference,
            target_scale=proficiency_scale_reference(scale),
        ),
        dimension_id="reading_planning",
        band_count=2,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 2),
            GroupingSignalBandDefinition(2, 3, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale="Temporary contextual planning support.",
        revised_at=NOW,
    )
    write_grouping_signal_policy_revision(workspace, grouping_policy)
    select_grouping_signal_policy_revision(
        workspace,
        CLASS_ID,
        grouping_policy.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    return grouping_policy.policy_id


def _run_generation_acceptance(
    tmp_path: Path,
) -> GroupingSignalDerivationReference:
    workspace, scale = _seed_workspace(tmp_path)
    grade_item_basis, membership, membership_sha256 = _seed_current_grade_item_result(
        workspace,
        scale,
    )
    policy_id = _seed_period_result_and_grouping_policy(
        workspace,
        scale,
        grade_item_basis,
        membership,
        membership_sha256,
    )

    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()

    generated = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy_id,
    )
    assert generated.status == "generated"
    assert generated.write_disposition == "created"
    assert generated.stored is not None
    snapshot = generated.stored.snapshot
    assert snapshot.class_id == CLASS_ID
    assert snapshot.dimension_id == "reading_planning"
    assert snapshot.band_count == 2
    assert snapshot.roster_basis.student_ids == (STUDENT_ID,)
    assert len(snapshot.student_derivations) == 1
    student = snapshot.student_derivations[0]
    assert student.student_id == STUDENT_ID
    assert student.source_state == "calculated"
    assert student.proficiency_level_id == "proficient"
    assert student.scale_position == 3
    assert student.band == 2

    replay = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy_id,
    )
    assert replay.status == "generated"
    assert replay.write_disposition == "existing"
    assert replay.stored is not None
    assert replay.stored.reference == generated.stored.reference
    assert replay.stored.content == generated.stored.content

    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()
    return generated.stored.reference


def _run_preview_review_acceptance(
    workspace: Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> None:
    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()

    preview_result = generate_grouping_signal_preview(
        workspace,
        derivation_reference,
    )
    assert preview_result.write_disposition == "created"
    preview = preview_result.stored.snapshot
    assert preview.currentness.state == "current"
    assert preview.derivation_reference == derivation_reference
    assert preview.coverage.roster_student_count == 1
    assert preview.coverage.contributing_student_count == 1
    assert preview.student_rows[0].student_id == STUDENT_ID
    assert preview.student_rows[0].band == 2
    assert list_grouping_signal_preview_ids(workspace, CLASS_ID) == (
        preview.preview_id,
    )

    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in preview.diagnostics
            if item.severity == "warning"
        )
    )
    assert warning_ids

    review_result = record_grouping_signal_review(
        workspace,
        preview_result.stored.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id="teacher_local",
        reviewed_at=NOW + timedelta(minutes=4),
    )
    assert review_result.disposition == "created"
    derivation_id = derivation_reference.derivation_id
    assert list_grouping_signal_review_revisions(
        workspace,
        CLASS_ID,
        derivation_id,
    ) == (1,)
    assert get_current_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
    ) is None

    selected = select_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )
    assert selected.disposition == "created"

    projection = build_grouping_signal_teacher_projection(
        workspace,
        preview_result.stored.reference,
    )
    assert projection.live_currentness.state == "current"
    assert projection.student_assignments[0].display_name == "Synthetic Student"
    assert projection.student_assignments[0].band == 2
    assert projection.review_status.decision == "accepted_for_export"
    assert projection.review_status.applicability is not None
    assert projection.review_status.applicability.status == "current"

    rendered = format_grouping_signal_teacher_projection(projection)
    assert "Band 2" in rendered
    assert "Previewing does not export." in rendered
    assert "Accepting does not export." in rendered
    assert "Export happens only in #40." in rendered

    replay = generate_grouping_signal_preview(
        workspace,
        derivation_reference,
    )
    assert replay.write_disposition == "existing"
    assert replay.stored.reference == preview_result.stored.reference
    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()



def _run_export_acceptance(
    workspace: Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> None:
    signal_set_id = "reading_mp1_export_001"
    created_at = NOW + timedelta(minutes=5)
    exported = export_grouping_signal(
        workspace,
        CLASS_ID,
        derivation_reference.derivation_id,
        signal_set_id=signal_set_id,
        created_at=created_at,
    )
    assert exported.core.write_result.disposition == "created"
    assert exported.receipt.disposition == "created"
    stored = load_grouping_signal(workspace, CLASS_ID, signal_set_id)
    assert stored.signal.source.module_id == "meridian"
    assert stored.signal.source.snapshot_id == derivation_reference.derivation_id
    assert (
        stored.signal.source.snapshot_digest
        == derivation_reference.derivation_sha256
    )
    receipt = load_grouping_signal_export_receipt(
        workspace,
        CLASS_ID,
        signal_set_id,
    )
    assert receipt.receipt.core_signal_digest == stored.digest

    csv_path = workspace.parent / "reading-planning-signal.csv"
    csv_result = export_grouping_signal_csv(
        workspace, CLASS_ID, signal_set_id, csv_path
    )
    assert csv_result.disposition == "created"
    document = parse_grouping_signal_csv(csv_path.read_bytes())
    assert document.representation_scope == "complete_signal"
    reconstructed = grouping_signal_csv_to_signal_set(document)
    assert reconstructed == stored.signal
    assert (
        grouping_signal_set_to_json_bytes(reconstructed)
        == grouping_signal_set_to_json_bytes(stored.signal)
    )

    replay = export_grouping_signal(
        workspace,
        CLASS_ID,
        derivation_reference.derivation_id,
        signal_set_id=signal_set_id,
        created_at=created_at,
    )
    assert replay.core.write_result.disposition == "existing"
    assert replay.receipt.disposition == "existing"
    assert export_grouping_signal_csv(
        workspace, CLASS_ID, signal_set_id, csv_path
    ).disposition == "existing"

def main() -> None:
    assert importlib.util.find_spec("scoreform") is None
    assert importlib.util.find_spec("quillan") is None
    assert importlib.util.find_spec("concord") is None
    assert importlib.util.find_spec("portia") is None
    assert importlib.util.find_spec("vitrine") is None
    assert importlib.util.find_spec("paper_data_suite") is None

    package_root = Path(sys.prefix).resolve()
    import meridian

    assert Path(meridian.__file__).resolve().is_relative_to(package_root)

    root = Path(".").resolve()
    derivation_reference = _run_generation_acceptance(root)

    workspace = root / "workspace"
    _run_preview_review_acceptance(workspace, derivation_reference)
    derivation_ids = list_grouping_signal_derivation_ids(workspace, CLASS_ID)
    assert len(derivation_ids) == 1
    assert derivation_ids[0].startswith("gsd_")
    assert list_grouping_signal_ids(workspace, CLASS_ID) == ()
    _run_export_acceptance(workspace, derivation_reference)

    assert importlib.util.find_spec("scoreform") is None
    assert importlib.util.find_spec("quillan") is None
    assert importlib.util.find_spec("concord") is None
    assert importlib.util.find_spec("portia") is None
    assert importlib.util.find_spec("vitrine") is None
    assert importlib.util.find_spec("paper_data_suite") is None
    print("Installed grouping-signal Core/receipt/CSV export smoke passed.")


if __name__ == "__main__":
    main()
