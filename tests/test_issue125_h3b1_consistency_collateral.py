"""#125-H3B1: adversarial batch consistency and private progress write scope.

All identities and records here are synthetic. A mocked #122 action checks
batch orchestration; a real progress store checks bounded filesystem effects.
These tests do NOT substitute for installed canonical 174-action acceptance.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from test_issue125_slicec_batch_review_plan import make_review
from test_issue125_slicec_batch_review_plan import plan as make_plan
from test_issue125_sliced_batch_execution import FakeBatchHarness
from test_issue125_slicee1_progress_links import action_for, setup
from test_issue125_slicee2_recovery import authorize_for, inspect, seed

import meridian.assessment_eligibility_execution as execution
import meridian.assessment_eligibility_progress as progress
import meridian.assessment_eligibility_recovery as recovery


def _statuses(outcome: execution.BatchEligibilityOutcome) -> tuple[str, ...]:
    return tuple(row.status for row in outcome.items)


def _run_with_hook(
    harness: FakeBatchHarness,
    plan: object,
    before_apply: object,
) -> execution.BatchEligibilityOutcome:
    return execution.execute_batch_eligibility_plan(
        "synthetic_workspace",
        plan,
        confirmed=True,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=cast(object, before_apply),
    )


@pytest.mark.parametrize("position", (0, 2, 3))
def test_selected_pointer_race_blocks_only_later_work(
    monkeypatch: pytest.MonkeyPatch, position: int
) -> None:
    review = make_review(student_count=1, questions=4)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    original_capture = execution.capture_batch_pointer_witnesses
    single_checks = 0

    def changing_capture(*args: object, **kwargs: object) -> object:
        nonlocal single_checks
        result = original_capture(*args, **kwargs)
        selected = args[3]
        if len(selected) == 1:
            single_checks += 1
            if single_checks == position + 1:
                return (replace(result[0], membership_sha256="f" * 64),)
        return result

    monkeypatch.setattr(execution, "capture_batch_pointer_witnesses", changing_capture)
    outcome = harness.run(plan)
    assert outcome.stopped and outcome.stop_reason == "item_preflight_failed"
    assert _statuses(outcome) == (
        ("applied",) * position
        + ("blocked_before_write",)
        + ("not_attempted",) * (3 - position)
    )
    assert harness.events.count("apply") == position
    assert outcome.verified_current_count == position
    assert single_checks == position + 1


@pytest.mark.parametrize("position", (0, 1, 3))
@pytest.mark.parametrize("status", ("written_not_current", "recovery_required"))
def test_uncertain_canonical_action_stops_after_exact_position(
    monkeypatch: pytest.MonkeyPatch, position: int, status: str
) -> None:
    review = make_review(student_count=1, questions=4)
    plan = make_plan(review)
    harness = FakeBatchHarness(
        monkeypatch, review, statuses=("applied",) * position + (status,)
    )
    outcome = harness.run(plan)
    assert outcome.stopped and outcome.stop_reason == "item_not_verified_current"
    assert _statuses(outcome) == (
        ("applied",) * position + (status,) + ("not_attempted",) * (3 - position)
    )
    assert harness.events.count("apply") == position + 1
    assert outcome.verified_current_count == position
    assert outcome.items[position].action_id == "a" * 32
    rendered = execution.render_batch_execution_outcome(outcome)
    assert "Do not blindly replay" in rendered
    assert "A partial batch does not make" in rendered
    for item in plan.items:
        assert item.source.item_id not in rendered


@pytest.mark.parametrize("position", (0, 2, 3))
def test_seal_failure_at_any_position_prevents_corresponding_apply(
    monkeypatch: pytest.MonkeyPatch, position: int
) -> None:
    review = make_review(student_count=1, questions=4)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    sealed: list[str] = []

    def before_apply(_plan: object, item: object, _action: object) -> None:
        assert harness.events.count("apply") == len(sealed)
        if len(sealed) == position:
            raise OSError("synthetic durable seal refused")
        sealed.append(item.source.item_id)

    outcome = _run_with_hook(harness, plan, before_apply)
    assert outcome.stopped and outcome.stop_reason == "progress_seal_failed"
    assert _statuses(outcome) == (
        ("applied",) * position
        + ("blocked_before_write",)
        + ("not_attempted",) * (3 - position)
    )
    assert len(sealed) == harness.events.count("apply") == position
    assert outcome.verified_current_count == position


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _populate_non_eligibility_sentinels(root: Path, class_id: str) -> None:
    class_root = root / "classes" / class_id
    for index, name in enumerate(
        (
            "attempt_selection",
            "standards_alignment",
            "grade_policy_activation",
            "proficiency",
            "grades",
            "gradebook_exports",
            "producer_publications",
            "academic_periods",
        )
    ):
        path = class_root / "meridian" / name / "frozen.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f'{{"synthetic_canary":{index}}}\n'.encode())


def test_real_progress_sealing_touches_only_expected_private_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch, questions=3)
    _populate_non_eligibility_sentinels(tmp_path, plan.class_id)
    before = _snapshot(tmp_path)
    for index, item in enumerate(plan.items, 1):
        action = action_for(plan, item, action_id=f"{index:032x}")
        link = store.seal(plan, item, action)
        assert store.load(plan, item) == link
        assert store.seal(plan, item, action) == link
    after = _snapshot(tmp_path)
    assert all(after[name] == content for name, content in before.items())
    new_files = set(after) - set(before)
    expected = {
        path.relative_to(tmp_path).as_posix()
        for path in store.directory.rglob("*.json")
    }
    assert new_files == expected and len(new_files) == 3
    expected_prefix = store.directory.relative_to(tmp_path).as_posix() + "/"
    assert all(path.startswith(expected_prefix) for path in new_files)
    assert all(
        b"Sample" not in after[name] and b"student_" not in after[name]
        for name in new_files
    )


def test_sealed_action_id_conflict_cannot_touch_other_domains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch, questions=2)
    _populate_non_eligibility_sentinels(tmp_path, plan.class_id)
    item = plan.items[0]
    original = action_for(plan, item, action_id="a" * 32)
    store.seal(plan, item, original)
    before = _snapshot(tmp_path)
    with pytest.raises(progress.BatchEligibilityProgressError, match="Prior action"):
        store.seal(plan, item, action_for(plan, item, action_id="b" * 32))
    assert _snapshot(tmp_path) == before
    assert store.load(plan, item).action_id == "a" * 32


@pytest.mark.parametrize("denied_index", (0, 1, 3))
def test_recovery_denial_at_any_selected_item_yields_no_partial_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied_index: int
) -> None:
    plan, store, _ = seed(tmp_path, monkeypatch, questions=4)
    before = _snapshot(tmp_path)
    calls: list[str] = []

    def loader(root: Path, source: object) -> object:
        calls.append(source.item_id)
        if len(calls) - 1 == denied_index:
            raise PermissionError("synthetic scope narrowed")
        return authorize_for(plan)(root, source)

    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda *a, **k: pytest.fail("No partial receipt reads are allowed"),
    )
    with pytest.raises(recovery.BatchEligibilityRecoveryError, match="authorization"):
        recovery.reconcile_sealed_eligibility_batch(
            tmp_path,
            plan,
            authorized_loader=loader,
            actor_checker=lambda _: None,
        )
    assert len(calls) == denied_index + 1
    assert _snapshot(tmp_path) == before
    assert len(tuple(store.directory.rglob("*.json"))) == 4


def test_repeat_reconciliation_reads_every_item_without_resealing_or_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, actions = seed(tmp_path, monkeypatch, questions=4)
    before = _snapshot(tmp_path)
    seen: list[str] = []

    def inspect_current(
        _root: Path, _plan: object, item: object, **kw: object
    ) -> object:
        seen.append(item.source.item_id)
        return inspect(
            item,
            "already_applied",
            action_id=actions[item.source.item_id].preview.action_id,
        )

    monkeypatch.setattr(recovery, "inspect_sealed_batch_item", inspect_current)
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("Read-only reconciliation may not resume"),
    )
    for _ in range(2):
        report = recovery.reconcile_sealed_eligibility_batch(
            tmp_path,
            plan,
            authorized_loader=authorize_for(plan),
            actor_checker=lambda _: None,
        )
        assert not report.stopped
        assert report.verified_action_count == 4
        assert report.unstarted_action_count == 0
        assert not report.requires_attention
        assert _snapshot(tmp_path) == before
    expected = [item.source.item_id for item in plan.items]
    assert seen == expected * 2
    assert len(tuple(store.directory.rglob("*.json"))) == 4


def test_cancelled_plan_never_enters_durable_progress_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, review = setup(tmp_path, monkeypatch, questions=3)
    _populate_non_eligibility_sentinels(tmp_path, plan.class_id)
    before = _snapshot(tmp_path)
    harness = FakeBatchHarness(monkeypatch, review)
    outcome = execution.execute_batch_eligibility_plan(
        tmp_path,
        plan,
        confirmed=False,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=lambda *_: pytest.fail("Cancelled plan must never seal"),
    )
    assert not outcome.confirmed and not outcome.stopped
    assert outcome.counts == (("cancelled", 3),)
    assert not harness.events
    assert _snapshot(tmp_path) == before
