from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_eligibility import GuidedEligibilityDependencies
from meridian.guided_proficiency import GuidedProficiencyDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import (
    GuidedScaleChoice,
    GuidedStandardChoice,
    GuidedStandardChoices,
    GuidedStandardsDependencies,
)
from meridian.menu_teacher_standards import run_guided_standard_menu
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")


def _prepared() -> GuidedProjectionResult:
    return cast(
        GuidedProjectionResult,
        SimpleNamespace(
            authorized=SimpleNamespace(
                current_context=SimpleNamespace(
                    publication=SimpleNamespace(work=WORK)
                )
            )
        ),
    )


def _evidence() -> TeacherEvidenceReviewItem:
    return TeacherEvidenceReviewItem(
        item_id="hidden_item",
        student_id="00001",
        evidence_label="Attempt 1",
        value_label="8 / 10",
        result_kind_label="Submitted result",
        standard_ids=("durable:RL.TS.11-12.4",),
    )


def test_associated_standard_offers_contextual_proficiency(monkeypatch) -> None:
    import meridian.menu_teacher_standards as menu

    calls: list[dict[str, object]] = []
    standard = GuidedStandardChoice(
        standard_id="durable:RL.TS.11-12.4",
        label="RL.TS.11-12.4 | Text Structure | NJSLS-ELA",
        code="RL.TS.11-12.4",
        short_name="Text Structure",
        source="NJSLS-ELA",
        producer_declared=True,
    )
    scale = GuidedScaleChoice(
        title="English 4-Level Scale",
        context="Developing → Approaching → Meeting → Exceeding",
        display_label="English 4-Level Scale",
        reference=ProficiencyScaleReference(
            "english_12_pd2",
            "hidden_scale",
            3,
            "a" * 64,
        ),
    )

    monkeypatch.setattr(
        menu,
        "discover_guided_eligibility_grade_items",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                grade_item_id="hidden_grade",
                display_label="Unit 1 Writing",
            ),
        ),
    )
    monkeypatch.setattr(
        menu,
        "load_guided_standard_choices",
        lambda *_args, **_kwargs: GuidedStandardChoices(
            declared=(standard,),
            active=(standard,),
            unresolved_declared_ids=(),
        ),
    )
    monkeypatch.setattr(
        menu,
        "load_guided_scale_choices",
        lambda *_args, **_kwargs: (scale,),
    )
    monkeypatch.setattr(
        menu,
        "build_guided_standards_projection",
        lambda *_args, **_kwargs: SimpleNamespace(
            association_disposition=None,
        ),
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_standard_association",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_standard_association",
        lambda *_args, **_kwargs: SimpleNamespace(written_revision=2),
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_standard_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_standard_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "reload_guided_standards_projection",
        lambda *_args, **_kwargs: SimpleNamespace(
            association_disposition="associated",
        ),
    )

    def proficiency(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr(menu, "run_guided_proficiency_menu", proficiency)

    output = StringIO()
    scripted = ScriptedInput(
        "1",
        "1",
        "1",
        "Stephen Severino",
        "",
        "1",
        "1",
        "1",
    )
    run_guided_standard_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=TeacherSessionContext(
            active_class_id="english_12_pd2"
        ),
        dependencies=GuidedStandardsDependencies(),
        eligibility_dependencies=GuidedEligibilityDependencies(),
        proficiency_dependencies=GuidedProficiencyDependencies(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    assert len(calls) == 1
    assert calls[0]["grade_item_label"] == "Unit 1 Writing"
    assert calls[0]["subject_label"] == "Jane Smith"
    rendered = output.getvalue()
    assert "Recommended next step:" in rendered
    assert "Preview proficiency" in rendered
    assert "hidden_grade" not in rendered
    assert "00001" not in rendered


def test_standard_menu_uses_code_label_and_scale_title_without_ids(
    monkeypatch,
) -> None:
    import meridian.menu_teacher_standards as menu

    standard = GuidedStandardChoice(
        standard_id="durable:RL.TS.11-12.4",
        label="RL.TS.11-12.4 | Text Structure | NJSLS-ELA",
        code="RL.TS.11-12.4",
        short_name="Text Structure",
        source="NJSLS-ELA",
        producer_declared=True,
    )
    scale = GuidedScaleChoice(
        title="English 4-Level Scale",
        context="Developing → Approaching → Meeting → Exceeding",
        display_label=(
            "English 4-Level Scale · "
            "Developing → Approaching → Meeting → Exceeding"
        ),
        reference=ProficiencyScaleReference(
            "english_12_pd2",
            "hidden_scale",
            3,
            "a" * 64,
        ),
    )
    projection = SimpleNamespace(
        association_disposition=None,
    )
    refreshed = SimpleNamespace(
        association_disposition="associated",
    )

    monkeypatch.setattr(
        menu,
        "discover_guided_eligibility_grade_items",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                grade_item_id="hidden_grade",
                display_label="Unit 1 Writing",
            ),
        ),
    )
    monkeypatch.setattr(
        menu,
        "load_guided_standard_choices",
        lambda *_args, **_kwargs: GuidedStandardChoices(
            declared=(standard,),
            active=(standard,),
            unresolved_declared_ids=(),
        ),
    )
    monkeypatch.setattr(
        menu,
        "load_guided_scale_choices",
        lambda *_args, **_kwargs: (scale,),
    )
    monkeypatch.setattr(
        menu,
        "build_guided_standards_projection",
        lambda *_args, **_kwargs: projection,
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_standard_association",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_standard_association",
        lambda *_args, **_kwargs: SimpleNamespace(written_revision=2),
    )
    monkeypatch.setattr(
        menu,
        "preview_guided_standard_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "commit_guided_standard_selection",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        menu,
        "reload_guided_standards_projection",
        lambda *_args, **_kwargs: refreshed,
    )

    scripted = ScriptedInput(
        "1",
        "1",
        "1",
        "Stephen Severino",
        "",
        "1",
        "1",
        "",
    )
    output = StringIO()
    session = TeacherSessionContext(active_class_id="english_12_pd2")

    run_guided_standard_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=_evidence(),
        subject_label="Jane Smith",
        session_context=session,
        dependencies=GuidedStandardsDependencies(),
        eligibility_dependencies=GuidedEligibilityDependencies(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "RL.TS.11-12.4 | Text Structure | NJSLS-ELA" in rendered
    assert "English 4-Level Scale" in rendered
    assert "Producer-declared alignment" in rendered
    assert "Current association: Associated" in rendered
    for forbidden in (
        "durable:RL.TS.11-12.4",
        "hidden_scale",
        "hidden_grade",
        "hidden_item",
        "00001",
        "Standard ID",
        "scale ID",
        "scale revision",
        "sha256",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)
