"""#124 E2G3N: one-confirmation teacher review of an already-bound setup.

This terminal controller never discovers work, prepares actions, writes a
journal, or selects canonical records itself. The trusted caller must bind the
D2 live composite and retain the original review; #124 durable correlation
and recovery still govern partial actions across process restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TextIO, TypeAlias

from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.menu_ui import InputFunction, print_menu_header, read_choice, write_lines
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


__all__ = ("TeacherAssessmentReviewOutcome", "review_assessment_setup_once")
