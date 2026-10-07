"""Installed ScoreForm 0.12.1 punctuation-bearing identity acceptance."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib import metadata
from typing import cast

from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationCapability, PublicationRecord
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef
from scoreform.academic_result_manifest import (
    AcademicResultManifest,
    AssignmentSnapshot,
    AssignmentSourceSnapshot,
    Attempt,
    PlainPaperManualProvenance,
    Question,
    RecordSet,
    Response,
    ResultsHistorySourceSnapshot,
    SourceSnapshot,
    StudentResults,
    WorkReference,
    academic_result_manifest_to_canonical_json_bytes,
)
from scoreform.academic_result_reader import read_academic_result_manifest

from meridian.adapters import AdapterProjectionRequest, AdapterRegistry
from meridian.evidence import NativePointValue
from meridian.scoreform_adapter import (
    SCOREFORM_READER_VERSION,
    ScoreFormAcademicResultAdapter,
)

PROFILE_ID = "english12.njsls.2023"
STANDARD_IDS = (
    "njsls-ela.TS.11-12.4",
    "njsls-ela.NW.11-12.3.D",
    "njsls-ela:RL.TS.11-12.4",
    "njsls-ela:W.NW.11-12.3.D",
)
GENERATED_AT = datetime(2026, 10, 6, 21, 0, tzinfo=UTC)
LATER_AT = datetime(2026, 10, 6, 22, 0, tzinfo=UTC)
WORK = ModuleWorkRef("scoreform", "issue107_class", "issue107_quiz")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _manifest_bytes() -> bytes:
    questions = (
        Question(1, 1, STANDARD_IDS),
        Question(2, 1, ()),
    )
    attempts = (
        Attempt(
            1,
            "plain_paper_manual",
            GENERATED_AT,
            2,
            2,
            (
                Response(1, "selected", "A", True),
                Response(2, "selected", "B", True),
            ),
            PlainPaperManualProvenance(),
        ),
        Attempt(
            2,
            "plain_paper_manual",
            LATER_AT,
            0,
            2,
            (
                Response(1, "blank", None, False),
                Response(2, "ambiguous", None, False),
            ),
            PlainPaperManualProvenance(),
        ),
    )
    manifest = AcademicResultManifest(
        "scoreform_academic_result_manifest",
        "scoreform_academic_result_manifest_v1",
        "scoreform",
        GENERATED_AT,
        RecordSet("academic_results", 1),
        WorkReference(WORK.module_id, WORK.class_id, WORK.work_id),
        SourceSnapshot(
            AssignmentSourceSnapshot("assignment.json", "1" * 64),
            ResultsHistorySourceSnapshot("results.csv", "2" * 64, "2"),
        ),
        AssignmentSnapshot(
            WORK.work_id,
            "Issue 107 punctuation identity qualification",
            2,
            "standard_15q_abcd_v1",
            ("A", "B", "C", "D"),
            2,
            PROFILE_ID,
            questions,
        ),
        (StudentResults("issue107_student", attempts),),
    )
    return academic_result_manifest_to_canonical_json_bytes(manifest)


def _request(manifest_bytes: bytes) -> AdapterProjectionRequest:
    registration = AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "scoreform_academic_work_v1",
        "Issue 107 punctuation identity qualification",
        "assignment",
        "formative",
        "active",
        GENERATED_AT,
        GENERATED_AT,
        (
            ModuleRecordRef(
                "scoreform",
                "assignment",
                WORK.work_id,
                None,
            ),
        ),
    )
    publication = PublicationRecord(
        "1",
        "publication_record",
        "pub_10710710710710710710710710710710",
        WORK,
        None,
        "academic_result_set",
        cast(
            tuple[PublicationCapability, ...],
            ("points", "question_evidence", "multiple_attempts"),
        ),
        "academic_results",
        1,
        "scoreform_academic_result_manifest_v1",
        (
            "classes/issue107_class/modules/scoreform/work/issue107_quiz/"
            "publications/academic_results/1.json"
        ),
        "sha256",
        hashlib.sha256(manifest_bytes).hexdigest(),
        GENERATED_AT,
        1,
        None,
    )
    return AdapterProjectionRequest(publication, registration, None, manifest_bytes)


def main() -> None:
    _require(metadata.version("scoreform") == "0.12.1", "ScoreForm version changed.")
    _require(SCOREFORM_READER_VERSION == "0.12.1", "Adapter version changed.")

    source = _manifest_bytes()
    source_before = bytes(source)
    digest_before = hashlib.sha256(source).hexdigest()
    parsed = read_academic_result_manifest(source)

    _require(
        parsed.contract_version == "scoreform_academic_result_manifest_v1",
        "Manifest contract changed.",
    )
    _require(
        parsed.assignment.standards_profile_id == PROFILE_ID,
        "ScoreForm changed the Standards Profile identity.",
    )
    _require(
        parsed.assignment.questions[0].standard_ids == STANDARD_IDS,
        "ScoreForm changed the ordered Standard identities.",
    )
    _require(
        academic_result_manifest_to_canonical_json_bytes(parsed) == source,
        "ScoreForm reader did not preserve canonical manifest evidence.",
    )

    inventory = AdapterRegistry((ScoreFormAcademicResultAdapter(),)).invoke(
        _request(source),
        metadata.version,
    )

    _require(source == source_before, "Meridian mutated source manifest bytes.")
    _require(
        hashlib.sha256(source).hexdigest() == digest_before,
        "Meridian changed source manifest evidence.",
    )
    _require(len(inventory.items) == 12, "Meridian dropped native attempt evidence.")
    _require(
        all(
            item.provenance.projection.producer_reader_version == "0.12.1"
            for item in inventory.items
        ),
        "Projection identity is not the exact ScoreForm reader.",
    )

    question_one = tuple(
        item
        for item in inventory.items
        if item.target.target_id == "question_1"
    )
    _require(len(question_one) == 4, "Question evidence was selected or dropped.")
    _require(
        all(item.target.standard_ids == STANDARD_IDS for item in question_one),
        "Meridian rewrote producer-native Standard identities.",
    )
    _require(
        all(
            any(
                reference.kind == "standards_profile"
                and reference.identifier == PROFILE_ID
                for reference in item.provenance.native.references
            )
            for item in inventory.items
        ),
        "Meridian did not preserve the producer-native Standards Profile identity.",
    )

    points = tuple(
        item.value for item in inventory.items if item.result_kind == "attempt_points"
    )
    _require(
        points == (NativePointValue(2, 2), NativePointValue(0, 2)),
        "Meridian selected newest, highest, best, or official attempt evidence.",
    )
    _require(
        all(item.eligibility.status == "unevaluated" for item in inventory.items),
        "Standards alignment inferred evidence eligibility.",
    )
    _require(
        not any(
            token in item.result_kind
            for item in inventory.items
            for token in ("proficiency", "mastery", "grade", "official", "current")
        ),
        "Standards alignment inferred downstream policy or Grade authority.",
    )


if __name__ == "__main__":
    main()
