"""Bounded, verified Grade Item revision choices for Meridian #123 Slice 4D1.

A revision choice is not permission or a selection command. The existing
Grade Item selection workflow remains the only consequential write boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from meridian.grade_item_storage import (
    StoredGradeItemRevision,
    get_current_grade_item_revision,
    list_grade_item_revisions,
    load_grade_item_revision,
)
from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.teacher_navigation_choices import TeacherChoice, TeacherChoiceUnavailable
from meridian.teacher_navigation_context import TeacherNavigationContext

HistoryReader: TypeAlias = Callable[[Path, str, str], tuple[int, ...]]
RevisionReader: TypeAlias = Callable[[Path, str, str, int], StoredGradeItemRevision]
CurrentReader: TypeAlias = Callable[[Path, str, str], int | None]
ReviewReader: TypeAlias = Callable[[Path, str], GradeItemsReview]


@dataclass(slots=True)
class TeacherGradeItemRevisionCatalog:
    """Offer actual immutable history as labeled, never automatically used, rows."""

    navigation: TeacherNavigationContext
    review_loader: ReviewReader = project_grade_items_review
    history_reader: HistoryReader = list_grade_item_revisions
    revision_reader: RevisionReader = load_grade_item_revision
    current_reader: CurrentReader = get_current_grade_item_revision

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        if scope != "grade_item_revision":
            raise TeacherChoiceUnavailable("Unsupported revision catalog scope.")
        class_id = selected.get("class")
        item_id = selected.get("grade_item")
        if not class_id or not item_id:
            raise TeacherChoiceUnavailable("Choose class and Grade Item first.")
        verified = self.navigation.verify_class(class_id)
        root = verified.workspace
        review = self.review_loader(root, class_id)
        if review.class_id != class_id or len(review.items) > 500:
            raise TeacherChoiceUnavailable("Grade Item review is unavailable.")
        matches = tuple(row for row in review.items if row.grade_item_id == item_id)
        if len(matches) != 1:
            raise TeacherChoiceUnavailable("Grade Item is missing or ambiguous.")
        history = self.history_reader(root, class_id, item_id)
        if (
            not history
            or len(history) > 100
            or history != tuple(range(1, len(history) + 1))
        ):
            raise TeacherChoiceUnavailable("Revision history is missing or unbounded.")
        current = self.current_reader(root, class_id, item_id)
        if current is not None and current not in history:
            raise TeacherChoiceUnavailable("Current revision is outside history.")
        row = matches[0]
        if (
            row.latest_persisted_revision != history[-1]
            or row.selected_revision != current
        ):
            raise TeacherChoiceUnavailable(
                "Grade Item review changed during discovery."
            )
        choices: list[TeacherChoice] = []
        for number in history:
            stored = self.revision_reader(root, class_id, item_id, number)
            revision = stored.revision
            if (
                revision.class_id != class_id
                or revision.grade_item_id != item_id
                or revision.grade_item_revision != number
            ):
                raise TeacherChoiceUnavailable("Revision identity changed.")
            selected_state = "Currently in use" if number == current else "Not current"
            choices.append(
                TeacherChoice(
                    identity=(str(number),),
                    label=revision.title,
                    detail=(
                        f"Version {number} · {revision.status.replace('_', ' ')} · "
                        f"{revision.revised_at.date().isoformat()}"
                    ),
                    status=selected_state,
                    witness=(
                        f"{stored.revision_sha256}:{current or 'none'}:{history[-1]}"
                    ),
                )
            )
        return tuple(choices)


__all__ = ("TeacherGradeItemRevisionCatalog",)
