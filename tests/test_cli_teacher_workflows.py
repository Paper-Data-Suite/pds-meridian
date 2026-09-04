from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.teacher_workflows import TEACHER_WORKFLOW_TASK_IDS


def test_workflow_group_without_subcommand_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("workflow",)) == 0
    output = capsys.readouterr().out

    assert "usage: meridian workflow" in output
    assert "list" in output
    assert "task-oriented teacher workflow" in output


def test_workflow_list_text_is_deterministic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("workflow", "list")) == 0
    first = capsys.readouterr().out
    assert main(("workflow", "list")) == 0
    second = capsys.readouterr().out

    assert first == second
    assert "Issue #41 teacher workflows" in first
    for index, task_id in enumerate(TEACHER_WORKFLOW_TASK_IDS, start=1):
        assert f"{index}. {task_id} |" in first
    assert "catalog only; this command performs no workflow write" in first


def test_workflow_list_json_has_exact_task_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("workflow", "list", "--format", "json")) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == 1
    assert [task["task_id"] for task in payload["tasks"]] == list(
        TEACHER_WORKFLOW_TASK_IDS
    )


def test_workflow_list_does_not_touch_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    before = tuple(tmp_path.iterdir())

    assert main(("workflow", "list")) == 0
    capsys.readouterr()

    assert tuple(tmp_path.iterdir()) == before
