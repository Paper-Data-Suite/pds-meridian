"""#124: bounded, read-only assessment and Grade Item setup inventory.

A Core catalog entry is a discovery hint, not an academic authority or
permission to open protected producer evidence. No publication manifest is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, TypeAlias

from pds_core.academic_catalog import (
    AcademicWorkRegistrationCatalogQuery,
    CatalogAcademicWorkRegistration,
    CatalogPublication,
    PublicationCatalogQuery,
    query_academic_work_registration_catalog,
    query_publication_catalog,
)
from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.academic_periods import AcademicPeriodCalendar
from pds_core.academic_work_registration_storage import (
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationKind, PublicationRecord
from pds_core.publication_storage import get_current_publication_record
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review

MAX_ASSESSMENTS = 500
PublicationState: TypeAlias = Literal[
    "catalog_current_verified", "no_current_catalog_result", "ambiguous_publication"
]
SetupState: TypeAlias = Literal[
    "ready", "needs_create", "choose_existing", "review_relationship", "ambiguous"
]


class AssessmentSetupInventoryError(RuntimeError):
    """Read-only discovery cannot be trusted for this selected context."""


@dataclass(frozen=True, slots=True)
class AssessmentSetupCandidate:
    """One verified registration plus separate publication and setup states."""

    work: ModuleWorkRef
    school_year: str
    title: str
    work_kind: str
    academic_intent: str
    lifecycle: str
    registration_revision: int
    publication_state: PublicationState
    publication_id: str | None
    setup_state: SetupState
    ready_grade_item_id: str | None
    related_grade_item_ids: tuple[str, ...]
    active_unlinked_grade_item_ids: tuple[str, ...]
    period_id: str
    calendar_revision: int

    @property
    def grade_item_ready(self) -> bool:
        return self.setup_state == "ready"


RegistrationLister: TypeAlias = Callable[
    [Path, AcademicWorkRegistrationCatalogQuery],
    tuple[CatalogAcademicWorkRegistration, ...],
]
PublicationLister: TypeAlias = Callable[
    [Path, PublicationCatalogQuery], tuple[CatalogPublication, ...]
]
RegistrationLoader: TypeAlias = Callable[
    [Path, ModuleWorkRef], AcademicWorkRegistration | None
]
CurrentPublicationLoader: TypeAlias = Callable[
    [Path, ModuleWorkRef, PublicationKind, str], PublicationRecord | None
]
CalendarLoader: TypeAlias = Callable[[Path, str], AcademicPeriodCalendar | None]
ReviewLoader: TypeAlias = Callable[[Path, str], GradeItemsReview]


@dataclass(frozen=True, slots=True)
class AssessmentSetupReaders:
    """Injected public read ports; no reader can confer evidence permission."""

    registrations: RegistrationLister = query_academic_work_registration_catalog
    publications: PublicationLister = query_publication_catalog
    current_registration: RegistrationLoader = load_current_academic_work_registration
    current_publication: CurrentPublicationLoader = get_current_publication_record
    calendar: CalendarLoader = load_current_academic_period_calendar
    grade_items: ReviewLoader = project_grade_items_review


def _check_registration(
    row: CatalogAcademicWorkRegistration,
    current: AcademicWorkRegistration | None,
    class_id: str,
    school_year: str,
) -> None:
    if (
        current is None
        or row.work.class_id != class_id
        or row.school_year != school_year
        or not row.is_current_registration
        or row.work != current.work
        or row.registration_revision != current.registration_revision
        or row.title != current.title
        or row.work_kind != current.work_kind
        or row.academic_intent != current.academic_intent
        or row.lifecycle != current.lifecycle
        or row.producer_contract_version != current.producer_contract_version
        or row.source_records != current.source_records
    ):
        raise AssessmentSetupInventoryError(
            "Registered assessment changed; refresh the derived catalog before setup."
        )


def _publication_state(
    root: Path,
    row: CatalogAcademicWorkRegistration,
    publications: tuple[CatalogPublication, ...],
    readers: AssessmentSetupReaders,
) -> tuple[PublicationState, str | None]:
    matches = tuple(pub for pub in publications if pub.work == row.work)
    if len(matches) > 1:
        return "ambiguous_publication", None
    if not matches:
        return "no_current_catalog_result", None
    candidate = matches[0]
    current = readers.current_publication(
        root, row.work, "academic_result_set", candidate.record_set_id
    )
    if (
        current is None
        or current.publication_id != candidate.publication_id
        or current.work != row.work
        or current.publication_kind != "academic_result_set"
        or current.manifest_digest != candidate.manifest_digest
        or current.record_set_revision != candidate.record_set_revision
        or current.academic_work_registration_revision
        != candidate.academic_work_registration_revision
    ):
        raise AssessmentSetupInventoryError(
            "Published assessment changed; refresh the derived catalog before setup."
        )
    # Do not read manifest bytes or infer an evidence grant from the record.
    return "catalog_current_verified", current.publication_id


def _setup_state(
    row: CatalogAcademicWorkRegistration,
    review: GradeItemsReview,
    period_id: str,
    calendar_revision: int,
) -> tuple[SetupState, str | None, tuple[str, ...], tuple[str, ...]]:
    related = []
    ready = []
    unlinked = []
    for item in review.items:
        links = tuple(link for link in item.memberships if link.work == row.work)
        if links:
            related.append(item.grade_item_id)
        if not links and item.selected_revision is not None and item.status == "active":
            unlinked.append(item.grade_item_id)
        for link in links:
            if (
                item.selected_revision is not None
                and item.status == "active"
                and link.selected_revision is not None
                and link.decision == "included"
                and link.grade_item_basis_state == "matches_current_grade_item"
                and link.registration_revision == row.registration_revision
                and link.academic_period_school_year == row.school_year
                and link.academic_period_id == period_id
                and link.academic_period_calendar_revision == calendar_revision
            ):
                ready.append(item.grade_item_id)
    if len(ready) > 1:
        state: SetupState = "ambiguous"
    elif len(ready) == 1:
        state = "ready" if len(related) == 1 else "ambiguous"
    elif related:
        state = "review_relationship"
    elif unlinked:
        state = "choose_existing"
    else:
        state = "needs_create"
    return (
        state,
        ready[0] if state == "ready" else None,
        tuple(sorted(related)),
        tuple(sorted(unlinked)),
    )


def discover_assessment_setup_inventory(
    workspace_root: str | Path,
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    readers: AssessmentSetupReaders = AssessmentSetupReaders(),
) -> tuple[AssessmentSetupCandidate, ...]:
    """Discover work without changing catalog, academic state, or authorization.

    Requires caller-selected exact class, year and named marking-period identity.
    Before using any candidate for a write, revalidate all canonical witnesses.
    """
    root = Path(workspace_root)
    try:
        calendar = readers.calendar(root, school_year)
        if calendar is None or calendar.school_year != school_year:
            raise AssessmentSetupInventoryError(
                "Current academic calendar is unavailable; choose a configured year."
            )
        periods = tuple(
            period
            for period in calendar.periods
            if period.period_id == period_id
            and period.period_type == "marking_period"
            and period.lifecycle != "cancelled"
        )
        if len(periods) != 1:
            raise AssessmentSetupInventoryError(
                "Selected marking period is unavailable or no longer current."
            )
        registrations = readers.registrations(
            root,
            AcademicWorkRegistrationCatalogQuery(
                school_year=school_year,
                class_id=class_id,
                current_only=True,
                limit=MAX_ASSESSMENTS + 1,
            ),
        )
        publications = readers.publications(
            root,
            PublicationCatalogQuery(
                school_year=school_year,
                class_id=class_id,
                publication_kind="academic_result_set",
                state="current",
                limit=MAX_ASSESSMENTS + 1,
            ),
        )
        if len(registrations) > MAX_ASSESSMENTS or len(publications) > MAX_ASSESSMENTS:
            raise AssessmentSetupInventoryError(
                "Assessment listing exceeds the safe limit; narrow the class scope."
            )
        review = readers.grade_items(root, class_id)
        if review.class_id != class_id or len(review.items) > MAX_ASSESSMENTS:
            raise AssessmentSetupInventoryError(
                "Grade Item class scope is unavailable."
            )
        result = []
        identities: set[ModuleWorkRef] = set()
        for row in registrations:
            if row.work in identities:
                raise AssessmentSetupInventoryError(
                    "Registered assessment catalog contains duplicate work identity."
                )
            identities.add(row.work)
            current = readers.current_registration(root, row.work)
            _check_registration(row, current, class_id, school_year)
            publication_state, publication_id = _publication_state(
                root, row, publications, readers
            )
            setup_state, ready_id, related, unlinked = _setup_state(
                row, review, period_id, calendar.calendar_revision
            )
            result.append(
                AssessmentSetupCandidate(
                    work=row.work,
                    school_year=school_year,
                    title=row.title,
                    work_kind=row.work_kind,
                    academic_intent=row.academic_intent,
                    lifecycle=row.lifecycle,
                    registration_revision=row.registration_revision,
                    publication_state=publication_state,
                    publication_id=publication_id,
                    setup_state=(
                        "review_relationship"
                        if row.lifecycle == "cancelled"
                        else setup_state
                    ),
                    ready_grade_item_id=(
                        None if row.lifecycle == "cancelled" else ready_id
                    ),
                    related_grade_item_ids=related,
                    active_unlinked_grade_item_ids=unlinked,
                    period_id=period_id,
                    calendar_revision=calendar.calendar_revision,
                )
            )
        if any(pub.work not in identities for pub in publications):
            raise AssessmentSetupInventoryError(
                "Publication catalog contains work without a current registration."
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.title.casefold(),
                    item.work.module_id,
                    item.work.work_id,
                ),
            )
        )
    except AssessmentSetupInventoryError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        raise AssessmentSetupInventoryError(
            "Assessment setup inventory could not be verified; refresh canonical state."
        ) from error


__all__ = (
    "AssessmentSetupCandidate",
    "AssessmentSetupInventoryError",
    "AssessmentSetupReaders",
    "MAX_ASSESSMENTS",
    "discover_assessment_setup_inventory",
)
