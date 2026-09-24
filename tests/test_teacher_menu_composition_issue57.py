from __future__ import annotations

from io import StringIO
from typing import cast

import meridian.menu as menu_module
from meridian.diagnostics import DiagnosticsDependencies
from meridian.menu import (
    TEACHER_MENU_TASKS,
    default_teacher_menu_dependencies,
)


def test_default_composition_routes_all_eight_real_controllers(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object, object, object]] = []

    def input_fn(prompt: str) -> str:
        _ = prompt
        return "b"

    output = StringIO()

    def clear_fn() -> None:
        return None
    diagnostics = cast(DiagnosticsDependencies, object())
    evidence_deps = object()
    freeze_deps = object()
    factory_observations: list[tuple[str, object]] = []

    monkeypatch.setattr(
        menu_module,
        "default_evidence_menu_dependencies",
        lambda *, diagnostics=None: (
            factory_observations.append(("evidence", diagnostics))
            or evidence_deps
        ),
    )
    monkeypatch.setattr(
        menu_module,
        "default_snapshot_freeze_dependencies",
        lambda *, diagnostics=None: (
            factory_observations.append(("freeze", diagnostics))
            or freeze_deps
        ),
    )

    def fake(name: str):
        def run(**kwargs: object) -> None:
            calls.append(
                (
                    name,
                    kwargs["input_fn"],
                    kwargs["output"],
                    kwargs["clear_fn"],
                )
            )
            if name == "review-new-evidence":
                assert kwargs["dependencies"] is evidence_deps
            if name == "snapshots":
                assert kwargs["freeze_dependencies"] is freeze_deps

        return run

    routes = {
        "run_new_evidence_menu": "review-new-evidence",
        "run_grade_items_menu": "manage-grade-items",
        "run_proficiency_menu": "review-proficiency",
        "run_grade_preview_menu": "preview-grades",
        "run_overrides_menu": "overrides",
        "run_snapshots_menu": "snapshots",
        "run_export_menu": "export",
        "run_explain_menu": "explain",
    }
    for attribute, name in routes.items():
        monkeypatch.setattr(menu_module, attribute, fake(name))

    dependencies = default_teacher_menu_dependencies(
        diagnostics=diagnostics,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    for task in TEACHER_MENU_TASKS:
        dependencies.handler_for(task.task_id)()

    assert [item[0] for item in calls] == [
        task.task_id for task in TEACHER_MENU_TASKS
    ]
    assert all(item[1] is input_fn for item in calls)
    assert all(item[2] is output for item in calls)
    assert all(item[3] is clear_fn for item in calls)
    assert factory_observations == [
        ("evidence", diagnostics),
        ("freeze", diagnostics),
    ]
