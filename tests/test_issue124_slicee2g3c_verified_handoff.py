"""E2G3C: only reverified fresh review may enter the composite prompt."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.menu_teacher_action_recovery import (
    _offer_verified_assessment_setup_if_bound,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


def _entry():
    preview = SimpleNamespace(
        action_id="original",
        scope=SimpleNamespace(class_id="class-1", grade_item_id="grade-1"),
    )
    return SimpleNamespace(
        receipt=SimpleNamespace(action_id="original", preview=preview)
    )


def _context():
    reviewed = Mock(spec=AssessmentSetupPreview)
    reviewed.class_id = "class-1"
    reviewed.grade_item_id = "grade-1"
    reviewed.work = SimpleNamespace(module_id="scoreform", work_id="work-1")
    actor = Mock(spec=TeacherActionActor)
    return reviewed, actor


def _call(tmp_path: Path, loader, output=None):
    return _offer_verified_assessment_setup_if_bound(
        tmp_path,
        TeacherSessionContext(active_class_id="class-1"),
        _entry(),
        loader=loader,
        input_fn=lambda _: "B",
        output=output or StringIO(),
    )


def test_missing_loader_keeps_legacy_route(tmp_path: Path):
    assert not _call(tmp_path, None)


def test_none_from_loader_keeps_legacy_route(tmp_path: Path):
    assert not _call(tmp_path, lambda *_: None)


def test_invalid_context_refuses_without_prompt(tmp_path: Path):
    with patch(
        "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery"
    ) as prompt:
        assert _call(tmp_path, lambda *_: (None, None))
        prompt.assert_not_called()


def test_failed_fresh_gate_refuses_without_prompt(tmp_path: Path):
    reviewed, actor = _context()
    with (
        patch(
            "meridian.menu_teacher_action_recovery.inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(disposition="requires_review", reviewed=None),
        ) as gate,
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery"
        ) as prompt,
    ):
        assert _call(tmp_path, lambda *_: (reviewed, actor, lambda: reviewed))
        gate.assert_called_once()
        prompt.assert_not_called()


def test_verified_gate_then_exact_original_binding(tmp_path: Path):
    reviewed, actor = _context()
    original = _entry().receipt.preview
    with (
        patch(
            "meridian.menu_teacher_action_recovery.inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(
                disposition="verified_for_review", reviewed=reviewed
            ),
        ),
        patch(
            "meridian.menu_teacher_action_recovery.inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified", original_preview=original
            ),
        ),
        patch(
            "meridian.menu_teacher_action_recovery.offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status="cancelled"),
        ) as prompt,
    ):
        assert _call(tmp_path, lambda *_: (reviewed, actor, lambda: reviewed))
        prompt.assert_called_once()


def test_malformed_fresh_loader_refuses(tmp_path: Path):
    reviewed, actor = _context()
    assert _call(tmp_path, lambda *_: (reviewed, actor))
