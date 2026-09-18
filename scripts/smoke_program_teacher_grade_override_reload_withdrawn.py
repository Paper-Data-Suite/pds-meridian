"""Fresh-process selected-withdrawal reload for installed issue #53 acceptance."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade_storage import load_current_conventional_grade_result
from meridian.effective_grade import resolve_effective_grade
from meridian.teacher_grade_override import GradeOverrideSourceResultReference
from meridian.teacher_grade_override_storage import (
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceResult,
)

BASELINE_NAME = "issue53-teacher-grade-override-baseline.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return cast(dict[str, Any], value)


def _list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise RuntimeError(message)
    return value


def _text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(message)
    return value


def _integer(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(message)
    return value


def main() -> None:
    root = Path(".").resolve()
    data = _mapping(
        json.loads((root / BASELINE_NAME).read_text(encoding="utf-8")),
        "Issue #53 baseline must be a JSON object.",
    )
    workspace = root / _text(data.get("workspace"), "Workspace missing.")
    class_id = _text(data.get("class_id"), "Class identity missing.")
    student_id = _text(data.get("student_id"), "Student identity missing.")
    period = AcademicPeriodRef(
        _text(data.get("school_year"), "School year missing."),
        _text(data.get("period_id"), "Period identity missing."),
    )
    calendar_revision = _integer(
        data.get("calendar_revision"),
        "Calendar revision missing.",
    )
    current = load_current_conventional_grade_result(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
    )
    _require(current is not None, "Base result did not reload after withdrawal.")
    assert current is not None
    _require(
        current.result_sha256
        == _text(data.get("source_sha256"), "Source digest missing."),
        "Base result identity changed.",
    )
    _require(
        hashlib.sha256(current.content).hexdigest()
        == _text(
            data.get("source_content_sha256"),
            "Source-content digest missing.",
        ),
        "Base result bytes changed.",
    )
    _require(
        hashlib.sha256(
            current.path.with_suffix(".json.sha256").read_bytes()
        ).hexdigest()
        == _text(
            data.get("source_digest_file_sha256"),
            "Source sidecar digest missing.",
        ),
        "Base result digest sidecar changed.",
    )

    selected = load_current_teacher_grade_override(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
    )
    _require(selected is not None, "Selected withdrawal did not reload.")
    assert selected is not None
    _require(selected.decision.decision == "withdraw", "Expected selected withdrawal.")
    _require(
        selected.reference.override_revision
        == _integer(data.get("withdrawal_revision"), "Withdrawal revision missing."),
        "Withdrawal revision changed.",
    )
    _require(
        selected.reference.override_sha256
        == _text(data.get("withdrawal_sha256"), "Withdrawal digest missing."),
        "Withdrawal digest changed.",
    )
    source = TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "conventional",
                current.reference,
            ),
            source_status=current.snapshot.outcome.status,
            base_grade=current.snapshot.outcome.rounded_grade,
        ),
        freshness_status="current",
        freshness_reasons=(),
    )
    effective = resolve_effective_grade(
        source,
        selected_override_reference=selected.reference,
        selected_override=selected.decision,
    )
    _require(
        effective.override_applicability == "withdrawn",
        "Selected withdrawal did not remain authoritative.",
    )
    _require(
        effective.effective_grade == Decimal("100.00")
        and effective.effective_source == "base",
        "Base Grade did not regain precedence after selected withdrawal.",
    )

    history = list_teacher_grade_override_revisions(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
    )
    _require(history == (1, 2), "Installed override history is not exact (1, 2).")
    active = load_teacher_grade_override_revision(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
        1,
    )
    _require(active.decision.decision == "override", "Original override was mutated.")
    _require(
        active.override_sha256
        == _text(
            data.get("active_override_sha256"),
            "Original override digest missing.",
        ),
        "Original override digest changed after withdrawal.",
    )

    producer_files = _list(data.get("producer_files"), "Producer files missing.")
    for raw in producer_files:
        item = _mapping(raw, "Producer file entry malformed.")
        relative = _text(item.get("path"), "Producer path missing.")
        expected = _text(item.get("sha256"), "Producer digest missing.")
        _require(
            hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected,
            f"Producer source changed: {relative}",
        )
    print("Issue #53 fresh-process selected-withdrawal acceptance passed.")


if __name__ == "__main__":
    main()
