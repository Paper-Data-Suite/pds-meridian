"""Fresh-process active-override reload and immutable withdrawal for issue #53."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade_storage import load_current_conventional_grade_result
from meridian.effective_grade import resolve_effective_grade
from meridian.teacher_grade_override import GradeOverrideSourceResultReference
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    commit_teacher_grade_override_withdrawal_preview,
    preview_teacher_grade_override_selection,
    preview_teacher_grade_override_withdrawal,
)
from meridian.teacher_grade_override_storage import (
    load_current_teacher_grade_override,
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


def _selected_source(current: object) -> TeacherGradeOverrideSelectedSource:
    stored = cast(Any, current)
    return TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                "conventional",
                stored.reference,
            ),
            source_status=stored.snapshot.outcome.status,
            base_grade=stored.snapshot.outcome.rounded_grade,
        ),
        freshness_status="current",
        freshness_reasons=(),
    )


def _verify_files(root: Path, data: dict[str, Any]) -> None:
    producer_files = _list(data.get("producer_files"), "Producer files missing.")
    for raw in producer_files:
        item = _mapping(raw, "Producer file entry is malformed.")
        relative = _text(item.get("path"), "Producer file path missing.")
        expected = _text(item.get("sha256"), "Producer file digest missing.")
        _require(
            hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected,
            f"Producer source changed: {relative}",
        )


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
    _require(current is not None, "Fresh process could not reload base result.")
    assert current is not None
    _require(
        current.snapshot.result_revision
        == _integer(data.get("source_revision"), "Source revision missing."),
        "Source result revision changed.",
    )
    _require(
        current.result_sha256
        == _text(data.get("source_sha256"), "Source digest missing."),
        "Source result digest changed.",
    )
    _require(
        hashlib.sha256(current.content).hexdigest()
        == _text(
            data.get("source_content_sha256"),
            "Source-content digest missing.",
        ),
        "Source result bytes changed.",
    )
    digest_path = current.path.with_suffix(".json.sha256")
    _require(
        hashlib.sha256(digest_path.read_bytes()).hexdigest()
        == _text(
            data.get("source_digest_file_sha256"),
            "Source sidecar digest missing.",
        ),
        "Source result digest sidecar changed.",
    )

    selected_override = load_current_teacher_grade_override(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
    )
    _require(selected_override is not None, "Active override did not reload.")
    assert selected_override is not None
    _require(
        selected_override.reference.override_revision
        == _integer(
            data.get("active_override_revision"),
            "Active override revision missing.",
        ),
        "Active override revision changed.",
    )
    _require(
        selected_override.reference.override_sha256
        == _text(
            data.get("active_override_sha256"),
            "Active override digest missing.",
        ),
        "Active override digest changed.",
    )
    source = _selected_source(current)
    effective = resolve_effective_grade(
        source,
        selected_override_reference=selected_override.reference,
        selected_override=selected_override.decision,
    )
    replacement = Decimal(
        _text(data.get("replacement_grade"), "Replacement Grade missing.")
    )
    _require(
        effective.effective_grade == replacement
        and effective.effective_source == "override",
        "Fresh process did not reproduce active override precedence.",
    )

    withdrawal_preview = preview_teacher_grade_override_withdrawal(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
        actor_id="teacher_local",
        rationale="Installed issue #53 withdrawal after fresh-process reload.",
        decided_at=datetime(2026, 9, 10, 23, 30, tzinfo=UTC),
    )
    withdrawn = commit_teacher_grade_override_withdrawal_preview(
        workspace,
        withdrawal_preview,
    )
    still_selected = load_current_teacher_grade_override(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
    )
    _require(still_selected is not None, "Active override selection disappeared.")
    assert still_selected is not None
    _require(
        still_selected.reference == selected_override.reference,
        "Writing withdrawal must not select it.",
    )
    still_effective = resolve_effective_grade(
        source,
        selected_override_reference=still_selected.reference,
        selected_override=still_selected.decision,
    )
    _require(
        still_effective.effective_grade == replacement
        and still_effective.effective_source == "override",
        "Unselected withdrawal changed effective Grade authority.",
    )

    selection = preview_teacher_grade_override_selection(
        workspace,
        withdrawn.stored_reference,
    )
    commit_teacher_grade_override_selection_preview(workspace, selection)
    selected_withdrawal = load_current_teacher_grade_override(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
        "conventional",
    )
    _require(selected_withdrawal is not None, "Withdrawal did not select.")
    assert selected_withdrawal is not None
    _require(
        selected_withdrawal.decision.decision == "withdraw",
        "Selected decision is not withdrawal.",
    )
    data["withdrawal_revision"] = selected_withdrawal.reference.override_revision
    data["withdrawal_sha256"] = selected_withdrawal.reference.override_sha256
    (root / BASELINE_NAME).write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _verify_files(root, data)
    print("Issue #53 fresh-process active override/withdrawal acceptance passed.")


if __name__ == "__main__":
    main()
