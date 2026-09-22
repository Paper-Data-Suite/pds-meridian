"""Immutable reporting-snapshot foundation contracts for Meridian v0.3.

This first issue #55 slice establishes the versioned report-definition and exact
snapshot-reference primitives that later snapshot storage/workflows build on.
It deliberately does not persist definitions, compose/freeze ReportingSnapshots,
select a current snapshot, export artifacts, or acquire authority over Core,
producer, Grade, proficiency, or override state.
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

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

REPORTING_DEFINITION_SCHEMA_VERSION: Final[str] = "1"
REPORTING_DEFINITION_RECORD_TYPE: Final[str] = "meridian_reporting_definition"

MAXIMUM_REPORTING_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_REPORTING_TITLE_LENGTH: Final[int] = 256
MAXIMUM_REPORTING_PURPOSE_LENGTH: Final[int] = 256
MAXIMUM_REPORTING_RATIONALE_LENGTH: Final[int] = 2000

ReportingActorKind: TypeAlias = Literal["teacher"]
ReportingKind: TypeAlias = Literal["grade_report"]
ReportingAudience: TypeAlias = Literal["teacher"]
ReportingSnapshotRelationship: TypeAlias = Literal[
    "supersedes",
    "corrects",
    "replaces_for_current_use",
]

_ACTOR_KINDS: Final[frozenset[str]] = frozenset({"teacher"})
_REPORT_KINDS: Final[frozenset[str]] = frozenset({"grade_report"})
_AUDIENCES: Final[frozenset[str]] = frozenset({"teacher"})
_SNAPSHOT_RELATIONSHIPS: Final[frozenset[str]] = frozenset(
    {"supersedes", "corrects", "replaces_for_current_use"}
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_DEFINITION_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "definition_id", "definition_revision", "definition_sha256"}
)
_SNAPSHOT_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "snapshot_id", "snapshot_sha256"}
)
_PREDECESSOR_KEYS: Final[frozenset[str]] = frozenset(
    {"relationship", "snapshot_reference"}
)
_DEFINITION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "definition_id",
        "definition_revision",
        "supersedes_revision",
        "report_kind",
        "purpose",
        "title",
        "target_period",
        "intended_audience",
        "actor",
        "rationale",
        "revised_at",
    }
)


class ReportingSnapshotError(ValueError):
    """Base error for immutable reporting-snapshot domain contracts."""

    code = "reporting_snapshot.error"


class ReportingSnapshotValidationError(ReportingSnapshotError):
    """Raised when reporting-snapshot domain data violates its contract."""

    code = "reporting_snapshot.scope_invalid"


class ReportingDefinitionValidationError(ReportingSnapshotValidationError):
    """Raised when a report definition violates the bounded v1 contract."""

    code = "reporting_snapshot.definition_invalid"


class ReportingSnapshotSerializationError(ReportingSnapshotError):
    """Raised when reporting-snapshot JSON is invalid or noncanonical."""

    code = "reporting_snapshot.integrity_failed"


@dataclass(frozen=True, slots=True)
class ReportingActor:
    """Explicit teacher identity for one deliberate reporting action."""

    kind: ReportingActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise ReportingSnapshotValidationError(
                "reporting actor kind must be teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_REPORTING_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ReportingDefinitionRevision:
    """One immutable v1 definition for a teacher-facing Grade report."""

    schema_version: str
    record_type: str
    class_id: str
    definition_id: str
    definition_revision: int
    supersedes_revision: int | None
    report_kind: ReportingKind
    purpose: str
    title: str
    target_period: AcademicPeriodRef
    intended_audience: ReportingAudience
    actor: ReportingActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REPORTING_DEFINITION_SCHEMA_VERSION:
            raise ReportingDefinitionValidationError(
                'reporting definition schema_version must be "1".'
            )
        if self.record_type != REPORTING_DEFINITION_RECORD_TYPE:
            raise ReportingDefinitionValidationError(
                'reporting definition record_type must be '
                '"meridian_reporting_definition".'
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "definition_id",
            _identifier(self.definition_id, "definition_id"),
        )
        revision = _positive_int(self.definition_revision, "definition_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_linear_revision(revision, supersedes)
        if self.report_kind not in _REPORT_KINDS:
            raise ReportingDefinitionValidationError(
                "report_kind must be grade_report."
            )
        purpose = _bounded_text(
            self.purpose,
            "purpose",
            MAXIMUM_REPORTING_PURPOSE_LENGTH,
        )
        title = _bounded_text(
            self.title,
            "title",
            MAXIMUM_REPORTING_TITLE_LENGTH,
        )
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise ReportingDefinitionValidationError(
                "target_period must be an AcademicPeriodRef."
            )
        try:
            target_period = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise ReportingDefinitionValidationError(
                f"target_period is invalid: {error}"
            ) from error
        if self.intended_audience not in _AUDIENCES:
            raise ReportingDefinitionValidationError(
                "intended_audience must be teacher for v1."
            )
        if not isinstance(self.actor, ReportingActor):
            raise ReportingDefinitionValidationError(
                "actor must be a ReportingActor."
            )
        actor = ReportingActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_REPORTING_RATIONALE_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "definition_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class ReportingDefinitionReference:
    """Exact immutable reporting-definition revision and canonical-byte digest."""

    class_id: str
    definition_id: str
    definition_revision: int
    definition_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "definition_id",
            _identifier(self.definition_id, "definition_id"),
        )
        object.__setattr__(
            self,
            "definition_revision",
            _positive_int(self.definition_revision, "definition_revision"),
        )
        object.__setattr__(
            self,
            "definition_sha256",
            _sha256(self.definition_sha256, "definition_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotReference:
    """Exact immutable ReportingSnapshot identity and canonical-byte digest."""

    class_id: str
    snapshot_id: str
    snapshot_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "snapshot_id",
            _identifier(self.snapshot_id, "snapshot_id"),
        )
        object.__setattr__(
            self,
            "snapshot_sha256",
            _sha256(self.snapshot_sha256, "snapshot_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotPredecessor:
    """Explicit immutable relationship from a future snapshot to one predecessor."""

    relationship: ReportingSnapshotRelationship
    snapshot_reference: ReportingSnapshotReference

    def __post_init__(self) -> None:
        if self.relationship not in _SNAPSHOT_RELATIONSHIPS:
            raise ReportingSnapshotValidationError(
                "snapshot relationship must be supersedes, corrects, or "
                "replaces_for_current_use."
            )
        if not isinstance(self.snapshot_reference, ReportingSnapshotReference):
            raise ReportingSnapshotValidationError(
                "snapshot_reference must be a ReportingSnapshotReference."
            )
        object.__setattr__(
            self,
            "snapshot_reference",
            ReportingSnapshotReference(
                class_id=self.snapshot_reference.class_id,
                snapshot_id=self.snapshot_reference.snapshot_id,
                snapshot_sha256=self.snapshot_reference.snapshot_sha256,
            ),
        )


def validate_reporting_definition_revision(
    value: ReportingDefinitionRevision,
) -> ReportingDefinitionRevision:
    """Fully revalidate one immutable reporting-definition revision."""

    if not isinstance(value, ReportingDefinitionRevision):
        raise ReportingDefinitionValidationError(
            "reporting definition must be a ReportingDefinitionRevision."
        )
    return ReportingDefinitionRevision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        definition_id=value.definition_id,
        definition_revision=value.definition_revision,
        supersedes_revision=value.supersedes_revision,
        report_kind=value.report_kind,
        purpose=value.purpose,
        title=value.title,
        target_period=value.target_period,
        intended_audience=value.intended_audience,
        actor=value.actor,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def validate_reporting_definition_transition(
    previous: ReportingDefinitionRevision,
    candidate: ReportingDefinitionRevision,
) -> ReportingDefinitionRevision:
    """Validate a linear immutable revision transition for one definition."""

    old = validate_reporting_definition_revision(previous)
    new = validate_reporting_definition_revision(candidate)
    if new.class_id != old.class_id:
        raise ReportingDefinitionValidationError(
            "candidate class_id must match previous definition."
        )
    if new.definition_id != old.definition_id:
        raise ReportingDefinitionValidationError(
            "candidate definition_id must match previous definition."
        )
    if new.definition_revision != old.definition_revision + 1:
        raise ReportingDefinitionValidationError(
            "candidate definition_revision must increment by one."
        )
    if new.supersedes_revision != old.definition_revision:
        raise ReportingDefinitionValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise ReportingDefinitionValidationError(
            "candidate revised_at must not be earlier than previous revision."
        )
    return new


def reporting_definition_reference(
    value: ReportingDefinitionRevision,
) -> ReportingDefinitionReference:
    """Return the exact digest-bound reference for one definition revision."""

    definition = validate_reporting_definition_revision(value)
    digest = hashlib.sha256(
        reporting_definition_revision_to_json_bytes(definition)
    ).hexdigest()
    return ReportingDefinitionReference(
        class_id=definition.class_id,
        definition_id=definition.definition_id,
        definition_revision=definition.definition_revision,
        definition_sha256=digest,
    )


def reporting_definition_reference_to_dict(
    value: ReportingDefinitionReference,
) -> dict[str, object]:
    """Convert an exact reporting-definition reference to JSON-native data."""

    if not isinstance(value, ReportingDefinitionReference):
        raise ReportingSnapshotValidationError(
            "definition reference must be a ReportingDefinitionReference."
        )
    reference = ReportingDefinitionReference(
        class_id=value.class_id,
        definition_id=value.definition_id,
        definition_revision=value.definition_revision,
        definition_sha256=value.definition_sha256,
    )
    return {
        "class_id": reference.class_id,
        "definition_id": reference.definition_id,
        "definition_revision": reference.definition_revision,
        "definition_sha256": reference.definition_sha256,
    }


def reporting_definition_reference_from_dict(
    data: object,
) -> ReportingDefinitionReference:
    """Parse an exact reporting-definition reference."""

    mapping = _exact_mapping(
        data,
        _DEFINITION_REFERENCE_KEYS,
        "reporting definition reference",
    )
    return ReportingDefinitionReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        definition_id=_require_str(mapping["definition_id"], "definition_id"),
        definition_revision=_require_int(
            mapping["definition_revision"],
            "definition_revision",
        ),
        definition_sha256=_require_str(
            mapping["definition_sha256"],
            "definition_sha256",
        ),
    )


def reporting_snapshot_reference_to_dict(
    value: ReportingSnapshotReference,
) -> dict[str, object]:
    """Convert an exact ReportingSnapshot reference to JSON-native data."""

    if not isinstance(value, ReportingSnapshotReference):
        raise ReportingSnapshotValidationError(
            "snapshot reference must be a ReportingSnapshotReference."
        )
    reference = ReportingSnapshotReference(
        class_id=value.class_id,
        snapshot_id=value.snapshot_id,
        snapshot_sha256=value.snapshot_sha256,
    )
    return {
        "class_id": reference.class_id,
        "snapshot_id": reference.snapshot_id,
        "snapshot_sha256": reference.snapshot_sha256,
    }


def reporting_snapshot_reference_from_dict(
    data: object,
) -> ReportingSnapshotReference:
    """Parse an exact ReportingSnapshot reference."""

    mapping = _exact_mapping(
        data,
        _SNAPSHOT_REFERENCE_KEYS,
        "reporting snapshot reference",
    )
    return ReportingSnapshotReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        snapshot_id=_require_str(mapping["snapshot_id"], "snapshot_id"),
        snapshot_sha256=_require_str(mapping["snapshot_sha256"], "snapshot_sha256"),
    )


def reporting_snapshot_predecessor_to_dict(
    value: ReportingSnapshotPredecessor,
) -> dict[str, object]:
    """Convert one explicit predecessor relationship to JSON-native data."""

    if not isinstance(value, ReportingSnapshotPredecessor):
        raise ReportingSnapshotValidationError(
            "predecessor must be a ReportingSnapshotPredecessor."
        )
    predecessor = ReportingSnapshotPredecessor(
        relationship=value.relationship,
        snapshot_reference=value.snapshot_reference,
    )
    return {
        "relationship": predecessor.relationship,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            predecessor.snapshot_reference
        ),
    }


def reporting_snapshot_predecessor_from_dict(
    data: object,
) -> ReportingSnapshotPredecessor:
    """Parse one explicit predecessor relationship."""

    mapping = _exact_mapping(
        data,
        _PREDECESSOR_KEYS,
        "reporting snapshot predecessor",
    )
    relationship = _require_str(mapping["relationship"], "relationship")
    if relationship not in _SNAPSHOT_RELATIONSHIPS:
        raise ReportingSnapshotValidationError(
            "snapshot relationship must be supersedes, corrects, or "
            "replaces_for_current_use."
        )
    return ReportingSnapshotPredecessor(
        relationship=cast(ReportingSnapshotRelationship, relationship),
        snapshot_reference=reporting_snapshot_reference_from_dict(
            mapping["snapshot_reference"]
        ),
    )


def reporting_definition_revision_to_dict(
    value: ReportingDefinitionRevision,
) -> dict[str, object]:
    """Convert a validated definition revision to exact JSON-native data."""

    definition = validate_reporting_definition_revision(value)
    return {
        "schema_version": definition.schema_version,
        "record_type": definition.record_type,
        "class_id": definition.class_id,
        "definition_id": definition.definition_id,
        "definition_revision": definition.definition_revision,
        "supersedes_revision": definition.supersedes_revision,
        "report_kind": definition.report_kind,
        "purpose": definition.purpose,
        "title": definition.title,
        "target_period": academic_period_ref_to_dict(definition.target_period),
        "intended_audience": definition.intended_audience,
        "actor": _actor_to_dict(definition.actor),
        "rationale": definition.rationale,
        "revised_at": definition.revised_at.isoformat(),
    }


def reporting_definition_revision_from_dict(
    data: object,
) -> ReportingDefinitionRevision:
    """Parse a strict v1 reporting-definition revision."""

    mapping = _exact_mapping(data, _DEFINITION_KEYS, "reporting definition")
    actor_data = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "reporting actor")
    try:
        period = academic_period_ref_from_dict(mapping["target_period"])
    except (AcademicPeriodValidationError, TypeError, ValueError) as error:
        raise ReportingSnapshotValidationError(
            f"target_period is invalid: {error}"
        ) from error
    actor_kind = _require_str(actor_data["kind"], "actor.kind")
    if actor_kind not in _ACTOR_KINDS:
        raise ReportingSnapshotValidationError(
            "reporting actor kind must be teacher."
        )
    report_kind = _require_str(mapping["report_kind"], "report_kind")
    if report_kind not in _REPORT_KINDS:
        raise ReportingSnapshotValidationError("report_kind must be grade_report.")
    intended_audience = _require_str(
        mapping["intended_audience"],
        "intended_audience",
    )
    if intended_audience not in _AUDIENCES:
        raise ReportingSnapshotValidationError(
            "intended_audience must be teacher for v1."
        )
    return ReportingDefinitionRevision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        definition_id=_require_str(mapping["definition_id"], "definition_id"),
        definition_revision=_require_int(
            mapping["definition_revision"],
            "definition_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        report_kind=cast(ReportingKind, report_kind),
        purpose=_require_str(mapping["purpose"], "purpose"),
        title=_require_str(mapping["title"], "title"),
        target_period=period,
        intended_audience=cast(ReportingAudience, intended_audience),
        actor=ReportingActor(
            kind=cast(ReportingActorKind, actor_kind),
            actor_id=_require_str(actor_data["actor_id"], "actor.actor_id"),
        ),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def reporting_definition_revision_to_json_bytes(
    value: ReportingDefinitionRevision,
) -> bytes:
    """Serialize one reporting definition using canonical UTF-8 JSON."""

    return _canonical_json_bytes(reporting_definition_revision_to_dict(value))


def reporting_definition_revision_from_json_bytes(
    data: bytes,
) -> ReportingDefinitionRevision:
    """Parse canonical reporting-definition JSON and reject alternate encodings."""

    decoded = _decode_json(data, "reporting definition")
    definition = reporting_definition_revision_from_dict(decoded)
    if reporting_definition_revision_to_json_bytes(definition) != data:
        raise ReportingSnapshotSerializationError(
            "reporting definition bytes are not the canonical encoding."
        )
    return definition


def _actor_to_dict(value: ReportingActor) -> dict[str, object]:
    if not isinstance(value, ReportingActor):
        raise ReportingSnapshotValidationError("actor must be a ReportingActor.")
    actor = ReportingActor(value.kind, value.actor_id)
    return {"kind": actor.kind, "actor_id": actor.actor_id}


def _validate_linear_revision(revision: int, supersedes: int | None) -> None:
    if revision == 1:
        if supersedes is not None:
            raise ReportingDefinitionValidationError(
                "definition revision 1 must use supersedes_revision=null."
            )
        return
    if supersedes != revision - 1:
        raise ReportingDefinitionValidationError(
            "supersedes_revision must equal definition_revision - 1."
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
        raise ReportingSnapshotSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ReportingSnapshotSerializationError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportingSnapshotSerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportingSnapshotSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportingSnapshotSerializationError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportingSnapshotSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportingSnapshotSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ReportingSnapshotValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ReportingSnapshotValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportingSnapshotValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportingSnapshotValidationError(str(error)) from error


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise ReportingSnapshotValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ReportingSnapshotValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise ReportingSnapshotValidationError(
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
        raise ReportingSnapshotValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ReportingSnapshotValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReportingSnapshotValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ReportingSnapshotValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportingSnapshotValidationError(f"{field_name} must be an integer.")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


__all__ = [
    "MAXIMUM_REPORTING_ACTOR_ID_LENGTH",
    "MAXIMUM_REPORTING_PURPOSE_LENGTH",
    "MAXIMUM_REPORTING_RATIONALE_LENGTH",
    "MAXIMUM_REPORTING_TITLE_LENGTH",
    "REPORTING_DEFINITION_RECORD_TYPE",
    "REPORTING_DEFINITION_SCHEMA_VERSION",
    "ReportingActor",
    "ReportingActorKind",
    "ReportingAudience",
    "ReportingDefinitionReference",
    "ReportingDefinitionRevision",
    "ReportingDefinitionValidationError",
    "ReportingKind",
    "ReportingSnapshotError",
    "ReportingSnapshotPredecessor",
    "ReportingSnapshotReference",
    "ReportingSnapshotRelationship",
    "ReportingSnapshotSerializationError",
    "ReportingSnapshotValidationError",
    "reporting_definition_reference",
    "reporting_definition_reference_from_dict",
    "reporting_definition_reference_to_dict",
    "reporting_definition_revision_from_dict",
    "reporting_definition_revision_from_json_bytes",
    "reporting_definition_revision_to_dict",
    "reporting_definition_revision_to_json_bytes",
    "reporting_snapshot_predecessor_from_dict",
    "reporting_snapshot_predecessor_to_dict",
    "reporting_snapshot_reference_from_dict",
    "reporting_snapshot_reference_to_dict",
    "validate_reporting_definition_revision",
    "validate_reporting_definition_transition",
]
