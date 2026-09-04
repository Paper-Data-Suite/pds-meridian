from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.grouping_signal_csv import parse_grouping_signal_csv
from pds_core.grouping_signal_storage import load_grouping_signal

import meridian.planning_signal_export_commit_workflow as workflow
from meridian.grouping_signal_csv_export import (
    GroupingSignalCsvExportConflictError,
)
from meridian.grouping_signal_export_storage import (
    load_grouping_signal_export_receipt,
)
from meridian.planning_signal_core_export_commit_workflow import (
    PlanningSignalCoreExportCommitPartialSuccessError,
)
from meridian.planning_signal_core_export_preview_workflow import (
    preview_planning_signal_core_export,
)
from tests.test_planning_signal_core_export_preview_workflow import (
    CLASS_ID,
    NOW,
    SIGNAL_SET_ID,
    _seed_selected_review,
)


def _preview(tmp_path: Path, *, signal_set_id: str = SIGNAL_SET_ID):
    root, stored_preview, _ = _seed_selected_review(tmp_path)
    preview = preview_planning_signal_core_export(
        root,
        CLASS_ID,
        stored_preview.snapshot.policy_reference.policy_id,
        stored_preview.reference.preview_id,
        stored_preview.reference.preview_sha256,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )
    return root, preview


def test_final_export_without_csv_commits_only_core_and_receipt(
    tmp_path: Path,
) -> None:
    root, preview = _preview(tmp_path)

    result = workflow.commit_planning_signal_export(root, preview)

    assert result.core.core_write_disposition == "created"
    assert result.core.receipt_write_disposition == "created"
    assert result.csv is None
    assert result.core_export_action == "performed"
    assert result.export_receipt_action == "performed"
    assert result.csv_export_action == "not_performed"
    assert result.concord_action == "not_performed"
    assert load_grouping_signal(root, CLASS_ID, SIGNAL_SET_ID).signal == (
        preview.signal_set
    )
    load_grouping_signal_export_receipt(root, CLASS_ID, SIGNAL_SET_ID)


def test_final_export_optional_csv_uses_exact_stored_core_signal(
    tmp_path: Path,
) -> None:
    root, preview = _preview(tmp_path)
    destination = tmp_path / "teacher-planning-signal.csv"

    result = workflow.commit_planning_signal_export(
        root,
        preview,
        csv_destination=destination,
    )

    assert result.core.core_write_disposition == "created"
    assert result.core.receipt_write_disposition == "created"
    assert result.csv is not None
    assert result.csv.disposition == "created"
    assert result.csv.destination == destination.resolve()
    assert result.csv_export_action == "performed"
    assert result.concord_action == "not_performed"

    document = parse_grouping_signal_csv(destination.read_bytes())
    assert document.csv_contract == "grouping_signal_csv_v1"
    assert document.representation_scope == "complete_signal"
    assert document.signal_set_id == SIGNAL_SET_ID
    assert document.class_id == CLASS_ID
    assert load_grouping_signal(root, CLASS_ID, SIGNAL_SET_ID).signal == (
        preview.signal_set
    )


def test_exact_final_export_retry_reconciles_core_receipt_and_csv(
    tmp_path: Path,
) -> None:
    signal_set_id = "meridian_reading_groups_final_retry"
    root, preview = _preview(tmp_path, signal_set_id=signal_set_id)
    destination = tmp_path / "retry.csv"

    first = workflow.commit_planning_signal_export(
        root,
        preview,
        csv_destination=destination,
    )
    second = workflow.commit_planning_signal_export(
        root,
        preview,
        csv_destination=destination,
    )

    assert first.core.core_write_disposition == "created"
    assert first.core.receipt_write_disposition == "created"
    assert first.csv is not None and first.csv.disposition == "created"
    assert second.core.core_write_disposition == "existing"
    assert second.core.receipt_write_disposition == "existing"
    assert second.csv is not None and second.csv.disposition == "existing"
    assert first.csv.csv_sha256 == second.csv.csv_sha256


def test_csv_failure_after_core_commit_is_explicit_partial_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, preview = _preview(tmp_path)
    destination = tmp_path / "blocked.csv"

    def fail_csv(*args: object, **kwargs: object) -> object:
        raise GroupingSignalCsvExportConflictError(
            "synthetic teacher-edited destination"
        )

    monkeypatch.setattr(workflow, "export_grouping_signal_csv", fail_csv)

    with pytest.raises(
        workflow.PlanningSignalCsvExportPartialSuccessError
    ) as raised:
        workflow.commit_planning_signal_export(
            root,
            preview,
            csv_destination=destination,
        )

    error = raised.value
    assert error.signal_set_id == SIGNAL_SET_ID
    assert error.core_write_disposition == "created"
    assert error.receipt_write_disposition == "created"
    assert error.csv_error_code == "csv_destination_conflict"
    assert error.csv_destination == destination
    assert load_grouping_signal(root, CLASS_ID, SIGNAL_SET_ID).signal == (
        preview.signal_set
    )
    receipt = load_grouping_signal_export_receipt(
        root,
        CLASS_ID,
        SIGNAL_SET_ID,
    )
    assert receipt.receipt.core_signal_digest == error.core_signal_digest
    assert receipt.receipt_sha256 == error.receipt_sha256


def test_core_partial_success_never_attempts_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, preview = _preview(tmp_path)
    observed: list[str] = []

    def core_partial(*args: object, **kwargs: object) -> object:
        raise PlanningSignalCoreExportCommitPartialSuccessError(
            signal_set_id=SIGNAL_SET_ID,
            core_digest_algorithm="sha256",
            core_signal_digest="a" * 64,
            core_disposition="created",
        )

    def should_not_csv(*args: object, **kwargs: object) -> object:
        observed.append("csv")
        raise AssertionError("CSV must not run without a verified receipt")

    monkeypatch.setattr(
        workflow,
        "commit_planning_signal_core_export",
        core_partial,
    )
    monkeypatch.setattr(workflow, "export_grouping_signal_csv", should_not_csv)

    with pytest.raises(PlanningSignalCoreExportCommitPartialSuccessError):
        workflow.commit_planning_signal_export(
            root,
            preview,
            csv_destination=tmp_path / "never.csv",
        )

    assert observed == []
