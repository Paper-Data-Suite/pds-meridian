"""Immutable export receipts and class-local receipt storage for Meridian v0.3.

Issue #56 records one exact, teacher-initiated report export after deterministic
preview revalidation and destination handling.  A receipt binds the immutable
ReportingSnapshot, immutable Export Profile revision, exact bounded roster
observation when one was material, exact output representation/schema, preview
identity, payload identity, destination kind, and teacher decision metadata.

Receipts intentionally retain no absolute destination path and never claim that
an external SIS/LMS/gradebook accepted the exported payload.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.export_profile import (
    ExportProfileReference,
    ExportRepresentation,
    export_profile_reference_from_dict,
    export_profile_reference_to_dict,
)
from meridian.report_export_preview import (
    REPORT_EXPORTER_VERSION,
    ExportPreview,
    ExportPreviewColumn,
    validate_export_preview,
)
from meridian.report_export_roster import (
    ExportRosterObservation,
    export_roster_observation_from_dict,
    export_roster_observation_reference,
    export_roster_observation_to_dict,
    validate_export_roster_observation,
)
from meridian.reporting_snapshot import (
    ReportingSnapshotReference,
    reporting_snapshot_reference_from_dict,
    reporting_snapshot_reference_to_dict,
)

REPORT_EXPORT_RECEIPT_SCHEMA_VERSION: Final[str] = "1"
REPORT_EXPORT_RECEIPT_RECORD_TYPE: Final[str] = "meridian_report_export_receipt"
DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_BYTES: Final[int] = 16 * 1024 * 1024
DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_DIGEST_BYTES: Final[int] = 128
MAXIMUM_REPORT_EXPORT_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_REPORT_EXPORT_RATIONALE_LENGTH: Final[int] = 2000
MAXIMUM_REPORT_EXPORT_BASENAME_LENGTH: Final[int] = 255

ReportExportDestinationKind: TypeAlias = Literal["file", "copyable_text"]
ReportExportActorKind: TypeAlias = Literal["teacher"]
ReportExportReceiptWriteDisposition: TypeAlias = Literal["created", "existing"]

_DESTINATION_KINDS: Final[frozenset[str]] = frozenset({"file", "copyable_text"})
_ACTOR_KINDS: Final[frozenset[str]] = frozenset({"teacher"})
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_JSON: Final[re.Pattern[str]] = re.compile(r"^([A-Za-z0-9_-]+)\.json$")
_RECEIPT_DIGEST: Final[re.Pattern[str]] = re.compile(
    r"^([A-Za-z0-9_-]+)\.json\.sha256$"
)

_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_DESTINATION_KEYS: Final[frozenset[str]] = frozenset({"kind", "basename"})
_COLUMN_KEYS: Final[frozenset[str]] = frozenset({"source_field", "output_name"})
_REPRESENTATION_KEYS: Final[frozenset[str]] = frozenset(
    {"format", "include_header", "line_ending", "utf8_bom"}
)
_RECEIPT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "export_id",
        "snapshot_reference",
        "profile_reference",
        "roster_observation",
        "roster_observation_sha256",
        "exporter_version",
        "output_schema",
        "representation",
        "preview_sha256",
        "payload_sha256",
        "payload_byte_length",
        "row_count",
        "destination",
        "actor",
        "rationale",
        "exported_at",
    }
)


class ReportExportReceiptError(RuntimeError):
    """Base error for immutable report-export receipt handling."""

    code = "report_export.receipt_error"


class ReportExportReceiptValidationError(ReportExportReceiptError, ValueError):
    """Raised when a receipt value violates its v1 contract."""

    code = "report_export.receipt_invalid"


class ReportExportReceiptSerializationError(ReportExportReceiptError):
    """Raised when receipt bytes are noncanonical or otherwise invalid."""

    code = "report_export.receipt_integrity_failed"


class ReportExportReceiptStorageError(ReportExportReceiptError):
    """Base error for class-local immutable receipt persistence."""

    code = "report_export.receipt_storage_error"


class ReportExportReceiptNotFoundError(ReportExportReceiptStorageError):
    """Raised when a requested exact receipt does not exist."""

    code = "report_export.receipt_not_found"


class ReportExportReceiptReadError(ReportExportReceiptStorageError):
    """Raised when receipt storage cannot be read safely."""

    code = "report_export.receipt_read_failed"


class ReportExportReceiptWriteError(ReportExportReceiptStorageError):
    """Raised when receipt storage cannot be written safely."""

    code = "report_export.receipt_write_failed"


class ReportExportReceiptConflictError(ReportExportReceiptStorageError):
    """Raised when one export identity already has different receipt content."""

    code = "report_export.receipt_conflict"


class ReportExportReceiptIntegrityError(ReportExportReceiptStorageError):
    """Raised when persisted receipt state fails closed validation."""

    code = "report_export.receipt_integrity_failed"


class ReportExportReceiptTooLargeError(ReportExportReceiptReadError):
    """Raised when stored receipt bytes exceed the configured bound."""

    code = "report_export.receipt_too_large"


class ReportExportReceiptLockError(ReportExportReceiptConflictError):
    """Raised when another writer owns the class receipt collection."""

    code = "report_export.receipt_locked"


@dataclass(frozen=True, slots=True)
class ReportExportActor:
    """Explicit teacher identity for one deliberate export action."""

    kind: ReportExportActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise ReportExportReceiptValidationError(
                "report export actor kind must be teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_REPORT_EXPORT_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ReportExportDestinationReceipt:
    """Privacy-minimized destination identity retained in academic provenance."""

    kind: ReportExportDestinationKind
    basename: str | None

    def __post_init__(self) -> None:
        if self.kind not in _DESTINATION_KINDS:
            raise ReportExportReceiptValidationError(
                "destination kind must be file or copyable_text."
            )
        if self.kind == "file":
            if self.basename is None:
                raise ReportExportReceiptValidationError(
                    "file destination receipt requires a basename."
                )
            basename = _safe_basename(self.basename)
        else:
            if self.basename is not None:
                raise ReportExportReceiptValidationError(
                    "copyable_text destination must not retain a basename."
                )
            basename = None
        object.__setattr__(self, "basename", basename)


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """One immutable receipt for an exact deterministic report export."""

    schema_version: str
    record_type: str
    class_id: str
    export_id: str
    snapshot_reference: ReportingSnapshotReference
    profile_reference: ExportProfileReference
    roster_observation: ExportRosterObservation | None
    roster_observation_sha256: str | None
    exporter_version: str
    output_schema: tuple[ExportPreviewColumn, ...]
    representation: ExportRepresentation
    preview_sha256: str
    payload_sha256: str
    payload_byte_length: int
    row_count: int
    destination: ReportExportDestinationReceipt
    actor: ReportExportActor
    rationale: str | None
    exported_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_EXPORT_RECEIPT_SCHEMA_VERSION:
            raise ReportExportReceiptValidationError(
                'receipt schema_version must be "1".'
            )
        if self.record_type != REPORT_EXPORT_RECEIPT_RECORD_TYPE:
            raise ReportExportReceiptValidationError(
                'receipt record_type must be "meridian_report_export_receipt".'
            )
        class_id = _identifier(self.class_id, "class_id")
        export_id = _identifier(self.export_id, "export_id")
        if not isinstance(self.snapshot_reference, ReportingSnapshotReference):
            raise ReportExportReceiptValidationError(
                "snapshot_reference must be ReportingSnapshotReference."
            )
        snapshot_reference = ReportingSnapshotReference(
            self.snapshot_reference.class_id,
            self.snapshot_reference.snapshot_id,
            self.snapshot_reference.snapshot_sha256,
        )
        if not isinstance(self.profile_reference, ExportProfileReference):
            raise ReportExportReceiptValidationError(
                "profile_reference must be ExportProfileReference."
            )
        profile_reference = ExportProfileReference(
            self.profile_reference.class_id,
            self.profile_reference.profile_id,
            self.profile_reference.profile_revision,
            self.profile_reference.profile_sha256,
        )
        if (
            snapshot_reference.class_id != class_id
            or profile_reference.class_id != class_id
        ):
            raise ReportExportReceiptValidationError(
                "receipt source references must match receipt class_id."
            )
        roster = self.roster_observation
        roster_sha256 = self.roster_observation_sha256
        if roster is None:
            if roster_sha256 is not None:
                raise ReportExportReceiptValidationError(
                    "snapshot-native receipt must not carry roster digest."
                )
        else:
            roster = validate_export_roster_observation(roster)
            if roster.class_id != class_id:
                raise ReportExportReceiptValidationError(
                    "receipt roster observation must match receipt class_id."
                )
            roster_sha256 = _sha256(
                roster_sha256,
                "roster_observation_sha256",
            )
            expected_roster_sha256 = (
                export_roster_observation_reference(roster).observation_sha256
            )
            if roster_sha256 != expected_roster_sha256:
                raise ReportExportReceiptValidationError(
                    "roster observation digest does not match embedded observation."
                )
        if self.exporter_version != REPORT_EXPORTER_VERSION:
            raise ReportExportReceiptValidationError(
                "receipt exporter_version does not match this exporter contract."
            )
        if not isinstance(self.output_schema, tuple) or not self.output_schema:
            raise ReportExportReceiptValidationError(
                "output_schema must be a nonempty tuple."
            )
        schema = tuple(
            ExportPreviewColumn(item.source_field, item.output_name)
            if isinstance(item, ExportPreviewColumn)
            else _raise_schema_item()
            for item in self.output_schema
        )
        if not isinstance(self.representation, ExportRepresentation):
            raise ReportExportReceiptValidationError(
                "representation must be ExportRepresentation."
            )
        representation = ExportRepresentation(
            self.representation.format,
            self.representation.include_header,
            self.representation.line_ending,
            self.representation.utf8_bom,
        )
        preview_sha256 = _sha256(self.preview_sha256, "preview_sha256")
        payload_sha256 = _sha256(self.payload_sha256, "payload_sha256")
        payload_byte_length = _nonnegative_int(
            self.payload_byte_length,
            "payload_byte_length",
        )
        row_count = _nonnegative_int(self.row_count, "row_count")
        if not isinstance(self.destination, ReportExportDestinationReceipt):
            raise ReportExportReceiptValidationError(
                "destination must be ReportExportDestinationReceipt."
            )
        destination = ReportExportDestinationReceipt(
            self.destination.kind,
            self.destination.basename,
        )
        if not isinstance(self.actor, ReportExportActor):
            raise ReportExportReceiptValidationError(
                "actor must be ReportExportActor."
            )
        actor = ReportExportActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_REPORT_EXPORT_RATIONALE_LENGTH,
        )
        exported_at = _aware_utc_datetime(self.exported_at, "exported_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "export_id", export_id)
        object.__setattr__(self, "snapshot_reference", snapshot_reference)
        object.__setattr__(self, "profile_reference", profile_reference)
        object.__setattr__(self, "roster_observation", roster)
        object.__setattr__(self, "roster_observation_sha256", roster_sha256)
        object.__setattr__(self, "output_schema", schema)
        object.__setattr__(self, "representation", representation)
        object.__setattr__(self, "preview_sha256", preview_sha256)
        object.__setattr__(self, "payload_sha256", payload_sha256)
        object.__setattr__(self, "payload_byte_length", payload_byte_length)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "exported_at", exported_at)


@dataclass(frozen=True, slots=True)
class ExportReceiptReference:
    """Exact digest-bound identity for one immutable export receipt."""

    class_id: str
    export_id: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "export_id", _identifier(self.export_id, "export_id"))
        object.__setattr__(
            self,
            "receipt_sha256",
            _sha256(self.receipt_sha256, "receipt_sha256"),
        )


@dataclass(frozen=True, slots=True)
class StoredExportReceipt:
    """One verified immutable receipt plus its exact canonical bytes."""

    receipt: ExportReceipt
    receipt_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        receipt = validate_export_receipt(self.receipt)
        digest = _sha256(self.receipt_sha256, "receipt_sha256")
        if type(self.content) is not bytes:
            raise ReportExportReceiptValidationError(
                "stored receipt content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ReportExportReceiptValidationError(
                "receipt_sha256 does not match exact stored bytes."
            )
        try:
            decoded = export_receipt_from_json_bytes(self.content)
        except ReportExportReceiptError as error:
            raise ReportExportReceiptValidationError(
                "stored content is not a canonical ExportReceipt."
            ) from error
        if decoded != receipt:
            raise ReportExportReceiptValidationError(
                "stored content does not decode to receipt."
            )
        expected = report_export_receipt_relative_path(
            receipt.class_id,
            receipt.export_id,
        )
        if self.relative_path != expected:
            raise ReportExportReceiptValidationError(
                "relative_path is not the canonical receipt location."
            )
        if self.path.name != f"{receipt.export_id}.json":
            raise ReportExportReceiptValidationError(
                "receipt path filename does not match export identity."
            )
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "receipt_sha256", digest)

    @property
    def reference(self) -> ExportReceiptReference:
        return ExportReceiptReference(
            self.receipt.class_id,
            self.receipt.export_id,
            self.receipt_sha256,
        )


@dataclass(frozen=True, slots=True)
class ExportReceiptWriteResult:
    """Result of create-only immutable receipt persistence."""

    disposition: ReportExportReceiptWriteDisposition
    stored: StoredExportReceipt

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "existing"}:
            raise ReportExportReceiptValidationError(
                "receipt write disposition is invalid."
            )
        if not isinstance(self.stored, StoredExportReceipt):
            raise ReportExportReceiptValidationError(
                "stored must be StoredExportReceipt."
            )


def export_receipt_from_preview(
    *,
    export_id: str,
    preview: ExportPreview,
    roster_observation: ExportRosterObservation | None,
    destination: ReportExportDestinationReceipt,
    actor: ReportExportActor,
    rationale: str | None,
    exported_at: datetime,
) -> ExportReceipt:
    """Create one receipt from the exact preview and material roster observation."""

    exact = validate_export_preview(preview)
    roster = roster_observation
    if exact.roster_observation_reference is None:
        if roster is not None:
            raise ReportExportReceiptValidationError(
                "snapshot-native preview must not retain a roster observation."
            )
    else:
        if roster is None:
            raise ReportExportReceiptValidationError(
                "roster-backed preview requires exact roster observation in receipt."
            )
        roster = validate_export_roster_observation(roster)
        if export_roster_observation_reference(roster) != (
            exact.roster_observation_reference
        ):
            raise ReportExportReceiptValidationError(
                "receipt roster observation does not match preview reference."
            )
    return ExportReceipt(
        schema_version=REPORT_EXPORT_RECEIPT_SCHEMA_VERSION,
        record_type=REPORT_EXPORT_RECEIPT_RECORD_TYPE,
        class_id=exact.snapshot_reference.class_id,
        export_id=export_id,
        snapshot_reference=exact.snapshot_reference,
        profile_reference=exact.profile_reference,
        roster_observation=roster,
        roster_observation_sha256=(
            None
            if exact.roster_observation_reference is None
            else exact.roster_observation_reference.observation_sha256
        ),
        exporter_version=exact.exporter_version,
        output_schema=exact.output_schema,
        representation=exact.representation,
        preview_sha256=exact.preview_sha256,
        payload_sha256=exact.payload_sha256,
        payload_byte_length=exact.payload_byte_length,
        row_count=exact.row_count,
        destination=destination,
        actor=actor,
        rationale=rationale,
        exported_at=exported_at,
    )


def validate_export_receipt(value: ExportReceipt) -> ExportReceipt:
    """Fully revalidate one immutable ExportReceipt."""

    if not isinstance(value, ExportReceipt):
        raise ReportExportReceiptValidationError(
            "value must be ExportReceipt."
        )
    return ExportReceipt(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        export_id=value.export_id,
        snapshot_reference=value.snapshot_reference,
        profile_reference=value.profile_reference,
        roster_observation=value.roster_observation,
        roster_observation_sha256=value.roster_observation_sha256,
        exporter_version=value.exporter_version,
        output_schema=value.output_schema,
        representation=value.representation,
        preview_sha256=value.preview_sha256,
        payload_sha256=value.payload_sha256,
        payload_byte_length=value.payload_byte_length,
        row_count=value.row_count,
        destination=value.destination,
        actor=value.actor,
        rationale=value.rationale,
        exported_at=value.exported_at,
    )


def export_receipt_to_dict(value: ExportReceipt) -> dict[str, object]:
    """Convert one validated receipt to exact JSON-native data."""

    receipt = validate_export_receipt(value)
    return {
        "schema_version": receipt.schema_version,
        "record_type": receipt.record_type,
        "class_id": receipt.class_id,
        "export_id": receipt.export_id,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            receipt.snapshot_reference
        ),
        "profile_reference": export_profile_reference_to_dict(
            receipt.profile_reference
        ),
        "roster_observation": (
            None
            if receipt.roster_observation is None
            else export_roster_observation_to_dict(receipt.roster_observation)
        ),
        "roster_observation_sha256": receipt.roster_observation_sha256,
        "exporter_version": receipt.exporter_version,
        "output_schema": [
            {
                "source_field": column.source_field,
                "output_name": column.output_name,
            }
            for column in receipt.output_schema
        ],
        "representation": {
            "format": receipt.representation.format,
            "include_header": receipt.representation.include_header,
            "line_ending": receipt.representation.line_ending,
            "utf8_bom": receipt.representation.utf8_bom,
        },
        "preview_sha256": receipt.preview_sha256,
        "payload_sha256": receipt.payload_sha256,
        "payload_byte_length": receipt.payload_byte_length,
        "row_count": receipt.row_count,
        "destination": {
            "kind": receipt.destination.kind,
            "basename": receipt.destination.basename,
        },
        "actor": {
            "kind": receipt.actor.kind,
            "actor_id": receipt.actor.actor_id,
        },
        "rationale": receipt.rationale,
        "exported_at": receipt.exported_at.isoformat(),
    }


def export_receipt_from_dict(data: object) -> ExportReceipt:
    """Strictly parse one exact ExportReceipt mapping."""

    mapping = _exact_mapping(data, _RECEIPT_KEYS, "ExportReceipt")
    roster_data = mapping["roster_observation"]
    roster = (
        None
        if roster_data is None
        else export_roster_observation_from_dict(roster_data)
    )
    columns = tuple(
        ExportPreviewColumn(
            _require_str(item["source_field"], "source_field"),
            _require_str(item["output_name"], "output_name"),
        )
        for item in (
            _exact_mapping(item, _COLUMN_KEYS, "receipt output column")
            for item in _require_list(mapping["output_schema"], "output_schema")
        )
    )
    representation_data = _exact_mapping(
        mapping["representation"],
        _REPRESENTATION_KEYS,
        "receipt representation",
    )
    representation = ExportRepresentation(
        format=cast(
            Literal["csv", "tsv"],
            _require_str(representation_data["format"], "format"),
        ),
        include_header=_require_bool(
            representation_data["include_header"],
            "include_header",
        ),
        line_ending=cast(
            Literal["lf", "crlf"],
            _require_str(representation_data["line_ending"], "line_ending"),
        ),
        utf8_bom=_require_bool(
            representation_data["utf8_bom"],
            "utf8_bom",
        ),
    )
    destination_data = _exact_mapping(
        mapping["destination"],
        _DESTINATION_KEYS,
        "receipt destination",
    )
    destination = ReportExportDestinationReceipt(
        kind=cast(
            ReportExportDestinationKind,
            _require_str(destination_data["kind"], "destination.kind"),
        ),
        basename=_optional_str(destination_data["basename"], "destination.basename"),
    )
    actor_data = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "receipt actor")
    actor = ReportExportActor(
        kind=cast(
            ReportExportActorKind,
            _require_str(actor_data["kind"], "actor.kind"),
        ),
        actor_id=_require_str(actor_data["actor_id"], "actor.actor_id"),
    )
    return ExportReceipt(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        export_id=_require_str(mapping["export_id"], "export_id"),
        snapshot_reference=reporting_snapshot_reference_from_dict(
            mapping["snapshot_reference"]
        ),
        profile_reference=export_profile_reference_from_dict(
            mapping["profile_reference"]
        ),
        roster_observation=roster,
        roster_observation_sha256=_optional_str(
            mapping["roster_observation_sha256"],
            "roster_observation_sha256",
        ),
        exporter_version=_require_str(
            mapping["exporter_version"],
            "exporter_version",
        ),
        output_schema=columns,
        representation=representation,
        preview_sha256=_require_str(mapping["preview_sha256"], "preview_sha256"),
        payload_sha256=_require_str(mapping["payload_sha256"], "payload_sha256"),
        payload_byte_length=_require_int(
            mapping["payload_byte_length"],
            "payload_byte_length",
        ),
        row_count=_require_int(mapping["row_count"], "row_count"),
        destination=destination,
        actor=actor,
        rationale=_optional_str(mapping["rationale"], "rationale"),
        exported_at=_datetime_from_text(mapping["exported_at"], "exported_at"),
    )


def export_receipt_to_json_bytes(value: ExportReceipt) -> bytes:
    """Return canonical UTF-8 JSON bytes for one receipt."""

    return _canonical_json_bytes(export_receipt_to_dict(value))


def export_receipt_from_json_bytes(
    data: bytes,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_BYTES,
) -> ExportReceipt:
    """Strictly load canonical ExportReceipt bytes."""

    if type(data) is not bytes:
        raise ReportExportReceiptSerializationError(
            "ExportReceipt data must be immutable bytes."
        )
    maximum = _positive_int(maximum_bytes, "maximum_bytes")
    if len(data) > maximum:
        raise ReportExportReceiptSerializationError(
            "ExportReceipt exceeds configured maximum byte size."
        )
    decoded = _decode_json(data, "ExportReceipt")
    try:
        receipt = export_receipt_from_dict(decoded)
    except (ReportExportReceiptValidationError, ValueError) as error:
        raise ReportExportReceiptSerializationError(
            f"ExportReceipt is invalid: {error}"
        ) from error
    canonical = export_receipt_to_json_bytes(receipt)
    if canonical != data:
        raise ReportExportReceiptSerializationError(
            "ExportReceipt bytes are not canonical."
        )
    return receipt


def export_receipt_sha256(value: ExportReceipt) -> str:
    return hashlib.sha256(export_receipt_to_json_bytes(value)).hexdigest()


def report_export_receipts_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    path = class_module_dir(root, class_value, "meridian") / "reporting_exports"
    _require_containment(root, path)
    return path


def report_export_receipt_path(
    workspace_root: str | Path,
    class_id: str,
    export_id: str,
) -> Path:
    return report_export_receipts_directory(
        workspace_root,
        class_id,
    ) / f"{_identifier(export_id, 'export_id')}.json"


def report_export_receipt_digest_path(
    workspace_root: str | Path,
    class_id: str,
    export_id: str,
) -> Path:
    return Path(
        str(report_export_receipt_path(workspace_root, class_id, export_id))
        + ".sha256"
    )


def report_export_receipt_relative_path(class_id: str, export_id: str) -> str:
    class_value = _identifier(class_id, "class_id")
    export_value = _identifier(export_id, "export_id")
    return (
        f"classes/{class_value}/modules/meridian/reporting_exports/"
        f"{export_value}.json"
    )


def write_export_receipt(
    workspace_root: str | Path,
    receipt: ExportReceipt,
) -> ExportReceiptWriteResult:
    """Persist one immutable receipt with exact-replay semantics."""

    candidate = validate_export_receipt(receipt)
    root = _root(workspace_root)
    _require_existing_core_class(root, candidate.class_id)
    collection = report_export_receipts_directory(root, candidate.class_id)
    _ensure_directory_chain(root, collection)
    lock = collection / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_receipts_directory(collection)
        path = report_export_receipt_path(
            root,
            candidate.class_id,
            candidate.export_id,
        )
        digest_path = report_export_receipt_digest_path(
            root,
            candidate.class_id,
            candidate.export_id,
        )
        content = export_receipt_to_json_bytes(candidate)
        if len(content) > DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_BYTES:
            raise ReportExportReceiptWriteError(
                "ExportReceipt exceeds canonical storage byte limit."
            )
        digest = hashlib.sha256(content).hexdigest()

        if path.exists() or digest_path.exists():
            try:
                stored = load_export_receipt(
                    root,
                    candidate.class_id,
                    candidate.export_id,
                )
            except ReportExportReceiptStorageError as error:
                raise ReportExportReceiptIntegrityError(
                    "Existing ExportReceipt identity is incomplete or invalid."
                ) from error
            if stored.content != content or stored.receipt_sha256 != digest:
                raise ReportExportReceiptConflictError(
                    "ExportReceipt identity already has different content."
                )
            return ExportReceiptWriteResult("existing", stored)

        _write_pair(path, digest_path, content, digest)
        stored = load_export_receipt(
            root,
            candidate.class_id,
            candidate.export_id,
        )
        return ExportReceiptWriteResult("created", stored)
    finally:
        _release_lock(lock)


def load_export_receipt(
    workspace_root: str | Path,
    class_id: str,
    export_id: str,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_BYTES,
) -> StoredExportReceipt:
    """Load and strictly verify one immutable ExportReceipt."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    export_value = _identifier(export_id, "export_id")
    collection = report_export_receipts_directory(root, class_value)
    _validate_existing_directory_chain(root, collection)
    _validate_receipts_directory(collection)
    path = report_export_receipt_path(root, class_value, export_value)
    digest_path = report_export_receipt_digest_path(
        root,
        class_value,
        export_value,
    )
    content, digest = _read_pair(path, digest_path, maximum_bytes)
    try:
        receipt = export_receipt_from_json_bytes(content, maximum_bytes=maximum_bytes)
    except ReportExportReceiptError as error:
        raise ReportExportReceiptIntegrityError(
            f"Stored ExportReceipt is invalid: {error}"
        ) from error
    if receipt.class_id != class_value or receipt.export_id != export_value:
        raise ReportExportReceiptIntegrityError(
            "Stored ExportReceipt identity does not match canonical path."
        )
    return StoredExportReceipt(
        receipt=receipt,
        receipt_sha256=digest,
        path=path,
        relative_path=report_export_receipt_relative_path(
            class_value,
            export_value,
        ),
        content=content,
    )


def list_export_receipt_ids(
    workspace_root: str | Path,
    class_id: str,
) -> tuple[str, ...]:
    """Return immutable receipt identities in deterministic lexical order."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    collection = report_export_receipts_directory(root, class_value)
    if not collection.exists():
        return ()
    _validate_existing_directory_chain(root, collection)
    _validate_receipts_directory(collection)
    json_ids: set[str] = set()
    digest_ids: set[str] = set()
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ReportExportReceiptReadError(
            "Could not enumerate ExportReceipt collection."
        ) from error
    for entry in entries:
        if entry.name == ".write.lock":
            continue
        _reject_symlink(entry, "ExportReceipt collection entry")
        if not entry.is_file():
            raise ReportExportReceiptIntegrityError(
                "ExportReceipt collection contains a non-file entry."
            )
        json_match = _RECEIPT_JSON.fullmatch(entry.name)
        if json_match is not None:
            json_ids.add(_identifier(json_match.group(1), "export_id"))
            continue
        digest_match = _RECEIPT_DIGEST.fullmatch(entry.name)
        if digest_match is not None:
            digest_ids.add(_identifier(digest_match.group(1), "export_id"))
            continue
        raise ReportExportReceiptIntegrityError(
            f"Unexpected ExportReceipt collection entry: {entry.name}."
        )
    if json_ids != digest_ids:
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt JSON/digest pairs are incomplete."
        )
    ordered = tuple(sorted(json_ids))
    for export_id in ordered:
        load_export_receipt(root, class_value, export_id)
    return ordered


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise ReportExportReceiptNotFoundError(
            "Core class workspace must exist before receipt creation."
        )
    _validate_existing_directory_chain(root, path)


def _validate_receipts_directory(collection: Path) -> None:
    if collection.is_symlink() or not collection.is_dir():
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt canonical root is unsafe or not a directory."
        )
    try:
        entries = tuple(collection.iterdir())
    except OSError as error:
        raise ReportExportReceiptReadError(
            "Could not inspect ExportReceipt canonical root."
        ) from error
    for entry in entries:
        if entry.name == ".write.lock":
            if entry.is_symlink() or not entry.is_file():
                raise ReportExportReceiptIntegrityError(
                    "ExportReceipt lock entry must be a regular file."
                )
            continue
        if entry.is_symlink() or not entry.is_file():
            raise ReportExportReceiptIntegrityError(
                "ExportReceipt canonical root contains an unsafe entry."
            )
        if (
            _RECEIPT_JSON.fullmatch(entry.name) is None
            and _RECEIPT_DIGEST.fullmatch(entry.name) is None
        ):
            raise ReportExportReceiptIntegrityError(
                "ExportReceipt canonical root contains an unexpected entry."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise ReportExportReceiptValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise ReportExportReceiptNotFoundError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise ReportExportReceiptIntegrityError(
            "Workspace root must be a real directory, not a symlink."
        )
    return root


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ReportExportReceiptIntegrityError(
                    "ExportReceipt storage directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ReportExportReceiptWriteError(
                    "Could not create ExportReceipt storage directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise ReportExportReceiptNotFoundError(
                "Required ExportReceipt storage directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ReportExportReceiptIntegrityError(
                "ExportReceipt storage directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ReportExportReceiptValidationError(
            "ExportReceipt storage path escapes supplied workspace root."
        ) from error


def _read_pair(
    path: Path,
    digest_path: Path,
    maximum_bytes: int,
) -> tuple[bytes, str]:
    content = _read_bounded_regular_file(
        path,
        maximum_bytes,
        missing_message="ExportReceipt does not exist.",
    )
    digest_bytes = _read_bounded_regular_file(
        digest_path,
        DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_DIGEST_BYTES,
        missing_message="ExportReceipt digest does not exist.",
    )
    expected_digest = _parse_digest_sidecar(digest_bytes)
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt digest does not match exact JSON bytes."
        )
    return content, expected_digest


def _read_bounded_regular_file(
    path: Path,
    maximum_bytes: int,
    *,
    missing_message: str,
) -> bytes:
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt storage file must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise ReportExportReceiptIntegrityError(
                    "ExportReceipt storage path must be a regular file."
                )
            content = source.read(limit + 1)
    except ReportExportReceiptStorageError:
        raise
    except FileNotFoundError as error:
        raise ReportExportReceiptNotFoundError(missing_message) from error
    except OSError as error:
        raise ReportExportReceiptReadError(
            "Could not read ExportReceipt storage file."
        ) from error
    if len(content) > limit:
        raise ReportExportReceiptTooLargeError(
            "ExportReceipt storage file exceeds configured byte limit."
        )
    return content


def _parse_digest_sidecar(data: bytes) -> str:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt SHA-256 sidecar must be ASCII."
        ) from error
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt SHA-256 sidecar is not canonical."
        )
    try:
        return _sha256(text[:-1], "sha256")
    except ReportExportReceiptValidationError as error:
        raise ReportExportReceiptIntegrityError(
            "ExportReceipt SHA-256 sidecar digest is invalid."
        ) from error


def _write_pair(path: Path, digest_path: Path, content: bytes, digest: str) -> None:
    json_created = False
    digest_created = False
    try:
        with path.open("xb") as output:
            json_created = True
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        with digest_path.open("xb") as output:
            digest_created = True
            output.write((digest + "\n").encode("ascii"))
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory_if_supported(path.parent)
    except FileExistsError as error:
        raise ReportExportReceiptConflictError(
            "ExportReceipt identity was created concurrently."
        ) from error
    except OSError as error:
        cleanup_error: OSError | None = None
        for target, created in (
            (digest_path, digest_created),
            (path, json_created),
        ):
            if not created:
                continue
            try:
                target.unlink(missing_ok=True)
            except OSError as caught:
                cleanup_error = caught
        message = "Could not write ExportReceipt JSON/digest pair."
        if cleanup_error is not None:
            message += f" Cleanup failed: {cleanup_error}"
        raise ReportExportReceiptWriteError(message) from error


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as lock_file:
            lock_file.write(f"pid={os.getpid()}\n".encode("ascii"))
            lock_file.flush()
            os.fsync(lock_file.fileno())
    except FileExistsError as error:
        raise ReportExportReceiptLockError(
            "Another ExportReceipt writer owns this class collection."
        ) from error
    except OSError as error:
        raise ReportExportReceiptWriteError(
            "Could not acquire ExportReceipt write lock."
        ) from error


def _release_lock(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise ReportExportReceiptWriteError(
            "Could not release ExportReceipt write lock."
        ) from error


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ReportExportReceiptIntegrityError(f"{label} must not be a symlink.")


def _fsync_directory_if_supported(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _raise_schema_item() -> ExportPreviewColumn:
    raise ReportExportReceiptValidationError(
        "output_schema must contain ExportPreviewColumn values."
    )


def _safe_basename(value: object) -> str:
    text = _bounded_text(
        value,
        "basename",
        MAXIMUM_REPORT_EXPORT_BASENAME_LENGTH,
    )
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ReportExportReceiptValidationError(
            "basename must be one safe filename component."
        )
    if Path(text).name != text:
        raise ReportExportReceiptValidationError(
            "basename must not contain path components."
        )
    return text


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportExportReceiptSerializationError(
            f"{label} must be valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportExportReceiptSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ReportExportReceiptSerializationError(
            f"{label} must contain valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportExportReceiptSerializationError(
                f"duplicate JSON object key: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportExportReceiptSerializationError(
        f"non-finite JSON constant is not permitted: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, dict):
        raise ReportExportReceiptValidationError(f"{label} must be an object.")
    actual = frozenset(data)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportExportReceiptValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportExportReceiptValidationError(str(error)) from error


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise ReportExportReceiptValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ReportExportReceiptValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise ReportExportReceiptValidationError(
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
        raise ReportExportReceiptValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _nonnegative_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer < 0:
        raise ReportExportReceiptValidationError(
            f"{field_name} must be nonnegative."
        )
    return integer


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReportExportReceiptValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a boolean."
        )
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportExportReceiptValidationError(
            f"{field_name} must be a JSON array."
        )
    return value


__all__ = [
    "DEFAULT_MAXIMUM_REPORT_EXPORT_RECEIPT_BYTES",
    "ExportReceipt",
    "ExportReceiptReference",
    "ExportReceiptWriteResult",
    "MAXIMUM_REPORT_EXPORT_ACTOR_ID_LENGTH",
    "MAXIMUM_REPORT_EXPORT_BASENAME_LENGTH",
    "MAXIMUM_REPORT_EXPORT_RATIONALE_LENGTH",
    "REPORT_EXPORT_RECEIPT_RECORD_TYPE",
    "REPORT_EXPORT_RECEIPT_SCHEMA_VERSION",
    "ReportExportActor",
    "ReportExportActorKind",
    "ReportExportDestinationKind",
    "ReportExportDestinationReceipt",
    "ReportExportReceiptConflictError",
    "ReportExportReceiptError",
    "ReportExportReceiptIntegrityError",
    "ReportExportReceiptLockError",
    "ReportExportReceiptNotFoundError",
    "ReportExportReceiptReadError",
    "ReportExportReceiptSerializationError",
    "ReportExportReceiptStorageError",
    "ReportExportReceiptTooLargeError",
    "ReportExportReceiptValidationError",
    "ReportExportReceiptWriteDisposition",
    "ReportExportReceiptWriteError",
    "StoredExportReceipt",
    "export_receipt_from_dict",
    "export_receipt_from_json_bytes",
    "export_receipt_from_preview",
    "export_receipt_sha256",
    "export_receipt_to_dict",
    "export_receipt_to_json_bytes",
    "list_export_receipt_ids",
    "load_export_receipt",
    "report_export_receipt_digest_path",
    "report_export_receipt_path",
    "report_export_receipt_relative_path",
    "report_export_receipts_directory",
    "validate_export_receipt",
    "write_export_receipt",
]
