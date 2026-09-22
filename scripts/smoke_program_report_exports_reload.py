"""Fresh-process reload of installed issue #56 report exports."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_report_exports as issue56  # type: ignore[import-not-found]
from pds_core.classes import load_class_roster

from meridian.export_profile import ExportProfileReference
from meridian.report_export_preview import build_export_preview
from meridian.report_export_receipt import load_export_receipt
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_storage import load_reporting_snapshot


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


def _integer(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(message)
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_reference(
    *,
    class_id: str,
    data: dict[str, Any],
) -> ExportProfileReference:
    return ExportProfileReference(
        class_id=class_id,
        profile_id=_text(data.get("profile_id"), "profile_id missing"),
        profile_revision=_integer(
            data.get("profile_revision"),
            "profile_revision missing",
        ),
        profile_sha256=_text(
            data.get("profile_sha256"),
            "profile_sha256 missing",
        ),
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: smoke_program_report_exports_reload.py <root>"
        )

    issue56._verify_installed_composition()
    root = Path(sys.argv[1]).resolve()
    baseline = _mapping(
        json.loads((root / issue56.BASELINE_NAME).read_text(encoding="utf-8")),
        "Issue #56 baseline must be an object.",
    )
    workspace = root / _text(baseline.get("workspace"), "workspace missing")
    before = issue54._tree_digest(workspace)

    class_id = _text(baseline.get("class_id"), "class_id missing")
    snapshot_reference = ReportingSnapshotReference(
        class_id=class_id,
        snapshot_id=_text(baseline.get("snapshot_id"), "snapshot_id missing"),
        snapshot_sha256=_text(
            baseline.get("snapshot_sha256"),
            "snapshot_sha256 missing",
        ),
    )
    snapshot_profile_data = _mapping(
        baseline.get("snapshot_profile"),
        "snapshot_profile missing",
    )
    roster_profile_data = _mapping(
        baseline.get("roster_profile"),
        "roster_profile missing",
    )

    snapshot_preview = build_export_preview(
        workspace,
        snapshot_reference,
        _profile_reference(
            class_id=class_id,
            data=snapshot_profile_data,
        ),
    )
    _require(
        snapshot_preview.preview.preview_sha256
        == _text(
            snapshot_profile_data.get("preview_sha256"),
            "snapshot preview digest missing",
        ),
        "Fresh-process snapshot-only preview digest changed.",
    )
    _require(
        snapshot_preview.preview.payload_sha256
        == _text(
            snapshot_profile_data.get("payload_sha256"),
            "snapshot payload digest missing",
        ),
        "Fresh-process snapshot-only payload digest changed.",
    )
    _require(
        snapshot_preview.roster_observation is None,
        "Fresh-process snapshot-only preview unexpectedly observed roster state.",
    )

    roster_preview = build_export_preview(
        workspace,
        snapshot_reference,
        _profile_reference(
            class_id=class_id,
            data=roster_profile_data,
        ),
    )
    _require(
        roster_preview.preview.preview_sha256
        == _text(
            roster_profile_data.get("preview_sha256"),
            "roster preview digest missing",
        ),
        "Fresh-process roster-backed preview digest changed.",
    )
    _require(
        roster_preview.preview.payload_sha256
        == _text(
            roster_profile_data.get("payload_sha256"),
            "roster payload digest missing",
        ),
        "Fresh-process roster-backed payload digest changed.",
    )
    _require(
        roster_preview.preview.roster_observation_reference is not None
        and (
            roster_preview.preview.roster_observation_reference
            .observation_sha256
            == _text(
                roster_profile_data.get("roster_observation_sha256"),
                "roster observation digest missing",
            )
        ),
        "Fresh-process bounded roster observation digest changed.",
    )

    copy_receipt = load_export_receipt(
        workspace,
        class_id,
        _text(baseline.get("copy_export_id"), "copy export id missing"),
    )
    file_receipt = load_export_receipt(
        workspace,
        class_id,
        _text(baseline.get("file_export_id"), "file export id missing"),
    )
    _require(
        copy_receipt.receipt_sha256
        == _text(
            baseline.get("copy_receipt_sha256"),
            "copy receipt digest missing",
        ),
        "Fresh-process copyable receipt digest changed.",
    )
    _require(
        file_receipt.receipt_sha256
        == _text(
            baseline.get("file_receipt_sha256"),
            "file receipt digest missing",
        ),
        "Fresh-process file receipt digest changed.",
    )

    destination = root / _text(
        baseline.get("file_name"),
        "file name missing",
    )
    _require(
        _sha256_file(destination)
        == _text(baseline.get("file_sha256"), "file digest missing"),
        "Fresh-process exported file bytes changed.",
    )

    stored_snapshot = load_reporting_snapshot(
        workspace,
        class_id,
        snapshot_reference.snapshot_id,
    )
    _require(
        hashlib.sha256(stored_snapshot.content).hexdigest()
        == _text(
            baseline.get("snapshot_source_sha256"),
            "snapshot source digest missing",
        ),
        "Fresh-process export reload observed mutated ReportingSnapshot bytes.",
    )
    roster = load_class_roster(workspace, class_id)
    _require(
        roster.source_path is not None,
        "Fresh-process acceptance requires a file-backed Core roster.",
    )
    assert roster.source_path is not None
    _require(
        _sha256_file(Path(roster.source_path))
        == _text(
            baseline.get("roster_source_sha256"),
            "roster source digest missing",
        ),
        "Fresh-process export reload observed mutated Core roster bytes.",
    )

    after = issue54._tree_digest(workspace)
    _require(
        after == before,
        "Fresh-process Issue #56 preview/receipt reload wrote workspace state.",
    )
    print("Issue #56 fresh-process report-export acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
