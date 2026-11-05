"""#124 E2F2: cancellation and fail-closed recovery port boundaries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from meridian.assessment_setup_restored_port import (
    resume_restored_assessment_setup_selection,
)


def test_cancel_has_no_reads(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_restored_port."
        "inspect_original_assessment_setup_receipt"
    ) as inspection:
        result = resume_restored_assessment_setup_selection(
            tmp_path,
            None,
            None,
            confirmation="CANCEL",  # type: ignore[arg-type]
        )
    inspection.assert_not_called()
    assert result.disposition == "cancelled"


def test_invalid_context_refuses_before_reads(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_restored_port."
        "inspect_original_assessment_setup_receipt"
    ) as inspection:
        result = resume_restored_assessment_setup_selection(
            Path("relative"),
            None,
            None,
            confirmation="RESUME",  # type: ignore[arg-type]
        )
    inspection.assert_not_called()
    assert result.disposition == "requires_review"


def test_nonexact_witness_never_builds_port(tmp_path: Path) -> None:
    from meridian.assessment_setup_original_receipt import OriginalReceiptWitness

    # Invalid values cannot bypass the typed entrance.
    result = resume_restored_assessment_setup_selection(
        tmp_path,
        None,
        None,
        confirmation="RESUME",  # type: ignore[arg-type]
    )
    assert result.disposition == "requires_review"
    assert not OriginalReceiptWitness(
        "requires_review", "unsafe"
    ).may_select_academic_record
