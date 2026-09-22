"""Freeze one real installed issue #55 ReportingSnapshot."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_hybrid_grade as issue52  # type: ignore[import-not-found]

from meridian.grade_preview_explanation import (
    GradePreviewTarget,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_to_grade_report_preview,
)
from meridian.reporting_snapshot_freeze import freeze_reporting_snapshot
from meridian.reporting_snapshot_record import (
    reporting_snapshot_build_request_from_preview_requests,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_snapshot,
    write_reporting_definition_revision,
)

BASELINE_NAME = "issue55-reporting-snapshot-baseline.json"
DEFINITION_ID = "issue55_installed_hybrid_report"
SNAPSHOT_ID = "issue55_installed_hybrid_snapshot"
ACTOR_ID = "teacher_local"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _verify_installed_composition() -> None:
    issue54._verify_installed_composition()
    for module_name in (
        "meridian.reporting_snapshot",
        "meridian.reporting_snapshot_preview",
        "meridian.reporting_snapshot_record",
        "meridian.reporting_snapshot_storage",
        "meridian.reporting_snapshot_selection",
        "meridian.reporting_snapshot_freeze",
        "meridian.reporting_snapshot_comparison",
        "meridian.reporting_snapshot_cli",
    ):
        issue54._installed_origin(module_name)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_reporting_snapshot.py <root>")
    _verify_installed_composition()
    root = Path(sys.argv[1]).resolve()
    workspace = root / "issue55-hybrid"

    producer, work_evidence, descriptor = issue54._hybrid_state(workspace)
    target = GradePreviewTarget(
        issue52.CLASS_ID,
        issue52.STUDENT_ID,
        issue52.PERIOD,
        issue52.CALENDAR_REVISION,
        "hybrid",
    )
    request = GradeReportPreviewRequest(target, work_evidence=work_evidence)
    current_report = explain_grade_report_preview(workspace, (request,))
    _require(
        current_report.summary.requested_count == 1
        and current_report.summary.available_count == 1,
        "Installed #54 hybrid report preview is not available.",
    )

    actor = ReportingActor("teacher", ACTOR_ID)
    definition = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=issue52.CLASS_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="installed_reporting_snapshot_acceptance",
        title="Installed ReportingSnapshot acceptance",
        target_period=issue52.PERIOD,
        intended_audience="teacher",
        actor=actor,
        rationale="Issue #55 candidate-wheel acceptance.",
        revised_at=issue52.NOW + timedelta(hours=1),
    )
    stored_definition = write_reporting_definition_revision(
        workspace,
        definition,
    ).stored
    build_request = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=actor,
        requested_at=issue52.NOW + timedelta(hours=2),
        rationale="Freeze the exact installed hybrid Grade report.",
    )
    stored = freeze_reporting_snapshot(
        workspace,
        snapshot_id=SNAPSHOT_ID,
        build_request=build_request,
        preview_requests=(request,),
        created_at=issue52.NOW + timedelta(hours=3),
    )
    reloaded = load_reporting_snapshot(
        workspace,
        issue52.CLASS_ID,
        SNAPSHOT_ID,
    )
    _require(reloaded.reference == stored.reference, "Snapshot reference changed.")
    _require(reloaded.content == stored.content, "Snapshot bytes changed after reload.")
    _require(
        hashlib.sha256(reloaded.content).hexdigest() == stored.snapshot_sha256,
        "Snapshot digest does not match exact installed bytes.",
    )
    row = reloaded.snapshot.report_preview.rows[0]
    _require(row.observation is not None, "Frozen installed row lost its observation.")
    assert row.observation is not None
    live_row = current_report.rows[0]
    _require(
        live_row.observation is not None,
        "Live installed row lost its observation.",
    )
    assert live_row.observation is not None
    _require(
        grade_preview_observation_to_json_bytes(row.observation)
        == grade_preview_observation_to_json_bytes(live_row.observation),
        "Frozen observation differs from the exact #54 installed observation.",
    )
    comparisons = compare_reporting_snapshot_to_grade_report_preview(
        reloaded.snapshot,
        current_report,
    )
    _require(
        len(comparisons) == 1
        and comparisons[0].relationship == "comparable"
        and not comparisons[0].changed,
        "Freshly frozen installed snapshot did not compare as unchanged.",
    )
    issue54.issue50._assert_unchanged(producer)

    baseline = {
        "schema_version": "1",
        "workspace": workspace.name,
        "class_id": issue52.CLASS_ID,
        "student_id": issue52.STUDENT_ID,
        "school_year": issue52.PERIOD.school_year,
        "period_id": issue52.PERIOD.period_id,
        "calendar_revision": issue52.CALENDAR_REVISION,
        "calculation_family": "hybrid",
        "definition_id": DEFINITION_ID,
        "definition_revision": 1,
        "definition_sha256": stored_definition.definition_sha256,
        "snapshot_id": SNAPSHOT_ID,
        "snapshot_sha256": stored.snapshot_sha256,
        "payload_sha256": stored.snapshot.payload_sha256,
        "report_preview_sha256": stored.snapshot.report_preview_sha256,
        "frozen_observation": _encoded(
            grade_preview_observation_to_json_bytes(row.observation)
        ),
        "hybrid_evidence": descriptor,
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #55 installed ReportingSnapshot freeze acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
