"""Mechanical next-step resolver for the Issue #110 guided evidence route."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptError,
    load_guided_attempt_review,
)
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityError,
    GuidedEligibilityGradeItemChoice,
    discover_guided_eligibility_grade_items,
    load_guided_eligibility_context,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem
from meridian.teacher_session import TeacherSessionContext

TeacherEvidenceContinuationAction: TypeAlias = Literal[
    "eligibility",
    "attempts",
    "standards",
    "refresh",
    "finish",
]


@dataclass(frozen=True, slots=True)
class TeacherEvidenceContinuation:
    """One mechanical recommendation; never an academic decision."""

    action: TeacherEvidenceContinuationAction
    label: str
    reason: str


def _eligibility(
    label: str,
    reason: str,
) -> TeacherEvidenceContinuation:
    return TeacherEvidenceContinuation("eligibility", label, reason)


def _selected_grade_item(
    choices: tuple[GuidedEligibilityGradeItemChoice, ...],
    session: TeacherSessionContext,
) -> GuidedEligibilityGradeItemChoice | None:
    if session.active_grade_item_id is not None:
        matches = tuple(
            choice
            for choice in choices
            if choice.grade_item_id == session.active_grade_item_id
        )
        if len(matches) == 1:
            return matches[0]
    if len(choices) == 1:
        return choices[0]
    return None


def resolve_teacher_evidence_continuation(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    session: TeacherSessionContext,
    *,
    eligibility_dependencies: GuidedEligibilityDependencies,
    attempt_dependencies: GuidedAttemptDependencies,
) -> TeacherEvidenceContinuation:
    """Reload current state and derive the next teacher-controlled stage."""

    work = prepared.authorized.current_context.publication.work
    try:
        grade_items = discover_guided_eligibility_grade_items(
            workspace_root,
            work,
            dependencies=eligibility_dependencies,
        )
    except GuidedEligibilityError:
        return TeacherEvidenceContinuation(
            "refresh",
            "Refresh current evidence state",
            "Current Grade Item state changed or could not be revalidated.",
        )

    if not grade_items:
        return _eligibility(
            "Set up Grade Item and review eligibility",
            "No current included Grade Item relationship is available.",
        )

    grade_item = _selected_grade_item(grade_items, session)
    if grade_item is None:
        return _eligibility(
            "Choose Grade Item and review eligibility",
            "More than one current included Grade Item is available.",
        )

    try:
        eligibility = load_guided_eligibility_context(
            workspace_root,
            prepared,
            grade_item,
            item_id=evidence.item_id,
            dependencies=eligibility_dependencies,
        )
    except GuidedEligibilityError:
        return TeacherEvidenceContinuation(
            "refresh",
            "Refresh current evidence state",
            "The selected evidence or eligibility basis changed.",
        )

    if not eligibility.row.operative_included:
        return _eligibility(
            "Review eligibility",
            (
                "This evidence is not currently operative as included for "
                f"{grade_item.display_label}."
            ),
        )

    if evidence.student_id is None:
        return TeacherEvidenceContinuation(
            "finish",
            "Finish for now",
            "No student-specific continuation applies to this shared evidence.",
        )

    try:
        attempts = load_guided_attempt_review(
            workspace_root,
            prepared=prepared,
            grade_item_id=grade_item.grade_item_id,
            student_id=evidence.student_id,
            dependencies=attempt_dependencies,
        )
    except GuidedAttemptError:
        return TeacherEvidenceContinuation(
            "refresh",
            "Refresh current evidence state",
            "Current attempt/reassessment state could not be revalidated.",
        )

    if attempts.status in {"selected", "selected_none", "not_applicable"}:
        return TeacherEvidenceContinuation(
            "standards",
            "Review Standard association",
            "Eligibility and applicable attempt selection are current.",
        )

    return TeacherEvidenceContinuation(
        "attempts",
        "Review attempts / reassessment",
        "Eligibility is current; attempt/reassessment state still needs review.",
    )


__all__ = (
    "TeacherEvidenceContinuation",
    "TeacherEvidenceContinuationAction",
    "resolve_teacher_evidence_continuation",
)
