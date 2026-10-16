"""Lossless, source-bound teacher notes for immutable benchmark-plan revisions.

The original benchmark revision remains canonical. A separate append-only,
SHA-256 checked annotation record permits exact draft restoration without
adding opaque metadata to printable teacher reports. Legacy records lacking
notes stay readable but cannot be reconstructed as editable typed drafts.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Literal, cast

from meridian.benchmark_analysis import (
    BenchmarkInstructionalGroup,
    InstructionalResponse,
    InterventionStatus,
    TargetedInstructionResult,
)
from meridian.benchmark_plan_authoring import (
    BenchmarkTeacherAnnotations,
    TeacherStandardAssessment,
    TeacherStandardJudgment,
    compose_teacher_benchmark_plan,
)
from meridian.benchmark_plan_storage import StoredBenchmarkPlanRevision

_MAX_BYTES = 8 * 1024 * 1024


class BenchmarkPlanNotesError(RuntimeError):
    """Saved notes are missing, corrupt, stale, or not safely accessible."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _obj(value: object, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise BenchmarkPlanNotesError("Annotation record has unexpected fields.")
    mapping = cast(dict[str, object], value)
    if frozenset(mapping) != fields:
        raise BenchmarkPlanNotesError("Annotation record has unexpected fields.")
    return mapping


def _string(value: object) -> str:
    if type(value) is not str:
        raise BenchmarkPlanNotesError("Annotation field is not text.")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise BenchmarkPlanNotesError("Annotation confirmation is not boolean.")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise BenchmarkPlanNotesError("Annotation member list is invalid.")
    return tuple(_string(item) for item in cast(list[object], value))


def _objects(value: object) -> list[object]:
    if type(value) is not list:
        raise BenchmarkPlanNotesError("Annotation list is invalid.")
    return cast(list[object], value)


def _date(value: object) -> date:
    try:
        parsed = date.fromisoformat(_string(value))
    except ValueError as error:
        raise BenchmarkPlanNotesError("Annotation date is invalid.") from error
    if parsed.isoformat() != value:
        raise BenchmarkPlanNotesError("Annotation date is not canonical.")
    return parsed


def _maybe_date(value: object) -> date | None:
    return None if value is None else _date(value)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkPlanNotesError("Duplicate annotation JSON key.")
        result[key] = value
    return result


def _to_dict(value: BenchmarkTeacherAnnotations) -> dict[str, object]:
    return {
        "interpretation": value.interpretation,
        "standards": [
            {
                "standard_id": item.standard_id,
                "judgment": item.judgment,
                "basis": item.basis,
                "comparable_evidence_confirmed": item.comparable_evidence_confirmed,
            }
            for item in value.standards
        ],
        "groups": [
            {
                "group_id": item.group_id,
                "label": item.label,
                "student_ids": list(item.student_ids),
                "rationale": item.rationale,
            }
            for item in value.groups
        ],
        "responses": [
            {
                "response_id": item.response_id,
                "response_kind": item.response_kind,
                "target": item.target,
                "student_ids": list(item.student_ids),
                "strategy_resource": item.strategy_resource,
                "planned_date": item.planned_date.isoformat()
                if item.planned_date else None,
                "reevaluation_date": item.reevaluation_date.isoformat()
                if item.reevaluation_date else None,
                "rework_items": list(item.rework_items),
                "retest_targets": list(item.retest_targets),
                "status": item.status,
                "teacher_reflection": item.teacher_reflection,
            }
            for item in value.responses
        ],
        "follow_up": None if value.follow_up is None else {
            "reassessment_tool": value.follow_up.reassessment_tool,
            "reassessment_date": value.follow_up.reassessment_date.isoformat(),
            "follow_up_results": value.follow_up.follow_up_results,
            "students_still_needing_support": list(
                value.follow_up.students_still_needing_support
            ),
            "standards_needing_attention": list(
                value.follow_up.standards_needing_attention
            ),
            "additional_support_strategy": value.follow_up.additional_support_strategy,
            "teacher_observations": value.follow_up.teacher_observations,
            "follow_up_source_id": value.follow_up.follow_up_source_id,
            "comparison_basis": value.follow_up.comparison_basis,
        },
    }


def _from_dict(value: object) -> BenchmarkTeacherAnnotations:
    fields = frozenset({
        "interpretation", "standards", "groups", "responses", "follow_up",
    })
    data = _obj(value, fields)
    standard_fields = frozenset({
        "standard_id", "judgment", "basis", "comparable_evidence_confirmed",
    })
    group_fields = frozenset({"group_id", "label", "student_ids", "rationale"})
    response_fields = frozenset({
        "response_id", "response_kind", "target", "student_ids",
        "strategy_resource", "planned_date", "reevaluation_date", "rework_items",
        "retest_targets", "status", "teacher_reflection",
    })
    followup_fields = frozenset({
        "reassessment_tool", "reassessment_date", "follow_up_results",
        "students_still_needing_support", "standards_needing_attention",
        "additional_support_strategy", "teacher_observations", "follow_up_source_id",
        "comparison_basis",
    })
    standards = []
    for entry in _objects(data["standards"]):
        item = _obj(entry, standard_fields)
        standards.append(TeacherStandardAssessment(
            _string(item["standard_id"]),
            cast(TeacherStandardJudgment, _string(item["judgment"])),
            _string(item["basis"]),
            _boolean(item["comparable_evidence_confirmed"]),
        ))
    groups = []
    for entry in _objects(data["groups"]):
        item = _obj(entry, group_fields)
        groups.append(BenchmarkInstructionalGroup(
            _string(item["group_id"]), _string(item["label"]),
            _strings(item["student_ids"]), _string(item["rationale"]),
        ))
    responses = []
    for entry in _objects(data["responses"]):
        item = _obj(entry, response_fields)
        responses.append(InstructionalResponse(
            response_id=_string(item["response_id"]),
            response_kind=cast(
                Literal["reteach", "revisit", "small_group", "enrichment", "extension"],
                _string(item["response_kind"]),
            ),
            target=_string(item["target"]),
            student_ids=_strings(item["student_ids"]),
            strategy_resource=_string(item["strategy_resource"]),
            planned_date=_maybe_date(item["planned_date"]),
            reevaluation_date=_maybe_date(item["reevaluation_date"]),
            rework_items=_strings(item["rework_items"]),
            retest_targets=_strings(item["retest_targets"]),
            status=cast(InterventionStatus, _string(item["status"])),
            teacher_reflection=_string(item["teacher_reflection"]),
        ))
    follow_up: TargetedInstructionResult | None = None
    if data["follow_up"] is not None:
        item = _obj(data["follow_up"], followup_fields)
        follow_up = TargetedInstructionResult(
            reassessment_tool=_string(item["reassessment_tool"]),
            reassessment_date=_date(item["reassessment_date"]),
            follow_up_results=_string(item["follow_up_results"]),
            students_still_needing_support=_strings(
                item["students_still_needing_support"]
            ),
            standards_needing_attention=_strings(item["standards_needing_attention"]),
            additional_support_strategy=_string(item["additional_support_strategy"]),
            teacher_observations=_string(item["teacher_observations"]),
            follow_up_source_id=_optional_string(item["follow_up_source_id"]),
            comparison_basis=_optional_string(item["comparison_basis"]),
        )
    return BenchmarkTeacherAnnotations(
        interpretation=_string(data["interpretation"]),
        standards=tuple(standards),
        groups=tuple(groups),
        responses=tuple(responses),
        follow_up=follow_up,
    )


def _paths(stored: StoredBenchmarkPlanRevision) -> tuple[Path, Path]:
    # Plan location comes from the verified, bounded, immutable plan store.
    folder = stored.path.parent.parent / "teacher_annotations"
    return folder / f"{stored.revision.plan_revision}.json", folder


def _safe_folders(root: Path, folder: Path) -> None:
    try:
        parts = folder.relative_to(root).parts
    except ValueError as error:
        raise BenchmarkPlanNotesError("Notes path escapes the workspace.") from error
    current = root
    if current.is_symlink() or not current.is_dir():
        raise BenchmarkPlanNotesError("Workspace path is not a regular directory.")
    for component in parts:
        current = current / component
        if current.is_symlink():
            raise BenchmarkPlanNotesError("Notes path uses a symlink.")
        if current.exists():
            if not current.is_dir():
                raise BenchmarkPlanNotesError("Notes path is not a directory.")
        else:
            current.mkdir()


def _atomic_new(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise BenchmarkPlanNotesError("Notes revision already exists.")
    descriptor, temporary = tempfile.mkstemp(
        prefix=".benchmark-notes-", dir=path.parent
    )
    temp = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, path)
        except OSError as error:
            raise BenchmarkPlanNotesError(
                "Notes revision could not be published."
            ) from error
    finally:
        temp.unlink(missing_ok=True)


def _verification_roster_ids(
    stored: StoredBenchmarkPlanRevision,
    annotations: BenchmarkTeacherAnnotations,
) -> tuple[str, ...]:
    """Recover the source roster *size* for deterministic rendering only.

    The original writer already validated student IDs against the real Core
    roster. The saved report retains roster size but not every roster ID.
    Placeholder IDs here cannot authorize student access or change stored notes.
    """
    members = {
        student_id
        for group in annotations.groups
        for student_id in group.student_ids
    }
    for response in annotations.responses:
        members.update(response.student_ids)
    if annotations.follow_up is not None:
        members.update(annotations.follow_up.students_still_needing_support)
    counts = [
        row.values[3]
        for row in stored.revision.report.rows
        if row.values[0] == "1. Assessment Data"
        and row.values[1] == "Participation"
        and row.values[2] == "Students on roster"
        and row.values[6] == "no"
    ]
    if len(counts) != 1:
        raise BenchmarkPlanNotesError("Saved benchmark roster count is unavailable.")
    raw_count = counts[0]
    if (
        raw_count is None
        or not raw_count.isascii()
        or not raw_count.isdecimal()
        or len(raw_count) > 5
    ):
        raise BenchmarkPlanNotesError("Saved benchmark roster count is invalid.")
    count = int(raw_count)
    if str(count) != raw_count or count > 10_000 or count < len(members):
        raise BenchmarkPlanNotesError("Saved benchmark roster count is inconsistent.")
    number = 0
    while len(members) < count:
        number += 1
        # Rendering-only stand-ins for students not selected into a plan.
        members.add(f"__benchmark_verification_{number}")
    return tuple(sorted(members))


def _verify_annotations_match_report(
    stored: StoredBenchmarkPlanRevision,
    annotations: BenchmarkTeacherAnnotations,
) -> None:
    try:
        verification = compose_teacher_benchmark_plan(
            stored.revision.report,
            annotations,
            roster_student_ids=_verification_roster_ids(stored, annotations),
        )
    except ValueError as error:
        raise BenchmarkPlanNotesError(
            "Teacher notes do not reproduce their saved plan."
        ) from error
    if verification.preview_sha256 != stored.revision.report.preview_sha256:
        raise BenchmarkPlanNotesError(
            "Teacher notes do not reproduce their saved plan."
        )


def save_benchmark_plan_notes(
    workspace_root: str | Path,
    stored: StoredBenchmarkPlanRevision,
    annotations: BenchmarkTeacherAnnotations,
) -> None:
    """Append an exact lossless record bound to the saved plan SHA-256."""
    if not isinstance(annotations, BenchmarkTeacherAnnotations):
        raise BenchmarkPlanNotesError("Only typed teacher notes may be persisted.")
    _verify_annotations_match_report(stored, annotations)
    root = Path(workspace_root).resolve(strict=True)
    path, folder = _paths(stored)
    _safe_folders(root, folder)
    body = {
        "schema_version": "1",
        "record_type": "meridian_benchmark_teacher_annotations",
        "plan_id": stored.revision.plan_id,
        "plan_revision": stored.revision.plan_revision,
        "plan_sha256": stored.revision_sha256,
        "annotations": _to_dict(annotations),
    }
    payload = _canonical(body)
    if len(payload) > _MAX_BYTES:
        raise BenchmarkPlanNotesError("Teacher notes exceed the size limit.")
    sidecar = path.with_suffix(".json.sha256")
    if path.exists() or sidecar.exists() or path.is_symlink() or sidecar.is_symlink():
        existing = load_benchmark_plan_notes(root, stored)
        if existing == annotations and existing is not None:
            return
        raise BenchmarkPlanNotesError(
            "Different notes already exist for this revision."
        )
    _atomic_new(sidecar, (hashlib.sha256(payload).hexdigest() + "\n").encode("ascii"))
    try:
        _atomic_new(path, payload)
    except BenchmarkPlanNotesError:
        sidecar.unlink(missing_ok=True)
        raise


def load_benchmark_plan_notes(
    workspace_root: str | Path,
    stored: StoredBenchmarkPlanRevision,
) -> BenchmarkTeacherAnnotations | None:
    """Return None only for genuinely legacy, unannotated plan revisions."""
    root = Path(workspace_root).resolve(strict=True)
    path, folder = _paths(stored)
    # Never create folders while reading historical notes.
    try:
        parts = folder.relative_to(root).parts
    except ValueError as error:
        raise BenchmarkPlanNotesError("Notes path escapes the workspace.") from error
    current = root
    for component in parts:
        current = current / component
        if current.is_symlink():
            raise BenchmarkPlanNotesError("Notes path uses a symlink.")
        if current.exists() and not current.is_dir():
            raise BenchmarkPlanNotesError("Notes path is not a directory.")
        if not current.exists():
            return None
    sidecar = path.with_suffix(".json.sha256")
    if (
        not path.exists() and not path.is_symlink()
        and not sidecar.exists() and not sidecar.is_symlink()
    ):
        return None
    if (
        path.is_symlink() or sidecar.is_symlink()
        or not path.is_file() or not sidecar.is_file()
    ):
        raise BenchmarkPlanNotesError("Annotation record is missing or linked.")
    if path.stat().st_size > _MAX_BYTES:
        raise BenchmarkPlanNotesError("Annotation record exceeds the size limit.")
    payload = path.read_bytes()
    try:
        recorded = sidecar.read_text("ascii").strip()
    except (OSError, UnicodeError) as error:
        raise BenchmarkPlanNotesError("Annotation digest is unreadable.") from error
    if hashlib.sha256(payload).hexdigest() != recorded:
        raise BenchmarkPlanNotesError("Annotation digest does not match content.")
    try:
        raw = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError) as error:
        raise BenchmarkPlanNotesError("Annotation JSON is invalid.") from error
    body = _obj(raw, frozenset({
        "schema_version", "record_type", "plan_id", "plan_revision",
        "plan_sha256", "annotations",
    }))
    if (
        body["schema_version"] != "1"
        or body["record_type"] != "meridian_benchmark_teacher_annotations"
        or body["plan_id"] != stored.revision.plan_id
        or type(body["plan_revision"]) is not int
        or body["plan_revision"] != stored.revision.plan_revision
        or body["plan_sha256"] != stored.revision_sha256
    ):
        raise BenchmarkPlanNotesError("Annotation source or plan identity changed.")
    try:
        annotations = _from_dict(body["annotations"])
    except (ValueError, TypeError) as error:
        raise BenchmarkPlanNotesError("Typed annotations are invalid.") from error
    if (
        _canonical(body) != payload
        or _canonical(_to_dict(annotations)) != _canonical(body["annotations"])
    ):
        raise BenchmarkPlanNotesError("Annotation JSON is not canonical.")
    _verify_annotations_match_report(stored, annotations)
    return annotations


__all__ = (
    "BenchmarkPlanNotesError",
    "load_benchmark_plan_notes",
    "save_benchmark_plan_notes",
)
