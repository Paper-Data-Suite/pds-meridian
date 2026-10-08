from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
    GuidedAttemptReview,
)
from meridian.guided_eligibility import GuidedEligibilityDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_attempts import run_guided_attempt_menu
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
POLICY = GuidedAttemptPolicyPreset(
    title="Select exactly one attempt",
    description="Use one explicit attempt.",
    policy_id="hidden_policy",
    minimum_selected=1,
    maximum_selected=1,
)


def _prepared() -> GuidedProjectionResult:
    return cast(
        GuidedProjectionResult,
        SimpleNamespace(
            authorized=SimpleNamespace(
                current_context=SimpleNamespace(
                    publication=SimpleNamespace(work=WORK)
                )
            )
        ),
    )


def _evidence() -> TeacherEvidenceReviewItem:
    return TeacherEvidenceReviewItem(
        item_id="hidden_item",
        student_id="00001",
        evidence_label="Attempt 1",
        value_label="8 / 10",
        result_kind_label="Submitted result",
        standard_ids=(),
    )


def test_no_grade_item_relationship_blocks_without_ids() -> None:
    output = StringIO()
    run_guided_attempt_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=TeacherSessionContext(
            active_class_id="english_12_pd2"
        ),
        dependencies=GuidedAttemptDependencies(policies=(POLICY,)),
        eligibility_dependencies=GuidedEligibilityDependencies(
            grade_items_loader=lambda *_args: SimpleNamespace(items=())
        ),
        input_fn=ScriptedInput(""),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Grade Item Relationship Needed" in rendered
    assert "hidden_item" not in rendered
    assert "00001" not in rendered


def test_attempt_menu_uses_teacher_labels_not_hidden_identity(
    monkeypatch,
) -> None:
    import meridian.menu_teacher_attempts as menu

    output = StringIO()
    session = TeacherSessionContext(active_class_id="english_12_pd2")
    session.select_grade_item("hidden_grade")

    grade_choice = SimpleNamespace(
        grade_item_id="hidden_grade",
        display_label="Unit 1 Writing",
    )
    candidate_attempt = SimpleNamespace()
    review = GuidedAttemptReview(
        status="no_decision",
        candidates=(
            SimpleNamespace(
                label="Attempt 2",
                eligible_evidence_count=1,
                attempt=candidate_attempt,
            ),
        ),
        selected_count=0,
        minimum_selected=1,
        maximum_selected=1,
        projection=cast(object, SimpleNamespace()),
    )  # type: ignore[arg-type]

    monkeypatch.setattr(
        menu,
        "discover_guided_eligibility_grade_items",
        lambda *_args, **_kwargs: (grade_choice,),
    )
    monkeypatch.setattr(
        menu,
        "plan_guided_attempt_policy",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="ready",
            preset=POLICY,
            target_revision=None,
        ),
    )
    monkeypatch.setattr(menu, "apply_guided_attempt_policy", lambda *_a, **_k: None)
    states = iter((review, SimpleNamespace(selected_count=1)))
    monkeypatch.setattr(
        menu,
        "load_guided_attempt_review",
        lambda *_args, **_kwargs: next(states),
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_attempt_decision",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_attempt_decision",
        lambda *_args, **_kwargs: SimpleNamespace(written_revision=1),
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_attempt_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_attempt_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )

    scripted = ScriptedInput(
        "1",
        "Stephen Severino",
        "1",
        "",
        "1",
        "1",
        "",
    )
    run_guided_attempt_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=session,
        dependencies=GuidedAttemptDependencies(policies=(POLICY,)),
        eligibility_dependencies=GuidedEligibilityDependencies(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Jane Smith" in rendered
    assert "Unit 1 Writing" in rendered
    assert "Select exactly one attempt" in rendered
    assert "Attempt 2" in rendered
    assert "Current selected attempts: 1" in rendered
    for forbidden in (
        "hidden_policy",
        "hidden_grade",
        "hidden_item",
        "00001",
        "Student ID",
        "Policy ID",
        "Attempt-selection policy ID",
        "revision",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)
