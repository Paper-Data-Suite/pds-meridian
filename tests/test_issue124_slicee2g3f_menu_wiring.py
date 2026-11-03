"""#124 E2G3F: opt-in teacher-choice wizard wiring in recovery navigation."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meridian.menu_teacher_action_recovery import run_teacher_action_recovery_menu
from meridian.teacher_session import TeacherSessionContext


def test_dependencies_wire_explicit_wizard_without_action(tmp_path: Path) -> None:
    output = StringIO()
    dependencies = Mock()
    session = TeacherSessionContext(active_class_id=None)
    provider = Mock()
    constructed = Mock()
    with (
        patch(
            "meridian.menu_teacher_action_recovery."
            "make_interactive_assessment_choice_provider",
            return_value=provider,
        ) as wizard,
        patch(
            "meridian.menu_teacher_action_recovery."
            "make_fresh_assessment_context_loader",
            return_value=constructed,
        ) as fresh,
    ):
        run_teacher_action_recovery_menu(
            session_context=session,
            assessment_bridge_dependencies=dependencies,
            workspace_resolver=lambda: tmp_path,
            input_fn=lambda _: "",
            output=output,
            clear_fn=lambda: None,
        )
    wizard.assert_called_once()
    fresh.assert_called_once_with(dependencies, choose=provider)
    assert "Select a class" in output.getvalue()


def test_explicit_loader_takes_precedence(tmp_path: Path) -> None:
    explicit = Mock()
    with (
        patch(
            "meridian.menu_teacher_action_recovery."
            "make_interactive_assessment_choice_provider"
        ) as wizard,
        patch(
            "meridian.menu_teacher_action_recovery.make_fresh_assessment_context_loader"
        ) as fresh,
    ):
        run_teacher_action_recovery_menu(
            session_context=TeacherSessionContext(active_class_id=None),
            assessment_bridge_dependencies=Mock(),
            reconstructed_context_loader=explicit,
            input_fn=lambda _: "",
            output=StringIO(),
            clear_fn=lambda: None,
        )
    wizard.assert_not_called()
    fresh.assert_not_called()


def test_no_dependencies_preserves_legacy_default() -> None:
    with patch(
        "meridian.menu_teacher_action_recovery."
        "make_interactive_assessment_choice_provider"
    ) as wizard:
        run_teacher_action_recovery_menu(
            session_context=TeacherSessionContext(active_class_id=None),
            input_fn=lambda _: "",
            output=StringIO(),
            clear_fn=lambda: None,
        )
    wizard.assert_not_called()


def test_verified_composite_handled_never_falls_through(tmp_path: Path) -> None:
    from meridian import menu_teacher_action_recovery as menu

    entry = SimpleNamespace(
        kind="grade_item",
        title="Saved Grade Item",
        description="Interrupted",
        stage="written",
        disposition="pending",
        recorded_at="2026-11-02",
        receipt=SimpleNamespace(),
    )
    inbox = SimpleNamespace(
        class_id="class-1",
        review_count=1,
        completed_receipt_count=0,
        entries=(entry,),
    )
    answers = iter(("1", "", "B"))
    with (
        patch.object(menu, "TeacherActionReceiptStore"),
        patch.object(menu, "read_recovery_inbox", return_value=inbox),
        patch.object(
            menu, "_offer_verified_assessment_setup_if_bound", return_value=True
        ) as verified,
        patch.object(menu, "_offer_grade_item_resume") as legacy,
        patch.object(menu, "_offer_assessment_setup_if_bound") as composite,
    ):
        run_teacher_action_recovery_menu(
            session_context=TeacherSessionContext(active_class_id="class-1"),
            reconstructed_context_loader=Mock(),
            workspace_resolver=lambda: tmp_path,
            class_validator=lambda *_: None,
            input_fn=lambda _: next(answers),
            output=StringIO(),
            clear_fn=lambda: None,
        )
    verified.assert_called_once()
    legacy.assert_not_called()
    composite.assert_not_called()
