"""#123 11K guardrails for the installed cross-task acceptance program."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import smoke_test_issue123_joined_journey_wheel as harness


def test_runs_standalone_script_in_isolated_python_and_outside_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    harness.run_prepared_smoke(Path("/installed/python"), outside, tmp_path / "new")
    assert len(calls) == 1
    command, cwd, env = calls[0]
    assert Path(command[0]) == Path("/installed/python")
    assert command[1].endswith("smoke_program_issue123_joined_journey.py")
    assert cwd == outside
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env


def test_failure_and_missing_marker_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    for returncode, text in ((1, "error"), (0, "nothing"), (0, "Traceback")):
        monkeypatch.setattr(
            harness.subprocess,
            "run",
            lambda command, **kwargs: subprocess.CompletedProcess(
                command, returncode, text, ""
            ),
        )
        with pytest.raises(RuntimeError):
            harness.run_prepared_smoke(
                Path("python"), outside, tmp_path / "synthetic-root"
            )
    (tmp_path / "synthetic-root").mkdir()
    with pytest.raises(RuntimeError, match="new synthetic root"):
        harness.run_prepared_smoke(Path("python"), outside, tmp_path / "synthetic-root")


def test_joined_program_uses_real_read_only_controllers_and_no_fake_grade() -> None:
    source = harness.PROGRAM.read_text(encoding="utf-8")
    for marker in (
        "run_named_grade_item_review",
        "run_named_grade_item_proficiency",
        "run_named_current_grade_review",
        "run_named_grade_item_proficiency_explanation",
        "run_named_planning_readiness",
        "default_explain_menu_dependencies",
        "project_planning_signal_readiness",
        "base._tree(root) == selected_before",
        "nav.choose_class(base.OTHER)",
        "Current Grade Review",
        "cannot be verified or is not configured",
        "Read-only: no derivation, review, or Core export was performed",
    ):
        assert marker in source
    assert "main()" in source
