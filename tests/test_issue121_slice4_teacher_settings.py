"""Issue #121 Slice 4: teacher settings, first-use setup, safe resumption."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.teacher_preferences as nav_module
from meridian.menu_teacher_settings import run_teacher_settings_menu
from meridian.teacher_preferences import TeacherNavigationPreferencesStore
from meridian.teacher_profile import TeacherProfileStore
from meridian.teacher_session import TeacherSessionContext


class Answers:
    def __init__(self, *responses: str) -> None:
        self.responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self.responses)


@pytest.fixture
def context(tmp_path: Path):
    config = tmp_path / "config"
    config.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = TeacherProfileStore(
        config_directory=config, actor_id_factory=lambda: "teacher-111"
    )
    preferences = TeacherNavigationPreferencesStore(store)
    session = TeacherSessionContext()
    return store, preferences, workspace, session


def run(context, *answers: str) -> str:
    store, prefs, root, session = context
    output = StringIO()
    run_teacher_settings_menu(
        session_context=session,
        profile_store=store,
        preferences_store=prefs,
        workspace_resolver=lambda: root,
        input_fn=Answers(*answers),
        output=output,
        clear_fn=lambda: None,
    )
    return output.getvalue()


def test_first_use_setup_requires_explicit_save(context) -> None:
    store, _, _, _ = context
    text = run(context, "1", "Teacher Example", "SAVE", "", "b")
    assert "Teacher Profile Saved" in text
    assert store.load().profile.display_name == "Teacher Example"
    assert store.load().profile.actor_id == "teacher-111"


def test_first_use_cancel_does_not_write(context) -> None:
    store, _, _, _ = context
    text = run(context, "1", "Teacher Example", "no", "", "b")
    assert "Nothing was changed" in text
    assert store.load() is None


def test_display_name_preserves_actor_and_historical_identity(context) -> None:
    store, _, _, _ = context
    first = store.create("Previous Name")
    run(context, "2", "Updated Name", "SAVE", "", "b")
    current = store.load().profile
    assert current.actor_id == first.profile.actor_id
    assert current.display_name == "Updated Name"
    assert current.revision == first.profile.revision + 1


def test_new_identity_requires_advanced_explicit_confirmation(context) -> None:
    store, _, _, _ = context
    first = store.create("Before", actor_id="teacher-before")
    run(context, "3", "After", "NO", "", "b")
    assert store.load() == first
    run(context, "3", "After", "CHANGE", "", "b")
    assert store.load().profile.display_name == "After"
    assert store.load().profile.actor_id != first.profile.actor_id


def test_reset_removes_profile_not_navigation_preferences(context) -> None:
    store, prefs, root, _ = context
    store.create("Teacher")
    prefs.save_selection(root, school_year="2026-2027", class_id=None)
    run(context, "4", "RESET", "", "b")
    assert store.load() is None
    assert prefs.load() is not None


def test_no_profile_does_not_block_read_only_navigation(context) -> None:
    text = run(context, "1", "", "", "b")
    assert "Name is required" in text
    assert "Set Up Teacher Profile" in text


def test_profile_error_does_not_overwrite_invalid_bytes(context) -> None:
    store, _, _, _ = context
    store.create("Teacher")
    store.profile_path.write_bytes(b"not-json")
    text = run(context, "1", "")
    assert "Teacher Profile Unavailable" in text
    assert store.profile_path.read_bytes() == b"not-json"


def _core_valid(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(nav_module, "get_active_school_year", lambda r: "2026-2027")
    monkeypatch.setattr(
        nav_module,
        "load_class_metadata_for_class",
        lambda r, c: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(nav_module, "load_class_roster", lambda r, c: object())
    monkeypatch.setattr(
        nav_module,
        "load_current_academic_work_registration",
        lambda r, w: SimpleNamespace(lifecycle="active"),
    )
    monkeypatch.setattr(
        "meridian.menu_teacher_settings.get_active_school_year",
        lambda r: "2026-2027",
    )


def test_explicit_save_and_resume_no_protected_scope(context, monkeypatch) -> None:
    _, prefs, root, session = context
    _core_valid(monkeypatch, root)
    original = ModuleWorkRef("scoreform", "class1", "assessment1")
    session.select_work(original)
    text = run(context, "5", "SAVE", "", "b")
    assert "Preference Saved" in text
    saved = prefs.load()
    assert saved.preferences.work == original
    session.clear()
    text = run(context, "6", "RESUME", "", "b")
    assert "Class Navigation Restored" in text
    assert session.active_work == original
    assert session.active_class_id == "class1"
    assert session.active_student_id is None
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None


def test_resume_requires_confirmation(context, monkeypatch) -> None:
    _, prefs, root, session = context
    _core_valid(monkeypatch, root)
    prefs.save_selection(root, school_year="2026-2027", class_id="class1")
    run(context, "6", "no", "", "b")
    assert session.active_class_id is None


def test_resume_rejects_stale_school_year(context, monkeypatch) -> None:
    _, prefs, root, session = context
    _core_valid(monkeypatch, root)
    prefs.save_selection(root, school_year="2026-2027", class_id="class1")
    monkeypatch.setattr(nav_module, "get_active_school_year", lambda r: "2027-2028")
    text = run(context, "6", "", "b")
    assert "School year is not active" in text
    assert session.active_class_id is None


def test_resume_does_not_override_active_session(context, monkeypatch) -> None:
    _, prefs, root, session = context
    _core_valid(monkeypatch, root)
    prefs.save_selection(root, school_year="2026-2027", class_id="class1")
    session.select_class("class2")
    text = run(context, "6", "", "b")
    assert "Class Already Selected" in text
    assert session.active_class_id == "class2"


def test_clear_preferences_does_not_change_profile_or_session(context) -> None:
    store, prefs, root, session = context
    store.create("Teacher")
    prefs.save_selection(root, school_year="2026-2027", class_id="class1")
    session.select_class("class1")
    run(context, "7", "CLEAR", "", "b")
    assert store.load() is not None
    assert session.active_class_id == "class1"
    assert prefs.load().preferences.class_id is None
    assert prefs.load().preferences.work is None


def test_unconfigured_school_year_prevents_preference_save(
    context, monkeypatch
) -> None:
    _, prefs, root, session = context
    session.select_class("class1")
    monkeypatch.setattr(
        "meridian.menu_teacher_settings.get_active_school_year", lambda r: None
    )
    text = run(context, "5", "", "b")
    assert "No Active School Year" in text
    assert prefs.load() is None


def test_save_requires_core_validation(context, monkeypatch) -> None:
    _, prefs, root, session = context
    session.select_class("class1")
    monkeypatch.setattr(
        "meridian.menu_teacher_settings.get_active_school_year",
        lambda r: "2026-2027",
    )
    monkeypatch.setattr(nav_module, "get_active_school_year", lambda r: "2027-2028")
    text = run(context, "5", "", "b")
    assert "Classroom Context Is Stale" in text
    assert prefs.load() is None


def test_main_menu_settings_routing_is_declared() -> None:
    source = Path("meridian/menu.py")
    if not source.exists():
        pytest.skip("Full Meridian checkout required for integration assertion")
    content = source.read_text(encoding="utf-8")
    assert "S. Teacher Settings" in content
    assert "run_teacher_settings_menu" in content
