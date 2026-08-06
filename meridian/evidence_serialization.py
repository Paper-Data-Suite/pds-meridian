"""Exact mapping conversion for Meridian's immutable evidence inventory."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Final, TypeAlias, cast

from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    academic_work_registration_from_dict,
    academic_work_registration_to_dict,
)
from pds_core.publication_records import (
    PublicationWithdrawal,
    publication_record_from_dict,
    publication_record_to_dict,
    publication_withdrawal_from_dict,
    publication_withdrawal_to_dict,
)

from meridian.evidence import (
    EligibilityStatus,
    EvidenceEligibility,
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    EvidenceTargetIdentity,
    EvidenceValidationError,
    EvidenceValue,
    NativeArtifact,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalar,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    NativeTimestamp,
    ProjectionIdentity,
    StudentSubject,
)

__all__ = [
    "EvidenceSerializationError",
    "evidence_inventory_from_dict",
    "evidence_inventory_to_dict",
]

JsonMapping: TypeAlias = Mapping[str, object]
ScalarType: TypeAlias = str

_SCALAR_KEYS: Final[frozenset[str]] = frozenset({"type", "value"})
_PROJECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "projection_id",
        "projection_contract_version",
        "producer_reader_distribution",
        "producer_reader_version",
    }
)
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "identifier", "sequence"}
)
_ARTIFACT_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "path", "digest_algorithm", "digest"}
)
_TIMESTAMP_KEYS: Final[frozenset[str]] = frozenset({"kind", "value"})
_NATIVE_PROVENANCE_KEYS: Final[frozenset[str]] = frozenset(
    {"references", "artifacts", "timestamps"}
)
_EVIDENCE_PROVENANCE_KEYS: Final[frozenset[str]] = frozenset(
    {"publication", "registration", "withdrawal", "projection", "native"}
)
_SUBJECT_KEYS: Final[frozenset[str]] = frozenset({"student_id"})
_TARGET_IDENTITY_KEYS: Final[frozenset[str]] = frozenset(
    {"target_kind", "target_id"}
)
_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {"target_kind", "target_id", "parent_target", "standard_ids", "sequence"}
)
_SCALE_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"value", "label", "description"}
)
_SCALE_KEYS: Final[frozenset[str]] = frozenset(
    {"scale_id", "contract_version", "order_is_meaningful", "levels"}
)
_VALUE_BASE_KEYS: Final[frozenset[str]] = frozenset({"kind"})
_VALUE_SCALAR_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "scalar_type", "value"}
)
_VALUE_POINTS_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "earned", "possible"}
)
_VALUE_SCALED_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "value", "scale"}
)
_VALUE_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "code", "label", "description"}
)
_ELIGIBILITY_KEYS: Final[frozenset[str]] = frozenset(
    {"status", "policy_id", "policy_version", "reason_codes"}
)
_ITEM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "item_id",
        "subject",
        "target",
        "result_kind",
        "value",
        "provenance",
        "eligibility",
    }
)
_INVENTORY_KEYS: Final[frozenset[str]] = frozenset({"items"})


class EvidenceSerializationError(ValueError):
    """Raised when an evidence mapping violates the exact persistence contract."""


def _mapping(value: object, keys: frozenset[str], label: str) -> JsonMapping:
    if not isinstance(value, Mapping):
        raise EvidenceSerializationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise EvidenceSerializationError(f"{label} keys must be strings.")
    mapping = cast(Mapping[str, object], value)
    actual = frozenset(mapping)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing!r}")
        if unknown:
            details.append(f"unknown={unknown!r}")
        raise EvidenceSerializationError(
            f"{label} must use the exact key set ({', '.join(details)})."
        )
    return mapping


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise EvidenceSerializationError(f"{label} must be a list.")
    return cast(list[object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise EvidenceSerializationError(f"{label} must be a string.")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceSerializationError(f"{label} must be an integer or null.")
    return value


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceSerializationError(f"{label} must be boolean.")
    return value


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as error:
        raise EvidenceSerializationError(
            f"{label} is not a valid ISO datetime."
        ) from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise EvidenceSerializationError(f"{label} must be timezone-aware.")
    return result


def _finite_number(value: object, label: str) -> int | float:
    if type(value) not in {int, float}:
        raise EvidenceSerializationError(f"{label} must be a finite number.")
    number = cast(int | float, value)
    if type(number) is float and not math.isfinite(number):
        raise EvidenceSerializationError(f"{label} must be finite.")
    return number


def _scalar_to_dict(value: NativeScalar) -> dict[str, object]:
    if type(value) is bool:
        scalar_type = "boolean"
    elif type(value) is int:
        scalar_type = "integer"
    elif type(value) is float:
        if not math.isfinite(value):
            raise EvidenceSerializationError("native scalar float must be finite.")
        scalar_type = "float"
    elif type(value) is str:
        scalar_type = "string"
    else:  # pragma: no cover - existing model contract makes this defensive
        raise EvidenceSerializationError("unsupported native scalar type.")
    return {"type": scalar_type, "value": value}


def _scalar_from_dict(data: object, label: str) -> NativeScalar:
    mapping = _mapping(data, _SCALAR_KEYS, label)
    scalar_type = _string(mapping["type"], f"{label}.type")
    value = mapping["value"]
    if scalar_type == "boolean" and type(value) is bool:
        return value
    if scalar_type == "integer" and type(value) is int:
        return value
    if scalar_type == "float" and type(value) is float and math.isfinite(value):
        return value
    if scalar_type == "string" and type(value) is str:
        return value
    raise EvidenceSerializationError(
        f"{label} scalar type and value do not agree exactly."
    )


def _projection_to_dict(value: ProjectionIdentity) -> dict[str, object]:
    return {
        "projection_id": value.projection_id,
        "projection_contract_version": value.projection_contract_version,
        "producer_reader_distribution": value.producer_reader_distribution,
        "producer_reader_version": value.producer_reader_version,
    }


def _projection_from_dict(data: object) -> ProjectionIdentity:
    mapping = _mapping(data, _PROJECTION_KEYS, "projection")
    return ProjectionIdentity(
        projection_id=_string(mapping["projection_id"], "projection_id"),
        projection_contract_version=_string(
            mapping["projection_contract_version"],
            "projection_contract_version",
        ),
        producer_reader_distribution=_string(
            mapping["producer_reader_distribution"],
            "producer_reader_distribution",
        ),
        producer_reader_version=_string(
            mapping["producer_reader_version"],
            "producer_reader_version",
        ),
    )


def _reference_to_dict(value: NativeReference) -> dict[str, object]:
    return {
        "kind": value.kind,
        "identifier": value.identifier,
        "sequence": value.sequence,
    }


def _reference_from_dict(data: object) -> NativeReference:
    mapping = _mapping(data, _REFERENCE_KEYS, "native reference")
    return NativeReference(
        kind=_string(mapping["kind"], "kind"),
        identifier=_optional_string(mapping["identifier"], "identifier"),
        sequence=_optional_int(mapping["sequence"], "sequence"),
    )


def _artifact_to_dict(value: NativeArtifact) -> dict[str, object]:
    return {
        "kind": value.kind,
        "path": value.path,
        "digest_algorithm": value.digest_algorithm,
        "digest": value.digest,
    }


def _artifact_from_dict(data: object) -> NativeArtifact:
    mapping = _mapping(data, _ARTIFACT_KEYS, "native artifact")
    return NativeArtifact(
        kind=_string(mapping["kind"], "kind"),
        path=_optional_string(mapping["path"], "path"),
        digest_algorithm=_optional_string(
            mapping["digest_algorithm"], "digest_algorithm"
        ),
        digest=_optional_string(mapping["digest"], "digest"),
    )


def _timestamp_to_dict(value: NativeTimestamp) -> dict[str, object]:
    return {"kind": value.kind, "value": value.value.isoformat()}


def _timestamp_from_dict(data: object) -> NativeTimestamp:
    mapping = _mapping(data, _TIMESTAMP_KEYS, "native timestamp")
    return NativeTimestamp(
        kind=_string(mapping["kind"], "kind"),
        value=_datetime(mapping["value"], "value"),
    )


def _native_provenance_to_dict(value: NativeProvenance) -> dict[str, object]:
    return {
        "references": [_reference_to_dict(item) for item in value.references],
        "artifacts": [_artifact_to_dict(item) for item in value.artifacts],
        "timestamps": [_timestamp_to_dict(item) for item in value.timestamps],
    }


def _native_provenance_from_dict(data: object) -> NativeProvenance:
    mapping = _mapping(data, _NATIVE_PROVENANCE_KEYS, "native provenance")
    return NativeProvenance(
        references=tuple(
            _reference_from_dict(item)
            for item in _list(mapping["references"], "references")
        ),
        artifacts=tuple(
            _artifact_from_dict(item)
            for item in _list(mapping["artifacts"], "artifacts")
        ),
        timestamps=tuple(
            _timestamp_from_dict(item)
            for item in _list(mapping["timestamps"], "timestamps")
        ),
    )


def _registration_from_dict(data: object) -> AcademicWorkRegistration | None:
    if data is None:
        return None
    try:
        return academic_work_registration_from_dict(data)
    except ValueError as error:
        raise EvidenceSerializationError("registration is invalid.") from error


def _withdrawal_from_dict(data: object) -> PublicationWithdrawal | None:
    if data is None:
        return None
    try:
        return publication_withdrawal_from_dict(data)
    except ValueError as error:
        raise EvidenceSerializationError("withdrawal is invalid.") from error


def _evidence_provenance_to_dict(value: EvidenceProvenance) -> dict[str, object]:
    return {
        "publication": publication_record_to_dict(value.publication),
        "registration": (
            academic_work_registration_to_dict(value.registration)
            if value.registration is not None
            else None
        ),
        "withdrawal": (
            publication_withdrawal_to_dict(value.withdrawal)
            if value.withdrawal is not None
            else None
        ),
        "projection": _projection_to_dict(value.projection),
        "native": _native_provenance_to_dict(value.native),
    }


def _evidence_provenance_from_dict(data: object) -> EvidenceProvenance:
    mapping = _mapping(data, _EVIDENCE_PROVENANCE_KEYS, "evidence provenance")
    try:
        publication = publication_record_from_dict(mapping["publication"])
    except ValueError as error:
        raise EvidenceSerializationError("publication is invalid.") from error
    return EvidenceProvenance(
        publication=publication,
        registration=_registration_from_dict(mapping["registration"]),
        withdrawal=_withdrawal_from_dict(mapping["withdrawal"]),
        projection=_projection_from_dict(mapping["projection"]),
        native=_native_provenance_from_dict(mapping["native"]),
    )


def _subject_to_dict(value: StudentSubject) -> dict[str, object]:
    return {"student_id": value.student_id}


def _subject_from_dict(data: object) -> StudentSubject:
    mapping = _mapping(data, _SUBJECT_KEYS, "student subject")
    return StudentSubject(_string(mapping["student_id"], "student_id"))


def _target_identity_to_dict(value: EvidenceTargetIdentity) -> dict[str, object]:
    return {"target_kind": value.target_kind, "target_id": value.target_id}


def _target_identity_from_dict(data: object) -> EvidenceTargetIdentity:
    mapping = _mapping(data, _TARGET_IDENTITY_KEYS, "target identity")
    return EvidenceTargetIdentity(
        target_kind=_string(mapping["target_kind"], "target_kind"),
        target_id=_optional_string(mapping["target_id"], "target_id"),
    )


def _target_to_dict(value: EvidenceTarget) -> dict[str, object]:
    return {
        "target_kind": value.target_kind,
        "target_id": value.target_id,
        "parent_target": (
            _target_identity_to_dict(value.parent_target)
            if value.parent_target is not None
            else None
        ),
        "standard_ids": list(value.standard_ids),
        "sequence": value.sequence,
    }


def _target_from_dict(data: object) -> EvidenceTarget:
    mapping = _mapping(data, _TARGET_KEYS, "evidence target")
    parent = mapping["parent_target"]
    standards = _list(mapping["standard_ids"], "standard_ids")
    return EvidenceTarget(
        target_kind=_string(mapping["target_kind"], "target_kind"),
        target_id=_optional_string(mapping["target_id"], "target_id"),
        parent_target=(
            _target_identity_from_dict(parent) if parent is not None else None
        ),
        standard_ids=tuple(_string(item, "standard_id") for item in standards),
        sequence=_optional_int(mapping["sequence"], "sequence"),
    )


def _scale_level_to_dict(value: NativeScaleLevel) -> dict[str, object]:
    return {
        "value": _scalar_to_dict(value.value),
        "label": value.label,
        "description": value.description,
    }


def _scale_level_from_dict(data: object) -> NativeScaleLevel:
    mapping = _mapping(data, _SCALE_LEVEL_KEYS, "native scale level")
    return NativeScaleLevel(
        value=_scalar_from_dict(mapping["value"], "level value"),
        label=_optional_string(mapping["label"], "label"),
        description=_optional_string(mapping["description"], "description"),
    )


def _scale_to_dict(value: NativeScale) -> dict[str, object]:
    return {
        "scale_id": value.scale_id,
        "contract_version": value.contract_version,
        "order_is_meaningful": value.order_is_meaningful,
        "levels": [_scale_level_to_dict(item) for item in value.levels],
    }


def _scale_from_dict(data: object) -> NativeScale:
    mapping = _mapping(data, _SCALE_KEYS, "native scale")
    return NativeScale(
        scale_id=_string(mapping["scale_id"], "scale_id"),
        contract_version=_optional_string(
            mapping["contract_version"], "contract_version"
        ),
        order_is_meaningful=_boolean(
            mapping["order_is_meaningful"], "order_is_meaningful"
        ),
        levels=tuple(
            _scale_level_from_dict(item)
            for item in _list(mapping["levels"], "levels")
        ),
    )


def _value_to_dict(value: object) -> dict[str, object]:
    if isinstance(value, NativeScalarValue):
        scalar = _scalar_to_dict(value.value)
        return {
            "kind": "scalar",
            "scalar_type": scalar["type"],
            "value": scalar["value"],
        }
    if isinstance(value, NativePointValue):
        return {"kind": "points", "earned": value.earned, "possible": value.possible}
    if isinstance(value, NativeScaledValue):
        return {
            "kind": "scaled",
            "value": _scalar_to_dict(value.value),
            "scale": _scale_to_dict(value.scale),
        }
    if isinstance(value, NativeStateValue):
        return {
            "kind": "state",
            "code": value.code,
            "label": value.label,
            "description": value.description,
        }
    raise EvidenceSerializationError("unsupported evidence value variant.")


def _value_from_dict(data: object) -> EvidenceValue:
    if not isinstance(data, Mapping):
        raise EvidenceSerializationError("evidence value must be an object.")
    if "kind" not in data:
        raise EvidenceSerializationError("evidence value is missing kind.")
    kind = _string(data["kind"], "kind")
    if kind == "scalar":
        mapping = _mapping(data, _VALUE_SCALAR_KEYS, "scalar value")
        scalar = _scalar_from_dict(
            {"type": mapping["scalar_type"], "value": mapping["value"]},
            "scalar value",
        )
        return NativeScalarValue(scalar)
    if kind == "points":
        mapping = _mapping(data, _VALUE_POINTS_KEYS, "point value")
        return NativePointValue(
            earned=_finite_number(mapping["earned"], "earned"),
            possible=_finite_number(mapping["possible"], "possible"),
        )
    if kind == "scaled":
        mapping = _mapping(data, _VALUE_SCALED_KEYS, "scaled value")
        return NativeScaledValue(
            value=_scalar_from_dict(mapping["value"], "scaled value"),
            scale=_scale_from_dict(mapping["scale"]),
        )
    if kind == "state":
        mapping = _mapping(data, _VALUE_STATE_KEYS, "state value")
        return NativeStateValue(
            code=_string(mapping["code"], "code"),
            label=_optional_string(mapping["label"], "label"),
            description=_optional_string(mapping["description"], "description"),
        )
    if frozenset(data) == _VALUE_BASE_KEYS:
        raise EvidenceSerializationError(f"unsupported evidence value kind: {kind!r}.")
    raise EvidenceSerializationError(f"unsupported evidence value kind: {kind!r}.")


def _eligibility_to_dict(value: EvidenceEligibility) -> dict[str, object]:
    return {
        "status": value.status,
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "reason_codes": list(value.reason_codes),
    }


def _eligibility_from_dict(data: object) -> EvidenceEligibility:
    mapping = _mapping(data, _ELIGIBILITY_KEYS, "evidence eligibility")
    reasons = _list(mapping["reason_codes"], "reason_codes")
    return EvidenceEligibility(
        status=cast(
            EligibilityStatus, _string(mapping["status"], "status")
        ),
        policy_id=_optional_string(mapping["policy_id"], "policy_id"),
        policy_version=_optional_string(
            mapping["policy_version"], "policy_version"
        ),
        reason_codes=tuple(_string(item, "reason_code") for item in reasons),
    )


def _item_to_dict(value: EvidenceItem) -> dict[str, object]:
    return {
        "item_id": value.item_id,
        "subject": _subject_to_dict(value.subject),
        "target": _target_to_dict(value.target),
        "result_kind": value.result_kind,
        "value": _value_to_dict(value.value),
        "provenance": _evidence_provenance_to_dict(value.provenance),
        "eligibility": _eligibility_to_dict(value.eligibility),
    }


def _item_from_dict(data: object) -> EvidenceItem:
    mapping = _mapping(data, _ITEM_KEYS, "evidence item")
    try:
        return EvidenceItem(
            item_id=_string(mapping["item_id"], "item_id"),
            subject=_subject_from_dict(mapping["subject"]),
            target=_target_from_dict(mapping["target"]),
            result_kind=_string(mapping["result_kind"], "result_kind"),
            value=_value_from_dict(mapping["value"]),
            provenance=_evidence_provenance_from_dict(mapping["provenance"]),
            eligibility=_eligibility_from_dict(mapping["eligibility"]),
        )
    except EvidenceValidationError as error:
        raise EvidenceSerializationError("evidence item is invalid.") from error


def evidence_inventory_to_dict(inventory: EvidenceInventory) -> dict[str, object]:
    """Convert one validated immutable inventory to its exact mapping shape."""
    if not isinstance(inventory, EvidenceInventory):
        raise EvidenceSerializationError("inventory must be an EvidenceInventory.")
    return {"items": [_item_to_dict(item) for item in inventory.items]}


def evidence_inventory_from_dict(data: object) -> EvidenceInventory:
    """Parse one exact inventory mapping and reconstruct immutable models."""
    mapping = _mapping(data, _INVENTORY_KEYS, "evidence inventory")
    try:
        return EvidenceInventory(
            tuple(
                _item_from_dict(item)
                for item in _list(mapping["items"], "items")
            )
        )
    except EvidenceValidationError as error:
        raise EvidenceSerializationError("evidence inventory is invalid.") from error
