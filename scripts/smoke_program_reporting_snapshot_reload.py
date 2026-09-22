"""Fresh-process reload of one installed issue #55 ReportingSnapshot."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_grade_report_preview_reload as issue54_reload  # type: ignore
from pds_core.academic_periods import AcademicPeriodRef

from meridian.grade_preview_explanation import (
    GradePreviewTarget,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_to_grade_report_preview,
    load_reporting_snapshot_for_comparison,
    load_reporting_snapshot_prior_grade_bases,
)
from meridian.reporting_snapshot_storage import load_reporting_definition_revision


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return cast(dict[str, Any], value)


def _text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(message)
    return value


def _integer(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(message)
    return value


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: smoke_program_reporting_snapshot_reload.py <root>"
        )
    issue54._verify_installed_composition()
    root = Path(sys.argv[1]).resolve()
    baseline = _mapping(
        json.loads((root / "issue55-reporting-snapshot-baseline.json").read_text(
            encoding="utf-8"
        )),
        "Issue #55 baseline must be an object.",
    )
    workspace = root / _text(baseline.get("workspace"), "workspace missing")
    before = issue54._tree_digest(workspace)

    class_id = _text(baseline.get("class_id"), "class_id missing")
    target = GradePreviewTarget(
        class_id,
        _text(baseline.get("student_id"), "student_id missing"),
        AcademicPeriodRef(
            _text(baseline.get("school_year"), "school_year missing"),
            _text(baseline.get("period_id"), "period_id missing"),
        ),
        _integer(baseline.get("calendar_revision"), "calendar_revision missing"),
        "hybrid",
    )
    evidence = issue54_reload._authorized_evidence(
        workspace,
        _mapping(baseline.get("hybrid_evidence"), "hybrid evidence missing"),
    )
    current_report = explain_grade_report_preview(
        workspace,
        (GradeReportPreviewRequest(target, work_evidence=evidence),),
    )

    definition = load_reporting_definition_revision(
        workspace,
        class_id,
        _text(baseline.get("definition_id"), "definition_id missing"),
        _integer(
            baseline.get("definition_revision"),
            "definition_revision missing",
        ),
    )
    _require(
        definition.definition_sha256
        == _text(baseline.get("definition_sha256"), "definition digest missing"),
        "Fresh-process reporting-definition digest changed.",
    )
    reference = ReportingSnapshotReference(
        class_id=class_id,
        snapshot_id=_text(baseline.get("snapshot_id"), "snapshot_id missing"),
        snapshot_sha256=_text(
            baseline.get("snapshot_sha256"),
            "snapshot digest missing",
        ),
    )
    stored = load_reporting_snapshot_for_comparison(workspace, reference)
    _require(stored.reference == reference, "Fresh-process snapshot reference changed.")
    _require(
        hashlib.sha256(stored.content).hexdigest() == reference.snapshot_sha256,
        "Fresh-process snapshot bytes fail exact digest verification.",
    )
    _require(
        stored.snapshot.payload_sha256
        == _text(baseline.get("payload_sha256"), "payload digest missing"),
        "Fresh-process snapshot payload digest changed.",
    )
    _require(
        stored.snapshot.report_preview_sha256
        == _text(
            baseline.get("report_preview_sha256"),
            "report preview digest missing",
        ),
        "Fresh-process frozen report digest changed.",
    )
    row = stored.snapshot.report_preview.rows[0]
    _require(row.observation is not None, "Fresh-process frozen observation missing.")
    assert row.observation is not None
    _require(
        _encoded(grade_preview_observation_to_json_bytes(row.observation))
        == _text(
            baseline.get("frozen_observation"),
            "frozen observation baseline missing",
        ),
        "Fresh-process frozen GradePreviewObservation changed.",
    )
    prior = load_reporting_snapshot_prior_grade_bases(workspace, reference)
    _require(
        len(prior) == 1 and prior[0].observation == row.observation,
        "Fresh-process prior-snapshot adaptation changed.",
    )
    comparisons = compare_reporting_snapshot_to_grade_report_preview(
        stored.snapshot,
        current_report,
    )
    _require(
        len(comparisons) == 1
        and comparisons[0].relationship == "comparable"
        and not comparisons[0].changed
        and comparisons[0].reasons == (),
        "Fresh-process snapshot/current comparison is not unchanged.",
    )
    after = issue54._tree_digest(workspace)
    _require(
        after == before,
        "Fresh-process #55 reload/comparison wrote workspace state.",
    )
    print("Issue #55 fresh-process ReportingSnapshot acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
