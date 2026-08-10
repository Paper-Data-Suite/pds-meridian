"""Privacy-safe ScoreForm v0.10.0 test publication builders."""

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

GENERATED_AT = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)
RECORDED_AT = datetime(2026, 8, 8, 15, 0, tzinfo=UTC)
LATER_RECORDED_AT = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", "synthetic_class_2026", "synthetic_quiz_alpha")


def scoreform_manifest_bytes(
    *,
    module_id: str = "scoreform",
    class_id: str = "synthetic_class_2026",
    work_id: str = "synthetic_quiz_alpha",
    record_set_id: str = "academic_results",
    revision: int = 1,
) -> bytes:
    """Build exact canonical bytes with the released producer model serializer."""
    from scoreform.academic_result_manifest import (
        AcademicResultManifest,
        AssignmentSnapshot,
        AssignmentSourceSnapshot,
        Attempt,
        Pds2ScanProvenance,
        PlainPaperManualProvenance,
        Question,
        RecordSet,
        Response,
        ResultsHistorySourceSnapshot,
        ReviewReference,
        ScanReviewManualProvenance,
        SourceSnapshot,
        StudentResults,
        WorkReference,
        academic_result_manifest_to_canonical_json_bytes,
    )

    questions = (
        Question(1, 1, ("standard_reading_1", "standard_close_reading")),
        Question(2, 1, ("standard_reading_2",)),
        Question(3, 1, ()),
    )
    pds2_attempt = Attempt(
        1,
        "pds2_scan",
        RECORDED_AT,
        2,
        3,
        (
            Response(1, "selected", "A", True),
            Response(2, "selected", "B", True),
            Response(3, "blank", None, False),
        ),
        Pds2ScanProvenance(
            "iss_synthetic_001",
            "gen_synthetic_001",
            "artifact_synthetic_001",
            ("page_synthetic_001",),
            ("route_synthetic_001",),
            (1,),
            "scan_synthetic_001",
            (2,),
            "scans/source/2026-08-08/synthetic_scan.pdf",
            "3" * 64,
        ),
    )
    later_manual_attempt = Attempt(
        2,
        "plain_paper_manual",
        LATER_RECORDED_AT,
        1,
        3,
        (
            Response(1, "ambiguous", None, False),
            Response(2, "selected", "B", True),
            Response(3, "selected", "C", False),
        ),
        PlainPaperManualProvenance(),
    )
    review_attempt = Attempt(
        1,
        "scan_review_manual",
        RECORDED_AT,
        1,
        3,
        (
            Response(1, "selected", "A", True),
            Response(2, "blank", None, False),
            Response(3, "ambiguous", None, False),
        ),
        ScanReviewManualProvenance(ReviewReference("failure_synthetic_001")),
    )
    manifest = AcademicResultManifest(
        "scoreform_academic_result_manifest",
        "scoreform_academic_result_manifest_v1",
        module_id,
        GENERATED_AT,
        RecordSet(record_set_id, revision),
        WorkReference(module_id, class_id, work_id),
        SourceSnapshot(
            AssignmentSourceSnapshot("assignment.json", "1" * 64),
            ResultsHistorySourceSnapshot("results.csv", "2" * 64, "2"),
        ),
        AssignmentSnapshot(
            work_id,
            "Synthetic Quiz Alpha",
            3,
            "standard_15q_abcd_v1",
            ("A", "B", "C", "D"),
            3,
            "synthetic_profile",
            questions,
        ),
        (
            StudentResults(
                "student_synthetic_001", (pds2_attempt, later_manual_attempt)
            ),
            StudentResults("student_synthetic_002", (review_attempt,)),
        ),
    )
    return academic_result_manifest_to_canonical_json_bytes(manifest)


def scoreform_registration() -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "scoreform_academic_work_v1",
        "Synthetic Quiz Alpha",
        "assignment",
        "formative",
        "active",
        GENERATED_AT,
        GENERATED_AT,
        (
            ModuleRecordRef(
                "scoreform",
                "assignment",
                "synthetic_quiz_alpha",
                None,
            ),
        ),
    )


def scoreform_publication(
    manifest_bytes: bytes,
    *,
    module_id: str = "scoreform",
    publication_kind: str = "academic_result_set",
    manifest_contract: str = "scoreform_academic_result_manifest_v1",
    record_set_id: str = "academic_results",
    revision: int = 1,
    capabilities: tuple[str, ...] = (
        "points",
        "question_evidence",
        "multiple_attempts",
    ),
    source_record: ModuleRecordRef | None = None,
) -> PublicationRecord:
    work = ModuleWorkRef(module_id, WORK.class_id, WORK.work_id)
    return PublicationRecord(
        "1",
        "publication_record",
        "pub_11111111111111111111111111111111",
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


def scoreform_withdrawal() -> PublicationWithdrawal:
    return PublicationWithdrawal(
        "1",
        "publication_withdrawal",
        "pub_11111111111111111111111111111111",
        LATER_RECORDED_AT,
        "Synthetic correction",
    )
