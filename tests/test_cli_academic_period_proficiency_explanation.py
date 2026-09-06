from __future__ import annotations

import json
from datetime import UTC, date, datetime
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

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.cli import main
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_proficiency import StandardProficiencyActor

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STUDENT_ID = "student_001"
STANDARD_ID = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 9, 4, 13, tzinfo=UTC)


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
        rationale=None,
        revised_at=NOW,
    )


def _policy(target: ProficiencyScale) -> AcademicPeriodProficiencyAggregationPolicy:
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
        rationale="Explain exact period aggregation.",
        revised_at=NOW,
    )


def _workspace(tmp_path: Path) -> tuple[Path, ProficiencyScale]:
    root = tmp_path / "workspace"
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
    scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    write_academic_period_proficiency_policy_revision(root, _policy(scale))
    return root, scale


def _write_result(
    root: Path,
    scale: ProficiencyScale,
    *,
    select: bool = False,
) -> None:
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        entries=(),
    )
    policy = _policy(scale)
    outcome = calculate_academic_period_proficiency(inputs, policy, scale)
    snapshot = create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    write_academic_period_proficiency_result_revision(root, snapshot)
    if select:
        select_academic_period_proficiency_result_revision(
            root,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
            expected_current_result_revision=None,
        )


def _base_args(root: Path) -> tuple[str, ...]:
    return (
        "trace",
        "academic-period-proficiency",
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        "--workspace",
        str(root),
    )


def test_trace_group_lists_academic_period_proficiency(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("trace",)) == 0
    output = capsys.readouterr().out
    assert "usage: meridian trace" in output
    assert "grade-item-proficiency" in output
    assert "academic-period-proficiency" in output
    assert "read-only" in output


def test_academic_period_trace_exact_revision_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, scale = _workspace(tmp_path)
    _write_result(root, scale)

    assert main(_base_args(root) + ("--result-revision", "1")) == 0
    output = capsys.readouterr().out

    assert "Academic Period proficiency explanation" in output
    assert "Revision: 1 (no_current_selection;" in output
    assert "Marking Period 1 (calendar revision 1)" in output
    assert "insufficient_evidence -> no calculated proficiency level" in output


def test_academic_period_trace_current_json_uses_selected_pointer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, scale = _workspace(tmp_path)
    _write_result(root, scale, select=True)

    assert main(_base_args(root) + ("--current", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"]["result_revision"] == 1
    assert payload["target"]["selection_state"] == "selected_current"
    assert payload["target"]["current_result_revision"] == 1
    assert payload["target"]["school_year"] == SCHOOL_YEAR
    assert payload["target"]["period_id"] == PERIOD_ID
    assert payload["calculation"]["status"] == "insufficient_evidence"


def test_academic_period_trace_current_requires_explicit_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, scale = _workspace(tmp_path)
    _write_result(root, scale)

    assert main(_base_args(root) + ("--current",)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "explanation_trace.target_not_found" in captured.err
