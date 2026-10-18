"""Slice 4 focused tests for guarded guided actions; synthetic state only."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from meridian.teacher_action_contract import (
    TeacherActionActor,
    TeacherActionRecord,
    TeacherActionResult,
)
from meridian.teacher_action_guided import (
    _GuidedPort,
    _prepare,
)
from meridian.teacher_action_orchestration import TeacherActionConflictError

A = "a" * 64
B = "b" * 64
C = "c" * 64


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "classes" / "synthetic_class").mkdir(parents=True)
    return tmp_path


def _action(root: Path, *, fail: str = "") -> tuple[object, list[str]]:
    events: list[str] = []
    state: dict[str, object] = {"written": False, "current": None}

    def revalidate() -> None:
        events.append("check")
        if fail == "preflight":
            raise TeacherActionConflictError("Academic scope changed")

    def read() -> tuple[str | None, int | None, str | None, str]:
        events.append("read")
        return (
            B if state["written"] else None,
            1 if state["current"] else None,
            B if state["current"] else None,
            "current",
        )

    def write() -> str:
        events.append("write")
        state["written"] = True
        if fail == "after_write":
            raise OSError("synthetic interrupted write")
        return "created"

    def select() -> str:
        events.append("select")
        if fail == "before_select":
            raise OSError("synthetic blocked CAS")
        state["current"] = True
        return "created"

    port = _GuidedPort(
        kind="grade_item",
        revalidate=revalidate,
        read=cast(object, read),  # type: ignore[arg-type]
        write=cast(object, write),  # type: ignore[arg-type]
        select=cast(object, select),  # type: ignore[arg-type]
    )
    return (
        _prepare(
            root=root,
            class_id="synthetic_class",
            grade_item_id="item",
            actor=TeacherActionActor("teacher_synthetic", A, "saved"),
            kind="grade_item",
            revision=1,
            candidate_sha256=B,
            current_revision=None,
            current_sha256=None,
            identity=C,
            source_binding=A,
            port=port,
        ),
        events,
    )


def test_single_confirmation_saves_and_selects(workspace: Path) -> None:
    action, events = _action(workspace)
    result = action.apply(confirmed=True)  # type: ignore[attr-defined]
    assert result.status == "applied"
    assert events.count("write") == 1
    assert events.count("select") == 1
    assert events.index("write") < events.index("select")


def test_cancel_before_any_receipt_or_write(workspace: Path) -> None:
    action, events = _action(workspace)
    result = action.apply(confirmed=False)  # type: ignore[attr-defined]
    assert result.status == "blocked_before_write"
    assert events == []
    assert not (
        workspace
        / "classes"
        / "synthetic_class"
        / "modules"
        / "meridian"
        / "teacher_action_receipts"
    ).exists()


def test_interruption_does_not_duplicate_decision(workspace: Path) -> None:
    action, events = _action(workspace, fail="after_write")
    first = action.apply(confirmed=True)  # type: ignore[attr-defined]
    assert first.status in ("written_not_current", "recovery_required")
    second = action.apply(confirmed=True)  # type: ignore[attr-defined]
    assert not second.succeeded
    assert events.count("write") == 1


def test_selector_failure_keeps_written_not_current(workspace: Path) -> None:
    action, events = _action(workspace, fail="before_select")
    result = action.apply(confirmed=True)  # type: ignore[attr-defined]
    assert result.status == "written_not_current"
    assert events.count("write") == 1
    assert events.count("select") == 1


def test_stale_preflight_never_writes(workspace: Path) -> None:
    action, events = _action(workspace, fail="preflight")
    result = action.apply(confirmed=True)  # type: ignore[attr-defined]
    assert result.status == "conflict_requires_review"
    assert "write" not in events


def test_port_rejects_different_record_without_select(workspace: Path) -> None:
    action, events = _action(workspace)
    wrong = TeacherActionRecord("grade_item", C, 2, B, "created")
    with pytest.raises(TeacherActionConflictError):
        action.port.select_exact(  # type: ignore[attr-defined]
            action.preview,
            wrong,  # type: ignore[attr-defined]
        )
    assert "select" not in events


def test_teacher_menu_uses_one_review_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meridian.menu_teacher_grade_items import _review_apply

    responses = iter(("1",))
    writes: list[bool] = []
    result = cast(
        TeacherActionResult,
        SimpleNamespace(succeeded=True, status="applied"),
    )
    action = SimpleNamespace(
        apply=lambda *, confirmed: writes.append(confirmed) or result
    )
    monkeypatch.setattr(
        "meridian.menu_teacher_grade_items.teacher_action_outcome_message",
        lambda _value: "Saved and made current",
    )
    output = StringIO()
    assert _review_apply(
        cast(object, action),  # type: ignore[arg-type]
        input_fn=lambda _prompt: next(responses),
        output=output,
        clear_fn=lambda: None,
    )
    assert writes == [True]
    assert "Saved and made current" in output.getvalue()


def test_partial_save_offers_explicit_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from meridian.menu_teacher_grade_items import _review_apply

    responses = iter(("1", "1"))
    first = SimpleNamespace(succeeded=False, status="written_not_current")
    last = SimpleNamespace(succeeded=True, status="applied")
    log: list[str] = []
    action = SimpleNamespace(
        apply=lambda *, confirmed: log.append("apply") or first,
        resume=lambda *, confirmed: log.append("resume") or last,
    )
    monkeypatch.setattr(
        "meridian.menu_teacher_grade_items.teacher_action_outcome_message",
        lambda _value: "Recovery status",
    )
    assert _review_apply(
        cast(object, action),  # type: ignore[arg-type]
        input_fn=lambda _prompt: next(responses),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["apply", "resume"]
