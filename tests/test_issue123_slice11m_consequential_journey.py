"""#123 11M installed consequential journey harness and scope guardrails."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import smoke_test_issue123_consequential_journey_wheel as harness


def test_isolated_program_uses_external_directory_and_cleans_python_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs["cwd"], kwargs["env"]))  # type: ignore[arg-type]
        return subprocess.CompletedProcess(command, 0, harness.SUCCESS + "\n", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    outside = tmp_path / "outside"
    outside.mkdir()
    harness.run_prepared_smoke(Path("python"), outside, tmp_path / "new-root")
    assert len(calls) == 1
    command, cwd, env = calls[0]
    assert Path(command[0]) == Path("python")
    assert command[1].endswith("smoke_program_issue123_consequential_journey.py")
    assert cwd == outside
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env


def test_failed_process_missing_marker_and_traceback_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    for returncode, output in ((1, "error"), (0, "missing"), (0, "Traceback")):
        monkeypatch.setattr(
            harness.subprocess,
            "run",
            lambda cmd, **kwargs: subprocess.CompletedProcess(
                cmd, returncode, output, ""
            ),
        )
        with pytest.raises(RuntimeError):
            harness.run_prepared_smoke(Path("python"), outside, tmp_path / "absent")
    (tmp_path / "existing").mkdir()
    with pytest.raises(RuntimeError, match="new synthetic root"):
        harness.run_prepared_smoke(Path("python"), outside, tmp_path / "existing")


def test_installed_program_joins_real_domain_services_and_named_delivery() -> None:
    source = harness.PROGRAM.read_text(encoding="utf-8")
    for marker in (
        "run_fixture(issue55.main, root)",
        "run_fixture(issue56.main, root)",
        "run_named_current_grade_review",
        "run_named_snapshot_browse",
        "run_named_export_receipt_browse",
        "run_named_report_export_delivery",
        "Base Grade: 96.00",
        "Effective Grade: 96.00",
        "EXPORT",
        "Exact local ExportReceipt verified.",
        "ReportExportCurrentnessConflictError",
        "synthetic-private-evidence-token",
        "assert tree(workspace) == before_named_write",
        "assert not conflict_destination.exists()",
    ):
        assert marker in source
    assert "not a published release" not in harness.SUCCESS
