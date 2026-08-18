"""Privacy-safe Quillan v0.9.0 publication builders."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast

from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import (
    PublicationCapability,
    PublicationRecord,
    PublicationWithdrawal,
)
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

GENERATED_AT = datetime(2026, 8, 15, 14, 0, tzinfo=UTC)
UPDATED_AT = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)
LATER_AT = datetime(2026, 8, 16, 15, 0, tzinfo=UTC)
WORK = ModuleWorkRef("quillan", "synthetic_class_2026", "synthetic_essay_alpha")


def quillan_manifest_bytes(
    *,
    module_id: str = "quillan",
    class_id: str = "synthetic_class_2026",
    work_id: str = "synthetic_essay_alpha",
    record_set_id: str = "academic_results",
    revision: int = 1,
    secondary_review_state: str = "returned_without_full_review",
    secondary_minimum_status: str = "returned_without_full_review",
    scale_id: str = "synthetic_0_2_4",
    rated_unit_id: str = "body_4",
    rated_observation_id: str = "observation_native_minimum",
    evidence_standard_id: str = "standard_evidence",
    minimum_scale_label: str = "Beginning",
    minimum_scale_description: str = "Initial native evidence.",
    primary_student_id: str = "student_synthetic_001",
    secondary_student_id: str = "student_synthetic_002",
    rating_value: int = 0,
) -> bytes:
    """Build canonical bytes solely through the released producer contract."""
    from quillan.academic_result_manifest import (
        AcademicResultManifest,
        AssignmentSnapshot,
        BasicRequirements,
        DigitalSubmissionProvenance,
        FeedbackComment,
        FeedbackComposition,
        MinimumRequirementOutcome,
        MinimumRequirementPolicy,
        OverallStandardRating,
        PublishedText,
        RatingScale,
        RatingScaleLevel,
        RecordSet,
        ReviewSnapshot,
        ReviewUnit,
        ReviewUnitDefinition,
        SourceRecordSnapshot,
        StandardFeedback,
        StandardObservation,
        StudentResult,
        StudentSourceSnapshot,
        SubmissionSnapshot,
        WorkReference,
        manifest_to_canonical_json_bytes,
    )

    absent = PublishedText("absent", None)
    withheld = PublishedText("withheld", None)
    included = PublishedText("included", "Synthetic public feedback.")
    assignment_source = SourceRecordSnapshot("assignment.json", "1" * 64, "2")
    assignment = AssignmentSnapshot(
        work_id,
        "Synthetic Essay Alpha",
        "argumentative",
        "Synthetic prompt text that must not become evidence.",
        "synthetic_focus_profile",
        ("standard_claim", evidence_standard_id),
        ReviewUnitDefinition("paragraph", "Paragraph", "Paragraphs"),
        RatingScale(
            scale_id,
            (
                RatingScaleLevel(0, minimum_scale_label, minimum_scale_description),
                RatingScaleLevel(2, "Developing", "Developing native evidence."),
                RatingScaleLevel(4, "Secure", "Secure native evidence."),
            ),
        ),
        BasicRequirements(1, None, 100, None, ("claim",)),
        MinimumRequirementPolicy(True),
    )

    def sources(
        student_number: int,
        student_id: str,
    ) -> StudentSourceSnapshot:
        return StudentSourceSnapshot(
            SourceRecordSnapshot(
                f"submissions/{student_id}/submission.json",
                f"{student_number + 1:x}" * 64,
                "1",
            ),
            SourceRecordSnapshot(
                f"submissions/{student_id}/review.json",
                f"{student_number + 5:x}" * 64,
                "2",
            ),
        )

    observations = (
        StandardObservation(
            "observation_not_applicable",
            "standard_claim",
            False,
            None,
            None,
            absent,
            False,
            UPDATED_AT,
        ),
        StandardObservation(
            "observation_evidence_absent",
            evidence_standard_id,
            True,
            False,
            None,
            withheld,
            False,
            UPDATED_AT,
        ),
        StandardObservation(
            "observation_present_unrated",
            "standard_claim",
            True,
            True,
            None,
            included,
            True,
            UPDATED_AT,
        ),
        StandardObservation(
            rated_observation_id,
            evidence_standard_id,
            True,
            True,
            rating_value,
            absent,
            True,
            UPDATED_AT,
        ),
    )
    pds2 = DigitalSubmissionProvenance(
        "iss_11111111111111111111111111111111",
        "gen_22222222222222222222222222222222",
        "art_33333333333333333333333333333333",
        ("pg_44444444444444444444444444444444",),
        (),
    )
    complete = StudentResult(
        primary_student_id,
        sources(1, primary_student_id),
        SubmissionSnapshot(
            class_id,
            work_id,
            primary_student_id,
            "reviewed",
            "pds2_response_pages",
            1,
            pds2,
        ),
        ReviewSnapshot(
            class_id,
            work_id,
            "student_synthetic_001",
            "exported",
            MinimumRequirementOutcome("met", False, UPDATED_AT, withheld),
            tuple(
                ReviewUnit(
                    rated_unit_id if index == 4 else f"body_{index}",
                    index,
                    f"Body {index}",
                    "paragraph",
                    (observation,),
                )
                for index, observation in enumerate(observations, start=1)
            ),
            (
                OverallStandardRating(
                    evidence_standard_id,
                    rating_value,
                    included,
                    True,
                    UPDATED_AT,
                ),
            ),
            FeedbackComposition(
                True,
                True,
                (
                    StandardFeedback(
                        evidence_standard_id,
                        True,
                        True,
                        (rated_observation_id,),
                        (
                            FeedbackComment(
                                "comment_synthetic_001", included, True, UPDATED_AT
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    returned = StudentResult(
        secondary_student_id,
        sources(2, secondary_student_id),
        SubmissionSnapshot(
            class_id,
            work_id,
            secondary_student_id,
            "reviewed",
            "plain_paper_manual",
            None,
            None,
        ),
        ReviewSnapshot(
            class_id,
            work_id,
            "student_synthetic_002",
            cast(object, secondary_review_state),
            MinimumRequirementOutcome(
                cast(object, secondary_minimum_status),
                secondary_minimum_status == "returned_without_full_review",
                None if secondary_minimum_status == "not_checked" else UPDATED_AT,
                included,
            ),
            (),
            (),
            FeedbackComposition(False, False, ()),
        ),
    )
    manifest = AcademicResultManifest(
        "quillan_academic_result_manifest",
        "quillan_academic_result_manifest_v1",
        module_id,
        GENERATED_AT,
        RecordSet(record_set_id, revision),
        WorkReference(module_id, class_id, work_id),
        assignment_source,
        assignment,
        (complete, returned),
    )
    return manifest_to_canonical_json_bytes(manifest)


def quillan_registration() -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "quillan_academic_work_v1",
        "Synthetic Essay Alpha",
        "assignment",
        "formative",
        "active",
        GENERATED_AT,
        GENERATED_AT,
        (ModuleRecordRef("quillan", "assignment", WORK.work_id, "2"),),
    )


def quillan_publication(
    manifest_bytes: bytes,
    *,
    module_id: str = "quillan",
    publication_kind: str = "academic_result_set",
    manifest_contract: str = "quillan_academic_result_manifest_v1",
    record_set_id: str = "academic_results",
    revision: int = 1,
    capabilities: tuple[str, ...] = ("standards_ratings",),
    source_record: ModuleRecordRef | None = None,
) -> PublicationRecord:
    work = ModuleWorkRef(module_id, WORK.class_id, WORK.work_id)
    return PublicationRecord(
        "1",
        "publication_record",
        "pub_22222222222222222222222222222222",
        work,
        source_record,
        cast(object, publication_kind),
        cast(tuple[PublicationCapability, ...], capabilities),
        record_set_id,
        revision,
        manifest_contract,
        (
            f"classes/{work.class_id}/modules/{module_id}/work/{work.work_id}/"
            f"publications/{record_set_id}/{revision}.json"
        ),
        "sha256",
        hashlib.sha256(manifest_bytes).hexdigest(),
        GENERATED_AT,
        1,
        None,
    )


def quillan_withdrawal() -> PublicationWithdrawal:
    return PublicationWithdrawal(
        "1",
        "publication_withdrawal",
        "pub_22222222222222222222222222222222",
        LATER_AT,
        "Synthetic correction",
    )
