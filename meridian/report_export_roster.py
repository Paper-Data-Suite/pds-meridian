"""Privacy-bounded Core roster observations for Meridian report exports.

Issue #56 permits an Export Profile to select a narrow set of Core roster fields
that are not frozen inside a ReportingSnapshot.  This module observes only the
selected roster-backed source fields for the exact distinct snapshot student IDs,
canonicalizes that bounded state, and binds it to a SHA-256 digest.  It never
copies a complete roster, mutates Core state, or treats roster order/path/mtime as
material export provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from pds_core.classes import load_class_roster
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.rosters import (
    RosterError,
    StudentRecord,
    student_display_name,
    student_lookup,
)

from meridian.export_profile import (
    ExportProfileRevision,
    ExportProfileValidationError,
    export_source_kind,
    roster_extra_field_name,
    validate_export_profile_revision,
    validate_export_source_field,
)

EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION: Final[str] = "1"
EXPORT_ROSTER_OBSERVATION_RECORD_TYPE: Final[str] = (
    "meridian_export_roster_observation"
)

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_VALUE_KEYS: Final[frozenset[str]] = frozenset({"source_field", "value"})
_STUDENT_KEYS: Final[frozenset[str]] = frozenset({"student_id", "values"})
_OBSERVATION_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "record_type", "class_id", "source_fields", "students"}
)
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "observation_sha256"}
)


class ReportExportRosterError(RuntimeError):
    """Base error for bounded roster observation used by report export."""

    code = "report_export.roster_error"


class ReportExportRosterValidationError(ReportExportRosterError, ValueError):
    """Raised for invalid roster-observation arguments or model values."""

    code = "report_export.roster_invalid"


class ReportExportRosterUnavailableError(ReportExportRosterError):
    """Raised when the canonical Core roster cannot be safely loaded."""

    code = "report_export.roster_unavailable"


class ReportExportRosterSubjectMissingError(ReportExportRosterError):
    """Raised when one exact snapshot student is absent from the roster."""

    code = "report_export.roster_subject_missing"


class ReportExportRosterFieldMissingError(ReportExportRosterError):
    """Raised when an explicitly selected optional roster column is absent."""

    code = "report_export.roster_field_missing"


class ReportExportRosterIntegrityError(ReportExportRosterError):
    """Raised when serialized roster-observation bytes fail closed validation."""

    code = "report_export.roster_integrity_failed"


@dataclass(frozen=True, slots=True)
class ExportRosterObservedValue:
    """One selected roster-backed source field and its observed string value."""

    source_field: str
    value: str

    def __post_init__(self) -> None:
        try:
            source = validate_export_source_field(self.source_field)
        except ExportProfileValidationError as error:
            raise ReportExportRosterValidationError(str(error)) from error
        if export_source_kind(source) != "roster":
            raise ReportExportRosterValidationError(
                "roster observation values must use roster-backed source fields."
            )
        if not isinstance(self.value, str):
            raise ReportExportRosterValidationError(
                "roster observation value must be a string."
            )
        object.__setattr__(self, "source_field", source)


@dataclass(frozen=True, slots=True)
class ExportRosterStudentObservation:
    """Selected roster state for one exact student identity."""

    student_id: str
    values: tuple[ExportRosterObservedValue, ...]

    def __post_init__(self) -> None:
        student_id = _identifier(self.student_id, "student_id")
        if not isinstance(self.values, tuple) or any(
            not isinstance(value, ExportRosterObservedValue) for value in self.values
        ):
            raise ReportExportRosterValidationError(
                "values must be a tuple of ExportRosterObservedValue values."
            )
        values = tuple(
            ExportRosterObservedValue(value.source_field, value.value)
            for value in self.values
        )
        if not values:
            raise ReportExportRosterValidationError(
                "student roster observation must contain at least one selected field."
            )
        source_fields = tuple(value.source_field for value in values)
        if len(set(source_fields)) != len(source_fields):
            raise ReportExportRosterValidationError(
                "student roster observation source fields must not contain duplicates."
            )
        if source_fields != tuple(sorted(source_fields)):
            raise ReportExportRosterValidationError(
                "student roster observation source fields must be canonically sorted."
            )
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class ExportRosterObservation:
    """Exact privacy-minimized roster state material to one export preview."""

    schema_version: str
    record_type: str
    class_id: str
    source_fields: tuple[str, ...]
    students: tuple[ExportRosterStudentObservation, ...]

    def __post_init__(self) -> None:
        if self.schema_version != EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION:
            raise ReportExportRosterValidationError(
                'roster observation schema_version must be "1".'
            )
        if self.record_type != EXPORT_ROSTER_OBSERVATION_RECORD_TYPE:
            raise ReportExportRosterValidationError(
                "roster observation record_type must be "
                '"meridian_export_roster_observation".'
            )
        class_id = _identifier(self.class_id, "class_id")
        source_fields = _roster_source_fields(self.source_fields)
        if not isinstance(self.students, tuple) or any(
            not isinstance(student, ExportRosterStudentObservation)
            for student in self.students
        ):
            raise ReportExportRosterValidationError(
                "students must be a tuple of ExportRosterStudentObservation values."
            )
        students = tuple(
            ExportRosterStudentObservation(student.student_id, student.values)
            for student in self.students
        )
        student_ids = tuple(student.student_id for student in students)
        if len(set(student_ids)) != len(student_ids):
            raise ReportExportRosterValidationError(
                "roster observation student IDs must not contain duplicates."
            )
        if student_ids != tuple(sorted(student_ids)):
            raise ReportExportRosterValidationError(
                "roster observation students must be canonically sorted by student_id."
            )
        for student in students:
            if tuple(value.source_field for value in student.values) != source_fields:
                raise ReportExportRosterValidationError(
                    "every student roster observation must cover exactly the "
                    "observation source fields."
                )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "source_fields", source_fields)
        object.__setattr__(self, "students", students)


@dataclass(frozen=True, slots=True)
class ExportRosterObservationReference:
    """Digest-bound identity for one exact bounded roster observation."""

    class_id: str
    observation_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "observation_sha256",
            _sha256(self.observation_sha256, "observation_sha256"),
        )


def export_profile_roster_source_fields(
    profile: ExportProfileRevision,
) -> tuple[str, ...]:
    """Return the distinct canonical roster-backed fields selected by a profile."""

    exact = validate_export_profile_revision(profile)
    fields = {
        column.source_field
        for column in exact.columns
        if export_source_kind(column.source_field) == "roster"
    }
    return tuple(sorted(fields))


def build_export_roster_observation(
    workspace_root: str | Path,
    profile: ExportProfileRevision,
    student_ids: tuple[str, ...],
) -> ExportRosterObservation | None:
    """Observe only selected roster fields for exact distinct snapshot students.

    Snapshot-native profiles return ``None`` without loading or requiring a Core
    roster.  Roster-backed profiles load the canonical Core roster through its
    public API and fail closed when the roster, an exact student, or an explicitly
    selected optional column is unavailable.
    """

    exact_profile = validate_export_profile_revision(profile)
    source_fields = export_profile_roster_source_fields(exact_profile)
    if not source_fields:
        return None

    selected_student_ids = _student_ids(student_ids)
    try:
        roster = load_class_roster(workspace_root, exact_profile.class_id)
    except (RosterError, OSError, ValueError) as error:
        raise ReportExportRosterUnavailableError(
            "Canonical Core roster is unavailable for roster-backed export fields."
        ) from error

    for source_field in source_fields:
        extra_field = roster_extra_field_name(source_field)
        if extra_field is not None and extra_field not in roster.columns:
            raise ReportExportRosterFieldMissingError(
                "Selected Core roster optional field is absent: "
                f"{extra_field!r}."
            )

    lookup = student_lookup(roster)
    students: list[ExportRosterStudentObservation] = []
    for student_id in selected_student_ids:
        student = lookup.get(student_id)
        if student is None:
            raise ReportExportRosterSubjectMissingError(
                "Snapshot student is absent from the current Core roster: "
                f"{student_id!r}."
            )
        values = tuple(
            ExportRosterObservedValue(
                source_field=source_field,
                value=_roster_value(student, source_field),
            )
            for source_field in source_fields
        )
        students.append(
            ExportRosterStudentObservation(
                student_id=student_id,
                values=values,
            )
        )

    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=exact_profile.class_id,
        source_fields=source_fields,
        students=tuple(students),
    )


def export_roster_observation_sha256(value: ExportRosterObservation) -> str:
    """Return the SHA-256 digest of one exact canonical observation."""

    return hashlib.sha256(export_roster_observation_to_json_bytes(value)).hexdigest()


def export_roster_observation_reference(
    value: ExportRosterObservation,
) -> ExportRosterObservationReference:
    """Return the digest-bound reference for one exact roster observation."""

    observation = validate_export_roster_observation(value)
    return ExportRosterObservationReference(
        class_id=observation.class_id,
        observation_sha256=export_roster_observation_sha256(observation),
    )


def validate_export_roster_observation(
    value: ExportRosterObservation,
) -> ExportRosterObservation:
    """Fully revalidate one bounded roster observation."""

    if not isinstance(value, ExportRosterObservation):
        raise ReportExportRosterValidationError(
            "value must be an ExportRosterObservation."
        )
    return ExportRosterObservation(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        source_fields=value.source_fields,
        students=value.students,
    )


def export_roster_observation_to_dict(
    value: ExportRosterObservation,
) -> dict[str, object]:
    """Convert one validated roster observation to exact JSON-native data."""

    observation = validate_export_roster_observation(value)
    return {
        "schema_version": observation.schema_version,
        "record_type": observation.record_type,
        "class_id": observation.class_id,
        "source_fields": list(observation.source_fields),
        "students": [
            {
                "student_id": student.student_id,
                "values": [
                    {
                        "source_field": item.source_field,
                        "value": item.value,
                    }
                    for item in student.values
                ],
            }
            for student in observation.students
        ],
    }


def export_roster_observation_from_dict(data: object) -> ExportRosterObservation:
    """Parse one strict bounded roster-observation mapping."""

    mapping = _exact_mapping(data, _OBSERVATION_KEYS, "roster observation")
    source_data = mapping["source_fields"]
    if not isinstance(source_data, list) or any(
        not isinstance(item, str) for item in source_data
    ):
        raise ReportExportRosterValidationError(
            "source_fields must be a JSON array of strings."
        )
    student_data = mapping["students"]
    if not isinstance(student_data, list):
        raise ReportExportRosterValidationError(
            "students must be a JSON array."
        )
    students: list[ExportRosterStudentObservation] = []
    for item in student_data:
        student_mapping = _exact_mapping(
            item,
            _STUDENT_KEYS,
            "roster student observation",
        )
        values_data = student_mapping["values"]
        if not isinstance(values_data, list):
            raise ReportExportRosterValidationError(
                "roster student observation values must be a JSON array."
            )
        values: list[ExportRosterObservedValue] = []
        for value_data in values_data:
            value_mapping = _exact_mapping(
                value_data,
                _VALUE_KEYS,
                "roster observed value",
            )
            values.append(
                ExportRosterObservedValue(
                    source_field=_require_str(
                        value_mapping["source_field"],
                        "source_field",
                    ),
                    value=_require_str(value_mapping["value"], "value"),
                )
            )
        students.append(
            ExportRosterStudentObservation(
                student_id=_require_str(
                    student_mapping["student_id"],
                    "student_id",
                ),
                values=tuple(values),
            )
        )
    return ExportRosterObservation(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        source_fields=tuple(cast(list[str], source_data)),
        students=tuple(students),
    )


def export_roster_observation_to_json_bytes(
    value: ExportRosterObservation,
) -> bytes:
    """Serialize one roster observation using canonical UTF-8 JSON."""

    return _canonical_json_bytes(export_roster_observation_to_dict(value))


def export_roster_observation_from_json_bytes(
    data: bytes,
) -> ExportRosterObservation:
    """Parse canonical roster-observation JSON and reject alternate encodings."""

    decoded = _decode_json(data, "roster observation")
    observation = export_roster_observation_from_dict(decoded)
    if export_roster_observation_to_json_bytes(observation) != data:
        raise ReportExportRosterIntegrityError(
            "roster observation bytes are not the canonical encoding."
        )
    return observation


def export_roster_observation_reference_to_dict(
    value: ExportRosterObservationReference,
) -> dict[str, object]:
    """Convert an exact roster-observation reference to JSON-native data."""

    if not isinstance(value, ExportRosterObservationReference):
        raise ReportExportRosterValidationError(
            "value must be ExportRosterObservationReference."
        )
    reference = ExportRosterObservationReference(
        value.class_id,
        value.observation_sha256,
    )
    return {
        "class_id": reference.class_id,
        "observation_sha256": reference.observation_sha256,
    }


def export_roster_observation_reference_from_dict(
    data: object,
) -> ExportRosterObservationReference:
    """Parse one exact roster-observation reference."""

    mapping = _exact_mapping(
        data,
        _REFERENCE_KEYS,
        "roster observation reference",
    )
    return ExportRosterObservationReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        observation_sha256=_require_str(
            mapping["observation_sha256"],
            "observation_sha256",
        ),
    )


def _student_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise ReportExportRosterValidationError(
            "student_ids must be a tuple of student ID strings."
        )
    return tuple(sorted({_identifier(item, "student_id") for item in value}))


def _roster_source_fields(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
        raise ReportExportRosterValidationError(
            "source_fields must be a tuple of source-field strings."
        )
    if not value:
        raise ReportExportRosterValidationError(
            "roster observation must identify at least one source field."
        )
    fields: list[str] = []
    for item in value:
        try:
            source = validate_export_source_field(item)
        except ExportProfileValidationError as error:
            raise ReportExportRosterValidationError(str(error)) from error
        if export_source_kind(source) != "roster":
            raise ReportExportRosterValidationError(
                "roster observation source_fields must all be roster-backed."
            )
        fields.append(source)
    if len(set(fields)) != len(fields):
        raise ReportExportRosterValidationError(
            "roster observation source_fields must not contain duplicates."
        )
    if tuple(fields) != tuple(sorted(fields)):
        raise ReportExportRosterValidationError(
            "roster observation source_fields must be canonically sorted."
        )
    return tuple(fields)


def _roster_value(student: StudentRecord, source_field: str) -> str:
    if source_field == "roster.first_name":
        return student.first_name
    if source_field == "roster.last_name":
        return student.last_name
    if source_field == "roster.period":
        return student.period
    if source_field == "roster.display_name":
        return student_display_name(student)
    extra_field = roster_extra_field_name(source_field)
    if extra_field is None:
        raise ReportExportRosterValidationError(
            "unsupported roster-backed source field reached observation resolution."
        )
    return student.extra_fields[extra_field]


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
        raise ReportExportRosterIntegrityError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ReportExportRosterIntegrityError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportExportRosterIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportExportRosterIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportExportRosterIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportExportRosterIntegrityError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportExportRosterIntegrityError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ReportExportRosterValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ReportExportRosterValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportExportRosterValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportRosterValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportExportRosterValidationError(str(error)) from error


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportExportRosterValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportRosterValidationError(
            f"{field_name} must be a string."
        )
    return value


__all__ = [
    "EXPORT_ROSTER_OBSERVATION_RECORD_TYPE",
    "EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION",
    "ExportRosterObservation",
    "ExportRosterObservationReference",
    "ExportRosterObservedValue",
    "ExportRosterStudentObservation",
    "ReportExportRosterError",
    "ReportExportRosterFieldMissingError",
    "ReportExportRosterIntegrityError",
    "ReportExportRosterSubjectMissingError",
    "ReportExportRosterUnavailableError",
    "ReportExportRosterValidationError",
    "build_export_roster_observation",
    "export_profile_roster_source_fields",
    "export_roster_observation_from_dict",
    "export_roster_observation_from_json_bytes",
    "export_roster_observation_reference",
    "export_roster_observation_reference_from_dict",
    "export_roster_observation_reference_to_dict",
    "export_roster_observation_sha256",
    "export_roster_observation_to_dict",
    "export_roster_observation_to_json_bytes",
    "validate_export_roster_observation",
]
