"""High-level #40 Core export plus immutable Meridian receipt reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meridian.grouping_signal_export_receipt import (
    create_grouping_signal_export_receipt,
)
from meridian.grouping_signal_export_storage import (
    GroupingSignalExportReceiptStorageError,
    GroupingSignalExportReceiptStorageNotFoundError,
    GroupingSignalExportReceiptWriteResult,
    StoredGroupingSignalExportReceipt,
    load_grouping_signal_export_receipt,
    write_grouping_signal_export_receipt,
)
from meridian.grouping_signal_export_workflow import (
    GroupingSignalCoreExportResult,
    export_grouping_signal_to_core,
)


class GroupingSignalExportReceiptWorkflowError(RuntimeError):
    """Base error for #40 Core/receipt reconciliation."""


class GroupingSignalExportReceiptIntegrityError(
    GroupingSignalExportReceiptWorkflowError
):
    """Raised when pre-existing receipt/Core state cannot be reconciled safely."""

    code = "receipt_integrity_failed"


class GroupingSignalExportPartialSuccessError(
    GroupingSignalExportReceiptWorkflowError
):
    """Core is exact and durable, but Meridian receipt persistence failed."""

    code = "partial_core_write_success"

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
            "Core grouping signal is durably verified but Meridian export "
            "receipt persistence failed; retry the exact export request."
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalExportResult:
    """Verified Core signal plus its immutable Meridian audit receipt."""

    core: GroupingSignalCoreExportResult
    receipt: GroupingSignalExportReceiptWriteResult

    def __post_init__(self) -> None:
        if not isinstance(self.core, GroupingSignalCoreExportResult):
            raise GroupingSignalExportReceiptIntegrityError(
                "core must be a GroupingSignalCoreExportResult."
            )
        if not isinstance(
            self.receipt,
            GroupingSignalExportReceiptWriteResult,
        ):
            raise GroupingSignalExportReceiptIntegrityError(
                "receipt must be a GroupingSignalExportReceiptWriteResult."
            )
        stored_signal = self.core.write_result.stored
        stored_receipt = self.receipt.stored
        if (
            stored_receipt.receipt.class_id != stored_signal.signal.class_id
            or stored_receipt.receipt.signal_set_id
            != stored_signal.signal.signal_set_id
            or stored_receipt.receipt.core_signal_digest != stored_signal.digest
        ):
            raise GroupingSignalExportReceiptIntegrityError(
                "Receipt does not bind the exact Core export result."
            )


def export_grouping_signal(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    *,
    signal_set_id: str,
    created_at: datetime,
) -> GroupingSignalExportResult:
    """Export through Core and reconcile the exact Meridian audit receipt."""

    _preflight_existing_receipt(
        workspace_root,
        class_id,
        signal_set_id,
    )

    core_result = export_grouping_signal_to_core(
        workspace_root,
        class_id,
        derivation_id,
        signal_set_id=signal_set_id,
        created_at=created_at,
    )
    stored_core = core_result.write_result.stored
    receipt = create_grouping_signal_export_receipt(
        derivation_reference=core_result.eligibility.derivation_reference,
        preview_reference=core_result.eligibility.preview_reference,
        review_reference=core_result.eligibility.review_reference,
        signal=stored_core.signal,
        core_signal_digest=stored_core.digest,
    )
    try:
        receipt_result = write_grouping_signal_export_receipt(
            workspace_root,
            receipt,
        )
    except GroupingSignalExportReceiptStorageError as error:
        raise GroupingSignalExportPartialSuccessError(
            signal_set_id=stored_core.signal.signal_set_id,
            core_digest_algorithm=stored_core.digest_algorithm,
            core_signal_digest=stored_core.digest,
            core_disposition=core_result.write_result.disposition,
        ) from error

    return GroupingSignalExportResult(
        core=core_result,
        receipt=receipt_result,
    )


def _preflight_existing_receipt(
    workspace_root: str | Path,
    class_id: str,
    signal_set_id: str,
) -> StoredGroupingSignalExportReceipt | None:
    try:
        return load_grouping_signal_export_receipt(
            workspace_root,
            class_id,
            signal_set_id,
        )
    except GroupingSignalExportReceiptStorageNotFoundError:
        return None
    except GroupingSignalExportReceiptStorageError as error:
        raise GroupingSignalExportReceiptIntegrityError(
            "Existing export receipt/Core state is incomplete, corrupt, or "
            "digest-mismatched; no Core recreation was attempted."
        ) from error
