"""#123 11B: measured cross-menu context/navigation and bounded choice journeys.

The actual nine-task compositor, seven nested named-menu routes and the real
class/choice controllers are used. Domain record readers/writers are synthetic
read-only probes; this is not a wheel, protected-evidence, or write E2E test.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from time import perf_counter_ns
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from meridian.menu_teacher_named_review import _class
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_terminal import select_teacher_choice
from meridian.teacher_session import TeacherSessionContext

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/architecture/issue123-slice11b-interaction-contract.json"


@dataclass
class Script:
    answers: list[str]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, prompt: str = "") -> str:
        if not self.answers:
            raise AssertionError(f"Unexpected teacher input prompt: {prompt}")
        answer = self.answers.pop(0)
        self.calls.append((prompt, answer))
        return answer


@dataclass
class SyntheticCore:
    root: Path
    year: str = "2026-2027"
    revision: int = 13
    roster_failure: bool = False
    reads: dict[str, int] = field(default_factory=dict)

    def count(self, name: str) -> None:
        self.reads[name] = self.reads.get(name, 0) + 1

    def workspace(self) -> Path:
        self.count("workspace")
        return self.root

    def active_year(self, root: Path) -> str:
        self.count("year")
        assert root == self.root
        return self.year

    def metadata(self, root: Path, class_id: str) -> SimpleNamespace:
        self.count("metadata")
        assert root == self.root
        if class_id not in {"english_12_pd2", "english_10_pd1"}:
            raise ValueError("Unknown synthetic class")
        return SimpleNamespace(class_id=class_id, school_year=self.year)

    def roster(self, root: Path, class_id: str) -> SimpleNamespace:
        self.count("roster")
        assert root == self.root
        if self.roster_failure:
            raise OSError("Synthetic roster inaccessible")
        return SimpleNamespace(class_id=class_id, students=())

    def periods(self, root: Path, year: str) -> tuple[SimpleNamespace, ...]:
        self.count("periods")
        assert root == self.root and year == self.year
        return (
            SimpleNamespace(
                school_year=year,
                period_id="mp1",
                calendar_revision=self.revision,
                is_current_calendar=True,
                period=SimpleNamespace(
                    period_type="marking_period",
                    lifecycle="active",
                    label="Marking Period 1",
                ),
            ),
        )


def make_navigation(tmp_path: Path) -> tuple[TeacherNavigationContext, SyntheticCore]:
    core = SyntheticCore(tmp_path)
    nav = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=core.workspace,
            active_year_loader=core.active_year,
            class_metadata_loader=core.metadata,
            roster_loader=core.roster,
            period_lister=core.periods,  # type: ignore[arg-type]
        ),
    )
    return nav, core


@dataclass
class OneClassCatalog:
    reads: int = 0

    def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
        assert scope == "class" and not selected
        self.reads += 1
        return (
            TeacherChoice(
                identity=("english_12_pd2",),
                label="English 12 · Period 2",
                detail="2026–2027 · 29 rostered students",
                witness="verified-core-class-v1",
            ),
        )


def _composed(
    monkeypatch: pytest.MonkeyPatch,
    nav: TeacherNavigationContext,
    script: Script,
    output: StringIO,
) -> tuple[Any, list[str], OneClassCatalog]:
    import meridian.menu as main
    import meridian.menu_explain as explain
    import meridian.menu_export as export
    import meridian.menu_grade_items as items
    import meridian.menu_grades as grades
    import meridian.menu_overrides as overrides
    import meridian.menu_proficiency as proficiency
    import meridian.menu_snapshots as snapshots

    names = (
        (items, "run_named_grade_item_review", "Grade Items"),
        (proficiency, "run_named_grade_item_proficiency", "Proficiency"),
        (grades, "run_named_current_grade_review", "Grades"),
        (overrides, "run_named_current_override_review", "Overrides"),
        (snapshots, "run_named_snapshot_browse", "Snapshots"),
        (export, "run_named_export_profile_browse", "Export"),
        (explain, "run_named_current_grade_explanation", "Explain"),
    )
    visited: list[str] = []
    classes = OneClassCatalog()
    for module, handler_name, area in names:

        def named_probe(*, _area: str = area, **kwargs: Any) -> None:
            assert kwargs["navigation"] is nav
            current = _class(
                nav,
                classes,
                input_fn=kwargs["input_fn"],
                output=kwargs["output"],
                clear_fn=kwargs["clear_fn"],
            )
            assert current == (nav.current_class().workspace, "english_12_pd2")
            visited.append(_area)

        monkeypatch.setattr(module, handler_name, named_probe)

    def navigation_factory(
        *, session: TeacherSessionContext
    ) -> TeacherNavigationContext:
        assert session is nav.session
        return nav

    monkeypatch.setattr(main, "TeacherNavigationContext", navigation_factory)
    dependencies = main.default_teacher_menu_dependencies(
        diagnostics=MagicMock(),
        session_context=nav.session,
        input_fn=script,
        output=output,
        clear_fn=lambda: None,
    )
    assert dependencies.navigation_context is nav
    return dependencies, visited, classes


def _is_raw_prompt(prompt: str) -> bool:
    return bool(
        re.search(
            r"\b(?:class|student|work|grade.item|policy|period|"
            r"snapshot|review|publication)\s+id\b|sha256|cache key|"
            r"digest|revision\s*:",
            prompt,
            flags=re.I,
        )
    )


def test_all_eight_non_inbox_teacher_tasks_reuse_one_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.menu as main

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    nav, core = make_navigation(tmp_path)
    script = Script(
        [
            "2",
            "1",
            "1",
            "B",  # Grade Items: choose class by title once
            "3",
            "1",
            "B",  # Proficiency
            "4",
            "1",
            "B",  # Grades
            "5",
            "1",
            "B",  # Overrides
            "6",
            "7",
            "B",  # Snapshots
            "7",
            "7",
            "B",  # Export
            "8",
            "9",
            "B",  # Explain
            "9",
            "B",  # real Reports screen; existing guided detail tested in #111
            "Q",
        ]
    )
    output = StringIO()
    dependencies, visited, classes = _composed(monkeypatch, nav, script, output)
    started = perf_counter_ns()
    assert (
        main.run_menu(
            dependencies=dependencies,
            input_fn=script,
            output=output,
            clear_fn=lambda: None,
        )
        == 0
    )
    elapsed_ns = perf_counter_ns() - started
    assert elapsed_ns > 0
    assert visited == contract["seven_named_domain_probes"]
    assert classes.reads == 3  # list, selector refresh, class handoff
    assert not script.answers
    assert len(script.calls) == contract["expected_input_calls"]
    assert (
        sum(answer == "1" and prompt == "Choice: " for prompt, answer in script.calls)
        >= 1
    )
    assert sum("Search visible names" in prompt for prompt, _ in script.calls) == 0
    assert sum(_is_raw_prompt(prompt) for prompt, _ in script.calls) == 0
    assert core.reads.get("roster", 0) >= 7  # class checked on every task
    assert nav.session.active_class_id is None  # Q clears process-local session
    assert "Reports are read-only" in output.getvalue()


def test_main_menu_unwinds_m_then_reuses_class_without_reselection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.menu as main

    nav, _ = make_navigation(tmp_path)
    script = Script(["2", "1", "1", "M", "3", "1", "B", "Q"])
    output = StringIO()
    dependencies, visited, classes = _composed(monkeypatch, nav, script, output)
    assert (
        main.run_menu(
            dependencies=dependencies,
            input_fn=script,
            output=output,
            clear_fn=lambda: None,
        )
        == 0
    )
    assert visited == ["Grade Items", "Proficiency"]
    assert classes.reads == 3
    assert len(script.calls) == 8
    assert not script.answers


def test_class_switch_discards_grade_item_student_and_period_context(
    tmp_path: Path,
) -> None:
    nav, core = make_navigation(tmp_path)
    nav.choose_class("english_12_pd2")
    nav.choose_period("mp1")
    nav.session.select_grade_item("grade_item_01")
    nav.session.select_student("student_07")
    nav.choose_class("english_10_pd1")
    assert nav.session.active_class_id == "english_10_pd1"
    assert nav.session.active_grade_item_id is None
    assert nav.session.active_student_id is None
    assert nav.current_period() is None
    assert nav.current_class().class_id == "english_10_pd1"
    nav.choose_period("mp1")
    core.revision = 14
    with pytest.raises(NavigationScopeUnavailable, match="changed"):
        nav.current_period()
    assert nav.current_period() is None


def test_lost_roster_metadata_cannot_serve_as_authorized_class(
    tmp_path: Path,
) -> None:
    nav, core = make_navigation(tmp_path)
    nav.choose_class("english_12_pd2")
    core.roster_failure = True
    with pytest.raises(NavigationScopeUnavailable, match="cannot be verified"):
        nav.current_class()
    assert core.reads["roster"] >= 2


@dataclass
class StudentCatalog:
    choices: tuple[TeacherChoice, ...]
    calls: int = 0
    drift_after: int = 0

    def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
        assert scope == "student" and selected == {"class": "english_12_pd2"}
        self.calls += 1
        if self.drift_after and self.calls >= self.drift_after:
            return tuple(
                TeacherChoice(
                    item.identity, item.label, item.detail, witness="changed-revision"
                )
                if item.identity == ("student_07",)
                else item
                for item in self.choices
            )
        return self.choices


def _students() -> tuple[TeacherChoice, ...]:
    entries = []
    for number in range(1, 30):
        if number in (7, 21):
            label = "José García"
            detail = f"English 12 · seat {number:02d}"
        else:
            label = f"Student {number:02d}"
            detail = "English 12 · active roster"
        entries.append(
            TeacherChoice(
                identity=(f"student_{number:02d}",),
                label=label,
                detail=detail,
                witness=f"roster-v2:{number}",
            )
        )
    return tuple(entries)


def _select(
    catalog: StudentCatalog, script: Script, output: StringIO, *, page_size: int = 10
) -> TeacherChoice | None:
    return select_teacher_choice(
        catalog=catalog,
        scope="student",
        selected={"class": "english_12_pd2"},
        title="Roster Students",
        question="Which student is being reviewed?",
        input_fn=script,
        output=output,
        clear_fn=lambda: None,
        page_size=page_size,
    )


def test_29_roster_students_duplicate_unicode_names_are_disambiguated() -> None:
    catalog = StudentCatalog(_students())
    script = Script(["S", "josé", "2"])
    output = StringIO()
    chosen = _select(catalog, script, output)
    assert chosen is not None and chosen.identity == ("student_21",)
    assert catalog.calls == 2
    assert len(script.calls) == 3
    display = output.getvalue()
    assert "José García" in display and "seat 07" in display
    assert "seat 21" in display
    assert "student_21" not in display  # opaque ID remains hidden
    assert "roster-v2" not in display


def test_29_roster_students_paging_and_refresh_are_bounded() -> None:
    catalog = StudentCatalog(_students())
    script = Script(["N", "N", "9"])
    output = StringIO()
    chosen = _select(catalog, script, output)
    assert chosen is not None and chosen.identity == ("student_29",)
    assert catalog.calls == 2
    assert "Page 3/3" in output.getvalue()
    assert len(script.calls) == 3


def test_indistinguishable_duplicate_names_fail_closed_without_input() -> None:
    same = (
        TeacherChoice(("student_1",), "José García", "English 12"),
        TeacherChoice(("student_2",), "José García", "English 12"),
    )
    catalog = StudentCatalog(same)
    output = StringIO()
    assert _select(catalog, Script([]), output) is None
    assert catalog.calls == 1
    assert "could not be verified" in output.getvalue().lower()


def test_changed_choice_witness_never_silently_approves_old_row() -> None:
    catalog = StudentCatalog(_students(), drift_after=2)
    output = StringIO()
    # First visible row is José García, seat 07; the fresh witness changes.
    chosen = _select(catalog, Script(["1", "B"]), output)
    assert chosen is None
    assert catalog.calls == 2
    assert "changed" in output.getvalue().lower()


def test_choice_cancel_and_refresh_perform_no_selection() -> None:
    catalog = StudentCatalog(_students())
    script = Script(["R", "B"])
    output = StringIO()
    assert _select(catalog, script, output) is None
    assert catalog.calls == 2  # original plus explicit refresh, no selection
    assert len(script.calls) == 2


def test_acceptance_contract_records_limits_without_claiming_installed_proof() -> None:
    value = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert value["schema"] == "pds.meridian.issue123.interaction_contract.v1"
    assert value["source_base"] == "751c9e0721f74451dc691650c5877619c77ecefc"
    assert value["expected_input_calls"] == 25
    assert value["status"] == "source-tree qualification pending"
    assert value["installed_wheel_acceptance"] == "not attempted in Slice 11B"
