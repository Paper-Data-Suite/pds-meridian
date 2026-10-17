"""Teacher-controlled local attribution profile; never academic authority.

This is a Meridian-owned compatibility layer until a released Core-wide
teacher-profile contract exists. No operation authorizes protected evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.workspace import get_workspace_config_path

SCHEMA_VERSION: Final = 1
_MAX_PROFILE_BYTES: Final = 4096
_PROFILE_FILENAME: Final = "teacher-profile-v1.json"
_LOCK_FILENAME: Final = ".teacher-profile-v1.lock"


class TeacherProfileError(Exception):
    """Base profile error; excludes canonical academic record operations."""


class TeacherProfileValidationError(TeacherProfileError):
    """Profile content is invalid or incompatible."""


class TeacherProfileStorageError(TeacherProfileError):
    """Local profile cannot be accessed safely."""


class TeacherProfileConflictError(TeacherProfileError):
    """Profile changed after the teacher reviewed it."""


class TeacherProfileNotConfiguredError(TeacherProfileError):
    """An explicit teacher profile has not yet been configured."""


def _display_name(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TeacherProfileValidationError("Teacher display name is required.")
    if len(value) > 160 or unicodedata.normalize("NFC", value) != value:
        raise TeacherProfileValidationError(
            "Teacher display name must be at most 160 normalized characters."
        )
    if any(unicodedata.category(ch).startswith("C") for ch in value):
        raise TeacherProfileValidationError(
            "Teacher display name contains a control or format character."
        )
    return value


def _actor_id(value: object) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise TeacherProfileValidationError(
            "Teacher actor ID must be a bounded Core-safe identifier."
        )
    try:
        return validate_identifier(value, "teacher actor ID")
    except IdentifierValidationError as error:
        raise TeacherProfileValidationError(
            "Teacher actor ID must be a Core-safe identifier."
        ) from error


def _utc_datetime(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("+00:00"):
        raise TeacherProfileValidationError(f"{field} must be a UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TeacherProfileValidationError(f"{field} is invalid.") from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise TeacherProfileValidationError(f"{field} must be UTC.")
    if parsed.isoformat() != value:
        raise TeacherProfileValidationError(f"{field} is not canonical.")
    return value


def _timestamp(clock: Callable[[], datetime]) -> str:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TeacherProfileValidationError("Profile clock must be timezone-aware.")
    return now.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class TeacherProfile:
    """Local self-declared identity; neither login nor evidence permission."""

    revision: int
    actor_id: str
    display_name: str
    created_at: str
    updated_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise TeacherProfileValidationError(
                "Unsupported teacher profile schema version."
            )
        if type(self.revision) is not int or not 1 <= self.revision <= 1_000_000:
            raise TeacherProfileValidationError("Invalid teacher profile revision.")
        _actor_id(self.actor_id)
        _display_name(self.display_name)
        created = _utc_datetime(self.created_at, "created_at")
        updated = _utc_datetime(self.updated_at, "updated_at")
        if datetime.fromisoformat(updated) < datetime.fromisoformat(created):
            raise TeacherProfileValidationError("Profile timestamps are reversed.")


@dataclass(frozen=True, slots=True)
class StoredTeacherProfile:
    """Profile plus exact bytes fingerprint for optimistic concurrency."""

    profile: TeacherProfile
    sha256: str


@dataclass(frozen=True, slots=True)
class TeacherIdentity:
    """Attribution values to pass into existing canonical services."""

    actor_id: str
    display_name: str
    source: Literal["saved", "temporary"]

    def __post_init__(self) -> None:
        _actor_id(self.actor_id)
        _display_name(self.display_name)
        if self.source not in ("saved", "temporary"):
            raise TeacherProfileValidationError("Unsupported identity source.")


def _serialize(profile: TeacherProfile) -> bytes:
    payload = {
        "schema_version": profile.schema_version,
        "revision": profile.revision,
        "actor_id": profile.actor_id,
        "display_name": profile.display_name,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    return (encoded + "\n").encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TeacherProfileValidationError("Duplicate profile JSON key.")
        result[key] = value
    return result


def _deserialize(content: bytes) -> TeacherProfile:
    if not 0 < len(content) <= _MAX_PROFILE_BYTES:
        raise TeacherProfileValidationError("Profile exceeds its bounded size.")
    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise TeacherProfileValidationError("Profile JSON is invalid.") from error
    fields = {
        "schema_version",
        "revision",
        "actor_id",
        "display_name",
        "created_at",
        "updated_at",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise TeacherProfileValidationError("Profile fields do not match schema v1.")
    return TeacherProfile(
        schema_version=value["schema_version"],
        revision=value["revision"],
        actor_id=value["actor_id"],
        display_name=value["display_name"],
        created_at=value["created_at"],
        updated_at=value["updated_at"],
    )


def _is_unsafe_link(path: Path) -> bool:
    """Check links and Windows reparse points without following the target."""
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(entry.st_mode):
        return True
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(entry, "st_file_attributes", 0) & reparse)


def _check_private_directory(path: Path) -> None:
    if _is_unsafe_link(path) or not path.is_dir():
        raise TeacherProfileStorageError("Profile directory is not safe.")
    try:
        mode = path.stat().st_mode
    except OSError as error:
        raise TeacherProfileStorageError("Cannot inspect profile directory.") from error
    if os.name != "nt" and stat.S_IMODE(mode) & 0o077:
        raise TeacherProfileStorageError("Profile directory is not private.")


def _read_safe_file(path: Path) -> bytes | None:
    if _is_unsafe_link(path):
        raise TeacherProfileStorageError("Profile file is a link or reparse point.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise TeacherProfileStorageError(
            "Cannot open teacher profile safely."
        ) from error
    try:
        info = os.fstat(fd)
        try:
            observed = path.lstat()
        except OSError as error:
            raise TeacherProfileStorageError(
                "Profile path changed during read."
            ) from error
        if _is_unsafe_link(path) or (
            info.st_dev != observed.st_dev or info.st_ino != observed.st_ino
        ):
            raise TeacherProfileStorageError("Profile path changed during read.")
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TeacherProfileStorageError("Teacher profile is not a regular file.")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise TeacherProfileStorageError("Teacher profile file is not private.")
        content = bytearray()
        while len(content) <= _MAX_PROFILE_BYTES:
            piece = os.read(fd, _MAX_PROFILE_BYTES + 1 - len(content))
            if not piece:
                return bytes(content)
            content.extend(piece)
        raise TeacherProfileValidationError("Profile exceeds its bounded size.")
    finally:
        os.close(fd)


def _flush_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _posix_flock(fd: int, *, unlock: bool) -> None:
    """Use actual POSIX flock, typed without relying on Windows fcntl stubs."""
    import fcntl

    flock = cast(Callable[[int, int], None], getattr(fcntl, "flock"))
    operation = cast(int, getattr(fcntl, "LOCK_UN" if unlock else "LOCK_EX"))
    flock(fd, operation)


class TeacherProfileStore:
    """Guarded user-local profile under Core's per-user config convention."""

    def __init__(
        self,
        *,
        config_directory: Path | None = None,
        clock: Callable[[], datetime] | None = None,
        actor_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config_directory = config_directory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._actor_id_factory = actor_id_factory or (
            lambda: "teacher-" + uuid.uuid4().hex
        )

    @property
    def directory(self) -> Path:
        base = (
            get_workspace_config_path().parent
            if self._config_directory is None
            else self._config_directory
        )
        if not isinstance(base, Path) or not base.is_absolute():
            raise TeacherProfileStorageError("Profile config root must be absolute.")
        return base / "meridian"

    @property
    def profile_path(self) -> Path:
        return self.directory / _PROFILE_FILENAME

    def _guard_directory(self, *, create: bool) -> bool:
        parent = self.directory.parent
        if _is_unsafe_link(parent):
            raise TeacherProfileStorageError("Profile config root is a link.")
        if not parent.exists():
            if not create:
                return False
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise TeacherProfileStorageError(
                    "Cannot create local profile configuration root."
                ) from error
        if not parent.is_dir() or _is_unsafe_link(parent):
            raise TeacherProfileStorageError("Invalid profile configuration root.")
        directory = self.directory
        if not directory.exists() and not _is_unsafe_link(directory):
            if not create:
                return False
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as error:
                raise TeacherProfileStorageError(
                    "Cannot create profile directory."
                ) from error
        _check_private_directory(directory)
        return True

    def load(self) -> StoredTeacherProfile | None:
        """Read-only: never creates a profile, directory, or academic state."""
        try:
            if not self._guard_directory(create=False):
                return None
            content = _read_safe_file(self.profile_path)
        except OSError as error:
            raise TeacherProfileStorageError("Could not load local profile.") from error
        if content is None:
            return None
        return StoredTeacherProfile(
            profile=_deserialize(content), sha256=hashlib.sha256(content).hexdigest()
        )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Interprocess exclusive lock around CAS and atomic replacement."""
        self._guard_directory(create=True)
        path = self.directory / _LOCK_FILENAME
        if _is_unsafe_link(path):
            raise TeacherProfileStorageError("Profile lock path is unsafe.")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as error:
            raise TeacherProfileStorageError("Cannot open profile lock.") from error
        try:
            info = os.fstat(fd)
            observed = path.lstat()
            if _is_unsafe_link(path) or (
                info.st_dev != observed.st_dev or info.st_ino != observed.st_ino
            ):
                raise TeacherProfileStorageError("Profile lock changed during open.")
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077)
            ):
                raise TeacherProfileStorageError(
                    "Profile lock is not private or regular."
                )
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                if info.st_size == 0:
                    os.write(fd, b"0")
                    os.fsync(fd)
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                except OSError as error:
                    raise TeacherProfileStorageError(
                        "Cannot lock local profile."
                    ) from error
            else:
                _posix_flock(fd, unlock=False)
            try:
                # Revalidate after locking to catch file/directory replacement.
                self._guard_directory(create=False)
                yield
            finally:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    _posix_flock(fd, unlock=True)
        finally:
            os.close(fd)

    def _write(self, profile: TeacherProfile) -> StoredTeacherProfile:
        content = _serialize(profile)
        if len(content) > _MAX_PROFILE_BYTES:
            raise TeacherProfileValidationError("Profile exceeds its bounded size.")
        path = self.profile_path
        if _is_unsafe_link(path):
            raise TeacherProfileStorageError("Refusing profile write through a link.")
        temp_path: Path | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=".teacher-profile-", suffix=".tmp", dir=self.directory
            )
            temp_path = Path(name)
            with os.fdopen(fd, "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, path)
            temp_path = None
            _flush_directory(self.directory)
        except OSError as error:
            raise TeacherProfileStorageError(
                "Teacher profile could not be saved."
            ) from error
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return StoredTeacherProfile(profile, hashlib.sha256(content).hexdigest())

    def _check_expected(self, expected: StoredTeacherProfile) -> TeacherProfile:
        current = self.load()
        if current is None or (
            current.sha256 != expected.sha256
            or current.profile.revision != expected.profile.revision
        ):
            raise TeacherProfileConflictError(
                "Teacher profile changed. Refresh before editing."
            )
        return current.profile

    def create(
        self, display_name: str, *, actor_id: str | None = None
    ) -> StoredTeacherProfile:
        """Explicit first-use setup; actor ID can be generated from this action."""
        name = _display_name(display_name)
        actor = _actor_id(
            actor_id if actor_id is not None else self._actor_id_factory()
        )
        with self._locked():
            if self.load() is not None:
                raise TeacherProfileConflictError(
                    "Teacher profile already exists; reload instead."
                )
            now = _timestamp(self._clock)
            return self._write(TeacherProfile(1, actor, name, now, now))

    def update_display_name(
        self, expected: StoredTeacherProfile, display_name: str
    ) -> StoredTeacherProfile:
        """Preserve stable actor identity while changing only its display name."""
        name = _display_name(display_name)
        with self._locked():
            previous = self._check_expected(expected)
            if name == previous.display_name:
                return expected
            return self._write(
                TeacherProfile(
                    previous.revision + 1,
                    previous.actor_id,
                    name,
                    previous.created_at,
                    _timestamp(self._clock),
                )
            )

    def replace_identity(
        self,
        expected: StoredTeacherProfile,
        *,
        display_name: str,
        actor_id: str | None = None,
        confirmed: bool = False,
    ) -> StoredTeacherProfile:
        """Deliberate future-only actor change; no historical record mutation."""
        if not confirmed:
            raise TeacherProfileValidationError(
                "Changing teacher identity requires explicit confirmation."
            )
        name = _display_name(display_name)
        new_actor = _actor_id(
            actor_id if actor_id is not None else self._actor_id_factory()
        )
        with self._locked():
            previous = self._check_expected(expected)
            if previous.actor_id == new_actor:
                raise TeacherProfileValidationError(
                    "New identity must have a different actor ID."
                )
            return self._write(
                TeacherProfile(
                    previous.revision + 1,
                    new_actor,
                    name,
                    previous.created_at,
                    _timestamp(self._clock),
                )
            )

    def reset(self, expected: StoredTeacherProfile, *, confirmed: bool = False) -> None:
        """Clear local profile only; never delete academic records or credentials."""
        if not confirmed:
            raise TeacherProfileValidationError(
                "Resetting the teacher profile requires confirmation."
            )
        with self._locked():
            self._check_expected(expected)
            try:
                self.profile_path.unlink()
                _flush_directory(self.directory)
            except OSError as error:
                raise TeacherProfileStorageError("Profile reset failed.") from error


class TeacherIdentityProvider:
    """Injectable teacher attribution values for future menu integration."""

    def __init__(self, store: TeacherProfileStore) -> None:
        self._store = store

    def resolve(self) -> TeacherIdentity:
        current = self._store.load()
        if current is None:
            raise TeacherProfileNotConfiguredError(
                "Set up teacher identity in Settings before recording a decision."
            )
        return TeacherIdentity(
            current.profile.actor_id, current.profile.display_name, "saved"
        )

    @staticmethod
    def temporary_override(*, actor_id: str, display_name: str) -> TeacherIdentity:
        """Explicit one-action override; does not update the saved profile."""
        return TeacherIdentity(actor_id, display_name, "temporary")


__all__ = [
    "SCHEMA_VERSION",
    "StoredTeacherProfile",
    "TeacherIdentity",
    "TeacherIdentityProvider",
    "TeacherProfile",
    "TeacherProfileConflictError",
    "TeacherProfileError",
    "TeacherProfileNotConfiguredError",
    "TeacherProfileStorageError",
    "TeacherProfileStore",
    "TeacherProfileValidationError",
]
