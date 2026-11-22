"""#126-G1: installed Core capability discrimination and teacher-menu invariants."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian import menu_ui


def _precontract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(menu_ui, "find_spec", lambda name: None)


def _claimed(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capabilities: object = frozenset({"terminal.header.v1"}),
    version: str = "1",
    printer: object | None = None,
    failure: Exception | None = None,
) -> list[tuple[object, str]]:
    called: list[tuple[object, str]] = []
    contract = SimpleNamespace(
        TEACHER_EXPERIENCE_CONTRACT_VERSION=version,
        get_teacher_experience_capabilities=lambda: capabilities,
    )

    class Header:
        def __init__(self, *, application_name: str, screen_title: str):
            called.append((application_name, screen_title))
            self.application_name = application_name
            self.screen_title = screen_title

    def core_printer(header: Header, *, output: StringIO, color: str) -> None:
        called.append((header, color))
        output.write(f"{header.application_name}\n{header.screen_title}\n")

    ui = SimpleNamespace(
        TeacherScreenHeader=Header,
        print_teacher_header=core_printer if printer is None else printer,
    )

    def importer(name: str) -> object:
        if name == "pds_core.teacher_experience":
            if failure is not None:
                raise failure
            return contract
        if name == "pds_core.teacher_ui":
            return ui
        raise AssertionError("Private or unknown Core import")

    monkeypatch.setattr(menu_ui, "find_spec", lambda name: object())
    monkeypatch.setattr(menu_ui, "import_module", importer)
    return called


def test_installed_core_066_plain_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _precontract(monkeypatch)
    out = StringIO()
    menu_ui.print_menu_header(out, "Review Corrections & Attempts")
    assert out.getvalue() == "Meridian\nReview Corrections & Attempts\n\n"
    assert "\x1b" not in out.getvalue()


def test_no_title_keeps_legacy_plain_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _precontract(monkeypatch)
    out = StringIO()
    menu_ui.print_menu_header(out)
    assert out.getvalue() == "Meridian\n\n"


def test_core_v1_advertised_header_uses_public_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = _claimed(monkeypatch)
    out = StringIO()
    menu_ui.print_menu_header(out, "Review Student Attempts")
    assert out.getvalue() == "Meridian\nReview Student Attempts\n\n"
    assert called[0] == ("Meridian", "Review Student Attempts")
    assert called[1][1] == "auto"


def test_claimed_core_without_header_token_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = _claimed(
        monkeypatch, capabilities=frozenset({"terminal.notes_command.v1"})
    )
    out = StringIO()
    menu_ui.print_menu_header(out, "Review")
    assert called == []
    assert out.getvalue() == "Meridian\nReview\n\n"


@pytest.mark.parametrize(
    "capabilities", [set(), ["terminal.header.v1"], frozenset({1})]
)
def test_invalid_capability_declaration_is_not_silent_fallback(
    monkeypatch: pytest.MonkeyPatch, capabilities: object
) -> None:
    _claimed(monkeypatch, capabilities=capabilities)
    with pytest.raises(menu_ui.TeacherHeaderCompatibilityError):
        menu_ui.print_menu_header(StringIO(), "Review")


def test_core_contract_wrong_version_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claimed(monkeypatch, version="2")
    with pytest.raises(menu_ui.TeacherHeaderCompatibilityError):
        menu_ui.print_menu_header(StringIO(), "Review")


def test_broken_claimed_contract_import_is_not_missing_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claimed(
        monkeypatch,
        failure=ModuleNotFoundError("nested import", name="missing_nested"),
    )
    with pytest.raises(menu_ui.TeacherHeaderCompatibilityError):
        menu_ui.print_menu_header(StringIO(), "Review")


def test_broken_advertised_public_printer_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _claimed(monkeypatch, printer=object())
    with pytest.raises(menu_ui.TeacherHeaderCompatibilityError):
        menu_ui.print_menu_header(StringIO(), "Review")


@pytest.mark.parametrize(
    "value", ["Bad\x1b[31m", "Bad\nLine", "\u2028", " ", "Bad\u202eTitle"]
)
def test_unsafe_task_titles_never_reach_terminal(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _precontract(monkeypatch)
    out = StringIO()
    with pytest.raises(ValueError):
        menu_ui.print_menu_header(out, value)
    assert out.getvalue() == ""


@pytest.mark.parametrize("term", ["dumb", "xterm"])
def test_plain_fallback_has_no_color_even_with_terminal_environment(
    monkeypatch: pytest.MonkeyPatch, term: str
) -> None:
    _precontract(monkeypatch)
    monkeypatch.setenv("TERM", term)
    monkeypatch.setenv("NO_COLOR", "1")
    out = StringIO()
    menu_ui.print_menu_header(out, "Review Student Attempts")
    assert "\x1b" not in out.getvalue()


def test_navigation_core_labels_and_exception_unwind() -> None:
    out = StringIO()
    menu_ui.print_standard_navigation(out)
    assert out.getvalue() == "B. Back\nM. Main Menu\nQ. Quit\n"
    assert parse_navigation_choice(" b ") is NavigationChoice.BACK
    with pytest.raises(ReturnToMainMenu):
        parse_navigation_choice("m")
    with pytest.raises(QuitPDS):
        parse_navigation_choice("q")


def test_notes_stays_literal_in_data_confirmation_and_pause() -> None:
    seen: list[str] = []

    def input_fn(prompt: str) -> str:
        seen.append(prompt)
        return " :NoTeS "

    assert menu_ui.read_choice(input_fn, "Rationale: ") == ":NoTeS"
    assert menu_ui.read_choice(input_fn, "Confirmation: ") == ":NoTeS"
    menu_ui.pause_for_user(input_fn)
    assert seen == ["Rationale: ", "Confirmation: ", "Press Enter to continue..."]


def test_no_implicit_command_hook_during_import() -> None:
    assert not hasattr(menu_ui, "run_notes_menu")
    assert not hasattr(menu_ui, "launch_shared_command")
