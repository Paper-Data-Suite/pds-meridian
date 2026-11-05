"""#124 E2G3O9: installed native ScoreForm/Quillan -> Meridian teacher setup.

All student data is synthetic. These tests are enabled only in a quarantined
five-wheel install, never in an ordinary source-tree pytest collection.
The producer's *own* manifest builder and publication controller are called.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.publication_storage import get_current_publication_record
from pds_core.routes import class_metadata_path
from pds_core.routing_models import ModuleWorkRef
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    STAMP,
    YEAR,
    _all_bytes,
)
from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey

from meridian.assessment_setup_choices import load_named_assessment_choices
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import get_current_grade_item_revision
from meridian.teacher_action_receipts import TeacherActionReceiptStore

pytestmark = pytest.mark.skipif(
    os.environ.get("PDS_ISSUE124_NATIVE_TEST") != "1",
    reason="Requires the isolated five-wheel E2G3O9 native-producer runner",
)


def _native_workspace(tmp_path: Path) -> Path:
    """Fresh canonical class/calendar, no pre-registered producer work.

    The existing E2G3K _workspace() deliberately registers the `scene`
    ScoreForm fixture. Native publication must instead own the registration
    itself, and discovery must have exactly the work it publishes.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    write_class_metadata(
        class_metadata_path(root, CLASS),
        ClassMetadata(CLASS, YEAR, STAMP, STAMP, {}),
    )
    write_academic_period_calendar(
        root,
        AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=YEAR,
            calendar_revision=1,
            created_at=STAMP,
            updated_at=STAMP,
            periods=(
                AcademicPeriod(
                    period_id="mp1",
                    period_type="marking_period",
                    label="Marking Period 1",
                    start_date=date(2026, 9, 8),
                    end_date=date(2026, 11, 13),
                    parent_period_id=None,
                    sequence=1,
                    lifecycle="active",
                ),
            ),
        ),
        expected_current_revision=None,
    )
    return root


def _scoreform_publication(root: Path) -> tuple[ModuleWorkRef, str]:
    """Generate real ScoreForm manifest from 29 students x six questions."""
    from scoreform.academic_result_manifest import manifest_from_json_bytes
    from scoreform.academic_result_manifest_generation import (
        generate_academic_result_manifest,
    )
    from scoreform.academic_result_publication import publish_scoreform_academic_results
    from scoreform.academic_work_registration import register_scoreform_academic_work
    from scoreform.page_scoring import ScoredAnswer
    from scoreform.results import ScoreFormRoutedResult, export_scoreform_result_models
    from scoreform.work_paths import scoreform_work_paths

    work = ModuleWorkRef("scoreform", CLASS, "scene")
    paths = scoreform_work_paths(root, CLASS, work.work_id)
    paths.work_root.mkdir(parents=True, exist_ok=True)
    questions = range(1, 7)
    paths.assignment_path.write_text(
        json.dumps(
            {
                "assignment_id": work.work_id,
                "title": "Synthetic Six-Question Scene Assessment",
                "question_count": 6,
                "choices": ["A", "B", "C", "D"],
                "layout_id": "standard_15q_abcd_v1",
                "answer_key": {str(q): "A" for q in questions},
                "standards": {str(q): [] for q in questions},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    records = []
    for student_index in range(1, 30):
        student_id = f"student{student_index:03}"
        # Alternate a few deliberate wrong answers; no actual student records.
        answers = tuple(
            ScoredAnswer(
                q,
                "B" if (student_index + q) % 7 == 0 else "A",
                (student_index + q) % 7 != 0,
            )
            for q in questions
        )
        records.append(
            ScoreFormRoutedResult(
                result_origin="plain_paper_manual",
                class_id=CLASS,
                assignment_id=work.work_id,
                student_id=student_id,
                first_name="Synthetic",
                last_name="Learner",
                period="1",
                page_display="manual",
                score=sum(int(item.correct) for item in answers),
                total_points=6,
                answers=answers,
                source_file="plain_paper_manual_entry",
            )
        )
    assert export_scoreform_result_models(tuple(records), workspace_root=root).succeeded
    registration = register_scoreform_academic_work(
        root, CLASS, work.work_id, academic_intent="summative", lifecycle="active"
    )
    assert registration is not None
    generated = generate_academic_result_manifest(root, CLASS, work.work_id)
    published = publish_scoreform_academic_results(
        root, CLASS, work.work_id, manifest_revision=generated.revision
    )
    assert published.publication.manifest_digest == generated.sha256
    assert published.publication.capabilities == (
        "multiple_attempts",
        "points",
        "question_evidence",
    )
    manifest_file = root / published.publication.manifest_path
    raw_manifest = manifest_file.read_bytes()
    assert hashlib.sha256(raw_manifest).hexdigest() == generated.sha256
    native_manifest = manifest_from_json_bytes(raw_manifest)
    assert len(native_manifest.students) == 29
    assert len(native_manifest.assignment.questions) == 6
    assert published.compatibility.compatible
    return work, published.publication.publication_id


def _quillan_publication(root: Path) -> tuple[ModuleWorkRef, str]:
    """Produce an actual Quillan assignment, student review and manifest."""
    from pds_core.standards import (
        StandardDefinition,
        StandardsLibrary,
        StandardsProfile,
        write_workspace_standards_library,
    )
    from quillan.academic_result_manifest_generation import (
        generate_academic_result_manifest,
    )
    from quillan.academic_result_publication import publish_quillan_academic_results
    from quillan.academic_work_registration import register_quillan_academic_work
    from quillan.review_record import build_empty_review_record
    from quillan.work_paths import (
        quillan_work_ref,
        review_record_path,
        submission_manifest_path,
    )

    work = quillan_work_ref(CLASS, "essay_native")
    timestamp = "2026-06-22T14:20:00+00:00"
    library = StandardsLibrary(
        standards=(
            StandardDefinition(
                standard_id="synthetic:W.A",
                code="W.A",
                source="synthetic",
                short_name="Synthetic Writing",
                description="Non-student synthetic writing standard",
            ),
        ),
        profiles=(
            StandardsProfile(
                profile_id="synthetic_profile", standards=("synthetic:W.A",)
            ),
        ),
    )
    write_workspace_standards_library(root, library)
    assignment = {
        "schema_version": "2",
        "module": "quillan",
        "record_type": "assignment",
        "assignment_id": work.work_id,
        "title": "Synthetic Quillan Essay",
        "class_ids": [CLASS],
        "writing_type": "argument",
        "student_prompt": "Write a synthetic argument.",
        "standards_profile_id": "synthetic_profile",
        "focus_standard_ids": ["synthetic:W.A"],
        "review_unit": {
            "type": "paragraph",
            "singular_label": "paragraph",
            "plural_label": "paragraphs",
        },
        "rating_scale": {
            "scale_id": "standards_2_level",
            "levels": [
                {"value": 1, "label": "Developing", "description": "Limited evidence."}
            ],
        },
        "basic_requirements": {"paragraphs_min": 5},
        "minimum_requirement_policy": {"allow_return_without_full_review": True},
        "created_at": timestamp,
        "updated_at": timestamp,
        "module_details": {},
    }
    root_assignment = (
        root
        / "classes"
        / CLASS
        / "modules"
        / "quillan"
        / "work"
        / work.work_id
        / "assignment.json"
    )
    root_assignment.parent.mkdir(parents=True, exist_ok=True)
    root_assignment.write_text(json.dumps(assignment, sort_keys=True), encoding="utf-8")
    student_id = "student001"
    submission = {
        "schema_version": "1",
        "module": "quillan",
        "record_type": "submission_manifest",
        "class_id": CLASS,
        "assignment_id": work.work_id,
        "student_id": student_id,
        "expected_pages": None,
        "submission_state": "unreviewed",
        "pages": [],
        "created_at": timestamp,
        "updated_at": timestamp,
        "module_details": {
            "submission_entry_method": "plain_paper_manual",
            "physical_evidence_status": "teacher_has_external_plain_paper",
            "created_by_workflow": "plain_paper_submission",
        },
    }
    path = submission_manifest_path(root, work, student_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(submission, sort_keys=True), encoding="utf-8")
    review = build_empty_review_record(
        class_id=CLASS,
        assignment_id=work.work_id,
        student_id=student_id,
        created_at=timestamp,
    )
    path = review_record_path(root, work, student_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review, sort_keys=True), encoding="utf-8")
    register_quillan_academic_work(
        root, CLASS, work.work_id, academic_intent="summative", lifecycle="active"
    )
    generated = generate_academic_result_manifest(root, CLASS, work.work_id)
    published = publish_quillan_academic_results(
        root, CLASS, work.work_id, manifest_revision=generated.revision
    )
    assert published.publication.capabilities == ("standards_ratings",)
    assert published.publication.manifest_digest == generated.sha256
    manifest_file = root / published.publication.manifest_path
    assert hashlib.sha256(manifest_file.read_bytes()).hexdigest() == generated.sha256
    return work, published.publication.publication_id


@pytest.mark.parametrize("producer", ("scoreform", "quillan"))
def test_native_producer_manifest_to_verified_meridian_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, producer: str
) -> None:
    root = _native_workspace(tmp_path)
    work, publication_id = (
        _scoreform_publication(root)
        if producer == "scoreform"
        else _quillan_publication(root)
    )
    named = load_named_assessment_choices(
        root, class_id=CLASS, school_year="2026-2027", period_id="mp1"
    )
    assert len(named.items) == 1
    assert named.items[0].publication_state == "current_results_verified"
    assert named.items[0].candidate.work == work
    assert named.items[0].candidate.publication_id == publication_id
    answers = (
        "1",
        "1",
        "S",
        "1",
        "Scene" if producer == "scoreform" else "Quillan Essay",
        "",
        ACTOR.actor_id,
        "APPLY",
        "",
    )
    journey = _journey(root, monkeypatch, answers)
    assert journey.prompts.count("Confirmation: ") == 1
    assert "Assessment relationship verified current." in journey.output
    assert journey.session.active_work == work
    assert journey.session.active_publication_id == publication_id
    grade_id = journey.session.active_grade_item_id
    assert grade_id is not None
    assert get_current_grade_item_revision(root, CLASS, grade_id) == 1
    selected = load_current_grade_item_membership_decision(root, CLASS, grade_id, work)
    assert selected is not None and selected.decision.decision == "included"
    assert selected.decision.academic_period is not None
    assert selected.decision.academic_period.period.period_id == "mp1"
    assert (
        get_current_publication_record(
            root, work, "academic_result_set", "academic_results"
        )
        is not None
    )
    receipts = TeacherActionReceiptStore(root, CLASS).list_receipts()
    assert len(receipts) == 2
    correlations = AssessmentSetupCorrelationStore(root, CLASS).list_records()
    assert len(correlations) == 1
    assert correlations[0].grade_action_id is not None
    assert correlations[0].membership_action_id is not None
    before = _all_bytes(root)
    reopened = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert reopened.prompts.count("Confirmation: ") == 0
    assert reopened.session.active_publication_id == publication_id
    assert _all_bytes(root) == before
