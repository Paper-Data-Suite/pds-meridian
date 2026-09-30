"""Fresh-process reload for Issue #99 profile-constrained Grade acceptance."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import smoke_program_profile_constrained_grade as profile  # type: ignore
import smoke_program_standards_grade as base  # type: ignore

from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_assembly import assemble_standards_grade_calculation
from meridian.standards_grade_result import (
    assess_standards_grade_result_freshness,
    standards_grade_result_snapshot_from_json_bytes,
    standards_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade_storage import load_current_standards_grade_result


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: smoke_program_profile_constrained_grade_reload.py <workspace>"
        )
    profile._verify_installed()
    workspace = Path(sys.argv[1]).resolve()
    baseline = json.loads(
        (workspace / profile.PROFILE_BASELINE_NAME).read_text(encoding="utf-8")
    )
    current = load_current_standards_grade_result(
        workspace,
        base.CLASS_ID,
        base.STUDENT_ID,
        base.PERIOD,
        base.CALENDAR_REVISION,
    )
    base._require(current is not None, "Fresh process could not reload profile Grade.")
    assert current is not None
    outcome = current.snapshot.outcome
    base._require(
        current.snapshot.result_revision == baseline["result_revision"],
        "Profile result revision changed.",
    )
    base._require(current.result_sha256 == baseline["result_sha256"], "Digest changed.")
    base._require(
        current.snapshot.calculation_fingerprint == baseline["calculation_fingerprint"],
        "Fingerprint changed.",
    )
    base._require(outcome.base_unrounded_grade == Decimal("90"), "Base mean changed.")
    base._require(outcome.selected_profile_band_id == "high", "Band changed.")
    base._require(outcome.profile_adjustment == "floor", "Adjustment changed.")
    base._require(outcome.rounded_grade == Decimal("95.00"), "Grade changed.")
    base._require(
        current.snapshot.inputs.target_scale_definition is not None,
        "Exact scale authority was lost.",
    )
    base._require(
        calculate_standards_grade(current.snapshot.inputs) == outcome,
        "Fresh process cannot reproduce profile Grade.",
    )
    encoded = standards_grade_result_snapshot_to_json_bytes(current.snapshot)
    base._require(
        standards_grade_result_snapshot_from_json_bytes(encoded) == current.snapshot,
        "Fresh-process canonical round-trip failed.",
    )
    refreshed = assemble_standards_grade_calculation(
        workspace, base.CLASS_ID, base.STUDENT_ID, base.PERIOD, base.CALENDAR_REVISION
    )
    freshness = assess_standards_grade_result_freshness(
        current.snapshot, refreshed.inputs
    )
    base._require(freshness.status == "current", "Fresh profile Grade is stale.")
    base._require(freshness.reasons == (), "Fresh profile Grade has stale reasons.")
    base._require(
        base._upstream_snapshot(workspace) == baseline["upstream"],
        "Fresh read mutated producer/proficiency state.",
    )
    print("Issue #99 fresh-process profile-constrained Grade reload passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
