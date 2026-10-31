"""Teacher-readable membership history with Core provenance checks (#123 4D2).

Choices are transient. Their witnesses are not write authority; the legacy
membership selection workflow rechecks exact immutable dependencies under CAS.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_storage import (
    StoredGradeItemMembershipDecision,
    get_current_grade_item_membership_revision,
    list_grade_item_membership_revisions,
    load_grade_item_membership_revision,
)
from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
)
from meridian.teacher_navigation_work import RegistrationLister, _registrations

ReviewReader: TypeAlias = Callable[[Path, str], GradeItemsReview]
HistoryReader: TypeAlias = Callable[[Path, str, str, ModuleWorkRef], tuple[int, ...]]
RevisionReader: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, int], StoredGradeItemMembershipDecision
]
CurrentReader: TypeAlias = Callable[[Path, str, str, ModuleWorkRef], int | None]


@dataclass(slots=True)
class TeacherMembershipRevisionCatalog:
    """A bounded current-work / existing-membership history selector."""

    navigation: TeacherNavigationContext
    review_loader: ReviewReader = project_grade_items_review
    registration_lister: RegistrationLister = _registrations
    history_reader: HistoryReader = list_grade_item_membership_revisions
    revision_reader: RevisionReader = load_grade_item_membership_revision
    current_reader: CurrentReader = get_current_grade_item_membership_revision

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "membership_revision":
            raise TeacherChoiceUnavailable("Unsupported membership history scope.")
        class_id = selected.get("class")
        item_id = selected.get("grade_item")
        module_id = selected.get("module")
        work_id = selected.get("work")
        if not all((class_id, item_id, module_id, work_id)):
            raise TeacherChoiceUnavailable(
                "Choose class, Grade Item and registered work."
            )
        assert class_id is not None and item_id is not None
        assert module_id is not None and work_id is not None
        verified = self.navigation.verify_class(class_id)
        root = verified.workspace
        work = ModuleWorkRef(module_id, class_id, work_id)
        review = self.review_loader(root, class_id)
        if review.class_id != class_id or len(review.items) > 500:
            raise TeacherChoiceUnavailable("Grade Item review changed.")
        grade_items = tuple(row for row in review.items if row.grade_item_id == item_id)
        if len(grade_items) != 1:
            raise TeacherChoiceUnavailable("Grade Item is missing or ambiguous.")
        grade_item = grade_items[0]
        memberships = tuple(row for row in grade_item.memberships if row.work == work)
        if len(memberships) != 1:
            raise TeacherChoiceUnavailable(
                "No unique authored membership history exists."
            )
        row = memberships[0]
        registrations = self.registration_lister(root, class_id, verified.school_year)
        if not isinstance(registrations, tuple) or len(registrations) > 500:
            raise TeacherChoiceUnavailable("Registration catalog is unbounded.")
        matching = tuple(reg for reg in registrations if reg.work == work)
        if len(matching) != 1:
            raise TeacherChoiceUnavailable("Work registration is missing or ambiguous.")
        registration = matching[0]
        if (
            not registration.is_current_registration
            or registration.school_year != verified.school_year
            or registration.lifecycle not in {"active", "planned"}
        ):
            raise TeacherChoiceUnavailable("Work registration is no longer eligible.")
        history = self.history_reader(root, class_id, item_id, work)
        if (
            not history
            or len(history) > 100
            or history != tuple(range(1, len(history) + 1))
        ):
            raise TeacherChoiceUnavailable("Membership history missing or unbounded.")
        current = self.current_reader(root, class_id, item_id, work)
        if (
            row.latest_persisted_revision != history[-1]
            or row.selected_revision != current
            or (current is not None and current not in history)
        ):
            raise TeacherChoiceUnavailable(
                "Membership review changed during discovery."
            )
        choices: list[TeacherChoice] = []
        for number in history:
            stored = self.revision_reader(root, class_id, item_id, work, number)
            decision = stored.decision
            if (
                decision.class_id != class_id
                or decision.grade_item_id != item_id
                or decision.work_reference.work != work
                or decision.membership_revision != number
            ):
                raise TeacherChoiceUnavailable("Membership identity changed.")
            if (
                number == current
                and row.selected_revision_sha256 != stored.decision_sha256
            ):
                raise TeacherChoiceUnavailable("Selected membership digest changed.")
            basis_current = (
                grade_item.selected_revision is not None
                and grade_item.selected_revision_sha256 is not None
                and decision.grade_item_revision == grade_item.selected_revision
                and decision.grade_item_revision_sha256
                == grade_item.selected_revision_sha256
                and decision.work_reference.registration_revision
                == registration.registration_revision
            )
            period_text = "No period assignment"
            period_current = True
            if decision.decision == "included":
                period_current = False
                assignment = decision.academic_period
                if (
                    assignment is not None
                    and assignment.period.school_year == verified.school_year
                ):
                    try:
                        period = self.navigation.verify_period(
                            assignment.period.period_id
                        )
                    except NavigationScopeUnavailable:
                        pass
                    else:
                        if period.calendar_revision == assignment.calendar_revision:
                            period_current = True
                            period_text = period.label
                if not period_current:
                    period_text = "Historical or unavailable period"
            available = (
                basis_current
                and period_current
                and not (
                    decision.decision == "included" and grade_item.status != "active"
                )
            )
            decision_date = decision.decided_at.date().isoformat()
            choices.append(
                TeacherChoice(
                    identity=(str(number),),
                    label=f"{decision.decision.title()} relationship",
                    detail=(f"Version {number} · {decision_date} · {period_text}"),
                    status=(
                        "Available to use"
                        if available
                        else "Historical basis · Advanced only"
                    ),
                    witness=(
                        f"{stored.decision_sha256}:{current or 'none'}:{history[-1]}:"
                        f"{grade_item.selected_revision or 'none'}:"
                        f"{grade_item.selected_revision_sha256 or 'none'}:"
                        f"{registration.registration_revision}"
                    ),
                )
            )
        return tuple(choices)


__all__ = ("TeacherMembershipRevisionCatalog",)
