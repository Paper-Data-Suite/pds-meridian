"""Teacher-facing workflow catalog for Meridian issue #41.

This module defines the stable presentation identity for the seven task-oriented
teacher workflows. Task-specific application controllers remain separate from
terminal rendering and reuse the canonical #27-#40 services for discovery,
revision writes, explicit selection, calculation, review, and export.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

TeacherWorkflowTaskId: TypeAlias = Literal[
    "new-evidence",
    "grade-items",
    "attempt-decisions",
    "exclusions",
    "standards-review",
    "calculation-preview",
    "create-planning-signal",
]

TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION: Final = 1
TEACHER_WORKFLOW_TASK_IDS: Final[tuple[TeacherWorkflowTaskId, ...]] = (
    "new-evidence",
    "grade-items",
    "attempt-decisions",
    "exclusions",
    "standards-review",
    "calculation-preview",
    "create-planning-signal",
)


def _bounded_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string.")
    if not value or value != value.strip():
        raise ValueError(f"{field} must be nonblank without surrounding whitespace.")
    if "\x00" in value:
        raise ValueError(f"{field} must not contain NUL.")
    if len(value) > maximum:
        raise ValueError(f"{field} must be at most {maximum} characters.")
    return value


@dataclass(frozen=True, slots=True)
class TeacherWorkflowDescriptor:
    """Stable teacher-facing identity and scope for one issue #41 workflow."""

    task_id: TeacherWorkflowTaskId
    title: str
    summary: str
    write_boundary: str

    def __post_init__(self) -> None:
        if self.task_id not in TEACHER_WORKFLOW_TASK_IDS:
            raise ValueError(f"Unsupported teacher workflow task: {self.task_id!r}.")
        _bounded_text(self.title, "title", maximum=80)
        _bounded_text(self.summary, "summary", maximum=240)
        _bounded_text(self.write_boundary, "write_boundary", maximum=200)


@dataclass(frozen=True, slots=True)
class TeacherWorkflowCatalog:
    """Deterministic presentation projection of the issue #41 task surface."""

    schema_version: int
    tasks: tuple[TeacherWorkflowDescriptor, ...]

    def __post_init__(self) -> None:
        if self.schema_version != TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION:
            raise ValueError(
                "Teacher workflow catalog schema_version must be "
                f"{TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION}."
            )
        actual = tuple(task.task_id for task in self.tasks)
        if actual != TEACHER_WORKFLOW_TASK_IDS:
            raise ValueError(
                "Teacher workflow catalog tasks must exactly match the canonical "
                "issue #41 task order."
            )


_TEACHER_WORKFLOW_DESCRIPTORS: Final = (
    TeacherWorkflowDescriptor(
        task_id="new-evidence",
        title="New Evidence",
        summary=(
            "Review newly available, unresolved, stale, unsupported, superseded, "
            "or withdrawn evidence and route it to the next explicit teacher decision."
        ),
        write_boundary=(
            "Discovery is read-only; later task actions may create/select explicit "
            "Meridian membership or eligibility revisions."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="grade-items",
        title="Grade Items",
        summary=(
            "Review and manage Grade Item revisions, registered-work membership, and "
            "explicit Core Academic Period assignment."
        ),
        write_boundary=(
            "Revision writes and current selection remain separate explicit actions."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="attempt-decisions",
        title="Attempt Decisions",
        summary=(
            "Resolve applicable attempt selection and reassessment relationships "
            "without automatic highest/latest/best preference."
        ),
        write_boundary=(
            "Attempt/reassessment revisions and current selection require explicit "
            "teacher action."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="exclusions",
        title="Exclusions",
        summary=(
            "Review evidence eligibility while preserving included, excluded, pending, "
            "unsupported, superseded, and withdrawn distinctions."
        ),
        write_boundary=(
            "Academic eligibility revisions may be teacher-authored; Core source "
            "withdrawal/supersession authority is never rewritten."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="standards-review",
        title="Standards Review",
        summary=(
            "Review standards associations and exact native-value mapping context "
            "before evidence becomes bounded proficiency input."
        ),
        write_boundary=(
            "Standards-association revisions are explicit; mapping profiles are never "
            "silently selected by similarity."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="calculation-preview",
        title="Calculation Preview",
        summary=(
            "Preview Grade Item or Academic Period standards proficiency before any "
            "immutable result is persisted or selected."
        ),
        write_boundary=(
            "Preview is read-only; result persistence and current-result selection are "
            "separate confirmations."
        ),
    ),
    TeacherWorkflowDescriptor(
        task_id="create-planning-signal",
        title="Create Planning Signal",
        summary=(
            "Guide policy, derivation, preview/review, explicit review selection, "
            "Core/receipt export, and optional Core-native CSV without invoking "
            "Concord."
        ),
        write_boundary=(
            "Generation, review acceptance, review selection, Core/receipt export, "
            "and optional CSV remain deliberate stages; no Concord state is created."
        ),
    ),
)


def teacher_workflow_catalog() -> TeacherWorkflowCatalog:
    """Return the deterministic read-only issue #41 task catalog."""

    return TeacherWorkflowCatalog(
        schema_version=TEACHER_WORKFLOW_CATALOG_SCHEMA_VERSION,
        tasks=_TEACHER_WORKFLOW_DESCRIPTORS,
    )


def teacher_workflow_catalog_to_dict(
    catalog: TeacherWorkflowCatalog,
) -> dict[str, object]:
    """Return a deterministic JSON-ready representation of the task catalog."""

    if not isinstance(catalog, TeacherWorkflowCatalog):
        raise TypeError("catalog must be a TeacherWorkflowCatalog.")
    catalog.__post_init__()
    return {
        "schema_version": catalog.schema_version,
        "tasks": [
            {
                "task_id": task.task_id,
                "title": task.title,
                "summary": task.summary,
                "write_boundary": task.write_boundary,
            }
            for task in catalog.tasks
        ],
    }
