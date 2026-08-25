"""Immutable Meridian Grade Item models and canonical serialization."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    module_work_ref_from_dict,
    module_work_ref_to_dict,
    validate_module_work_ref,
)

GRADE_ITEM_SCHEMA_VERSION: Final[str] = "1"
GRADE_ITEM_RECORD_TYPE: Final[str] = "meridian_grade_item"

GradeItemPurpose: TypeAlias = Literal[
    "standards_proficiency",
    "conventional_grade",
    "standards_and_conventional",
    "reporting_only",
]
GradeItemStatus: TypeAlias = Literal["active", "archived"]

GRADE_ITEM_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "standards_proficiency",
        "conventional_grade",
        "standards_and_conventional",
        "reporting_only",
    }
)
GRADE_ITEM_STATUSES: Final[frozenset[str]] = frozenset({"active", "archived"})

_WEIGHTING_KEYS: Final[frozenset[str]] = frozenset(
    {"category_id", "relative_weight"}
)
_WORK_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"work", "registration_revision"}
)
_GRADE_ITEM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "supersedes_revision",
        "title",
        "purpose",
        "status",
        "weighting",
        "created_at",
        "revised_at",
    }
)


class GradeItemError(ValueError):
    """Base error for Grade Item model and serialization failures."""


class GradeItemValidationError(GradeItemError):
    """Raised when Grade Item data violates the contract."""


class GradeItemSerializationError(GradeItemError):
    """Raised when Grade Item JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GradeItemWeightingMetadata:
    """Reserved exact metadata for later conventional/hybrid Grade policy."""

    category_id: str | None = None
    relative_weight: Decimal | None = None

    def __post_init__(self) -> None:
        category = self.category_id
        if category is not None:
            object.__setattr__(
                self,
                "category_id",
                _identifier(category, "category_id"),
            )
        weight = self.relative_weight
        if weight is not None:
            object.__setattr__(
                self,
                "relative_weight",
                _positive_decimal(weight, "relative_weight"),
            )
        if self.category_id is None and self.relative_weight is None:
            raise GradeItemValidationError(
                "weighting must contain category_id or relative_weight."
            )


@dataclass(frozen=True, slots=True)
class GradeItemWorkReference:
    """Exact Core-registered work revision reference for later membership state."""

    work: ModuleWorkRef
    registration_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise GradeItemValidationError("work must be a ModuleWorkRef.")
        try:
            work = validate_module_work_ref(self.work)
        except RoutingModelError as error:
            raise GradeItemValidationError(f"work is invalid: {error}") from error
        object.__setattr__(self, "work", work)
        object.__setattr__(
            self,
            "registration_revision",
            _positive_int(self.registration_revision, "registration_revision"),
        )


@dataclass(frozen=True, slots=True)
class GradeItemRevision:
    """One immutable semantic revision of a Meridian Grade Item."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    grade_item_revision: int
    supersedes_revision: int | None
    title: str
    purpose: GradeItemPurpose
    status: GradeItemStatus
    weighting: GradeItemWeightingMetadata | None
    created_at: datetime
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_ITEM_SCHEMA_VERSION:
            raise GradeItemValidationError('schema_version must be "1".')
        if self.record_type != GRADE_ITEM_RECORD_TYPE:
            raise GradeItemValidationError(
                'record_type must be "meridian_grade_item".'
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        revision = _positive_int(self.grade_item_revision, "grade_item_revision")
        object.__setattr__(self, "grade_item_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise GradeItemValidationError(
                    "revision 1 must use supersedes_revision=null."
                )
        else:
            if supersedes != revision - 1:
                raise GradeItemValidationError(
                    "supersedes_revision must equal grade_item_revision - 1."
                )
        object.__setattr__(self, "title", _title(self.title))
        if self.purpose not in GRADE_ITEM_PURPOSES:
            raise GradeItemValidationError(
                "purpose must be one of: "
                + ", ".join(sorted(GRADE_ITEM_PURPOSES))
                + "."
            )
        if self.status not in GRADE_ITEM_STATUSES:
            raise GradeItemValidationError(
                "status must be one of: "
                + ", ".join(sorted(GRADE_ITEM_STATUSES))
                + "."
            )
        if self.weighting is not None and not isinstance(
            self.weighting, GradeItemWeightingMetadata
        ):
            raise GradeItemValidationError(
                "weighting must be GradeItemWeightingMetadata or None."
            )
        created = _aware_utc_datetime(self.created_at, "created_at")
        revised = _aware_utc_datetime(self.revised_at, "revised_at")
        if revised < created:
            raise GradeItemValidationError(
                "revised_at must not be earlier than created_at."
            )
        if revision == 1 and revised != created:
            raise GradeItemValidationError(
                "revision 1 must use revised_at equal to created_at."
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "revised_at", revised)


def validate_grade_item_revision(value: GradeItemRevision) -> GradeItemRevision:
    """Fully revalidate one Grade Item revision and return a fresh value."""
    if not isinstance(value, GradeItemRevision):
        raise GradeItemValidationError(
            "grade item revision must be a GradeItemRevision."
        )
    weighting = value.weighting
    if weighting is not None:
        weighting = GradeItemWeightingMetadata(
            category_id=weighting.category_id,
            relative_weight=weighting.relative_weight,
        )
    return GradeItemRevision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        grade_item_revision=value.grade_item_revision,
        supersedes_revision=value.supersedes_revision,
        title=value.title,
        purpose=value.purpose,
        status=value.status,
        weighting=weighting,
        created_at=value.created_at,
        revised_at=value.revised_at,
    )


def validate_grade_item_revision_transition(
    previous: GradeItemRevision,
    candidate: GradeItemRevision,
) -> GradeItemRevision:
    """Validate a pure linear transition between immutable revisions."""
    old = validate_grade_item_revision(previous)
    new = validate_grade_item_revision(candidate)
    if new.class_id != old.class_id:
        raise GradeItemValidationError("candidate class_id must match previous.")
    if new.grade_item_id != old.grade_item_id:
        raise GradeItemValidationError(
            "candidate grade_item_id must match previous."
        )
    if new.created_at != old.created_at:
        raise GradeItemValidationError(
            "candidate created_at must match previous."
        )
    if new.grade_item_revision != old.grade_item_revision + 1:
        raise GradeItemValidationError(
            "candidate grade_item_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.grade_item_revision:
        raise GradeItemValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise GradeItemValidationError(
            "candidate revised_at must not be earlier than previous revised_at."
        )
    return new


def grade_item_weighting_to_dict(
    value: GradeItemWeightingMetadata,
) -> dict[str, object]:
    """Convert weighting metadata to its exact JSON-native shape."""
    if not isinstance(value, GradeItemWeightingMetadata):
        raise GradeItemValidationError(
            "weighting must be GradeItemWeightingMetadata."
        )
    validated = GradeItemWeightingMetadata(
        category_id=value.category_id,
        relative_weight=value.relative_weight,
    )
    return {
        "category_id": validated.category_id,
        "relative_weight": (
            _decimal_text(validated.relative_weight)
            if validated.relative_weight is not None
            else None
        ),
    }


def grade_item_weighting_from_dict(data: object) -> GradeItemWeightingMetadata:
    """Parse exact weighting metadata."""
    mapping = _exact_mapping(data, _WEIGHTING_KEYS, "weighting")
    category = mapping["category_id"]
    if category is not None and not isinstance(category, str):
        raise GradeItemValidationError(
            "weighting.category_id must be a string or null."
        )
    weight = mapping["relative_weight"]
    if weight is not None and not isinstance(weight, str):
        raise GradeItemValidationError(
            "weighting.relative_weight must be decimal text or null."
        )
    parsed: Decimal | None = None
    if weight is not None:
        try:
            parsed = Decimal(weight)
        except InvalidOperation as error:
            raise GradeItemValidationError(
                "weighting.relative_weight must be valid decimal text."
            ) from error
    return GradeItemWeightingMetadata(
        category_id=category,
        relative_weight=parsed,
    )


def grade_item_work_reference_to_dict(
    value: GradeItemWorkReference,
) -> dict[str, object]:
    """Convert an exact registered-work revision reference to JSON-native data."""
    if not isinstance(value, GradeItemWorkReference):
        raise GradeItemValidationError(
            "work reference must be a GradeItemWorkReference."
        )
    validated = GradeItemWorkReference(
        work=value.work,
        registration_revision=value.registration_revision,
    )
    return {
        "work": module_work_ref_to_dict(validated.work),
        "registration_revision": validated.registration_revision,
    }


def grade_item_work_reference_from_dict(data: object) -> GradeItemWorkReference:
    """Parse an exact registered-work revision reference."""
    mapping = _exact_mapping(data, _WORK_REFERENCE_KEYS, "grade item work reference")
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except RoutingModelError as error:
        raise GradeItemValidationError(f"work is invalid: {error}") from error
    return GradeItemWorkReference(
        work=work,
        registration_revision=_require_int(
            mapping["registration_revision"], "registration_revision"
        ),
    )


def grade_item_revision_to_dict(value: GradeItemRevision) -> dict[str, object]:
    """Convert a validated Grade Item revision to exact JSON-native data."""
    revision = validate_grade_item_revision(value)
    return {
        "schema_version": revision.schema_version,
        "record_type": revision.record_type,
        "class_id": revision.class_id,
        "grade_item_id": revision.grade_item_id,
        "grade_item_revision": revision.grade_item_revision,
        "supersedes_revision": revision.supersedes_revision,
        "title": revision.title,
        "purpose": revision.purpose,
        "status": revision.status,
        "weighting": (
            grade_item_weighting_to_dict(revision.weighting)
            if revision.weighting is not None
            else None
        ),
        "created_at": revision.created_at.isoformat(),
        "revised_at": revision.revised_at.isoformat(),
    }


def grade_item_revision_from_dict(data: object) -> GradeItemRevision:
    """Parse one exact Grade Item revision mapping."""
    mapping = _exact_mapping(data, _GRADE_ITEM_KEYS, "grade item revision")
    weighting_data = mapping["weighting"]
    weighting = (
        grade_item_weighting_from_dict(weighting_data)
        if weighting_data is not None
        else None
    )
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None and (
        isinstance(supersedes, bool) or not isinstance(supersedes, int)
    ):
        raise GradeItemValidationError(
            "supersedes_revision must be an integer or null."
        )
    return GradeItemRevision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        grade_item_revision=_require_int(
            mapping["grade_item_revision"], "grade_item_revision"
        ),
        supersedes_revision=supersedes,
        title=_require_str(mapping["title"], "title"),
        purpose=cast(
            GradeItemPurpose,
            _require_str(mapping["purpose"], "purpose"),
        ),
        status=cast(
            GradeItemStatus,
            _require_str(mapping["status"], "status"),
        ),
        weighting=weighting,
        created_at=_datetime_from_text(mapping["created_at"], "created_at"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def grade_item_revision_to_json_bytes(value: GradeItemRevision) -> bytes:
    """Return deterministic canonical UTF-8 bytes for one revision."""
    return _canonical_json_bytes(grade_item_revision_to_dict(value))


def grade_item_revision_from_json_bytes(data: bytes) -> GradeItemRevision:
    """Parse exact canonical Grade Item revision bytes."""
    if type(data) is not bytes:
        raise GradeItemSerializationError(
            "grade item revision data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradeItemSerializationError(
            "grade item revision is not valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except GradeItemSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradeItemSerializationError(
            "grade item revision is not valid JSON."
        ) from error
    revision = grade_item_revision_from_dict(decoded)
    if grade_item_revision_to_json_bytes(revision) != data:
        raise GradeItemSerializationError(
            "grade item revision bytes are not the canonical encoding."
        )
    return revision


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise GradeItemSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradeItemSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise GradeItemSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise GradeItemValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise GradeItemValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise GradeItemValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradeItemValidationError(str(error)) from error


def _title(value: object) -> str:
    if not isinstance(value, str):
        raise GradeItemValidationError("title must be a string.")
    if not value.strip():
        raise GradeItemValidationError("title must not be blank.")
    if value != value.strip():
        raise GradeItemValidationError(
            "title must not contain leading or trailing whitespace."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise GradeItemValidationError(
            "title must be single-line and free of control characters."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise GradeItemValidationError(f"{field_name} must be greater than zero.")
    return integer


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise GradeItemValidationError(f"{field_name} must be a Decimal.")
    if not value.is_finite():
        raise GradeItemValidationError(f"{field_name} must be finite.")
    if value <= 0:
        raise GradeItemValidationError(f"{field_name} must be greater than zero.")
    return Decimal(_decimal_text(value))


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise GradeItemValidationError(
            "relative_weight must be a finite positive Decimal."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return text


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GradeItemValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise GradeItemValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise GradeItemValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeItemValidationError(f"{field_name} must be a string.")
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GradeItemValidationError(f"{field_name} must be an integer.")
    return value
