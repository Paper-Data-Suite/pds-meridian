"""Deliberate named selection of the latest Export Profile revision (#123 8B).

The choice and session are never write authority. Meridian's existing profile
selection preview and digest-bound compare-and-swap committer own the mutation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_export_profiles import (
    NamedExportProfileCatalog,
    ProfileLister,
    ProfileLoader,
    _ProfileChanged,
    _revalidate,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_export import (
        ExportProfileListItem,
        ExportProfilePresentation,
        ExportProfileSelectionPlan,
    )

SelectionPreviewer: TypeAlias = Callable[[Path, str, str], "ExportProfileSelectionPlan"]
SelectionCommitter: TypeAlias = Callable[
    [Path, "ExportProfileSelectionPlan", str, str | None, datetime], str
]
Clock: TypeAlias = Callable[[], datetime]

# Existing TeacherAttributionInput intercepts this exact prompt in the main menu.
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "


def _validate_plan(
    plan: "ExportProfileSelectionPlan",
    *,
    row: "ExportProfileListItem",
    class_id: str,
) -> None:
    target = plan.target
    current = plan.expected_current
    if (
        target.class_id != class_id
        or target.profile_id != row.profile_id
        or target.profile_revision != row.latest_revision
        or plan.title != row.title
    ):
        raise _ProfileChanged("Export Profile preview targets another revision.")
    if row.current_revision is None:
        if current is not None:
            raise _ProfileChanged("Unexpected current selector during preview.")
    elif (
        current is None
        or current.class_id != class_id
        or current.profile_id != row.profile_id
    ):
        raise _ProfileChanged("Current Export Profile selector changed.")


def _verify_selected(
    value: "ExportProfilePresentation | None",
    *,
    row: "ExportProfileListItem",
    class_id: str,
) -> None:
    if row.current_revision is None:
        if value is not None:
            raise _ProfileChanged("Export Profile selection changed.")
    elif (
        value is None
        or value.class_id != class_id
        or value.profile_id != row.profile_id
        or value.revision != row.current_revision
    ):
        raise _ProfileChanged("Selected Export Profile changed.")


def run_named_export_profile_selection(
    *,
    navigation: TeacherNavigationContext,
    profile_lister: ProfileLister,
    profile_loader: ProfileLoader,
    selection_previewer: SelectionPreviewer,
    selection_committer: SelectionCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    profile_catalog: NamedExportProfileCatalog | None = None,
) -> None:
    """Make one reviewed latest version current, never write an export file."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        profiles = profile_catalog or NamedExportProfileCatalog(
            navigation=navigation, lister=profile_lister
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
            raise _ProfileChanged("Class changed before selection.")
        year = verified.school_year
        choice = select_teacher_choice(
            catalog=profiles,
            scope="export_profile",
            selected={"class": class_id},
            title="Choose Export Profile",
            question="Which saved export format should become current?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if choice is None:
            return

        def current_row() -> "ExportProfileListItem":
            return _revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=year,
                catalog=profiles,
                choice=choice,
            )

        row = current_row()
        selected = profile_loader(root, class_id, row.profile_id)
        _verify_selected(selected, row=row, class_id=class_id)
        if row.current_revision == row.latest_revision:
            if selected is None or selected.title != row.title:
                raise _ProfileChanged("Latest profile and current selection differ.")
            if (
                current_row() != row
                or profile_loader(root, class_id, row.profile_id) != selected
            ):
                raise _ProfileChanged("Current profile changed during review.")
            write_lines(
                output,
                "The latest version of this Export Profile is already selected.",
                "No selection was changed and no export was performed.",
            )
            pause_for_user(input_fn)
            return
        actor = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor:
            write_lines(output, "Teacher attribution unavailable. Nothing changed.")
            pause_for_user(input_fn)
            return
        rationale_text = read_choice(input_fn, "Reason (optional): ")
        rationale = rationale_text or None
        if (
            current_row() != row
            or profile_loader(root, class_id, row.profile_id) != selected
        ):
            raise _ProfileChanged("Export Profile changed during input.")
        plan = selection_previewer(root, class_id, row.profile_id)
        _validate_plan(plan, row=row, class_id=class_id)
        if (
            current_row() != row
            or profile_loader(root, class_id, row.profile_id) != selected
        ):
            raise _ProfileChanged("Export Profile changed during preview.")
        clear_fn()
        print_menu_header(output, "Use Export Profile Version")
        write_lines(
            output,
            f"Profile: {choice.label}",
            f"Latest authored version: {row.latest_revision}",
            (
                "Currently selected version: none"
                if row.current_revision is None
                else f"Currently selected version: {row.current_revision}"
            ),
            f"Version to use: {plan.target.profile_revision}",
            "Teacher attribution is recorded with this selection.",
            "",
            "USE changes only this Export Profile's local current version.",
            "It does not prepare a report, create a file/receipt, or update SIS.",
            "Type USE to confirm, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "USE":
            write_lines(output, "Canceled. Export Profile selection unchanged.")
            pause_for_user(input_fn)
            return
        if (
            current_row() != row
            or profile_loader(root, class_id, row.profile_id) != selected
        ):
            raise _ProfileChanged("Export Profile changed after confirmation.")
        fresh = selection_previewer(root, class_id, row.profile_id)
        _validate_plan(fresh, row=row, class_id=class_id)
        if fresh != plan or current_row() != row:
            raise _ProfileChanged("Reviewed exact selector authority changed.")
        attempted = True
        disposition = selection_committer(root, plan, actor, rationale, clock())
        if disposition not in {"created", "updated", "existing"}:
            raise _ProfileChanged("Unrecognized selector result.")
        confirmed = profile_loader(root, class_id, row.profile_id)
        if (
            confirmed is None
            or confirmed.class_id != class_id
            or confirmed.profile_id != row.profile_id
            or confirmed.revision != plan.target.profile_revision
            or confirmed.profile_sha256 != plan.target.profile_sha256
            or confirmed.title != plan.title
        ):
            raise _ProfileChanged("Committed Export Profile cannot be verified.")
        after = profile_lister(root, class_id)
        matches = tuple(value for value in after if value.profile_id == row.profile_id)
        if (
            len(matches) != 1
            or matches[0].latest_revision != row.latest_revision
            or matches[0].current_revision != row.latest_revision
            or matches[0].title != row.title
        ):
            raise _ProfileChanged("Current export version could not be verified.")
        write_lines(
            output,
            f"Export Profile version selected for local use ({disposition}).",
            "No report file, receipt, or district/SIS record was created.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ProfileChanged:
        if attempted:
            write_lines(
                output,
                "Export Profile selection outcome is uncertain; it may be stored.",
                "Inspect the selected version before trying again.",
            )
        else:
            write_lines(
                output,
                "Class, profile, or current version changed before selection.",
                "No selection was attempted. Refresh the named choices.",
            )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "Export Profile selection outcome could not be verified safely.",
                "A new selection may exist. Inspect it before retrying.",
            )
        else:
            write_lines(
                output,
                "Export Profile selection could not be verified safely.",
                "No selection was attempted. Use Advanced for diagnostics.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_export_profile_selection",)
