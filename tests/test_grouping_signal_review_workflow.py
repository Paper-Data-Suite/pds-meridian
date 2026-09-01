from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import meridian.grouping_signal_review_workflow as review_workflow
from meridian.grouping_signal_generation import (
    generate_grouping_signal_derivation,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
)
from meridian.grouping_signal_preview_generation import (
    generate_grouping_signal_preview,
)
from meridian.grouping_signal_review_storage import (
    get_current_grouping_signal_review_revision,
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import (
    assess_selected_grouping_signal_review_applicability,
    record_grouping_signal_review,
)
from tests.test_grouping_signal_generation_integration import (
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


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
    assert preview_result.stored.snapshot.currentness.state == "current"
    return workspace, preview_result.stored


def test_recording_review_does_not_select_it_and_selected_applicability_is_current(
    tmp_path: Path,
) -> None:
    root, stored_preview = _seed(tmp_path)

    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in stored_preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )
    assert warning_ids

    recorded = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    derivation_id = recorded.stored.review.derivation_reference.derivation_id

    assert recorded.disposition == "created"
    assert get_current_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
    ) is None
    assert assess_selected_grouping_signal_review_applicability(
        root,
        CLASS_ID,
        derivation_id,
    ) is None

    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )
    applicability = assess_selected_grouping_signal_review_applicability(
        root,
        CLASS_ID,
        derivation_id,
    )
    assert applicability is not None
    assert applicability.status == "current"
    assert applicability.reason_codes == ()

def test_acceptance_rechecks_live_currentness_but_rejection_remains_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, stored_preview = _seed(tmp_path)
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in stored_preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )

    monkeypatch.setattr(
        review_workflow,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: GroupingSignalPreviewCurrentness(
            "blocked",
            ("current_basis_unavailable",),
            None,
        ),
    )

    with pytest.raises(
        review_workflow.GroupingSignalReviewWorkflowValidationError,
        match="current at review time",
    ):
        record_grouping_signal_review(
            root,
            stored_preview.reference,
            review_revision=1,
            supersedes_revision=None,
            decision="accepted_for_export",
            acknowledged_warning_ids=warning_ids,
            actor_id="teacher_local",
            reviewed_at=NOW,
        )

    rejected = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    assert rejected.stored.review.decision == "rejected"

