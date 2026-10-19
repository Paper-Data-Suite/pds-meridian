"""#122 Slice 15: synthetic exact-policy restart selection and fail-closed cases."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_policy import (
    _RestartPolicyPort,
    inspect_restart_policy,
    resume_restart_policy,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import meridian.teacher_action_restart_policy as restart

    (tmp_path / "classes" / "class_one").mkdir(parents=True)
    work = ModuleWorkRef("scoreform", "class_one", "work_1")
    policy_id = "teacher_guided_exactly_one"
    target = 1
    action = "create"
    actor = TeacherActionActor("teacher_one", A, "saved")
    assignment = SimpleNamespace(
        period=SimpleNamespace(school_year="2026-2027", period_id="mp1"),
        calendar_revision=1,
    )
    member = SimpleNamespace(
        decision_sha256=C,
        decision=SimpleNamespace(
            decision="included",
            academic_period=assignment,
            grade_item_revision_sha256=D,
            work_reference=SimpleNamespace(registration_revision=1),
        ),
    )
    grade = SimpleNamespace(revision_sha256=D)
    source_digest = _identity(
        "attempt_policy_source",
        work.module_id,
        work.work_id,
        policy_id,
        str(target),
        B,
        action,
        C,
        D,
        A,
    )
    identity = _identity(
        "attempt_policy",
        "class_one",
        "grade_1",
        work.module_id,
        work.work_id,
        policy_id,
    )
    preview = TeacherActionPreview(
        action_id="ab" * 16,
        kind="attempt_policy",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(tmp_path)),
            class_id="class_one",
            grade_item_id="grade_1",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=A,
            work_identity_sha256=_identity(
                "work", "class_one", work.module_id, work.work_id
            ),
        ),
        actor=actor,
        target=TeacherActionTarget(
            family="attempt_policy",
            identity_sha256=identity,
            revision=target,
            candidate_sha256=B,
            expected_current_revision=None,
            expected_current_sha256=None,
        ),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis("canonical_source", identity, source_digest),
        ),
        reviewed_decision_sha256=B,
    )
    store = TeacherActionReceiptStore(tmp_path, "class_one")
    receipt = store.prepare(preview)
    receipt = store.record_checkpoint(
        preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    state = {
        "current": None,
        "history": (1,),
        "digest": B,
        "member": True,
        "grade": True,
        "calendar": True,
        "registration": True,
        "identity": True,
        "selected": 0,
        "writes": 0,
    }
    policy = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_1",
        work=work,
        policy_id=policy_id,
        policy_revision=1,
        selection_basis="explicit",
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_one"),
    )
    stored = SimpleNamespace(policy=policy, policy_sha256=B)

    def identity_loader(*_args, **_kwargs):
        if not state["identity"]:
            return ()
        return (("grade_1", work, policy_id),)

    def current(*_args):
        return None if state["current"] is None else stored

    def preview_selection(*_args):
        return SimpleNamespace(
            target_sha256=B,
            expected_current_policy_revision=state["current"],
            history=state["history"],
        )

    def commit_selection(_root, _preview, *, currentness_check=None):
        assert currentness_check is not None
        currentness_check()
        if state["current"] is not None:
            raise TeacherActionConflictError("Synthetic stale CAS")
        state["current"] = 1
        state["selected"] += 1
        return SimpleNamespace(
            selected_policy_sha256=B, selection_disposition="created"
        )

    monkeypatch.setattr(
        restart, "list_attempt_selection_policy_identities", identity_loader
    )
    monkeypatch.setattr(
        restart,
        "list_attempt_selection_policy_revisions",
        lambda *_args: state["history"],
    )
    monkeypatch.setattr(
        restart,
        "load_attempt_selection_policy_revision",
        lambda *_args: SimpleNamespace(policy=policy, policy_sha256=state["digest"]),
    )
    monkeypatch.setattr(restart, "load_current_attempt_selection_policy", current)
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_membership_decision",
        lambda *_args: member if state["member"] else None,
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_revision",
        lambda *_args: grade if state["grade"] else None,
    )
    monkeypatch.setattr(
        restart, "validate_grade_item_membership_dependencies", lambda *_args: None
    )
    monkeypatch.setattr(
        restart,
        "get_current_academic_work_registration_revision",
        lambda *_args: 1 if state["registration"] else 2,
    )
    monkeypatch.setattr(
        restart, "_calendar_digest", lambda *_args: A if state["calendar"] else D
    )
    monkeypatch.setattr(restart, "preview_attempt_policy_selection", preview_selection)
    monkeypatch.setattr(
        restart, "commit_attempt_policy_selection_preview", commit_selection
    )

    def checker(_actor: object) -> None:
        return None

    return SimpleNamespace(
        root=tmp_path,
        receipt=receipt,
        store=store,
        state=state,
        checker=checker,
        preview=preview,
    )


def test_restart_inspection_is_read_only(example):
    checked = inspect_restart_policy(
        example.root,
        example.store,
        example.receipt,
        actor_checker=example.checker,
    )
    assert checked.can_resume
    assert checked.reason == "eligible_to_resume"
    assert example.state["selected"] == example.state["writes"] == 0


def test_exact_restart_selects_without_authoring(example):
    result = resume_restart_policy(
        example.root,
        example.store,
        example.receipt,
        confirmation="RESUME",
        actor_checker=example.checker,
    )
    assert result.succeeded and result.status == "applied"
    assert example.state["selected"] == 1
    assert example.state["writes"] == 0
    finalized = example.store.load(example.receipt.action_id)
    assert finalized is not None
    assert not inspect_restart_policy(
        example.root,
        example.store,
        finalized,
        actor_checker=example.checker,
    ).can_resume


def test_restart_cancellation_makes_no_changes(example):
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_policy(
            example.root,
            example.store,
            example.receipt,
            confirmation="CANCEL",
            actor_checker=example.checker,
        )
    assert example.state["selected"] == 0


def test_recovery_port_has_no_immutable_writer(example):
    port = _RestartPolicyPort(example.root, example.receipt, example.checker)
    with pytest.raises(TeacherActionConflictError, match="never writes"):
        port.persist_exact(example.preview)


@pytest.mark.parametrize(
    "reason",
    ["history", "digest", "member", "grade", "calendar", "registration", "identity"],
)
def test_changed_canonical_basis_blocks_recovery(example, reason):
    state = example.state
    if reason == "history":
        state["history"] = (1, 2)
    elif reason == "digest":
        state["digest"] = D
    else:
        state[reason] = False
    with pytest.raises((TeacherActionConflictError, ValueError, RuntimeError)):
        inspect_restart_policy(
            example.root,
            example.store,
            example.receipt,
            actor_checker=example.checker,
        )
    assert state["selected"] == 0


def test_changed_actor_blocks_without_selection(example):
    def refuse(_actor):
        raise TeacherActionConflictError("Teacher profile changed")

    with pytest.raises(TeacherActionConflictError, match="profile"):
        inspect_restart_policy(
            example.root, example.store, example.receipt, actor_checker=refuse
        )
    assert example.state["selected"] == 0


def test_missing_receipt_blocks_recovery(example):
    with pytest.raises(TeacherActionConflictError, match="Journal changed"):
        inspect_restart_policy(
            example.root,
            example.store,
            SimpleNamespace(action_id="ff" * 16, preview=example.preview),
            actor_checker=example.checker,
        )
    assert example.state["selected"] == 0


def test_menu_explicit_confirmation_and_cancel(example, monkeypatch):
    import meridian.menu_teacher_action_recovery as menu

    entry = SimpleNamespace(receipt=example.receipt)
    monkeypatch.setattr(
        menu,
        "inspect_restart_policy",
        lambda *_args: SimpleNamespace(can_resume=True),
    )
    commits = []
    monkeypatch.setattr(
        menu,
        "resume_restart_policy",
        lambda *_args, **_kwargs: commits.append(True),
    )
    rendered = StringIO()
    menu._offer_policy_resume(
        example.root,
        example.store,
        entry,
        input_fn=lambda _prompt: "CANCEL",
        output=rendered,
    )
    assert commits == []
    assert "Type RESUME" in rendered.getvalue()


def test_policy_menu_is_wired_and_does_not_use_producer_authorizer():
    import inspect

    import meridian.menu_teacher_action_recovery as menu

    body = inspect.getsource(menu.run_teacher_action_recovery_menu)
    assert 'entry.kind == "attempt_policy"' in body
    handler = inspect.getsource(menu._offer_policy_resume)
    assert '"RESUME"' in handler
    assert "diagnostics.authorizer" not in handler
