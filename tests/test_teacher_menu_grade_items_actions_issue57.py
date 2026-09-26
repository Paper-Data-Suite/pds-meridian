from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from meridian.menu_grade_items import (
    GradeItemsMenuDependencies,
    GradeItemsWriteDependencies,
    run_grade_items_menu,
)


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _read_deps() -> GradeItemsMenuDependencies:
    return GradeItemsMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        review_loader=lambda *_args: SimpleNamespace(items=()),
    )


def _write_deps(
    log: list[str],
    *,
    author_preview: object | None = None,
    selection_preview: object | None = None,
    membership_preview: object | None = None,
    membership_selection_preview: object | None = None,
) -> GradeItemsWriteDependencies:
    now = datetime(2026, 9, 23, 20, 0, tzinfo=UTC)
    return GradeItemsWriteDependencies(
        clock=lambda: now,
        authoring_previewer=lambda *_args: author_preview,
        authoring_committer=lambda *_args: (
            log.append("grade-item-write")
            or SimpleNamespace(
                write_disposition="created",
                selected_revision_after=None,
            )
        ),
        selection_previewer=lambda *_args: selection_preview,
        selection_committer=lambda *_args: (
            log.append("grade-item-select")
            or SimpleNamespace(
                selection_disposition="created",
                selected_revision=2,
            )
        ),
        membership_authoring_previewer=lambda *_args: membership_preview,
        membership_authoring_committer=lambda *_args: (
            log.append("membership-write")
            or SimpleNamespace(
                write_disposition="created",
                written_revision=1,
            )
        ),
        membership_selection_previewer=lambda *_args: (
            membership_selection_preview
        ),
        membership_selection_committer=lambda *_args: (
            log.append("membership-select")
            or SimpleNamespace(
                selection_disposition="created",
                selected_revision=1,
                selected_decision="included",
            )
        ),
    )  # type: ignore[arg-type]


def test_menu_exposes_required_grade_item_operations() -> None:
    output = StringIO()
    run_grade_items_menu(
        dependencies=_read_deps(),
        write_dependencies=_write_deps([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Author Grade Item revision" in rendered
    assert "Select Grade Item revision" in rendered
    assert "Author work membership revision" in rendered
    assert "Select work membership revision" in rendered
    assert "Review one Grade Item and work relationships" in rendered


def test_grade_item_write_cancel_does_not_commit() -> None:
    log: list[str] = []
    candidate = SimpleNamespace(
        title="Essay",
        purpose="conventional_grade",
        status="active",
        grade_item_revision=1,
    )
    preview = SimpleNamespace(
        operation="create",
        candidate=candidate,
        candidate_sha256="a" * 64,
        actor_id="teacher_1",
    )
    output = StringIO()
    run_grade_items_menu(
        dependencies=_read_deps(),
        write_dependencies=_write_deps(log, author_preview=preview),
        input_fn=ScriptedInput(
            "3",
            "class_1",
            "essay",
            "1",
            "teacher_1",
            "Essay",
            "2",
            "no",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    assert "No Grade Item revision was written." in output.getvalue()


def test_grade_item_selection_uses_separate_select_confirmation() -> None:
    log: list[str] = []
    target = SimpleNamespace(
        revision=SimpleNamespace(title="Essay"),
        revision_sha256="b" * 64,
    )
    preview = SimpleNamespace(
        target=target,
        target_revision=2,
        target_status="active",
        expected_current_revision=1,
        latest_revision=2,
    )
    run_grade_items_menu(
        dependencies=_read_deps(),
        write_dependencies=_write_deps(log, selection_preview=preview),
        input_fn=ScriptedInput(
            "4",
            "class_1",
            "essay",
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["grade-item-select"]


def test_membership_write_review_includes_academic_period_and_can_cancel() -> None:
    log: list[str] = []
    candidate = SimpleNamespace(
        work_reference=SimpleNamespace(
            work=SimpleNamespace(module_id="quillan", work_id="essay_1"),
            registration_revision=3,
        ),
        decision="included",
        membership_revision=1,
        grade_item_revision=2,
        academic_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=4,
        ),
        actor_id="teacher_1",
    )
    preview = SimpleNamespace(candidate=candidate)
    output = StringIO()
    run_grade_items_menu(
        dependencies=_read_deps(),
        write_dependencies=_write_deps(log, membership_preview=preview),
        input_fn=ScriptedInput(
            "5",
            "class_1",
            "essay",
            "quillan",
            "essay_1",
            "1",
            "2",
            "3",
            "1",
            "2026-2027",
            "mp1",
            "4",
            "teacher_1",
            "",
            "no",
            "",
            "b",
        ),
        output=output,
        clear_fn=lambda: None,
    )
    assert log == []
    rendered = output.getvalue()
    assert "Academic Period: 2026-2027 / mp1 (calendar r4)" in rendered
    assert "No membership revision was written." in rendered


def test_membership_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    preview = SimpleNamespace(
        work=SimpleNamespace(module_id="quillan", work_id="essay_1"),
        target_revision=1,
        target_decision="included",
        target_grade_item_revision=2,
        target_registration_revision=3,
        target=SimpleNamespace(decision_sha256="c" * 64),
        expected_current_membership_revision=None,
    )
    run_grade_items_menu(
        dependencies=_read_deps(),
        write_dependencies=_write_deps(
            log,
            membership_selection_preview=preview,
        ),
        input_fn=ScriptedInput(
            "6",
            "class_1",
            "essay",
            "quillan",
            "essay_1",
            "1",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["membership-select"]
