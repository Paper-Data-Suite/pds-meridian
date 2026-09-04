from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import list_grouping_signal_ids

import meridian.planning_signal_core_export_preview_workflow as workflow
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockedError,
    resolve_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewReference
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from tests.test_grouping_signal_review_workflow import CLASS_ID, _seed

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
SIGNAL_SET_ID = "meridian_reading_groups_2026_09_03"


def _warning_ids(stored_preview: object) -> tuple[str, ...]:
    snapshot = stored_preview.snapshot  # type: ignore[attr-defined]
    return tuple(
        sorted(
            item.diagnostic_id
            for item in snapshot.diagnostics
            if item.severity == "warning"
        )
    )


def _seed_selected_review(
    tmp_path: Path,
    *,
    decision: str = "accepted_for_export",
):
    root, stored_preview = _seed(tmp_path)
    recorded = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision=decision,  # type: ignore[arg-type]
        acknowledged_warning_ids=(
            _warning_ids(stored_preview)
            if decision == "accepted_for_export"
            else ()
        ),
        actor_id="teacher_local",
        reviewed_at=NOW,
    ).stored
    derivation_id = recorded.review.derivation_reference.derivation_id
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )
    return root, stored_preview, recorded


def _workspace_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_preview_builds_exact_authorized_core_candidate_without_writes(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review = _seed_selected_review(tmp_path)
    policy_id = stored_preview.snapshot.policy_reference.policy_id
    before_files = _workspace_files(root)
    before_core = list_grouping_signal_ids(root, CLASS_ID)

    preview = workflow.preview_planning_signal_core_export(
        root,
        CLASS_ID,
        policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW,
    )

    assert preview.eligibility.review_reference == stored_review.reference
    assert preview.eligibility.preview_reference == stored_preview.reference
    assert (
        preview.eligibility.derivation_reference
        == stored_review.review.derivation_reference
    )
    assert preview.signal_set.signal_set_id == SIGNAL_SET_ID
    assert preview.signal_set.class_id == CLASS_ID
    assert preview.signal_set.source.module_id == "meridian"
    assert (
        preview.signal_set.source.snapshot_id
        == stored_review.review.derivation_reference.derivation_id
    )
    assert preview.contributing_student_ids
    assert preview.final_core_revalidation_required is True
    assert preview.review_write_action == "not_performed"
    assert preview.review_selection_action == "not_performed"
    assert preview.core_export_action == "not_performed"
    assert preview.export_receipt_action == "not_performed"
    assert preview.csv_export_action == "not_performed"
    assert list_grouping_signal_ids(root, CLASS_ID) == before_core
    assert _workspace_files(root) == before_files


def test_preview_rejects_selected_review_that_is_not_accepted(
    tmp_path: Path,
) -> None:
    root, stored_preview, _ = _seed_selected_review(
        tmp_path,
        decision="rejected",
    )

    with pytest.raises(
        workflow.PlanningSignalCoreExportPreviewAuthorizationError
    ) as raised:
        workflow.preview_planning_signal_core_export(
            root,
            CLASS_ID,
            stored_preview.snapshot.policy_reference.policy_id,
            stored_preview.reference.preview_id,
            stored_preview.reference.preview_sha256,
            signal_set_id=SIGNAL_SET_ID,
            created_at=NOW,
        )

    assert raised.value.block_code == "review_not_accepted"
    assert raised.value.reason_codes == ()


def test_preview_requires_selected_review_to_authorize_requested_exact_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, stored_preview, stored_review = _seed_selected_review(tmp_path)
    actual = resolve_grouping_signal_export_eligibility(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )
    different_preview = GroupingSignalPreviewReference(
        class_id=CLASS_ID,
        preview_id="gsp_" + "f" * 64,
        preview_sha256="e" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_grouping_signal_export_eligibility",
        lambda *args, **kwargs: replace(
            actual,
            preview_reference=different_preview,
        ),
    )

    with pytest.raises(
        workflow.PlanningSignalCoreExportPreviewAuthorizationError,
        match="different exact #39 preview",
    ):
        workflow.preview_planning_signal_core_export(
            root,
            CLASS_ID,
            stored_preview.snapshot.policy_reference.policy_id,
            stored_preview.reference.preview_id,
            stored_preview.reference.preview_sha256,
            signal_set_id=SIGNAL_SET_ID,
            created_at=NOW,
        )


def test_preview_surfaces_authorization_drift_during_final_read_only_recheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, stored_preview, _ = _seed_selected_review(tmp_path)

    def stale(*args: object, **kwargs: object) -> object:
        raise GroupingSignalExportBlockedError("review_selection_changed")

    monkeypatch.setattr(
        workflow,
        "revalidate_grouping_signal_export_eligibility",
        stale,
    )

    with pytest.raises(
        workflow.PlanningSignalCoreExportPreviewStaleError
    ) as raised:
        workflow.preview_planning_signal_core_export(
            root,
            CLASS_ID,
            stored_preview.snapshot.policy_reference.policy_id,
            stored_preview.reference.preview_id,
            stored_preview.reference.preview_sha256,
            signal_set_id=SIGNAL_SET_ID,
            created_at=NOW,
        )

    assert raised.value.block_code == "review_selection_changed"


def test_invalid_signal_set_id_fails_before_workspace_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "project_planning_signal_preview_diagnostics",
        lambda *args, **kwargs: pytest.fail("scope validation must run first"),
    )

    with pytest.raises(
        workflow.PlanningSignalCoreExportPreviewScopeError,
        match="signal_set_id",
    ):
        workflow.preview_planning_signal_core_export(
            "synthetic-workspace",
            CLASS_ID,
            "reading_groups",
            "gsp_" + "a" * 64,
            "b" * 64,
            signal_set_id="bad signal set id",
            created_at=NOW,
        )
