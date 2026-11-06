"""#125-D: one-confirmation coordinator over #122 canonical eligibility actions.

The only academic mutation is PreparedGuidedAction.apply(confirmed=True).
Every item delegates to the established author/select/receipt bridge; a batch
never owns a canonical eligibility record or promises cross-item atomicity.
Recovery from uncertain item outcomes belongs to #125-E, not blind replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from meridian.assessment_eligibility_plan import (
    AssessmentEligibilityPlanStaleError,
    BatchEligibilityPlanItem,
    BatchEligibilityReviewPlan,
    _classify_action,
    assert_batch_plan_review_current,
    capture_batch_pointer_witnesses,
)
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityReview,
    project_assessment_eligibility_review,
)
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityGradeItemChoice,
    load_guided_eligibility_context,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_action_contract import TeacherActionResult
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    bind_reviewed_actor,
    prepare_eligibility_action,
)

BatchOutcomeStatus = Literal[
    "applied",
    "already_applied",
    "blocked_before_write",
    "written_not_current",
    "current_unverified",
    "conflict_requires_review",
    "recovery_required",
    "unchanged",
    "deferred",
    "blocked",
    "not_attempted",
    "cancelled",
]

_SUCCESS = frozenset({"applied", "already_applied"})
_RESULTS = frozenset(
    {
        "applied",
        "already_applied",
        "blocked_before_write",
        "written_not_current",
        "current_unverified",
        "conflict_requires_review",
        "recovery_required",
        "unchanged",
        "deferred",
        "blocked",
        "not_attempted",
        "cancelled",
    }
)


class BatchEligibilityExecutionError(RuntimeError):
    """The plan or execution context cannot safely execute a batch."""

    code = "teacher_workflow.assessment_eligibility.execution_invalid"


@dataclass(frozen=True, slots=True)
class BatchEligibilityItemOutcome:
    """Truthful per-source result. An action_id is a receipt lookup, not truth."""

    source_item_id: str
    student_label: str
    evidence_label: str
    requested_disposition: str | None
    status: BatchOutcomeStatus
    reason: str | None = None
    action_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_item_id or self.status not in _RESULTS:
            raise BatchEligibilityExecutionError("Invalid exact item outcome.")
        if self.action_id is not None and (
            len(self.action_id) != 32
            or any(c not in "0123456789abcdef" for c in self.action_id)
        ):
            raise BatchEligibilityExecutionError("Invalid #122 action identity.")


@dataclass(frozen=True, slots=True)
class BatchEligibilityOutcome:
    """Complete ordered accounting; never an assessment-level eligibility flag."""

    plan_sha256: str
    confirmed: bool
    stopped: bool
    stop_reason: str | None
    items: tuple[BatchEligibilityItemOutcome, ...]

    def __post_init__(self) -> None:
        if len(self.plan_sha256) != 64 or not isinstance(self.items, tuple):
            raise BatchEligibilityExecutionError("Invalid batch outcome contract.")
        if self.stopped != (self.stop_reason is not None):
            raise BatchEligibilityExecutionError("Stop reason/accounting mismatch.")
        if len({item.source_item_id for item in self.items}) != len(self.items):
            raise BatchEligibilityExecutionError("Duplicate item outcome.")

    @property
    def counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (status, sum(item.status == status for item in self.items))
            for status in sorted(_RESULTS)
            if any(item.status == status for item in self.items)
        )

    @property
    def verified_current_count(self) -> int:
        return sum(item.status in _SUCCESS for item in self.items)


def _plan_digest(plan: BatchEligibilityReviewPlan) -> str:
    """Recompute the exact #125-C reviewed-intent digest; not authorization."""
    content = {
        "review": plan.roster_and_source_sha256,
        "actor": (
            plan.actor.actor_id,
            plan.actor.profile_sha256,
            plan.actor.source,
        ),
        "policy": (plan.policy.policy_id, plan.policy.policy_version),
        "membership_sha256": plan.membership_sha256,
        "items": [
            (
                item.source.item_id,
                item.witness.selected_revision,
                item.witness.selected_sha256,
                item.disposition,
                item.reason_codes,
                item.rationale,
                item.replace_existing,
                item.status,
            )
            for item in plan.items
        ],
    }
    encoded = json.dumps(
        content, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _check_plan(
    plan: BatchEligibilityReviewPlan, review: AssessmentEligibilityReview
) -> None:
    """Fail closed on forged state, stale roster, or modified intent."""
    if not isinstance(plan, BatchEligibilityReviewPlan):
        raise BatchEligibilityExecutionError("Expected an exact #125-C plan.")
    if _plan_digest(plan) != plan.plan_sha256:
        raise BatchEligibilityExecutionError("Plan intent changed after review.")
    assert_batch_plan_review_current(plan, review)
    if (
        plan.work != review.work
        or plan.grade_item_id != review.grade_item_id
        or plan.publication_id != review.publication_id
        or plan.cache_key != review.cache_key
        or plan.snapshot_digest != review.snapshot_digest
        or plan.membership_revision != review.membership_revision
        or plan.academic_period_id != review.academic_period_id
        or plan.academic_period_calendar_revision
        != review.academic_period_calendar_revision
        or review.source_status != "current"
        or review.membership_state != "included"
        or not plan.items
    ):
        raise AssessmentEligibilityPlanStaleError("Assessment basis is not current.")
    indexed = {
        x.source.item_id: (student.display_label, x)
        for student in review.students
        for x in student.items
    }
    indexed.update(
        (x.source.item_id, ("Unmatched or shared evidence", x))
        for x in (*review.shared_items, *review.unmatched_items)
    )
    if any(item.source.item_id not in indexed for item in plan.items):
        raise AssessmentEligibilityPlanStaleError(
            "Selected source is no longer in review."
        )
    for item in plan.items:
        label, canonical = indexed[item.source.item_id]
        status, status_reason = _classify_action(
            canonical, item.disposition, item.replace_existing, review
        )
        if (
            item.source != canonical.source
            or item.student_id != canonical.student_id
            or item.student_label != label
            or item.evidence_label != canonical.evidence_label
            or item.reviewed_eligibility_status != canonical.eligibility_status
            or item.reviewed_disposition != canonical.selected_eligibility_disposition
            or item.reviewed_operative_included != canonical.operative_included
            or item.witness.source != canonical.source
            or item.witness.membership_revision != plan.membership_revision
            or item.witness.membership_sha256 != plan.membership_sha256
            or item.witness.selected_revision != canonical.selected_eligibility_revision
            or (item.status, item.status_reason) != (status, status_reason)
        ):
            raise AssessmentEligibilityPlanStaleError(
                "Plan item no longer matches the exact reviewed status."
            )


def _base_outcome(item: BatchEligibilityPlanItem) -> BatchEligibilityItemOutcome:
    status: BatchOutcomeStatus = (
        "not_attempted" if item.status == "action" else item.status
    )
    return BatchEligibilityItemOutcome(
        item.source.item_id,
        item.student_label,
        item.evidence_label,
        item.disposition,
        status,
        item.status_reason,
    )


def _finalize(
    plan: BatchEligibilityReviewPlan,
    confirmed: bool,
    items: list[BatchEligibilityItemOutcome],
    stop_reason: str | None = None,
) -> BatchEligibilityOutcome:
    return BatchEligibilityOutcome(
        plan.plan_sha256,
        confirmed,
        stop_reason is not None,
        stop_reason,
        tuple(items),
    )


def execute_batch_eligibility_plan(
    workspace_root: str | Path,
    plan: BatchEligibilityReviewPlan,
    *,
    confirmed: bool,
    prepared: GuidedProjectionResult,
    grade_item: GuidedEligibilityGradeItemChoice,
    dependencies: GuidedEligibilityDependencies,
    before_apply: Callable[
        [BatchEligibilityReviewPlan, BatchEligibilityPlanItem, PreparedGuidedAction],
        None,
    ]
    | None = None,
) -> BatchEligibilityOutcome:
    """Execute one reviewed confirmation through the canonical #122 item bridge.

    The supplied GuidedProjectionResult MUST be freshly authorized for the
    exact current publication. This function does not grant or widen access.
    A failed/uncertain action halts later writes; #125-E provides exact restart.
    """
    if not isinstance(plan, BatchEligibilityReviewPlan):
        raise BatchEligibilityExecutionError("Invalid batch plan.")
    if type(confirmed) is not bool:
        raise BatchEligibilityExecutionError("Confirmation must be explicit boolean.")
    if not isinstance(plan.items, tuple):
        raise BatchEligibilityExecutionError("Invalid immutable selection.")
    if before_apply is not None and not callable(before_apply):
        raise BatchEligibilityExecutionError("Invalid pre-apply progress sealer.")
    rows = [_base_outcome(item) for item in plan.items]
    if not confirmed:
        rows = [
            BatchEligibilityItemOutcome(
                item.source.item_id,
                item.student_label,
                item.evidence_label,
                item.disposition,
                "cancelled" if item.status == "action" else item.status,
                (
                    "cancelled_before_apply"
                    if item.status == "action"
                    else item.status_reason
                ),
            )
            for item in plan.items
        ]
        return _finalize(plan, False, rows)
    if not isinstance(prepared, GuidedProjectionResult):
        raise BatchEligibilityExecutionError("Fresh authorized projection required.")
    if not isinstance(grade_item, GuidedEligibilityGradeItemChoice) or (
        grade_item.grade_item_id != plan.grade_item_id
    ):
        raise BatchEligibilityExecutionError("Exact reviewed Grade Item required.")
    if not isinstance(dependencies, GuidedEligibilityDependencies):
        raise BatchEligibilityExecutionError("Guided #122 dependencies required.")

    root = Path(workspace_root)
    try:
        if plan.policy not in dependencies.policies:
            raise BatchEligibilityExecutionError("Eligibility policy not qualified.")
        if (
            bind_reviewed_actor(
                plan.actor.actor_id,
                identity_source=plan.actor.source,
                profile_sha256=plan.actor.profile_sha256,
            )
            != plan.actor
        ):
            raise BatchEligibilityExecutionError("Actor attribution changed.")
        review = project_assessment_eligibility_review(
            root,
            grade_item_id=plan.grade_item_id,
            prepared=prepared,
            class_label=plan.class_label,
            assessment_title=plan.assessment_title,
        )
        _check_plan(plan, review)
        fresh_witnesses = capture_batch_pointer_witnesses(
            root,
            review,
            prepared.authorized,
            tuple(item.source.item_id for item in plan.items),
        )
        if {w.source.item_id: w for w in fresh_witnesses} != {
            item.source.item_id: item.witness for item in plan.items
        }:
            raise AssessmentEligibilityPlanStaleError("Selected pointers changed.")
    except Exception:
        # All work above is read-only; no new #122 receipts or academic writes.
        return _finalize(plan, True, rows, "batch_preflight_failed")

    for index, item in enumerate(plan.items):
        if item.status != "action":
            continue
        try:
            # Recheck the specific not-yet-written pointer immediately before
            # authoring. Earlier batch selections cannot change a distinct item.
            current = capture_batch_pointer_witnesses(
                root, review, prepared.authorized, (item.source.item_id,)
            )
            if current != (item.witness,):
                raise AssessmentEligibilityPlanStaleError("Current pointer drift.")
            context = load_guided_eligibility_context(
                root,
                prepared,
                grade_item,
                item_id=item.source.item_id,
                dependencies=dependencies,
            )
            if (
                context.row.source != item.source
                or context.row.selected_eligibility_revision
                != item.witness.selected_revision
                or context.row.eligibility_status != item.reviewed_eligibility_status
                or context.review.membership_revision != plan.membership_revision
                or context.review.academic_period_id != plan.academic_period_id
            ):
                raise AssessmentEligibilityPlanStaleError(
                    "Item changed before authoring."
                )
            if item.disposition is None:
                raise BatchEligibilityExecutionError("Unspecified action disposition.")
            preview = dependencies.authoring_previewer(
                root,
                context.review,
                prepared.authorized,
                item.source.item_id,
                item.disposition,
                plan.actor.actor_id,
                plan.policy.policy_id,
                plan.policy.policy_version,
                item.reason_codes,
                item.rationale,
                dependencies.clock(),
            )
            decision = preview.decision
            if (
                decision.source != item.source
                or decision.disposition != item.disposition
                or decision.actor.actor_id != plan.actor.actor_id
                or decision.actor.kind != "teacher"
                or decision.policy is None
                or decision.policy.policy_id != plan.policy.policy_id
                or decision.policy.policy_version != plan.policy.policy_version
                or decision.reason_codes != item.reason_codes
                or decision.rationale != item.rationale
                or preview.selected_revision != item.witness.selected_revision
            ):
                raise BatchEligibilityExecutionError(
                    "Authoring intent no longer matches."
                )
            action = prepare_eligibility_action(
                root, prepared, context, preview, plan.actor, dependencies
            )
        except Exception:
            rows[index] = BatchEligibilityItemOutcome(
                item.source.item_id,
                item.student_label,
                item.evidence_label,
                item.disposition,
                "blocked_before_write",
                "item_preflight_failed",
            )
            return _finalize(plan, True, rows, "item_preflight_failed")

        if before_apply is not None:
            try:
                before_apply(plan, item, action)
            except Exception:
                # No canonical apply has begun; a partial index is unsafe to
                # retry blindly, and later items must not be attempted.
                rows[index] = BatchEligibilityItemOutcome(
                    item.source.item_id,
                    item.student_label,
                    item.evidence_label,
                    item.disposition,
                    "blocked_before_write",
                    "progress_seal_failed",
                )
                return _finalize(plan, True, rows, "progress_seal_failed")
        try:
            outcome = action.apply(confirmed=True)
            if not isinstance(outcome, TeacherActionResult):
                raise BatchEligibilityExecutionError(
                    "#122 returned an invalid outcome."
                )
            if (
                outcome.action_id != action.preview.action_id
                or outcome.intent_sha256 != action.preview.intent_sha256
                or outcome.target != action.preview.target
            ):
                raise BatchEligibilityExecutionError(
                    "#122 outcome does not match the prepared exact action."
                )
            result_status: BatchOutcomeStatus = outcome.status
            rows[index] = BatchEligibilityItemOutcome(
                item.source.item_id,
                item.student_label,
                item.evidence_label,
                item.disposition,
                result_status,
                outcome.reason_code,
                outcome.action_id,
            )
            if outcome.status not in _SUCCESS:
                return _finalize(plan, True, rows, "item_not_verified_current")
        except Exception:
            # A raised failure during apply may follow a canonical write. It is
            # NEVER safe to label that operation as blocked-before-write.
            rows[index] = BatchEligibilityItemOutcome(
                item.source.item_id,
                item.student_label,
                item.evidence_label,
                item.disposition,
                "recovery_required",
                "item_apply_uncertain",
                action.preview.action_id,
            )
            return _finalize(plan, True, rows, "item_apply_uncertain")
    return _finalize(plan, True, rows)


def render_batch_execution_outcome(outcome: BatchEligibilityOutcome) -> str:
    """Teacher-facing accounting; no IDs, implicit grades, or false batch flag."""
    if not isinstance(outcome, BatchEligibilityOutcome):
        raise TypeError("Expected exact batch execution outcome.")
    lines = [
        "BATCH ELIGIBILITY — PER-ITEM CANONICAL OUTCOMES",
        "Confirmation: " + ("APPLY" if outcome.confirmed else "CANCEL"),
        "Stopped: " + (outcome.stop_reason or "No"),
        f"Verified current via #122: {outcome.verified_current_count}",
        "Outcome counts: "
        + ", ".join(f"{key} {value}" for key, value in outcome.counts),
        "A partial batch does not make an entire assessment eligible.",
    ]
    for item in outcome.items:
        lines.append(
            f"- {item.student_label} / {item.evidence_label}: "
            f"{item.status.replace('_', ' ')}"
        )
    if outcome.stopped:
        lines.append(
            "Do not blindly replay; review the exact incomplete/uncertain "
            "item via #122 recovery."
        )
    return "\n".join(lines)


__all__ = (
    "BatchEligibilityExecutionError",
    "BatchEligibilityItemOutcome",
    "BatchEligibilityOutcome",
    "BatchOutcomeStatus",
    "execute_batch_eligibility_plan",
    "render_batch_execution_outcome",
)
