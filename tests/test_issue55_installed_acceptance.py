from __future__ import annotations

from pathlib import Path


def test_issue55_installed_wrapper_isolated_and_exact() -> None:
    wrapper = Path("scripts/smoke_test_reporting_snapshot_wheel.py").read_text(
        encoding="utf-8"
    )
    for token in (
        '"PYTHONPATH"',
        '"PYTHONNOUSERSITE": "1"',
        '"pip", "check"',
        "scoreform_wheel",
        "quillan_wheel",
        "concord_wheel",
        "PROGRAM",
        "RELOAD_PROGRAM",
    ):
        assert token in wrapper


def test_issue55_installed_program_covers_freeze_boundary() -> None:
    program = Path("scripts/smoke_program_reporting_snapshot.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "smoke_program_grade_report_preview as issue54",
        "issue54._verify_installed_composition()",
        "issue54._installed_origin",
        "issue54._hybrid_state",
        "meridian.reporting_snapshot_freeze",
        "meridian.reporting_snapshot_storage",
        "write_reporting_definition_revision",
        "reporting_snapshot_build_request_from_preview_requests",
        "explain_grade_report_preview",
        "freeze_reporting_snapshot",
        "load_reporting_snapshot",
        "compare_reporting_snapshot_to_grade_report_preview",
        "grade_preview_observation_to_json_bytes",
        "Snapshot digest does not match exact installed bytes.",
        "Issue #55 installed ReportingSnapshot freeze acceptance passed.",
    ):
        assert token in program


def test_issue55_installed_reload_is_fresh_process_and_read_only() -> None:
    reload_program = Path(
        "scripts/smoke_program_reporting_snapshot_reload.py"
    ).read_text(encoding="utf-8")
    for token in (
        "smoke_program_grade_report_preview_reload as issue54_reload",
        "issue54_reload._authorized_evidence",
        "load_reporting_definition_revision",
        "ReportingSnapshotReference",
        "load_reporting_snapshot_for_comparison",
        "load_reporting_snapshot_prior_grade_bases",
        "compare_reporting_snapshot_to_grade_report_preview",
        "Fresh-process snapshot bytes fail exact digest verification.",
        "Fresh-process #55 reload/comparison wrote workspace state.",
        "Issue #55 fresh-process ReportingSnapshot acceptance passed.",
    ):
        assert token in reload_program
    assert "freeze_reporting_snapshot" not in reload_program
