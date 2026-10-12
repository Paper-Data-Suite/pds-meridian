"""Immutable external-gradebook representation mappings for Meridian reports."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.proficiency_mapping import (
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
)

EXTERNAL_GRADEBOOK_MAPPING_SCHEMA_VERSION: Final[str] = "1"
EXTERNAL_GRADEBOOK_MAPPING_RECORD_TYPE: Final[str] = (
    "meridian_external_gradebook_mapping"
)
_MAX_TEXT: Final[int] = 2000
_MAX_VALUE: Final[int] = 256
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class ExternalGradebookMappingError(ValueError):
    """Base error for external-gradebook representation mappings."""

    code = "external_gradebook_mapping.error"


class ExternalGradebookMappingValidationError(ExternalGradebookMappingError):
    """Raised when a mapping revision violates its immutable contract."""

    code = "external_gradebook_mapping.invalid"


class ExternalGradebookMappingSerializationError(ExternalGradebookMappingError):
    """Raised when canonical mapping JSON cannot be trusted."""

    code = "external_gradebook_mapping.integrity_failed"


@dataclass(frozen=True, slots=True)
class ExternalGradebookMappingEntry:
    """One exact Meridian proficiency level -> external representation value."""

    proficiency_level_id: str
    external_value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )
        object.__setattr__(
            self,
            "external_value",
            _bounded_single_line(self.external_value, "external_value", _MAX_VALUE),
        )


@dataclass(frozen=True, slots=True)
class ExternalGradebookMappingRevision:
    """One teacher-owned immutable external-gradebook representation profile."""

    schema_version: str
    record_type: str
    class_id: str
    profile_id: str
    profile_revision: int
    supersedes_revision: int | None
    title: str
    system_label: str
    target_period: AcademicPeriodRef
    target_scale: ProficiencyScaleReference
    entries: tuple[ExternalGradebookMappingEntry, ...]
    actor_id: str
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != EXTERNAL_GRADEBOOK_MAPPING_SCHEMA_VERSION:
            raise ExternalGradebookMappingValidationError(
                'mapping schema_version must be "1".'
            )
        if self.record_type != EXTERNAL_GRADEBOOK_MAPPING_RECORD_TYPE:
            raise ExternalGradebookMappingValidationError(
                "record_type must identify an external-gradebook mapping."
            )
        class_id = _identifier(self.class_id, "class_id")
        profile_id = _identifier(self.profile_id, "profile_id")
        revision = _positive_int(self.profile_revision, "profile_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        if revision == 1 and supersedes is not None:
            raise ExternalGradebookMappingValidationError(
                "mapping revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise ExternalGradebookMappingValidationError(
                "mapping supersedes_revision must identify the prior revision."
            )
        title = _bounded_single_line(self.title, "title", _MAX_TEXT)
        system_label = _bounded_single_line(
            self.system_label,
            "system_label",
            _MAX_TEXT,
        )
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise ExternalGradebookMappingValidationError(
                "target_period must be an AcademicPeriodRef."
            )
        try:
            target_period = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise ExternalGradebookMappingValidationError(str(error)) from error
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise ExternalGradebookMappingValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != class_id:
            raise ExternalGradebookMappingValidationError(
                "target_scale must match the mapping class."
            )
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ExternalGradebookMappingValidationError(
                "entries must be a non-empty tuple."
            )
        entries = tuple(
            ExternalGradebookMappingEntry(
                item.proficiency_level_id,
                item.external_value,
            )
            for item in self.entries
        )
        if entries != tuple(
            sorted(entries, key=lambda item: item.proficiency_level_id)
        ):
            raise ExternalGradebookMappingValidationError(
                "mapping entries must use canonical proficiency-level order."
            )
        level_ids = tuple(item.proficiency_level_id for item in entries)
        if len(set(level_ids)) != len(level_ids):
            raise ExternalGradebookMappingValidationError(
                "mapping entries must not duplicate proficiency levels."
            )
        actor_id = _bounded_single_line(self.actor_id, "actor_id", _MAX_TEXT)
        rationale = (
            None
            if self.rationale is None
            else _bounded_single_line(self.rationale, "rationale", _MAX_TEXT)
        )
        revised_at = _utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "profile_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "system_label", system_label)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class ExternalGradebookMappingReference:
    """Exact immutable mapping revision and digest."""

    class_id: str
    profile_id: str
    profile_revision: int
    profile_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "profile_id",
            _identifier(self.profile_id, "profile_id"),
        )
        object.__setattr__(
            self,
            "profile_revision",
            _positive_int(self.profile_revision, "profile_revision"),
        )
        object.__setattr__(
            self,
            "profile_sha256",
            _sha256(self.profile_sha256, "profile_sha256"),
        )


def compose_external_gradebook_mapping_revision(
    *,
    class_id: str,
    profile_id: str,
    profile_revision: int,
    title: str,
    system_label: str,
    target_period: AcademicPeriodRef,
    target_scale: ProficiencyScaleReference,
    entries: Sequence[ExternalGradebookMappingEntry],
    actor_id: str,
    revised_at: datetime,
    rationale: str | None = None,
) -> ExternalGradebookMappingRevision:
    """Compose one canonical immutable mapping revision."""

    return ExternalGradebookMappingRevision(
        schema_version=EXTERNAL_GRADEBOOK_MAPPING_SCHEMA_VERSION,
        record_type=EXTERNAL_GRADEBOOK_MAPPING_RECORD_TYPE,
        class_id=class_id,
        profile_id=profile_id,
        profile_revision=profile_revision,
        supersedes_revision=(None if profile_revision == 1 else profile_revision - 1),
        title=title,
        system_label=system_label,
        target_period=target_period,
        target_scale=target_scale,
        entries=tuple(sorted(entries, key=lambda item: item.proficiency_level_id)),
        actor_id=actor_id,
        rationale=rationale,
        revised_at=revised_at,
    )


def validate_external_gradebook_mapping_against_scale(
    mapping: ExternalGradebookMappingRevision,
    scale: ProficiencyScale,
) -> ExternalGradebookMappingRevision:
    """Fail closed unless the mapping binds the exact complete scale revision."""

    profile = validate_external_gradebook_mapping(mapping)
    if not isinstance(scale, ProficiencyScale):
        raise ExternalGradebookMappingValidationError(
            "scale must be a ProficiencyScale."
        )
    scale.__post_init__()
    if profile.target_scale != proficiency_scale_reference(scale):
        raise ExternalGradebookMappingValidationError(
            "mapping target_scale does not match the exact proficiency scale."
        )
    expected = {item.level_id for item in scale.levels}
    actual = {item.proficiency_level_id for item in profile.entries}
    if actual != expected:
        raise ExternalGradebookMappingValidationError(
            "mapping must explicitly represent every proficiency level exactly once."
        )
    return profile


def validate_external_gradebook_mapping(
    value: ExternalGradebookMappingRevision,
) -> ExternalGradebookMappingRevision:
    if not isinstance(value, ExternalGradebookMappingRevision):
        raise ExternalGradebookMappingValidationError(
            "value must be an ExternalGradebookMappingRevision."
        )
    return ExternalGradebookMappingRevision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        profile_id=value.profile_id,
        profile_revision=value.profile_revision,
        supersedes_revision=value.supersedes_revision,
        title=value.title,
        system_label=value.system_label,
        target_period=value.target_period,
        target_scale=value.target_scale,
        entries=value.entries,
        actor_id=value.actor_id,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def external_gradebook_mapping_reference(
    value: ExternalGradebookMappingRevision,
) -> ExternalGradebookMappingReference:
    mapping = validate_external_gradebook_mapping(value)
    return ExternalGradebookMappingReference(
        class_id=mapping.class_id,
        profile_id=mapping.profile_id,
        profile_revision=mapping.profile_revision,
        profile_sha256=hashlib.sha256(
            external_gradebook_mapping_to_json_bytes(mapping)
        ).hexdigest(),
    )


def external_gradebook_value(
    value: ExternalGradebookMappingRevision,
    proficiency_level_id: str,
) -> str:
    mapping = validate_external_gradebook_mapping(value)
    level_id = _identifier(proficiency_level_id, "proficiency_level_id")
    for entry in mapping.entries:
        if entry.proficiency_level_id == level_id:
            return entry.external_value
    raise ExternalGradebookMappingValidationError(
        "mapping does not represent the requested proficiency level."
    )


def external_gradebook_mapping_to_dict(
    value: ExternalGradebookMappingRevision,
) -> dict[str, object]:
    mapping = validate_external_gradebook_mapping(value)
    return {
        "schema_version": mapping.schema_version,
        "record_type": mapping.record_type,
        "class_id": mapping.class_id,
        "profile_id": mapping.profile_id,
        "profile_revision": mapping.profile_revision,
        "supersedes_revision": mapping.supersedes_revision,
        "title": mapping.title,
        "system_label": mapping.system_label,
        "target_period": academic_period_ref_to_dict(mapping.target_period),
        "target_scale": _scale_reference_to_dict(mapping.target_scale),
        "entries": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "external_value": item.external_value,
            }
            for item in mapping.entries
        ],
        "actor_id": mapping.actor_id,
        "rationale": mapping.rationale,
        "revised_at": _datetime_text(mapping.revised_at),
    }


def external_gradebook_mapping_to_json_bytes(
    value: ExternalGradebookMappingRevision,
) -> bytes:
    return _canonical_json_bytes(external_gradebook_mapping_to_dict(value))


def external_gradebook_mapping_from_json_bytes(
    data: bytes,
) -> ExternalGradebookMappingRevision:
    raw = _decode_json(data)
    mapping = _exact_mapping(
        raw,
        frozenset(
            {
                "schema_version",
                "record_type",
                "class_id",
                "profile_id",
                "profile_revision",
                "supersedes_revision",
                "title",
                "system_label",
                "target_period",
                "target_scale",
                "entries",
                "actor_id",
                "rationale",
                "revised_at",
            }
        ),
        "external-gradebook mapping",
    )
    entries_data = _require_list(mapping["entries"], "entries")
    value = ExternalGradebookMappingRevision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        profile_revision=_require_int(
            mapping["profile_revision"],
            "profile_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        title=_require_str(mapping["title"], "title"),
        system_label=_require_str(mapping["system_label"], "system_label"),
        target_period=academic_period_ref_from_dict(mapping["target_period"]),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        entries=tuple(_entry_from_dict(item) for item in entries_data),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(
            _require_str(mapping["revised_at"], "revised_at")
        ),
    )
    if external_gradebook_mapping_to_json_bytes(value) != data:
        raise ExternalGradebookMappingSerializationError(
            "mapping JSON is not canonically encoded."
        )
    return value


def _entry_from_dict(data: object) -> ExternalGradebookMappingEntry:
    mapping = _exact_mapping(
        data,
        frozenset({"proficiency_level_id", "external_value"}),
        "mapping entry",
    )
    return ExternalGradebookMappingEntry(
        proficiency_level_id=_require_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        external_value=_require_str(mapping["external_value"], "external_value"),
    )


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _scale_reference_from_dict(data: object) -> ProficiencyScaleReference:
    mapping = _exact_mapping(
        data,
        frozenset({"class_id", "scale_id", "scale_revision", "scale_sha256"}),
        "proficiency-scale reference",
    )
    return ProficiencyScaleReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        scale_revision=_require_int(mapping["scale_revision"], "scale_revision"),
        scale_sha256=_require_str(mapping["scale_sha256"], "scale_sha256"),
    )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExternalGradebookMappingValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ExternalGradebookMappingValidationError(str(error)) from error


def _bounded_single_line(value: object, field_name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or "\r" in value
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ExternalGradebookMappingValidationError(
            f"{field_name} must be bounded nonblank single-line text."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExternalGradebookMappingValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ExternalGradebookMappingValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _utc_datetime(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ExternalGradebookMappingValidationError(
            f"{field_name} must be an aware datetime."
        )
    return value.astimezone(UTC)


def _datetime_text(value: datetime) -> str:
    return _utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _datetime_from_text(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise ExternalGradebookMappingSerializationError(
            "revised_at must be an ISO 8601 timestamp."
        ) from error
    return _utc_datetime(parsed, "revised_at")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ExternalGradebookMappingSerializationError(
            "mapping cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes) -> object:
    if type(data) is not bytes:
        raise ExternalGradebookMappingSerializationError(
            "mapping JSON must be immutable bytes."
        )
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ExternalGradebookMappingSerializationError(
            "mapping JSON is invalid."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _exact_mapping(
    data: object,
    expected: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ExternalGradebookMappingSerializationError(
            f"{label} must be a JSON object."
        )
    mapping = cast(Mapping[str, object], data)
    if frozenset(mapping.keys()) != expected:
        raise ExternalGradebookMappingSerializationError(
            f"{label} has unexpected or missing fields."
        )
    return mapping


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExternalGradebookMappingSerializationError(
            f"{field_name} must be a JSON string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExternalGradebookMappingSerializationError(
            f"{field_name} must be a JSON integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ExternalGradebookMappingSerializationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


__all__ = [
    "EXTERNAL_GRADEBOOK_MAPPING_RECORD_TYPE",
    "EXTERNAL_GRADEBOOK_MAPPING_SCHEMA_VERSION",
    "ExternalGradebookMappingEntry",
    "ExternalGradebookMappingError",
    "ExternalGradebookMappingReference",
    "ExternalGradebookMappingRevision",
    "ExternalGradebookMappingSerializationError",
    "ExternalGradebookMappingValidationError",
    "compose_external_gradebook_mapping_revision",
    "external_gradebook_mapping_from_json_bytes",
    "external_gradebook_mapping_reference",
    "external_gradebook_mapping_to_dict",
    "external_gradebook_mapping_to_json_bytes",
    "external_gradebook_value",
    "validate_external_gradebook_mapping",
    "validate_external_gradebook_mapping_against_scale",
]
