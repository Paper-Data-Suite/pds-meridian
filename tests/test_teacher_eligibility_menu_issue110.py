from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityPolicyChoice,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_eligibility import run_guided_eligibility_menu
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


def _prepared() -> GuidedProjectionResult:
    return cast(
        GuidedProjectionResult,
        SimpleNamespace(
            authorized=SimpleNamespace(
                current_context=SimpleNamespace(
                    publication=SimpleNamespace(
                        work=ModuleWorkRef(
                            "scoreform",
                            "english_12_pd2",
                            "memory_snapshot",
                        )
                    )
                )
            )
        ),
    )


def _evidence() -> TeacherEvidenceReviewItem:
    return TeacherEvidenceReviewItem(
        item_id="hidden_item_1",
        student_id="00001",
        evidence_label="Attempt 1",
        value_label="8 / 10",
        result_kind_label="Submitted result",
        standard_ids=("RL.TS.11-12.4",),
    )


def test_no_grade_item_relationship_is_teacher_facing() -> None:
    deps = GuidedEligibilityDependencies(
        grade_items_loader=lambda _root, _class_id: SimpleNamespace(items=()),
    )
    output = StringIO()

    run_guided_eligibility_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=TeacherSessionContext(
            active_class_id="english_12_pd2"
        ),
        dependencies=deps,
        input_fn=ScriptedInput(""),
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Grade Item Relationship Needed" in rendered
    assert "will not infer or create" in rendered
    assert "hidden_item_1" not in rendered
    assert "00001" not in rendered


def test_guided_menu_uses_labels_and_explicit_write_then_select() -> None:
    log: list[str] = []
    policy = GuidedEligibilityPolicyChoice(
        title="Teacher review",
        policy_id="teacher_local_eligibility",
        policy_version="1",
    )
    prepared = _prepared()
    exact_work = prepared.authorized.current_context.publication.work

    states = iter(("no_decision", "included"))

    def review_loader(*_args: object) -> object:
        return SimpleNamespace(
            work=exact_work,
            membership_state="included",
            rows=(
                SimpleNamespace(
                    source=SimpleNamespace(item_id="hidden_item_1"),
                    eligibility_status=next(states),
                ),
            ),
        )

    deps = GuidedEligibilityDependencies(
        grade_items_loader=lambda _root, _class_id: SimpleNamespace(
            items=(
                SimpleNamespace(
                    grade_item_id="hidden_grade_item",
                    selected_revision=1,
                    status="active",
                    title="Unit 1 Writing",
                    purpose="conventional_grade",
                    memberships=(
                        SimpleNamespace(
                            work=exact_work,
                            selected_revision=1,
                            decision="included",
                            grade_item_basis_state=(
                                "matches_current_grade_item"
                            ),
                        ),
                    ),
                ),
            )
        ),
        evidence_review_loader=review_loader,  # type: ignore[arg-type]
        authoring_previewer=lambda *_args: (
            log.append("preview-write") or SimpleNamespace()
        ),
        authoring_committer=lambda *_args: (
            log.append("write") or SimpleNamespace(written_revision=3)
        ),
        selection_previewer=lambda *_args: (
            log.append("preview-select") or SimpleNamespace()
        ),
        selection_committer=lambda *_args: (
            log.append("select") or SimpleNamespace()
        ),
        policies=(policy,),
    )  # type: ignore[arg-type]

    output = StringIO()
    scripted = ScriptedInput(
        "1",
        "1",
        "1",
        "Stephen Severino",
        "",
        "1",
        "1",
        "",
    )
    session = TeacherSessionContext(active_class_id="english_12_pd2")

    run_guided_eligibility_menu(
        workspace_root=Path("workspace"),
        prepared=prepared,
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=session,
        dependencies=deps,
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    assert log == ["preview-write", "write", "preview-select", "select"]
    assert session.active_grade_item_id == "hidden_grade_item"
    rendered = output.getvalue()
    assert "Unit 1 Writing" in rendered
    assert "Jane Smith" in rendered
    assert "Teacher review" in rendered
    assert "Current eligibility: Included" in rendered
    assert "Current canonical state was reloaded" in rendered
    for forbidden in (
        "hidden_grade_item",
        "hidden_item_1",
        "00001",
        "Grade Item ID",
        "Evidence item ID",
        "Teacher actor ID",
        "Policy ID",
        "Policy version",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)
