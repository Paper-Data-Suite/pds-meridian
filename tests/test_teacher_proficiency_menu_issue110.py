from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_proficiency import (
    GuidedMappingProfileChoice,
    GuidedProficiencyContext,
    GuidedProficiencyDependencies,
    GuidedProficiencyPolicyChoice,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import GuidedScaleChoice, GuidedStandardChoice
from meridian.menu_teacher_proficiency import run_guided_proficiency_menu
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
SCALE = GuidedScaleChoice(
    title="English 4-Level Scale",
    context="Developing → Approaching → Meeting → Exceeding",
    display_label="English 4-Level Scale",
    reference=ProficiencyScaleReference(
        "english_12_pd2",
        "hidden_scale",
        2,
        "a" * 64,
    ),
)
STANDARD = GuidedStandardChoice(
    standard_id="durable:RL.TS.11-12.4",
    label="RL.TS.11-12.4 | Text Structure | NJSLS-ELA",
    code="RL.TS.11-12.4",
    short_name="Text Structure",
    source="NJSLS-ELA",
    producer_declared=True,
)
EVIDENCE = TeacherEvidenceReviewItem(
    item_id="hidden_item",
    student_id="00001",
    evidence_label="Attempt 1",
    value_label="8 / 10",
    result_kind_label="Submitted result",
    standard_ids=(STANDARD.standard_id,),
)


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


def test_proficiency_menu_carries_context_without_raw_ids(monkeypatch) -> None:
    import meridian.menu_teacher_proficiency as menu

    policy = GuidedProficiencyPolicyChoice(
        title="Standards Policy",
        strategy="highest",
        minimum_observations=1,
        display_label="Standards Policy · Highest · minimum 1",
        reference=cast(object, SimpleNamespace()),
    )
    mapping = GuidedMappingProfileChoice(
        display_label="Raw points · 10 points possible · 4 ranges",
        mapping_kind="raw_points",
        reference=cast(object, SimpleNamespace()),
    )
    context = GuidedProficiencyContext(
        source=cast(object, SimpleNamespace()),
        evidence_item=cast(object, SimpleNamespace()),
        scale=cast(
            object,
            SimpleNamespace(
                scale=SimpleNamespace(
                    levels=(
                        SimpleNamespace(level_id="meeting", label="Meeting"),
                    )
                )
            ),
        ),
        policies=(policy,),
        mappings=(mapping,),
    )  # type: ignore[arg-type]
    outcome = SimpleNamespace(
        status="calculated",
        proficiency_level_id="meeting",
        performance_observation_count=1,
        native_state_count=0,
        excluded_count=0,
    )
    reviewed = SimpleNamespace(
        calculation=SimpleNamespace(outcome=outcome),
    )

    monkeypatch.setattr(
        menu,
        "load_guided_proficiency_context",
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(
        menu,
        "build_guided_proficiency_preview",
        lambda *_args, **_kwargs: reviewed,
    )

    output = StringIO()
    scripted = ScriptedInput("1", "1", "2")
    run_guided_proficiency_menu(
        workspace_root=Path("workspace"),
        prepared=_prepared(),
        evidence=EVIDENCE,
        subject_label="Jane Smith",
        grade_item_id="hidden_grade",
        grade_item_label="Unit 1 Writing",
        standard=STANDARD,
        scale=SCALE,
        dependencies=GuidedProficiencyDependencies(),
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    assert "Jane Smith" in rendered
    assert "Unit 1 Writing" in rendered
    assert "RL.TS.11-12.4 | Text Structure | NJSLS-ELA" in rendered
    assert "English 4-Level Scale" in rendered
    assert "Standards Policy" in rendered
    assert "Raw points · 10 points possible · 4 ranges" in rendered
    assert "Proficiency: Meeting" in rendered
    assert "This preview uses only the evidence row you just reviewed." in rendered
    for forbidden in (
        "hidden_grade",
        "hidden_scale",
        "hidden_item",
        "00001",
        "Policy ID",
        "Target proficiency scale ID",
        "Target scale revision",
        "sha256",
    ):
        assert forbidden not in rendered
        assert all(forbidden not in prompt for prompt in scripted.prompts)
