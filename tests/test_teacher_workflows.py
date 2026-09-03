from __future__ import annotations

import pytest

from meridian.teacher_workflows import (
    TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION,
    TEACHER_WORKFLOW_TASK_IDS,
    TeacherWorkflowCatalog,
    TeacherWorkflowDescriptor,
    teacher_workflow_catalog,
    teacher_workflow_catalog_to_dict,
)


def test_teacher_workflow_catalog_has_exact_issue_41_task_order() -> None:
    catalog = teacher_workflow_catalog()

    assert catalog.schema_version == TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION == 1
    assert tuple(task.task_id for task in catalog.tasks) == TEACHER_WORKFLOW_TASK_IDS
    assert TEACHER_WORKFLOW_TASK_IDS == (
        "new-evidence",
        "grade-items",
        "attempt-decisions",
        "exclusions",
        "standards-review",
        "calculation-preview",
        "create-planning-signal",
    )


def test_teacher_workflow_catalog_is_deterministic_and_json_ready() -> None:
    first = teacher_workflow_catalog_to_dict(teacher_workflow_catalog())
    second = teacher_workflow_catalog_to_dict(teacher_workflow_catalog())

    assert first == second
    tasks = first["tasks"]
    assert isinstance(tasks, list)
    assert [task["task_id"] for task in tasks] == list(TEACHER_WORKFLOW_TASK_IDS)
    assert all(task["write_boundary"] for task in tasks)


def test_teacher_workflow_descriptor_rejects_unknown_task() -> None:
    with pytest.raises(ValueError, match="Unsupported teacher workflow task"):
        TeacherWorkflowDescriptor(  # type: ignore[arg-type]
            task_id="latest-wins",
            title="Bad Task",
            summary="This task must not exist.",
            write_boundary="No write.",
        )


def test_teacher_workflow_catalog_rejects_reordered_or_missing_tasks() -> None:
    canonical = teacher_workflow_catalog()

    with pytest.raises(ValueError, match="exactly match"):
        TeacherWorkflowCatalog(
            schema_version=1,
            tasks=canonical.tasks[:-1],
        )


def test_catalog_language_preserves_important_confirmation_boundaries() -> None:
    by_id = {task.task_id: task for task in teacher_workflow_catalog().tasks}

    assert "separate" in by_id["grade-items"].write_boundary
    assert "never silently selected" in by_id["standards-review"].write_boundary
    assert "Preview is read-only" in by_id["calculation-preview"].write_boundary
    assert "without invoking Concord" in by_id["create-planning-signal"].summary
