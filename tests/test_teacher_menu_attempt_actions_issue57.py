from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from meridian.attempt_selection_storage import AttemptCandidateDerivation
from meridian.menu_evidence import (
    AttemptActionDependencies,
    AuthorizedEvidenceContext,
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
    review = cast(
        NewEvidenceReview,
        SimpleNamespace(grade_item_id="grade_item_1"),
    )
    authorized = cast(AuthorizedProjectionSnapshot, object())
    return AuthorizedEvidenceContext(review=review, authorized=authorized)


def _menu_deps() -> EvidenceMenuDependencies:
    return EvidenceMenuDependencies(
        workspace_resolver=lambda: Path("workspace"),
        diagnostics=cast(object, object()),  # type: ignore[arg-type]
        review_loader=lambda *_args: cast(NewEvidenceReview, object()),
    )


def _attempts(
    log: list[str],
    *,
    derivation: object | None = None,
    author_preview: object | None = None,
    selection_preview: object | None = None,
) -> AttemptActionDependencies:
    return AttemptActionDependencies(
        clock=lambda: datetime(2026, 9, 23, 20, 0, tzinfo=UTC),
        context_loader=lambda *_args: _context(),
        candidate_loader=lambda *_args: cast(
            AttemptCandidateDerivation,
            derivation,
        ),
        authoring_previewer=lambda *_args: author_preview,
        authoring_committer=lambda *_args: (
            log.append("write")
            or SimpleNamespace(
                write_disposition="created",
                written_revision=2,
            )
        ),
        selection_previewer=lambda *_args: selection_preview,
        selection_committer=lambda *_args: (
            log.append("select")
            or SimpleNamespace(
                selection_disposition="updated",
                selected_revision=2,
            )
        ),
    )  # type: ignore[arg-type]


def _empty_derivation() -> object:
    return SimpleNamespace(status="applicable", candidates=())


def test_new_evidence_menu_exposes_attempt_follow_up() -> None:
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=_attempts([], derivation=_empty_derivation()),
        input_fn=ScriptedInput("b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Author attempt / reassessment decision" in rendered
    assert "Select attempt / reassessment decision" in rendered


def test_attempt_write_cancel_does_not_commit() -> None:
    log: list[str] = []
    candidate = SimpleNamespace(
        student_id="student_1",
        policy=SimpleNamespace(policy_id="policy_1", policy_revision=3),
        decision_revision=2,
        selected_attempts=(),
    )
    preview = SimpleNamespace(
        candidate=candidate,
        candidate_count=0,
        selected_count=0,
        reviewed_current_decision_revision=1,
    )
    output = StringIO()
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=_attempts(
            log,
            derivation=_empty_derivation(),
            author_preview=preview,
        ),
        input_fn=ScriptedInput(
            "4",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "",
            "",
            "policy_1",
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
    assert "Writing this revision will NOT select it." in rendered
    assert "No attempt decision revision was written." in rendered


def test_attempt_selection_requires_select_confirmation() -> None:
    log: list[str] = []
    decision = SimpleNamespace(
        student_id="student_1",
        selected_attempts=(),
        candidates=(),
        policy=SimpleNamespace(policy_id="policy_1", policy_revision=3),
    )
    preview = SimpleNamespace(
        target=SimpleNamespace(decision=decision),
        target_revision=2,
        target_sha256="b" * 64,
        expected_current_decision_revision=1,
    )
    run_new_evidence_menu(
        dependencies=_menu_deps(),
        action_dependencies=cast(object, object()),  # type: ignore[arg-type]
        attempt_dependencies=_attempts(log, selection_preview=preview),
        input_fn=ScriptedInput(
            "5",
            "pub_00000000000000000000000000000000",
            "a" * 64,
            "grade_item_1",
            "teacher_review",
            "student_1",
            "2",
            "SELECT",
            "",
            "b",
        ),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    assert log == ["select"]
