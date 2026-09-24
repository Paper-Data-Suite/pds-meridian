from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.menu_evidence import (
    AuthorizedEvidenceContext,
    EvidenceActionDependencies,
    EvidenceMenuDependencies,
    run_new_evidence_menu,
)
from meridian.new_evidence_workflow import NewEvidenceReview
from meridian.projection_cache import AuthorizedProjectionSnapshot


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)

    def __call__(self, prompt: str) -> str:
        _ = prompt
        return next(self._responses)


def _context() -> AuthorizedEvidenceContext:
    review = cast(NewEvidenceReview, SimpleNamespace(rows=()))
    authorized = cast(AuthorizedProjectionSnapshot, object())
    return AuthorizedEvidenceContext(review=review, authorized=authorized)


def _menu_deps() -> EvidenceMenuDependencies:
    return EvidenceMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        diagnostics=cast(object, object()),  # type: ignore[arg-type]
        review_loader=lambda *_args: cast(NewEvidenceReview, object()),
    )


def _actions(
    log: list[str],
    *,
    author_preview: object | None = None,
    selection_preview: object | None = None,
) -> EvidenceActionDependencies:
    return EvidenceActionDependencies(
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        context_loader=lambda *_args: _context(),
        authoring_previewer=lambda *_args: author_preview,
        authoring_committer=lambda *_args: (
            log.append("write")
            or SimpleNamespace(
                written_revision=2,
                written_disposition="excluded",
            )
        ),
        selection_previewer=lambda *_args: selection_preview,
        selection_committer=lambda *_args: (
            log.append("select")
            or SimpleNamespace(
                selection_disposition="updated",
                selected_revision=2,
                selected_disposition="excluded",
            )
        ),
    )  # type: ignore[arg-type]


def test_new_evidence_menu_exposes_eligibility_follow_up() -> None:
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions([]),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Author academic eligibility revision" in rendered
    assert "Select academic eligibility revision" in rendered
    assert "Grade Item authoring remains in Manage Grade Items." in rendered


def test_eligibility_write_cancel_does_not_commit() -> None:
    log: list[str] = []
    decision = SimpleNamespace(
        source=SimpleNamespace(item_id="item_1"),
        disposition="excluded",
        policy=SimpleNamespace(policy_id="teacher", policy_version="1"),
        actor=SimpleNamespace(actor_id="teacher_1"),
    )
    preview = SimpleNamespace(
        decision=decision,
        candidate_revision=2,
        selected_revision=1,
    )
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions(log, author_preview=preview),
        input_fn=ScriptedInput(
            "2",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "item_1",
            "2",
            "teacher_1",
            "teacher",
            "1",
            "",
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
    assert "Writing this revision will NOT select it." in rendered
    assert "No eligibility revision was written." in rendered


def test_eligibility_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    preview = SimpleNamespace(
        target=SimpleNamespace(
            decision=SimpleNamespace(
                source=SimpleNamespace(item_id="item_1"),
            ),
            decision_sha256="b" * 64,
        ),
        target_revision=2,
        target_disposition="excluded",
        expected_current_revision=1,
        membership_revision=3,
        source_state=SimpleNamespace(state="current"),
    )
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=_actions(log, selection_preview=preview),
        input_fn=ScriptedInput(
            "3",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "item_1",
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]
