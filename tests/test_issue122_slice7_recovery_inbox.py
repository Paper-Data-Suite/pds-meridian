"""#122 Slice 7: restart-safe, privacy-minimal read-only recovery inbox."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from meridian.menu_teacher_action_recovery import (
    run_teacher_action_recovery_menu,
)
from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_receipts import (
    TeacherActionReceiptStore,
    TeacherActionReceiptUnsafeError,
)
from meridian.teacher_action_recovery_inventory import read_recovery_inbox
from meridian.teacher_session import TeacherSessionContext

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64


class Inputs:
    def __init__(self, *answers: str) -> None:
        self._values = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._values)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for class_id in ("class_one", "class_two"):
        (tmp_path / "classes" / class_id).mkdir(parents=True)
    return tmp_path


def _workspace_sha(root: Path) -> str:
    return hashlib.sha256(
        "\x1f".join(("workspace", str(root))).encode("utf-8")
    ).hexdigest()


def _preview(root: Path, suffix: str = "01") -> TeacherActionPreview:
    return TeacherActionPreview(
        action_id=(suffix * 16),
        kind="eligibility",
        scope=TeacherActionScope(
            workspace_sha256=_workspace_sha(root),
            class_id="class_one",
            grade_item_id="grade_one",
            school_year="2026-2027",
            academic_period_id="mp1",
            calendar_sha256=A,
            work_identity_sha256=B,
        ),
        actor=TeacherActionActor("teacher-fixture", A, "saved"),
        target=TeacherActionTarget(
            "eligibility",
            B,
            2,
            C,
            1,
            D,
        ),
        basis=(TeacherActionBasis("authorization", A, B),),
        reviewed_decision_sha256=C,
    )


def _store(root: Path, class_id: str = "class_one") -> TeacherActionReceiptStore:
    return TeacherActionReceiptStore(root, class_id)


def test_empty_scan_is_read_only(root: Path) -> None:
    store = _store(root)
    assert store.list_receipts() == ()
    assert read_recovery_inbox(store).entries == ()
    assert not store.directory.exists()


def test_prepared_receipt_discovered_after_restart(root: Path) -> None:
    _store(root).prepare(_preview(root))
    reopened = _store(root)
    inbox = read_recovery_inbox(reopened)
    assert len(inbox.entries) == inbox.review_count == 1
    assert inbox.entries[0].stage == "receipt_prepared"
    assert inbox.entries[0].needs_review
    assert inbox.entries[0].scope_matches_workspace
    assert inbox.entries[0].title == "Evidence eligibility"


def test_finalized_receipt_is_not_called_canonical_success(root: Path) -> None:
    store = _store(root)
    preview = _preview(root)
    store.prepare(preview)
    store.record_checkpoint(
        preview,
        expected_generation=1,
        checkpoint=TeacherActionCheckpoint("receipt_finalized", "completed"),
    )
    inbox = read_recovery_inbox(_store(root))
    assert inbox.review_count == 0
    assert inbox.completed_receipt_count == 1
    assert "not rechecked" in inbox.entries[0].description


def test_other_workspace_scope_needs_review(root: Path) -> None:
    store = _store(root)
    preview = _preview(root)
    foreign = replace(
        preview,
        scope=replace(preview.scope, workspace_sha256=A),
    )
    store.prepare(foreign)
    store.record_checkpoint(
        foreign,
        expected_generation=1,
        checkpoint=TeacherActionCheckpoint("receipt_finalized", "completed"),
    )
    inbox = read_recovery_inbox(store)
    assert inbox.review_count == 1
    assert inbox.entries[0].scope_matches_workspace is False


def test_class_scoping_and_multiple_sorted_items(root: Path) -> None:
    store = _store(root)
    store.prepare(_preview(root, "01"))
    store.prepare(_preview(root, "02"))
    assert len(read_recovery_inbox(_store(root)).entries) == 2
    assert read_recovery_inbox(_store(root, "class_two")).entries == ()


def test_corrupt_receipt_stops_whole_inbox(root: Path) -> None:
    store = _store(root)
    valid = _preview(root, "01")
    store.prepare(valid)
    store.path_for(valid.action_id).write_bytes(b"{not json")
    with pytest.raises(TeacherActionReceiptUnsafeError):
        read_recovery_inbox(store)


def test_unexpected_entry_refuses_partial_listing(root: Path) -> None:
    store = _store(root)
    store.prepare(_preview(root))
    (store.directory / "foreign.tmp").write_text("", encoding="utf-8")
    with pytest.raises(TeacherActionReceiptUnsafeError, match="unrecognized"):
        store.list_receipts()


def test_oversized_receipt_is_rejected(root: Path) -> None:
    store = _store(root)
    preview = _preview(root)
    store.prepare(preview)
    store.path_for(preview.action_id).write_bytes(b"x" * (32768 + 1))
    with pytest.raises(TeacherActionReceiptUnsafeError):
        store.list_receipts()


def test_symlinked_journal_entry_is_rejected(root: Path) -> None:
    store = _store(root)
    store.prepare(_preview(root))
    original = store.path_for(_preview(root).action_id)
    linked = store.directory / ("ff" * 16 + ".json")
    try:
        linked.symlink_to(original)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(TeacherActionReceiptUnsafeError):
        store.list_receipts()


def test_inbox_menu_is_read_only_and_opaque(root: Path) -> None:
    store = _store(root)
    preview = _preview(root)
    store.prepare(preview)
    state = store.path_for(preview.action_id).read_bytes()
    scripted = Inputs("1", "", "B")
    output = StringIO()
    run_teacher_action_recovery_menu(
        session_context=TeacherSessionContext(active_class_id="class_one"),
        workspace_resolver=lambda: root,
        class_validator=lambda _root, _class_id: None,
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Checkpoints needing review: 1" in rendered
    assert "No canonical academic state has been independently verified" in rendered
    assert preview.action_id not in rendered
    assert preview.actor.actor_id not in rendered
    assert preview.scope.grade_item_id not in rendered
    assert store.path_for(preview.action_id).read_bytes() == state
    assert sorted(p.name for p in store.directory.iterdir()) == [
        ".journal.lock",
        f"{preview.action_id}.json",
    ]


def test_inbox_missing_active_class_can_cancel_without_touching_disk(
    root: Path,
) -> None:
    output = StringIO()
    run_teacher_action_recovery_menu(
        session_context=TeacherSessionContext(),
        workspace_resolver=lambda: root,
        input_fn=Inputs(""),
        output=output,
        clear_fn=lambda: None,
    )
    assert "Class ID" not in output.getvalue()
    assert not _store(root).directory.exists()


def test_inbox_class_validation_blocks_without_guessing(root: Path) -> None:
    output = StringIO()
    run_teacher_action_recovery_menu(
        session_context=TeacherSessionContext(active_class_id="class_one"),
        workspace_resolver=lambda: root,
        class_validator=lambda _root, _class_id: (_ for _ in ()).throw(
            ValueError("not registered")
        ),
        input_fn=Inputs(""),
        output=output,
        clear_fn=lambda: None,
    )
    assert "could not be reviewed completely or safely" in output.getvalue()


def test_read_only_store_does_not_initialize_lock(root: Path) -> None:
    store = _store(root)
    before = sorted(str(p) for p in root.rglob("*"))
    assert read_recovery_inbox(store).entries == ()
    assert sorted(str(p) for p in root.rglob("*")) == before


def test_read_only_inventory_does_not_make_permission_claims(root: Path) -> None:
    store = _store(root)
    store.prepare(_preview(root))
    inbox = read_recovery_inbox(store)
    assert all(entry.needs_review for entry in inbox.entries)
    assert all(not item.description.startswith("Saved and") for item in inbox.entries)


def test_main_menu_uses_optional_r_without_renumbering_tasks() -> None:
    from meridian.menu import _render_main_menu

    output = StringIO()
    _render_main_menu(output, recovery_available=True)
    rendered = output.getvalue()
    assert "R. Review Interrupted Saves" in rendered
    assert "1. Review New Evidence" in rendered
    assert "9. Reports" in rendered
    unavailable = StringIO()
    _render_main_menu(unavailable, recovery_available=False)
    assert "R. Review Interrupted Saves" not in unavailable.getvalue()


def test_main_menu_r_routes_to_injected_read_only_handler() -> None:
    from meridian.menu import TeacherMenuDependencies, run_menu

    called: list[str] = []
    handlers = [lambda: None for _ in range(9)]
    dependencies = TeacherMenuDependencies(
        *handlers, review_save_recovery=lambda: called.append("read-only")
    )
    choices = iter(("r",))

    def input_once_then_quit(_prompt: str) -> str:
        try:
            return next(choices)
        except StopIteration:
            raise EOFError from None

    output = StringIO()
    result = run_menu(
        dependencies=dependencies,
        input_fn=input_once_then_quit,
        output=output,
        clear_fn=lambda: None,
    )
    assert result == 0
    assert called == ["read-only"]
