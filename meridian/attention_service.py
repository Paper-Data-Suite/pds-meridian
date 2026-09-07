"""Read-only orchestration for native Meridian attention inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import classes_dir
from pds_core.school_years import SchoolYearValidationError, validate_school_year

from meridian.academic_period_attention import (
    AcademicPeriodAttentionReadError,
    inspect_academic_period_attention_for_class,
)
from meridian.planning_attention import (
    PlanningAttentionReadError,
    inspect_planning_attention_for_class,
)
from meridian.proficiency_attention import (
    MeridianAttentionSummary,
    MeridianAttentionValidationError,
    merge_meridian_attention_summaries,
)


class MeridianAttentionReadError(RuntimeError):
    """Raised when a requested attention scope cannot be inspected safely."""

    code = "attention.read_failed"


@dataclass(frozen=True, slots=True)
class MeridianAttentionInspection:
    """One successful native attention inspection and its coverage state."""

    summary: MeridianAttentionSummary
    partial: bool
    evaluated_class_count: int
    failed_scope_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.summary, MeridianAttentionSummary):
            raise MeridianAttentionValidationError(
                "inspection summary must be a MeridianAttentionSummary."
            )
        if not isinstance(self.partial, bool):
            raise MeridianAttentionValidationError(
                "inspection partial must be boolean."
            )
        for name in ("evaluated_class_count", "failed_scope_count"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise MeridianAttentionValidationError(
                    f"inspection {name} must be a nonnegative integer."
                )
        if self.partial != (self.failed_scope_count > 0):
            raise MeridianAttentionValidationError(
                "inspection partial must exactly reflect failed_scope_count."
            )
        if self.partial and self.evaluated_class_count == 0:
            raise MeridianAttentionValidationError(
                "a partial inspection requires at least one evaluated class."
            )


def inspect_meridian_attention(
    workspace_root: str | Path,
    *,
    class_id: str | None = None,
    active_school_year: str | None = None,
) -> MeridianAttentionInspection:
    """Inspect one exact class or all discoverable classes without writing."""

    root = _workspace_root(workspace_root)
    school_year = _optional_school_year(active_school_year)

    if class_id is not None:
        class_value = _identifier(class_id, "class_id")
        _require_exact_class(root, class_value)
        summary = _inspect_class(root, class_value, school_year)
        return MeridianAttentionInspection(
            summary=summary,
            partial=False,
            evaluated_class_count=1,
            failed_scope_count=0,
        )

    class_ids, discovery_failures = _discover_workspace_class_ids(root)
    summaries: list[MeridianAttentionSummary] = []
    failed = discovery_failures
    for class_value in class_ids:
        try:
            summaries.append(_inspect_class(root, class_value, school_year))
        except MeridianAttentionReadError:
            failed += 1

    if failed and not summaries:
        raise MeridianAttentionReadError(
            "No Meridian class attention scope could be inspected safely."
        )

    try:
        merged = merge_meridian_attention_summaries(tuple(summaries))
    except MeridianAttentionValidationError as error:
        raise MeridianAttentionReadError(
            "Workspace-wide Meridian attention could not be aggregated safely."
        ) from error

    return MeridianAttentionInspection(
        summary=merged,
        partial=failed > 0,
        evaluated_class_count=len(summaries),
        failed_scope_count=failed,
    )


def _inspect_class(
    workspace_root: Path,
    class_id: str,
    active_school_year: str | None,
) -> MeridianAttentionSummary:
    try:
        planning = inspect_planning_attention_for_class(
            workspace_root,
            class_id,
            active_school_year=active_school_year,
        )
        academic_period = inspect_academic_period_attention_for_class(
            workspace_root,
            class_id,
            active_school_year=active_school_year,
        )
        return merge_meridian_attention_summaries((planning, academic_period))
    except (
        PlanningAttentionReadError,
        AcademicPeriodAttentionReadError,
        MeridianAttentionValidationError,
    ) as error:
        raise MeridianAttentionReadError(
            "The Meridian class attention scope could not be inspected safely."
        ) from error


def _discover_workspace_class_ids(
    workspace_root: Path,
) -> tuple[tuple[str, ...], int]:
    collection = classes_dir(workspace_root)
    if not collection.exists():
        return (), 0
    if collection.is_symlink() or not collection.is_dir():
        raise MeridianAttentionReadError(
            "The Core class collection is not a regular directory."
        )
    try:
        entries = tuple(sorted(collection.iterdir(), key=lambda item: item.name))
    except OSError as error:
        raise MeridianAttentionReadError(
            "The Core class collection could not be enumerated safely."
        ) from error

    class_ids: list[str] = []
    failed = 0
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_symlink() or not entry.is_dir():
                failed += 1
                continue
            class_ids.append(validate_identifier(entry.name, "class_id"))
        except (IdentifierValidationError, OSError):
            failed += 1
    return tuple(class_ids), failed


def _require_exact_class(workspace_root: Path, class_id: str) -> None:
    path = classes_dir(workspace_root) / class_id
    try:
        valid = path.exists() and not path.is_symlink() and path.is_dir()
    except OSError as error:
        raise MeridianAttentionReadError(
            "The requested Core class could not be inspected safely."
        ) from error
    if not valid:
        raise MeridianAttentionReadError(
            "The requested Core class does not exist as a regular class directory."
        )


def _workspace_root(value: str | Path) -> Path:
    root = Path(value).resolve()
    try:
        valid = root.exists() and root.is_dir()
    except OSError as error:
        raise MeridianAttentionReadError(
            "The requested workspace cannot be inspected safely."
        ) from error
    if not valid:
        raise MeridianAttentionReadError(
            "The requested workspace does not exist as a directory."
        )
    return root


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise MeridianAttentionReadError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise MeridianAttentionReadError(str(error)) from error


def _optional_school_year(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_school_year(value)
    except SchoolYearValidationError as error:
        raise MeridianAttentionReadError(str(error)) from error


__all__ = [
    "MeridianAttentionInspection",
    "MeridianAttentionReadError",
    "inspect_meridian_attention",
]
