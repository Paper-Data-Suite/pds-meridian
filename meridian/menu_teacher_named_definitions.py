"""Read-only, teacher-named reporting definition discovery (#123 Slice 7C).

A definition may exist before any frozen snapshot. Canonical family IDs and
immutable revision digests stay in opaque choice identity/currentness witnesses.
No definition is authored, selected, or frozen by browsing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.reporting_snapshot_storage import (
    list_reporting_definition_ids,
    list_reporting_definition_revisions,
    load_reporting_definition_revision,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

_MAX_DEFINITIONS = 200
_MAX_REVISIONS = 500


class _DefinitionChanged(RuntimeError):
    """An earlier named choice no longer matches canonical reporting records."""


@dataclass(frozen=True, slots=True)
class NamedDefinitionItem:
    definition_id: str
    revision: int
    sha256: str
    title: str
    purpose: str
    school_year: str
    period_id: str
    revised_at: str


DefinitionLister: TypeAlias = Callable[[Path, str], tuple[NamedDefinitionItem, ...]]


def _list_definitions(root: Path, class_id: str) -> tuple[NamedDefinitionItem, ...]:
    """Enumerate exact latest definition revisions, independent of snapshots."""
    ids = list_reporting_definition_ids(root, class_id)
    if len(ids) > _MAX_DEFINITIONS:
        raise TeacherChoiceUnavailable("Too many definitions for this menu.")
    results: list[NamedDefinitionItem] = []
    for definition_id in ids:
        history = list_reporting_definition_revisions(root, class_id, definition_id)
        if not history or len(history) > _MAX_REVISIONS:
            raise TeacherChoiceUnavailable("Definition history is unavailable.")
        revision = history[-1]
        stored = load_reporting_definition_revision(
            root, class_id, definition_id, revision
        )
        value = stored.definition
        if (
            value.class_id != class_id
            or value.definition_id != definition_id
            or value.definition_revision != revision
        ):
            raise TeacherChoiceUnavailable("Definition history identity changed.")
        results.append(
            NamedDefinitionItem(
                definition_id=definition_id,
                revision=revision,
                sha256=stored.definition_sha256,
                title=value.title,
                purpose=value.purpose,
                school_year=value.target_period.school_year,
                period_id=value.target_period.period_id,
                revised_at=value.revised_at.isoformat(),
            )
        )
    return tuple(results)


@dataclass(slots=True)
class NamedDefinitionCatalog:
    """Read-only bounded catalog of canonical report definition families."""

    navigation: TeacherNavigationContext
    lister: DefinitionLister = _list_definitions

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "report_definition":
            raise TeacherChoiceUnavailable("Unsupported definition choice scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            items = self.lister(current.workspace, current.class_id)
            if len(items) > _MAX_DEFINITIONS:
                raise TeacherChoiceUnavailable("Too many reporting definitions.")
            return tuple(
                TeacherChoice(
                    identity=(item.definition_id,),
                    label=item.title,
                    detail=(
                        f"{item.purpose} · {item.school_year} / {item.period_id} · "
                        f"Updated {item.revised_at}"
                    ),
                    status=f"Latest revision {item.revision}",
                    witness=f"{item.revision}:{item.sha256}",
                )
                for item in items
            )
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Reporting definitions could not be verified."
            ) from error


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    school_year: str,
    catalog: NamedDefinitionCatalog,
    choice: TeacherChoice,
) -> NamedDefinitionItem:
    current = navigation.current_class()
    if (
        current is None
        or current.workspace != root
        or current.class_id != class_id
        or current.school_year != school_year
        or choice
        not in load_teacher_choices(
            catalog, scope="report_definition", selected={"class": class_id}
        )
    ):
        raise _DefinitionChanged("Class or definition choice changed.")
    matches = tuple(
        item
        for item in catalog.lister(root, class_id)
        if item.definition_id == choice.identity[0]
    )
    if len(matches) != 1:
        raise _DefinitionChanged("Definition is no longer unique.")
    item = matches[0]
    if item.title != choice.label or choice.witness != f"{item.revision}:{item.sha256}":
        raise _DefinitionChanged("Definition revision changed.")
    return item


def run_named_definition_browse(
    *,
    navigation: TeacherNavigationContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    definition_lister: DefinitionLister = _list_definitions,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    definition_catalog: NamedDefinitionCatalog | None = None,
) -> None:
    """Show one latest immutable definition by name without any write/selection."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        definitions = definition_catalog or NamedDefinitionCatalog(
            navigation=navigation, lister=definition_lister
        )
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
            raise _DefinitionChanged("Class changed before discovery.")
        school_year = verified.school_year
        choice = select_teacher_choice(
            catalog=definitions,
            scope="report_definition",
            selected={"class": class_id},
            title="Reporting Definitions",
            question="Which report definition would you like to inspect?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return
        first = _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=school_year,
            catalog=definitions,
            choice=choice,
        )
        last = _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=school_year,
            catalog=definitions,
            choice=choice,
        )
        if last != first:
            raise _DefinitionChanged("Definition revision changed during review.")
        clear_fn()
        print_menu_header(output, "Reporting Definition")
        write_lines(
            output,
            f"Report: {first.title}",
            f"Purpose: {first.purpose}",
            f"Academic period: {first.school_year} / {first.period_id}",
            f"Latest authored revision: {first.revision}",
            f"Revised: {first.revised_at}",
            "",
            "A definition describes a report; it is not a frozen checkpoint.",
            "No ReportingSnapshot was frozen or selected.",
            "No report definition or district/SIS record was changed.",
            "Use Advanced for exact identifiers and technical provenance.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _DefinitionChanged:
        write_lines(
            output,
            "Class or reporting definition changed since its selection.",
            "Nothing was changed. Refresh the named choices and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Reporting definition records could not be verified safely.",
            "Nothing was changed. Use Advanced for technical diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "NamedDefinitionItem",
    "NamedDefinitionCatalog",
    "DefinitionLister",
    "run_named_definition_browse",
)
