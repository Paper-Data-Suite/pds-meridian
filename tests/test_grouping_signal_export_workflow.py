from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pds_core.grouping_signal_diagnostics import (
    GroupingSignalDimensionDiagnostics,
)
from pds_core.grouping_signal_diagnostics import (
    diagnose_grouping_signal as core_diagnose_grouping_signal,
)
from pds_core.grouping_signal_storage import (
    list_grouping_signal_ids,
    load_grouping_signal,
)

import meridian.grouping_signal_export_workflow as export_workflow
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockedError,
)
from meridian.grouping_signal_export_workflow import (
    GroupingSignalCoreExportConflictError,
    GroupingSignalCoreExportInvariantError,
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


def test_core_export_writes_exact_reviewed_signal_and_preserves_partial_coverage(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review, derivation_id = _seed(tmp_path)

    result = export_grouping_signal_to_core(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_export_001",
        created_at=NOW,
    )

    assert result.write_result.disposition == "created"
    assert result.eligibility.review_reference == stored_review.reference
    assert result.diagnostics.has_errors is False
    assert (
        result.diagnostics.roster_student_count
        == stored_preview.snapshot.coverage.roster_student_count
    )
    dimension = result.diagnostics.dimensions[0]
    assert (
        dimension.matched_student_count
        == stored_preview.snapshot.coverage.contributing_student_count
    )
    assert (
        dimension.missing_student_count
        == stored_preview.snapshot.coverage.noncontributing_student_count
    )

    stored = load_grouping_signal(
        root,
        CLASS_ID,
        "reading_mp1_export_001",
    )
    assert stored == result.write_result.stored
    assert stored.signal.source.module_id == "meridian"
    assert stored.signal.source.snapshot_id == derivation_id
    assert (
        stored.signal.source.snapshot_digest
        == stored_review.review.derivation_reference.derivation_sha256
    )
    assert list_grouping_signal_ids(root, CLASS_ID) == (
        "reading_mp1_export_001",
    )


def test_exact_core_export_retry_is_idempotent_existing(tmp_path: Path) -> None:
    root, _, _, derivation_id = _seed(tmp_path)

    first = export_grouping_signal_to_core(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_export_retry",
        created_at=NOW,
    )
    second = export_grouping_signal_to_core(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_export_retry",
        created_at=NOW,
    )

    assert first.write_result.disposition == "created"
    assert second.write_result.disposition == "existing"
    assert first.write_result.stored == second.write_result.stored
    assert list_grouping_signal_ids(root, CLASS_ID) == (
        "reading_mp1_export_retry",
    )


def test_same_core_identity_with_different_bytes_fails_closed(
    tmp_path: Path,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)

    export_grouping_signal_to_core(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id="reading_mp1_export_conflict",
        created_at=NOW,
    )

    with pytest.raises(GroupingSignalCoreExportConflictError) as raised:
        export_grouping_signal_to_core(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id="reading_mp1_export_conflict",
            created_at=NOW.replace(minute=NOW.minute + 1),
        )

    assert raised.value.code == "core_signal_conflict"
    stored = load_grouping_signal(
        root,
        CLASS_ID,
        "reading_mp1_export_conflict",
    )
    assert stored.signal.created_at == NOW


def test_core_diagnostic_distribution_mismatch_blocks_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)

    def mismatched_diagnostics(workspace_root, signal, *, expected_class_id=None):
        report = core_diagnose_grouping_signal(
            workspace_root,
            signal,
            expected_class_id=expected_class_id,
        )
        dimension = report.dimensions[0]
        counts = list(dimension.band_counts)
        source_index = next(
            index for index, (_, count) in enumerate(counts) if count > 0
        )
        target_index = next(
            index for index in range(len(counts)) if index != source_index
        )
        source_band, source_count = counts[source_index]
        target_band, target_count = counts[target_index]
        counts[source_index] = (source_band, source_count - 1)
        counts[target_index] = (target_band, target_count + 1)
        bad_dimension = GroupingSignalDimensionDiagnostics(
            dimension_id=dimension.dimension_id,
            band_count=dimension.band_count,
            roster_student_count=dimension.roster_student_count,
            signal_entry_count=dimension.signal_entry_count,
            matched_student_count=dimension.matched_student_count,
            missing_student_count=dimension.missing_student_count,
            unknown_student_count=dimension.unknown_student_count,
            wrong_class_student_count=dimension.wrong_class_student_count,
            band_counts=tuple(counts),
        )
        return replace(report, dimensions=(bad_dimension,))

    monkeypatch.setattr(
        export_workflow,
        "diagnose_grouping_signal",
        mismatched_diagnostics,
    )

    with pytest.raises(
        GroupingSignalCoreExportInvariantError,
        match="band distribution",
    ):
        export_grouping_signal_to_core(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id="reading_mp1_export_bad_diag",
            created_at=NOW,
        )

    assert list_grouping_signal_ids(root, CLASS_ID) == ()


def test_final_revalidation_failure_prevents_core_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, _, derivation_id = _seed(tmp_path)
    calls: list[str] = []

    original_revalidate = (
        export_workflow.revalidate_grouping_signal_export_eligibility
    )

    def blocked_revalidate(workspace_root, expected):
        calls.append("revalidate")
        original_revalidate(workspace_root, expected)
        raise GroupingSignalExportBlockedError("review_selection_changed")

    def forbidden_write(*args, **kwargs):
        calls.append("write")
        raise AssertionError("Core write must not run after failed revalidation.")

    monkeypatch.setattr(
        export_workflow,
        "revalidate_grouping_signal_export_eligibility",
        blocked_revalidate,
    )
    monkeypatch.setattr(
        export_workflow,
        "write_grouping_signal",
        forbidden_write,
    )

    with pytest.raises(GroupingSignalExportBlockedError) as raised:
        export_grouping_signal_to_core(
            root,
            CLASS_ID,
            derivation_id,
            signal_set_id="reading_mp1_export_revalidate",
            created_at=NOW,
        )

    assert raised.value.code == "review_selection_changed"
    assert calls == ["revalidate"]
    assert list_grouping_signal_ids(root, CLASS_ID) == ()
