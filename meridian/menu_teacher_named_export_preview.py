"""Teacher-named, read-only preview of an authorized local report export (#123 8D).

Neither menu labels nor remembered class/period scopes grant data access.
The established export preview builder retains all source/roster authorization.
This route never copies a student payload to terminal output or commits exports.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_export_profiles import (
    NamedExportProfileCatalog,
    ProfileLister,
    ProfileLoader,
    _ProfileChanged,
)
from meridian.menu_teacher_named_export_profiles import (
    _revalidate as _profile_revalidate,
)
from meridian.menu_teacher_named_grades import _marking_period
from meridian.menu_teacher_named_review import _class
from meridian.menu_teacher_named_snapshots import (
    FrozenSnapshotChoiceCatalog,
    SnapshotLister,
    _SnapshotChanged,
)
from meridian.menu_teacher_named_snapshots import (
    _revalidate as _snapshot_revalidate,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    write_lines,
)
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_export import (
        ExportPreviewPresentation,
        ExportProfileListItem,
        ExportProfilePresentation,
    )
    from meridian.menu_snapshots import SnapshotListItem

PreviewBuilder: TypeAlias = Callable[
    [Path, str, str, str, str], "ExportPreviewPresentation"
]
_MAX_SNAPSHOTS = 200
_MAX_PROFILES = 200
_MAX_DIAGNOSTICS = 100


class _PreviewChanged(RuntimeError):
    """A previously reviewed exact input or output is no longer current."""


def _validate_preview(
    value: "ExportPreviewPresentation",
    *,
    class_id: str,
    snapshot: "SnapshotListItem",
    profile: "ExportProfilePresentation",
) -> None:
    if (
        value.class_id != class_id
        or value.snapshot_id != snapshot.snapshot_id
        or value.snapshot_sha256 != snapshot.snapshot_sha256
        or value.profile_id != profile.profile_id
        or value.profile_revision != profile.revision
        or value.profile_sha256 != profile.profile_sha256
        or value.format != profile.format
        or value.row_count < 0
        or value.payload_byte_length < 0
        or len(value.diagnostic_lines) > _MAX_DIAGNOSTICS
        or len(value.preview_sha256) != 64
        or len(value.payload_sha256) != 64
        or not all(ch in "0123456789abcdef" for ch in value.preview_sha256)
        or not all(ch in "0123456789abcdef" for ch in value.payload_sha256)
    ):
        raise _PreviewChanged("The export preview does not match chosen inputs.")


def run_named_report_export_preview(
    *,
    navigation: TeacherNavigationContext,
    snapshot_lister: SnapshotLister,
    profile_lister: ProfileLister,
    profile_loader: ProfileLoader,
    preview_builder: PreviewBuilder,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
    snapshot_catalog: FrozenSnapshotChoiceCatalog | None = None,
    profile_catalog: NamedExportProfileCatalog | None = None,
) -> None:
    """Inspect only preview metadata; no payload display, export, or receipt write."""
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
            raise _PreviewChanged("Class scope changed.")
        chosen_period = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen_period is None:
            return
        period, period_choice = chosen_period

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
                raise _PreviewChanged("Class or period is no longer current.")

        def scoped_snapshots(path: Path, cid: str) -> tuple["SnapshotListItem", ...]:
            values = snapshot_lister(path, cid)
            if len(values) > _MAX_SNAPSHOTS:
                raise _PreviewChanged("Too many frozen checkpoints to verify.")
            return tuple(
                item
                for item in values
                if item.school_year == period.school_year
                and item.period_id == period.period_id
                and item.calendar_revision == period.calendar_revision
            )

        def scoped_profiles(
            path: Path, cid: str
        ) -> tuple["ExportProfileListItem", ...]:
            values = profile_lister(path, cid)
            if len(values) > _MAX_PROFILES:
                raise _PreviewChanged("Too many Export Profiles to verify.")
            return tuple(item for item in values if item.current_revision is not None)

        snapshots = snapshot_catalog or FrozenSnapshotChoiceCatalog(
            navigation=navigation, lister=scoped_snapshots
        )
        profiles = profile_catalog or NamedExportProfileCatalog(
            navigation=navigation, lister=scoped_profiles
        )
        check_scope()
        frozen_choice = select_teacher_choice(
            catalog=snapshots,
            scope="frozen_snapshot",
            selected={"class": class_id},
            title="Choose Frozen Reporting Checkpoint",
            question="Which frozen report should be previewed for a local export?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if frozen_choice is None:
            return
        check_scope()
        profile_choice = select_teacher_choice(
            catalog=profiles,
            scope="export_profile",
            selected={"class": class_id},
            title="Choose Selected Export Profile",
            question="Which already-selected export format should be used?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if profile_choice is None:
            return

        def recheck_inputs() -> tuple["SnapshotListItem", "ExportProfilePresentation"]:
            check_scope()
            _snapshot_revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified.school_year,
                catalog=snapshots,
                choice=frozen_choice,
            )
            frozen = tuple(
                item
                for item in scoped_snapshots(root, class_id)
                if item.snapshot_id == frozen_choice.identity[0]
            )
            if len(frozen) != 1:
                raise _PreviewChanged("Frozen report is no longer unique.")
            _profile_revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified.school_year,
                catalog=profiles,
                choice=profile_choice,
            )
            selected = tuple(
                item
                for item in scoped_profiles(root, class_id)
                if item.profile_id == profile_choice.identity[0]
            )
            if len(selected) != 1:
                raise _PreviewChanged("Selected export format is no longer unique.")
            profile = profile_loader(root, class_id, selected[0].profile_id)
            if (
                profile is None
                or profile.class_id != class_id
                or profile.profile_id != selected[0].profile_id
                or profile.revision != selected[0].current_revision
            ):
                raise _PreviewChanged("Current export version changed.")
            return frozen[0], profile

        frozen, profile = recheck_inputs()
        preview = preview_builder(
            root,
            class_id,
            frozen.snapshot_id,
            frozen.snapshot_sha256,
            profile.profile_id,
        )
        _validate_preview(preview, class_id=class_id, snapshot=frozen, profile=profile)
        if recheck_inputs() != (frozen, profile):
            raise _PreviewChanged("Export inputs changed during preview.")
        second = preview_builder(
            root,
            class_id,
            frozen.snapshot_id,
            frozen.snapshot_sha256,
            profile.profile_id,
        )
        _validate_preview(second, class_id=class_id, snapshot=frozen, profile=profile)
        if second != preview or recheck_inputs() != (frozen, profile):
            raise _PreviewChanged("The export preview or its inputs changed.")
        clear_fn()
        print_menu_header(output, "Local Report Export Preview")
        write_lines(
            output,
            f"Frozen report: {frozen_choice.label}",
            f"Period: {period.label}",
            f"Export format: {profile_choice.label}",
            f"Selected profile version: {profile.revision}",
            f"File representation: {preview.format.upper()}",
            "Column headings: " + ", ".join(name for _, name in profile.columns),
            f"Rows: {preview.row_count}",
            f"Payload bytes: {preview.payload_byte_length}",
            f"Diagnostic categories: {len(preview.diagnostic_lines)}",
            "",
            "Preview metadata only; student-level payload is not printed here.",
            "No export file, receipt, or external-system update was performed.",
            "Use Advanced for exact preview hashes or technical diagnostics.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_SnapshotChanged, _ProfileChanged, _PreviewChanged):
        write_lines(
            output,
            "Class, period, checkpoint, profile, or preview changed during review.",
            "Nothing was exported. Refresh the named choices before retrying.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Authorized export preview could not be verified safely.",
            "No export was performed. Use Advanced for technical diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_report_export_preview",)
