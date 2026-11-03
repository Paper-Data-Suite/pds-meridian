"""#124 E2G3E: choices are explicitly entered and never inferred from a receipt."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.assessment_setup_teacher_choices import (
    make_interactive_assessment_choice_provider,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


def _input(*values: str):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_new_choices_are_explicit(tmp_path):
    actor = TeacherActionActor("teacher", "a" * 64, "saved")
    choice = make_interactive_assessment_choice_provider(
        input_fn=_input(
            "scoreform",
            "work-1",
            "2026-2027",
            "mp1",
            "standards_proficiency",
            "new",
            "Original",
            "",
            "teacher",
        ),
        output=StringIO(),
    )
    with patch(
        "meridian.assessment_setup_teacher_choices.resolve_menu_actor",
        return_value=actor,
    ):
        result = choice(
            tmp_path,
            TeacherSessionContext(active_class_id="class-1"),
            SimpleNamespace(receipt=object()),
        )
    assert result is not None
    selected, verified = result
    assert selected.work.work_id == "work-1"
    assert selected.new_title == "Original"
    assert selected.existing_grade_item_id is None
    assert verified == actor


def test_back_cancels_without_actor_lookup(tmp_path):
    provider = make_interactive_assessment_choice_provider(
        input_fn=_input("B"), output=StringIO()
    )
    with patch("meridian.assessment_setup_teacher_choices.resolve_menu_actor") as actor:
        assert (
            provider(
                tmp_path, TeacherSessionContext(active_class_id="class-1"), object()
            )
            is None
        )
        actor.assert_not_called()


@pytest.mark.parametrize("control,error", [("M", ReturnToMainMenu), ("Q", QuitPDS)])
def test_global_navigation_propagates(tmp_path, control, error):
    provider = make_interactive_assessment_choice_provider(
        input_fn=_input(control), output=StringIO()
    )
    with pytest.raises(error):
        provider(tmp_path, TeacherSessionContext(active_class_id="class-1"), object())


def test_unsupported_purpose_fails_before_actor(tmp_path):
    provider = make_interactive_assessment_choice_provider(
        input_fn=_input("scoreform", "work", "2026-2027", "mp1", "bogus"),
        output=StringIO(),
    )
    with pytest.raises(ValueError, match="purpose"):
        provider(tmp_path, TeacherSessionContext(active_class_id="class-1"), object())
