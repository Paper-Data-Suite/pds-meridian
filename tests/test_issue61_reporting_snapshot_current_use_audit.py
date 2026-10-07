from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import meridian.reporting_snapshot_freeze as freeze_module
from meridian.reporting_snapshot import ReportingActor, ReportingSnapshotPredecessor
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_to_current_observations,
)
from meridian.reporting_snapshot_record import reporting_snapshot_to_json_bytes
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionConflictError,
    get_current_reporting_snapshot_selection_reference,
    load_current_reporting_snapshot,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_snapshot,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)
from tests import test_reporting_snapshot_comparison_issue55 as comparison_support
from tests import test_reporting_snapshot_freeze_issue55 as freeze_support
from tests import test_reporting_snapshot_selection_issue55 as selection_support


@pytest.mark.parametrize(
    "relationship",
    ("supersedes", "corrects", "replaces_for_current_use"),
)
def test_issue61_predecessor_metadata_never_selects_current_use(
    tmp_path: Path,
    relationship: str,
) -> None:
    root = selection_support._workspace(tmp_path)
    definition = write_reporting_definition_revision(
        root,
        selection_support._definition(),
    ).stored
    first = write_reporting_snapshot(
        root,
        selection_support._snapshot(
            definition.reference,
            snapshot_id=f"issue61_{relationship}_a",
            created_at=selection_support.NOW,
        ),
    ).stored
    second = write_reporting_snapshot(
        root,
        selection_support._snapshot(
            definition.reference,
            snapshot_id=f"issue61_{relationship}_b",
            created_at=selection_support.NOW + timedelta(minutes=5),
            predecessor=ReportingSnapshotPredecessor(
                relationship=relationship,  # type: ignore[arg-type]
                snapshot_reference=first.reference,
            ),
        ),
    ).stored

    assert second.snapshot.predecessor is not None
    assert second.snapshot.predecessor.relationship == relationship
    assert get_current_reporting_snapshot_selection_reference(
        root,
        selection_support.CLASS_ID,
        definition.reference.definition_id,
        selection_support.PERIOD,
        1,
    ) is None
    assert load_current_reporting_snapshot(
        root,
        selection_support.CLASS_ID,
        definition.reference.definition_id,
        selection_support.PERIOD,
        1,
    ) is None


def test_issue61_current_use_is_explicit_digest_bound_and_historical(
    tmp_path: Path,
) -> None:
    root, definition, first_snapshot, second_snapshot = (
        selection_support._setup_snapshots(tmp_path)
    )

    first = selection_support._select(
        root,
        first_snapshot,
        None,
        10,
    )
    second = selection_support._select(
        root,
        second_snapshot,
        first.selection.reference,
        15,
    )
    historical = selection_support._select(
        root,
        first_snapshot,
        second.selection.reference,
        20,
    )

    current = load_current_reporting_snapshot(
        root,
        selection_support.CLASS_ID,
        definition.reference.definition_id,
        selection_support.PERIOD,
        1,
    )
    assert current is not None
    assert current.reference == first_snapshot.reference
    assert historical.selection.selection.selection_revision == 3
    assert historical.selection.selection.previous_selection == (
        second.selection.reference
    )

    with pytest.raises(ReportingSnapshotSelectionConflictError):
        selection_support._select(
            root,
            second_snapshot,
            first.selection.reference,
            25,
        )


def test_issue61_wrong_snapshot_digest_cannot_become_current(
    tmp_path: Path,
) -> None:
    root, _, first_snapshot, _ = selection_support._setup_snapshots(tmp_path)
    bad_reference = replace(
        first_snapshot.reference,
        snapshot_sha256="f" * 64,
    )

    with pytest.raises(
        ReportingSnapshotSelectionConflictError,
        match="digest",
    ):
        select_reporting_snapshot(
            root,
            bad_reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale="Reject digest drift.",
            decided_at=selection_support.NOW + timedelta(minutes=10),
            expected_current=None,
        )


def test_issue61_selection_never_rewrites_frozen_snapshot_or_grade_state(
    tmp_path: Path,
) -> None:
    root, _, first_snapshot, second_snapshot = (
        selection_support._setup_snapshots(tmp_path)
    )
    original_content = first_snapshot.content
    original_digest = first_snapshot.snapshot_sha256

    first = selection_support._select(root, first_snapshot, None, 10)
    selection_support._select(
        root,
        second_snapshot,
        first.selection.reference,
        15,
    )

    historical = load_reporting_snapshot(
        root,
        selection_support.CLASS_ID,
        first_snapshot.snapshot.snapshot_id,
    )
    assert historical.content == original_content
    assert historical.snapshot_sha256 == original_digest
    assert historical.snapshot == first_snapshot.snapshot

    row = historical.snapshot.report_preview.rows[0]
    assert row.status == "unavailable"
    assert row.unavailable_reason == "no_selected_grade"
    assert row.observation is None


def test_issue61_freeze_persists_history_without_selecting_current_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = freeze_support._workspace(tmp_path)
    definition, request, build = freeze_support._setup_request(root)
    report = freeze_support._preview(request.target)
    calls = 0

    def stable_report(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return report

    monkeypatch.setattr(
        freeze_module,
        "explain_grade_report_preview",
        stable_report,
    )

    stored = freeze_module.freeze_reporting_snapshot(
        root,
        snapshot_id="issue61_freeze_only",
        build_request=build,
        preview_requests=(request,),
        created_at=freeze_support.NOW + timedelta(minutes=1),
    )

    assert calls == 2
    assert stored.snapshot.definition_reference == definition.reference
    assert get_current_reporting_snapshot_selection_reference(
        root,
        freeze_support.CLASS_ID,
        definition.reference.definition_id,
        freeze_support.PERIOD,
        1,
    ) is None


def test_issue61_comparison_is_descriptive_and_snapshot_neutral() -> None:
    prior = comparison_support._observation()
    snapshot = comparison_support._snapshot(prior)
    before = reporting_snapshot_to_json_bytes(snapshot)
    current = replace(
        prior,
        base_freshness_status="stale",
        base_freshness_reasons=("inputs_changed",),
        effective_grade=None,
        effective_source="none",
    )

    comparisons = compare_reporting_snapshot_to_current_observations(
        snapshot,
        (current,),
    )

    assert comparisons[0].relationship == "comparable"
    assert "freshness_changed" in comparisons[0].reasons
    assert "effective_grade_changed" in comparisons[0].reasons
    assert "effective_source_changed" in comparisons[0].reasons
    assert reporting_snapshot_to_json_bytes(snapshot) == before
    assert snapshot.report_preview.rows[0].observation == prior
