from __future__ import annotations

import re
import subprocess
import sys

import pytest

from meridian.storage_path_keys import (
    STORAGE_PATH_KEY_DIGEST_HEX_LENGTH,
    STORAGE_PATH_KEY_JSON_FILENAME_MAX_LENGTH,
    STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH,
    STORAGE_PATH_KEY_MAX_LENGTH,
    STORAGE_PATH_KEY_PREFIX,
    STORAGE_PATH_KEY_SCHEMA_VERSION,
    STORAGE_PATH_NAMESPACE_MAX_LENGTH,
    StoragePathKeyError,
    storage_path_key,
    storage_path_key_json_digest_filename,
    storage_path_key_json_filename,
    validate_storage_path_key,
)


def test_storage_path_key_has_fixed_path_safe_shape() -> None:
    key = storage_path_key("grade_item", "grade-item-1")

    assert len(key) == STORAGE_PATH_KEY_MAX_LENGTH == 67
    assert STORAGE_PATH_KEY_DIGEST_HEX_LENGTH == 64
    assert STORAGE_PATH_KEY_PREFIX == "mk_"
    assert STORAGE_PATH_KEY_SCHEMA_VERSION == 1
    assert re.fullmatch(r"mk_[0-9a-f]{64}", key)


def test_storage_path_key_length_is_independent_of_semantic_identity_length() -> None:
    short = storage_path_key("grade_item", "g")
    long = storage_path_key("grade_item", "g" * 10_000)

    assert len(short) == STORAGE_PATH_KEY_MAX_LENGTH
    assert len(long) == STORAGE_PATH_KEY_MAX_LENGTH
    assert short != long


def test_storage_path_key_uses_full_semantic_value_not_prefix_truncation() -> None:
    common = "grade-" + ("x" * 5_000)
    first = storage_path_key("grade_item", common + "-first")
    second = storage_path_key("grade_item", common + "-second")

    assert first != second


def test_storage_path_key_separates_namespaces() -> None:
    identity = "same-logical-text"

    assert storage_path_key("grade_item", identity) != storage_path_key(
        "reporting_snapshot",
        identity,
    )


def test_storage_path_key_preserves_part_boundaries() -> None:
    assert storage_path_key("membership", "ab", "c") != storage_path_key(
        "membership",
        "a",
        "bc",
    )


def test_storage_path_key_has_stable_known_serialization() -> None:
    assert storage_path_key("grade_item", "alpha") == (
        "mk_d81168a09c18b9693bdc2de50b182f74feac4963582e4ab4badea7620e63b3e7"
    )


def test_storage_path_key_is_deterministic_in_fresh_process() -> None:
    expected = storage_path_key("grade_item", "alpha")
    command = (
        "from meridian.storage_path_keys import storage_path_key; "
        "print(storage_path_key('grade_item', 'alpha'))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == expected
    assert completed.stderr == ""


def test_key_backed_json_leaf_and_digest_leaf_are_explicitly_bounded() -> None:
    key = storage_path_key("reporting_snapshot", "snapshot-" + ("z" * 5_000))

    json_filename = storage_path_key_json_filename(key)
    digest_filename = storage_path_key_json_digest_filename(key)

    assert len(json_filename) == STORAGE_PATH_KEY_JSON_FILENAME_MAX_LENGTH == 72
    assert (
        len(digest_filename)
        == STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH
        == 79
    )
    assert json_filename == f"{key}.json"
    assert digest_filename == f"{key}.json.sha256"


@pytest.mark.parametrize(
    "namespace",
    [
        "",
        "GradeItem",
        "_grade_item",
        "grade-item",
        "grade item",
        "a" * (STORAGE_PATH_NAMESPACE_MAX_LENGTH + 1),
    ],
)
def test_storage_path_key_rejects_invalid_namespace(namespace: str) -> None:
    with pytest.raises(StoragePathKeyError, match="namespace"):
        storage_path_key(namespace, "identity")


def test_storage_path_key_rejects_missing_identity_parts() -> None:
    with pytest.raises(StoragePathKeyError, match="at least one"):
        storage_path_key("grade_item")


def test_storage_path_key_rejects_empty_identity_part() -> None:
    with pytest.raises(StoragePathKeyError, match="must not be empty"):
        storage_path_key("grade_item", "")


def test_storage_path_key_rejects_non_string_identity_part() -> None:
    with pytest.raises(StoragePathKeyError, match="must be a string"):
        storage_path_key("grade_item", 7)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "mk_" + ("a" * 63),
        "mk_" + ("A" * 64),
        "xx_" + ("a" * 64),
        "mk_" + ("g" * 64),
        "mk_" + ("a" * 65),
    ],
)
def test_validate_storage_path_key_rejects_wrong_shape(value: object) -> None:
    with pytest.raises(StoragePathKeyError):
        validate_storage_path_key(value)


def test_validate_storage_path_key_round_trips_generated_key() -> None:
    key = storage_path_key("export_profile", "profile-1")

    assert validate_storage_path_key(key) == key
