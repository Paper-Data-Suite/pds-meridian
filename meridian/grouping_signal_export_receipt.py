"""Immutable Meridian audit receipt for one exact Core grouping-signal export."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

from pds_core.grouping_signals import (
    GROUPING_SIGNAL_CONTRACT_NAME,
    GroupingSignalSet,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
    grouping_signal_derivation_reference_from_dict,
    grouping_signal_derivation_reference_to_dict,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewReference,
    grouping_signal_preview_reference_from_dict,
    grouping_signal_preview_reference_to_dict,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewReference,
    grouping_signal_review_reference_from_dict,
    grouping_signal_review_reference_to_dict,
)

GROUPING_SIGNAL_EXPORT_RECEIPT_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_EXPORT_RECEIPT_RECORD_TYPE: Final[str] = (
    "meridian_grouping_signal_export_receipt"
)
MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES: Final[int] = 512 * 1024
GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_ALGORITHM: Final[str] = "sha256"

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "signal_set_id",
        "created_at",
        "derivation_reference",
        "preview_reference",
        "review_reference",
        "core_contract",
        "core_digest_algorithm",
        "core_signal_digest",
    }
)
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "signal_set_id", "receipt_sha256"}
)


class GroupingSignalExportReceiptError(ValueError):
    """Base error for #40 export-receipt domain state."""


class GroupingSignalExportReceiptValidationError(
    GroupingSignalExportReceiptError
):
    """Raised when an export receipt violates its closed contract."""


class GroupingSignalExportReceiptSerializationError(
    GroupingSignalExportReceiptError
):
    """Raised when export-receipt JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GroupingSignalExportReceipt:
    """Privacy-minimal exact authorization/audit binding for one Core signal."""

    schema_version: str
    record_type: str
    class_id: str
    signal_set_id: str
    created_at: datetime
    derivation_reference: GroupingSignalDerivationReference
    preview_reference: GroupingSignalPreviewReference
    review_reference: GroupingSignalReviewReference
    core_contract: str
    core_digest_algorithm: str
    core_signal_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != GROUPING_SIGNAL_EXPORT_RECEIPT_SCHEMA_VERSION:
            raise GroupingSignalExportReceiptValidationError(
                "unsupported grouping-signal export receipt schema_version."
            )
        if self.record_type != GROUPING_SIGNAL_EXPORT_RECEIPT_RECORD_TYPE:
            raise GroupingSignalExportReceiptValidationError(
                "record_type must identify a grouping-signal export receipt."
            )

        class_id = _identifier(self.class_id, "class_id")
        signal_set_id = _identifier(self.signal_set_id, "signal_set_id")
        created_at = _aware_utc_datetime(self.created_at, "created_at")

        if not isinstance(
            self.derivation_reference,
            GroupingSignalDerivationReference,
        ):
            raise GroupingSignalExportReceiptValidationError(
                "derivation_reference must be an exact #38 reference."
            )
        self.derivation_reference.__post_init__()
        if not isinstance(
            self.preview_reference,
            GroupingSignalPreviewReference,
        ):
            raise GroupingSignalExportReceiptValidationError(
                "preview_reference must be an exact #39 preview reference."
            )
        self.preview_reference.__post_init__()
        if not isinstance(self.review_reference, GroupingSignalReviewReference):
            raise GroupingSignalExportReceiptValidationError(
                "review_reference must be an exact #39 review reference."
            )
        self.review_reference.__post_init__()

        if (
            self.derivation_reference.class_id != class_id
            or self.preview_reference.class_id != class_id
            or self.review_reference.class_id != class_id
            or self.review_reference.derivation_id
            != self.derivation_reference.derivation_id
        ):
            raise GroupingSignalExportReceiptValidationError(
                "receipt provenance must share one exact class/derivation scope."
            )

        if self.core_contract != GROUPING_SIGNAL_CONTRACT_NAME:
            raise GroupingSignalExportReceiptValidationError(
                f"core_contract must be {GROUPING_SIGNAL_CONTRACT_NAME!r}."
            )
        if (
            self.core_digest_algorithm
            != GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_ALGORITHM
        ):
            raise GroupingSignalExportReceiptValidationError(
                'core_digest_algorithm must be "sha256".'
            )
        core_digest = _sha256(self.core_signal_digest, "core_signal_digest")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "signal_set_id", signal_set_id)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "core_signal_digest", core_digest)


@dataclass(frozen=True, slots=True)
class GroupingSignalExportReceiptReference:
    """Exact immutable export receipt identity and canonical-byte digest."""

    class_id: str
    signal_set_id: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "signal_set_id",
            _identifier(self.signal_set_id, "signal_set_id"),
        )
        object.__setattr__(
            self,
            "receipt_sha256",
            _sha256(self.receipt_sha256, "receipt_sha256"),
        )


def create_grouping_signal_export_receipt(
    *,
    derivation_reference: GroupingSignalDerivationReference,
    preview_reference: GroupingSignalPreviewReference,
    review_reference: GroupingSignalReviewReference,
    signal: GroupingSignalSet,
    core_signal_digest: str,
) -> GroupingSignalExportReceipt:
    """Build the minimal Meridian audit binding for an exact stored Core signal."""

    if not isinstance(signal, GroupingSignalSet):
        raise GroupingSignalExportReceiptValidationError(
            "signal must be a Core GroupingSignalSet."
        )
    if (
        signal.source.kind != "module_generated"
        or signal.source.module_id != "meridian"
        or signal.source.snapshot_id != derivation_reference.derivation_id
        or signal.source.snapshot_digest_algorithm != "sha256"
        or signal.source.snapshot_digest
        != derivation_reference.derivation_sha256
    ):
        raise GroupingSignalExportReceiptValidationError(
            "Core signal source must bind the exact Meridian #38 derivation."
        )
    if signal.class_id != derivation_reference.class_id:
        raise GroupingSignalExportReceiptValidationError(
            "Core signal class must match the exact #38 derivation."
        )

    return GroupingSignalExportReceipt(
        schema_version=GROUPING_SIGNAL_EXPORT_RECEIPT_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_EXPORT_RECEIPT_RECORD_TYPE,
        class_id=signal.class_id,
        signal_set_id=signal.signal_set_id,
        created_at=signal.created_at,
        derivation_reference=derivation_reference,
        preview_reference=preview_reference,
        review_reference=review_reference,
        core_contract=GROUPING_SIGNAL_CONTRACT_NAME,
        core_digest_algorithm=GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_ALGORITHM,
        core_signal_digest=core_signal_digest,
    )


def validate_grouping_signal_export_receipt(
    value: GroupingSignalExportReceipt,
) -> GroupingSignalExportReceipt:
    if not isinstance(value, GroupingSignalExportReceipt):
        raise GroupingSignalExportReceiptValidationError(
            "value must be a GroupingSignalExportReceipt."
        )
    value.__post_init__()
    return value


def grouping_signal_export_receipt_to_dict(
    value: GroupingSignalExportReceipt,
) -> dict[str, object]:
    receipt = validate_grouping_signal_export_receipt(value)
    return {
        "schema_version": receipt.schema_version,
        "record_type": receipt.record_type,
        "class_id": receipt.class_id,
        "signal_set_id": receipt.signal_set_id,
        "created_at": receipt.created_at.isoformat(),
        "derivation_reference": grouping_signal_derivation_reference_to_dict(
            receipt.derivation_reference
        ),
        "preview_reference": grouping_signal_preview_reference_to_dict(
            receipt.preview_reference
        ),
        "review_reference": grouping_signal_review_reference_to_dict(
            receipt.review_reference
        ),
        "core_contract": receipt.core_contract,
        "core_digest_algorithm": receipt.core_digest_algorithm,
        "core_signal_digest": receipt.core_signal_digest,
    }


def grouping_signal_export_receipt_from_dict(
    data: object,
) -> GroupingSignalExportReceipt:
    mapping = _exact_mapping(data, _KEYS, "grouping-signal export receipt")
    return GroupingSignalExportReceipt(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        signal_set_id=_require_str(mapping["signal_set_id"], "signal_set_id"),
        created_at=_datetime_from_text(mapping["created_at"], "created_at"),
        derivation_reference=grouping_signal_derivation_reference_from_dict(
            mapping["derivation_reference"]
        ),
        preview_reference=grouping_signal_preview_reference_from_dict(
            mapping["preview_reference"]
        ),
        review_reference=grouping_signal_review_reference_from_dict(
            mapping["review_reference"]
        ),
        core_contract=_require_str(mapping["core_contract"], "core_contract"),
        core_digest_algorithm=_require_str(
            mapping["core_digest_algorithm"],
            "core_digest_algorithm",
        ),
        core_signal_digest=_require_str(
            mapping["core_signal_digest"],
            "core_signal_digest",
        ),
    )


def grouping_signal_export_receipt_to_json_bytes(
    value: GroupingSignalExportReceipt,
) -> bytes:
    payload = _canonical_json_bytes(grouping_signal_export_receipt_to_dict(value))
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES:
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt exceeds bounded canonical JSON size."
        )
    return payload


def grouping_signal_export_receipt_from_json_bytes(
    payload: bytes,
) -> GroupingSignalExportReceipt:
    if not isinstance(payload, bytes):
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt JSON must be bytes."
        )
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_EXPORT_RECEIPT_BYTES:
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt exceeds bounded canonical JSON size."
        )
    data = _parse_json_bytes(payload)
    value = grouping_signal_export_receipt_from_dict(data)
    if grouping_signal_export_receipt_to_json_bytes(value) != payload:
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt is not canonical JSON."
        )
    return value


def grouping_signal_export_receipt_sha256(
    value: GroupingSignalExportReceipt,
) -> str:
    return hashlib.sha256(
        grouping_signal_export_receipt_to_json_bytes(value)
    ).hexdigest()


def grouping_signal_export_receipt_reference(
    value: GroupingSignalExportReceipt,
) -> GroupingSignalExportReceiptReference:
    receipt = validate_grouping_signal_export_receipt(value)
    return GroupingSignalExportReceiptReference(
        receipt.class_id,
        receipt.signal_set_id,
        grouping_signal_export_receipt_sha256(receipt),
    )


def grouping_signal_export_receipt_reference_to_dict(
    value: GroupingSignalExportReceiptReference,
) -> dict[str, object]:
    if not isinstance(value, GroupingSignalExportReceiptReference):
        raise GroupingSignalExportReceiptValidationError(
            "value must be a GroupingSignalExportReceiptReference."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "signal_set_id": value.signal_set_id,
        "receipt_sha256": value.receipt_sha256,
    }


def grouping_signal_export_receipt_reference_from_dict(
    data: object,
) -> GroupingSignalExportReceiptReference:
    mapping = _exact_mapping(
        data,
        _REFERENCE_KEYS,
        "grouping-signal export receipt reference",
    )
    return GroupingSignalExportReceiptReference(
        _require_str(mapping["class_id"], "class_id"),
        _require_str(mapping["signal_set_id"], "signal_set_id"),
        _require_str(mapping["receipt_sha256"], "receipt_sha256"),
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalExportReceiptValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalExportReceiptValidationError(str(error)) from error


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalExportReceiptValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GroupingSignalExportReceiptValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise GroupingSignalExportReceiptValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise GroupingSignalExportReceiptSerializationError(
            f"{field_name} must be an ISO-8601 datetime."
        ) from error
    normalized = _aware_utc_datetime(parsed, field_name)
    if text != normalized.isoformat():
        raise GroupingSignalExportReceiptSerializationError(
            f"{field_name} must use canonical UTC ISO-8601 form."
        )
    return normalized


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise GroupingSignalExportReceiptSerializationError(
            f"{label} must be a JSON object."
        )
    if any(not isinstance(key, str) for key in data):
        raise GroupingSignalExportReceiptSerializationError(
            f"{label} keys must be strings."
        )
    actual = frozenset(cast(str, key) for key in data)
    if actual != keys:
        raise GroupingSignalExportReceiptSerializationError(
            f"{label} has an invalid closed field set."
        )
    return cast(Mapping[str, object], data)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalExportReceiptSerializationError(
            f"{field_name} must be a string."
        )
    return value


def _canonical_json_bytes(data: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _parse_json_bytes(payload: bytes) -> Mapping[str, object]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt must be UTF-8."
        ) from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (
        json.JSONDecodeError,
        GroupingSignalExportReceiptSerializationError,
    ) as error:
        if isinstance(error, GroupingSignalExportReceiptSerializationError):
            raise
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt is invalid JSON."
        ) from error
    if not isinstance(value, Mapping):
        raise GroupingSignalExportReceiptSerializationError(
            "grouping-signal export receipt must be a JSON object."
        )
    return cast(Mapping[str, object], value)


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GroupingSignalExportReceiptSerializationError(
                f"duplicate JSON key: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise GroupingSignalExportReceiptSerializationError(
        f"non-standard JSON numeric constant is not permitted: {value}."
    )
