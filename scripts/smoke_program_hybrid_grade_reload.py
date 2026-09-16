"""Fresh-process reload for issue #52 installed bounded-hybrid Grade acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import smoke_program_hybrid_grade as hybrid_smoke  # type: ignore
from pds_core.academic_periods import AcademicPeriodRef

from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_result import (
    hybrid_grade_result_snapshot_from_json_bytes,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.hybrid_grade_storage import load_current_hybrid_grade_result


class ReloadFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReloadFailure(message)


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReloadFailure(message)
    return cast(dict[str, Any], value)


def _text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise ReloadFailure(message)
    return value


def _integer(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReloadFailure(message)
    return value


def _load_baseline(workspace: Path) -> dict[str, Any]:
    path = workspace.parent / hybrid_smoke.BASELINE_NAME
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = _mapping(raw, "Issue #52 reload baseline must be a JSON object.")
    _require(data.get("schema_version") == "1", "Baseline schema mismatch.")
    return data


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_hybrid_grade_reload.py <workspace>")
    hybrid_smoke._verify_installed_composition()
    workspace = Path(sys.argv[1]).resolve()
    data = _load_baseline(workspace)
    class_id = _text(data.get("class_id"), "Class identity is missing.")
    student_id = _text(data.get("student_id"), "Student identity is missing.")
    school_year = _text(data.get("school_year"), "School year is missing.")
    period_id = _text(data.get("period_id"), "Period identity is missing.")
    calendar_revision = _integer(
        data.get("calendar_revision"),
        "Calendar revision is missing.",
    )
    result_revision = _integer(
        data.get("result_revision"),
        "Result revision is missing.",
    )
    result_sha256 = _text(data.get("result_sha256"), "Result digest is missing.")
    fingerprint = _text(
        data.get("calculation_fingerprint"),
        "Calculation fingerprint is missing.",
    )
    rounded_grade = _text(data.get("rounded_grade"), "Rounded Grade is missing.")
    upstream = _mapping(data.get("upstream"), "Upstream digest map is missing.")

    period = AcademicPeriodRef(school_year, period_id)
    current = load_current_hybrid_grade_result(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
    )
    _require(current is not None, "Fresh process could not reload hybrid result.")
    assert current is not None
    _require(current.snapshot.result_revision == result_revision, "Revision changed.")
    _require(current.result_sha256 == result_sha256, "Result digest changed.")
    _require(
        current.snapshot.calculation_fingerprint == fingerprint,
        "Fresh-process calculation fingerprint changed.",
    )
    _require(
        str(current.snapshot.outcome.rounded_grade) == rounded_grade,
        "Fresh-process rounded Grade changed.",
    )
    _require(
        calculate_hybrid_grade(current.snapshot.inputs) == current.snapshot.outcome,
        "Fresh-process hybrid reproduction differs from persisted outcome.",
    )
    encoded = hybrid_grade_result_snapshot_to_json_bytes(current.snapshot)
    _require(
        hybrid_grade_result_snapshot_from_json_bytes(encoded) == current.snapshot,
        "Fresh-process hybrid canonical JSON round-trip failed.",
    )
    _require(
        hybrid_smoke._upstream_snapshot(workspace) == upstream,
        "Fresh-process Grade read mutated producer or v0.2 source state.",
    )
    hybrid_smoke._assert_no_standalone_grade_results(workspace)
    print("Issue #52 fresh-process bounded hybrid Grade reload passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
