"""#123 Slice 4C: exact current Core work, linked Grade Item, no writes."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from pds_core.routing_models import ModuleWorkRef

from meridian.menu_teacher_named_work import run_named_work_membership_review
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_work import TeacherRegisteredWorkCatalog
from meridian.teacher_session import TeacherSessionContext

CLASS = "english-12"
YEAR = "2026-2027"
ITEM = "opaque-grade-item"


def fixture(tmp_path: Path):
    session = TeacherSessionContext()
    session.select_class(CLASS)
    nav = MagicMock()
    nav.session = session
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    nav.verify_class.return_value = verified
    nav.current_class.return_value = verified
    nav.verify_period.return_value = SimpleNamespace(
        label="Marking Period 1", calendar_revision=2
    )
    work = ModuleWorkRef("quillan", CLASS, "opaque-work")
    registration = SimpleNamespace(
        work=work,
        title="Memoir Draft 2",
        work_kind="writing_assignment",
        school_year=YEAR,
        lifecycle="active",
        registration_revision=3,
        is_current_registration=True,
        updated_at=datetime(2026, 10, 18, tzinfo=UTC),
    )
    membership = SimpleNamespace(
        work=work,
        decision="included",
        selected_revision=2,
        selected_revision_sha256="b" * 64,
        latest_persisted_revision=2,
        grade_item_basis_state="matches_current_grade_item",
        academic_period_id="mp1",
        academic_period_school_year=YEAR,
        academic_period_calendar_revision=2,
    )
    row = SimpleNamespace(
        class_id=CLASS,
        grade_item_id=ITEM,
        title="The Guava Memoir",
        memberships=(membership,),
        selected_revision=1,
        selected_revision_sha256="a" * 64,
        latest_persisted_revision=1,
    )
    review = SimpleNamespace(class_id=CLASS, items=(row,))
    reviewer = MagicMock(return_value=review)
    lister = MagicMock(return_value=(registration,))
    catalog = TeacherRegisteredWorkCatalog(
        nav, grade_item_reviewer=reviewer, registration_lister=lister
    )
    return nav, catalog, reviewer, lister, registration, membership, row


def context():
    return {"class": CLASS, "grade_item": ITEM}


def next_inputs(*values: str):
    entries = iter(values)
    return lambda _prompt: next(entries)


def test_names_and_exact_identity_are_distinct(tmp_path: Path) -> None:
    _, catalog, _, _, _, _, _ = fixture(tmp_path)
    choice = load_teacher_choices(catalog, scope="registered_work", selected=context())[
        0
    ]
    assert choice.identity == ("quillan", "opaque-work")
    assert "Memoir Draft 2" in choice.display
    assert "Membership included" in choice.display
    assert "opaque-work" not in choice.display
    assert "b" * 64 not in choice.display
    assert choice.witness


def test_no_recorded_membership_is_not_assumed_included(tmp_path: Path) -> None:
    _, catalog, _, _, _, _, row = fixture(tmp_path)
    row.memberships = ()
    choice = load_teacher_choices(catalog, scope="registered_work", selected=context())[
        0
    ]
    assert "No recorded relationship" in choice.display
    assert "included" not in choice.display


def test_unselected_membership_is_not_an_active_decision(tmp_path: Path) -> None:
    _, catalog, _, _, _, membership, _ = fixture(tmp_path)
    membership.decision = None
    membership.selected_revision = None
    membership.selected_revision_sha256 = None
    choice = load_teacher_choices(catalog, scope="registered_work", selected=context())[
        0
    ]
    assert "Membership not selected" in choice.display
    assert "included" not in choice.display


def test_old_registration_revision_invalidates_exact_candidate(tmp_path: Path) -> None:
    _, catalog, _, _, registration, _, _ = fixture(tmp_path)
    original = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    registration.registration_revision += 1
    changed = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    assert original.identity == changed.identity
    assert original != changed


def test_new_membership_decision_invalidates_exact_candidate(tmp_path: Path) -> None:
    _, catalog, _, _, _, membership, _ = fixture(tmp_path)
    original = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    membership.decision = "excluded"
    membership.selected_revision_sha256 = "c" * 64
    changed = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    assert original != changed
    assert "Membership excluded" in changed.display


def test_catalog_wrong_class_year_and_scope_fail_closed(tmp_path: Path) -> None:
    _, catalog, _, _, registration, _, _ = fixture(tmp_path)
    for selected in ({"class": CLASS}, {"grade_item": ITEM}):
        with pytest.raises(TeacherChoiceUnavailable):
            catalog.options(scope="registered_work", selected=selected)
    with pytest.raises(TeacherChoiceUnavailable):
        catalog.options(scope="other", selected=context())
    registration.school_year = "2025-2026"
    with pytest.raises(TeacherChoiceUnavailable, match="changed scope"):
        catalog.options(scope="registered_work", selected=context())


def test_archived_registration_is_not_presented_as_current(tmp_path: Path) -> None:
    _, catalog, _, _, registration, _, _ = fixture(tmp_path)
    registration.lifecycle = "archived"
    assert (
        load_teacher_choices(catalog, scope="registered_work", selected=context()) == ()
    )


def test_duplicate_current_registrations_are_not_silently_chosen(
    tmp_path: Path,
) -> None:
    _, catalog, _, lister, registration, _, _ = fixture(tmp_path)
    lister.return_value = (registration, registration)
    with pytest.raises(TeacherChoiceUnavailable, match="repeated an exact identity"):
        load_teacher_choices(catalog, scope="registered_work", selected=context())


def test_more_than_500_registrations_block_instead_of_truncate(tmp_path: Path) -> None:
    _, catalog, _, lister, registration, _, _ = fixture(tmp_path)
    lister.return_value = (registration,) * 501
    with pytest.raises(TeacherChoiceUnavailable, match="exceeds bound"):
        catalog.options(scope="registered_work", selected=context())


def test_missing_or_duplicate_grade_item_is_blocked(tmp_path: Path) -> None:
    _, catalog, _, _, _, _, row = fixture(tmp_path)
    catalog.grade_item_reviewer = MagicMock(
        return_value=SimpleNamespace(class_id=CLASS, items=())
    )
    with pytest.raises(TeacherChoiceUnavailable, match="changed"):
        catalog.options(scope="registered_work", selected=context())
    catalog.grade_item_reviewer.return_value.items = (row, row)
    with pytest.raises(TeacherChoiceUnavailable, match="changed"):
        catalog.options(scope="registered_work", selected=context())


def test_provider_error_is_redacted_at_selector_boundary(tmp_path: Path) -> None:
    from meridian.teacher_navigation_terminal import select_teacher_choice

    _, catalog, _, lister, _, _, _ = fixture(tmp_path)
    lister.side_effect = RuntimeError("secret diagnostic path /class/data")
    output = StringIO()
    choice = select_teacher_choice(
        catalog=catalog,
        scope="registered_work",
        selected=context(),
        title="Work",
        question="Which work?",
        input_fn=next_inputs(),
        output=output,
        clear_fn=lambda: None,
    )
    assert choice is None
    assert "secret diagnostic" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


def test_workflow_selected_work_and_grade_item_are_hints_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import meridian.menu_teacher_named_review as named
    import meridian.menu_teacher_named_work as menu

    nav, catalog, reviewer, _, _, _, _ = fixture(tmp_path)
    chosen_work = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    chosen_item = TeacherChoice(identity=(ITEM,), label="The Guava Memoir")
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: chosen_item)
    monkeypatch.setattr(menu, "select_teacher_choice", lambda **_kw: chosen_work)
    monkeypatch.setattr(
        menu,
        "load_teacher_choices",
        lambda _catalog, *, scope, selected: (
            (chosen_item,) if scope == "grade_item" else (chosen_work,)
        ),
    )
    output = StringIO()
    run_named_work_membership_review(
        navigation=nav,
        review_loader=reviewer,
        catalog=catalog,
        input_fn=next_inputs(""),
        output=output,
        clear_fn=lambda: None,
    )
    screen = output.getvalue()
    assert "Memoir Draft 2" in screen
    assert "Current membership decision: included" in screen
    assert "Marking period: Marking Period 1" in screen
    assert "opaque-work" not in screen
    assert nav.session.active_work == ModuleWorkRef("quillan", CLASS, "opaque-work")
    assert nav.session.active_grade_item_id == ITEM
    reviewer.assert_called()


def test_stale_work_does_not_change_navigation_hints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import meridian.menu_teacher_named_review as named
    import meridian.menu_teacher_named_work as menu

    nav, catalog, reviewer, _, _, _, _ = fixture(tmp_path)
    selected_work = load_teacher_choices(
        catalog, scope="registered_work", selected=context()
    )[0]
    selected_item = TeacherChoice(identity=(ITEM,), label="The Guava Memoir")
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: selected_item)
    monkeypatch.setattr(menu, "select_teacher_choice", lambda **_kw: selected_work)
    monkeypatch.setattr(
        menu,
        "load_teacher_choices",
        lambda _catalog, *, scope, selected: (
            (selected_item,) if scope == "grade_item" else ()
        ),
    )
    output = StringIO()
    run_named_work_membership_review(
        navigation=nav,
        review_loader=reviewer,
        catalog=catalog,
        input_fn=next_inputs(""),
        output=output,
        clear_fn=lambda: None,
    )
    assert "could not be verified" in output.getvalue()
    assert nav.session.active_work is None
    assert nav.session.active_grade_item_id is None


def test_navigation_commands_propagate_from_grade_item_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import meridian.menu_teacher_named_review as named

    nav, catalog, reviewer, _, _, _, _ = fixture(tmp_path)
    for action, raised in (("M", ReturnToMainMenu), ("Q", QuitPDS)):
        monkeypatch.setattr(
            named, "select_teacher_choice", MagicMock(side_effect=raised)
        )
        with pytest.raises(raised):
            run_named_work_membership_review(
                navigation=nav,
                review_loader=reviewer,
                catalog=catalog,
                input_fn=next_inputs(),
                output=StringIO(),
                clear_fn=lambda: None,
            )


def test_scope_and_advanced_routes_remain_in_existing_grade_items_menu() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "meridian/menu_grade_items.py").read_text(encoding="utf-8")
    assert 'if choice == "7" and navigation_context is not None:' in source
    assert "run_named_work_membership_review(" in source
    assert "Advanced: Select work membership revision" in source
    assert "Advanced: Author work membership revision" in source
