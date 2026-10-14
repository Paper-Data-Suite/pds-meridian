from __future__ import annotations

from io import StringIO

from meridian.menu_reports import REPORT_MENU_TITLES, run_reports_menu
from meridian.report_guided_selection import ReportOption, ReportScope


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def test_reports_menu_presents_eight_teacher_questions() -> None:
    output = StringIO()
    run_reports_menu(
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert len(REPORT_MENU_TITLES) == 8
    assert "What would you like to find out?" in rendered
    assert "1. What do I need to update in my gradebook?" in rendered
    assert "8. What did this assessment contribute?" in rendered
    assert "Genesis" not in rendered
    for title in REPORT_MENU_TITLES:
        assert title in rendered  # preserve legacy report-family names


def test_all_eight_reports_have_an_advanced_direct_cli_route() -> None:
    output = StringIO()
    responses: list[str] = []
    for number in range(1, 9):
        responses.extend((str(number), "t", "", "b"))
    responses.append("b")
    run_reports_menu(
        input_fn=ScriptedInput(*responses),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    for command in (
        "reconciliation", "justify", "standards profile", "standards growth",
        "evidence", "checkpoint", "readiness", "impact"
    ):
        assert f"meridian reports {command} --help" in rendered
    assert "For advanced use" in rendered


def test_unconnected_catalog_does_not_claim_to_generate_report() -> None:
    output = StringIO()
    run_reports_menu(
        input_fn=ScriptedInput("7", "1", "", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    assert "not connected to your class data yet" in output.getvalue()
    assert "No report was generated or saved." in output.getvalue()


def test_injected_catalog_prepares_scopes_without_running_engine() -> None:
    class Catalog:
        def options(self, *, report_kind: str, scope: ReportScope, selected: object):
            options = {
                "class": (ReportOption("class_12", "English 12 - Period 3"),),
                "period": (ReportOption("mp1", "Marking Period 1"),),
            }
            return options[scope]

    prepared = []
    output = StringIO()
    run_reports_menu(
        input_fn=ScriptedInput("7", "1", "1", "1", "b", "b"),
        output=output,
        clear_fn=lambda: None,
        catalog=Catalog(),
        on_prepared=prepared.append,
    )
    assert len(prepared) == 1
    assert prepared[0].report_kind == "marking_period_readiness"
    assert prepared[0].identifiers() == {"class": "class_12", "period": "mp1"}
