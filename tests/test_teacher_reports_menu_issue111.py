from __future__ import annotations

from io import StringIO

from meridian.menu_reports import REPORT_MENU_TITLES, run_reports_menu


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def test_reports_menu_shell_names_all_eight_report_families() -> None:
    output = StringIO()

    run_reports_menu(
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert len(REPORT_MENU_TITLES) == 8
    for index, title in enumerate(REPORT_MENU_TITLES, start=1):
        assert f"{index}. {title}" in rendered
    assert "Reports 1-6 are available now." in rendered


def test_unimplemented_report_choice_is_explicit_not_silent() -> None:
    output = StringIO()

    run_reports_menu(
        input_fn=ScriptedInput("7", "", "b"),
        output=output,
        clear_fn=lambda: None,
    )

    assert "That report generator is not implemented yet." in output.getvalue()
