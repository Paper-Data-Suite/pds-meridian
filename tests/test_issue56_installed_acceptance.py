from __future__ import annotations

from pathlib import Path


def test_issue56_installed_wrapper_isolated_and_exact() -> None:
    wrapper = Path("scripts/smoke_test_report_exports_wheel.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        '"pip", "check"',
        "scoreform_wheel",
        "quillan_wheel",
        "concord_wheel",
        "SNAPSHOT_PROGRAM",
        "PROGRAM",
        "RELOAD_PROGRAM",
        '"reporting", "exports", "--help"',
    ):
        assert token in wrapper


def test_issue56_installed_program_covers_export_boundaries() -> None:
    program = Path("scripts/smoke_program_report_exports.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "issue55._verify_installed_composition()",
        "write_export_profile_revision",
        "build_export_preview",
        "copyable_text_destination",
        "file_export_destination",
        "commit_report_export",
        "load_export_receipt",
        "load_class_roster",
        "Snapshot-only installed export unexpectedly observed the roster.",
        "Installed export mutated source ReportingSnapshot bytes.",
        "Installed export mutated Core roster source bytes.",
        "Issue #56 installed report-export acceptance passed.",
    ):
        assert token in program


def test_issue56_installed_reload_is_fresh_process_and_read_only() -> None:
    program = Path("scripts/smoke_program_report_exports_reload.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "build_export_preview",
        "load_export_receipt",
        "load_reporting_snapshot",
        "load_class_roster",
        "Fresh-process bounded roster observation digest changed.",
        "Fresh-process Issue #56 preview/receipt reload wrote workspace state.",
        "Issue #56 fresh-process report-export acceptance passed.",
    ):
        assert token in program
    assert "commit_report_export" not in program
    assert "write_export_profile_revision" not in program
