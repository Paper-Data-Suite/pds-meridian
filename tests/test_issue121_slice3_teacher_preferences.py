"""Issue #121 Slice 3: bounded durable navigation and safe resume."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.teacher_preferences import (
    TeacherNavigationPreferences,
    TeacherNavigationPreferencesStore,
    TeacherPreferencesConflictError,
    TeacherPreferencesStorageError,
    TeacherPreferencesValidationError,
    apply_verified_navigation,
    validate_resume_hint,
)
from meridian.teacher_profile import TeacherProfileStore
from meridian.teacher_session import TeacherSessionContext


@pytest.fixture
def env(tmp_path: Path) -> tuple[TeacherNavigationPreferencesStore, Path]:
    config = tmp_path / "private"
    config.mkdir(mode=0o700)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return TeacherNavigationPreferencesStore(
        TeacherProfileStore(config_directory=config)
    ), workspace


def work(class_id: str = "class_A") -> ModuleWorkRef:
    return ModuleWorkRef(module_id="scoreform", class_id=class_id, work_id="work1")


def save(store: TeacherNavigationPreferencesStore, root: Path, **kw: object):
    return store.save_selection(
        root,
        school_year="2026-2027",
        class_id="class_A",
        **kw,
    )


def test_read_only_load_does_not_create_files(env):
    store, root = env
    assert store.load() is None
    assert store.for_workspace(root) is None
    assert not store.path.exists()
    assert not store.path.parent.exists()


def test_explicit_save_and_reload(env):
    store, root = env
    written = save(store, root, work=work())
    assert store.load() == written
    assert store.for_workspace(root) == written
    assert written.preferences.revision == 1
    assert written.preferences.work == work()


def test_saved_context_has_no_student_or_evidence_bytes(env):
    store, root = env
    save(store, root, work=work())
    content = store.path.read_text()
    assert set(json.loads(content)) == {
        "schema_version",
        "revision",
        "workspace_fingerprint",
        "school_year",
        "class_id",
        "work",
    }
    assert str(root) not in content
    for forbidden in (
        "student_id",
        "publication_id",
        "scan",
        "grade_item",
        "authorization",
    ):
        assert forbidden not in content


def test_cross_workspace_hint_is_not_reused(env):
    store, root = env
    old = save(store, root)
    other = root.parent / "other"
    other.mkdir()
    assert store.for_workspace(other) is None
    assert not validate_resume_hint(other, old).resumable
    assert store.load() == old


def test_cross_workspace_explicit_replace_requires_cas(env):
    store, root = env
    previous = save(store, root)
    other = root.parent / "other"
    other.mkdir()
    with pytest.raises(TeacherPreferencesConflictError):
        save(store, other)
    replacement = save(store, other, expected=previous)
    assert replacement.preferences.revision == 2
    assert store.for_workspace(other) == replacement
    assert store.for_workspace(root) is None


def test_stale_writer_cannot_clobber_new_selection(env):
    store, root = env
    first = save(store, root)
    newer = store.save_selection(
        root, school_year="2026-2027", class_id=None, expected=first
    )
    with pytest.raises(TeacherPreferencesConflictError):
        save(store, root, expected=first)
    assert store.load() == newer


def test_reset_class_drops_work_by_model_requirement(env):
    store, root = env
    first = save(store, root, work=work())
    updated = store.save_selection(
        root, school_year="2026-2027", class_id=None, expected=first
    )
    assert updated.preferences.class_id is None
    assert updated.preferences.work is None


@pytest.mark.parametrize("value", ["2026-2026", "2026-2028", "foo", "2026-2027 ", 23])
def test_invalid_school_year_fail_closed(value):
    with pytest.raises(TeacherPreferencesValidationError):
        TeacherNavigationPreferences(1, "a" * 64, school_year=value)


def test_class_requires_year():
    with pytest.raises(TeacherPreferencesValidationError):
        TeacherNavigationPreferences(1, "a" * 64, class_id="class_A")


def test_work_must_belong_to_selected_class():
    with pytest.raises(TeacherPreferencesValidationError):
        TeacherNavigationPreferences(
            1, "a" * 64, school_year="2026-2027", class_id="class_A", work=work("B")
        )


@pytest.mark.parametrize("revision", [True, 0, -1, 1000001, "1"])
def test_invalid_revision(revision):
    with pytest.raises(TeacherPreferencesValidationError):
        TeacherNavigationPreferences(revision, "a" * 64)


def test_invalid_json_and_duplicate_keys(env):
    store, root = env
    save(store, root)
    original = store.path.read_bytes()
    store.path.write_bytes(b'{"revision":1,"revision":2}')
    with pytest.raises(TeacherPreferencesValidationError):
        store.load()
    store.path.write_bytes(original)
    assert store.load() is not None


def test_json_unknown_field_rejected(env):
    store, root = env
    save(store, root)
    data = json.loads(store.path.read_text())
    data["student_id"] = "private"
    store.path.write_text(json.dumps(data))
    with pytest.raises(TeacherPreferencesValidationError):
        store.load()


def test_oversize_json_rejected(env):
    store, root = env
    save(store, root)
    store.path.write_bytes(b"{" + b" " * 4100 + b"}")
    with pytest.raises(TeacherPreferencesValidationError):
        store.load()


def test_file_symlink_refused_where_supported(env):
    store, root = env
    save(store, root)
    target = root / "target"
    target.write_text("keep")
    store.path.unlink()
    try:
        store.path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this platform")
    with pytest.raises(TeacherPreferencesStorageError):
        store.load()
    with pytest.raises(TeacherPreferencesStorageError):
        store.save_selection(root, school_year=None, class_id=None)
    assert target.read_text() == "keep"


def test_read_only_resume_empty(env):
    store, root = env
    candidate = validate_resume_hint(root, store.load())
    assert not candidate.resumable
    assert candidate.reason == "No saved context."
    assert not store.path.exists()


def test_resume_requires_matching_active_school_year(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root)
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2025-2026")
    candidate = validate_resume_hint(root, written)
    assert not candidate.resumable
    assert candidate.school_year is None


def test_resume_missing_class_fails_closed(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root)
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")

    def no_roster(_root, _class_id):
        raise mod.RosterError("not found")

    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", no_roster)
    candidate = validate_resume_hint(root, written)
    assert candidate.class_id is None
    assert candidate.reason == "Class is unavailable."


def test_resume_valid_class_only(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root)
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", lambda _root, _class_id: object())
    candidate = validate_resume_hint(root, written)
    assert candidate.resumable
    assert candidate.class_id == "class_A"
    assert candidate.work is None


def test_resume_stale_work_never_restores_it(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root, work=work())
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", lambda _root, _class_id: object())
    monkeypatch.setattr(
        mod, "load_current_academic_work_registration", lambda _root, _work: None
    )
    candidate = validate_resume_hint(root, written)
    assert candidate.class_id == "class_A"
    assert candidate.work is None


def test_resume_current_work_only_with_canonical_registration(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root, work=work())
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", lambda _root, _class_id: object())
    monkeypatch.setattr(
        mod,
        "load_current_academic_work_registration",
        lambda _root, _work: SimpleNamespace(lifecycle="active"),
    )
    candidate = validate_resume_hint(root, written)
    assert candidate.resumable
    assert candidate.work == work()


def test_resume_closed_work_falls_back_to_class(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    written = save(store, root, work=work())
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", lambda _root, _class_id: object())
    monkeypatch.setattr(
        mod,
        "load_current_academic_work_registration",
        lambda _root, _work: SimpleNamespace(lifecycle="closed"),
    )
    candidate = validate_resume_hint(root, written)
    assert candidate.work is None


def test_profile_is_not_created_by_navigation_save(env):
    store, root = env
    save(store, root)
    assert store._profile_store.load() is None


def test_same_preferences_are_not_implicitly_authorization(env):
    store, root = env
    saved = save(store, root, work=work())
    assert not hasattr(saved.preferences, "authorizer")
    assert not hasattr(saved.preferences, "eligible")
    assert not hasattr(saved.preferences, "student_id")


def test_opt_in_application_sets_navigation_without_academic_selection(
    env, monkeypatch
):
    import meridian.teacher_preferences as mod

    store, root = env
    saved = save(store, root, work=work())
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2026-2027"),
    )
    monkeypatch.setattr(mod, "load_class_roster", lambda _root, _class_id: object())
    monkeypatch.setattr(
        mod,
        "load_current_academic_work_registration",
        lambda _root, _work: SimpleNamespace(lifecycle="active"),
    )
    candidate = validate_resume_hint(root, saved)
    session = TeacherSessionContext()
    assert apply_verified_navigation(session, candidate)
    assert session.active_class_id == "class_A"
    assert session.active_work == work()
    assert session.active_publication_id is None
    assert session.active_student_id is None
    assert session.active_grade_item_id is None
    assert not apply_verified_navigation(session, candidate)


def test_opt_in_application_does_not_restore_unverified_class(env):
    store, root = env
    first = save(store, root)
    second = root.parent / "other"
    second.mkdir()
    candidate = validate_resume_hint(second, first)
    session = TeacherSessionContext()
    assert not apply_verified_navigation(session, candidate)
    assert session.active_class_id is None


def test_resume_wrong_class_school_year_fails_closed(env, monkeypatch):
    import meridian.teacher_preferences as mod

    store, root = env
    saved = save(store, root)
    monkeypatch.setattr(mod, "get_active_school_year", lambda _root: "2026-2027")
    monkeypatch.setattr(
        mod,
        "load_class_metadata_for_class",
        lambda _root, _class_id: SimpleNamespace(school_year="2025-2026"),
    )
    candidate = validate_resume_hint(root, saved)
    assert candidate.class_id is None
    assert candidate.reason == "Class is from another school year."
