"""Academic Period carry-forward support for Meridian issue #44."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

import meridian.standards_evidence_storage as standards_storage
from meridian.academic_period_calculation_assembly_workflow import (
    AcademicPeriodCalculationCandidateSpec,
    AcademicPeriodMembershipSpec,
    BoundedAcademicPeriodCalculationPreview,
    build_bounded_academic_period_calculation_preview,
)
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
)
from meridian.academic_period_proficiency_storage import (
    StoredAcademicPeriodProficiencyAggregationPolicy,
    select_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_policy_revision,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
    STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
    NativeStateHandling,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    StandardProficiencyResultSnapshot,
    calculate_standard_proficiency,
)
from meridian.standards_proficiency_storage import (
    StoredStandardProficiencyResult,
    load_current_standard_proficiency_result,
    select_standard_proficiency_policy_revision,
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)
from tests.cross_producer_aggregation_support import (
    Issue44AggregationScenario,
    prepare_aggregation_scenario,
)
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    NOW,
    PERIOD_ID,
    SCHOOL_YEAR,
)
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
)


@dataclass(frozen=True, slots=True)
class Issue44PeriodScenario:
    """Exact selected #34 result and #35 preview basis."""

    aggregation: Issue44AggregationScenario
    grade_item_result: StoredStandardProficiencyResult
    period_policy: StoredAcademicPeriodProficiencyAggregationPolicy
    preview: BoundedAcademicPeriodCalculationPreview


def _grade_item_policy(
    scenario: Issue44AggregationScenario,
    *,
    policy_id: str,
    native_state_handling: NativeStateHandling,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=scenario.grade_item.class_id,
        policy_id=policy_id,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 44 persisted mixed Grade Item policy",
        target_scale=scenario.target_scale.reference,
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(),
        native_state_handling=native_state_handling,
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #44 Academic Period carry-forward basis.",
        revised_at=NOW,
    )


def _persist_selected_grade_item_result(
    scenario: Issue44AggregationScenario,
    *,
    native_state_handling: NativeStateHandling,
) -> StoredStandardProficiencyResult:
    inputs = standards_storage.resolve_standard_aggregation_inputs(
        scenario.workspace.mixed.root,
        scenario.grade_item,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        scenario.target_scale.reference,
        scenario.bindings,
        standards_library=scenario.standard_library,
    )
    policy = _grade_item_policy(
        scenario,
        policy_id=(
            "issue44_period_nonblocking"
            if native_state_handling == "noncontributing"
            else "issue44_period_blocking"
        ),
        native_state_handling=native_state_handling,
    )
    stored_policy = write_standard_proficiency_policy_revision(
        scenario.workspace.mixed.root,
        policy,
    ).stored
    select_standard_proficiency_policy_revision(
        scenario.workspace.mixed.root,
        policy.class_id,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )
    outcome = calculate_standard_proficiency(
        inputs,
        stored_policy.policy,
        scenario.target_scale.scale,
    )
    snapshot = StandardProficiencyResultSnapshot(
        schema_version=STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
        class_id=scenario.grade_item.class_id,
        grade_item_id=scenario.grade_item.grade_item_id,
        student_id=SHARED_STUDENT_ID,
        standard_id=SHARED_STANDARD_ID,
        result_revision=1,
        supersedes_revision=None,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=inputs.sha256,
        policy_reference=stored_policy.reference,
        target_scale=scenario.target_scale.reference,
        outcome=outcome,
        calculated_at=NOW,
    )
    stored = write_standard_proficiency_result_revision(
        scenario.workspace.mixed.root,
        snapshot,
    ).stored
    select_standard_proficiency_result_revision(
        scenario.workspace.mixed.root,
        snapshot.class_id,
        snapshot.grade_item_id,
        snapshot.student_id,
        snapshot.standard_id,
        snapshot.result_revision,
        expected_current_result_revision=None,
    )
    current = load_current_standard_proficiency_result(
        scenario.workspace.mixed.root,
        snapshot.class_id,
        snapshot.grade_item_id,
        snapshot.student_id,
        snapshot.standard_id,
    )
    if current is None or current.reference != stored.reference:
        raise AssertionError("Issue #44 exact #34 result must be explicitly current.")
    return current


def _persist_period_policy(
    scenario: Issue44AggregationScenario,
) -> StoredAcademicPeriodProficiencyAggregationPolicy:
    policy = AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=scenario.grade_item.class_id,
        policy_id="issue44_academic_period",
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 44 Academic Period proficiency",
        target_scale=scenario.target_scale.reference,
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", ACTOR_ID),
        rationale="Issue #44 producer-neutral Academic Period aggregation.",
        revised_at=NOW,
    )
    stored = write_academic_period_proficiency_policy_revision(
        scenario.workspace.mixed.root,
        policy,
    ).stored
    select_academic_period_proficiency_policy_revision(
        scenario.workspace.mixed.root,
        policy.class_id,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )
    return stored


def _candidate_spec(
    scenario: Issue44AggregationScenario,
    result: StoredStandardProficiencyResult,
    *,
    reverse_memberships: bool = False,
) -> AcademicPeriodCalculationCandidateSpec:
    modules = ("scoreform", "quillan", "concord")
    memberships = tuple(
        AcademicPeriodMembershipSpec(
            work=scenario.workspace.mixed.publications[module_id].work,
            membership_revision=1,
            membership_sha256=scenario.workspace.membership_digests[module_id],
        )
        for module_id in modules
    )
    if reverse_memberships:
        memberships = tuple(reversed(memberships))
    return AcademicPeriodCalculationCandidateSpec(
        grade_item_id=scenario.grade_item.grade_item_id,
        grade_item_revision=scenario.grade_item.grade_item_revision,
        grade_item_revision_sha256=scenario.grade_item.grade_item_revision_sha256,
        memberships=memberships,
        result_revision=result.snapshot.result_revision,
        result_sha256=result.result_sha256,
    )


def _build_period_preview(
    aggregation: Issue44AggregationScenario,
    result: StoredStandardProficiencyResult,
    period_policy: StoredAcademicPeriodProficiencyAggregationPolicy,
    *,
    reverse_memberships: bool = False,
) -> BoundedAcademicPeriodCalculationPreview:
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    return build_bounded_academic_period_calculation_preview(
        aggregation.workspace.mixed.root,
        target,
        SHARED_STUDENT_ID,
        SHARED_STANDARD_ID,
        (
            _candidate_spec(
                aggregation,
                result,
                reverse_memberships=reverse_memberships,
            ),
        ),
        period_policy.reference,
    )


def rebuild_period_preview(
    scenario: Issue44PeriodScenario,
    *,
    reverse_memberships: bool = False,
) -> BoundedAcademicPeriodCalculationPreview:
    """Re-run #35 over the same exact persisted basis with caller reordering."""
    return _build_period_preview(
        scenario.aggregation,
        scenario.grade_item_result,
        scenario.period_policy,
        reverse_memberships=reverse_memberships,
    )


def prepare_period_scenario(
    tmp_path: Path,
    *,
    native_state_handling: NativeStateHandling,
    reverse_memberships: bool = False,
) -> Issue44PeriodScenario:
    """Persist a mixed #34 result and carry it through exact #35 assembly."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    aggregation = prepare_aggregation_scenario(tmp_path)
    result = _persist_selected_grade_item_result(
        aggregation,
        native_state_handling=native_state_handling,
    )
    period_policy = _persist_period_policy(aggregation)
    preview = _build_period_preview(
        aggregation,
        result,
        period_policy,
        reverse_memberships=reverse_memberships,
    )
    return Issue44PeriodScenario(
        aggregation=aggregation,
        grade_item_result=result,
        period_policy=period_policy,
        preview=preview,
    )
