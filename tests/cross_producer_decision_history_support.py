"""Teacher decision-history support for Meridian issue #44."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import meridian.attempt_selection_storage as attempt_storage
import meridian.reassessment_storage as reassessment_storage
from meridian.reassessment import (
    AttemptSelectionDecisionReference,
    ReassessmentPolicyReference,
)
from tests.cross_producer_academic_period_support import Issue44PeriodScenario
from tests.cross_producer_attempts_support import REASSESSMENT_POLICY_ID
from tests.cross_producer_proficiency_support import GRADE_ITEM_ID, NOW
from tests.cross_producer_test_support import SHARED_STUDENT_ID


def revise_scoreform_teacher_choices(
    scenario: Issue44PeriodScenario,
) -> reassessment_storage.ReassessmentResolution:
    """Reconfirm #30 and change #31 from replace to retain on one projection."""
    workspace = scenario.aggregation.workspace
    root = workspace.mixed.root
    work = workspace.mixed.publications["scoreform"].work
    authorized = workspace.authorized["scoreform"]

    old_attempt = attempt_storage.load_attempt_selection_decision_revision(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        1,
    )
    attempt_two = replace(
        old_attempt.decision,
        decision_revision=2,
        supersedes_revision=1,
        rationale=(
            "Teacher explicitly reconfirms both exact producer attempts before "
            "changing reassessment treatment."
        ),
        decided_at=NOW + timedelta(minutes=1),
    )
    written_attempt = attempt_storage.write_attempt_selection_decision_revision(
        root,
        attempt_two,
        authorized_snapshot=authorized,
    ).stored
    attempt_storage.select_attempt_selection_decision_revision(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        attempt_two.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=1,
    )
    selection = attempt_storage.resolve_current_attempt_selection(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=authorized,
    )
    if (
        selection.status != "selected"
        or selection.selected is None
        or selection.selected.decision_sha256
        != written_attempt.decision_sha256
    ):
        raise AssertionError("Issue #44 #30 revision 2 must resolve exactly.")

    old_policy = reassessment_storage.load_reassessment_policy_revision(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        REASSESSMENT_POLICY_ID,
        1,
    )
    policy_two = replace(
        old_policy.policy,
        policy_revision=2,
        supersedes_revision=1,
        allowed_modes=("retain", "replace"),
        rationale=(
            "Teacher may retain both selected attempts rather than treating "
            "one as a replacement."
        ),
        revised_at=NOW + timedelta(minutes=2),
    )
    written_policy = reassessment_storage.write_reassessment_policy_revision(
        root,
        policy_two,
    ).stored
    reassessment_storage.select_reassessment_policy_revision(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        policy_two.policy_id,
        policy_two.policy_revision,
        expected_current_policy_revision=1,
    )

    old_reassessment = (
        reassessment_storage.load_reassessment_decision_revision(
            root,
            work.class_id,
            GRADE_ITEM_ID,
            work,
            SHARED_STUDENT_ID,
            1,
        )
    )
    selected_attempts = selection.selected.decision.selected_attempts
    reassessment_two = replace(
        old_reassessment.decision,
        attempt_selection=AttemptSelectionDecisionReference(
            selection.selected.decision.decision_revision,
            selection.selected.decision_sha256,
        ),
        policy=ReassessmentPolicyReference(
            policy_two.policy_id,
            policy_two.policy_revision,
            written_policy.policy_sha256,
        ),
        mode="retain",
        contributing_attempts=selected_attempts,
        replacement_relationships=(),
        combinations=(),
        recency_order=(),
        decision_revision=2,
        supersedes_revision=1,
        rationale=(
            "Teacher explicitly retains both selected attempts; neither is "
            "treated as replacing the other."
        ),
        decided_at=NOW + timedelta(minutes=3),
    )
    written_reassessment = (
        reassessment_storage.write_reassessment_decision_revision(
            root,
            reassessment_two,
            authorized_snapshot=authorized,
        ).stored
    )
    reassessment_storage.select_reassessment_decision_revision(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        reassessment_two.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=1,
    )
    resolution = reassessment_storage.resolve_current_reassessment(
        root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=authorized,
    )
    if (
        resolution.status != "resolved"
        or resolution.selected is None
        or resolution.selected.decision_sha256
        != written_reassessment.decision_sha256
        or resolution.contributing_attempts != selected_attempts
    ):
        raise AssertionError("Issue #44 #31 revision 2 must retain both attempts.")
    return resolution
