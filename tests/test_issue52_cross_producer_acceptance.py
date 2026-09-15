from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.standards import write_workspace_standards_library

import tests.test_issue50_cross_producer_acceptance as issue50_acceptance
import tests.test_issue51_cross_producer_acceptance as issue51_acceptance
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.conventional_grade_storage import (
    get_current_conventional_grade_result_revision,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    HybridGradeConfiguration,
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
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_assembly import assemble_hybrid_grade_calculation
from meridian.hybrid_grade_result import (
    assess_hybrid_grade_result_freshness,
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.hybrid_grade_storage import (
    get_current_hybrid_grade_result_revision,
    load_current_hybrid_grade_result,
    select_hybrid_grade_result_revision,
    write_hybrid_grade_result_revision,
)
from meridian.standards_grade_storage import (
    get_current_standards_grade_result_revision,
)
from tests.cross_producer_academic_period_support import prepare_period_scenario
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    PERIOD_ID,
    SCHOOL_YEAR,
)
from tests.cross_producer_test_support import SHARED_STANDARD_ID, SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import CLASS_ID, SCOREFORM_WORK

PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
CALENDAR_REVISION = 1
HYBRID_POLICY_ID = "issue52_bounded_hybrid_grade"
RESULT_TIME = datetime(2026, 9, 14, 23, 30, tzinfo=UTC)
CONVENTIONAL_WEIGHT = Decimal("0.60")
STANDARDS_WEIGHT = Decimal("0.40")


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


def _install_hybrid_policy(
    scenario: object,
    item_sha256: str,
) -> None:
    aggregation = scenario.aggregation  # type: ignore[attr-defined]
    root = aggregation.workspace.mixed.root
    write_workspace_standards_library(root, aggregation.standard_library)
    scale = aggregation.target_scale
    assert {level.level_id for level in scale.scale.levels} == set(
        issue51_acceptance.CONVERSIONS
    )

    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=HYBRID_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 52 bounded hybrid Grade policy",
        calculation_family="hybrid",
        configuration=HybridGradeConfiguration(
            conventional=ConventionalGradeConfiguration(
                mode="total_points",
                items=(
                    GradePolicyItemParticipation(
                        grade_item=GradePolicyItemReference(
                            CLASS_ID,
                            issue50_acceptance.GRADE_ITEM_ID,
                            1,
                            item_sha256,
                        ),
                        category_id=None,
                        weight=None,
                        possible_points=Decimal("3"),
                    ),
                ),
                categories=(),
            ),
            standards_based=StandardsBasedGradeConfiguration(
                target_scale=scale.reference,
                standards=(
                    StandardGradeParticipation(
                        standard_id=SHARED_STANDARD_ID,
                        weight=Decimal("1"),
                    ),
                ),
                conversions=tuple(
                    ProficiencyGradeConversion(level_id, grade_value)
                    for level_id, grade_value in issue51_acceptance.CONVERSIONS.items()
                ),
                aggregation_strategy="weighted_mean",
                minimum_calculated_results=1,
            ),
            conventional_weight=CONVENTIONAL_WEIGHT,
            standards_weight=STANDARDS_WEIGHT,
        ),
        state_treatment=_state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #52 one-policy hybrid cross-producer acceptance.",
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
        rationale="Activate the exact issue #52 hybrid Grade policy.",
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


def test_one_hybrid_policy_composes_real_conventional_and_proficiency_paths(
    tmp_path: Path,
) -> None:
    scenario = prepare_period_scenario(
        tmp_path / "issue52_cross_producer",
        native_state_handling="noncontributing",
    )
    aggregation = scenario.aggregation
    attempt_workspace = aggregation.workspace
    root = attempt_workspace.mixed.root
    period_outcome = scenario.preview.calculation.outcome
    assert period_outcome.status == "calculated"
    assert period_outcome.proficiency_level_id in issue51_acceptance.CONVERSIONS

    issue51_acceptance._persist_selected_period_result(scenario)

    producer_before = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }

    item, item_sha256 = issue50_acceptance._install_conventional_grade_item(root)
    membership, membership_sha256 = issue50_acceptance._install_membership(
        root,
        item,
        item_sha256,
    )
    issue50_acceptance._install_eligibility(
        root,
        attempt_workspace,
        membership,
        membership_sha256,
    )
    issue50_acceptance._install_attempt_and_reassessment(
        root,
        attempt_workspace,
        membership_sha256,
    )
    _install_hybrid_policy(scenario, item_sha256)

    work_evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50_acceptance.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(attempt_workspace.authorized["scoreform"],),
        ),
    )

    assert get_current_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None
    assert get_current_standards_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None

    assembly = assemble_hybrid_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    assert assembly.policy.policy.calculation_family == "hybrid"
    assert assembly.conventional.outcome.status == "calculated"
    assert assembly.conventional.outcome.rounded_grade == Decimal("33.33")
    assert assembly.conventional.inputs.items[0].earned == Decimal("1")
    assert assembly.conventional.inputs.items[0].possible == Decimal("3")

    expected_standards_grade = issue51_acceptance.CONVERSIONS[
        period_outcome.proficiency_level_id
    ]
    assert assembly.standards_based.outcome.status == "calculated"
    assert assembly.standards_based.outcome.unrounded_grade == expected_standards_grade

    outcome = assembly.outcome
    assert outcome.status == "calculated"
    assert outcome.active_weight == Decimal("1.00")
    assert outcome.conventional_component.source_status == "calculated"
    assert outcome.conventional_component.configured_weight == CONVENTIONAL_WEIGHT
    assert outcome.standards_component.source_status == "calculated"
    assert outcome.standards_component.configured_weight == STANDARDS_WEIGHT
    assert outcome.conventional_component.unrounded_grade == (
        assembly.conventional.outcome.unrounded_grade
    )
    assert outcome.standards_component.unrounded_grade == (
        assembly.standards_based.outcome.unrounded_grade
    )
    with localcontext() as context:
        context.prec = 100
        expected_weighted_numerator = (
            outcome.conventional_component.weighted_contribution
            + outcome.standards_component.weighted_contribution
        )
    assert outcome.weighted_numerator == expected_weighted_numerator
    rounded_component_mix = (
        assembly.conventional.outcome.rounded_grade * CONVENTIONAL_WEIGHT
        + assembly.standards_based.outcome.rounded_grade * STANDARDS_WEIGHT
    )
    assert outcome.unrounded_grade != rounded_component_mix
    assert outcome.rounded_grade == outcome.unrounded_grade.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    snapshot = create_hybrid_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=RESULT_TIME,
    )
    written = write_hybrid_grade_result_revision(
        root,
        snapshot,
        work_evidence=work_evidence,
    )
    assert written.disposition == "created"
    assert get_current_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None

    selected = select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    assert selected.stored.reference == written.stored.reference

    current = load_current_hybrid_grade_result(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    assert current is not None
    assert current.reference == written.stored.reference
    assert calculate_hybrid_grade(current.snapshot.inputs) == current.snapshot.outcome

    payload = hybrid_grade_result_snapshot_to_json_bytes(current.snapshot)
    assert hybrid_grade_result_snapshot_from_json_bytes(payload) == current.snapshot
    assert hybrid_grade_result_snapshot_to_json_bytes(
        hybrid_grade_result_snapshot_from_json_bytes(payload)
    ) == payload

    refreshed = assemble_hybrid_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    freshness = assess_hybrid_grade_result_freshness(
        current.snapshot,
        refreshed.inputs,
    )
    assert freshness.status == "current"
    assert freshness.reasons == ()

    assert get_current_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None
    assert get_current_standards_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None

    producer_after = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }
    assert producer_after == producer_before
