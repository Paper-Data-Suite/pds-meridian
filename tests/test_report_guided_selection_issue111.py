from __future__ import annotations

from io import StringIO
from typing import Mapping

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.report_guided_selection import (
    REPORT_GUIDES,
    ReportOption,
    ReportScope,
    collect_guided_report_selection,
)


class ScriptedInput:
    def __init__(self, *choices: str) -> None:
        self.choices = iter(choices)

    def __call__(self, prompt: str) -> str:
        assert prompt == "Choice: " or prompt.startswith("Press Enter")
        return next(self.choices)


class Catalog:
    calls: list[tuple[str, ReportScope, dict[ReportScope, str]]]

    def __init__(self) -> None:
        self.calls = []

    def options(
        self,
        *,
        report_kind: str,
        scope: ReportScope,
        selected: Mapping[ReportScope, str],
    ) -> tuple[ReportOption, ...]:
        self.calls.append((report_kind, scope, dict(selected)))
        options = {
            "class": (ReportOption("class_10", "English 10 - Period 2"),),
            "period": (ReportOption("mp1", "Marking Period 1"),),
            "student": (
                ReportOption("student_b", "Taylor Green", "Record B"),
                ReportOption("student_a", "Alex Green", "Record A"),
            ),
            "grade_item": (ReportOption("gi_17", "Comparative Essay"),),
            "checkpoint": (ReportOption("prior", "October Checkpoint"),),
            "mapping": (ReportOption("policy_r2", "School gradebook scale"),),
        }
        if scope != "class":
            assert selected["class"] == "class_10"
        if scope not in {"class", "period"}:
            assert selected["period"] == "mp1"
        return options[scope]


def test_eight_guides_use_sis_neutral_teacher_questions() -> None:
    assert len(REPORT_GUIDES) == 8
    assert len({guide.report_kind for guide in REPORT_GUIDES}) == 8
    assert all(guide.scopes[:2] == ("class", "period") for guide in REPORT_GUIDES)
    assert "my gradebook" in REPORT_GUIDES[0].question
    assert "Genesis" not in str(REPORT_GUIDES)


def test_gathers_verified_identities_and_displays_labels_only() -> None:
    output = StringIO()
    catalog = Catalog()
    prepared = collect_guided_report_selection(
        REPORT_GUIDES[1],
        catalog=catalog,
        input_fn=ScriptedInput("1", "1", "2"),
        output=output,
        clear_fn=lambda: None,
    )
    assert prepared is not None
    assert prepared.identifiers() == {
        "class": "class_10", "period": "mp1", "student": "student_b"
    }
    assert "English 10 - Period 2" in output.getvalue()
    assert "Alex Green - Record A" in output.getvalue()
    assert "class_10" not in output.getvalue()
    assert "student_b" not in output.getvalue()
    assert len(catalog.calls) >= 6  # choices are revalidated before acceptance


def test_back_moves_one_scope_and_clears_its_choice() -> None:
    output = StringIO()
    prepared = collect_guided_report_selection(
        REPORT_GUIDES[1],
        catalog=Catalog(),
        input_fn=ScriptedInput("1", "1", "b", "b", "1", "1", "1"),
        output=output,
        clear_fn=lambda: None,
    )
    assert prepared is not None
    assert prepared.identifiers()["student"] == "student_a"
    assert "Step 2 of 3" in output.getvalue()


def test_back_on_first_step_cancels_without_result() -> None:
    prepared = collect_guided_report_selection(
        REPORT_GUIDES[0],
        catalog=Catalog(),
        input_fn=ScriptedInput("b"),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert prepared is None


@pytest.mark.parametrize(
    ("choice", "expected"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_global_navigation_bubbles_to_main_controller(
    choice: str,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected):
        collect_guided_report_selection(
            REPORT_GUIDES[7],
            catalog=Catalog(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def test_duplicate_catalog_identifiers_fail_closed() -> None:
    class DuplicateCatalog(Catalog):
        def options(
            self,
            *,
            report_kind: str,
            scope: ReportScope,
            selected: Mapping[ReportScope, str],
        ) -> tuple[ReportOption, ...]:
            return (
                ReportOption("same", "English 10"),
                ReportOption("same", "English 12"),
            )

    output = StringIO()
    result = collect_guided_report_selection(
        REPORT_GUIDES[0],
        catalog=DuplicateCatalog(),
        input_fn=ScriptedInput(""),
        output=output,
        clear_fn=lambda: None,
    )
    assert result is None
    assert "could not be verified" in output.getvalue()


def test_indistinguishable_display_labels_fail_closed() -> None:
    class AmbiguousCatalog(Catalog):
        def options(
            self,
            *,
            report_kind: str,
            scope: ReportScope,
            selected: Mapping[ReportScope, str],
        ) -> tuple[ReportOption, ...]:
            return (
                ReportOption("a", "English 10"),
                ReportOption("b", "English 10"),
            )

    assert collect_guided_report_selection(
        REPORT_GUIDES[0],
        catalog=AmbiguousCatalog(),
        input_fn=ScriptedInput(""),
        output=StringIO(),
        clear_fn=lambda: None,
    ) is None


def test_option_fields_cannot_contain_control_characters() -> None:
    with pytest.raises(ValueError):
        ReportOption("student_id", "Student\nSecrets")


def test_unavailable_scope_returns_no_selection() -> None:
    class EmptyCatalog(Catalog):
        def options(
            self,
            *,
            report_kind: str,
            scope: ReportScope,
            selected: Mapping[ReportScope, str],
        ) -> tuple[ReportOption, ...]:
            return ()

    output = StringIO()
    assert collect_guided_report_selection(
        REPORT_GUIDES[3],
        catalog=EmptyCatalog(),
        input_fn=ScriptedInput(""),
        output=output,
        clear_fn=lambda: None,
    ) is None
    assert "No report was generated or changed." in output.getvalue()


def test_stale_option_is_rejected_and_offered_again() -> None:
    class MovingCatalog(Catalog):
        def __init__(self) -> None:
            super().__init__()
            self.visits = 0

        def options(
            self,
            *,
            report_kind: str,
            scope: ReportScope,
            selected: Mapping[ReportScope, str],
        ) -> tuple[ReportOption, ...]:
            self.visits += 1
            if self.visits == 2:
                return ()  # The selected class ceased being available.
            return (ReportOption("class_10", "English 10"),)

    output = StringIO()
    assert collect_guided_report_selection(
        REPORT_GUIDES[0],
        catalog=MovingCatalog(),
        input_fn=ScriptedInput("1", "", "b"),
        output=output,
        clear_fn=lambda: None,
    ) is None
    assert "The choices changed. Please select again." in output.getvalue()


def test_invalid_number_is_reprompted_without_selecting() -> None:
    output = StringIO()
    assert collect_guided_report_selection(
        REPORT_GUIDES[6],
        catalog=Catalog(),
        input_fn=ScriptedInput("99", "", "b"),
        output=output,
        clear_fn=lambda: None,
    ) is None
    assert "Choose a number from the list" in output.getvalue()


def test_final_revalidation_rejects_prior_scope_after_change() -> None:
    class ChangedEarlierCatalog(Catalog):
        def __init__(self) -> None:
            super().__init__()
            self.class_calls = 0

        def options(
            self,
            *,
            report_kind: str,
            scope: ReportScope,
            selected: Mapping[ReportScope, str],
        ) -> tuple[ReportOption, ...]:
            if scope == "class":
                self.class_calls += 1
                if self.class_calls > 2:
                    return (ReportOption("other", "Other class"),)
            return super().options(
                report_kind=report_kind, scope=scope, selected=selected
            )

    output = StringIO()
    result = collect_guided_report_selection(
        REPORT_GUIDES[6],
        catalog=ChangedEarlierCatalog(),
        input_fn=ScriptedInput("1", "1", ""),
        output=output,
        clear_fn=lambda: None,
    )
    assert result is None
    assert "changed during selection" in output.getvalue()
