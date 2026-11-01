"""#124 B2: read-only, named assessment choices and publication-history context.

A catalog row is a discovery hint. This module checks source identities against
canonical Core records; it never reads producer manifests or changes academic state.
A TeacherChoice's hidden identity/witness is *not* execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal, TypeAlias

from pds_core.academic_catalog import (
    CatalogPublication,
    PublicationCatalogQuery,
    query_publication_catalog,
)
from pds_core.academic_work_registration_storage import (
    load_current_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import (
    PublicationKind,
    PublicationRecord,
    PublicationWithdrawal,
)
from pds_core.publication_storage import (
    get_current_publication_record,
    load_publication_record,
    load_publication_withdrawal,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_inventory import (
    MAX_ASSESSMENTS,
    AssessmentSetupCandidate,
    AssessmentSetupInventoryError,
    AssessmentSetupReaders,
    discover_assessment_setup_inventory,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
    page_teacher_choices,
)

PublicationDisplayState: TypeAlias = Literal[
    "current_results_verified",
    "multiple_current_results",
    "withdrawn_results",
    "historical_results_only",
    "no_results_indexed",
]

RegistrationReader: TypeAlias = Callable[
    [Path, ModuleWorkRef], AcademicWorkRegistration | None
]
PublicationCatalogReader: TypeAlias = Callable[
    [Path, PublicationCatalogQuery], tuple[CatalogPublication, ...]
]
PublicationReader: TypeAlias = Callable[[Path, str], PublicationRecord]
WithdrawalReader: TypeAlias = Callable[[Path, str], PublicationWithdrawal | None]
CurrentSeriesReader: TypeAlias = Callable[
    [Path, ModuleWorkRef, PublicationKind, str], PublicationRecord | None
]

PRODUCER_NAMES = {"scoreform": "ScoreForm", "quillan": "Quillan", "concord": "Concord"}
_PUBLICATION_NAMES: dict[PublicationDisplayState, str] = {
    "current_results_verified": "Published results (record verified)",
    "multiple_current_results": "Multiple current publications — review",
    "withdrawn_results": "Published results withdrawn",
    "historical_results_only": "Historical publication — refresh/review",
    "no_results_indexed": "No published results indexed — refresh if expected",
}
_SETUP_NAMES = {
    "ready": "Grade Item ready",
    "needs_create": "Grade Item not yet created",
    "choose_existing": "Choose existing Grade Item",
    "review_relationship": "Review existing Grade Item relationship",
    "ambiguous": "More than one Grade Item relationship — review",
}


@dataclass(frozen=True, slots=True)
class AssessmentChoiceReaders:
    """All Core history reads are injectable; none may read protected manifests."""

    registration: RegistrationReader = load_current_academic_work_registration
    publications: PublicationCatalogReader = query_publication_catalog
    publication: PublicationReader = load_publication_record
    withdrawal: WithdrawalReader = load_publication_withdrawal
    current_series: CurrentSeriesReader = get_current_publication_record


@dataclass(frozen=True, slots=True)
class NamedAssessment:
    """One exact inventory candidate with disambiguated teacher presentation."""

    candidate: AssessmentSetupCandidate
    choice: TeacherChoice
    publication_state: PublicationDisplayState
    historical_publication_count: int
    registration_created_at: datetime


@dataclass(frozen=True, slots=True)
class NamedAssessmentList:
    """Stable in-memory list with #123 teacher search/pagination semantics."""

    class_id: str
    school_year: str
    period_id: str
    items: tuple[NamedAssessment, ...]
    choices: tuple[TeacherChoice, ...]

    def page(
        self, *, search: str = "", page_index: int = 0
    ) -> tuple[TeacherChoice, ...]:
        """Return a page of visible choices; no fresh reads or execution authority."""
        return page_teacher_choices(
            self.choices, query=search, page_index=page_index
        ).items


@dataclass(frozen=True, slots=True)
class _ChoiceCatalog:
    class_id: str
    choices: tuple[TeacherChoice, ...]

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "assessment" or selected != {"class": self.class_id}:
            raise TeacherChoiceUnavailable("Assessment choices lost the class scope.")
        return self.choices


def _verify_historical_row(
    root: Path, row: CatalogPublication, readers: AssessmentChoiceReaders
) -> None:
    """Verify immutable publication and withdrawal metadata without opening data."""
    record = readers.publication(root, row.publication_id)
    if (
        record.publication_id != row.publication_id
        or record.work != row.work
        or record.publication_kind != "academic_result_set"
        or row.publication_kind != "academic_result_set"
        or record.record_set_id != row.record_set_id
        or record.record_set_revision != row.record_set_revision
        or record.academic_work_registration_revision
        != row.academic_work_registration_revision
        or record.manifest_digest != row.manifest_digest
        or record.published_at != row.published_at
        or record.supersedes_publication_id != row.supersedes_publication_id
    ):
        raise AssessmentSetupInventoryError(
            "Publication history changed; refresh the Core academic catalog."
        )
    withdrawn = readers.withdrawal(root, row.publication_id)
    if row.is_withdrawn != (withdrawn is not None):
        raise AssessmentSetupInventoryError(
            "Publication withdrawal changed; refresh the Core academic catalog."
        )


def _availability(
    root: Path,
    candidate: AssessmentSetupCandidate,
    history: tuple[CatalogPublication, ...],
    readers: AssessmentChoiceReaders,
) -> PublicationDisplayState:
    if candidate.publication_state == "ambiguous_publication":
        return "multiple_current_results"
    if candidate.publication_state == "catalog_current_verified":
        matching = [
            row for row in history if row.publication_id == candidate.publication_id
        ]
        if len(matching) != 1 or not matching[0].is_current_selectable:
            raise AssessmentSetupInventoryError(
                "Current publication disappeared from history; refresh the catalog."
            )
        if matching[0].academic_work_registration_revision != (
            candidate.registration_revision
        ):
            raise AssessmentSetupInventoryError(
                "Current publication has a different registration basis."
            )
        return "current_results_verified"
    if not history:
        return "no_results_indexed"
    heads = [row for row in history if row.is_series_head]
    if not heads:
        raise AssessmentSetupInventoryError(
            "Publication history has no current series head; refresh the catalog."
        )
    for row in heads:
        current = readers.current_series(
            root, row.work, "academic_result_set", row.record_set_id
        )
        if row.is_withdrawn:
            if current is not None:
                raise AssessmentSetupInventoryError(
                    "Withdrawn publication still appears current; refresh the catalog."
                )
        elif current is None or current.publication_id != row.publication_id:
            raise AssessmentSetupInventoryError(
                "Publication history no longer matches its current series."
            )
    if any(row.is_current_selectable for row in heads):
        raise AssessmentSetupInventoryError(
            "A current publication is missing from the current catalog."
        )
    return (
        "withdrawn_results"
        if all(row.is_withdrawn for row in heads)
        else "historical_results_only"
    )


def project_named_assessment_choices(
    workspace_root: str | Path,
    candidates: tuple[AssessmentSetupCandidate, ...],
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    readers: AssessmentChoiceReaders = AssessmentChoiceReaders(),
) -> NamedAssessmentList:
    """Convert B1 verified work into safe, disambiguated, paged #123 choices.

    Source timestamps are canonical registration values. Equal display labels
    fail closed instead of exposing opaque work IDs or guessing by position.
    """
    if len(candidates) > MAX_ASSESSMENTS or len({x.work for x in candidates}) != len(
        candidates
    ):
        raise AssessmentSetupInventoryError(
            "Assessment candidates are not bounded/unique."
        )
    for candidate in candidates:
        if (
            candidate.work.class_id != class_id
            or candidate.school_year != school_year
            or candidate.period_id != period_id
        ):
            raise AssessmentSetupInventoryError(
                "Assessment identity changed outside the selected class/year/period."
            )
    root = Path(workspace_root)
    try:
        history = readers.publications(
            root,
            PublicationCatalogQuery(
                school_year=school_year,
                class_id=class_id,
                publication_kind="academic_result_set",
                state="all",
                limit=MAX_ASSESSMENTS + 1,
            ),
        )
        if len(history) > MAX_ASSESSMENTS:
            raise AssessmentSetupInventoryError(
                "Publication history is too large; narrow the class scope."
            )
        seen: set[str] = set()
        per_work: dict[ModuleWorkRef, list[CatalogPublication]] = {}
        for row in history:
            if row.publication_id in seen:
                raise AssessmentSetupInventoryError(
                    "Duplicate publication history row."
                )
            seen.add(row.publication_id)
            if row.work.class_id != class_id or row.school_year != school_year:
                raise AssessmentSetupInventoryError(
                    "Publication history escaped the selected class/year."
                )
            _verify_historical_row(root, row, readers)
            per_work.setdefault(row.work, []).append(row)

        named = []
        for candidate in candidates:
            registration = readers.registration(root, candidate.work)
            if (
                registration is None
                or registration.work != candidate.work
                or registration.title != candidate.title
                or registration.registration_revision != candidate.registration_revision
                or registration.lifecycle != candidate.lifecycle
                or registration.academic_intent != candidate.academic_intent
            ):
                raise AssessmentSetupInventoryError(
                    "Assessment registration changed since inventory; refresh."
                )
            created = registration.created_at
            if created.tzinfo is None:
                raise AssessmentSetupInventoryError(
                    "Assessment registration has no verifiable timestamp."
                )
            provenance = tuple(per_work.get(candidate.work, []))
            state = _availability(root, candidate, provenance, readers)
            source = PRODUCER_NAMES.get(
                candidate.work.module_id, candidate.work.module_id
            )
            when = created.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            next_step = (
                "Cancelled registration — setup blocked"
                if candidate.lifecycle == "cancelled"
                else _SETUP_NAMES[candidate.setup_state]
            )
            if candidate.lifecycle not in {"active", "planned", "cancelled"}:
                next_step = "Registration not active — review before setup"
            label = candidate.title
            detail = f"{candidate.work_kind.replace('_', ' ')} · registered {when}"
            choice = TeacherChoice(
                identity=(
                    candidate.work.class_id,
                    candidate.work.module_id,
                    candidate.work.work_id,
                ),
                label=label,
                detail=detail,
                source=source,
                status=f"{_PUBLICATION_NAMES[state]} · {next_step}",
                witness=(
                    f"registration={candidate.registration_revision};"
                    f"calendar={candidate.calendar_revision};"
                    f"publication={candidate.publication_id or 'none'}"
                ),
            )
            named.append(
                NamedAssessment(candidate, choice, state, len(provenance), created)
            )
        catalog = _ChoiceCatalog(class_id, tuple(row.choice for row in named))
        verified = load_teacher_choices(
            catalog, scope="assessment", selected={"class": class_id}
        )
        by_identity = {item.choice.identity: item for item in named}
        return NamedAssessmentList(
            class_id,
            school_year,
            period_id,
            tuple(by_identity[choice.identity] for choice in verified),
            verified,
        )
    except (AssessmentSetupInventoryError, TeacherChoiceUnavailable):
        raise
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        raise AssessmentSetupInventoryError(
            "Assessment choices cannot be verified; refresh Core and try again."
        ) from error


def load_named_assessment_choices(
    workspace_root: str | Path,
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    inventory_readers: AssessmentSetupReaders = AssessmentSetupReaders(),
    choice_readers: AssessmentChoiceReaders = AssessmentChoiceReaders(),
) -> NamedAssessmentList:
    """Fresh B1 inventory and B2 history; never apply academic changes."""
    candidates = discover_assessment_setup_inventory(
        workspace_root,
        class_id=class_id,
        school_year=school_year,
        period_id=period_id,
        readers=inventory_readers,
    )
    return project_named_assessment_choices(
        workspace_root,
        candidates,
        class_id=class_id,
        school_year=school_year,
        period_id=period_id,
        readers=choice_readers,
    )


__all__ = (
    "AssessmentChoiceReaders",
    "NamedAssessment",
    "NamedAssessmentList",
    "PublicationDisplayState",
    "load_named_assessment_choices",
    "project_named_assessment_choices",
)
