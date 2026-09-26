from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.menu_overrides import (
    OverrideAuthoringPlan,
    OverrideMenuDependencies,
    OverrideReviewPresentation,
    OverrideScope,
    OverrideSelectionPlan,
    OverrideWithdrawalPlan,
    run_overrides_menu,
)
from meridian.menu_snapshots import (
    ReportingDefinitionPlan,
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


def _override_deps(log: list[str]) -> OverrideMenuDependencies:
    return OverrideMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        review_loader=lambda *_args: OverrideReviewPresentation(
            scope=_scope(),
            selected=True,
            decision="override",
            override_revision=2,
            override_sha256="a" * 64,
            replacement_grade="91",
            actor_id="teacher_1",
            rationale="Prior review",
            source_result_revision=5,
            source_result_sha256="b" * 64,
        ),
        authoring_previewer=lambda *_args: OverrideAuthoringPlan(
            scope=_scope(),
            replacement_grade="91",
            source_status="calculated",
            source_grade="87.5",
            source_freshness="current",
            candidate_revision=3,
            candidate_sha256="c" * 64,
            actor_id="teacher_1",
            rationale="Prior review",
            preview=object(),  # type: ignore[arg-type]
        ),
        authoring_committer=lambda *_args: "created",
        selection_previewer=lambda *_args: OverrideSelectionPlan(
            scope=_scope(),
            target_revision=3,
            target_sha256="d" * 64,
            target_decision="withdraw",
            replacement_grade=None,
            current_revision=2,
            current_sha256="a" * 64,
            preview=object(),  # type: ignore[arg-type]
        ),
        selection_committer=lambda *_args: log.append("select") or "updated",
        withdrawal_previewer=lambda *_args: OverrideWithdrawalPlan(
            scope=_scope(),
            selected_revision=2,
            selected_sha256="a" * 64,
            source_status="calculated",
            source_grade="87.5",
            candidate_revision=3,
            candidate_sha256="d" * 64,
            actor_id="teacher_1",
            rationale="Return to base Grade",
            preview=object(),  # type: ignore[arg-type]
        ),
        withdrawal_committer=lambda *_args: log.append("withdraw") or "created",
    )


def test_withdrawal_requires_write_and_separate_selection() -> None:
    log: list[str] = []
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(log),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "teacher_1",
            "Return to base Grade",
            "WITHDRAW",
            "SELECT",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["withdraw", "select"]
    rendered = output.getvalue()
    assert "prior override remains current until the withdrawal" in rendered
    assert "Effective Grade precedence can now return" in rendered


def test_withdrawal_write_without_selection_keeps_current_explicit() -> None:
    log: list[str] = []
    output = StringIO()
    run_overrides_menu(
        dependencies=_override_deps(log),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "student_1",
            "2026-2027",
            "mp1",
            "4",
            "2",
            "teacher_1",
            "Return to base Grade",
            "WITHDRAW",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["withdraw"]
    assert "current override selection is unchanged" in output.getvalue()


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
        snapshot_sha256="e" * 64,
    )


def _snapshot_deps(log: list[str]) -> SnapshotMenuDependencies:
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
            snapshot_id=None,
            snapshot_sha256=None,
            selection_revision=None,
            selection_sha256=None,
        ),
        selection_previewer=lambda *_args: SnapshotSelectionPlan(
            class_id="class_1",
            snapshot_id="snapshot_1",
            snapshot_sha256="e" * 64,
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
            target_reference=object(),  # type: ignore[arg-type]
            expected_current=None,
        ),
        selection_committer=lambda *_args: "created",
        definition_previewer=lambda *_args: ReportingDefinitionPlan(
            class_id="class_1",
            definition_id="report_1",
            definition_revision=3,
            definition_sha256="f" * 64,
            title="MP1 Grade Report",
            purpose="Teacher reporting",
            school_year="2026-2027",
            period_id="mp1",
            actor_id="teacher_1",
            rationale="Quarterly reporting",
            candidate=object(),  # type: ignore[arg-type]
        ),
        definition_committer=lambda *_args: log.append("write") or "created",
    )


def test_reporting_definition_requires_write_confirmation() -> None:
    log: list[str] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(log),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "report_1",
            "MP1 Grade Report",
            "Teacher reporting",
            "2026-2027",
            "mp1",
            "teacher_1",
            "Quarterly reporting",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    assert "No Reporting Definition was written." in output.getvalue()


def test_reporting_definition_write_does_not_freeze_or_select() -> None:
    log: list[str] = []
    output = StringIO()
    run_snapshots_menu(
        dependencies=_snapshot_deps(log),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "report_1",
            "MP1 Grade Report",
            "Teacher reporting",
            "2026-2027",
            "mp1",
            "teacher_1",
            "Quarterly reporting",
            "WRITE",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == ["write"]
    rendered = output.getvalue()
    assert "Reporting Definition revision: created." in rendered
    assert "No ReportingSnapshot or official school-system Grade" in rendered
