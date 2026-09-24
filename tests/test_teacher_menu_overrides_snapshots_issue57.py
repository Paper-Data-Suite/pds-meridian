from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_overrides import (
    OverrideAuthoringPlan,
    OverrideMenuDependencies,
    OverrideReviewPresentation,
    OverrideScope,
    OverrideSelectionPlan,
    run_overrides_menu,
)
from meridian.menu_snapshots import (
    SnapshotListItem,
    SnapshotMenuDependencies,
    SnapshotPresentation,
    SnapshotSelectionPlan,
    SnapshotSelectionPresentation,
    run_snapshots_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _scope() -> OverrideScope:
    return OverrideScope(
        class_id="class_1",
        student_id="student_1",
        period=AcademicPeriodRef("2026-2027", "mp1"),
        calendar_revision=4,
        family="standards_based",
    )


def _review() -> OverrideReviewPresentation:
    return OverrideReviewPresentation(
        scope=_scope(),
        selected=True,
        decision="override",
        override_revision=2,
        override_sha256="a" * 64,
        replacement_grade="91",
        actor_id="teacher_1",
        rationale="Reviewed portfolio evidence",
        source_result_revision=5,
        source_result_sha256="b" * 64,
    )


def _authoring_plan() -> OverrideAuthoringPlan:
    return OverrideAuthoringPlan(
        scope=_scope(),
        replacement_grade="91",
        source_status="calculated",
        source_grade="87.5",
        source_freshness="current",
        candidate_revision=3,
        candidate_sha256="c" * 64,
        actor_id="teacher_1",
        rationale="Reviewed portfolio evidence",
        preview=object(),  # type: ignore[arg-type]
    )


def _selection_plan() -> OverrideSelectionPlan:
    return OverrideSelectionPlan(
        scope=_scope(),
        target_revision=3,
        target_sha256="c" * 64,
        target_decision="override",
        replacement_grade="91",
        current_revision=2,
        current_sha256="a" * 64,
        preview=object(),  # type: ignore[arg-type]
    )


def _override_deps(
    *,
    commits: list[str] | None = None,
) -> OverrideMenuDependencies:
    log = commits if commits is not None else []
    return OverrideMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        review_loader=lambda *_args: _review(),
        authoring_previewer=lambda *_args: _authoring_plan(),
        authoring_committer=lambda *_args: log.append("write") or "created",
        selection_previewer=lambda *_args: _selection_plan(),
        selection_committer=lambda *_args: log.append("select") or "updated",
    )


def test_override_review_hides_digests_until_technical_view() -> None:
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(),
        input_fn=ScriptedInput(
            "1",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Replacement Grade: 91" in rendered
    assert "override_sha256" not in rendered
    assert "source_result_sha256" not in rendered


def test_override_authoring_requires_exact_write_confirmation() -> None:
    commits: list[str] = []
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(commits=commits),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "91",
            "teacher_1",
            "Reviewed portfolio evidence",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert commits == []
    assert "No override revision was written." in output.getvalue()


def test_override_authoring_commits_exact_preview_but_does_not_select() -> None:
    commits: list[str] = []
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(commits=commits),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "91",
            "teacher_1",
            "Reviewed portfolio evidence",
            "WRITE",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert commits == ["write"]
    assert "It is not current until explicitly selected." in output.getvalue()


def test_override_selection_requires_exact_select_confirmation() -> None:
    commits: list[str] = []
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(commits=commits),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert commits == ["select"]
    assert "Target sha256:" in output.getvalue()


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_overrides_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_overrides_menu(
            dependencies=_override_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )


def _snapshot_item() -> SnapshotListItem:
    return SnapshotListItem(
        snapshot_id="snapshot_1",
        definition_id="report_1",
        definition_revision=2,
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        row_count=24,
        created_at="2026-09-23T20:00:00+00:00",
        snapshot_sha256="d" * 64,
    )


def _snapshot_plan() -> SnapshotSelectionPlan:
    return SnapshotSelectionPlan(
        class_id="class_1",
        snapshot_id="snapshot_1",
        snapshot_sha256="d" * 64,
        definition_id="report_1",
        school_year="2026-2027",
        period_id="mp1",
        calendar_revision=4,
        row_count=24,
        actor_id="teacher_1",
        rationale="Quarterly report",
        decided_at=datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        current_snapshot_id="snapshot_0",
        current_selection_revision=2,
        target_reference=object(),  # type: ignore[arg-type]
        expected_current=object(),  # type: ignore[arg-type]
    )


def _snapshot_deps(
    *,
    commits: list[str] | None = None,
) -> SnapshotMenuDependencies:
    log = commits if commits is not None else []
    return SnapshotMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        lister=lambda *_args: (_snapshot_item(),),
        inspector=lambda *_args: SnapshotPresentation(
            item=_snapshot_item(),
            current_for_scope=False,
        ),
        selection_loader=lambda *_args: SnapshotSelectionPresentation(
            class_id="class_1",
            definition_id="report_1",
            school_year="2026-2027",
            period_id="mp1",
            calendar_revision=4,
            snapshot_id="snapshot_0",
            snapshot_sha256="e" * 64,
            selection_revision=2,
            selection_sha256="f" * 64,
        ),
        selection_previewer=lambda *_args: _snapshot_plan(),
        selection_committer=lambda *_args: log.append("select") or "updated",
    )


def test_snapshot_list_states_listing_is_not_current_authority() -> None:
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(),
        input_fn=ScriptedInput("1", "class_1", "", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "snapshot_1" in rendered
    assert "Listing order is not current-use authority." in rendered
    assert "dddddddd" not in rendered


def test_snapshot_inspect_technical_view_exposes_digest_explicitly() -> None:
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(),
        input_fn=ScriptedInput(
            "2",
            "class_1",
            "snapshot_1",
            "t",
            "",
            "b",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Current for this reporting scope: no" in rendered
    assert f"snapshot_sha256: {'d' * 64}" in rendered


def test_snapshot_selection_cancel_does_not_commit() -> None:
    commits: list[str] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(commits=commits),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "snapshot_1",
            "teacher_1",
            "Quarterly report",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert commits == []
    assert "selection was not changed" in output.getvalue()


def test_snapshot_selection_requires_exact_select_and_keeps_local_authority() -> None:
    commits: list[str] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(commits=commits),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "snapshot_1",
            "teacher_1",
            "Quarterly report",
            "SELECT",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert commits == ["select"]
    rendered = output.getvalue()
    assert f"Snapshot sha256: {'d' * 64}" in rendered
    assert "No official SIS/district Grade was changed." in rendered


@pytest.mark.parametrize(
    ("choice", "error"),
    [("m", ReturnToMainMenu), ("q", QuitPDS)],
)
def test_snapshots_menu_preserves_shared_navigation(
    choice: str,
    error: type[BaseException],
) -> None:
    with pytest.raises(error):
        run_snapshots_menu(
            dependencies=_snapshot_deps(),
            input_fn=ScriptedInput(choice),
            output=StringIO(),
            clear_fn=lambda: None,
        )
