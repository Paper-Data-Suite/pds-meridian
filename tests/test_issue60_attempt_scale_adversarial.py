from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import meridian.reassessment_storage as reassessment_storage
from meridian.evidence import NativePointValue
from meridian.grade_policy import (
    GradePolicyItemParticipation,
    GradePolicyItemReference,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeValidationError,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from tests import test_issue50_cross_producer_acceptance as issue50
from tests import test_issue99_exact_scale_authority as issue99
from tests import test_standards_grade as standards
from tests.cross_producer_attempts_support import prepare_attempt_workspace
from tests.cross_producer_test_support import SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import SCOREFORM_WORK


def _scoreform_points_by_attempt(scenario: object) -> dict[int, Decimal]:
    inventory = scenario.projected["scoreform"].inventory
    result: dict[int, Decimal] = {}
    for item in inventory.items:
        if (
            item.subject is None
            or item.subject.student_id != SHARED_STUDENT_ID
            or item.result_kind != "attempt_points"
            or not isinstance(item.value, NativePointValue)
        ):
            continue
        sequence = item.target.sequence
        if sequence is None:
            raise AssertionError("ScoreForm attempt must carry a sequence.")
        result[sequence] = Decimal(str(item.value.earned))
    return result


def test_lower_score_explicit_replacement_controls_conventional_grade(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    root = scenario.mixed.root
    points = _scoreform_points_by_attempt(scenario)
    assert points == {1: Decimal("2"), 2: Decimal("1")}
    assert points[2] < points[1]

    item, item_sha256 = issue50._install_conventional_grade_item(root)
    membership, membership_sha256 = issue50._install_membership(
        root,
        item,
        item_sha256,
    )
    issue50._install_eligibility(
        root,
        scenario,
        membership,
        membership_sha256,
    )
    issue50._install_attempt_and_reassessment(
        root,
        scenario,
        membership_sha256,
    )
    issue50._install_grade_policy(root, item_sha256)

    reassessment = reassessment_storage.resolve_current_reassessment(
        root,
        issue50.CLASS_ID,
        issue50.GRADE_ITEM_ID,
        SCOREFORM_WORK,
        SHARED_STUDENT_ID,
        authorized_snapshot=scenario.authorized["scoreform"],
    )
    assert reassessment.status == "resolved"
    assert tuple(
        attempt.native.sequence for attempt in reassessment.contributing_attempts
    ) == (2,)

    work_evidence = (
        issue50.ConventionalGradeWorkEvidenceSpec(
            grade_item_id=issue50.GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(scenario.authorized["scoreform"],),
        ),
    )
    assembled = issue50.assemble_conventional_grade_calculation(
        root,
        issue50.CLASS_ID,
        SHARED_STUDENT_ID,
        issue50.PERIOD,
        issue50.CALENDAR_REVISION,
        work_evidence,
    )

    assert assembled.outcome.status == "calculated"
    assert assembled.outcome.rounded_grade == Decimal("33.33")
    assert len(assembled.inputs.items) == 1
    exact = assembled.inputs.items[0]
    assert exact.status == "points"
    assert exact.earned == Decimal("1")
    assert exact.possible == Decimal("3")
    provenance_kinds = {entry.kind for entry in exact.provenance}
    assert "attempt_selection" in provenance_kinds
    assert "reassessment" in provenance_kinds


def test_multiple_point_observations_do_not_self_rank_without_authority() -> None:
    participation = GradePolicyItemParticipation(
        GradePolicyItemReference(
            standards.CLASS_ID,
            "issue60_multi_attempt",
            1,
            "f" * 64,
        ),
        None,
        None,
        Decimal("3"),
    )

    from meridian.conventional_grade import resolve_conventional_grade_item_input

    resolved = resolve_conventional_grade_item_input(
        participation=participation,
        student_id=standards.STUDENT_ID,
        target_period=standards.PERIOD,
        calendar_revision=1,
        point_observations=(
            NativePointValue(2, 3),
            NativePointValue(1, 3),
        ),
        no_point_state="missing",
    )

    assert resolved.status == "unresolved"
    assert resolved.earned is None
    assert resolved.possible is None
    assert resolved.reason_codes == ("multiple_point_observations",)


@pytest.mark.parametrize(
    "wrong_scale",
    (
        ProficiencyScaleReference(
            standards.CLASS_ID,
            "other_scale",
            1,
            standards.SHA_A,
        ),
        ProficiencyScaleReference(
            standards.CLASS_ID,
            "course_scale",
            2,
            standards.SHA_A,
        ),
        ProficiencyScaleReference(
            standards.CLASS_ID,
            "course_scale",
            1,
            "e" * 64,
        ),
    ),
    ids=("scale-id", "scale-revision", "scale-digest"),
)
def test_weighted_mean_rejects_exact_scale_mismatch_without_using_label(
    wrong_scale: ProficiencyScaleReference,
) -> None:
    configuration = standards.configuration(
        ("std.issue60.scale", "1"),
        minimum=1,
    )
    value = standards.policy(configuration)
    outcome = calculate_standards_grade(
        standards.calculation_input(
            value,
            standards.calculated(
                configuration.standards[0],
                "advanced",
                scale=wrong_scale,
            ),
        )
    )

    assert outcome.status == "blocked"
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    result = outcome.standard_results[0]
    assert result.source_state == "unresolved"
    assert result.action == "blocking"
    assert result.proficiency_level_id is None
    assert result.converted_grade_value is None
    assert "proficiency_scale_mismatch" in result.reason_codes


def test_profile_strategy_rejects_mismatched_result_scale_before_band_logic() -> None:
    exact_scale = issue99.scale()
    configuration = issue99.profile_configuration(exact_scale)
    value = issue99.policy(configuration)
    wrong_scale = ProficiencyScaleReference(
        issue99.CLASS_ID,
        "course_scale",
        2,
        "e" * 64,
    )
    mismatched = replace(
        issue99.standard_input(configuration, "meeting"),
        target_scale=wrong_scale,
    )

    inputs = create_standards_grade_calculation_input(
        policy=value,
        activation=issue99.activation(value),
        student_id=issue99.STUDENT_ID,
        target_period=issue99.PERIOD,
        calendar_revision=1,
        standards=(mismatched,),
        target_scale_definition=exact_scale,
    )
    outcome = calculate_standards_grade(inputs)

    assert outcome.status == "blocked"
    assert outcome.base_unrounded_grade is None
    assert outcome.unrounded_grade is None
    assert outcome.rounded_grade is None
    assert outcome.profile_evaluation is None
    assert outcome.selected_profile_band_id is None
    result = outcome.standard_results[0]
    assert result.source_state == "unresolved"
    assert result.proficiency_level_id is None
    assert "proficiency_scale_mismatch" in result.reason_codes


def test_profile_strategy_rejects_same_labels_but_different_scale_bytes() -> None:
    exact_scale = issue99.scale()
    configuration = issue99.profile_configuration(exact_scale)
    value = issue99.policy(configuration)

    same_labels_different_authority = issue99.scale(
        description="Same level IDs and order, different canonical authority."
    )

    with pytest.raises(
        StandardsGradeValidationError,
        match="match exact policy target_scale",
    ):
        create_standards_grade_calculation_input(
            policy=value,
            activation=issue99.activation(value),
            student_id=issue99.STUDENT_ID,
            target_period=issue99.PERIOD,
            calendar_revision=1,
            standards=(issue99.standard_input(configuration, "meeting"),),
            target_scale_definition=same_labels_different_authority,
        )
