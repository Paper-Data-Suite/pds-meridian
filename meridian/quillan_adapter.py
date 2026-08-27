"""Exact Quillan v0.10.0 academic-result evidence projection."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Final

from pds_core.publication_records import PublicationCapability

from meridian.adapters import (
    AdapterDescriptor,
    AdapterKey,
    AdapterProjectionError,
    AdapterProjectionRequest,
    ProducerAdapter,
    projection_identity_from_descriptor,
)
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    EvidenceTargetIdentity,
    NativeArtifact,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    NativeTimestamp,
    StudentSubject,
)

if TYPE_CHECKING:
    from quillan.academic_result_manifest import (
        AcademicResultManifest,
        ReviewUnit,
        StandardObservation,
        StudentResult,
    )

__all__ = [
    "QUILLAN_ADAPTER_DESCRIPTOR",
    "QUILLAN_ADAPTER_ID",
    "QUILLAN_ADAPTER_KEY",
    "QUILLAN_PROJECTION_CONTRACT_VERSION",
    "QUILLAN_READER_DISTRIBUTION",
    "QUILLAN_READER_VERSION",
    "QuillanAcademicResultAdapter",
]

QUILLAN_ADAPTER_ID: Final = "quillan.academic_result"
QUILLAN_PROJECTION_CONTRACT_VERSION: Final = "1"
QUILLAN_READER_DISTRIBUTION: Final = "quillan"
QUILLAN_READER_VERSION: Final = "0.10.0"
_QUILLAN_RECORD_SET_ID: Final = "academic_results"
_QUILLAN_CAPABILITIES: Final[frozenset[PublicationCapability]] = frozenset(
    {"standards_ratings"}
)

QUILLAN_ADAPTER_KEY: Final = AdapterKey(
    producer_module_id="quillan",
    publication_kind="academic_result_set",
    manifest_contract_version="quillan_academic_result_manifest_v1",
    producer_contract_version="quillan_academic_work_v1",
    source_record_kind=None,
    source_record_contract_version=None,
)
QUILLAN_ADAPTER_DESCRIPTOR: Final = AdapterDescriptor(
    adapter_id=QUILLAN_ADAPTER_ID,
    key=QUILLAN_ADAPTER_KEY,
    projection_contract_version=QUILLAN_PROJECTION_CONTRACT_VERSION,
    supported_capabilities=_QUILLAN_CAPABILITIES,
    producer_reader_distribution=QUILLAN_READER_DISTRIBUTION,
    supported_producer_reader_versions=frozenset({QUILLAN_READER_VERSION}),
)


def _projection_failure(request: AdapterProjectionRequest) -> AdapterProjectionError:
    return AdapterProjectionError(
        "Quillan evidence could not be projected from the verified publication.",
        adapter_id=QUILLAN_ADAPTER_ID,
        publication_id=request.publication.publication_id,
    )


def _require_contract_agreement(
    request: AdapterProjectionRequest, manifest: AcademicResultManifest
) -> None:
    publication = request.publication
    registration = request.registration
    if (
        request.adapter_key != QUILLAN_ADAPTER_KEY
        or registration is None
        or publication.source_record is not None
        or publication.record_set_id != _QUILLAN_RECORD_SET_ID
        or frozenset(publication.capabilities) != _QUILLAN_CAPABILITIES
        or manifest.producer_module_id != QUILLAN_ADAPTER_KEY.producer_module_id
        or manifest.contract_version != QUILLAN_ADAPTER_KEY.manifest_contract_version
        or manifest.work.module_id != publication.work.module_id
        or manifest.work.class_id != publication.work.class_id
        or manifest.work.work_id != publication.work.work_id
        or manifest.record_set.record_set_id != publication.record_set_id
        or manifest.record_set.revision != publication.record_set_revision
    ):
        raise _projection_failure(request)


def _item_id(
    *,
    class_id: str,
    work_id: str,
    student_id: str,
    scope: str,
    unit_id: str | None,
    observation_id: str | None,
    standard_id: str | None,
    result_kind: str,
) -> str:
    fields = (
        QUILLAN_READER_DISTRIBUTION,
        class_id,
        work_id,
        student_id,
        scope,
        unit_id or "-",
        observation_id or "-",
        standard_id or "-",
        result_kind,
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"quillan_{digest.hexdigest()}"


def _native_scale(manifest: AcademicResultManifest) -> NativeScale:
    scale = manifest.assignment.rating_scale
    return NativeScale(
        scale_id=scale.scale_id,
        levels=tuple(
            NativeScaleLevel(level.value, level.label, level.description)
            for level in scale.levels
        ),
        contract_version=None,
    )


def _artifacts(
    manifest: AcademicResultManifest, student: StudentResult
) -> tuple[NativeArtifact, ...]:
    snapshots = (
        ("assignment_source_snapshot", manifest.source_snapshot),
        ("submission_source_snapshot", student.source_snapshot.submission),
        ("review_source_snapshot", student.source_snapshot.review),
    )
    return tuple(
        NativeArtifact(
            kind=kind,
            path=snapshot.relative_path,
            digest_algorithm="sha256",
            digest=snapshot.sha256,
        )
        for kind, snapshot in snapshots
    )


def _submission_references(student: StudentResult) -> list[NativeReference]:
    references = [
        NativeReference(kind="student", identifier=student.student_id),
        NativeReference(
            kind="submission_entry_method", identifier=student.submission.entry_method
        ),
    ]
    digital = student.submission.digital_provenance
    if digital is not None:
        references.extend(
            (
                NativeReference(kind="issuance", identifier=digital.issuance_id),
                NativeReference(kind="generation", identifier=digital.generation_id),
                NativeReference(kind="artifact", identifier=digital.artifact_id),
            )
        )
    return references


def _native_provenance(
    manifest: AcademicResultManifest,
    student: StudentResult,
    *,
    unit: ReviewUnit | None = None,
    observation: StandardObservation | None = None,
    standard_id: str | None = None,
    timestamp_kind: str | None = None,
    timestamp: datetime | None = None,
) -> NativeProvenance:
    references = _submission_references(student)
    if unit is not None:
        references.append(NativeReference(kind="review_unit", identifier=unit.unit_id))
        references.append(
            NativeReference(kind="review_unit_sequence", sequence=unit.sequence)
        )
    if observation is not None:
        references.append(
            NativeReference(kind="observation", identifier=observation.observation_id)
        )
    if standard_id is not None:
        references.append(NativeReference(kind="standard", identifier=standard_id))
    timestamps = [
        NativeTimestamp(kind="manifest_generated_at", value=manifest.generated_at)
    ]
    if timestamp_kind is not None and timestamp is not None:
        timestamps.append(NativeTimestamp(kind=timestamp_kind, value=timestamp))
    return NativeProvenance(
        references=tuple(references),
        artifacts=_artifacts(manifest, student),
        timestamps=tuple(timestamps),
    )


class QuillanAcademicResultAdapter(ProducerAdapter):
    """Project one exact released Quillan manifest without grading inference."""

    @property
    def descriptor(self) -> AdapterDescriptor:
        return QUILLAN_ADAPTER_DESCRIPTOR

    def project(self, request: AdapterProjectionRequest) -> EvidenceInventory:
        if not isinstance(request, AdapterProjectionRequest):
            raise AdapterProjectionError(
                "Quillan projection requires a verified Meridian request.",
                adapter_id=QUILLAN_ADAPTER_ID,
            )
        try:
            from quillan.academic_result_reader import read_academic_result_manifest
        except (ImportError, ModuleNotFoundError) as error:
            raise _projection_failure(request) from error
        try:
            manifest = read_academic_result_manifest(request.manifest_bytes)
            _require_contract_agreement(request, manifest)
            return self._project_validated(request, manifest)
        except AdapterProjectionError:
            raise
        except Exception as error:
            raise _projection_failure(request) from error

    @staticmethod
    def _project_validated(
        request: AdapterProjectionRequest, manifest: AcademicResultManifest
    ) -> EvidenceInventory:
        projection = projection_identity_from_descriptor(
            QUILLAN_ADAPTER_DESCRIPTOR, QUILLAN_READER_VERSION
        )
        scale = _native_scale(manifest)
        items: list[EvidenceItem] = []
        submission_target = EvidenceTarget(target_kind="submission", target_id=None)
        submission_parent = EvidenceTargetIdentity(
            target_kind="submission", target_id=None
        )

        for student in manifest.students:
            subject = StudentSubject(student.student_id)
            review = student.review

            def append_item(
                result_kind: str,
                value: NativeScalarValue | NativeScaledValue | NativeStateValue,
                target: EvidenceTarget,
                native: NativeProvenance,
                *,
                scope: str,
                unit_id: str | None = None,
                observation_id: str | None = None,
                standard_id: str | None = None,
            ) -> None:
                items.append(
                    EvidenceItem(
                        item_id=_item_id(
                            class_id=manifest.work.class_id,
                            work_id=manifest.work.work_id,
                            student_id=student.student_id,
                            scope=scope,
                            unit_id=unit_id,
                            observation_id=observation_id,
                            standard_id=standard_id,
                            result_kind=result_kind,
                        ),
                        subject=subject,
                        target=target,
                        result_kind=result_kind,
                        value=value,
                        provenance=EvidenceProvenance(
                            publication=request.publication,
                            registration=request.registration,
                            withdrawal=request.withdrawal,
                            projection=projection,
                            native=native,
                        ),
                    )
                )

            review_native = _native_provenance(manifest, student)
            append_item(
                "review_state",
                NativeStateValue(review.review_state),
                submission_target,
                review_native,
                scope="review",
            )
            if review.review_state == "returned_without_full_review":
                append_item(
                    "review_disposition",
                    NativeStateValue("returned_without_full_review"),
                    submission_target,
                    review_native,
                    scope="review",
                )

            outcome = review.minimum_requirement_outcome
            outcome_native = _native_provenance(
                manifest,
                student,
                timestamp_kind="minimum_requirement_updated_at",
                timestamp=outcome.updated_at,
            )
            append_item(
                "minimum_requirement_status",
                NativeStateValue(outcome.status),
                submission_target,
                outcome_native,
                scope="minimum_requirement",
            )

            for unit in review.review_units:
                for observation in unit.standard_observations:
                    target = EvidenceTarget(
                        target_kind="review_unit",
                        target_id=unit.unit_id,
                        parent_target=submission_parent,
                        standard_ids=(observation.standard_id,),
                        sequence=unit.sequence,
                    )
                    native = _native_provenance(
                        manifest,
                        student,
                        unit=unit,
                        observation=observation,
                        standard_id=observation.standard_id,
                        timestamp_kind="observation_updated_at",
                        timestamp=observation.updated_at,
                    )
                    identity = {
                        "scope": "observation",
                        "unit_id": unit.unit_id,
                        "observation_id": observation.observation_id,
                        "standard_id": observation.standard_id,
                    }
                    append_item(
                        "standard_applicability",
                        NativeScalarValue(observation.applicable),
                        target,
                        native,
                        **identity,
                    )
                    if observation.evidence_present is not None:
                        append_item(
                            "standard_evidence_presence",
                            NativeScalarValue(observation.evidence_present),
                            target,
                            native,
                            **identity,
                        )
                    observation_value = (
                        NativeStateValue("unrated")
                        if observation.rating is None
                        else NativeScaledValue(observation.rating, scale)
                    )
                    append_item(
                        "standard_observation_rating",
                        observation_value,
                        target,
                        native,
                        **identity,
                    )

            for overall_rating in review.overall_standard_ratings:
                target = EvidenceTarget(
                    target_kind="standard",
                    target_id=overall_rating.standard_id,
                    standard_ids=(overall_rating.standard_id,),
                )
                native = _native_provenance(
                    manifest,
                    student,
                    standard_id=overall_rating.standard_id,
                    timestamp_kind="overall_rating_updated_at",
                    timestamp=overall_rating.updated_at,
                )
                append_item(
                    "overall_standard_rating",
                    NativeScaledValue(overall_rating.rating, scale),
                    target,
                    native,
                    scope="overall_rating",
                    standard_id=overall_rating.standard_id,
                )
        return EvidenceInventory(tuple(items))
