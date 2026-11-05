"""#124 E2G2: fail-closed optional composite context in existing recovery UI."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.menu_teacher_action_recovery import (
    _offer_assessment_setup_if_bound,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


def _entry() -> SimpleNamespace:
    original = SimpleNamespace(
        action_id="original-action",
        scope=SimpleNamespace(class_id="class-1", grade_item_id="grade-1"),
    )
    return SimpleNamespace(
        receipt=SimpleNamespace(preview=original, action_id="original-action")
    )


def test_no_loader_preserves_individual_recovery(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    assert not _offer_assessment_setup_if_bound(
        tmp_path,
        session,
        _entry(),
        loader=None,
        input_fn=lambda _: "RESUME",
        output=StringIO(),
    )


def test_no_matching_context_preserves_individual_recovery(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    assert not _offer_assessment_setup_if_bound(
        tmp_path,
        session,
        _entry(),
        loader=lambda *_: None,
        input_fn=lambda _: "RESUME",
        output=StringIO(),
    )


def test_wrong_reviewed_context_refuses_without_prompt(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    shown = StringIO()
    assert _offer_assessment_setup_if_bound(
        tmp_path,
        session,
        _entry(),
        loader=lambda *_: (None, None),
        input_fn=lambda _: (_ for _ in ()).throw(AssertionError("No prompt allowed")),
        output=shown,
    )
    assert "could not be verified" in shown.getvalue()


def test_exact_bound_context_delegates_only_same_original_action(
    tmp_path: Path,
) -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    reviewed = Mock(spec=AssessmentSetupPreview)
    reviewed.class_id = "class-1"
    reviewed.grade_item_id = "grade-1"
    actor = Mock(spec=TeacherActionActor)
    entry = _entry()
    witness = SimpleNamespace(
        disposition="original_receipt_verified",
        original_preview=entry.receipt.preview,
    )
    with (
        patch(
            "meridian.menu_teacher_action_recovery.inspect_original_assessment_setup_receipt",
            return_value=witness,
        ),
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status="cancelled"),
        ) as prompt,
    ):
        assert _offer_assessment_setup_if_bound(
            tmp_path,
            session,
            entry,
            loader=lambda *_: (reviewed, actor),
            input_fn=lambda _: "B",
            output=StringIO(),
        )
        prompt.assert_called_once()


def test_different_original_action_refuses_without_prompt(tmp_path: Path) -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    reviewed = Mock(spec=AssessmentSetupPreview)
    reviewed.class_id = "class-1"
    reviewed.grade_item_id = "grade-1"
    actor = Mock(spec=TeacherActionActor)
    entry = _entry()
    witness = SimpleNamespace(
        disposition="original_receipt_verified",
        original_preview=SimpleNamespace(action_id="another-action"),
    )
    with (
        patch(
            "meridian.menu_teacher_action_recovery.inspect_original_assessment_setup_receipt",
            return_value=witness,
        ),
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery"
        ) as prompt,
    ):
        assert _offer_assessment_setup_if_bound(
            tmp_path,
            session,
            entry,
            loader=lambda *_: (reviewed, actor),
            input_fn=lambda _: "RESUME",
            output=StringIO(),
        )
        prompt.assert_not_called()
