"""Common deterministic teacher-report preview contracts for Meridian Issue #111."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
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

TEACHER_REPORT_SCHEMA_VERSION: Final[str] = "1"

TeacherReportKind: TypeAlias = Literal[
    "sis_gradebook_reconciliation",
    "student_current_grade_justification",
    "class_standards_profile",
    "student_proficiency_growth",
    "evidence_coverage",
    "grade_checkpoint_comparison",
    "marking_period_readiness",
    "assessment_impact",
]
TeacherReportDiagnosticSeverity: TypeAlias = Literal["info", "warning"]

TEACHER_REPORT_KINDS: Final[tuple[TeacherReportKind, ...]] = (
    "sis_gradebook_reconciliation",
    "student_current_grade_justification",
    "class_standards_profile",
    "student_proficiency_growth",
    "evidence_coverage",
    "grade_checkpoint_comparison",
    "marking_period_readiness",
    "assessment_impact",
)

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_MAX_TEXT: Final[int] = 20_000


class TeacherReportError(ValueError):
    code = "teacher_report.error"


class TeacherReportValidationError(TeacherReportError):
    code = "teacher_report.invalid"


class TeacherReportSerializationError(TeacherReportError):
    code = "teacher_report.integrity_failed"


@dataclass(frozen=True, slots=True)
class TeacherReportSourceReference:
    source_kind: str
    source_id: str
    source_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_kind", _stable_id(self.source_kind, "source_kind")
        )
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(
            self, "source_sha256", _sha256(self.source_sha256, "source_sha256")
        )


@dataclass(frozen=True, slots=True)
class TeacherReportColumn:
    column_id: str
    title: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "column_id", _identifier(self.column_id, "column_id"))
        object.__setattr__(self, "title", _text(self.title, "title"))


@dataclass(frozen=True, slots=True)
class TeacherReportRow:
    row_id: str
    values: tuple[str | None, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_id", _identifier(self.row_id, "row_id"))
        if not isinstance(self.values, tuple):
            raise TeacherReportValidationError("row values must be a tuple.")
        object.__setattr__(
            self,
            "values",
            tuple(None if value is None else _cell(value) for value in self.values),
        )


@dataclass(frozen=True, slots=True)
class TeacherReportDiagnostic:
    code: str
    severity: TeacherReportDiagnosticSeverity
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _stable_id(self.code, "code"))
        if self.severity not in {"info", "warning"}:
            raise TeacherReportValidationError(
                "diagnostic severity must be info or warning."
            )
        object.__setattr__(self, "message", _text(self.message, "message"))


@dataclass(frozen=True, slots=True)
class TeacherReportPreview:
    schema_version: str
    report_kind: TeacherReportKind
    title: str
    class_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    source_references: tuple[TeacherReportSourceReference, ...]
    generated_at: datetime
    summary: tuple[str, ...]
    columns: tuple[TeacherReportColumn, ...]
    rows: tuple[TeacherReportRow, ...]
    diagnostics: tuple[TeacherReportDiagnostic, ...]
    preview_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != TEACHER_REPORT_SCHEMA_VERSION:
            raise TeacherReportValidationError('schema_version must be "1".')
        if self.report_kind not in TEACHER_REPORT_KINDS:
            raise TeacherReportValidationError("unsupported teacher report kind.")
        object.__setattr__(self, "title", _text(self.title, "title"))
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise TeacherReportValidationError(
                "target_period must be an AcademicPeriodRef."
            )
        try:
            period = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise TeacherReportValidationError(str(error)) from error
        object.__setattr__(self, "target_period", period)
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        object.__setattr__(
            self, "generated_at", _utc(self.generated_at, "generated_at")
        )

        sources = tuple(self.source_references)
        if sources != tuple(
            sorted(
                sources,
                key=lambda item: (item.source_kind, item.source_id, item.source_sha256),
            )
        ):
            raise TeacherReportValidationError(
                "source_references must use canonical sort order."
            )
        if len({(item.source_kind, item.source_id) for item in sources}) != len(
            sources
        ):
            raise TeacherReportValidationError(
                "source_references must not duplicate source identity."
            )

        columns = tuple(self.columns)
        if not columns:
            raise TeacherReportValidationError("columns must not be empty.")
        if len({item.column_id for item in columns}) != len(columns):
            raise TeacherReportValidationError("column IDs must be unique.")

        rows = tuple(self.rows)
        if rows != tuple(sorted(rows, key=lambda item: item.row_id)):
            raise TeacherReportValidationError("rows must use canonical row_id order.")
        if len({item.row_id for item in rows}) != len(rows):
            raise TeacherReportValidationError("row IDs must be unique.")
        if any(len(item.values) != len(columns) for item in rows):
            raise TeacherReportValidationError("every row must match the column count.")

        diagnostics = tuple(self.diagnostics)
        expected_diagnostics = tuple(
            sorted(
                diagnostics, key=lambda item: (item.code, item.severity, item.message)
            )
        )
        if diagnostics != expected_diagnostics:
            raise TeacherReportValidationError(
                "diagnostics must use canonical sort order."
            )

        object.__setattr__(self, "summary", tuple(_cell(item) for item in self.summary))
        object.__setattr__(self, "source_references", sources)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "diagnostics", diagnostics)

        digest = _sha256(self.preview_sha256, "preview_sha256")
        object.__setattr__(self, "preview_sha256", digest)
        expected = hashlib.sha256(_json_bytes(_body(self))).hexdigest()
        if digest != expected:
            raise TeacherReportValidationError(
                "preview_sha256 does not match the preview body."
            )


def compose_teacher_report_preview(
    *,
    report_kind: TeacherReportKind,
    title: str,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    source_references: Sequence[TeacherReportSourceReference],
    generated_at: datetime,
    summary: Sequence[str] = (),
    columns: Sequence[TeacherReportColumn],
    rows: Sequence[TeacherReportRow],
    diagnostics: Sequence[TeacherReportDiagnostic] = (),
) -> TeacherReportPreview:
    sources = tuple(
        sorted(
            source_references,
            key=lambda item: (item.source_kind, item.source_id, item.source_sha256),
        )
    )
    ordered_rows = tuple(sorted(rows, key=lambda item: item.row_id))
    ordered_diagnostics = tuple(
        sorted(diagnostics, key=lambda item: (item.code, item.severity, item.message))
    )
    body = {
        "schema_version": TEACHER_REPORT_SCHEMA_VERSION,
        "report_kind": report_kind,
        "title": title,
        "class_id": class_id,
        "target_period": academic_period_ref_to_dict(target_period),
        "calendar_revision": calendar_revision,
        "source_references": [_source_to_dict(item) for item in sources],
        "generated_at": _datetime_text(generated_at),
        "summary": list(summary),
        "columns": [_column_to_dict(item) for item in columns],
        "rows": [_row_to_dict(item) for item in ordered_rows],
        "diagnostics": [_diagnostic_to_dict(item) for item in ordered_diagnostics],
    }
    digest = hashlib.sha256(_json_bytes(body)).hexdigest()
    return TeacherReportPreview(
        schema_version=TEACHER_REPORT_SCHEMA_VERSION,
        report_kind=report_kind,
        title=title,
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        source_references=sources,
        generated_at=generated_at,
        summary=tuple(summary),
        columns=tuple(columns),
        rows=ordered_rows,
        diagnostics=ordered_diagnostics,
        preview_sha256=digest,
    )


def validate_teacher_report_preview(
    value: TeacherReportPreview,
) -> TeacherReportPreview:
    if not isinstance(value, TeacherReportPreview):
        raise TeacherReportValidationError("value must be a TeacherReportPreview.")
    return TeacherReportPreview(
        schema_version=value.schema_version,
        report_kind=value.report_kind,
        title=value.title,
        class_id=value.class_id,
        target_period=value.target_period,
        calendar_revision=value.calendar_revision,
        source_references=value.source_references,
        generated_at=value.generated_at,
        summary=value.summary,
        columns=value.columns,
        rows=value.rows,
        diagnostics=value.diagnostics,
        preview_sha256=value.preview_sha256,
    )


def teacher_report_preview_to_dict(value: TeacherReportPreview) -> dict[str, object]:
    preview = validate_teacher_report_preview(value)
    data = _body(preview)
    data["preview_sha256"] = preview.preview_sha256
    return data


def teacher_report_preview_to_json_bytes(value: TeacherReportPreview) -> bytes:
    return _json_bytes(teacher_report_preview_to_dict(value))


def teacher_report_preview_from_json_bytes(data: bytes) -> TeacherReportPreview:
    if type(data) is not bytes:
        raise TeacherReportSerializationError("preview JSON must be bytes.")
    try:
        raw = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise TeacherReportSerializationError("preview JSON is invalid.") from error
    mapping = _mapping(raw)
    preview = TeacherReportPreview(
        schema_version=_str(mapping["schema_version"]),
        report_kind=cast(TeacherReportKind, _str(mapping["report_kind"])),
        title=_str(mapping["title"]),
        class_id=_str(mapping["class_id"]),
        target_period=academic_period_ref_from_dict(mapping["target_period"]),
        calendar_revision=_int(mapping["calendar_revision"]),
        source_references=tuple(
            _source_from_dict(item) for item in _list(mapping["source_references"])
        ),
        generated_at=_datetime_from_text(_str(mapping["generated_at"])),
        summary=tuple(_str(item) for item in _list(mapping["summary"])),
        columns=tuple(_column_from_dict(item) for item in _list(mapping["columns"])),
        rows=tuple(_row_from_dict(item) for item in _list(mapping["rows"])),
        diagnostics=tuple(
            _diagnostic_from_dict(item) for item in _list(mapping["diagnostics"])
        ),
        preview_sha256=_str(mapping["preview_sha256"]),
    )
    if teacher_report_preview_to_json_bytes(preview) != data:
        raise TeacherReportSerializationError("preview JSON is not canonical.")
    return preview


def _body(value: TeacherReportPreview) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "report_kind": value.report_kind,
        "title": value.title,
        "class_id": value.class_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "source_references": [
            _source_to_dict(item) for item in value.source_references
        ],
        "generated_at": _datetime_text(value.generated_at),
        "summary": list(value.summary),
        "columns": [_column_to_dict(item) for item in value.columns],
        "rows": [_row_to_dict(item) for item in value.rows],
        "diagnostics": [_diagnostic_to_dict(item) for item in value.diagnostics],
    }


def _source_to_dict(value: TeacherReportSourceReference) -> dict[str, object]:
    return {
        "source_kind": value.source_kind,
        "source_id": value.source_id,
        "source_sha256": value.source_sha256,
    }


def _source_from_dict(data: object) -> TeacherReportSourceReference:
    mapping = _mapping(data, frozenset({"source_kind", "source_id", "source_sha256"}))
    return TeacherReportSourceReference(
        _str(mapping["source_kind"]),
        _str(mapping["source_id"]),
        _str(mapping["source_sha256"]),
    )


def _column_to_dict(value: TeacherReportColumn) -> dict[str, object]:
    return {"column_id": value.column_id, "title": value.title}


def _column_from_dict(data: object) -> TeacherReportColumn:
    mapping = _mapping(data, frozenset({"column_id", "title"}))
    return TeacherReportColumn(_str(mapping["column_id"]), _str(mapping["title"]))


def _row_to_dict(value: TeacherReportRow) -> dict[str, object]:
    return {"row_id": value.row_id, "values": list(value.values)}


def _row_from_dict(data: object) -> TeacherReportRow:
    mapping = _mapping(data, frozenset({"row_id", "values"}))
    values = tuple(
        None if item is None else _str(item) for item in _list(mapping["values"])
    )
    return TeacherReportRow(_str(mapping["row_id"]), values)


def _diagnostic_to_dict(value: TeacherReportDiagnostic) -> dict[str, object]:
    return {"code": value.code, "severity": value.severity, "message": value.message}


def _diagnostic_from_dict(data: object) -> TeacherReportDiagnostic:
    mapping = _mapping(data, frozenset({"code", "severity", "message"}))
    return TeacherReportDiagnostic(
        _str(mapping["code"]),
        cast(TeacherReportDiagnosticSeverity, _str(mapping["severity"])),
        _str(mapping["message"]),
    )


def _mapping(
    data: object, expected: frozenset[str] | None = None
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise TeacherReportSerializationError("expected JSON object.")
    mapping = cast(Mapping[str, object], data)
    if expected is None:
        expected = frozenset(
            {
                "schema_version",
                "report_kind",
                "title",
                "class_id",
                "target_period",
                "calendar_revision",
                "source_references",
                "generated_at",
                "summary",
                "columns",
                "rows",
                "diagnostics",
                "preview_sha256",
            }
        )
    if frozenset(mapping.keys()) != expected:
        raise TeacherReportSerializationError("unexpected or missing JSON fields.")
    return mapping


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherReportValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise TeacherReportValidationError(str(error)) from error


def _stable_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise TeacherReportValidationError(
            f"{field_name} must be a stable lowercase identifier."
        )
    return value


def _text(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or len(value) > _MAX_TEXT
    ):
        raise TeacherReportValidationError(
            f"{field_name} must be bounded nonblank single-line text."
        )
    return value


def _cell(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value or len(value) > _MAX_TEXT:
        raise TeacherReportValidationError("report text must be bounded string data.")
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TeacherReportValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TeacherReportValidationError(f"{field_name} must be a positive integer.")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TeacherReportValidationError(f"{field_name} must be an aware datetime.")
    return value.astimezone(UTC)


def _datetime_text(value: datetime) -> str:
    return _utc(value, "generated_at").isoformat().replace("+00:00", "Z")


def _datetime_from_text(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise TeacherReportSerializationError("generated_at is invalid.") from error
    return _utc(parsed, "generated_at")


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TeacherReportSerializationError("expected JSON string.")
    return value


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeacherReportSerializationError("expected JSON integer.")
    return value


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TeacherReportSerializationError("expected JSON array.")
    return cast(list[object], value)


__all__ = [
    "TEACHER_REPORT_KINDS",
    "TEACHER_REPORT_SCHEMA_VERSION",
    "TeacherReportColumn",
    "TeacherReportDiagnostic",
    "TeacherReportDiagnosticSeverity",
    "TeacherReportError",
    "TeacherReportKind",
    "TeacherReportPreview",
    "TeacherReportRow",
    "TeacherReportSerializationError",
    "TeacherReportSourceReference",
    "TeacherReportValidationError",
    "compose_teacher_report_preview",
    "teacher_report_preview_from_json_bytes",
    "teacher_report_preview_to_dict",
    "teacher_report_preview_to_json_bytes",
    "validate_teacher_report_preview",
]
