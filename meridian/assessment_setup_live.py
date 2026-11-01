"""#124 D2: bind a reviewed setup to canonical #122 prepare/apply actions.

This is deliberately not a CLI entry point. The prepared composite is one-shot;
partial outcomes require #124 E durable recovery, never a new create attempt.
No evidence manifest or producer/student record is opened here.
"""

from __future__ import annotations

from pathlib import Path

from meridian.assessment_setup_choices import load_named_assessment_choices
from meridian.assessment_setup_composite import PreparedAssessmentSetupComposite
from meridian.assessment_setup_preview import (
    AssessmentSetupPreview,
    load_assessment_setup_preview,
)
from meridian.guided_grade_items import (
    GuidedAcademicPeriodChoice,
    GuidedGradeItemBridgeContext,
    GuidedGradeItemBridgeDependencies,
    GuidedGradeItemChoice,
    load_guided_grade_item_bridge_context,
    preview_membership_link,
    preview_new_grade_item,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import (
    PreparedGuidedAction,
    prepare_grade_item_action,
    prepare_membership_action,
)


class AssessmentSetupLiveError(RuntimeError):
    """Live canonical source or exact reviewed action could not be bound."""


def bind_live_assessment_setup(
    workspace_root: str | Path,
    preview: AssessmentSetupPreview,
    *,
    actor: TeacherActionActor | None,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> PreparedAssessmentSetupComposite:
    """Bind *existing* authoritative workflows; never execute during binding.

    The returned object can receive exactly one teacher APPLY. A failure after
    a write is NOT safe to retry with another newly bound object: consult #122
    receipts and the forthcoming #124 E composite-recovery contract instead.
    """
    root = Path(workspace_root).resolve()
    if not root.is_dir() or not isinstance(preview, AssessmentSetupPreview):
        raise AssessmentSetupLiveError("Reviewed setup/workspace is unavailable.")
    if not isinstance(dependencies, GuidedGradeItemBridgeDependencies):
        raise AssessmentSetupLiveError("Canonical guided dependencies are required.")
    if preview.kind == "already_ready":
        if actor is not None or preview.actor_attribution is not None:
            raise AssessmentSetupLiveError("Already-ready setup cannot bind an actor.")
    elif (
        actor is None
        or not isinstance(actor, TeacherActionActor)
        or actor.actor_id != preview.actor_attribution
    ):
        raise AssessmentSetupLiveError("Teacher actor differs from the reviewed setup.")

    def fresh_preview() -> AssessmentSetupPreview:
        current = load_assessment_setup_preview(
            root,
            class_id=preview.class_id,
            school_year=preview.school_year,
            period_id=preview.marking_period_id,
            work=preview.work,
            dependencies=dependencies,
            purpose=(
                None if preview.kind == "already_ready" else preview.grade_item_purpose
            ),
            existing_grade_item_id=(
                preview.grade_item_id if preview.kind == "use_existing" else None
            ),
            new_title=(
                preview.grade_item_title if preview.kind == "create_and_link" else None
            ),
            actor_attribution=preview.actor_attribution,
            rationale=preview.rationale,
        )
        return current

    def live_state() -> tuple[
        GuidedGradeItemBridgeContext,
        GuidedGradeItemChoice,
        GuidedAcademicPeriodChoice,
        str,
    ]:
        """Independently reread registration, publication history and selected item."""
        named = load_named_assessment_choices(
            root,
            class_id=preview.class_id,
            school_year=preview.school_year,
            period_id=preview.marking_period_id,
        )
        matches = tuple(
            item for item in named.items if item.candidate.work == preview.work
        )
        if len(matches) != 1:
            raise AssessmentSetupLiveError("Reviewed assessment identity disappeared.")
        item = matches[0]
        registration = item.candidate
        if (
            registration.school_year != preview.school_year
            or registration.registration_revision != preview.registration_revision
            or registration.lifecycle != preview.registration_lifecycle
            or registration.title != preview.assessment_title
            or registration.period_id != preview.marking_period_id
            or registration.calendar_revision != preview.calendar_revision
            or registration.publication_id != preview.publication_id
        ):
            raise AssessmentSetupLiveError(
                "Registration, period or publication changed."
            )
        if (
            preview.publication_id is None
            and item.publication_state != "no_results_indexed"
        ) or (
            preview.publication_id is not None
            and item.publication_state != "current_results_verified"
        ):
            raise AssessmentSetupLiveError("Publication status changed.")
        bridge = load_guided_grade_item_bridge_context(
            root, preview.work, dependencies=dependencies
        )
        if (
            bridge.work != preview.work
            or bridge.work_title != preview.assessment_title
            or bridge.registration_revision != preview.registration_revision
        ):
            raise AssessmentSetupLiveError("Canonical registration bridge changed.")
        periods = tuple(
            p
            for p in bridge.periods
            if p.period_type == "marking_period"
            and p.assignment.period.school_year == preview.school_year
            and p.assignment.period.period_id == preview.marking_period_id
            and p.assignment.calendar_revision == preview.calendar_revision
            and p.display_label == preview.marking_period_label
        )
        grades = tuple(
            g
            for g in bridge.existing_grade_items
            if g.grade_item_id == preview.grade_item_id
            and g.title == preview.grade_item_title
            and g.purpose == preview.grade_item_purpose
        )
        if len(periods) != 1 or len(grades) != 1:
            raise AssessmentSetupLiveError("Selected Grade Item or calendar changed.")
        selected = grades[0]
        if (
            preview.kind != "create_and_link"
            and selected.selected_revision != preview.selected_grade_item_revision
        ):
            raise AssessmentSetupLiveError("Existing Grade Item revision changed.")
        return bridge, selected, periods[0], registration.setup_state

    def after_grade_read() -> bool:
        try:
            _, grade, _, _ = live_state()
            if preview.kind == "create_and_link":
                return grade.selected_revision == new_grade_revision
            return grade.selected_revision == preview.selected_grade_item_revision
        except Exception:
            return False

    def verify_ready() -> bool:
        try:
            _, grade, _, state = live_state()
            if state != "ready":
                return False
            if preview.kind == "create_and_link":
                return grade.selected_revision == new_grade_revision
            return grade.selected_revision == preview.selected_grade_item_revision
        except Exception:
            return False

    try:
        current = fresh_preview()
        if current != preview or current.review_sha256 != preview.review_sha256:
            raise AssessmentSetupLiveError("Source changed before action binding.")
        grade_action: PreparedGuidedAction | None = None
        new_grade_revision: int | None = None
        if preview.kind == "create_and_link":
            assert actor is not None
            initial_context = load_guided_grade_item_bridge_context(
                root, preview.work, dependencies=dependencies
            )
            if initial_context.work != preview.work or (
                initial_context.registration_revision != preview.registration_revision
            ):
                raise AssessmentSetupLiveError(
                    "Registration changed during preparation."
                )
            grade_authoring = preview_new_grade_item(
                root,
                initial_context,
                title=preview.grade_item_title,
                purpose=preview.grade_item_purpose,
                teacher_attribution=actor.actor_id,
                dependencies=dependencies,
            )
            candidate = grade_authoring.candidate
            if (
                candidate.class_id != preview.class_id
                or candidate.grade_item_id != preview.grade_item_id
                or candidate.title != preview.grade_item_title
                or candidate.purpose != preview.grade_item_purpose
                or candidate.status != "active"
                or candidate.grade_item_revision != 1
                or grade_authoring.actor_id != actor.actor_id
            ):
                raise AssessmentSetupLiveError("New Grade Item preview was retargeted.")
            new_grade_revision = candidate.grade_item_revision
            grade_action = prepare_grade_item_action(
                root, grade_authoring, actor, dependencies
            )
        elif preview.kind not in ("use_existing", "already_ready"):
            raise AssessmentSetupLiveError("Unsupported reviewed setup plan.")

        def make_membership() -> PreparedGuidedAction:
            if actor is None:
                raise AssessmentSetupLiveError("Membership cannot be anonymous.")
            context, grade, period, _ = live_state()
            if preview.kind == "create_and_link":
                if grade.selected_revision != new_grade_revision:
                    raise AssessmentSetupLiveError("Created Grade Item is not current.")
            elif grade.selected_revision != preview.selected_grade_item_revision:
                raise AssessmentSetupLiveError("Existing Grade Item selection changed.")
            authoring = preview_membership_link(
                root,
                context,
                grade,
                period,
                teacher_attribution=actor.actor_id,
                rationale=preview.rationale,
                dependencies=dependencies,
            )
            proposed = authoring.candidate
            if (
                proposed.class_id != preview.class_id
                or proposed.grade_item_id != preview.grade_item_id
                or proposed.grade_item_revision != grade.selected_revision
                or proposed.work_reference.registration_revision
                != preview.registration_revision
                or proposed.work_reference.work != preview.work
                or proposed.decision != "included"
                or proposed.actor_id != actor.actor_id
                or proposed.academic_period != period.assignment
            ):
                raise AssessmentSetupLiveError("Membership authoring was retargeted.")
            return prepare_membership_action(root, authoring, actor, dependencies)

        return PreparedAssessmentSetupComposite(
            preview=preview,
            fresh_review=fresh_preview,
            after_grade_read=after_grade_read,
            verify_ready=verify_ready,
            grade_item_action=grade_action,
            membership_factory=(
                None if preview.kind == "already_ready" else make_membership
            ),
        )
    except AssessmentSetupLiveError:
        raise
    except Exception as error:
        raise AssessmentSetupLiveError(
            "Canonical setup action could not be bound; refresh before retry."
        ) from error


__all__ = ("AssessmentSetupLiveError", "bind_live_assessment_setup")
