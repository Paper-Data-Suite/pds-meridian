"""Issue #123 Slice 3: verified process-local context and route composition."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_session import TeacherSessionContext


def make_context(tmp_path: Path) -> tuple[TeacherNavigationContext, dict[str, object]]:
    state: dict[str, object] = {
        "year": "2026-2027",
        "class_id": "english_12_pd2",
        "roster_class": "english_12_pd2",
        "calendar_revision": 13,
        "period_label": "Marking Period 1",
        "period_lifecycle": "active",
        "period_id": "mp1",
        "calls": [],
        "workspace": tmp_path,
    }

    def record(label: str) -> None:
        calls = state["calls"]
        assert isinstance(calls, list)
        calls.append(label)

    def workspace() -> Path:
        record("workspace")
        return state["workspace"]  # type: ignore[return-value]

    def year(root: Path) -> str | None:
        record("year")
        return state["year"]  # type: ignore[return-value]

    def metadata(root: Path, class_id: str) -> SimpleNamespace:
        record("metadata")
        return SimpleNamespace(class_id=state["class_id"], school_year=state["year"])

    def roster(root: Path, class_id: str) -> SimpleNamespace:
        record("roster")
        return SimpleNamespace(class_id=state["roster_class"], students=())

    def periods(root: Path, school_year: str) -> tuple[SimpleNamespace, ...]:
        record("periods")
        return (
            SimpleNamespace(
                period_id=state["period_id"],
                school_year=state["year"],
                calendar_revision=state["calendar_revision"],
                is_current_calendar=True,
                period=SimpleNamespace(
                    period_type="marking_period",
                    lifecycle=state["period_lifecycle"],
                    label=state["period_label"],
                ),
            ),
        )

    context = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=workspace,
            active_year_loader=year,
            class_metadata_loader=metadata,
            roster_loader=roster,
            period_lister=periods,  # type: ignore[arg-type]
        ),
    )
    return context, state


def test_no_eager_core_reads_and_identity_is_shared(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    assert state["calls"] == []
    assert navigation.session.active_class_id is None
    assert navigation.current_class() is None
    assert state["calls"] == []
    result = navigation.choose_class("english_12_pd2")
    assert result.school_year == "2026-2027"
    assert navigation.session.active_class_id == "english_12_pd2"
    assert state["calls"] == ["workspace", "year", "metadata", "roster"]
    assert navigation.current_class() == result
    assert len(state["calls"]) == 8


def test_failed_class_verification_never_changes_session(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    state["roster_class"] = "wrong_class"
    with pytest.raises(NavigationScopeUnavailable, match="roster"):
        navigation.choose_class("english_12_pd2")
    assert navigation.session.active_class_id is None


def test_active_school_year_missing_blocks_scope(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    state["year"] = None
    with pytest.raises(NavigationScopeUnavailable, match="active"):
        navigation.choose_class("english_12_pd2")
    assert navigation.current_period() is None


def test_period_requires_current_verified_class(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    with pytest.raises(NavigationScopeUnavailable, match="class"):
        navigation.choose_period("mp1")
    assert "periods" not in state["calls"]


def test_period_stays_exact_while_current(tmp_path: Path) -> None:
    navigation, _ = make_context(tmp_path)
    navigation.choose_class("english_12_pd2")
    selected = navigation.choose_period("mp1")
    assert selected.label == "Marking Period 1"
    assert selected.calendar_revision == 13
    assert navigation.current_period() == selected


@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("calendar_revision", 14),
        ("period_label", "Renamed Period"),
        ("period_id", "mp2"),
        ("period_lifecycle", "cancelled"),
    ],
)
def test_period_drift_fails_and_clears_without_retargeting(
    tmp_path: Path, changed: str, value: object
) -> None:
    navigation, state = make_context(tmp_path)
    navigation.choose_class("english_12_pd2")
    navigation.choose_period("mp1")
    state[changed] = value
    with pytest.raises(NavigationScopeUnavailable):
        navigation.current_period()
    assert navigation.current_period() is None
    assert navigation.session.active_class_id == "english_12_pd2"


def test_workspace_switch_fails_closed(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    navigation.choose_class("english_12_pd2")
    navigation.choose_period("mp1")
    other = tmp_path / "other"
    other.mkdir()
    state["workspace"] = other
    with pytest.raises(NavigationScopeUnavailable):
        navigation.current_period()
    assert navigation.current_period() is None


def test_external_class_switch_invalidates_period(tmp_path: Path) -> None:
    navigation, state = make_context(tmp_path)
    navigation.choose_class("english_12_pd2")
    navigation.choose_period("mp1")
    navigation.session.select_class("english_10_pd1")
    state["class_id"] = "english_10_pd1"
    state["roster_class"] = "english_10_pd1"
    with pytest.raises(NavigationScopeUnavailable):
        navigation.current_period()
    assert navigation.current_period() is None


def test_authoritative_reader_failure_is_never_treated_as_empty(tmp_path: Path) -> None:
    navigation, _ = make_context(tmp_path)
    navigation.choose_class("english_12_pd2")

    def broken_period_catalog(root: Path, year: str) -> tuple[object, ...]:
        raise OSError("unavailable")

    navigation.readers = TeacherNavigationReaders(
        workspace_resolver=navigation.readers.workspace_resolver,
        active_year_loader=navigation.readers.active_year_loader,
        class_metadata_loader=navigation.readers.class_metadata_loader,
        roster_loader=navigation.readers.roster_loader,
        period_lister=broken_period_catalog,  # type: ignore[arg-type]
    )
    with pytest.raises(NavigationScopeUnavailable, match="unavailable"):
        navigation.choose_period("mp1")


def test_controller_signatures_are_optional_for_legacy_injected_callers() -> None:
    from meridian.menu_explain import run_explain_menu
    from meridian.menu_export import run_export_menu
    from meridian.menu_grade_items import run_grade_items_menu
    from meridian.menu_grades import run_grade_preview_menu
    from meridian.menu_overrides import run_overrides_menu
    from meridian.menu_planning_signal import run_planning_signal_menu
    from meridian.menu_proficiency import run_proficiency_menu
    from meridian.menu_reports import run_reports_menu
    from meridian.menu_snapshots import run_snapshots_menu

    for runner in (
        run_grade_items_menu,
        run_proficiency_menu,
        run_grade_preview_menu,
        run_overrides_menu,
        run_snapshots_menu,
        run_export_menu,
        run_explain_menu,
        run_planning_signal_menu,
        run_reports_menu,
    ):
        signature = inspect.signature(runner)
        assert signature.parameters["navigation_context"].default is None


def test_main_menu_passes_one_identical_context_to_eight_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import meridian.menu as menu

    captures: dict[str, object] = {}
    for name in (
        "run_grade_items_menu",
        "run_proficiency_menu",
        "run_grade_preview_menu",
        "run_overrides_menu",
        "run_snapshots_menu",
        "run_export_menu",
        "run_explain_menu",
        "run_reports_menu",
    ):

        def route(*, _name: str = name, **kwargs: object) -> None:
            captures[_name] = kwargs.get("navigation_context")

        monkeypatch.setattr(menu, name, route)

    dependencies = menu.default_teacher_menu_dependencies(
        output=None,
        clear_fn=lambda: None,
    )
    for task in (
        "manage-grade-items",
        "review-proficiency",
        "preview-grades",
        "overrides",
        "snapshots",
        "export",
        "explain",
        "reports",
    ):
        dependencies.handler_for(task)()  # type: ignore[arg-type]
    assert len(captures) == 8
    assert all(
        context is dependencies.navigation_context for context in captures.values()
    )
    assert dependencies.navigation_context is not None
    assert dependencies.navigation_context.session is dependencies.session_context


def test_audited_original_inventory_stays_byte_for_byte_frozen() -> None:
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from issue123_navigation_audit import snapshot_bytes, verify_sources

    verify_sources(root)
    assert (root / "docs/architecture/issue123-slice1-inventory.json").read_bytes() == (
        snapshot_bytes(root)
    )
