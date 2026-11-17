"""#125-H3D1: synthetic native non-Include / exact override acceptance.

The native tests are opt-in and require an independently isolated candidate-wheel
installation with genuine official producer/Core distributions. No classroom data.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest
from test_issue125_slicec_batch_review_plan import (
    ids,
    make_review,
)
from test_issue125_slicec_batch_review_plan import (
    plan as synthetic_plan,
)
from test_issue125_sliceg2a_canonical_batch_acceptance import _ready_native

from meridian.assessment_eligibility_plan import (
    AssessmentEligibilityPlanError,
    BatchEligibilitySelection,
    BatchItemException,
    BatchStudentException,
    TeacherDisposition,
    build_batch_eligibility_plan,
    capture_batch_pointer_witnesses,
)
from meridian.assessment_eligibility_progress import execute_batch_with_sealed_progress
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore

_NATIVE = os.environ.get("PDS_ISSUE125_H3D1_NATIVE_TEST") == "1"
_REASON = ("eligibility.manual",)


@pytest.mark.parametrize("disposition", ("excluded", "pending", "unsupported"))
def test_noninclude_cannot_be_implicit(disposition: str) -> None:
    with pytest.raises(AssessmentEligibilityPlanError, match="reason"):
        BatchEligibilitySelection(
            ("synthetic_item",), cast(TeacherDisposition, disposition)
        )


def test_student_exception_and_item_precedence_is_fixed_and_read_only() -> None:
    review = make_review(student_count=2, questions=3)
    selected = ids(review)
    choice = BatchEligibilitySelection(
        selected,
        "included",
        student_exceptions=(
            BatchStudentException("student_02", "excluded", _REASON, "Manual review"),
        ),
        item_exceptions=(
            BatchItemException("student_02_question_2", "pending", _REASON),
            BatchItemException("student_02_question_3", None),
        ),
    )
    plan = synthetic_plan(review, choice)
    statuses = {row.source.item_id: (row.status, row.disposition) for row in plan.items}
    assert statuses["student_01_question_1"] == ("action", "included")
    assert statuses["student_02_question_1"] == ("action", "excluded")
    assert statuses["student_02_question_2"] == ("action", "pending")
    assert statuses["student_02_question_3"] == ("deferred", None)
    assert plan.action_count == 5
    assert plan.deferred_count == 1


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated installed official producer wheels"
)
@pytest.mark.parametrize(
    ("producer", "disposition"),
    (("scoreform", "excluded"), ("quillan", "pending"), ("concord", "unsupported")),
)
def test_installed_native_noninclude_creates_exact_decision_and_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer: str,
    disposition: str,
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, producer
    )
    options = sorted(
        (
            item
            for student in review.students
            for item in student.items
            if item.candidate_for_explicit_review
        ),
        key=lambda item: item.source.item_id,
    )
    assert options, producer
    selected = (options[0].source.item_id,)
    choice = BatchEligibilitySelection(
        selected,
        cast(TeacherDisposition, disposition),
        _REASON,
        f"Synthetic {producer} explicit review",
    )
    proposal = build_batch_eligibility_plan(
        review,
        choice,
        actor=actor,
        policy=deps.policies[0],
        witnesses=capture_batch_pointer_witnesses(
            root, review, prepared.authorized, selected
        ),
        qualified_policies=deps.policies,
    )
    assert proposal.action_count == 1 and proposal.deferred_count == 0
    outcome = execute_batch_with_sealed_progress(
        root,
        proposal,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not outcome.stopped, (producer, outcome.stop_reason, outcome.counts)
    assert outcome.verified_current_count == 1
    action_id = outcome.items[0].action_id
    assert action_id is not None
    stored = load_current_evidence_eligibility_decision(
        root, proposal.class_id, grade_id, options[0].source
    )
    assert stored is not None
    assert stored.decision.disposition == disposition
    assert stored.decision.reason_codes == _REASON
    assert stored.decision.rationale == f"Synthetic {producer} explicit review"
    assert stored.decision.source == options[0].source
    receipt = TeacherActionReceiptStore(root, proposal.class_id).load(action_id)
    assert receipt is not None
    print(
        f"H3D1_NATIVE_NONINCLUDE producer={producer} "
        f"disposition={disposition} actions=1"
    )


@pytest.mark.skipif(not _NATIVE, reason="Requires isolated installed ScoreForm wheel")
def test_installed_scoreform_exact_student_item_exception_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    groups = [
        (
            student,
            sorted(
                (
                    item
                    for item in student.items
                    if item.candidate_for_explicit_review
                    and item.result_kind == "question_correctness"
                ),
                key=lambda item: item.source.item_id,
            ),
        )
        for student in review.students
    ]
    eligible = [(student, items) for student, items in groups if len(items) >= 3]
    assert len(eligible) >= 2
    first_student, first_items = eligible[0]
    _, second_items = eligible[1]
    chosen = (*first_items[:3], second_items[0])
    selected = tuple(item.source.item_id for item in chosen)
    dispositions = {
        chosen[0].source.item_id: "excluded",
        chosen[1].source.item_id: "pending",
        chosen[2].source.item_id: None,
        chosen[3].source.item_id: "included",
    }
    choice = BatchEligibilitySelection(
        selected,
        "included",
        student_exceptions=(
            BatchStudentException(
                first_student.student_id, "excluded", _REASON, "Student exception"
            ),
        ),
        item_exceptions=(
            BatchItemException(chosen[1].source.item_id, "pending", _REASON),
            BatchItemException(chosen[2].source.item_id, None),
        ),
    )
    proposal = build_batch_eligibility_plan(
        review,
        choice,
        actor=actor,
        policy=deps.policies[0],
        witnesses=capture_batch_pointer_witnesses(
            root, review, prepared.authorized, selected
        ),
        qualified_policies=deps.policies,
    )
    assert len(proposal.items) == 4
    assert proposal.action_count == 3 and proposal.deferred_count == 1
    for item in proposal.items:
        expected = dispositions[item.source.item_id]
        assert item.disposition == expected
        assert item.status == ("deferred" if expected is None else "action")
    result = execute_batch_with_sealed_progress(
        root,
        proposal,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not result.stopped, (result.stop_reason, result.counts)
    assert result.verified_current_count == 3
    assert result.counts == (("applied", 3), ("deferred", 1))
    assert {row.source_item_id for row in result.items} == set(selected)
    for item in chosen:
        expected = dispositions[item.source.item_id]
        stored = load_current_evidence_eligibility_decision(
            root, proposal.class_id, grade_id, item.source
        )
        if expected is None:
            assert stored is None, "Deferred source was written"
        else:
            assert stored is not None
            assert stored.decision.disposition == expected
            assert stored.decision.reason_codes == (
                _REASON if expected != "included" else ()
            )
    assert len({row.action_id for row in result.items if row.action_id}) == 3
    print("H3D1_NATIVE_OVERRIDE actions=3 deferred=1 untouched=1")
