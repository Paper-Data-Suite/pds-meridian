"""#124 E2B: guarded persistent correlation store, not academic authority.

The store never creates a #122 action, selects a Grade Item, or resumes a write.
An exact reviewed correlation is durably created before the first academic
operation; subsequent action IDs must be bound by monotonic exact-byte CAS.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    AssessmentSetupCorrelationError,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_receipts import (
    _file_lock,
    _flush_dir,
    _guard_dir,
    _guard_file,
    _read_file,
    _unsafe_link,
)

_ID = re.compile(r"[0-9a-f]{64}\Z")
_LIMIT = 10000


class AssessmentSetupCorrelationStorageError(RuntimeError):
    """Refuse unsafe, incomplete or unavailable durable correlation storage."""


class AssessmentSetupCorrelationStorageConflict(AssessmentSetupCorrelationStorageError):
    """The expected exact correlation state no longer matches the file."""


@dataclass(frozen=True, slots=True)
class CorrelationStoreResult:
    record: AssessmentSetupCorrelation
    disposition: Literal["created", "advanced", "existing"]


class AssessmentSetupCorrelationStore:
    """Per-class persistent correlation file and nonblocking advisory lock.

    File identity is the full E2A reviewed intent hash, never title or a
    discovery listing. An orphaned temp file deliberately blocks enumeration.
    """

    def __init__(self, workspace_root: Path, class_id: str) -> None:
        if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
            raise AssessmentSetupCorrelationStorageError(
                "Absolute workspace path required."
            )
        try:
            validated = validate_identifier(class_id, "class_id")
        except IdentifierValidationError as error:
            raise AssessmentSetupCorrelationStorageError(
                "Unsafe class identity."
            ) from error
        self.root = workspace_root
        self.class_id = validated
        self.directory = class_module_dir(workspace_root, validated, "meridian") / (
            "assessment_setup_correlations"
        )

    def path_for(self, intent_sha256: str) -> Path:
        if not isinstance(intent_sha256, str) or not _ID.fullmatch(intent_sha256):
            raise AssessmentSetupCorrelationStorageError("Invalid intent fingerprint.")
        return self.directory / f"{intent_sha256}.json"

    def _guard_chain(self, *, create: bool) -> bool:
        root = self.root
        try:
            _guard_dir(root)
            class_dir = root / "classes" / self.class_id
            # A correlation must never register or fabricate a missing class.
            if create:
                _guard_dir(root / "classes")
                _guard_dir(class_dir)
            relative = self.directory.relative_to(root)
            current = root
            for part in relative.parts:
                current = current / part
                if not current.exists() and not _unsafe_link(current):
                    if not create:
                        return False
                    if current == class_dir:
                        raise AssessmentSetupCorrelationStorageError(
                            "Registered class directory is absent."
                        )
                    current.mkdir(mode=0o700)
                _guard_dir(current, private=current == self.directory)
            return True
        except (OSError, ValueError) as error:
            raise AssessmentSetupCorrelationStorageError(
                "Unsafe correlation directory chain."
            ) from error

    def _check_scope(self, value: AssessmentSetupCorrelation) -> None:
        if not isinstance(value, AssessmentSetupCorrelation):
            raise AssessmentSetupCorrelationStorageError("Typed correlation required.")
        if value.class_id != self.class_id or value.workspace_sha256 != _identity(
            "workspace", str(self.root.resolve())
        ):
            raise AssessmentSetupCorrelationStorageError(
                "Correlation belongs to another class or workspace."
            )

    def _load_verified(self, intent: str) -> AssessmentSetupCorrelation | None:
        try:
            data = _read_file(self.path_for(intent))
            if data is None:
                return None
            result = AssessmentSetupCorrelation.from_json_bytes(data)
            self._check_scope(result)
            if result.intent_sha256 != intent:
                raise AssessmentSetupCorrelationStorageError(
                    "Correlation filename and intent differ."
                )
            return result
        except (AssessmentSetupCorrelationError, OSError, ValueError) as error:
            raise AssessmentSetupCorrelationStorageError(
                "Corrupt or unsafe correlation record."
            ) from error

    def load(self, intent_sha256: str) -> AssessmentSetupCorrelation | None:
        """Read only: does not create a directory or a lock."""
        self.path_for(intent_sha256)
        if not self._guard_chain(create=False):
            return None
        return self._load_verified(intent_sha256)

    def _entries(self) -> tuple[Path, ...]:
        """Require a complete clean directory; no hidden/incomplete entries."""
        try:
            entries = tuple(sorted(self.directory.iterdir(), key=lambda p: p.name))
            if len(entries) > _LIMIT + 1:
                raise AssessmentSetupCorrelationStorageError(
                    "Correlation inventory exceeds bound."
                )
            for entry in entries:
                if entry.name == ".correlation.lock":
                    _guard_file(entry)
                elif re.fullmatch(r"[0-9a-f]{64}\.json", entry.name):
                    _guard_file(entry)
                else:
                    raise AssessmentSetupCorrelationStorageError(
                        "Unrecognized or interrupted correlation entry."
                    )
            return entries
        except OSError as error:
            raise AssessmentSetupCorrelationStorageError(
                "Correlation directory cannot be enumerated."
            ) from error

    def list_records(self) -> tuple[AssessmentSetupCorrelation, ...]:
        """Strict read-only restart enumeration; refuse any partial inventory."""
        if not self._guard_chain(create=False):
            return ()
        entries = self._entries()
        found: list[AssessmentSetupCorrelation] = []
        for entry in entries:
            if entry.name == ".correlation.lock":
                continue
            record = self._load_verified(entry.stem)
            if record is None:
                raise AssessmentSetupCorrelationStorageError(
                    "Correlation disappeared during enumeration."
                )
            found.append(record)
        if tuple(p.name for p in self._entries()) != tuple(p.name for p in entries):
            raise AssessmentSetupCorrelationStorageError(
                "Correlation directory changed during enumeration."
            )
        return tuple(found)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._guard_chain(create=True)
        path = self.directory / ".correlation.lock"
        _guard_file(path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as error:
            raise AssessmentSetupCorrelationStorageError(
                "Cannot open correlation lock."
            ) from error
        locked = False
        try:
            info = os.fstat(fd)
            observed = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (info.st_ino, info.st_dev) != (observed.st_ino, observed.st_dev)
            ):
                raise AssessmentSetupCorrelationStorageError(
                    "Correlation lock identity changed."
                )
            _guard_file(path)
            if os.name == "nt" and info.st_size == 0:
                os.write(fd, b"0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                _file_lock(fd, unlock=False)
                locked = True
            except OSError as error:
                raise AssessmentSetupCorrelationStorageConflict(
                    "Correlation writer is busy."
                ) from error
            self._guard_chain(create=False)
            yield
        finally:
            if locked:
                os.lseek(fd, 0, os.SEEK_SET)
                _file_lock(fd, unlock=True)
            os.close(fd)

    def _persist(self, value: AssessmentSetupCorrelation) -> None:
        target = self.path_for(value.intent_sha256)
        _guard_file(target)
        content = value.to_json_bytes()
        temporary: Path | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=".correlation-", suffix=".tmp", dir=self.directory
            )
            temporary = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._guard_chain(create=False)
            _guard_file(target)
            os.replace(temporary, target)
            temporary = None
            _flush_dir(self.directory)
        except OSError as error:
            raise AssessmentSetupCorrelationStorageError(
                "Atomic correlation persistence failed."
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def create_reviewed(
        self, value: AssessmentSetupCorrelation
    ) -> CorrelationStoreResult:
        """Durably claim a reviewed intent before any #122 action is invoked."""
        self._check_scope(value)
        if value.stage != "reviewed":
            raise AssessmentSetupCorrelationStorageError(
                "Initial correlation must have no action bindings."
            )
        with self._locked():
            entries = self._entries()
            if len(entries) >= _LIMIT + 1:
                raise AssessmentSetupCorrelationStorageError(
                    "Correlation inventory capacity reached."
                )
            current = self._load_verified(value.intent_sha256)
            if current is not None:
                if current == value:
                    return CorrelationStoreResult(current, "existing")
                raise AssessmentSetupCorrelationStorageConflict(
                    "Reviewed intent already advanced; never reinitialize."
                )
            self._persist(value)
            return CorrelationStoreResult(value, "created")

    def advance_exact(
        self,
        *,
        expected: AssessmentSetupCorrelation,
        updated: AssessmentSetupCorrelation,
    ) -> CorrelationStoreResult:
        """Exact-byte CAS; monotone action binding before next #122 APPLY."""
        self._check_scope(expected)
        self._check_scope(updated)
        if expected.intent_sha256 != updated.intent_sha256:
            raise AssessmentSetupCorrelationStorageConflict(
                "Cannot retarget correlated assessment intent."
            )
        if updated.stage == expected.stage:
            raise AssessmentSetupCorrelationStorageConflict(
                "No correlation stage advancement requested."
            )
        if (
            (
                updated.stage == "grade_bound"
                and (expected.stage != "reviewed" or updated.kind != "create_and_link")
            )
            or (
                updated.stage == "membership_bound"
                and expected.stage
                not in (
                    ("grade_bound",)
                    if expected.kind == "create_and_link"
                    else ("reviewed",)
                )
            )
            or updated.stage == "reviewed"
        ):
            raise AssessmentSetupCorrelationStorageConflict(
                "Correlation stage transition is not monotone."
            )
        # The E2A writer supplies only a new original action binding: forbid
        # replacing an already witnessed ID or changing any reviewed field.
        if updated.stage == "grade_bound":
            valid = updated == replace(
                expected,
                grade_action_id=updated.grade_action_id,
                grade_target_sha256=updated.grade_target_sha256,
            )
        else:
            valid = updated == replace(
                expected,
                membership_action_id=updated.membership_action_id,
                membership_target_sha256=updated.membership_target_sha256,
            )
        if not valid:
            raise AssessmentSetupCorrelationStorageConflict(
                "Correlation changed more than the next action binding."
            )
        with self._locked():
            self._entries()
            current = self._load_verified(expected.intent_sha256)
            if current is None or current.to_json_bytes() != expected.to_json_bytes():
                raise AssessmentSetupCorrelationStorageConflict(
                    "Stored correlation differs from exact CAS baseline."
                )
            self._persist(updated)
            return CorrelationStoreResult(updated, "advanced")


__all__ = (
    "AssessmentSetupCorrelationStore",
    "AssessmentSetupCorrelationStorageConflict",
    "AssessmentSetupCorrelationStorageError",
    "CorrelationStoreResult",
)
