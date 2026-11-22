"""#126-I1: installed ScoreForm public reader + Core 29x6 synthetic classroom.

These are *not* scanned paper or a completed teacher #29/#30/#31 write.
All identifiers, scan references, manifests, and roster rows are synthetic.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.classes import ensure_class_folder, write_class_roster
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.rosters import create_roster
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleWorkRef
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
from scoreform.academic_result_reader import read_academic_result_manifest

from meridian.diagnostics import default_diagnostics_dependencies
from meridian.evidence import NativePointValue, NativeScalarValue
from meridian.guided_projection import (
    GuidedProjectionAuthorizationDeniedError,
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
)
from meridian.publication_authorization import (
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
)
from meridian.teacher_evidence_review import project_teacher_evidence_review

WORK = ModuleWorkRef("scoreform", "synthetic_class_126_i1", "synthetic_6q_126_i1")
GENERATED = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
STUDENTS = tuple(f"student_synthetic_{number:03d}" for number in range(1, 30))
FIRST = STUDENTS[0]
RETAKE = STUDENTS[1]


def _attempt(number: int, earned: int, *, student: str, origin: str) -> Attempt:
    if origin == "pds2_scan":
        provenance = Pds2ScanProvenance(
            f"iss_{student}_{number}",
            f"gen_{student}_{number}",
            f"artifact_{student}_{number}",
            (f"page_{student}_{number}",),
            (f"route_{student}_{number}",),
            (1,),
            f"scan_{student}_{number}",
            (1,),
            f"scans/source/2026-11-20/{student}_{number}.pdf",
            "3" * 64,
        )
    elif origin == "scan_review_manual":
        provenance = ScanReviewManualProvenance(
            ReviewReference(f"failure_{student}_{number}")
        )
    else:
        assert origin == "plain_paper_manual"
        provenance = PlainPaperManualProvenance()
    return Attempt(
        number,
        origin,
        GENERATED + timedelta(minutes=number),
        earned,
        6,
        tuple(
            Response(
                question,
                "selected",
                "A" if question <= earned else "B",
                question <= earned,
            )
            for question in range(1, 7)
        ),
        provenance,
    )


def _manifest() -> bytes:
    rows: list[StudentResults] = []
    for index, student in enumerate(STUDENTS):
        if index == 0:
            # Scan 0/6 followed by explicitly recorded scan-review 6/6.
            # Neither ScoreForm chronology nor review provenance certifies the cause.
            attempts = (
                _attempt(1, 0, student=student, origin="pds2_scan"),
                _attempt(2, 6, student=student, origin="scan_review_manual"),
            )
        elif index == 1:
            # Distinct retake is indistinguishable from mere chronology without
            # a teacher-reviewed academic interpretation.
            attempts = (
                _attempt(1, 4, student=student, origin="plain_paper_manual"),
                _attempt(2, 5, student=student, origin="plain_paper_manual"),
            )
        else:
            attempts = (_attempt(1, 5, student=student, origin="plain_paper_manual"),)
        rows.append(StudentResults(student, attempts))
    manifest = AcademicResultManifest(
        "scoreform_academic_result_manifest",
        "scoreform_academic_result_manifest_v1",
        "scoreform",
        GENERATED,
        RecordSet("academic_results", 1),
        WorkReference("scoreform", WORK.class_id, WORK.work_id),
        SourceSnapshot(
            AssignmentSourceSnapshot("assignment.json", "1" * 64),
            ResultsHistorySourceSnapshot("results.csv", "2" * 64, "2"),
        ),
        AssignmentSnapshot(
            WORK.work_id,
            "Synthetic Six-Question Correction Check",
            6,
            "standard_15q_abcd_v1",
            ("A", "B", "C", "D"),
            6,
            "synthetic_profile_126",
            tuple(
                Question(index, 1, ("standard_synthetic_reading",))
                for index in range(1, 7)
            ),
        ),
        tuple(rows),
    )
    return academic_result_manifest_to_canonical_json_bytes(manifest)


def _publish(root: Path, data: bytes) -> str:
    ensure_class_folder(root, WORK.class_id)
    roster = create_roster(
        WORK.class_id,
        tuple(
            {
                "student_id": student,
                "first_name": "Synthetic",
                "last_name": f"Learner{i:02d}",
                "period": "1",
            }
            for i, student in enumerate(STUDENTS, start=1)
        ),
    )
    write_class_roster(root, roster)
    module_work_dir(root, WORK).mkdir(parents=True)
    registration = register_academic_work(
        root,
        AcademicWorkRegistrationRequest(
            work=WORK,
            producer_contract_version="scoreform_academic_work_v1",
            title="Synthetic Six-Question Correction Check",
            work_kind="assignment",
            academic_intent="formative",
            lifecycle="active",
            source_records=(),
        ),
    )
    assert registration.registration.registration_revision == 1
    rel = (
        f"classes/{WORK.class_id}/modules/scoreform/work/{WORK.work_id}/"
        "publications/academic_results/1.json"
    )
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    publication = publish_manifest_revision(
        root,
        PublicationManifestRequest(
            work=WORK,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=("points", "question_evidence", "multiple_attempts"),
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version="scoreform_academic_result_manifest_v1",
            manifest_path=rel,
            academic_work_registration_revision=1,
            expected_manifest_digest=hashlib.sha256(data).hexdigest(),
        ),
    )
    rebuild_academic_catalog(root)
    return publication.publication.publication_id


def _authorize(
    root: Path, *, allowed: bool = True
) -> TeacherLocalPublicationAuthorizer:
    return TeacherLocalPublicationAuthorizer(
        root,
        "synthetic_policy_126_i1",
        "1",
        (
            PublicationAuthorizationGrant(
                class_id=WORK.class_id,
                operations=(
                    ("project_evidence", "read_projection_cache")
                    if allowed
                    else ("read_projection_cache",)
                ),
                purpose_ids=("review_evidence",),
                producer_module_ids=("scoreform",),
                publication_ids=(),
                student_ids=(),
            ),
        ),
    )


def _read(root: Path, publication_id: str):
    diag = default_diagnostics_dependencies(
        workspace_root=root, authorizer=_authorize(root)
    )
    return prepare_guided_evidence_projection(
        root,
        WORK,
        publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diag),
    )


@pytest.fixture
def native_classroom(tmp_path: Path):
    data = _manifest()
    root = tmp_path / "synthetic_workspace"
    root.mkdir()
    pub = _publish(root, data)
    return root, pub, data


def test_native_scoreform_reader_29_students_31_attempts_186_responses() -> None:
    manifest = read_academic_result_manifest(_manifest())
    assert manifest.assignment.question_count == 6
    assert len(manifest.students) == 29
    assert sum(len(student.attempts) for student in manifest.students) == 31
    response_count = sum(
        len(attempt.responses)
        for student in manifest.students
        for attempt in student.attempts
    )
    assert response_count == 186
    first = manifest.students[0]
    assert first.student_id == FIRST
    scores = [
        (attempt.attempt_number, attempt.points_earned, attempt.points_possible)
        for attempt in first.attempts
    ]
    assert scores == [(1, 0, 6), (2, 6, 6)]
    assert first.attempts[0].result_origin == "pds2_scan"
    assert first.attempts[1].result_origin == "scan_review_manual"
    assert [a.points_earned for a in manifest.students[1].attempts] == [4, 5]
    assert manifest.record_set.revision == 1


def test_installed_core_publication_preserves_native_history(
    native_classroom,
) -> None:
    root, publication_id, data = native_classroom
    prepared = _read(root, publication_id)
    projected = prepared.authorized.stored.snapshot.inventory.items
    source = prepared.authorized.current_context.publication
    assert hashlib.sha256(data).hexdigest() == source.manifest_digest
    assert len(projected) == 31 * (2 + 2 * 6)
    assert len({item.item_id for item in projected}) == len(projected)
    native_attempts = tuple(
        item
        for item in projected
        if item.subject is not None
        and item.subject.student_id == FIRST
        and item.result_kind == "attempt_points"
    )
    scores = [
        (item.target.sequence, item.value.earned, item.value.possible)
        for item in native_attempts
    ]
    assert scores == [(1, 0, 6), (2, 6, 6)]
    assert all(isinstance(item.value, NativePointValue) for item in native_attempts)
    review_failure = tuple(
        ref
        for ref in native_attempts[1].provenance.native.references
        if ref.kind == "review_failure"
    )
    assert len(review_failure) == 1
    origins = tuple(
        item.value.value
        for item in projected
        if item.subject is not None
        and item.subject.student_id == FIRST
        and item.result_kind == "result_origin"
    )
    assert origins == ("pds2_scan", "scan_review_manual")
    assert all(
        isinstance(item.value, NativeScalarValue)
        for item in projected
        if item.result_kind == "result_origin"
    )
    # Review-only projection cannot author a canonical #30/#31 current pointer.
    attempt_store = root / "classes" / WORK.class_id / "modules" / "meridian"
    assert not (attempt_store / "attempts" / "s").exists()


def test_teacher_review_sees_all_29_authorized_students(
    native_classroom,
) -> None:
    root, pub, _ = native_classroom
    prepared = _read(root, pub)
    review = project_teacher_evidence_review(root, prepared)
    assert review.class_id == WORK.class_id
    assert review.publication_id == pub
    assert len(review.students) == 29
    assert {student.student_id for student in review.students} == set(STUDENTS)
    correction = next(
        student for student in review.students if student.student_id == FIRST
    )
    assert len(correction.items) == 2 * (2 + 2 * 6)
    # No teacher #30 selection or #31 relationship has been authored by inspection.
    attempt_store = root / "classes" / WORK.class_id / "modules" / "meridian"
    assert not (attempt_store / "attempts" / "s").exists()


def test_manifest_unchanged_and_retake_preserved(
    native_classroom,
) -> None:
    root, pub, data = native_classroom
    before = hashlib.sha256(data).hexdigest()
    prepared = _read(root, pub)
    projected = prepared.authorized.stored.snapshot.inventory.items
    scores = tuple(
        (item.target.sequence, item.value.earned)
        for item in projected
        if item.subject is not None
        and item.subject.student_id == RETAKE
        and item.result_kind == "attempt_points"
    )
    assert scores == ((1, 4), (2, 5))
    manifest_path = (
        module_work_dir(root, WORK) / "publications" / "academic_results" / "1.json"
    )
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == before
    assert pub == prepared.authorized.current_context.publication.publication_id


def test_missing_permission_blocks_native_teacher_review(
    native_classroom,
) -> None:
    root, pub, _ = native_classroom
    diagnostics = default_diagnostics_dependencies(
        workspace_root=root,
        authorizer=_authorize(root, allowed=False),
    )
    with pytest.raises(GuidedProjectionAuthorizationDeniedError):
        prepare_guided_evidence_projection(
            root,
            WORK,
            pub,
            dependencies=default_guided_projection_dependencies(
                diagnostics=diagnostics
            ),
        )
