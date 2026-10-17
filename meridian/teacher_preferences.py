"""Issue #121: durable, workspace-bound navigation *hints*, never authority.

No protected producer record is read here. A verified resume candidate may be
applied to transient UI navigation, never used as a canonical grading decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    load_current_academic_work_registration,
)
from pds_core.class_metadata import (
    ClassMetadataError,
    load_class_metadata_for_class,
)
from pds_core.classes import load_class_roster
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.rosters import RosterError
from pds_core.routing_models import ModuleWorkRef
from pds_core.school_years import (
    SchoolYearStateError,
    SchoolYearValidationError,
    get_active_school_year,
    validate_school_year,
)

from meridian.teacher_profile import (
    TeacherProfileStorageError,
    TeacherProfileStore,
    TeacherProfileValidationError,
    _flush_directory,
    _is_unsafe_link,
    _read_safe_file,
    _reject_duplicate_keys,
)
from meridian.teacher_session import TeacherSessionContext

PREFERENCES_SCHEMA_VERSION: Final = 1
_PREFERENCES_FILENAME: Final = "teacher-preferences-v1.json"
_MAX_BYTES: Final = 4096
_HEX64: Final = re.compile(r"^[a-f0-9]{64}$")


class TeacherPreferencesError(Exception):
    """Teacher-local preferences cannot be safely interpreted."""


class TeacherPreferencesValidationError(TeacherPreferencesError):
    """Invalid, corrupt, or incompatible convenience settings."""


class TeacherPreferencesStorageError(TeacherPreferencesError):
    """Preferences cannot be accessed securely."""


class TeacherPreferencesConflictError(TeacherPreferencesError):
    """Another session updated preferences since the caller observed them."""


def _identifier(value: object, field: str) -> str:
    try:
        if not isinstance(value, str):
            raise TeacherPreferencesValidationError(f"{field} must be a string.")
        return validate_identifier(value, field)
    except IdentifierValidationError as error:
        raise TeacherPreferencesValidationError(f"{field} is invalid.") from error


def _school_year(value: object) -> str:
    try:
        validated = validate_school_year(value)
        if validated != value:
            raise TeacherPreferencesValidationError("School year is not canonical.")
        return validated
    except (SchoolYearValidationError, TypeError) as error:
        raise TeacherPreferencesValidationError("Invalid school year.") from error


def _fingerprint(root: str | Path) -> str:
    """Bind hints to the exact local workspace without storing its path."""
    try:
        path = Path(root)
        if not path.is_absolute() or not path.is_dir():
            raise TeacherPreferencesValidationError(
                "Select an existing workspace before saving preferences."
            )
        real = path.resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as error:
        raise TeacherPreferencesValidationError(
            "Workspace is not available."
        ) from error
    return hashlib.sha256(os.path.normcase(str(real)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TeacherNavigationPreferences:
    """Explicitly selected school/year/class/work hints; no student context."""

    revision: int
    workspace_fingerprint: str
    school_year: str | None = None
    class_id: str | None = None
    work: ModuleWorkRef | None = None
    schema_version: int = PREFERENCES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise TeacherPreferencesValidationError("Unsupported preferences schema.")
        if type(self.revision) is not int or not 1 <= self.revision <= 1_000_000:
            raise TeacherPreferencesValidationError("Invalid preferences revision.")
        if not isinstance(self.workspace_fingerprint, str) or not _HEX64.fullmatch(
            self.workspace_fingerprint
        ):
            raise TeacherPreferencesValidationError("Invalid workspace fingerprint.")
        if self.school_year is not None:
            _school_year(self.school_year)
        if self.class_id is not None:
            _identifier(self.class_id, "class_id")
            if self.school_year is None:
                raise TeacherPreferencesValidationError(
                    "A class preference requires a school year."
                )
        if self.work is not None:
            if not isinstance(self.work, ModuleWorkRef):
                raise TeacherPreferencesValidationError("Invalid work reference.")
            if self.class_id is None or self.work.class_id != self.class_id:
                raise TeacherPreferencesValidationError(
                    "Work preference must belong to the selected class."
                )


@dataclass(frozen=True, slots=True)
class StoredTeacherNavigationPreferences:
    preferences: TeacherNavigationPreferences
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidatedResumeCandidate:
    """Read-only safe navigation suggestion from current Core state."""

    school_year: str | None
    class_id: str | None
    work: ModuleWorkRef | None
    reason: str

    @property
    def resumable(self) -> bool:
        return self.class_id is not None


def _serialize(value: TeacherNavigationPreferences) -> bytes:
    work = value.work
    content = {
        "schema_version": value.schema_version,
        "revision": value.revision,
        "workspace_fingerprint": value.workspace_fingerprint,
        "school_year": value.school_year,
        "class_id": value.class_id,
        "work": None
        if work is None
        else {
            "module_id": work.module_id,
            "class_id": work.class_id,
            "work_id": work.work_id,
        },
    }
    serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2)
    return (serialized + "\n").encode("utf-8")


def _deserialize(content: bytes) -> TeacherNavigationPreferences:
    if not 0 < len(content) <= _MAX_BYTES:
        raise TeacherPreferencesValidationError("Preferences exceed size limit.")
    try:
        data = json.loads(
            content.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (
        ValueError,
        UnicodeDecodeError,
        TypeError,
        TeacherProfileValidationError,
    ) as error:
        raise TeacherPreferencesValidationError(
            "Preferences JSON is invalid."
        ) from error
    expected = {
        "schema_version",
        "revision",
        "workspace_fingerprint",
        "school_year",
        "class_id",
        "work",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise TeacherPreferencesValidationError("Unexpected preferences fields.")
    work_data = data["work"]
    work: ModuleWorkRef | None = None
    if work_data is not None:
        if not isinstance(work_data, dict) or set(work_data) != {
            "module_id",
            "class_id",
            "work_id",
        }:
            raise TeacherPreferencesValidationError("Invalid work reference fields.")
        try:
            work = ModuleWorkRef(
                module_id=_identifier(work_data["module_id"], "module_id"),
                class_id=_identifier(work_data["class_id"], "class_id"),
                work_id=_identifier(work_data["work_id"], "work_id"),
            )
        except ValueError as error:
            raise TeacherPreferencesValidationError(
                "Invalid work reference."
            ) from error
    return TeacherNavigationPreferences(
        schema_version=data["schema_version"],
        revision=data["revision"],
        workspace_fingerprint=data["workspace_fingerprint"],
        school_year=data["school_year"],
        class_id=data["class_id"],
        work=work,
    )


class TeacherNavigationPreferencesStore:
    """One guarded per-user settings file using Slice 2's shared lock.

    A saved hint is workspace-specific. Neither reading it nor resuming a hint
    writes academic state or opens a protected producer publication.
    """

    def __init__(self, profile_store: TeacherProfileStore | None = None) -> None:
        self._profile_store = profile_store or TeacherProfileStore()

    @property
    def path(self) -> Path:
        return self._profile_store.directory / _PREFERENCES_FILENAME

    def load(self) -> StoredTeacherNavigationPreferences | None:
        try:
            if not self._profile_store._guard_directory(create=False):
                return None
            content = _read_safe_file(self.path)
        except TeacherProfileValidationError as error:
            raise TeacherPreferencesValidationError(
                "Preferences exceed size limit."
            ) from error
        except (OSError, TeacherProfileStorageError) as error:
            raise TeacherPreferencesStorageError(
                "Cannot read local preferences safely."
            ) from error
        if content is None:
            return None
        try:
            prefs = _deserialize(content)
        except (TeacherPreferencesValidationError, ValueError) as error:
            raise TeacherPreferencesValidationError(
                "Local navigation preferences are corrupt or incompatible."
            ) from error
        return StoredTeacherNavigationPreferences(
            prefs, hashlib.sha256(content).hexdigest()
        )

    def for_workspace(
        self, root: str | Path
    ) -> StoredTeacherNavigationPreferences | None:
        """Return only a matching hint; never migrate another workspace implicitly."""
        expected = _fingerprint(root)
        current = self.load()
        if current is None or current.preferences.workspace_fingerprint != expected:
            return None
        return current

    def save_selection(
        self,
        root: str | Path,
        *,
        school_year: str | None,
        class_id: str | None,
        work: ModuleWorkRef | None = None,
        expected: StoredTeacherNavigationPreferences | None = None,
    ) -> StoredTeacherNavigationPreferences:
        """Only call after an explicit teacher navigation choice or clear action."""
        fingerprint = _fingerprint(root)
        # Validate before entering the lock; a remembered choice is not authority.
        staged = TeacherNavigationPreferences(
            revision=1,
            workspace_fingerprint=fingerprint,
            school_year=school_year,
            class_id=class_id,
            work=work,
        )
        try:
            with self._profile_store._locked():
                current = self.load()
                if expected is None:
                    if current is not None:
                        raise TeacherPreferencesConflictError(
                            "Preferences already exist; refresh before saving."
                        )
                elif (
                    current is None
                    or current.sha256 != expected.sha256
                    or current.preferences.revision != expected.preferences.revision
                ):
                    raise TeacherPreferencesConflictError(
                        "Preferences changed; reload before saving."
                    )
                revision = 1 if current is None else current.preferences.revision + 1
                updated = TeacherNavigationPreferences(
                    revision=revision,
                    workspace_fingerprint=staged.workspace_fingerprint,
                    school_year=staged.school_year,
                    class_id=staged.class_id,
                    work=staged.work,
                )
                encoded = _serialize(updated)
                if len(encoded) > _MAX_BYTES:
                    raise TeacherPreferencesValidationError(
                        "Preferences exceed size limit."
                    )
                if _is_unsafe_link(self.path):
                    raise TeacherPreferencesStorageError("Preferences path is unsafe.")
                temp: Path | None = None
                try:
                    fd, temp_name = tempfile.mkstemp(
                        prefix=".teacher-preferences-",
                        suffix=".tmp",
                        dir=self.path.parent,
                    )
                    temp = Path(temp_name)
                    with os.fdopen(fd, "wb") as target:
                        target.write(encoded)
                        target.flush()
                        os.fsync(target.fileno())
                    os.replace(temp, self.path)
                    temp = None
                    _flush_directory(self.path.parent)
                except OSError as error:
                    raise TeacherPreferencesStorageError(
                        "Could not save local navigation preferences."
                    ) from error
                finally:
                    if temp is not None:
                        temp.unlink(missing_ok=True)
                return StoredTeacherNavigationPreferences(
                    updated, hashlib.sha256(encoded).hexdigest()
                )
        except TeacherProfileStorageError as error:
            raise TeacherPreferencesStorageError(
                "Cannot lock preferences safely."
            ) from error


def validate_resume_hint(
    root: str | Path,
    stored: StoredTeacherNavigationPreferences | None,
) -> ValidatedResumeCandidate:
    """Check Core school year, roster and registration before navigation.

    No protected publication access, student restoration, or academic mutation.
    Any mismatch becomes an explicit non-resumable state, never guessed.
    """
    if stored is None:
        return ValidatedResumeCandidate(None, None, None, "No saved context.")
    hint = stored.preferences
    if hint.workspace_fingerprint != _fingerprint(root):
        return ValidatedResumeCandidate(None, None, None, "Different workspace.")
    if hint.school_year is None:
        return ValidatedResumeCandidate(None, None, None, "No saved school year.")
    try:
        active_year = get_active_school_year(root)
    except (SchoolYearStateError, OSError, ValueError) as error:
        raise TeacherPreferencesStorageError(
            "Cannot verify current Core school year."
        ) from error
    if active_year != hint.school_year:
        return ValidatedResumeCandidate(None, None, None, "School year is not active.")
    if hint.class_id is None:
        return ValidatedResumeCandidate(
            hint.school_year, None, None, "School year available."
        )
    try:
        metadata = load_class_metadata_for_class(root, hint.class_id)
        if metadata.school_year != hint.school_year:
            return ValidatedResumeCandidate(
                hint.school_year, None, None, "Class is from another school year."
            )
        load_class_roster(root, hint.class_id)
    except (ClassMetadataError, RosterError, ValueError, OSError):
        return ValidatedResumeCandidate(
            hint.school_year, None, None, "Class is unavailable."
        )
    if hint.work is None:
        return ValidatedResumeCandidate(
            hint.school_year, hint.class_id, None, "Class verified."
        )
    try:
        registered = load_current_academic_work_registration(root, hint.work)
    except (AcademicWorkRegistrationStorageError, ValueError, OSError):
        return ValidatedResumeCandidate(
            hint.school_year, hint.class_id, None, "Work is unavailable."
        )
    if registered is None or registered.lifecycle not in ("active", "planned"):
        return ValidatedResumeCandidate(
            hint.school_year, hint.class_id, None, "Work is not active."
        )
    return ValidatedResumeCandidate(
        hint.school_year, hint.class_id, hint.work, "Work verified."
    )


def apply_verified_navigation(
    session: TeacherSessionContext,
    candidate: ValidatedResumeCandidate,
) -> bool:
    """Opt-in navigation-only resume; caller must provide freshly verified hint.

    Never replaces an already active teacher selection, carries no student,
    publication or academic selection, and does not authorize evidence access.
    """
    if session.active_class_id is not None:
        return False
    if candidate.class_id is None:
        return False
    session.select_class(candidate.class_id)
    if candidate.work is not None:
        session.select_work(candidate.work)
    return True


__all__ = [
    "apply_verified_navigation",
    "PREFERENCES_SCHEMA_VERSION",
    "StoredTeacherNavigationPreferences",
    "TeacherNavigationPreferences",
    "TeacherNavigationPreferencesStore",
    "TeacherPreferencesConflictError",
    "TeacherPreferencesError",
    "TeacherPreferencesStorageError",
    "TeacherPreferencesValidationError",
    "ValidatedResumeCandidate",
    "validate_resume_hint",
]
