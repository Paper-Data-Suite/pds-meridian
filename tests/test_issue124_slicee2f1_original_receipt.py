"""E2F1: exact original receipt inspection is advisory and fail closed."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from meridian.assessment_setup_original_receipt import (
    OriginalReceiptWitness,
    inspect_original_assessment_setup_receipt,
)


def test_witness_never_grants_resume_or_selection() -> None:
    for disposition in ("requires_review", "original_receipt_verified"):
        witness = OriginalReceiptWitness(disposition, "test")
        assert not witness.may_resume_automatically
        assert not witness.may_select_academic_record


def test_invalid_context_refuses_without_observation(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_original_receipt.create_assessment_setup_correlation"
    ) as create:
        result = inspect_original_assessment_setup_receipt(Path("relative"), None, None)
    assert result.disposition == "requires_review"
    assert result.original_preview is None
    create.assert_not_called()


def test_absolute_root_not_sufficient_without_typed_review(tmp_path: Path) -> None:
    result = inspect_original_assessment_setup_receipt(tmp_path, None, None)
    assert result.reason == "invalid_reconstruction_context"
    assert result.original_preview is None
