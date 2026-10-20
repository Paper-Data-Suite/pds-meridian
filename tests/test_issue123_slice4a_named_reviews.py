"""Slice 4A — exact read-only named Grade Item and proficiency selection."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from meridian.menu_teacher_named_review import (
    run_named_grade_item_proficiency,
    run_named_grade_item_review,
)
from meridian.teacher_navigation_choices import (
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_domain import (
    TeacherAcademicChoiceCatalog,
    TeacherAcademicChoiceReaders,
)
from meridian.teacher_session import TeacherSessionContext


def fixture_catalog(tmp_path: Path, *, duplicate: bool = False):
    """All input is synthetic; do not open a real PDS workspace."""
    class_id = "english-12"
    session = TeacherSessionContext()
    session.select_class(class_id)
    navigation = MagicMock()
    navigation.session = session
    navigation._root.return_value = tmp_path
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=class_id, school_year="2026-2027"
    )
    navigation.verify_class.return_value = navigation.current_class.return_value
    navigation.readers.roster_loader.return_value = SimpleNamespace(
        class_id=class_id,
        students=(
            SimpleNamespace(
                student_id="s-opaque",
                first_name="Alex",
                last_name="Rivera",
                period="2",
                extra_fields={},
            ),
        ),
    )
    row = SimpleNamespace(
        class_id=class_id,
        grade_item_id="gi-opaque",
        title="The Guava Memoir",
        purpose="standards_proficiency",
        status="active",
        selection_state="selected_latest",
        selected_revision=2,
        selected_revision_sha256="a" * 64,
        latest_persisted_revision=2,
        memberships=(),
    )
    second = SimpleNamespace(**vars(row))
    second.grade_item_id = "different-opaque"
    if not duplicate:
        second.title = "Another Assessment"
    review = SimpleNamespace(class_id=class_id, items=(row, second))
    reviewer = MagicMock(return_value=review)
    stored = SimpleNamespace(
        snapshot=SimpleNamespace(result_revision=1), result_sha256="b" * 64
    )
    result_loader = MagicMock(return_value=stored)
    readers = TeacherAcademicChoiceReaders(
        class_lister=lambda _root: (),
        grade_item_reviewer=reviewer,
        result_identity_lister=lambda _root, _class: (
            ("gi-opaque", "s-opaque", "RL.CR.11-12.1"),
        ),
        result_loader=result_loader,
    )
    return (
        TeacherAcademicChoiceCatalog(navigation, readers),
        navigation,
        reviewer,
        result_loader,
    )


def input_sequence(*values: str):
    entries = iter(values)
    return lambda _prompt: next(entries)


def test_named_grade_item_choice_is_exact_and_does_not_expose_ids(
    tmp_path: Path,
) -> None:
    catalog, _, reviewer, _ = fixture_catalog(tmp_path)
    choices = load_teacher_choices(
        catalog, scope="grade_item", selected={"class": "english-12"}
    )
    assert {choice.identity for choice in choices} == {
        ("gi-opaque",),
        ("different-opaque",),
    }
    assert "gi-opaque" not in " ".join(choice.display for choice in choices)
    assert all(choice.witness for choice in choices)
    assert reviewer.call_count == 1


def test_duplicate_teacher_labels_fail_closed_even_with_distinct_ids(
    tmp_path: Path,
) -> None:
    catalog, *_ = fixture_catalog(tmp_path, duplicate=True)
    with pytest.raises(TeacherChoiceUnavailable, match="indistinguishable"):
        load_teacher_choices(
            catalog, scope="grade_item", selected={"class": "english-12"}
        )


def test_standard_choices_include_only_current_selected_results(
    tmp_path: Path,
) -> None:
    catalog, _, _, result_loader = fixture_catalog(tmp_path)
    selected = {"class": "english-12", "grade_item": "gi-opaque", "student": "s-opaque"}
    current = load_teacher_choices(catalog, scope="standard", selected=selected)
    assert len(current) == 1
    assert current[0].identity == ("RL.CR.11-12.1",)
    assert "b" * 64 not in current[0].display
    result_loader.return_value = None
    assert load_teacher_choices(catalog, scope="standard", selected=selected) == ()


def test_wrong_class_student_or_grade_item_blocks_result_enumeration(
    tmp_path: Path,
) -> None:
    catalog, _, _, result_loader = fixture_catalog(tmp_path)
    for selected in (
        {"class": "english-12", "grade_item": "other", "student": "s-opaque"},
        {"class": "english-12", "grade_item": "gi-opaque", "student": "other"},
    ):
        with pytest.raises(TeacherChoiceUnavailable):
            load_teacher_choices(catalog, scope="standard", selected=selected)
    result_loader.assert_not_called()


def test_named_grade_item_view_is_read_only_and_carries_session_choice(
    tmp_path: Path,
) -> None:
    catalog, navigation, reviewer, _ = fixture_catalog(tmp_path)
    output = StringIO()
    run_named_grade_item_review(
        navigation=navigation,
        catalog=catalog,
        review_loader=reviewer,
        input_fn=input_sequence("2", ""),
        output=output,
        clear_fn=lambda: None,
    )
    screen = output.getvalue()
    assert "The Guava Memoir" in screen
    assert "No Grade Item revision or membership was selected" in screen
    assert "gi-opaque" not in screen
    assert navigation.session.active_grade_item_id == "gi-opaque"


def test_named_proficiency_renders_student_name_not_canonical_id(
    tmp_path: Path,
) -> None:
    catalog, navigation, _, _ = fixture_catalog(tmp_path)
    output = StringIO()
    loader = MagicMock(
        return_value=SimpleNamespace(
            status="calculated",
            proficiency_label="Meeting",
            policy_title="Grading Policy",
            scale_title="Four levels",
        )
    )
    run_named_grade_item_proficiency(
        navigation=navigation,
        catalog=catalog,
        load_proficiency=loader,
        input_fn=input_sequence("2", "1", "1", ""),
        output=output,
        clear_fn=lambda: None,
    )
    screen = output.getvalue()
    assert "Student: Alex Rivera" in screen
    assert "Current proficiency: Meeting" in screen
    assert "s-opaque" not in screen
    assert "gi-opaque" not in screen
    assert navigation.session.active_student_id == "s-opaque"
    loader.assert_called_once()


def test_stale_or_unexplainable_proficiency_returns_blocker_not_grade(
    tmp_path: Path,
) -> None:
    catalog, navigation, _, _ = fixture_catalog(tmp_path)
    output = StringIO()
    loader = MagicMock(side_effect=RuntimeError("revoked evidence access"))
    run_named_grade_item_proficiency(
        navigation=navigation,
        catalog=catalog,
        load_proficiency=loader,
        input_fn=input_sequence("2", "1", "1", ""),
        output=output,
        clear_fn=lambda: None,
    )
    assert "could not be verified or explained safely" in output.getvalue()
    assert "revoked evidence access" not in output.getvalue()
    assert navigation.session.active_student_id is None


def test_grade_item_and_proficiency_original_exact_routes_stay_in_source() -> None:
    root = Path(__file__).resolve().parents[1]
    for menu in ("menu_grade_items.py", "menu_proficiency.py"):
        source = (root / "meridian" / menu).read_text(encoding="utf-8")
        assert "navigation_context is not None" in source
        assert "Advanced:" in source
        assert "def run_" in source
        assert "read_choice(input_fn" in source
        assert "TeacherAcademicChoiceCatalog(navigation_context)" in source


def test_main_menu_and_quit_unwind_named_navigation(
    tmp_path: Path,
) -> None:
    from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

    catalog, navigation, reviewer, _ = fixture_catalog(tmp_path)
    for command, raised in (("M", ReturnToMainMenu), ("Q", QuitPDS)):
        with pytest.raises(raised):
            run_named_grade_item_review(
                navigation=navigation,
                catalog=catalog,
                review_loader=reviewer,
                input_fn=input_sequence(command),
                output=StringIO(),
                clear_fn=lambda: None,
            )


def test_student_names_are_disambiguated_by_verified_roster_position(
    tmp_path: Path,
) -> None:
    catalog, navigation, _, _ = fixture_catalog(tmp_path)
    student = navigation.readers.roster_loader.return_value.students[0]
    other = SimpleNamespace(**vars(student))
    other.student_id = "s-other"
    navigation.readers.roster_loader.return_value.students = (student, other)
    choices = load_teacher_choices(
        catalog, scope="student", selected={"class": "english-12"}
    )
    assert len(choices) == 2
    assert choices[0].identity != choices[1].identity
    assert choices[0].display != choices[1].display
    assert all("s-" not in choice.display for choice in choices)
