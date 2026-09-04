"""Explicit #40 Core grouping-signal export commit for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockCode,
    GroupingSignalExportBlockedError,
    GroupingSignalExportEligibilityError,
    revalidate_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_export_receipt_workflow import (
    GroupingSignalExportPartialSuccessError,
    GroupingSignalExportReceiptWorkflowError,
    GroupingSignalExportResult,
    export_grouping_signal,
)
from meridian.grouping_signal_export_workflow import GroupingSignalCoreExportError
from meridian.planning_signal_core_export_preview_workflow import (
    PlanningSignalCoreExportPreview,
)


class PlanningSignalCoreExportCommitError(RuntimeError):
    """Base failure for explicit #40 Core/receipt export commit."""

    code = "teacher_workflow.create_planning_signal.core_export_commit_error"


class PlanningSignalCoreExportCommitScopeError(
    PlanningSignalCoreExportCommitError,
    ValueError,
):
    """Raised when the commit input is not an exact export preview."""

    code = "teacher_workflow.create_planning_signal.core_export_commit_invalid"


class PlanningSignalCoreExportCommitDependencyError(
    PlanningSignalCoreExportCommitError
):
    """Raised when canonical Core/export state cannot be reconciled safely."""

    code = (
        "teacher_workflow.create_planning_signal."
        "core_export_commit_dependency_error"
    )


class PlanningSignalCoreExportCommitStaleError(
    PlanningSignalCoreExportCommitError
):
    """Raised when exact selected-review authorization changed before export."""

    code = "teacher_workflow.create_planning_signal.core_export_commit_stale"

    block_code: GroupingSignalExportBlockCode | None
    reason_codes: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        block_code: GroupingSignalExportBlockCode | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self.block_code = block_code
        self.reason_codes = tuple(sorted(set(reason_codes)))
        super().__init__(message)


class PlanningSignalCoreExportCommitPartialSuccessError(
    PlanningSignalCoreExportCommitError
):
    """Core is durable and exact, but Meridian receipt persistence failed."""

    code = (
        "teacher_workflow.create_planning_signal."
        "core_export_commit_partial_success"
    )

    signal_set_id: str
    core_digest_algorithm: str
    core_signal_digest: str
    core_disposition: str

    def __init__(
        self,
        *,
        signal_set_id: str,
        core_digest_algorithm: str,
        core_signal_digest: str,
        core_disposition: str,
    ) -> None:
        self.signal_set_id = signal_set_id
        self.core_digest_algorithm = core_digest_algorithm
        self.core_signal_digest = core_signal_digest
        self.core_disposition = core_disposition
        super().__init__(
            "Core grouping signal is durably verified, but Meridian export "
            "receipt persistence failed. Retry the exact same export request "
            "to reconcile the receipt."
        )


@dataclass(frozen=True, slots=True)
class PlanningSignalCoreExportCommitResult:
    """Verified exact Core write plus immutable Meridian export receipt."""

    preview: PlanningSignalCoreExportPreview
    export_result: GroupingSignalExportResult

    def __post_init__(self) -> None:
        if not isinstance(self.preview, PlanningSignalCoreExportPreview):
            raise PlanningSignalCoreExportCommitDependencyError(
                "preview must be an exact PlanningSignalCoreExportPreview."
            )
        if not isinstance(self.export_result, GroupingSignalExportResult):
            raise PlanningSignalCoreExportCommitDependencyError(
                "export_result must be the canonical #40 Core/receipt result."
            )

        core = self.export_result.core
        if core.eligibility != self.preview.eligibility:
            raise PlanningSignalCoreExportCommitDependencyError(
                "Canonical export authorization differs from the exact "
                "teacher-reviewed export preview."
            )

        stored_signal = core.write_result.stored
        if stored_signal.signal != self.preview.signal_set:
            raise PlanningSignalCoreExportCommitDependencyError(
                "Stored Core grouping signal differs from the exact reviewed "
                "grouping_signal_set_v1 candidate."
            )

        receipt = self.export_result.receipt.stored.receipt
        eligibility = self.preview.eligibility
        if (
            receipt.class_id != self.preview.signal_set.class_id
            or receipt.signal_set_id != self.preview.signal_set.signal_set_id
            or receipt.created_at != self.preview.signal_set.created_at
            or receipt.derivation_reference != eligibility.derivation_reference
            or receipt.preview_reference != eligibility.preview_reference
            or receipt.review_reference != eligibility.review_reference
            or receipt.core_signal_digest != stored_signal.digest
        ):
            raise PlanningSignalCoreExportCommitDependencyError(
                "Meridian export receipt does not bind the exact reviewed "
                "Core signal and #38/#39 authorization."
            )

    @property
    def core_write_disposition(self) -> str:
        return self.export_result.core.write_result.disposition

    @property
    def receipt_write_disposition(self) -> str:
        return self.export_result.receipt.disposition

    @property
    def core_signal_digest(self) -> str:
        return self.export_result.core.write_result.stored.digest

    @property
    def receipt_sha256(self) -> str:
        return self.export_result.receipt.stored.receipt_sha256

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "performed"

    @property
    def export_receipt_action(self) -> str:
        return "performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"

    @property
    def concord_action(self) -> str:
        return "not_performed"


def commit_planning_signal_core_export(
    workspace_root: str | Path,
    preview: PlanningSignalCoreExportPreview,
) -> PlanningSignalCoreExportCommitResult:
    """Commit only the exact reviewed #40 Core/receipt export.

    The exact selected-review authorization is revalidated before entering
    the canonical #40 exporter. The canonical exporter then performs Core
    roster diagnostics and its own final immediately-before-write
    authorization revalidation before immutable Core persistence.
    """
    if not isinstance(preview, PlanningSignalCoreExportPreview):
        raise PlanningSignalCoreExportCommitScopeError(
            "preview must be an exact PlanningSignalCoreExportPreview."
        )
    preview.__post_init__()

    try:
        current = revalidate_grouping_signal_export_eligibility(
            workspace_root,
            preview.eligibility,
        )
    except GroupingSignalExportBlockedError as error:
        raise PlanningSignalCoreExportCommitStaleError(
            str(error),
            block_code=error.code,
            reason_codes=error.reason_codes,
        ) from error
    except GroupingSignalExportEligibilityError as error:
        raise PlanningSignalCoreExportCommitDependencyError(str(error)) from error

    if current != preview.eligibility:
        raise PlanningSignalCoreExportCommitStaleError(
            "Exact #40 export authorization changed after the teacher preview."
        )

    signal = preview.signal_set
    derivation = preview.eligibility.derivation_reference
    try:
        result = export_grouping_signal(
            workspace_root,
            signal.class_id,
            derivation.derivation_id,
            signal_set_id=signal.signal_set_id,
            created_at=signal.created_at,
        )
    except GroupingSignalExportPartialSuccessError as error:
        raise PlanningSignalCoreExportCommitPartialSuccessError(
            signal_set_id=error.signal_set_id,
            core_digest_algorithm=error.core_digest_algorithm,
            core_signal_digest=error.core_signal_digest,
            core_disposition=error.core_disposition,
        ) from error
    except GroupingSignalExportBlockedError as error:
        raise PlanningSignalCoreExportCommitStaleError(
            str(error),
            block_code=error.code,
            reason_codes=error.reason_codes,
        ) from error
    except (
        GroupingSignalExportEligibilityError,
        GroupingSignalCoreExportError,
        GroupingSignalExportReceiptWorkflowError,
    ) as error:
        raise PlanningSignalCoreExportCommitDependencyError(str(error)) from error

    return PlanningSignalCoreExportCommitResult(
        preview=preview,
        export_result=result,
    )
