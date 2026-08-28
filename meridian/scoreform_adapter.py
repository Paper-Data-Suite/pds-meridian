"""Exact ScoreForm v0.11.0 academic-result evidence projection."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final, cast

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
    EvidenceValue,
    NativeArtifact,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeStateValue,
    NativeTimestamp,
    StudentSubject,
)

if TYPE_CHECKING:
    from scoreform.academic_result_manifest import (
        Pds2ScanProvenance,
        ScanReviewManualProvenance,
    )
    from scoreform.academic_result_reader import AcademicResultManifest, Attempt

__all__ = [
    "SCOREFORM_ADAPTER_DESCRIPTOR",
    "SCOREFORM_ADAPTER_ID",
    "SCOREFORM_ADAPTER_KEY",
    "SCOREFORM_PROJECTION_CONTRACT_VERSION",
    "SCOREFORM_READER_DISTRIBUTION",
    "SCOREFORM_READER_VERSION",
    "ScoreFormAcademicResultAdapter",
]

SCOREFORM_ADAPTER_ID: Final = "scoreform.academic_result"
SCOREFORM_PROJECTION_CONTRACT_VERSION: Final = "1"
SCOREFORM_READER_DISTRIBUTION: Final = "scoreform"
SCOREFORM_READER_VERSION: Final = "0.11.0"
_SCOREFORM_RECORD_SET_ID: Final = "academic_results"
_SCOREFORM_CAPABILITIES: Final[frozenset[PublicationCapability]] = frozenset(
    {"points", "question_evidence", "multiple_attempts"}
)

SCOREFORM_ADAPTER_KEY: Final = AdapterKey(
    producer_module_id="scoreform",
    publication_kind="academic_result_set",
    manifest_contract_version="scoreform_academic_result_manifest_v1",
    producer_contract_version="scoreform_academic_work_v1",
    source_record_kind=None,
    source_record_contract_version=None,
)
SCOREFORM_ADAPTER_DESCRIPTOR: Final = AdapterDescriptor(
    adapter_id=SCOREFORM_ADAPTER_ID,
    key=SCOREFORM_ADAPTER_KEY,
    projection_contract_version=SCOREFORM_PROJECTION_CONTRACT_VERSION,
    supported_capabilities=_SCOREFORM_CAPABILITIES,
    producer_reader_distribution=SCOREFORM_READER_DISTRIBUTION,
    supported_producer_reader_versions=frozenset({SCOREFORM_READER_VERSION}),
)


def _projection_failure(request: AdapterProjectionRequest) -> AdapterProjectionError:
    return AdapterProjectionError(
        "ScoreForm evidence could not be projected from the verified publication.",
        adapter_id=SCOREFORM_ADAPTER_ID,
        publication_id=request.publication.publication_id,
    )


def _require_contract_agreement(
    request: AdapterProjectionRequest, manifest: AcademicResultManifest
) -> None:
    publication = request.publication
    registration = request.registration
    work = manifest.work
    record_set = manifest.record_set
    if (
        request.adapter_key != SCOREFORM_ADAPTER_KEY
        or registration is None
        or publication.source_record is not None
        or publication.record_set_id != _SCOREFORM_RECORD_SET_ID
        or frozenset(publication.capabilities) != _SCOREFORM_CAPABILITIES
        or manifest.producer_module_id != SCOREFORM_ADAPTER_KEY.producer_module_id
        or manifest.contract_version
        != SCOREFORM_ADAPTER_KEY.manifest_contract_version
        or work.module_id != publication.work.module_id
        or work.class_id != publication.work.class_id
        or work.work_id != publication.work.work_id
        or record_set.record_set_id != publication.record_set_id
        or record_set.revision != publication.record_set_revision
    ):
        raise _projection_failure(request)


def _item_id(
    *,
    class_id: str,
    work_id: str,
    student_id: str,
    attempt_number: int,
    question_number: int | None,
    result_kind: str,
) -> str:
    fields = (
        SCOREFORM_READER_DISTRIBUTION,
        class_id,
        work_id,
        student_id,
        str(attempt_number),
        "attempt" if question_number is None else str(question_number),
        result_kind,
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"scoreform_{digest.hexdigest()}"


def _native_provenance(
    manifest: AcademicResultManifest,
    attempt: Attempt,
    question_number: int | None,
) -> NativeProvenance:
    references = [NativeReference(kind="attempt", sequence=attempt.attempt_number)]
    if question_number is not None:
        references.append(NativeReference(kind="question", sequence=question_number))

    artifacts = [
        NativeArtifact(
            kind="assignment_source_snapshot",
            digest_algorithm="sha256",
            digest=manifest.source_snapshot.assignment.sha256,
        ),
        NativeArtifact(
            kind="results_history_source_snapshot",
            digest_algorithm="sha256",
            digest=manifest.source_snapshot.results_history.sha256,
        ),
    ]
    if attempt.result_origin == "pds2_scan":
        scan = cast("Pds2ScanProvenance", attempt.provenance)
        references.extend(
            (
                NativeReference(kind="issuance", identifier=scan.issuance_id),
                NativeReference(kind="generation", identifier=scan.generation_id),
                NativeReference(kind="artifact", identifier=scan.artifact_id),
                NativeReference(kind="source_scan", identifier=scan.source_scan_id),
            )
        )
        for page_id, route_id, logical_page, source_page in zip(
            scan.page_ids,
            scan.route_ids,
            scan.logical_pages,
            scan.source_page_numbers,
            strict=True,
        ):
            references.extend(
                (
                    NativeReference(kind="page", identifier=page_id),
                    NativeReference(kind="route", identifier=route_id),
                    NativeReference(kind="logical_page", sequence=logical_page),
                    NativeReference(kind="source_page", sequence=source_page),
                )
            )
        artifacts.append(
            NativeArtifact(
                kind="retained_source",
                path=scan.retained_source_path,
                digest_algorithm="sha256",
                digest=scan.source_sha256,
            )
        )
    elif attempt.result_origin == "scan_review_manual":
        review = cast("ScanReviewManualProvenance", attempt.provenance)
        references.append(
            NativeReference(
                kind="review_failure",
                identifier=review.review_reference.failure_id,
            )
        )

    return NativeProvenance(
        references=tuple(references),
        artifacts=tuple(artifacts),
        timestamps=(
            NativeTimestamp(kind="manifest_generated_at", value=manifest.generated_at),
            NativeTimestamp(kind="recorded_at", value=attempt.recorded_at),
        ),
    )


class ScoreFormAcademicResultAdapter(ProducerAdapter):
    """Project one exact released ScoreForm manifest without selecting attempts."""

    @property
    def descriptor(self) -> AdapterDescriptor:
        return SCOREFORM_ADAPTER_DESCRIPTOR

    def project(self, request: AdapterProjectionRequest) -> EvidenceInventory:
        if not isinstance(request, AdapterProjectionRequest):
            raise AdapterProjectionError(
                "ScoreForm projection requires a verified Meridian request.",
                adapter_id=SCOREFORM_ADAPTER_ID,
            )
        try:
            from scoreform.academic_result_reader import (
                read_academic_result_manifest,
            )
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
            SCOREFORM_ADAPTER_DESCRIPTOR, SCOREFORM_READER_VERSION
        )
        questions = {
            question.question_number: question
            for question in manifest.assignment.questions
        }
        items: list[EvidenceItem] = []
        for student in manifest.students:
            subject = StudentSubject(student_id=student.student_id)
            for attempt in student.attempts:
                attempt_target = EvidenceTarget(
                    target_kind="attempt",
                    target_id=f"attempt_{attempt.attempt_number}",
                    sequence=attempt.attempt_number,
                )
                attempt_native = _native_provenance(manifest, attempt, None)
                common = EvidenceProvenance(
                    publication=request.publication,
                    registration=request.registration,
                    withdrawal=request.withdrawal,
                    projection=projection,
                    native=attempt_native,
                )
                for result_kind, attempt_value in (
                    (
                        "attempt_points",
                        NativePointValue(
                            earned=attempt.points_earned,
                            possible=attempt.points_possible,
                        ),
                    ),
                    ("result_origin", NativeScalarValue(attempt.result_origin)),
                ):
                    items.append(
                        EvidenceItem(
                            item_id=_item_id(
                                class_id=manifest.work.class_id,
                                work_id=manifest.work.work_id,
                                student_id=student.student_id,
                                attempt_number=attempt.attempt_number,
                                question_number=None,
                                result_kind=result_kind,
                            ),
                            subject=subject,
                            target=attempt_target,
                            result_kind=result_kind,
                            value=attempt_value,
                            provenance=common,
                        )
                    )
                for response in attempt.responses:
                    question = questions[response.question_number]
                    question_target = EvidenceTarget(
                        target_kind="question",
                        target_id=f"question_{response.question_number}",
                        parent_target=EvidenceTargetIdentity(
                            target_kind="attempt",
                            target_id=f"attempt_{attempt.attempt_number}",
                        ),
                        standard_ids=question.standard_ids,
                        sequence=response.question_number,
                    )
                    native = _native_provenance(
                        manifest, attempt, response.question_number
                    )
                    provenance = EvidenceProvenance(
                        publication=request.publication,
                        registration=request.registration,
                        withdrawal=request.withdrawal,
                        projection=projection,
                        native=native,
                    )
                    if response.response_state == "selected":
                        response_kind = "selected_response"
                        if response.selected_answer is None:
                            raise _projection_failure(request)
                        response_value: EvidenceValue = NativeScalarValue(
                            response.selected_answer
                        )
                    else:
                        response_kind = "selected_response_state"
                        response_value = NativeStateValue(response.response_state)
                    for result_kind, response_evidence in (
                        (response_kind, response_value),
                        (
                            "question_correctness",
                            NativeScalarValue(response.correct),
                        ),
                    ):
                        items.append(
                            EvidenceItem(
                                item_id=_item_id(
                                    class_id=manifest.work.class_id,
                                    work_id=manifest.work.work_id,
                                    student_id=student.student_id,
                                    attempt_number=attempt.attempt_number,
                                    question_number=response.question_number,
                                    result_kind=result_kind,
                                ),
                                subject=subject,
                                target=question_target,
                                result_kind=result_kind,
                                value=response_evidence,
                                provenance=provenance,
                            )
                        )
        return EvidenceInventory(tuple(items))
