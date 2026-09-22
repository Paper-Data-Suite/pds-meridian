"""Deterministic report-export preview and CSV/TSV rendering for Meridian v0.3.

Issue #56 exports only exact immutable ReportingSnapshots through exact immutable
Export Profile revisions.  This module is a representation layer: it reads the
already-frozen report rows and optional bounded Core roster observation, projects
only fields selected by the profile, renders deterministic tabular bytes, and
binds the result to an immutable preview digest.  It never recalculates Grades,
selects current academic state, applies rounding, mutates a snapshot, or writes an
external system.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.export_profile import (
    ExportColumn,
    ExportProfileReference,
    ExportProfileRevision,
    ExportRepresentation,
    export_profile_reference,
    export_profile_reference_from_dict,
    export_profile_reference_to_dict,
    export_source_kind,
    validate_export_profile_revision,
    validate_export_source_field,
)
from meridian.export_profile_storage import (
    ExportProfileStorageError,
    load_export_profile_reference,
)
from meridian.report_export_roster import (
    ExportRosterObservation,
    ExportRosterObservationReference,
    ReportExportRosterError,
    build_export_roster_observation,
    export_profile_roster_source_fields,
    export_roster_observation_reference,
    export_roster_observation_reference_from_dict,
    export_roster_observation_reference_to_dict,
    validate_export_roster_observation,
)
from meridian.reporting_snapshot import (
    ReportingSnapshotReference,
    reporting_snapshot_reference_from_dict,
    reporting_snapshot_reference_to_dict,
)
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    FrozenGradeReportPreviewRow,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    load_reporting_snapshot,
)

REPORT_EXPORT_PREVIEW_SCHEMA_VERSION: Final[str] = "1"
REPORT_EXPORT_PREVIEW_RECORD_TYPE: Final[str] = "meridian_report_export_preview"
REPORT_EXPORTER_VERSION: Final[str] = "1"
MAXIMUM_REPORT_EXPORT_PREVIEW_BYTES: Final[int] = 16 * 1024 * 1024

ExportPreviewDiagnosticCode: TypeAlias = Literal[
    "unavailable_rows",
    "stale_grade_rows",
    "nonnumeric_effective_grade_rows",
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "unavailable_rows",
        "stale_grade_rows",
        "nonnumeric_effective_grade_rows",
    }
)
_PREVIEW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "exporter_version",
        "snapshot_reference",
        "profile_reference",
        "roster_observation_reference",
        "output_schema",
        "representation",
        "row_count",
        "logical_rows",
        "payload_sha256",
        "payload_byte_length",
        "diagnostics",
        "preview_sha256",
    }
)
_COLUMN_KEYS: Final[frozenset[str]] = frozenset({"source_field", "output_name"})
_REPRESENTATION_KEYS: Final[frozenset[str]] = frozenset(
    {"format", "include_header", "line_ending", "utf8_bom"}
)
_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "student_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "calculation_family",
        "values",
    }
)
_DIAGNOSTIC_KEYS: Final[frozenset[str]] = frozenset({"code", "count"})


class ReportExportPreviewError(RuntimeError):
    """Base error for deterministic report-export preview composition."""

    code = "report_export.preview_error"


class ReportExportPreviewValidationError(ReportExportPreviewError, ValueError):
    """Raised when preview arguments or model values are invalid."""

    code = "report_export.preview_invalid"


class ReportExportPreviewSourceError(ReportExportPreviewError):
    """Raised when an exact snapshot/profile/roster source cannot be resolved."""

    code = "report_export.preview_source_unavailable"


class ReportExportPreviewIntegrityError(ReportExportPreviewError):
    """Raised when canonical preview bytes or bound payload fail integrity checks."""

    code = "report_export.preview_integrity_failed"


@dataclass(frozen=True, slots=True)
class ExportPreviewColumn:
    """One exact output-schema column in semantic render order."""

    source_field: str
    output_name: str

    def __post_init__(self) -> None:
        try:
            column = ExportColumn(self.source_field, self.output_name)
        except ValueError as error:
            raise ReportExportPreviewValidationError(str(error)) from error
        object.__setattr__(self, "source_field", column.source_field)
        object.__setattr__(self, "output_name", column.output_name)


@dataclass(frozen=True, slots=True)
class ExportPreviewLogicalRow:
    """One exact frozen report row projected into profile column order."""

    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    calculation_family: str
    values: tuple[str | None, ...]

    def __post_init__(self) -> None:
        student_id = _identifier(self.student_id, "student_id")
        if not isinstance(self.school_year, str) or not self.school_year:
            raise ReportExportPreviewValidationError(
                "logical row school_year must be a nonblank string."
            )
        period_id = _identifier(self.period_id, "period_id")
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if self.calculation_family not in {
            "conventional",
            "standards_based",
            "hybrid",
        }:
            raise ReportExportPreviewValidationError(
                "logical row calculation_family is unsupported."
            )
        if not isinstance(self.values, tuple) or any(
            value is not None and not isinstance(value, str)
            for value in self.values
        ):
            raise ReportExportPreviewValidationError(
                "logical row values must be a tuple of strings or None."
            )
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "period_id", period_id)
        object.__setattr__(self, "calendar_revision", calendar_revision)


@dataclass(frozen=True, slots=True)
class ExportPreviewDiagnostic:
    """Deterministic count-only diagnostic over the frozen export row set."""

    code: ExportPreviewDiagnosticCode
    count: int

    def __post_init__(self) -> None:
        if self.code not in _DIAGNOSTIC_CODES:
            raise ReportExportPreviewValidationError(
                "preview diagnostic code is unsupported."
            )
        count = _nonnegative_int(self.count, "diagnostic count")
        if count == 0:
            raise ReportExportPreviewValidationError(
                "preview diagnostics must omit zero-count entries."
            )
        object.__setattr__(self, "count", count)


@dataclass(frozen=True, slots=True)
class ExportPreview:
    """Digest-bound deterministic preview of one exact export representation."""

    schema_version: str
    record_type: str
    exporter_version: str
    snapshot_reference: ReportingSnapshotReference
    profile_reference: ExportProfileReference
    roster_observation_reference: ExportRosterObservationReference | None
    output_schema: tuple[ExportPreviewColumn, ...]
    representation: ExportRepresentation
    row_count: int
    logical_rows: tuple[ExportPreviewLogicalRow, ...]
    payload_sha256: str
    payload_byte_length: int
    diagnostics: tuple[ExportPreviewDiagnostic, ...]
    preview_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_EXPORT_PREVIEW_SCHEMA_VERSION:
            raise ReportExportPreviewValidationError(
                'preview schema_version must be "1".'
            )
        if self.record_type != REPORT_EXPORT_PREVIEW_RECORD_TYPE:
            raise ReportExportPreviewValidationError(
                'preview record_type must be "meridian_report_export_preview".'
            )
        if self.exporter_version != REPORT_EXPORTER_VERSION:
            raise ReportExportPreviewValidationError(
                'preview exporter_version must be "1".'
            )
        if not isinstance(self.snapshot_reference, ReportingSnapshotReference):
            raise ReportExportPreviewValidationError(
                "snapshot_reference must be ReportingSnapshotReference."
            )
        if not isinstance(self.profile_reference, ExportProfileReference):
            raise ReportExportPreviewValidationError(
                "profile_reference must be ExportProfileReference."
            )
        if self.snapshot_reference.class_id != self.profile_reference.class_id:
            raise ReportExportPreviewValidationError(
                "snapshot and profile references must share class_id."
            )
        roster_reference = self.roster_observation_reference
        if roster_reference is not None:
            if not isinstance(roster_reference, ExportRosterObservationReference):
                raise ReportExportPreviewValidationError(
                    "roster_observation_reference is invalid."
                )
            if roster_reference.class_id != self.snapshot_reference.class_id:
                raise ReportExportPreviewValidationError(
                    "roster observation class must match snapshot class."
                )
        if not isinstance(self.output_schema, tuple) or not self.output_schema:
            raise ReportExportPreviewValidationError(
                "output_schema must contain at least one column."
            )
        if any(
            not isinstance(item, ExportPreviewColumn) for item in self.output_schema
        ):
            raise ReportExportPreviewValidationError(
                "output_schema must contain ExportPreviewColumn values."
            )
        schema = tuple(
            ExportPreviewColumn(item.source_field, item.output_name)
            for item in self.output_schema
        )
        if len({item.output_name for item in schema}) != len(schema):
            raise ReportExportPreviewValidationError(
                "output_schema output names must be unique."
            )
        if not isinstance(self.representation, ExportRepresentation):
            raise ReportExportPreviewValidationError(
                "representation must be ExportRepresentation."
            )
        representation = ExportRepresentation(
            format=self.representation.format,
            include_header=self.representation.include_header,
            line_ending=self.representation.line_ending,
            utf8_bom=self.representation.utf8_bom,
        )
        row_count = _nonnegative_int(self.row_count, "row_count")
        if not isinstance(self.logical_rows, tuple) or any(
            not isinstance(row, ExportPreviewLogicalRow) for row in self.logical_rows
        ):
            raise ReportExportPreviewValidationError(
                "logical_rows must be a tuple of ExportPreviewLogicalRow values."
            )
        rows = tuple(
            ExportPreviewLogicalRow(
                student_id=row.student_id,
                school_year=row.school_year,
                period_id=row.period_id,
                calendar_revision=row.calendar_revision,
                calculation_family=row.calculation_family,
                values=row.values,
            )
            for row in self.logical_rows
        )
        if len(rows) != row_count:
            raise ReportExportPreviewValidationError(
                "row_count must match exact logical row count."
            )
        width = len(schema)
        if any(len(row.values) != width for row in rows):
            raise ReportExportPreviewValidationError(
                "every logical row must match output_schema width."
            )
        payload_sha256 = _sha256(self.payload_sha256, "payload_sha256")
        payload_byte_length = _nonnegative_int(
            self.payload_byte_length,
            "payload_byte_length",
        )
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, ExportPreviewDiagnostic) for item in self.diagnostics
        ):
            raise ReportExportPreviewValidationError(
                "diagnostics must be a tuple of ExportPreviewDiagnostic values."
            )
        diagnostics = tuple(
            ExportPreviewDiagnostic(item.code, item.count) for item in self.diagnostics
        )
        codes = tuple(item.code for item in diagnostics)
        if len(set(codes)) != len(codes):
            raise ReportExportPreviewValidationError(
                "preview diagnostics must not repeat a code."
            )
        if codes != tuple(sorted(codes)):
            raise ReportExportPreviewValidationError(
                "preview diagnostics must use canonical code order."
            )
        preview_sha256 = _sha256(self.preview_sha256, "preview_sha256")

        object.__setattr__(self, "output_schema", schema)
        object.__setattr__(self, "representation", representation)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "logical_rows", rows)
        object.__setattr__(self, "payload_sha256", payload_sha256)
        object.__setattr__(self, "payload_byte_length", payload_byte_length)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "preview_sha256", preview_sha256)

        expected_preview = hashlib.sha256(
            _canonical_json_bytes(_preview_body_to_dict(self))
        ).hexdigest()
        if preview_sha256 != expected_preview:
            raise ReportExportPreviewIntegrityError(
                "preview_sha256 does not match exact preview body."
            )


@dataclass(frozen=True, slots=True)
class BuiltExportPreview:
    """One verified preview plus the exact payload bytes it describes."""

    preview: ExportPreview
    payload: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.preview, ExportPreview):
            raise ReportExportPreviewValidationError(
                "preview must be ExportPreview."
            )
        if type(self.payload) is not bytes:
            raise ReportExportPreviewValidationError(
                "payload must be immutable bytes."
            )
        if len(self.payload) != self.preview.payload_byte_length:
            raise ReportExportPreviewIntegrityError(
                "payload byte length does not match preview."
            )
        if hashlib.sha256(self.payload).hexdigest() != self.preview.payload_sha256:
            raise ReportExportPreviewIntegrityError(
                "payload digest does not match preview."
            )


def compose_export_preview(
    *,
    snapshot_reference: ReportingSnapshotReference,
    report_preview: FrozenGradeReportPreview,
    profile_reference: ExportProfileReference,
    profile: ExportProfileRevision,
    roster_observation: ExportRosterObservation | None,
) -> BuiltExportPreview:
    """Project exact frozen sources into deterministic tabular payload bytes."""

    if not isinstance(snapshot_reference, ReportingSnapshotReference):
        raise ReportExportPreviewValidationError(
            "snapshot_reference must be ReportingSnapshotReference."
        )
    if not isinstance(report_preview, FrozenGradeReportPreview):
        raise ReportExportPreviewValidationError(
            "report_preview must be FrozenGradeReportPreview."
        )
    exact_profile = validate_export_profile_revision(profile)
    if not isinstance(profile_reference, ExportProfileReference):
        raise ReportExportPreviewValidationError(
            "profile_reference must be ExportProfileReference."
        )
    if export_profile_reference(exact_profile) != profile_reference:
        raise ReportExportPreviewIntegrityError(
            "profile reference does not match exact profile revision bytes."
        )
    if snapshot_reference.class_id != exact_profile.class_id:
        raise ReportExportPreviewValidationError(
            "snapshot and profile must share class_id."
        )

    roster = _validated_roster_for_preview(
        exact_profile,
        report_preview,
        roster_observation,
    )
    schema = tuple(
        ExportPreviewColumn(column.source_field, column.output_name)
        for column in exact_profile.columns
    )
    roster_lookup = _roster_lookup(roster)
    rows = tuple(
        _logical_row(
            snapshot_reference,
            row,
            schema,
            roster_lookup,
        )
        for row in report_preview.rows
    )
    payload = _render_payload(schema, rows, exact_profile.representation)
    diagnostics = _diagnostics(report_preview)
    roster_reference = (
        None if roster is None else export_roster_observation_reference(roster)
    )

    body: dict[str, object] = {
        "schema_version": REPORT_EXPORT_PREVIEW_SCHEMA_VERSION,
        "record_type": REPORT_EXPORT_PREVIEW_RECORD_TYPE,
        "exporter_version": REPORT_EXPORTER_VERSION,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            snapshot_reference
        ),
        "profile_reference": export_profile_reference_to_dict(profile_reference),
        "roster_observation_reference": (
            None
            if roster_reference is None
            else export_roster_observation_reference_to_dict(roster_reference)
        ),
        "output_schema": [_column_to_dict(item) for item in schema],
        "representation": _representation_to_dict(exact_profile.representation),
        "row_count": len(rows),
        "logical_rows": [_row_to_dict(row) for row in rows],
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_byte_length": len(payload),
        "diagnostics": [_diagnostic_to_dict(item) for item in diagnostics],
    }
    preview_sha256 = hashlib.sha256(_canonical_json_bytes(body)).hexdigest()
    preview = ExportPreview(
        schema_version=REPORT_EXPORT_PREVIEW_SCHEMA_VERSION,
        record_type=REPORT_EXPORT_PREVIEW_RECORD_TYPE,
        exporter_version=REPORT_EXPORTER_VERSION,
        snapshot_reference=snapshot_reference,
        profile_reference=profile_reference,
        roster_observation_reference=roster_reference,
        output_schema=schema,
        representation=exact_profile.representation,
        row_count=len(rows),
        logical_rows=rows,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_byte_length=len(payload),
        diagnostics=diagnostics,
        preview_sha256=preview_sha256,
    )
    return BuiltExportPreview(preview=preview, payload=payload)


def build_export_preview(
    workspace_root: str | Path,
    snapshot_reference: ReportingSnapshotReference,
    profile_reference: ExportProfileReference,
) -> BuiltExportPreview:
    """Load exact immutable sources and build one deterministic export preview.

    This function never reads current ReportingSnapshot or Export Profile
    selectors.  Both source revisions must be supplied as exact digest-bound
    references.
    """

    if not isinstance(snapshot_reference, ReportingSnapshotReference):
        raise ReportExportPreviewValidationError(
            "snapshot_reference must be ReportingSnapshotReference."
        )
    if not isinstance(profile_reference, ExportProfileReference):
        raise ReportExportPreviewValidationError(
            "profile_reference must be ExportProfileReference."
        )
    if snapshot_reference.class_id != profile_reference.class_id:
        raise ReportExportPreviewValidationError(
            "snapshot and profile references must share class_id."
        )
    try:
        stored_snapshot = load_reporting_snapshot(
            workspace_root,
            snapshot_reference.class_id,
            snapshot_reference.snapshot_id,
        )
        stored_profile = load_export_profile_reference(
            workspace_root,
            profile_reference,
        )
    except (ReportingSnapshotStorageError, ExportProfileStorageError) as error:
        raise ReportExportPreviewSourceError(
            "Exact export snapshot/profile source is unavailable or invalid."
        ) from error
    if stored_snapshot.reference != snapshot_reference:
        raise ReportExportPreviewSourceError(
            "Requested ReportingSnapshot digest does not match stored source."
        )

    student_ids = tuple(
        row.target.student_id for row in stored_snapshot.snapshot.report_preview.rows
    )
    try:
        roster = build_export_roster_observation(
            workspace_root,
            stored_profile.profile,
            student_ids,
        )
    except ReportExportRosterError as error:
        raise ReportExportPreviewSourceError(
            "Bounded Core roster source required by Export Profile is unavailable."
        ) from error

    return compose_export_preview(
        snapshot_reference=stored_snapshot.reference,
        report_preview=stored_snapshot.snapshot.report_preview,
        profile_reference=stored_profile.reference,
        profile=stored_profile.profile,
        roster_observation=roster,
    )


def export_preview_to_dict(value: ExportPreview) -> dict[str, object]:
    """Convert one validated export preview to exact JSON-native data."""

    preview = validate_export_preview(value)
    data = _preview_body_to_dict(preview)
    data["preview_sha256"] = preview.preview_sha256
    return data


def export_preview_to_json_bytes(value: ExportPreview) -> bytes:
    """Return canonical UTF-8 JSON bytes for one export preview."""

    return _canonical_json_bytes(export_preview_to_dict(value))


def export_preview_from_dict(data: object) -> ExportPreview:
    """Strictly parse one exact export-preview representation."""

    mapping = _exact_mapping(data, _PREVIEW_KEYS, "export preview")
    snapshot_reference = reporting_snapshot_reference_from_dict(
        mapping["snapshot_reference"]
    )
    profile_reference = export_profile_reference_from_dict(
        mapping["profile_reference"]
    )
    roster_data = mapping["roster_observation_reference"]
    roster_reference = (
        None
        if roster_data is None
        else export_roster_observation_reference_from_dict(roster_data)
    )
    schema = tuple(
        _column_from_dict(item)
        for item in _require_list(mapping["output_schema"], "output_schema")
    )
    representation = _representation_from_dict(mapping["representation"])
    rows = tuple(
        _row_from_dict(item)
        for item in _require_list(mapping["logical_rows"], "logical_rows")
    )
    diagnostics = tuple(
        _diagnostic_from_dict(item)
        for item in _require_list(mapping["diagnostics"], "diagnostics")
    )
    return ExportPreview(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        exporter_version=_require_str(
            mapping["exporter_version"],
            "exporter_version",
        ),
        snapshot_reference=snapshot_reference,
        profile_reference=profile_reference,
        roster_observation_reference=roster_reference,
        output_schema=schema,
        representation=representation,
        row_count=_require_int(mapping["row_count"], "row_count"),
        logical_rows=rows,
        payload_sha256=_require_str(mapping["payload_sha256"], "payload_sha256"),
        payload_byte_length=_require_int(
            mapping["payload_byte_length"],
            "payload_byte_length",
        ),
        diagnostics=diagnostics,
        preview_sha256=_require_str(mapping["preview_sha256"], "preview_sha256"),
    )


def export_preview_from_json_bytes(
    data: bytes,
    *,
    maximum_bytes: int = MAXIMUM_REPORT_EXPORT_PREVIEW_BYTES,
) -> ExportPreview:
    """Strictly load canonical export-preview bytes."""

    if type(data) is not bytes:
        raise ReportExportPreviewIntegrityError(
            "export preview data must be immutable bytes."
        )
    maximum = _positive_int(maximum_bytes, "maximum_bytes")
    if len(data) > maximum:
        raise ReportExportPreviewIntegrityError(
            "export preview exceeds configured maximum byte size."
        )
    decoded = _decode_json(data, "export preview")
    preview = export_preview_from_dict(decoded)
    if export_preview_to_json_bytes(preview) != data:
        raise ReportExportPreviewIntegrityError(
            "export preview bytes are not canonical."
        )
    return preview


def export_preview_sha256(value: ExportPreview) -> str:
    """Return the exact digest of the preview body bound by preview_sha256."""

    return validate_export_preview(value).preview_sha256


def validate_export_preview(value: ExportPreview) -> ExportPreview:
    """Fully revalidate one immutable export preview."""

    if not isinstance(value, ExportPreview):
        raise ReportExportPreviewValidationError(
            "value must be ExportPreview."
        )
    return ExportPreview(
        schema_version=value.schema_version,
        record_type=value.record_type,
        exporter_version=value.exporter_version,
        snapshot_reference=value.snapshot_reference,
        profile_reference=value.profile_reference,
        roster_observation_reference=value.roster_observation_reference,
        output_schema=value.output_schema,
        representation=value.representation,
        row_count=value.row_count,
        logical_rows=value.logical_rows,
        payload_sha256=value.payload_sha256,
        payload_byte_length=value.payload_byte_length,
        diagnostics=value.diagnostics,
        preview_sha256=value.preview_sha256,
    )


def _validated_roster_for_preview(
    profile: ExportProfileRevision,
    report_preview: FrozenGradeReportPreview,
    roster_observation: ExportRosterObservation | None,
) -> ExportRosterObservation | None:
    required_fields = export_profile_roster_source_fields(profile)
    student_ids = tuple(sorted({row.target.student_id for row in report_preview.rows}))
    if not required_fields:
        if roster_observation is not None:
            raise ReportExportPreviewValidationError(
                "snapshot-native profile must not bind a roster observation."
            )
        return None
    if roster_observation is None:
        raise ReportExportPreviewValidationError(
            "roster-backed profile requires exact bounded roster observation."
        )
    roster = validate_export_roster_observation(roster_observation)
    if roster.class_id != profile.class_id:
        raise ReportExportPreviewValidationError(
            "roster observation class must match profile class."
        )
    if roster.source_fields != required_fields:
        raise ReportExportPreviewValidationError(
            "roster observation fields must match exactly selected profile fields."
        )
    if tuple(student.student_id for student in roster.students) != student_ids:
        raise ReportExportPreviewValidationError(
            "roster observation students must match distinct snapshot students."
        )
    return roster


def _roster_lookup(
    roster: ExportRosterObservation | None,
) -> dict[str, dict[str, str]]:
    if roster is None:
        return {}
    return {
        student.student_id: {
            item.source_field: item.value for item in student.values
        }
        for student in roster.students
    }


def _logical_row(
    snapshot_reference: ReportingSnapshotReference,
    row: FrozenGradeReportPreviewRow,
    schema: tuple[ExportPreviewColumn, ...],
    roster_lookup: Mapping[str, Mapping[str, str]],
) -> ExportPreviewLogicalRow:
    target = row.target
    values = tuple(
        _source_value(
            snapshot_reference,
            row,
            column.source_field,
            roster_lookup,
        )
        for column in schema
    )
    return ExportPreviewLogicalRow(
        student_id=target.student_id,
        school_year=target.target_period.school_year,
        period_id=target.target_period.period_id,
        calendar_revision=target.calendar_revision,
        calculation_family=target.calculation_family,
        values=values,
    )


def _source_value(
    snapshot_reference: ReportingSnapshotReference,
    row: FrozenGradeReportPreviewRow,
    source_field: str,
    roster_lookup: Mapping[str, Mapping[str, str]],
) -> str | None:
    source = validate_export_source_field(source_field)
    target = row.target
    if export_source_kind(source) == "roster":
        student = roster_lookup.get(target.student_id)
        if student is None or source not in student:
            raise ReportExportPreviewIntegrityError(
                "bounded roster observation does not cover an exported value."
            )
        return student[source]

    if source == "snapshot.class_id":
        return snapshot_reference.class_id
    if source == "snapshot.snapshot_id":
        return snapshot_reference.snapshot_id
    if source == "snapshot.snapshot_sha256":
        return snapshot_reference.snapshot_sha256
    if source == "target.student_id":
        return target.student_id
    if source == "target.school_year":
        return target.target_period.school_year
    if source == "target.period_id":
        return target.target_period.period_id
    if source == "target.calendar_revision":
        return str(target.calendar_revision)
    if source == "target.calculation_family":
        return target.calculation_family
    if source == "row.status":
        return row.status
    if source == "row.unavailable_reason":
        return row.unavailable_reason

    observation = row.observation
    if observation is None:
        return None
    if source == "grade.base_result_status":
        return observation.base_result_status
    if source == "grade.base_grade":
        return _optional_decimal_text(observation.base_grade)
    if source == "grade.base_freshness_status":
        return observation.base_freshness_status
    if source == "grade.effective_grade":
        return _optional_decimal_text(observation.effective_grade)
    if source == "grade.effective_source":
        return observation.effective_source
    if source == "policy.policy_id":
        return observation.policy_reference.policy_id
    if source == "policy.policy_revision":
        return str(observation.policy_reference.policy_revision)
    raise ReportExportPreviewIntegrityError(
        "validated snapshot source field has no v1 export resolver."
    )


def _render_payload(
    schema: tuple[ExportPreviewColumn, ...],
    rows: tuple[ExportPreviewLogicalRow, ...],
    representation: ExportRepresentation,
) -> bytes:
    delimiter = "," if representation.format == "csv" else "\t"
    line_ending = "\n" if representation.line_ending == "lf" else "\r\n"
    output = io.StringIO(newline="")
    writer = csv.writer(
        output,
        delimiter=delimiter,
        quotechar='"',
        quoting=csv.QUOTE_MINIMAL,
        lineterminator=line_ending,
    )
    if representation.include_header:
        writer.writerow(tuple(column.output_name for column in schema))
    for row in rows:
        writer.writerow(tuple("" if value is None else value for value in row.values))
    payload = output.getvalue().encode("utf-8")
    if representation.utf8_bom:
        payload = b"\xef\xbb\xbf" + payload
    return payload


def _diagnostics(
    report_preview: FrozenGradeReportPreview,
) -> tuple[ExportPreviewDiagnostic, ...]:
    counts: dict[ExportPreviewDiagnosticCode, int] = {
        "unavailable_rows": 0,
        "stale_grade_rows": 0,
        "nonnumeric_effective_grade_rows": 0,
    }
    for row in report_preview.rows:
        if row.status == "unavailable":
            counts["unavailable_rows"] += 1
            continue
        observation = row.observation
        if observation is None:
            raise ReportExportPreviewIntegrityError(
                "available frozen report row is missing Grade observation."
            )
        if observation.base_freshness_status == "stale":
            counts["stale_grade_rows"] += 1
        if observation.effective_grade is None:
            counts["nonnumeric_effective_grade_rows"] += 1
    return tuple(
        ExportPreviewDiagnostic(code, counts[code])
        for code in sorted(counts)
        if counts[code] > 0
    )


def _preview_body_to_dict(value: ExportPreview) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "exporter_version": value.exporter_version,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            value.snapshot_reference
        ),
        "profile_reference": export_profile_reference_to_dict(
            value.profile_reference
        ),
        "roster_observation_reference": (
            None
            if value.roster_observation_reference is None
            else export_roster_observation_reference_to_dict(
                value.roster_observation_reference
            )
        ),
        "output_schema": [_column_to_dict(item) for item in value.output_schema],
        "representation": _representation_to_dict(value.representation),
        "row_count": value.row_count,
        "logical_rows": [_row_to_dict(row) for row in value.logical_rows],
        "payload_sha256": value.payload_sha256,
        "payload_byte_length": value.payload_byte_length,
        "diagnostics": [_diagnostic_to_dict(item) for item in value.diagnostics],
    }


def _column_to_dict(value: ExportPreviewColumn) -> dict[str, object]:
    return {"source_field": value.source_field, "output_name": value.output_name}


def _column_from_dict(data: object) -> ExportPreviewColumn:
    mapping = _exact_mapping(data, _COLUMN_KEYS, "output schema column")
    return ExportPreviewColumn(
        _require_str(mapping["source_field"], "source_field"),
        _require_str(mapping["output_name"], "output_name"),
    )


def _representation_to_dict(value: ExportRepresentation) -> dict[str, object]:
    return {
        "format": value.format,
        "include_header": value.include_header,
        "line_ending": value.line_ending,
        "utf8_bom": value.utf8_bom,
    }


def _representation_from_dict(data: object) -> ExportRepresentation:
    mapping = _exact_mapping(data, _REPRESENTATION_KEYS, "representation")
    format_value = _require_str(mapping["format"], "format")
    line_ending = _require_str(mapping["line_ending"], "line_ending")
    include_header = mapping["include_header"]
    utf8_bom = mapping["utf8_bom"]
    if type(include_header) is not bool or type(utf8_bom) is not bool:
        raise ReportExportPreviewValidationError(
            "representation booleans must be JSON booleans."
        )
    if format_value not in {"csv", "tsv"}:
        raise ReportExportPreviewValidationError("format must be csv or tsv.")
    if line_ending not in {"lf", "crlf"}:
        raise ReportExportPreviewValidationError(
            "line_ending must be lf or crlf."
        )
    return ExportRepresentation(
        format=cast(Literal["csv", "tsv"], format_value),
        include_header=include_header,
        line_ending=cast(Literal["lf", "crlf"], line_ending),
        utf8_bom=utf8_bom,
    )


def _row_to_dict(value: ExportPreviewLogicalRow) -> dict[str, object]:
    return {
        "student_id": value.student_id,
        "school_year": value.school_year,
        "period_id": value.period_id,
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
        "values": list(value.values),
    }


def _row_from_dict(data: object) -> ExportPreviewLogicalRow:
    mapping = _exact_mapping(data, _ROW_KEYS, "logical row")
    values_data = _require_list(mapping["values"], "values")
    values: list[str | None] = []
    for index, value in enumerate(values_data):
        if value is not None and not isinstance(value, str):
            raise ReportExportPreviewValidationError(
                f"values[{index}] must be a string or null."
            )
        values.append(value)
    return ExportPreviewLogicalRow(
        student_id=_require_str(mapping["student_id"], "student_id"),
        school_year=_require_str(mapping["school_year"], "school_year"),
        period_id=_require_str(mapping["period_id"], "period_id"),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        calculation_family=_require_str(
            mapping["calculation_family"],
            "calculation_family",
        ),
        values=tuple(values),
    )


def _diagnostic_to_dict(value: ExportPreviewDiagnostic) -> dict[str, object]:
    return {"code": value.code, "count": value.count}


def _diagnostic_from_dict(data: object) -> ExportPreviewDiagnostic:
    mapping = _exact_mapping(data, _DIAGNOSTIC_KEYS, "diagnostic")
    code = _require_str(mapping["code"], "diagnostic.code")
    if code not in _DIAGNOSTIC_CODES:
        raise ReportExportPreviewValidationError(
            "preview diagnostic code is unsupported."
        )
    return ExportPreviewDiagnostic(
        cast(ExportPreviewDiagnosticCode, code),
        _require_int(mapping["count"], "diagnostic.count"),
    )


def _optional_decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ReportExportPreviewIntegrityError(
            "frozen Grade value must be a finite Decimal or None."
        )
    return format(value, "f")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise ReportExportPreviewIntegrityError(
            "export preview cannot be encoded as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportExportPreviewIntegrityError(
            f"{label} must be valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportExportPreviewIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportExportPreviewIntegrityError(
            f"{label} is not valid strict JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportExportPreviewIntegrityError(
                f"duplicate JSON object key: {key}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportExportPreviewIntegrityError(
        f"non-finite JSON numeric constant is not permitted: {value}."
    )


def _exact_mapping(
    data: object,
    expected_keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, dict):
        raise ReportExportPreviewValidationError(
            f"{label} must be a JSON object."
        )
    keys = set(data)
    if keys != expected_keys:
        missing = sorted(expected_keys - keys)
        unknown = sorted(keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportExportPreviewValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportPreviewValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportExportPreviewValidationError(str(error)) from error


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportExportPreviewValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise ReportExportPreviewValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _nonnegative_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer < 0:
        raise ReportExportPreviewValidationError(
            f"{field_name} must be nonnegative."
        )
    return integer


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportPreviewValidationError(
            f"{field_name} must be a string."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportExportPreviewValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportExportPreviewValidationError(
            f"{field_name} must be a JSON array."
        )
    return value


__all__ = [
    "BuiltExportPreview",
    "ExportPreview",
    "ExportPreviewColumn",
    "ExportPreviewDiagnostic",
    "ExportPreviewDiagnosticCode",
    "ExportPreviewLogicalRow",
    "MAXIMUM_REPORT_EXPORT_PREVIEW_BYTES",
    "REPORT_EXPORTER_VERSION",
    "REPORT_EXPORT_PREVIEW_RECORD_TYPE",
    "REPORT_EXPORT_PREVIEW_SCHEMA_VERSION",
    "ReportExportPreviewError",
    "ReportExportPreviewIntegrityError",
    "ReportExportPreviewSourceError",
    "ReportExportPreviewValidationError",
    "build_export_preview",
    "compose_export_preview",
    "export_preview_from_dict",
    "export_preview_from_json_bytes",
    "export_preview_sha256",
    "export_preview_to_dict",
    "export_preview_to_json_bytes",
    "validate_export_preview",
]
