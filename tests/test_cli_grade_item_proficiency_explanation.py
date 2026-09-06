from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.routes import class_dir

from meridian.cli import main
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWeightingMetadata
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
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
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
NOW = datetime(2026, 9, 4, 13, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    class_dir(root, CLASS_ID).mkdir(parents=True)
    return root


def _scale() -> ProficiencyScale:
    return ProficiencyScale(
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
        rationale=None,
        revised_at=NOW,
    )


def _write_result(root: Path, *, select: bool = False) -> None:
    grade_item = write_grade_item_revision(
        root,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Unit 1 assessment",
            purpose="standards_proficiency",
            status="active",
            weighting=GradeItemWeightingMetadata(
                category_id="assessment",
                relative_weight=Decimal("1.0"),
            ),
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    policy = write_standard_proficiency_policy_revision(
        root,
        _policy(scale),
    ).stored.policy
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
        entries=(),
    )
    outcome = calculate_standard_proficiency(inputs, policy, scale)
    result = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    write_standard_proficiency_result_revision(root, result)
    if select:
        select_standard_proficiency_result_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
            expected_current_result_revision=None,
        )


def _base_args(root: Path) -> tuple[str, ...]:
    return (
        "trace",
        "grade-item-proficiency",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        "--workspace",
        str(root),
    )


def test_trace_group_without_subcommand_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("trace",)) == 0
    output = capsys.readouterr().out
    assert "usage: meridian trace" in output
    assert "grade-item-proficiency" in output
    assert "read-only" in output


def test_grade_item_trace_exact_revision_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    _write_result(root)

    assert main(_base_args(root) + ("--result-revision", "1")) == 0
    output = capsys.readouterr().out

    assert "Grade Item proficiency explanation" in output
    assert "Revision: 1 (no_current_selection;" in output
    assert "insufficient_evidence -> no calculated proficiency level" in output


def test_grade_item_trace_current_json_uses_selected_pointer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    _write_result(root, select=True)

    assert main(_base_args(root) + ("--current", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["target"]["result_revision"] == 1
    assert payload["target"]["selection_state"] == "selected_current"
    assert payload["target"]["current_result_revision"] == 1
    assert payload["calculation"]["status"] == "insufficient_evidence"


def test_grade_item_trace_current_requires_explicit_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    _write_result(root)

    assert main(_base_args(root) + ("--current",)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "explanation_trace.target_not_found" in captured.err
