"""#125-B: read-only assessment scale, Core roster, exceptions, provenance."""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.rosters import ROSTER_REQUIRED_COLUMNS, Roster, StudentRecord
from pds_core.routing_models import ModuleWorkRef

import meridian.assessment_eligibility_review as batch
from meridian.evidence import EvidenceInventory, NativePointValue
from meridian.evidence_eligibility import (
    EvidenceEligibilityDisposition,
    EvidenceSourceReference,
)
from meridian.evidence_eligibility_storage import EvidenceEligibilityResolutionStatus
from meridian.new_evidence_workflow import (
    NewEvidenceMembershipState,
    NewEvidenceReview,
    NewEvidenceRow,
    NewEvidenceStatusSummary,
)
from meridian.teacher_evidence_review import build_teacher_evidence_review

CLASS_ID = "synthetic_class_2026"
WORK = ModuleWorkRef("scoreform", CLASS_ID, "assessment_125_b")
PUBLICATION = "pub_" + "1" * 32
CACHE = "2" * 64
DIGEST = "3" * 64


def student(
    index: int, *, first_name: str | None = None, period: str = "2"
) -> StudentRecord:
    return StudentRecord(
        class_id=CLASS_ID,
        student_id=f"student_{index:02d}",
        first_name=first_name or f"Sample{index}",
        last_name="Student",
        period=period,
        extra_fields={},
    )


def roster(*students: StudentRecord) -> Roster:
    return Roster(class_id=CLASS_ID, students=students, columns=ROSTER_REQUIRED_COLUMNS)


def source(item_id: str) -> EvidenceSourceReference:
    return EvidenceSourceReference(WORK, PUBLICATION, CACHE, DIGEST, item_id)


def eligibility_row(
    student_id: str | None,
    question: int,
    *,
    item_id: str | None = None,
    status: str = "no_decision",
    membership: str = "included",
    operative: bool = False,
    target_id: str | None = None,
) -> NewEvidenceRow:
    return NewEvidenceRow(
        source=source(item_id or f"{student_id or 'shared'}_question_{question}"),
        student_id=student_id,
        target_kind="question",
        target_id=target_id or f"q{question}",
        standard_ids=("RL.CR.9-10.1",),
        result_kind="question_score",
        membership_state=cast(NewEvidenceMembershipState, membership),
        eligibility_status=cast(EvidenceEligibilityResolutionStatus, status)
        if membership == "included"
        else None,
        selected_eligibility_revision=1
        if status in {"included", "excluded", "pending"} and membership == "included"
        else None,
        selected_eligibility_disposition=cast(EvidenceEligibilityDisposition, status)
        if status in {"included", "excluded", "pending"} and membership == "included"
        else None,
        eligibility_source_state="current" if membership == "included" else None,
        operative_included=operative,
        attention_required=membership == "no_decision"
        or status not in {"included", "excluded"},
        recommended_task="grade-items"
        if membership == "no_decision"
        else (
            "exclusions"
            if status not in {"included", "excluded"} and membership == "included"
            else None
        ),
    )


def review(
    *rows: NewEvidenceRow, source_status: str = "current", membership: str = "included"
) -> NewEvidenceReview:
    statuses: Counter[str] = Counter()
    for row in rows:
        label = (
            "eligibility_" + str(row.eligibility_status)
            if row.membership_state == "included"
            else "membership_" + row.membership_state
        )
        statuses[label] += 1
    return NewEvidenceReview(
        class_id=CLASS_ID,
        grade_item_id="grade_125b",
        work=WORK,
        publication_id=PUBLICATION,
        cache_key=CACHE,
        snapshot_digest=DIGEST,
        projection_source_status=source_status,
        membership_state=cast(NewEvidenceMembershipState, membership),
        membership_revision=2 if membership != "no_decision" else None,
        academic_period_id="mp1" if membership == "included" else None,
        academic_period_calendar_revision=3 if membership == "included" else None,
        rows=tuple(rows),
        status_summary=tuple(
            NewEvidenceStatusSummary(status=key, count=value)
            for key, value in sorted(statuses.items())
        ),
        attention_count=sum(row.attention_required for row in rows),
    )


def native_item(row: NewEvidenceRow) -> SimpleNamespace:
    return SimpleNamespace(
        item_id=row.source.item_id,
        subject=(
            SimpleNamespace(student_id=row.student_id) if row.student_id else None
        ),
        target=SimpleNamespace(
            target_kind=row.target_kind,
            target_id=row.target_id,
            sequence=int(row.target_id[1:])
            if row.target_id and row.target_id.startswith("q")
            else None,
            standard_ids=row.standard_ids,
        ),
        result_kind=row.result_kind,
        value=NativePointValue(1, 1),
        provenance=SimpleNamespace(native=SimpleNamespace(references=())),
    )


def project(
    rows: tuple[NewEvidenceRow, ...], roster_value: Roster, **kwargs: object
) -> batch.AssessmentEligibilityReview:
    allowed = {s.student_id for s in roster_value.students}
    known = [
        native_item(row)
        for row in rows
        if row.student_id is None or row.student_id in allowed
    ]
    teacher = build_teacher_evidence_review(
        inventory=cast(EvidenceInventory, SimpleNamespace(items=tuple(known))),
        roster=roster_value,
        work=WORK,
        publication_id=PUBLICATION,
    )
    return batch.build_assessment_eligibility_review(
        evidence=review(
            *rows, source_status=str(kwargs.get("source_status", "current"))
        ),
        teacher=teacher,
        roster=roster_value,
        class_label="English 12",
        assessment_title="Synthetic six-question check",
    )


def test_29_by_6_roster_and_native_labels_are_read_only_and_complete() -> None:
    rows = tuple(
        eligibility_row(f"student_{i:02d}", q)
        for i in range(1, 30)
        for q in range(1, 7)
    )
    summary = project(rows, roster(*(student(i) for i in range(1, 30))))
    assert len(summary.students) == 29
    assert summary.projected_item_count == 174
    assert summary.candidate_item_count == 174
    assert summary.no_result_student_count == 0
    assert summary.exception_count == 0
    assert len({item.source for s in summary.students for item in s.items}) == 174
    assert summary.students[0].items[0].evidence_label == "Question 1"
    assert summary.status_counts == (("eligibility_no_decision", 174),)
    text = batch.render_assessment_eligibility_preview(summary)
    assert "174 items" in text
    assert "29 students" in text
    assert "No grades, missing-result zeros" in text
    assert "student_01_question_1" not in text
    with pytest.raises(FrozenInstanceError):
        summary.students[0].items = ()  # type: ignore[misc]


def test_no_result_is_roster_observation_never_zero() -> None:
    rows = (eligibility_row("student_01", 1),)
    summary = project(rows, roster(student(1), student(2)))
    assert len(summary.students) == 2
    assert summary.students[1].no_result
    assert summary.no_result_student_count == 1
    assert any(issue.code == "no_result_in_publication" for issue in summary.exceptions)
    assert (
        "No result returned in this publication (not a zero)"
        in batch.render_assessment_eligibility_preview(summary)
    )


def test_unknown_roster_subject_and_shared_item_remain_visible_but_blocked() -> None:
    rows = (
        eligibility_row("student_01", 1),
        eligibility_row("non_roster_id", 2),
        eligibility_row(None, 3),
    )
    summary = project(rows, roster(student(1)))
    assert summary.projected_item_count == 3
    assert len(summary.unmatched_items) == 1
    assert len(summary.shared_items) == 1
    assert summary.candidate_item_count == 1
    assert {issue.code for issue in summary.exceptions} == {
        "unknown_roster_student",
        "non_student_evidence",
    }
    assert not summary.unmatched_items[0].candidate_for_explicit_review
    assert not summary.shared_items[0].candidate_for_explicit_review
    text = batch.render_assessment_eligibility_preview(summary)
    assert "UNMATCHED STUDENT ATTRIBUTION" in text
    assert "SHARED / NON-STUDENT" in text
    assert "non_roster_id" not in text


def test_duplicate_native_target_needs_attempt_review_without_guessing() -> None:
    rows = (
        eligibility_row("student_01", 1, item_id="first_attempt_q1"),
        eligibility_row("student_01", 1, item_id="second_attempt_q1"),
        eligibility_row("student_01", 2),
    )
    summary = project(rows, roster(student(1)))
    assert summary.candidate_item_count == 1
    assert [issue.code for issue in summary.exceptions] == [
        "multiple_items_same_native_target",
        "multiple_items_same_native_target",
    ]
    assert all(issue.route == "review-attempts" for issue in summary.exceptions)


def test_membership_source_and_decision_statuses_are_not_collapsed() -> None:
    rows = (
        eligibility_row("student_01", 1, status="included", operative=True),
        eligibility_row("student_01", 2, status="excluded"),
        eligibility_row("student_01", 3, status="pending"),
        eligibility_row("student_01", 4, status="membership_stale"),
        eligibility_row("student_01", 5, status="no_decision"),
    )
    summary = project(rows, roster(student(1)), source_status="withdrawn")
    assert summary.candidate_item_count == 0
    assert summary.source_status == "withdrawn"
    codes = Counter(issue.code for issue in summary.exceptions)
    assert codes["source_not_current"] == 5
    assert codes["previous_excluded"] == 1
    assert codes["previous_pending"] == 1
    assert codes["eligibility_membership_stale"] == 1
    assert summary.students[0].items[0].operative_included
    assert summary.status_counts == (
        ("eligibility_excluded", 1),
        ("eligibility_included", 1),
        ("eligibility_membership_stale", 1),
        ("eligibility_no_decision", 1),
        ("eligibility_pending", 1),
    )


def test_duplicate_roster_names_are_disambiguated_including_missing_students() -> None:
    rows = (eligibility_row("student_01", 1),)
    good = project(
        rows,
        roster(
            student(1, first_name="Alex", period="2"),
            student(2, first_name="Alex", period="5"),
        ),
    )
    assert [s.display_label for s in good.students] == [
        "Alex Student · Period 2",
        "Alex Student · Period 5",
    ]
    with pytest.raises(
        batch.AssessmentEligibilityReviewScopeError, match="distinguished"
    ):
        project(
            rows, roster(student(1, first_name="Alex"), student(2, first_name="Alex"))
        )


def test_wrong_exact_source_identity_fails_before_projection() -> None:
    rows = (eligibility_row("student_01", 1),)
    original = review(*rows)
    tampered = replace(
        rows[0], source=replace(rows[0].source, snapshot_digest="f" * 64)
    )
    changed = replace(
        original,
        rows=(tampered,),
        status_summary=original.status_summary,
    )
    student_roster = roster(student(1))
    teacher = build_teacher_evidence_review(
        inventory=cast(
            EvidenceInventory, SimpleNamespace(items=(native_item(rows[0]),))
        ),
        roster=student_roster,
        work=WORK,
        publication_id=PUBLICATION,
    )
    with pytest.raises(
        batch.AssessmentEligibilityReviewScopeError, match="different exact source"
    ):
        batch.build_assessment_eligibility_review(
            evidence=changed, teacher=teacher, roster=student_roster
        )


def test_bounded_review_does_not_truncate_or_silently_hide_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(batch, "MAXIMUM_EVIDENCE_ITEMS", 1)
    rows = (eligibility_row("student_01", 1), eligibility_row("student_01", 2))
    with pytest.raises(batch.AssessmentEligibilityReviewScopeError, match="bounded"):
        project(rows, roster(student(1)))


def test_guided_projection_entry_reuses_authorized_source_and_core_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = eligibility_row("student_01", 1)
    student_roster = roster(student(1))
    fake_item = native_item(row)

    class FakeInventory:
        def __init__(self, items: tuple[object, ...]):
            self.items = tuple(items)

    publication = SimpleNamespace(work=WORK, publication_id=PUBLICATION)
    authorized = SimpleNamespace(
        current_context=SimpleNamespace(publication=publication),
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
                inventory=FakeInventory((fake_item,)),
            )
        ),
    )
    observed: list[object] = []
    monkeypatch.setattr(batch, "GuidedProjectionResult", SimpleNamespace)
    monkeypatch.setattr(batch, "EvidenceInventory", FakeInventory)
    monkeypatch.setattr(
        batch,
        "load_class_roster",
        lambda root, cid: (observed.append((root, cid)), student_roster)[1],
    )
    monkeypatch.setattr(
        batch,
        "project_new_evidence_review",
        lambda root, cid, gid, auth: (
            observed.append((root, cid, gid, auth)),
            review(row),
        )[1],
    )
    summary = batch.project_assessment_eligibility_review(
        "workspace",
        grade_item_id="grade_125b",
        prepared=SimpleNamespace(authorized=authorized, requested_student_ids=()),
    )
    assert summary.projected_item_count == 1
    assert observed[0] == ("workspace", CLASS_ID)
    assert observed[1] == ("workspace", CLASS_ID, "grade_125b", authorized)


def test_preparation_rejects_unauthorized_object_without_any_roster_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        batch, "load_class_roster", lambda *_: pytest.fail("must not load roster")
    )
    with pytest.raises(batch.AssessmentEligibilityReviewScopeError, match="authorized"):
        batch.project_assessment_eligibility_review(
            "workspace",
            grade_item_id="grade_125b",
            prepared=object(),  # type: ignore[arg-type]
        )


def test_narrow_requested_student_scope_not_misreported_as_missing() -> None:
    rows = (eligibility_row("student_01", 1),)
    students = roster(student(1), student(2))
    known = build_teacher_evidence_review(
        inventory=cast(
            EvidenceInventory, SimpleNamespace(items=(native_item(rows[0]),))
        ),
        roster=students,
        work=WORK,
        publication_id=PUBLICATION,
    )
    summary = batch.build_assessment_eligibility_review(
        evidence=review(*rows),
        teacher=known,
        roster=students,
        requested_student_ids=("student_01",),
    )
    assert summary.no_result_student_count == 0
    assert summary.outside_authorization_scope_count == 1
    assert any(
        e.code == "outside_requested_authorization_scope" for e in summary.exceptions
    )
    assert (
        "Outside requested evidence scope"
        in batch.render_assessment_eligibility_preview(summary)
    )


def test_inconsistent_selected_pointer_evidence_cannot_be_batch_candidate() -> None:
    row = replace(
        eligibility_row("student_01", 1),
        selected_eligibility_revision=1,
        selected_eligibility_disposition="excluded",
    )
    summary = project((row,), roster(student(1)))
    assert summary.candidate_item_count == 0
    assert any(
        issue.code == "eligibility_resolution_inconsistent" and issue.route == "stop"
        for issue in summary.exceptions
    )


def test_evidence_outside_requested_scope_fails_closed() -> None:
    rows = (eligibility_row("student_01", 1), eligibility_row("student_02", 1))
    students = roster(student(1), student(2))
    teacher = build_teacher_evidence_review(
        inventory=cast(
            EvidenceInventory,
            SimpleNamespace(items=tuple(native_item(row) for row in rows)),
        ),
        roster=students,
        work=WORK,
        publication_id=PUBLICATION,
    )
    with pytest.raises(
        batch.AssessmentEligibilityReviewScopeError, match="outside requested"
    ):
        batch.build_assessment_eligibility_review(
            evidence=review(*rows),
            teacher=teacher,
            roster=students,
            requested_student_ids=("student_01",),
        )
