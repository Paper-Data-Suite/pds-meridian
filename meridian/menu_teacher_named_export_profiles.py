"""Named, read-only inspection of Export Profiles (#123 Slice 8A).

A display label is not authority. Every candidate retains its exact opaque ID,
latest history revision, and selected revision. The selected profile is freshly
loaded and cross-checked before display. No export, selection, or file write.
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
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_export import ExportProfileListItem, ExportProfilePresentation

ProfileLister: TypeAlias = Callable[[Path, str], tuple["ExportProfileListItem", ...]]
ProfileLoader: TypeAlias = Callable[
    [Path, str, str], "ExportProfilePresentation | None"
]
_MAX_PROFILES = 200


class _ProfileChanged(RuntimeError):
    """A verified Export Profile changed after the teacher chose its name."""


@dataclass(slots=True)
class NamedExportProfileCatalog:
    """Bounded class-scoped display of real Export Profile families."""

    navigation: TeacherNavigationContext
    lister: ProfileLister

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "export_profile":
            raise TeacherChoiceUnavailable("Unsupported Export Profile scope.")
        current = self.navigation.current_class()
        if current is None or selected.get("class") != current.class_id:
            raise TeacherChoiceUnavailable("Choose a verified class first.")
        try:
            profiles = self.lister(current.workspace, current.class_id)
            if len(profiles) > _MAX_PROFILES:
                raise TeacherChoiceUnavailable(
                    "Too many Export Profiles; use Advanced diagnostics."
                )
            return tuple(
                TeacherChoice(
                    identity=(item.profile_id,),
                    label=item.title,
                    detail=f"Latest authored version {item.latest_revision}",
                    status=(
                        "Not selected for export"
                        if item.current_revision is None
                        else f"Selected version {item.current_revision}"
                    ),
                    witness=f"{item.latest_revision}:{item.current_revision}",
                )
                for item in profiles
            )
        except TeacherChoiceUnavailable:
            raise
        except Exception as error:
            raise TeacherChoiceUnavailable(
                "Export Profile choices could not be verified."
            ) from error


def _revalidate(
    *,
    navigation: TeacherNavigationContext,
    root: Path,
    class_id: str,
    school_year: str,
    catalog: NamedExportProfileCatalog,
    choice: TeacherChoice,
) -> "ExportProfileListItem":
    current = navigation.current_class()
    if (
        current is None
        or current.workspace != root
        or current.class_id != class_id
        or current.school_year != school_year
        or choice
        not in load_teacher_choices(
            catalog, scope="export_profile", selected={"class": class_id}
        )
    ):
        raise _ProfileChanged("Class or named Export Profile changed.")
    rows = catalog.lister(root, class_id)
    if len(rows) > _MAX_PROFILES:
        raise _ProfileChanged("Export Profile inventory changed or became too large.")
    matches = tuple(row for row in rows if row.profile_id == choice.identity[0])
    if len(matches) != 1:
        raise _ProfileChanged("The Export Profile is missing or ambiguous.")
    selected = matches[0]
    if (
        selected.title != choice.label
        or choice.witness != f"{selected.latest_revision}:{selected.current_revision}"
    ):
        raise _ProfileChanged("The Export Profile version or selector changed.")
    return selected


def run_named_export_profile_browse(
    *,
    navigation: TeacherNavigationContext,
    profile_lister: ProfileLister,
    profile_loader: ProfileLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    profile_catalog: NamedExportProfileCatalog | None = None,
) -> None:
    """Inspect a named Export Profile and its local selected status; no writes."""
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
            raise _ProfileChanged("Class changed before browsing.")
        year = verified.school_year
        choice = select_teacher_choice(
            catalog=profiles,
            scope="export_profile",
            selected={"class": class_id},
            title="Choose Export Profile",
            question="Which saved export format would you like to inspect?",
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
            school_year=year,
            catalog=profiles,
            choice=choice,
        )
        selected_profile = profile_loader(root, class_id, first.profile_id)
        if first.current_revision is None:
            if selected_profile is not None:
                raise _ProfileChanged("Profile selection changed during inspection.")
        elif (
            selected_profile is None
            or selected_profile.class_id != class_id
            or selected_profile.profile_id != first.profile_id
            or selected_profile.revision != first.current_revision
        ):
            raise _ProfileChanged("Selected Export Profile identity changed.")
        last = _revalidate(
            navigation=navigation,
            root=root,
            class_id=class_id,
            school_year=year,
            catalog=profiles,
            choice=choice,
        )
        if (
            last != first
            or profile_loader(root, class_id, first.profile_id) != selected_profile
        ):
            raise _ProfileChanged("Export Profile selection changed during review.")
        clear_fn()
        print_menu_header(output, "Saved Export Profile")
        write_lines(
            output,
            f"Profile: {choice.label}",
            f"Latest authored version: {first.latest_revision}",
            (
                "Selected version: none — select a version before exporting"
                if first.current_revision is None
                else f"Selected version: {first.current_revision}"
            ),
        )
        if selected_profile is not None:
            write_lines(
                output,
                f"Selected version title: {selected_profile.title}",
                f"Purpose: {selected_profile.purpose}",
                f"Local file format: {selected_profile.format.upper()}",
                f"Column headings: {len(selected_profile.columns)}",
                "Columns: " + ", ".join(name for _, name in selected_profile.columns),
                f"Header row: {'yes' if selected_profile.include_header else 'no'}",
                (
                    "A newer version is available but not selected."
                    if first.latest_revision > selected_profile.revision
                    else "The latest authored version is selected."
                ),
            )
        else:
            write_lines(
                output,
                "No version is selected for export; output settings are unavailable.",
            )
        write_lines(
            output,
            "",
            "Read-only Export Profile inspection; no profile was selected.",
            "No report, file, receipt, or district/SIS record was written.",
            "Advanced contains exact record identities and provenance.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ProfileChanged:
        write_lines(
            output,
            "Class, Export Profile, or selected version changed during review.",
            "No record was changed. Refresh the named choices and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Export Profile choices could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = (
    "NamedExportProfileCatalog",
    "ProfileLister",
    "ProfileLoader",
    "run_named_export_profile_browse",
)
