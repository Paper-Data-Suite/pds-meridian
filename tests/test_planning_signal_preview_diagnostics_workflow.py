from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.planning_signal_preview_diagnostics_workflow as workflow
from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherProjectionReadError,
)

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"
PREVIEW_ID = "gsp_" + "a" * 64
PREVIEW_SHA256 = "b" * 64


def _projection(*, policy_id: str = POLICY_ID) -> object:
    return SimpleNamespace(
        preview_reference=workflow.GroupingSignalPreviewReference(
            class_id=CLASS_ID,
            preview_id=PREVIEW_ID,
            preview_sha256=PREVIEW_SHA256,
        ),
        class_id=CLASS_ID,
        policy_reference=SimpleNamespace(
            class_id=CLASS_ID,
            policy_id=policy_id,
        ),
    )


def test_projects_exact_preview_through_canonical_teacher_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _projection()
    observed: list[tuple[object, object]] = []

    def build(workspace_root: object, reference: object) -> object:
        observed.append((workspace_root, reference))
        return expected

    monkeypatch.setattr(
        workflow,
        "build_grouping_signal_teacher_projection",
        build,
    )

    result = workflow.project_planning_signal_preview_diagnostics(
        "synthetic-workspace",
        CLASS_ID,
        POLICY_ID,
        PREVIEW_ID,
        PREVIEW_SHA256,
    )

    assert result is expected
    assert len(observed) == 1
    workspace_root, reference = observed[0]
    assert workspace_root == "synthetic-workspace"
    assert reference == expected.preview_reference


def test_rejects_preview_from_different_policy_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "build_grouping_signal_teacher_projection",
        lambda *args, **kwargs: _projection(policy_id="other_policy"),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewDiagnosticsScopeError,
        match="different #37 policy family",
    ):
        workflow.project_planning_signal_preview_diagnostics(
            "synthetic-workspace",
            CLASS_ID,
            POLICY_ID,
            PREVIEW_ID,
            PREVIEW_SHA256,
        )


def test_translates_canonical_projection_read_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise GroupingSignalTeacherProjectionReadError(
            "Could not load the exact grouping-signal preview."
        )

    monkeypatch.setattr(
        workflow,
        "build_grouping_signal_teacher_projection",
        fail,
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewDiagnosticsDependencyError,
        match="Could not load the exact grouping-signal preview",
    ):
        workflow.project_planning_signal_preview_diagnostics(
            "synthetic-workspace",
            CLASS_ID,
            POLICY_ID,
            PREVIEW_ID,
            PREVIEW_SHA256,
        )


def test_invalid_exact_preview_reference_fails_before_workspace_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "build_grouping_signal_teacher_projection",
        lambda *args, **kwargs: pytest.fail("invalid reference must fail first"),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewDiagnosticsScopeError,
        match="invalid preview_id",
    ):
        workflow.project_planning_signal_preview_diagnostics(
            "synthetic-workspace",
            CLASS_ID,
            POLICY_ID,
            "not-a-preview",
            PREVIEW_SHA256,
        )
