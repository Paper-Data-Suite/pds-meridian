"""#124 E2G3N: teacher-facing single confirmation and truthful continuation.

The prepared actions are injected #122 stand-ins. Canonical persistence and
original-receipt restart are independently qualified in E2G3K/L.
"""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.menu_teacher_assessment_setup_review import review_assessment_setup_once
from meridian.teacher_action_contract import TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction
from meridian.teacher_session import TeacherSessionContext

CLASS = "english12"
WORK = ModuleWorkRef("scoreform", CLASS, "scene")
PUBLICATION = "pub_" + "a" * 32
GRADE = "gi_scene"


def _preview(
    *, kind: str = "create_and_link", publication: str | None = PUBLICATION
) -> AssessmentSetupPreview:
    from typing import Any

    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=WORK,
        class_id=CLASS,
        school_year="2026-2027",
        registration_revision=1,
        registration_lifecycle="active",
        assessment_title="Scene and Pacing Check",
        producer_label="ScoreForm",
        publication_label="Published results" if publication else "Registered only",
        publication_id=publication,
        grade_item_id=GRADE,
        grade_item_title="Scene and Pacing",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=1 if kind != "create_and_link" else None,
        marking_period_id="mp1",
        marking_period_label="Marking Period 1",
        calendar_revision=1,
        actor_attribution=None if kind == "already_ready" else "teacher_local",
        rationale=None,
        operations=("Create and select Grade Item", "Include in marking period"),
        weighting_message="Not configured",
        review_sha256="c" * 64,
    )


def _harness(
    *,
    kind: str = "create_and_link",
    grade_status: str = "applied",
    membership_status: str = "applied",
    fresh_ok: bool = True,
    verified: bool = True,
    publication: str | None = PUBLICATION,
) -> tuple[PreparedAssessmentSetupComposite, list[str]]:
    events: list[str] = []
    review = _preview(kind=kind, publication=publication)

    def action(family: str, status: str) -> PreparedGuidedAction:
        preview = SimpleNamespace(
            kind=family,
            target=SimpleNamespace(family=family),
            scope=SimpleNamespace(
                class_id=CLASS,
                grade_item_id=GRADE,
                school_year="2026-2027",
                academic_period_id="mp1",
            ),
            actor=SimpleNamespace(actor_id="teacher_local"),
        )

        def apply(*, confirmed: bool) -> TeacherActionResult:
            assert confirmed is True
            events.append("apply:" + family)
            return cast(
                TeacherActionResult,
                SimpleNamespace(
                    status=status,
                    action_id=("b" if family == "grade_item" else "d") * 32,
                ),
            )

        return cast(PreparedGuidedAction, SimpleNamespace(preview=preview, apply=apply))

    def fresh() -> AssessmentSetupPreview:
        events.append("fresh")
        return review if fresh_ok else _preview(kind="use_existing")

    def after_grade() -> bool:
        events.append("after_grade")
        return True

    def final() -> bool:
        events.append("verify_ready")
        return verified

    def membership() -> PreparedGuidedAction:
        events.append("prepare_membership")
        return action("grade_item_membership", membership_status)

    prepared = PreparedAssessmentSetupComposite(
        preview=review,
        fresh_review=fresh,
        after_grade_read=after_grade,
        verify_ready=final,
        grade_item_action=(
            action("grade_item", grade_status) if kind == "create_and_link" else None
        ),
        membership_factory=membership if kind != "already_ready" else None,
    )
    return prepared, events


def _session() -> TeacherSessionContext:
    return TeacherSessionContext(active_class_id=CLASS)


def _run(
    prepared: PreparedAssessmentSetupComposite,
    session: TeacherSessionContext,
    answer: str = "APPLY",
) -> tuple[object, str, list[str]]:
    output = StringIO()
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    result = review_assessment_setup_once(
        prepared, session, input_fn=read, output=output
    )
    return result, output.getvalue(), prompts


@pytest.mark.parametrize("answer", ["CANCEL", "", "apply", "B", "RESUME"])
def test_cancel_does_not_execute_or_change_navigation(answer: str) -> None:
    prepared, events = _harness()
    session = _session()
    result, message, prompts = _run(prepared, session, answer)
    assert result.status == "cancelled"
    assert prompts == ["Confirmation: "]
    assert "Cancelled" in message
    assert events == []
    assert session.active_work is None
    assert session.active_grade_item_id is None
    assert session.active_publication_id is None


def test_create_and_link_one_teacher_confirmation_two_domain_actions() -> None:
    prepared, events = _harness()
    session = _session()
    result, message, prompts = _run(prepared, session)
    assert result.status == "ready"
    assert result.ready
    assert result.action_ids == ("b" * 32, "d" * 32)
    assert prompts == ["Confirmation: "]
    assert events == [
        "fresh",
        "apply:grade_item",
        "after_grade",
        "prepare_membership",
        "apply:grade_item_membership",
        "verify_ready",
    ]
    assert session.active_work == WORK
    assert session.active_grade_item_id == GRADE
    assert session.active_publication_id == PUBLICATION
    assert "Scene and Pacing Check" in message
    assert "Marking Period 1" in message
    assert "verified current" in message


def test_use_existing_only_selects_missing_membership() -> None:
    prepared, events = _harness(kind="use_existing")
    result, _, prompts = _run(prepared, _session())
    assert result.status == "ready"
    assert prompts == ["Confirmation: "]
    assert "apply:grade_item" not in events
    assert events.count("apply:grade_item_membership") == 1


def test_verified_already_ready_needs_no_prompt_or_writes() -> None:
    prepared, events = _harness(kind="already_ready", publication=None)
    session = _session()
    result, _, prompts = _run(prepared, session, answer="CANCEL")
    assert result.status == "already_ready"
    assert prompts == []
    assert events == ["fresh", "verify_ready"]
    assert session.active_work == WORK
    assert session.active_publication_id is None


@pytest.mark.parametrize("which", ["grade", "membership", "verify", "review"])
def test_partial_or_stale_result_never_advances_session(which: str) -> None:
    prepared, _ = _harness(
        grade_status="recovery_required" if which == "grade" else "applied",
        membership_status=(
            "written_not_current" if which == "membership" else "applied"
        ),
        verified=which != "verify",
        fresh_ok=which != "review",
    )
    session = _session()
    session.select_work(WORK)
    session.select_student("student_01")
    previous = (
        session.active_work,
        session.active_publication_id,
        session.active_grade_item_id,
        session.active_student_id,
    )
    result, message, prompts = _run(prepared, session)
    assert result.status == "requires_review"
    assert prompts == ["Confirmation: "]
    assert "not verified ready" in message
    assert (
        session.active_work,
        session.active_publication_id,
        session.active_grade_item_id,
        session.active_student_id,
    ) == previous


@pytest.mark.parametrize("which", ["class", "work", "grade", "publication"])
def test_conflicting_navigation_refuses_before_confirmation(which: str) -> None:
    prepared, events = _harness()
    session = _session()
    if which == "class":
        session.select_class("english11")
    elif which == "work":
        session.select_work(ModuleWorkRef("scoreform", CLASS, "other"))
    elif which == "grade":
        session.select_grade_item("other_grade")
    else:
        session.select_work(WORK)
        session.select_publication("pub_" + "d" * 32)
    result, _, prompts = _run(prepared, session)
    assert result.status == "requires_review"
    assert result.reason == "session_scope_changed"
    assert prompts == []
    assert events == []


def test_one_shot_reentry_never_reexecutes_the_same_plan() -> None:
    prepared, events = _harness()
    session = _session()
    result, _, _ = _run(prepared, session)
    assert result.ready
    before = tuple(events)
    again, message, _ = _run(prepared, session)
    assert again.status == "requires_review"
    assert "not verified ready" in message
    assert tuple(events) == before


def test_already_ready_requires_canonical_reverification() -> None:
    prepared, events = _harness(kind="already_ready", verified=False)
    session = _session()
    result, _, prompts = _run(prepared, session)
    assert result.status == "requires_review"
    assert prompts == []
    assert events == ["fresh", "verify_ready"]
    assert session.active_work is None


def test_registered_only_does_not_invent_publication() -> None:
    prepared, _ = _harness(publication=None)
    session = _session()
    result, _, _ = _run(prepared, session)
    assert result.ready
    assert session.active_work == WORK
    assert session.active_publication_id is None
