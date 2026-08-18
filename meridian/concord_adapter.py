"""Exact Concord v0.2.0 academic-result evidence projection."""

from __future__ import annotations

import hashlib
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
    EvidenceValue,
    NativeProvenance,
    NativeReference,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    NativeTimestamp,
    StudentSubject,
)

if TYPE_CHECKING:
    from concord.academic_result_manifest import (
        AcademicResultManifest,
        EvidenceLocatorProjection,
        EvidenceReferenceProjection,
        ModerationProjection,
        PublicActor,
        ScoreEvidenceLinkProjection,
        ScoreProjection,
        ScoringScaleProjection,
        SubjectReferenceProjection,
    )

__all__ = [
    "CONCORD_ADAPTER_DESCRIPTOR",
    "CONCORD_ADAPTER_ID",
    "CONCORD_ADAPTER_KEY",
    "CONCORD_PROJECTION_CONTRACT_VERSION",
    "CONCORD_READER_DISTRIBUTION",
    "CONCORD_READER_VERSION",
    "ConcordAcademicResultAdapter",
]

CONCORD_ADAPTER_ID: Final = "concord.academic_result"
CONCORD_PROJECTION_CONTRACT_VERSION: Final = "1"
CONCORD_READER_DISTRIBUTION: Final = "pds-concord"
CONCORD_READER_VERSION: Final = "0.2.0"

_CONCORD_RECORD_SET_ID: Final = "academic_results"
_CONCORD_WORK_KIND: Final = "collaborative_activity"
_CONCORD_CAPABILITIES: Final[frozenset[PublicationCapability]] = frozenset(
    {"criterion_scores", "moderated_scores", "standards_ratings"}
)

CONCORD_ADAPTER_KEY: Final = AdapterKey(
    producer_module_id="concord",
    publication_kind="academic_result_set",
    manifest_contract_version="concord_academic_result_manifest_v1",
    producer_contract_version="concord_academic_work_v1",
    source_record_kind="activity",
    source_record_contract_version="concord_activity_v1",
)
CONCORD_ADAPTER_DESCRIPTOR: Final = AdapterDescriptor(
    adapter_id=CONCORD_ADAPTER_ID,
    key=CONCORD_ADAPTER_KEY,
    projection_contract_version=CONCORD_PROJECTION_CONTRACT_VERSION,
    supported_capabilities=_CONCORD_CAPABILITIES,
    producer_reader_distribution=CONCORD_READER_DISTRIBUTION,
    supported_producer_reader_versions=frozenset({CONCORD_READER_VERSION}),
)


def _projection_failure(
    request: AdapterProjectionRequest,
) -> AdapterProjectionError:
    return AdapterProjectionError(
        "Concord evidence could not be projected from the verified publication.",
        adapter_id=CONCORD_ADAPTER_ID,
        publication_id=request.publication.publication_id,
    )


def _require_contract_agreement(
    request: AdapterProjectionRequest,
    manifest: AcademicResultManifest,
    derived_capabilities: tuple[PublicationCapability, ...],
) -> None:
    publication = request.publication
    registration = request.registration
    source = publication.source_record
    if (
        request.adapter_key != CONCORD_ADAPTER_KEY
        or registration is None
        or registration.producer_contract_version
        != CONCORD_ADAPTER_KEY.producer_contract_version
        or registration.work_kind != _CONCORD_WORK_KIND
        or source is None
        or source.module_id != CONCORD_ADAPTER_KEY.producer_module_id
        or source.record_kind != CONCORD_ADAPTER_KEY.source_record_kind
        or source.contract_version
        != CONCORD_ADAPTER_KEY.source_record_contract_version
        or source not in registration.source_records
        or publication.record_set_id != _CONCORD_RECORD_SET_ID
        or frozenset(publication.capabilities)
        != frozenset(derived_capabilities)
        or manifest.producer_module_id
        != CONCORD_ADAPTER_KEY.producer_module_id
        or manifest.contract_version
        != CONCORD_ADAPTER_KEY.manifest_contract_version
        or manifest.work != publication.work
        or manifest.activity_context.activity_id != publication.work.work_id
        or manifest.activity_context.class_id != publication.work.class_id
        or manifest.record_set.record_set_id != publication.record_set_id
        or manifest.record_set.revision != publication.record_set_revision
        or manifest.source_activity != source
    ):
        raise _projection_failure(request)


def _item_id(
    manifest: AcademicResultManifest,
    score: ScoreProjection,
    result_kind: str,
) -> str:
    fields = (
        CONCORD_READER_DISTRIBUTION,
        manifest.work.class_id,
        manifest.work.work_id,
        score.score_record_id,
        result_kind,
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return f"concord_{digest.hexdigest()}"


def _native_scale(scale: ScoringScaleProjection) -> NativeScale:
    return NativeScale(
        scale_id=scale.scoring_scale_id,
        levels=tuple(
            NativeScaleLevel(
                value=level.value,
                label=level.label,
                description=level.description,
                meaning=level.meaning,
                position=level.position,
            )
            for level in scale.levels
        ),
        contract_version=None,
        order_is_meaningful=all(
            level.position is not None for level in scale.levels
        ),
        lineage_id=scale.lineage_id,
        name=scale.name,
        revision=scale.revision,
        scale_type=scale.scale_type,
        status=scale.status,
        supersedes_scale_id=scale.supersedes_scoring_scale_id,
    )


def _append_actor(
    references: list[NativeReference],
    prefix: str,
    actor: PublicActor,
) -> None:
    references.extend(
        (
            NativeReference(
                kind=f"{prefix}_kind",
                identifier=actor.actor_kind,
            ),
            NativeReference(
                kind=f"{prefix}_id",
                identifier=actor.actor_id,
            ),
            NativeReference(
                kind=f"{prefix}_system",
                identifier=actor.owning_system,
            ),
        )
    )


def _append_subjects(
    references: list[NativeReference],
    prefix: str,
    subjects: tuple[SubjectReferenceProjection, ...],
) -> None:
    for sequence, subject in enumerate(subjects, start=1):
        references.extend(
            (
                NativeReference(
                    kind=f"{prefix}_kind",
                    identifier=subject.subject_kind,
                    sequence=sequence,
                ),
                NativeReference(
                    kind=f"{prefix}_id",
                    identifier=subject.subject_id,
                    sequence=sequence,
                ),
                NativeReference(
                    kind=f"{prefix}_system",
                    identifier=subject.owning_system,
                    sequence=sequence,
                ),
            )
        )
        if subject.contract_version is not None:
            references.append(
                NativeReference(
                    kind=f"{prefix}_contract",
                    identifier=subject.contract_version,
                    sequence=sequence,
                )
            )


def _append_locator(
    references: list[NativeReference],
    prefix: str,
    locator: EvidenceLocatorProjection | None,
) -> None:
    if locator is None:
        return
    if locator.page_number is not None:
        references.append(
            NativeReference(
                kind=f"{prefix}_page_number",
                sequence=locator.page_number,
            )
        )
    if locator.source_page_index is not None:
        references.append(
            NativeReference(
                kind=f"{prefix}_source_page_index",
                identifier=str(locator.source_page_index),
            )
        )
    for suffix, value in (
        ("section_label", locator.section_label),
        ("row_label", locator.row_label),
        ("column_label", locator.column_label),
        ("participant_label", locator.participant_label),
        ("session_id", locator.session_id),
    ):
        if value is not None:
            references.append(
                NativeReference(
                    kind=f"{prefix}_{suffix}",
                    identifier=value,
                )
            )


def _append_evidence_reference(
    references: list[NativeReference],
    value: EvidenceReferenceProjection,
) -> None:
    references.extend(
        (
            NativeReference(
                kind="evidence_kind",
                identifier=value.evidence_kind,
            ),
            NativeReference(
                kind="evidence_system",
                identifier=value.owning_system,
            ),
            NativeReference(
                kind="evidence_record",
                identifier=value.record_id,
            ),
        )
    )
    if value.contract_version is not None:
        references.append(
            NativeReference(
                kind="evidence_contract",
                identifier=value.contract_version,
            )
        )
    source_publication = value.source_publication_reference
    if source_publication is not None:
        references.append(
            NativeReference(
                kind="evidence_source_publication",
                identifier=source_publication.publication_id,
            )
        )
        if source_publication.publication_schema_version is not None:
            references.append(
                NativeReference(
                    kind="evidence_source_publication_schema",
                    identifier=source_publication.publication_schema_version,
                )
            )
    if value.immutable_source_version is not None:
        references.append(
            NativeReference(
                kind="evidence_immutable_source_version",
                identifier=value.immutable_source_version,
            )
        )
    _append_locator(references, "evidence_locator", value.locator)
    _append_subjects(
        references,
        "evidence_subject",
        value.subject_context,
    )
    if value.moderation_requirement is not None:
        references.append(
            NativeReference(
                kind="evidence_moderation_requirement",
                identifier=value.moderation_requirement,
            )
        )


def _append_moderation(
    references: list[NativeReference],
    moderation: ModerationProjection,
) -> None:
    references.extend(
        (
            NativeReference(
                kind="moderation_record",
                identifier=moderation.moderation_record_id,
            ),
            NativeReference(
                kind="moderation_status",
                identifier=moderation.status,
            ),
            NativeReference(
                kind="moderation_permitted_use",
                identifier=moderation.permitted_use,
            ),
            NativeReference(
                kind="moderation_current_state",
                identifier=moderation.current_state,
            ),
        )
    )
    if moderation.qualification is not None:
        references.append(
            NativeReference(
                kind="moderation_qualification",
                identifier=moderation.qualification,
            )
        )
    if moderation.supersedes_moderation_record_id is not None:
        references.append(
            NativeReference(
                kind="moderation_supersedes",
                identifier=moderation.supersedes_moderation_record_id,
            )
        )
    _append_subjects(
        references,
        "moderation_subject",
        moderation.target_subject_references,
    )


def _append_evidence_link(
    references: list[NativeReference],
    link: ScoreEvidenceLinkProjection,
    moderation_by_id: dict[str, ModerationProjection],
) -> None:
    references.append(
        NativeReference(
            kind="score_evidence_link",
            identifier=link.score_evidence_link_id,
        )
    )
    _append_evidence_reference(references, link.evidence_reference)
    _append_locator(references, "score_link_locator", link.evidence_locator)
    _append_subjects(
        references,
        "score_link_subject",
        link.subject_context,
    )
    references.extend(
        (
            NativeReference(
                kind="score_link_relevance",
                identifier=link.relevance_description,
            ),
            NativeReference(
                kind="score_link_status",
                identifier=link.status,
            ),
        )
    )
    if link.significance is not None:
        references.append(
            NativeReference(
                kind="score_link_significance",
                identifier=link.significance,
            )
        )
    if link.supersedes_score_evidence_link_id is not None:
        references.append(
            NativeReference(
                kind="score_link_supersedes",
                identifier=link.supersedes_score_evidence_link_id,
            )
        )
    if link.moderation_record_id is not None:
        moderation = moderation_by_id[link.moderation_record_id]
        _append_moderation(references, moderation)


def _native_provenance(
    manifest: AcademicResultManifest,
    score: ScoreProjection,
    links: tuple[ScoreEvidenceLinkProjection, ...],
    moderation_by_id: dict[str, ModerationProjection],
) -> NativeProvenance:
    references = [
        NativeReference(
            kind="score_record",
            identifier=score.score_record_id,
        ),
        NativeReference(
            kind="activity",
            identifier=score.activity_id,
        ),
        NativeReference(
            kind="criterion",
            identifier=score.criterion_id,
        ),
        NativeReference(
            kind="scoring_scale",
            identifier=score.scoring_scale_id,
        ),
        NativeReference(
            kind="score_kind",
            identifier=score.score_kind,
        ),
        NativeReference(
            kind="score_disposition",
            identifier=score.disposition,
        ),
        NativeReference(
            kind="score_basis",
            identifier=score.basis,
        ),
        NativeReference(
            kind="score_current_state",
            identifier=score.current_state,
        ),
        NativeReference(
            kind="score_moderation_complete",
            identifier=("true" if score.moderation_complete else "false"),
        ),
        NativeReference(
            kind="manifest_source_snapshot_revision",
            sequence=manifest.projection.source_snapshot_revision,
        ),
        NativeReference(
            kind="manifest_revision_reason",
            identifier=manifest.projection.revision_reason,
        ),
    ]
    if score.session_id is not None:
        references.append(
            NativeReference(
                kind="session",
                identifier=score.session_id,
            )
        )
    if score.standard_id is not None:
        references.append(
            NativeReference(
                kind="standard",
                identifier=score.standard_id,
            )
        )
    if score.supersedes_score_record_id is not None:
        references.append(
            NativeReference(
                kind="score_supersedes",
                identifier=score.supersedes_score_record_id,
            )
        )
    _append_actor(references, "score_scorer", score.scorer)
    _append_actor(
        references,
        "manifest_generated_by",
        manifest.projection.generated_by,
    )

    timestamps = [
        NativeTimestamp(
            kind="manifest_generated_at",
            value=manifest.generated_at,
        ),
        NativeTimestamp(
            kind="score_scored_at",
            value=score.scored_at,
        ),
    ]
    reason = score.status_reason
    if reason is not None:
        references.append(
            NativeReference(
                kind="score_status_reason",
                identifier=reason.reason_code,
            )
        )
        _append_actor(
            references,
            "score_status_recorded_by",
            reason.recorded_by,
        )
        timestamps.append(
            NativeTimestamp(
                kind="score_status_recorded_at",
                value=reason.recorded_at,
            )
        )
        related = reason.related_record
        if related is not None:
            references.extend(
                (
                    NativeReference(
                        kind="score_status_related_module",
                        identifier=related.module_id,
                    ),
                    NativeReference(
                        kind="score_status_related_kind",
                        identifier=related.record_kind,
                    ),
                    NativeReference(
                        kind="score_status_related_record",
                        identifier=related.record_id,
                    ),
                )
            )
            if related.contract_version is not None:
                references.append(
                    NativeReference(
                        kind="score_status_related_contract",
                        identifier=related.contract_version,
                    )
                )

    for link in links:
        _append_evidence_link(
            references,
            link,
            moderation_by_id,
        )

    return NativeProvenance(
        references=tuple(references),
        timestamps=tuple(timestamps),
    )


def _subject(score: ScoreProjection) -> StudentSubject | None:
    target = score.target_reference
    if target.target_kind != "core_student":
        return None
    return StudentSubject(target.target_id)


def _target(score: ScoreProjection) -> EvidenceTarget:
    target = score.target_reference
    standards = (
        (score.standard_id,) if score.standard_id is not None else ()
    )
    return EvidenceTarget(
        target_kind=target.target_kind,
        target_id=target.target_id,
        standard_ids=standards,
        owning_system=target.owning_system,
        contract_version=target.contract_version,
    )


class ConcordAcademicResultAdapter(ProducerAdapter):
    """Project every represented Concord Score without consumer selection."""

    @property
    def descriptor(self) -> AdapterDescriptor:
        return CONCORD_ADAPTER_DESCRIPTOR

    def project(self, request: AdapterProjectionRequest) -> EvidenceInventory:
        if not isinstance(request, AdapterProjectionRequest):
            raise AdapterProjectionError(
                "Concord projection requires a verified Meridian request.",
                adapter_id=CONCORD_ADAPTER_ID,
            )
        try:
            from concord.academic_result_manifest import (
                derive_manifest_capabilities,
            )
            from concord.academic_result_reader import (
                read_academic_result_manifest,
            )
        except (ImportError, ModuleNotFoundError) as error:
            raise _projection_failure(request) from error

        try:
            manifest = read_academic_result_manifest(request.manifest_bytes)
            capabilities = derive_manifest_capabilities(manifest)
            _require_contract_agreement(
                request,
                manifest,
                capabilities,
            )
            return self._project_validated(request, manifest)
        except AdapterProjectionError:
            raise
        except Exception as error:
            raise _projection_failure(request) from error

    @staticmethod
    def _project_validated(
        request: AdapterProjectionRequest,
        manifest: AcademicResultManifest,
    ) -> EvidenceInventory:
        projection = projection_identity_from_descriptor(
            CONCORD_ADAPTER_DESCRIPTOR,
            CONCORD_READER_VERSION,
        )
        scale_by_id = {
            scale.scoring_scale_id: _native_scale(scale)
            for scale in manifest.scoring_scales
        }
        links_by_score: dict[
            str,
            list[ScoreEvidenceLinkProjection],
        ] = {}
        for link in manifest.score_evidence_links:
            links_by_score.setdefault(link.score_record_id, []).append(link)
        moderation_by_id = {
            moderation.moderation_record_id: moderation
            for moderation in manifest.moderation_records
        }

        items: list[EvidenceItem] = []
        for score in manifest.scores:
            result_kind = (
                "standard_backed_score"
                if score.score_kind == "standard_backed"
                else "local_score"
            )
            value: EvidenceValue
            if score.disposition == "scored":
                if score.value is None:
                    raise _projection_failure(request)
                value = NativeScaledValue(
                    value=score.value,
                    scale=scale_by_id[score.scoring_scale_id],
                )
            else:
                value = NativeStateValue(score.disposition)

            native = _native_provenance(
                manifest,
                score,
                tuple(links_by_score.get(score.score_record_id, [])),
                moderation_by_id,
            )
            items.append(
                EvidenceItem(
                    item_id=_item_id(
                        manifest,
                        score,
                        result_kind,
                    ),
                    subject=_subject(score),
                    target=_target(score),
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
        return EvidenceInventory(tuple(items))
