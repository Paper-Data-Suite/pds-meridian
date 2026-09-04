from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import list_grouping_signal_ids

import meridian.planning_signal_core_export_commit_workflow as workflow
from meridian.grouping_signal_export_receipt_workflow import (
    GroupingSignalExportPartialSuccessError,
)
from meridian.grouping_signal_export_storage import (
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_review_storage import (
    load_current_grouping_signal_review,
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from meridian.planning_signal_core_export_preview_workflow import (
    preview_planning_signal_core_export,
)
from tests.test_planning_signal_core_export_preview_workflow import (
    CLASS_ID,
    NOW,
    SIGNAL_SET_ID,
    _seed_selected_review,
)

RETRY_SIGNAL_SET_ID = "meridian_reading_groups_2026_09_03_retry"


def _preview(
    tmp_path: Path,
    *,
    signal_set_id: str = SIGNAL_SET_ID,
):
    root, stored_preview, stored_review = _seed_selected_review(tmp_path)
    preview = preview_planning_signal_core_export(
        root,
        CLASS_ID,
        stored_preview.snapshot.policy_reference.policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )
    return root, stored_preview, stored_review, preview


def test_commit_writes_exact_core_signal_and_matching_receipt_only(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review, preview = _preview(tmp_path)
    before_selected = load_current_grouping_signal_review(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )
    before_csv = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.csv")
    }

    result = workflow.commit_planning_signal_core_export(root, preview)

    assert result.core_write_disposition == "created"
    assert result.receipt_write_disposition == "created"
    assert result.core_export_action == "performed"
    assert result.export_receipt_action == "performed"
    assert result.review_write_action == "not_performed"
    assert result.review_selection_action == "not_performed"
    assert result.csv_export_action == "not_performed"
    assert result.concord_action == "not_performed"

    assert list_grouping_signal_ids(root, CLASS_ID) == (SIGNAL_SET_ID,)
    stored_receipt = load_grouping_signal_export_receipt(
        root,
        CLASS_ID,
        SIGNAL_SET_ID,
    )
    receipt = stored_receipt.receipt
    assert receipt.derivation_reference == preview.eligibility.derivation_reference
    assert receipt.preview_reference == stored_preview.reference
    assert receipt.review_reference == stored_review.reference
    assert receipt.core_signal_digest == result.core_signal_digest
    assert stored_receipt.receipt_sha256 == result.receipt_sha256

    after_selected = load_current_grouping_signal_review(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )
    assert after_selected == before_selected
    after_csv = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*.csv")
    }
    assert after_csv == before_csv


def test_exact_commit_retry_reconciles_as_existing(tmp_path: Path) -> None:
    root, _, _, preview = _preview(
        tmp_path,
        signal_set_id=RETRY_SIGNAL_SET_ID,
    )

    first = workflow.commit_planning_signal_core_export(root, preview)
    second = workflow.commit_planning_signal_core_export(root, preview)

    assert first.core_write_disposition == "created"
    assert first.receipt_write_disposition == "created"
    assert second.core_write_disposition == "existing"
    assert second.receipt_write_disposition == "existing"
    assert first.export_result.core.write_result.stored == (
        second.export_result.core.write_result.stored
    )
    assert first.export_result.receipt.stored == second.export_result.receipt.stored


def test_commit_rejects_selected_review_drift_before_core_write(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review, preview = _preview(tmp_path)
    rejected = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=2,
        supersedes_revision=1,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=datetime(2026, 9, 3, 12, 5, tzinfo=UTC),
    ).stored
    assert rejected.review.review_revision == 2
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
        2,
        expected_current_review_revision=1,
    )

    with pytest.raises(
        workflow.PlanningSignalCoreExportCommitStaleError
    ) as raised:
        workflow.commit_planning_signal_core_export(root, preview)

    assert raised.value.block_code == "review_selection_changed"
    assert list_grouping_signal_ids(root, CLASS_ID) == ()


def test_partial_core_success_preserves_recovery_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, preview = _preview(tmp_path)
    digest = "d" * 64

    def partial(*args: object, **kwargs: object) -> object:
        raise GroupingSignalExportPartialSuccessError(
            signal_set_id=SIGNAL_SET_ID,
            core_digest_algorithm="sha256",
            core_signal_digest=digest,
            core_disposition="created",
        )

    monkeypatch.setattr(workflow, "export_grouping_signal", partial)

    with pytest.raises(
        workflow.PlanningSignalCoreExportCommitPartialSuccessError
    ) as raised:
        workflow.commit_planning_signal_core_export(root, preview)

    error = raised.value
    assert error.signal_set_id == SIGNAL_SET_ID
    assert error.core_digest_algorithm == "sha256"
    assert error.core_signal_digest == digest
    assert error.core_disposition == "created"
    assert "Retry the exact same export request" in str(error)


def test_commit_requires_exact_export_preview() -> None:
    with pytest.raises(
        workflow.PlanningSignalCoreExportCommitScopeError,
        match="PlanningSignalCoreExportPreview",
    ):
        workflow.commit_planning_signal_core_export(
            "synthetic-workspace",
            object(),  # type: ignore[arg-type]
        )
