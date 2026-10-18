"""#122 durable teacher-action checkpoints and conservative canonical reconciliation.

This store is a *journal*, not the source of truth for an academic decision.
No function in this module writes, selects, or authorizes academic records.
Domain-specific readers supplied by #122's later adapters must independently
load exact immutable history, current pointers and current dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.teacher_action_contract import (
    ActionKind,
    ActionStatus,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionContractError,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionScope,
    TeacherActionTarget,
)

ReceiptPhase = Literal["prepared", "in_progress"]
RecoveryReason = Literal[
    "exact_current",
    "eligible_to_resume",
    "target_absent",
    "missing_receipt",
    "missing_receipt_target_present",
    "unsafe_receipt",
    "canonical_read_failed",
    "target_digest_conflict",
    "dependencies_changed",
    "current_pointer_changed",
    "current_pointer_unknown",
    "receipt_canonical_divergence",
    "incomplete_multi_record_action",
]
_SHA256: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_ACTION_ID: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}\Z")
_SCHEMA: Final = 1
_T = TypeVar("_T")
_MAX_RECEIPT_BYTES: Final = 32 * 1024
_MAX_CHECKPOINTS: Final = 64
_MAX_RECORDS: Final = 16
_MAX_RECEIPTS_PER_CLASS: Final = 10000
_STAGES: Final = (
    "preflight",
    "receipt_prepared",
    "write",
    "selection_preview",
    "selection_commit",
    "verification",
    "receipt_finalized",
)


class TeacherActionReceiptError(RuntimeError):
    """Base class for fail-closed action-journal errors."""


class TeacherActionReceiptUnsafeError(TeacherActionReceiptError):
    """Unsafe filesystem path, permissions, or receipt bytes."""


class TeacherActionReceiptConflictError(TeacherActionReceiptError):
    """An action was updated by another process or mismatched its reviewed intent."""


class TeacherActionReceiptLockError(TeacherActionReceiptError):
    """The class-scoped receipt writer is busy or its lock is unsafe."""


def _sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _utc(value: object) -> str:
    if not isinstance(value, str):
        raise TeacherActionReceiptUnsafeError("Journal timestamp must be UTC.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TeacherActionReceiptUnsafeError("Malformed UTC timestamp.") from error
    offset = parsed.utcoffset()
    if (
        not value.endswith("+00:00")
        or parsed.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
        or parsed.isoformat() != value
    ):
        raise TeacherActionReceiptUnsafeError("Noncanonical UTC timestamp.")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _strict_mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TeacherActionReceiptUnsafeError("Journal JSON schema mismatch.")
    if any(not isinstance(key, str) for key in value):
        raise TeacherActionReceiptUnsafeError("Invalid journal JSON member key.")
    return value


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TeacherActionReceiptUnsafeError("Duplicate journal JSON key.")
        result[key] = value
    return result


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TeacherActionReceiptUnsafeError("Journal is not serializable.") from error


def _from_dict(dataclass_type: type[_T], value: object, keys: set[str]) -> _T:
    row = _strict_mapping(value, keys)
    try:
        return dataclass_type(**row)
    except (TypeError, ValueError, TeacherActionContractError) as error:
        raise TeacherActionReceiptUnsafeError("Invalid typed journal value.") from error


def _preview_from_dict(value: object) -> TeacherActionPreview:
    row = _strict_mapping(
        value,
        {
            "action_id",
            "kind",
            "scope",
            "actor",
            "target",
            "basis",
            "reviewed_decision_sha256",
            "make_current",
            "schema_version",
        },
    )
    basis = row["basis"]
    if not isinstance(basis, list) or len(basis) > _MAX_RECORDS:
        raise TeacherActionReceiptUnsafeError("Journal has invalid dependency count.")
    try:
        return TeacherActionPreview(
            action_id=cast(str, row["action_id"]),
            kind=cast(ActionKind, row["kind"]),
            scope=_from_dict(
                TeacherActionScope,
                row["scope"],
                {
                    "workspace_sha256",
                    "class_id",
                    "grade_item_id",
                    "school_year",
                    "academic_period_id",
                    "calendar_sha256",
                    "work_identity_sha256",
                },
            ),
            actor=_from_dict(
                TeacherActionActor,
                row["actor"],
                {"actor_id", "profile_sha256", "source"},
            ),
            target=_from_dict(
                TeacherActionTarget,
                row["target"],
                {
                    "family",
                    "identity_sha256",
                    "revision",
                    "candidate_sha256",
                    "expected_current_revision",
                    "expected_current_sha256",
                },
            ),
            basis=tuple(
                _from_dict(
                    TeacherActionBasis,
                    item,
                    {
                        "role",
                        "identity_sha256",
                        "content_sha256",
                        "revision",
                        "selected_revision",
                        "selected_sha256",
                    },
                )
                for item in basis
            ),
            reviewed_decision_sha256=cast(str, row["reviewed_decision_sha256"]),
            make_current=cast(bool, row["make_current"]),
            schema_version=cast(int, row["schema_version"]),
        )
    except (TeacherActionContractError, TypeError, ValueError) as error:
        raise TeacherActionReceiptUnsafeError("Invalid journal preview.") from error


@dataclass(frozen=True, slots=True)
class TeacherActionReceipt:
    """Bounded mutable checkpoint journal for one *exact* reviewed action."""

    preview: TeacherActionPreview
    generation: int
    created_at: str
    updated_at: str
    phase: ReceiptPhase
    checkpoints: tuple[TeacherActionCheckpoint, ...]
    observed_records: tuple[TeacherActionRecord, ...]
    schema_version: int = _SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.preview, TeacherActionPreview):
            raise TeacherActionReceiptUnsafeError("Receipt requires exact preview.")
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA:
            raise TeacherActionReceiptUnsafeError("Unsupported journal schema.")
        if type(self.generation) is not int or not 1 <= self.generation <= 1_000_000:
            raise TeacherActionReceiptUnsafeError("Invalid receipt generation.")
        if _utc(self.updated_at) < _utc(self.created_at):
            raise TeacherActionReceiptUnsafeError("Receipt timestamps are reversed.")
        if self.phase not in ("prepared", "in_progress"):
            raise TeacherActionReceiptUnsafeError("Invalid receipt phase.")
        if not isinstance(self.checkpoints, tuple) or not (
            1 <= len(self.checkpoints) <= _MAX_CHECKPOINTS
        ):
            raise TeacherActionReceiptUnsafeError("Invalid checkpoint count.")
        if any(not isinstance(c, TeacherActionCheckpoint) for c in self.checkpoints):
            raise TeacherActionReceiptUnsafeError("Invalid checkpoint type.")
        if self.checkpoints[0] != TeacherActionCheckpoint(
            "receipt_prepared", "completed"
        ):
            raise TeacherActionReceiptUnsafeError(
                "Receipt must begin with preparation."
            )
        ranks = tuple(_STAGES.index(c.stage) for c in self.checkpoints)
        if tuple(sorted(ranks)) != ranks:
            raise TeacherActionReceiptUnsafeError("Out-of-order checkpoint trace.")
        if self.phase == "prepared" and len(self.checkpoints) != 1:
            raise TeacherActionReceiptUnsafeError("Prepared receipt has progress.")
        if self.phase == "in_progress" and len(self.checkpoints) < 2:
            raise TeacherActionReceiptUnsafeError("Progress receipt has no event.")
        if not isinstance(self.observed_records, tuple) or (
            len(self.observed_records) > _MAX_RECORDS
        ):
            raise TeacherActionReceiptUnsafeError("Invalid observed-record count.")
        if any(not isinstance(r, TeacherActionRecord) for r in self.observed_records):
            raise TeacherActionReceiptUnsafeError("Invalid observed record type.")
        identity = [
            (r.family, r.identity_sha256, r.revision) for r in self.observed_records
        ]
        if len(set(identity)) != len(identity):
            raise TeacherActionReceiptUnsafeError("Duplicate observed record.")
        if self.phase == "prepared" and self.observed_records:
            raise TeacherActionReceiptUnsafeError("Prepared receipt contains records.")

    @property
    def action_id(self) -> str:
        return self.preview.action_id

    @property
    def intent_sha256(self) -> str:
        return self.preview.intent_sha256


def _encode(receipt: TeacherActionReceipt) -> bytes:
    payload = asdict(receipt)
    checksum = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    content = _canonical_bytes({"payload": payload, "payload_sha256": checksum})
    if len(content) > _MAX_RECEIPT_BYTES:
        raise TeacherActionReceiptUnsafeError("Journal exceeds bounded JSON size.")
    return content


def _decode(data: bytes) -> TeacherActionReceipt:
    if not isinstance(data, bytes) or not 0 < len(data) <= _MAX_RECEIPT_BYTES:
        raise TeacherActionReceiptUnsafeError("Journal has invalid byte length.")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise TeacherActionReceiptUnsafeError("Journal JSON is corrupt.") from error
    envelope = _strict_mapping(value, {"payload", "payload_sha256"})
    payload = _strict_mapping(
        envelope["payload"],
        {
            "preview",
            "generation",
            "created_at",
            "updated_at",
            "phase",
            "checkpoints",
            "observed_records",
            "schema_version",
        },
    )
    if not _sha(envelope["payload_sha256"]) or (
        hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        != envelope["payload_sha256"]
    ):
        raise TeacherActionReceiptUnsafeError("Journal checksum mismatch.")
    checks = payload["checkpoints"]
    records = payload["observed_records"]
    if not isinstance(checks, list) or not isinstance(records, list):
        raise TeacherActionReceiptUnsafeError("Journal arrays are malformed.")
    if len(checks) > _MAX_CHECKPOINTS or len(records) > _MAX_RECORDS:
        raise TeacherActionReceiptUnsafeError("Journal arrays exceed safe bounds.")
    try:
        receipt = TeacherActionReceipt(
            preview=_preview_from_dict(payload["preview"]),
            generation=cast(int, payload["generation"]),
            created_at=cast(str, payload["created_at"]),
            updated_at=cast(str, payload["updated_at"]),
            phase=cast(ReceiptPhase, payload["phase"]),
            checkpoints=tuple(
                _from_dict(
                    TeacherActionCheckpoint,
                    c,
                    {"stage", "disposition", "reason_code"},
                )
                for c in checks
            ),
            observed_records=tuple(
                _from_dict(
                    TeacherActionRecord,
                    r,
                    {
                        "family",
                        "identity_sha256",
                        "revision",
                        "sha256",
                        "write_disposition",
                    },
                )
                for r in records
            ),
            schema_version=cast(int, payload["schema_version"]),
        )
    except (ValueError, TypeError, TeacherActionContractError) as error:
        raise TeacherActionReceiptUnsafeError("Journal content is invalid.") from error
    if _encode(receipt) != data:
        raise TeacherActionReceiptUnsafeError("Journal bytes are not canonical.")
    return receipt


def _unsafe_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _guard_dir(path: Path, *, private: bool = False) -> None:
    if _unsafe_link(path) or not path.is_dir():
        raise TeacherActionReceiptUnsafeError("Unsafe journal directory.")
    if private and os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TeacherActionReceiptUnsafeError("Journal directory is not private.")


def _guard_file(path: Path) -> None:
    if _unsafe_link(path):
        raise TeacherActionReceiptUnsafeError("Journal path is a link/reparse point.")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TeacherActionReceiptUnsafeError("Journal path is not a regular file.")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise TeacherActionReceiptUnsafeError("Journal file is not private.")


def _read_file(path: Path) -> bytes | None:
    _guard_file(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise TeacherActionReceiptUnsafeError("Cannot open journal safely.") from error
    try:
        info = os.fstat(fd)
        observed = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_ino != observed.st_ino
            or info.st_dev != observed.st_dev
        ):
            raise TeacherActionReceiptUnsafeError("Journal changed during open.")
        _guard_file(path)
        data = bytearray()
        while len(data) <= _MAX_RECEIPT_BYTES:
            part = os.read(fd, _MAX_RECEIPT_BYTES + 1 - len(data))
            if not part:
                return bytes(data)
            data.extend(part)
        raise TeacherActionReceiptUnsafeError("Journal exceeds bounded byte length.")
    finally:
        os.close(fd)


def _flush_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _file_lock(fd: int, *, unlock: bool) -> None:
    if os.name == "nt":
        import msvcrt

        operation = msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK
        msvcrt.locking(fd, operation, 1)
    else:
        import fcntl

        flock = cast(Callable[[int, int], None], getattr(fcntl, "flock"))
        operation = cast(int, getattr(fcntl, "LOCK_UN" if unlock else "LOCK_EX"))
        if not unlock:
            operation |= cast(int, getattr(fcntl, "LOCK_NB"))
        flock(fd, operation)


class TeacherActionReceiptStore:
    """Class-local, bounded and CAS-updated journal; independent of Core records."""

    def __init__(self, workspace_root: Path, class_id: str) -> None:
        if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
            raise TeacherActionReceiptUnsafeError("Workspace root must be absolute.")
        try:
            value = validate_identifier(class_id, "class_id")
        except IdentifierValidationError as error:
            raise TeacherActionReceiptUnsafeError("Unsafe class identifier.") from error
        self.root = workspace_root
        self.class_id = value
        self.directory = class_module_dir(workspace_root, value, "meridian") / (
            "teacher_action_receipts"
        )

    def _guard_chain(self, *, create: bool) -> bool:
        # Do not resolve a symlinked root and then declare it contained.
        root = self.root
        _guard_dir(root)
        relative = self.directory.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if not current.exists() and not _unsafe_link(current):
                if not create:
                    return False
                if current == self.root / "classes" / self.class_id:
                    raise TeacherActionReceiptUnsafeError(
                        "Action receipt cannot create an unregistered class."
                    )
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise TeacherActionReceiptUnsafeError(
                        "Cannot create safe journal directory."
                    ) from error
            _guard_dir(current, private=current == self.directory)
        return True

    def path_for(self, action_id: str) -> Path:
        if not isinstance(action_id, str) or not _ACTION_ID.fullmatch(action_id):
            raise TeacherActionReceiptUnsafeError("Unsafe action ID.")
        return self.directory / f"{action_id}.json"

    def _load_existing(self, action_id: str) -> TeacherActionReceipt | None:
        data = _read_file(self.path_for(action_id))
        if data is None:
            return None
        receipt = _decode(data)
        if (
            receipt.action_id != action_id
            or receipt.preview.scope.class_id != self.class_id
        ):
            raise TeacherActionReceiptUnsafeError("Journal path and scope differ.")
        return receipt

    def load(self, action_id: str) -> TeacherActionReceipt | None:
        """Read without creating directories, lock files, or canonical mutations."""
        self.path_for(action_id)
        if not self._guard_chain(create=False):
            return None
        return self._load_existing(action_id)

    def list_receipts(self) -> tuple[TeacherActionReceipt, ...]:
        """Enumerate validated class receipts without creating or modifying files.

        Unknown names, temporary files, symlinks, corrupt receipts and excessive
        entries cause a fail-closed error. A partial inventory is never returned.
        """
        if not self._guard_chain(create=False):
            return ()
        try:
            entries = tuple(self.directory.iterdir())
        except OSError as error:
            raise TeacherActionReceiptUnsafeError(
                "Could not enumerate the action journal."
            ) from error
        if len(entries) > _MAX_RECEIPTS_PER_CLASS + 1:
            raise TeacherActionReceiptUnsafeError(
                "Journal has too many entries for complete review."
            )
        receipts: list[TeacherActionReceipt] = []
        for entry in sorted(entries, key=lambda item: item.name):
            if entry.name == ".journal.lock":
                _guard_file(entry)
                continue
            match = re.fullmatch(r"([0-9a-f]{32})\.json", entry.name)
            if match is None:
                raise TeacherActionReceiptUnsafeError(
                    "Journal contains an unrecognized or incomplete entry."
                )
            _guard_file(entry)
            receipt = self._load_existing(match.group(1))
            if receipt is None:
                raise TeacherActionReceiptUnsafeError(
                    "Journal receipt disappeared during enumeration."
                )
            receipts.append(receipt)
        try:
            final_names = tuple(sorted(item.name for item in self.directory.iterdir()))
        except OSError as error:
            raise TeacherActionReceiptUnsafeError(
                "Journal changed while enumerating entries."
            ) from error
        original_names = tuple(sorted(entry.name for entry in entries))
        if final_names != original_names:
            raise TeacherActionReceiptUnsafeError(
                "Journal changed while enumerating entries."
            )
        return tuple(receipts)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._guard_chain(create=True)
        path = self.directory / ".journal.lock"
        _guard_file(path)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as error:
            raise TeacherActionReceiptLockError("Cannot open journal lock.") from error
        locked = False
        try:
            info = os.fstat(fd)
            observed = path.lstat()
            if (
                info.st_ino != observed.st_ino
                or info.st_dev != observed.st_dev
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise TeacherActionReceiptLockError("Journal lock changed during open.")
            _guard_file(path)
            if os.name == "nt" and info.st_size == 0:
                os.write(fd, b"0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                _file_lock(fd, unlock=False)
                locked = True
            except OSError as error:
                raise TeacherActionReceiptLockError("Journal is busy.") from error
            self._guard_chain(create=False)
            yield
        finally:
            if locked:
                os.lseek(fd, 0, os.SEEK_SET)
                _file_lock(fd, unlock=True)
            os.close(fd)

    def _save(self, receipt: TeacherActionReceipt) -> None:
        target = self.path_for(receipt.action_id)
        _guard_file(target)
        content = _encode(receipt)
        temp: Path | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=".journal-", suffix=".tmp", dir=self.directory
            )
            temp = Path(name)
            with os.fdopen(fd, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            self._guard_chain(create=False)
            _guard_file(target)
            os.replace(temp, target)
            temp = None
            _flush_dir(self.directory)
        except OSError as error:
            raise TeacherActionReceiptUnsafeError("Journal commit failed.") from error
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def prepare(self, preview: TeacherActionPreview) -> TeacherActionReceipt:
        """Prepare a receipt BEFORE any academic mutation, or fail closed."""
        if not isinstance(preview, TeacherActionPreview):
            raise TeacherActionReceiptUnsafeError("Expected reviewed action preview.")
        if preview.scope.class_id != self.class_id:
            raise TeacherActionReceiptUnsafeError("Preview class does not match store.")
        with self._locked():
            existing = self._load_existing(preview.action_id)
            if existing is not None:
                if existing.preview != preview:
                    raise TeacherActionReceiptConflictError(
                        "Action ID already belongs to another reviewed decision."
                    )
                return existing
            # Bound growth; unknown names and links prevent a blind overwrite.
            count = 0
            for entry in self.directory.iterdir():
                if entry.name.endswith(".json"):
                    count += 1
                    _guard_file(entry)
                if count >= _MAX_RECEIPTS_PER_CLASS:
                    raise TeacherActionReceiptUnsafeError(
                        "Class action journal is at its configured limit."
                    )
            now = _now()
            receipt = TeacherActionReceipt(
                preview=preview,
                generation=1,
                created_at=now,
                updated_at=now,
                phase="prepared",
                checkpoints=(TeacherActionCheckpoint("receipt_prepared", "completed"),),
                observed_records=(),
            )
            self._save(receipt)
            return receipt

    def record_checkpoint(
        self,
        preview: TeacherActionPreview,
        *,
        expected_generation: int,
        checkpoint: TeacherActionCheckpoint,
        observed_records: tuple[TeacherActionRecord, ...] | None = None,
    ) -> TeacherActionReceipt:
        """CAS append: exact teacher intent, ordered step, bounded observations."""
        if not isinstance(preview, TeacherActionPreview) or not isinstance(
            checkpoint, TeacherActionCheckpoint
        ):
            raise TeacherActionReceiptUnsafeError("Invalid checkpoint request.")
        if type(expected_generation) is not int or expected_generation < 1:
            raise TeacherActionReceiptUnsafeError("Invalid expected generation.")
        with self._locked():
            receipt = self._load_existing(preview.action_id)
            if receipt is None or receipt.preview != preview:
                raise TeacherActionReceiptConflictError(
                    "Reviewed action journal is absent."
                )
            if receipt.generation != expected_generation:
                raise TeacherActionReceiptConflictError(
                    "Another writer updated this action journal."
                )
            if _STAGES.index(checkpoint.stage) < _STAGES.index(
                receipt.checkpoints[-1].stage
            ):
                raise TeacherActionReceiptConflictError(
                    "Cannot move the checkpoint journal backwards."
                )
            observed = (
                receipt.observed_records
                if observed_records is None
                else observed_records
            )
            if observed_records is not None and any(
                old not in observed_records for old in receipt.observed_records
            ):
                raise TeacherActionReceiptConflictError(
                    "Cannot discard previously observed immutable identities."
                )
            updated = replace(
                receipt,
                generation=receipt.generation + 1,
                updated_at=_now(),
                phase="in_progress",
                checkpoints=(*receipt.checkpoints, checkpoint),
                observed_records=observed,
            )
            self._save(updated)
            return updated


@dataclass(frozen=True, slots=True)
class CanonicalActionObservation:
    """Observation returned by a *live* domain authority reader, never a journal.

    target_sha256: None means exact history revision absent. A digest mismatch
    means history exists under that revision but does not match the preview.
    current_revision/digest must be read from the canonical selector+record.
    current_basis may be current, stale or unknown for the reviewed sources.
    """

    target_sha256: str | None
    current_revision: int | None
    current_sha256: str | None
    current_basis: Literal["current", "stale", "unknown"]
    target_history_verified: bool = True

    def __post_init__(self) -> None:
        if self.target_sha256 is not None and not _sha(self.target_sha256):
            raise TeacherActionReceiptUnsafeError("Invalid target digest observation.")
        if (self.current_revision is None) != (self.current_sha256 is None):
            raise TeacherActionReceiptUnsafeError("Incomplete current-pointer read.")
        if self.current_revision is not None and (
            type(self.current_revision) is not int or self.current_revision < 1
        ):
            raise TeacherActionReceiptUnsafeError("Invalid selected revision.")
        if self.current_sha256 is not None and not _sha(self.current_sha256):
            raise TeacherActionReceiptUnsafeError("Invalid selected digest.")
        if self.current_basis not in ("current", "stale", "unknown"):
            raise TeacherActionReceiptUnsafeError("Invalid source-currentness result.")
        if type(self.target_history_verified) is not bool:
            raise TeacherActionReceiptUnsafeError("Unverified history flag.")


@dataclass(frozen=True, slots=True)
class TeacherActionRecoveryAssessment:
    """Read-only outcome: never invokes authoring or selection itself."""

    status: ActionStatus
    reason: RecoveryReason
    can_resume_exact_selection: bool
    receipt_generation: int | None
    target_verified_present: bool


def assess_teacher_action_recovery(
    store: TeacherActionReceiptStore,
    preview: TeacherActionPreview,
    canonical_loader: Callable[[TeacherActionPreview], CanonicalActionObservation],
) -> TeacherActionRecoveryAssessment:
    """Re-read canonical truth and bound receipt; never blindly retry a write.

    A missing/corrupted journal does NOT authorize replay, even when target
    history was discovered. An adapter must explicitly rereview and establish
    authority to continue. Resume is *advice*, not an executable capability.
    """
    if not isinstance(preview, TeacherActionPreview):
        raise TeacherActionReceiptUnsafeError("Recovery requires reviewed action.")
    if preview.scope.class_id != store.class_id:
        raise TeacherActionReceiptUnsafeError("Class-scoped recovery mismatch.")
    unsafe_receipt = False
    try:
        receipt = store.load(preview.action_id)
    except TeacherActionReceiptError:
        receipt = None
        unsafe_receipt = True
    # Canonical inspection still takes place when the receipt is corrupted.
    # Never try to repair a hostile journal as a side effect of recovery.
    try:
        observation = canonical_loader(preview)
        if not isinstance(observation, CanonicalActionObservation):
            raise TeacherActionReceiptUnsafeError("Invalid canonical reader result.")
    except Exception:
        return TeacherActionRecoveryAssessment(
            "recovery_required",
            "canonical_read_failed",
            False,
            None if receipt is None else receipt.generation,
            False,
        )
    if not observation.target_history_verified:
        return TeacherActionRecoveryAssessment(
            "recovery_required",
            "canonical_read_failed",
            False,
            None if receipt is None else receipt.generation,
            False,
        )
    if unsafe_receipt:
        return TeacherActionRecoveryAssessment(
            "recovery_required",
            "unsafe_receipt",
            False,
            None,
            observation.target_sha256 == preview.target.candidate_sha256,
        )
    if receipt is not None and receipt.preview != preview:
        return TeacherActionRecoveryAssessment(
            "conflict_requires_review",
            "dependencies_changed",
            False,
            receipt.generation,
            False,
        )
    generation = None if receipt is None else receipt.generation
    present = observation.target_sha256 is not None
    if present and observation.target_sha256 != preview.target.candidate_sha256:
        return TeacherActionRecoveryAssessment(
            "conflict_requires_review",
            "target_digest_conflict",
            False,
            generation,
            False,
        )
    if receipt is None:
        return TeacherActionRecoveryAssessment(
            "recovery_required",
            "missing_receipt_target_present" if present else "missing_receipt",
            False,
            None,
            present,
        )
    if any(item.matches_target(preview.target) for item in receipt.observed_records):
        if not present:
            return TeacherActionRecoveryAssessment(
                "recovery_required",
                "receipt_canonical_divergence",
                False,
                generation,
                False,
            )
    if any(
        not item.matches_target(preview.target) for item in receipt.observed_records
    ):
        return TeacherActionRecoveryAssessment(
            "recovery_required",
            "incomplete_multi_record_action",
            False,
            generation,
            present,
        )
    if observation.current_basis == "unknown":
        return TeacherActionRecoveryAssessment(
            "current_unverified" if present else "recovery_required",
            "current_pointer_unknown",
            False,
            generation,
            present,
        )
    if observation.current_basis == "stale":
        return TeacherActionRecoveryAssessment(
            "conflict_requires_review",
            "dependencies_changed",
            False,
            generation,
            present,
        )
    if not present:
        # Even an exact receipt cannot prove that a write did not start.
        if any(
            c.stage
            in (
                "write",
                "selection_preview",
                "selection_commit",
                "verification",
                "receipt_finalized",
            )
            for c in receipt.checkpoints
        ):
            return TeacherActionRecoveryAssessment(
                "recovery_required", "target_absent", False, generation, False
            )
        return TeacherActionRecoveryAssessment(
            "blocked_before_write", "target_absent", False, generation, False
        )
    if (
        observation.current_revision == preview.target.revision
        and observation.current_sha256 == preview.target.candidate_sha256
    ):
        if not preview.make_current:
            return TeacherActionRecoveryAssessment(
                "recovery_required",
                "incomplete_multi_record_action",
                False,
                generation,
                True,
            )
        # Existing CAS selection and still-current dependencies, independently read.
        return TeacherActionRecoveryAssessment(
            "already_applied", "exact_current", False, generation, True
        )
    if (
        observation.current_revision == preview.target.expected_current_revision
        and observation.current_sha256 == preview.target.expected_current_sha256
    ):
        # Future kernel must still recheck CAS, actor, authority and source before
        # selecting this exact immutable revision. No selection happens here.
        return TeacherActionRecoveryAssessment(
            "written_not_current",
            "eligible_to_resume",
            bool(preview.make_current),
            generation,
            True,
        )
    return TeacherActionRecoveryAssessment(
        "conflict_requires_review",
        "current_pointer_changed",
        False,
        generation,
        True,
    )


__all__ = (
    "CanonicalActionObservation",
    "TeacherActionReceipt",
    "TeacherActionReceiptConflictError",
    "TeacherActionReceiptError",
    "TeacherActionReceiptLockError",
    "TeacherActionReceiptStore",
    "TeacherActionReceiptUnsafeError",
    "TeacherActionRecoveryAssessment",
    "assess_teacher_action_recovery",
)
