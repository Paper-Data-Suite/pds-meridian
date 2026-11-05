"""#124 E2G3B: no automatic selection after reconstructed review."""

from pathlib import Path
from unittest.mock import patch

from meridian.assessment_setup_reconstructed_context import (
    inspect_reconstructed_assessment_context,
)
from meridian.teacher_action_contract import TeacherActionActor


def test_invalid_loader_refused(tmp_path: Path) -> None:
    result = inspect_reconstructed_assessment_context(
        tmp_path,
        "class",
        "scoreform",
        "work",
        TeacherActionActor("teacher", "a" * 64, "saved"),
        load_fresh_review=None,  # type: ignore[arg-type]
    )
    assert result.disposition == "requires_review"
    assert not result.may_resume_automatically
    assert not result.may_select_academic_record


def test_missing_candidate_prevents_review_loading(tmp_path: Path) -> None:
    actor = TeacherActionActor("teacher", "a" * 64, "saved")
    with patch(
        "meridian.assessment_setup_reconstructed_context."
        "inspect_restart_context_candidate"
    ) as inspector:
        inspector.return_value.disposition = "requires_review"
        inspector.return_value.reason = "absent_or_ambiguous_context"
        inspector.return_value.intent_sha256 = None
        result = inspect_reconstructed_assessment_context(
            tmp_path,
            "class",
            "scoreform",
            "work",
            actor,
            load_fresh_review=lambda: (_ for _ in ()).throw(AssertionError()),
        )
    assert result.reason == "absent_or_ambiguous_context"


def test_reconstructed_wrong_type_refused(tmp_path: Path) -> None:
    actor = TeacherActionActor("teacher", "a" * 64, "saved")
    with patch(
        "meridian.assessment_setup_reconstructed_context."
        "inspect_restart_context_candidate"
    ) as inspector:
        inspector.return_value.disposition = "unique_candidate"
        inspector.return_value.intent_sha256 = "b" * 64
        result = inspect_reconstructed_assessment_context(
            tmp_path,
            "class",
            "scoreform",
            "work",
            actor,
            load_fresh_review=lambda: None,  # type: ignore[return-value]
        )
    assert result.reason == "invalid_fresh_review"
