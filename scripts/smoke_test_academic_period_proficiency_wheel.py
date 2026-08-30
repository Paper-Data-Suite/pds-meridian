"""Smoke-test Academic Period proficiency from an installed Meridian wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import textwrap
import venv
from pathlib import Path


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_environment(),
    )


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install exact Core + Meridian and exercise the first #35 vertical."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-academic-period-proficiency-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)

        code = textwrap.dedent(
            """
            import pathlib
            import shutil
            import tempfile
            from datetime import UTC, date, datetime, timedelta

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
            from pds_core.routes import class_metadata_path, module_work_dir
            from pds_core.routing_models import ModuleWorkRef

            from meridian.academic_period_proficiency import (
                ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                AcademicPeriodProficiencyAggregationPolicy,
                AcademicPeriodProficiencyTarget,
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
                academic_period_proficiency_result_revision_path,
                get_current_academic_period_proficiency_result_revision,
                load_current_academic_period_proficiency_result,
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
            from meridian.proficiency_mapping_storage import (
                write_proficiency_scale_revision,
            )
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
                select_standard_proficiency_policy_revision,
                select_standard_proficiency_result_revision,
                write_standard_proficiency_policy_revision,
                write_standard_proficiency_result_revision,
            )

            workspace = pathlib.Path(
                tempfile.mkdtemp(prefix="meridian-academic-period-proficiency-")
            )
            try:
                class_id = "synthetic_class_2026"
                school_year = "2026-2027"
                student_id = "student_001"
                standard_id = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
                grade_item_id = "grade_item_a"
                work = ModuleWorkRef("syntheticproducer", class_id, "synthetic_a")
                now = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)

                write_class_metadata(
                    class_metadata_path(workspace, class_id),
                    ClassMetadata(
                        class_id=class_id,
                        school_year=school_year,
                        created_at=now,
                        updated_at=now,
                        module_details={},
                    ),
                )

                calendar = AcademicPeriodCalendar(
                    schema_version="1",
                    record_type="academic_period_calendar",
                    school_year=school_year,
                    calendar_revision=1,
                    created_at=now,
                    updated_at=now,
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
                    workspace,
                    calendar,
                    expected_current_revision=None,
                )
                loaded_calendar = load_academic_period_calendar_revision(
                    workspace,
                    school_year,
                    1,
                )
                assert loaded_calendar == calendar
                calendar = loaded_calendar

                module_work_dir(workspace, work).mkdir(parents=True, exist_ok=True)
                write_academic_work_registration(
                    workspace,
                    AcademicWorkRegistration(
                        schema_version="1",
                        record_type="academic_work_registration",
                        work=work,
                        registration_revision=1,
                        producer_contract_version="v1",
                        title="Synthetic assessment A",
                        work_kind="assessment",
                        academic_intent="summative",
                        lifecycle="active",
                        created_at=now,
                        updated_at=now,
                        source_records=(),
                    ),
                    expected_current_revision=None,
                )

                stored_item = write_grade_item_revision(
                    workspace,
                    GradeItemRevision(
                        schema_version="1",
                        record_type="meridian_grade_item",
                        class_id=class_id,
                        grade_item_id=grade_item_id,
                        grade_item_revision=1,
                        supersedes_revision=None,
                        title="Grade Item A",
                        purpose="standards_proficiency",
                        status="active",
                        weighting=None,
                        created_at=now,
                        revised_at=now,
                    ),
                ).stored
                grade_item_basis = GradeItemAggregationBasis(
                    class_id,
                    grade_item_id,
                    1,
                    stored_item.revision_sha256,
                )

                membership = GradeItemMembershipDecision(
                    schema_version="1",
                    record_type="meridian_grade_item_membership",
                    class_id=class_id,
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
                        period=AcademicPeriodRef(school_year, "mp1"),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now + timedelta(minutes=1),
                )
                stored_membership = write_grade_item_membership_revision(
                    workspace,
                    membership,
                ).stored
                membership_select = select_grade_item_membership_revision(
                    workspace,
                    class_id,
                    grade_item_id,
                    work,
                    1,
                    expected_current_membership_revision=None,
                )
                assert membership_select.disposition == "created"

                scale = ProficiencyScale(
                    schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
                    record_type=PROFICIENCY_SCALE_RECORD_TYPE,
                    class_id=class_id,
                    scale_id="course_proficiency",
                    scale_revision=1,
                    supersedes_revision=None,
                    title="Course proficiency",
                    description="Synthetic criterion-referenced scale.",
                    levels=(
                        ProficiencyLevel(
                            "beginning", 1, "Beginning", "Initial evidence."
                        ),
                        ProficiencyLevel(
                            "developing", 2, "Developing", "Partial evidence."
                        ),
                        ProficiencyLevel(
                            "proficient", 3, "Proficient", "Meets criterion."
                        ),
                        ProficiencyLevel(
                            "advanced", 4, "Advanced", "Extends criterion."
                        ),
                    ),
                    proficiency_threshold_level_id="proficient",
                    actor=MappingActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                exact_scale = write_proficiency_scale_revision(
                    workspace,
                    scale,
                ).stored.scale

                grade_item_policy = StandardProficiencyCalculationPolicy(
                    schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                    record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    policy_id="grade_item_proficiency",
                    policy_revision=1,
                    supersedes_revision=None,
                    title="Grade Item proficiency",
                    target_scale=proficiency_scale_reference(exact_scale),
                    strategy="highest",
                    minimum_performance_observations=1,
                    mode_tie_rule=None,
                    median_even_rule=None,
                    blocking_exclusion_reasons=("association_unresolved",),
                    native_state_handling="noncontributing",
                    actor=StandardProficiencyActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                stored_grade_item_policy = write_standard_proficiency_policy_revision(
                    workspace,
                    grade_item_policy,
                ).stored.policy
                grade_item_policy_select = select_standard_proficiency_policy_revision(
                    workspace,
                    class_id,
                    grade_item_policy.policy_id,
                    1,
                    expected_current_policy_revision=None,
                )
                assert grade_item_policy_select.disposition == "created"

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
                        class_id,
                        exact_scale.scale_id,
                        "synthetic_mapping_profile",
                        1,
                        "5" * 64,
                    ),
                    proficiency_scale_reference(exact_scale),
                    proficiency_level_id="proficient",
                )
                resolved = ResolvedStandardAggregationCandidate(
                    source=source,
                    standard_id=standard_id,
                    result_kind="question_correctness",
                    target_kind="question",
                    subject_kind="student",
                    subject_student_id=student_id,
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
                        class_id,
                        grade_item_id,
                        source,
                        standard_id,
                        1,
                        "9" * 64,
                    ),
                    mapping_outcome=mapped,
                )
                grade_item_inputs = build_standard_aggregation_inputs(
                    grade_item_basis,
                    student_id,
                    standard_id,
                    proficiency_scale_reference(exact_scale),
                    (resolved,),
                )
                grade_item_outcome = calculate_standard_proficiency(
                    grade_item_inputs,
                    stored_grade_item_policy,
                    exact_scale,
                )
                assert grade_item_outcome.status == "calculated"
                assert grade_item_outcome.proficiency_level_id == "proficient"
                grade_item_result = create_standard_proficiency_result_snapshot(
                    grade_item_inputs,
                    grade_item_outcome,
                    result_revision=1,
                    calculated_at=now + timedelta(minutes=2),
                )
                grade_item_result_write = write_standard_proficiency_result_revision(
                    workspace,
                    grade_item_result,
                )
                assert grade_item_result_write.disposition == "created"
                grade_item_result_select = select_standard_proficiency_result_revision(
                    workspace,
                    class_id,
                    grade_item_id,
                    student_id,
                    standard_id,
                    1,
                    expected_current_result_revision=None,
                )
                assert grade_item_result_select.disposition == "created"

                period_policy = AcademicPeriodProficiencyAggregationPolicy(
                    schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                    record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    policy_id="mp1_proficiency",
                    policy_revision=1,
                    supersedes_revision=None,
                    title="MP1 proficiency",
                    target_scale=proficiency_scale_reference(exact_scale),
                    strategy="highest",
                    period_membership_scope="direct",
                    minimum_calculated_results=1,
                    mode_tie_rule=None,
                    median_even_rule=None,
                    missing_result_handling="noncontributing",
                    insufficient_result_handling="noncontributing",
                    actor=StandardProficiencyActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                period_policy_write = write_academic_period_proficiency_policy_revision(
                    workspace,
                    period_policy,
                )
                assert period_policy_write.disposition == "created"
                exact_period_policy = period_policy_write.stored.policy
                period_policy_select = (
                    select_academic_period_proficiency_policy_revision(
                        workspace,
                        class_id,
                        period_policy.policy_id,
                        1,
                        expected_current_policy_revision=None,
                    )
                )
                assert period_policy_select.disposition == "created"

                target_period = AcademicPeriodProficiencyTarget(
                    AcademicPeriodRef(school_year, "mp1"),
                    calendar.calendar_revision,
                )
                period_inputs = build_academic_period_proficiency_aggregation_inputs(
                    target_period=target_period,
                    calendar=calendar,
                    student_id=student_id,
                    standard_id=standard_id,
                    target_scale=proficiency_scale_reference(exact_scale),
                    period_membership_scope="direct",
                    candidates=(
                        ResolvedAcademicPeriodProficiencyCandidate(
                            grade_item_basis,
                            (
                                academic_period_proficiency_membership_basis_from_decision(
                                    membership,
                                    stored_membership.decision_sha256,
                                ),
                            ),
                            grade_item_result,
                        ),
                    ),
                )
                assert len(period_inputs.entries) == 1
                assert period_inputs.entries[0].status == "calculated"
                inputs_sha256 = academic_period_proficiency_aggregation_inputs_sha256(
                    period_inputs
                )
                assert period_inputs.sha256 == inputs_sha256

                period_outcome = calculate_academic_period_proficiency(
                    period_inputs,
                    exact_period_policy,
                    exact_scale,
                )
                assert period_outcome.status == "calculated"
                assert period_outcome.proficiency_level_id == "proficient"
                assert period_outcome.calculated_result_count == 1
                assert period_outcome.calculation_fingerprint == (
                    academic_period_proficiency_calculation_fingerprint(
                        period_inputs,
                        exact_period_policy,
                        exact_scale,
                    )
                )

                period_result = create_academic_period_proficiency_result_snapshot(
                    period_inputs,
                    period_outcome,
                    result_revision=1,
                    calculated_at=now + timedelta(minutes=3),
                )
                period_result_write = write_academic_period_proficiency_result_revision(
                    workspace,
                    period_result,
                )
                assert period_result_write.disposition == "created"
                result_revision_path = (
                    academic_period_proficiency_result_revision_path(
                        workspace,
                        class_id,
                        school_year,
                        "mp1",
                        student_id,
                        standard_id,
                        1,
                    )
                )
                historical_result_bytes = result_revision_path.read_bytes()
                result_digest_path = result_revision_path.with_name(
                    result_revision_path.name + ".sha256"
                )
                historical_result_digest_bytes = result_digest_path.read_bytes()
                assert get_current_academic_period_proficiency_result_revision(
                    workspace,
                    class_id,
                    school_year,
                    "mp1",
                    student_id,
                    standard_id,
                ) is None

                period_result_select = (
                    select_academic_period_proficiency_result_revision(
                        workspace,
                        class_id,
                        school_year,
                        "mp1",
                        student_id,
                        standard_id,
                        1,
                        expected_current_result_revision=None,
                    )
                )
                assert period_result_select.disposition == "created"
                current = load_current_academic_period_proficiency_result(
                    workspace,
                    class_id,
                    school_year,
                    "mp1",
                    student_id,
                    standard_id,
                )
                assert current is not None
                assert current.snapshot == period_result

                replay = calculate_academic_period_proficiency(
                    current.snapshot.inputs,
                    exact_period_policy,
                    exact_scale,
                )
                assert replay == current.snapshot.outcome

                freshness = assess_academic_period_proficiency_result_freshness(
                    current.snapshot,
                    period_inputs,
                    period_outcome.policy_reference,
                    proficiency_scale_reference(exact_scale),
                    calendar.calendar_revision,
                    period_outcome.algorithm_version,
                )
                assert freshness.status == "current"
                assert freshness.reasons == ()

                # Parent descendant aggregation from separate atomic #34 results.
                work_b = ModuleWorkRef(
                    "syntheticproducer",
                    class_id,
                    "synthetic_b",
                )
                module_work_dir(workspace, work_b).mkdir(parents=True, exist_ok=True)
                write_academic_work_registration(
                    workspace,
                    AcademicWorkRegistration(
                        schema_version="1",
                        record_type="academic_work_registration",
                        work=work_b,
                        registration_revision=1,
                        producer_contract_version="v1",
                        title="Synthetic assessment B",
                        work_kind="assessment",
                        academic_intent="summative",
                        lifecycle="active",
                        created_at=now,
                        updated_at=now,
                        source_records=(),
                    ),
                    expected_current_revision=None,
                )

                grade_item_b_id = "grade_item_b"
                stored_item_b = write_grade_item_revision(
                    workspace,
                    GradeItemRevision(
                        schema_version="1",
                        record_type="meridian_grade_item",
                        class_id=class_id,
                        grade_item_id=grade_item_b_id,
                        grade_item_revision=1,
                        supersedes_revision=None,
                        title="Grade Item B",
                        purpose="standards_proficiency",
                        status="active",
                        weighting=None,
                        created_at=now,
                        revised_at=now,
                    ),
                ).stored
                grade_item_b_basis = GradeItemAggregationBasis(
                    class_id,
                    grade_item_b_id,
                    1,
                    stored_item_b.revision_sha256,
                )
                membership_b = GradeItemMembershipDecision(
                    schema_version="1",
                    record_type="meridian_grade_item_membership",
                    class_id=class_id,
                    grade_item_id=grade_item_b_id,
                    grade_item_revision=1,
                    grade_item_revision_sha256=stored_item_b.revision_sha256,
                    work_reference=GradeItemWorkReference(
                        work=work_b,
                        registration_revision=1,
                    ),
                    membership_revision=1,
                    supersedes_revision=None,
                    decision="included",
                    academic_period=GradeItemAcademicPeriodAssignment(
                        period=AcademicPeriodRef(school_year, "mp2"),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now + timedelta(minutes=4),
                )
                stored_membership_b = write_grade_item_membership_revision(
                    workspace,
                    membership_b,
                ).stored
                select_grade_item_membership_revision(
                    workspace,
                    class_id,
                    grade_item_b_id,
                    work_b,
                    1,
                    expected_current_membership_revision=None,
                )

                source_b = EvidenceSourceReference(
                    work_b,
                    "pub_" + "b" * 32,
                    "b" * 64,
                    "e" * 64,
                    "item_b",
                )
                mapped_b = NativeValueMappingOutcome(
                    "mapped",
                    NativeValueMappingProfileReference(
                        class_id,
                        exact_scale.scale_id,
                        "synthetic_mapping_profile",
                        1,
                        "5" * 64,
                    ),
                    proficiency_scale_reference(exact_scale),
                    proficiency_level_id="developing",
                )
                resolved_b = ResolvedStandardAggregationCandidate(
                    source=source_b,
                    standard_id=standard_id,
                    result_kind="question_correctness",
                    target_kind="question",
                    subject_kind="student",
                    subject_student_id=student_id,
                    association_state="associated",
                    eligibility_state="included",
                    attempt_state="not_applicable",
                    reassessment_state="not_applicable",
                    membership_reference=AggregationDecisionReference(
                        "membership",
                        1,
                        stored_membership_b.decision_sha256,
                    ),
                    eligibility_reference=AggregationDecisionReference(
                        "eligibility",
                        1,
                        "d" * 64,
                    ),
                    attempt_selection_reference=None,
                    reassessment_reference=None,
                    association_reference=StandardEvidenceAssociationReference(
                        class_id,
                        grade_item_b_id,
                        source_b,
                        standard_id,
                        1,
                        "8" * 64,
                    ),
                    mapping_outcome=mapped_b,
                )
                grade_item_b_inputs = build_standard_aggregation_inputs(
                    grade_item_b_basis,
                    student_id,
                    standard_id,
                    proficiency_scale_reference(exact_scale),
                    (resolved_b,),
                )
                grade_item_b_outcome = calculate_standard_proficiency(
                    grade_item_b_inputs,
                    stored_grade_item_policy,
                    exact_scale,
                )
                assert grade_item_b_outcome.status == "calculated"
                assert grade_item_b_outcome.proficiency_level_id == "developing"
                grade_item_b_result = create_standard_proficiency_result_snapshot(
                    grade_item_b_inputs,
                    grade_item_b_outcome,
                    result_revision=1,
                    calculated_at=now + timedelta(minutes=5),
                )
                write_standard_proficiency_result_revision(
                    workspace,
                    grade_item_b_result,
                )
                select_standard_proficiency_result_revision(
                    workspace,
                    class_id,
                    grade_item_b_id,
                    student_id,
                    standard_id,
                    1,
                    expected_current_result_revision=None,
                )

                descendants_policy = AcademicPeriodProficiencyAggregationPolicy(
                    schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                    record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    policy_id="semester_descendants",
                    policy_revision=1,
                    supersedes_revision=None,
                    title="Semester descendants proficiency",
                    target_scale=proficiency_scale_reference(exact_scale),
                    strategy="highest",
                    period_membership_scope="descendants",
                    minimum_calculated_results=1,
                    mode_tie_rule=None,
                    median_even_rule=None,
                    missing_result_handling="noncontributing",
                    insufficient_result_handling="noncontributing",
                    actor=StandardProficiencyActor("teacher", "teacher_local"),
                    rationale=None,
                    revised_at=now,
                )
                semester_inputs = (
                    build_academic_period_proficiency_aggregation_inputs(
                        target_period=AcademicPeriodProficiencyTarget(
                            AcademicPeriodRef(school_year, "semester_1"),
                            calendar.calendar_revision,
                        ),
                        calendar=calendar,
                        student_id=student_id,
                        standard_id=standard_id,
                        target_scale=proficiency_scale_reference(exact_scale),
                        period_membership_scope="descendants",
                        candidates=(
                            ResolvedAcademicPeriodProficiencyCandidate(
                                grade_item_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        membership,
                                        stored_membership.decision_sha256,
                                    ),
                                ),
                                grade_item_result,
                            ),
                            ResolvedAcademicPeriodProficiencyCandidate(
                                grade_item_b_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        membership_b,
                                        stored_membership_b.decision_sha256,
                                    ),
                                ),
                                grade_item_b_result,
                            ),
                        ),
                    )
                )
                assert tuple(
                    entry.status for entry in semester_inputs.entries
                ) == ("calculated", "calculated")
                semester_outcome = calculate_academic_period_proficiency(
                    semester_inputs,
                    descendants_policy,
                    exact_scale,
                )
                assert semester_outcome.status == "calculated"
                assert semester_outcome.proficiency_level_id == "proficient"
                assert semester_outcome.calculated_result_count == 2

                # One atomic #34 basis spanning sibling periods is never split.
                mixed_grade_item_id = "grade_item_mixed"
                stored_mixed_item = write_grade_item_revision(
                    workspace,
                    GradeItemRevision(
                        schema_version="1",
                        record_type="meridian_grade_item",
                        class_id=class_id,
                        grade_item_id=mixed_grade_item_id,
                        grade_item_revision=1,
                        supersedes_revision=None,
                        title="Mixed sibling Grade Item",
                        purpose="standards_proficiency",
                        status="active",
                        weighting=None,
                        created_at=now,
                        revised_at=now,
                    ),
                ).stored
                mixed_basis = GradeItemAggregationBasis(
                    class_id,
                    mixed_grade_item_id,
                    1,
                    stored_mixed_item.revision_sha256,
                )

                mixed_membership_a = GradeItemMembershipDecision(
                    schema_version="1",
                    record_type="meridian_grade_item_membership",
                    class_id=class_id,
                    grade_item_id=mixed_grade_item_id,
                    grade_item_revision=1,
                    grade_item_revision_sha256=stored_mixed_item.revision_sha256,
                    work_reference=GradeItemWorkReference(
                        work=work,
                        registration_revision=1,
                    ),
                    membership_revision=1,
                    supersedes_revision=None,
                    decision="included",
                    academic_period=GradeItemAcademicPeriodAssignment(
                        period=AcademicPeriodRef(school_year, "mp1"),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now + timedelta(minutes=6),
                )
                mixed_membership_b = GradeItemMembershipDecision(
                    schema_version="1",
                    record_type="meridian_grade_item_membership",
                    class_id=class_id,
                    grade_item_id=mixed_grade_item_id,
                    grade_item_revision=1,
                    grade_item_revision_sha256=stored_mixed_item.revision_sha256,
                    work_reference=GradeItemWorkReference(
                        work=work_b,
                        registration_revision=1,
                    ),
                    membership_revision=1,
                    supersedes_revision=None,
                    decision="included",
                    academic_period=GradeItemAcademicPeriodAssignment(
                        period=AcademicPeriodRef(school_year, "mp2"),
                        calendar_revision=1,
                    ),
                    actor_id="teacher_local",
                    rationale=None,
                    decided_at=now + timedelta(minutes=6),
                )
                stored_mixed_membership_a = write_grade_item_membership_revision(
                    workspace,
                    mixed_membership_a,
                ).stored
                stored_mixed_membership_b = write_grade_item_membership_revision(
                    workspace,
                    mixed_membership_b,
                ).stored

                def mixed_candidate(
                    candidate_source,
                    membership_sha256,
                    level_id,
                    marker,
                ):
                    return ResolvedStandardAggregationCandidate(
                        source=candidate_source,
                        standard_id=standard_id,
                        result_kind="question_correctness",
                        target_kind="question",
                        subject_kind="student",
                        subject_student_id=student_id,
                        association_state="associated",
                        eligibility_state="included",
                        attempt_state="not_applicable",
                        reassessment_state="not_applicable",
                        membership_reference=AggregationDecisionReference(
                            "membership",
                            1,
                            membership_sha256,
                        ),
                        eligibility_reference=AggregationDecisionReference(
                            "eligibility",
                            1,
                            marker * 64,
                        ),
                        attempt_selection_reference=None,
                        reassessment_reference=None,
                        association_reference=StandardEvidenceAssociationReference(
                            class_id,
                            mixed_grade_item_id,
                            candidate_source,
                            standard_id,
                            1,
                            marker * 64,
                        ),
                        mapping_outcome=NativeValueMappingOutcome(
                            "mapped",
                            NativeValueMappingProfileReference(
                                class_id,
                                exact_scale.scale_id,
                                "synthetic_mapping_profile",
                                1,
                                "5" * 64,
                            ),
                            proficiency_scale_reference(exact_scale),
                            proficiency_level_id=level_id,
                        ),
                    )

                mixed_inputs = build_standard_aggregation_inputs(
                    mixed_basis,
                    student_id,
                    standard_id,
                    proficiency_scale_reference(exact_scale),
                    (
                        mixed_candidate(
                            source,
                            stored_mixed_membership_a.decision_sha256,
                            "developing",
                            "6",
                        ),
                        mixed_candidate(
                            source_b,
                            stored_mixed_membership_b.decision_sha256,
                            "proficient",
                            "7",
                        ),
                    ),
                )
                mixed_grade_item_outcome = calculate_standard_proficiency(
                    mixed_inputs,
                    stored_grade_item_policy,
                    exact_scale,
                )
                assert mixed_grade_item_outcome.status == "calculated"
                assert mixed_grade_item_outcome.proficiency_level_id == "proficient"
                mixed_grade_item_result = (
                    create_standard_proficiency_result_snapshot(
                        mixed_inputs,
                        mixed_grade_item_outcome,
                        result_revision=1,
                        calculated_at=now + timedelta(minutes=7),
                    )
                )

                mixed_period_inputs = (
                    build_academic_period_proficiency_aggregation_inputs(
                        target_period=target_period,
                        calendar=calendar,
                        student_id=student_id,
                        standard_id=standard_id,
                        target_scale=proficiency_scale_reference(exact_scale),
                        period_membership_scope="direct",
                        candidates=(
                            ResolvedAcademicPeriodProficiencyCandidate(
                                mixed_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        mixed_membership_a,
                                        stored_mixed_membership_a.decision_sha256,
                                    ),
                                    academic_period_proficiency_membership_basis_from_decision(
                                        mixed_membership_b,
                                        stored_mixed_membership_b.decision_sha256,
                                    ),
                                ),
                                mixed_grade_item_result,
                            ),
                        ),
                    )
                )
                mixed_entry = mixed_period_inputs.entries[0]
                assert mixed_entry.status == "period_scope_mismatch"
                assert (
                    mixed_entry.period_scope_mismatch_reason
                    == "mixed_sibling_periods"
                )
                assert mixed_entry.proficiency_level_id == "proficient"
                mixed_period_outcome = calculate_academic_period_proficiency(
                    mixed_period_inputs,
                    exact_period_policy,
                    exact_scale,
                )
                assert mixed_period_outcome.status == "insufficient_evidence"
                assert mixed_period_outcome.calculated_result_count == 0
                assert mixed_period_outcome.period_scope_mismatch_count == 1
                assert tuple(
                    reason.kind
                    for reason in mixed_period_outcome.insufficiency_reasons
                ) == ("period_scope_mismatch", "no_calculated_results")

                # Missing #34 results, #34 insufficiency, and genuinely low
                # calculated proficiency remain distinct at the period layer.
                work_c = ModuleWorkRef(
                    "syntheticproducer", class_id, "synthetic_c"
                )
                module_work_dir(workspace, work_c).mkdir(
                    parents=True,
                    exist_ok=True,
                )
                write_academic_work_registration(
                    workspace,
                    AcademicWorkRegistration(
                        schema_version="1",
                        record_type="academic_work_registration",
                        work=work_c,
                        registration_revision=1,
                        producer_contract_version="v1",
                        title="Synthetic assessment C",
                        work_kind="assessment",
                        academic_intent="summative",
                        lifecycle="active",
                        created_at=now,
                        updated_at=now,
                        source_records=(),
                    ),
                    expected_current_revision=None,
                )

                def period_grade_item(
                    item_id,
                    title,
                    item_work,
                    minute,
                ):
                    stored = write_grade_item_revision(
                        workspace,
                        GradeItemRevision(
                            schema_version="1",
                            record_type="meridian_grade_item",
                            class_id=class_id,
                            grade_item_id=item_id,
                            grade_item_revision=1,
                            supersedes_revision=None,
                            title=title,
                            purpose="standards_proficiency",
                            status="active",
                            weighting=None,
                            created_at=now,
                            revised_at=now,
                        ),
                    ).stored
                    basis = GradeItemAggregationBasis(
                        class_id,
                        item_id,
                        1,
                        stored.revision_sha256,
                    )
                    decision = GradeItemMembershipDecision(
                        schema_version="1",
                        record_type="meridian_grade_item_membership",
                        class_id=class_id,
                        grade_item_id=item_id,
                        grade_item_revision=1,
                        grade_item_revision_sha256=stored.revision_sha256,
                        work_reference=GradeItemWorkReference(
                            work=item_work,
                            registration_revision=1,
                        ),
                        membership_revision=1,
                        supersedes_revision=None,
                        decision="included",
                        academic_period=GradeItemAcademicPeriodAssignment(
                            period=AcademicPeriodRef(school_year, "mp1"),
                            calendar_revision=1,
                        ),
                        actor_id="teacher_local",
                        rationale=None,
                        decided_at=now + timedelta(minutes=minute),
                    )
                    stored_decision = write_grade_item_membership_revision(
                        workspace,
                        decision,
                    ).stored
                    selected_decision = select_grade_item_membership_revision(
                        workspace,
                        class_id,
                        item_id,
                        item_work,
                        1,
                        expected_current_membership_revision=None,
                    )
                    assert selected_decision.disposition == "created"
                    return basis, decision, stored_decision.decision_sha256

                low_basis, low_membership, low_membership_sha = period_grade_item(
                    "grade_item_case_a_low",
                    "Low Grade Item",
                    work,
                    8,
                )
                (
                    missing_basis,
                    missing_membership,
                    missing_membership_sha,
                ) = period_grade_item(
                    "grade_item_case_b_missing",
                    "Missing-result Grade Item",
                    work_b,
                    9,
                )
                (
                    insufficient_basis,
                    insufficient_membership,
                    insufficient_membership_sha,
                ) = period_grade_item(
                    "grade_item_case_c_insufficient",
                    "Insufficient-result Grade Item",
                    work_c,
                    10,
                )

                def one_performance_result(
                    basis,
                    item_work,
                    membership_sha,
                    level_id,
                    marker,
                    policy,
                    minute,
                ):
                    candidate_source = EvidenceSourceReference(
                        item_work,
                        "pub_" + marker * 32,
                        marker * 64,
                        marker * 64,
                        "item_" + marker,
                    )
                    candidate = ResolvedStandardAggregationCandidate(
                        source=candidate_source,
                        standard_id=standard_id,
                        result_kind="question_correctness",
                        target_kind="question",
                        subject_kind="student",
                        subject_student_id=student_id,
                        association_state="associated",
                        eligibility_state="included",
                        attempt_state="not_applicable",
                        reassessment_state="not_applicable",
                        membership_reference=AggregationDecisionReference(
                            "membership",
                            1,
                            membership_sha,
                        ),
                        eligibility_reference=AggregationDecisionReference(
                            "eligibility",
                            1,
                            marker * 64,
                        ),
                        attempt_selection_reference=None,
                        reassessment_reference=None,
                        association_reference=(
                            StandardEvidenceAssociationReference(
                                class_id,
                                basis.grade_item_id,
                                candidate_source,
                                standard_id,
                                1,
                                marker * 64,
                            )
                        ),
                        mapping_outcome=NativeValueMappingOutcome(
                            "mapped",
                            NativeValueMappingProfileReference(
                                class_id,
                                exact_scale.scale_id,
                                "synthetic_mapping_profile",
                                1,
                                "5" * 64,
                            ),
                            proficiency_scale_reference(exact_scale),
                            proficiency_level_id=level_id,
                        ),
                    )
                    inputs = build_standard_aggregation_inputs(
                        basis,
                        student_id,
                        standard_id,
                        proficiency_scale_reference(exact_scale),
                        (candidate,),
                    )
                    outcome = calculate_standard_proficiency(
                        inputs,
                        policy,
                        exact_scale,
                    )
                    snapshot = create_standard_proficiency_result_snapshot(
                        inputs,
                        outcome,
                        result_revision=1,
                        calculated_at=now + timedelta(minutes=minute),
                    )
                    written = write_standard_proficiency_result_revision(
                        workspace,
                        snapshot,
                    )
                    assert written.disposition == "created"
                    selected = select_standard_proficiency_result_revision(
                        workspace,
                        class_id,
                        basis.grade_item_id,
                        student_id,
                        standard_id,
                        1,
                        expected_current_result_revision=None,
                    )
                    assert selected.disposition == "created"
                    return snapshot

                low_result = one_performance_result(
                    low_basis,
                    work,
                    low_membership_sha,
                    "beginning",
                    "1",
                    stored_grade_item_policy,
                    11,
                )
                assert low_result.outcome.status == "calculated"
                assert low_result.outcome.proficiency_level_id == "beginning"

                strict_grade_item_policy = StandardProficiencyCalculationPolicy(
                    schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                    record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    policy_id="strict_grade_item_proficiency",
                    policy_revision=1,
                    supersedes_revision=None,
                    title="Strict Grade Item proficiency",
                    target_scale=proficiency_scale_reference(exact_scale),
                    strategy="highest",
                    minimum_performance_observations=2,
                    mode_tie_rule=None,
                    median_even_rule=None,
                    blocking_exclusion_reasons=("association_unresolved",),
                    native_state_handling="noncontributing",
                    actor=StandardProficiencyActor(
                        "teacher",
                        "teacher_local",
                    ),
                    rationale=None,
                    revised_at=now,
                )
                strict_grade_item_policy = (
                    write_standard_proficiency_policy_revision(
                        workspace,
                        strict_grade_item_policy,
                    ).stored.policy
                )
                strict_policy_select = (
                    select_standard_proficiency_policy_revision(
                        workspace,
                        class_id,
                        strict_grade_item_policy.policy_id,
                        1,
                        expected_current_policy_revision=None,
                    )
                )
                assert strict_policy_select.disposition == "created"
                insufficient_result = one_performance_result(
                    insufficient_basis,
                    work_c,
                    insufficient_membership_sha,
                    "proficient",
                    "2",
                    strict_grade_item_policy,
                    12,
                )
                assert insufficient_result.outcome.status == "insufficient_evidence"
                assert insufficient_result.outcome.proficiency_level_id is None

                low_missing_insufficient_inputs = (
                    build_academic_period_proficiency_aggregation_inputs(
                        target_period=target_period,
                        calendar=calendar,
                        student_id=student_id,
                        standard_id=standard_id,
                        target_scale=proficiency_scale_reference(exact_scale),
                        period_membership_scope="direct",
                        candidates=(
                            ResolvedAcademicPeriodProficiencyCandidate(
                                low_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        low_membership,
                                        low_membership_sha,
                                    ),
                                ),
                                low_result,
                            ),
                            ResolvedAcademicPeriodProficiencyCandidate(
                                missing_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        missing_membership,
                                        missing_membership_sha,
                                    ),
                                ),
                                None,
                            ),
                            ResolvedAcademicPeriodProficiencyCandidate(
                                insufficient_basis,
                                (
                                    academic_period_proficiency_membership_basis_from_decision(
                                        insufficient_membership,
                                        insufficient_membership_sha,
                                    ),
                                ),
                                insufficient_result,
                            ),
                        ),
                    )
                )
                assert tuple(
                    entry.status
                    for entry in low_missing_insufficient_inputs.entries
                ) == (
                    "calculated",
                    "missing_result",
                    "insufficient_evidence",
                )
                assert (
                    low_missing_insufficient_inputs.entries[0].proficiency_level_id
                    == "beginning"
                )
                assert (
                    low_missing_insufficient_inputs.entries[1].result_reference
                    is None
                )
                assert (
                    low_missing_insufficient_inputs.entries[2].result_reference
                    is not None
                )

                noncontributing_policy = (
                    AcademicPeriodProficiencyAggregationPolicy(
                        schema_version=(
                            ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION
                        ),
                        record_type=(
                            ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE
                        ),
                        class_id=class_id,
                        policy_id="mp1_noncontributing_smoke",
                        policy_revision=1,
                        supersedes_revision=None,
                        title="MP1 noncontributing smoke",
                        target_scale=proficiency_scale_reference(exact_scale),
                        strategy="highest",
                        period_membership_scope="direct",
                        minimum_calculated_results=1,
                        mode_tie_rule=None,
                        median_even_rule=None,
                        missing_result_handling="noncontributing",
                        insufficient_result_handling="noncontributing",
                        actor=StandardProficiencyActor(
                            "teacher",
                            "teacher_local",
                        ),
                        rationale=None,
                        revised_at=now,
                    )
                )
                noncontributing_outcome = (
                    calculate_academic_period_proficiency(
                        low_missing_insufficient_inputs,
                        noncontributing_policy,
                        exact_scale,
                    )
                )
                assert noncontributing_outcome.status == "calculated"
                assert (
                    noncontributing_outcome.proficiency_level_id
                    == "beginning"
                )
                assert noncontributing_outcome.calculated_result_count == 1
                assert noncontributing_outcome.missing_result_count == 1
                assert noncontributing_outcome.insufficient_result_count == 1
                assert tuple(
                    item.contributed
                    for item in noncontributing_outcome.explanation_entries
                ) == (True, False, False)

                blocking_policy = AcademicPeriodProficiencyAggregationPolicy(
                    schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
                    record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
                    class_id=class_id,
                    policy_id="mp1_blocking_smoke",
                    policy_revision=1,
                    supersedes_revision=None,
                    title="MP1 blocking smoke",
                    target_scale=proficiency_scale_reference(exact_scale),
                    strategy="highest",
                    period_membership_scope="direct",
                    minimum_calculated_results=1,
                    mode_tie_rule=None,
                    median_even_rule=None,
                    missing_result_handling="blocking",
                    insufficient_result_handling="blocking",
                    actor=StandardProficiencyActor(
                        "teacher",
                        "teacher_local",
                    ),
                    rationale=None,
                    revised_at=now,
                )
                blocking_outcome = calculate_academic_period_proficiency(
                    low_missing_insufficient_inputs,
                    blocking_policy,
                    exact_scale,
                )
                assert blocking_outcome.status == "insufficient_evidence"
                assert blocking_outcome.proficiency_level_id is None
                assert blocking_outcome.calculated_result_count == 1
                assert blocking_outcome.missing_result_count == 1
                assert blocking_outcome.insufficient_result_count == 1
                assert tuple(
                    reason.kind
                    for reason in blocking_outcome.insufficiency_reasons
                ) == (
                    "blocking_missing_result",
                    "blocking_insufficient_result",
                )
                assert (
                    blocking_outcome.explanation_entries[0].proficiency_level_id
                    == "beginning"
                )

                stale = assess_academic_period_proficiency_result_freshness(
                    current.snapshot,
                    low_missing_insufficient_inputs,
                    current.snapshot.policy_reference,
                    proficiency_scale_reference(exact_scale),
                    calendar.calendar_revision,
                    current.snapshot.algorithm_version,
                )
                assert stale.status == "stale"
                assert stale.reasons == ("inputs_changed",)
                assert result_revision_path.read_bytes() == historical_result_bytes
                assert (
                    result_digest_path.read_bytes()
                    == historical_result_digest_bytes
                )
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
            """
        )
        smoke_program = root / "academic_period_proficiency_installed_smoke.py"
        smoke_program.write_text(code, encoding="utf-8")
        _run([str(python), "-I", str(smoke_program)], outside)


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and execute the isolated #35 installed smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    print("Installed Academic Period proficiency smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
