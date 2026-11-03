"""#124 E2G3K: live canonical Grade Item + membership restart state ladder.

Everything is synthetic and stored beneath pytest's temporary workspace.
Only fixture setup writes academic data; the inspected recovery services do not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.academic_work_registration_storage import (
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_correlation import create_assessment_setup_correlation
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import inspect_assessment_setup_recovery
from meridian.assessment_setup_restart import (
    inspect_restart_context_candidate,
    inspect_stored_assessment_setup_restart,
)
from meridian.grade_item_membership_storage import (
    grade_item_membership_revision_digest_path,
    list_grade_item_membership_revisions,
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    get_current_grade_item_revision,
    list_grade_item_revisions,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.teacher_action_contract import TeacherActionActor

CLASS = "english12"
YEAR = "2026-2027"
GRADE = "gi_scene"
WORK = ModuleWorkRef("scoreform", CLASS, "scene")
STAMP = datetime(2026, 9, 8, 12, tzinfo=UTC)
ACTOR = TeacherActionActor("teacher_local", "b" * 64, "saved")


def _registration(revision: int = 1) -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=WORK,
        registration_revision=revision,
        producer_contract_version="v1",
        title="Synthetic Scene Study",
        work_kind="assessment",
        academic_intent="summative",
        lifecycle="active",
        created_at=STAMP,
        updated_at=STAMP + timedelta(minutes=revision - 1),
        source_records=(),
    )


def _workspace(tmp_path: Path) -> Path:
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
    module_work_dir(root, WORK).mkdir(parents=True)
    write_academic_work_registration(
        root, _registration(), expected_current_revision=None
    )
    rebuild_academic_catalog(root)
    return root


def _preview() -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind="create_and_link",
        work=WORK,
        class_id=CLASS,
        school_year=YEAR,
        registration_revision=1,
        registration_lifecycle="active",
        assessment_title="Synthetic Scene Study",
        producer_label="ScoreForm",
        publication_label="No published results indexed",
        publication_id=None,
        grade_item_id=GRADE,
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=None,
        marking_period_id="mp1",
        marking_period_label="Marking Period 1",
        calendar_revision=1,
        actor_attribution=ACTOR.actor_id,
        rationale=None,
        operations=(),
        weighting_message="Weighting not configured",
        review_sha256="a" * 64,
    )


def _grade_written(root: Path) -> str:
    stored = write_grade_item_revision(
        root,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS,
            grade_item_id=GRADE,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Scene Grade",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=STAMP,
            revised_at=STAMP,
        ),
    ).stored
    return stored.revision_sha256


def _membership_written(root: Path, grade_digest: str) -> None:
    write_grade_item_membership_revision(
        root,
        GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=CLASS,
            grade_item_id=GRADE,
            grade_item_revision=1,
            grade_item_revision_sha256=grade_digest,
            work_reference=GradeItemWorkReference(work=WORK, registration_revision=1),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(school_year=YEAR, period_id="mp1"),
                calendar_revision=1,
            ),
            actor_id=ACTOR.actor_id,
            rationale=None,
            decided_at=STAMP + timedelta(hours=1),
        ),
    )


def _all_bytes(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def _state(root: Path) -> str:
    before = _all_bytes(root)
    inspection = inspect_assessment_setup_recovery(root, _preview())
    assert _all_bytes(root) == before
    assert not inspection.can_resume_without_review
    return inspection.state


def test_real_canonical_composite_state_ladder(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    assert _state(root) == "pristine"
    digest = _grade_written(root)
    assert _state(root) == "grade_item_written_not_selected"
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    assert _state(root) == "grade_item_selected_link_missing"
    _membership_written(root, digest)
    assert _state(root) == "membership_written_not_selected"
    select_grade_item_membership_revision(
        root, CLASS, GRADE, WORK, 1, expected_current_membership_revision=None
    )
    assert _state(root) == "ready_verified"
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_reopened_canonical_ready_state_never_writes_again(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    digest = _grade_written(root)
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    _membership_written(root, digest)
    select_grade_item_membership_revision(
        root, CLASS, GRADE, WORK, 1, expected_current_membership_revision=None
    )
    before = _all_bytes(root)
    assert _state(Path(str(root))) == "ready_verified"
    assert _state(Path(str(root))) == "ready_verified"
    assert _all_bytes(root) == before


def test_correlation_restarts_as_hint_not_write_authority(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    preview = _preview()
    correlation = create_assessment_setup_correlation(root, preview, ACTOR)
    store = AssessmentSetupCorrelationStore(root, CLASS)
    assert store.create_reviewed(correlation).disposition == "created"
    reloaded = AssessmentSetupCorrelationStore(root, CLASS)
    assert reloaded.list_records() == (correlation,)
    hint = inspect_restart_context_candidate(
        root, CLASS, WORK.module_id, WORK.work_id, ACTOR
    )
    assert hint.disposition == "unique_candidate"
    assert hint.intent_sha256 == correlation.intent_sha256
    assert not hint.may_resume_automatically
    assert not hint.may_select_academic_record
    before = _all_bytes(root)
    inspection = inspect_stored_assessment_setup_restart(root, preview, ACTOR)
    assert inspection.disposition == "reviewed_not_started"
    assert not inspection.may_resume_automatically
    assert not inspection.may_create_new_action
    assert not inspection.may_select_academic_record
    assert _all_bytes(root) == before


def test_unbound_grade_write_does_not_gain_composite_resume(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    preview = _preview()
    correlation = create_assessment_setup_correlation(root, preview, ACTOR)
    AssessmentSetupCorrelationStore(root, CLASS).create_reviewed(correlation)
    _grade_written(root)
    assert _state(root) == "grade_item_written_not_selected"
    before = _all_bytes(root)
    result = inspect_stored_assessment_setup_restart(root, preview, ACTOR)
    assert result.disposition == "requires_review"
    assert not result.may_resume_automatically
    assert not result.may_select_academic_record
    assert _all_bytes(root) == before


def test_registration_revision_drift_blocks_old_review(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    digest = _grade_written(root)
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    _membership_written(root, digest)
    select_grade_item_membership_revision(
        root, CLASS, GRADE, WORK, 1, expected_current_membership_revision=None
    )
    assert _state(root) == "ready_verified"
    write_academic_work_registration(
        root, _registration(2), expected_current_revision=1
    )
    rebuild_academic_catalog(root)
    assert _state(root) == "source_changed"
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_corrupt_membership_digest_never_reports_ready(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    digest = _grade_written(root)
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    _membership_written(root, digest)
    select_grade_item_membership_revision(
        root, CLASS, GRADE, WORK, 1, expected_current_membership_revision=None
    )
    assert _state(root) == "ready_verified"
    sidecar = grade_item_membership_revision_digest_path(root, CLASS, GRADE, WORK, 1)
    sidecar.write_bytes(("0" * 64 + "\n").encode("ascii"))
    assert _state(root) == "inspection_unavailable"
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1


@pytest.mark.parametrize("stage", ["grade", "member"])
def test_incomplete_composite_never_claims_ready(tmp_path: Path, stage: str) -> None:
    root = _workspace(tmp_path)
    digest = _grade_written(root)
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    if stage == "member":
        _membership_written(root, digest)
    assert _state(root) != "ready_verified"
