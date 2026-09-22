"""High-level immutable ReportingSnapshot freeze workflow for Meridian v0.3.

Issue #55 Slice 6 composes the accepted #54 report-preview boundary with the
#55 immutable request, provenance, snapshot, and storage contracts.  The service
uses optimistic whole-report revalidation:

1. verify the exact immutable definition and Core Academic Period calendar;
2. build one #54 report from only the caller-supplied explicit requests;
3. freeze and bind its exact canonical bytes plus typed provenance;
4. rebuild the same report immediately before commit; and
5. commit only when the second canonical report is byte-identical.

No Grade calculation, policy selection, override selection, producer state, or
current ReportingSnapshot selection is mutated here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_academic_period_calendar_revision,
)
from pds_core.academic_periods import (
    AcademicPeriodCalendar,
    academic_period_calendar_to_dict,
)
from pds_core.publication_records import (
    publication_record_to_dict,
    publication_withdrawal_to_dict,
)
from pds_core.publication_storage import (
    PublicationManifestError,
    verify_publication_manifest,
)
from pds_core.routing_models import module_work_ref_to_dict

from meridian.grade_policy import grade_policy_reference_to_dict
from meridian.grade_policy_activation import grade_policy_activation_reference_to_dict
from meridian.grade_preview_explanation import (
    GradePreviewCurrentnessConflictError,
    GradePreviewError,
    GradePreviewObservation,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
    grade_report_preview_to_json_bytes,
)
from meridian.ingestion import (
    PublicationIngestionError,
    load_canonical_publication_context,
)
from meridian.projection_cache import (
    ProjectionCacheError,
    ProjectionSourceObservation,
    projection_cache_path,
    projection_snapshot_from_json_bytes,
)
from meridian.reporting_snapshot import ReportingSnapshotValidationError
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    ReportingSnapshotPreviewIntegrityError,
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshot,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotIntegrityError,
    ReportingSnapshotProvenanceAuthorityKind,
    ReportingSnapshotProvenanceBinding,
    ReportingSnapshotRequestValidationError,
    compose_reporting_snapshot,
    reporting_snapshot_build_request_from_preview_requests,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    StoredReportingSnapshot,
    load_reporting_definition_revision,
    write_reporting_snapshot,
)
from meridian.teacher_grade_override import (
    grade_override_source_result_reference_to_dict,
    teacher_grade_override_reference_to_dict,
)

_MAXIMUM_EXPLANATION_JSON_BYTES: Final[int] = 16 * 1024 * 1024


class ReportingSnapshotFreezeError(RuntimeError):
    """Base error for the high-level ReportingSnapshot freeze service."""

    code: str = "reporting_snapshot.freeze_failed"


class ReportingSnapshotFreezeValidationError(ReportingSnapshotFreezeError, ValueError):
    """Raised when the requested freeze operation is malformed."""

    code = "reporting_snapshot.freeze_invalid"


class ReportingSnapshotFreezeIntegrityError(ReportingSnapshotFreezeError):
    """Raised when exact reporting authority cannot be trusted."""

    code = "reporting_snapshot.freeze_integrity_failed"


class ReportingSnapshotCurrentnessConflictError(ReportingSnapshotFreezeError):
    """Raised when the whole report moves before immutable commit."""

    code = "reporting_snapshot.currentness_conflict"


def utc_now() -> datetime:
    """Return an aware UTC timestamp for default freeze metadata."""

    return datetime.now(UTC)


def freeze_reporting_snapshot(
    workspace_root: str | Path,
    *,
    snapshot_id: str,
    build_request: ReportingSnapshotBuildRequest,
    preview_requests: tuple[GradeReportPreviewRequest, ...],
    created_at: datetime | None = None,
) -> StoredReportingSnapshot:
    """Freeze one coherent exact #54 report into immutable #55 storage.

    ``build_request`` is the canonical data-only request retained by the
    snapshot. ``preview_requests`` carry the live authorized objects required by
    #54 to re-observe conventional/hybrid currentness.  Their normalized request
    identity must match exactly before any reporting work begins.
    """

    if not isinstance(build_request, ReportingSnapshotBuildRequest):
        raise ReportingSnapshotFreezeValidationError(
            "build_request must be ReportingSnapshotBuildRequest."
        )
    if not isinstance(preview_requests, tuple) or any(
        not isinstance(item, GradeReportPreviewRequest) for item in preview_requests
    ):
        raise ReportingSnapshotFreezeValidationError(
            "preview_requests must be a tuple of GradeReportPreviewRequest values."
        )

    root = Path(workspace_root)
    _require_matching_request(build_request, preview_requests)
    _verify_definition(root, build_request)
    calendar = _load_exact_calendar(root, build_request)
    _verify_live_publication_provenance(
        root,
        preview_requests,
        final=False,
    )

    initial_bytes = _observe_report_bytes(root, preview_requests, final=False)
    try:
        frozen = frozen_grade_report_preview_from_json_bytes(initial_bytes)
    except ReportingSnapshotPreviewIntegrityError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"Candidate Grade report cannot be frozen safely: {error}"
        ) from error

    bindings = extract_reporting_snapshot_provenance_bindings(
        build_request=build_request,
        report_preview=frozen,
        calendar=calendar,
        preview_requests=preview_requests,
    )
    candidate = _compose_candidate(
        snapshot_id=snapshot_id,
        build_request=build_request,
        report_preview=frozen,
        provenance_bindings=bindings,
        created_at=created_at,
    )

    # Revalidate every non-report dependency before the last #54 observation.
    # The final report bytes below are therefore the optimistic witness closest
    # to the only canonical write rather than being followed by additional
    # mutable academic-state reads.
    _verify_definition(root, build_request)
    _load_exact_calendar(root, build_request)
    _verify_live_publication_provenance(
        root,
        preview_requests,
        final=True,
    )
    final_bytes = _observe_report_bytes(root, preview_requests, final=True)
    if final_bytes != initial_bytes:
        raise ReportingSnapshotCurrentnessConflictError(
            "Reporting basis changed during whole-report snapshot generation."
        )

    try:
        result = write_reporting_snapshot(root, candidate)
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"ReportingSnapshot commit failed canonical verification: {error}"
        ) from error
    return result.stored


def extract_reporting_snapshot_provenance_bindings(
    *,
    build_request: ReportingSnapshotBuildRequest,
    report_preview: FrozenGradeReportPreview,
    calendar: AcademicPeriodCalendar,
    preview_requests: tuple[GradeReportPreviewRequest, ...] | None = None,
) -> tuple[ReportingSnapshotProvenanceBinding, ...]:
    """Project the frozen report into deterministic typed #55 provenance.

    Rich #54 explanation bytes have already passed the strict Slice 2 decoder.
    This projection deliberately preserves authority distinctions instead of
    treating the report digest as a substitute for exact provenance.
    """

    if not isinstance(build_request, ReportingSnapshotBuildRequest):
        raise ReportingSnapshotFreezeValidationError(
            "build_request must be ReportingSnapshotBuildRequest."
        )
    if not isinstance(report_preview, FrozenGradeReportPreview):
        raise ReportingSnapshotFreezeValidationError(
            "report_preview must be FrozenGradeReportPreview."
        )
    if not isinstance(calendar, AcademicPeriodCalendar):
        raise ReportingSnapshotFreezeValidationError(
            "calendar must be AcademicPeriodCalendar."
        )
    if (
        calendar.school_year != build_request.target_period.school_year
        or calendar.calendar_revision != build_request.calendar_revision
    ):
        raise ReportingSnapshotFreezeIntegrityError(
            "Academic Period calendar does not match exact build-request scope."
        )

    bindings: list[ReportingSnapshotProvenanceBinding] = []
    bindings.append(_calendar_binding(build_request, calendar))
    _append_request_publication_bindings(bindings, build_request)
    if preview_requests is not None:
        if not isinstance(preview_requests, tuple) or any(
            not isinstance(item, GradeReportPreviewRequest)
            for item in preview_requests
        ):
            raise ReportingSnapshotFreezeValidationError(
                "preview_requests must contain GradeReportPreviewRequest values."
            )
        _append_live_publication_bindings(bindings, preview_requests)

    for row in report_preview.rows:
        if row.status != "available":
            continue
        observation = row.observation
        if observation is None or row.explanation_json is None:
            raise ReportingSnapshotFreezeIntegrityError(
                "Available frozen row lost required observation/explanation state."
            )
        bindings.extend(_observation_bindings(observation))
        explanation = _json_mapping(
            row.explanation_json,
            "frozen Grade explanation",
        )
        bindings.extend(_rich_explanation_bindings(explanation))

    unique: dict[
        tuple[str, str, str], ReportingSnapshotProvenanceBinding
    ] = {}
    for binding in bindings:
        key = (
            binding.authority_kind,
            binding.reference_kind,
            binding.reference_sha256,
        )
        existing = unique.get(key)
        if existing is not None and existing.reference_json != binding.reference_json:
            raise ReportingSnapshotFreezeIntegrityError(
                "Conflicting provenance references share one canonical digest key."
            )
        unique[key] = binding
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.authority_kind,
                item.reference_kind,
                item.reference_sha256,
            ),
        )
    )


def _require_matching_request(
    build_request: ReportingSnapshotBuildRequest,
    preview_requests: tuple[GradeReportPreviewRequest, ...],
) -> None:
    try:
        normalized = reporting_snapshot_build_request_from_preview_requests(
            definition_reference=build_request.definition_reference,
            requests=preview_requests,
            actor=build_request.actor,
            requested_at=build_request.requested_at,
            rationale=build_request.rationale,
            predecessor=build_request.predecessor,
        )
    except (
        ReportingSnapshotRequestValidationError,
        ReportingSnapshotValidationError,
    ) as error:
        raise ReportingSnapshotFreezeValidationError(
            f"preview requests cannot reproduce the canonical build request: {error}"
        ) from error
    if normalized != build_request:
        raise ReportingSnapshotFreezeValidationError(
            "preview_requests do not match the exact canonical build_request."
        )


def _verify_definition(
    root: Path,
    build_request: ReportingSnapshotBuildRequest,
) -> None:
    reference = build_request.definition_reference
    try:
        stored = load_reporting_definition_revision(
            root,
            reference.class_id,
            reference.definition_id,
            reference.definition_revision,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            "Exact reporting definition required by freeze is unavailable."
        ) from error
    if stored.reference != reference:
        raise ReportingSnapshotFreezeIntegrityError(
            "Build-request definition reference does not match stored exact revision."
        )


def _load_exact_calendar(
    root: Path,
    build_request: ReportingSnapshotBuildRequest,
) -> AcademicPeriodCalendar:
    period = build_request.target_period
    try:
        calendar = load_academic_period_calendar_revision(
            root,
            period.school_year,
            build_request.calendar_revision,
        )
    except AcademicPeriodCalendarStorageError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            "Exact Core Academic Period calendar revision is unavailable."
        ) from error
    if not any(item.period_id == period.period_id for item in calendar.periods):
        raise ReportingSnapshotFreezeIntegrityError(
            "Requested Academic Period is absent from the exact calendar revision."
        )
    return calendar


def _verify_live_publication_provenance(
    root: Path,
    requests: tuple[GradeReportPreviewRequest, ...],
    *,
    final: bool,
) -> None:
    """Revalidate exact authorized projection/Core state without reauthorizing.

    Authorization itself remains the caller/deployment responsibility.  This
    guard proves that the already-authorized object still names the same exact
    cache bytes and canonical Core publication state at freeze time.
    """

    for request in requests:
        evidence = request.work_evidence
        if evidence is None:
            continue
        for work_spec in evidence:
            for authorized in work_spec.authorized_snapshots:
                stored = authorized.stored
                source = stored.snapshot.source
                publication_id = source.publication.publication_id
                expected_path = projection_cache_path(
                    root,
                    publication_id,
                    stored.cache_key,
                    stored.snapshot_digest,
                )
                if stored.path != expected_path:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Authorized projection path does not match canonical cache "
                        "identity."
                    )
                if expected_path.is_symlink() or not expected_path.is_file():
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache file is missing or unsafe."
                    )
                try:
                    content = expected_path.read_bytes()
                except OSError as error:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache bytes cannot be read."
                    ) from error
                if content != stored.content:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache bytes changed after "
                        "authorization."
                    )
                if hashlib.sha256(content).hexdigest() != stored.snapshot_digest:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache digest no longer matches."
                    )
                try:
                    decoded = projection_snapshot_from_json_bytes(content)
                except ProjectionCacheError as error:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache is invalid."
                    ) from error
                if decoded != stored.snapshot:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact authorized projection cache no longer decodes to the "
                        "authorized snapshot."
                    )

                try:
                    current_context = load_canonical_publication_context(
                        root,
                        publication_id,
                    )
                    verify_publication_manifest(root, current_context.publication)
                except (PublicationIngestionError, PublicationManifestError) as error:
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Exact Core publication provenance cannot be verified."
                    ) from error

                expected_source = ProjectionSourceObservation.from_context(
                    current_context
                )
                moved = (
                    current_context != authorized.current_context
                    or expected_source != source
                    or not authorized.assessment.reusable_for_current_use
                )
                if moved:
                    if final:
                        raise ReportingSnapshotCurrentnessConflictError(
                            "Core publication/projection authority changed during "
                            "ReportingSnapshot generation."
                        )
                    raise ReportingSnapshotFreezeIntegrityError(
                        "Authorized Core publication/projection authority is not "
                        "current for snapshot generation."
                    )


def _observe_report_bytes(
    root: Path,
    requests: tuple[GradeReportPreviewRequest, ...],
    *,
    final: bool,
) -> bytes:
    try:
        preview = explain_grade_report_preview(root, requests)
        return grade_report_preview_to_json_bytes(preview)
    except GradePreviewCurrentnessConflictError as error:
        if final:
            raise ReportingSnapshotCurrentnessConflictError(
                "Grade-report authority changed during final re-observation."
            ) from error
        raise ReportingSnapshotFreezeIntegrityError(
            f"Initial Grade report was not coherently observable: {error}"
        ) from error
    except GradePreviewError as error:
        if final:
            raise ReportingSnapshotCurrentnessConflictError(
                "Grade-report authority changed before immutable commit."
            ) from error
        raise ReportingSnapshotFreezeIntegrityError(
            f"Initial Grade report could not be resolved safely: {error}"
        ) from error
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotFreezeValidationError(
            f"Grade-report request is invalid: {error}"
        ) from error


def _compose_candidate(
    *,
    snapshot_id: str,
    build_request: ReportingSnapshotBuildRequest,
    report_preview: FrozenGradeReportPreview,
    provenance_bindings: tuple[ReportingSnapshotProvenanceBinding, ...],
    created_at: datetime | None,
) -> ReportingSnapshot:
    timestamp = utc_now() if created_at is None else created_at
    try:
        return compose_reporting_snapshot(
            snapshot_id=snapshot_id,
            build_request=build_request,
            report_preview=report_preview,
            provenance_bindings=provenance_bindings,
            created_at=timestamp,
        )
    except (
        ReportingSnapshotIntegrityError,
        ReportingSnapshotRequestValidationError,
        ReportingSnapshotValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise ReportingSnapshotFreezeValidationError(
            f"ReportingSnapshot candidate is invalid: {error}"
        ) from error


def _calendar_binding(
    request: ReportingSnapshotBuildRequest,
    calendar: AcademicPeriodCalendar,
) -> ReportingSnapshotProvenanceBinding:
    calendar_bytes = (
        json.dumps(
            academic_period_calendar_to_dict(calendar),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    reference = {
        "school_year": calendar.school_year,
        "calendar_revision": calendar.calendar_revision,
        "period_id": request.target_period.period_id,
        "calendar_sha256": hashlib.sha256(calendar_bytes).hexdigest(),
    }
    return reporting_snapshot_provenance_binding(
        authority_kind="academic_period_calendar",
        reference_kind="core_academic_period_calendar",
        reference=reference,
    )


def _append_request_publication_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    request: ReportingSnapshotBuildRequest,
) -> None:
    for grade_request in request.grade_requests:
        if grade_request.work_evidence is None:
            continue
        for evidence in grade_request.work_evidence:
            work = module_work_ref_to_dict(evidence.work)
            for projection in evidence.projection_snapshots:
                output.append(
                    _binding(
                        "core_publication",
                        "authorized_projection_source",
                        {
                            "grade_item_id": evidence.grade_item_id,
                            "work": work,
                            "publication_id": projection.publication_id,
                            "cache_key": projection.cache_key,
                            "snapshot_digest": projection.snapshot_digest,
                        },
                    )
                )


def _append_live_publication_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    requests: tuple[GradeReportPreviewRequest, ...],
) -> None:
    """Bind exact Core Publication Records and observed series state.

    The normalized build request retains privacy-minimized projection identity.
    The live #54 request also carries the authorized stored projection object,
    whose digest already identifies the exact cached projection bytes.  Preserve
    its Core-owned source record and the publication-series state Meridian
    actually observed without opening producer-private storage.
    """

    for request in requests:
        evidence = request.work_evidence
        if evidence is None:
            continue
        for work_spec in evidence:
            for authorized in work_spec.authorized_snapshots:
                stored = authorized.stored
                source = stored.snapshot.source
                publication = publication_record_to_dict(source.publication)
                output.append(
                    _binding(
                        "core_publication",
                        "core_publication_record",
                        {
                            "publication": publication,
                            "projection_cache_key": stored.cache_key,
                            "projection_snapshot_sha256": stored.snapshot_digest,
                        },
                    )
                )
                withdrawal = (
                    publication_withdrawal_to_dict(source.withdrawal)
                    if source.withdrawal is not None
                    else None
                )
                assessment = authorized.assessment
                output.append(
                    _binding(
                        "core_publication_state",
                        "core_publication_observation",
                        {
                            "publication_id": source.publication.publication_id,
                            "series_publication_ids": list(
                                source.series_publication_ids
                            ),
                            "target_index": source.target_index,
                            "observed_head_publication_id": (
                                source.head_publication_id
                            ),
                            "observed_successor_publication_id": (
                                source.successor_publication_id
                            ),
                            "observed_canonical_state": source.canonical_state,
                            "withdrawal": withdrawal,
                            "source_status": assessment.source_status,
                            "reuse_status": assessment.reuse_status,
                            "reason_codes": list(assessment.reason_codes),
                            "current_canonical_state": (
                                assessment.current_canonical_state
                            ),
                            "current_head_publication_id": (
                                assessment.current_head_publication_id
                            ),
                            "observed_current_registration_revision": (
                                assessment.observed_current_registration_revision
                            ),
                            "current_registration_revision": (
                                assessment.current_registration_revision
                            ),
                        },
                    )
                )


def _observation_bindings(
    observation: GradePreviewObservation,
) -> tuple[ReportingSnapshotProvenanceBinding, ...]:
    result = [
        _binding(
            "grade_result",
            "selected_grade_result",
            grade_override_source_result_reference_to_dict(
                observation.base_result_reference
            ),
        ),
        _binding(
            "grade_policy_activation",
            "grade_policy_activation",
            grade_policy_activation_reference_to_dict(
                observation.activation_reference
            ),
        ),
        _binding(
            "grade_policy_revision",
            "grade_policy_revision",
            grade_policy_reference_to_dict(observation.policy_reference),
        ),
    ]
    if observation.selected_override_reference is not None:
        result.append(
            _binding(
                "teacher_grade_override",
                "teacher_grade_override",
                teacher_grade_override_reference_to_dict(
                    observation.selected_override_reference
                ),
            )
        )
    return tuple(result)


def _rich_explanation_bindings(
    explanation: Mapping[str, object],
) -> tuple[ReportingSnapshotProvenanceBinding, ...]:
    result: list[ReportingSnapshotProvenanceBinding] = []
    if "items" in explanation and "mode" in explanation:
        _append_conventional_bindings(result, explanation)
    if "standards" in explanation and "target_scale" in explanation:
        _append_standards_bindings(result, explanation)
    if "conventional_component" in explanation and "standards_component" in explanation:
        conventional = _mapping(
            explanation["conventional_component"],
            "conventional component",
        )
        standards = _mapping(explanation["standards_component"], "standards component")
        _append_conventional_bindings(
            result,
            _mapping(conventional["breakdown"], "conventional breakdown"),
        )
        _append_standards_bindings(
            result,
            _mapping(standards["breakdown"], "standards breakdown"),
        )
    return tuple(result)


def _append_conventional_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    detail: Mapping[str, object],
) -> None:
    for raw_item in _list(detail.get("items"), "conventional items"):
        item = _mapping(raw_item, "conventional item")
        grade_item = _mapping(item["grade_item"], "conventional grade_item")
        reference = _mapping(grade_item["reference"], "Grade Item reference")
        output.append(_binding("grade_item_revision", "grade_item_revision", reference))
        for raw_provenance in _list(item["provenance"], "conventional provenance"):
            provenance = _mapping(raw_provenance, "conventional provenance entry")
            kind = _string(provenance["kind"], "provenance.kind")
            authority = _conventional_authority(kind)
            output.append(
                _binding(
                    authority,
                    f"conventional_{kind}_provenance",
                    {
                        "grade_item": dict(reference),
                        "reference_key": _string(
                            provenance["reference_key"], "reference_key"
                        ),
                        "reference_sha256": _string(
                            provenance["reference_sha256"], "reference_sha256"
                        ),
                    },
                )
            )


def _append_standards_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    detail: Mapping[str, object],
) -> None:
    target_scale = detail.get("target_scale")
    if target_scale is not None:
        output.append(
            _binding(
                "proficiency_mapping",
                "proficiency_scale",
                _mapping(target_scale, "target scale"),
            )
        )
    for raw_standard in _list(detail.get("standards"), "standards"):
        standard = _mapping(raw_standard, "standards explanation entry")
        reference = standard.get("result_reference")
        if reference is not None:
            output.append(
                _binding(
                    "academic_period_proficiency_result",
                    "academic_period_proficiency_result",
                    _mapping(reference, "Academic Period proficiency reference"),
                )
            )
        scale = standard.get("target_scale")
        if scale is not None:
            output.append(
                _binding(
                    "proficiency_mapping",
                    "proficiency_scale",
                    _mapping(scale, "standard target scale"),
                )
            )
        nested = standard.get("nested_proficiency_explanation")
        if nested is not None:
            _append_academic_period_proficiency_bindings(
                output,
                _mapping(nested, "nested Academic Period proficiency explanation"),
            )


def _append_academic_period_proficiency_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    nested: Mapping[str, object],
) -> None:
    scale = nested.get("scale")
    target = _mapping(nested.get("target"), "Academic Period proficiency target")
    if scale is not None:
        scale_mapping = _mapping(scale, "Academic Period proficiency scale")
        output.append(
            _binding(
                "proficiency_mapping",
                "proficiency_scale",
                _reference_subset(
                    scale_mapping,
                    ("scale_id", "scale_revision", "scale_sha256"),
                    class_id=_string(target["class_id"], "target.class_id"),
                ),
            )
        )
    for raw_item in _list(nested.get("grade_items"), "Academic Period grade_items"):
        item = _mapping(raw_item, "Academic Period Grade Item explanation")
        grade_item = _mapping(item["grade_item"], "Academic Period Grade Item")
        output.append(
            _binding(
                "grade_item_revision",
                "grade_item_revision",
                _reference_subset(
                    grade_item,
                    (
                        "class_id",
                        "grade_item_id",
                        "grade_item_revision",
                        "grade_item_revision_sha256",
                    ),
                ),
            )
        )
        for raw_membership in _list(item["memberships"], "Grade Item memberships"):
            membership = _mapping(raw_membership, "Grade Item membership")
            output.append(
                _binding(
                    "grade_item_membership",
                    "grade_item_membership",
                    membership,
                )
            )
        result_reference = item.get("result_reference")
        if result_reference is not None:
            output.append(
                _binding(
                    "grade_item_proficiency_result",
                    "grade_item_proficiency_result",
                    _mapping(result_reference, "Grade Item proficiency reference"),
                )
            )
        nested_item = item.get("nested_grade_item_explanation")
        if nested_item is not None:
            _append_grade_item_proficiency_bindings(
                output,
                _mapping(nested_item, "nested Grade Item proficiency explanation"),
            )


def _append_grade_item_proficiency_bindings(
    output: list[ReportingSnapshotProvenanceBinding],
    nested: Mapping[str, object],
) -> None:
    grade_item = _mapping(nested.get("grade_item"), "Grade Item proficiency grade_item")
    output.append(
        _binding(
            "grade_item_revision",
            "grade_item_revision",
            _reference_subset(
                grade_item,
                (
                    "class_id",
                    "grade_item_id",
                    "grade_item_revision",
                    "grade_item_revision_sha256",
                ),
            ),
        )
    )
    target = _mapping(nested.get("target"), "Grade Item proficiency target")
    scale = _mapping(nested.get("scale"), "Grade Item proficiency scale")
    output.append(
        _binding(
            "proficiency_mapping",
            "proficiency_scale",
            _reference_subset(
                scale,
                ("scale_id", "scale_revision", "scale_sha256"),
                class_id=_string(target["class_id"], "target.class_id"),
            ),
        )
    )
    output.append(
        _binding(
            "grade_item_proficiency_result",
            "grade_item_proficiency_result",
            _reference_subset(
                target,
                (
                    "class_id",
                    "grade_item_id",
                    "student_id",
                    "standard_id",
                    "result_revision",
                    "result_sha256",
                ),
            ),
        )
    )
    for raw_evidence in _list(
        nested.get("evidence"),
        "Grade Item proficiency evidence",
    ):
        evidence = _mapping(raw_evidence, "Grade Item proficiency evidence entry")
        source = _mapping(evidence["source"], "evidence source")
        output.append(_binding("evidence_source", "evidence_source", source))
        core_reference = _core_publication_from_source(source)
        if core_reference is not None:
            output.append(
                _binding(
                    "core_publication",
                    "evidence_source_publication",
                    core_reference,
                )
            )
        for raw_stage in _list(evidence["stages"], "provenance stages"):
            stage = _mapping(raw_stage, "provenance stage")
            if stage.get("status") != "verified":
                continue
            revision = stage.get("revision")
            sha256 = stage.get("sha256")
            if revision is None or sha256 is None:
                raise ReportingSnapshotFreezeIntegrityError(
                    "Verified provenance stage lacks exact revision/digest identity."
                )
            name = _string(stage["name"], "stage.name")
            authority = _stage_authority(name)
            output.append(
                _binding(
                    authority,
                    f"proficiency_{name}",
                    {
                        "source": dict(source),
                        "revision": revision,
                        "sha256": _string(sha256, "stage.sha256"),
                        "details": dict(_mapping(stage["details"], "stage.details")),
                    },
                )
            )


def _core_publication_from_source(
    source: Mapping[str, object],
) -> dict[str, object] | None:
    required = ("work", "publication_id", "cache_key", "snapshot_digest")
    if any(key not in source for key in required):
        return None
    return {key: source[key] for key in required}


def _conventional_authority(kind: str) -> ReportingSnapshotProvenanceAuthorityKind:
    mapping: dict[str, ReportingSnapshotProvenanceAuthorityKind] = {
        "source": "evidence_source",
        "membership": "grade_item_membership",
        "eligibility": "evidence_eligibility",
        "attempt_selection": "attempt_selection",
        "reassessment": "reassessment",
    }
    try:
        return mapping[kind]
    except KeyError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"Unsupported conventional provenance kind: {kind}."
        ) from error


def _stage_authority(name: str) -> ReportingSnapshotProvenanceAuthorityKind:
    mapping: dict[str, ReportingSnapshotProvenanceAuthorityKind] = {
        "membership": "grade_item_membership",
        "eligibility": "evidence_eligibility",
        "attempt_selection": "attempt_selection",
        "reassessment": "reassessment",
        "standard_association": "evidence_source",
        "mapping_profile": "proficiency_mapping",
    }
    try:
        return mapping[name]
    except KeyError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"Unsupported proficiency provenance stage: {name}."
        ) from error


def _binding(
    authority_kind: ReportingSnapshotProvenanceAuthorityKind,
    reference_kind: str,
    reference: Mapping[str, object],
) -> ReportingSnapshotProvenanceBinding:
    try:
        return reporting_snapshot_provenance_binding(
            authority_kind=authority_kind,
            reference_kind=reference_kind,
            reference=reference,
        )
    except ReportingSnapshotIntegrityError as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"Could not bind exact {authority_kind} provenance: {error}"
        ) from error


def _reference_subset(
    mapping: Mapping[str, object],
    keys: tuple[str, ...],
    **extra: object,
) -> dict[str, object]:
    missing = tuple(key for key in keys if key not in mapping)
    if missing:
        raise ReportingSnapshotFreezeIntegrityError(
            "Provenance reference is missing required fields: " + ", ".join(missing)
        )
    result = {key: mapping[key] for key in keys}
    result.update(extra)
    return result


def _json_mapping(data: bytes, label: str) -> Mapping[str, object]:
    if type(data) is not bytes or not data:
        raise ReportingSnapshotFreezeIntegrityError(
            f"{label} must be nonempty immutable bytes."
        )
    if len(data) > _MAXIMUM_EXPLANATION_JSON_BYTES:
        raise ReportingSnapshotFreezeIntegrityError(
            f"{label} exceeds the configured maximum byte size."
        )
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ReportingSnapshotFreezeIntegrityError(
            f"{label} is not valid canonical JSON."
        ) from error
    return _mapping(decoded, label)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ReportingSnapshotFreezeIntegrityError(f"{label} must be an object.")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportingSnapshotFreezeIntegrityError(f"{label} must be a list.")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReportingSnapshotFreezeIntegrityError(
            f"{label} must be nonempty text."
        )
    return value
