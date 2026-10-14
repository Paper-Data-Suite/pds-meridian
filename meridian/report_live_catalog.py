"""Canonical read-only catalog for teacher report choices (Issue #111 Slice 12.2).

Uses Core class metadata, roster and the verified academic-period catalog, and
Meridian's existing Grade Item and ReportingSnapshot selection projections.
It does not rebuild the catalog, manufacture identities, run reports or write files.
External gradebook mapping profiles currently live as explicit CLI-input files,
not a class-scoped canonical inventory: that scope remains safely unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import TypeAlias

from pds_core.academic_catalog import (
    AcademicPeriodCatalogQuery,
    CatalogAcademicPeriod,
    query_academic_period_catalog,
)
from pds_core.class_metadata import ClassMetadata, load_class_metadata_for_class
from pds_core.classes import ClassFolder, list_class_folders, load_class_roster
from pds_core.rosters import Roster
from pds_core.routes import classes_dir
from pds_core.workspace import resolve_workspace_root

from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingError,
    external_gradebook_mapping_from_json_bytes,
    external_gradebook_mapping_reference,
)
from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.report_guided_selection import (
    REPORT_GUIDES,
    ReportOption,
    ReportScope,
    ReportSelectionUnavailable,
)
from meridian.reporting_snapshot_storage import (
    StoredReportingSnapshot,
    list_reporting_snapshot_ids,
    load_reporting_snapshot,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
ClassLister: TypeAlias = Callable[[Path], tuple[ClassFolder, ...]]
PeriodLister: TypeAlias = Callable[[Path, str], tuple[CatalogAcademicPeriod, ...]]
ClassMetadataLoader: TypeAlias = Callable[[Path, str], ClassMetadata]
RosterLoader: TypeAlias = Callable[[Path, str], Roster]
GradeItemReviewer: TypeAlias = Callable[[Path, str], GradeItemsReview]
SnapshotIdLister: TypeAlias = Callable[[Path, str], tuple[str, ...]]
SnapshotLoader: TypeAlias = Callable[[Path, str, str], StoredReportingSnapshot]


def _classes(root: Path) -> tuple[ClassFolder, ...]:
    if classes_dir(root).is_symlink():
        raise ReportSelectionUnavailable("Linked class collections are not supported.")
    folders = list_class_folders(root, require_metadata=True, load_metadata=True)
    if any(
        item.class_dir.is_symlink()
        or item.metadata_path.is_symlink()
        or item.roster_path.is_symlink()
        for item in folders
    ):
        raise ReportSelectionUnavailable("Linked class records are not supported.")
    return folders


def _periods(root: Path, school_year: str) -> tuple[CatalogAcademicPeriod, ...]:
    # Core verifies the disposable index against its source digest and schema.
    # Never rebuild it as a side effect of a read-only report selection.
    return query_academic_period_catalog(
        root,
        AcademicPeriodCatalogQuery(
            school_year=school_year,
            period_type="marking_period",
            current_calendar_only=True,
        ),
    )


@dataclass(frozen=True, slots=True)
class ReportLiveCatalogDependencies:
    workspace_resolver: WorkspaceResolver = resolve_workspace_root
    class_lister: ClassLister = _classes
    period_lister: PeriodLister = _periods
    class_metadata_loader: ClassMetadataLoader = load_class_metadata_for_class
    roster_loader: RosterLoader = load_class_roster
    grade_item_reviewer: GradeItemReviewer = project_grade_items_review
    snapshot_id_lister: SnapshotIdLister = list_reporting_snapshot_ids
    snapshot_loader: SnapshotLoader = load_reporting_snapshot


@dataclass(slots=True)
class LiveReportChoiceCatalog:
    """Provide bounded choices from verified sources, never raw folder guesses."""

    dependencies: ReportLiveCatalogDependencies = field(
        default_factory=ReportLiveCatalogDependencies
    )
    _workspace: Path | None = field(default=None, init=False, repr=False)
    _mapping_file: Path | None = field(default=None, init=False, repr=False)

    def _root(self) -> Path:
        root = self.dependencies.workspace_resolver().resolve(strict=True)
        if self._workspace is None:
            self._workspace = root
        elif root != self._workspace:
            raise ReportSelectionUnavailable(
                "The active workspace changed during selection."
            )
        return root

    def _class(self, root: Path, selected: Mapping[ReportScope, str]) -> ClassFolder:
        class_id = selected.get("class")
        if not class_id:
            raise ReportSelectionUnavailable("Choose a class first.")
        for folder in self.dependencies.class_lister(root):
            if folder.class_id == class_id and folder.metadata is not None:
                # Load again: do not rely on an earlier menu's stale class record.
                current = self.dependencies.class_metadata_loader(root, class_id)
                if current.school_year != folder.metadata.school_year:
                    raise ReportSelectionUnavailable("The class information changed.")
                return folder
        raise ReportSelectionUnavailable("The class is no longer available.")

    def _period(
        self,
        root: Path,
        folder: ClassFolder,
        selected: Mapping[ReportScope, str],
    ) -> CatalogAcademicPeriod:
        period_id = selected.get("period")
        if not period_id:
            raise ReportSelectionUnavailable("Choose a marking period first.")
        assert folder.metadata is not None
        matches = tuple(
            period
            for period in self.dependencies.period_lister(
                root, folder.metadata.school_year
            )
            if period.period_id == period_id and period.lifecycle != "cancelled"
        )
        if len(matches) != 1:
            raise ReportSelectionUnavailable(
                "The marking period is unavailable or ambiguous."
            )
        return matches[0]

    def options(
        self,
        *,
        report_kind: str,
        scope: ReportScope,
        selected: Mapping[ReportScope, str],
    ) -> tuple[ReportOption, ...]:
        if report_kind not in {guide.report_kind for guide in REPORT_GUIDES}:
            raise ReportSelectionUnavailable("Unknown report family.")
        if scope not in {
            "class", "period", "student", "grade_item", "checkpoint", "mapping"
        }:
            raise ReportSelectionUnavailable("Unknown report selection type.")
        try:
            root = self._root()
            if scope == "class":
                classes = self.dependencies.class_lister(root)
                return tuple(
                    ReportOption(
                        folder.class_id,
                        folder.class_id.replace("_", " "),
                        f"{folder.metadata.school_year} · {folder.class_id}",
                    )
                    for folder in classes
                    if folder.metadata is not None
                )
            folder = self._class(root, selected)
            assert folder.metadata is not None
            if scope == "period":
                return tuple(
                    ReportOption(
                        item.period_id,
                        item.label,
                        (
                            f"{item.start_date.isoformat()} to "
                            f"{item.end_date.isoformat()} · {item.lifecycle}"
                        ),
                    )
                    for item in self.dependencies.period_lister(
                        root, folder.metadata.school_year
                    )
                    if item.lifecycle != "cancelled"
                )
            period = self._period(root, folder, selected)
            if scope == "student":
                roster = self.dependencies.roster_loader(root, folder.class_id)
                names = [
                    f"{row.first_name} {row.last_name}" for row in roster.students
                ]
                return tuple(
                    ReportOption(
                        row.student_id,
                        f"{row.first_name} {row.last_name}",
                        (
                            f"Record {row.student_id}"
                            if names.count(names[index]) > 1
                            else None
                        ),
                    )
                    for index, row in enumerate(roster.students)
                )
            if scope == "grade_item":
                review = self.dependencies.grade_item_reviewer(root, folder.class_id)
                return tuple(
                    ReportOption(
                        row.grade_item_id,
                        row.title or row.grade_item_id,
                        (
                            "Archived"
                            if row.status == "archived"
                            else f"Item {row.grade_item_id}"
                        ),
                    )
                    for row in review.items
                    if row.selected_revision is not None
                )
            if scope == "checkpoint":
                found: list[ReportOption] = []
                for snapshot_id in self.dependencies.snapshot_id_lister(
                    root, folder.class_id
                ):
                    stored = self.dependencies.snapshot_loader(
                        root, folder.class_id, snapshot_id
                    )
                    snapshot = stored.snapshot
                    if (
                        snapshot.target_period.school_year != period.school_year
                        or snapshot.target_period.period_id != period.period_id
                        or snapshot.calendar_revision != period.calendar_revision
                    ):
                        continue
                    when = snapshot.created_at.astimezone(UTC).strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                    found.append(
                        ReportOption(
                            snapshot_id, f"Checkpoint {when}",
                            f"Snapshot {snapshot_id}",
                        )
                    )
                return tuple(found)
            # An external mapping profile is a teacher-supplied file, not an
            # enumerated Meridian record. It appears only after the teacher has
            # named one exact file through ``choose_mapping_file``.
            if self._mapping_file is None:
                return ()
            return (
                self._mapping_option(
                    root,
                    folder.class_id,
                    period,
                    self._mapping_file,
                ),
            )
        except ReportSelectionUnavailable:
            raise
        except (OSError, ValueError) as error:
            raise ReportSelectionUnavailable(
                "Authoritative report choices could not be verified."
            ) from error

    def choose_mapping_file(
        self,
        *,
        report_kind: str,
        path_text: str,
        selected: Mapping[ReportScope, str],
    ) -> ReportOption:
        """Validate one teacher-named mapping file without searching directories."""

        if report_kind != "sis_gradebook_reconciliation":
            raise ReportSelectionUnavailable(
                "A mapping profile is not used by this report."
            )
        root = self._root()
        folder = self._class(root, selected)
        period = self._period(root, folder, selected)
        try:
            candidate = Path(path_text).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as error:
            raise ReportSelectionUnavailable(
                "The mapping profile file is unavailable."
            ) from error
        option = self._mapping_option(root, folder.class_id, period, candidate)
        self._mapping_file = candidate
        return option

    @staticmethod
    def _mapping_option(
        root: Path,
        class_id: str,
        period: CatalogAcademicPeriod,
        path: Path,
    ) -> ReportOption:
        # The file is an explicit teacher input, not canonical workspace state.
        _ = root
        try:
            if path.is_symlink() or not path.is_file():
                raise ReportSelectionUnavailable(
                    "The mapping profile must be one regular non-linked file."
                )
            if path.stat().st_size > 512 * 1024:
                raise ReportSelectionUnavailable(
                    "The mapping profile exceeds the bounded input size."
                )
            profile = external_gradebook_mapping_from_json_bytes(path.read_bytes())
        except ReportSelectionUnavailable:
            raise
        except (ExternalGradebookMappingError, OSError, ValueError) as error:
            raise ReportSelectionUnavailable(
                "The mapping profile file is invalid."
            ) from error
        if (
            profile.class_id != class_id
            or profile.target_period.school_year != period.school_year
            or profile.target_period.period_id != period.period_id
        ):
            raise ReportSelectionUnavailable(
                "The mapping profile does not match the selected class and period."
            )
        reference = external_gradebook_mapping_reference(profile)
        return ReportOption(
            str(path),
            profile.title,
            f"{profile.system_label} · revision {profile.profile_revision} "
            f"· {reference.profile_sha256[:12]}",
        )


__all__ = ("LiveReportChoiceCatalog", "ReportLiveCatalogDependencies")
