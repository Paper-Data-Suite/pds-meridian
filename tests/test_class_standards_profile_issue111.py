from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pds_core.academic_periods import AcademicPeriodRef

from meridian.class_standards_profile import compose_class_standards_profile
from meridian.grade_policy import ProfileStandardGroup
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
from meridian.sis_gradebook_reconciliation import CurrentProficiencyObservation
from meridian.teacher_report import teacher_report_preview_to_json_bytes

CLASS_ID = "english_11"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 10, 12, 23, 30, tzinfo=UTC)
S1 = "urn:njsls:ela:RL.CR.11-12.1"
S2 = "urn:njsls:ela:RL.CI.11-12.2"


def _scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Teacher scale",
        description="Custom labels.",
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


def _roster() -> ExportRosterObservation:
    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        source_fields=("roster.display_name",),
        students=tuple(
            ExportRosterStudentObservation(
                student_id,
                (
                    ExportRosterObservedValue(
                        "roster.display_name",
                        display_name,
                    ),
                ),
            )
            for student_id, display_name in (
                ("student_001", "Avery Chen"),
                ("student_002", "Jordan Rivera"),
                ("student_003", "Morgan Lee"),
            )
        ),
    )


def _obs(
    student_id: str,
    standard_id: str,
    revision: int,
    *,
    level_id: str | None,
    digest: str,
) -> CurrentProficiencyObservation:
    status = "calculated" if level_id is not None else "insufficient_evidence"
    return CurrentProficiencyObservation(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        student_id=student_id,
        standard_id=standard_id,
        result_revision=revision,
        result_sha256=digest * 64,
        target_scale=proficiency_scale_reference(_scale()),
        status=status,
        proficiency_level_id=level_id,
    )


def test_matrix_preserves_custom_labels_absence_and_distributions() -> None:
    preview = compose_class_standards_profile(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        target_scale=_scale(),
        reporting_standard_ids=(S2, S1),
        roster_observation=_roster(),
        current_observations=(
            _obs("student_001", S1, 1, level_id="emerging", digest="a"),
            _obs("student_001", S2, 1, level_id="secure", digest="b"),
            _obs("student_002", S1, 1, level_id="secure", digest="c"),
            _obs("student_002", S2, 1, level_id=None, digest="d"),
        ),
        generated_at=NOW,
    )

    assert preview.report_kind == "class_standards_profile"
    assert [column.title for column in preview.columns[2:]] == list(sorted((S1, S2)))
    student_rows = [row for row in preview.rows if row.row_id.startswith("student_")]
    assert student_rows[0].values[2:] == ("Secure", "Emerging")
    assert student_rows[1].values[2:] == ("Insufficient evidence", "Secure")
    assert student_rows[2].values[2:] == (
        "No current judgment",
        "No current judgment",
    )
    rendered = teacher_report_preview_to_json_bytes(preview)
    assert b"Emerging" in rendered
    assert b"Secure" in rendered
    assert b"Extending" in rendered
    assert b"Developing" not in rendered

    distributions = {
        row.values[1]: row.values[2:]
        for row in preview.rows
        if row.row_id.startswith("zz_distribution_")
    }
    assert distributions["Count — Emerging"] == ("0", "1")
    assert distributions["Count — Secure"] == ("1", "1")
    assert distributions["Count — Extending"] == ("0", "0")
    assert distributions["Count — Insufficient evidence"] == ("1", "0")
    assert distributions["Count — No current judgment"] == ("1", "1")


def test_profile_group_student_and_level_filters_are_bounded() -> None:
    preview = compose_class_standards_profile(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        target_scale=_scale(),
        reporting_standard_ids=(S1, S2),
        roster_observation=_roster(),
        current_observations=(
            _obs("student_001", S1, 1, level_id="emerging", digest="a"),
            _obs("student_002", S1, 1, level_id="secure", digest="b"),
            _obs("student_003", S1, 1, level_id="secure", digest="c"),
        ),
        generated_at=NOW + timedelta(seconds=1),
        profile_groups=(ProfileStandardGroup("focus", (S1,)),),
        profile_group_filter="focus",
        student_filter=("student_003", "student_002"),
        proficiency_level_filter=("secure",),
    )

    assert len(preview.columns) == 3
    assert preview.columns[2].title == S1
    students = [row for row in preview.rows if row.row_id.startswith("student_")]
    assert [row.values[0] for row in students] == ["student_002", "student_003"]


def test_same_inputs_and_timestamp_are_deterministic() -> None:
    kwargs = dict(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        target_scale=_scale(),
        reporting_standard_ids=(S1,),
        roster_observation=_roster(),
        current_observations=(
            _obs("student_001", S1, 1, level_id="secure", digest="e"),
        ),
        generated_at=NOW,
    )
    first = compose_class_standards_profile(**kwargs)
    second = compose_class_standards_profile(**kwargs)
    assert first.preview_sha256 == second.preview_sha256
    assert teacher_report_preview_to_json_bytes(first) == (
        teacher_report_preview_to_json_bytes(second)
    )
