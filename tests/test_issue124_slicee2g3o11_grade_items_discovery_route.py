"""#124 E2G3O11: Manage Grade Items routes to existing one-APPLY discovery.

These checks exercise teacher menu composition and delegated navigation only.
The canonical save/selection operation is already covered by E2G3O4-O10.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest

from meridian import menu as teacher_menu
from meridian.menu_grade_items import run_grade_items_menu
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_session import TeacherSessionContext


def _read_sequence(answers: tuple[str, ...]) -> Any:
    iterator = iter(answers)
    return lambda _prompt="": next(iterator)


def test_grade_items_offers_discovery_and_returns_without_losing_class() -> None:
    session = TeacherSessionContext(active_class_id="english12")
    navigation = TeacherNavigationContext(session=session)
    output = StringIO()
    called: list[TeacherSessionContext] = []

    def discover() -> None:
        called.append(navigation.session)

    run_grade_items_menu(
        navigation_context=navigation,
        discover_assessments=discover,
        input_fn=_read_sequence(("d", "b")),
        output=output,
        clear_fn=lambda: None,
    )
    assert called == [session]
    assert session.active_class_id == "english12"
    assert output.getvalue().count("Manage Grade Items") >= 2
    assert "D. Discover Registered Assessments / Set Up Grade Item" in output.getvalue()


def test_grade_items_d_is_not_offered_without_trusted_callback() -> None:
    session = TeacherSessionContext(active_class_id="english12")
    output = StringIO()
    run_grade_items_menu(
        navigation_context=TeacherNavigationContext(session=session),
        input_fn=_read_sequence(("d", "", "b")),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "D. Discover Registered Assessments / Set Up Grade Item" not in rendered
    assert "Please choose 1-9, B, M, or Q." in rendered


def test_legacy_grade_items_d_is_inert_even_if_callback_supplied() -> None:
    output = StringIO()
    called: list[str] = []
    run_grade_items_menu(
        discover_assessments=lambda: called.append("not allowed"),
        input_fn=_read_sequence(("d", "", "b")),
        output=output,
        clear_fn=lambda: None,
    )
    assert called == []
    assert "Please choose 1-6, B, M, or Q." in output.getvalue()


def test_default_teacher_menu_routes_main_and_grade_items_to_same_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = TeacherSessionContext(active_class_id="english12")
    captures: list[dict[str, Any]] = []
    grade_menu_calls: list[dict[str, Any]] = []

    def fake_discovery(**kwargs: Any) -> None:
        captures.append(kwargs)

    def fake_grade_items(**kwargs: Any) -> None:
        grade_menu_calls.append(kwargs)
        assert kwargs["navigation_context"].session is session
        callback = kwargs["discover_assessments"]
        assert callable(callback)
        callback()

    monkeypatch.setattr(
        teacher_menu, "run_teacher_assessment_discovery_menu", fake_discovery
    )
    monkeypatch.setattr(teacher_menu, "run_grade_items_menu", fake_grade_items)

    answers = _read_sequence(("b",))
    output = StringIO()
    deps = teacher_menu.default_teacher_menu_dependencies(
        session_context=session,
        input_fn=answers,
        output=output,
        clear_fn=lambda: None,
    )
    assert deps.discover_assessments is not None
    deps.manage_grade_items()
    deps.discover_assessments()
    assert len(grade_menu_calls) == 1
    assert len(captures) == 2
    first, second = captures
    assert first["session_context"] is session
    assert second["session_context"] is session
    assert (
        first["assessment_bridge_dependencies"]
        is second["assessment_bridge_dependencies"]
    )
    assert first["input_fn"] is second["input_fn"] is answers
    assert first["output"] is second["output"] is output
    assert first["clear_fn"] is second["clear_fn"]
