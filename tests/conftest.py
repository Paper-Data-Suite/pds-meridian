from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class DuplicateJsonKeyError(ValueError):
    """Raised when a test fixture repeats an object key."""


def _object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def load_strict_json(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with duplicate-key and number checks."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    value = json.loads(
        text,
        object_pairs_hook=_object_without_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("fixture root must be a JSON object")
    return value


@pytest.fixture
def fixture_loader() -> Callable[[str], dict[str, Any]]:
    def load(relative: str) -> dict[str, Any]:
        return load_strict_json(FIXTURES / relative)

    return load
