"""Issue #121 Slice 2 — independent profile/provider/storage acceptance."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meridian.teacher_profile import (
    TeacherIdentityProvider,
    TeacherProfileConflictError,
    TeacherProfileNotConfiguredError,
    TeacherProfileStorageError,
    TeacherProfileStore,
    TeacherProfileValidationError,
)

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> TeacherProfileStore:
    return TeacherProfileStore(
        config_directory=tmp_path / "configuration",
        clock=lambda: NOW,
        actor_id_factory=lambda: "teacher-generated-123",
    )


def test_missing_profile_is_read_only_and_never_creates_config(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.load() is None
    assert not store.directory.exists()
    with pytest.raises(TeacherProfileNotConfiguredError, match="Settings"):
        TeacherIdentityProvider(store).resolve()
    assert not (tmp_path / "configuration").exists()


def test_create_reload_persist_identity_outside_workspace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recorded = store.create("Alex Teacher")
    assert recorded.profile.actor_id == "teacher-generated-123"
    assert recorded.profile.display_name == "Alex Teacher"
    assert recorded.profile.revision == 1
    assert recorded.profile.created_at == NOW.isoformat()
    assert recorded.profile.updated_at == NOW.isoformat()
    assert recorded.sha256 == store.load().sha256  # type: ignore[union-attr]
    restored = _store(tmp_path).load()
    assert restored == recorded
    provider = TeacherIdentityProvider(_store(tmp_path))
    assert provider.resolve().display_name == "Alex Teacher"
    assert provider.resolve().actor_id == "teacher-generated-123"
    assert provider.resolve().source == "saved"
    assert "Alex Teacher" in store.profile_path.read_text(encoding="utf-8")
    assert not (tmp_path / "workspace").exists()
    assert not list(store.directory.glob("*.tmp"))
    if os.name != "nt":
        assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.profile_path.stat().st_mode) == 0o600


def test_duplicate_creation_does_not_replace_original(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.create("First Teacher")
    with pytest.raises(TeacherProfileConflictError, match="already exists"):
        _store(tmp_path).create("Second Teacher")
    assert store.load() == original


def test_display_name_edit_preserves_actor_id_and_increments_revision(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    original = store.create("Alex Teacher")
    changed = store.update_display_name(original, "Alex Morgan")
    assert changed.profile.actor_id == original.profile.actor_id
    assert changed.profile.created_at == original.profile.created_at
    assert changed.profile.display_name == "Alex Morgan"
    assert changed.profile.revision == 2
    assert changed.sha256 != original.sha256
    assert store.update_display_name(changed, "Alex Morgan") == changed
    assert _store(tmp_path).load() == changed


def test_stale_updates_and_resets_block_without_clobber(tmp_path: Path) -> None:
    store = _store(tmp_path)
    previous = store.create("Original")
    changed = _store(tmp_path).update_display_name(previous, "Updated")
    with pytest.raises(TeacherProfileConflictError, match="Refresh"):
        store.update_display_name(previous, "Stale")
    with pytest.raises(TeacherProfileConflictError):
        store.reset(previous, confirmed=True)
    assert store.load() == changed


def test_identity_change_requires_confirmation_and_preserves_history(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    old = store.create("Alex Teacher")
    with pytest.raises(TeacherProfileValidationError, match="confirmation"):
        store.replace_identity(old, display_name="A. Teacher", actor_id="teacher-new")
    assert store.load() == old
    new = store.replace_identity(
        old, display_name="A. Teacher", actor_id="teacher-new", confirmed=True
    )
    assert new.profile.actor_id == "teacher-new"
    assert new.profile.revision == 2
    assert old.profile.actor_id == "teacher-generated-123"
    assert new.profile.created_at == old.profile.created_at
    with pytest.raises(TeacherProfileValidationError, match="different actor ID"):
        store.replace_identity(
            new, display_name="A. Teacher", actor_id="teacher-new", confirmed=True
        )


def test_reset_is_explicit_and_recreates_new_identity(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.create("Teacher One")
    with pytest.raises(TeacherProfileValidationError, match="confirmation"):
        store.reset(original)
    assert store.load() == original
    store.reset(original, confirmed=True)
    assert store.load() is None
    again = store.create("Teacher Two", actor_id="teacher-two")
    assert again.profile.actor_id == "teacher-two"
    assert original.profile.actor_id != again.profile.actor_id


def test_temporary_override_never_changes_profile(tmp_path: Path) -> None:
    store = _store(tmp_path)
    current = store.create("Saved Teacher")
    alternate = TeacherIdentityProvider.temporary_override(
        actor_id="teacher-substitute", display_name="Substitute Teacher"
    )
    assert alternate.source == "temporary"
    assert alternate.actor_id == "teacher-substitute"
    assert TeacherIdentityProvider(store).resolve().display_name == "Saved Teacher"
    assert store.load() == current


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
        " Leading",
        "Trailing ",
        "Two\nLines",
        "Zero\u200bWidth",
        "e\u0301",
        "a" * 161,
    ],
)
def test_unsafe_names_are_rejected_without_creating_files(
    tmp_path: Path, name: str
) -> None:
    store = _store(tmp_path)
    with pytest.raises(TeacherProfileValidationError):
        store.create(name)
    assert store.load() is None


@pytest.mark.parametrize(
    "actor",
    [
        "",
        " bad",
        "bad/actor",
        "bad\\actor",
        "bad\nactor",
        "bad:actor",
        "bad.actor",
        "a" * 129,
    ],
)
def test_invalid_actor_ids_are_rejected(tmp_path: Path, actor: str) -> None:
    with pytest.raises(TeacherProfileValidationError):
        _store(tmp_path).create("Teacher", actor_id=actor)


@pytest.mark.parametrize(
    "damage",
    [
        b"{not JSON",
        b"{}",
        b"[]",
        b"a" * 5000,
        b'{"schema_version":1,"schema_version":1}',
    ],
)
def test_corrupt_profiles_fail_without_reset_or_overwrite(
    tmp_path: Path, damage: bytes
) -> None:
    store = _store(tmp_path)
    store.create("Teacher")
    store.profile_path.write_bytes(damage)
    with pytest.raises(TeacherProfileValidationError):
        store.load()
    with pytest.raises(TeacherProfileValidationError):
        store.create("New teacher")
    assert store.profile_path.read_bytes() == damage


def test_unsupported_version_is_not_silently_migrated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create("Teacher")
    content = json.loads(store.profile_path.read_text(encoding="utf-8"))
    content["schema_version"] = 2
    store.profile_path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(TeacherProfileValidationError, match="Unsupported"):
        store.load()


def test_profile_file_symlink_and_directory_symlink_are_refused(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.create("Teacher")
    secret = tmp_path / "outside.json"
    secret.write_text("important", encoding="utf-8")
    store.profile_path.unlink()
    try:
        store.profile_path.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this runner")
    with pytest.raises(TeacherProfileStorageError):
        store.load()
    with pytest.raises(TeacherProfileStorageError):
        store.create("Teacher Two")
    assert secret.read_text(encoding="utf-8") == "important"
    store.profile_path.unlink()
    store.directory.rename(store.directory.with_name("safe_backup"))
    try:
        store.directory.symlink_to(
            store.directory.with_name("safe_backup"), target_is_directory=True
        )
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable on this runner")
    with pytest.raises(TeacherProfileStorageError):
        store.load()


def test_profile_named_pipe_is_rejected_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("Named pipes unavailable on this platform")
    store = _store(tmp_path)
    store.create("Teacher")
    store.profile_path.unlink()
    os.mkfifo(store.profile_path)
    with pytest.raises(TeacherProfileStorageError, match="regular"):
        store.load()


def test_insecure_directory_mode_is_refused(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX directory permissions")
    store = _store(tmp_path)
    store.create("Teacher")
    store.directory.chmod(0o777)
    with pytest.raises(TeacherProfileStorageError, match="private"):
        store.load()
    store.directory.chmod(0o700)


def test_timestamp_validation_and_backward_clock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initial = store.create("Teacher")
    backward = TeacherProfileStore(
        config_directory=tmp_path / "configuration",
        clock=lambda: NOW - timedelta(days=1),
    )
    with pytest.raises(TeacherProfileValidationError, match="timestamps"):
        backward.update_display_name(initial, "New Name")
    assert store.load() == initial


def test_profile_disk_is_not_grading_authority_or_read_authorization(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    current = store.create("Teacher")
    content = store.profile_path.read_text(encoding="utf-8")
    assert "student_id" not in content
    assert "publication_id" not in content
    assert "authorization" not in content
    assert "workspace_root" not in content
    assert current.profile.actor_id in content


def test_lock_cannot_be_replaced_with_symlink(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create("Teacher")
    lock = store.directory / ".teacher-profile-v1.lock"
    lock.unlink()
    outside = tmp_path / "untouched"
    outside.write_text("safe", encoding="utf-8")
    try:
        lock.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this runner")
    with pytest.raises(TeacherProfileStorageError):
        store.update_display_name(store.load(), "Changed")  # type: ignore[arg-type]
    assert outside.read_text(encoding="utf-8") == "safe"


def test_competing_writers_are_serialized(tmp_path: Path) -> None:
    """The same reviewed revision cannot be applied twice by two writers."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    initial = _store(tmp_path).create("Initial")
    barrier = Barrier(2)

    def update(name: str) -> str:
        barrier.wait(timeout=5)
        try:
            _store(tmp_path).update_display_name(initial, name)
        except TeacherProfileConflictError:
            return "conflict"
        return "updated"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, name) for name in ("One", "Two")]
        outcomes = [future.result(timeout=10) for future in futures]

    assert sorted(outcomes) == ["conflict", "updated"]
    assert _store(tmp_path).load().profile.revision == 2  # type: ignore[union-attr]


def test_default_path_reuses_core_location_without_modifying_core_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "core-config" / "config.json"
    config.parent.mkdir()
    content = '{"workspace_root":"important-existing-workspace"}\n'
    config.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        "meridian.teacher_profile.get_workspace_config_path", lambda: config
    )
    store = TeacherProfileStore(clock=lambda: NOW)
    created = store.create("Teacher", actor_id="teacher-config-test")
    assert created.profile.display_name == "Teacher"
    assert store.profile_path.parent == config.parent / "meridian"
    assert config.read_text(encoding="utf-8") == content


def test_hardlinked_profile_and_lock_are_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create("Teacher")
    outside = tmp_path / "out.json"
    outside.write_bytes(store.profile_path.read_bytes())
    store.profile_path.unlink()
    try:
        os.link(outside, store.profile_path)
    except OSError:
        pytest.skip("Hardlinks unavailable on this runner")
    with pytest.raises(TeacherProfileStorageError, match="regular"):
        store.load()
    store.profile_path.unlink()
    store.create("Restored", actor_id="restored")
    lock = store.directory / ".teacher-profile-v1.lock"
    lock.unlink()
    os.link(outside, lock)
    with pytest.raises(TeacherProfileStorageError, match="private or regular"):
        store.update_display_name(store.load(), "Blocked")  # type: ignore[arg-type]
    assert outside.read_bytes()
