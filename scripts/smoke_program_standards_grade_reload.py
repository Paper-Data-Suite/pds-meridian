"""Fresh-process reload and reproduction for issue #51 installed acceptance."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_assembly import assemble_standards_grade_calculation
from meridian.standards_grade_result import assess_standards_grade_result_freshness
from meridian.standards_grade_storage import load_current_standards_grade_result

CLASS_ID = "issue51_installed_class"
STUDENT_ID = "issue51_student_001"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "q1"
CALENDAR_REVISION = 1
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
BASELINE_NAME = "issue51-standards-grade-baseline.json"


class AcceptanceFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _installed_origin(module_name: str) -> None:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    _require(isinstance(raw, str) and bool(raw), f"{module_name} has no origin.")
    assert isinstance(raw, str)
    origin = Path(raw).resolve()
    prefix = Path(sys.prefix).resolve()
    _require(origin.is_relative_to(prefix), f"{module_name} is outside the venv.")
    _require(
        "site-packages" in {part.lower() for part in origin.parts},
        f"{module_name} is not installed from site-packages.",
    )


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest_map(base: Path, workspace: Path) -> dict[str, str]:
    if not base.exists():
        return {}
    return {
        path.relative_to(workspace).as_posix(): _file_digest(path)
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _upstream_snapshot(workspace: Path) -> dict[str, dict[str, str]]:
    class_root = workspace / "classes" / CLASS_ID / "modules"
    meridian_root = class_root / "meridian"
    return {
        "scoreform": _tree_digest_map(class_root / "scoreform", workspace),
        "quillan": _tree_digest_map(class_root / "quillan", workspace),
        "proficiency_scales": _tree_digest_map(
            meridian_root / "proficiency_scales",
            workspace,
        ),
        "grade_items": _tree_digest_map(meridian_root / "grade_items", workspace),
        "standards_proficiency": _tree_digest_map(
            meridian_root / "standards_proficiency",
            workspace,
        ),
        "academic_period_proficiency": _tree_digest_map(
            meridian_root / "academic_period_proficiency",
            workspace,
        ),
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_standards_grade_reload.py <workspace>")
    for module_name in (
        "meridian",
        "meridian.standards_grade",
        "meridian.standards_grade_assembly",
        "meridian.standards_grade_result",
        "meridian.standards_grade_storage",
    ):
        _installed_origin(module_name)
    workspace = Path(sys.argv[1]).resolve()
    baseline = json.loads((workspace / BASELINE_NAME).read_text(encoding="utf-8"))
    current = load_current_standards_grade_result(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(current is not None, "Fresh process could not reload selected Grade.")
    assert current is not None
    _require(
        current.snapshot.result_revision == baseline["result_revision"],
        "Fresh-process result revision changed.",
    )
    _require(
        current.result_sha256 == baseline["result_sha256"],
        "Fresh-process result digest changed.",
    )
    _require(
        current.snapshot.calculation_fingerprint
        == baseline["calculation_fingerprint"],
        "Fresh-process calculation fingerprint changed.",
    )
    _require(
        str(current.snapshot.outcome.rounded_grade) == baseline["rounded_grade"],
        "Fresh-process Grade value changed.",
    )
    _require(
        calculate_standards_grade(current.snapshot.inputs) == current.snapshot.outcome,
        "Fresh process cannot reproduce stored Grade from embedded inputs.",
    )
    refreshed = assemble_standards_grade_calculation(
        workspace,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    _require(
        refreshed.outcome == current.snapshot.outcome,
        "Fresh-process live assembly differs from selected Grade result.",
    )
    freshness = assess_standards_grade_result_freshness(
        current.snapshot,
        refreshed.inputs,
    )
    _require(freshness.status == "current", "Fresh-process Grade is stale.")
    _require(freshness.reasons == (), "Fresh-process Grade has stale reasons.")
    _require(
        _upstream_snapshot(workspace) == baseline["upstream"],
        "Fresh-process Grade read mutated producer or proficiency source state.",
    )
    print("Issue #51 fresh-process standards Grade reload passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
