"""#125-E2: synthetic canonical reconciliation and exact selection-only restart."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_issue125_slicec_batch_review_plan import make_review
from test_issue125_slicec_batch_review_plan import plan as make_plan
from test_issue125_slicee1_progress_links import action_for, setup

import meridian.assessment_eligibility_recovery as recovery
from meridian.assessment_eligibility_progress import BatchActionRecoveryInspection
from meridian.teacher_action_contract import TeacherActionRecord, TeacherActionResult


def authorize_for(plan: object):
    def load(_root: Path, source: object) -> SimpleNamespace:
        publication = SimpleNamespace(
            work=plan.work, publication_id=plan.publication_id
        )
        return SimpleNamespace(
            current_context=SimpleNamespace(publication=publication),
            stored=SimpleNamespace(
                cache_key=source.cache_key,
                snapshot_digest=source.snapshot_digest,
                snapshot=SimpleNamespace(
                    source=SimpleNamespace(publication=publication),
                    inventory=SimpleNamespace(
                        items=(SimpleNamespace(item_id=source.item_id),),
                    ),
                ),
            ),
            assessment=SimpleNamespace(reusable_for_current_use=True),
            cache_read_authorization=SimpleNamespace(allowed=True),
            current_projection_authorization=SimpleNamespace(allowed=True),
        )

    return load


def inspect(
    row: object,
    status: str,
    *,
    resume: bool = False,
    action_id: str | None = None,
) -> BatchActionRecoveryInspection:
    return BatchActionRecoveryInspection(
        row.source.item_id,
        status,
        "eligible_to_resume" if resume else status,
        resume,
        action_id,
    )


def success(receipt: object) -> TeacherActionResult:
    preview = receipt.preview
    target = preview.target
    record = TeacherActionRecord(
        "eligibility",
        target.identity_sha256,
        target.revision,
        target.candidate_sha256,
        "created",
    )
    return TeacherActionResult(
        action_id=preview.action_id,
        intent_sha256=preview.intent_sha256,
        target=target,
        status="applied",
        persisted=(record,),
        current_state="matches",
        current_record=record,
        selection_disposition="created",
    )


def seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, questions: int = 2):
    plan, store, _ = setup(tmp_path, monkeypatch, questions=questions)
    actions = {}
    for i, item in enumerate(plan.items):
        action = action_for(plan, item, action_id=f"{i + 1:032x}")
        store.seal(plan, item, action)
        actions[item.source.item_id] = action
    return plan, store, actions


def stub_receipts(monkeypatch: pytest.MonkeyPatch, actions: dict[str, object]):
    by_id = {
        action.preview.action_id: SimpleNamespace(preview=action.preview)
        for action in actions.values()
    }
    store = SimpleNamespace(load=lambda action_id: by_id.get(action_id))
    monkeypatch.setattr(recovery, "TeacherActionReceiptStore", lambda *a: store)
    return store


def test_no_sealed_items_reports_unstarted_without_canonical_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch, questions=3)
    report = recovery.reconcile_sealed_eligibility_batch(
        tmp_path,
        plan,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.unstarted_action_count == 3
    assert report.verified_action_count == 0
    assert report.selection_resume_count == 0
    assert report.counts == (("not_attempted", 3),)
    assert "fresh authorized review" in recovery.render_batch_recovery_report(report)


def test_all_sealed_items_are_independently_rechecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=3)
    seen = []
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: (
            seen.append(item.source.item_id)
            or inspect(
                item,
                "already_applied",
                action_id=actions[item.source.item_id].preview.action_id,
            )
        ),
    )
    report = recovery.reconcile_sealed_eligibility_batch(
        tmp_path,
        plan,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert seen == [x.source.item_id for x in plan.items]
    assert report.verified_action_count == 3
    assert not report.requires_attention


def test_29_by_6_is_bounded_and_never_collapses_item_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = make_review(student_count=29, questions=6)
    plan = make_plan(review)
    seen = []
    report = recovery.reconcile_sealed_eligibility_batch(
        tmp_path,
        plan,
        authorized_loader=lambda root, source: (
            seen.append(source.item_id) or authorize_for(plan)(root, source)
        ),
        actor_checker=lambda _: None,
    )
    assert len(seen) == len(report.items) == 174
    assert report.counts == (("not_attempted", 174),)


def test_denied_authorization_refuses_to_return_partial_roster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch, questions=3)
    called = []

    def loader(root, source):
        called.append(source.item_id)
        if len(called) == 2:
            raise PermissionError("scope narrowed")
        return authorize_for(plan)(root, source)

    with pytest.raises(recovery.BatchEligibilityRecoveryError, match="authorization"):
        recovery.reconcile_sealed_eligibility_batch(
            tmp_path,
            plan,
            authorized_loader=loader,
            actor_checker=lambda _: None,
        )
    assert len(called) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "publication",
        "cache",
        "reusable",
        "snapshot",
        "missing_item",
        "cache_denied",
        "current_denied",
    ],
)
def test_authority_drift_prevents_any_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch)

    def loader(root, source):
        auth = authorize_for(plan)(root, source)
        if mutation == "publication":
            auth.current_context.publication.publication_id = "other"
        elif mutation == "cache":
            auth.stored.cache_key = "a" * 64
        elif mutation == "reusable":
            auth.assessment.reusable_for_current_use = False
        elif mutation == "snapshot":
            auth.stored.snapshot.source.publication = SimpleNamespace(work=plan.work)
        elif mutation == "missing_item":
            auth.stored.snapshot.inventory.items = ()
        elif mutation == "cache_denied":
            auth.cache_read_authorization.allowed = False
        else:
            auth.current_projection_authorization.allowed = False
        return auth

    with pytest.raises(recovery.BatchEligibilityRecoveryError):
        recovery.reconcile_sealed_eligibility_batch(
            tmp_path,
            plan,
            authorized_loader=loader,
            actor_checker=lambda _: None,
        )


def test_mutated_plan_digest_refused_before_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch)
    bad = replace(plan, plan_sha256="f" * 64)
    with pytest.raises(recovery.BatchEligibilityRecoveryError, match="plan"):
        recovery.reconcile_sealed_eligibility_batch(
            tmp_path,
            bad,
            authorized_loader=lambda *a: pytest.fail("reader"),
            actor_checker=lambda _: None,
        )


def test_corrupted_seal_is_recovery_required_not_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, store, _ = seed(tmp_path, monkeypatch, questions=1)
    (next(store.directory.rglob("*.json"))).write_text("{bad")
    report = recovery.reconcile_sealed_eligibility_batch(
        tmp_path,
        plan,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.items[0].status == "recovery_required"
    assert report.items[0].reason == "sealed_link_unreadable"
    assert report.unstarted_action_count == 0


def test_cancel_does_not_read_authority_or_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, _ = setup(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("No read or write on cancel")

    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=False,
        authorized_loader=forbidden,
        actor_checker=forbidden,
    )
    assert report.stopped and report.stop_reason == "cancelled_without_io"
    assert report.counts == (("not_attempted", 2),)
    assert not tuple(
        (tmp_path / "classes" / plan.class_id / "meridian").rglob("*.json")
    )


def test_missing_receipt_keeps_sealed_item_uncertain_and_stops_all(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch)
    stub_receipts(monkeypatch, {})
    # Real E1 inspection checks the absent receipt; no #122 resume call.
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("must not resume"),
    )
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped
    assert report.counts == (("recovery_required", 2),)


def test_uncertain_middle_link_blocks_all_selection_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=3)
    statuses = ("already_applied", "recovery_required", "written_not_current")
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            statuses[plan.items.index(item)],
            resume=item == plan.items[2],
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("must stop before any mutation"),
    )
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped and report.stop_reason == "uncertain_action_requires_review"
    assert report.selection_resume_count == 1


def test_exact_selection_only_resume_and_verified_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    stub_receipts(monkeypatch, actions)
    calls = []
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "written_not_current",
            resume=True,
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )

    def resume(root, receipts, receipt, *, confirmation, **kw):
        calls.append(confirmation)
        return success(receipt)

    monkeypatch.setattr(recovery, "resume_restart_eligibility", resume)
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert calls == ["RESUME"]
    assert not report.stopped
    assert report.verified_action_count == 1
    assert report.items[0].resumed_in_this_request
    assert report.items[0].status == "applied"


def test_new_action_id_in_receipt_never_restarted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    stub_receipts(monkeypatch, actions)
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "written_not_current",
            resume=True,
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "_revalidate_link_receipt",
        lambda *a: (_ for _ in ()).throw(ValueError("receipt drift")),
    )
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("must not call resume on forged receipt"),
    )
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped and report.items[0].status == "recovery_required"


def test_preflight_race_reinspection_blocks_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    stub_receipts(monkeypatch, actions)
    seen = []

    def changing(_r, _p, item, **kw):
        seen.append(None)
        return inspect(
            item,
            "written_not_current" if len(seen) == 1 else "already_applied",
            resume=len(seen) == 1,
            action_id=actions[item.source.item_id].preview.action_id,
        )

    monkeypatch.setattr(recovery, "inspect_sealed_batch_item", changing)
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("reinspection must block"),
    )
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped and len(seen) == 2


def test_uncertain_result_after_selector_write_halts_remaining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=3)
    stub_receipts(monkeypatch, actions)
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "written_not_current",
            resume=True,
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    calls = []

    def resume(_root, _receipts, receipt, *, confirmation, **kw):
        calls.append(receipt.preview.action_id)
        if len(calls) == 2:
            raise OSError("write may have happened")
        return success(receipt)

    monkeypatch.setattr(recovery, "resume_restart_eligibility", resume)
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped and len(calls) == 2
    assert report.items[0].resumed_in_this_request
    assert report.items[1].status == "recovery_required"
    assert report.items[2].status == "written_not_current"


def test_wrong_success_action_id_is_never_counted_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    stub_receipts(monkeypatch, actions)
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "written_not_current",
            resume=True,
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )

    def fraudulent(*args, **kwargs):
        preview = actions[plan.items[0].source.item_id].preview
        result = success(SimpleNamespace(preview=preview))
        return replace(result, action_id="c" * 32)

    monkeypatch.setattr(recovery, "resume_restart_eligibility", fraudulent)
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.stopped and report.verified_action_count == 0


def test_already_current_is_not_resumed_or_reauthored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=2)
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "already_applied",
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "resume_restart_eligibility",
        lambda *a, **k: pytest.fail("already current must never write"),
    )
    report = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert report.verified_action_count == 2
    assert not report.stopped


def test_restart_is_idempotent_after_canonical_changes_to_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    stub_receipts(monkeypatch, actions)
    state = ["written_not_current"]
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            state[0],
            resume=state[0] == "written_not_current",
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    calls = []

    def resume(_root, _receipts, receipt, **kw):
        calls.append(1)
        state[0] = "already_applied"
        return success(receipt)

    monkeypatch.setattr(recovery, "resume_restart_eligibility", resume)
    for _ in range(2):
        report = recovery.resume_sealed_eligibility_batch(
            tmp_path,
            plan,
            confirmed=True,
            authorized_loader=authorize_for(plan),
            actor_checker=lambda _: None,
        )
        assert report.verified_action_count == 1
    assert calls == [1]


def test_recovery_required_state_never_reauthors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, actions = seed(tmp_path, monkeypatch, questions=1)
    monkeypatch.setattr(
        recovery,
        "inspect_sealed_batch_item",
        lambda _r, _p, item, **kw: inspect(
            item,
            "recovery_required",
            action_id=actions[item.source.item_id].preview.action_id,
        ),
    )
    result = recovery.resume_sealed_eligibility_batch(
        tmp_path,
        plan,
        confirmed=True,
        authorized_loader=authorize_for(plan),
        actor_checker=lambda _: None,
    )
    assert result.stopped and result.verified_action_count == 0


def test_report_never_claims_entire_assessment_is_eligible() -> None:
    row = recovery.ReconciledBatchItem(
        "q1",
        "applied",
        "exact_selection_verified",
        "a" * 32,
        resumed_in_this_request=True,
    )
    report = recovery.BatchEligibilityRecoveryReport("f" * 64, (row,))
    text = recovery.render_batch_recovery_report(report)
    assert "Verified current individual actions: 1" in text
    assert "assessment eligible" not in text.casefold()
    assert "author" not in text.casefold()
