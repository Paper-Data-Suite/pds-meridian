"""Grade Checkpoint Comparison report for Meridian Issue #111 Slice 10.

This module never implements Grade-difference semantics.  It delegates all
available Grade comparisons to the existing issue #54 comparison engine and
adds only teacher-report presentation, exact checkpoint loading, and whole-live-
report currentness verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef

from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_preview_comparison import GradePreviewComparison
from meridian.grade_preview_explanation import (
    GradePreviewObservation,
    GradePreviewTarget,
)
from meridian.grade_report_preview import GradeReportPreview, GradeReportPreviewRow
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonError,
    compare_reporting_snapshot_to_current_observations,
    compare_reporting_snapshot_to_grade_report_preview,
    load_reporting_snapshot_for_comparison,
)
from meridian.reporting_snapshot_preview import FrozenGradeReportPreviewRow
from meridian.reporting_snapshot_record import (
    ReportingSnapshot,
    ReportingSnapshotBuildRequest,
    reporting_snapshot_build_request_sha256,
)
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotProjectionAuthorization,
    ReportingSnapshotWorkflowError,
    prepare_reporting_snapshot_freeze,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

CheckpointSideStatus: TypeAlias = Literal["available", "unavailable"]
CheckpointChangeState: TypeAlias = Literal[
    "INCREASED",
    "DECREASED",
    "UNCHANGED",
    "NEW_OR_NEWLY_AVAILABLE",
    "REMOVED_OR_UNAVAILABLE",
    "NEEDS_REVIEW",
    "UNAVAILABLE_UNCHANGED",
]


class GradeCheckpointComparisonError(RuntimeError):
    """Base error for teacher-facing Grade checkpoint comparison."""

    code = "grade_checkpoint_comparison.error"


class GradeCheckpointComparisonValidationError(
    GradeCheckpointComparisonError,
    ValueError,
):
    code = "grade_checkpoint_comparison.invalid"


class GradeCheckpointComparisonSourceError(GradeCheckpointComparisonError):
    code = "grade_checkpoint_comparison.source_unavailable"


class GradeCheckpointComparisonCurrentnessConflictError(GradeCheckpointComparisonError):
    code = "grade_checkpoint_comparison.currentness_conflict"


@dataclass(frozen=True, slots=True)
class CheckpointSideRow:
    """Presentation state for one exact requested Grade row."""

    target: GradePreviewTarget
    status: CheckpointSideStatus
    observation: GradePreviewObservation | None
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise GradeCheckpointComparisonValidationError(
                "checkpoint side target must be GradePreviewTarget."
            )
        if self.status == "available":
            if self.observation is None or self.unavailable_reason is not None:
                raise GradeCheckpointComparisonValidationError(
                    "available checkpoint row requires only an observation."
                )
            if self.observation.target != self.target:
                raise GradeCheckpointComparisonValidationError(
                    "checkpoint observation target must match row target."
                )
        elif self.status == "unavailable":
            if self.observation is not None or self.unavailable_reason is None:
                raise GradeCheckpointComparisonValidationError(
                    "unavailable checkpoint row requires only its reason."
                )
        else:
            raise GradeCheckpointComparisonValidationError(
                "unsupported checkpoint row status."
            )


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_snapshot_to_snapshot_grade_checkpoint_comparison(
    workspace_root: str | Path,
    *,
    prior_reference: ReportingSnapshotReference,
    current_reference: ReportingSnapshotReference,
    generated_at: datetime | None = None,
) -> TeacherReportPreview:
    """Compare two exact immutable ReportingSnapshots using the #54 engine."""

    root = Path(workspace_root)
    try:
        prior_stored = load_reporting_snapshot_for_comparison(root, prior_reference)
        current_stored = load_reporting_snapshot_for_comparison(
            root,
            current_reference,
        )
    except ReportingSnapshotComparisonError as error:
        raise GradeCheckpointComparisonSourceError(
            "Exact ReportingSnapshot checkpoint could not be loaded safely."
        ) from error

    _require_snapshot_scope(prior_stored.snapshot, current_stored.snapshot)
    current_observations = tuple(
        row.observation
        for row in current_stored.snapshot.report_preview.rows
        if row.observation is not None
    )
    try:
        comparisons = compare_reporting_snapshot_to_current_observations(
            prior_stored.snapshot,
            current_observations,
        )
    except ReportingSnapshotComparisonError as error:
        raise GradeCheckpointComparisonSourceError(
            "Existing Grade comparison engine rejected snapshot comparison."
        ) from error

    return compose_grade_checkpoint_comparison(
        class_id=prior_stored.snapshot.class_id,
        target_period=prior_stored.snapshot.target_period,
        calendar_revision=prior_stored.snapshot.calendar_revision,
        prior_rows=_frozen_side_rows(prior_stored.snapshot),
        current_rows=_frozen_side_rows(current_stored.snapshot),
        comparisons=comparisons,
        source_references=(
            TeacherReportSourceReference(
                "reporting_snapshot",
                f"prior:{prior_reference.snapshot_id}",
                prior_reference.snapshot_sha256,
            ),
            TeacherReportSourceReference(
                "reporting_snapshot",
                f"current:{current_reference.snapshot_id}",
                current_reference.snapshot_sha256,
            ),
        ),
        generated_at=utc_now() if generated_at is None else generated_at,
        comparison_basis="snapshot_to_snapshot",
    )


def build_snapshot_to_current_grade_checkpoint_comparison(
    workspace_root: str | Path,
    *,
    prior_reference: ReportingSnapshotReference,
    current_build_request: ReportingSnapshotBuildRequest | None = None,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...] = (),
    generated_at: datetime | None = None,
    dependencies: DiagnosticsDependencies | None = None,
) -> TeacherReportPreview:
    """Compare an exact snapshot with one twice-observed live Grade report."""

    root = Path(workspace_root)
    try:
        prior_stored = load_reporting_snapshot_for_comparison(root, prior_reference)
    except ReportingSnapshotComparisonError as error:
        raise GradeCheckpointComparisonSourceError(
            "Exact prior ReportingSnapshot could not be loaded safely."
        ) from error

    request = (
        prior_stored.snapshot.build_request
        if current_build_request is None
        else current_build_request
    )
    _require_request_scope(prior_stored.snapshot, request)
    timestamp = utc_now() if generated_at is None else generated_at
    try:
        first = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="checkpoint_comparison_preview",
            build_request=request,
            authorizations=authorizations,
            created_at=timestamp,
            dependencies=dependencies,
        )
        comparisons = compare_reporting_snapshot_to_grade_report_preview(
            prior_stored.snapshot,
            first.live_report,
        )
        second = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="checkpoint_comparison_preview",
            build_request=request,
            authorizations=authorizations,
            created_at=timestamp,
            dependencies=dependencies,
        )
    except (ReportingSnapshotWorkflowError, ReportingSnapshotComparisonError) as error:
        raise GradeCheckpointComparisonSourceError(
            "Live/current Grade checkpoint could not be observed safely."
        ) from error

    if first.live_report_sha256 != second.live_report_sha256:
        raise GradeCheckpointComparisonCurrentnessConflictError(
            "Live Grade report changed during checkpoint comparison."
        )

    return compose_grade_checkpoint_comparison(
        class_id=prior_stored.snapshot.class_id,
        target_period=prior_stored.snapshot.target_period,
        calendar_revision=prior_stored.snapshot.calendar_revision,
        prior_rows=_frozen_side_rows(prior_stored.snapshot),
        current_rows=_live_side_rows(first.live_report),
        comparisons=comparisons,
        source_references=(
            TeacherReportSourceReference(
                "reporting_snapshot",
                f"prior:{prior_reference.snapshot_id}",
                prior_reference.snapshot_sha256,
            ),
            TeacherReportSourceReference(
                "reporting_snapshot_build_request",
                "current_live_request",
                reporting_snapshot_build_request_sha256(request),
            ),
            TeacherReportSourceReference(
                "live_grade_report",
                "current_live_report",
                first.live_report_sha256,
            ),
        ),
        generated_at=timestamp,
        comparison_basis="snapshot_to_current",
    )


def compose_grade_checkpoint_comparison(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    prior_rows: tuple[CheckpointSideRow, ...],
    current_rows: tuple[CheckpointSideRow, ...],
    comparisons: tuple[GradePreviewComparison, ...],
    source_references: tuple[TeacherReportSourceReference, ...],
    generated_at: datetime,
    comparison_basis: Literal["snapshot_to_snapshot", "snapshot_to_current"],
) -> TeacherReportPreview:
    """Project existing Grade comparisons into one deterministic teacher report."""

    if comparison_basis not in {"snapshot_to_snapshot", "snapshot_to_current"}:
        raise GradeCheckpointComparisonValidationError(
            "unsupported checkpoint comparison basis."
        )
    prior = _side_rows(prior_rows, class_id, target_period, calendar_revision)
    current = _side_rows(current_rows, class_id, target_period, calendar_revision)

    output: list[tuple[str | None, ...]] = []
    represented_exact_pairs: set[tuple[str, str, str]] = set()

    for comparison in comparisons:
        if not isinstance(comparison, GradePreviewComparison):
            raise GradeCheckpointComparisonValidationError(
                "comparisons must contain GradePreviewComparison values."
            )
        target = comparison.current_target or comparison.prior_target
        if target is None:  # defensive; domain contract forbids this.
            raise GradeCheckpointComparisonValidationError(
                "comparison does not identify a Grade target."
            )
        prior_row = _row_for_comparison_side(
            prior,
            comparison.prior_target,
            target,
        )
        current_row = _row_for_comparison_side(
            current,
            comparison.current_target,
            target,
        )
        state = _change_state(comparison)
        prior_grade = _grade_text(prior_row)
        current_grade = _grade_text(current_row)
        delta = (
            None
            if comparison.effective_grade_delta is None
            else str(comparison.effective_grade_delta)
        )
        reasons = ", ".join(comparison.reasons) or "none"
        output.append(
            (
                target.student_id,
                _family(prior_row),
                _family(current_row),
                prior_grade,
                current_grade,
                delta,
                _status_text(prior_row),
                _status_text(current_row),
                state,
                reasons,
            )
        )
        if prior_row is not None and current_row is not None:
            represented_exact_pairs.add(
                (
                    prior_row.target.student_id,
                    prior_row.target.calculation_family,
                    current_row.target.calculation_family,
                )
            )

    # The issue #54 comparison engine intentionally has no synthetic observation
    # for unavailable rows. Preserve exact unavailable->unavailable status without
    # manufacturing Grade-diff reasons.
    prior_unavailable = {
        _exact_target_key(row.target): row
        for row in prior
        if row.status == "unavailable"
    }
    current_unavailable = {
        _exact_target_key(row.target): row
        for row in current
        if row.status == "unavailable"
    }
    for key in sorted(set(prior_unavailable).intersection(current_unavailable)):
        before = prior_unavailable[key]
        after = current_unavailable[key]
        represented = (
            before.target.student_id,
            before.target.calculation_family,
            after.target.calculation_family,
        )
        if represented in represented_exact_pairs:
            continue
        output.append(
            (
                before.target.student_id,
                before.target.calculation_family,
                after.target.calculation_family,
                None,
                None,
                None,
                _status_text(before),
                _status_text(after),
                "UNAVAILABLE_UNCHANGED",
                "none",
            )
        )

    output.sort(key=lambda row: (row[0], row[1] or "", row[2] or ""))
    report_rows = tuple(
        TeacherReportRow(
            f"checkpoint_{index:05d}",
            row,
        )
        for index, row in enumerate(output, start=1)
    )

    counts = {
        state: sum(row[8] == state for row in output)
        for state in (
            "INCREASED",
            "DECREASED",
            "UNCHANGED",
            "NEW_OR_NEWLY_AVAILABLE",
            "REMOVED_OR_UNAVAILABLE",
            "NEEDS_REVIEW",
            "UNAVAILABLE_UNCHANGED",
        )
    }
    diagnostics: list[TeacherReportDiagnostic] = []
    if counts["NEEDS_REVIEW"]:
        diagnostics.append(
            TeacherReportDiagnostic(
                "grade_checkpoint.needs_review",
                "info",
                (
                    f"{counts['NEEDS_REVIEW']} comparable Grade rows changed without "
                    "a meaningful numeric increase/decrease."
                ),
            )
        )
    if counts["REMOVED_OR_UNAVAILABLE"]:
        diagnostics.append(
            TeacherReportDiagnostic(
                "grade_checkpoint.removed_or_unavailable",
                "info",
                (
                    f"{counts['REMOVED_OR_UNAVAILABLE']} prior Grade rows are no "
                    "longer represented as an available current observation."
                ),
            )
        )

    return compose_teacher_report_preview(
        report_kind="grade_checkpoint_comparison",
        title="Grade Checkpoint Comparison",
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        source_references=source_references,
        generated_at=generated_at,
        summary=(
            f"Comparison basis: {comparison_basis}.",
            f"Increased: {counts['INCREASED']}.",
            f"Decreased: {counts['DECREASED']}.",
            f"Unchanged: {counts['UNCHANGED']}.",
            (f"New/newly available: {counts['NEW_OR_NEWLY_AVAILABLE']}."),
            (f"Removed/unavailable: {counts['REMOVED_OR_UNAVAILABLE']}."),
            f"Needs review: {counts['NEEDS_REVIEW']}.",
            (
                "All Grade-change reasons come from the existing "
                "GradePreviewComparison engine."
            ),
        ),
        columns=(
            TeacherReportColumn("student_id", "Student ID"),
            TeacherReportColumn("prior_family", "Prior Family"),
            TeacherReportColumn("current_family", "Current Family"),
            TeacherReportColumn("prior_grade", "Prior Effective Grade"),
            TeacherReportColumn("current_grade", "Current Effective Grade"),
            TeacherReportColumn("delta", "Delta"),
            TeacherReportColumn("prior_status", "Prior Status"),
            TeacherReportColumn("current_status", "Current Status"),
            TeacherReportColumn("change_state", "Change State"),
            TeacherReportColumn("reasons", "Material Reasons"),
        ),
        rows=report_rows,
        diagnostics=diagnostics,
    )


def checkpoint_side_row_from_frozen(
    row: FrozenGradeReportPreviewRow,
) -> CheckpointSideRow:
    if row.status == "available":
        return CheckpointSideRow(row.target, "available", row.observation, None)
    return CheckpointSideRow(
        row.target,
        "unavailable",
        None,
        row.unavailable_reason or "unavailable",
    )


def checkpoint_side_row_from_live(row: GradeReportPreviewRow) -> CheckpointSideRow:
    if row.status == "available":
        return CheckpointSideRow(row.target, "available", row.observation, None)
    return CheckpointSideRow(
        row.target,
        "unavailable",
        None,
        row.unavailable_reason or "unavailable",
    )


def _frozen_side_rows(
    snapshot: ReportingSnapshot,
) -> tuple[CheckpointSideRow, ...]:
    return tuple(
        checkpoint_side_row_from_frozen(row) for row in snapshot.report_preview.rows
    )


def _live_side_rows(preview: GradeReportPreview) -> tuple[CheckpointSideRow, ...]:
    return tuple(checkpoint_side_row_from_live(row) for row in preview.rows)


def _side_rows(
    rows: tuple[CheckpointSideRow, ...],
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> tuple[CheckpointSideRow, ...]:
    values = tuple(rows)
    keys: set[tuple[str, str, str, str, int, str]] = set()
    for row in values:
        if not isinstance(row, CheckpointSideRow):
            raise GradeCheckpointComparisonValidationError(
                "checkpoint rows must contain CheckpointSideRow values."
            )
        target = row.target
        if (
            target.class_id != class_id
            or target.target_period != target_period
            or target.calendar_revision != calendar_revision
        ):
            raise GradeCheckpointComparisonValidationError(
                "checkpoint row is outside report scope."
            )
        key = _exact_target_key(target)
        if key in keys:
            raise GradeCheckpointComparisonValidationError(
                "checkpoint side rows must not duplicate exact Grade targets."
            )
        keys.add(key)
    return tuple(sorted(values, key=lambda item: _exact_target_key(item.target)))


def _row_for_comparison_side(
    rows: tuple[CheckpointSideRow, ...],
    exact_target: GradePreviewTarget | None,
    logical_target: GradePreviewTarget,
) -> CheckpointSideRow | None:
    if exact_target is not None:
        exact_key = _exact_target_key(exact_target)
        for row in rows:
            if _exact_target_key(row.target) == exact_key:
                return row
    candidates = [
        row
        for row in rows
        if _logical_target_key(row.target) == _logical_target_key(logical_target)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _change_state(comparison: GradePreviewComparison) -> CheckpointChangeState:
    if comparison.relationship == "new":
        return "NEW_OR_NEWLY_AVAILABLE"
    if comparison.relationship == "removed":
        return "REMOVED_OR_UNAVAILABLE"
    if not comparison.changed:
        return "UNCHANGED"
    delta = comparison.effective_grade_delta
    if delta is None or delta == Decimal("0"):
        return "NEEDS_REVIEW"
    if delta > 0:
        return "INCREASED"
    return "DECREASED"


def _family(row: CheckpointSideRow | None) -> str | None:
    return None if row is None else row.target.calculation_family


def _grade_text(row: CheckpointSideRow | None) -> str | None:
    if row is None or row.observation is None:
        return None
    value = row.observation.effective_grade
    return None if value is None else str(value)


def _status_text(row: CheckpointSideRow | None) -> str:
    if row is None:
        return "not represented"
    if row.status == "unavailable":
        return f"unavailable/{row.unavailable_reason}"
    observation = row.observation
    assert observation is not None
    return (
        f"available/{observation.base_result_status}/"
        f"{observation.base_freshness_status}/"
        f"{observation.effective_source}"
    )


def _require_snapshot_scope(
    prior: ReportingSnapshot,
    current: ReportingSnapshot,
) -> None:
    if (
        prior.class_id != current.class_id
        or prior.target_period != current.target_period
        or prior.calendar_revision != current.calendar_revision
    ):
        raise GradeCheckpointComparisonValidationError(
            "ReportingSnapshots must share exact class/period/calendar scope."
        )


def _require_request_scope(
    prior: ReportingSnapshot,
    request: ReportingSnapshotBuildRequest,
) -> None:
    first = request.grade_requests[0].target
    if (
        first.class_id != prior.class_id
        or request.target_period != prior.target_period
        or request.calendar_revision != prior.calendar_revision
    ):
        raise GradeCheckpointComparisonValidationError(
            "Current build request must share prior snapshot class/period/calendar "
            "scope."
        )


def _exact_target_key(
    target: GradePreviewTarget,
) -> tuple[str, str, str, str, int, str]:
    return (
        target.class_id,
        target.student_id,
        target.target_period.school_year,
        target.target_period.period_id,
        target.calendar_revision,
        target.calculation_family,
    )


def _logical_target_key(
    target: GradePreviewTarget,
) -> tuple[str, str, str, str, int]:
    return (
        target.class_id,
        target.student_id,
        target.target_period.school_year,
        target.target_period.period_id,
        target.calendar_revision,
    )


__all__ = [
    "CheckpointChangeState",
    "CheckpointSideRow",
    "GradeCheckpointComparisonCurrentnessConflictError",
    "GradeCheckpointComparisonError",
    "GradeCheckpointComparisonSourceError",
    "GradeCheckpointComparisonValidationError",
    "build_snapshot_to_current_grade_checkpoint_comparison",
    "build_snapshot_to_snapshot_grade_checkpoint_comparison",
    "checkpoint_side_row_from_frozen",
    "checkpoint_side_row_from_live",
    "compose_grade_checkpoint_comparison",
]
