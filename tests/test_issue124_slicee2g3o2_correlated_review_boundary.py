"""#124 E2G3O2: only the original E2C fenced binder reaches one-APPLY review.

All fixtures are synthetic. Injected actions stand in for #122 academic ports;
E2C persistence and original-receipt behavior have separate regression gates.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu_teacher_assessment_setup_review import (
    review_correlated_assessment_setup_once,
)
from meridian.teacher_action_contract import TeacherActionActor, TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction
from meridian.teacher_session import TeacherSessionContext

CLASS = "english12"
WORK = ModuleWorkRef("scoreform", CLASS, "scene")
GRADE = "gi_scene"
ACTOR = TeacherActionActor("teacher_local", "b" * 64, "saved")
DEPS = GuidedGradeItemBridgeDependencies()


def _review(kind: str = "create_and_link") -> AssessmentSetupPreview:
    return AssessmentSetupPreview(
        kind=cast(Any, kind),
        work=WORK,
        class_id=CLASS,
        school_year="2026-2027",
        registration_revision=1,
        registration_lifecycle="active",
        assessment_title="Synthetic Scene Assessment",
        producer_label="ScoreForm",
        publication_label="Registered only",
        publication_id=None,
        grade_item_id=GRADE,
        grade_item_title="Scene Grade",
        grade_item_purpose="standards_proficiency",
        selected_grade_item_revision=(None if kind == "create_and_link" else 1),
        marking_period_id="mp1",
        marking_period_label="Marking Period 1",
        calendar_revision=1,
        actor_attribution=(None if kind == "already_ready" else ACTOR.actor_id),
        rationale=None,
        operations=(),
        weighting_message="Not configured",
        review_sha256="a" * 64,
    )


def _composite(
    review: AssessmentSetupPreview,
    log: list[str],
    *,
    member_status: str = "applied",
) -> PreparedAssessmentSetupComposite:
    def action(family: str, status: str) -> PreparedGuidedAction:
        p = SimpleNamespace(
            kind=family,
            target=SimpleNamespace(family=family),
            scope=SimpleNamespace(
                class_id=CLASS,
                grade_item_id=GRADE,
                school_year="2026-2027",
                academic_period_id="mp1",
            ),
            actor=SimpleNamespace(actor_id=ACTOR.actor_id),
        )

        def apply(*, confirmed: bool) -> TeacherActionResult:
            assert confirmed
            log.append("apply:" + family)
            return cast(
                TeacherActionResult,
                SimpleNamespace(
                    status=status,
                    action_id=("c" if family == "grade_item" else "d") * 32,
                ),
            )

        return cast(PreparedGuidedAction, SimpleNamespace(preview=p, apply=apply))

    def fresh() -> AssessmentSetupPreview:
        log.append("fresh")
        return review

    def interim() -> bool:
        log.append("interim")
        return True

    def final() -> bool:
        log.append("final")
        return True

    def member() -> PreparedGuidedAction:
        log.append("prepare:membership")
        return action("grade_item_membership", member_status)

    return PreparedAssessmentSetupComposite(
        preview=review,
        fresh_review=fresh,
        after_grade_read=interim,
        verify_ready=final,
        grade_item_action=(
            action("grade_item", "applied")
            if review.kind == "create_and_link"
            else None
        ),
        membership_factory=None if review.kind == "already_ready" else member,
    )


def _run(
    tmp_path: Path,
    *,
    kind: str = "create_and_link",
    answer: str = "APPLY",
    member_status: str = "applied",
) -> tuple[object, object, list[str], str, Mock]:
    review = _review(kind)
    session = TeacherSessionContext(active_class_id=CLASS)
    log: list[str] = []
    binder = Mock(return_value=_composite(review, log, member_status=member_status))
    input_fn = Mock(return_value=answer)
    output = StringIO()
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "bind_correlated_live_assessment_setup",
        binder,
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            review,
            session,
            actor=None if kind == "already_ready" else ACTOR,
            dependencies=DEPS,
            input_fn=input_fn,
            output=output,
        )
    binder.assert_called_once_with(
        tmp_path,
        review,
        actor=None if kind == "already_ready" else ACTOR,
        dependencies=DEPS,
    )
    return result, session, log, output.getvalue(), input_fn


def test_create_and_link_requires_one_apply_and_retains_verified_context(
    tmp_path: Path,
) -> None:
    result, session, events, message, input_fn = _run(tmp_path)
    assert result.ready and result.status == "ready"
    assert result.action_ids == ("c" * 32, "d" * 32)
    assert session.active_work == WORK
    assert session.active_grade_item_id == GRADE
    assert session.active_publication_id is None
    assert events == [
        "fresh",
        "apply:grade_item",
        "interim",
        "prepare:membership",
        "apply:grade_item_membership",
        "final",
    ]
    input_fn.assert_called_once_with("Confirmation: ")
    assert "verified current" in message


def test_existing_item_has_only_original_membership_action(tmp_path: Path) -> None:
    result, session, events, _, input_fn = _run(tmp_path, kind="use_existing")
    assert result.status == "ready" and result.action_ids == ("d" * 32,)
    assert session.active_work == WORK
    assert "apply:grade_item" not in events
    assert events.count("apply:grade_item_membership") == 1
    input_fn.assert_called_once_with("Confirmation: ")


def test_already_ready_requires_fresh_read_but_no_confirmation(tmp_path: Path) -> None:
    result, session, events, _, input_fn = _run(tmp_path, kind="already_ready")
    assert result.status == "already_ready"
    assert session.active_grade_item_id == GRADE
    assert events == ["fresh", "final"]
    input_fn.assert_not_called()


def test_cancellation_never_enters_domain_action_or_changes_session(
    tmp_path: Path,
) -> None:
    result, session, events, _, input_fn = _run(tmp_path, answer="B")
    assert result.status == "cancelled"
    assert events == []
    assert session.active_work is None
    assert session.active_grade_item_id is None
    input_fn.assert_called_once()


def test_partial_membership_does_not_claim_readiness_or_change_session(
    tmp_path: Path,
) -> None:
    result, session, events, message, _ = _run(
        tmp_path, member_status="written_not_current"
    )
    assert result.status == "requires_review"
    assert "apply:grade_item" in events
    assert "apply:grade_item_membership" in events
    assert session.active_grade_item_id is None
    assert "not verified ready" in message


@pytest.mark.parametrize(
    "actor",
    [
        None,
        TeacherActionActor("teacher_local", "b" * 64, "temporary"),
        TeacherActionActor("other", "b" * 64, "saved"),
    ],
)
def test_missing_temporary_or_mismatched_actor_refuses_before_binding(
    tmp_path: Path, actor: TeacherActionActor | None
) -> None:
    reviewed = _review()
    session = TeacherSessionContext(active_class_id=CLASS)
    binder = Mock()
    input_fn = Mock(return_value="APPLY")
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "bind_correlated_live_assessment_setup",
        binder,
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            reviewed,
            session,
            actor=actor,
            dependencies=DEPS,
            input_fn=input_fn,
            output=StringIO(),
        )
    assert result.reason == "saved_actor_required"
    binder.assert_not_called()
    input_fn.assert_not_called()


def test_wrong_session_refuses_before_binder_or_prompt(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id="english10")
    binder = Mock()
    input_fn = Mock(return_value="APPLY")
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "bind_correlated_live_assessment_setup",
        binder,
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            _review(),
            session,
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=input_fn,
            output=StringIO(),
        )
    assert result.reason == "session_scope_changed"
    binder.assert_not_called()
    input_fn.assert_not_called()


def test_missing_root_refuses_before_binder(tmp_path: Path) -> None:
    binder = Mock()
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "bind_correlated_live_assessment_setup",
        binder,
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path / "absent",
            _review(),
            TeacherSessionContext(active_class_id=CLASS),
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=Mock(return_value="APPLY"),
            output=StringIO(),
        )
    assert result.reason == "invalid_correlated_context"
    binder.assert_not_called()


def test_prior_correlation_is_not_a_new_apply_authority(tmp_path: Path) -> None:
    binder = Mock()
    old = SimpleNamespace(
        grade_item_id=GRADE, module_id="other_module", work_id="different_work"
    )
    with (
        patch(
            "meridian.menu_teacher_assessment_setup_review."
            "AssessmentSetupCorrelationStore.list_records",
            return_value=(old,),
        ),
        patch(
            "meridian.menu_teacher_assessment_setup_review."
            "bind_correlated_live_assessment_setup",
            binder,
        ),
    ):
        output = StringIO()
        input_fn = Mock(return_value="APPLY")
        result = review_correlated_assessment_setup_once(
            tmp_path,
            _review(),
            TeacherSessionContext(active_class_id=CLASS),
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=input_fn,
            output=output,
        )
    assert result.reason == "prior_correlated_action_requires_recovery"
    assert "Review Interrupted Saves" in output.getvalue()
    binder.assert_not_called()
    input_fn.assert_not_called()


def test_prior_work_identity_is_also_a_collision(tmp_path: Path) -> None:
    old = SimpleNamespace(
        grade_item_id="other_grade",
        module_id=WORK.module_id,
        work_id=WORK.work_id,
    )
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "AssessmentSetupCorrelationStore.list_records",
        return_value=(old,),
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            _review(),
            TeacherSessionContext(active_class_id=CLASS),
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=Mock(),
            output=StringIO(),
        )
    assert result.reason == "prior_correlated_action_requires_recovery"


def test_corrupt_correlation_inventory_fails_closed(tmp_path: Path) -> None:
    binder = Mock()
    with (
        patch(
            "meridian.menu_teacher_assessment_setup_review."
            "AssessmentSetupCorrelationStore.list_records",
            side_effect=RuntimeError("corrupt inventory"),
        ),
        patch(
            "meridian.menu_teacher_assessment_setup_review."
            "bind_correlated_live_assessment_setup",
            binder,
        ),
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            _review(),
            TeacherSessionContext(active_class_id=CLASS),
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=Mock(),
            output=StringIO(),
        )
    assert result.reason == "correlation_inventory_unavailable"
    binder.assert_not_called()


def test_binder_failure_refuses_without_confirmation(tmp_path: Path) -> None:
    input_fn = Mock(return_value="APPLY")
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "bind_correlated_live_assessment_setup",
        side_effect=RuntimeError("canonical source drift"),
    ):
        result = review_correlated_assessment_setup_once(
            tmp_path,
            _review(),
            TeacherSessionContext(active_class_id=CLASS),
            actor=ACTOR,
            dependencies=DEPS,
            input_fn=input_fn,
            output=StringIO(),
        )
    assert result.reason == "correlated_binding_unavailable"
    input_fn.assert_not_called()


def test_ready_path_does_not_reinspect_old_claimed_correlation(tmp_path: Path) -> None:
    # Read-only already-ready verification is permitted even after a prior
    # successfully correlated setup; it must not create another action.
    with patch(
        "meridian.menu_teacher_assessment_setup_review."
        "AssessmentSetupCorrelationStore.list_records",
    ) as inventory:
        result, _, _, _, _ = _run(tmp_path, kind="already_ready")
    assert result.ready
    inventory.assert_not_called()
