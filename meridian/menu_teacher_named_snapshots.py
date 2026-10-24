"""Named, read-only browsing of frozen ReportingSnapshots (#123 Slice 7A).

A label is never snapshot authority. Choices bind the lister's exact digest,
immutable definition title, and frozen row count. The established inspector
reloads canonical selection state before presentation. No freeze or select.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.reporting_snapshot_storage import load_reporting_definition_revision
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_snapshots import SnapshotListItem, SnapshotPresentation

SnapshotLister: TypeAlias = Callable[[Path, str], tuple["SnapshotListItem", ...]]
SnapshotInspector: TypeAlias = Callable[[Path, str, str], "SnapshotPresentation"]
DefinitionTitleLoader: TypeAlias = Callable[[Path, str, str, int], str]
_MAX_SNAPSHOTS = 200


class _SnapshotChanged(RuntimeError):
    """A prior choice no longer identifies its original frozen record."""


def _definition_title(
    root: Path, class_id: str, definition_id: str, revision: int
) -> str:
    """Read the immutable title, never fabricate a human name from an ID."""
    stored = load_reporting_definition_revision(root, class_id, definition_id, revision)
    record = stored.definition
    if (
        record.class_id != class_id
        or record.definition_id != definition_id
        or record.definition_revision != revision
    ):
        raise TeacherChoiceUnavailable("Reporting definition identity changed.")
    return record.title


@dataclass(slots=True)
class FrozenSnapshotChoiceCatalog:
    """Bounded catalog of immutable class snapshots with teacher-readable titles."""

    navigation: TeacherNavigationContext
    lister: SnapshotLister
    title_loader: DefinitionTitleLoader = _definition_title

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "frozen_snapshot":
            raise TeacherChoiceUnavailable("Unsupported snapshot choice scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Rechoose the verified class.")
        try:
            items = self.lister(current.workspace, current.class_id)
            if len(items) > _MAX_SNAPSHOTS:
                raise TeacherChoiceUnavailable(
                    "Too many snapshots to browse safely. Use Advanced diagnostics."
                )
            choices: list[TeacherChoice] = []
            for item in items:
                title = self.title_loader(
                    current.workspace,
                    current.class_id,
                    item.definition_id,
                    item.definition_revision,
                )
                # A title/date/row-count is context, not a canonical identifier.
                choices.append(
                    TeacherChoice(
                        identity=(item.snapshot_id,),
                        label=title,
                        detail=(
                            f"{item.school_year} · Frozen {item.created_at} · "
                            f"{item.row_count} rows"
                        ),
                        status="Saved reporting checkpoint",
                        witness=(
                            f"{item.snapshot_sha256}:"
                            f"{item.definition_revision}:{item.calendar_revision}"
                        ),
                    )
                )
            return tuple(choices)
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Frozen report choices could not be verified."
            ) from error


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    school_year: str,
    catalog: FrozenSnapshotChoiceCatalog,
    choice: TeacherChoice,
) -> None:
    verified = navigation.current_class()
    if (
        verified is None
        or verified.workspace != root
        or verified.class_id != class_id
        or verified.school_year != school_year
        or choice
        not in load_teacher_choices(
            catalog, scope="frozen_snapshot", selected={"class": class_id}
        )
    ):
        raise _SnapshotChanged("Frozen snapshot or class changed.")


def run_named_snapshot_browse(
    *,
    navigation: TeacherNavigationContext,
    lister: SnapshotLister,
    inspector: SnapshotInspector,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    title_loader: DefinitionTitleLoader = _definition_title,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    snapshot_catalog: FrozenSnapshotChoiceCatalog | None = None,
) -> None:
    """Inspect one named immutable snapshot; never freeze/select/report externally."""
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        snapshots = snapshot_catalog or FrozenSnapshotChoiceCatalog(
            navigation=navigation, lister=lister, title_loader=title_loader
        )
        active = _class(
            navigation,
            classes,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
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
            raise _SnapshotChanged("Class changed before browsing.")
        school_year = verified.school_year
        choice = select_teacher_choice(
            catalog=snapshots,
            scope="frozen_snapshot",
            selected={"class": class_id},
            title="Frozen Reporting Checkpoints",
            question="Which saved reporting checkpoint would you like to inspect?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=school_year,
            catalog=snapshots,
            choice=choice,
        )
        candidates = lister(root, class_id)
        if len(candidates) > _MAX_SNAPSHOTS:
            raise _SnapshotChanged("Snapshot inventory exceeds the browse limit.")
        matches = [row for row in candidates if row.snapshot_id == choice.identity[0]]
        if len(matches) != 1:
            raise _SnapshotChanged("Selected snapshot is no longer unique.")
        first = inspector(root, class_id, choice.identity[0])
        if first.item != matches[0]:
            raise _SnapshotChanged("Frozen snapshot content changed.")
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=school_year,
            catalog=snapshots,
            choice=choice,
        )
        refreshed = inspector(root, class_id, choice.identity[0])
        if refreshed != first:
            raise _SnapshotChanged("Current reporting selection changed.")
        _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=school_year,
            catalog=snapshots,
            choice=choice,
        )
        clear_fn()
        print_menu_header(output, "Frozen Reporting Checkpoint")
        write_lines(
            output,
            f"Report: {choice.label}",
            f"School year: {first.item.school_year}",
            f"Frozen: {first.item.created_at}",
            f"Report rows: {first.item.row_count}",
            (
                "Current for this reporting scope: yes"
                if first.current_for_scope
                else "Current for this reporting scope: no"
            ),
            "",
            "Read-only historical checkpoint. No snapshot was frozen or selected.",
            "No district/SIS Grade or external system was updated.",
            "Use Advanced for exact identities, hashes and selection details.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _SnapshotChanged:
        write_lines(
            output,
            "Class, frozen snapshot, or reporting selection changed.",
            "No record was changed. Refresh the named choices and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Frozen reporting checkpoints could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "DefinitionTitleLoader",
    "FrozenSnapshotChoiceCatalog",
    "run_named_snapshot_browse",
)
