"""Verified, read-only catalog adapters for #123 Grade Items and Proficiency.

All labels are presentation only; only exact Core/Meridian identities select records.
No publication, producer evidence, or write-side API is invoked in discovery.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

from pds_core.classes import ClassFolder, list_class_folders
from pds_core.rosters import Roster, student_display_name
from pds_core.routes import classes_dir

from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.standards_proficiency_storage import (
    StoredStandardProficiencyResult,
    list_standard_proficiency_result_identities,
    load_current_standard_proficiency_result,
)
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import TeacherNavigationContext

ClassLister: TypeAlias = Callable[[Path], tuple[ClassFolder, ...]]
GradeItemReviewer: TypeAlias = Callable[[Path, str], GradeItemsReview]
ResultIdentityLister: TypeAlias = Callable[
    [Path, str], tuple[tuple[str, str, str], ...]
]
ResultLoader: TypeAlias = Callable[
    [Path, str, str, str, str], StoredStandardProficiencyResult | None
]


def _classes(root: Path) -> tuple[ClassFolder, ...]:
    if classes_dir(root).is_symlink():
        raise TeacherChoiceUnavailable("Linked class collections are unavailable.")
    folders = list_class_folders(
        root, require_metadata=True, load_metadata=True, require_roster=True
    )
    if any(
        item.class_dir.is_symlink()
        or item.metadata_path.is_symlink()
        or item.roster_path.is_symlink()
        for item in folders
    ):
        raise TeacherChoiceUnavailable("Linked class records are unavailable.")
    return folders


def _identities(root: Path, class_id: str) -> tuple[tuple[str, str, str], ...]:
    return list_standard_proficiency_result_identities(
        root, class_id, maximum_families=500
    )


@dataclass(frozen=True, slots=True)
class TeacherAcademicChoiceReaders:
    """Injected public read boundary; never mutates academic or teacher state."""

    class_lister: ClassLister = _classes
    grade_item_reviewer: GradeItemReviewer = project_grade_items_review
    result_identity_lister: ResultIdentityLister = _identities
    result_loader: ResultLoader = load_current_standard_proficiency_result


@dataclass(slots=True)
class TeacherAcademicChoiceCatalog:
    """Scoped, bounded teacher choice service over current authoritative reads."""

    navigation: TeacherNavigationContext
    readers: TeacherAcademicChoiceReaders = field(
        default_factory=TeacherAcademicChoiceReaders
    )

    def _class(self, selected: Mapping[str, str]) -> tuple[Path, str]:
        class_id = selected.get("class")
        if not class_id:
            raise TeacherChoiceUnavailable("Choose a class first.")
        checked = self.navigation.verify_class(class_id)
        return checked.workspace, checked.class_id

    def _roster(self, root: Path, class_id: str) -> Roster:
        roster = self.navigation.readers.roster_loader(root, class_id)
        if roster.class_id != class_id:
            raise TeacherChoiceUnavailable("Class roster changed.")
        return roster

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        """Return finite verified candidates. Selection never has side effects."""
        if scope == "class":
            root = self.navigation.readers.workspace_resolver().resolve(strict=True)
            year = self.navigation.readers.active_year_loader(root)
            if year is None:
                raise TeacherChoiceUnavailable("No active school year.")
            folders = self.readers.class_lister(root)
            if len(folders) > 500:
                raise TeacherChoiceUnavailable("Class catalog exceeds safe bound.")
            choices: list[TeacherChoice] = []
            for folder in folders:
                if folder.metadata is None or folder.metadata.school_year != year:
                    continue
                checked = self.navigation.verify_class(folder.class_id)
                if checked.workspace != root:
                    raise TeacherChoiceUnavailable("Workspace changed.")
                choices.append(
                    TeacherChoice(
                        identity=(folder.class_id,),
                        label=f"Class {folder.class_id}",
                        detail=f"School year {year}",
                        witness=folder.metadata.updated_at.isoformat(),
                    )
                )
            return tuple(choices)

        root, class_id = self._class(selected)
        if scope == "grade_item":
            review = self.readers.grade_item_reviewer(root, class_id)
            if review.class_id != class_id or len(review.items) > 500:
                raise TeacherChoiceUnavailable("Grade Item review is unavailable.")
            return tuple(
                TeacherChoice(
                    identity=(row.grade_item_id,),
                    label=row.title or "Grade Item without selected revision",
                    detail=(
                        f"{(row.purpose or 'Purpose unselected').replace('_', ' ')}"
                        f" · {len(row.memberships)} work relationships"
                    ),
                    status=row.status or row.selection_state.replace("_", " "),
                    witness=(
                        f"{row.selected_revision or 'none'}:"
                        f"{row.selected_revision_sha256 or 'none'}:"
                        f"{row.latest_persisted_revision}"
                    ),
                )
                for row in review.items
            )

        if scope == "student":
            roster = self._roster(root, class_id)
            if len(roster.students) > 500:
                raise TeacherChoiceUnavailable("Class roster exceeds safe bound.")
            return tuple(
                TeacherChoice(
                    identity=(student.student_id,),
                    label=student_display_name(student),
                    detail=(f"Class period {student.period} · roster position {index}"),
                )
                for index, student in enumerate(roster.students, start=1)
            )

        if scope == "standard":
            grade_item_id = selected.get("grade_item")
            student_id = selected.get("student")
            if not grade_item_id or not student_id:
                raise TeacherChoiceUnavailable("Choose a Grade Item and student first.")
            # Reverify both parent identities. A stray result family is not an
            # authority to navigate outside the chosen class or roster.
            review = self.readers.grade_item_reviewer(root, class_id)
            if review.class_id != class_id or not any(
                row.grade_item_id == grade_item_id for row in review.items
            ):
                raise TeacherChoiceUnavailable("Grade Item is no longer available.")
            if student_id not in {
                item.student_id for item in self._roster(root, class_id).students
            }:
                raise TeacherChoiceUnavailable("Student left this roster.")
            identities = self.readers.result_identity_lister(root, class_id)
            if len(identities) > 500:
                raise TeacherChoiceUnavailable("Result catalog exceeds safe bound.")
            choices = []
            for item_id, owner_id, standard_id in identities:
                if item_id != grade_item_id or owner_id != student_id:
                    continue
                current = self.readers.result_loader(
                    root, class_id, item_id, owner_id, standard_id
                )
                if current is None:
                    continue
                choices.append(
                    TeacherChoice(
                        identity=(standard_id,),
                        label=f"Standard {standard_id}",
                        status="Current selected result",
                        witness=(
                            f"{current.snapshot.result_revision}:"
                            f"{current.result_sha256}"
                        ),
                    )
                )
            return tuple(choices)
        raise TeacherChoiceUnavailable("Unsupported choice scope.")


__all__ = ("TeacherAcademicChoiceCatalog", "TeacherAcademicChoiceReaders")
