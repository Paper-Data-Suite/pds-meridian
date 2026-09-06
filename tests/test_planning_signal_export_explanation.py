from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from pds_core.grouping_signal_storage import (
    grouping_signal_digest_path,
    grouping_signal_path,
    write_grouping_signal,
)
from pds_core.grouping_signals import grouping_signal_set_to_json_bytes

from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
)
from meridian.grouping_signal_export import build_grouping_signal_export_candidate
from meridian.grouping_signal_export_receipt import (
    create_grouping_signal_export_receipt,
    grouping_signal_export_receipt_to_json_bytes,
)
from meridian.grouping_signal_export_storage import (
    write_grouping_signal_export_receipt,
)
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
    write_grouping_signal_review_revision,
)
from meridian.planning_signal_export_explanation import (
    PlanningSignalExportTraceTarget,
    explain_planning_signal_export,
    planning_signal_export_explanation_to_json_bytes,
    render_planning_signal_export_explanation_text,
)
from tests.test_planning_signal_derivation_explanation import (
    CLASS_ID,
    NOW,
    _prepared,
)
from tests.test_planning_signal_preview_review_explanation import (
    _review,
    _stored_preview,
)

SIGNAL_SET_ID = "reading_mp1_trace_001"


def _target(signal_set_id: str = SIGNAL_SET_ID) -> PlanningSignalExportTraceTarget:
    return PlanningSignalExportTraceTarget(
        class_id=CLASS_ID,
        signal_set_id=signal_set_id,
    )


def _exported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    stored_review = write_grouping_signal_review_revision(root, review).stored
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        1,
        expected_current_review_revision=None,
    )

    candidate = build_grouping_signal_export_candidate(
        derivation.snapshot,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW,
    )
    core = write_grouping_signal(root, candidate).stored
    receipt = create_grouping_signal_export_receipt(
        derivation_reference=derivation.reference,
        preview_reference=preview.reference,
        review_reference=stored_review.reference,
        signal=core.signal,
        core_signal_digest=core.digest,
    )
    stored_receipt = write_grouping_signal_export_receipt(root, receipt).stored
    return root, derivation, preview, stored_review, core, stored_receipt


def test_target_requires_canonical_core_identity() -> None:
    with pytest.raises(ExplanationTraceTargetError):
        PlanningSignalExportTraceTarget("bad class id", SIGNAL_SET_ID)
    with pytest.raises(ExplanationTraceTargetError):
        PlanningSignalExportTraceTarget(CLASS_ID, "bad signal id")


def test_missing_exact_core_and_receipt_target_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(ExplanationTraceNotFoundError):
        explain_planning_signal_export(tmp_path, _target())


def test_core_without_meridian_receipt_is_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    candidate = build_grouping_signal_export_candidate(
        derivation.snapshot,
        signal_set_id=SIGNAL_SET_ID,
        created_at=NOW,
    )
    write_grouping_signal(root, candidate)

    with pytest.raises(ExplanationTraceIntegrityError, match="without.*receipt"):
        explain_planning_signal_export(root, _target())


def test_export_trace_reconciles_exported_and_omitted_students(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation, preview, review, core, receipt = _exported(
        tmp_path,
        monkeypatch,
    )

    explained = explain_planning_signal_export(root, _target())

    assert explained.signal_set_id == SIGNAL_SET_ID
    assert explained.core_contract == "grouping_signal_set_v1"
    assert explained.core_signal_digest == core.digest
    assert explained.receipt_sha256 == receipt.receipt_sha256
    assert explained.derivation_id == derivation.snapshot.derivation_id
    assert explained.derivation_sha256 == derivation.derivation_sha256
    assert explained.preview_id == preview.snapshot.preview_id
    assert explained.preview_sha256 == preview.preview_sha256
    assert explained.review_revision == 1
    assert explained.review_sha256 == review.review_sha256
    assert explained.review_decision == "accepted_for_export"
    assert explained.dimension_id == derivation.snapshot.dimension_id
    assert explained.band_count == derivation.snapshot.band_count

    students = {item.student_id: item for item in explained.students}
    assert students["student_1"].exported is True
    assert students["student_1"].core_band == students["student_1"].meridian_band
    assert students["student_1"].source_result is not None
    assert students["student_1"].source_result.result_revision == 1
    assert students["student_1"].matching_band_definition is not None

    assert students["student_2"].exported is False
    assert students["student_2"].core_band is None
    assert students["student_2"].noncontribution_reason == "insufficient_evidence"
    assert students["student_2"].policy_handling == "noncontributing"

    assert students["student_3"].exported is False
    assert students["student_3"].source_result is None
    assert students["student_3"].noncontribution_reason == "missing_result"
    assert students["student_3"].policy_handling == "noncontributing"

    nested_student = next(
        item
        for item in explained.nested_derivation_explanation.students
        if item.student_id == "student_1"
    )
    assert nested_student.nested_academic_period_explanation is not None
    assert nested_student.nested_academic_period_explanation.result_revision == 1
    assert nested_student.nested_academic_period_explanation.selection_state == (
        "historical"
    )


def test_receipt_historical_review_is_not_replaced_by_new_selected_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation, preview, _, _, _ = _exported(tmp_path, monkeypatch)
    second = _review(preview, 2, decision="rejected")
    stored_second = write_grouping_signal_review_revision(root, second).stored
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        2,
        expected_current_review_revision=1,
    )

    explained = explain_planning_signal_export(root, _target())

    assert stored_second.review.decision == "rejected"
    assert explained.review_revision == 1
    assert explained.review_decision == "accepted_for_export"


def test_coherent_core_receipt_band_tamper_fails_semantic_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, _, core, receipt = _exported(tmp_path, monkeypatch)
    original_entry = core.signal.student_bands[0]
    changed_band = 2 if original_entry.band != 2 else 1
    changed_signal = replace(
        core.signal,
        student_bands=(replace(original_entry, band=changed_band),),
    )
    core_bytes = grouping_signal_set_to_json_bytes(changed_signal)
    core_digest = hashlib.sha256(core_bytes).hexdigest()
    grouping_signal_path(root, CLASS_ID, SIGNAL_SET_ID).write_bytes(core_bytes)
    grouping_signal_digest_path(root, CLASS_ID, SIGNAL_SET_ID).write_bytes(
        f"{core_digest}\n".encode("ascii")
    )

    changed_receipt = replace(
        receipt.receipt,
        core_signal_digest=core_digest,
    )
    receipt_bytes = grouping_signal_export_receipt_to_json_bytes(changed_receipt)
    receipt.path.write_bytes(receipt_bytes)
    Path(str(receipt.path) + ".sha256").write_bytes(
        (hashlib.sha256(receipt_bytes).hexdigest() + "\n").encode("ascii")
    )

    with pytest.raises(
        ExplanationTraceIntegrityError,
        match="exported band disagrees",
    ):
        explain_planning_signal_export(root, _target())


def test_json_and_text_render_exact_lineage_and_absence_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, _, _, _ = _exported(tmp_path, monkeypatch)
    explained = explain_planning_signal_export(root, _target())

    payload = planning_signal_export_explanation_to_json_bytes(explained).decode()
    text = render_planning_signal_export_explanation_text(explained)

    assert SIGNAL_SET_ID in payload
    assert '"review_revision": 1' in payload
    assert '"noncontribution_reason": "missing_result"' in payload
    assert '"noncontribution_reason": "insufficient_evidence"' in payload
    assert "Planning signal export trace" in text
    assert "decision=accepted_for_export" in text
    assert "student_1" in text and "exported=yes" in text
    assert "student_2" in text and "reason=insufficient_evidence" in text
    assert "student_3" in text and "reason=missing_result" in text
    assert "Nested exact #38 derivation trace:" in text
