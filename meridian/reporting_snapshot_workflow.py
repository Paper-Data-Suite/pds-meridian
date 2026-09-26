"""Shared ReportingSnapshot freeze application workflow for Meridian."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.diagnostics import (
    DiagnosticsDependencies,
    default_diagnostics_dependencies,
)
from meridian.grade_preview_explanation import GradePreviewError
from meridian.grade_report_preview import (
    GradeReportPreview,
    GradeReportPreviewRequest,
    explain_grade_report_preview,
    grade_report_preview_to_json_bytes,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheError,
    load_authorized_projection_snapshot,
)
from meridian.reporting_snapshot_freeze import (
    ReportingSnapshotFreezeError,
    freeze_reporting_snapshot,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotRequestValidationError,
    reporting_snapshot_build_request_from_json_bytes,
    reporting_snapshot_build_request_from_preview_requests,
    reporting_snapshot_build_request_sha256,
)
from meridian.reporting_snapshot_storage import StoredReportingSnapshot

MAXIMUM_BUILD_REQUEST_BYTES = 2 * 1024 * 1024


class ReportingSnapshotWorkflowError(RuntimeError):
    """Base teacher/CLI application-workflow failure."""


class ReportingSnapshotWorkflowInputError(ReportingSnapshotWorkflowError):
    """Raised when bounded explicit freeze input is invalid."""


class ReportingSnapshotWorkflowAuthorizationError(ReportingSnapshotWorkflowError):
    """Raised when protected evidence cannot be explicitly authorized."""


class ReportingSnapshotWorkflowSourceError(ReportingSnapshotWorkflowError):
    """Raised when an exact requested projection cannot be materialized."""


class ReportingSnapshotWorkflowStaleError(ReportingSnapshotWorkflowError):
    """Raised when the reviewed live report changes before freeze commit."""


@dataclass(frozen=True, slots=True)
class ReportingSnapshotProjectionAuthorization:
    """Explicit caller-provided authorization for one exact projection request."""

    publication_id: str
    cache_key: str
    purpose_id: str
    student_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.publication_id:
            raise ReportingSnapshotWorkflowInputError(
                "projection publication_id must be nonblank."
            )
        if len(self.cache_key) != 64:
            raise ReportingSnapshotWorkflowInputError(
                "projection cache_key must be a 64-character digest."
            )
        if not self.purpose_id:
            raise ReportingSnapshotWorkflowInputError(
                "projection purpose_id must be nonblank."
            )
        students = tuple(self.student_ids)
        if any(not value for value in students):
            raise ReportingSnapshotWorkflowInputError(
                "projection student IDs must be nonblank."
            )
        if len(set(students)) != len(students):
            raise ReportingSnapshotWorkflowInputError(
                "projection student IDs must not contain duplicates."
            )
        object.__setattr__(self, "student_ids", tuple(sorted(students)))

    @property
    def key(self) -> tuple[str, str]:
        return (self.publication_id, self.cache_key)


@dataclass(frozen=True, slots=True)
class ReportingSnapshotFreezePreview:
    """Exact reviewed live report plus authorization inputs for final freeze."""

    snapshot_id: str
    build_request: ReportingSnapshotBuildRequest = field(repr=False)
    build_request_sha256: str
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...]
    live_report: GradeReportPreview = field(repr=False)
    live_report_sha256: str
    row_count: int
    created_at: datetime | None

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ReportingSnapshotWorkflowInputError(
                "snapshot_id must be nonblank."
            )
        if len(self.build_request_sha256) != 64:
            raise ReportingSnapshotWorkflowInputError(
                "build_request_sha256 must be a digest."
            )
        if len(self.live_report_sha256) != 64:
            raise ReportingSnapshotWorkflowInputError(
                "live_report_sha256 must be a digest."
            )
        if self.row_count != len(self.live_report.rows):
            raise ReportingSnapshotWorkflowInputError(
                "row_count must match the reviewed live report."
            )
        authorizations = tuple(self.authorizations)
        keys = tuple(item.key for item in authorizations)
        if len(set(keys)) != len(keys):
            raise ReportingSnapshotWorkflowInputError(
                "projection authorizations must not duplicate request identity."
            )
        object.__setattr__(
            self,
            "authorizations",
            tuple(sorted(authorizations, key=lambda item: item.key)),
        )


def load_reporting_snapshot_build_request_file(
    path: Path,
) -> ReportingSnapshotBuildRequest:
    """Load one bounded canonical build-request JSON file."""

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ReportingSnapshotWorkflowInputError(
            "Build-request JSON file cannot be resolved."
        ) from error
    if path.is_symlink() or not resolved.is_file():
        raise ReportingSnapshotWorkflowInputError(
            "Build-request JSON must be one regular non-symlink file."
        )
    try:
        size = resolved.stat().st_size
    except OSError as error:
        raise ReportingSnapshotWorkflowInputError(
            "Build-request JSON size cannot be inspected."
        ) from error
    if size > MAXIMUM_BUILD_REQUEST_BYTES:
        raise ReportingSnapshotWorkflowInputError(
            "Build-request JSON exceeds the bounded input limit."
        )
    try:
        data = resolved.read_bytes()
        return reporting_snapshot_build_request_from_json_bytes(data)
    except (OSError, ReportingSnapshotRequestValidationError) as error:
        raise ReportingSnapshotWorkflowInputError(
            f"Build-request JSON is invalid: {error}"
        ) from error


def required_projection_authorizations(
    build_request: ReportingSnapshotBuildRequest,
) -> tuple[ReportingSnapshotProjectionInputReference, ...]:
    """Return each exact protected projection identity once, deterministically."""

    values: dict[
        tuple[str, str],
        ReportingSnapshotProjectionInputReference,
    ] = {}
    for grade_request in build_request.grade_requests:
        evidence = grade_request.work_evidence
        if evidence is None:
            continue
        for item in evidence:
            for reference in item.projection_snapshots:
                key = (reference.publication_id, reference.cache_key)
                prior = values.get(key)
                if prior is not None and prior.snapshot_digest != (
                    reference.snapshot_digest
                ):
                    raise ReportingSnapshotWorkflowInputError(
                        "Build request reuses publication/cache identity with "
                        "different projection digests."
                    )
                values[key] = reference
    return tuple(values[key] for key in sorted(values))


def _effective_dependencies(
    supplied: DiagnosticsDependencies | None,
) -> DiagnosticsDependencies:
    return supplied if supplied is not None else default_diagnostics_dependencies()


def _authorization_map(
    build_request: ReportingSnapshotBuildRequest,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...],
) -> dict[tuple[str, str], ReportingSnapshotProjectionAuthorization]:
    values = tuple(authorizations)
    if any(
        not isinstance(item, ReportingSnapshotProjectionAuthorization)
        for item in values
    ):
        raise ReportingSnapshotWorkflowInputError(
            "authorizations must contain projection authorization values."
        )
    mapping = {item.key: item for item in values}
    if len(mapping) != len(values):
        raise ReportingSnapshotWorkflowInputError(
            "projection authorizations must not duplicate request identity."
        )
    required = {
        (item.publication_id, item.cache_key)
        for item in required_projection_authorizations(build_request)
    }
    supplied = set(mapping)
    missing = sorted(required - supplied)
    extra = sorted(supplied - required)
    if missing:
        raise ReportingSnapshotWorkflowAuthorizationError(
            "One or more build-request projections are missing explicit "
            "authorization."
        )
    if extra:
        raise ReportingSnapshotWorkflowInputError(
            "One or more projection authorizations are not used by the "
            "build request."
        )
    return mapping


def _load_projection(
    root: Path,
    reference: ReportingSnapshotProjectionInputReference,
    authorization: ReportingSnapshotProjectionAuthorization,
    dependencies: DiagnosticsDependencies,
) -> AuthorizedProjectionSnapshot:
    authorizer = dependencies.authorizer
    if authorizer is None:
        raise ReportingSnapshotWorkflowAuthorizationError(
            "Live reporting projection access requires a deployment authorizer."
        )
    registry = dependencies.producer_registry
    if (
        dependencies.producer_registry_state != "available"
        or registry is None
    ):
        raise ReportingSnapshotWorkflowSourceError(
            "Live reporting projection access requires an available "
            "producer registry."
        )
    try:
        authorized = load_authorized_projection_snapshot(
            root,
            reference.publication_id,
            reference.cache_key,
            authorizer=authorizer,
            authorization_purpose_id=authorization.purpose_id,
            requested_student_ids=authorization.student_ids,
            producer_registry=registry,
            adapter_registry=dependencies.adapter_registry,
            distribution_version_resolver=(
                dependencies.distribution_version_resolver
            ),
        )
    except ProjectionCacheError as error:
        raise ReportingSnapshotWorkflowSourceError(
            f"Exact reporting projection could not be authorized: {error}"
        ) from error
    if authorized.stored.snapshot_digest != reference.snapshot_digest:
        raise ReportingSnapshotWorkflowSourceError(
            "Authorized projection digest does not match build-request identity."
        )
    return authorized


def _materialize_preview_requests(
    root: Path,
    build_request: ReportingSnapshotBuildRequest,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...],
    dependencies: DiagnosticsDependencies | None,
) -> tuple[GradeReportPreviewRequest, ...]:
    mapping = _authorization_map(build_request, authorizations)
    effective = _effective_dependencies(dependencies)
    requests: list[GradeReportPreviewRequest] = []
    for grade_request in build_request.grade_requests:
        evidence = grade_request.work_evidence
        work_specs: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None
        if evidence is None:
            work_specs = None
        else:
            specs: list[ConventionalGradeWorkEvidenceSpec] = []
            for item in evidence:
                snapshots = tuple(
                    _load_projection(
                        root,
                        reference,
                        mapping[(reference.publication_id, reference.cache_key)],
                        effective,
                    )
                    for reference in item.projection_snapshots
                )
                specs.append(
                    ConventionalGradeWorkEvidenceSpec(
                        grade_item_id=item.grade_item_id,
                        work=item.work,
                        status=item.status,
                        authorized_snapshots=snapshots,
                    )
                )
            work_specs = tuple(specs)
        requests.append(
            GradeReportPreviewRequest(
                target=grade_request.target,
                work_evidence=work_specs,
            )
        )
    result = tuple(requests)
    normalized = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=build_request.definition_reference,
        requests=result,
        actor=build_request.actor,
        requested_at=build_request.requested_at,
        rationale=build_request.rationale,
        predecessor=build_request.predecessor,
    )
    if normalized != build_request:
        raise ReportingSnapshotWorkflowInputError(
            "Authorized live requests do not reproduce the exact build request."
        )
    return result


def prepare_reporting_snapshot_freeze(
    workspace_root: str | Path,
    *,
    snapshot_id: str,
    build_request: ReportingSnapshotBuildRequest,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...] = (),
    created_at: datetime | None = None,
    dependencies: DiagnosticsDependencies | None = None,
) -> ReportingSnapshotFreezePreview:
    """Prepare the exact live report a teacher/CLI will review before freeze."""

    root = Path(workspace_root)
    requests = _materialize_preview_requests(
        root,
        build_request,
        authorizations,
        dependencies,
    )
    try:
        report = explain_grade_report_preview(root, requests)
    except GradePreviewError as error:
        raise ReportingSnapshotWorkflowSourceError(
            f"Live Grade report cannot be previewed safely: {error}"
        ) from error
    report_bytes = grade_report_preview_to_json_bytes(report)
    return ReportingSnapshotFreezePreview(
        snapshot_id=snapshot_id,
        build_request=build_request,
        build_request_sha256=reporting_snapshot_build_request_sha256(
            build_request
        ),
        authorizations=authorizations,
        live_report=report,
        live_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        row_count=len(report.rows),
        created_at=created_at,
    )


def commit_reporting_snapshot_freeze_preview(
    workspace_root: str | Path,
    preview: ReportingSnapshotFreezePreview,
    *,
    dependencies: DiagnosticsDependencies | None = None,
) -> StoredReportingSnapshot:
    """Reauthorize/reobserve the reviewed report, then invoke canonical freeze."""

    if not isinstance(preview, ReportingSnapshotFreezePreview):
        raise ReportingSnapshotWorkflowInputError(
            "preview must be ReportingSnapshotFreezePreview."
        )
    root = Path(workspace_root)
    requests = _materialize_preview_requests(
        root,
        preview.build_request,
        preview.authorizations,
        dependencies,
    )
    try:
        current_report = explain_grade_report_preview(root, requests)
    except GradePreviewError as error:
        raise ReportingSnapshotWorkflowSourceError(
            f"Live Grade report cannot be revalidated safely: {error}"
        ) from error
    current_bytes = grade_report_preview_to_json_bytes(current_report)
    current_digest = hashlib.sha256(current_bytes).hexdigest()
    if current_digest != preview.live_report_sha256:
        raise ReportingSnapshotWorkflowStaleError(
            "Live Grade report changed after the freeze preview."
        )
    try:
        return freeze_reporting_snapshot(
            root,
            snapshot_id=preview.snapshot_id,
            build_request=preview.build_request,
            preview_requests=requests,
            created_at=preview.created_at,
        )
    except ReportingSnapshotFreezeError as error:
        raise ReportingSnapshotWorkflowError(
            f"ReportingSnapshot freeze failed safely: {error}"
        ) from error
