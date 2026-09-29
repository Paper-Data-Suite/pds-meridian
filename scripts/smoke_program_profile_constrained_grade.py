"""Installed Issue #99 profile-constrained standards Grade acceptance."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import smoke_program_standards_grade as base  # type: ignore

from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    ProficiencyGradeConversion,
    ProfileConstraintConfiguration,
    ProfileGradeBand,
    ProfilePredicate,
    ProfileStandardGroup,
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
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    calculate_standards_grade,
)
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

PROFILE_POLICY_ID = "issue99_profile_constrained_grade"
PROFILE_BASELINE_NAME = "issue99-profile-constrained-grade-baseline.json"


def _verify_installed() -> None:
    base._verify_installed_composition()
    base._installed_origin("meridian.standards_grade_profile")
    base._require(
        STANDARDS_GRADE_ALGORITHM_VERSION == "2",
        "Issue #99 requires standards Grade algorithm version 2.",
    )


def _install_policy(workspace: Path, scale: base.StoredProficiencyScale) -> None:
    configuration = StandardsBasedGradeConfiguration(
        target_scale=scale.reference,
        standards=(StandardGradeParticipation(base.STANDARD_ID, Decimal("1")),),
        conversions=tuple(
            ProficiencyGradeConversion(level_id, value)
            for level_id, value in base.CONVERSIONS.items()
        ),
        aggregation_strategy="profile_constrained_mean",
        minimum_calculated_results=1,
        profile_constraints=ProfileConstraintConfiguration(
            groups=(ProfileStandardGroup("focus", (base.STANDARD_ID,)),),
            bands=(
                ProfileGradeBand(
                    "high",
                    1,
                    Decimal("95"),
                    Decimal("100"),
                    (
                        ProfilePredicate(
                            "all_focus_proficient",
                            "all_at_or_above",
                            "focus",
                            "proficient",
                        ),
                    ),
                ),
                ProfileGradeBand(
                    "fallback",
                    2,
                    Decimal("0"),
                    Decimal("94.99"),
                    (),
                ),
            ),
            fallback_band_id="fallback",
        ),
    )
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=base.CLASS_ID,
        policy_id=PROFILE_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 99 installed profile-constrained Grade",
        calculation_family="standards_based",
        configuration=configuration,
        state_treatment=base._state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state", "blocking"
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", base.ACTOR_ID),
        rationale="Issue #99 installed exact-wheel acceptance.",
        revised_at=base.NOW,
    )
    stored = write_grade_policy_revision(workspace, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=base.CLASS_ID,
        target_period=base.PERIOD,
        calendar_revision=base.CALENDAR_REVISION,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored.reference,
        actor=GradePolicyActor("teacher", base.ACTOR_ID),
        rationale="Activate Issue #99 profile Grade policy.",
        decided_at=base.NOW,
    )
    write_grade_policy_activation_revision(workspace, activation)
    select_grade_policy_activation_revision(
        workspace,
        base.CLASS_ID,
        base.PERIOD,
        1,
        expected_current_revision=None,
    )


def _calculate(workspace: Path) -> dict[str, object]:
    assembly = assemble_standards_grade_calculation(
        workspace,
        base.CLASS_ID,
        base.STUDENT_ID,
        base.PERIOD,
        base.CALENDAR_REVISION,
    )
    outcome = assembly.outcome
    base._require(outcome.status == "calculated", "Profile Grade did not calculate.")
    base._require(outcome.base_unrounded_grade == Decimal("90"), "Base mean mismatch.")
    base._require(outcome.selected_profile_band_id == "high", "Band mismatch.")
    base._require(outcome.profile_adjustment == "floor", "Adjustment mismatch.")
    base._require(outcome.unrounded_grade == Decimal("95"), "Adjusted Grade mismatch.")
    base._require(outcome.rounded_grade == Decimal("95.00"), "Rounded Grade mismatch.")
    base._require(
        assembly.inputs.target_scale_definition == assembly.target_scale.scale,
        "Exact ordered scale authority was not bound.",
    )
    evaluation = outcome.profile_evaluation
    base._require(evaluation is not None, "Profile evaluation is missing.")
    assert evaluation is not None
    base._require(evaluation.bands[0].status == "matched", "High band did not match.")
    base._require(
        evaluation.bands[0].predicates[0].status == "matched",
        "Profile predicate did not match.",
    )

    repeated = assemble_standards_grade_calculation(
        workspace, base.CLASS_ID, base.STUDENT_ID, base.PERIOD, base.CALENDAR_REVISION
    )
    base._require(repeated.inputs == assembly.inputs, "Assembly is not deterministic.")
    base._require(repeated.outcome == outcome, "Outcome is not deterministic.")

    snapshot = create_standards_grade_result_snapshot(
        assembly.inputs, outcome, result_revision=1, calculated_at=base.NOW
    )
    written = write_standards_grade_result_revision(workspace, snapshot)
    base._require(written.disposition == "created", "Profile Grade write failed.")
    base._require(
        get_current_standards_grade_result_revision(
            workspace,
            base.CLASS_ID,
            base.STUDENT_ID,
            base.PERIOD,
            base.CALENDAR_REVISION,
        )
        is None,
        "Write must not select.",
    )
    selected = select_standards_grade_result_revision(
        workspace,
        base.CLASS_ID,
        base.STUDENT_ID,
        base.PERIOD,
        base.CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    base._require(
        selected.stored.reference == written.stored.reference,
        "Selection reference mismatch.",
    )
    current = load_current_standards_grade_result(
        workspace,
        base.CLASS_ID,
        base.STUDENT_ID,
        base.PERIOD,
        base.CALENDAR_REVISION,
    )
    base._require(current is not None, "Selected profile Grade is missing.")
    assert current is not None
    base._require(
        calculate_standards_grade(current.snapshot.inputs) == current.snapshot.outcome,
        "Stored profile Grade does not reproduce.",
    )
    encoded = standards_grade_result_snapshot_to_json_bytes(current.snapshot)
    base._require(
        standards_grade_result_snapshot_from_json_bytes(encoded) == current.snapshot,
        "Canonical profile round-trip failed.",
    )
    refreshed = assemble_standards_grade_calculation(
        workspace, base.CLASS_ID, base.STUDENT_ID, base.PERIOD, base.CALENDAR_REVISION
    )
    freshness = assess_standards_grade_result_freshness(
        current.snapshot, refreshed.inputs
    )
    base._require(freshness.status == "current", "Profile Grade is stale.")
    base._require(freshness.reasons == (), "Profile Grade has stale reasons.")
    return {
        "result_revision": current.snapshot.result_revision,
        "result_sha256": current.result_sha256,
        "calculation_fingerprint": current.snapshot.calculation_fingerprint,
        "rounded_grade": str(current.snapshot.outcome.rounded_grade),
        "upstream": base._upstream_snapshot(workspace),
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: smoke_program_profile_constrained_grade.py <workspace>"
        )
    _verify_installed()
    workspace = Path(sys.argv[1]).resolve()
    calendar = base._seed_core(workspace)
    scale = base._persist_scale(workspace)
    standard_policy = base._persist_standard_policy(workspace, scale)
    scoreform = base._persist_grade_item_result(
        workspace, base.SCOREFORM_WORK, "proficient", scale, standard_policy
    )
    quillan = base._persist_grade_item_result(
        workspace, base.QUILLAN_WORK, "proficient", scale, standard_policy
    )
    base._persist_period_result(workspace, calendar, scale, (scoreform, quillan))
    upstream_before = base._upstream_snapshot(workspace)
    _install_policy(workspace, scale)
    result = _calculate(workspace)
    base._require(
        base._upstream_snapshot(workspace) == upstream_before,
        "Profile Grade mutated producer/proficiency source state.",
    )
    result["upstream"] = upstream_before
    (workspace / PROFILE_BASELINE_NAME).write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #99 installed profile-constrained Grade acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
