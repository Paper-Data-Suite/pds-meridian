from __future__ import annotations

import pytest

from meridian.cli import build_parser, main
from meridian.teacher_workflows import (
    TEACHER_WORKFLOW_TASK_IDS,
    teacher_workflow_catalog,
)


def test_main_help_describes_task_workflows_not_library_only() -> None:
    help_text = build_parser().format_help()
    assert "task-oriented teacher workflows" in help_text
    assert "planning-signal export through Core" in help_text
    assert "implemented as library APIs" not in help_text


@pytest.mark.parametrize("task_id", TEACHER_WORKFLOW_TASK_IDS)
def test_all_seven_workflow_commands_are_independently_invocable_help(
    task_id: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(("workflow", task_id, "--help"))
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert f"usage: meridian workflow {task_id}" in output


def test_create_planning_signal_catalog_closes_core_csv_concord_boundary() -> None:
    task = teacher_workflow_catalog().tasks[-1]
    assert task.task_id == "create-planning-signal"
    assert "Core/receipt export" in task.summary
    assert "optional Core-native CSV" in task.summary
    assert "without invoking Concord" in task.summary
    assert "review selection" in task.write_boundary
    assert "optional CSV" in task.write_boundary
    assert "no Concord state is created" in task.write_boundary
