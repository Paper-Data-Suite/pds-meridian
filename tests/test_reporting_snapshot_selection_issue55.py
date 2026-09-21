from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
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
    ReportingSnapshotCurrentSelection,
    ReportingSnapshotSelectionConflictError,
    ReportingSnapshotSelectionIntegrityError,
    ReportingSnapshotSelectionValidationError,
    get_current_reporting_snapshot_selection_reference,
    load_current_reporting_snapshot,
    load_current_reporting_snapshot_selection,
    reporting_snapshot_selection_current_path,
    reporting_snapshot_selection_from_json_bytes,
    reporting_snapshot_selection_relative_path,
    reporting_snapshot_selection_sha256,
    reporting_snapshot_selection_to_json_bytes,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    load_reporting_snapshot,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _definition(revision: int = 1) -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title=f"Quarter Grade Report {revision}",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def _target(student_id: str = "student_001") -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="standards_based",
    )


def _preview(target: GradePreviewTarget):
    data = {
        "summary": {
            "requested_count": 1,
            "available_count": 0,
            "unavailable_count": 1,
            "base_calculated_count": 0,
            "base_blocked_count": 0,
            "base_insufficient_count": 0,
            "current_count": 0,
            "stale_count": 0,
            "effective_numeric_count": 0,
            "effective_nonnumeric_count": 0,
            "effective_base_count": 0,
            "effective_override_count": 0,
            "effective_none_count": 0,
        },
        "rows": [
            {
                "target": {
                    "class_id": target.class_id,
                    "student_id": target.student_id,
                    "target_period": {
                        "school_year": target.target_period.school_year,
                        "period_id": target.target_period.period_id,
                    },
                    "calendar_revision": target.calendar_revision,
                    "calculation_family": target.calculation_family,
                },
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
        ],
    }
    encoded = (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return frozen_grade_report_preview_from_json_bytes(encoded)


def _snapshot(
    definition_reference,
    *,
    snapshot_id: str,
    created_at: datetime,
    predecessor: ReportingSnapshotPredecessor | None = None,
):
    target = _target()
    request = ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition_reference,
        grade_requests=(
            ReportingSnapshotGradeRequest(target=target, work_evidence=None),
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze reviewed report.",
        requested_at=NOW,
        predecessor=predecessor,
    )
    return compose_reporting_snapshot(
        snapshot_id=snapshot_id,
        build_request=request,
        report_preview=_preview(target),
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": PERIOD.school_year,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=created_at,
    )


def _setup_snapshots(tmp_path: Path):
    root = _workspace(tmp_path)
    definition = write_reporting_definition_revision(root, _definition()).stored
    snapshot_a = write_reporting_snapshot(
        root,
        _snapshot(
            definition.reference,
            snapshot_id="snapshot_a",
            created_at=NOW,
        ),
    ).stored
    predecessor = ReportingSnapshotPredecessor(
        relationship="replaces_for_current_use",
        snapshot_reference=snapshot_a.reference,
    )
    snapshot_b = write_reporting_snapshot(
        root,
        _snapshot(
            definition.reference,
            snapshot_id="snapshot_b",
            created_at=NOW + timedelta(minutes=5),
            predecessor=predecessor,
        ),
    ).stored
    return root, definition, snapshot_a, snapshot_b


def _select(root: Path, snapshot, expected, minute: int):
    return select_reporting_snapshot(
        root,
        snapshot.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Use this frozen report.",
        decided_at=NOW + timedelta(minutes=minute),
        expected_current=expected,
    )


def test_no_current_selection_before_explicit_selection(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)

    assert get_current_reporting_snapshot_selection_reference(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 1
    ) is None
    assert load_current_reporting_snapshot(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 1
    ) is None
    assert load_reporting_snapshot(root, CLASS_ID, snapshot_a.snapshot.snapshot_id)


def test_freeze_does_not_silently_select_snapshot(tmp_path: Path) -> None:
    root, _, _, _ = _setup_snapshots(tmp_path)

    path = reporting_snapshot_selection_current_path(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 1
    )
    assert not path.exists()


def test_first_explicit_selection_creates_digest_bound_pointer(tmp_path: Path) -> None:
    root, definition, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)

    assert result.disposition == "created"
    assert result.selection.selection.selection_revision == 1
    assert result.selection.selection.previous_selection is None
    assert result.selection.selection.snapshot_reference == snapshot_a.reference
    assert result.selection.selection.definition_reference == definition.reference
    assert result.selection.reference.selection_sha256 == (
        reporting_snapshot_selection_sha256(result.selection.selection)
    )


def test_current_selection_round_trips_canonically(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    encoded = reporting_snapshot_selection_to_json_bytes(
        result.selection.selection
    )

    assert reporting_snapshot_selection_from_json_bytes(encoded) == (
        result.selection.selection
    )
    assert encoded == result.selection.content


def test_selection_path_is_privacy_safe_and_scope_local(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)

    assert result.selection.relative_path == (
        "classes/english_12/modules/meridian/reporting_snapshot_selections/"
        "quarter_grade_report/2026-2027/q1/calendar_1/current.json"
    )
    assert "student_001" not in result.selection.relative_path
    assert result.selection.relative_path == reporting_snapshot_selection_relative_path(
        CLASS_ID, "quarter_grade_report", PERIOD, 1
    )


def test_newer_snapshot_and_relationship_do_not_imply_selection(
    tmp_path: Path,
) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)

    current = load_current_reporting_snapshot(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 1
    )
    assert current is not None
    assert current.reference == snapshot_a.reference
    assert snapshot_b.snapshot.created_at > snapshot_a.snapshot.created_at
    assert snapshot_b.snapshot.predecessor is not None
    assert get_current_reporting_snapshot_selection_reference(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 1
    ) == first.selection.reference


def test_select_new_snapshot_updates_revision_and_prior_exact_state(
    tmp_path: Path,
) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    second = _select(root, snapshot_b, first.selection.reference, 15)

    assert second.disposition == "updated"
    assert second.selection.selection.selection_revision == 2
    assert second.selection.selection.previous_selection == first.selection.reference
    assert second.selection.selection.snapshot_reference == snapshot_b.reference


def test_reselect_historical_snapshot_is_intentional_and_supported(
    tmp_path: Path,
) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    second = _select(root, snapshot_b, first.selection.reference, 15)
    third = _select(root, snapshot_a, second.selection.reference, 20)

    assert third.disposition == "updated"
    assert third.selection.selection.selection_revision == 3
    assert third.selection.selection.snapshot_reference == snapshot_a.reference
    assert third.selection.selection.previous_selection == second.selection.reference


def test_reselect_same_exact_snapshot_is_idempotent(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    second = _select(root, snapshot_a, first.selection.reference, 20)

    assert second.disposition == "existing"
    assert second.selection == first.selection
    assert second.selection.selection.selection_revision == 1


def test_stale_expected_selector_fails_compare_and_swap(tmp_path: Path) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    _select(root, snapshot_b, first.selection.reference, 15)

    with pytest.raises(
        ReportingSnapshotSelectionConflictError,
        match="changed before commit",
    ):
        _select(root, snapshot_a, first.selection.reference, 20)


def test_expected_none_fails_once_selection_exists(tmp_path: Path) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    _select(root, snapshot_a, None, 10)

    with pytest.raises(ReportingSnapshotSelectionConflictError):
        _select(root, snapshot_b, None, 15)


def test_wrong_snapshot_digest_cannot_be_selected(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    bad = type(snapshot_a.reference)(
        class_id=snapshot_a.reference.class_id,
        snapshot_id=snapshot_a.reference.snapshot_id,
        snapshot_sha256="f" * 64,
    )

    with pytest.raises(
        ReportingSnapshotSelectionConflictError,
        match="digest",
    ):
        select_reporting_snapshot(
            root,
            bad,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW + timedelta(minutes=10),
            expected_current=None,
        )


def test_selection_time_cannot_predate_snapshot(tmp_path: Path) -> None:
    root, _, _, snapshot_b = _setup_snapshots(tmp_path)

    with pytest.raises(
        ReportingSnapshotSelectionValidationError,
        match="earlier",
    ):
        select_reporting_snapshot(
            root,
            snapshot_b.reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW + timedelta(minutes=1),
            expected_current=None,
        )


def test_selection_can_move_to_new_definition_revision_same_family(
    tmp_path: Path,
) -> None:
    root, definition_one, snapshot_a, _ = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    definition_two = write_reporting_definition_revision(root, _definition(2)).stored
    snapshot_c = write_reporting_snapshot(
        root,
        _snapshot(
            definition_two.reference,
            snapshot_id="snapshot_c",
            created_at=NOW + timedelta(minutes=20),
        ),
    ).stored
    second = _select(root, snapshot_c, first.selection.reference, 25)

    assert definition_two.reference.definition_revision == 2
    assert definition_one.reference.definition_revision == 1
    assert second.selection.selection.definition_reference == definition_two.reference
    assert second.selection.selection.definition_id == "quarter_grade_report"


def test_different_calendar_revision_is_a_different_selection_scope(
    tmp_path: Path,
) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    current = _select(root, snapshot_a, None, 10)

    assert get_current_reporting_snapshot_selection_reference(
        root, CLASS_ID, "quarter_grade_report", PERIOD, 2
    ) is None
    with pytest.raises(ReportingSnapshotSelectionValidationError, match="different"):
        select_reporting_snapshot(
            root,
            snapshot_a.reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW + timedelta(minutes=11),
            expected_current=type(current.selection.reference)(
                class_id=CLASS_ID,
                definition_id="quarter_grade_report",
                target_period=PERIOD,
                calendar_revision=2,
                selection_revision=1,
                selection_sha256=current.selection.reference.selection_sha256,
            ),
        )


def test_tampered_selected_snapshot_reference_fails_closed(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    path = result.selection.path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["snapshot_reference"]["snapshot_sha256"] = "f" * 64
    path.write_bytes(
        (
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(ReportingSnapshotSelectionIntegrityError, match="digest"):
        load_current_reporting_snapshot_selection(
            root, CLASS_ID, "quarter_grade_report", PERIOD, 1
        )


def test_noncanonical_current_selector_fails_closed(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    data = json.loads(result.selection.content)
    result.selection.path.write_bytes(
        json.dumps(data, sort_keys=True).encode("utf-8")
    )

    with pytest.raises(
        ReportingSnapshotSelectionIntegrityError,
        match="canonically",
    ):
        load_current_reporting_snapshot_selection(
            root, CLASS_ID, "quarter_grade_report", PERIOD, 1
        )


def test_unknown_selector_field_fails_closed(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    data = json.loads(result.selection.content)
    data["unexpected"] = True
    result.selection.path.write_bytes(
        (
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(
        ReportingSnapshotSelectionIntegrityError,
        match="exact schema",
    ):
        load_current_reporting_snapshot_selection(
            root, CLASS_ID, "quarter_grade_report", PERIOD, 1
        )


def test_selector_scope_rejects_unexpected_entry(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    (result.selection.path.parent / "surprise.txt").write_text("x", encoding="utf-8")

    with pytest.raises(
        ReportingSnapshotSelectionIntegrityError,
        match="unexpected entry",
    ):
        load_current_reporting_snapshot_selection(
            root, CLASS_ID, "quarter_grade_report", PERIOD, 1
        )


def test_selector_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    result = _select(root, snapshot_a, None, 10)
    target = tmp_path / "outside.json"
    target.write_bytes(result.selection.content)
    result.selection.path.unlink()
    try:
        os.symlink(target, result.selection.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(ReportingSnapshotSelectionIntegrityError, match="symlink"):
        load_current_reporting_snapshot_selection(
            root, CLASS_ID, "quarter_grade_report", PERIOD, 1
        )


def test_pointer_digest_changes_for_material_selector_change(tmp_path: Path) -> None:
    root, _, snapshot_a, snapshot_b = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)
    second = _select(root, snapshot_b, first.selection.reference, 15)

    assert first.selection.selection_sha256 != second.selection.selection_sha256
    assert first.selection.reference != second.selection.reference


def test_selector_model_rejects_broken_prior_revision_chain(tmp_path: Path) -> None:
    root, _, snapshot_a, _ = _setup_snapshots(tmp_path)
    first = _select(root, snapshot_a, None, 10)

    with pytest.raises(
        ReportingSnapshotSelectionValidationError,
        match="immediately precede",
    ):
        ReportingSnapshotCurrentSelection(
            schema_version=first.selection.selection.schema_version,
            record_type=first.selection.selection.record_type,
            class_id=CLASS_ID,
            definition_id="quarter_grade_report",
            target_period=PERIOD,
            calendar_revision=1,
            selection_revision=3,
            snapshot_reference=snapshot_a.reference,
            definition_reference=snapshot_a.snapshot.definition_reference,
            actor=ReportingActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW + timedelta(minutes=20),
            previous_selection=first.selection.reference,
        )
