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

import meridian.grouping_signal_policy_storage as grouping_policy_storage
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.academic_period_proficiency_storage import (
    write_academic_period_proficiency_policy_revision,
)
from meridian.cli import main
from meridian.grouping_signal_derivation import (
    GroupingSignalResolvedStudentResult,
    derive_grouping_signal_snapshot,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    StoredGroupingSignalDerivation,
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
    write_grouping_signal_policy_revision,
)
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
STANDARD_ID = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 9, 4, 17, tzinfo=UTC)


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
        rationale="Exact #35 source policy for planning.",
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


def _workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, StoredGroupingSignalDerivation]:
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
    period_policy = write_academic_period_proficiency_policy_revision(
        root,
        _period_policy(scale),
    ).stored.policy

    monkeypatch.setattr(
        grouping_policy_storage,
        "validate_grouping_signal_policy_dependencies",
        lambda *args, **kwargs: object(),
    )
    grouping_policy = write_grouping_signal_policy_revision(
        root,
        _grouping_policy(scale, period_policy),
    ).stored

    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_2", "student_1"),
    )
    snapshot = derive_grouping_signal_snapshot(
        grouping_policy.policy,
        grouping_policy.reference,
        scale,
        roster,
        (
            GroupingSignalResolvedStudentResult("student_1", None),
            GroupingSignalResolvedStudentResult("student_2", None),
        ),
    )
    derivation = write_grouping_signal_derivation(root, snapshot).stored
    return root, derivation


def _base_args(
    root: Path,
    derivation_id: str,
) -> tuple[str, ...]:
    return (
        "trace",
        "planning-derivation",
        CLASS_ID,
        derivation_id,
        "--workspace",
        str(root),
    )


def test_trace_group_lists_planning_derivation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("trace",)) == 0
    output = capsys.readouterr().out
    assert "grade-item-proficiency" in output
    assert "academic-period-proficiency" in output
    assert "planning-derivation" in output


def test_planning_derivation_trace_exact_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation = _workspace(tmp_path, monkeypatch)

    assert main(_base_args(root, derivation.snapshot.derivation_id)) == 0
    output = capsys.readouterr().out

    assert "Planning-signal derivation explanation" in output
    assert f"derivation_id: {derivation.snapshot.derivation_id}" in output
    assert "policy: reading_planning_signal revision=1" in output
    assert (
        "student=student_1 source_state=missing disposition=noncontributing"
        in output
    )
    assert "band: none reason=missing_result policy_handling=noncontributing" in output


def test_planning_derivation_trace_json_preserves_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, derivation = _workspace(tmp_path, monkeypatch)

    args = _base_args(root, derivation.snapshot.derivation_id) + (
        "--format",
        "json",
    )
    assert main(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"]["derivation_id"] == derivation.snapshot.derivation_id
    assert payload["target"]["derivation_sha256"] == derivation.derivation_sha256
    assert payload["policy"]["policy_id"] == "reading_planning_signal"
    assert payload["planning_context"]["dimension_id"] == "reading_planning"
    assert [item["student_id"] for item in payload["students"]] == [
        "student_1",
        "student_2",
    ]
    assert all(item["source_state"] == "missing" for item in payload["students"])
    assert all(item["band"] is None for item in payload["students"])


def test_planning_derivation_trace_missing_exact_identity_is_not_found(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = "gsd_" + "0" * 64
    assert main(_base_args(tmp_path, missing)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "explanation_trace.target_not_found" in captured.err
