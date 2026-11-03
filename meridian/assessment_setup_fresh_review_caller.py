"""#124 E2G3D: explicitly chosen fresh context for guarded restart review.

The caller cannot infer teacher choices from a receipt. This port requires
freshly supplied choices, and E2G3B still owns reconciliation/eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_preview import (
    AssessmentSetupPreview,
    load_assessment_setup_preview,
)
from meridian.grade_items import GradeItemPurpose
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_recovery_inventory import RecoveryInboxEntry
from meridian.teacher_session import TeacherSessionContext


@dataclass(frozen=True, slots=True)
class FreshAssessmentChoices:
    """Explicit current teacher choices, not decoded journal metadata."""

    work: ModuleWorkRef
    school_year: str
    period_id: str
    purpose: GradeItemPurpose | None
    existing_grade_item_id: str | None
    new_title: str | None
    actor_attribution: str
    rationale: str | None


ChoiceProvider = Callable[
    [Path, TeacherSessionContext, RecoveryInboxEntry],
    tuple[FreshAssessmentChoices, TeacherActionActor] | None,
]
FreshContext = tuple[
    AssessmentSetupPreview,
    TeacherActionActor,
    Callable[[], AssessmentSetupPreview],
]


def make_fresh_assessment_context_loader(
    dependencies: GuidedGradeItemBridgeDependencies,
    *,
    choose: ChoiceProvider,
) -> Callable[[Path, TeacherSessionContext, RecoveryInboxEntry], FreshContext | None]:
    """Adapt explicit teacher choices to E2G3C's fresh review gate.

    No cached assessment preview crosses a restart boundary. Repeated reads
    use the same explicit choices but load canonical data independently.
    """
    if not callable(choose):
        raise TypeError("Teacher choice provider required")

    def load(
        root: Path,
        session: TeacherSessionContext,
        entry: RecoveryInboxEntry,
    ) -> FreshContext | None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("Absolute workspace root required")
        selected = choose(root, session, entry)
        if selected is None:
            return None
        if not isinstance(selected, tuple) or len(selected) != 2:
            raise ValueError("Invalid teacher choices")
        choices, actor = selected
        if not isinstance(choices, FreshAssessmentChoices) or not isinstance(
            actor, TeacherActionActor
        ):
            raise ValueError("Typed teacher choices and actor required")
        scope = entry.receipt.preview.scope
        if (
            session.active_class_id is None
            or choices.work.class_id != session.active_class_id
            or scope.class_id != session.active_class_id
            or choices.school_year != entry.receipt.preview.scope.school_year
            and scope.school_year is not None
            or actor.source != "saved"
            or actor.actor_id != choices.actor_attribution
            or (session.active_work is not None and choices.work != session.active_work)
        ):
            raise ValueError("Teacher choices do not match recovery scope")

        def fresh() -> AssessmentSetupPreview:
            return load_assessment_setup_preview(
                root,
                class_id=choices.work.class_id,
                school_year=choices.school_year,
                period_id=choices.period_id,
                work=choices.work,
                dependencies=dependencies,
                purpose=choices.purpose,
                existing_grade_item_id=choices.existing_grade_item_id,
                new_title=choices.new_title,
                actor_attribution=choices.actor_attribution,
                rationale=choices.rationale,
            )

        preview = fresh()
        if preview.grade_item_id != scope.grade_item_id:
            raise ValueError("Reconstructed Grade Item differs from receipt")
        return preview, actor, fresh

    return load


__all__ = (
    "FreshAssessmentChoices",
    "ChoiceProvider",
    "make_fresh_assessment_context_loader",
)
