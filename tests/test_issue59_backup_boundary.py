"""Issue #59 opaque whole-workspace backup/restore boundary tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import meridian.conventional_grade_storage as conventional_storage
from meridian.export_profile_storage import (
    load_current_export_profile,
    write_export_profile_revision,
)
from meridian.report_export_preview import compose_export_preview
from meridian.report_export_receipt import (
    ReportExportActor,
    ReportExportDestinationReceipt,
    export_receipt_from_preview,
    load_export_receipt,
    write_export_receipt,
)
from meridian.reporting_snapshot_selection import load_current_reporting_snapshot
from meridian.reporting_snapshot_storage import (
    load_reporting_definition_revision,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)
from tests import test_conventional_grade_storage as grade_support
from tests import test_export_profile_storage_issue56 as export_profile_support
from tests import test_report_export_preview_issue56 as export_preview_support
from tests import test_report_export_receipt_issue56 as receipt_support
from tests import test_reporting_snapshot_selection_issue55 as snapshot_support


def _workspace_bytes(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    )


def _assert_contained(root: Path, *paths: Path) -> None:
    resolved_root = root.resolve()
    for path in paths:
        assert path.resolve().is_relative_to(resolved_root)


def test_representative_grade_report_state_reloads_from_opaque_workspace_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "workspace"

    grade_support._workspace(source, monkeypatch)
    grade = grade_support._write(
        source,
        monkeypatch,
        grade_support._result(),
    ).stored
    conventional_storage.select_conventional_grade_result_revision(
        source,
        grade_support.CLASS_ID,
        grade_support.STUDENT_ID,
        grade_support.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )

    (source / "classes" / snapshot_support.CLASS_ID).mkdir(
        parents=True,
        exist_ok=True,
    )
    definition = write_reporting_definition_revision(
        source,
        snapshot_support._definition(),
    ).stored
    snapshot = write_reporting_snapshot(
        source,
        snapshot_support._snapshot(
            definition.reference,
            snapshot_id="snapshot_backup_boundary",
            created_at=snapshot_support.NOW,
        ),
    ).stored
    snapshot_selection = snapshot_support._select(
        source,
        snapshot,
        None,
        10,
    ).selection

    profile = write_export_profile_revision(
        source,
        export_profile_support._profile(),
    ).stored
    profile_selection = export_profile_support._select(
        source,
        profile,
        None,
        5,
    ).selection

    built = compose_export_preview(
        snapshot_reference=snapshot.reference,
        report_preview=export_preview_support._unavailable_preview(),
        profile_reference=profile.reference,
        profile=profile.profile,
        roster_observation=None,
    )

    external_output = tmp_path / "external-reports" / "quarter-grades.csv"
    external_output.parent.mkdir()
    external_output.write_bytes(built.payload)

    receipt = export_receipt_from_preview(
        export_id="export_backup_boundary",
        preview=built.preview,
        roster_observation=built.roster_observation,
        destination=ReportExportDestinationReceipt(
            "file",
            external_output.name,
        ),
        actor=ReportExportActor("teacher", "teacher_local"),
        rationale="Representative external report export.",
        exported_at=receipt_support.NOW,
    )
    stored_receipt = write_export_receipt(source, receipt).stored

    _assert_contained(
        source,
        grade.path,
        definition.path,
        snapshot.path,
        snapshot_selection.path,
        profile.path,
        profile_selection.path,
        stored_receipt.path,
    )
    assert not external_output.resolve().is_relative_to(source.resolve())
    assert external_output.name.encode("utf-8") in stored_receipt.content
    assert str(external_output).encode("utf-8") not in stored_receipt.content

    expected_workspace_bytes = _workspace_bytes(source)
    restored = tmp_path / "restored-workspace"
    shutil.copytree(source, restored)
    assert _workspace_bytes(restored) == expected_workspace_bytes

    shutil.rmtree(source)
    external_output.unlink()
    assert not source.exists()
    assert not external_output.exists()

    restored_grade = conventional_storage.load_current_conventional_grade_result(
        restored,
        grade_support.CLASS_ID,
        grade_support.STUDENT_ID,
        grade_support.PERIOD,
        1,
    )
    assert restored_grade is not None
    assert restored_grade.reference == grade.reference
    assert restored_grade.content == grade.content

    restored_definition = load_reporting_definition_revision(
        restored,
        snapshot_support.CLASS_ID,
        definition.reference.definition_id,
        definition.reference.definition_revision,
    )
    assert restored_definition.reference == definition.reference
    assert restored_definition.content == definition.content

    restored_snapshot = load_current_reporting_snapshot(
        restored,
        snapshot_support.CLASS_ID,
        definition.reference.definition_id,
        snapshot_support.PERIOD,
        1,
    )
    assert restored_snapshot is not None
    assert restored_snapshot.reference == snapshot.reference
    assert restored_snapshot.content == snapshot.content

    restored_profile = load_current_export_profile(
        restored,
        export_profile_support.CLASS_ID,
        profile.reference.profile_id,
    )
    assert restored_profile is not None
    assert restored_profile.reference == profile.reference
    assert restored_profile.content == profile.content

    restored_receipt = load_export_receipt(
        restored,
        receipt.class_id,
        receipt.export_id,
    )
    assert restored_receipt.reference == stored_receipt.reference
    assert restored_receipt.content == stored_receipt.content
    assert restored_receipt.receipt.destination.basename == external_output.name


def test_meridian_introduces_no_suite_specific_backup_or_restore_protocol() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("meridian").glob("*.py"))
    )

    assert "paper-data-suite" not in pyproject
    assert not Path("meridian/backup.py").exists()
    assert not Path("meridian/restore.py").exists()

    for forbidden in (
        "paper_data_suite.workspace_backup",
        "MeridianBackupProvider",
        "MeridianBackupManifest",
        "meridian_backup_exclusions",
        "meridian_restore_hook",
    ):
        assert forbidden not in runtime
