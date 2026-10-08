from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_items_workflow import GradeItemsReview
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityGradeItemAmbiguityError,
    GuidedEligibilityPolicyChoice,
    discover_guided_eligibility_grade_items,
    preview_guided_eligibility,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringPreview,
)

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")


def _membership(*, included: bool = True) -> object:
    return SimpleNamespace(
        work=WORK,
        selected_revision=1,
        decision="included" if included else "excluded",
        grade_item_basis_state="matches_current_grade_item",
    )


def _grade_row(
    grade_item_id: str,
    title: str,
    *,
    purpose: str = "conventional_grade",
    membership: object | None = None,
) -> object:
    return SimpleNamespace(
        grade_item_id=grade_item_id,
        selected_revision=1,
        status="active",
        title=title,
        purpose=purpose,
        memberships=(() if membership is None else (membership,)),
    )


def _review(*rows: object) -> GradeItemsReview:
    return cast(GradeItemsReview, SimpleNamespace(items=rows))


def test_grade_item_choices_require_current_included_relationship() -> None:
    review = _review(
        _grade_row("essay", "Essay", membership=_membership()),
        _grade_row(
            "quiz",
            "Quiz",
            membership=_membership(included=False),
        ),
        _grade_row("other", "Other"),
    )
    deps = GuidedEligibilityDependencies(
        grade_items_loader=lambda _root, _class_id: review,
    )

    choices = discover_guided_eligibility_grade_items(
        Path("workspace"),
        WORK,
        dependencies=deps,
    )

    assert len(choices) == 1
    assert choices[0].grade_item_id == "essay"
    assert choices[0].display_label == "Essay"


def test_duplicate_titles_use_purpose_then_block_if_still_ambiguous() -> None:
    distinct = _review(
        _grade_row(
            "a",
            "Unit 1",
            purpose="conventional_grade",
            membership=_membership(),
        ),
        _grade_row(
            "b",
            "Unit 1",
            purpose="standards_evidence",
            membership=_membership(),
        ),
    )
    deps = GuidedEligibilityDependencies(
        grade_items_loader=lambda _root, _class_id: distinct,
    )
    choices = discover_guided_eligibility_grade_items(
        Path("workspace"),
        WORK,
        dependencies=deps,
    )
    assert {choice.display_label for choice in choices} == {
        "Unit 1 · conventional_grade",
        "Unit 1 · standards_evidence",
    }

    ambiguous = _review(
        _grade_row("a", "Unit 1", membership=_membership()),
        _grade_row("b", "Unit 1", membership=_membership()),
    )
    deps = GuidedEligibilityDependencies(
        grade_items_loader=lambda _root, _class_id: ambiguous,
    )
    with pytest.raises(GuidedEligibilityGradeItemAmbiguityError):
        discover_guided_eligibility_grade_items(
            Path("workspace"),
            WORK,
            dependencies=deps,
        )


def test_guided_preview_supplies_policy_and_manual_reason_without_id_prompts() -> None:
    observed: dict[str, object] = {}
    expected = cast(NewEvidenceEligibilityAuthoringPreview, object())
    row = SimpleNamespace(
        source=SimpleNamespace(item_id="hidden_item"),
        eligibility_status="no_decision",
    )
    context = SimpleNamespace(
        review=object(),
        row=row,
    )
    prepared = cast(
        GuidedProjectionResult,
        SimpleNamespace(authorized=object()),
    )
    policy = GuidedEligibilityPolicyChoice(
        "Teacher review",
        "teacher_local_eligibility",
        "1",
    )

    def previewer(*args: object) -> NewEvidenceEligibilityAuthoringPreview:
        observed["args"] = args
        return expected

    deps = GuidedEligibilityDependencies(
        authoring_previewer=previewer,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 7, 20, 0, tzinfo=UTC),
    )

    result = preview_guided_eligibility(
        Path("workspace"),
        prepared,
        context,  # type: ignore[arg-type]
        disposition="excluded",
        teacher_attribution="Stephen Severino",
        policy=policy,
        rationale="Not part of this Grade Item.",
        dependencies=deps,
    )

    assert result is expected
    args = cast(tuple[object, ...], observed["args"])
    assert args[4] == "excluded"
    assert args[5] == "Stephen Severino"
    assert args[6:8] == ("teacher_local_eligibility", "1")
    assert args[8] == ("eligibility.manual",)
    assert args[9] == "Not part of this Grade Item."
