"""#125-H3D2: bounded CAS, seal, uncertainty and collateral-write faults.

All students/records are synthetic. The first tests exercise the batch
coordinator's precise stop/accounting contracts. Native fault cases additionally
verify real installed-wheel storage boundaries using three exact source items.
Never infer a cross-record transaction or automatic replay from a batch status.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_issue125_slicec_batch_review_plan import make_review
from test_issue125_slicec_batch_review_plan import plan as make_plan
from test_issue125_sliced_batch_execution import FakeBatchHarness
from test_issue125_slicee1_progress_links import action_for, setup
from test_issue125_sliceg2a_canonical_batch_acceptance import (
    _build_plan,
    _ready_native,
)

import meridian.assessment_eligibility_execution as execution
import meridian.assessment_eligibility_progress as progress
from meridian.teacher_action_receipts import TeacherActionReceiptStore

_NATIVE = os.environ.get("PDS_ISSUE125_H3D2_NATIVE_TEST") == "1"


def _assert_stopped_at(
    outcome: execution.BatchEligibilityOutcome, target: int, *, status: str
) -> None:
    statuses = tuple(row.status for row in outcome.items)
    assert statuses == (
        *("applied" for _ in range(target)),
        status,
        *("not_attempted" for _ in range(2 - target)),
    ), (target, statuses)
    assert outcome.stopped
    assert outcome.verified_current_count == target
    assert len(outcome.items) == 3


@pytest.mark.parametrize("target", (0, 1, 2))
def test_cas_pointer_drift_at_each_item_stops_later_mutations(
    monkeypatch: pytest.MonkeyPatch, target: int
) -> None:
    review = make_review(student_count=1, questions=3)
    planned = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    original = execution.capture_batch_pointer_witnesses
    target_id = planned.items[target].source.item_id

    def drift(*args: object, **kwargs: object) -> object:
        if tuple(args[3]) == (target_id,):
            raise OSError("Selected pointer moved before this item")
        return original(*args, **kwargs)

    monkeypatch.setattr(execution, "capture_batch_pointer_witnesses", drift)
    outcome = harness.run(planned)
    _assert_stopped_at(outcome, target, status="blocked_before_write")
    assert outcome.stop_reason == "item_preflight_failed"
    assert harness.events.count("apply") == target
    assert tuple(row.source_item_id for row in outcome.items) == tuple(
        item.source.item_id for item in planned.items
    )


@pytest.mark.parametrize("target", (0, 1, 2))
def test_progress_seal_fault_at_each_item_stops_before_its_apply(
    monkeypatch: pytest.MonkeyPatch, target: int
) -> None:
    review = make_review(student_count=1, questions=3)
    planned = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    target_id = planned.items[target].source.item_id
    sealed: list[str] = []

    def seal(_plan: object, item: object, _action: object) -> None:
        if item.source.item_id == target_id:
            raise OSError("Durable progress seal unavailable")
        sealed.append(item.source.item_id)

    outcome = execution.execute_batch_eligibility_plan(
        "synthetic_workspace",
        planned,
        confirmed=True,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=seal,
    )
    _assert_stopped_at(outcome, target, status="blocked_before_write")
    assert outcome.stop_reason == "progress_seal_failed"
    assert harness.events.count("apply") == target
    assert sealed == [item.source.item_id for item in planned.items[:target]]


@pytest.mark.parametrize("target", (0, 1, 2))
def test_apply_uncertainty_at_each_item_never_relabels_possible_write_as_blocked(
    monkeypatch: pytest.MonkeyPatch, target: int
) -> None:
    review = make_review(student_count=1, questions=3)
    planned = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    original = execution.prepare_eligibility_action
    target_id = planned.items[target].source.item_id

    def prepare(*args: object, **kwargs: object) -> object:
        action = original(*args, **kwargs)
        preview = args[3]
        if preview.decision.source.item_id != target_id:
            return action

        def uncertain(*, confirmed: bool) -> object:
            assert confirmed is True
            harness.events.append("apply")
            raise OSError("Unknown whether canonical selector committed")

        return SimpleNamespace(preview=action.preview, apply=uncertain)

    monkeypatch.setattr(execution, "prepare_eligibility_action", prepare)
    outcome = harness.run(planned)
    _assert_stopped_at(outcome, target, status="recovery_required")
    assert outcome.stop_reason == "item_apply_uncertain"
    assert outcome.items[target].action_id is not None
    assert harness.events.count("apply") == target + 1
    assert all(item.action_id is None for item in outcome.items[target + 1 :])


@pytest.mark.parametrize("target", (0, 1, 2))
def test_corrupt_progress_link_is_never_silently_resealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: int
) -> None:
    planned, store, _review = setup(tmp_path, monkeypatch, questions=3)
    links: dict[str, object] = {}
    paths: dict[str, Path] = {}
    for index, item in enumerate(planned.items):
        before = set(store.directory.rglob("*.json"))
        link = store.seal(
            planned,
            item,
            action_for(planned, item, action_id=f"{index + 1:032x}"),
        )
        new_paths = set(store.directory.rglob("*.json")) - before
        assert len(new_paths) == 1
        paths[item.source.item_id] = next(iter(new_paths))
        links[item.source.item_id] = link
    target_item = planned.items[target]
    corrupted_path = paths[target_item.source.item_id]
    corrupted_path.write_bytes(b'{"truncated":')
    with pytest.raises(progress.BatchEligibilityProgressError):
        store.load(planned, target_item)
    with pytest.raises(progress.BatchEligibilityProgressError):
        store.seal(
            planned,
            target_item,
            action_for(planned, target_item, action_id=f"{target + 1:032x}"),
        )
    assert corrupted_path.read_bytes() == b'{"truncated":'
    for item in planned.items:
        if item.source.item_id != target_item.source.item_id:
            assert store.load(planned, item) == links[item.source.item_id]


@pytest.mark.skipif(
    not _NATIVE, reason="Requires isolated official Core/producer/Meridian wheels"
)
@pytest.mark.parametrize("stage", ("cas", "seal"))
@pytest.mark.parametrize("target", (0, 1, 2))
def test_native_prewrite_fault_preserves_canonical_and_noneligibility_domains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: int, stage: str
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
    from test_issue125_h3b2_native_write_isolation import _eligible_rows

    from meridian.evidence_eligibility_storage import (
        load_current_evidence_eligibility_decision,
    )

    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    rows = _eligible_rows(review, "scoreform")[:3]
    selected = tuple(row.source.item_id for row in rows)
    planned = _build_plan(root, prepared, review, deps, actor, selected)
    assert planned.action_count == 3

    receipts = TeacherActionReceiptStore(root, CLASS)
    receipt_ids_before = {r.action_id for r in receipts.list_receipts()}
    before = _all_bytes(root)
    original_seal = progress.BatchEligibilityProgressStore.seal
    count = 0

    def failing_seal(self: object, *args: object, **kwargs: object) -> object:
        nonlocal count
        count += 1
        if count == target + 1:
            raise OSError("Synthetic disk/seal failure before canonical apply")
        return original_seal(self, *args, **kwargs)

    if stage == "seal":
        monkeypatch.setattr(
            progress.BatchEligibilityProgressStore, "seal", failing_seal
        )
    else:
        original_capture = execution.capture_batch_pointer_witnesses
        target_id = planned.items[target].source.item_id

        def drift(*args: object, **kwargs: object) -> object:
            if tuple(args[3]) == (target_id,):
                raise OSError("Concurrent native selected pointer changed")
            return original_capture(*args, **kwargs)

        monkeypatch.setattr(execution, "capture_batch_pointer_witnesses", drift)
    outcome = progress.execute_batch_with_sealed_progress(
        root,
        planned,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    _assert_stopped_at(outcome, target, status="blocked_before_write")
    assert outcome.stop_reason == (
        "progress_seal_failed" if stage == "seal" else "item_preflight_failed"
    )
    if stage == "seal":
        assert count == target + 1
    else:
        assert count == 0

    after = _all_bytes(root)
    assert before.keys() <= after.keys(), "Existing academic file removed"
    changed = {
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    }
    prefix = f"classes/{CLASS}/modules/meridian/"
    allowed = (
        prefix + "elig/",
        prefix + "teacher_action_receipts/",
        prefix + "assessment_eligibility_progress/",
    )
    assert all(key.startswith(allowed) for key in changed), sorted(changed)[:8]
    if target == 0:
        assert not changed, (
            "Failure before first action must produce no workspace writes"
        )
    else:
        assert changed, "Earlier successful actions must remain durable"

    receipt_ids_after = {r.action_id for r in receipts.list_receipts()}
    assert len(receipt_ids_after - receipt_ids_before) == target
    for index, row in enumerate(rows):
        decision = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, row.source
        )
        if index < target:
            assert decision is not None and decision.decision.disposition == "included"
        else:
            assert decision is None
    print(
        f"H3D2_NATIVE_PREWRITE_FAULT stage={stage} position={target + 1}/3 "
        f"applied={target} changed_paths={len(changed)} collateral=0",
        flush=True,
    )
