"""#126 G2: real Meridian menu routing against installed Core B/M/Q semantics.

All student data come from the accepted synthetic 29-student F1 fixture.
Handlers are inert observation seams; these tests never write academic state.
"""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue126_slicef1_assessment_corrections_queue import _setup

from meridian import menu_ui


@pytest.mark.parametrize(
    "choice,handler_name",
    [
        ("c", "correction_handler"),
        ("s", "reassessment_handler"),
        ("d", "decision_history_handler"),
        ("i", "recovery_handler"),
        ("v", "standards_handler"),
        ("x", "reassessment_recovery_handler"),
        ("z", "pair_restart_handler"),
    ],
)
def test_student_shortcuts_dispatch_only_one_owner_and_refresh(
    tmp_path: Path, choice: str, handler_name: str
) -> None:
    fixture = _setup(tmp_path, "1", choice, "b")
    invocations: list[tuple[object, ...]] = []

    def chosen(*args: object) -> bool:
        invocations.append(args)
        return True

    ports = replace(fixture.services, **{handler_name: chosen})
    fixture.run(ports=ports)
    assert len(invocations) == 1
    assert invocations[0][0] == tmp_path
    assert invocations[0][2] is fixture.inventory
    assert fixture.session.active_student_id == "synthetic_student_01"
    assert fixture.calls == ["read", "read"]
    assert "Review Student Attempts" in fixture.output.getvalue()


def test_uppercase_shortcut_preserves_local_semantics(tmp_path: Path) -> None:
    fixture = _setup(tmp_path, "1", "Z", "b")
    calls: list[object] = []

    def restart(*args: object) -> bool:
        calls.append(args)
        return True

    fixture.run(ports=replace(fixture.services, pair_restart_handler=restart))
    assert len(calls) == 1
    assert fixture.calls == ["read", "read"]


def test_class_recovery_is_accessible_without_student_selection(
    tmp_path: Path,
) -> None:
    fixture = _setup(tmp_path, "i", "b")
    calls: list[tuple[object, ...]] = []

    def recovery(*args: object) -> None:
        calls.append(args)

    fixture.run(ports=replace(fixture.services, recovery_handler=recovery))
    assert len(calls) == 1
    assert calls[0][2] is fixture.inventory
    assert fixture.session.active_student_id is None
    assert fixture.calls == ["read", "read"]


def test_history_and_technical_details_remain_local_read_only(
    tmp_path: Path,
) -> None:
    fixture = _setup(tmp_path, "1", "h", "", "t", "", "b", "b")
    fixture.run()
    text = fixture.output.getvalue()
    assert "Source Attempt History (READ ONLY)" in text
    assert "Technical Details (READ ONLY)" in text
    assert "not proof of correction cause" in text
    assert fixture.calls == ["read"]


@pytest.mark.parametrize(
    "entry,command,exception",
    [
        ((), "m", ReturnToMainMenu),
        ((), "q", QuitPDS),
        (("1",), "m", ReturnToMainMenu),
        (("1",), "q", QuitPDS),
    ],
)
def test_core_main_quit_exceptions_unwind_from_real_menu(
    tmp_path: Path,
    entry: tuple[str, ...],
    command: str,
    exception: type[Exception],
) -> None:
    fixture = _setup(tmp_path, *entry, command)
    with pytest.raises(exception):
        fixture.run()
    assert fixture.calls == ["read"]


def test_back_from_detail_returns_without_action(tmp_path: Path) -> None:
    fixture = _setup(tmp_path, "1", "b", "b")
    fixture.run()
    assert fixture.calls == ["read"]
    assert fixture.input.prompts == ["Choice: ", "Choice: ", "Choice: "]


def test_notes_token_at_queue_cannot_dispatch_shared_notes(tmp_path: Path) -> None:
    fixture = _setup(tmp_path, ":notes", "", "b")
    fixture.run()
    assert "Choose a listed student" in fixture.output.getvalue()
    assert fixture.calls == ["read"]


def test_notes_token_in_student_menu_is_invalid_not_action(tmp_path: Path) -> None:
    fixture = _setup(tmp_path, "1", ":notes", "", "b", "b")
    fixture.run()
    assert "Choose C, S, D, I, V, X, Z" in fixture.output.getvalue()
    assert fixture.calls == ["read"]


@pytest.mark.parametrize(
    "prompt",
    [
        "Teacher explanation (required; Enter cancels): ",
        "Confirmation: ",
        "Search: ",
    ],
)
def test_shared_notes_is_literal_data_and_confirmation(prompt: str) -> None:
    seen: list[str] = []

    def entry(value: str) -> str:
        seen.append(value)
        return " :NoTeS "

    assert menu_ui.read_choice(entry, prompt) == ":NoTeS"
    assert seen == [prompt]


def test_pause_has_no_command_interception() -> None:
    seen: list[str] = []

    def entry(prompt: str) -> str:
        seen.append(prompt)
        return ":notes"

    menu_ui.pause_for_user(entry)
    assert seen == ["Press Enter to continue..."]


def test_session_publication_drift_blocks_post_action_reload(tmp_path: Path) -> None:
    fixture = _setup(tmp_path, "1", "d", "")
    actions: list[str] = []

    def view(*args: object) -> None:
        actions.append("history")
        fixture.session.select_publication("different_publication")

    fixture.run(ports=replace(fixture.services, decision_history_handler=view))
    assert actions == ["history"]
    assert fixture.calls == ["read"]
    assert "Refresh Required" in fixture.output.getvalue()


def test_installed_menu_headers_are_legible_under_no_color(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    fixture = _setup(tmp_path, "1", "b", "b")
    fixture.run()
    output = fixture.output.getvalue()
    assert "Meridian\nReview Corrections & Attempts\n" in output
    assert "Meridian\nReview Student Attempts\n" in output
    assert "\x1b" not in output
    assert "B. Back\nM. Main Menu\nQ. Quit" in output


def test_core_navigation_is_rendered_to_requested_stream_only() -> None:
    out = StringIO()
    menu_ui.print_standard_navigation(out, back=False)
    assert out.getvalue() == "M. Main Menu\nQ. Quit\n"
    assert not hasattr(menu_ui, "run_notes_menu")
