"""Read-only Grade/report attention derived from canonical Meridian state.

Issue #58 extends Meridian's existing attention system without inventing a
parallel currentness model.  This slice implements only the safest reporting
fact: an explicit ``replaces_for_current_use`` successor while the exact
predecessor remains the explicit current-use ReportingSnapshot selection.

Snapshot timestamps, lexical order, mere snapshot existence, exportability,
and absent selections are deliberately not attention authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir
from pds_core.school_years import SchoolYearValidationError, validate_school_year

from meridian.grade_preview_comparison import compare_grade_preview_basis
from meridian.grade_preview_explanation import (
    GradePreviewError,
    GradePreviewSourceError,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
)
from meridian.proficiency_attention import (
    MAX_MERIDIAN_ATTENTION_COUNT,
    MeridianAttentionItem,
    MeridianAttentionSummary,
    build_meridian_attention_summary,
)
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonError,
    reporting_snapshot_prior_grade_basis,
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
from meridian.standards_grade_assembly import (
    StandardsGradeAssemblyError,
    assemble_standards_grade_calculation,
)
from meridian.standards_grade_result import (
    StandardsGradeResultReference,
    StandardsGradeResultValidationError,
    assess_standards_grade_result_freshness,
)
from meridian.standards_grade_storage import (
    DEFAULT_MAXIMUM_STANDARDS_GRADE_POINTER_BYTES,
    STANDARDS_GRADE_RESULT_CURRENT_RECORD_TYPE,
    STANDARDS_GRADE_RESULT_CURRENT_SCHEMA_VERSION,
    StandardsGradeStorageError,
    StoredStandardsGradeResult,
    load_current_standards_grade_result,
    standards_grade_result_current_path,
    standards_grade_subject_key,
    standards_grades_directory,
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
StandardsGradeTargetKey = tuple[str, str, str, int]

_STANDARDS_GRADE_CURRENT_POINTER_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "student_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "subject_key",
        "result_revision",
        "result_sha256",
    }
)


def inspect_grade_report_attention_for_class(
    workspace_root: str | Path,
    class_id: str,
    *,
    active_school_year: str | None = None,
) -> MeridianAttentionSummary:
    """Inspect safely provable Grade/report attention for one exact class.

    The neutral Core v1 boundary can safely reconstruct standards-based Grade
    freshness from Meridian/Core canonical state, so selected stale standards
    Grade targets are included. Conventional and hybrid freshness remains omitted
    here because those families require caller-supplied protected work evidence.

    ReportingSnapshot replacement attention remains one count per exact reporting
    scope, even if more than one immutable successor names the same selected
    predecessor. Selected current-use snapshots are also compared against live
    standards-based Grade observations when that comparison is safely resolvable.
    Conventional and hybrid rows remain outside the neutral Core v1 evidence
    boundary and therefore cannot make a snapshot refresh claim here.
    """

    root = Path(workspace_root).resolve()
    class_value = _identifier(class_id, "class_id")
    school_year = _optional_school_year(active_school_year)
    _require_exact_class(root, class_value)

    try:
        stale_grades: dict[
            StandardsGradeTargetKey, StandardsGradeResultReference
        ] = {}
        selected_standards = _discover_current_standards_grade_results(
            root,
            class_value,
            active_school_year=school_year,
        )
        for stored in selected_standards:
            if not _selected_standards_grade_result_is_stale(root, stored):
                continue
            key = _standards_grade_target_key(stored)
            previous = stale_grades.get(key)
            if previous is not None and previous != stored.reference:
                raise GradeReportAttentionReadError(
                    "Duplicate selected standards Grade target changed during "
                "inspection."
                )
            stale_grades[key] = stored.reference
        _revalidate_stale_grade_selections(root, class_value, stale_grades)

        snapshot_ids = list_reporting_snapshot_ids(root, class_value)
        if len(snapshot_ids) > MAX_MERIDIAN_ATTENTION_COUNT:
            raise GradeReportAttentionReadError(
                "ReportingSnapshot count exceeds the bounded attention maximum."
            )

        reporting_scopes: set[ReportingScopeKey] = set()
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

            reporting_scopes.add(_reporting_scope(snapshot))
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

        _revalidate_reporting_selections(root, class_value, pending)

        refresh_needed: dict[
            ReportingScopeKey,
            ReportingSnapshotSelectionReference,
        ] = {}
        for scope in sorted(reporting_scopes):
            definition_id, scope_year, period_id, calendar_revision = scope
            selected = load_current_reporting_snapshot_selection(
                root,
                class_value,
                definition_id,
                AcademicPeriodRef(scope_year, period_id),
                calendar_revision,
            )
            if selected is None:
                continue
            selected_snapshot = load_reporting_snapshot(
                root,
                class_value,
                selected.selection.snapshot_reference.snapshot_id,
            )
            if selected_snapshot.reference != selected.selection.snapshot_reference:
                raise GradeReportAttentionIntegrityError(
                    "Selected ReportingSnapshot changed unexpectedly."
                )
            if _reporting_scope(selected_snapshot.snapshot) != scope:
                raise GradeReportAttentionIntegrityError(
                    "Selected ReportingSnapshot crosses its selector scope."
                )
            if not _selected_reporting_snapshot_needs_refresh(
                root, selected_snapshot.snapshot
            ):
                continue
            refresh_needed[scope] = selected.reference

        _revalidate_reporting_selections(root, class_value, refresh_needed)
    except GradeReportAttentionReadError:
        raise
    except (
        GradePreviewError,
        ReportingSnapshotComparisonError,
        ReportingSnapshotStorageError,
        ReportingSnapshotSelectionError,
        StandardsGradeAssemblyError,
        StandardsGradeResultValidationError,
        StandardsGradeStorageError,
        OSError,
        ValueError,
    ) as error:
        raise GradeReportAttentionReadError(
            "Canonical Grade/report attention could not be inspected safely."
        ) from error

    items: list[MeridianAttentionItem] = []
    if stale_grades:
        items.append(
            MeridianAttentionItem(
                code="meridian_grade_result_stale",
                count=len(stale_grades),
                class_id=class_value,
            )
        )
    if refresh_needed:
        items.append(
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_refresh_needed",
                count=len(refresh_needed),
                class_id=class_value,
            )
        )
    if pending:
        items.append(
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_selection_pending",
                count=len(pending),
                class_id=class_value,
            )
        )
    return build_meridian_attention_summary(tuple(items))


def _discover_current_standards_grade_results(
    workspace_root: Path,
    class_id: str,
    *,
    active_school_year: str | None,
) -> tuple[StoredStandardsGradeResult, ...]:
    """Discover exact selected standards Grade results from canonical pointers."""

    collection = standards_grades_directory(workspace_root, class_id)
    if not collection.exists():
        return ()
    if collection.is_symlink() or not collection.is_dir():
        raise GradeReportAttentionReadError(
            "Standards Grade result collection is not a regular directory."
        )

    pointers = tuple(
        sorted(collection.rglob("current.json"), key=lambda path: path.as_posix())
    )
    if len(pointers) > MAX_MERIDIAN_ATTENTION_COUNT:
        raise GradeReportAttentionReadError(
            "Selected standards Grade target count exceeds the bounded "
            "attention maximum."
        )

    selected: list[StoredStandardsGradeResult] = []
    seen: set[StandardsGradeTargetKey] = set()
    for pointer in pointers:
        _require_regular_path_below(collection, pointer)
        data = _read_standards_grade_current_pointer(pointer)
        pointer_class = _required_identifier(data, "class_id")
        if pointer_class != class_id:
            raise GradeReportAttentionReadError(
                "Standards Grade current pointer crosses class scope."
            )
        school_year = _required_school_year(data, "school_year")
        if active_school_year is not None and school_year != active_school_year:
            continue
        student_id = _required_identifier(data, "student_id")
        period_id = _required_identifier(data, "period_id")
        calendar_revision = _required_positive_int(data, "calendar_revision")
        period = AcademicPeriodRef(school_year, period_id)
        expected = standards_grade_result_current_path(
            workspace_root,
            class_id,
            student_id,
            period,
            calendar_revision,
        )
        if pointer != expected:
            raise GradeReportAttentionReadError(
                "Standards Grade current pointer is not at its canonical path."
            )
        if data["subject_key"] != standards_grade_subject_key(
            class_id, student_id, period, calendar_revision
        ):
            raise GradeReportAttentionReadError(
                "Standards Grade current pointer subject key is invalid."
            )
        stored = load_current_standards_grade_result(
            workspace_root,
            class_id,
            student_id,
            period,
            calendar_revision,
        )
        if stored is None:
            raise GradeReportAttentionReadError(
                "Discovered standards Grade current pointer did not resolve."
            )
        key = _standards_grade_target_key(stored)
        if key in seen:
            raise GradeReportAttentionReadError(
                "Standards Grade current pointer duplicates a logical target."
            )
        seen.add(key)
        selected.append(stored)
    return tuple(selected)


def _selected_standards_grade_result_is_stale(
    workspace_root: Path,
    stored: StoredStandardsGradeResult,
) -> bool:
    """Apply the authoritative standards Grade freshness contract read-only."""

    snapshot = stored.snapshot
    assembly = assemble_standards_grade_calculation(
        workspace_root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    freshness = assess_standards_grade_result_freshness(
        snapshot,
        assembly.inputs,
    )
    current = load_current_standards_grade_result(
        workspace_root,
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    if current is None or current.reference != stored.reference:
        raise GradeReportAttentionReadError(
            "Standards Grade current selection changed during freshness inspection."
        )
    return freshness.status == "stale"


def _revalidate_stale_grade_selections(
    workspace_root: Path,
    class_id: str,
    stale: dict[StandardsGradeTargetKey, StandardsGradeResultReference],
) -> None:
    """Fail closed if any stale-result selector moves before summary return."""

    for key in sorted(stale):
        student_id, school_year, period_id, calendar_revision = key
        current = load_current_standards_grade_result(
            workspace_root,
            class_id,
            student_id,
            AcademicPeriodRef(school_year, period_id),
            calendar_revision,
        )
        if current is None or current.reference != stale[key]:
            raise GradeReportAttentionReadError(
                "Standards Grade current selection changed during attention inspection."
            )


def _standards_grade_target_key(
    stored: StoredStandardsGradeResult,
) -> StandardsGradeTargetKey:
    snapshot = stored.snapshot
    return (
        snapshot.student_id,
        snapshot.target_period.school_year,
        snapshot.target_period.period_id,
        snapshot.calendar_revision,
    )


def _read_standards_grade_current_pointer(path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise GradeReportAttentionReadError(
            "Could not inspect a standards Grade current pointer."
        ) from error
    if size <= 0 or size > DEFAULT_MAXIMUM_STANDARDS_GRADE_POINTER_BYTES:
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer has invalid size."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer is unreadable."
        ) from error
    if not isinstance(data, dict) or frozenset(data) != (
        _STANDARDS_GRADE_CURRENT_POINTER_KEYS
    ):
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer shape is invalid."
        )
    if data["schema_version"] != STANDARDS_GRADE_RESULT_CURRENT_SCHEMA_VERSION:
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer schema is unsupported."
        )
    if data["record_type"] != STANDARDS_GRADE_RESULT_CURRENT_RECORD_TYPE:
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer record type is invalid."
        )
    return cast(dict[str, object], data)


def _required_identifier(data: dict[str, object], field: str) -> str:
    return _identifier(data[field], field)


def _required_school_year(data: dict[str, object], field: str) -> str:
    value = data[field]
    if not isinstance(value, str):
        raise GradeReportAttentionReadError(f"{field} must be a string.")
    try:
        return validate_school_year(value)
    except SchoolYearValidationError as error:
        raise GradeReportAttentionReadError(str(error)) from error


def _required_positive_int(data: dict[str, object], field: str) -> int:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GradeReportAttentionReadError(
            f"{field} must be a positive integer."
        )
    return value


def _require_regular_path_below(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise GradeReportAttentionReadError(
            "Standards Grade pointer escaped its canonical collection."
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise GradeReportAttentionReadError(
                "Standards Grade attention refuses symlinked state."
            )
    if not path.is_file():
        raise GradeReportAttentionReadError(
            "Standards Grade current pointer is not a regular file."
        )


def _selected_reporting_snapshot_needs_refresh(
    workspace_root: Path,
    snapshot: ReportingSnapshot,
) -> bool:
    """Return true only for safely proven material standards-row changes.

    A selected ReportingSnapshot may contain conventional, standards-based, and
    hybrid rows. The neutral Core v1 request has no protected-evidence capability,
    so only standards-based rows are reconstructed here. An unavailable current
    standards basis is omitted rather than treated as changed.
    """

    for request in snapshot.build_request.grade_requests:
        target = request.target
        if target.calculation_family != "standards_based":
            continue
        prior = reporting_snapshot_prior_grade_basis(snapshot, target)
        try:
            preview = explain_grade_report_preview(
                workspace_root,
                (GradeReportPreviewRequest(target=target),),
            )
        except GradePreviewSourceError:
            # Current state exists but cannot be safely resolved at this neutral
            # boundary. Issue #58 requires omission instead of a guessed claim.
            continue
        if len(preview.rows) != 1 or preview.rows[0].target != target:
            raise GradeReportAttentionIntegrityError(
                "Standards Grade report preview did not preserve its exact target."
            )
        current = preview.rows[0].observation
        if prior is None and current is None:
            continue
        comparison = compare_grade_preview_basis(current, prior)
        if comparison.changed:
            return True
    return False


def _revalidate_reporting_selections(
    workspace_root: Path,
    class_id: str,
    observed: dict[ReportingScopeKey, ReportingSnapshotSelectionReference],
) -> None:
    """Fail closed if mutable selector authority moves during inspection."""

    for scope in sorted(observed):
        definition_id, school_year, period_id, calendar_revision = scope
        current = load_current_reporting_snapshot_selection(
            workspace_root,
            class_id,
            definition_id,
            AcademicPeriodRef(school_year, period_id),
            calendar_revision,
        )
        if current is None or current.reference != observed[scope]:
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
