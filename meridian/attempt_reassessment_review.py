"""#126-D2A: exact, side-effect-free #30 -> #31 relationship preview.

Do not persist this preview. The upcoming guarded #31 executor must reload the
current upstream selection and current reassessment policy, check the exact
immutable hashes/CAS witnesses, and separately reconcile partial #30/#31 writes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeAlias

from meridian.attempt_correction_interpretation import AttemptInterpretationPreview
from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_selection import (
    AttemptObservationReference,
    attempt_selection_decision_to_json_bytes,
)
from meridian.reassessment import (
    REASSESSMENT_DECISION_RECORD_TYPE,
    REASSESSMENT_DECISION_SCHEMA_VERSION,
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentCombination,
    ReassessmentDecision,
    ReassessmentMode,
    ReassessmentPolicyReference,
    ReassessmentValidationError,
    ReplacementRelationship,
    reassessment_decision_to_json_bytes,
)
from meridian.reassessment_storage import (
    StoredReassessmentDecision,
    StoredReassessmentPolicy,
)
from meridian.teacher_action_contract import TeacherActionActor


class AttemptReassessmentReviewError(ValueError):
    """The prospective relationship cannot be safely justified by exact facts."""

    code = "teacher_workflow.attempt_resolution.reassessment_review_invalid"


@dataclass(frozen=True, slots=True)
class ReviewedReassessmentChoice:
    """Explicit academic relationship, not a highest/latest numerical policy.

    Retain deliberately contributes all selected attempts. Replace removes
    *only* explicitly replaced attempts. Combine preserves contributors and
    needs explicit semantic groups. Recency is a teacher-provided exact order,
    not chronological inference; contributors are also explicitly supplied.
    """

    mode: ReassessmentMode
    replacements: tuple[ReplacementRelationship, ...] = ()
    combinations: tuple[ReassessmentCombination, ...] = ()
    recency_order: tuple[AttemptObservationReference, ...] = ()
    recency_contributors: tuple[AttemptObservationReference, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in {"retain", "replace", "combine", "recency"}:
            raise AttemptReassessmentReviewError("Unknown reassessment mode.")
        if (
            not isinstance(self.replacements, tuple)
            or any(
                not isinstance(item, ReplacementRelationship)
                for item in self.replacements
            )
            or not isinstance(self.combinations, tuple)
            or any(
                not isinstance(item, ReassessmentCombination)
                for item in self.combinations
            )
            or not isinstance(self.recency_order, tuple)
            or any(
                not isinstance(item, AttemptObservationReference)
                for item in self.recency_order
            )
            or not isinstance(self.recency_contributors, tuple)
            or any(
                not isinstance(item, AttemptObservationReference)
                for item in self.recency_contributors
            )
        ):
            raise AttemptReassessmentReviewError(
                "Relationship components must be exact typed tuples."
            )


ReviewExpectedCurrent: TypeAlias = tuple[int | None, str | None]


@dataclass(frozen=True, slots=True)
class ProspectiveReassessmentReview:
    """A proposed immutable #31 record bound to the *future* #30 digest.

    Neither record is current merely because a preview was created. The next
    implementation must first verify #30 was made current before using #31.
    """

    decision: ReassessmentDecision = field(repr=False)
    upstream_decision_sha256: str
    reassessment_decision_sha256: str
    policy_sha256: str
    expected_current_reassessment: ReviewExpectedCurrent
    history_before: tuple[int, ...]
    student_label: str
    teacher_treatment: str

    @property
    def may_execute_without_revalidation(self) -> bool:
        """No preview can grant write authority over mutable current pointers."""
        return False


def _validate_history(
    history: tuple[int, ...], current: StoredReassessmentDecision | None
) -> ReviewExpectedCurrent:
    if (
        not isinstance(history, tuple)
        or any(type(revision) is not int for revision in history)
        or history != tuple(range(1, len(history) + 1))
    ):
        raise AttemptReassessmentReviewError(
            "Reassessment revision history is not exact and contiguous."
        )
    if current is None:
        return (None, None)
    revision = current.decision.decision_revision
    if revision not in history:
        raise AttemptReassessmentReviewError(
            "Current reassessment pointer is absent from the reviewed history."
        )
    return (revision, current.decision_sha256)


def _contributors(
    selected: tuple[AttemptObservationReference, ...],
    choice: ReviewedReassessmentChoice,
) -> tuple[AttemptObservationReference, ...]:
    selected_set = set(selected)
    if choice.mode == "retain":
        if (
            choice.replacements
            or choice.combinations
            or choice.recency_order
            or choice.recency_contributors
        ):
            raise AttemptReassessmentReviewError(
                "Retain does not accept additional relationship structures."
            )
        return selected
    if choice.mode == "replace":
        if (
            not choice.replacements
            or choice.combinations
            or choice.recency_order
            or choice.recency_contributors
        ):
            raise AttemptReassessmentReviewError(
                "Replace needs explicit replacement relationships only."
            )
        related = tuple(
            attempt
            for relation in choice.replacements
            for attempt in (relation.replacement_attempt, *relation.replaced_attempts)
        )
        if any(attempt not in selected_set for attempt in related):
            raise AttemptReassessmentReviewError(
                "Replacement contains an attempt absent from exact #30 selection."
            )
        replaced = {
            attempt
            for relation in choice.replacements
            for attempt in relation.replaced_attempts
        }
        return tuple(attempt for attempt in selected if attempt not in replaced)
    if choice.mode == "combine":
        if (
            choice.replacements
            or not choice.combinations
            or choice.recency_order
            or choice.recency_contributors
        ):
            raise AttemptReassessmentReviewError(
                "Combine needs explicit combination groups only."
            )
        if any(
            member not in selected_set
            for group in choice.combinations
            for member in group.members
        ):
            raise AttemptReassessmentReviewError(
                "Combination contains an attempt absent from exact #30 selection."
            )
        return selected
    if choice.mode == "recency":
        if choice.replacements or choice.combinations:
            raise AttemptReassessmentReviewError(
                "Recency cannot also carry replacement or combination groups."
            )
        if (
            len(choice.recency_order) != len(selected)
            or len(set(choice.recency_order)) != len(selected)
            or set(choice.recency_order) != selected_set
            or not choice.recency_contributors
        ):
            raise AttemptReassessmentReviewError(
                "Recency requires an exact explicit order and contributors."
            )
        return choice.recency_contributors
    raise AttemptReassessmentReviewError("Unsupported explicit reassessment mode.")


def preview_reviewed_reassessment(
    *,
    interpretation: AttemptInterpretationPreview,
    authoring: AttemptDecisionAuthoringPreview,
    policy: StoredReassessmentPolicy,
    history: tuple[int, ...],
    current: StoredReassessmentDecision | None,
    choice: ReviewedReassessmentChoice,
    actor: TeacherActionActor,
    decided_at: datetime,
) -> ProspectiveReassessmentReview:
    """Pure contract: link an explicitly reviewed #31 mode to a planned #30.

    This uses *already loaded* canonical typed objects. The caller must not
    treat those objects as a current authority after the teacher review; both
    domains must be re-read and CAS-checked by the later execution service.
    """
    if not isinstance(interpretation, AttemptInterpretationPreview):
        raise AttemptReassessmentReviewError("Typed #126-C testimony required.")
    if not isinstance(authoring, AttemptDecisionAuthoringPreview):
        raise AttemptReassessmentReviewError("Exact #30 authoring preview required.")
    if not isinstance(policy, StoredReassessmentPolicy):
        raise AttemptReassessmentReviewError("Verified immutable #31 policy required.")
    if current is not None and not isinstance(current, StoredReassessmentDecision):
        raise AttemptReassessmentReviewError("Invalid current #31 decision witness.")
    if not isinstance(choice, ReviewedReassessmentChoice):
        raise AttemptReassessmentReviewError("Explicit typed relationship required.")
    if not isinstance(actor, TeacherActionActor):
        raise AttemptReassessmentReviewError("Verified teacher attribution required.")
    if (
        interpretation.treatment != "teacher_reviewed_reassessment"
        or not interpretation.needs_reassessment_decision
        or interpretation.original_attempt is not None
    ):
        raise AttemptReassessmentReviewError(
            "Only teacher-reviewed separate performances can use multiple attempts."
        )
    candidate = authoring.candidate
    selected = candidate.selected_attempts
    source = interpretation.source_snapshot
    if (
        len(selected) < 2
        or len(set(selected)) != len(selected)
        or selected != interpretation.intended_selected_attempts
        or source != candidate.source_snapshot
        or candidate.class_id != interpretation.class_id
        or candidate.grade_item_id != interpretation.grade_item_id
        or candidate.student_id != interpretation.student_id
        or candidate.work != source.work
        or candidate.actor.kind != "teacher"
        or candidate.actor.actor_id != actor.actor_id
        or candidate.rationale != interpretation.suggested_canonical_rationale
        or any(
            attempt.source_snapshot != source
            or attempt.student_id != candidate.student_id
            for attempt in selected
        )
    ):
        raise AttemptReassessmentReviewError(
            "Exact #30 selection/source/teacher testimony does not match review."
        )
    if (
        authoring.reviewed_current_decision_revision
        != interpretation.selected_revision_at_preview
    ):
        raise AttemptReassessmentReviewError(
            "#30 current-selection witness changed since teacher review."
        )
    if (
        policy.policy.class_id != candidate.class_id
        or policy.policy.grade_item_id != candidate.grade_item_id
        or policy.policy.work != candidate.work
        or choice.mode not in policy.policy.allowed_modes
    ):
        raise AttemptReassessmentReviewError(
            "The exact #31 policy is incompatible with the teacher's choice."
        )
    expected = _validate_history(history, current)
    if current is not None and (
        current.decision.class_id != candidate.class_id
        or current.decision.grade_item_id != candidate.grade_item_id
        or current.decision.work != candidate.work
        or current.decision.student_id != candidate.student_id
    ):
        raise AttemptReassessmentReviewError(
            "Current #31 pointer belongs to another academic student/scope."
        )
    try:
        contributors = _contributors(selected, choice)
        upstream_digest = hashlib.sha256(
            attempt_selection_decision_to_json_bytes(candidate)
        ).hexdigest()
        proposal = ReassessmentDecision(
            schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
            record_type=REASSESSMENT_DECISION_RECORD_TYPE,
            class_id=candidate.class_id,
            grade_item_id=candidate.grade_item_id,
            work=candidate.work,
            student_id=candidate.student_id,
            attempt_selection=AttemptSelectionDecisionReference(
                decision_revision=candidate.decision_revision,
                decision_sha256=upstream_digest,
            ),
            policy=ReassessmentPolicyReference(
                policy_id=policy.policy.policy_id,
                policy_revision=policy.policy.policy_revision,
                policy_revision_sha256=policy.policy_sha256,
            ),
            mode=choice.mode,
            contributing_attempts=contributors,
            replacement_relationships=choice.replacements,
            combinations=choice.combinations,
            recency_order=choice.recency_order,
            decision_revision=len(history) + 1,
            supersedes_revision=history[-1] if history else None,
            actor=ReassessmentActor(kind="teacher", actor_id=actor.actor_id),
            rationale=interpretation.suggested_canonical_rationale,
            decided_at=decided_at,
        )
        digest = hashlib.sha256(
            reassessment_decision_to_json_bytes(proposal)
        ).hexdigest()
    except (ReassessmentValidationError, ValueError) as error:
        raise AttemptReassessmentReviewError(
            "Explicit reassessment relationship is invalid."
        ) from error
    return ProspectiveReassessmentReview(
        decision=proposal,
        upstream_decision_sha256=upstream_digest,
        reassessment_decision_sha256=digest,
        policy_sha256=policy.policy_sha256,
        expected_current_reassessment=expected,
        history_before=history,
        student_label=interpretation.student_label,
        teacher_treatment=interpretation.treatment,
    )


def render_reviewed_reassessment(value: ProspectiveReassessmentReview) -> str:
    """No internal IDs or false claims of atomic cross-record execution."""
    if not isinstance(value, ProspectiveReassessmentReview):
        raise TypeError("Expected reviewed reassessment preview.")
    name = "".join(ch if ch.isprintable() else "?" for ch in value.student_label)
    decision = value.decision
    lines = [
        "Meridian — Review Multiple Attempts (NOT SAVED)",
        f"Student: {name}",
        "Source relationship: teacher-reviewed separate performances",
        f"Current-use decision: {len(decision.contributing_attempts)} contributors",
        f"Reassessment mode: {decision.mode}",
        "Both #30 selection and #31 relationship require exact current validation.",
        "No score is averaged and no higher/latest result is inferred.",
        "This preview DOES NOT save #30 or #31, change a Grade, or publish.",
        "Reassessment policies are selected independently, never implicitly.",
        "Cross-record execution is NOT atomic; interrupted actions require recovery.",
    ]
    return "\n".join(lines)


__all__ = (
    "AttemptReassessmentReviewError",
    "ProspectiveReassessmentReview",
    "ReviewedReassessmentChoice",
    "preview_reviewed_reassessment",
    "render_reviewed_reassessment",
)
