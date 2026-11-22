"""#126-I2A: real ScoreForm + Core + #29 + #30 synthetic correction chain.

Exercises *native* immutable Meridian stores/CAS without replacing producer,
Core membership, or #29/#30 readers. A teacher's #122 confirmed menu journey
is a separate I2B gate. Only synthetic identities and an isolated root are used.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path, module_work_dir
from scoreform.academic_result_reader import read_academic_result_manifest
from test_issue126_slicei1_native_scoreform_29x6 import (
    FIRST,
    RETAKE,
    STUDENTS,
    WORK,
    _manifest,
    _publish,
    _read,
)

from meridian.assessment_attempt_inventory import project_assessment_attempt_inventory
from meridian.attempt_selection import (
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionStorageConflictError,
    derive_attempt_candidates,
    get_current_attempt_selection_decision_revision,
    list_attempt_selection_decision_revisions,
    load_current_attempt_selection_decision,
    load_current_attempt_selection_policy,
    resolve_current_attempt_selection,
    select_attempt_selection_decision_revision,
    select_attempt_selection_policy_revision,
    write_attempt_selection_decision_revision,
    write_attempt_selection_policy_revision,
)
from meridian.evidence_eligibility import (
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceReference,
)
from meridian.evidence_eligibility_storage import (
    get_current_evidence_eligibility_revision,
    observe_evidence_source_state,
    select_evidence_eligibility_revision,
    write_evidence_eligibility_revision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.menu_teacher_verified_continuation import (
    VerifiedContinuationPorts,
    verify_student_current_use,
)

GRADE_ITEM = "synthetic_grade_126_i2"
TEACHER = "synthetic_teacher_126_i2"
SCHOOL_YEAR = "2026-2027"
NOW = datetime(2026, 11, 20, 15, tzinfo=UTC)
POLICY = "teacher_guided_exactly_one"


@dataclass(frozen=True)
class NativeScenario:
    root: Path
    publication_id: str
    prepared: object
    original_data: bytes
    membership_digest: str
    policy_digest: str
    item_sources: tuple[EvidenceSourceReference, ...]


def _grade_item_and_membership(root: Path) -> str:
    """No fake membership digest: use persisted Core and Meridian authorities."""
    write_class_metadata(
        class_metadata_path(root, WORK.class_id),
        ClassMetadata(
            class_id=WORK.class_id,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
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
    )
    write_academic_period_calendar(root, calendar, expected_current_revision=None)
    grade = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=WORK.class_id,
        grade_item_id=GRADE_ITEM,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Synthetic Six-Question Correction Check",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    saved_grade = write_grade_item_revision(root, grade).stored
    select_grade_item_revision(
        root, WORK.class_id, GRADE_ITEM, 1, expected_current_revision=None
    )
    member = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=WORK.class_id,
        grade_item_id=GRADE_ITEM,
        grade_item_revision=1,
        grade_item_revision_sha256=saved_grade.revision_sha256,
        work_reference=GradeItemWorkReference(work=WORK, registration_revision=1),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(SCHOOL_YEAR, "mp1"),
            calendar_revision=1,
        ),
        actor_id=TEACHER,
        rationale=None,
        decided_at=NOW,
    )
    saved_member = write_grade_item_membership_revision(root, member).stored
    select_grade_item_membership_revision(
        root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        1,
        expected_current_membership_revision=None,
    )
    assert (
        load_current_grade_item_membership_decision(
            root, WORK.class_id, GRADE_ITEM, WORK
        ).decision_sha256
        == saved_member.decision_sha256
    )
    return saved_member.decision_sha256


def _setup(root: Path) -> NativeScenario:
    data = _manifest()
    root.mkdir()
    publication_id = _publish(root, data)
    membership_digest = _grade_item_and_membership(root)
    prepared = _read(root, publication_id)
    stored = prepared.authorized.stored
    sources: list[EvidenceSourceReference] = []
    # Choose the two exact published attempt-point sources, not a score rank.
    points = tuple(
        item
        for item in stored.snapshot.inventory.items
        if item.subject is not None
        and item.subject.student_id == FIRST
        and item.result_kind == "attempt_points"
    )
    assert len(points) == 2
    assert tuple(item.target.sequence for item in points) == (1, 2)
    for item in points:
        source = EvidenceSourceReference(
            work=WORK,
            publication_id=publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=item.item_id,
        )
        current_state = observe_evidence_source_state(root, source)
        assert current_state.state == "current"
        decision = EvidenceEligibilityDecision(
            schema_version="1",
            record_type="meridian_evidence_eligibility_decision",
            class_id=WORK.class_id,
            grade_item_id=GRADE_ITEM,
            source=source,
            membership_revision=1,
            membership_revision_sha256=membership_digest,
            eligibility_revision=1,
            supersedes_revision=None,
            disposition="included",
            actor=EvidenceDecisionActor("teacher", TEACHER),
            policy=EvidenceEligibilityPolicyReference("teacher_local_eligibility", "1"),
            reason_codes=(),
            rationale="Both native attempts are retained for teacher review.",
            source_state=current_state,
            decided_at=NOW,
        )
        saved = write_evidence_eligibility_revision(
            root, decision, authorized_snapshot=prepared.authorized
        )
        assert saved.disposition == "created"
        select_evidence_eligibility_revision(
            root,
            WORK.class_id,
            GRADE_ITEM,
            source,
            1,
            authorized_snapshot=prepared.authorized,
            expected_current_eligibility_revision=None,
        )
        assert (
            get_current_evidence_eligibility_revision(
                root, WORK.class_id, GRADE_ITEM, source
            )
            == 1
        )
        sources.append(source)

    policy = AttemptSelectionPolicy(
        schema_version="1",
        record_type="meridian_attempt_selection_policy",
        class_id=WORK.class_id,
        grade_item_id=GRADE_ITEM,
        work=WORK,
        policy_id=POLICY,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=1,
        maximum_selected=1,
        actor=AttemptSelectionActor("teacher", TEACHER),
        rationale="Separate, explicit teacher-selected attempt policy.",
        revised_at=NOW,
    )
    saved_policy = write_attempt_selection_policy_revision(root, policy).stored
    select_attempt_selection_policy_revision(
        root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        POLICY,
        1,
        expected_current_policy_revision=None,
    )
    assert (
        load_current_attempt_selection_policy(
            root, WORK.class_id, GRADE_ITEM, WORK, POLICY
        ).policy_sha256
        == saved_policy.policy_sha256
    )
    return NativeScenario(
        root,
        publication_id,
        prepared,
        data,
        membership_digest,
        saved_policy.policy_sha256,
        tuple(sources),
    )


def _decision(scenario: NativeScenario) -> AttemptSelectionDecision:
    derivation = derive_attempt_candidates(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        FIRST,
        scenario.prepared.authorized,
    )
    assert derivation.status == "applicable"
    assert tuple(
        candidate.attempt.native.sequence for candidate in derivation.candidates
    ) == (1, 2)
    assert tuple(
        len(candidate.eligible_evidence) for candidate in derivation.candidates
    ) == (1, 1)
    # The actor explicitly chooses Attempt 2; score magnitude and order never choose.
    corrected = derivation.candidates[1].attempt
    return AttemptSelectionDecision(
        schema_version="1",
        record_type="meridian_attempt_selection_decision",
        class_id=WORK.class_id,
        grade_item_id=GRADE_ITEM,
        work=WORK,
        student_id=FIRST,
        membership_revision=1,
        membership_revision_sha256=scenario.membership_digest,
        policy=AttemptSelectionPolicyReference(POLICY, 1, scenario.policy_digest),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=(corrected,),
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", TEACHER),
        rationale=(
            "Teacher compared retained source and verified corrected Attempt 2; "
            "cause is teacher-reviewed, not producer-certified."
        ),
        decided_at=NOW,
    )


def _save(scenario: NativeScenario) -> AttemptSelectionDecision:
    candidate = _decision(scenario)
    assert (
        get_current_attempt_selection_decision_revision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
        )
        is None
    )
    write = write_attempt_selection_decision_revision(
        scenario.root, candidate, authorized_snapshot=scenario.prepared.authorized
    )
    assert write.disposition == "created"
    assert (
        get_current_attempt_selection_decision_revision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
        )
        is None
    )  # Immutable write alone is NOT current use.
    selected = select_attempt_selection_decision_revision(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        FIRST,
        1,
        authorized_snapshot=scenario.prepared.authorized,
        expected_current_decision_revision=None,
    )
    assert selected.disposition == "created"
    return candidate


def test_real_native_correction_selects_only_attempt_2(tmp_path: Path) -> None:
    scenario = _setup(tmp_path / "native")
    candidate = _save(scenario)
    resolved = resolve_current_attempt_selection(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        FIRST,
        authorized_snapshot=scenario.prepared.authorized,
    )
    assert resolved.status == "selected" and resolved.operative_selection
    assert resolved.selected is not None
    assert resolved.selected.decision.selected_attempts == candidate.selected_attempts
    assert tuple(
        a.native.sequence for a in resolved.selected.decision.selected_attempts
    ) == (2,)
    assert len(resolved.current_candidates) == 2
    manifest = read_academic_result_manifest(scenario.original_data)
    assert manifest.students[0].attempts[0].points_earned == 0
    assert manifest.students[0].attempts[1].points_earned == 6
    source_path = (
        module_work_dir(scenario.root, WORK)
        / "publications"
        / "academic_results"
        / "1.json"
    )
    assert (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        == hashlib.sha256(scenario.original_data).hexdigest()
    )
    assert list_attempt_selection_decision_revisions(
        scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
    ) == (1,)
    assert (
        get_current_attempt_selection_decision_revision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, RETAKE
        )
        is None
    )


def test_native_cas_refuses_stale_expected_current(tmp_path: Path) -> None:
    scenario = _setup(tmp_path / "native")
    decision = _decision(scenario)
    write_attempt_selection_decision_revision(
        scenario.root, decision, authorized_snapshot=scenario.prepared.authorized
    )
    with pytest.raises(AttemptSelectionStorageConflictError):
        select_attempt_selection_decision_revision(
            scenario.root,
            WORK.class_id,
            GRADE_ITEM,
            WORK,
            FIRST,
            1,
            authorized_snapshot=scenario.prepared.authorized,
            expected_current_decision_revision=2,
        )
    assert (
        get_current_attempt_selection_decision_revision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
        )
        is None
    )
    assert list_attempt_selection_decision_revisions(
        scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
    ) == (1,)  # Written, not current; no unsafe replay.


def test_unselected_native_revision_not_operative(tmp_path: Path) -> None:
    scenario = _setup(tmp_path / "native")
    candidate = _decision(scenario)
    write_attempt_selection_decision_revision(
        scenario.root, candidate, authorized_snapshot=scenario.prepared.authorized
    )
    status = resolve_current_attempt_selection(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        FIRST,
        authorized_snapshot=scenario.prepared.authorized,
    )
    assert status.status == "no_decision" and not status.operative_selection
    assert (
        load_current_attempt_selection_decision(
            scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
        )
        is None
    )


def test_exact_native_selection_repeat_cannot_duplicate_revision(
    tmp_path: Path,
) -> None:
    scenario = _setup(tmp_path / "native")
    candidate = _save(scenario)
    repeat = write_attempt_selection_decision_revision(
        scenario.root, candidate, authorized_snapshot=scenario.prepared.authorized
    )
    assert repeat.disposition == "existing"
    assert list_attempt_selection_decision_revisions(
        scenario.root, WORK.class_id, GRADE_ITEM, WORK, FIRST
    ) == (1,)


def test_native_standards_gate_receives_selected_attempt_2_only(tmp_path: Path) -> None:
    scenario = _setup(tmp_path / "native")
    _save(scenario)
    inventory = project_assessment_attempt_inventory(
        scenario.root,
        grade_item_id=GRADE_ITEM,
        prepared=scenario.prepared,
        class_label="Synthetic English 11",
        assessment_title="Synthetic Six-Question Correction Check",
    )
    assert len(inventory.students) == len(STUDENTS) == 29
    row = next(person for person in inventory.students if person.student_id == FIRST)
    assert row.selection_status == "selected"
    assert tuple(
        attempt.attempt.native.sequence
        for attempt in row.attempts
        if attempt.current_selected
    ) == (2,)
    verified = verify_student_current_use(
        scenario.root,
        scenario.prepared,
        inventory,
        row,
        ports=VerifiedContinuationPorts(
            fresh_projection=lambda root, work, publication_id: _read(
                root, publication_id
            ),
        ),
    )
    assert verified.selected_attempt_count == 1
    assert verified.included_item_ids
    assert all(
        item_id in set(row.attempts[1].item_ids)
        for item_id in verified.included_item_ids
    )
    assert not set(row.attempts[0].item_ids).intersection(verified.included_item_ids)


def test_retaken_attempt_does_not_become_automatically_selected(tmp_path: Path) -> None:
    scenario = _setup(tmp_path / "native")
    _save(scenario)
    retake = resolve_current_attempt_selection(
        scenario.root,
        WORK.class_id,
        GRADE_ITEM,
        WORK,
        RETAKE,
        authorized_snapshot=scenario.prepared.authorized,
    )
    assert retake.status == "no_decision" and not retake.operative_selection
    assert retake.selected is None
