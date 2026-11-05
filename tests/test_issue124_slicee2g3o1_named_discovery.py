"""#124 E2G3O1: named assessment discovery through real menu navigation.

The controller is read-only; catalogs are navigation hints, not setup grants.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pds_core.menu_navigation import ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian import menu_teacher_assessment_discovery as discovery
from meridian.assessment_setup_choices import NamedAssessment, NamedAssessmentList
from meridian.menu import default_teacher_menu_dependencies, run_menu
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_session import TeacherSessionContext

CLASS = "english12"
YEAR = "2026-2027"
PERIOD = "mp1"


def _named(count: int = 1) -> NamedAssessmentList:
    entries = []
    for index in range(count):
        work = ModuleWorkRef("scoreform", CLASS, f"scene_{index:02}")
        choice = TeacherChoice(
            identity=(work.class_id, work.module_id, work.work_id),
            label=f"Scene Study {index:02}",
            detail="registered assessment",
            source="ScoreForm",
            status="Grade Item not yet created",
        )
        candidate = SimpleNamespace(
            work=work,
            title=choice.label,
            registration_revision=1,
            setup_state="needs_create",
        )
        entries.append(
            NamedAssessment(
                candidate=candidate,
                choice=choice,
                publication_state="no_results_indexed",
                historical_publication_count=0,
                registration_created_at=datetime(2026, 9, 8, tzinfo=UTC),
            )
        )
    return NamedAssessmentList(
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        items=tuple(entries),
        choices=tuple(item.choice for item in entries),
    )


def _run(
    tmp_path: Path,
    answers: tuple[str, ...],
    *,
    session: TeacherSessionContext | None = None,
    named: NamedAssessmentList | None = None,
    metadata_class: str = CLASS,
    calendar_year: str = YEAR,
) -> tuple[str, Mock]:
    stream = StringIO()
    supplied = iter(answers)
    loader = Mock(return_value=_named() if named is None else named)
    period = SimpleNamespace(
        period_id=PERIOD,
        label="Marking Period 1",
        sequence=1,
        period_type="marking_period",
        lifecycle="active",
    )
    with (
        patch.object(
            discovery,
            "load_class_metadata",
            return_value=SimpleNamespace(class_id=metadata_class, school_year=YEAR),
        ),
        patch.object(
            discovery,
            "load_current_academic_period_calendar",
            return_value=SimpleNamespace(school_year=calendar_year, periods=(period,)),
        ),
        patch.object(discovery, "load_named_assessment_choices", loader),
    ):
        discovery.run_teacher_assessment_discovery_menu(
            session_context=(
                TeacherSessionContext(active_class_id=CLASS)
                if session is None
                else session
            ),
            input_fn=lambda _: next(supplied),
            output=stream,
            clear_fn=lambda: None,
            workspace_resolver=lambda: tmp_path,
        )
    return stream.getvalue(), loader


def test_requires_explicit_class_before_any_discovery(tmp_path: Path) -> None:
    output, loader = _run(tmp_path, ("",), session=TeacherSessionContext())
    loader.assert_not_called()
    assert "Select a class" in output


def test_discovery_is_explicitly_scoped_to_selected_period(
    tmp_path: Path,
) -> None:
    output, loader = _run(tmp_path, ("1", "B", "B"))
    loader.assert_called_once_with(
        tmp_path, class_id=CLASS, school_year=YEAR, period_id=PERIOD
    )
    assert "Scene Study 00" in output
    assert "read-only" in output.lower()
    assert "Setup execution is not enabled" in output


def test_details_are_hints_not_academic_selection(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("protected\n", encoding="utf-8")
    session = TeacherSessionContext(active_class_id=CLASS)
    before = (
        session.active_class_id,
        session.active_work,
        session.active_publication_id,
        session.active_grade_item_id,
        session.active_student_id,
    )
    output, _ = _run(tmp_path, ("1", "1", "", "B", "B"), session=session)
    assert "Registration revision: 1" in output
    assert "Catalog setup hint: needs_create" in output
    assert session.active_work is None
    assert (
        session.active_class_id,
        session.active_work,
        session.active_publication_id,
        session.active_grade_item_id,
        session.active_student_id,
    ) == before
    assert sentinel.read_text(encoding="utf-8") == "protected\n"


def test_search_and_clear_keep_bounded_navigation(tmp_path: Path) -> None:
    output, loader = _run(
        tmp_path,
        ("1", "F", "nomatch", "C", "B", "B"),
        named=_named(12),
    )
    loader.assert_called_once()
    assert "No assessments match this search" in output
    assert "Matches: 12" in output


def test_next_previous_pages_do_not_refresh_catalog(tmp_path: Path) -> None:
    output, loader = _run(tmp_path, ("1", "N", "P", "B", "B"), named=_named(12))
    assert "Page 2 of 2" in output
    assert "Page 1 of 2" in output
    loader.assert_called_once()


def test_invalid_scope_metadata_fails_without_discovery(tmp_path: Path) -> None:
    output, loader = _run(tmp_path, ("",), metadata_class="wrong")
    loader.assert_not_called()
    assert "cannot verify the selected class/calendar" in output


def test_invalid_calendar_year_fails_without_discovery(tmp_path: Path) -> None:
    output, loader = _run(tmp_path, ("",), calendar_year="2025-2026")
    loader.assert_not_called()
    assert "cannot verify the selected class/calendar" in output


def test_period_back_does_not_query_academic_catalog(tmp_path: Path) -> None:
    output, loader = _run(tmp_path, ("B",))
    loader.assert_not_called()
    assert "Choose a marking period" in output


def test_catalog_unavailable_refuses_without_write(tmp_path: Path) -> None:
    stream = StringIO()
    with (
        patch.object(
            discovery,
            "load_class_metadata",
            return_value=SimpleNamespace(class_id=CLASS, school_year=YEAR),
        ),
        patch.object(
            discovery,
            "load_current_academic_period_calendar",
            return_value=SimpleNamespace(
                school_year=YEAR,
                periods=(
                    SimpleNamespace(
                        period_id=PERIOD,
                        label="Marking Period 1",
                        sequence=1,
                        period_type="marking_period",
                        lifecycle="active",
                    ),
                ),
            ),
        ),
        patch.object(
            discovery,
            "load_named_assessment_choices",
            side_effect=RuntimeError("catalog unavailable"),
        ),
    ):
        answers = iter(("1", "", "B"))
        discovery.run_teacher_assessment_discovery_menu(
            session_context=TeacherSessionContext(active_class_id=CLASS),
            input_fn=lambda _: next(answers),
            output=stream,
            clear_fn=lambda: None,
            workspace_resolver=lambda: tmp_path,
        )
    assert "choices could not be verified safely" in stream.getvalue()
    assert "No setup or academic selection was attempted" in stream.getvalue()


def test_duplicate_choice_identity_refused(tmp_path: Path) -> None:
    item = _named().items[0]
    list_with_duplicate = NamedAssessmentList(
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        items=(item, item),
        choices=(item.choice, item.choice),
    )
    output, _ = _run(tmp_path, ("1", "", "B"), named=list_with_duplicate)
    assert "choices could not be verified safely" in output


def test_main_menu_registers_D_and_passes_shared_session() -> None:
    output = StringIO()
    answers = iter(("D", "Q"))

    def read(_: str) -> str:
        return next(answers)

    with patch("meridian.menu.run_teacher_assessment_discovery_menu") as route:
        dependencies = default_teacher_menu_dependencies(
            input_fn=read, output=output, clear_fn=lambda: None
        )
        session = dependencies.session_context
        result = run_menu(
            dependencies=dependencies,
            input_fn=read,
            output=output,
            clear_fn=lambda: None,
        )
    assert result == 0
    assert "D. Discover Registered Assessments" in output.getvalue()
    route.assert_called_once()
    assert route.call_args.kwargs["session_context"] is session
    assert route.call_args.kwargs["input_fn"] is read


def test_main_menu_existing_R_and_numbered_routes_remain_intact() -> None:
    output = StringIO()
    answers = iter(("R", "2", "Q"))

    def read(_: str) -> str:
        return next(answers)

    with (
        patch("meridian.menu.run_teacher_action_recovery_menu") as recovery,
        patch("meridian.menu.run_grade_items_menu") as grades,
    ):
        dependencies = default_teacher_menu_dependencies(
            input_fn=read, output=output, clear_fn=lambda: None
        )
        assert (
            run_menu(
                dependencies=dependencies,
                input_fn=read,
                output=output,
                clear_fn=lambda: None,
            )
            == 0
        )
    recovery.assert_called_once()
    grades.assert_called_once()


def test_main_menu_help_describes_non_authoritative_discovery() -> None:
    output = StringIO()
    answers = iter(("H", "", "Q"))

    def read(_: str) -> str:
        return next(answers)

    dependencies = default_teacher_menu_dependencies(
        input_fn=read, output=output, clear_fn=lambda: None
    )
    assert (
        run_menu(
            dependencies=dependencies,
            input_fn=read,
            output=output,
            clear_fn=lambda: None,
        )
        == 0
    )
    assert "fresh review and one apply" in output.getvalue().lower()


def test_M_preserves_global_navigation_semantics(tmp_path: Path) -> None:
    with pytest.raises(ReturnToMainMenu):
        _run(tmp_path, ("M",))
