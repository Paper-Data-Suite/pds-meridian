"""Fresh-process reload for issue #50 installed conventional-Grade acceptance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import calculate_conventional_grade
from meridian.conventional_grade_storage import load_current_conventional_grade_result

BASELINE_NAME = "issue50-conventional-grade-baseline.json"


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


def _load_baseline(root: Path) -> dict[str, Any]:
    value = json.loads((root / BASELINE_NAME).read_text(encoding="utf-8"))
    data = _mapping(value, "Issue #50 reload baseline must be a JSON object.")
    _require(data.get("schema_version") == "1", "Baseline schema mismatch.")
    return data


def main() -> None:
    _require(metadata.version("pds-core") == "0.6.3", "Core version mismatch.")
    _require(metadata.version("scoreform") == "0.11.0", "ScoreForm version mismatch.")
    for distribution_name, package_name in (
        ("quillan", "quillan"),
        ("pds-concord", "concord"),
    ):
        try:
            metadata.version(distribution_name)
        except metadata.PackageNotFoundError:
            pass
        else:
            raise RuntimeError(f"{distribution_name} must remain absent.")
        _require(
            importlib.util.find_spec(package_name) is None,
            f"{package_name} became importable.",
        )

    root = Path(".").resolve()
    data = _load_baseline(root)
    workspace_name = _text(data.get("workspace"), "Workspace identity is missing.")
    workspace = root / workspace_name
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

    period = AcademicPeriodRef(school_year, period_id)
    current = load_current_conventional_grade_result(
        workspace,
        class_id,
        student_id,
        period,
        calendar_revision,
    )
    _require(current is not None, "Fresh process could not reload current result.")
    assert current is not None
    _require(
        current.snapshot.result_revision == result_revision,
        "Result revision changed.",
    )
    _require(current.result_sha256 == result_sha256, "Result digest changed.")
    _require(
        current.snapshot.calculation_fingerprint == fingerprint,
        "Calculation fingerprint changed.",
    )
    _require(
        str(current.snapshot.outcome.rounded_grade) == rounded_grade,
        "Rounded Grade changed.",
    )
    _require(
        calculate_conventional_grade(current.snapshot.inputs)
        == current.snapshot.outcome,
        "Fresh-process reproduction differs from persisted outcome.",
    )

    producer_files = _list(
        data.get("producer_files"),
        "Producer-file baseline is missing.",
    )
    for raw in producer_files:
        item = _mapping(raw, "Producer-file baseline entry is malformed.")
        relative = _text(item.get("path"), "Producer path is missing.")
        expected = _text(item.get("sha256"), "Producer digest is missing.")
        _require(
            hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected,
            f"Producer source changed: {relative}",
        )
    print("Issue #50 fresh-process conventional-Grade reload passed.")


if __name__ == "__main__":
    main()
