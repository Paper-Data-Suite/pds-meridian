from __future__ import annotations

import hashlib
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
    ReportingDefinitionReference,
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
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageConflictError,
    ReportingSnapshotStorageIntegrityError,
    ReportingSnapshotStorageNotFoundError,
    ReportingSnapshotStorageTooLargeError,
    list_reporting_definition_ids,
    list_reporting_definition_revisions,
    list_reporting_snapshot_ids,
    load_reporting_definition_revision,
    load_reporting_snapshot,
    reporting_definition_revision_digest_path,
    reporting_definition_revision_path,
    reporting_definition_revision_relative_path,
    reporting_snapshot_digest_path,
    reporting_snapshot_path,
    reporting_snapshot_relative_path,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 5, 15, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _definition(
    revision: int = 1,
    *,
    definition_id: str = "quarter_grade_report",
    title: str | None = None,
) -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=definition_id,
        definition_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title=title or f"Quarter Grade Report {revision}",
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


def _summary(count: int) -> dict[str, int]:
    return {
        "requested_count": count,
        "available_count": 0,
        "unavailable_count": count,
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
    }


def _preview(*targets: GradePreviewTarget):
    ordered = tuple(
        sorted(
            targets,
            key=lambda value: (
                value.class_id,
                value.student_id,
                value.target_period.school_year,
                value.target_period.period_id,
                value.calendar_revision,
                value.calculation_family,
            ),
        )
    )
    data = {
        "summary": _summary(len(ordered)),
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
            for target in ordered
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
    snapshot_id: str = "snapshot_001",
    predecessor: ReportingSnapshotPredecessor | None = None,
    student_id: str = "student_001",
):
    target = _target(student_id)
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
        created_at=NOW,
    )


def _write_definition(root: Path, revision: int = 1):
    return write_reporting_definition_revision(root, _definition(revision)).stored


def test_definition_first_write_and_exact_reload(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = write_reporting_definition_revision(root, _definition())

    assert result.disposition == "created"
    loaded = load_reporting_definition_revision(
        root, CLASS_ID, "quarter_grade_report", 1
    )
    assert loaded == result.stored
    assert loaded.reference.definition_sha256 == hashlib.sha256(
        loaded.content
    ).hexdigest()
    assert loaded.path.read_bytes() == loaded.content
    assert reporting_definition_revision_digest_path(
        root, CLASS_ID, "quarter_grade_report", 1
    ).read_text(encoding="ascii") == loaded.definition_sha256 + "\n"


def test_definition_exact_replay_is_idempotent(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first = write_reporting_definition_revision(root, _definition())
    second = write_reporting_definition_revision(root, _definition())

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert second.stored == first.stored


def test_definition_contradictory_identity_reuse_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_reporting_definition_revision(root, _definition())

    with pytest.raises(
        ReportingSnapshotStorageConflictError,
        match="different content",
    ):
        write_reporting_definition_revision(
            root,
            _definition(title="Contradictory title"),
        )


def test_definition_history_is_linear_and_historical_revision_survives(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    first = _write_definition(root, 1)
    second = _write_definition(root, 2)

    assert list_reporting_definition_revisions(
        root, CLASS_ID, "quarter_grade_report"
    ) == (1, 2)
    assert load_reporting_definition_revision(
        root, CLASS_ID, "quarter_grade_report", 1
    ) == first
    assert load_reporting_definition_revision(
        root, CLASS_ID, "quarter_grade_report", 2
    ) == second


def test_definition_revision_gap_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_definition(root, 1)

    with pytest.raises(ReportingSnapshotStorageConflictError, match="exactly one"):
        write_reporting_definition_revision(root, _definition(3))


def test_definition_listing_is_deterministic(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_reporting_definition_revision(
        root,
        _definition(definition_id="z_report"),
    )
    write_reporting_definition_revision(
        root,
        _definition(definition_id="a_report"),
    )

    assert list_reporting_definition_ids(root, CLASS_ID) == (
        "a_report",
        "z_report",
    )


def test_definition_relative_path_is_class_local_and_canonical(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = _write_definition(root)

    assert stored.relative_path == (
        "classes/english_12/modules/meridian/reporting_definitions/"
        "quarter_grade_report/revisions/1.json"
    )
    assert stored.relative_path == reporting_definition_revision_relative_path(
        CLASS_ID, "quarter_grade_report", 1
    )
    assert stored.path == reporting_definition_revision_path(
        root, CLASS_ID, "quarter_grade_report", 1
    )


def test_snapshot_first_write_exact_reload_and_reference(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    snapshot = _snapshot(definition.reference)

    result = write_reporting_snapshot(root, snapshot)
    loaded = load_reporting_snapshot(root, CLASS_ID, "snapshot_001")

    assert result.disposition == "created"
    assert loaded == result.stored
    assert loaded.snapshot == snapshot
    assert loaded.reference.snapshot_sha256 == hashlib.sha256(
        loaded.content
    ).hexdigest()
    assert reporting_snapshot_digest_path(
        root, CLASS_ID, "snapshot_001"
    ).read_text(encoding="ascii") == loaded.snapshot_sha256 + "\n"


def test_snapshot_exact_replay_is_idempotent(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    snapshot = _snapshot(definition.reference)

    first = write_reporting_snapshot(root, snapshot)
    second = write_reporting_snapshot(root, snapshot)

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert second.stored == first.stored


def test_snapshot_contradictory_id_reuse_fails(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    changed = _snapshot(
        definition.reference,
        snapshot_id="snapshot_001",
        student_id="student_002",
    )

    with pytest.raises(ReportingSnapshotStorageConflictError):
        write_reporting_snapshot(root, changed)


def test_snapshot_requires_exact_stored_definition(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _definition()
    fake_reference = ReportingDefinitionReference(
        CLASS_ID,
        definition.definition_id,
        definition.definition_revision,
        "f" * 64,
    )

    with pytest.raises(
        ReportingSnapshotStorageIntegrityError,
        match="reporting definition",
    ):
        write_reporting_snapshot(root, _snapshot(fake_reference))


def test_snapshot_definition_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    snapshot = _snapshot(definition.reference)
    write_reporting_snapshot(root, snapshot)

    definition_digest = reporting_definition_revision_digest_path(
        root, CLASS_ID, "quarter_grade_report", 1
    )
    definition_digest.write_text("f" * 64 + "\n", encoding="ascii")

    with pytest.raises(ReportingSnapshotStorageIntegrityError):
        load_reporting_snapshot(root, CLASS_ID, snapshot.snapshot_id)


def test_snapshot_predecessor_must_exist_with_exact_digest(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    first = write_reporting_snapshot(
        root,
        _snapshot(definition.reference, snapshot_id="snapshot_001"),
    ).stored
    predecessor = ReportingSnapshotPredecessor("supersedes", first.reference)
    second = _snapshot(
        definition.reference,
        snapshot_id="snapshot_002",
        predecessor=predecessor,
    )

    written = write_reporting_snapshot(root, second)
    assert written.stored.snapshot.predecessor == predecessor

    first_digest = reporting_snapshot_digest_path(
        root, CLASS_ID, "snapshot_001"
    )
    first_digest.write_text("f" * 64 + "\n", encoding="ascii")
    with pytest.raises(ReportingSnapshotStorageIntegrityError):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_002")


def test_snapshot_write_does_not_create_current_selection(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))

    snapshots = reporting_snapshot_path(root, CLASS_ID, "snapshot_001").parent
    assert not any("current" in entry.name for entry in snapshots.iterdir())


def test_snapshot_listing_is_deterministic_not_timestamp_authority(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    for snapshot_id in ("snapshot_z", "snapshot_a", "snapshot_m"):
        write_reporting_snapshot(
            root,
            _snapshot(definition.reference, snapshot_id=snapshot_id),
        )

    assert list_reporting_snapshot_ids(root, CLASS_ID) == (
        "snapshot_a",
        "snapshot_m",
        "snapshot_z",
    )


def test_snapshot_path_does_not_expose_student_id(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    stored = write_reporting_snapshot(
        root,
        _snapshot(definition.reference, snapshot_id="opaque_snapshot_01"),
    ).stored

    assert "student_001" not in stored.relative_path
    assert stored.relative_path == reporting_snapshot_relative_path(
        CLASS_ID, "opaque_snapshot_01"
    )


def test_snapshot_missing_file_and_missing_digest_fail_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    snapshot_path = reporting_snapshot_path(root, CLASS_ID, "snapshot_001")
    digest_path = reporting_snapshot_digest_path(root, CLASS_ID, "snapshot_001")

    snapshot_path.unlink()
    with pytest.raises(ReportingSnapshotStorageNotFoundError):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_001")

    snapshot_path.write_bytes(b"{}\n")
    digest_path.unlink()
    with pytest.raises(ReportingSnapshotStorageNotFoundError):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_001")


def test_snapshot_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    digest_path = reporting_snapshot_digest_path(root, CLASS_ID, "snapshot_001")
    digest_path.write_bytes(("f" * 64 + "\n").encode("ascii"))

    with pytest.raises(ReportingSnapshotStorageIntegrityError, match="digest"):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_001")


def test_snapshot_malformed_json_fails_closed_even_with_matching_sidecar(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    path = reporting_snapshot_path(root, CLASS_ID, "snapshot_001")
    digest_path = reporting_snapshot_digest_path(root, CLASS_ID, "snapshot_001")
    malformed = b'{"not":"a snapshot"}\n'
    path.write_bytes(malformed)
    digest_path.write_bytes(
        (hashlib.sha256(malformed).hexdigest() + "\n").encode("ascii")
    )

    with pytest.raises(ReportingSnapshotStorageIntegrityError, match="invalid"):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_001")


def test_snapshot_read_is_bounded(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))

    with pytest.raises(ReportingSnapshotStorageTooLargeError):
        load_reporting_snapshot(
            root,
            CLASS_ID,
            "snapshot_001",
            maximum_snapshot_bytes=16,
        )


def test_snapshot_collection_rejects_unexpected_entry(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    collection = reporting_snapshot_path(root, CLASS_ID, "snapshot_001").parent
    (collection / "notes.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ReportingSnapshotStorageIntegrityError, match="unexpected"):
        list_reporting_snapshot_ids(root, CLASS_ID)


def test_definition_collection_rejects_incomplete_digest_pair(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _write_definition(root)
    reporting_definition_revision_digest_path(
        root, CLASS_ID, "quarter_grade_report", 1
    ).unlink()

    with pytest.raises(ReportingSnapshotStorageIntegrityError, match="incomplete"):
        list_reporting_definition_revisions(root, CLASS_ID, "quarter_grade_report")


def test_snapshot_symlink_is_rejected_when_platform_supports_it(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    definition = _write_definition(root)
    write_reporting_snapshot(root, _snapshot(definition.reference))
    path = reporting_snapshot_path(root, CLASS_ID, "snapshot_001")
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    try:
        os.symlink(outside, path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(ReportingSnapshotStorageIntegrityError):
        load_reporting_snapshot(root, CLASS_ID, "snapshot_001")


def test_reporting_storage_path_helpers_reject_traversal(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    from meridian.reporting_snapshot_storage import (
        ReportingSnapshotStorageValidationError,
    )

    with pytest.raises(ReportingSnapshotStorageValidationError):
        reporting_snapshot_path(root, CLASS_ID, "../outside")
    with pytest.raises(ReportingSnapshotStorageValidationError):
        reporting_definition_revision_path(root, CLASS_ID, "../outside", 1)


def test_reporting_storage_rejects_missing_core_class(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ReportingSnapshotStorageNotFoundError, match="Core class"):
        write_reporting_definition_revision(root, _definition())
