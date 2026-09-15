from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.standards import write_workspace_standards_library

from meridian.academic_period_proficiency import (
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    get_current_academic_period_proficiency_result_revision,
    load_current_academic_period_proficiency_result,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_policy_activation_storage import (
    select_grade_policy_activation_revision,
    write_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import write_grade_policy_revision
from meridian.proficiency_mapping_storage import select_proficiency_scale_revision
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_assembly import assemble_standards_grade_calculation
from meridian.standards_grade_result import (
    assess_standards_grade_result_freshness,
    create_standards_grade_result_snapshot,
    standards_grade_result_snapshot_from_json_bytes,
    standards_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade_storage import (
    get_current_standards_grade_result_revision,
    load_current_standards_grade_result,
    select_standards_grade_result_revision,
    write_standards_grade_result_revision,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    PERIOD_ID,
    SCHOOL_YEAR,
)
from tests.cross_producer_test_support import SHARED_STANDARD_ID, SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import CLASS_ID

PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
CALENDAR_REVISION = 1
GRADE_POLICY_ID = "issue51_standards_grade"
RESULT_TIME = datetime(2026, 9, 13, 22, 0, tzinfo=UTC)
CONVERSIONS = {
    "beginning": Decimal("55"),
    "developing": Decimal("70"),
    "proficient": Decimal("85"),
    "advanced": Decimal("100"),
}


def _tree_bytes(root: Path, module_id: str) -> dict[str, bytes]:
    base = root / "classes" / CLASS_ID / "modules" / module_id
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def _persist_selected_period_result(scenario) -> None:
    root = scenario.aggregation.workspace.mixed.root
    scale_reference = scenario.aggregation.target_scale.reference
    selected_scale = select_proficiency_scale_revision(
        root,
        scale_reference.class_id,
        scale_reference.scale_id,
        scale_reference.scale_revision,
        expected_current_scale_revision=None,
    )
    assert selected_scale.stored.reference == scale_reference

    preview = scenario.preview
    snapshot = create_academic_period_proficiency_result_snapshot(
        preview.inputs,
        preview.calculation.outcome,
        result_revision=1,
        calculated_at=RESULT_TIME,
    )
    stored = write_academic_period_proficiency_result_revision(root, snapshot).stored
    assert (
        get_current_academic_period_proficiency_result_revision(
            root,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            SHARED_STUDENT_ID,
            SHARED_STANDARD_ID,
        )
        is None
    )
    selected = select_academic_period_proficiency_result_revision(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected.stored.reference == stored.reference
    current = load_current_academic_period_proficiency_result(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
    )
    assert current is not None
    assert current.reference == stored.reference


def _install_standards_grade_policy(scenario) -> None:
    root = scenario.aggregation.workspace.mixed.root
    write_workspace_standards_library(
        root,
        scenario.aggregation.standard_library,
    )
    scale = scenario.aggregation.target_scale
    assert {level.level_id for level in scale.scale.levels} == set(CONVERSIONS)
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=GRADE_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 51 standards-based Grade policy",
        calculation_family="standards_based",
        configuration=StandardsBasedGradeConfiguration(
            target_scale=scale.reference,
            standards=(
                StandardGradeParticipation(
                    standard_id=SHARED_STANDARD_ID,
                    weight=Decimal("1"),
                ),
            ),
            conversions=tuple(
                ProficiencyGradeConversion(level_id, grade_value)
                for level_id, grade_value in CONVERSIONS.items()
            ),
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
        ),
        state_treatment=_state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #51 cross-producer standards Grade acceptance.",
        revised_at=RESULT_TIME,
    )
    stored_policy = write_grade_policy_revision(root, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=CALENDAR_REVISION,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Activate the exact issue #51 standards Grade policy.",
        decided_at=RESULT_TIME,
    )
    write_grade_policy_activation_revision(root, activation)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        PERIOD,
        1,
        expected_current_revision=None,
    )


def test_cross_producer_proficiency_flows_through_selected_period_result_to_grade(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path / "issue51_cross_producer",
        native_state_handling="noncontributing",
    )
    root = scenario.aggregation.workspace.mixed.root
    period_outcome = scenario.preview.calculation.outcome
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id in CONVERSIONS

    _persist_selected_period_result(scenario)
    producer_before = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }
    _install_standards_grade_policy(scenario)

    assembly = assemble_standards_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    expected_grade = CONVERSIONS[period_outcome.proficiency_level_id]
    assert assembly.outcome.status == "calculated"
    assert assembly.outcome.actual_calculated_result_count == 1
    assert assembly.outcome.minimum_calculated_results == 1
    assert assembly.outcome.active_weight == Decimal("1")
    assert assembly.outcome.unrounded_grade == expected_grade
    assert assembly.outcome.rounded_grade == expected_grade.quantize(Decimal("0.01"))
    assert len(assembly.outcome.standard_results) == 1
    standard_result = assembly.outcome.standard_results[0]
    assert standard_result.standard_id == SHARED_STANDARD_ID
    assert standard_result.source_state == "calculated"
    assert standard_result.action == "contribute"
    assert standard_result.proficiency_level_id == period_outcome.proficiency_level_id
    assert standard_result.converted_grade_value == expected_grade
    assert standard_result.result_reference is not None

    snapshot = create_standards_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=RESULT_TIME,
    )
    written = write_standards_grade_result_revision(root, snapshot)
    assert written.disposition == "created"
    assert (
        get_current_standards_grade_result_revision(
            root,
            CLASS_ID,
            SHARED_STUDENT_ID,
            PERIOD,
            CALENDAR_REVISION,
        )
        is None
    )

    selected = select_standards_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    assert selected.stored.reference == written.stored.reference
    current = load_current_standards_grade_result(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    assert current is not None
    assert current.reference == written.stored.reference
    assert (
        calculate_standards_grade(current.snapshot.inputs)
        == current.snapshot.outcome
    )

    payload = standards_grade_result_snapshot_to_json_bytes(current.snapshot)
    assert standards_grade_result_snapshot_from_json_bytes(payload) == current.snapshot
    refreshed = assemble_standards_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    freshness = assess_standards_grade_result_freshness(
        current.snapshot,
        refreshed.inputs,
    )
    assert freshness.status == "current"
    assert freshness.reasons == ()

    producer_after = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }
    assert producer_after == producer_before
