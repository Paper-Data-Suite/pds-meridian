"""#124 E2G3L: real original #122 receipts + correlated canonical restart.

The workspace and all records are synthetic. Tests use the existing #122
selection-only restart ports; no domain writers are installed in recovery.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.academic_work_registration_storage import write_academic_work_registration
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    GRADE,
    STAMP,
    WORK,
    YEAR,
    _all_bytes,
    _preview,
    _registration,
    _workspace,
)

from meridian.assessment_setup_correlation import (
    bind_correlation_action,
    create_assessment_setup_correlation,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_exact_resume import (
    resume_original_assessment_setup_selection,
)
from meridian.assessment_setup_original_receipt import (
    inspect_original_assessment_setup_receipt,
)
from meridian.assessment_setup_restart import inspect_stored_assessment_setup_restart
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    load_current_grade_item_membership_decision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
    grade_item_membership_decision_to_json_bytes,
)
from meridian.grade_item_storage import (
    get_current_grade_item_revision,
    list_grade_item_revisions,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GradeItemRevision,
    GradeItemWorkReference,
    grade_item_revision_to_json_bytes,
)
from meridian.teacher_action_contract import (
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    _calendar_digest,
    _identity,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_grade_item import _RestartGradeItemPort
from meridian.teacher_action_restart_membership import _RestartMembershipPort


def _actor_check(_actor: object) -> None:
    """Synthetic actor verification; exact identity is bound by the receipt."""


def _grade_candidate() -> GradeItemRevision:
    return GradeItemRevision(
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
    )


def _membership_candidate(grade_sha256: str) -> GradeItemMembershipDecision:
    return GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS,
        grade_item_id=GRADE,
        grade_item_revision=1,
        grade_item_revision_sha256=grade_sha256,
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
    )


def _basis(family: str, identity: str, sha256: str) -> tuple[TeacherActionBasis, ...]:
    source = (
        "grade_item_candidate" if family == "grade_item" else "membership_candidate"
    )
    return (
        TeacherActionBasis(
            "actor_profile", _identity(ACTOR.actor_id), ACTOR.profile_sha256
        ),
        TeacherActionBasis("canonical_source", identity, _identity(source, sha256)),
    )


def _original_grade(root: Path) -> tuple[PreparedGuidedAction, str]:
    """Claim, journal, author exact once, and bind original action before restart."""
    review = _preview()
    correlations = AssessmentSetupCorrelationStore(root, CLASS)
    baseline = create_assessment_setup_correlation(root, review, ACTOR)
    assert correlations.create_reviewed(baseline).disposition == "created"
    candidate = _grade_candidate()
    digest = hashlib.sha256(grade_item_revision_to_json_bytes(candidate)).hexdigest()
    identity = _identity("grade_item", CLASS, GRADE)
    action_preview = TeacherActionPreview(
        action_id="1" * 32,
        kind="grade_item",
        scope=TeacherActionScope(_identity("workspace", str(root)), CLASS, GRADE),
        actor=ACTOR,
        target=TeacherActionTarget("grade_item", identity, 1, digest, None, None),
        basis=_basis("grade_item", identity, digest),
        reviewed_decision_sha256=digest,
    )
    journal = TeacherActionReceiptStore(root, CLASS)
    prepared = journal.prepare(action_preview)
    port = _RestartGradeItemPort(root, prepared, _actor_check)
    original = PreparedGuidedAction(action_preview, port, journal)
    bound = bind_correlation_action(baseline, original, family="grade_item")
    correlations.advance_exact(expected=baseline, updated=bound)
    stored = write_grade_item_revision(root, candidate).stored
    assert stored.revision_sha256 == digest
    journal.record_checkpoint(
        action_preview,
        expected_generation=prepared.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    return original, digest


def _original_membership(root: Path, grade_digest: str) -> PreparedGuidedAction:
    """Journal the original membership action before its immutable write."""
    decision = _membership_candidate(grade_digest)
    digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(decision)
    ).hexdigest()
    identity = _identity("membership", CLASS, GRADE, WORK.module_id, WORK.work_id)
    action_preview = TeacherActionPreview(
        action_id="2" * 32,
        kind="grade_item_membership",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(root)),
            class_id=CLASS,
            grade_item_id=GRADE,
            school_year=YEAR,
            academic_period_id="mp1",
            calendar_sha256=_calendar_digest(root, YEAR, 1),
            work_identity_sha256=_identity("work", CLASS, WORK.module_id, WORK.work_id),
        ),
        actor=ACTOR,
        target=TeacherActionTarget(
            "grade_item_membership", identity, 1, digest, None, None
        ),
        basis=_basis("grade_item_membership", identity, digest),
        reviewed_decision_sha256=digest,
    )
    journal = TeacherActionReceiptStore(root, CLASS)
    prepared = journal.prepare(action_preview)
    port = _RestartMembershipPort(root, prepared, _actor_check)
    original = PreparedGuidedAction(action_preview, port, journal)
    correlations = AssessmentSetupCorrelationStore(root, CLASS)
    base = create_assessment_setup_correlation(root, _preview(), ACTOR)
    grade_bound = correlations.load(base.intent_sha256)
    assert grade_bound is not None and grade_bound.grade_action_id == "1" * 32
    member_bound = bind_correlation_action(
        grade_bound, original, family="grade_item_membership"
    )
    correlations.advance_exact(expected=grade_bound, updated=member_bound)
    assert (
        write_grade_item_membership_revision(root, decision).stored.decision_sha256
        == digest
    )
    journal.record_checkpoint(
        action_preview,
        expected_generation=prepared.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    return original


def test_original_grade_receipt_and_correlation_verify_without_mutation(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    original, digest = _original_grade(root)
    before = _all_bytes(root)
    restart = inspect_stored_assessment_setup_restart(root, _preview(), ACTOR)
    witness = inspect_original_assessment_setup_receipt(root, _preview(), ACTOR)
    assert restart.disposition == "original_grade_action_pending"
    assert restart.canonical_state == "grade_item_written_not_selected"
    assert restart.grade_action_id == original.preview.action_id
    assert witness.disposition == "original_receipt_verified"
    assert witness.original_preview == original.preview
    assert get_current_grade_item_revision(root, CLASS, GRADE) is None
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert original.preview.target.candidate_sha256 == digest
    assert not restart.may_resume_automatically
    assert not restart.may_select_academic_record
    assert _all_bytes(root) == before


def test_original_grade_cancellation_and_wrong_id_are_zero_write(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    original, _ = _original_grade(root)
    before = _all_bytes(root)
    cancelled = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=original, confirmation="B"
    )
    assert cancelled.disposition == "cancelled"
    assert _all_bytes(root) == before
    wrong_id = PreparedGuidedAction(
        replace(original.preview, action_id="f" * 32), original.port, original.store
    )
    rejected = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=wrong_id, confirmation="RESUME"
    )
    assert rejected.disposition == "requires_review"
    assert rejected.reason == "original_action_binding_mismatch"
    assert _all_bytes(root) == before


def test_explicit_original_grade_resume_only_selects_existing_revision(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    original, digest = _original_grade(root)
    outcome = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=original, confirmation="RESUME"
    )
    assert outcome.disposition == "original_grade_selected"
    assert outcome.action_result is not None and outcome.action_result.succeeded
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert original.preview.target.candidate_sha256 == digest
    after = inspect_stored_assessment_setup_restart(root, _preview(), ACTOR)
    assert after.disposition == "original_membership_action_pending"
    assert after.canonical_state == "grade_item_selected_link_missing"
    before_retry = _all_bytes(root)
    retry = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=original, confirmation="RESUME"
    )
    assert retry.disposition == "requires_review"
    assert _all_bytes(root) == before_retry


def test_original_membership_resume_reaches_ready_without_duplicate_revision(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    grade, grade_digest = _original_grade(root)
    grade_result = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=grade, confirmation="RESUME"
    )
    assert grade_result.disposition == "original_grade_selected"
    membership = _original_membership(root, grade_digest)
    before = _all_bytes(root)
    restart = inspect_stored_assessment_setup_restart(root, _preview(), ACTOR)
    witness = inspect_original_assessment_setup_receipt(root, _preview(), ACTOR)
    assert restart.disposition == "original_membership_action_pending"
    assert restart.canonical_state == "membership_written_not_selected"
    assert witness.disposition == "original_receipt_verified"
    assert witness.original_preview == membership.preview
    assert _all_bytes(root) == before
    outcome = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=membership, confirmation="RESUME"
    )
    assert outcome.disposition == "ready_verified"
    assert outcome.action_result is not None and outcome.action_result.succeeded
    current = load_current_grade_item_membership_decision(root, CLASS, GRADE, WORK)
    assert current is not None and current.decision.decision == "included"
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)
    assert (
        inspect_stored_assessment_setup_restart(root, _preview(), ACTOR).disposition
        == "ready_verified"
    )
    before_retry = _all_bytes(root)
    assert (
        resume_original_assessment_setup_selection(
            root, _preview(), ACTOR, original_action=membership, confirmation="RESUME"
        ).disposition
        == "requires_review"
    )
    assert _all_bytes(root) == before_retry


def test_registration_drift_refuses_original_grade_selection(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    original, _ = _original_grade(root)
    write_academic_work_registration(
        root, _registration(2), expected_current_revision=1
    )
    rebuild_academic_catalog(root)
    before = _all_bytes(root)
    outcome = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=original, confirmation="RESUME"
    )
    assert outcome.disposition == "requires_review"
    assert get_current_grade_item_revision(root, CLASS, GRADE) is None
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert _all_bytes(root) == before


def test_corrupt_original_journal_never_authorizes_resume(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    original, _ = _original_grade(root)
    journal_path = original.store.path_for(original.preview.action_id)
    journal_path.write_bytes(b"not a valid action journal\n")
    before = _all_bytes(root)
    witness = inspect_original_assessment_setup_receipt(root, _preview(), ACTOR)
    outcome = resume_original_assessment_setup_selection(
        root, _preview(), ACTOR, original_action=original, confirmation="RESUME"
    )
    assert witness.disposition == "requires_review"
    assert outcome.disposition == "requires_review"
    assert get_current_grade_item_revision(root, CLASS, GRADE) is None
    assert _all_bytes(root) == before
