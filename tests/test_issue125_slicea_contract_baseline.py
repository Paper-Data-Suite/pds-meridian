"""#125-A: freeze the pre-batch academic/provenance contracts, synthetic only.

These tests intentionally do not persist eligibility, select a pointer, read a
producer manifest, or grant evidence access. Later slices add batch behavior.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from typing import get_args

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_DISPOSITIONS,
    EvidenceSourceReference,
    evidence_source_key,
)
from meridian.evidence_eligibility_storage import EvidenceEligibilityResolutionStatus
from meridian.new_evidence_eligibility_workflow import TeacherEligibilityDisposition
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    NewEvidenceStatusSummary,
    NewEvidenceWorkflowScopeError,
    new_evidence_review_to_dict,
)
from meridian.teacher_action_contract import ActionKind, ActionStatus

_CLASS = "synthetic_class_2026"
_WORK = ModuleWorkRef("scoreform", _CLASS, "assessment_125a")
_PUBLICATION = "pub_" + "a" * 32
_CACHE = "b" * 64
_SNAPSHOT = "c" * 64


def _source(item_id: str) -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=_WORK,
        publication_id=_PUBLICATION,
        cache_key=_CACHE,
        snapshot_digest=_SNAPSHOT,
        item_id=item_id,
    )


def _row(student: int, question: int) -> NewEvidenceRow:
    return NewEvidenceRow(
        source=_source(f"student_{student:02d}_question_{question}"),
        student_id=f"student_{student:02d}",
        target_kind="question",
        target_id=f"question_{question}",
        standard_ids=(),
        result_kind="question_score",
        membership_state="included",
        eligibility_status="no_decision",
        selected_eligibility_revision=None,
        selected_eligibility_disposition=None,
        eligibility_source_state="current",
        operative_included=False,
        attention_required=True,
        recommended_task="exclusions",
    )


def test_canonical_dispositions_and_teacher_choices_remain_distinct() -> None:
    assert EVIDENCE_ELIGIBILITY_DISPOSITIONS == {
        "included",
        "excluded",
        "pending",
        "unsupported",
        "superseded",
        "withdrawn",
    }
    assert set(get_args(TeacherEligibilityDisposition)) == {
        "included",
        "excluded",
        "pending",
        "unsupported",
    }
    assert set(get_args(EvidenceEligibilityResolutionStatus)) >= {
        "no_decision",
        "included",
        "included_source_superseded",
        "included_source_withdrawn",
        "excluded",
        "pending",
        "unsupported",
        "membership_stale",
        "source_unverifiable",
    }
    assert "eligibility" in get_args(ActionKind)
    assert {
        "applied",
        "already_applied",
        "written_not_current",
        "current_unverified",
        "conflict_requires_review",
        "recovery_required",
    } <= set(get_args(ActionStatus))


def test_exact_source_identity_not_just_question_or_student_name() -> None:
    first = _source("student_01_question_1")
    same_name_new_publication = replace(first, publication_id="pub_" + "d" * 32)
    same_name_new_snapshot = replace(first, snapshot_digest="e" * 64)
    other_item_same_source = replace(first, item_id="student_02_question_1")
    assert (
        len(
            {
                evidence_source_key(item)
                for item in (
                    first,
                    same_name_new_publication,
                    same_name_new_snapshot,
                    other_item_same_source,
                )
            }
        )
        == 4
    )
    with pytest.raises(FrozenInstanceError):
        first.item_id = "mutated"  # type: ignore[misc]


def test_nominal_29_by_6_fixture_preserves_174_distinct_exact_items() -> None:
    """A shape/interaction baseline, not a producer manifest-size assumption."""
    rows = tuple(
        _row(student, question) for student in range(1, 30) for question in range(1, 7)
    )
    review = NewEvidenceReview(
        class_id=_CLASS,
        grade_item_id="grade_item_125a",
        work=_WORK,
        publication_id=_PUBLICATION,
        cache_key=_CACHE,
        snapshot_digest=_SNAPSHOT,
        projection_source_status="current",
        membership_state="included",
        membership_revision=1,
        academic_period_id="mp1",
        academic_period_calendar_revision=1,
        rows=rows,
        status_summary=(
            NewEvidenceStatusSummary(status="eligibility_no_decision", count=174),
        ),
        attention_count=174,
    )
    assert len(review.rows) == 174
    assert len({r.source for r in rows}) == 174
    by_student = Counter(row.student_id for row in rows)
    assert len(by_student) == 29
    assert set(by_student.values()) == {6}
    assert all(not row.operative_included for row in rows)
    assert all(row.selected_eligibility_revision is None for row in rows)
    assert new_evidence_review_to_dict(review)["status_summary"] == [
        {"status": "eligibility_no_decision", "count": 174}
    ]


def test_read_only_review_cannot_fabricate_current_eligibility() -> None:
    row = _row(1, 1)
    assert row.eligibility_status == "no_decision"
    assert row.operative_included is False
    with pytest.raises(NewEvidenceWorkflowScopeError):
        replace(row, membership_state="no_decision", operative_included=True)
    with pytest.raises(NewEvidenceWorkflowScopeError):
        replace(row, membership_state="excluded")


def test_shared_or_group_item_is_not_silently_student_attributed() -> None:
    base = _row(1, 1)
    group = replace(
        base,
        source=_source("group_evidence_1"),
        student_id=None,
        target_kind="concord_group",
        target_id="group_1",
    )
    assert group.student_id is None
    assert group.target_kind == "concord_group"
    assert group.source != base.source


def test_status_summary_cannot_hide_unresolved_items() -> None:
    rows = (_row(1, 1), _row(1, 2))
    with pytest.raises(NewEvidenceWorkflowScopeError, match="status_summary"):
        NewEvidenceReview(
            class_id=_CLASS,
            grade_item_id="grade_item_125a",
            work=_WORK,
            publication_id=_PUBLICATION,
            cache_key=_CACHE,
            snapshot_digest=_SNAPSHOT,
            projection_source_status="current",
            membership_state="included",
            membership_revision=1,
            academic_period_id="mp1",
            academic_period_calendar_revision=1,
            rows=rows,
            status_summary=(
                NewEvidenceStatusSummary(status="eligibility_no_decision", count=1),
            ),
            attention_count=2,
        )
