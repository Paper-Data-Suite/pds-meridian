"""Exercise issue #56 report exports from one installed Meridian wheel."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_reporting_snapshot as issue55  # type: ignore[import-not-found]
from pds_core.classes import load_class_roster

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileRevision,
    ExportRepresentation,
)
from meridian.export_profile_storage import write_export_profile_revision
from meridian.report_export_commit import (
    commit_report_export,
    copyable_text_destination,
    file_export_destination,
)
from meridian.report_export_preview import build_export_preview
from meridian.report_export_receipt import (
    ReportExportActor,
    load_export_receipt,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_storage import load_reporting_snapshot

BASELINE_NAME = "issue56-report-export-baseline.json"
SNAPSHOT_PROFILE_ID = "issue56_snapshot_only"
ROSTER_PROFILE_ID = "issue56_roster_backed"
COPY_EXPORT_ID = "issue56_copy_export"
FILE_EXPORT_ID = "issue56_file_export"
ACTOR_ID = "teacher_local"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return cast(dict[str, Any], value)


def _text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(message)
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile(
    *,
    class_id: str,
    profile_id: str,
    columns: tuple[ExportColumn, ...],
    title: str,
) -> ExportProfileRevision:
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=class_id,
        profile_id=profile_id,
        profile_revision=1,
        supersedes_revision=None,
        title=title,
        purpose="Installed Issue #56 report-export acceptance.",
        columns=columns,
        representation=ExportRepresentation(
            format="csv",
            include_header=True,
            line_ending="lf",
            utf8_bom=False,
        ),
        actor=ExportProfileActor("teacher", ACTOR_ID),
        rationale="Candidate-wheel qualification.",
        revised_at=datetime(2026, 9, 22, 8, 0, tzinfo=UTC),
    )


def _verify_installed_composition() -> None:
    issue55._verify_installed_composition()
    for module_name in (
        "meridian.export_profile",
        "meridian.export_profile_storage",
        "meridian.report_export_roster",
        "meridian.report_export_preview",
        "meridian.report_export_receipt",
        "meridian.report_export_commit",
        "meridian.report_export_cli",
    ):
        issue54._installed_origin(module_name)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_report_exports.py <root>")

    _verify_installed_composition()
    root = Path(sys.argv[1]).resolve()
    issue55_baseline = _mapping(
        json.loads(
            (root / issue55.BASELINE_NAME).read_text(encoding="utf-8")
        ),
        "Issue #55 baseline must be an object.",
    )
    workspace = root / _text(
        issue55_baseline.get("workspace"),
        "Issue #55 workspace missing.",
    )
    class_id = _text(
        issue55_baseline.get("class_id"),
        "Issue #55 class_id missing.",
    )
    snapshot_reference = ReportingSnapshotReference(
        class_id=class_id,
        snapshot_id=_text(
            issue55_baseline.get("snapshot_id"),
            "Issue #55 snapshot_id missing.",
        ),
        snapshot_sha256=_text(
            issue55_baseline.get("snapshot_sha256"),
            "Issue #55 snapshot_sha256 missing.",
        ),
    )

    stored_snapshot = load_reporting_snapshot(
        workspace,
        class_id,
        snapshot_reference.snapshot_id,
    )
    _require(
        stored_snapshot.reference == snapshot_reference,
        "Installed #56 source ReportingSnapshot reference changed.",
    )
    snapshot_source_sha256 = hashlib.sha256(
        stored_snapshot.content
    ).hexdigest()

    roster = load_class_roster(workspace, class_id)
    _require(
        roster.source_path is not None,
        "Installed acceptance requires a file-backed Core roster.",
    )
    assert roster.source_path is not None
    roster_source_path = Path(roster.source_path)
    roster_source_sha256 = _sha256_file(roster_source_path)

    snapshot_profile = _profile(
        class_id=class_id,
        profile_id=SNAPSHOT_PROFILE_ID,
        title="Installed snapshot-only export",
        columns=(
            ExportColumn("target.student_id", "student_id"),
            ExportColumn(
                "target.calculation_family",
                "calculation_family",
            ),
            ExportColumn("grade.effective_grade", "effective_grade"),
        ),
    )
    stored_snapshot_profile = write_export_profile_revision(
        workspace,
        snapshot_profile,
    ).stored
    snapshot_preview = build_export_preview(
        workspace,
        snapshot_reference,
        stored_snapshot_profile.reference,
    )
    _require(
        snapshot_preview.roster_observation is None,
        "Snapshot-only installed export unexpectedly observed the roster.",
    )
    copied = commit_report_export(
        workspace,
        export_id=COPY_EXPORT_ID,
        approved_preview=snapshot_preview.preview,
        destination=copyable_text_destination(),
        actor=ReportExportActor("teacher", ACTOR_ID),
        rationale="Copy exact installed snapshot-only export.",
        exported_at=datetime(2026, 9, 22, 8, 5, tzinfo=UTC),
    )
    _require(
        copied.copyable_text == snapshot_preview.payload.decode("utf-8"),
        "Installed copyable export did not preserve exact UTF-8 payload text.",
    )
    _require(
        copied.receipt.receipt.destination.kind == "copyable_text",
        "Installed copyable export receipt has the wrong destination kind.",
    )

    roster_profile = _profile(
        class_id=class_id,
        profile_id=ROSTER_PROFILE_ID,
        title="Installed roster-backed export",
        columns=(
            ExportColumn("target.student_id", "student_id"),
            ExportColumn(
                "target.calculation_family",
                "calculation_family",
            ),
            ExportColumn("roster.display_name", "student_name"),
            ExportColumn("roster.period", "roster_period"),
            ExportColumn("grade.effective_grade", "effective_grade"),
        ),
    )
    stored_roster_profile = write_export_profile_revision(
        workspace,
        roster_profile,
    ).stored
    roster_preview = build_export_preview(
        workspace,
        snapshot_reference,
        stored_roster_profile.reference,
    )
    _require(
        roster_preview.roster_observation is not None,
        "Roster-backed installed export did not bind a roster observation.",
    )
    assert roster_preview.roster_observation is not None
    roster_observation_reference = (
        roster_preview.preview.roster_observation_reference
    )
    _require(
        roster_observation_reference is not None,
        "Roster-backed installed preview lost its roster observation reference.",
    )
    assert roster_observation_reference is not None
    _require(
        roster_preview.roster_observation.source_fields
        == ("roster.display_name", "roster.period"),
        "Installed roster observation contains unexpected source fields.",
    )
    destination = root / "issue56-installed-export.csv"
    written = commit_report_export(
        workspace,
        export_id=FILE_EXPORT_ID,
        approved_preview=roster_preview.preview,
        destination=file_export_destination(destination),
        actor=ReportExportActor("teacher", ACTOR_ID),
        rationale="Write exact installed roster-backed export.",
        exported_at=datetime(2026, 9, 22, 8, 10, tzinfo=UTC),
    )
    _require(
        destination.read_bytes() == roster_preview.payload,
        "Installed file export bytes differ from the approved preview payload.",
    )
    _require(
        written.receipt.receipt.destination.kind == "file"
        and written.receipt.receipt.destination.basename == destination.name,
        "Installed file receipt did not retain only the safe basename.",
    )
    _require(
        str(destination).encode("utf-8") not in written.receipt.content,
        "Installed export receipt retained an absolute destination path.",
    )

    copy_receipt = load_export_receipt(workspace, class_id, COPY_EXPORT_ID)
    file_receipt = load_export_receipt(workspace, class_id, FILE_EXPORT_ID)
    _require(
        copy_receipt.reference == copied.receipt.reference,
        "Installed copyable receipt changed after immediate reload.",
    )
    _require(
        file_receipt.reference == written.receipt.reference,
        "Installed file receipt changed after immediate reload.",
    )

    reloaded_snapshot = load_reporting_snapshot(
        workspace,
        class_id,
        snapshot_reference.snapshot_id,
    )
    _require(
        hashlib.sha256(reloaded_snapshot.content).hexdigest()
        == snapshot_source_sha256,
        "Installed export mutated source ReportingSnapshot bytes.",
    )
    _require(
        _sha256_file(roster_source_path) == roster_source_sha256,
        "Installed export mutated Core roster source bytes.",
    )

    baseline = {
        "schema_version": "1",
        "workspace": workspace.name,
        "class_id": class_id,
        "snapshot_id": snapshot_reference.snapshot_id,
        "snapshot_sha256": snapshot_reference.snapshot_sha256,
        "snapshot_source_sha256": snapshot_source_sha256,
        "roster_source_sha256": roster_source_sha256,
        "snapshot_profile": {
            "profile_id": stored_snapshot_profile.reference.profile_id,
            "profile_revision": (
                stored_snapshot_profile.reference.profile_revision
            ),
            "profile_sha256": (
                stored_snapshot_profile.reference.profile_sha256
            ),
            "preview_sha256": snapshot_preview.preview.preview_sha256,
            "payload_sha256": snapshot_preview.preview.payload_sha256,
        },
        "roster_profile": {
            "profile_id": stored_roster_profile.reference.profile_id,
            "profile_revision": stored_roster_profile.reference.profile_revision,
            "profile_sha256": stored_roster_profile.reference.profile_sha256,
            "preview_sha256": roster_preview.preview.preview_sha256,
            "payload_sha256": roster_preview.preview.payload_sha256,
            "roster_observation_sha256": (
                roster_observation_reference.observation_sha256
            ),
        },
        "copy_export_id": COPY_EXPORT_ID,
        "copy_receipt_sha256": copy_receipt.receipt_sha256,
        "file_export_id": FILE_EXPORT_ID,
        "file_receipt_sha256": file_receipt.receipt_sha256,
        "file_name": destination.name,
        "file_sha256": _sha256_file(destination),
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print("Issue #56 installed report-export acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
