"""Read-only Grade/report attention derived from canonical Meridian state.

Issue #58 extends Meridian's existing attention system without inventing a
parallel currentness model.  This slice implements only the safest reporting
fact: an explicit ``replaces_for_current_use`` successor while the exact
predecessor remains the explicit current-use ReportingSnapshot selection.

Snapshot timestamps, lexical order, mere snapshot existence, exportability,
and absent selections are deliberately not attention authority.
"""

from __future__ import annotations

from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir
from pds_core.school_years import SchoolYearValidationError, validate_school_year

from meridian.proficiency_attention import (
    MAX_MERIDIAN_ATTENTION_COUNT,
    MeridianAttentionItem,
    MeridianAttentionSummary,
    build_meridian_attention_summary,
)
from meridian.reporting_snapshot_record import ReportingSnapshot
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionError,
    ReportingSnapshotSelectionReference,
    load_current_reporting_snapshot_selection,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    list_reporting_snapshot_ids,
    load_reporting_snapshot,
)


class GradeReportAttentionError(RuntimeError):
    """Base error for bounded Grade/report attention inspection."""


class GradeReportAttentionReadError(GradeReportAttentionError):
    """Raised when canonical Grade/report attention cannot be read safely."""

    code = "grade_report_attention.read_failed"


class GradeReportAttentionIntegrityError(GradeReportAttentionReadError):
    """Raised when reporting state cannot support a trustworthy attention fact."""

    code = "grade_report_attention.integrity_failed"


ReportingScopeKey = tuple[str, str, str, int]


def inspect_grade_report_attention_for_class(
    workspace_root: str | Path,
    class_id: str,
    *,
    active_school_year: str | None = None,
) -> MeridianAttentionSummary:
    """Inspect safely provable Grade/report attention for one exact class.

    This slice derives only ``meridian_reporting_snapshot_selection_pending``.
    One count represents one exact reporting scope, even if more than one
    immutable successor names the same selected predecessor.
    """

    root = Path(workspace_root).resolve()
    class_value = _identifier(class_id, "class_id")
    school_year = _optional_school_year(active_school_year)
    _require_exact_class(root, class_value)

    try:
        snapshot_ids = list_reporting_snapshot_ids(root, class_value)
        if len(snapshot_ids) > MAX_MERIDIAN_ATTENTION_COUNT:
            raise GradeReportAttentionReadError(
                "ReportingSnapshot count exceeds the bounded attention maximum."
            )

        pending: dict[
            ReportingScopeKey,
            ReportingSnapshotSelectionReference,
        ] = {}
        for snapshot_id in snapshot_ids:
            successor = load_reporting_snapshot(
                root,
                class_value,
                snapshot_id,
            )
            snapshot = successor.snapshot
            if (
                school_year is not None
                and snapshot.target_period.school_year != school_year
            ):
                continue

            predecessor_link = snapshot.predecessor
            if (
                predecessor_link is None
                or predecessor_link.relationship != "replaces_for_current_use"
            ):
                continue

            predecessor = load_reporting_snapshot(
                root,
                class_value,
                predecessor_link.snapshot_reference.snapshot_id,
            )
            if predecessor.reference != predecessor_link.snapshot_reference:
                raise GradeReportAttentionIntegrityError(
                    "ReportingSnapshot replacement predecessor changed unexpectedly."
                )
            if _reporting_scope(snapshot) != _reporting_scope(
                predecessor.snapshot
            ):
                # The immutable relationship is real, but it cannot prove a
                # replacement pending in one current-use selector scope.
                continue

            definition_id = snapshot.definition_reference.definition_id
            selected = load_current_reporting_snapshot_selection(
                root,
                class_value,
                definition_id,
                snapshot.target_period,
                snapshot.calendar_revision,
            )
            if selected is None:
                continue
            if selected.selection.snapshot_reference != predecessor.reference:
                continue

            scope = _reporting_scope(snapshot)
            observed = pending.get(scope)
            if observed is not None and observed != selected.reference:
                raise GradeReportAttentionReadError(
                    "ReportingSnapshot current-use selection changed during inspection."
                )
            pending[scope] = selected.reference

        _revalidate_pending_selections(root, class_value, pending)
    except GradeReportAttentionReadError:
        raise
    except (
        ReportingSnapshotStorageError,
        ReportingSnapshotSelectionError,
        OSError,
        ValueError,
    ) as error:
        raise GradeReportAttentionReadError(
            "Canonical Grade/report attention could not be inspected safely."
        ) from error

    items: tuple[MeridianAttentionItem, ...] = ()
    if pending:
        items = (
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_selection_pending",
                count=len(pending),
                class_id=class_value,
            ),
        )
    return build_meridian_attention_summary(items)


def _revalidate_pending_selections(
    workspace_root: Path,
    class_id: str,
    pending: dict[ReportingScopeKey, ReportingSnapshotSelectionReference],
) -> None:
    """Fail closed if mutable selector authority moves during inspection."""

    for scope in sorted(pending):
        definition_id, school_year, period_id, calendar_revision = scope
        current = load_current_reporting_snapshot_selection(
            workspace_root,
            class_id,
            definition_id,
            AcademicPeriodRef(school_year, period_id),
            calendar_revision,
        )
        if current is None or current.reference != pending[scope]:
            raise GradeReportAttentionReadError(
                "ReportingSnapshot current-use selection changed during inspection."
            )


def _reporting_scope(snapshot: ReportingSnapshot) -> ReportingScopeKey:
    return (
        snapshot.definition_reference.definition_id,
        snapshot.target_period.school_year,
        snapshot.target_period.period_id,
        snapshot.calendar_revision,
    )


def _require_exact_class(workspace_root: Path, class_id: str) -> None:
    path = class_dir(workspace_root, class_id)
    try:
        valid = path.exists() and not path.is_symlink() and path.is_dir()
    except OSError as error:
        raise GradeReportAttentionReadError(
            "The requested Core class could not be inspected safely."
        ) from error
    if not valid:
        raise GradeReportAttentionReadError(
            "The requested Core class does not exist as a regular class directory."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradeReportAttentionIntegrityError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradeReportAttentionIntegrityError(str(error)) from error


def _optional_school_year(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_school_year(value)
    except SchoolYearValidationError as error:
        raise GradeReportAttentionReadError(str(error)) from error


__all__ = [
    "GradeReportAttentionError",
    "GradeReportAttentionIntegrityError",
    "GradeReportAttentionReadError",
    "inspect_grade_report_attention_for_class",
]
