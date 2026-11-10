"""#125-H3C1: native candidate-wheel full-class eligibility execution benchmark.

Requires the explicitly enabled isolated Meridian candidate and official producer
wheels. All 29 students and publications are synthetic. This tests 174 exact
question-correctness actions against 406 ScoreForm evidence items; it does NOT
claim that the ordinary teacher menu selects the subset with a single keypress.
"""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter

import pytest
from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
from test_issue125_h3b2_native_write_isolation import (
    _eligible_rows,
    _write_inventory,
)
from test_issue125_sliceg2a_canonical_batch_acceptance import (
    _build_plan,
    _ready_native,
)

from meridian.assessment_eligibility_progress import (
    BatchEligibilityProgressStore,
    execute_batch_with_sealed_progress,
)
from meridian.assessment_eligibility_recovery import (
    reconcile_sealed_eligibility_batch,
)
from meridian.assessment_eligibility_review import (
    project_assessment_eligibility_review,
)
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.menu_teacher_assessment_eligibility import _enumerate_candidates
from meridian.teacher_action_guided import _actor_now
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_eligibility import (
    load_fresh_restart_authorization,
)

_NATIVE = os.environ.get("PDS_ISSUE125_H3C1_NATIVE_TEST") == "1"
pytestmark = pytest.mark.skipif(
    not _NATIVE,
    reason="Requires isolated official producer and Meridian candidate wheels",
)


def test_installed_174_canonical_actions_and_exact_no_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measure 174 real writes and 174-source repeated review, not mocked applies."""
    from functools import partial

    root, grade_id, prepared, review, deps, grade_item, diagnostics, actor = (
        _ready_native(tmp_path, monkeypatch, "scoreform")
    )
    assert len(review.students) == 29
    assert review.projected_item_count == 406
    all_candidates = _enumerate_candidates(review)
    assert len(all_candidates) >= 174
    correctness = _eligible_rows(review, "scoreform")
    assert len(correctness) == 174
    selected = tuple(item.source.item_id for item in correctness)
    assert len(selected) == len(set(selected)) == 174
    assert set(selected).issubset({row[0] for row in all_candidates})
    chosen_set = set(selected)
    untouched = tuple(
        row
        for student in review.students
        for row in student.items
        if row.source.item_id not in chosen_set
    )
    assert len(untouched) == 232

    preplan_bytes = _all_bytes(root)
    plan_start = perf_counter()
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    planning_seconds = perf_counter() - plan_start
    assert plan.action_count == 174
    assert plan.blocked_count == plan.deferred_count == 0
    assert _all_bytes(root) == preplan_bytes

    cancelled = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=False,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not cancelled.confirmed and not cancelled.stopped
    assert cancelled.verified_current_count == 0
    assert cancelled.counts == (("cancelled", 174),)
    assert _all_bytes(root) == preplan_bytes
    assert not (
        BatchEligibilityProgressStore(root, CLASS).directory / plan.plan_sha256
    ).exists()

    receipts = TeacherActionReceiptStore(root, CLASS)
    receipt_ids_before = {entry.action_id for entry in receipts.list_receipts()}
    before = _all_bytes(root)
    execution_start = perf_counter()
    result = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    execution_seconds = perf_counter() - execution_start
    assert not result.stopped, (result.stop_reason, result.counts)
    assert result.confirmed and result.verified_current_count == 174
    assert result.counts == (("applied", 174),)
    assert len(result.items) == 174
    assert {row.source_item_id for row in result.items} == set(selected)
    action_ids = {row.action_id for row in result.items}
    assert None not in action_ids and len(action_ids) == 174
    new_receipt_ids = {r.action_id for r in receipts.list_receipts()}
    assert len(new_receipt_ids - receipt_ids_before) == 174
    after = _all_bytes(root)
    changes = _write_inventory(before, after)
    progress = BatchEligibilityProgressStore(root, CLASS)

    for item in plan.items:
        stored = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, item.source
        )
        assert stored is not None
        assert stored.decision.disposition == "included"
        assert stored.decision.eligibility_revision == 1
        assert progress.load(plan, item) is not None
    for item in untouched:
        assert (
            load_current_evidence_eligibility_decision(
                root, CLASS, grade_id, item.source
            )
            is None
        )
    assert _all_bytes(root) == after

    # The old action plan is stale: no second attempt may author or select it.
    repeat_start = perf_counter()
    old = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert old.stopped and old.verified_current_count == 0
    assert _all_bytes(root) == after

    # A NEW read-only review sees the exact 174 decided items as unchanged.
    updated = project_assessment_eligibility_review(
        root, grade_item_id=grade_id, prepared=prepared
    )
    fresh = _build_plan(root, prepared, updated, deps, actor, selected)
    assert fresh.action_count == 0
    assert len(fresh.items) == 174
    assert all(item.status == "unchanged" for item in fresh.items)
    repeat = execute_batch_with_sealed_progress(
        root,
        fresh,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not repeat.stopped, (repeat.stop_reason, repeat.counts)
    assert repeat.counts == (("unchanged", 174),)
    assert _all_bytes(root) == after

    loader = partial(load_fresh_restart_authorization, diagnostics=diagnostics)
    for _ in range(2):
        reconciled = reconcile_sealed_eligibility_batch(
            root, plan, authorized_loader=loader, actor_checker=_actor_now
        )
        assert reconciled.verified_action_count == 174
        assert reconciled.unstarted_action_count == 0
        assert reconciled.selection_resume_count == 0
        assert not reconciled.requires_attention
        assert _all_bytes(root) == after
    repeat_seconds = perf_counter() - repeat_start
    assert {entry.action_id for entry in receipts.list_receipts()} == (
        receipt_ids_before | action_ids
    )
    print(
        "H3C1_FULL174 "
        f"evidence=406 correctness=174 other=232 "
        f"all_menu_candidates={len(all_candidates)} "
        f"canonical_applied={result.verified_current_count} "
        f"changed_paths={len(changes)} "
        f"plan_seconds={planning_seconds:.3f} "
        f"execution_seconds={execution_seconds:.3f} "
        f"repeat_seconds={repeat_seconds:.3f} "
        "stale_replay=0 fresh_noops=174 "
        "collateral_paths=0",
        flush=True,
    )
