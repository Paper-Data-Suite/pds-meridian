"""#124 E2G3N: one-confirmation teacher review of an already-bound setup.

This terminal controller never discovers work, prepares actions, writes a
journal, or selects canonical records itself. The trusted caller must bind the
D2 live composite and retain the original review; #124 durable correlation
and recovery still govern partial actions across process restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO, TypeAlias

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_correlated_live import (
    bind_correlated_live_assessment_setup,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu_ui import InputFunction, print_menu_header, read_choice, write_lines
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_session import TeacherSessionContext

ReviewStatus: TypeAlias = Literal[
    "cancelled", "ready", "already_ready", "requires_review"
]


@dataclass(frozen=True, slots=True)
class TeacherAssessmentReviewOutcome:
    """Presentation result; never a durable receipt or replay authority."""

    status: ReviewStatus
    reason: str
    action_ids: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status in ("ready", "already_ready")


def _session_matches(
    session: TeacherSessionContext, review: AssessmentSetupPreview
) -> bool:
    """Refuse conflicting navigation rather than overwriting another selection."""
    return (
        session.active_class_id == review.class_id
        and review.work.class_id == review.class_id
        and (session.active_work is None or session.active_work == review.work)
        and (
            session.active_grade_item_id is None
            or session.active_grade_item_id == review.grade_item_id
        )
        and (
            session.active_publication_id is None
            or session.active_publication_id == review.publication_id
        )
    )


def review_assessment_setup_once(
    prepared: PreparedAssessmentSetupComposite,
    session: TeacherSessionContext,
    *,
    input_fn: InputFunction,
    output: TextIO,
) -> TeacherAssessmentReviewOutcome:
    """Present one reviewed plan, request one APPLY, then report canonical truth.

    A verified no-op needs no confirmation. A changed review, partial write,
    exception or conflicting teacher-session selection never mutates the session.
    The caller must not retry an unknown academic outcome with a new composite.
    """
    if (
        not isinstance(prepared, PreparedAssessmentSetupComposite)
        or not isinstance(session, TeacherSessionContext)
        or not isinstance(prepared.preview, AssessmentSetupPreview)
    ):
        write_lines(output, "Assessment setup review is unavailable.")
        return TeacherAssessmentReviewOutcome(
            "requires_review", "invalid_review_context"
        )

    review = prepared.preview
    if not _session_matches(session, review):
        write_lines(
            output,
            "Assessment selection differs from the active teacher session.",
            "Choose the correct class and assessment before reviewing setup.",
        )
        return TeacherAssessmentReviewOutcome(
            "requires_review", "session_scope_changed"
        )

    print_menu_header(output, "Review Assessment Setup")
    write_lines(
        output,
        f"Assessment: {review.assessment_title}",
        f"Producer: {review.producer_label}",
        f"Class: {review.class_id}",
        f"Publication: {review.publication_label}",
        f"Grade Item: {review.grade_item_title}",
        f"Purpose: {review.grade_item_purpose.replace('_', ' ')}",
        f"Academic period: {review.marking_period_label}",
        f"Weighting: {review.weighting_message}",
        "",
    )
    if review.kind == "already_ready":
        write_lines(
            output,
            "Already configured: verify the current relationship without a write.",
        )
    else:
        write_lines(
            output,
            "One APPLY approves the entire reviewed setup.",
            "Underlying Grade Item and membership actions remain "
            "separate canonical operations.",
            "Neither evidence authorization nor Grade policy activation is included.",
            "Type APPLY to confirm; any other input cancels.",
        )
        if read_choice(input_fn, "Confirmation: ") != "APPLY":
            write_lines(output, "Cancelled. No setup action requested.")
            return TeacherAssessmentReviewOutcome("cancelled", "not_confirmed")

    try:
        result = prepared.apply(confirmation="APPLY")
    except Exception:
        write_lines(
            output,
            "Assessment setup outcome could not be verified.",
            "Review canonical state and original receipts; do not retry Save.",
        )
        return TeacherAssessmentReviewOutcome(
            "requires_review", "execution_outcome_unknown"
        )

    if (
        result.review_sha256 != review.review_sha256
        or not result.ready
        or (review.kind == "already_ready") != (result.state == "already_ready")
    ):
        write_lines(
            output,
            "Assessment setup is not verified ready.",
            f"Current disposition: {result.state}",
            "Review canonical state and original receipts before any new action.",
        )
        return TeacherAssessmentReviewOutcome(
            "requires_review", result.reason, result.action_ids
        )

    # Only a verified, matching composite may advance process-local navigation.
    # All foreseeable session conflicts were checked before APPLY.
    session.select_work(review.work)
    if review.publication_id is not None:
        session.select_publication(review.publication_id)
    session.select_grade_item(review.grade_item_id)
    write_lines(
        output,
        "Assessment relationship verified current.",
        "Return to Grade Items or evidence with this assessment selected.",
    )
    verified_status: ReviewStatus = (
        "already_ready" if result.state == "already_ready" else "ready"
    )
    return TeacherAssessmentReviewOutcome(
        verified_status, result.reason, result.action_ids
    )


def review_correlated_assessment_setup_once(
    workspace_root: Path,
    reviewed: AssessmentSetupPreview,
    session: TeacherSessionContext,
    *,
    actor: TeacherActionActor | None,
    dependencies: GuidedGradeItemBridgeDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> TeacherAssessmentReviewOutcome:
    """Enter the one-APPLY workflow only through E2C durable action fences.

    This is a trusted, reviewed-context boundary, not discovery or menu
    routing. Existing correlations are evidence of a prior attempt, never
    permission to prepare fresh #122 action IDs or repeat an academic write.
    """

    def unavailable(reason: str, *message: str) -> TeacherAssessmentReviewOutcome:
        write_lines(output, *message)
        return TeacherAssessmentReviewOutcome("requires_review", reason)

    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not workspace_root.is_dir()
        or not isinstance(reviewed, AssessmentSetupPreview)
        or not isinstance(session, TeacherSessionContext)
        or not isinstance(dependencies, GuidedGradeItemBridgeDependencies)
    ):
        return unavailable(
            "invalid_correlated_context",
            "Assessment setup context cannot be verified safely.",
        )
    if not _session_matches(session, reviewed):
        return unavailable(
            "session_scope_changed",
            "Selected assessment differs from the teacher session.",
            "Reopen the assessment review before applying a change.",
        )
    if reviewed.kind == "already_ready":
        if actor is not None:
            return unavailable(
                "unexpected_actor_for_ready_review",
                "Already-ready review must be verified without an action actor.",
            )
    elif (
        not isinstance(actor, TeacherActionActor)
        or actor.source != "saved"
        or actor.actor_id != reviewed.actor_attribution
    ):
        return unavailable(
            "saved_actor_required",
            "A current saved teacher attribution is required for setup.",
        )

    # This read-only preflight prevents a known interrupted action from being
    # shown as a fresh one-confirmation setup. E2C independently repeats the
    # collision check under the correlation store lock just before its write.
    if reviewed.kind != "already_ready":
        try:
            existing = AssessmentSetupCorrelationStore(
                workspace_root, reviewed.class_id
            ).list_records()
            if any(
                item.grade_item_id == reviewed.grade_item_id
                or (item.module_id, item.work_id)
                == (reviewed.work.module_id, reviewed.work.work_id)
                for item in existing
            ):
                return unavailable(
                    "prior_correlated_action_requires_recovery",
                    "A prior assessment setup is already recorded.",
                    "Use Review Interrupted Saves; do not repeat APPLY.",
                )
        except Exception:
            return unavailable(
                "correlation_inventory_unavailable",
                "Original setup correlation cannot be inspected safely.",
                "No new setup action was requested.",
            )
    try:
        prepared = bind_correlated_live_assessment_setup(
            workspace_root,
            reviewed,
            actor=actor,
            dependencies=dependencies,
        )
    except Exception:
        return unavailable(
            "correlated_binding_unavailable",
            "Canonical setup binding could not be verified safely.",
            "Review the original receipts before attempting another setup.",
        )
    return review_assessment_setup_once(
        prepared,
        session,
        input_fn=input_fn,
        output=output,
    )


__all__ = (
    "TeacherAssessmentReviewOutcome",
    "review_assessment_setup_once",
    "review_correlated_assessment_setup_once",
)
