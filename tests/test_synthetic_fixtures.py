from __future__ import annotations

from pathlib import Path

import pytest
from conftest import DuplicateJsonKeyError, load_strict_json


def test_baseline_fixtures_are_strict_utf8_objects(
    fixture_loader: object,
) -> None:
    loader = fixture_loader
    assert callable(loader)
    for relative in (
        "core_v0_6/baseline_registration.json",
        "core_v0_6/baseline_publication.json",
        "core_v0_6/baseline_withdrawal.json",
    ):
        value = loader(relative)
        assert isinstance(value, dict)


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"value": 1, "value": 2}\n', encoding="utf-8")
    with pytest.raises(DuplicateJsonKeyError):
        load_strict_json(path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_standard_numbers_are_rejected(tmp_path: Path, constant: str) -> None:
    path = tmp_path / "number.json"
    path.write_text(f'{{"value": {constant}}}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="non-standard JSON number"):
        load_strict_json(path)


def test_non_object_root_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fixture root"):
        load_strict_json(path)


def test_fixture_text_contains_only_synthetic_identity_markers() -> None:
    root = Path(__file__).parent / "fixtures"
    joined = "\n".join(
        path.read_text(encoding="utf-8") for path in root.rglob("*.json")
    )
    assert "synthetic_" in joined
    assert "C:\\Users\\" not in joined
    assert "/home/" not in joined
    assert "@" not in joined
