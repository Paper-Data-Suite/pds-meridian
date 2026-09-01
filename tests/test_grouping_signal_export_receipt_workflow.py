from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import (
    grouping_signal_digest_path,
    grouping_signal_path,
    load_grouping_signal,
)

import meridian.grouping_signal_export_receipt_workflow as receipt_workflow
from meridian.grouping_signal_export_receipt import (
    grouping_signal_export_receipt_to_dict,
)
from meridian.grouping_signal_export_receipt_workflow import (
    GroupingSignalExportPartialSuccessError,
    GroupingSignalExportReceiptIntegrityError,
    export_grouping_signal,
)
from meridian.grouping_signal_export_storage import (
    GroupingSignalExportReceiptStorageNotFoundError,
    GroupingSignalExportReceiptStorageWriteError,
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_export_workflow import (
    export_grouping_signal_to_core,
)
from tests.test_grouping_signal_export_eligibility import (
    CLASS_ID,
    NOW,
    _seed_selected_accepted_review,
)


def _seed(tmp_path: Path):
    root, stored_preview, stored_review = _seed_selected_accepted_review(
        tmp_path
    )
    return (
        root,
        stored_preview,
        stored_review,
        stored_review.review.derivation_reference.derivation_id,
    )


def test_export_creates_minimal_exact_receipt_after_core_write(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review, derivation_id = _seed(tmp_path)

    result = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_receipt_001",
        created_at=NOW,
    )

    assert result.core.write_result.disposition == "created"
    assert result.receipt.disposition == "created"
    receipt = result.receipt.stored.receipt
    assert receipt.derivation_reference == stored_review.review.derivation_reference
    assert receipt.preview_reference == stored_preview.reference
    assert receipt.review_reference == stored_review.reference
    assert receipt.core_contract == "grouping_signal_set_v1"
    assert receipt.core_digest_algorithm == "sha256"
    assert (
        receipt.core_signal_digest
        == result.core.write_result.stored.digest
    )

    payload = grouping_signal_export_receipt_to_dict(receipt)
    assert set(payload) == {
        "schema_version",
        "record_type",
        "class_id",
        "signal_set_id",
        "created_at",
        "derivation_reference",
        "preview_reference",
        "review_reference",
        "core_contract",
        "core_digest_algorithm",
        "core_signal_digest",
    }
    serialized = repr(payload)
    for forbidden in (
        "student_bands",
        "student_id",
        "band_count",
        "proficiency_level_id",
        "scale_position",
        "student_name",
        "display_name",
        "percentage",
    ):
        assert forbidden not in serialized


def test_exact_retry_reconciles_core_and_receipt_as_existing(
    tmp_path: Path,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)

    first = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_receipt_retry",
        created_at=NOW,
    )
    second = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_receipt_retry",
        created_at=NOW,
    )

    assert first.core.write_result.disposition == "created"
    assert first.receipt.disposition == "created"
    assert second.core.write_result.disposition == "existing"
    assert second.receipt.disposition == "existing"
    assert first.core.write_result.stored == second.core.write_result.stored
    assert first.receipt.stored == second.receipt.stored


def test_exact_existing_core_with_missing_receipt_is_reconciled(
    tmp_path: Path,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)

    core = export_grouping_signal_to_core(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_receipt_recovery",
        created_at=NOW,
    )
    assert core.write_result.disposition == "created"
    with pytest.raises(GroupingSignalExportReceiptStorageNotFoundError):
        load_grouping_signal_export_receipt(
            root,
            CLASS_ID,
            "reading_mp1_receipt_recovery",
        )

    recovered = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_receipt_recovery",
        created_at=NOW,
    )
    assert recovered.core.write_result.disposition == "existing"
    assert recovered.receipt.disposition == "created"
    assert (
        recovered.receipt.stored.receipt.core_signal_digest
        == core.write_result.stored.digest
    )


def test_existing_receipt_with_missing_core_fails_before_core_recreation(
    tmp_path: Path,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)
    signal_set_id = "reading_mp1_receipt_missing_core"

    export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )
    json_path = grouping_signal_path(root, CLASS_ID, signal_set_id)
    digest_path = grouping_signal_digest_path(root, CLASS_ID, signal_set_id)
    json_path.unlink()
    digest_path.unlink()

    with pytest.raises(GroupingSignalExportReceiptIntegrityError) as raised:
        export_grouping_signal(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id=signal_set_id,
            created_at=NOW,
        )

    assert raised.value.code == "receipt_integrity_failed"
    assert not json_path.exists()
    assert not digest_path.exists()


def test_post_core_receipt_failure_surfaces_recoverable_partial_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)
    signal_set_id = "reading_mp1_receipt_partial"
    original_write = receipt_workflow.write_grouping_signal_export_receipt

    def fail_receipt(*args, **kwargs):
        raise GroupingSignalExportReceiptStorageWriteError(
            "synthetic receipt failure"
        )

    monkeypatch.setattr(
        receipt_workflow,
        "write_grouping_signal_export_receipt",
        fail_receipt,
    )

    with pytest.raises(GroupingSignalExportPartialSuccessError) as raised:
        export_grouping_signal(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id=signal_set_id,
            created_at=NOW,
        )

    partial = raised.value
    assert partial.code == "partial_core_write_success"
    assert partial.signal_set_id == signal_set_id
    stored_core = load_grouping_signal(root, CLASS_ID, signal_set_id)
    assert partial.core_signal_digest == stored_core.digest

    monkeypatch.setattr(
        receipt_workflow,
        "write_grouping_signal_export_receipt",
        original_write,
    )
    recovered = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )
    assert recovered.core.write_result.disposition == "existing"
    assert recovered.receipt.disposition == "created"
    assert recovered.receipt.stored.receipt.core_signal_digest == stored_core.digest


def test_receipt_tamper_fails_closed(tmp_path: Path) -> None:
    root, _, _, derivation_id = _seed(tmp_path)
    signal_set_id = "reading_mp1_receipt_tamper"
    result = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )

    receipt_path = result.receipt.stored.path
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")

    with pytest.raises(GroupingSignalExportReceiptIntegrityError):
        export_grouping_signal(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id=signal_set_id,
            created_at=NOW,
        )
