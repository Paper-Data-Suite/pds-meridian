"""#124 E2G3M: verified composite recovery restores only navigation context.

Explicit RESUME and canonical verification remain owned by E2G1/E2G2/#122.
This suite verifies the session-navigation boundary, not a new writer.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian import menu_teacher_action_recovery as recovery
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext

CLASS = "english12"
WORK = ModuleWorkRef("scoreform", CLASS, "scene")
GRADE = "gi_scene"
ACTOR = TeacherActionActor("teacher_local", "b" * 64, "saved")
PUBLICATION = "pub_" + "c" * 32


def _review(publication_id: str | None = PUBLICATION) -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind="create_and_link",
        work=WORK,
        class_id=CLASS,
        school_year="2026-2027",
        registration_revision=1,
        registration_lifecycle="active",
        assessment_title="Scene Study",
        producer_label="ScoreForm",
        publication_label="Published results" if publication_id else "Registered only",
        publication_id=publication_id,
        grade_item_id=GRADE,
        grade_item_title="Scene Study Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=None,
        marking_period_id="mp1",
        marking_period_label="Marking Period 1",
        calendar_revision=1,
        actor_attribution=ACTOR.actor_id,
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="a" * 64,
    )


def _entry() -> SimpleNamespace:
    original = SimpleNamespace(
        action_id="ab" * 16,
        scope=SimpleNamespace(class_id=CLASS, grade_item_id=GRADE),
    )
    return SimpleNamespace(
        kind="grade_item",
        receipt=SimpleNamespace(action_id=original.action_id, preview=original),
    )


def _snapshot(session: TeacherSessionContext) -> tuple[object, ...]:
    return (
        session.active_class_id,
        session.active_work,
        session.active_publication_id,
        session.active_grade_item_id,
        session.active_student_id,
    )


def _offer(
    root: Path,
    session: TeacherSessionContext,
    preview: AssessmentSetupPreview,
    entry: SimpleNamespace,
    status: str,
) -> tuple[bool, str]:
    output = StringIO()
    with (
        patch.object(
            recovery,
            "inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified",
                original_preview=entry.receipt.preview,
            ),
        ) as witness,
        patch.object(
            recovery,
            "offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status=status),
        ) as prompt,
    ):
        handled = recovery._offer_assessment_setup_if_bound(
            root,
            session,
            entry,
            loader=lambda *_: (preview, ACTOR),
            input_fn=lambda _: "B",
            output=output,
        )
        witness.assert_called_once()
        prompt.assert_called_once()
    return handled, output.getvalue()


def test_verified_published_recovery_restores_exact_assessment_context(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    handled, message = _offer(tmp_path, session, _review(), _entry(), "ready_verified")
    assert handled
    assert session.active_class_id == CLASS
    assert session.active_work == WORK
    assert session.active_publication_id == PUBLICATION
    assert session.active_grade_item_id == GRADE
    assert session.active_student_id is None
    assert "retained in this session" in message


def test_verified_registered_only_recovery_does_not_invent_publication(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    handled, message = _offer(
        tmp_path, session, _review(None), _entry(), "ready_verified"
    )
    assert handled
    assert session.active_work == WORK
    assert session.active_publication_id is None
    assert session.active_grade_item_id == GRADE
    assert "retained in this session" in message


@pytest.mark.parametrize(
    "status",
    ["cancelled", "requires_review", "current_unverified", "original_grade_selected"],
)
def test_partial_or_cancelled_outcome_cannot_change_navigation(
    tmp_path: Path, status: str
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    session.select_work(WORK)
    session.select_publication(PUBLICATION)
    session.select_student("student_01")
    before = _snapshot(session)
    handled, message = _offer(tmp_path, session, _review(), _entry(), status)
    assert handled
    assert _snapshot(session) == before
    assert "Recheck the current assessment" in message


def test_existing_mismatched_publication_blocks_composite_prompt(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    session.select_work(WORK)
    session.select_publication("pub_" + "d" * 32)
    before = _snapshot(session)
    output = StringIO()
    with (
        patch.object(recovery, "inspect_original_assessment_setup_receipt") as witness,
        patch.object(recovery, "offer_assessment_setup_recovery") as prompt,
    ):
        handled = recovery._offer_assessment_setup_if_bound(
            tmp_path,
            session,
            _entry(),
            loader=lambda *_: (_review(), ACTOR),
            input_fn=lambda _: "RESUME",
            output=output,
        )
    assert handled
    assert _snapshot(session) == before
    witness.assert_not_called()
    prompt.assert_not_called()
    assert "could not be verified safely" in output.getvalue()


def test_verified_reconstruction_path_sets_session_only_after_verified_result(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    preview = _review()
    entry = _entry()
    output = StringIO()
    with (
        patch.object(
            recovery,
            "inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(
                disposition="verified_for_review", reviewed=preview
            ),
        ) as reconstructed,
        patch.object(
            recovery,
            "inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified",
                original_preview=entry.receipt.preview,
            ),
        ),
        patch.object(
            recovery,
            "offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status="ready_verified"),
        ) as prompt,
    ):
        handled = recovery._offer_verified_assessment_setup_if_bound(
            tmp_path,
            session,
            entry,
            loader=lambda *_: (preview, ACTOR, lambda: preview),
            input_fn=lambda _: "B",
            output=output,
        )
    assert handled
    reconstructed.assert_called_once()
    prompt.assert_called_once()
    assert session.active_work == WORK
    assert session.active_publication_id == PUBLICATION
    assert session.active_grade_item_id == GRADE


def test_mismatched_grade_item_blocks_context_change_before_prompt(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    session.select_work(WORK)
    session.select_grade_item("different_grade")
    before = _snapshot(session)
    output = StringIO()
    with patch.object(recovery, "offer_assessment_setup_recovery") as prompt:
        handled = recovery._offer_assessment_setup_if_bound(
            tmp_path,
            session,
            _entry(),
            loader=lambda *_: (_review(), ACTOR),
            input_fn=lambda _: "RESUME",
            output=output,
        )
    assert handled
    assert _snapshot(session) == before
    prompt.assert_not_called()
    assert "could not be verified safely" in output.getvalue()


def test_full_recovery_menu_retains_context_after_verified_prompt(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id=CLASS)
    entry = _entry()
    entry.title = "Original Grade Item"
    entry.description = "Interrupted selection"
    entry.stage = "write"
    entry.disposition = "completed"
    entry.recorded_at = "2026-11-02"
    inbox = SimpleNamespace(
        class_id=CLASS,
        review_count=1,
        completed_receipt_count=0,
        entries=(entry,),
    )
    preview = _review()
    output = StringIO()
    responses = iter(("1", "", "B"))
    with (
        patch.object(recovery, "TeacherActionReceiptStore"),
        patch.object(recovery, "read_recovery_inbox", return_value=inbox),
        patch.object(
            recovery,
            "inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(
                disposition="verified_for_review", reviewed=preview
            ),
        ),
        patch.object(
            recovery,
            "inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified",
                original_preview=entry.receipt.preview,
            ),
        ),
        patch.object(
            recovery,
            "offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status="ready_verified"),
        ) as prompt,
        patch.object(recovery, "_offer_grade_item_resume") as legacy,
    ):
        recovery.run_teacher_action_recovery_menu(
            session_context=session,
            reconstructed_context_loader=lambda *_: (preview, ACTOR, lambda: preview),
            workspace_resolver=lambda: tmp_path,
            class_validator=lambda *_: None,
            input_fn=lambda _: next(responses),
            output=output,
            clear_fn=lambda: None,
        )
    prompt.assert_called_once()
    legacy.assert_not_called()
    assert session.active_class_id == CLASS
    assert session.active_work == WORK
    assert session.active_publication_id == PUBLICATION
    assert session.active_grade_item_id == GRADE
    assert "Return to Grade Items or evidence" in output.getvalue()
