"""#125-G2B: bounded classroom batch and interrupted native #122 recovery.

All pupils, work, assessment results and teacher identity are synthetic.
Native ScoreForm uses the producer-owned publisher in #124, not invented data.
No test opens a production workspace or treats a receipt as academic authority.
"""

from __future__ import annotations

import os
from functools import partial
from time import perf_counter

import pytest
from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
from test_issue125_sliceg2a_canonical_batch_acceptance import (
    _build_plan,
    _ready_native,
)

from meridian.assessment_eligibility_progress import (
    BatchEligibilityProgressStore,
    execute_batch_with_sealed_progress,
)
from meridian.assessment_eligibility_recovery import (
    BatchEligibilityRecoveryError,
    reconcile_sealed_eligibility_batch,
)
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.teacher_action_guided import PreparedGuidedAction, _actor_now
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_eligibility import (
    load_fresh_restart_authorization,
)

_NATIVE = os.environ.get("PDS_ISSUE125_G2B_NATIVE_TEST") == "1"
pytestmark = pytest.mark.skipif(
    not _NATIVE,
    reason="Requires the exact pinned native ScoreForm/Core/Quillan/Concord matrix",
)


def _question_correctness(review):
    return tuple(
        row
        for student in review.students
        for row in student.items
        if row.result_kind == "question_correctness"
    )


def _six_students(review):
    """Select one exact correctness item per student, never all evidence kinds."""
    chosen = []
    for student in review.students[:6]:
        item = next(
            row for row in student.items if row.result_kind == "question_correctness"
        )
        chosen.append(item.source.item_id)
    assert len(chosen) == len(set(chosen)) == 6
    return tuple(chosen)


def _reconcile(root, plan, diagnostics):
    return reconcile_sealed_eligibility_batch(
        root,
        plan,
        authorized_loader=partial(
            load_fresh_restart_authorization, diagnostics=diagnostics
        ),
        actor_checker=_actor_now,
    )


def test_native_29x6_full_correctness_plan_cancel_is_zero_write(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    assert len(review.students) == 29
    assert review.projected_item_count == 406
    correctness = _question_correctness(review)
    assert len(correctness) == 174
    assert len({row.source for row in correctness}) == 174
    selected = tuple(row.source.item_id for row in correctness)
    before = _all_bytes(root)
    began = perf_counter()
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    planned_elapsed = perf_counter() - began
    assert plan.action_count == 174
    assert plan.blocked_count == plan.deferred_count == 0
    assert {row.source.item_id for row in plan.items} == set(selected)
    assert _all_bytes(root) == before

    cancelled = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=False,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not cancelled.confirmed
    assert not cancelled.stopped
    assert cancelled.verified_current_count == 0
    assert _all_bytes(root) == before
    store = BatchEligibilityProgressStore(root, CLASS)
    progress_path = store.directory / plan.plan_sha256
    assert not progress_path.exists()
    print(
        f"G2B_29X6_CANCEL exact_questions={len(correctness)} "
        f"plan_seconds={planned_elapsed:.3f} eligibility_writes=0"
    )


def test_native_six_student_actions_canonical_and_repeat_inspection(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, grade_id, prepared, review, deps, grade_item, diagnostics, actor = (
        _ready_native(tmp_path, monkeypatch, "scoreform")
    )
    selected = _six_students(review)
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    assert plan.action_count == 6
    original_receipts = {
        receipt.action_id
        for receipt in TeacherActionReceiptStore(root, CLASS).list_receipts()
    }
    started = perf_counter()
    outcome = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    elapsed = perf_counter() - started
    assert not outcome.stopped, (outcome.stop_reason, outcome.counts)
    assert outcome.verified_current_count == 6
    assert {row.source_item_id for row in outcome.items} == set(selected)
    assert len({row.action_id for row in outcome.items}) == 6
    receipts = TeacherActionReceiptStore(root, CLASS)
    latest = {r.action_id for r in receipts.list_receipts()}
    assert len(latest - original_receipts) == 6
    for item in plan.items:
        decision = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, item.source
        )
        assert decision is not None
        assert decision.decision.disposition == "included"
        assert decision.decision.eligibility_revision == 1
        assert BatchEligibilityProgressStore(root, CLASS).load(plan, item) is not None
    untouched = next(
        row
        for row in _question_correctness(review)
        if row.source.item_id not in selected
    )
    assert (
        load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, untouched.source
        )
        is None
    )
    before = _all_bytes(root)
    first = _reconcile(root, plan, diagnostics)
    second = _reconcile(root, plan, diagnostics)
    assert first.verified_action_count == second.verified_action_count == 6
    assert first.selection_resume_count == second.selection_resume_count == 0
    assert not first.requires_attention and not second.requires_attention
    assert _all_bytes(root) == before
    print(
        f"G2B_SIX_STUDENTS canonical_actions=6 "
        f"elapsed_seconds={elapsed:.3f} receipts_verified=6"
    )


def test_native_interruption_after_second_canonical_apply_does_not_replay(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, grade_id, prepared, review, deps, grade_item, diagnostics, actor = (
        _ready_native(tmp_path, monkeypatch, "scoreform")
    )
    selected = _six_students(review)[:3]
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    receipts = TeacherActionReceiptStore(root, CLASS)
    initial_ids = {receipt.action_id for receipt in receipts.list_receipts()}
    original_apply = PreparedGuidedAction.apply
    applied = 0

    def crash_after_second(self: PreparedGuidedAction, *, confirmed: bool):
        nonlocal applied
        result = original_apply(self, confirmed=confirmed)
        applied += 1
        if applied == 2:
            raise RuntimeError("synthetic crash after canonical second action")
        return result

    started = perf_counter()
    with monkeypatch.context() as patch:
        patch.setattr(PreparedGuidedAction, "apply", crash_after_second)
        interrupted = execute_batch_with_sealed_progress(
            root,
            plan,
            confirmed=True,
            prepared=prepared,
            grade_item=grade_item,
            dependencies=deps,
        )
    elapsed = perf_counter() - started
    assert applied == 2
    assert interrupted.stopped
    assert interrupted.stop_reason == "item_apply_uncertain"
    assert interrupted.verified_current_count == 1
    assert [row.status for row in interrupted.items] == [
        "applied",
        "recovery_required",
        "not_attempted",
    ]
    latest_ids = {receipt.action_id for receipt in receipts.list_receipts()}
    assert len(latest_ids - initial_ids) == 2
    by_id = {row.source.item_id: row for row in plan.items}
    for result in interrupted.items[:2]:
        decision = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, by_id[result.source_item_id].source
        )
        assert decision is not None
        assert decision.decision.disposition == "included"
        assert decision.decision.eligibility_revision == 1
    last = by_id[interrupted.items[2].source_item_id]
    assert (
        load_current_evidence_eligibility_decision(root, CLASS, grade_id, last.source)
        is None
    )
    assert BatchEligibilityProgressStore(root, CLASS).load(plan, last) is None

    before = _all_bytes(root)
    recovered = _reconcile(root, plan, diagnostics)
    assert recovered.verified_action_count == 2
    assert recovered.unstarted_action_count == 1
    assert recovered.selection_resume_count == 0
    assert not recovered.requires_attention
    assert _all_bytes(root) == before

    refused = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert refused.stopped
    assert refused.verified_current_count == 0
    assert _all_bytes(root) == before

    with pytest.raises(BatchEligibilityRecoveryError):
        reconcile_sealed_eligibility_batch(
            root,
            plan,
            authorized_loader=lambda *_: None,
            actor_checker=_actor_now,
        )
    assert _all_bytes(root) == before
    again = _reconcile(root, plan, diagnostics)
    assert again.verified_action_count == 2
    assert again.unstarted_action_count == 1
    assert _all_bytes(root) == before
    print(
        f"G2B_POST_WRITE_INTERRUPT attempted=2 recovered_current=2 "
        f"unattempted=1 elapsed_seconds={elapsed:.3f} replay_writes=0"
    )
