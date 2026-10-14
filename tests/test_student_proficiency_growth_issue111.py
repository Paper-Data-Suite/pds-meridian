from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
)
from meridian.standards_proficiency import StandardProficiencyActor
from meridian.student_proficiency_growth import (
    ProficiencyTrajectoryRevision,
    TrajectoryCurrentSelection,
    compose_student_proficiency_growth,
)

CLASS_ID = "english_11"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
STANDARD = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 10, 12, 23, 45, tzinfo=UTC)


def _scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="growth_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Growth scale",
        description="Custom growth labels.",
        levels=(
            ProficiencyLevel("emerging", 1, "Emerging", "Early evidence."),
            ProficiencyLevel("secure", 2, "Secure", "Meets target."),
            ProficiencyLevel("extending", 3, "Extending", "Beyond target."),
        ),
        proficiency_threshold_level_id="secure",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _policy() -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course proficiency policy",
        target_scale=proficiency_scale_reference(_scale()),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale="Teacher reporting policy.",
        revised_at=NOW,
    )


def _roster() -> ExportRosterObservation:
    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        source_fields=("roster.display_name",),
        students=(
            ExportRosterStudentObservation(
                STUDENT_ID,
                (
                    ExportRosterObservedValue(
                        "roster.display_name",
                        "Avery Chen",
                    ),
                ),
            ),
        ),
    )


def _revision(
    revision: int,
    level_id: str,
    *,
    contributing: tuple[str, ...],
    inputs_digest: str,
) -> ProficiencyTrajectoryRevision:
    return ProficiencyTrajectoryRevision(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        student_id=STUDENT_ID,
        standard_id=STANDARD,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        result_sha256=f"{revision:x}" * 64,
        calculated_at=NOW + timedelta(minutes=revision),
        target_scale=proficiency_scale_reference(_scale()),
        policy_reference=academic_period_proficiency_aggregation_policy_reference(
            _policy()
        ),
        status="calculated",
        proficiency_level_id=level_id,
        inputs_sha256=inputs_digest * 64,
        candidate_grade_item_ids=("essay_1", "essay_2"),
        contributing_grade_item_ids=contributing,
    )


def test_growth_preserves_up_unchanged_down_and_exact_lineage() -> None:
    preview = compose_student_proficiency_growth(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        observations=(
            _revision(1, "emerging", contributing=("essay_1",), inputs_digest="b"),
            _revision(
                2,
                "secure",
                contributing=("essay_1", "essay_2"),
                inputs_digest="c",
            ),
            _revision(
                3,
                "secure",
                contributing=("essay_1", "essay_2"),
                inputs_digest="d",
            ),
            _revision(4, "emerging", contributing=("essay_2",), inputs_digest="e"),
        ),
        current_selections=(TrajectoryCurrentSelection(STANDARD, 3),),
        scales=(_scale(),),
        policies=(_policy(),),
        roster_observation=_roster(),
        generated_at=NOW,
    )

    assert [row.values[6] for row in preview.rows] == [
        "INITIAL",
        "UP",
        "UNCHANGED",
        "DOWN",
    ]
    assert preview.rows[2].values[2] == "CURRENT_SELECTED / SUPERSEDED"
    assert preview.rows[3].values[2] == "LATEST_UNSELECTED"
    assert preview.rows[1].values[7] == "essay_1, essay_2"
    assert "+essay_2" in str(preview.rows[1].values[8])
    assert "teacher:teacher_local" in str(preview.rows[0].values[9])
    assert any(
        "Emerging -> Secure -> Secure -> Emerging" in item for item in preview.summary
    )
    assert "not averaged" in preview.summary[1]


def test_insufficient_state_remains_nonnumeric_and_is_not_averaged() -> None:
    insufficient = ProficiencyTrajectoryRevision(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        student_id=STUDENT_ID,
        standard_id=STANDARD,
        result_revision=1,
        supersedes_revision=None,
        result_sha256="f" * 64,
        calculated_at=NOW,
        target_scale=proficiency_scale_reference(_scale()),
        policy_reference=academic_period_proficiency_aggregation_policy_reference(
            _policy()
        ),
        status="insufficient_evidence",
        proficiency_level_id=None,
        inputs_sha256="1" * 64,
        candidate_grade_item_ids=("essay_1",),
        contributing_grade_item_ids=(),
    )
    preview = compose_student_proficiency_growth(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        observations=(insufficient,),
        current_selections=(TrajectoryCurrentSelection(STANDARD, 1),),
        scales=(_scale(),),
        policies=(_policy(),),
        roster_observation=_roster(),
        generated_at=NOW,
    )
    assert preview.rows[0].values[5] == "Insufficient evidence"
    assert preview.rows[0].values[6] == "INITIAL"
    assert "not averaged" in preview.summary[1]
