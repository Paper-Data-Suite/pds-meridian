"""#122 Slice 9: restart membership recovery revalidates source; no reauthoring."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

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
from meridian.teacher_action_restart_membership import (
    _RestartMembershipPort,
    inspect_restart_membership,
    resume_restart_membership,
)

A, B, C, G = "a" * 64, "b" * 64, "c" * 64, "d" * 64


def _receipt_preview(root: Path, source: str = "saved") -> TeacherActionPreview:
    actor = TeacherActionActor("teacher_1", A, source)
    identity = _identity("membership", "class_one", "grade_one", "scoreform", "work_1")
    return TeacherActionPreview(
        action_id="ef" * 16,
        kind="grade_item_membership",
        scope=TeacherActionScope(
            _identity("workspace", str(root)),
            "class_one",
            "grade_one",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=B,
            work_identity_sha256=_identity("work", "class_one", "scoreform", "work_1"),
        ),
        actor=actor,
        target=TeacherActionTarget("grade_item_membership", identity, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source", identity, _identity("membership_candidate", C)
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_membership as restart

    root = tmp_path
    (root / "classes" / "class_one").mkdir(parents=True)
    store = TeacherActionReceiptStore(root, "class_one")
    preview = _receipt_preview(root)
    receipt = store.prepare(preview)
    receipt = store.record_checkpoint(
        preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("write", "completed"),
    )
    work = SimpleNamespace(
        class_id="class_one", module_id="scoreform", work_id="work_1"
    )
    period = SimpleNamespace(school_year="2026-2027", period_id="mp1")
    candidate = SimpleNamespace(
        class_id="class_one",
        grade_item_id="grade_one",
        work_reference=SimpleNamespace(work=work, registration_revision=1),
        membership_revision=1,
        decision="included",
        actor_id="teacher_1",
        academic_period=SimpleNamespace(period=period, calendar_revision=1),
        grade_item_revision=1,
        grade_item_revision_sha256=G,
    )
    state = {
        "refs": (work,),
        "history": (1,),
        "candidate": candidate,
        "digest": C,
        "current": None,
        "grade_rev": 1,
        "grade_digest": G,
        "registration": 1,
        "calendar": B,
        "validated": 0,
        "selections": 0,
    }

    def stored():
        return SimpleNamespace(
            decision=state["candidate"], decision_sha256=state["digest"]
        )

    monkeypatch.setattr(
        restart, "list_grade_item_membership_work_refs", lambda *_a: state["refs"]
    )
    monkeypatch.setattr(
        restart, "list_grade_item_membership_revisions", lambda *_a: state["history"]
    )
    monkeypatch.setattr(
        restart, "load_grade_item_membership_revision", lambda *_a: stored()
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_membership_decision",
        lambda *_a: state["current"],
    )
    monkeypatch.setattr(
        restart,
        "load_current_grade_item_revision",
        lambda *_a: SimpleNamespace(
            revision=SimpleNamespace(grade_item_revision=state["grade_rev"]),
            revision_sha256=state["grade_digest"],
        ),
    )
    monkeypatch.setattr(
        restart,
        "get_current_academic_work_registration_revision",
        lambda *_a: state["registration"],
    )
    monkeypatch.setattr(restart, "_calendar_digest", lambda *_a: state["calendar"])
    monkeypatch.setattr(
        restart,
        "validate_grade_item_membership_dependencies",
        lambda *_a: state.__setitem__("validated", state["validated"] + 1),
    )

    def select_preview(*_a):
        return SimpleNamespace(
            target=stored(),
            expected_current_membership_revision=(
                None
                if state["current"] is None
                else state["current"].decision.membership_revision
            ),
            history=state["history"],
        )

    def commit(_root: Path, _selection: object):
        state["selections"] += 1
        state["current"] = stored()
        return SimpleNamespace(
            selection_result=SimpleNamespace(stored=stored()),
            selection_disposition="created",
        )

    monkeypatch.setattr(
        restart, "preview_grade_item_membership_selection", select_preview
    )
    monkeypatch.setattr(
        restart, "commit_grade_item_membership_selection_preview", commit
    )
    return root, store, receipt, state


def _accept(_actor: TeacherActionActor) -> None:
    return None


def test_restart_inspection_does_not_change_membership(example) -> None:
    root, store, receipt, state = example
    result = inspect_restart_membership(root, store, receipt, actor_checker=_accept)
    assert result.can_resume and result.status == "written_not_current"
    assert state["selections"] == 0
    assert state["validated"] >= 1


def test_restart_exact_selection_never_writes_revision(example) -> None:
    root, store, receipt, state = example
    result = resume_restart_membership(
        root, store, receipt, confirmation="RESUME", actor_checker=_accept
    )
    assert result.succeeded
    assert state["selections"] == 1
    assert state["history"] == (1,)


def test_cancellation_has_zero_mutations(example) -> None:
    root, store, receipt, state = example
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_membership(
            root, store, receipt, confirmation="CANCEL", actor_checker=_accept
        )
    assert state["selections"] == 0


def test_recovery_port_has_no_immutable_writer(example) -> None:
    root, _, receipt, _ = example
    port = _RestartMembershipPort(root, receipt, _accept)
    with pytest.raises(TeacherActionConflictError, match="cannot author"):
        port.persist_exact(receipt.preview)


@pytest.mark.parametrize(
    "change",
    [
        "registration",
        "calendar",
        "grade_rev",
        "grade_digest",
        "history",
        "digest",
        "refs",
    ],
)
def test_changed_dependencies_fail_closed(example, change: str) -> None:
    root, store, receipt, state = example
    state[change] = {
        "registration": 2,
        "calendar": A,
        "grade_rev": 2,
        "grade_digest": A,
        "history": (1, 2),
        "digest": A,
        "refs": (),
    }[change]
    with pytest.raises(TeacherActionConflictError):
        inspect_restart_membership(root, store, receipt, actor_checker=_accept)
    assert state["selections"] == 0


def test_changed_profile_fails_closed(example) -> None:
    root, store, receipt, state = example

    def changed(_actor: TeacherActionActor) -> None:
        raise TeacherActionConflictError("profile changed")

    with pytest.raises(TeacherActionConflictError, match="profile changed"):
        inspect_restart_membership(root, store, receipt, actor_checker=changed)
    assert state["selections"] == 0


def test_temporary_attribution_refused(example) -> None:
    root, _, receipt, _ = example
    changed = replace(
        receipt.preview, actor=replace(receipt.preview.actor, source="temporary")
    )
    with pytest.raises(TeacherActionConflictError, match="Temporary"):
        _RestartMembershipPort(root, replace(receipt, preview=changed), _accept)


def test_different_workspace_receipt_refused(example) -> None:
    root, _, receipt, _ = example
    changed = replace(
        receipt.preview,
        scope=replace(receipt.preview.scope, workspace_sha256=A),
    )
    with pytest.raises(TeacherActionConflictError, match="Workspace changed"):
        _RestartMembershipPort(root, replace(receipt, preview=changed), _accept)


def test_changed_receipt_generation_fails_closed(example) -> None:
    root, store, receipt, state = example
    store.record_checkpoint(
        receipt.preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
    )
    with pytest.raises(TeacherActionConflictError, match="Journal changed"):
        inspect_restart_membership(root, store, receipt, actor_checker=_accept)
    assert state["selections"] == 0


def test_wrong_actor_in_persisted_membership_fails(example) -> None:
    root, store, receipt, state = example
    state["candidate"].actor_id = "other_teacher"
    with pytest.raises(
        TeacherActionConflictError, match="Canonical relationship differs"
    ):
        inspect_restart_membership(root, store, receipt, actor_checker=_accept)
    assert state["selections"] == 0


def test_bounded_relationship_lookup(example) -> None:
    root, store, receipt, state = example
    state["refs"] = state["refs"] * 2049
    with pytest.raises(TeacherActionConflictError, match="safe bounds"):
        inspect_restart_membership(root, store, receipt, actor_checker=_accept)
    assert state["selections"] == 0


def test_recovery_menu_exact_resume_requires_one_explicit_confirmation(
    example, monkeypatch
) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, state = example
    calls: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_membership",
        lambda *_args: SimpleNamespace(can_resume=True),
    )

    def resume(*_args: object, confirmation: str):
        calls.append(confirmation)
        return SimpleNamespace(status="applied")

    monkeypatch.setattr(menu, "resume_restart_membership", resume)
    monkeypatch.setattr(
        menu, "teacher_action_outcome_message", lambda _outcome: "Verified current"
    )
    stream = StringIO()
    menu._offer_membership_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        input_fn=lambda _prompt: "RESUME",
        output=stream,
    )
    assert calls == ["RESUME"]
    assert "Verified current" in stream.getvalue()
    assert state["selections"] == 0  # Menu is routed through the provided seam.


def test_recovery_menu_cancellation_and_unavailable_action_never_select(
    example, monkeypatch
) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, _ = example
    calls: list[str] = []
    monkeypatch.setattr(
        menu,
        "resume_restart_membership",
        lambda *_a, **_k: calls.append("resumed"),
    )
    monkeypatch.setattr(
        menu,
        "inspect_restart_membership",
        lambda *_a: SimpleNamespace(can_resume=True),
    )
    menu._offer_membership_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        input_fn=lambda _prompt: "NO",
        output=StringIO(),
    )
    monkeypatch.setattr(
        menu,
        "inspect_restart_membership",
        lambda *_a: SimpleNamespace(can_resume=False),
    )
    menu._offer_membership_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        input_fn=lambda _prompt: (_ for _ in ()).throw(AssertionError("no prompt")),
        output=StringIO(),
    )
    assert not calls


def test_modified_reviewed_digest_is_not_a_recovery_authority(example) -> None:
    root, _, receipt, state = example
    changed = replace(
        receipt.preview,
        reviewed_decision_sha256=A,
    )
    with pytest.raises(TeacherActionConflictError, match="Reviewed membership digest"):
        _RestartMembershipPort(root, replace(receipt, preview=changed), _accept)
    assert state["selections"] == 0
