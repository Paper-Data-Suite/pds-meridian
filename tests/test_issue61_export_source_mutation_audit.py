from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import meridian.report_export_commit as commit_module
import meridian.report_export_preview as preview_module
from meridian.export_profile_storage import write_export_profile_revision
from meridian.report_export_commit import (
    ReportExportArtifactConflictError,
    ReportExportCurrentnessConflictError,
    commit_report_export,
    file_export_destination,
)
from meridian.report_export_preview import (
    build_export_preview,
    export_preview_to_json_bytes,
)
from meridian.report_export_receipt import (
    ReportExportActor,
    export_receipt_to_dict,
    report_export_receipt_path,
)
from meridian.reporting_snapshot_storage import write_reporting_snapshot
from tests import test_export_profile_storage_issue56 as profile_support
from tests import test_report_export_commit_issue56 as commit_support
from tests import test_reporting_snapshot_storage_issue55 as snapshot_support


def _workspace_file_state(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "reporting_exports" in relative.parts:
            continue
        result[relative.as_posix()] = path.read_bytes()
    return result


def _exact_snapshot_and_profile(tmp_path: Path):
    root = snapshot_support._workspace(tmp_path)
    definition = snapshot_support._write_definition(root)
    snapshot = write_reporting_snapshot(
        root,
        snapshot_support._snapshot(definition.reference),
    ).stored
    profile = write_export_profile_revision(
        root,
        profile_support._profile(),
    ).stored
    return root, snapshot, profile


def test_issue61_preview_is_deterministic_and_zero_write(
    tmp_path: Path,
) -> None:
    root, snapshot, profile = _exact_snapshot_and_profile(tmp_path)
    before = _workspace_file_state(root)

    first = build_export_preview(
        root,
        snapshot.reference,
        profile.reference,
    )
    middle = _workspace_file_state(root)
    second = build_export_preview(
        root,
        snapshot.reference,
        profile.reference,
    )
    after = _workspace_file_state(root)

    assert middle == before
    assert after == before
    assert first.payload == second.payload
    assert export_preview_to_json_bytes(first.preview) == (
        export_preview_to_json_bytes(second.preview)
    )
    assert first.preview.preview_sha256 == second.preview.preview_sha256
    assert first.preview.payload_sha256 == second.preview.payload_sha256


def test_issue61_preview_has_no_academic_mutation_or_recalculation_calls() -> None:
    source = inspect.getsource(preview_module.build_export_preview)

    for forbidden in (
        "write_",
        "select_",
        "calculate_",
        "resolve_effective_grade",
        "explain_current_grade_preview",
    ):
        assert forbidden not in source


def test_issue61_commit_revalidates_then_changes_only_artifact_and_receipt(
    tmp_path: Path,
) -> None:
    root, snapshot, profile = _exact_snapshot_and_profile(tmp_path)
    approved = build_export_preview(
        root,
        snapshot.reference,
        profile.reference,
    )
    before = _workspace_file_state(root)
    destination = tmp_path / "grades.csv"

    committed = commit_report_export(
        root,
        export_id="issue61_export_001",
        approved_preview=approved.preview,
        destination=file_export_destination(destination),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale=None,
        exported_at=commit_support.NOW,
    )

    assert destination.read_bytes() == approved.payload
    assert committed.preview.payload == approved.payload
    assert _workspace_file_state(root) == before
    assert report_export_receipt_path(
        root,
        snapshot_support.CLASS_ID,
        "issue61_export_001",
    ).is_file()

    receipt_data = export_receipt_to_dict(committed.receipt.receipt)
    assert "external_system_accepted" not in receipt_data
    assert "external_acknowledgement" not in receipt_data
    encoded = committed.receipt.content.lower()
    assert b"external_system_accepted" not in encoded
    assert b"external_acknowledgement" not in encoded


def test_issue61_material_drift_fails_before_artifact_or_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = commit_support._workspace(tmp_path)
    approved = commit_support._roster_built("Alex Rivera")
    rebuilt = commit_support._roster_built("Alexis Rivera")
    commit_support._patch_rebuild(monkeypatch, rebuilt)
    destination = tmp_path / "drift.csv"

    with pytest.raises(
        ReportExportCurrentnessConflictError,
        match="no longer matches",
    ):
        commit_report_export(
            root,
            export_id="issue61_drift_001",
            approved_preview=approved.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=commit_support.NOW,
        )

    assert not destination.exists()
    assert not report_export_receipt_path(
        root,
        commit_support.CLASS_ID,
        "issue61_drift_001",
    ).exists()


def test_issue61_existing_different_file_is_never_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = commit_support._workspace(tmp_path)
    built = commit_support._snapshot_only_built()
    commit_support._patch_rebuild(monkeypatch, built)
    destination = tmp_path / "grades.csv"
    original = b"teacher-owned-existing-bytes\n"
    destination.write_bytes(original)

    with pytest.raises(
        ReportExportArtifactConflictError,
        match="different bytes",
    ):
        commit_report_export(
            root,
            export_id="issue61_no_overwrite_001",
            approved_preview=built.preview,
            destination=file_export_destination(destination),
            actor=ReportExportActor("teacher", "teacher_local"),
            rationale=None,
            exported_at=commit_support.NOW,
        )

    assert destination.read_bytes() == original
    assert not report_export_receipt_path(
        root,
        commit_support.CLASS_ID,
        "issue61_no_overwrite_001",
    ).exists()


def test_issue61_commit_module_has_no_external_delivery_acknowledgement_api() -> None:
    source = inspect.getsource(commit_module.commit_report_export)

    assert "clipboard" not in source.lower()
    assert "external_system" not in source.lower()
    assert "acknowledg" not in source.lower()
