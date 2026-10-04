from pathlib import Path


def test_issue58_installed_smoke_is_core_only_and_real_state_backed() -> None:
    wrapper = Path(
        "scripts/smoke_test_grade_report_attention_wheel.py"
    ).read_text(encoding="utf-8")
    program = Path(
        "scripts/smoke_program_grade_report_attention.py"
    ).read_text(encoding="utf-8")

    for token in (
        "run_prepared_smoke",
        '"--no-index"',
        '"--no-deps"',
        '"pip", "check"',
        'metadata.version("pds-core") == "0.6.4"',
        "ReportingSnapshotPredecessor",
        "select_reporting_snapshot",
        "replaces_for_current_use",
        "meridian_reporting_snapshot_selection_pending",
        "SIBLING_DISTRIBUTIONS",
        "meridian_attention_partial",
        "Issue #58 installed Grade/report attention acceptance passed.",
    ):
        assert token in wrapper or token in program

    assert "scoreform_wheel" not in wrapper
    assert "quillan_wheel" not in wrapper
    assert "concord_wheel" not in wrapper


def test_issue58_runner_uses_core_matrix_without_new_environment() -> None:
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert "run_grade_report_attention_prepared_smoke" in runner
    assert '"grade-report-attention"' in runner
    core_start = runner.index("DependencyMatrixId.CORE")
    scoreform_start = runner.index("DependencyMatrixId.SCOREFORM", core_start)
    assert '"grade-report-attention"' in runner[core_start:scoreform_start]
