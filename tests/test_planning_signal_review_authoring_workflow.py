from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meridian.grouping_signal_generation import generate_grouping_signal_derivation
from meridian.grouping_signal_preview_generation import generate_grouping_signal_preview
from meridian.grouping_signal_review_storage import (
    get_current_grouping_signal_review_revision,
    list_grouping_signal_review_revisions,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from meridian.planning_signal_review_authoring_workflow import (
    PlanningSignalReviewAuthoringScopeError,
    PlanningSignalReviewAuthoringStaleError,
    commit_planning_signal_review_authoring,
    preview_planning_signal_review_authoring,
)
from tests.test_grouping_signal_generation_integration import (
    CLASS_ID,
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)

NOW = datetime(2026, 9, 3, 5, 0, tzinfo=UTC)


def _seed(tmp_path: Path):
    workspace, scale = _seed_workspace(tmp_path)
    grade_item_basis, membership, membership_sha256 = (
        _seed_current_grade_item_result(workspace, scale)
    )
    policy_id = _seed_period_result_and_grouping_policy(
        workspace,
        scale,
        grade_item_basis,
        membership,
        membership_sha256,
    )
    generated = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy_id,
    )
    assert generated.status == "generated"
    assert generated.stored is not None
    preview_result = generate_grouping_signal_preview(
        workspace,
        generated.stored.reference,
    )
    return workspace, policy_id, preview_result.stored


def _warning_ids(stored_preview: object) -> tuple[str, ...]:
    snapshot = getattr(stored_preview, "snapshot")
    return tuple(
        sorted(
            item.diagnostic_id
            for item in snapshot.diagnostics
            if item.severity == "warning"
        )
    )


def test_preview_builds_exact_next_review_without_writing_or_selecting(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview = _seed(tmp_path)
    warnings = _warning_ids(stored_preview)
    derivation_id = stored_preview.snapshot.derivation_reference.derivation_id

    preview = preview_planning_signal_review_authoring(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        decision="accepted_for_export",
        acknowledged_warning_ids=warnings,
        actor_id="teacher_local",
        reviewed_at=NOW,
    )

    assert preview.review_revision == 1
    assert preview.candidate.supersedes_revision is None
    assert preview.decision == "accepted_for_export"
    assert preview.acknowledged_warning_ids == warnings
    assert preview.warning_diagnostic_ids == warnings
    assert preview.blocking_diagnostic_ids == ()
    assert preview.actor_id == "teacher_local"
    assert preview.expected_current_review_revision is None
    assert preview.review_write_action == "not_performed"
    assert preview.review_selection_action == "not_performed"
    assert list_grouping_signal_review_revisions(
        workspace,
        CLASS_ID,
        derivation_id,
    ) == ()
    assert get_current_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
    ) is None


def test_confirmed_review_write_remains_separate_from_review_selection(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview = _seed(tmp_path)
    warnings = _warning_ids(stored_preview)
    derivation_id = stored_preview.snapshot.derivation_reference.derivation_id
    preview = preview_planning_signal_review_authoring(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        decision="accepted_for_export",
        acknowledged_warning_ids=warnings,
        actor_id="teacher_local",
        reviewed_at=NOW,
    )

    result = commit_planning_signal_review_authoring(workspace, preview)

    assert result.write_disposition == "created"
    assert result.review_revision == 1
    assert result.decision == "accepted_for_export"
    assert len(result.review_sha256) == 64
    assert result.selected_revision_before_write is None
    assert result.selected_revision_after_write is None
    assert result.selection_changed_during_write is False
    assert result.review_selection_action == "not_performed"
    assert result.core_export_action == "not_performed"
    assert result.csv_export_action == "not_performed"
    assert list_grouping_signal_review_revisions(
        workspace,
        CLASS_ID,
        derivation_id,
    ) == (1,)
    assert get_current_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
    ) is None


def test_preview_derives_contiguous_successor_revision(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview = _seed(tmp_path)
    warnings = _warning_ids(stored_preview)
    first_preview = preview_planning_signal_review_authoring(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        decision="accepted_for_export",
        acknowledged_warning_ids=warnings,
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    first_result = commit_planning_signal_review_authoring(
        workspace,
        first_preview,
    )
    assert first_result.review_revision == 1

    second_preview = preview_planning_signal_review_authoring(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW + timedelta(seconds=1),
    )

    assert second_preview.history == (1,)
    assert second_preview.review_revision == 2
    assert second_preview.candidate.supersedes_revision == 1
    assert second_preview.decision == "rejected"


def test_commit_fails_closed_when_review_history_changes_after_preview(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview = _seed(tmp_path)
    warnings = _warning_ids(stored_preview)
    preview = preview_planning_signal_review_authoring(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        decision="accepted_for_export",
        acknowledged_warning_ids=warnings,
        actor_id="teacher_one",
        reviewed_at=NOW,
    )

    record_grouping_signal_review(
        workspace,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_two",
        reviewed_at=NOW,
    )

    with pytest.raises(
        PlanningSignalReviewAuthoringStaleError,
        match="Review history changed",
    ):
        commit_planning_signal_review_authoring(workspace, preview)


def test_accepted_review_requires_exact_warning_acknowledgments(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview = _seed(tmp_path)
    warnings = _warning_ids(stored_preview)
    assert warnings

    with pytest.raises(
        PlanningSignalReviewAuthoringScopeError,
        match="acknowledge exactly every warning",
    ):
        preview_planning_signal_review_authoring(
            workspace,
            CLASS_ID,
            policy_id,
            stored_preview.reference.preview_id,
            stored_preview.reference.preview_sha256,
            decision="accepted_for_export",
            acknowledged_warning_ids=(),
            actor_id="teacher_local",
            reviewed_at=NOW,
        )
