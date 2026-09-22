"""Read-only #55 ReportingSnapshot to #54 Grade-comparison handoff.

This module owns only the adapter boundary between one already-validated
``ReportingSnapshot`` and the comparison engine completed in issue #54.  It does
not recalculate Grades, reopen academic authority, mutate snapshot state, or
implement another semantic diff algorithm.

Available frozen rows are adapted through
``prior_reporting_snapshot_grade_basis_from_observation()``.  Every material
Grade comparison is delegated to ``compare_grade_preview_basis()``.  Rows with
no ``GradePreviewObservation`` on either side do not invent a synthetic basis.
"""

from __future__ import annotations

from pathlib import Path

from meridian.grade_preview_comparison import (
    GradePreviewComparison,
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
    prior_reporting_snapshot_grade_basis_from_observation,
)
from meridian.grade_preview_explanation import (
    GradePreviewObservation,
    GradePreviewTarget,
)
from meridian.grade_report_preview import GradeReportPreview
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_record import ReportingSnapshot
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    ReportingSnapshotStorageNotFoundError,
    StoredReportingSnapshot,
    load_reporting_snapshot,
)


class ReportingSnapshotComparisonError(RuntimeError):
    """Base error for the #55 -> #54 comparison handoff."""

    code: str = "reporting_snapshot.comparison_error"


class ReportingSnapshotComparisonValidationError(
    ReportingSnapshotComparisonError, ValueError
):
    """Raised when a comparison request is malformed or out of scope."""

    code = "reporting_snapshot.comparison_invalid"


class ReportingSnapshotComparisonNotFoundError(ReportingSnapshotComparisonError):
    """Raised when an explicitly requested historical snapshot is absent."""

    code = "reporting_snapshot.not_found"


class ReportingSnapshotComparisonIntegrityError(ReportingSnapshotComparisonError):
    """Raised when exact historical snapshot identity cannot be trusted."""

    code = "reporting_snapshot.integrity_failed"


def reporting_snapshot_prior_grade_bases(
    snapshot: ReportingSnapshot,
) -> tuple[PriorReportingSnapshotGradeBasis, ...]:
    """Extract all available frozen #54 Grade bases from one snapshot.

    Unavailable rows intentionally produce no synthetic ``GradePreviewObservation``.
    The returned tuple follows the canonical frozen-report row order.
    """

    exact = _snapshot(snapshot)
    return tuple(
        prior_reporting_snapshot_grade_basis_from_observation(row.observation)
        for row in exact.report_preview.rows
        if row.observation is not None
    )


def reporting_snapshot_prior_grade_basis(
    snapshot: ReportingSnapshot,
    target: GradePreviewTarget,
) -> PriorReportingSnapshotGradeBasis | None:
    """Return one exact frozen prior basis, or ``None`` for an unavailable row.

    Absence of the exact target is different from an explicitly unavailable row
    and therefore raises ``ReportingSnapshotComparisonNotFoundError``.
    """

    exact = _snapshot(snapshot)
    wanted = _target(target)
    wanted_key = _exact_target_key(wanted)
    for row in exact.report_preview.rows:
        if _exact_target_key(row.target) != wanted_key:
            continue
        if row.observation is None:
            return None
        return prior_reporting_snapshot_grade_basis_from_observation(
            row.observation
        )
    raise ReportingSnapshotComparisonNotFoundError(
        "Exact Grade target is absent from the frozen ReportingSnapshot."
    )


def load_reporting_snapshot_for_comparison(
    workspace_root: str | Path,
    reference: ReportingSnapshotReference,
) -> StoredReportingSnapshot:
    """Load one exact digest-bound historical snapshot for comparison."""

    if not isinstance(reference, ReportingSnapshotReference):
        raise ReportingSnapshotComparisonValidationError(
            "reference must be ReportingSnapshotReference."
        )
    exact_reference = ReportingSnapshotReference(
        class_id=reference.class_id,
        snapshot_id=reference.snapshot_id,
        snapshot_sha256=reference.snapshot_sha256,
    )
    try:
        stored = load_reporting_snapshot(
            workspace_root,
            exact_reference.class_id,
            exact_reference.snapshot_id,
        )
    except ReportingSnapshotStorageNotFoundError as error:
        raise ReportingSnapshotComparisonNotFoundError(
            "Exact historical ReportingSnapshot does not exist."
        ) from error
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotComparisonIntegrityError(
            "Historical ReportingSnapshot failed canonical verification."
        ) from error
    if stored.snapshot_sha256 != exact_reference.snapshot_sha256:
        raise ReportingSnapshotComparisonIntegrityError(
            "ReportingSnapshot reference digest does not match exact stored bytes."
        )
    if stored.reference != exact_reference:
        raise ReportingSnapshotComparisonIntegrityError(
            "Stored ReportingSnapshot reference does not match requested identity."
        )
    return stored


def load_reporting_snapshot_prior_grade_bases(
    workspace_root: str | Path,
    reference: ReportingSnapshotReference,
) -> tuple[PriorReportingSnapshotGradeBasis, ...]:
    """Load an exact historical snapshot and extract all available prior bases."""

    stored = load_reporting_snapshot_for_comparison(workspace_root, reference)
    return reporting_snapshot_prior_grade_bases(stored.snapshot)


def compare_reporting_snapshot_to_current_observations(
    snapshot: ReportingSnapshot,
    current_observations: tuple[GradePreviewObservation, ...],
) -> tuple[GradePreviewComparison, ...]:
    """Compare frozen snapshot bases with caller-supplied current observations.

    Comparison semantics come entirely from issue #54.  This function only
    performs deterministic row matching. Exact target matches are paired first.
    A remaining prior/current pair may match across calculation families when
    the logical student/period scope is uniquely unambiguous on both sides; this
    preserves #54's ``calculation_family_changed`` comparison semantics.
    """

    exact = _snapshot(snapshot)
    current = _observations(current_observations)
    _require_scope(exact, current)

    prior = tuple(
        row.observation
        for row in exact.report_preview.rows
        if row.observation is not None
    )
    pairs = _match_observations(prior, current)
    comparisons: list[GradePreviewComparison] = []
    for previous, present in pairs:
        if previous is None and present is None:  # defensive; matcher never emits this.
            continue
        prior_basis = (
            prior_reporting_snapshot_grade_basis_from_observation(previous)
            if previous is not None
            else None
        )
        comparisons.append(compare_grade_preview_basis(present, prior_basis))
    return tuple(comparisons)


def compare_reporting_snapshot_to_grade_report_preview(
    snapshot: ReportingSnapshot,
    current_preview: GradeReportPreview,
) -> tuple[GradePreviewComparison, ...]:
    """Compare a snapshot with the available observations in a live #54 report."""

    if not isinstance(current_preview, GradeReportPreview):
        raise ReportingSnapshotComparisonValidationError(
            "current_preview must be GradeReportPreview."
        )
    observations = tuple(
        row.observation
        for row in current_preview.rows
        if row.observation is not None
    )
    return compare_reporting_snapshot_to_current_observations(
        snapshot,
        observations,
    )


def compare_reporting_snapshot_reference_to_current_observations(
    workspace_root: str | Path,
    reference: ReportingSnapshotReference,
    current_observations: tuple[GradePreviewObservation, ...],
) -> tuple[GradePreviewComparison, ...]:
    """Load one exact snapshot reference and delegate comparisons to #54."""

    stored = load_reporting_snapshot_for_comparison(workspace_root, reference)
    return compare_reporting_snapshot_to_current_observations(
        stored.snapshot,
        current_observations,
    )


def _snapshot(value: ReportingSnapshot) -> ReportingSnapshot:
    if not isinstance(value, ReportingSnapshot):
        raise ReportingSnapshotComparisonValidationError(
            "snapshot must be ReportingSnapshot."
        )
    return value


def _target(value: GradePreviewTarget) -> GradePreviewTarget:
    if not isinstance(value, GradePreviewTarget):
        raise ReportingSnapshotComparisonValidationError(
            "target must be GradePreviewTarget."
        )
    return value


def _observations(
    values: tuple[GradePreviewObservation, ...],
) -> tuple[GradePreviewObservation, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(item, GradePreviewObservation) for item in values
    ):
        raise ReportingSnapshotComparisonValidationError(
            "current_observations must be a tuple of GradePreviewObservation values."
        )
    keys = tuple(_exact_target_key(item.target) for item in values)
    if len(set(keys)) != len(keys):
        raise ReportingSnapshotComparisonValidationError(
            "current_observations must not duplicate an exact Grade target."
        )
    return tuple(sorted(values, key=lambda item: _exact_target_key(item.target)))


def _require_scope(
    snapshot: ReportingSnapshot,
    current: tuple[GradePreviewObservation, ...],
) -> None:
    expected = (
        snapshot.class_id,
        snapshot.target_period.school_year,
        snapshot.target_period.period_id,
        snapshot.calendar_revision,
    )
    for observation in current:
        target = observation.target
        actual = (
            target.class_id,
            target.target_period.school_year,
            target.target_period.period_id,
            target.calendar_revision,
        )
        if actual != expected:
            raise ReportingSnapshotComparisonValidationError(
                "current Grade observation is outside the snapshot reporting scope."
            )


def _match_observations(
    prior: tuple[GradePreviewObservation, ...],
    current: tuple[GradePreviewObservation, ...],
) -> tuple[
    tuple[GradePreviewObservation | None, GradePreviewObservation | None], ...
]:
    prior_by_exact = {_exact_target_key(item.target): item for item in prior}
    current_by_exact = {_exact_target_key(item.target): item for item in current}

    pairs: list[
        tuple[GradePreviewObservation | None, GradePreviewObservation | None]
    ] = []
    exact_keys = sorted(set(prior_by_exact).intersection(current_by_exact))
    for key in exact_keys:
        pairs.append((prior_by_exact.pop(key), current_by_exact.pop(key)))

    prior_by_scope = _by_logical_scope(tuple(prior_by_exact.values()))
    current_by_scope = _by_logical_scope(tuple(current_by_exact.values()))
    for scope in sorted(set(prior_by_scope).intersection(current_by_scope)):
        previous = prior_by_scope[scope]
        present = current_by_scope[scope]
        if len(previous) != 1 or len(present) != 1:
            continue
        prior_item = previous[0]
        current_item = present[0]
        prior_by_exact.pop(_exact_target_key(prior_item.target), None)
        current_by_exact.pop(_exact_target_key(current_item.target), None)
        pairs.append((prior_item, current_item))

    pairs.extend((item, None) for item in prior_by_exact.values())
    pairs.extend((None, item) for item in current_by_exact.values())
    return tuple(sorted(pairs, key=_pair_key))


def _by_logical_scope(
    values: tuple[GradePreviewObservation, ...],
) -> dict[tuple[str, str, str, str, int], tuple[GradePreviewObservation, ...]]:
    grouped: dict[
        tuple[str, str, str, str, int], list[GradePreviewObservation]
    ] = {}
    for item in values:
        grouped.setdefault(_logical_target_key(item.target), []).append(item)
    return {
        key: tuple(sorted(items, key=lambda item: _exact_target_key(item.target)))
        for key, items in grouped.items()
    }


def _pair_key(
    pair: tuple[GradePreviewObservation | None, GradePreviewObservation | None],
) -> tuple[str, str, str, str, int, str, str]:
    previous, current = pair
    if current is not None:
        target = current.target
    else:
        assert previous is not None
        target = previous.target
    previous_family = previous.target.calculation_family if previous else ""
    current_family = current.target.calculation_family if current else ""
    logical = _logical_target_key(target)
    return (*logical, previous_family, current_family)


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


def _exact_target_key(
    target: GradePreviewTarget,
) -> tuple[str, str, str, str, int, str]:
    return (*_logical_target_key(target), target.calculation_family)


__all__ = [
    "ReportingSnapshotComparisonError",
    "ReportingSnapshotComparisonIntegrityError",
    "ReportingSnapshotComparisonNotFoundError",
    "ReportingSnapshotComparisonValidationError",
    "compare_reporting_snapshot_reference_to_current_observations",
    "compare_reporting_snapshot_to_current_observations",
    "compare_reporting_snapshot_to_grade_report_preview",
    "load_reporting_snapshot_for_comparison",
    "load_reporting_snapshot_prior_grade_bases",
    "reporting_snapshot_prior_grade_basis",
    "reporting_snapshot_prior_grade_bases",
]
