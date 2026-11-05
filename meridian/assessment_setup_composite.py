"""#124 D1: one-confirmation coordinator for two existing #122 actions.

This is an *injected* composition boundary, not a new academic write engine.
Only #122 PreparedGuidedAction objects can persist/select canonical records.
No menu or live preparation adapter is wired in D1. Never replay a partial
result as a new create: #124 E must supply durable exact-step recovery.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, TypeAlias

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.teacher_action_contract import TeacherActionResult
from meridian.teacher_action_guided import PreparedGuidedAction

CompositeState: TypeAlias = Literal[
    "cancelled",
    "already_ready",
    "ready",
    "blocked_before_write",
    "conflict_requires_review",
    "grade_item_incomplete",
    "membership_incomplete",
    "current_unverified",
]


@dataclass(frozen=True, slots=True)
class AssessmentSetupCompositeResult:
    """Truthful stage outcomes, never a claim of multi-record atomicity."""

    state: CompositeState
    reason: str
    review_sha256: str
    grade_item_result: TeacherActionResult | None = None
    membership_result: TeacherActionResult | None = None

    @property
    def ready(self) -> bool:
        return self.state in ("already_ready", "ready")

    @property
    def action_ids(self) -> tuple[str, ...]:
        return tuple(
            item.action_id
            for item in (self.grade_item_result, self.membership_result)
            if item is not None
        )


FreshReview: TypeAlias = Callable[[], AssessmentSetupPreview]
CanonicalRead: TypeAlias = Callable[[], bool]
MembershipFactory: TypeAlias = Callable[[], PreparedGuidedAction]


@dataclass(slots=True)
class PreparedAssessmentSetupComposite:
    """A *one-shot* in-process reviewed sequence; not a durable retry handle.

    `fresh_review` must reload the full C1 context before any write.
    `after_grade_read` must independently validate reviewed source/actor/calendar
    witnesses after the first action, without requiring the now-changed Grade
    Item selection to equal its pre-create baseline.
    `verify_ready` must independently reload the canonical selected Grade Item,
    exact membership and registration/period; no action result implies ready.

    The D2 live binder is responsible for producing those *canonical* callbacks.
    No arbitrary writer or generic command executor is introduced here.
    """

    preview: AssessmentSetupPreview
    fresh_review: FreshReview
    after_grade_read: CanonicalRead
    verify_ready: CanonicalRead
    grade_item_action: PreparedGuidedAction | None = None
    membership_factory: MembershipFactory | None = None
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _used: bool = field(default=False, init=False, repr=False)

    def _result(
        self,
        state: CompositeState,
        reason: str,
        grade_item: TeacherActionResult | None = None,
        membership: TeacherActionResult | None = None,
    ) -> AssessmentSetupCompositeResult:
        return AssessmentSetupCompositeResult(
            state,
            reason,
            self.preview.review_sha256,
            grade_item,
            membership,
        )

    def _check_action(self, action: PreparedGuidedAction, kind: str) -> bool:
        """Reject retargeted #122 preparation before its academic write."""
        p = action.preview
        scope = p.scope
        return (
            p.kind == kind
            and p.target.family == kind
            and scope.class_id == self.preview.class_id
            and scope.grade_item_id == self.preview.grade_item_id
            and p.actor.actor_id == self.preview.actor_attribution
            and (
                kind != "grade_item_membership"
                or (
                    scope.school_year == self.preview.school_year
                    and scope.academic_period_id == self.preview.marking_period_id
                )
            )
        )

    def apply(self, *, confirmation: str) -> AssessmentSetupCompositeResult:
        """Execute only following one user APPLY; no second teacher prompt.

        Cancellation invokes *no* callbacks, receipts, files, or action ports.
        The one-shot guard prevents accidental in-process re-execution. On
        restart, a separate durable recovery path must inspect #122 receipts.
        """
        if confirmation != "APPLY":
            return self._result("cancelled", "not_confirmed")
        with self._lock:
            if self._used:
                return self._result(
                    "conflict_requires_review", "same_preview_already_attempted"
                )
            self._used = True
            return self._apply_once()

    def _apply_once(self) -> AssessmentSetupCompositeResult:
        try:
            current = self.fresh_review()
            if (
                current != self.preview
                or current.review_sha256 != self.preview.review_sha256
            ):
                return self._result("conflict_requires_review", "review_changed")
        except Exception:
            return self._result("blocked_before_write", "review_unavailable")
        kind = self.preview.kind
        if kind == "already_ready":
            if (
                self.grade_item_action is not None
                or self.membership_factory is not None
            ):
                return self._result("conflict_requires_review", "unexpected_action")
            try:
                verified = self.verify_ready()
            except Exception:
                verified = False
            return self._result(
                "already_ready" if verified else "current_unverified",
                "canonical_ready" if verified else "canonical_check_failed",
            )
        if (
            not self.preview.needs_confirmation
            or self.preview.actor_attribution is None
        ):
            return self._result("conflict_requires_review", "invalid_review")
        if self.membership_factory is None:
            return self._result("blocked_before_write", "membership_action_missing")
        grade_result: TeacherActionResult | None = None
        if kind == "create_and_link":
            action = self.grade_item_action
            if action is None or not self._check_action(action, "grade_item"):
                return self._result("blocked_before_write", "grade_action_mismatch")
            try:
                grade_result = action.apply(confirmed=True)
            except Exception:
                return self._result("grade_item_incomplete", "grade_action_unknown")
            if grade_result.status not in ("applied", "already_applied"):
                return self._result(
                    "grade_item_incomplete", "grade_action_not_current", grade_result
                )
        elif kind == "use_existing":
            if self.grade_item_action is not None:
                return self._result("blocked_before_write", "unexpected_grade_action")
        else:
            return self._result("blocked_before_write", "unsupported_plan")
        # The first #122 action may have changed Grade Item selection.
        # Do not call `fresh_review` here: it would reject intended progress.
        try:
            if not self.after_grade_read():
                return self._result(
                    "conflict_requires_review",
                    "post_grade_source_changed",
                    grade_result,
                )
            membership_action = self.membership_factory()
            if not self._check_action(membership_action, "grade_item_membership"):
                return self._result(
                    "conflict_requires_review",
                    "membership_action_mismatch",
                    grade_result,
                )
        except Exception:
            return self._result(
                "membership_incomplete", "membership_preparation_unknown", grade_result
            )
        try:
            membership_result = membership_action.apply(confirmed=True)
        except Exception:
            return self._result(
                "membership_incomplete", "membership_action_unknown", grade_result
            )
        if membership_result.status not in ("applied", "already_applied"):
            return self._result(
                "membership_incomplete",
                "membership_action_not_current",
                grade_result,
                membership_result,
            )
        try:
            verified = self.verify_ready()
        except Exception:
            verified = False
        return self._result(
            "ready" if verified else "current_unverified",
            "canonical_ready" if verified else "canonical_check_failed",
            grade_result,
            membership_result,
        )


__all__ = (
    "AssessmentSetupCompositeResult",
    "CompositeState",
    "PreparedAssessmentSetupComposite",
)
