"""#124 E2G3G: activate verified recovery from top-level teacher menu."""

from io import StringIO
from unittest.mock import Mock, patch

from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu import default_teacher_menu_dependencies
from meridian.teacher_session import TeacherSessionContext


def test_default_recovery_menu_receives_bridge_and_attributed_input() -> None:
    session = TeacherSessionContext(active_class_id="class-1")
    output = StringIO()
    raw_input = Mock(return_value="B")
    bridge = Mock(spec=GuidedGradeItemBridgeDependencies)
    with (
        patch("meridian.menu.run_teacher_action_recovery_menu") as recovery,
        patch("meridian.menu.default_diagnostics_dependencies") as diagnostics,
    ):
        dependencies = default_teacher_menu_dependencies(
            session_context=session,
            assessment_bridge_dependencies=bridge,
            input_fn=raw_input,
            output=output,
            clear_fn=lambda: None,
        )
        assert dependencies.review_save_recovery is not None
        dependencies.review_save_recovery()
        recovery.assert_called_once()
        kwargs = recovery.call_args.kwargs
        assert kwargs["session_context"] is session
        assert kwargs["assessment_bridge_dependencies"] is bridge
        assert kwargs["input_fn"] is raw_input
        assert kwargs["output"] is output
        assert kwargs["diagnostics"] is diagnostics.return_value


def test_default_recovery_route_constructs_bridge_without_calling_recovery() -> None:
    with patch("meridian.menu.run_teacher_action_recovery_menu") as recovery:
        dependencies = default_teacher_menu_dependencies(
            input_fn=lambda _: "B", output=StringIO(), clear_fn=lambda: None
        )
        assert dependencies.review_save_recovery is not None
        recovery.assert_not_called()
        dependencies.review_save_recovery()
        kwargs = recovery.call_args.kwargs
        assert isinstance(
            kwargs["assessment_bridge_dependencies"],
            GuidedGradeItemBridgeDependencies,
        )


def test_top_level_r_route_invokes_recovery_once_without_resuming() -> None:
    from meridian.menu import run_menu

    output = StringIO()
    commands = iter(("R", "Q"))
    with patch("meridian.menu.run_teacher_action_recovery_menu") as recovery:
        result = run_menu(
            dependencies=default_teacher_menu_dependencies(
                input_fn=lambda _: next(commands),
                output=output,
                clear_fn=lambda: None,
            ),
            input_fn=lambda _: next(commands),
            output=output,
            clear_fn=lambda: None,
        )
    assert result == 0
    recovery.assert_called_once()
