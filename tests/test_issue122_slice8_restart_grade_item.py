"""#122 Slice 8: no immutable reauthoring after restart (synthetic only)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import (
    TeacherActionReceiptStore,
)
from meridian.teacher_action_restart_grade_item import (
    _RestartGradeItemPort,
    inspect_restart_grade_item,
    resume_restart_grade_item,
)

A = "a" * 64
C = "c" * 64


def _preview(root: Path, source: str = "saved") -> TeacherActionPreview:
    actor = TeacherActionActor("test_teacher", A, source)
    identity = _identity("grade_item", "class_one", "grade_one")
    return TeacherActionPreview(
        action_id="ab" * 16,
        kind="grade_item",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(root)),
            class_id="class_one",
            grade_item_id="grade_one",
        ),
        actor=actor,
        target=TeacherActionTarget("grade_item", identity, 1, C, None, None),
        basis=(
            TeacherActionBasis("actor_profile", _identity(actor.actor_id), A),
            TeacherActionBasis(
                "canonical_source", identity, _identity("grade_item_candidate", C)
            ),
        ),
        reviewed_decision_sha256=C,
    )


@pytest.fixture
def example(tmp_path: Path, monkeypatch):
    import meridian.teacher_action_restart_grade_item as restart

    root = tmp_path
    (root / "classes" / "class_one").mkdir(parents=True)
    store = TeacherActionReceiptStore(root, "class_one")
    preview = _preview(root)
    receipt = store.prepare(preview)
    receipt = store.record_checkpoint(
        preview,
        expected_generation=receipt.generation,
        checkpoint=__import__(
            "meridian.teacher_action_contract", fromlist=["TeacherActionCheckpoint"]
        ).TeacherActionCheckpoint("write", "completed"),
    )
    state = {"history": (1,), "current": None, "digest": C, "commits": 0}
    stored = SimpleNamespace(
        revision=SimpleNamespace(
            class_id="class_one",
            grade_item_id="grade_one",
            grade_item_revision=1,
            title="Essay comparison",
        ),
        revision_sha256=C,
    )
    monkeypatch.setattr(
        restart,
        "load_class_metadata",
        lambda *_args: SimpleNamespace(class_id="class_one"),
    )
    monkeypatch.setattr(
        restart, "list_grade_item_revisions", lambda *_args: state["history"]
    )
    monkeypatch.setattr(
        restart,
        "load_grade_item_revision",
        lambda *_args: SimpleNamespace(
            revision=stored.revision,
            revision_sha256=state["digest"],
        ),
    )
    monkeypatch.setattr(
        restart, "load_current_grade_item_revision", lambda *_args: state["current"]
    )

    def preview_selector(*_args: object):
        return SimpleNamespace(
            target=stored,
            expected_current_revision=(
                None
                if state["current"] is None
                else state["current"].revision.grade_item_revision
            ),
            history=state["history"],
        )

    def select_selector(_root: Path, selection: object):
        if getattr(selection, "expected_current_revision") is not None:
            raise TeacherActionConflictError("CAS baseline changed.")
        state["current"] = stored
        state["commits"] += 1
        return SimpleNamespace(
            selection_result=SimpleNamespace(stored=stored),
            selection_disposition="created",
        )

    monkeypatch.setattr(restart, "preview_grade_item_selection", preview_selector)
    monkeypatch.setattr(restart, "commit_grade_item_selection_preview", select_selector)
    return root, store, receipt, state


def _check(_actor: TeacherActionActor) -> None:
    return None


def test_post_restart_grade_item_identified_without_mutation(example) -> None:
    root, store, receipt, state = example
    result = inspect_restart_grade_item(root, store, receipt, actor_checker=_check)
    assert result.can_resume
    assert result.status == "written_not_current"
    assert result.title == "Essay comparison"
    assert state["commits"] == 0


def test_exact_resume_selects_without_authoring(example) -> None:
    root, store, receipt, state = example
    result = resume_restart_grade_item(
        root, store, receipt, confirmation="RESUME", actor_checker=_check
    )
    assert result.succeeded
    assert state["commits"] == 1
    assert (
        inspect_restart_grade_item(
            root, store, store.load(receipt.action_id), actor_checker=_check
        ).status
        == "already_applied"
    )


def test_cancellation_does_not_select(example) -> None:
    root, store, receipt, state = example
    with pytest.raises(TeacherActionConflictError, match="not confirmed"):
        resume_restart_grade_item(
            root, store, receipt, confirmation="cancel", actor_checker=_check
        )
    assert state["commits"] == 0


def test_missing_immutable_revision_blocks(example) -> None:
    root, store, receipt, state = example
    state["history"] = ()
    result = inspect_restart_grade_item(root, store, receipt, actor_checker=_check)
    assert not result.can_resume
    assert state["commits"] == 0


def test_candidate_digest_changed_blocks(example) -> None:
    root, store, receipt, state = example
    state["digest"] = A
    result = inspect_restart_grade_item(root, store, receipt, actor_checker=_check)
    assert not result.can_resume


def test_later_revision_blocks(example) -> None:
    root, store, receipt, state = example
    state["history"] = (1, 2)
    with pytest.raises(TeacherActionConflictError, match="history changed"):
        inspect_restart_grade_item(root, store, receipt, actor_checker=_check)


def test_existing_different_current_blocks(example) -> None:
    root, store, receipt, state = example
    state["current"] = SimpleNamespace(
        revision=SimpleNamespace(grade_item_revision=2), revision_sha256=A
    )
    result = inspect_restart_grade_item(root, store, receipt, actor_checker=_check)
    assert not result.can_resume


def test_profile_change_blocks(example) -> None:
    root, store, receipt, state = example

    def changed(_actor: TeacherActionActor) -> None:
        raise TeacherActionConflictError("Teacher changed")

    with pytest.raises(TeacherActionConflictError, match="Teacher changed"):
        inspect_restart_grade_item(root, store, receipt, actor_checker=changed)
    assert state["commits"] == 0


def test_temporary_actor_cannot_rehydrate(example) -> None:
    root, store, receipt, state = example
    temporary = replace(
        receipt.preview,
        actor=replace(receipt.preview.actor, source="temporary"),
    )
    with pytest.raises(TeacherActionConflictError, match="temporary attribution"):
        _RestartGradeItemPort(root, replace(receipt, preview=temporary), _check)
    assert state["commits"] == 0


def test_wrong_family_identity_refuses(example) -> None:
    root, store, receipt, state = example
    invalid = replace(
        receipt.preview,
        target=replace(receipt.preview.target, identity_sha256=A),
    )
    with pytest.raises(TeacherActionConflictError, match="fingerprint"):
        _RestartGradeItemPort(root, replace(receipt, preview=invalid), _check)
    assert state["commits"] == 0


def test_recovery_port_never_has_a_writer(example) -> None:
    root, _, receipt, _ = example
    port = _RestartGradeItemPort(root, receipt, _check)
    with pytest.raises(TeacherActionConflictError, match="cannot author"):
        port.persist_exact(receipt.preview)


def test_stale_inbox_receipt_refuses_replay(example) -> None:
    root, store, receipt, state = example
    from meridian.teacher_action_contract import TeacherActionCheckpoint

    store.record_checkpoint(
        receipt.preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint("selection_preview", "completed"),
    )
    with pytest.raises(TeacherActionConflictError, match="Journal changed"):
        inspect_restart_grade_item(root, store, receipt, actor_checker=_check)
    assert state["commits"] == 0


def test_inbox_explicit_confirmation_required(example, monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, state = example
    calls: list[str] = []
    monkeypatch.setattr(
        menu,
        "inspect_restart_grade_item",
        lambda *_args: SimpleNamespace(can_resume=True, title="Essay comparison"),
    )
    monkeypatch.setattr(
        menu,
        "resume_restart_grade_item",
        lambda *_args, **_kwargs: calls.append("selected"),
    )
    stream = StringIO()
    menu._offer_grade_item_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        input_fn=lambda _prompt: "1",
        output=stream,
    )
    assert not calls
    assert "Type RESUME" in stream.getvalue()
    assert state["commits"] == 0


def test_inbox_withheld_option_on_stale_authority(example, monkeypatch) -> None:
    from io import StringIO

    import meridian.menu_teacher_action_recovery as menu

    root, store, receipt, state = example
    monkeypatch.setattr(
        menu,
        "inspect_restart_grade_item",
        lambda *_args: SimpleNamespace(can_resume=False, title=None),
    )
    stream = StringIO()
    menu._offer_grade_item_resume(
        root,
        store,
        SimpleNamespace(receipt=receipt),
        input_fn=lambda _prompt: pytest.fail("No recovery choice is permitted"),
        output=stream,
    )
    assert "not authorized" in stream.getvalue()
    assert state["commits"] == 0
