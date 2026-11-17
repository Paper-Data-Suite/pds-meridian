"""#125-E1: synthetic crash-boundary sealing and read-only #122 inspection."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from test_issue125_slicec_batch_review_plan import make_review
from test_issue125_slicec_batch_review_plan import plan as make_plan
from test_issue125_sliced_batch_execution import FakeBatchHarness

import meridian.assessment_eligibility_execution as execution
import meridian.assessment_eligibility_progress as progress
from meridian.teacher_action_contract import (
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)


def setup(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, questions: int = 2
) -> tuple[object, progress.BatchEligibilityProgressStore, object]:
    review = make_review(student_count=1, questions=questions)
    plan = make_plan(review)
    (root / "classes" / plan.class_id).mkdir(parents=True)
    monkeypatch.setattr(progress, "PreparedGuidedAction", SimpleNamespace)
    return plan, progress.BatchEligibilityProgressStore(root, plan.class_id), review


def action_for(
    plan: object, item: object, *, action_id: str = "a" * 32
) -> SimpleNamespace:
    scope = TeacherActionScope(
        workspace_sha256="f" * 64,
        class_id=plan.class_id,
        grade_item_id=plan.grade_item_id,
    )
    identity = progress._identity(
        "eligibility",
        plan.class_id,
        plan.grade_item_id,
        plan.work.module_id,
        plan.work.work_id,
        item.source.publication_id,
        item.source.item_id,
    )
    target = TeacherActionTarget(
        "eligibility",
        identity,
        1,
        "b" * 64,
        item.witness.selected_revision,
        item.witness.selected_sha256,
    )
    preview = TeacherActionPreview(
        action_id=action_id,
        kind="eligibility",
        scope=scope,
        actor=plan.actor,
        target=target,
        basis=(TeacherActionBasis("canonical_source", identity, "b" * 64),),
        reviewed_decision_sha256="b" * 64,
    )
    return SimpleNamespace(preview=preview)


def test_seal_persists_minimal_exact_reference_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    action = action_for(plan, item)
    assert store.load(plan, item) is None
    expected = store.seal(plan, item, action)
    assert store.load(plan, item) == expected
    assert store.seal(plan, item, action) == expected
    assert expected.action_id == "a" * 32
    assert expected.intent_sha256 == action.preview.intent_sha256
    paths = tuple(store.directory.rglob("*.json"))
    assert len(paths) == 1
    assert item.source.item_id not in paths[0].name
    assert b"Sample" not in paths[0].read_bytes()
    assert b"student_" not in paths[0].read_bytes()


def test_conflicting_new_action_id_cannot_replace_existing_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    original = store.seal(plan, item, action_for(plan, item))
    with pytest.raises(progress.BatchEligibilityProgressError, match="Prior action"):
        store.seal(plan, item, action_for(plan, item, action_id="c" * 32))
    assert store.load(plan, item) == original


def test_wrong_actor_pointer_or_source_cannot_be_sealed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    base = action_for(plan, item)
    wrong_target = replace(
        base.preview.target,
        expected_current_revision=1,
        expected_current_sha256="c" * 64,
    )
    invalid = (
        replace(base.preview, target=wrong_target),
        replace(base.preview, actor=replace(plan.actor, actor_id="other")),
        replace(
            base.preview, target=replace(base.preview.target, identity_sha256="d" * 64)
        ),
    )
    for preview in invalid:
        with pytest.raises(progress.BatchEligibilityProgressError):
            store.seal(plan, item, SimpleNamespace(preview=preview))
    assert store.load(plan, item) is None


def test_corrupt_link_is_not_automatically_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    store.seal(plan, item, action_for(plan, item))
    path = tuple(store.directory.rglob("*.json"))[0]
    path.write_bytes(b'{"truncated":')
    with pytest.raises(progress.BatchEligibilityProgressError, match="Corrupt"):
        store.load(plan, item)
    with pytest.raises(progress.BatchEligibilityProgressError):
        store.seal(plan, item, action_for(plan, item))


def test_unregistered_class_is_not_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    plan = make_plan(review)
    monkeypatch.setattr(progress, "PreparedGuidedAction", SimpleNamespace)
    store = progress.BatchEligibilityProgressStore(tmp_path, plan.class_id)
    with pytest.raises(progress.BatchEligibilityProgressError, match="unregistered"):
        store.seal(plan, plan.items[0], action_for(plan, plan.items[0]))
    assert not (tmp_path / "classes" / plan.class_id).exists()


def test_tampered_plan_digest_blocks_reads_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    changed = replace(plan, plan_sha256="e" * 64)
    with pytest.raises(progress.BatchEligibilityProgressError, match="Plan scope"):
        store.load(changed, item)
    with pytest.raises(progress.BatchEligibilityProgressError, match="Plan scope"):
        store.seal(changed, item, action_for(plan, item))


def test_deferred_item_cannot_generate_a_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = replace(plan.items[0], status="deferred", disposition=None)
    with pytest.raises(progress.BatchEligibilityProgressError):
        store.seal(plan, item, action_for(plan, plan.items[0]))


def test_29_by_6_action_links_are_exact_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=29, questions=6)
    plan = make_plan(review)
    (tmp_path / "classes" / plan.class_id).mkdir(parents=True)
    monkeypatch.setattr(progress, "PreparedGuidedAction", SimpleNamespace)
    store = progress.BatchEligibilityProgressStore(tmp_path, plan.class_id)
    for item in plan.items:
        action_id = hashlib.sha256(item.source.item_id.encode()).hexdigest()[:32]
        store.seal(plan, item, action_for(plan, item, action_id=action_id))
    assert len(tuple(store.directory.rglob("*.json"))) == 174
    assert len({store.load(plan, item).action_id for item in plan.items}) == 174


def test_pre_apply_hook_runs_before_every_canonical_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=3)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    links: list[str] = []

    def before_apply(_plan: object, item: object, _action: object) -> None:
        assert harness.events.count("apply") == len(links)
        links.append(item.source.item_id)

    outcome = execution.execute_batch_eligibility_plan(
        "synthetic_workspace",
        plan,
        confirmed=True,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=before_apply,
    )
    assert not outcome.stopped
    assert len(links) == harness.events.count("apply") == 3


def test_seal_failure_stops_before_first_write_and_before_later_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=3)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)

    def fail(*_args: object) -> None:
        raise OSError("No durable progress write")

    outcome = execution.execute_batch_eligibility_plan(
        "synthetic_workspace",
        plan,
        confirmed=True,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=fail,
    )
    assert outcome.stop_reason == "progress_seal_failed"
    assert outcome.counts == (("blocked_before_write", 1), ("not_attempted", 2))
    assert "apply" not in harness.events


def test_cancel_never_seals_or_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    review = make_review(student_count=1, questions=3)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)

    def forbidden(*_args: object) -> None:
        raise AssertionError("Cancellation must never seal")

    outcome = execution.execute_batch_eligibility_plan(
        "synthetic_workspace",
        plan,
        confirmed=False,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
        before_apply=forbidden,
    )
    assert outcome.counts == (("cancelled", 3),)
    assert not harness.events


def test_unlinked_recovery_read_is_no_io_except_progress_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("Unattempted item must not touch receipt/source")

    monkeypatch.setattr(progress, "TeacherActionReceiptStore", forbidden)
    result = progress.inspect_sealed_batch_item(
        tmp_path,
        plan,
        plan.items[0],
        authorized_loader=forbidden,
        actor_checker=forbidden,
    )
    assert result.status == "not_attempted"
    assert result.action_id is None


def test_missing_receipt_is_recovery_required_not_safe_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    store.seal(plan, item, action_for(plan, item))
    monkeypatch.setattr(
        progress,
        "TeacherActionReceiptStore",
        lambda *a: SimpleNamespace(load=lambda *_: None),
    )
    result = progress.inspect_sealed_batch_item(
        tmp_path,
        plan,
        item,
        authorized_loader=lambda *_: None,
        actor_checker=lambda *_: None,
    )
    assert result.status == "recovery_required"
    assert result.reason == "missing_receipt"
    assert result.action_id == "a" * 32


@pytest.mark.parametrize(
    "status,can_resume",
    [
        ("already_applied", False),
        ("written_not_current", True),
        ("recovery_required", False),
    ],
)
def test_receipt_requires_fresh_122_canonical_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    can_resume: bool,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    action = action_for(plan, item)
    store.seal(plan, item, action)
    receipt = SimpleNamespace(preview=action.preview)
    monkeypatch.setattr(
        progress,
        "TeacherActionReceiptStore",
        lambda *a: SimpleNamespace(load=lambda *_: receipt),
    )
    inspected = []

    def fake_inspect(*args: object, **kwargs: object) -> object:
        inspected.append((args, kwargs))
        return SimpleNamespace(
            status=status, reason="canonical_evidence", can_resume=can_resume
        )

    monkeypatch.setattr(progress, "inspect_restart_eligibility", fake_inspect)
    result = progress.inspect_sealed_batch_item(
        tmp_path,
        plan,
        item,
        authorized_loader=lambda *_: None,
        actor_checker=lambda *_: None,
    )
    assert result.status == status
    assert result.can_resume_exact_selection == can_resume
    assert len(inspected) == 1


def test_mismatched_receipt_never_reaches_canonical_inspector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    action = action_for(plan, item)
    store.seal(plan, item, action)
    wrong = SimpleNamespace(preview=replace(action.preview, action_id="c" * 32))
    monkeypatch.setattr(
        progress,
        "TeacherActionReceiptStore",
        lambda *a: SimpleNamespace(load=lambda *_: wrong),
    )
    monkeypatch.setattr(
        progress,
        "inspect_restart_eligibility",
        lambda *a, **k: pytest.fail("Must not trust mismatched receipt"),
    )
    result = progress.inspect_sealed_batch_item(
        tmp_path,
        plan,
        item,
        authorized_loader=lambda *_: None,
        actor_checker=lambda *_: None,
    )
    assert result.status == "conflict_requires_review"
    assert result.can_resume_exact_selection is False


def test_canonical_inspector_failure_never_claims_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch)
    item = plan.items[0]
    action = action_for(plan, item)
    store.seal(plan, item, action)
    monkeypatch.setattr(
        progress,
        "TeacherActionReceiptStore",
        lambda *a: SimpleNamespace(
            load=lambda *_: SimpleNamespace(preview=action.preview)
        ),
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("Store unavailable")

    monkeypatch.setattr(progress, "inspect_restart_eligibility", fail)
    result = progress.inspect_sealed_batch_item(
        tmp_path,
        plan,
        item,
        authorized_loader=lambda *_: None,
        actor_checker=lambda *_: None,
    )
    assert result.status == "recovery_required"
    assert not result.can_resume_exact_selection


def test_wrapper_uses_seal_hook_for_fresh_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=2)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)
    sealed: list[str] = []

    class FakeStore:
        def __init__(self, root: object, class_id: str) -> None:
            self.root = Path(root).absolute()
            assert class_id == plan.class_id

        def seal(self, selected: object, item: object, action: object) -> None:
            assert selected == plan
            sealed.append(item.source.item_id)

    monkeypatch.setattr(progress, "BatchEligibilityProgressStore", FakeStore)
    outcome = progress.execute_batch_with_sealed_progress(
        "synthetic_workspace",
        plan,
        confirmed=True,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
    )
    assert not outcome.stopped
    assert sealed == [item.source.item_id for item in plan.items]
    assert harness.events.count("apply") == 2


def test_wrapper_cancel_does_not_instantiate_progress_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=1, questions=1)
    plan = make_plan(review)
    harness = FakeBatchHarness(monkeypatch, review)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("No store may be created before confirmation")

    monkeypatch.setattr(progress, "BatchEligibilityProgressStore", forbidden)
    outcome = progress.execute_batch_with_sealed_progress(
        "synthetic_workspace",
        plan,
        confirmed=False,
        prepared=cast(execution.GuidedProjectionResult, harness.prepared),
        grade_item=harness.grade_item,
        dependencies=cast(
            execution.GuidedEligibilityDependencies, harness.dependencies
        ),
    )
    assert outcome.counts == (("cancelled", 1),)
    assert not harness.events


def test_symlinked_private_progress_folder_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = setup(tmp_path, monkeypatch, questions=1)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    store.directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        store.directory.symlink_to(elsewhere, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is restricted on this workstation")
    with pytest.raises(progress.BatchEligibilityProgressError, match="Link"):
        store.seal(plan, plan.items[0], action_for(plan, plan.items[0]))
    assert not tuple(elsewhere.iterdir())
