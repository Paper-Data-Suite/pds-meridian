"""Immutable teacher-controlled storage for benchmark planner revisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.storage_path_keys import storage_path_key
from meridian.teacher_report import (
    TeacherReportPreview,
    teacher_report_preview_from_json_bytes,
    teacher_report_preview_to_dict,
    validate_teacher_report_preview,
)

BENCHMARK_PLAN_SCHEMA_VERSION: Final[str] = "1"
BENCHMARK_PLAN_RECORD_TYPE: Final[str] = "meridian_benchmark_plan_revision"
DEFAULT_MAXIMUM_BENCHMARK_PLAN_BYTES: Final[int] = 16 * 1024 * 1024
BenchmarkPlanCurrentness: TypeAlias = Literal["current", "stale", "unverified"]
BenchmarkPlanWriteDisposition: TypeAlias = Literal["created", "existing"]


class BenchmarkPlanStorageError(RuntimeError):
    code = "benchmark_plan.storage_error"


class BenchmarkPlanValidationError(BenchmarkPlanStorageError, ValueError):
    code = "benchmark_plan.invalid"


class BenchmarkPlanNotFoundError(BenchmarkPlanStorageError):
    code = "benchmark_plan.not_found"


class BenchmarkPlanConflictError(BenchmarkPlanStorageError):
    code = "benchmark_plan.conflict"


class BenchmarkPlanIntegrityError(BenchmarkPlanStorageError):
    code = "benchmark_plan.integrity"


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise BenchmarkPlanValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value)
    except IdentifierValidationError as error:
        raise BenchmarkPlanValidationError(
            f"{field_name} must be a valid identifier."
        ) from error


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise BenchmarkPlanValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class BenchmarkPlanRevision:
    schema_version: str
    record_type: str
    plan_id: str
    plan_revision: int
    teacher_id: str
    class_id: str
    assessment_id: str
    created_at: datetime
    revised_at: datetime
    confirmed: bool
    currentness: BenchmarkPlanCurrentness
    report: TeacherReportPreview
    previous_revision_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != BENCHMARK_PLAN_SCHEMA_VERSION:
            raise BenchmarkPlanValidationError('schema_version must be "1".')
        if self.record_type != BENCHMARK_PLAN_RECORD_TYPE:
            raise BenchmarkPlanValidationError("record_type is invalid.")
        object.__setattr__(self, "plan_id", _identifier(self.plan_id, "plan_id"))
        object.__setattr__(
            self, "teacher_id", _identifier(self.teacher_id, "teacher_id")
        )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self, "assessment_id", _identifier(self.assessment_id, "assessment_id")
        )
        if type(self.plan_revision) is not int or self.plan_revision < 1:
            raise BenchmarkPlanValidationError("plan_revision must be positive.")
        created = _utc(self.created_at, "created_at")
        revised = _utc(self.revised_at, "revised_at")
        if revised < created:
            raise BenchmarkPlanValidationError("revised_at cannot precede created_at.")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "revised_at", revised)
        if self.confirmed is not True:
            raise BenchmarkPlanValidationError(
                "saving a plan requires explicit teacher confirmation."
            )
        if self.currentness not in {"current", "stale", "unverified"}:
            raise BenchmarkPlanValidationError("currentness is invalid.")
        report = validate_teacher_report_preview(self.report)
        if report.report_kind != "benchmark_analysis_instructional_response":
            raise BenchmarkPlanValidationError(
                "report must be a benchmark analysis planner."
            )
        if report.class_id != self.class_id:
            raise BenchmarkPlanValidationError(
                "report class does not match plan class."
            )
        object.__setattr__(self, "report", report)
        previous = self.previous_revision_sha256
        if self.plan_revision == 1 and previous is not None:
            raise BenchmarkPlanValidationError(
                "the first plan revision cannot have a predecessor digest."
            )
        if self.plan_revision > 1:
            if (
                previous is None
                or len(previous) != 64
                or any(character not in "0123456789abcdef" for character in previous)
            ):
                raise BenchmarkPlanValidationError(
                    "later plan revisions require a SHA-256 predecessor digest."
                )


@dataclass(frozen=True, slots=True)
class StoredBenchmarkPlanRevision:
    revision: BenchmarkPlanRevision
    revision_sha256: str
    path: Path = field(repr=False)
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BenchmarkPlanWriteResult:
    disposition: BenchmarkPlanWriteDisposition
    stored: StoredBenchmarkPlanRevision


def benchmark_plan_to_json_bytes(value: BenchmarkPlanRevision) -> bytes:
    return _json_bytes(_to_dict(value))


def benchmark_plan_from_json_bytes(data: bytes) -> BenchmarkPlanRevision:
    if type(data) is not bytes:
        raise BenchmarkPlanIntegrityError("plan JSON must be bytes.")
    try:
        raw = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"invalid constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise BenchmarkPlanIntegrityError("plan JSON is invalid.") from error
    mapping = _mapping(
        raw,
        {
            "schema_version",
            "record_type",
            "plan_id",
            "plan_revision",
            "teacher_id",
            "class_id",
            "assessment_id",
            "created_at",
            "revised_at",
            "confirmed",
            "currentness",
            "report",
            "previous_revision_sha256",
        },
    )
    revision = BenchmarkPlanRevision(
        schema_version=_str(mapping["schema_version"]),
        record_type=_str(mapping["record_type"]),
        plan_id=_str(mapping["plan_id"]),
        plan_revision=_int(mapping["plan_revision"]),
        teacher_id=_str(mapping["teacher_id"]),
        class_id=_str(mapping["class_id"]),
        assessment_id=_str(mapping["assessment_id"]),
        created_at=_datetime(mapping["created_at"]),
        revised_at=_datetime(mapping["revised_at"]),
        confirmed=_bool(mapping["confirmed"]),
        currentness=cast(BenchmarkPlanCurrentness, _str(mapping["currentness"])),
        report=teacher_report_preview_from_json_bytes(
            _json_bytes(mapping["report"]) + b"\n"
        ),
        previous_revision_sha256=_optional_str(mapping["previous_revision_sha256"]),
    )
    if benchmark_plan_to_json_bytes(revision) != data:
        raise BenchmarkPlanIntegrityError("plan JSON is not canonical.")
    return revision


def benchmark_plan_revisions_directory(
    workspace_root: str | Path, class_id: str, plan_id: str
) -> Path:
    root = Path(workspace_root)
    class_key = _identifier(class_id, "class_id")
    plan_key = storage_path_key("benchmark_plan", _identifier(plan_id, "plan_id"))
    return (
        class_module_dir(root, class_key, "meridian")
        / "benchmark_plans"
        / plan_key
        / "revisions"
    )


def write_benchmark_plan_revision(
    workspace_root: str | Path,
    revision: BenchmarkPlanRevision,
) -> BenchmarkPlanWriteResult:
    if not isinstance(revision, BenchmarkPlanRevision):
        raise BenchmarkPlanValidationError("revision must be a BenchmarkPlanRevision.")
    root = Path(workspace_root).resolve(strict=True)
    folder = benchmark_plan_revisions_directory(
        root, revision.class_id, revision.plan_id
    )
    _ensure_safe_directory_chain(root, folder)
    content = benchmark_plan_to_json_bytes(revision)
    if len(content) > DEFAULT_MAXIMUM_BENCHMARK_PLAN_BYTES:
        raise BenchmarkPlanValidationError("plan exceeds the size limit.")
    destination = folder / f"{revision.plan_revision}.json"
    if destination.exists():
        existing = _load_path(destination)
        if existing.content == content:
            return BenchmarkPlanWriteResult("existing", existing)
        raise BenchmarkPlanConflictError(
            "a different immutable plan revision already exists."
        )
    if revision.plan_revision > 1:
        predecessor = load_benchmark_plan_revision(
            root,
            revision.class_id,
            revision.plan_id,
            revision.plan_revision - 1,
        )
        if predecessor.revision_sha256 != revision.previous_revision_sha256:
            raise BenchmarkPlanConflictError(
                "plan predecessor changed before this revision was saved."
            )
        if (
            predecessor.revision.teacher_id != revision.teacher_id
            or predecessor.revision.assessment_id != revision.assessment_id
            or predecessor.revision.created_at != revision.created_at
        ):
            raise BenchmarkPlanConflictError(
                "plan identity fields cannot change between revisions."
            )
    digest = hashlib.sha256(content).hexdigest()
    # Publish the digest first. Readers enumerate only ``*.json`` revisions, so
    # the final JSON link is the commit point and cannot be observed half-written.
    _atomic_create(
        destination.with_suffix(".json.sha256"), (digest + "\n").encode()
    )
    try:
        _atomic_create(destination, content)
    except BenchmarkPlanStorageError:
        destination.with_suffix(".json.sha256").unlink(missing_ok=True)
        raise
    return BenchmarkPlanWriteResult("created", _load_path(destination))


def load_benchmark_plan_revision(
    workspace_root: str | Path,
    class_id: str,
    plan_id: str,
    plan_revision: int,
) -> StoredBenchmarkPlanRevision:
    if type(plan_revision) is not int or plan_revision < 1:
        raise BenchmarkPlanValidationError("plan_revision must be positive.")
    root = Path(workspace_root).resolve(strict=True)
    path = benchmark_plan_revisions_directory(root, class_id, plan_id) / (
        f"{plan_revision}.json"
    )
    if not path.exists():
        raise BenchmarkPlanNotFoundError("plan revision does not exist.")
    return _load_path(path)


def list_benchmark_plan_revisions(
    workspace_root: str | Path, class_id: str, plan_id: str
) -> tuple[int, ...]:
    root = Path(workspace_root).resolve(strict=True)
    folder = benchmark_plan_revisions_directory(root, class_id, plan_id)
    if not folder.exists():
        return ()
    if folder.is_symlink() or not folder.is_dir():
        raise BenchmarkPlanIntegrityError(
            "plan revision collection is not a regular directory."
        )
    revisions: list[int] = []
    for path in folder.iterdir():
        if path.name.endswith(".json.sha256"):
            continue
        if path.suffix != ".json" or not path.stem.isdigit() or path.is_symlink():
            raise BenchmarkPlanIntegrityError(
                "plan revision collection contains an unexpected entry."
            )
        revisions.append(int(path.stem))
    return tuple(sorted(revisions))


def load_latest_benchmark_plan_revision(
    workspace_root: str | Path, class_id: str, plan_id: str
) -> StoredBenchmarkPlanRevision:
    revisions = list_benchmark_plan_revisions(workspace_root, class_id, plan_id)
    if not revisions:
        raise BenchmarkPlanNotFoundError("plan does not have any revisions.")
    return load_benchmark_plan_revision(
        workspace_root, class_id, plan_id, revisions[-1]
    )


def _load_path(path: Path) -> StoredBenchmarkPlanRevision:
    if path.is_symlink() or not path.is_file():
        raise BenchmarkPlanIntegrityError(
            "plan revision must be a regular non-linked file."
        )
    if path.stat().st_size > DEFAULT_MAXIMUM_BENCHMARK_PLAN_BYTES:
        raise BenchmarkPlanIntegrityError("plan revision exceeds the size limit.")
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    sidecar = path.with_suffix(".json.sha256")
    if sidecar.is_symlink() or not sidecar.is_file():
        raise BenchmarkPlanIntegrityError("plan digest sidecar is missing.")
    try:
        recorded = sidecar.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise BenchmarkPlanIntegrityError("plan digest cannot be read.") from error
    if recorded != digest:
        raise BenchmarkPlanIntegrityError("plan digest does not match content.")
    revision = benchmark_plan_from_json_bytes(content)
    if path.name != f"{revision.plan_revision}.json":
        raise BenchmarkPlanIntegrityError(
            "plan revision filename does not match content."
        )
    return StoredBenchmarkPlanRevision(revision, digest, path, content)


def _to_dict(value: BenchmarkPlanRevision) -> dict[str, object]:
    if not isinstance(value, BenchmarkPlanRevision):
        raise BenchmarkPlanValidationError("value must be a BenchmarkPlanRevision.")
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "plan_id": value.plan_id,
        "plan_revision": value.plan_revision,
        "teacher_id": value.teacher_id,
        "class_id": value.class_id,
        "assessment_id": value.assessment_id,
        "created_at": value.created_at.isoformat(),
        "revised_at": value.revised_at.isoformat(),
        "confirmed": value.confirmed,
        "currentness": value.currentness,
        "report": teacher_report_preview_to_dict(value.report),
        "previous_revision_sha256": value.previous_revision_sha256,
    }


def _ensure_safe_directory_chain(root: Path, target: Path) -> None:
    try:
        target.relative_to(root)
    except ValueError as error:
        raise BenchmarkPlanIntegrityError(
            "plan storage path escapes the workspace."
        ) from error
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise BenchmarkPlanIntegrityError(
                    "plan storage path contains a linked or non-directory entry."
                )
        else:
            current.mkdir()


def _atomic_create(path: Path, content: bytes) -> None:
    if path.exists():
        raise BenchmarkPlanConflictError("plan storage target already exists.")
    descriptor, temporary = tempfile.mkstemp(prefix=".benchmark-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except OSError as error:
            if path.exists():
                raise BenchmarkPlanConflictError(
                    "plan storage target was created concurrently."
                ) from error
            raise BenchmarkPlanStorageError(
                "plan revision could not be saved."
            ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _mapping(value: object, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise BenchmarkPlanIntegrityError("plan contains missing or unexpected fields.")
    return cast(Mapping[str, object], value)


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise BenchmarkPlanIntegrityError("expected a string.")
    return value


def _optional_str(value: object) -> str | None:
    return None if value is None else _str(value)


def _int(value: object) -> int:
    if type(value) is not int:
        raise BenchmarkPlanIntegrityError("expected an integer.")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise BenchmarkPlanIntegrityError("expected a boolean.")
    return value


def _datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(_str(value))
    except ValueError as error:
        raise BenchmarkPlanIntegrityError("expected an ISO datetime.") from error
    return _utc(parsed, "datetime")


__all__ = [
    "BENCHMARK_PLAN_RECORD_TYPE",
    "BENCHMARK_PLAN_SCHEMA_VERSION",
    "BenchmarkPlanConflictError",
    "BenchmarkPlanIntegrityError",
    "BenchmarkPlanNotFoundError",
    "BenchmarkPlanRevision",
    "BenchmarkPlanStorageError",
    "BenchmarkPlanValidationError",
    "BenchmarkPlanWriteResult",
    "StoredBenchmarkPlanRevision",
    "benchmark_plan_from_json_bytes",
    "benchmark_plan_revisions_directory",
    "benchmark_plan_to_json_bytes",
    "list_benchmark_plan_revisions",
    "load_benchmark_plan_revision",
    "load_latest_benchmark_plan_revision",
    "write_benchmark_plan_revision",
]
