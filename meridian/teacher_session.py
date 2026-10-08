"""Process-local teacher session context for Issue #110."""

from __future__ import annotations

from dataclasses import dataclass

from pds_core.routing_models import ModuleWorkRef


class TeacherSessionContextError(ValueError):
    """Raised when transient teacher-session identity is structurally invalid."""


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherSessionContextError(f"{field_name} must be a string.")
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        raise TeacherSessionContextError(
            f"{field_name} must be a non-empty single-line identifier."
        )
    return value


@dataclass(slots=True)
class TeacherSessionContext:
    """Bounded process-local navigation context, never academic authority."""

    active_class_id: str | None = None
    active_work: ModuleWorkRef | None = None
    active_publication_id: str | None = None
    active_grade_item_id: str | None = None
    active_student_id: str | None = None

    def select_class(self, class_id: str) -> None:
        """Select one class and clear dependent context when it changes."""
        checked = _identifier(class_id, "class_id")
        if self.active_class_id == checked:
            return
        self.active_class_id = checked
        self._clear_below_class()

    def select_work(self, work: ModuleWorkRef) -> None:
        """Select one exact work reference and clear its dependent context."""
        if not isinstance(work, ModuleWorkRef):
            raise TeacherSessionContextError("work must be a ModuleWorkRef.")
        if self.active_work == work:
            return
        self.select_class(work.class_id)
        self.active_work = work
        self._clear_below_work()

    def select_publication(self, publication_id: str) -> None:
        """Select one publication for the active work."""
        if self.active_work is None:
            raise TeacherSessionContextError(
                "publication selection requires active work context."
            )
        checked = _identifier(publication_id, "publication_id")
        if self.active_publication_id == checked:
            return
        self.active_publication_id = checked
        self._clear_below_publication()

    def select_grade_item(self, grade_item_id: str) -> None:
        """Select one Grade Item for the active class."""
        if self.active_class_id is None:
            raise TeacherSessionContextError(
                "Grade Item selection requires active class context."
            )
        checked = _identifier(grade_item_id, "grade_item_id")
        if self.active_grade_item_id == checked:
            return
        self.active_grade_item_id = checked
        self.active_student_id = None

    def select_student(self, student_id: str) -> None:
        """Select one exact roster identity for the active class."""
        if self.active_class_id is None:
            raise TeacherSessionContextError(
                "student selection requires active class context."
            )
        self.active_student_id = _identifier(student_id, "student_id")

    def clear_student(self) -> None:
        """Clear only active student context."""
        self.active_student_id = None

    def clear_grade_item(self) -> None:
        """Clear Grade Item context and dependent student context."""
        self.active_grade_item_id = None
        self.active_student_id = None

    def clear_publication(self) -> None:
        """Clear publication context and all downstream context."""
        self.active_publication_id = None
        self._clear_below_publication()

    def clear_work(self) -> None:
        """Clear work context while retaining the active class."""
        self.active_work = None
        self._clear_below_work()

    def clear(self) -> None:
        """Discard the entire process-local context."""
        self.active_class_id = None
        self._clear_below_class()

    def _clear_below_class(self) -> None:
        self.active_work = None
        self._clear_below_work()

    def _clear_below_work(self) -> None:
        self.active_publication_id = None
        self._clear_below_publication()

    def _clear_below_publication(self) -> None:
        self.active_grade_item_id = None
        self.active_student_id = None


__all__ = ("TeacherSessionContext", "TeacherSessionContextError")
