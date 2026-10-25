"""Teacher-first revision of an existing immutable Reporting Definition (#123 7D).

A named current family and marking period are revalidated at every boundary.
WRITE authors one exact immutable revision; it never freezes/selects a snapshot.
Existing Meridian preview, CAS history, and attribution services retain authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_definitions import (
    DefinitionLister,
    NamedDefinitionCatalog,
    NamedDefinitionItem,
    _DefinitionChanged,
    _list_definitions,
    _revalidate,
)
from meridian.menu_teacher_named_grades import _marking_period
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_snapshots import ReportingDefinitionPlan

DefinitionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, AcademicPeriodRef, str, str | None, datetime],
    "ReportingDefinitionPlan",
]
DefinitionCommitter: TypeAlias = Callable[[Path, "ReportingDefinitionPlan"], str]
Clock: TypeAlias = Callable[[], datetime]

# Exact existing TeacherAttributionInput bridge; not a new typed academic ID.
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "
_MAX_DEFINITIONS = 200


def _check_plan(
    plan: "ReportingDefinitionPlan",
    prior: NamedDefinitionItem,
    *,
    class_id: str,
    title: str,
    purpose: str,
    actor: str,
    rationale: str | None,
    decided_at: datetime,
) -> None:
    """Bind canonical preview to reviewed inputs and next immutable revision."""
    candidate = plan.candidate
    if (
        plan.class_id != class_id
        or plan.definition_id != prior.definition_id
        or plan.definition_revision != prior.revision + 1
        or plan.title != title
        or plan.purpose != purpose
        or plan.school_year != prior.school_year
        or plan.period_id != prior.period_id
        or plan.actor_id != actor
        or plan.rationale != rationale
        or candidate.class_id != class_id
        or candidate.definition_id != prior.definition_id
        or candidate.definition_revision != prior.revision + 1
        or candidate.supersedes_revision != prior.revision
        or candidate.title != title
        or candidate.purpose != purpose
        or candidate.target_period
        != AcademicPeriodRef(prior.school_year, prior.period_id)
        or candidate.actor.kind != "teacher"
        or candidate.actor.actor_id != actor
        or candidate.rationale != rationale
        or candidate.revised_at != decided_at
        or candidate.report_kind != "grade_report"
        or candidate.intended_audience != "teacher"
    ):
        raise _DefinitionChanged("The authored candidate differs from its review.")
    from meridian.reporting_snapshot import reporting_definition_reference

    reference = reporting_definition_reference(candidate)
    if (
        reference.definition_id != prior.definition_id
        or reference.definition_revision != prior.revision + 1
        or plan.definition_sha256 != reference.definition_sha256
    ):
        raise _DefinitionChanged("The immutable candidate digest changed.")


def run_named_definition_revision(
    *,
    navigation: TeacherNavigationContext,
    definition_previewer: DefinitionPreviewer,
    definition_committer: DefinitionCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    definition_lister: DefinitionLister = _list_definitions,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Write a new revision of a named existing definition, never a snapshot."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified = navigation.current_class()
        if (
            verified is None
            or verified.workspace != root
            or verified.class_id != class_id
        ):
            raise _DefinitionChanged("Verified class changed.")
        period_selection = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if period_selection is None:
            return
        period, period_choice = period_selection

        def scoped_lister(path: Path, cid: str) -> tuple[NamedDefinitionItem, ...]:
            values = definition_lister(path, cid)
            if len(values) > _MAX_DEFINITIONS:
                raise _DefinitionChanged("Reporting definition inventory is too large.")
            return tuple(
                value
                for value in values
                if value.school_year == period.school_year
                and value.period_id == period.period_id
            )

        catalog = NamedDefinitionCatalog(navigation, scoped_lister)

        def check_scope() -> None:
            current = navigation.current_class()
            if (
                current is None
                or current.workspace != root
                or current.class_id != class_id
                or current.school_year != verified.school_year
                or navigation.current_period() != period
                or period_choice
                not in load_teacher_choices(
                    periods, scope="period", selected={"class": class_id}
                )
            ):
                raise _DefinitionChanged("The class or marking period became stale.")

        check_scope()
        choice = select_teacher_choice(
            catalog=catalog,
            scope="report_definition",
            selected={"class": class_id},
            title="Choose Reporting Definition",
            question="Which existing report definition should be revised?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return

        def check_choice() -> NamedDefinitionItem:
            check_scope()
            result = _revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified.school_year,
                catalog=catalog,
                choice=choice,
            )
            if (
                result.school_year != period.school_year
                or result.period_id != period.period_id
            ):
                raise _DefinitionChanged("Definition is outside the chosen period.")
            return result

        prior = check_choice()
        write_lines(
            output,
            f"Revising: {prior.title}",
            f"Purpose: {prior.purpose}",
            f"Marking period: {period.label}",
            "Press Enter to keep the existing title or purpose.",
        )
        new_title = (
            read_choice(input_fn, "New report title (optional): ") or prior.title
        )
        new_purpose = (
            read_choice(input_fn, "New report purpose (optional): ") or prior.purpose
        )
        if new_title == prior.title and new_purpose == prior.purpose:
            write_lines(output, "No title or purpose change. No revision was written.")
            pause_for_user(input_fn)
            return
        rationale_text = read_choice(input_fn, "Reason for this change (optional): ")
        rationale = rationale_text or None
        actor = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor:
            write_lines(output, "Teacher attribution is unavailable. Nothing written.")
            pause_for_user(input_fn)
            return
        revised_at = clock()
        if check_choice() != prior:
            raise _DefinitionChanged("Definition changed during teacher input.")
        plan = definition_previewer(
            root,
            class_id,
            prior.definition_id,
            new_title,
            new_purpose,
            AcademicPeriodRef(period.school_year, period.period_id),
            actor,
            rationale,
            revised_at,
        )
        _check_plan(
            plan,
            prior,
            class_id=class_id,
            title=new_title,
            purpose=new_purpose,
            actor=actor,
            rationale=rationale,
            decided_at=revised_at,
        )
        if check_choice() != prior:
            raise _DefinitionChanged("Definition changed during preview.")
        clear_fn()
        print_menu_header(output, "Review Reporting Definition Revision")
        write_lines(
            output,
            f"Report: {prior.title}",
            f"Marking period: {period.label}",
            f"Previous title: {prior.title}",
            f"New title: {plan.title}",
            f"Previous purpose: {prior.purpose}",
            f"New purpose: {plan.purpose}",
            f"New revision: {plan.definition_revision}",
            f"Rationale: {rationale or 'none'}",
            "Teacher attribution is recorded with the new revision.",
            "",
            "WRITE saves one immutable definition revision.",
            "It does not freeze or select a ReportingSnapshot or update SIS.",
            "Type WRITE to record this revision; press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "WRITE":
            write_lines(output, "Canceled. No definition revision was written.")
            pause_for_user(input_fn)
            return
        if check_choice() != prior:
            raise _DefinitionChanged("Definition changed since review.")
        fresh = definition_previewer(
            root,
            class_id,
            prior.definition_id,
            new_title,
            new_purpose,
            AcademicPeriodRef(period.school_year, period.period_id),
            actor,
            rationale,
            revised_at,
        )
        _check_plan(
            fresh,
            prior,
            class_id=class_id,
            title=new_title,
            purpose=new_purpose,
            actor=actor,
            rationale=rationale,
            decided_at=revised_at,
        )
        if fresh != plan or check_choice() != prior:
            raise _DefinitionChanged("Definition history or candidate changed.")
        attempted = True
        disposition = definition_committer(root, plan)
        if disposition not in {"created", "existing"}:
            raise _DefinitionChanged("Unrecognized definition write outcome.")
        current = tuple(
            item
            for item in definition_lister(root, class_id)
            if item.definition_id == prior.definition_id
        )
        if (
            len(current) != 1
            or current[0].revision != plan.definition_revision
            or current[0].sha256 != plan.definition_sha256
            or current[0].title != plan.title
            or current[0].purpose != plan.purpose
            or current[0].school_year != plan.school_year
            or current[0].period_id != plan.period_id
        ):
            raise _DefinitionChanged("Committed definition could not be reverified.")
        write_lines(
            output,
            "",
            f"Reporting Definition revision recorded ({disposition}).",
            f"Latest revision: {plan.definition_revision}",
            "No ReportingSnapshot was frozen or selected.",
            "No official district/SIS Grade was changed.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _DefinitionChanged:
        if attempted:
            write_lines(
                output,
                "Definition write outcome is uncertain; a revision may be stored.",
                "Inspect the latest definition before attempting another write.",
            )
        else:
            write_lines(
                output,
                "Class, marking period, or definition changed during review.",
                "No write was attempted. Refresh the named choices.",
            )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "Definition write outcome could not be verified safely.",
                "A revision may exist. Inspect the latest definition before retrying.",
            )
        else:
            write_lines(
                output,
                "The reporting definition revision could not be prepared safely.",
                "No write was attempted. Use Advanced for diagnostics.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_definition_revision",)
