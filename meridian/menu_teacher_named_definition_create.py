"""Teacher-named creation of a new immutable Reporting Definition (#123 7E).

The identifier is generated locally with cryptographic entropy and never typed.
Exact Core scope, preview integrity, and storage conflict authority remain in
existing domain services. WRITE creates a definition, not a ReportingSnapshot.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_definitions import (
    DefinitionLister,
    NamedDefinitionItem,
    _list_definitions,
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
from meridian.reporting_snapshot import reporting_definition_reference
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog

if TYPE_CHECKING:
    from meridian.menu_snapshots import ReportingDefinitionPlan

DefinitionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, AcademicPeriodRef, str, str | None, datetime],
    "ReportingDefinitionPlan",
]
DefinitionCommitter: TypeAlias = Callable[[Path, "ReportingDefinitionPlan"], str]
Clock: TypeAlias = Callable[[], datetime]
IdentityFactory: TypeAlias = Callable[[], str]

_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "
_NEW_ID = re.compile(r"report-[0-9a-f]{32}\Z")
_MAX_DEFINITIONS = 200


class _DefinitionCreationChanged(RuntimeError):
    """The proposed new definition no longer matches verified state."""


def _new_definition_id() -> str:
    """Generate a path-safe opaque identity, not a name-derived identity."""
    return "report-" + secrets.token_hex(16)


def _check_plan(
    plan: "ReportingDefinitionPlan",
    *,
    class_id: str,
    definition_id: str,
    title: str,
    purpose: str,
    period: AcademicPeriodRef,
    actor: str,
    rationale: str | None,
    created_at: datetime,
) -> None:
    candidate = plan.candidate
    if (
        plan.class_id != class_id
        or plan.definition_id != definition_id
        or plan.definition_revision != 1
        or plan.title != title
        or plan.purpose != purpose
        or plan.school_year != period.school_year
        or plan.period_id != period.period_id
        or plan.actor_id != actor
        or plan.rationale != rationale
        or candidate.class_id != class_id
        or candidate.definition_id != definition_id
        or candidate.definition_revision != 1
        or candidate.supersedes_revision is not None
        or candidate.title != title
        or candidate.purpose != purpose
        or candidate.target_period != period
        or candidate.actor.kind != "teacher"
        or candidate.actor.actor_id != actor
        or candidate.rationale != rationale
        or candidate.revised_at != created_at
        or candidate.report_kind != "grade_report"
        or candidate.intended_audience != "teacher"
    ):
        raise _DefinitionCreationChanged("New definition preview changed identity.")
    reference = reporting_definition_reference(candidate)
    if (
        reference.class_id != class_id
        or reference.definition_id != definition_id
        or reference.definition_revision != 1
        or reference.definition_sha256 != plan.definition_sha256
    ):
        raise _DefinitionCreationChanged("New definition digest changed.")


def run_named_definition_creation(
    *,
    navigation: TeacherNavigationContext,
    definition_previewer: DefinitionPreviewer,
    definition_committer: DefinitionCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    definition_lister: DefinitionLister = _list_definitions,
    identity_factory: IdentityFactory = _new_definition_id,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Create the first immutable revision without requesting a canonical ID."""
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
            raise _DefinitionCreationChanged("Class scope changed.")
        chosen = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return
        period, period_choice = chosen

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
                raise _DefinitionCreationChanged("Class or marking period changed.")

        check_scope()
        title = read_choice(input_fn, "Report title (blank cancels): ")
        if not title:
            return
        purpose = read_choice(input_fn, "Report purpose (blank cancels): ")
        if not purpose:
            return
        rationale_text = read_choice(input_fn, "Reason for creating (optional): ")
        rationale = rationale_text or None
        actor = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor:
            write_lines(output, "Teacher attribution unavailable. Nothing written.")
            pause_for_user(input_fn)
            return
        created_at = clock()
        definition_id = identity_factory()
        if (
            not isinstance(definition_id, str)
            or _NEW_ID.fullmatch(definition_id) is None
        ):
            raise _DefinitionCreationChanged("Generated record identity is invalid.")
        academic_period = AcademicPeriodRef(period.school_year, period.period_id)

        def check_new() -> None:
            check_scope()
            items = definition_lister(root, class_id)
            if len(items) > _MAX_DEFINITIONS:
                raise _DefinitionCreationChanged(
                    "Definition catalog exceeds safe bounds."
                )
            if any(item.definition_id == definition_id for item in items):
                raise _DefinitionCreationChanged("Generated identity already exists.")
            if any(
                item.school_year == academic_period.school_year
                and item.period_id == academic_period.period_id
                and item.title.casefold() == title.casefold()
                for item in items
            ):
                raise _DefinitionCreationChanged(
                    "An existing definition has this title in the same period."
                )

        check_new()
        plan = definition_previewer(
            root,
            class_id,
            definition_id,
            title,
            purpose,
            academic_period,
            actor,
            rationale,
            created_at,
        )
        _check_plan(
            plan,
            class_id=class_id,
            definition_id=definition_id,
            title=title,
            purpose=purpose,
            period=academic_period,
            actor=actor,
            rationale=rationale,
            created_at=created_at,
        )
        check_new()
        clear_fn()
        print_menu_header(output, "Review New Reporting Definition")
        write_lines(
            output,
            f"Title: {title}",
            f"Purpose: {purpose}",
            f"Marking period: {period.label}",
            "First immutable definition revision: 1",
            f"Reason: {rationale or 'none'}",
            "Teacher attribution will be recorded.",
            "",
            "WRITE creates a Reporting Definition only.",
            "It does not freeze a checkpoint, select a report, or update SIS.",
            "Type WRITE to create this definition, or Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "WRITE":
            write_lines(output, "Canceled. No reporting definition was written.")
            pause_for_user(input_fn)
            return
        check_new()
        fresh = definition_previewer(
            root,
            class_id,
            definition_id,
            title,
            purpose,
            academic_period,
            actor,
            rationale,
            created_at,
        )
        _check_plan(
            fresh,
            class_id=class_id,
            definition_id=definition_id,
            title=title,
            purpose=purpose,
            period=academic_period,
            actor=actor,
            rationale=rationale,
            created_at=created_at,
        )
        if fresh != plan:
            raise _DefinitionCreationChanged("Definition changed since review.")
        check_new()
        attempted = True
        disposition = definition_committer(root, plan)
        if disposition != "created":
            raise _DefinitionCreationChanged("New definition write was not confirmed.")
        items = definition_lister(root, class_id)
        matches = [item for item in items if item.definition_id == definition_id]
        if len(matches) != 1:
            raise _DefinitionCreationChanged("New definition cannot be verified.")
        stored: NamedDefinitionItem = matches[0]
        if (
            stored.revision != 1
            or stored.sha256 != plan.definition_sha256
            or stored.title != title
            or stored.purpose != purpose
            or stored.school_year != academic_period.school_year
            or stored.period_id != academic_period.period_id
        ):
            raise _DefinitionCreationChanged("Stored definition differs from review.")
        write_lines(
            output,
            "",
            "New Reporting Definition created (revision 1).",
            "No ReportingSnapshot was frozen or selected.",
            "No district/SIS Grade or external system was updated.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _DefinitionCreationChanged:
        if attempted:
            write_lines(
                output,
                "Definition write outcome is uncertain; it may be stored.",
                "Browse reporting definitions before trying again.",
            )
        else:
            write_lines(
                output,
                "Class, period, or definition availability changed.",
                "No definition write was attempted. Review the named choices.",
            )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "The definition write could not be verified; it may be stored.",
                "Browse current reporting definitions before trying again.",
            )
        else:
            write_lines(
                output,
                "New definition could not be prepared safely.",
                "No definition write was attempted. Use Advanced diagnostics.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_definition_creation",)
