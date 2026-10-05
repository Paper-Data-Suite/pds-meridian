from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
)
from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingSnapshotPredecessor,
)
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    compose_reporting_snapshot,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionConflictError,
    load_current_reporting_snapshot,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_snapshot,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)
from tests import test_issue99_reporting_snapshot_profile as profile99
from tests import test_reporting_snapshot_selection_issue55 as selection55


def test_snapshot_relationships_do_not_imply_current_use_and_selection_is_cas(
    tmp_path: Path,
) -> None:
    root = selection55._workspace(tmp_path)
    definition = write_reporting_definition_revision(
        root,
        selection55._definition(),
    ).stored

    snapshot_a = write_reporting_snapshot(
        root,
        selection55._snapshot(
            definition.reference,
            snapshot_id="issue60_snapshot_a",
            created_at=selection55.NOW,
        ),
    ).stored
    original_a_content = snapshot_a.content
    original_a_digest = snapshot_a.snapshot_sha256

    first = selection55._select(root, snapshot_a, None, 10)

    snapshot_b = write_reporting_snapshot(
        root,
        selection55._snapshot(
            definition.reference,
            snapshot_id="issue60_snapshot_b",
            created_at=selection55.NOW + timedelta(minutes=15),
            predecessor=ReportingSnapshotPredecessor(
                relationship="supersedes",
                snapshot_reference=snapshot_a.reference,
            ),
        ),
    ).stored
    snapshot_c = write_reporting_snapshot(
        root,
        selection55._snapshot(
            definition.reference,
            snapshot_id="issue60_snapshot_c",
            created_at=selection55.NOW + timedelta(minutes=20),
            predecessor=ReportingSnapshotPredecessor(
                relationship="corrects",
                snapshot_reference=snapshot_b.reference,
            ),
        ),
    ).stored

    # Neither successor metadata nor later creation time changes current use.
    current = load_current_reporting_snapshot(
        root,
        selection55.CLASS_ID,
        definition.reference.definition_id,
        selection55.PERIOD,
        1,
    )
    assert current is not None
    assert current.reference == snapshot_a.reference
    assert snapshot_b.snapshot.predecessor is not None
    assert snapshot_b.snapshot.predecessor.relationship == "supersedes"
    assert snapshot_c.snapshot.predecessor is not None
    assert snapshot_c.snapshot.predecessor.relationship == "corrects"

    reloaded_a = load_reporting_snapshot(
        root,
        selection55.CLASS_ID,
        snapshot_a.snapshot.snapshot_id,
    )
    assert reloaded_a.content == original_a_content
    assert reloaded_a.snapshot_sha256 == original_a_digest
    assert reloaded_a.reference == snapshot_a.reference

    second = select_reporting_snapshot(
        root,
        snapshot_b.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Explicitly move current use to the superseding snapshot.",
        decided_at=selection55.NOW + timedelta(minutes=25),
        expected_current=first.selection.reference,
    )
    assert second.selection.selection.snapshot_reference == snapshot_b.reference

    # A stale CAS basis cannot jump to C after current use has already moved to B.
    with pytest.raises(
        ReportingSnapshotSelectionConflictError,
        match="changed before commit",
    ):
        select_reporting_snapshot(
            root,
            snapshot_c.reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale="This stale selection basis must fail.",
            decided_at=selection55.NOW + timedelta(minutes=30),
            expected_current=first.selection.reference,
        )

    third = select_reporting_snapshot(
        root,
        snapshot_c.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Explicitly select the correcting snapshot.",
        decided_at=selection55.NOW + timedelta(minutes=30),
        expected_current=second.selection.reference,
    )
    assert third.selection.selection.snapshot_reference == snapshot_c.reference
    assert third.selection.selection.previous_selection == second.selection.reference

    # Historical A remains byte-for-byte immutable after both later selections.
    reloaded_a_after = load_reporting_snapshot(
        root,
        selection55.CLASS_ID,
        snapshot_a.snapshot.snapshot_id,
    )
    assert reloaded_a_after.content == original_a_content
    assert reloaded_a_after.snapshot_sha256 == original_a_digest
    assert reloaded_a_after.snapshot == snapshot_a.snapshot


def test_stored_profile_snapshot_replays_frozen_policy_scale_band_and_adjustment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = selection55._workspace(tmp_path)
    definition = write_reporting_definition_revision(
        root,
        selection55._definition(),
    ).stored

    encoded, original_observation = profile99._profile_preview_bytes(
        "standards_based",
        monkeypatch,
    )
    frozen = frozen_grade_report_preview_from_json_bytes(encoded)
    target = frozen.rows[0].target

    request = ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition.reference,
        grade_requests=(
            ReportingSnapshotGradeRequest(
                target=target,
                work_evidence=None,
            ),
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze exact Issue 60 historical profile basis.",
        requested_at=selection55.NOW + timedelta(minutes=1),
        predecessor=None,
    )
    snapshot = compose_reporting_snapshot(
        snapshot_id="issue60_profile_history",
        build_request=request,
        report_preview=frozen,
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": selection55.PERIOD.school_year,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=selection55.NOW + timedelta(minutes=2),
    )
    stored = write_reporting_snapshot(root, snapshot).stored
    original_content = stored.content
    original_digest = stored.snapshot_sha256

    reloaded = load_reporting_snapshot(
        root,
        selection55.CLASS_ID,
        "issue60_profile_history",
    )
    assert reloaded.content == original_content
    assert reloaded.snapshot_sha256 == original_digest

    row = reloaded.snapshot.report_preview.rows[0]
    assert row.observation == original_observation
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json)
    formula = explanation["formula"]

    # These are historical facts frozen into A, not values re-resolved from live
    # policy/scale state when the snapshot is later read.
    assert formula["aggregation_strategy"] == "profile_constrained_mean"
    assert formula["base_unrounded_grade"] == "87"
    assert formula["selected_profile_band_id"] == "high"
    assert formula["selected_profile_band_minimum_grade"] == "90"
    assert formula["selected_profile_band_maximum_grade"] == "100"
    assert formula["profile_adjustment"] == "floor"
    assert formula["profile_evaluation"]["bands"][0]["status"] == "matched"

    prior = row.observation
    assert prior is not None
    prior_entries = {entry.key: entry.sha256 for entry in prior.basis_entries}
    assert "standards_formula" in prior_entries
    assert "standards_profile_policy" in prior_entries
    assert "standards_profile_band" in prior_entries
    assert "standards_profile_adjustment" in prior_entries

    # Simulate a later live Grade basis whose exact scale/conversion formula and
    # profile policy have changed. Comparison must report movement relative to A;
    # it must not rewrite A into the live basis.
    current_entries = tuple(
        replace(
            entry,
            sha256=(
                "e" * 64
                if entry.key == "standards_formula"
                else "f" * 64
            ),
        )
        if entry.key in {"standards_formula", "standards_profile_policy"}
        else entry
        for entry in prior.basis_entries
    )
    current = replace(
        prior,
        inputs_sha256="8" * 64,
        calculation_fingerprint="9" * 64,
        basis_entries=current_entries,
    )
    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(prior),
    )
    assert comparison.reasons == (
        "formula_changed",
        "profile_policy_changed",
    )

    reloaded_again = load_reporting_snapshot(
        root,
        selection55.CLASS_ID,
        "issue60_profile_history",
    )
    assert reloaded_again.content == original_content
    assert reloaded_again.snapshot_sha256 == original_digest
    assert reloaded_again.snapshot.report_preview.rows[0].observation == prior

    replay = json.loads(
        reloaded_again.snapshot.report_preview.rows[0].explanation_json
    )
    replay_formula = replay["formula"]
    assert replay_formula["base_unrounded_grade"] == "87"
    assert replay_formula["selected_profile_band_id"] == "high"
    assert replay_formula["selected_profile_band_minimum_grade"] == "90"
    assert replay_formula["selected_profile_band_maximum_grade"] == "100"
    assert replay_formula["profile_adjustment"] == "floor"
