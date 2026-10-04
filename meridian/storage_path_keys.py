"""Bounded deterministic filesystem keys for Meridian-owned storage.

Logical/domain identifiers remain authoritative in structured Meridian records.
This module provides a separate, fixed-size serialization for Meridian-owned
filesystem components.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final

STORAGE_PATH_KEY_SCHEMA_VERSION: Final[int] = 1
STORAGE_PATH_KEY_PREFIX: Final[str] = "mk_"
STORAGE_PATH_KEY_DIGEST_HEX_LENGTH: Final[int] = 64
STORAGE_PATH_KEY_MAX_LENGTH: Final[int] = (
    len(STORAGE_PATH_KEY_PREFIX) + STORAGE_PATH_KEY_DIGEST_HEX_LENGTH
)
STORAGE_PATH_KEY_JSON_FILENAME_MAX_LENGTH: Final[int] = (
    STORAGE_PATH_KEY_MAX_LENGTH + len(".json")
)
STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH: Final[int] = (
    STORAGE_PATH_KEY_MAX_LENGTH + len(".json.sha256")
)
STORAGE_PATH_NAMESPACE_MAX_LENGTH: Final[int] = 64

_NAMESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^[a-z][a-z0-9_]{{0,{STORAGE_PATH_NAMESPACE_MAX_LENGTH - 1}}}$"
)
_PATH_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^{re.escape(STORAGE_PATH_KEY_PREFIX)}"
    rf"[0-9a-f]{{{STORAGE_PATH_KEY_DIGEST_HEX_LENGTH}}}$"
)


class StoragePathKeyError(ValueError):
    """Raised when bounded storage-path-key input or serialization is invalid."""


def storage_path_key(namespace: str, *identity_parts: str) -> str:
    """Return one deterministic fixed-size Meridian filesystem identity.

    ``namespace`` is a stable Meridian-owned semantic namespace such as
    ``grade_item`` or ``reporting_snapshot``. ``identity_parts`` are the exact
    already-validated semantic values that define the storage subject.

    The original semantic values are not truncated or normalized. They are
    retained in authoritative structured records by the owning domain. Only the
    filesystem serialization is opaque and bounded.
    """

    normalized_namespace = _validate_namespace(namespace)
    if not identity_parts:
        raise StoragePathKeyError(
            "storage path identity must contain at least one semantic part."
        )

    parts: list[str] = []
    for index, part in enumerate(identity_parts):
        if not isinstance(part, str):
            raise StoragePathKeyError(
                f"storage path identity part {index} must be a string."
            )
        if part == "":
            raise StoragePathKeyError(
                f"storage path identity part {index} must not be empty."
            )
        parts.append(part)

    payload = {
        "identity_parts": parts,
        "namespace": normalized_namespace,
        "schema_version": STORAGE_PATH_KEY_SCHEMA_VERSION,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    key = f"{STORAGE_PATH_KEY_PREFIX}{digest}"

    if len(key) != STORAGE_PATH_KEY_MAX_LENGTH:
        raise StoragePathKeyError(
            "generated storage path key violates the fixed-length contract."
        )
    if _PATH_KEY_PATTERN.fullmatch(key) is None:
        raise StoragePathKeyError(
            "generated storage path key violates the path-safe key contract."
        )
    return key


def validate_storage_path_key(value: object) -> str:
    """Validate and return one serialized Meridian storage path key."""

    if not isinstance(value, str):
        raise StoragePathKeyError("storage path key must be a string.")
    if len(value) != STORAGE_PATH_KEY_MAX_LENGTH:
        raise StoragePathKeyError(
            "storage path key has an invalid length."
        )
    if _PATH_KEY_PATTERN.fullmatch(value) is None:
        raise StoragePathKeyError(
            "storage path key must use the mk_<lowercase-sha256> form."
        )
    return value


def storage_path_key_json_filename(key: object) -> str:
    """Return the bounded JSON leaf for one validated storage path key."""

    validated = validate_storage_path_key(key)
    filename = f"{validated}.json"
    if len(filename) != STORAGE_PATH_KEY_JSON_FILENAME_MAX_LENGTH:
        raise StoragePathKeyError(
            "generated storage JSON filename violates the fixed-length contract."
        )
    return filename


def storage_path_key_json_digest_filename(key: object) -> str:
    """Return the bounded SHA-256 sidecar leaf for one storage path key."""

    validated = validate_storage_path_key(key)
    filename = f"{validated}.json.sha256"
    if len(filename) != STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH:
        raise StoragePathKeyError(
            "generated storage digest filename violates the fixed-length contract."
        )
    return filename


def _validate_namespace(value: object) -> str:
    if not isinstance(value, str):
        raise StoragePathKeyError("storage path namespace must be a string.")
    if _NAMESPACE_PATTERN.fullmatch(value) is None:
        raise StoragePathKeyError(
            "storage path namespace must start with a lowercase letter and "
            "contain only lowercase letters, digits, and underscores within "
            f"{STORAGE_PATH_NAMESPACE_MAX_LENGTH} characters."
        )
    return value


__all__ = [
    "STORAGE_PATH_KEY_DIGEST_HEX_LENGTH",
    "STORAGE_PATH_KEY_JSON_FILENAME_MAX_LENGTH",
    "STORAGE_PATH_KEY_JSON_SHA256_FILENAME_MAX_LENGTH",
    "STORAGE_PATH_KEY_MAX_LENGTH",
    "STORAGE_PATH_KEY_PREFIX",
    "STORAGE_PATH_KEY_SCHEMA_VERSION",
    "STORAGE_PATH_NAMESPACE_MAX_LENGTH",
    "StoragePathKeyError",
    "storage_path_key",
    "storage_path_key_json_digest_filename",
    "storage_path_key_json_filename",
    "validate_storage_path_key",
]
