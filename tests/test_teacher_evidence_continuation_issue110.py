from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.guided_attempts import GuidedAttemptDependencies
from meridian.guided_eligibility import GuidedEligibilityDependencies
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_evidence_continuation import (
    resolve_teacher_evidence_continuation,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
EVIDENCE = TeacherEvidenceReviewItem(
    item_id="item_hidden",
    student_id="00001",
    evidence_label="Attempt 1",
    value_label="8 / 10",
    result_kind_label="Submitted result",
    standard_ids=("RL.TS.11-12.4",),
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


def _grade_item() -> SimpleNamespace:
    return SimpleNamespace(
        grade_item_id="hidden_grade",
        display_label="Unit 1 Writing",
    )


def test_missing_grade_item_mechanically_recommends_bridge_via_eligibility() -> None:
    result = resolve_teacher_evidence_continuation(
        "workspace",
        _prepared(),
        EVIDENCE,
        TeacherSessionContext(active_class_id="english_12_pd2"),
        eligibility_dependencies=GuidedEligibilityDependencies(
            grade_items_loader=lambda *_args: SimpleNamespace(items=())
        ),
        attempt_dependencies=GuidedAttemptDependencies(),
    )

    assert result.action == "eligibility"
    assert result.label == "Set up Grade Item and review eligibility"


def test_included_evidence_with_selected_attempt_moves_to_standards() -> None:
    grade_item = _grade_item()
    session = TeacherSessionContext(active_class_id="english_12_pd2")
    session.select_grade_item("hidden_grade")

    eligibility_dependencies = GuidedEligibilityDependencies(
        grade_items_loader=lambda *_args: SimpleNamespace(
            items=(
                SimpleNamespace(
                    grade_item_id="hidden_grade",
                    selected_revision=2,
                    status="active",
                    title="Unit 1 Writing",
                    purpose="standards_proficiency",
                    memberships=(
                        SimpleNamespace(
                            work=WORK,
                            selected_revision=1,
                            decision="included",
                            grade_item_basis_state="matches_current_grade_item",
                        ),
                    ),
                ),
            )
        ),
        evidence_review_loader=lambda *_args: SimpleNamespace(
            work=WORK,
            membership_state="included",
            rows=(
                SimpleNamespace(
                    source=SimpleNamespace(item_id="item_hidden"),
                    operative_included=True,
                ),
            ),
        ),
    )
    attempt_dependencies = GuidedAttemptDependencies(
        attempt_projection_loader=lambda *_args: SimpleNamespace(
            status="selected",
            candidates=(),
            reviewed_selected_count=1,
            minimum_selected=1,
            maximum_selected=1,
        )
    )

    result = resolve_teacher_evidence_continuation(
        "workspace",
        _prepared(),
        EVIDENCE,
        session,
        eligibility_dependencies=eligibility_dependencies,
        attempt_dependencies=attempt_dependencies,
    )

    assert grade_item.display_label == "Unit 1 Writing"
    assert result.action == "standards"
    assert result.label == "Review Standard association"
