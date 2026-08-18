from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

from concord.academic_result_manifest import (
    ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
    ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
    AcademicResultManifest,
    ActivityContextProjection,
    CriterionProjection,
    CriterionSetProjection,
    EvidenceLocatorProjection,
    EvidenceReferenceProjection,
    ManifestProjection,
    ManifestRecordSet,
    ModerationProjection,
    PrivacyProjection,
    PublicActor,
    ScaleLevelProjection,
    ScoreEvidenceLinkProjection,
    ScoreProjection,
    ScoringScaleProjection,
    StandardsResultProjection,
    StatusReasonProjection,
    SubjectReferenceProjection,
    TargetReferenceProjection,
    academic_result_manifest_to_bytes,
    derive_manifest_capabilities,
    with_semantic_projection_digest,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

NOW = datetime(2026, 8, 17, 12, tzinfo=UTC)
WORK = ModuleWorkRef("concord", "class_2026", "activity_1")
SOURCE = ModuleRecordRef(
    "concord",
    "activity",
    "activity_1",
    "concord_activity_v1",
)
PUB_ID = "pub_44444444444444444444444444444444"

TEACHER = PublicActor(
    actor_kind="authorized_adult",
    actor_id="teacher_1",
    owning_system="concord",
)
SYSTEM = PublicActor(
    actor_kind="system",
    actor_id="projection_service",
    owning_system="concord",
)


def concord_registration(
    *,
    work_kind: str = "collaborative_activity",
    source_records: tuple[ModuleRecordRef, ...] = (SOURCE,),
) -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=WORK,
        registration_revision=1,
        producer_contract_version="concord_academic_work_v1",
        title="Synthetic Collaborative Activity",
        work_kind=work_kind,
        academic_intent="formative",
        lifecycle="active",
        created_at=NOW,
        updated_at=NOW,
        source_records=source_records,
    )


def _scale() -> ScoringScaleProjection:
    return ScoringScaleProjection(
        scoring_scale_id="scale_2",
        lineage_id="scale_lineage_1",
        name="Synthetic collaboration rubric",
        revision=2,
        scale_type="ordinal",
        levels=(
            ScaleLevelProjection(
                value=0,
                label="Beginning",
                meaning="Initial evidence.",
                position=1,
                description="Evidence is emerging.",
            ),
            ScaleLevelProjection(
                value=2,
                label="Developing",
                meaning="Partial command.",
                position=3,
                description="Evidence is developing.",
            ),
            ScaleLevelProjection(
                value=4,
                label="Secure",
                meaning="Consistent command.",
                position=7,
                description="Evidence is consistent.",
            ),
        ),
        status="active",
        supersedes_scoring_scale_id="scale_1",
    )


def _criterion_set(full: bool) -> CriterionSetProjection:
    criterion_ids = (
        ("criterion_local", "criterion_standard")
        if full
        else ("criterion_local",)
    )
    return CriterionSetProjection(
        criterion_set_id="criterion_set_1",
        lineage_id="criterion_set_lineage_1",
        revision=1,
        criterion_set_kind=("mixed" if full else "local"),
        scope="activity_specific",
        criterion_ids=criterion_ids,
        status="active",
        supersedes_criterion_set_id=None,
        standards_profile_id=("profile_1" if full else None),
    )


def _criteria(full: bool) -> tuple[CriterionProjection, ...]:
    local = CriterionProjection(
        criterion_id="criterion_local",
        criterion_set_id="criterion_set_1",
        key="collaboration",
        label="Collaboration",
        definition="Evaluate the collaborative result.",
        criterion_kind="local",
        supported_target_kinds=("concord_group",),
        status="active",
        standard_id=None,
        alignment_standard_ids=(),
        default_scoring_scale_id="scale_2",
    )
    if not full:
        return (local,)
    standard = CriterionProjection(
        criterion_id="criterion_standard",
        criterion_set_id="criterion_set_1",
        key="standard_quality",
        label="Standard quality",
        definition="Evaluate the represented standard.",
        criterion_kind="standard_backed",
        supported_target_kinds=("core_student",),
        status="active",
        standard_id="standard_ela_1",
        alignment_standard_ids=(),
        default_scoring_scale_id="scale_2",
    )
    return (local, standard)


def _evidence_reference(
    record_id: str,
    *,
    participant: str,
    moderation_requirement: str,
) -> EvidenceReferenceProjection:
    subject = SubjectReferenceProjection(
        subject_kind="concord_group",
        subject_id="group_1",
        owning_system="concord",
        contract_version="concord_group_v1",
    )
    return EvidenceReferenceProjection(
        evidence_kind="artifact_instance",
        owning_system="concord",
        record_id=record_id,
        contract_version="concord_artifact_instance_v1",
        source_publication_reference=None,
        immutable_source_version=None,
        locator=EvidenceLocatorProjection(
            page_number=1,
            source_page_index=0,
            section_label="Section A",
            row_label=None,
            column_label=None,
            participant_label=participant,
            session_id="session_1",
        ),
        subject_context=(subject,),
        moderation_requirement=moderation_requirement,
    )


def _full_manifest(
    *,
    primary_student_id: str = "student_1",
    secondary_student_id: str = "student_2",
) -> AcademicResultManifest:
    evidence_1 = _evidence_reference(
        "artifact_instance_1",
        participant="Group",
        moderation_requirement="not_required",
    )
    evidence_2 = _evidence_reference(
        "artifact_instance_2",
        participant="Student context",
        moderation_requirement="required",
    )
    scores = (
        ScoreProjection(
            score_record_id="score_001",
            activity_id=WORK.work_id,
            session_id="session_1",
            target_reference=TargetReferenceProjection(
                target_kind="concord_group",
                target_id="group_1",
                owning_system="concord",
                contract_version="concord_group_v1",
            ),
            criterion_id="criterion_local",
            score_kind="local",
            standard_id=None,
            scoring_scale_id="scale_2",
            disposition="scored",
            value=0,
            basis="linked_evidence",
            scorer=TEACHER,
            scored_at=NOW,
            moderation_complete=True,
            status_reason=None,
            supersedes_score_record_id=None,
            current_state="superseded",
        ),
        ScoreProjection(
            score_record_id="score_002",
            activity_id=WORK.work_id,
            session_id="session_1",
            target_reference=TargetReferenceProjection(
                target_kind="concord_group",
                target_id="group_1",
                owning_system="concord",
                contract_version="concord_group_v1",
            ),
            criterion_id="criterion_local",
            score_kind="local",
            standard_id=None,
            scoring_scale_id="scale_2",
            disposition="scored",
            value=4,
            basis="linked_evidence",
            scorer=TEACHER,
            scored_at=NOW.replace(minute=5),
            moderation_complete=True,
            status_reason=None,
            supersedes_score_record_id="score_001",
            current_state="current",
        ),
        ScoreProjection(
            score_record_id="score_003",
            activity_id=WORK.work_id,
            session_id=None,
            target_reference=TargetReferenceProjection(
                target_kind="core_student",
                target_id=primary_student_id,
                owning_system="core",
                contract_version=None,
            ),
            criterion_id="criterion_standard",
            score_kind="standard_backed",
            standard_id="standard_ela_1",
            scoring_scale_id="scale_2",
            disposition="scored",
            value=2,
            basis="professional_judgment",
            scorer=TEACHER,
            scored_at=NOW.replace(minute=10),
            moderation_complete=True,
            status_reason=None,
            supersedes_score_record_id=None,
            current_state="current",
        ),
        ScoreProjection(
            score_record_id="score_004",
            activity_id=WORK.work_id,
            session_id=None,
            target_reference=TargetReferenceProjection(
                target_kind="core_student",
                target_id=secondary_student_id,
                owning_system="core",
                contract_version=None,
            ),
            criterion_id="criterion_standard",
            score_kind="standard_backed",
            standard_id="standard_ela_1",
            scoring_scale_id="scale_2",
            disposition="absent",
            value=None,
            basis="professional_judgment",
            scorer=TEACHER,
            scored_at=NOW.replace(minute=15),
            moderation_complete=False,
            status_reason=StatusReasonProjection(
                reason_code="absent",
                recorded_by=TEACHER,
                recorded_at=NOW.replace(minute=15),
                related_record=None,
            ),
            supersedes_score_record_id=None,
            current_state="current",
        ),
    )
    links = (
        ScoreEvidenceLinkProjection(
            score_evidence_link_id="link_001",
            score_record_id="score_001",
            evidence_reference=evidence_1,
            evidence_locator=None,
            subject_context=(),
            relevance_description="Evidence for the initial Group Score.",
            significance="primary",
            moderation_record_id=None,
            status="active",
            supersedes_score_evidence_link_id=None,
        ),
        ScoreEvidenceLinkProjection(
            score_evidence_link_id="link_002",
            score_record_id="score_002",
            evidence_reference=evidence_2,
            evidence_locator=EvidenceLocatorProjection(
                page_number=None,
                source_page_index=2,
                section_label=None,
                row_label="Row 2",
                column_label=None,
                participant_label=None,
                session_id="session_1",
            ),
            subject_context=(
                SubjectReferenceProjection(
                    subject_kind="core_student",
                    subject_id=primary_student_id,
                    owning_system="core",
                    contract_version=None,
                ),
                SubjectReferenceProjection(
                    subject_kind="core_student",
                    subject_id=secondary_student_id,
                    owning_system="core",
                    contract_version=None,
                ),
            ),
            relevance_description="Moderated evidence for the Group Score.",
            significance="corroborating",
            moderation_record_id="moderation_001",
            status="active",
            supersedes_score_evidence_link_id=None,
        ),
    )
    moderation = ModerationProjection(
        moderation_record_id="moderation_001",
        target_evidence_reference=evidence_2,
        target_subject_references=(
            SubjectReferenceProjection(
                subject_kind="core_student",
                subject_id=primary_student_id,
                owning_system="core",
                contract_version=None,
            ),
            SubjectReferenceProjection(
                subject_kind="core_student",
                subject_id=secondary_student_id,
                owning_system="core",
                contract_version=None,
            ),
        ),
        status="accepted_with_qualification",
        permitted_use="support_group_score",
        qualification="Use only as corroborating Group evidence.",
        supersedes_moderation_record_id=None,
        current_state="current",
    )
    manifest = AcademicResultManifest(
        record_type=ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
        contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        producer_module_id="concord",
        generated_at=NOW,
        record_set=ManifestRecordSet("academic_results", 1),
        work=WORK,
        source_activity=SOURCE,
        projection=ManifestProjection(
            source_snapshot_revision=3,
            projection_digest_algorithm="sha256",
            projection_digest="0" * 64,
            generated_by=SYSTEM,
            revision_reason="moderation_change",
        ),
        activity_context=ActivityContextProjection(
            activity_id=WORK.work_id,
            class_id=WORK.class_id,
            title="Synthetic Collaborative Activity",
            scoring_orientation="mixed",
            standards_profile_id="profile_1",
            focus_standard_ids=("standard_ela_1",),
            criterion_set_ids=("criterion_set_1",),
        ),
        criterion_sets=(_criterion_set(True),),
        criteria=_criteria(True),
        scoring_scales=(_scale(),),
        scores=scores,
        score_evidence_links=links,
        moderation_records=(moderation,),
        standards_result_projection=(
            StandardsResultProjection("score_003", "standard_ela_1"),
            StandardsResultProjection("score_004", "standard_ela_1"),
        ),
        privacy=PrivacyProjection(
            classification="teacher_restricted",
            audience_references=(),
            policy_reference=None,
            inherited_from=None,
        ),
    )
    return with_semantic_projection_digest(manifest)


def _local_only_manifest() -> AcademicResultManifest:
    score = ScoreProjection(
        score_record_id="score_001",
        activity_id=WORK.work_id,
        session_id=None,
        target_reference=TargetReferenceProjection(
            target_kind="concord_group",
            target_id="group_1",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
        criterion_id="criterion_local",
        score_kind="local",
        standard_id=None,
        scoring_scale_id="scale_2",
        disposition="scored",
        value=0,
        basis="professional_judgment",
        scorer=TEACHER,
        scored_at=NOW,
        moderation_complete=True,
        status_reason=None,
        supersedes_score_record_id=None,
        current_state="current",
    )
    manifest = AcademicResultManifest(
        record_type=ACADEMIC_RESULT_MANIFEST_RECORD_TYPE,
        contract_version=ACADEMIC_RESULT_MANIFEST_CONTRACT_VERSION,
        producer_module_id="concord",
        generated_at=NOW,
        record_set=ManifestRecordSet("academic_results", 1),
        work=WORK,
        source_activity=SOURCE,
        projection=ManifestProjection(
            source_snapshot_revision=1,
            projection_digest_algorithm="sha256",
            projection_digest="0" * 64,
            generated_by=SYSTEM,
            revision_reason="initial",
        ),
        activity_context=ActivityContextProjection(
            activity_id=WORK.work_id,
            class_id=WORK.class_id,
            title="Synthetic Collaborative Activity",
            scoring_orientation="local_criteria_only",
            standards_profile_id=None,
            focus_standard_ids=(),
            criterion_set_ids=("criterion_set_1",),
        ),
        criterion_sets=(_criterion_set(False),),
        criteria=_criteria(False),
        scoring_scales=(_scale(),),
        scores=(score,),
        score_evidence_links=(),
        moderation_records=(),
        standards_result_projection=(),
        privacy=PrivacyProjection(
            classification="teacher_restricted",
            audience_references=(),
            policy_reference=None,
            inherited_from=None,
        ),
    )
    return with_semantic_projection_digest(manifest)


def _standard_only_manifest(
    *,
    primary_student_id: str,
    secondary_student_id: str,
) -> AcademicResultManifest:
    manifest = _full_manifest(
        primary_student_id=primary_student_id,
        secondary_student_id=secondary_student_id,
    )
    links = tuple(
        replace(
            link,
            evidence_reference=replace(
                link.evidence_reference,
                moderation_requirement="not_required",
            ),
            moderation_record_id=None,
        )
        for link in manifest.score_evidence_links
    )
    return with_semantic_projection_digest(
        replace(
            manifest,
            score_evidence_links=links,
            moderation_records=(),
            projection=replace(
                manifest.projection,
                projection_digest="0" * 64,
                revision_reason="projection_correction",
            ),
        )
    )


def _rejected_moderation_manifest(
    *,
    primary_student_id: str,
    secondary_student_id: str,
) -> AcademicResultManifest:
    manifest = _full_manifest(
        primary_student_id=primary_student_id,
        secondary_student_id=secondary_student_id,
    )
    moderation = manifest.moderation_records[0]
    rejected = replace(
        moderation,
        status="rejected",
        permitted_use="not_be_used_for_scoring",
        qualification=None,
    )
    return with_semantic_projection_digest(
        replace(
            manifest,
            moderation_records=(rejected,),
            projection=replace(
                manifest.projection,
                projection_digest="0" * 64,
                revision_reason="moderation_change",
            ),
        )
    )


def concord_manifest_bytes(
    *,
    local_only: bool = False,
    standard_only: bool = False,
    rejected_moderation: bool = False,
    primary_student_id: str = "student_1",
    secondary_student_id: str = "student_2",
) -> bytes:
    modes = sum((local_only, standard_only, rejected_moderation))
    if modes > 1:
        raise ValueError("only one Concord synthetic manifest mode may be selected")
    if local_only:
        manifest = _local_only_manifest()
    elif standard_only:
        manifest = _standard_only_manifest(
            primary_student_id=primary_student_id,
            secondary_student_id=secondary_student_id,
        )
    elif rejected_moderation:
        manifest = _rejected_moderation_manifest(
            primary_student_id=primary_student_id,
            secondary_student_id=secondary_student_id,
        )
    else:
        manifest = _full_manifest(
            primary_student_id=primary_student_id,
            secondary_student_id=secondary_student_id,
        )
    return academic_result_manifest_to_bytes(manifest)


def concord_publication(
    manifest_bytes: bytes,
    *,
    capabilities: tuple[str, ...] | None = None,
    source_record: ModuleRecordRef = SOURCE,
    record_set_revision: int = 1,
) -> PublicationRecord:
    from concord.academic_result_reader import read_academic_result_manifest

    manifest = read_academic_result_manifest(manifest_bytes)
    derived = derive_manifest_capabilities(manifest)
    selected = tuple(derived) if capabilities is None else capabilities
    return PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id=PUB_ID,
        work=WORK,
        source_record=source_record,
        publication_kind="academic_result_set",
        capabilities=selected,
        record_set_id="academic_results",
        record_set_revision=record_set_revision,
        manifest_contract_version="concord_academic_result_manifest_v1",
        manifest_path=(
            "classes/class_2026/modules/concord/work/activity_1/"
            "publications/academic_results/1.json"
        ),
        manifest_digest_algorithm="sha256",
        manifest_digest=hashlib.sha256(manifest_bytes).hexdigest(),
        published_at=NOW,
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )


def concord_withdrawal() -> PublicationWithdrawal:
    return PublicationWithdrawal(
        schema_version="1",
        record_type="publication_withdrawal",
        publication_id=PUB_ID,
        withdrawn_at=NOW.replace(hour=13),
        reason="Synthetic correction",
    )
