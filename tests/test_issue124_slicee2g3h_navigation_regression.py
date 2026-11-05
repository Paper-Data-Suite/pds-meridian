"""#124 E2G3H: recovery menu navigation and fail-closed handoff regressions."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from meridian import menu_teacher_action_recovery as recovery
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


def _inbox() -> SimpleNamespace:
    entry = SimpleNamespace(
        kind="grade_item",
        title="Original Grade Item",
        description="Interrupted selection",
        stage="written",
        disposition="pending",
        recorded_at="2026-11-02",
        receipt=SimpleNamespace(
            action_id="original-action",
            preview=SimpleNamespace(
                action_id="original-action",
                scope=SimpleNamespace(class_id="class-1", grade_item_id="grade-1"),
            ),
        ),
    )
    return SimpleNamespace(
        class_id="class-1",
        review_count=1,
        completed_receipt_count=0,
        entries=(entry,),
    )


def _run(tmp_path: Path, answers: tuple[str, ...], *, loader: object) -> str:
    stream = StringIO()
    with (
        patch.object(recovery, "TeacherActionReceiptStore"),
        patch.object(recovery, "read_recovery_inbox", return_value=_inbox()),
        patch.object(recovery, "_offer_grade_item_resume") as legacy,
    ):
        commands = iter(answers)
        recovery.run_teacher_action_recovery_menu(
            session_context=TeacherSessionContext(active_class_id="class-1"),
            reconstructed_context_loader=loader,  # type: ignore[arg-type]
            workspace_resolver=lambda: tmp_path,
            class_validator=lambda *_: None,
            input_fn=lambda _: next(commands),
            output=stream,
            clear_fn=lambda: None,
        )
        legacy.assert_not_called()
    return stream.getvalue()


def test_cancelled_review_never_enters_resume_prompt(tmp_path: Path) -> None:
    with patch.object(recovery, "offer_assessment_setup_recovery") as prompt:
        message = _run(tmp_path, ("B",), loader=lambda *_: None)
    prompt.assert_not_called()
    assert "Review Interrupted Saves" in message


def test_bad_loader_result_fails_closed_without_legacy_fallback(tmp_path: Path) -> None:
    with patch.object(recovery, "offer_assessment_setup_recovery") as prompt:
        message = _run(tmp_path, ("1", "", "B"), loader=lambda *_: (None, None))
    prompt.assert_not_called()
    assert "could not be verified safely" in message


def _review() -> tuple[Mock, Mock]:
    reviewed = Mock(spec=AssessmentSetupPreview)
    reviewed.class_id = "class-1"
    reviewed.grade_item_id = "grade-1"
    reviewed.work = SimpleNamespace(module_id="scoreform", work_id="work-1")
    actor = Mock(spec=TeacherActionActor)
    return reviewed, actor


def test_changed_canonical_review_refuses_before_action_prompt(tmp_path: Path) -> None:
    reviewed, actor = _review()
    with (
        patch.object(
            recovery,
            "inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(disposition="requires_review", reviewed=None),
        ),
        patch.object(recovery, "offer_assessment_setup_recovery") as prompt,
    ):
        message = _run(
            tmp_path,
            ("1", "", "B"),
            loader=lambda *_: (reviewed, actor, lambda: reviewed),
        )
    prompt.assert_not_called()
    assert "could not be verified safely" in message


def test_different_original_receipt_never_offers_resume(tmp_path: Path) -> None:
    reviewed, actor = _review()
    with (
        patch.object(
            recovery,
            "inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(
                disposition="verified_for_review",
                reviewed=reviewed,
            ),
        ),
        patch.object(
            recovery,
            "inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified",
                original_preview=SimpleNamespace(action_id="different-action"),
            ),
        ),
        patch.object(recovery, "offer_assessment_setup_recovery") as prompt,
    ):
        message = _run(
            tmp_path,
            ("1", "", "B"),
            loader=lambda *_: (reviewed, actor, lambda: reviewed),
        )
    prompt.assert_not_called()
    assert "could not be verified safely" in message


def test_duplicate_resume_prevented_for_same_selected_entry(tmp_path: Path) -> None:
    reviewed, actor = _review()
    original = _inbox().entries[0].receipt.preview
    with (
        patch.object(
            recovery,
            "inspect_reconstructed_assessment_context",
            return_value=SimpleNamespace(
                disposition="verified_for_review",
                reviewed=reviewed,
            ),
        ),
        patch.object(
            recovery,
            "inspect_original_assessment_setup_receipt",
            return_value=SimpleNamespace(
                disposition="original_receipt_verified",
                original_preview=original,
            ),
        ),
        patch.object(
            recovery,
            "offer_assessment_setup_recovery",
            return_value=SimpleNamespace(status="cancelled"),
        ) as prompt,
    ):
        _run(
            tmp_path,
            ("1", "", "B"),
            loader=lambda *_: (reviewed, actor, lambda: reviewed),
        )
    prompt.assert_called_once()


def test_loader_failure_does_not_silently_resume(tmp_path: Path) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("unavailable canonical review")

    with patch.object(recovery, "offer_assessment_setup_recovery") as prompt:
        message = _run(tmp_path, ("1", "", "B"), loader=broken)
    prompt.assert_not_called()
    assert "could not be verified safely" in message
