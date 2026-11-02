"""#124 E2G3A: read-only context candidate is not recovery authority."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meridian.assessment_setup_restart import inspect_restart_context_candidate
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import _identity


def _actor() -> TeacherActionActor:
    return TeacherActionActor("teacher", "a" * 64, "saved")


def _record(root: Path, *, work_id: str = "work") -> SimpleNamespace:
    return SimpleNamespace(
        class_id="class",
        module_id="scoreform",
        work_id=work_id,
        workspace_sha256=_identity("workspace", str(root.resolve())),
        actor_id="teacher",
        actor_profile_sha256="a" * 64,
        intent_sha256="b" * 64,
    )


def test_unique_candidate_is_only_a_hint(tmp_path: Path) -> None:
    record = _record(tmp_path)
    with patch(
        "meridian.assessment_setup_restart.AssessmentSetupCorrelationStore"
    ) as factory:
        factory.return_value.list_records.return_value = (record,)
        result = inspect_restart_context_candidate(
            tmp_path, "class", "scoreform", "work", _actor()
        )
        assert factory.return_value.list_records.call_count == 2
    assert result.disposition == "unique_candidate"
    assert result.intent_sha256 == "b" * 64
    assert not result.may_resume_automatically
    assert not result.may_select_academic_record


def test_absent_and_ambiguous_fail_closed(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_restart.AssessmentSetupCorrelationStore"
    ) as factory:
        for records in ((), (_record(tmp_path), _record(tmp_path))):
            factory.return_value.list_records.return_value = records
            result = inspect_restart_context_candidate(
                tmp_path, "class", "scoreform", "work", _actor()
            )
            assert result.disposition == "requires_review"


def test_changed_inventory_fails_closed(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_restart.AssessmentSetupCorrelationStore"
    ) as factory:
        factory.return_value.list_records.side_effect = [
            (_record(tmp_path),),
            (),
        ]
        result = inspect_restart_context_candidate(
            tmp_path, "class", "scoreform", "work", _actor()
        )
    assert result.reason == "inventory_changed"


def test_actor_drift_and_invalid_input_fail_closed(tmp_path: Path) -> None:
    with patch(
        "meridian.assessment_setup_restart.AssessmentSetupCorrelationStore"
    ) as factory:
        factory.return_value.list_records.return_value = (_record(tmp_path),)
        other = TeacherActionActor("other", "a" * 64, "saved")
        result = inspect_restart_context_candidate(
            tmp_path, "class", "scoreform", "work", other
        )
        assert result.reason == "scope_or_actor_changed"
    invalid = inspect_restart_context_candidate(
        tmp_path, "class", "scoreform", "", _actor()
    )
    assert invalid.reason == "invalid_context"
