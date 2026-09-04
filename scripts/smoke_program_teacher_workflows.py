"""Installed-wheel acceptance for Meridian issue #41 teacher workflows."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pds_core.grouping_signal_csv import parse_grouping_signal_csv
from pds_core.grouping_signal_storage import load_grouping_signal

from meridian.grade_items_workflow import project_grade_items_review
from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
    load_grouping_signal_derivation,
)
from meridian.grouping_signal_preview_storage import (
    list_grouping_signal_preview_ids,
    load_grouping_signal_preview,
)
from meridian.planning_signal_core_export_preview_workflow import (
    preview_planning_signal_core_export,
)
from meridian.planning_signal_derivation_persistence_workflow import (
    commit_planning_signal_derivation_persistence_preview,
    preview_planning_signal_derivation_persistence,
)
from meridian.planning_signal_export_commit_workflow import (
    commit_planning_signal_export,
)
from meridian.planning_signal_preview_diagnostics_workflow import (
    project_planning_signal_preview_diagnostics,
)
from meridian.planning_signal_preview_write_workflow import (
    commit_planning_signal_preview_write,
    preview_planning_signal_preview_write,
)
from meridian.planning_signal_workflow import project_planning_signal_readiness
from meridian.teacher_workflows import (
    TEACHER_WORKFLOW_TASK_IDS,
    teacher_workflow_catalog,
)

CLASS_ID = "synthetic_class_2026"
POLICY_ID = "reading_planning_signal"
SIGNAL_SET_ID = "reading_mp1_export_001"
EXPORT_CREATED_AT_OFFSET_MINUTES = 5
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


def _optional_packages_absent() -> None:
    for module_name in (
        "scoreform",
        "quillan",
        "concord",
        "pds_concord",
        "portia",
        "vitrine",
        "paper_data_suite",
    ):
        assert importlib.util.find_spec(module_name) is None


def main() -> None:
    """Exercise packaged #41 application controllers over exact #40 state."""

    _optional_packages_absent()

    package_root = Path(sys.prefix).resolve()
    import meridian

    assert meridian.__file__ is not None
    assert Path(meridian.__file__).resolve().is_relative_to(package_root)

    catalog = teacher_workflow_catalog()
    assert tuple(task.task_id for task in catalog.tasks) == TEACHER_WORKFLOW_TASK_IDS
    assert len(catalog.tasks) == 7

    root = Path(".").resolve()
    workspace = root / "workspace"

    grade_items = project_grade_items_review(workspace, CLASS_ID)
    assert grade_items.active_count == 1
    assert grade_items.archived_count == 0
    assert grade_items.membership_included_count == 1
    assert grade_items.membership_unselected_count == 0
    assert grade_items.items[0].title == "Synthetic Grade Item"
    assert grade_items.items[0].selection_state == "selected_latest"
    assert grade_items.items[0].memberships[0].decision == "included"
    assert (
        grade_items.items[0].memberships[0].academic_period_id
        == "mp1"
    )

    derivation_ids = list_grouping_signal_derivation_ids(workspace, CLASS_ID)
    assert len(derivation_ids) == 1
    derivation = load_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        derivation_ids[0],
    )

    readiness = project_planning_signal_readiness(
        workspace,
        CLASS_ID,
        POLICY_ID,
    )
    assert readiness.ready_for_derivation_persistence is True
    derivation_preview = preview_planning_signal_derivation_persistence(readiness)
    assert derivation_preview.derivation_write_action == "not_performed"
    derivation_replay = commit_planning_signal_derivation_persistence_preview(
        workspace,
        derivation_preview,
    )
    assert derivation_replay.write_disposition == "existing"
    assert derivation_replay.derivation_id == derivation.snapshot.derivation_id
    assert derivation_replay.derivation_sha256 == derivation.derivation_sha256

    preview_intent = preview_planning_signal_preview_write(
        workspace,
        CLASS_ID,
        POLICY_ID,
        derivation.snapshot.derivation_id,
        derivation.derivation_sha256,
    )
    assert preview_intent.preview_write_action == "not_performed"
    preview_replay = commit_planning_signal_preview_write(
        workspace,
        preview_intent,
    )
    assert preview_replay.write_disposition == "existing"

    preview_ids = list_grouping_signal_preview_ids(workspace, CLASS_ID)
    assert len(preview_ids) == 1
    stored_preview = load_grouping_signal_preview(
        workspace,
        CLASS_ID,
        preview_ids[0],
    )
    assert preview_replay.preview_id == stored_preview.snapshot.preview_id
    assert preview_replay.preview_sha256 == stored_preview.preview_sha256

    diagnostics = project_planning_signal_preview_diagnostics(
        workspace,
        CLASS_ID,
        POLICY_ID,
        stored_preview.snapshot.preview_id,
        stored_preview.preview_sha256,
    )
    assert diagnostics.preview_reference == stored_preview.reference
    assert diagnostics.live_currentness.state == "current"
    assert diagnostics.review_status.decision == "accepted_for_export"
    assert diagnostics.review_status.applicability is not None
    assert diagnostics.review_status.applicability.status == "current"

    export_preview = preview_planning_signal_core_export(
        workspace,
        CLASS_ID,
        POLICY_ID,
        stored_preview.snapshot.preview_id,
        stored_preview.preview_sha256,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW + timedelta(minutes=EXPORT_CREATED_AT_OFFSET_MINUTES),
    )
    assert export_preview.final_core_revalidation_required is True
    assert export_preview.core_export_action == "not_performed"
    assert export_preview.export_receipt_action == "not_performed"
    assert export_preview.csv_export_action == "not_performed"

    csv_path = root / "reading-planning-signal.csv"
    final = commit_planning_signal_export(
        workspace,
        export_preview,
        csv_destination=csv_path,
    )
    assert final.core.core_write_disposition == "existing"
    assert final.core.receipt_write_disposition == "existing"
    assert final.csv is not None
    assert final.csv.disposition == "existing"
    assert final.csv.destination == csv_path.resolve()
    assert final.core_export_action == "performed"
    assert final.export_receipt_action == "performed"
    assert final.csv_export_action == "performed"
    assert final.concord_action == "not_performed"

    stored_signal = load_grouping_signal(workspace, CLASS_ID, SIGNAL_SET_ID)
    assert stored_signal.signal == export_preview.signal_set
    csv_document = parse_grouping_signal_csv(csv_path.read_bytes())
    assert csv_document.csv_contract == "grouping_signal_csv_v1"
    assert csv_document.representation_scope == "complete_signal"
    assert csv_document.signal_set_id == SIGNAL_SET_ID

    _optional_packages_absent()
    print("Installed issue #41 teacher-workflow smoke passed.")


if __name__ == "__main__":
    main()
