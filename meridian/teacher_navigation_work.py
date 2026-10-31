"""Current registered-work choices and Grade Item membership state (#123 4C).

Registration, Grade Item, and membership reads are exact and read-only. A
catalog row is a navigation candidate, never authorization or a write command.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from pds_core.academic_catalog import (
    AcademicWorkRegistrationCatalogQuery,
    CatalogAcademicWorkRegistration,
    query_academic_work_registration_catalog,
)

from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
    VerifiedClassScope,
)

RegistrationLister: TypeAlias = Callable[
    [Path, str, str], tuple[CatalogAcademicWorkRegistration, ...]
]
GradeItemsReviewer: TypeAlias = Callable[[Path, str], GradeItemsReview]


def _registrations(
    root: Path, class_id: str, school_year: str
) -> tuple[CatalogAcademicWorkRegistration, ...]:
    """Use Core's verified disposable index, never rebuild it on a UI read."""
    return query_academic_work_registration_catalog(
        root,
        AcademicWorkRegistrationCatalogQuery(
            class_id=class_id,
            school_year=school_year,
            current_only=True,
            limit=501,
        ),
    )


def _period_text(
    navigation: TeacherNavigationContext,
    scope: VerifiedClassScope,
    membership: object,
) -> str:
    from meridian.grade_items_workflow import GradeItemMembershipReviewRow

    if not isinstance(membership, GradeItemMembershipReviewRow):
        return ""
    if membership.academic_period_id is None:
        return ""
    if membership.academic_period_school_year != scope.school_year:
        return " · Historical period assignment"
    try:
        verified = navigation.verify_period(membership.academic_period_id)
    except NavigationScopeUnavailable:
        return " · Period needs review"
    if verified.calendar_revision != membership.academic_period_calendar_revision:
        return " · Historical calendar assignment"
    return f" · {verified.label}"


@dataclass(slots=True)
class TeacherRegisteredWorkCatalog:
    """Class- and Grade Item-scoped current Core registered work choices."""

    navigation: TeacherNavigationContext
    grade_item_reviewer: GradeItemsReviewer = project_grade_items_review
    registration_lister: RegistrationLister = _registrations

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "registered_work":
            raise TeacherChoiceUnavailable("Unknown registered-work scope.")
        class_id = selected.get("class")
        grade_item_id = selected.get("grade_item")
        if not class_id or not grade_item_id:
            raise TeacherChoiceUnavailable("Choose a class and Grade Item first.")
        verified = self.navigation.verify_class(class_id)
        review = self.grade_item_reviewer(verified.workspace, class_id)
        if review.class_id != class_id or len(review.items) > 500:
            raise TeacherChoiceUnavailable("Grade Item review cannot be verified.")
        matching = tuple(
            row for row in review.items if row.grade_item_id == grade_item_id
        )
        if len(matching) != 1:
            raise TeacherChoiceUnavailable("Selected Grade Item changed.")
        grade_item = matching[0]
        registrations = self.registration_lister(
            verified.workspace, class_id, verified.school_year
        )
        if not isinstance(registrations, tuple) or len(registrations) > 500:
            raise TeacherChoiceUnavailable("Registered-work catalog exceeds bound.")
        choices: list[TeacherChoice] = []
        for registration in registrations:
            if (
                not registration.is_current_registration
                or registration.school_year != verified.school_year
                or registration.work.class_id != class_id
            ):
                raise TeacherChoiceUnavailable(
                    "Current registered-work catalog changed scope."
                )
            if registration.lifecycle not in {"active", "planned"}:
                continue
            memberships = tuple(
                item
                for item in grade_item.memberships
                if item.work == registration.work
            )
            if len(memberships) > 1:
                raise TeacherChoiceUnavailable("Duplicate work memberships.")
            membership = memberships[0] if memberships else None
            if membership is None:
                relation = "No recorded relationship"
                membership_witness = "unlinked"
                period = ""
            else:
                relation = (
                    "Membership not selected"
                    if membership.decision is None
                    else f"Membership {membership.decision}"
                )
                membership_witness = (
                    f"{membership.selected_revision or 'none'}:"
                    f"{membership.selected_revision_sha256 or 'none'}:"
                    f"{membership.latest_persisted_revision}:"
                    f"{membership.grade_item_basis_state}"
                )
                period = _period_text(self.navigation, verified, membership)
            choices.append(
                TeacherChoice(
                    identity=(registration.work.module_id, registration.work.work_id),
                    label=registration.title,
                    detail=(
                        f"{registration.work_kind.replace('_', ' ')} · "
                        f"{relation}{period}"
                    ),
                    source=registration.work.module_id.replace("_", " ").title(),
                    status=registration.lifecycle.replace("_", " "),
                    witness=(
                        f"{registration.registration_revision}:"
                        f"{registration.updated_at.isoformat()}:"
                        f"{membership_witness}:"
                        f"{grade_item.selected_revision or 'none'}:"
                        f"{grade_item.selected_revision_sha256 or 'none'}:"
                        f"{grade_item.latest_persisted_revision}"
                    ),
                )
            )
        return tuple(choices)


__all__ = ("TeacherRegisteredWorkCatalog", "RegistrationLister", "GradeItemsReviewer")
