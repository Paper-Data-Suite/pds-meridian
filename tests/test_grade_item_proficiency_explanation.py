from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.routes import class_dir

from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
    grade_item_proficiency_explanation_to_json_bytes,
    render_grade_item_proficiency_explanation_text,
)
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
    StandardProficiencyResultSnapshot,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    select_standard_proficiency_result_revision,
    standard_proficiency_policy_revision_path,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "https://standards.example/NJSLS:ELA/RI.CR.11-12.1"
NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


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
        title="Unit 1 assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=GradeItemWeightingMetadata(
            category_id="assessment",
            relative_weight=Decimal("1.0"),
        ),
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
        description="Synthetic criterion-referenced scale.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale="Coursewide scale.",
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
        title="Course policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale="Require one usable performance observation.",
        revised_at=NOW,
    )


def snapshot(
    root: Path,
    *,
    revision: int = 1,
    calculated_at: datetime = NOW,
) -> StandardProficiencyResultSnapshot:
    stored_grade_item = write_grade_item_revision(root, grade_item()).stored
    stored_scale = write_proficiency_scale_revision(root, scale()).stored.scale
    stored_policy = write_standard_proficiency_policy_revision(
        root,
        policy(stored_scale),
    ).stored.policy
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=GradeItemAggregationBasis(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            stored_grade_item.revision_sha256,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(stored_scale),
        entries=(),
    )
    outcome = calculate_standard_proficiency(inputs, stored_policy, stored_scale)
    return create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=calculated_at,
    )


def revision_target(revision: int) -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        selection="revision",
        result_revision=revision,
    )


def current_target() -> GradeItemProficiencyTraceTarget:
    return GradeItemProficiencyTraceTarget(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        selection="current",
    )


def test_target_requires_explicit_current_or_revision() -> None:
    with pytest.raises(ExplanationTraceTargetError):
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            "current",
            1,
        )
    with pytest.raises(ExplanationTraceTargetError):
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            "revision",
            None,
        )


def test_current_target_requires_explicit_selected_result(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    write_standard_proficiency_result_revision(root, snapshot(root))

    with pytest.raises(ExplanationTraceNotFoundError, match="current selected"):
        explain_grade_item_proficiency(root, current_target())


def test_exact_historical_result_is_not_replaced_by_current(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    first = snapshot(root)
    second = snapshot(
        root,
        revision=2,
        calculated_at=NOW + timedelta(minutes=1),
    )
    write_standard_proficiency_result_revision(root, first)
    write_standard_proficiency_result_revision(root, second)
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )

    historical = explain_grade_item_proficiency(root, revision_target(1))
    current = explain_grade_item_proficiency(root, current_target())

    assert historical.result_revision == 1
    assert historical.selection_state == "historical"
    assert historical.current_result_revision == 2
    assert current.result_revision == 2
    assert current.selection_state == "selected_current"
    assert current.current_result_revision == 2


def test_explanation_reverifies_exact_external_dependencies(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    value = snapshot(root)
    write_standard_proficiency_result_revision(root, value)

    policy_path = standard_proficiency_policy_revision_path(
        root,
        CLASS_ID,
        value.policy_reference.policy_id,
        value.policy_reference.policy_revision,
    )
    policy_path.unlink()
    Path(str(policy_path) + ".sha256").unlink()

    # The raw #34 result is intentionally replayable without current policy state;
    # #42 explanation must instead fail because its exact provenance edge is gone.
    with pytest.raises(ExplanationTraceIntegrityError, match="policy"):
        explain_grade_item_proficiency(root, revision_target(1))


def test_projection_preserves_insufficient_evidence_not_lowest_level(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    write_standard_proficiency_result_revision(root, snapshot(root))

    explanation = explain_grade_item_proficiency(root, revision_target(1))

    assert explanation.calculation.status == "insufficient_evidence"
    assert explanation.calculation.proficiency_level_id is None
    assert explanation.calculation.performance_observation_count == 0
    assert explanation.calculation.insufficiency_reasons[0].kind == (
        "no_performance_evidence"
    )
    assert explanation.evidence == ()


def test_json_and_text_renderers_are_deterministic_and_read_only(
    tmp_path: Path,
) -> None:
    root = workspace(tmp_path)
    write_standard_proficiency_result_revision(root, snapshot(root))

    explanation = explain_grade_item_proficiency(root, revision_target(1))
    first = grade_item_proficiency_explanation_to_json_bytes(explanation)
    second = grade_item_proficiency_explanation_to_json_bytes(explanation)
    text = render_grade_item_proficiency_explanation_text(explanation)

    assert first == second
    assert first.endswith(b"\n")
    assert b'"selection_state": "no_current_selection"' in first
    assert b'"status": "insufficient_evidence"' in first
    assert "no calculated proficiency level" in text
    assert "Evidence candidates: 0" in text
