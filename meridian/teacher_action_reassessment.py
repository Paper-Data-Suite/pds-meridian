"""#126-D2B1: canonical #31 Save/Select through #122's guarded action journal.

This is a single *reassessment* action, not an atomic #30/#31 transaction.
The exact #30 decision must already be current. Repeated or interrupted
operations must go through the bound #122 recovery path, never reauthor blindly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_selection_storage import (
    AttemptSelectionResolution,
    resolve_current_attempt_selection,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
    validate_grade_item_membership_dependencies,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.reassessment import reassessment_decision_to_json_bytes
from meridian.reassessment_storage import (
    ReassessmentResolution,
    list_reassessment_decision_revisions,
    load_current_reassessment_decision,
    load_current_reassessment_policy,
    load_reassessment_decision_revision,
    resolve_current_reassessment,
    select_reassessment_decision_revision,
    write_reassessment_decision_revision,
)
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
    TeacherActionResult,
)
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    _actor_now,
    _calendar_digest,
    _GuidedPort,
    _identity,
    _prepare,
    _root,
)
from meridian.teacher_action_orchestration import TeacherActionConflictError


class ReassessmentActionError(ValueError):
    """Reviewed or currently operative #31 basis is not demonstrably exact."""

    code = "teacher_workflow.attempt_resolution.reassessment_action_invalid"


ReassessmentActionStatus: TypeAlias = Literal[
    "canceled_before_write",
    "blocked_before_write",
    "conflict_requires_review",
    "written_not_current",
    "current_unverified",
    "recovery_required",
    "applied_current",
    "already_current",
]


@dataclass(frozen=True, slots=True)
class ReassessmentActionOutcome:
    """Independent readback outcome, never a receipt-derived grade authority."""

    status: ReassessmentActionStatus
    canonical_status: str | None
    exact_current: bool
    reason: str | None = None


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _upstream_current(
    root: Path,
    prepared: GuidedProjectionResult,
    review: ProspectiveReassessmentReview,
) -> AttemptSelectionResolution:
    """Verify #30 source AND immutable selected digest via canonical resolver."""
    decision = review.decision
    selection = resolve_current_attempt_selection(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
        authorized_snapshot=prepared.authorized,
    )
    if (
        selection.status != "selected"
        or not selection.operative_selection
        or selection.selected is None
        or selection.selected.decision.decision_revision
        != decision.attempt_selection.decision_revision
        or selection.selected.decision_sha256 != review.upstream_decision_sha256
        or selection.selected.decision.selected_attempts == ()
        or len(selection.selected.decision.selected_attempts) < 2
        or selection.selected.decision.source_snapshot.work != decision.work
    ):
        raise ReassessmentActionError(
            "Exact reviewed #30 decision is not operative current; #31 is blocked."
        )
    return selection


def _check_review(
    root: Path,
    prepared: GuidedProjectionResult,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
) -> tuple[str, int | None, str | None]:
    """Read fresh policy, history, selected #31, and upstream #30; never write."""
    if not isinstance(review, ProspectiveReassessmentReview):
        raise ReassessmentActionError("Exact D2A reviewed decision is required.")
    if not isinstance(actor, TeacherActionActor):
        raise ReassessmentActionError("Canonical #121 teacher attribution required.")
    decision = review.decision
    if not prepared.authorized.assessment.reusable_for_current_use:
        raise ReassessmentActionError(
            "Authorized projection is not reusable for current academic use."
        )
    publication = prepared.authorized.current_context.publication
    if (
        publication.work != decision.work
        or publication.publication_id
        != prepared.authorized.stored.snapshot.source.publication.publication_id
        or decision.class_id != publication.work.class_id
        or decision.actor.kind != "teacher"
        or decision.actor.actor_id != actor.actor_id
        or decision.attempt_selection.decision_sha256 != review.upstream_decision_sha256
        or _digest(reassessment_decision_to_json_bytes(decision))
        != review.reassessment_decision_sha256
    ):
        raise ReassessmentActionError(
            "Teacher, source, or immutable reassessment digest differs."
        )
    _upstream_current(root, prepared, review)
    current_policy = load_current_reassessment_policy(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.policy.policy_id,
    )
    if (
        current_policy is None
        or current_policy.policy_sha256 != review.policy_sha256
        or current_policy.policy_sha256 != decision.policy.policy_revision_sha256
        or current_policy.policy.policy_revision != decision.policy.policy_revision
        or decision.mode not in current_policy.policy.allowed_modes
    ):
        raise ReassessmentActionError(
            "A separate exact current #31 policy must be selected first."
        )
    history = list_reassessment_decision_revisions(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
    )
    if history not in (
        review.history_before,
        (*review.history_before, decision.decision_revision),
    ):
        raise ReassessmentActionError("Reassessment decision history changed.")
    if history and decision.decision_revision in history:
        persisted = load_reassessment_decision_revision(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
            decision.decision_revision,
        )
        if persisted.decision_sha256 != review.reassessment_decision_sha256:
            raise ReassessmentActionError("Immutable target content differs.")
    current = load_current_reassessment_decision(
        root,
        decision.class_id,
        decision.grade_item_id,
        decision.work,
        decision.student_id,
    )
    revision, digest = (
        (None, None)
        if current is None
        else (current.decision.decision_revision, current.decision_sha256)
    )
    if (revision, digest) not in (
        review.expected_current_reassessment,
        (decision.decision_revision, review.reassessment_decision_sha256),
    ):
        raise ReassessmentActionError("Current #31 pointer changed since review.")
    return (current_policy.policy_sha256, revision, digest)


def prepare_reviewed_reassessment_action(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    review: ProspectiveReassessmentReview,
    actor: TeacherActionActor,
) -> PreparedGuidedAction:
    """Bind a D2A #31 proposal to one #122 journal/immutable writer/CAS selector.

    Must be called only after the matching #30 action independently reaches
    operative current. Does not silently set up #31 policy or any Grade.
    """
    root = _root(root)
    if not isinstance(prepared, GuidedProjectionResult):
        raise ReassessmentActionError("Authorized projection required.")
    if not isinstance(review, ProspectiveReassessmentReview):
        raise ReassessmentActionError("Reviewed D2A proposal required.")
    if not isinstance(actor, TeacherActionActor):
        raise ReassessmentActionError("Verified teacher actor required.")
    decision = review.decision
    if review.teacher_treatment != "teacher_reviewed_reassessment":
        raise ReassessmentActionError("Review must represent separate performances.")
    try:
        _actor_now(actor)
        _check_review(root, prepared, review, actor)
        membership = load_current_grade_item_membership_decision(
            root, decision.class_id, decision.grade_item_id, decision.work
        )
        upstream = _upstream_current(root, prepared, review)
        if (
            membership is None
            or membership.decision.decision != "included"
            or membership.decision.academic_period is None
            or upstream.selected is None
            or membership.decision.membership_revision
            != upstream.selected.decision.membership_revision
            or membership.decision_sha256
            != upstream.selected.decision.membership_revision_sha256
        ):
            raise ReassessmentActionError("Current #30 membership is not included.")
        validate_grade_item_membership_dependencies(root, membership.decision)
        assignment = membership.decision.academic_period
        assert assignment is not None
        period = assignment.period
        calendar_sha = _calendar_digest(
            root, period.school_year, assignment.calendar_revision
        )
    except Exception as error:
        raise ReassessmentActionError(
            "Cannot prepare #31 against current #30, roster, policy or period."
        ) from error

    prior_rev, prior_sha = review.expected_current_reassessment

    def validate() -> None:
        _actor_now(actor)
        try:
            _check_review(root, prepared, review, actor)
            validate_grade_item_membership_dependencies(root, membership.decision)
            active = load_current_grade_item_membership_decision(
                root, decision.class_id, decision.grade_item_id, decision.work
            )
            if active is None or active.decision_sha256 != membership.decision_sha256:
                raise ReassessmentActionError("Included membership changed.")
            if (
                _calendar_digest(root, period.school_year, assignment.calendar_revision)
                != calendar_sha
            ):
                raise ReassessmentActionError("Academic calendar changed.")
        except Exception as error:
            raise TeacherActionConflictError(
                "#31 exact current dependencies changed."
            ) from error

    def read() -> tuple[
        str | None, int | None, str | None, Literal["current", "stale"]
    ]:
        history = list_reassessment_decision_revisions(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
        )
        target = (
            load_reassessment_decision_revision(
                root,
                decision.class_id,
                decision.grade_item_id,
                decision.work,
                decision.student_id,
                decision.decision_revision,
            )
            if decision.decision_revision in history
            else None
        )
        current = load_current_reassessment_decision(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
        )
        try:
            validate()
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if target is None else target.decision_sha256,
            None if current is None else current.decision.decision_revision,
            None if current is None else current.decision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = write_reassessment_decision_revision(
            root, decision, authorized_snapshot=prepared.authorized
        )
        if result.stored.decision_sha256 != review.reassessment_decision_sha256:
            raise TeacherActionConflictError("#31 writer returned another digest.")
        if result.disposition not in {"created", "existing"}:
            raise TeacherActionConflictError("Unknown #31 write disposition.")
        return result.disposition

    def select() -> SelectionDisposition:
        result = select_reassessment_decision_revision(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
            decision.decision_revision,
            authorized_snapshot=prepared.authorized,
            expected_current_decision_revision=prior_rev,
        )
        if result.stored.decision_sha256 != review.reassessment_decision_sha256:
            raise TeacherActionConflictError("#31 CAS selected another revision.")
        disposition = result.disposition
        if disposition not in {"created", "updated", "existing"}:
            raise TeacherActionConflictError("Unknown #31 selector disposition.")
        return disposition

    kind: ActionKind = "reassessment_decision"
    return _prepare(
        root=root,
        class_id=decision.class_id,
        grade_item_id=decision.grade_item_id,
        actor=actor,
        kind=kind,
        revision=decision.decision_revision,
        candidate_sha256=review.reassessment_decision_sha256,
        current_revision=prior_rev,
        current_sha256=prior_sha,
        identity=_identity(
            "reassessment_decision",
            decision.class_id,
            decision.grade_item_id,
            decision.work.module_id,
            decision.work.work_id,
            decision.student_id,
        ),
        source_binding=_identity(
            "reassessment_source",
            decision.attempt_selection.decision_sha256,
            review.policy_sha256,
            decision.work.module_id,
            decision.work.work_id,
        ),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity(
            "work", decision.class_id, decision.work.module_id, decision.work.work_id
        ),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


def observe_reviewed_reassessment_action(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    review: ProspectiveReassessmentReview,
    result: TeacherActionResult,
) -> ReassessmentActionOutcome:
    """Never claim success from a journal entry without canonical #31 readback."""
    if not isinstance(result, TeacherActionResult):
        raise ReassessmentActionError("#122 typed action outcome required.")
    if result.status not in {"applied", "already_applied"}:
        label: ReassessmentActionStatus
        if result.status == "blocked_before_write":
            label = "blocked_before_write"
        elif result.status == "conflict_requires_review":
            label = "conflict_requires_review"
        elif result.status == "written_not_current":
            label = "written_not_current"
        elif result.status == "current_unverified":
            label = "current_unverified"
        else:
            label = "recovery_required"
        return ReassessmentActionOutcome(label, None, False, result.reason_code)
    if (
        result.current_state != "matches"
        or result.current_record is None
        or result.current_record.sha256 != review.reassessment_decision_sha256
        or result.current_record.revision != review.decision.decision_revision
    ):
        return ReassessmentActionOutcome(
            "current_unverified", None, False, "#122_target_not_verified"
        )
    try:
        decision = review.decision
        canonical: ReassessmentResolution = resolve_current_reassessment(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.work,
            decision.student_id,
            authorized_snapshot=prepared.authorized,
        )
        exact = (
            canonical.status == "resolved"
            and canonical.operative_reassessment
            and canonical.selected is not None
            and canonical.selected.decision.decision_revision
            == decision.decision_revision
            and canonical.selected.decision_sha256
            == review.reassessment_decision_sha256
            and canonical.selected.decision.attempt_selection
            == decision.attempt_selection
            and canonical.contributing_attempts == decision.contributing_attempts
            and canonical.replacement_relationships
            == decision.replacement_relationships
            and canonical.combinations == decision.combinations
            and canonical.recency_order == decision.recency_order
        )
    except Exception:
        return ReassessmentActionOutcome(
            "current_unverified", None, False, "canonical_readback_unavailable"
        )
    if not exact:
        return ReassessmentActionOutcome(
            "current_unverified",
            canonical.status,
            False,
            "canonical_reassessment_does_not_match_review",
        )
    return ReassessmentActionOutcome(
        "already_current" if result.status == "already_applied" else "applied_current",
        canonical.status,
        True,
    )


__all__ = (
    "ReassessmentActionError",
    "ReassessmentActionOutcome",
    "observe_reviewed_reassessment_action",
    "prepare_reviewed_reassessment_action",
)
