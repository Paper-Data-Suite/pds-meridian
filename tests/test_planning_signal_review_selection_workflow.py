from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import list_grouping_signal_ids

from meridian.grouping_signal_generation import generate_grouping_signal_derivation
from meridian.grouping_signal_preview_generation import generate_grouping_signal_preview
from meridian.grouping_signal_review_storage import (
    get_current_grouping_signal_review_revision,
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from meridian.planning_signal_review_selection_workflow import (
    PlanningSignalReviewSelectionScopeError,
    PlanningSignalReviewSelectionStaleError,
    commit_planning_signal_review_selection,
    preview_planning_signal_review_selection,
)
from tests.test_grouping_signal_generation_integration import (
    CLASS_ID,
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)

NOW = datetime(2026, 9, 3, 5, 30, tzinfo=UTC)


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
    stored_preview = preview_result.stored
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in stored_preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )
    first = record_grouping_signal_review(
        workspace,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id="teacher_local",
        reviewed_at=NOW,
    ).stored
    return workspace, policy_id, stored_preview, first


def test_selection_preview_resolves_exact_review_and_is_read_only(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview, review = _seed(tmp_path)
    derivation_id = review.review.derivation_reference.derivation_id
    before_core = list_grouping_signal_ids(workspace, CLASS_ID)

    preview = preview_planning_signal_review_selection(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        review.review.review_revision,
        review.review_sha256,
    )

    assert preview.target.reference == review.reference
    assert preview.expected_current_review_revision is None
    assert preview.target_decision == "accepted_for_export"
    assert preview.target_applicability.status == "current"
    assert preview.review_selection_action == "not_performed"
    assert get_current_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
    ) is None
    assert list_grouping_signal_ids(workspace, CLASS_ID) == before_core


def test_commit_selects_exact_review_with_cas_and_does_not_export(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview, review = _seed(tmp_path)
    before_core = list_grouping_signal_ids(workspace, CLASS_ID)
    preview = preview_planning_signal_review_selection(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        review.review.review_revision,
        review.review_sha256,
    )

    result = commit_planning_signal_review_selection(workspace, preview)

    assert result.selection_disposition == "created"
    assert result.previous_current_review_revision is None
    assert result.selected_review_revision == 1
    assert result.selected_review_sha256 == review.review_sha256
    assert result.selected_decision == "accepted_for_export"
    assert result.review_write_action == "not_performed"
    assert result.review_selection_action == "performed"
    assert result.core_export_action == "not_performed"
    assert result.csv_export_action == "not_performed"
    assert get_current_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        review.review.derivation_reference.derivation_id,
    ) == 1
    assert list_grouping_signal_ids(workspace, CLASS_ID) == before_core


def test_selection_preview_requires_exact_review_digest(tmp_path: Path) -> None:
    workspace, policy_id, stored_preview, review = _seed(tmp_path)

    with pytest.raises(
        PlanningSignalReviewSelectionScopeError,
        match="exact requested review digest",
    ):
        preview_planning_signal_review_selection(
            workspace,
            CLASS_ID,
            policy_id,
            stored_preview.reference.preview_id,
            stored_preview.reference.preview_sha256,
            review.review.review_revision,
            "0" * 64,
        )


def test_commit_rejects_review_selector_drift(tmp_path: Path) -> None:
    workspace, policy_id, stored_preview, review = _seed(tmp_path)
    preview = preview_planning_signal_review_selection(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        review.review.review_revision,
        review.review_sha256,
    )
    select_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        review.review.derivation_reference.derivation_id,
        1,
        expected_current_review_revision=None,
    )

    with pytest.raises(
        PlanningSignalReviewSelectionStaleError,
        match="selection changed",
    ):
        commit_planning_signal_review_selection(workspace, preview)


def test_rejected_review_is_selectable_but_not_export_accepted(
    tmp_path: Path,
) -> None:
    workspace, policy_id, stored_preview, first = _seed(tmp_path)
    second = record_grouping_signal_review(
        workspace,
        stored_preview.reference,
        review_revision=2,
        supersedes_revision=1,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW + timedelta(seconds=1),
    ).stored

    preview = preview_planning_signal_review_selection(
        workspace,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        2,
        second.review_sha256,
    )
    assert preview.target_decision == "rejected"
    assert preview.target_applicability.status == "not_accepted"

    result = commit_planning_signal_review_selection(workspace, preview)
    assert result.selected_review_revision == 2
    assert result.selected_decision == "rejected"
    assert first.review.review_revision == 1
