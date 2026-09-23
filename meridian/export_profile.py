"""Immutable reusable export-profile contracts for Meridian v0.3.

Issue #56 profiles describe representation only. They select exact frozen report
fields (and, when explicit, bounded Core roster fields), output column names and
order, and deterministic tabular representation settings. They do not calculate
Grades, select evidence, apply overrides, discover students, write external
systems, or mutate ReportingSnapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

EXPORT_PROFILE_SCHEMA_VERSION: Final[str] = "1"
EXPORT_PROFILE_RECORD_TYPE: Final[str] = "meridian_export_profile"
EXPORT_SOURCE_FIELD_REGISTRY_VERSION: Final[str] = "1"

MAXIMUM_EXPORT_PROFILE_TITLE_LENGTH: Final[int] = 256
MAXIMUM_EXPORT_PROFILE_PURPOSE_LENGTH: Final[int] = 256
MAXIMUM_EXPORT_PROFILE_RATIONALE_LENGTH: Final[int] = 2000
MAXIMUM_EXPORT_PROFILE_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_EXPORT_COLUMN_NAME_LENGTH: Final[int] = 256
MAXIMUM_EXPORT_ROSTER_EXTRA_FIELD_LENGTH: Final[int] = 256
MAXIMUM_EXPORT_PROFILE_COLUMNS: Final[int] = 64

ExportProfileActorKind: TypeAlias = Literal["teacher"]
ExportFormat: TypeAlias = Literal["csv", "tsv"]
ExportLineEnding: TypeAlias = Literal["lf", "crlf"]
ExportSourceKind: TypeAlias = Literal["snapshot", "roster"]

_EXPORT_FORMATS: Final[frozenset[str]] = frozenset({"csv", "tsv"})
_LINE_ENDINGS: Final[frozenset[str]] = frozenset({"lf", "crlf"})
_ACTOR_KINDS: Final[frozenset[str]] = frozenset({"teacher"})
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

# Closed v1 snapshot-native registry. These names are public profile contract,
# not arbitrary attribute paths into ReportingSnapshot implementation objects.
SNAPSHOT_EXPORT_SOURCE_FIELDS: Final[tuple[str, ...]] = (
    "snapshot.class_id",
    "snapshot.snapshot_id",
    "snapshot.snapshot_sha256",
    "target.student_id",
    "target.school_year",
    "target.period_id",
    "target.calendar_revision",
    "target.calculation_family",
    "row.status",
    "row.unavailable_reason",
    "grade.base_result_status",
    "grade.base_grade",
    "grade.base_freshness_status",
    "grade.effective_grade",
    "grade.effective_source",
    "policy.policy_id",
    "policy.policy_revision",
)

ROSTER_EXPORT_SOURCE_FIELDS: Final[tuple[str, ...]] = (
    "roster.first_name",
    "roster.last_name",
    "roster.display_name",
    "roster.period",
)

_SNAPSHOT_SOURCE_FIELDS: Final[frozenset[str]] = frozenset(
    SNAPSHOT_EXPORT_SOURCE_FIELDS
)
_ROSTER_SOURCE_FIELDS: Final[frozenset[str]] = frozenset(ROSTER_EXPORT_SOURCE_FIELDS)
_ROSTER_EXTRA_PREFIX: Final[str] = "roster.extra:"
_CORE_REQUIRED_ROSTER_FIELDS: Final[frozenset[str]] = frozenset(
    {"class_id", "student_id", "last_name", "first_name", "period"}
)

_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_COLUMN_KEYS: Final[frozenset[str]] = frozenset({"source_field", "output_name"})
_REPRESENTATION_KEYS: Final[frozenset[str]] = frozenset(
    {"format", "include_header", "line_ending", "utf8_bom"}
)
_PROFILE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "profile_id", "profile_revision", "profile_sha256"}
)
_PROFILE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "source_registry_version",
        "class_id",
        "profile_id",
        "profile_revision",
        "supersedes_revision",
        "title",
        "purpose",
        "columns",
        "representation",
        "actor",
        "rationale",
        "revised_at",
    }
)


class ExportProfileError(ValueError):
    """Base error for immutable Export Profile domain contracts."""

    code = "export_profile.invalid"


class ExportProfileValidationError(ExportProfileError):
    """Raised when Export Profile data violates the bounded v1 contract."""

    code = "export_profile.invalid"


class ExportProfileSerializationError(ExportProfileError):
    """Raised when Export Profile JSON is invalid or noncanonical."""

    code = "export_profile.integrity_failed"


@dataclass(frozen=True, slots=True)
class ExportProfileActor:
    """Explicit teacher authorship for one immutable profile revision."""

    kind: ExportProfileActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise ExportProfileValidationError(
                "export profile actor kind must be teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_EXPORT_PROFILE_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExportColumn:
    """One explicit source field and its exact output column/header name."""

    source_field: str
    output_name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_field",
            validate_export_source_field(self.source_field),
        )
        object.__setattr__(
            self,
            "output_name",
            _bounded_text(
                self.output_name,
                "output_name",
                MAXIMUM_EXPORT_COLUMN_NAME_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ExportRepresentation:
    """Bounded deterministic v1 tabular representation settings."""

    format: ExportFormat
    include_header: bool
    line_ending: ExportLineEnding
    utf8_bom: bool

    def __post_init__(self) -> None:
        if self.format not in _EXPORT_FORMATS:
            raise ExportProfileValidationError("format must be csv or tsv.")
        if type(self.include_header) is not bool:
            raise ExportProfileValidationError("include_header must be a boolean.")
        if self.line_ending not in _LINE_ENDINGS:
            raise ExportProfileValidationError("line_ending must be lf or crlf.")
        if type(self.utf8_bom) is not bool:
            raise ExportProfileValidationError("utf8_bom must be a boolean.")


@dataclass(frozen=True, slots=True)
class ExportProfileRevision:
    """One immutable reusable teacher-controlled export-profile revision."""

    schema_version: str
    record_type: str
    source_registry_version: str
    class_id: str
    profile_id: str
    profile_revision: int
    supersedes_revision: int | None
    title: str
    purpose: str
    columns: tuple[ExportColumn, ...]
    representation: ExportRepresentation
    actor: ExportProfileActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != EXPORT_PROFILE_SCHEMA_VERSION:
            raise ExportProfileValidationError('schema_version must be "1".')
        if self.record_type != EXPORT_PROFILE_RECORD_TYPE:
            raise ExportProfileValidationError(
                'record_type must be "meridian_export_profile".'
            )
        if self.source_registry_version != EXPORT_SOURCE_FIELD_REGISTRY_VERSION:
            raise ExportProfileValidationError(
                'source_registry_version must be "1" for Export Profile v1.'
            )
        class_id = _identifier(self.class_id, "class_id")
        profile_id = _identifier(self.profile_id, "profile_id")
        revision = _positive_int(self.profile_revision, "profile_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_linear_revision(revision, supersedes)
        title = _bounded_text(
            self.title,
            "title",
            MAXIMUM_EXPORT_PROFILE_TITLE_LENGTH,
        )
        purpose = _bounded_text(
            self.purpose,
            "purpose",
            MAXIMUM_EXPORT_PROFILE_PURPOSE_LENGTH,
        )
        columns = _columns(self.columns)
        if not isinstance(self.representation, ExportRepresentation):
            raise ExportProfileValidationError(
                "representation must be an ExportRepresentation."
            )
        representation = ExportRepresentation(
            format=self.representation.format,
            include_header=self.representation.include_header,
            line_ending=self.representation.line_ending,
            utf8_bom=self.representation.utf8_bom,
        )
        if not isinstance(self.actor, ExportProfileActor):
            raise ExportProfileValidationError("actor must be an ExportProfileActor.")
        actor = ExportProfileActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_EXPORT_PROFILE_RATIONALE_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "profile_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "representation", representation)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class ExportProfileReference:
    """Exact immutable Export Profile revision and canonical-byte digest."""

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


def validate_export_source_field(value: object) -> str:
    """Validate one closed v1 source-field key without interpreting object paths."""

    if not isinstance(value, str):
        raise ExportProfileValidationError("source_field must be a string.")
    if value in _SNAPSHOT_SOURCE_FIELDS or value in _ROSTER_SOURCE_FIELDS:
        return value
    if value.startswith(_ROSTER_EXTRA_PREFIX):
        suffix = value[len(_ROSTER_EXTRA_PREFIX) :]
        _validate_roster_extra_field_name(suffix)
        return value
    raise ExportProfileValidationError(
        "source_field is not supported by Export Profile source registry v1."
    )


def export_source_kind(value: object) -> ExportSourceKind:
    """Return whether one validated source field is snapshot- or roster-backed."""

    source = validate_export_source_field(value)
    if source in _SNAPSHOT_SOURCE_FIELDS:
        return "snapshot"
    return "roster"


def roster_extra_field_name(value: object) -> str | None:
    """Return the exact Core optional roster column selected by one source field."""

    source = validate_export_source_field(value)
    if not source.startswith(_ROSTER_EXTRA_PREFIX):
        return None
    return source[len(_ROSTER_EXTRA_PREFIX) :]


def export_profile_requires_roster_observation(
    value: ExportProfileRevision,
) -> bool:
    """Return whether this exact profile revision requires current Core roster data."""

    profile = validate_export_profile_revision(value)
    return any(
        export_source_kind(column.source_field) == "roster"
        for column in profile.columns
    )


def validate_export_profile_revision(
    value: ExportProfileRevision,
) -> ExportProfileRevision:
    """Fully revalidate one immutable Export Profile revision."""

    if not isinstance(value, ExportProfileRevision):
        raise ExportProfileValidationError(
            "export profile revision must be an ExportProfileRevision."
        )
    return ExportProfileRevision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        source_registry_version=value.source_registry_version,
        class_id=value.class_id,
        profile_id=value.profile_id,
        profile_revision=value.profile_revision,
        supersedes_revision=value.supersedes_revision,
        title=value.title,
        purpose=value.purpose,
        columns=value.columns,
        representation=value.representation,
        actor=value.actor,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def validate_export_profile_transition(
    previous: ExportProfileRevision,
    candidate: ExportProfileRevision,
) -> ExportProfileRevision:
    """Validate a linear immutable revision transition for one profile family."""

    old = validate_export_profile_revision(previous)
    new = validate_export_profile_revision(candidate)
    if new.class_id != old.class_id:
        raise ExportProfileValidationError(
            "candidate class_id must match previous profile."
        )
    if new.profile_id != old.profile_id:
        raise ExportProfileValidationError(
            "candidate profile_id must match previous profile."
        )
    if new.profile_revision != old.profile_revision + 1:
        raise ExportProfileValidationError(
            "candidate profile_revision must increment by one."
        )
    if new.supersedes_revision != old.profile_revision:
        raise ExportProfileValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise ExportProfileValidationError(
            "candidate revised_at must not be earlier than previous revised_at."
        )
    return new


def export_profile_reference(value: ExportProfileRevision) -> ExportProfileReference:
    """Return the exact digest-bound reference for one Export Profile revision."""

    profile = validate_export_profile_revision(value)
    digest = hashlib.sha256(export_profile_revision_to_json_bytes(profile)).hexdigest()
    return ExportProfileReference(
        class_id=profile.class_id,
        profile_id=profile.profile_id,
        profile_revision=profile.profile_revision,
        profile_sha256=digest,
    )


def export_profile_reference_to_dict(
    value: ExportProfileReference,
) -> dict[str, object]:
    """Convert an exact Export Profile reference to JSON-native data."""

    if not isinstance(value, ExportProfileReference):
        raise ExportProfileValidationError(
            "profile reference must be an ExportProfileReference."
        )
    reference = ExportProfileReference(
        class_id=value.class_id,
        profile_id=value.profile_id,
        profile_revision=value.profile_revision,
        profile_sha256=value.profile_sha256,
    )
    return {
        "class_id": reference.class_id,
        "profile_id": reference.profile_id,
        "profile_revision": reference.profile_revision,
        "profile_sha256": reference.profile_sha256,
    }


def export_profile_reference_from_dict(data: object) -> ExportProfileReference:
    """Parse one exact Export Profile reference."""

    mapping = _exact_mapping(data, _PROFILE_REFERENCE_KEYS, "export profile reference")
    return ExportProfileReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        profile_revision=_require_int(mapping["profile_revision"], "profile_revision"),
        profile_sha256=_require_str(mapping["profile_sha256"], "profile_sha256"),
    )


def export_profile_revision_to_dict(
    value: ExportProfileRevision,
) -> dict[str, object]:
    """Convert a validated Export Profile revision to exact JSON-native data."""

    profile = validate_export_profile_revision(value)
    return {
        "schema_version": profile.schema_version,
        "record_type": profile.record_type,
        "source_registry_version": profile.source_registry_version,
        "class_id": profile.class_id,
        "profile_id": profile.profile_id,
        "profile_revision": profile.profile_revision,
        "supersedes_revision": profile.supersedes_revision,
        "title": profile.title,
        "purpose": profile.purpose,
        "columns": [_column_to_dict(column) for column in profile.columns],
        "representation": _representation_to_dict(profile.representation),
        "actor": _actor_to_dict(profile.actor),
        "rationale": profile.rationale,
        "revised_at": profile.revised_at.isoformat(),
    }


def export_profile_revision_from_dict(data: object) -> ExportProfileRevision:
    """Parse one strict v1 Export Profile revision mapping."""

    mapping = _exact_mapping(data, _PROFILE_KEYS, "export profile revision")
    columns_data = mapping["columns"]
    if not isinstance(columns_data, list):
        raise ExportProfileValidationError("columns must be a JSON array.")
    columns = tuple(_column_from_dict(item) for item in columns_data)
    representation = _representation_from_dict(mapping["representation"])
    actor = _actor_from_dict(mapping["actor"])
    return ExportProfileRevision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        source_registry_version=_require_str(
            mapping["source_registry_version"],
            "source_registry_version",
        ),
        class_id=_require_str(mapping["class_id"], "class_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        profile_revision=_require_int(mapping["profile_revision"], "profile_revision"),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        title=_require_str(mapping["title"], "title"),
        purpose=_require_str(mapping["purpose"], "purpose"),
        columns=columns,
        representation=representation,
        actor=actor,
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def export_profile_revision_to_json_bytes(value: ExportProfileRevision) -> bytes:
    """Serialize one Export Profile revision using canonical UTF-8 JSON."""

    return _canonical_json_bytes(export_profile_revision_to_dict(value))


def export_profile_revision_from_json_bytes(data: bytes) -> ExportProfileRevision:
    """Parse canonical profile JSON and reject alternate encodings."""

    decoded = _decode_json(data, "export profile revision")
    profile = export_profile_revision_from_dict(decoded)
    if export_profile_revision_to_json_bytes(profile) != data:
        raise ExportProfileSerializationError(
            "export profile revision bytes are not the canonical encoding."
        )
    return profile


def _columns(value: object) -> tuple[ExportColumn, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(column, ExportColumn) for column in value
    ):
        raise ExportProfileValidationError(
            "columns must be a tuple of ExportColumn values."
        )
    if not value:
        raise ExportProfileValidationError(
            "export profile must define at least one output column."
        )
    if len(value) > MAXIMUM_EXPORT_PROFILE_COLUMNS:
        raise ExportProfileValidationError(
            "export profile exceeds maximum column count "
            f"{MAXIMUM_EXPORT_PROFILE_COLUMNS}."
        )
    columns = tuple(
        ExportColumn(column.source_field, column.output_name) for column in value
    )
    output_names = tuple(column.output_name for column in columns)
    if len(set(output_names)) != len(output_names):
        raise ExportProfileValidationError(
            "output column names must not contain duplicates."
        )
    # Column order is semantically meaningful and intentionally not sorted.
    return columns


def _column_to_dict(value: ExportColumn) -> dict[str, object]:
    if not isinstance(value, ExportColumn):
        raise ExportProfileValidationError("column must be an ExportColumn.")
    column = ExportColumn(value.source_field, value.output_name)
    return {"source_field": column.source_field, "output_name": column.output_name}


def _column_from_dict(data: object) -> ExportColumn:
    mapping = _exact_mapping(data, _COLUMN_KEYS, "export column")
    return ExportColumn(
        source_field=_require_str(mapping["source_field"], "source_field"),
        output_name=_require_str(mapping["output_name"], "output_name"),
    )


def _representation_to_dict(value: ExportRepresentation) -> dict[str, object]:
    if not isinstance(value, ExportRepresentation):
        raise ExportProfileValidationError(
            "representation must be an ExportRepresentation."
        )
    exact = ExportRepresentation(
        value.format,
        value.include_header,
        value.line_ending,
        value.utf8_bom,
    )
    return {
        "format": exact.format,
        "include_header": exact.include_header,
        "line_ending": exact.line_ending,
        "utf8_bom": exact.utf8_bom,
    }


def _representation_from_dict(data: object) -> ExportRepresentation:
    mapping = _exact_mapping(data, _REPRESENTATION_KEYS, "export representation")
    format_text = _require_str(mapping["format"], "format")
    if format_text not in _EXPORT_FORMATS:
        raise ExportProfileValidationError("format must be csv or tsv.")
    line_ending = _require_str(mapping["line_ending"], "line_ending")
    if line_ending not in _LINE_ENDINGS:
        raise ExportProfileValidationError("line_ending must be lf or crlf.")
    return ExportRepresentation(
        format=cast(ExportFormat, format_text),
        include_header=_require_bool(mapping["include_header"], "include_header"),
        line_ending=cast(ExportLineEnding, line_ending),
        utf8_bom=_require_bool(mapping["utf8_bom"], "utf8_bom"),
    )


def _actor_to_dict(value: ExportProfileActor) -> dict[str, object]:
    if not isinstance(value, ExportProfileActor):
        raise ExportProfileValidationError("actor must be an ExportProfileActor.")
    actor = ExportProfileActor(value.kind, value.actor_id)
    return {"kind": actor.kind, "actor_id": actor.actor_id}


def _actor_from_dict(data: object) -> ExportProfileActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "export profile actor")
    kind = _require_str(mapping["kind"], "actor.kind")
    if kind not in _ACTOR_KINDS:
        raise ExportProfileValidationError("export profile actor kind must be teacher.")
    return ExportProfileActor(
        kind=cast(ExportProfileActorKind, kind),
        actor_id=_require_str(mapping["actor_id"], "actor.actor_id"),
    )


def _validate_roster_extra_field_name(value: object) -> str:
    field = _bounded_text(
        value,
        "roster extra field name",
        MAXIMUM_EXPORT_ROSTER_EXTRA_FIELD_LENGTH,
    )
    if "*" in field:
        raise ExportProfileValidationError(
            "roster extra field name must identify one exact column, not a wildcard."
        )
    if field in _CORE_REQUIRED_ROSTER_FIELDS:
        raise ExportProfileValidationError(
            "required Core roster fields must use their dedicated roster source key."
        )
    return field


def _validate_linear_revision(revision: int, supersedes: int | None) -> None:
    if revision == 1:
        if supersedes is not None:
            raise ExportProfileValidationError(
                "profile revision 1 must use supersedes_revision=null."
            )
        return
    if supersedes != revision - 1:
        raise ExportProfileValidationError(
            "supersedes_revision must equal profile_revision - 1."
        )


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
        raise ExportProfileSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ExportProfileSerializationError(f"{label} data must be immutable bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExportProfileSerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ExportProfileSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ExportProfileSerializationError(f"{label} is not valid JSON.") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ExportProfileSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ExportProfileSerializationError(f"nonfinite JSON number is invalid: {value}.")


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ExportProfileValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ExportProfileValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ExportProfileValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExportProfileValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ExportProfileValidationError(str(error)) from error


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ExportProfileValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise ExportProfileValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ExportProfileValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise ExportProfileValidationError(
            f"{field_name} must be single-line and free of control characters."
        )
    return value


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, maximum)


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise ExportProfileValidationError(f"{field_name} must be greater than zero.")
    return integer


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ExportProfileValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ExportProfileValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExportProfileValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ExportProfileValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExportProfileValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExportProfileValidationError(f"{field_name} must be an integer.")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ExportProfileValidationError(f"{field_name} must be a boolean.")
    return value


__all__ = [
    "EXPORT_PROFILE_RECORD_TYPE",
    "EXPORT_PROFILE_SCHEMA_VERSION",
    "EXPORT_SOURCE_FIELD_REGISTRY_VERSION",
    "MAXIMUM_EXPORT_COLUMN_NAME_LENGTH",
    "MAXIMUM_EXPORT_PROFILE_ACTOR_ID_LENGTH",
    "MAXIMUM_EXPORT_PROFILE_COLUMNS",
    "MAXIMUM_EXPORT_PROFILE_PURPOSE_LENGTH",
    "MAXIMUM_EXPORT_PROFILE_RATIONALE_LENGTH",
    "MAXIMUM_EXPORT_PROFILE_TITLE_LENGTH",
    "MAXIMUM_EXPORT_ROSTER_EXTRA_FIELD_LENGTH",
    "ROSTER_EXPORT_SOURCE_FIELDS",
    "SNAPSHOT_EXPORT_SOURCE_FIELDS",
    "ExportColumn",
    "ExportFormat",
    "ExportLineEnding",
    "ExportProfileActor",
    "ExportProfileActorKind",
    "ExportProfileError",
    "ExportProfileReference",
    "ExportProfileRevision",
    "ExportProfileSerializationError",
    "ExportProfileValidationError",
    "ExportRepresentation",
    "ExportSourceKind",
    "export_profile_reference",
    "export_profile_reference_from_dict",
    "export_profile_reference_to_dict",
    "export_profile_requires_roster_observation",
    "export_profile_revision_from_dict",
    "export_profile_revision_from_json_bytes",
    "export_profile_revision_to_dict",
    "export_profile_revision_to_json_bytes",
    "export_source_kind",
    "roster_extra_field_name",
    "validate_export_profile_revision",
    "validate_export_profile_transition",
    "validate_export_source_field",
]
