"""Canonical ReportingSnapshot record contracts for Meridian v0.3.

Issue #55 Slice 3 composes the already-frozen #54 Grade report representation
with an explicit build request, exact provenance bindings, and two distinct
integrity identities:

* ``payload_sha256`` identifies the semantic snapshot payload before the
  integrity envelope is added; and
* ``ReportingSnapshotReference.snapshot_sha256`` identifies the exact canonical
  stored snapshot bytes.

This module remains pure.  It does not read or write the workspace, select a
current snapshot, recalculate Grades, or mutate upstream academic authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    module_work_ref_from_dict,
    module_work_ref_to_dict,
    validate_module_work_ref,
)

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreviewRequest
from meridian.reporting_snapshot import (
    MAXIMUM_REPORTING_RATIONALE_LENGTH,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingSnapshotError,
    ReportingSnapshotPredecessor,
    ReportingSnapshotReference,
    ReportingSnapshotSerializationError,
    ReportingSnapshotValidationError,
    reporting_definition_reference_from_dict,
    reporting_definition_reference_to_dict,
    reporting_snapshot_predecessor_from_dict,
    reporting_snapshot_predecessor_to_dict,
)
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    ReportingSnapshotPreviewIntegrityError,
    frozen_grade_report_preview_from_dict,
    frozen_grade_report_preview_sha256,
)

REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION: Final[str] = "1"
REPORTING_SNAPSHOT_SCHEMA_VERSION: Final[str] = "1"
REPORTING_SNAPSHOT_RECORD_TYPE: Final[str] = "meridian_reporting_snapshot"
REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM: Final[str] = "sha256"

DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES: Final[int] = 128 * 1024 * 1024
MAXIMUM_REPORTING_SNAPSHOT_REQUEST_ROWS: Final[int] = 10_000
MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_BINDINGS: Final[int] = 10_000
MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_REFERENCE_BYTES: Final[int] = 1024 * 1024
MAXIMUM_REPORTING_SNAPSHOT_REFERENCE_KIND_LENGTH: Final[int] = 128

ReportingSnapshotEvidenceStatus: TypeAlias = Literal[
    "available",
    "missing",
    "unavailable",
]
ReportingSnapshotProvenanceAuthorityKind: TypeAlias = Literal[
    "academic_period_calendar",
    "core_publication",
    "core_publication_state",
    "grade_item_revision",
    "grade_item_membership",
    "evidence_source",
    "evidence_eligibility",
    "attempt_selection",
    "reassessment",
    "proficiency_mapping",
    "grade_item_proficiency_result",
    "academic_period_proficiency_result",
    "grade_policy_activation",
    "grade_policy_revision",
    "grade_result",
    "teacher_grade_override",
]

_EVIDENCE_STATUSES: Final[frozenset[str]] = frozenset(
    {"available", "missing", "unavailable"}
)
_PROVENANCE_AUTHORITY_KINDS: Final[frozenset[str]] = frozenset(
    {
        "academic_period_calendar",
        "core_publication",
        "core_publication_state",
        "grade_item_revision",
        "grade_item_membership",
        "evidence_source",
        "evidence_eligibility",
        "attempt_selection",
        "reassessment",
        "proficiency_mapping",
        "grade_item_proficiency_result",
        "academic_period_proficiency_result",
        "grade_policy_activation",
        "grade_policy_revision",
        "grade_result",
        "teacher_grade_override",
    }
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")

_PROJECTION_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {"publication_id", "cache_key", "snapshot_digest"}
)
_WORK_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"grade_item_id", "work", "status", "projection_snapshots"}
)
_GRADE_REQUEST_KEYS: Final[frozenset[str]] = frozenset(
    {"target", "work_evidence"}
)
_BUILD_REQUEST_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "definition_reference",
        "grade_requests",
        "actor",
        "rationale",
        "requested_at",
        "predecessor",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "student_id",
        "target_period",
        "calendar_revision",
        "calculation_family",
    }
)
_PROVENANCE_BINDING_KEYS: Final[frozenset[str]] = frozenset(
    {"authority_kind", "reference_kind", "reference", "reference_sha256"}
)
_SNAPSHOT_INTEGRITY_KEYS: Final[frozenset[str]] = frozenset(
    {"algorithm", "payload_sha256"}
)
_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "snapshot_id",
        "definition_reference",
        "build_request",
        "build_request_sha256",
        "class_id",
        "target_period",
        "calendar_revision",
        "report_preview",
        "report_preview_sha256",
        "provenance_bindings",
        "predecessor",
        "created_at",
        "integrity",
    }
)


class ReportingSnapshotRequestValidationError(ReportingSnapshotValidationError):
    """Raised when an explicit snapshot build request is invalid."""

    code = "reporting_snapshot.request_invalid"


class ReportingSnapshotIntegrityError(ReportingSnapshotSerializationError):
    """Raised when canonical snapshot/report provenance cannot be trusted."""

    code = "reporting_snapshot.integrity_failed"


@dataclass(frozen=True, slots=True)
class ReportingSnapshotProjectionInputReference:
    """Exact authorized projection snapshot supplied in one report request."""

    publication_id: str
    cache_key: str
    snapshot_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "publication_id",
            _request_identifier(self.publication_id, "publication_id"),
        )
        object.__setattr__(
            self,
            "cache_key",
            _request_sha256(self.cache_key, "cache_key"),
        )
        object.__setattr__(
            self,
            "snapshot_digest",
            _request_sha256(self.snapshot_digest, "snapshot_digest"),
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotWorkEvidenceRequest:
    """Privacy-minimized exact request-side evidence identity for one work."""

    grade_item_id: str
    work: ModuleWorkRef
    status: ReportingSnapshotEvidenceStatus
    projection_snapshots: tuple[ReportingSnapshotProjectionInputReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "grade_item_id",
            _request_identifier(self.grade_item_id, "grade_item_id"),
        )
        if not isinstance(self.work, ModuleWorkRef):
            raise ReportingSnapshotRequestValidationError(
                "work must be a ModuleWorkRef."
            )
        try:
            work = validate_module_work_ref(self.work)
        except RoutingModelError as error:
            raise ReportingSnapshotRequestValidationError(
                f"work is invalid: {error}"
            ) from error
        if self.status not in _EVIDENCE_STATUSES:
            raise ReportingSnapshotRequestValidationError(
                "evidence status must be available, missing, or unavailable."
            )
        snapshots = _typed_tuple(
            self.projection_snapshots,
            ReportingSnapshotProjectionInputReference,
            "projection_snapshots",
        )
        keys = tuple(_projection_input_key(item) for item in snapshots)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotRequestValidationError(
                "projection_snapshots must not duplicate exact snapshot identity."
            )
        snapshots = tuple(sorted(snapshots, key=_projection_input_key))
        if self.status == "available" and not snapshots:
            raise ReportingSnapshotRequestValidationError(
                "available work evidence requires projection_snapshots."
            )
        if self.status != "available" and snapshots:
            raise ReportingSnapshotRequestValidationError(
                "missing/unavailable work evidence must not carry projections."
            )
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "projection_snapshots", snapshots)


@dataclass(frozen=True, slots=True)
class ReportingSnapshotGradeRequest:
    """Canonical request identity for one explicit #54 Grade target."""

    target: GradePreviewTarget
    work_evidence: tuple[ReportingSnapshotWorkEvidenceRequest, ...] | None

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise ReportingSnapshotRequestValidationError(
                "grade request target must be GradePreviewTarget."
            )
        evidence = self.work_evidence
        if self.target.calculation_family in {"conventional", "hybrid"}:
            if evidence is None:
                raise ReportingSnapshotRequestValidationError(
                    f"{self.target.calculation_family} request requires work_evidence."
                )
        elif evidence is not None:
            raise ReportingSnapshotRequestValidationError(
                "standards-based request must not carry work_evidence."
            )
        if evidence is None:
            return
        typed = _typed_tuple(
            evidence,
            ReportingSnapshotWorkEvidenceRequest,
            "work_evidence",
        )
        keys = tuple(_work_evidence_key(item) for item in typed)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotRequestValidationError(
                "work_evidence must not duplicate a Grade Item/work relation."
            )
        for item in typed:
            if item.work.class_id != self.target.class_id:
                raise ReportingSnapshotRequestValidationError(
                    "work evidence class must match request target class."
                )
        object.__setattr__(
            self,
            "work_evidence",
            tuple(sorted(typed, key=_work_evidence_key)),
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotBuildRequest:
    """Explicit deterministic request whose exact identity is frozen in a snapshot."""

    schema_version: str
    definition_reference: ReportingDefinitionReference
    grade_requests: tuple[ReportingSnapshotGradeRequest, ...]
    actor: ReportingActor
    rationale: str | None
    requested_at: datetime
    predecessor: ReportingSnapshotPredecessor | None

    def __post_init__(self) -> None:
        if self.schema_version != REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION:
            raise ReportingSnapshotRequestValidationError(
                'build request schema_version must be "1".'
            )
        if not isinstance(self.definition_reference, ReportingDefinitionReference):
            raise ReportingSnapshotRequestValidationError(
                "definition_reference must be ReportingDefinitionReference."
            )
        definition = ReportingDefinitionReference(
            class_id=self.definition_reference.class_id,
            definition_id=self.definition_reference.definition_id,
            definition_revision=self.definition_reference.definition_revision,
            definition_sha256=self.definition_reference.definition_sha256,
        )
        requests = _typed_tuple(
            self.grade_requests,
            ReportingSnapshotGradeRequest,
            "grade_requests",
        )
        if not requests:
            raise ReportingSnapshotRequestValidationError(
                "grade_requests must contain at least one explicit Grade target."
            )
        if len(requests) > MAXIMUM_REPORTING_SNAPSHOT_REQUEST_ROWS:
            raise ReportingSnapshotRequestValidationError(
                "grade_requests exceeds the configured maximum row count."
            )
        keys = tuple(_target_key(item.target) for item in requests)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotRequestValidationError(
                "grade_requests must not duplicate exact Grade targets."
            )
        requests = tuple(sorted(requests, key=lambda item: _target_key(item.target)))
        first = requests[0].target
        for item in requests:
            target = item.target
            if target.class_id != definition.class_id:
                raise ReportingSnapshotRequestValidationError(
                    "grade request class must match reporting definition class."
                )
            if target.target_period != first.target_period:
                raise ReportingSnapshotRequestValidationError(
                    "all Grade requests must use one exact Academic Period."
                )
            if target.calendar_revision != first.calendar_revision:
                raise ReportingSnapshotRequestValidationError(
                    "all Grade requests must use one exact calendar revision."
                )
        if not isinstance(self.actor, ReportingActor):
            raise ReportingSnapshotRequestValidationError(
                "actor must be a ReportingActor."
            )
        actor = ReportingActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_REPORTING_RATIONALE_LENGTH,
        )
        requested_at = _aware_utc_datetime(self.requested_at, "requested_at")
        predecessor = self.predecessor
        if predecessor is not None:
            if not isinstance(predecessor, ReportingSnapshotPredecessor):
                raise ReportingSnapshotRequestValidationError(
                    "predecessor must be ReportingSnapshotPredecessor."
                )
            predecessor = ReportingSnapshotPredecessor(
                predecessor.relationship,
                predecessor.snapshot_reference,
            )
            if predecessor.snapshot_reference.class_id != definition.class_id:
                raise ReportingSnapshotRequestValidationError(
                    "predecessor snapshot class must match build request class."
                )
        object.__setattr__(self, "definition_reference", definition)
        object.__setattr__(self, "grade_requests", requests)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "predecessor", predecessor)

    @property
    def target_period(self) -> AcademicPeriodRef:
        """Return the one exact Academic Period shared by all requested rows."""

        return self.grade_requests[0].target.target_period

    @property
    def calendar_revision(self) -> int:
        """Return the one exact Core calendar revision shared by all rows."""

        return self.grade_requests[0].target.calendar_revision


@dataclass(frozen=True, slots=True)
class ReportingSnapshotProvenanceBinding:
    """Typed authority binding retaining one exact canonical reference object."""

    authority_kind: ReportingSnapshotProvenanceAuthorityKind
    reference_kind: str
    reference_json: bytes = field(repr=False)
    reference_sha256: str

    def __post_init__(self) -> None:
        if self.authority_kind not in _PROVENANCE_AUTHORITY_KINDS:
            raise ReportingSnapshotIntegrityError(
                "unsupported reporting snapshot provenance authority kind."
            )
        reference_kind = _identifier(self.reference_kind, "reference_kind")
        if len(reference_kind) > MAXIMUM_REPORTING_SNAPSHOT_REFERENCE_KIND_LENGTH:
            raise ReportingSnapshotIntegrityError(
                "reference_kind exceeds the configured maximum length."
            )
        if type(self.reference_json) is not bytes or not self.reference_json:
            raise ReportingSnapshotIntegrityError(
                "provenance reference_json must be nonempty immutable bytes."
            )
        if (
            len(self.reference_json)
            > MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_REFERENCE_BYTES
        ):
            raise ReportingSnapshotIntegrityError(
                "provenance reference exceeds the configured maximum byte size."
            )
        decoded = _decode_json(self.reference_json, "provenance reference")
        _require_mapping(decoded, "provenance reference")
        canonical = _canonical_json_bytes(decoded)
        if canonical != self.reference_json:
            raise ReportingSnapshotIntegrityError(
                "provenance reference bytes are not canonical."
            )
        digest = _sha256(self.reference_sha256, "reference_sha256")
        if hashlib.sha256(canonical).hexdigest() != digest:
            raise ReportingSnapshotIntegrityError(
                "provenance reference digest does not match exact reference bytes."
            )
        object.__setattr__(self, "reference_kind", reference_kind)
        object.__setattr__(self, "reference_sha256", digest)


@dataclass(frozen=True, slots=True)
class ReportingSnapshot:
    """One immutable canonical Meridian reporting observation."""

    schema_version: str
    record_type: str
    snapshot_id: str
    definition_reference: ReportingDefinitionReference
    build_request: ReportingSnapshotBuildRequest
    build_request_sha256: str
    class_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    report_preview: FrozenGradeReportPreview = field(repr=False)
    report_preview_sha256: str
    provenance_bindings: tuple[ReportingSnapshotProvenanceBinding, ...]
    predecessor: ReportingSnapshotPredecessor | None
    created_at: datetime
    integrity_algorithm: str
    payload_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != REPORTING_SNAPSHOT_SCHEMA_VERSION:
            raise ReportingSnapshotIntegrityError(
                'ReportingSnapshot schema_version must be "1".'
            )
        if self.record_type != REPORTING_SNAPSHOT_RECORD_TYPE:
            raise ReportingSnapshotIntegrityError(
                'ReportingSnapshot record_type must be "meridian_reporting_snapshot".'
            )
        snapshot_id = _identifier(self.snapshot_id, "snapshot_id")
        if not isinstance(self.definition_reference, ReportingDefinitionReference):
            raise ReportingSnapshotIntegrityError(
                "definition_reference must be ReportingDefinitionReference."
            )
        definition = ReportingDefinitionReference(
            class_id=self.definition_reference.class_id,
            definition_id=self.definition_reference.definition_id,
            definition_revision=self.definition_reference.definition_revision,
            definition_sha256=self.definition_reference.definition_sha256,
        )
        if not isinstance(self.build_request, ReportingSnapshotBuildRequest):
            raise ReportingSnapshotIntegrityError(
                "build_request must be ReportingSnapshotBuildRequest."
            )
        request = self.build_request
        if request.definition_reference != definition:
            raise ReportingSnapshotIntegrityError(
                "snapshot definition does not match exact build request definition."
            )
        request_digest = _sha256(
            self.build_request_sha256,
            "build_request_sha256",
        )
        if reporting_snapshot_build_request_sha256(request) != request_digest:
            raise ReportingSnapshotIntegrityError(
                "build request digest does not match exact request bytes."
            )
        class_id = _identifier(self.class_id, "class_id")
        if class_id != definition.class_id:
            raise ReportingSnapshotIntegrityError(
                "snapshot class must match exact reporting definition class."
            )
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise ReportingSnapshotIntegrityError(
                "target_period must be AcademicPeriodRef."
            )
        try:
            period = validate_academic_period_ref(self.target_period)
        except AcademicPeriodValidationError as error:
            raise ReportingSnapshotIntegrityError(
                f"target_period is invalid: {error}"
            ) from error
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if request.target_period != period:
            raise ReportingSnapshotIntegrityError(
                "snapshot Academic Period does not match exact build request."
            )
        if request.calendar_revision != calendar_revision:
            raise ReportingSnapshotIntegrityError(
                "snapshot calendar revision does not match exact build request."
            )
        if not isinstance(self.report_preview, FrozenGradeReportPreview):
            raise ReportingSnapshotIntegrityError(
                "report_preview must be FrozenGradeReportPreview."
            )
        preview_digest = _sha256(
            self.report_preview_sha256,
            "report_preview_sha256",
        )
        if frozen_grade_report_preview_sha256(self.report_preview) != preview_digest:
            raise ReportingSnapshotIntegrityError(
                "report preview digest does not match exact frozen preview."
            )
        request_targets = tuple(
            _target_key(item.target) for item in request.grade_requests
        )
        report_targets = tuple(
            _target_key(item.target) for item in self.report_preview.rows
        )
        if request_targets != report_targets:
            raise ReportingSnapshotIntegrityError(
                "frozen report targets do not match exact build request targets."
            )
        bindings = _typed_tuple(
            self.provenance_bindings,
            ReportingSnapshotProvenanceBinding,
            "provenance_bindings",
        )
        if not bindings:
            raise ReportingSnapshotIntegrityError(
                "ReportingSnapshot requires exact provenance bindings."
            )
        if len(bindings) > MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_BINDINGS:
            raise ReportingSnapshotIntegrityError(
                "provenance_bindings exceeds the configured maximum count."
            )
        if not any(
            item.authority_kind == "academic_period_calendar"
            for item in bindings
        ):
            raise ReportingSnapshotIntegrityError(
                "ReportingSnapshot requires Academic Period calendar provenance."
            )
        keys = tuple(_provenance_binding_key(item) for item in bindings)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotIntegrityError(
                "provenance_bindings must not contain duplicate exact bindings."
            )
        bindings = tuple(sorted(bindings, key=_provenance_binding_key))
        predecessor = self.predecessor
        if predecessor is not None:
            if not isinstance(predecessor, ReportingSnapshotPredecessor):
                raise ReportingSnapshotIntegrityError(
                    "predecessor must be ReportingSnapshotPredecessor."
                )
            predecessor = ReportingSnapshotPredecessor(
                predecessor.relationship,
                predecessor.snapshot_reference,
            )
            if predecessor.snapshot_reference.class_id != class_id:
                raise ReportingSnapshotIntegrityError(
                    "predecessor snapshot class must match snapshot class."
                )
        if predecessor != request.predecessor:
            raise ReportingSnapshotIntegrityError(
                "snapshot predecessor must match exact build request predecessor."
            )
        created_at = _aware_utc_datetime(self.created_at, "created_at")
        if created_at < request.requested_at:
            raise ReportingSnapshotIntegrityError(
                "created_at must not be earlier than requested_at."
            )
        if self.integrity_algorithm != REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM:
            raise ReportingSnapshotIntegrityError(
                "integrity_algorithm must be sha256."
            )
        payload_digest = _sha256(self.payload_sha256, "payload_sha256")

        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(self, "definition_reference", definition)
        object.__setattr__(self, "build_request_sha256", request_digest)
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "report_preview_sha256", preview_digest)
        object.__setattr__(self, "provenance_bindings", bindings)
        object.__setattr__(self, "predecessor", predecessor)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "payload_sha256", payload_digest)

        expected_payload = _snapshot_payload_sha256(self)
        if expected_payload != payload_digest:
            raise ReportingSnapshotIntegrityError(
                "snapshot payload digest does not match exact semantic payload."
            )


def reporting_snapshot_build_request_from_preview_requests(
    *,
    definition_reference: ReportingDefinitionReference,
    requests: tuple[GradeReportPreviewRequest, ...],
    actor: ReportingActor,
    requested_at: datetime,
    rationale: str | None = None,
    predecessor: ReportingSnapshotPredecessor | None = None,
) -> ReportingSnapshotBuildRequest:
    """Normalize explicit #54 requests into the stable #55 build-request contract."""

    if not isinstance(requests, tuple) or any(
        not isinstance(item, GradeReportPreviewRequest) for item in requests
    ):
        raise ReportingSnapshotRequestValidationError(
            "requests must be a tuple of GradeReportPreviewRequest values."
        )
    normalized = tuple(_normalize_grade_report_request(item) for item in requests)
    return ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition_reference,
        grade_requests=normalized,
        actor=actor,
        rationale=rationale,
        requested_at=requested_at,
        predecessor=predecessor,
    )


def reporting_snapshot_build_request_to_dict(
    value: ReportingSnapshotBuildRequest,
) -> dict[str, object]:
    """Convert one exact build request to deterministic JSON-native data."""

    request = _validate_build_request(value)
    return {
        "schema_version": request.schema_version,
        "definition_reference": reporting_definition_reference_to_dict(
            request.definition_reference
        ),
        "grade_requests": [
            _grade_request_to_dict(item) for item in request.grade_requests
        ],
        "actor": _actor_to_dict(request.actor),
        "rationale": request.rationale,
        "requested_at": request.requested_at.isoformat(),
        "predecessor": (
            reporting_snapshot_predecessor_to_dict(request.predecessor)
            if request.predecessor is not None
            else None
        ),
    }


def reporting_snapshot_build_request_from_dict(
    data: object,
) -> ReportingSnapshotBuildRequest:
    """Parse one strict snapshot build request."""

    try:
        mapping = _exact_mapping(data, _BUILD_REQUEST_KEYS, "snapshot build request")
        actor_data = _exact_mapping(
            mapping["actor"],
            _ACTOR_KEYS,
            "build request actor",
        )
        kind = _require_str(actor_data["kind"], "actor.kind")
        if kind != "teacher":
            raise ReportingSnapshotRequestValidationError(
                "build request actor kind must be teacher."
            )
        return ReportingSnapshotBuildRequest(
            schema_version=_require_str(mapping["schema_version"], "schema_version"),
            definition_reference=reporting_definition_reference_from_dict(
                mapping["definition_reference"]
            ),
            grade_requests=tuple(
                _grade_request_from_dict(item)
                for item in _require_list(mapping["grade_requests"], "grade_requests")
            ),
            actor=ReportingActor(
                cast(Literal["teacher"], kind),
                _require_str(actor_data["actor_id"], "actor.actor_id"),
            ),
            rationale=_optional_str(mapping["rationale"], "rationale"),
            requested_at=_datetime_from_text(mapping["requested_at"], "requested_at"),
            predecessor=(
                reporting_snapshot_predecessor_from_dict(mapping["predecessor"])
                if mapping["predecessor"] is not None
                else None
            ),
        )
    except ReportingSnapshotRequestValidationError:
        raise
    except ReportingSnapshotError as error:
        raise ReportingSnapshotRequestValidationError(
            f"snapshot build request is invalid: {error}"
        ) from error
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotRequestValidationError(
            f"snapshot build request is invalid: {error}"
        ) from error


def reporting_snapshot_build_request_to_json_bytes(
    value: ReportingSnapshotBuildRequest,
) -> bytes:
    """Serialize one build request using canonical #55 JSON bytes."""

    return _canonical_json_bytes(reporting_snapshot_build_request_to_dict(value))


def reporting_snapshot_build_request_from_json_bytes(
    data: bytes,
) -> ReportingSnapshotBuildRequest:
    """Load a canonical build request and reject alternate encodings."""

    decoded = _decode_json(data, "snapshot build request")
    request = reporting_snapshot_build_request_from_dict(decoded)
    if reporting_snapshot_build_request_to_json_bytes(request) != data:
        raise ReportingSnapshotSerializationError(
            "snapshot build request bytes are not the canonical encoding."
        )
    return request


def reporting_snapshot_build_request_sha256(
    value: ReportingSnapshotBuildRequest,
) -> str:
    """Return exact canonical build-request identity."""

    return hashlib.sha256(
        reporting_snapshot_build_request_to_json_bytes(value)
    ).hexdigest()


def reporting_snapshot_provenance_binding(
    *,
    authority_kind: ReportingSnapshotProvenanceAuthorityKind,
    reference_kind: str,
    reference: Mapping[str, object],
) -> ReportingSnapshotProvenanceBinding:
    """Create one exact typed provenance binding from structured reference data."""

    if not isinstance(reference, Mapping):
        raise ReportingSnapshotIntegrityError(
            "provenance reference must be a mapping."
        )
    canonical = _canonical_json_bytes(dict(reference))
    return ReportingSnapshotProvenanceBinding(
        authority_kind=authority_kind,
        reference_kind=reference_kind,
        reference_json=canonical,
        reference_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def reporting_snapshot_provenance_binding_to_dict(
    value: ReportingSnapshotProvenanceBinding,
) -> dict[str, object]:
    """Convert one exact provenance binding to deterministic JSON data."""

    if not isinstance(value, ReportingSnapshotProvenanceBinding):
        raise ReportingSnapshotIntegrityError(
            "value must be ReportingSnapshotProvenanceBinding."
        )
    return {
        "authority_kind": value.authority_kind,
        "reference_kind": value.reference_kind,
        "reference": _json_mapping_from_canonical_bytes(
            value.reference_json,
            "provenance reference",
        ),
        "reference_sha256": value.reference_sha256,
    }


def reporting_snapshot_provenance_binding_from_dict(
    data: object,
) -> ReportingSnapshotProvenanceBinding:
    """Parse and verify one exact typed provenance binding."""

    mapping = _exact_mapping(data, _PROVENANCE_BINDING_KEYS, "provenance binding")
    authority = _require_str(mapping["authority_kind"], "authority_kind")
    if authority not in _PROVENANCE_AUTHORITY_KINDS:
        raise ReportingSnapshotIntegrityError(
            "unsupported reporting snapshot provenance authority kind."
        )
    reference = _require_mapping(mapping["reference"], "provenance reference")
    canonical = _canonical_json_bytes(reference)
    return ReportingSnapshotProvenanceBinding(
        authority_kind=cast(ReportingSnapshotProvenanceAuthorityKind, authority),
        reference_kind=_require_str(mapping["reference_kind"], "reference_kind"),
        reference_json=canonical,
        reference_sha256=_require_str(
            mapping["reference_sha256"],
            "reference_sha256",
        ),
    )


def compose_reporting_snapshot(
    *,
    snapshot_id: str,
    build_request: ReportingSnapshotBuildRequest,
    report_preview: FrozenGradeReportPreview,
    provenance_bindings: tuple[ReportingSnapshotProvenanceBinding, ...],
    created_at: datetime,
) -> ReportingSnapshot:
    """Compose a validated immutable snapshot record without persistence or I/O."""

    request = _validate_build_request(build_request)
    if not isinstance(report_preview, FrozenGradeReportPreview):
        raise ReportingSnapshotIntegrityError(
            "report_preview must be FrozenGradeReportPreview."
        )
    bindings = tuple(
        sorted(
            _typed_tuple(
                provenance_bindings,
                ReportingSnapshotProvenanceBinding,
                "provenance_bindings",
            ),
            key=_provenance_binding_key,
        )
    )
    candidate = {
        "schema_version": REPORTING_SNAPSHOT_SCHEMA_VERSION,
        "record_type": REPORTING_SNAPSHOT_RECORD_TYPE,
        "snapshot_id": snapshot_id,
        "definition_reference": request.definition_reference,
        "build_request": request,
        "build_request_sha256": reporting_snapshot_build_request_sha256(request),
        "class_id": request.definition_reference.class_id,
        "target_period": request.target_period,
        "calendar_revision": request.calendar_revision,
        "report_preview": report_preview,
        "report_preview_sha256": frozen_grade_report_preview_sha256(report_preview),
        "provenance_bindings": bindings,
        "predecessor": request.predecessor,
        "created_at": created_at,
        "integrity_algorithm": REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM,
    }
    payload_sha256 = hashlib.sha256(
        _canonical_json_bytes(_snapshot_payload_dict_from_parts(candidate))
    ).hexdigest()
    return ReportingSnapshot(
        schema_version=cast(str, candidate["schema_version"]),
        record_type=cast(str, candidate["record_type"]),
        snapshot_id=cast(str, candidate["snapshot_id"]),
        definition_reference=cast(
            ReportingDefinitionReference,
            candidate["definition_reference"],
        ),
        build_request=cast(ReportingSnapshotBuildRequest, candidate["build_request"]),
        build_request_sha256=cast(str, candidate["build_request_sha256"]),
        class_id=cast(str, candidate["class_id"]),
        target_period=cast(AcademicPeriodRef, candidate["target_period"]),
        calendar_revision=cast(int, candidate["calendar_revision"]),
        report_preview=cast(FrozenGradeReportPreview, candidate["report_preview"]),
        report_preview_sha256=cast(str, candidate["report_preview_sha256"]),
        provenance_bindings=cast(
            tuple[ReportingSnapshotProvenanceBinding, ...],
            candidate["provenance_bindings"],
        ),
        predecessor=cast(
            ReportingSnapshotPredecessor | None,
            candidate["predecessor"],
        ),
        created_at=cast(datetime, candidate["created_at"]),
        integrity_algorithm=cast(str, candidate["integrity_algorithm"]),
        payload_sha256=payload_sha256,
    )


def reporting_snapshot_to_dict(value: ReportingSnapshot) -> dict[str, object]:
    """Convert one validated ReportingSnapshot to exact JSON-native data."""

    snapshot = _validate_snapshot(value)
    payload = _snapshot_payload_to_dict(snapshot)
    return {
        **payload,
        "integrity": {
            "algorithm": snapshot.integrity_algorithm,
            "payload_sha256": snapshot.payload_sha256,
        },
    }


def reporting_snapshot_from_dict(data: object) -> ReportingSnapshot:
    """Parse and fully verify one canonical ReportingSnapshot object."""

    mapping = _exact_mapping(data, _SNAPSHOT_KEYS, "ReportingSnapshot")
    integrity = _exact_mapping(
        mapping["integrity"],
        _SNAPSHOT_INTEGRITY_KEYS,
        "ReportingSnapshot integrity",
    )
    try:
        request = reporting_snapshot_build_request_from_dict(mapping["build_request"])
        preview = frozen_grade_report_preview_from_dict(mapping["report_preview"])
        bindings = tuple(
            reporting_snapshot_provenance_binding_from_dict(item)
            for item in _require_list(
                mapping["provenance_bindings"],
                "provenance_bindings",
            )
        )
        return ReportingSnapshot(
            schema_version=_require_str(mapping["schema_version"], "schema_version"),
            record_type=_require_str(mapping["record_type"], "record_type"),
            snapshot_id=_require_str(mapping["snapshot_id"], "snapshot_id"),
            definition_reference=reporting_definition_reference_from_dict(
                mapping["definition_reference"]
            ),
            build_request=request,
            build_request_sha256=_require_str(
                mapping["build_request_sha256"],
                "build_request_sha256",
            ),
            class_id=_require_str(mapping["class_id"], "class_id"),
            target_period=_period_from_dict(mapping["target_period"]),
            calendar_revision=_require_int(
                mapping["calendar_revision"],
                "calendar_revision",
            ),
            report_preview=preview,
            report_preview_sha256=_require_str(
                mapping["report_preview_sha256"],
                "report_preview_sha256",
            ),
            provenance_bindings=bindings,
            predecessor=(
                reporting_snapshot_predecessor_from_dict(mapping["predecessor"])
                if mapping["predecessor"] is not None
                else None
            ),
            created_at=_datetime_from_text(mapping["created_at"], "created_at"),
            integrity_algorithm=_require_str(
                integrity["algorithm"],
                "integrity.algorithm",
            ),
            payload_sha256=_require_str(
                integrity["payload_sha256"],
                "integrity.payload_sha256",
            ),
        )
    except ReportingSnapshotIntegrityError:
        raise
    except ReportingSnapshotPreviewIntegrityError as error:
        raise ReportingSnapshotIntegrityError(
            f"embedded frozen report preview is invalid: {error}"
        ) from error
    except ReportingSnapshotError as error:
        raise ReportingSnapshotIntegrityError(
            f"ReportingSnapshot is invalid: {error}"
        ) from error
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotIntegrityError(
            f"ReportingSnapshot is invalid: {error}"
        ) from error


def reporting_snapshot_to_json_bytes(value: ReportingSnapshot) -> bytes:
    """Serialize one ReportingSnapshot using canonical #55 JSON bytes."""

    return _canonical_json_bytes(reporting_snapshot_to_dict(value))


def reporting_snapshot_from_json_bytes(
    data: bytes,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES,
) -> ReportingSnapshot:
    """Load one exact snapshot, verifying canonical bytes and all nested digests."""

    if type(data) is not bytes:
        raise ReportingSnapshotIntegrityError(
            "ReportingSnapshot data must be immutable bytes."
        )
    limit = _positive_int(maximum_bytes, "maximum_bytes")
    if len(data) > limit:
        raise ReportingSnapshotIntegrityError(
            "ReportingSnapshot exceeds the configured maximum byte size."
        )
    decoded = _decode_json(data, "ReportingSnapshot")
    snapshot = reporting_snapshot_from_dict(decoded)
    if reporting_snapshot_to_json_bytes(snapshot) != data:
        raise ReportingSnapshotIntegrityError(
            "ReportingSnapshot bytes are not the canonical encoding."
        )
    return snapshot


def reporting_snapshot_reference(
    value: ReportingSnapshot,
) -> ReportingSnapshotReference:
    """Return the exact outer-byte identity for one immutable snapshot."""

    snapshot = _validate_snapshot(value)
    digest = hashlib.sha256(reporting_snapshot_to_json_bytes(snapshot)).hexdigest()
    return ReportingSnapshotReference(
        class_id=snapshot.class_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=digest,
    )


def _normalize_grade_report_request(
    value: GradeReportPreviewRequest,
) -> ReportingSnapshotGradeRequest:
    evidence = value.work_evidence
    normalized_evidence: tuple[ReportingSnapshotWorkEvidenceRequest, ...] | None
    if evidence is None:
        normalized_evidence = None
    else:
        normalized_evidence = tuple(_normalize_work_evidence(item) for item in evidence)
    return ReportingSnapshotGradeRequest(
        target=value.target,
        work_evidence=normalized_evidence,
    )


def _normalize_work_evidence(
    value: ConventionalGradeWorkEvidenceSpec,
) -> ReportingSnapshotWorkEvidenceRequest:
    if not isinstance(value, ConventionalGradeWorkEvidenceSpec):
        raise ReportingSnapshotRequestValidationError(
            "work evidence must be ConventionalGradeWorkEvidenceSpec."
        )
    snapshots = tuple(
        ReportingSnapshotProjectionInputReference(
            publication_id=item.stored.snapshot.source.publication.publication_id,
            cache_key=item.stored.cache_key,
            snapshot_digest=item.stored.snapshot_digest,
        )
        for item in value.authorized_snapshots
    )
    return ReportingSnapshotWorkEvidenceRequest(
        grade_item_id=value.grade_item_id,
        work=value.work,
        status=value.status,
        projection_snapshots=snapshots,
    )


def _projection_input_to_dict(
    value: ReportingSnapshotProjectionInputReference,
) -> dict[str, object]:
    return {
        "publication_id": value.publication_id,
        "cache_key": value.cache_key,
        "snapshot_digest": value.snapshot_digest,
    }


def _projection_input_from_dict(
    data: object,
) -> ReportingSnapshotProjectionInputReference:
    mapping = _exact_mapping(data, _PROJECTION_INPUT_KEYS, "projection input")
    return ReportingSnapshotProjectionInputReference(
        publication_id=_require_str(mapping["publication_id"], "publication_id"),
        cache_key=_require_str(mapping["cache_key"], "cache_key"),
        snapshot_digest=_require_str(mapping["snapshot_digest"], "snapshot_digest"),
    )


def _work_evidence_to_dict(
    value: ReportingSnapshotWorkEvidenceRequest,
) -> dict[str, object]:
    return {
        "grade_item_id": value.grade_item_id,
        "work": module_work_ref_to_dict(value.work),
        "status": value.status,
        "projection_snapshots": [
            _projection_input_to_dict(item) for item in value.projection_snapshots
        ],
    }


def _work_evidence_from_dict(data: object) -> ReportingSnapshotWorkEvidenceRequest:
    mapping = _exact_mapping(data, _WORK_EVIDENCE_KEYS, "work evidence request")
    status = _require_str(mapping["status"], "status")
    if status not in _EVIDENCE_STATUSES:
        raise ReportingSnapshotRequestValidationError(
            "evidence status must be available, missing, or unavailable."
        )
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except (RoutingModelError, TypeError, ValueError) as error:
        raise ReportingSnapshotRequestValidationError(
            f"work evidence reference is invalid: {error}"
        ) from error
    return ReportingSnapshotWorkEvidenceRequest(
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        work=work,
        status=cast(ReportingSnapshotEvidenceStatus, status),
        projection_snapshots=tuple(
            _projection_input_from_dict(item)
            for item in _require_list(
                mapping["projection_snapshots"],
                "projection_snapshots",
            )
        ),
    )


def _grade_request_to_dict(value: ReportingSnapshotGradeRequest) -> dict[str, object]:
    return {
        "target": _target_to_dict(value.target),
        "work_evidence": (
            [_work_evidence_to_dict(item) for item in value.work_evidence]
            if value.work_evidence is not None
            else None
        ),
    }


def _grade_request_from_dict(data: object) -> ReportingSnapshotGradeRequest:
    mapping = _exact_mapping(data, _GRADE_REQUEST_KEYS, "grade request")
    raw_evidence = mapping["work_evidence"]
    return ReportingSnapshotGradeRequest(
        target=_target_from_dict(mapping["target"]),
        work_evidence=(
            tuple(
                _work_evidence_from_dict(item)
                for item in _require_list(raw_evidence, "work_evidence")
            )
            if raw_evidence is not None
            else None
        ),
    )


def _snapshot_payload_to_dict(value: ReportingSnapshot) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "snapshot_id": value.snapshot_id,
        "definition_reference": reporting_definition_reference_to_dict(
            value.definition_reference
        ),
        "build_request": reporting_snapshot_build_request_to_dict(value.build_request),
        "build_request_sha256": value.build_request_sha256,
        "class_id": value.class_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "report_preview": _json_mapping_from_canonical_bytes(
            value.report_preview.canonical_json,
            "frozen report preview",
        ),
        "report_preview_sha256": value.report_preview_sha256,
        "provenance_bindings": [
            reporting_snapshot_provenance_binding_to_dict(item)
            for item in value.provenance_bindings
        ],
        "predecessor": (
            reporting_snapshot_predecessor_to_dict(value.predecessor)
            if value.predecessor is not None
            else None
        ),
        "created_at": value.created_at.isoformat(),
    }


def _snapshot_payload_dict_from_parts(parts: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": parts["schema_version"],
        "record_type": parts["record_type"],
        "snapshot_id": parts["snapshot_id"],
        "definition_reference": reporting_definition_reference_to_dict(
            cast(ReportingDefinitionReference, parts["definition_reference"])
        ),
        "build_request": reporting_snapshot_build_request_to_dict(
            cast(ReportingSnapshotBuildRequest, parts["build_request"])
        ),
        "build_request_sha256": parts["build_request_sha256"],
        "class_id": parts["class_id"],
        "target_period": academic_period_ref_to_dict(
            cast(AcademicPeriodRef, parts["target_period"])
        ),
        "calendar_revision": parts["calendar_revision"],
        "report_preview": _json_mapping_from_canonical_bytes(
            cast(FrozenGradeReportPreview, parts["report_preview"]).canonical_json,
            "frozen report preview",
        ),
        "report_preview_sha256": parts["report_preview_sha256"],
        "provenance_bindings": [
            reporting_snapshot_provenance_binding_to_dict(item)
            for item in cast(
                tuple[ReportingSnapshotProvenanceBinding, ...],
                parts["provenance_bindings"],
            )
        ],
        "predecessor": (
            reporting_snapshot_predecessor_to_dict(
                cast(ReportingSnapshotPredecessor, parts["predecessor"])
            )
            if parts["predecessor"] is not None
            else None
        ),
        "created_at": cast(datetime, parts["created_at"]).isoformat(),
    }


def _snapshot_payload_sha256(value: ReportingSnapshot) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(_snapshot_payload_to_dict(value))
    ).hexdigest()


def _validate_build_request(
    value: ReportingSnapshotBuildRequest,
) -> ReportingSnapshotBuildRequest:
    if not isinstance(value, ReportingSnapshotBuildRequest):
        raise ReportingSnapshotRequestValidationError(
            "value must be ReportingSnapshotBuildRequest."
        )
    return ReportingSnapshotBuildRequest(
        schema_version=value.schema_version,
        definition_reference=value.definition_reference,
        grade_requests=value.grade_requests,
        actor=value.actor,
        rationale=value.rationale,
        requested_at=value.requested_at,
        predecessor=value.predecessor,
    )


def _validate_snapshot(value: ReportingSnapshot) -> ReportingSnapshot:
    if not isinstance(value, ReportingSnapshot):
        raise ReportingSnapshotIntegrityError(
            "value must be ReportingSnapshot."
        )
    value.__post_init__()
    return value


def _actor_to_dict(value: ReportingActor) -> dict[str, object]:
    return {"kind": value.kind, "actor_id": value.actor_id}


def _target_to_dict(value: GradePreviewTarget) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
    }


def _target_from_dict(data: object) -> GradePreviewTarget:
    mapping = _exact_mapping(data, _TARGET_KEYS, "Grade target")
    family = _require_str(mapping["calculation_family"], "calculation_family")
    if family not in {"conventional", "standards_based", "hybrid"}:
        raise ReportingSnapshotRequestValidationError(
            "unsupported Grade calculation family."
        )
    return GradePreviewTarget(
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        calculation_family=cast(
            Literal["conventional", "standards_based", "hybrid"],
            family,
        ),
    )


def _period_from_dict(data: object) -> AcademicPeriodRef:
    try:
        return academic_period_ref_from_dict(data)
    except (AcademicPeriodValidationError, TypeError, ValueError) as error:
        raise ReportingSnapshotIntegrityError(
            f"Academic Period reference is invalid: {error}"
        ) from error


def _projection_input_key(
    value: ReportingSnapshotProjectionInputReference,
) -> tuple[str, str, str]:
    return value.publication_id, value.cache_key, value.snapshot_digest


def _work_evidence_key(
    value: ReportingSnapshotWorkEvidenceRequest,
) -> tuple[str, str, str]:
    return value.grade_item_id, value.work.module_id, value.work.work_id


def _target_key(value: GradePreviewTarget) -> tuple[str, str, str, str, int, str]:
    return (
        value.class_id,
        value.student_id,
        value.target_period.school_year,
        value.target_period.period_id,
        value.calendar_revision,
        value.calculation_family,
    )


def _provenance_binding_key(
    value: ReportingSnapshotProvenanceBinding,
) -> tuple[str, str, str]:
    return value.authority_kind, value.reference_kind, value.reference_sha256


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
        raise ReportingSnapshotIntegrityError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportingSnapshotIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportingSnapshotError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportingSnapshotIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportingSnapshotIntegrityError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportingSnapshotIntegrityError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    mapping = _require_mapping(data, label)
    actual = frozenset(mapping.keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ReportingSnapshotIntegrityError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return mapping


def _require_mapping(data: object, label: str) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ReportingSnapshotIntegrityError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ReportingSnapshotIntegrityError(f"{label} keys must be strings.")
    return cast(Mapping[str, object], data)


def _json_mapping_from_canonical_bytes(data: bytes, label: str) -> dict[str, object]:
    decoded = _decode_json(data, label)
    mapping = _require_mapping(decoded, label)
    if _canonical_json_bytes(mapping) != data:
        # #54 report-preview bytes intentionally use a different canonical spacing.
        # They have already been strictly validated by Slice 2, so return the object.
        if label != "frozen report preview":
            raise ReportingSnapshotIntegrityError(
                f"{label} bytes are not canonical #55 JSON."
            )
    return dict(mapping)


def _request_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotRequestValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportingSnapshotRequestValidationError(str(error)) from error


def _request_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotRequestValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportingSnapshotValidationError(str(error)) from error


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotRequestValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise ReportingSnapshotRequestValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ReportingSnapshotRequestValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise ReportingSnapshotRequestValidationError(
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


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotIntegrityError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise ReportingSnapshotIntegrityError(
            f"{field_name} must be greater than zero."
        )
    return integer


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
        raise ReportingSnapshotIntegrityError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotIntegrityError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportingSnapshotIntegrityError(f"{field_name} must be an integer.")
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportingSnapshotIntegrityError(f"{field_name} must be a JSON array.")
    return cast(list[object], value)


def _typed_tuple(
    value: object,
    expected_type: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if not isinstance(value, tuple):
        raise ReportingSnapshotValidationError(
            f"{field_name} must be a tuple."
        )
    if any(not isinstance(item, expected_type) for item in value):
        raise ReportingSnapshotValidationError(
            f"{field_name} contains an invalid value."
        )
    return cast(tuple[_T, ...], value)


__all__ = [
    "DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_BYTES",
    "MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_BINDINGS",
    "MAXIMUM_REPORTING_SNAPSHOT_PROVENANCE_REFERENCE_BYTES",
    "MAXIMUM_REPORTING_SNAPSHOT_REQUEST_ROWS",
    "REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION",
    "REPORTING_SNAPSHOT_INTEGRITY_ALGORITHM",
    "REPORTING_SNAPSHOT_RECORD_TYPE",
    "REPORTING_SNAPSHOT_SCHEMA_VERSION",
    "ReportingSnapshot",
    "ReportingSnapshotBuildRequest",
    "ReportingSnapshotEvidenceStatus",
    "ReportingSnapshotGradeRequest",
    "ReportingSnapshotIntegrityError",
    "ReportingSnapshotProjectionInputReference",
    "ReportingSnapshotProvenanceAuthorityKind",
    "ReportingSnapshotProvenanceBinding",
    "ReportingSnapshotRequestValidationError",
    "ReportingSnapshotWorkEvidenceRequest",
    "compose_reporting_snapshot",
    "reporting_snapshot_build_request_from_dict",
    "reporting_snapshot_build_request_from_json_bytes",
    "reporting_snapshot_build_request_from_preview_requests",
    "reporting_snapshot_build_request_sha256",
    "reporting_snapshot_build_request_to_dict",
    "reporting_snapshot_build_request_to_json_bytes",
    "reporting_snapshot_from_dict",
    "reporting_snapshot_from_json_bytes",
    "reporting_snapshot_provenance_binding",
    "reporting_snapshot_provenance_binding_from_dict",
    "reporting_snapshot_provenance_binding_to_dict",
    "reporting_snapshot_reference",
    "reporting_snapshot_to_dict",
    "reporting_snapshot_to_json_bytes",
]
