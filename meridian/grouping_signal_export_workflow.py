"""Core persistence workflow for approved Meridian grouping-signal exports.

Issue #40 Slice 3 composes the already-pure #38 -> Core projection with the
read-only #39 export-eligibility gate, Core roster diagnostics, a final
authorization recheck, and Core's immutable grouping-signal writer.

This module does not persist Meridian export receipts, emit CSV, mutate review
state, regenerate derivations/previews, or invoke Concord.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.grouping_signal_diagnostics import (
    GroupingSignalDiagnosticReport,
    GroupingSignalDiagnosticsError,
    diagnose_grouping_signal,
)
from pds_core.grouping_signal_storage import (
    GroupingSignalConflictError,
    GroupingSignalStorageError,
    GroupingSignalWriteResult,
    write_grouping_signal,
)

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationSnapshot,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_export import (
    GroupingSignalExportProjectionError,
    build_grouping_signal_export_candidate,
)
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportEligibility,
    resolve_grouping_signal_export_eligibility,
    revalidate_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewSnapshot
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)

GroupingSignalCoreExportFailureCode: TypeAlias = Literal[
    "projection_invariant_failed",
    "core_diagnostics_failed",
    "core_signal_conflict",
    "core_signal_integrity_failed",
]


class GroupingSignalCoreExportError(RuntimeError):
    """Base error for the #40 Core grouping-signal write workflow."""

    code: GroupingSignalCoreExportFailureCode


class GroupingSignalCoreExportInvariantError(GroupingSignalCoreExportError):
    """Raised when reviewed Meridian state and Core diagnostics disagree."""

    code: GroupingSignalCoreExportFailureCode = "projection_invariant_failed"


class GroupingSignalCoreExportDiagnosticsError(GroupingSignalCoreExportError):
    """Raised when Core diagnostics cannot verify the export candidate."""

    code: GroupingSignalCoreExportFailureCode = "core_diagnostics_failed"


class GroupingSignalCoreExportConflictError(GroupingSignalCoreExportError):
    """Raised when an existing Core identity has different canonical bytes."""

    code: GroupingSignalCoreExportFailureCode = "core_signal_conflict"


class GroupingSignalCoreExportStorageError(GroupingSignalCoreExportError):
    """Raised when Core immutable exchange storage is unreadable or unsafe."""

    code: GroupingSignalCoreExportFailureCode = "core_signal_integrity_failed"


@dataclass(frozen=True, slots=True)
class GroupingSignalCoreExportResult:
    """One verified Core write plus the exact authorization and diagnostics."""

    eligibility: GroupingSignalExportEligibility
    diagnostics: GroupingSignalDiagnosticReport
    write_result: GroupingSignalWriteResult

    def __post_init__(self) -> None:
        if not isinstance(self.eligibility, GroupingSignalExportEligibility):
            raise GroupingSignalCoreExportInvariantError(
                "eligibility must be exact #40 export authorization."
            )
        self.eligibility.__post_init__()
        if not isinstance(self.diagnostics, GroupingSignalDiagnosticReport):
            raise GroupingSignalCoreExportInvariantError(
                "diagnostics must be a Core GroupingSignalDiagnosticReport."
            )
        if not isinstance(self.write_result, GroupingSignalWriteResult):
            raise GroupingSignalCoreExportInvariantError(
                "write_result must be a Core GroupingSignalWriteResult."
            )
        signal = self.write_result.stored.signal
        if (
            signal.class_id != self.eligibility.derivation_reference.class_id
            or signal.source.snapshot_id
            != self.eligibility.derivation_reference.derivation_id
            or signal.source.snapshot_digest
            != self.eligibility.derivation_reference.derivation_sha256
        ):
            raise GroupingSignalCoreExportInvariantError(
                "Stored Core signal does not bind the exact authorized #38 "
                "derivation."
            )
        if (
            self.diagnostics.signal_set_id != signal.signal_set_id
            or self.diagnostics.signal_class_id != signal.class_id
            or self.diagnostics.target_class_id != signal.class_id
        ):
            raise GroupingSignalCoreExportInvariantError(
                "Core diagnostics do not describe the stored signal identity."
            )


def export_grouping_signal_to_core(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    *,
    signal_set_id: str,
    created_at: datetime,
) -> GroupingSignalCoreExportResult:
    """Persist one deliberately approved, still-current signal through Core.

    The final eligibility revalidation occurs after all candidate/diagnostic
    work and immediately before the immutable Core write call.
    """

    eligibility = resolve_grouping_signal_export_eligibility(
        workspace_root,
        class_id,
        derivation_id,
    )
    derivation, preview = _load_authorized_dependencies(
        workspace_root,
        eligibility,
    )

    try:
        candidate = build_grouping_signal_export_candidate(
            derivation,
            signal_set_id=signal_set_id,
            created_at=created_at,
        )
    except GroupingSignalExportProjectionError as error:
        raise GroupingSignalCoreExportInvariantError(str(error)) from error

    try:
        diagnostics = diagnose_grouping_signal(
            workspace_root,
            candidate,
            expected_class_id=class_id,
        )
    except GroupingSignalDiagnosticsError as error:
        raise GroupingSignalCoreExportDiagnosticsError(
            "Core roster diagnostics could not verify the grouping-signal "
            "candidate."
        ) from error

    _validate_diagnostics_against_reviewed_state(
        derivation,
        preview,
        diagnostics,
    )

    # This is deliberately the final read-only operation before Core persistence.
    final_eligibility = revalidate_grouping_signal_export_eligibility(
        workspace_root,
        eligibility,
    )

    try:
        write_result = write_grouping_signal(workspace_root, candidate)
    except GroupingSignalConflictError as error:
        raise GroupingSignalCoreExportConflictError(str(error)) from error
    except GroupingSignalStorageError as error:
        raise GroupingSignalCoreExportStorageError(
            "Core grouping-signal storage could not safely persist or reconcile "
            "the requested identity."
        ) from error

    return GroupingSignalCoreExportResult(
        eligibility=final_eligibility,
        diagnostics=diagnostics,
        write_result=write_result,
    )


def _load_authorized_dependencies(
    workspace_root: str | Path,
    eligibility: GroupingSignalExportEligibility,
) -> tuple[GroupingSignalDerivationSnapshot, GroupingSignalPreviewSnapshot]:
    try:
        stored_derivation = load_grouping_signal_derivation_reference(
            workspace_root,
            eligibility.derivation_reference,
        )
        stored_preview = load_grouping_signal_preview_reference(
            workspace_root,
            eligibility.preview_reference,
        )
    except (
        GroupingSignalDerivationStorageError,
        GroupingSignalPreviewStorageError,
    ) as error:
        raise GroupingSignalCoreExportInvariantError(
            "Exact authorized derivation/preview state is unavailable or invalid."
        ) from error

    derivation = stored_derivation.snapshot
    preview = stored_preview.snapshot
    if preview.derivation_reference != stored_derivation.reference:
        raise GroupingSignalCoreExportInvariantError(
            "Authorized preview does not bind the exact authorized derivation."
        )
    return derivation, preview


def _validate_diagnostics_against_reviewed_state(
    derivation: GroupingSignalDerivationSnapshot,
    preview: GroupingSignalPreviewSnapshot,
    report: GroupingSignalDiagnosticReport,
) -> None:
    if report.has_errors:
        codes = ", ".join(
            sorted(
                {
                    finding.code
                    for finding in report.findings
                    if finding.severity == "error"
                }
            )
        )
        raise GroupingSignalCoreExportDiagnosticsError(
            "Core grouping-signal diagnostics reported export error(s): "
            f"{codes}."
        )

    if (
        report.signal_class_id != derivation.class_id
        or report.target_class_id != derivation.class_id
        or report.roster_student_count != len(derivation.roster_basis.student_ids)
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Core diagnostic class/roster basis does not match the exact #38 "
            "derivation."
        )
    if (
        preview.derivation_reference.class_id != derivation.class_id
        or preview.roster_basis != derivation.roster_basis
        or preview.dimension_id != derivation.dimension_id
        or preview.band_count != derivation.band_count
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Exact #39 preview does not match the authorized #38 export basis."
        )
    if len(report.dimensions) != 1:
        raise GroupingSignalCoreExportInvariantError(
            "Meridian #40 requires exactly one Core diagnostic dimension."
        )

    dimension = report.dimensions[0]
    if (
        dimension.dimension_id != derivation.dimension_id
        or dimension.band_count != derivation.band_count
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Core diagnostic dimension does not match the exact #38 dimension."
        )

    contributing = tuple(
        item
        for item in derivation.student_derivations
        if item.disposition == "contributing"
    )
    noncontributing = tuple(
        item
        for item in derivation.student_derivations
        if item.disposition == "noncontributing"
    )
    contributing_ids = tuple(sorted(item.student_id for item in contributing))
    noncontributing_ids = tuple(
        sorted(item.student_id for item in noncontributing)
    )
    missing_ids = tuple(
        sorted(
            finding.student_id
            for finding in report.findings
            if finding.code == "missing_student_signal"
            and finding.student_id is not None
        )
    )

    if (
        dimension.roster_student_count != preview.coverage.roster_student_count
        or dimension.matched_student_count
        != preview.coverage.contributing_student_count
        or dimension.missing_student_count
        != preview.coverage.noncontributing_student_count
        or dimension.unknown_student_count != 0
        or dimension.wrong_class_student_count != 0
        or dimension.signal_entry_count != len(contributing_ids)
        or missing_ids != noncontributing_ids
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Core roster coverage does not exactly match the accepted #39 "
            "preview/noncontributor set."
        )

    expected_band_counts = Counter(
        item.band for item in contributing if item.band is not None
    )
    canonical_expected_counts = tuple(
        (band, expected_band_counts.get(band, 0))
        for band in range(1, derivation.band_count + 1)
    )
    preview_counts = tuple(
        (summary.band, summary.student_count)
        for summary in preview.band_summaries
    )
    if (
        dimension.band_counts != canonical_expected_counts
        or preview_counts != canonical_expected_counts
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Core band distribution does not exactly match the accepted #39 "
            "preview."
        )

    preview_contributing_ids = tuple(
        sorted(
            row.student_id
            for row in preview.student_rows
            if row.disposition == "contributing"
        )
    )
    preview_noncontributing_ids = tuple(
        sorted(
            row.student_id
            for row in preview.student_rows
            if row.disposition == "noncontributing"
        )
    )
    if (
        preview_contributing_ids != contributing_ids
        or preview_noncontributing_ids != noncontributing_ids
    ):
        raise GroupingSignalCoreExportInvariantError(
            "Accepted #39 preview student disposition does not match #38."
        )
