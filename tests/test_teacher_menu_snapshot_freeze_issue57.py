from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import cast

from meridian.menu_snapshots import (
    ReportingDefinitionPlan,
    SnapshotFreezeDependencies,
    SnapshotFreezePlan,
    SnapshotFreezeResult,
    SnapshotListItem,
    SnapshotMenuDependencies,
    SnapshotPresentation,
    SnapshotSelectionPlan,
    SnapshotSelectionPresentation,
    run_snapshots_menu,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    ReportingSnapshotProjectionInputReference,
)
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotFreezePreview,
    ReportingSnapshotProjectionAuthorization,
    ReportingSnapshotWorkflowAuthorizationError,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _request() -> ReportingSnapshotBuildRequest:
    return cast(ReportingSnapshotBuildRequest, object())


def _plan(*, authorization_count: int = 0) -> SnapshotFreezePlan:
    return SnapshotFreezePlan(
        snapshot_id="snapshot_1",
        definition_id="report_1",
        school_year="2026-2027",
        period_id="mp1",
        row_count=24,
        build_request_sha256="a" * 64,
        live_report_sha256="b" * 64,
        authorization_count=authorization_count,
        preview=cast(ReportingSnapshotFreezePreview, object()),
    )


def _result() -> SnapshotFreezeResult:
    return SnapshotFreezeResult(
        snapshot_id="snapshot_1",
        snapshot_sha256="c" * 64,
        report_preview_sha256="b" * 64,
        row_count=24,
    )


def _freeze_deps(
    log: list[object],
    *,
    protected: bool = False,
) -> SnapshotFreezeDependencies:
    requirement = ReportingSnapshotProjectionInputReference(
        publication_id="publication_1",
        cache_key="d" * 64,
        snapshot_digest="e" * 64,
    )
    return SnapshotFreezeDependencies(
        build_request_loader=lambda path: log.append(("load", path)) or _request(),
        requirements_loader=(
            (lambda request: (requirement,))
            if protected
            else (lambda request: ())
        ),
        previewer=lambda *args: (
            log.append(("preview", args))
            or _plan(authorization_count=1 if protected else 0)
        ),
        committer=lambda *args: log.append(("commit", args)) or _result(),
    )


def _menu_deps() -> SnapshotMenuDependencies:
    item = SnapshotListItem(
        snapshot_id="snapshot_0",
        definition_id="report_1",
        definition_revision=2,
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        row_count=24,
        created_at="2026-09-23T20:00:00+00:00",
        snapshot_sha256="f" * 64,
    )
    return SnapshotMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        lister=lambda *_args: (item,),
        inspector=lambda *_args: SnapshotPresentation(
            item=item,
            current_for_scope=False,
        ),
        selection_loader=lambda *_args: SnapshotSelectionPresentation(
            class_id="class_1",
            definition_id="report_1",
            school_year="2026-2027",
            period_id="mp1",
            calendar_revision=4,
            snapshot_id=None,
            snapshot_sha256=None,
            selection_revision=None,
            selection_sha256=None,
        ),
        selection_previewer=lambda *_args: SnapshotSelectionPlan(
            class_id="class_1",
            snapshot_id="snapshot_0",
            snapshot_sha256="f" * 64,
            definition_id="report_1",
            school_year="2026-2027",
            period_id="mp1",
            calendar_revision=4,
            row_count=24,
            actor_id="teacher_1",
            rationale=None,
            decided_at=datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
            current_snapshot_id=None,
            current_selection_revision=None,
            target_reference=cast(object, object()),  # type: ignore[arg-type]
            expected_current=None,
        ),
        selection_committer=lambda *_args: "created",
        definition_previewer=lambda *_args: ReportingDefinitionPlan(
            class_id="class_1",
            definition_id="report_1",
            definition_revision=3,
            definition_sha256="9" * 64,
            title="MP1 Grade Report",
            purpose="Teacher reporting",
            school_year="2026-2027",
            period_id="mp1",
            actor_id="teacher_1",
            rationale=None,
            candidate=cast(object, object()),  # type: ignore[arg-type]
        ),
        definition_committer=lambda *_args: "created",
    )


def test_freeze_cancel_after_review_does_not_commit() -> None:
    log: list[object] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_menu_deps(),
        freeze_dependencies=_freeze_deps(log),
        input_fn=ScriptedInput(
            "6",
            "request.json",
            "snapshot_1",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert [item[0] for item in log if isinstance(item, tuple)] == [
        "load",
        "preview",
    ]
    rendered = output.getvalue()
    assert "No ReportingSnapshot was frozen." in rendered
    assert "Live report sha256:" in rendered


def test_freeze_requires_exact_freeze_confirmation() -> None:
    log: list[object] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_menu_deps(),
        freeze_dependencies=_freeze_deps(log),
        input_fn=ScriptedInput(
            "6",
            "request.json",
            "snapshot_1",
            "FREEZE",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert any(
        isinstance(item, tuple) and item[0] == "commit"
        for item in log
    )
    rendered = output.getvalue()
    assert "ReportingSnapshot frozen: snapshot_1" in rendered
    assert f"Snapshot sha256: {'c' * 64}" in rendered
    assert "No official SIS/district Grade was changed." in rendered


def test_protected_freeze_collects_explicit_authorization_inputs() -> None:
    log: list[object] = []
    run_snapshots_menu(
        dependencies=_menu_deps(),
        freeze_dependencies=_freeze_deps(log, protected=True),
        input_fn=ScriptedInput(
            "6",
            "request.json",
            "snapshot_1",
            "teacher_reporting",
            "student_2,student_1",
            "no",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    preview_calls = [
        item for item in log
        if isinstance(item, tuple) and item[0] == "preview"
    ]
    assert len(preview_calls) == 1
    args = preview_calls[0][1]
    authorizations = args[3]
    assert len(authorizations) == 1
    assert authorizations[0].purpose_id == "teacher_reporting"
    assert authorizations[0].student_ids == ("student_1", "student_2")


def test_protected_freeze_fails_closed_without_authorizer() -> None:
    output = StringIO()

    def denied(
        root: Path,
        snapshot_id: str,
        build_request: ReportingSnapshotBuildRequest,
        authorizations: tuple[
            ReportingSnapshotProjectionAuthorization,
            ...,
        ],
    ) -> SnapshotFreezePlan:
        _ = (root, snapshot_id, build_request, authorizations)
        raise ReportingSnapshotWorkflowAuthorizationError(
            "Live reporting projection access requires a deployment authorizer."
        )

    deps = SnapshotFreezeDependencies(
        build_request_loader=lambda path: _request(),
        requirements_loader=lambda request: (
            ReportingSnapshotProjectionInputReference(
                publication_id="publication_1",
                cache_key="d" * 64,
                snapshot_digest="e" * 64,
            ),
        ),
        previewer=denied,
        committer=lambda *args: _result(),
    )
    run_snapshots_menu(
        dependencies=_menu_deps(),
        freeze_dependencies=deps,
        input_fn=ScriptedInput(
            "6",
            "request.json",
            "snapshot_1",
            "teacher_reporting",
            "student_1",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "could not be prepared safely" in rendered
    assert "deployment authorizer" in rendered
    assert "ReportingSnapshot frozen:" not in rendered
