"""Issue #110 teacher-friendly Grade Item bridge, after #122 single Save."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu_teacher_grade_items import run_grade_item_bridge
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")


def test_bridge_existing_grade_item_uses_teacher_labels(monkeypatch) -> None:
    import meridian.menu_teacher_grade_items as menu

    context = SimpleNamespace(
        work=WORK,
        registration_revision=4,
        work_title="Memory Snapshot",
        existing_grade_items=(
            SimpleNamespace(
                grade_item_id="hidden_grade",
                title="Unit 1 Writing",
                purpose="standards_proficiency",
                display_label="Unit 1 Writing",
                selected_revision=2,
            ),
        ),
        periods=(
            SimpleNamespace(
                label="Marking Period 1",
                display_label=(
                    "Marking Period 1 · marking period · 2026-09-01 to 2026-11-05"
                ),
            ),
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        menu,
        "load_guided_grade_item_bridge_context",
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(
        menu,
        "resolve_menu_actor",
        lambda *_args, **_kwargs: TeacherActionActor(
            "teacher_synthetic", "a" * 64, "saved"
        ),
    )
    monkeypatch.setattr(
        menu,
        "preview_membership_link",
        lambda *_args, **_kwargs: calls.append("preview") or SimpleNamespace(),
    )

    class SyntheticAction:
        def apply(self, *, confirmed: bool) -> object:
            assert confirmed
            calls.append("apply")
            return SimpleNamespace(succeeded=True, status="applied")

    monkeypatch.setattr(
        menu,
        "prepare_membership_action",
        lambda *_args, **_kwargs: calls.append("prepare") or SyntheticAction(),
    )
    monkeypatch.setattr(
        menu,
        "verify_current_membership_link",
        lambda *_args, **_kwargs: True,
    )

    output = StringIO()
    scripted = ScriptedInput("1", "teacher_synthetic", "1", "", "1", "")
    session = TeacherSessionContext(active_class_id="english_12_pd2")
    result = run_grade_item_bridge(
        workspace_root=Path("workspace"),
        work=WORK,
        session_context=session,
        dependencies=GuidedGradeItemBridgeDependencies(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    assert result is True
    assert calls == ["preview", "prepare", "apply"]
    assert session.active_grade_item_id == "hidden_grade"
    rendered = output.getvalue()
    assert "Memory Snapshot" in rendered
    assert "Unit 1 Writing" in rendered
    assert "Marking Period 1" in rendered
    assert "Save and make current" in rendered
    assert "Make Relationship Current" not in rendered
    assert "hidden_grade" not in rendered
    for forbidden in (
        "Grade Item ID",
        "registration revision",
        "calendar revision",
        "membership revision",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)
