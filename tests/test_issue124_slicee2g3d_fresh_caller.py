"""#124 E2G3D: fresh teacher choice port is read-only and fail closed."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_fresh_review_caller import (
    FreshAssessmentChoices,
    make_fresh_assessment_context_loader,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


def _fixtures():
    work = ModuleWorkRef("scoreform", "class-1", "work-1")
    choices = FreshAssessmentChoices(
        work,
        "2026-2027",
        "mp1",
        "standards_proficiency",
        None,
        "Assessment",
        "teacher",
        None,
    )
    actor = TeacherActionActor("teacher", "a" * 64, "saved")
    entry = SimpleNamespace(
        receipt=SimpleNamespace(
            preview=SimpleNamespace(
                scope=SimpleNamespace(
                    class_id="class-1", school_year=None, grade_item_id="grade-1"
                )
            )
        )
    )
    return choices, actor, entry


def test_repeated_fresh_reads_are_independent(tmp_path: Path) -> None:
    choices, actor, entry = _fixtures()
    session = TeacherSessionContext(active_class_id="class-1")
    with patch(
        "meridian.assessment_setup_fresh_review_caller.load_assessment_setup_preview"
    ) as source:
        source.return_value = SimpleNamespace(grade_item_id="grade-1")
        loader = make_fresh_assessment_context_loader(
            Mock(), choose=lambda *_: (choices, actor)
        )
        preview, restored_actor, refresh = loader(tmp_path, session, entry)
        assert preview.grade_item_id == "grade-1"
        assert restored_actor == actor
        assert refresh().grade_item_id == "grade-1"
        assert source.call_count == 2


def test_absent_choices_do_not_infer_from_receipt(tmp_path: Path) -> None:
    _, _, entry = _fixtures()
    session = TeacherSessionContext(active_class_id="class-1")
    loader = make_fresh_assessment_context_loader(Mock(), choose=lambda *_: None)
    assert loader(tmp_path, session, entry) is None


def test_actor_drift_rejected_before_preview_read(tmp_path: Path) -> None:
    choices, _, entry = _fixtures()
    session = TeacherSessionContext(active_class_id="class-1")
    wrong = TeacherActionActor("another", "a" * 64, "saved")
    with patch(
        "meridian.assessment_setup_fresh_review_caller.load_assessment_setup_preview"
    ) as source:
        loader = make_fresh_assessment_context_loader(
            Mock(), choose=lambda *_: (choices, wrong)
        )
        with pytest.raises(ValueError, match="scope"):
            loader(tmp_path, session, entry)
        source.assert_not_called()


def test_grade_item_drift_rejected(tmp_path: Path) -> None:
    choices, actor, entry = _fixtures()
    session = TeacherSessionContext(active_class_id="class-1")
    with patch(
        "meridian.assessment_setup_fresh_review_caller.load_assessment_setup_preview"
    ) as source:
        source.return_value = SimpleNamespace(grade_item_id="other")
        loader = make_fresh_assessment_context_loader(
            Mock(), choose=lambda *_: (choices, actor)
        )
        with pytest.raises(ValueError, match="Grade Item"):
            loader(tmp_path, session, entry)
