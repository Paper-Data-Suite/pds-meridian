"""Final Create Planning Signal export orchestration with optional Core CSV."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_csv_export import (
    GroupingSignalCsvExportError,
    GroupingSignalCsvExportResult,
    export_grouping_signal_csv,
)
from meridian.planning_signal_core_export_commit_workflow import (
    PlanningSignalCoreExportCommitResult,
    commit_planning_signal_core_export,
)
from meridian.planning_signal_core_export_preview_workflow import (
    PlanningSignalCoreExportPreview,
)


class PlanningSignalExportCommitError(RuntimeError):
    """Base error for the final #41 planning-signal export step."""

    code = "teacher_workflow.create_planning_signal.export_commit_error"


class PlanningSignalExportCommitIntegrityError(PlanningSignalExportCommitError):
    """Raised when Core/receipt/CSV results do not describe one exact export."""

    code = "teacher_workflow.create_planning_signal.export_commit_integrity_error"


class PlanningSignalCsvExportPartialSuccessError(PlanningSignalExportCommitError):
    """Core + receipt are verified, but the optional CSV operation failed."""

    code = (
        "teacher_workflow.create_planning_signal."
        "csv_export_partial_success"
    )

    core_result: PlanningSignalCoreExportCommitResult
    csv_error_code: str
    csv_destination: Path

    def __init__(
        self,
        *,
        core_result: PlanningSignalCoreExportCommitResult,
        csv_error: GroupingSignalCsvExportError,
        csv_destination: str | Path,
    ) -> None:
        if not isinstance(core_result, PlanningSignalCoreExportCommitResult):
            raise PlanningSignalExportCommitIntegrityError(
                "core_result must be the exact committed Core/receipt result."
            )
        self.core_result = core_result
        self.csv_error_code = getattr(csv_error, "code", "csv_export_failed")
        self.csv_destination = Path(csv_destination)
        super().__init__(
            "Core grouping signal and Meridian receipt are durably verified, "
            "but the optional Core-native CSV export failed. Core and receipt "
            "state must not be rolled back."
        )

    @property
    def signal_set_id(self) -> str:
        return self.core_result.preview.signal_set.signal_set_id

    @property
    def core_write_disposition(self) -> str:
        return self.core_result.core_write_disposition

    @property
    def receipt_write_disposition(self) -> str:
        return self.core_result.receipt_write_disposition

    @property
    def core_signal_digest(self) -> str:
        return self.core_result.core_signal_digest

    @property
    def receipt_sha256(self) -> str:
        return self.core_result.receipt_sha256


@dataclass(frozen=True, slots=True)
class PlanningSignalExportCommitResult:
    """Verified final export result for Core/receipt plus optional CSV."""

    core: PlanningSignalCoreExportCommitResult
    csv: GroupingSignalCsvExportResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.core, PlanningSignalCoreExportCommitResult):
            raise PlanningSignalExportCommitIntegrityError(
                "core must be an exact PlanningSignalCoreExportCommitResult."
            )
        if self.csv is None:
            return
        if not isinstance(self.csv, GroupingSignalCsvExportResult):
            raise PlanningSignalExportCommitIntegrityError(
                "csv must be a GroupingSignalCsvExportResult when present."
            )
        signal = self.core.preview.signal_set
        if (
            self.csv.class_id != signal.class_id
            or self.csv.signal_set_id != signal.signal_set_id
        ):
            raise PlanningSignalExportCommitIntegrityError(
                "CSV result does not bind the exact committed Core signal."
            )

    @property
    def core_export_action(self) -> str:
        return "performed"

    @property
    def export_receipt_action(self) -> str:
        return "performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed" if self.csv is None else "performed"

    @property
    def concord_action(self) -> str:
        return "not_performed"


def commit_planning_signal_export(
    workspace_root: str | Path,
    preview: PlanningSignalCoreExportPreview,
    *,
    csv_destination: str | Path | None = None,
) -> PlanningSignalExportCommitResult:
    """Commit exact Core/receipt state, then optionally emit Core-native CSV.

    Core persistence and CSV file emission remain separate stores and are not
    treated as one transaction. CSV is generated only from the exact stored
    Core signal plus matching Meridian receipt through the canonical #40
    exporter.
    """

    core = commit_planning_signal_core_export(workspace_root, preview)
    if csv_destination is None:
        return PlanningSignalExportCommitResult(core=core, csv=None)

    signal = preview.signal_set
    try:
        csv_result = export_grouping_signal_csv(
            workspace_root,
            signal.class_id,
            signal.signal_set_id,
            csv_destination,
        )
    except GroupingSignalCsvExportError as error:
        raise PlanningSignalCsvExportPartialSuccessError(
            core_result=core,
            csv_error=error,
            csv_destination=csv_destination,
        ) from error

    return PlanningSignalExportCommitResult(
        core=core,
        csv=csv_result,
    )
