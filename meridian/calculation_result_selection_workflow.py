"""Explicit current selection of one persisted Grade Item proficiency result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.standards_proficiency_storage import (
    StandardProficiencyResultSelectionResult,
    StandardProficiencyStorageConflictError,
    StandardProficiencyStorageError,
    StoredStandardProficiencyResult,
    get_current_standard_proficiency_result_revision,
    list_standard_proficiency_result_revisions,
    load_standard_proficiency_result_revision,
    select_standard_proficiency_result_revision,
)


class CalculationResultSelectionError(RuntimeError):
    """Base teacher-workflow failure for #34 result current selection."""

    code = "teacher_workflow.calculation_preview.result_selection_error"


class CalculationResultSelectionScopeError(
    CalculationResultSelectionError,
    ValueError,
):
    """Raised when an exact result-selection scope is invalid."""

    code = "teacher_workflow.calculation_preview.result_selection_invalid"


class CalculationResultSelectionStaleError(CalculationResultSelectionError):
    """Raised when reviewed result history/target/current state changes."""

    code = "teacher_workflow.calculation_preview.result_selection_stale"


@dataclass(frozen=True, slots=True)
class CalculationResultSelectionPreview:
    """Exact persisted historical result targeted for current selection."""

    target: StoredStandardProficiencyResult
    history: tuple[int, ...]
    expected_current_result_revision: int | None

    @property
    def class_id(self) -> str:
        return self.target.snapshot.class_id

    @property
    def grade_item_id(self) -> str:
        return self.target.snapshot.grade_item_id

    @property
    def student_id(self) -> str:
        return self.target.snapshot.student_id

    @property
    def standard_id(self) -> str:
        return self.target.snapshot.standard_id

    @property
    def target_revision(self) -> int:
        return self.target.snapshot.result_revision

    @property
    def target_result_sha256(self) -> str:
        return self.target.result_sha256

    @property
    def target_status(self) -> str:
        return self.target.snapshot.outcome.status

    @property
    def target_proficiency_level_id(self) -> str | None:
        return self.target.snapshot.outcome.proficiency_level_id

    @property
    def target_calculation_fingerprint(self) -> str:
        return self.target.snapshot.calculation_fingerprint

    @property
    def target_is_latest(self) -> bool:
        return bool(self.history) and self.target_revision == self.history[-1]

    @property
    def authoring_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class CalculationResultSelectionWorkflowResult:
    """Canonical #34 current-pointer selection receipt."""

    preview: CalculationResultSelectionPreview
    selection_result: StandardProficiencyResultSelectionResult
    previous_current_result_revision: int | None

    @property
    def selected_revision(self) -> int:
        return self.selection_result.stored.snapshot.result_revision

    @property
    def selected_result_sha256(self) -> str:
        return self.selection_result.stored.result_sha256

    @property
    def selected_status(self) -> str:
        return self.selection_result.stored.snapshot.outcome.status

    @property
    def selected_proficiency_level_id(self) -> str | None:
        return self.selection_result.stored.snapshot.outcome.proficiency_level_id

    @property
    def selection_disposition(self) -> str:
        return self.selection_result.disposition

    @property
    def authoring_action(self) -> str:
        return "not_performed"


def preview_calculation_result_selection(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> CalculationResultSelectionPreview:
    """Freeze exact history, target result, and current pointer for selection."""
    if not isinstance(result_revision, int) or isinstance(result_revision, bool):
        raise CalculationResultSelectionScopeError(
            "result_revision must be a positive integer."
        )
    if result_revision <= 0:
        raise CalculationResultSelectionScopeError(
            "result_revision must be a positive integer."
        )

    try:
        history = list_standard_proficiency_result_revisions(
            workspace_root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
        )
        if result_revision not in history:
            raise CalculationResultSelectionScopeError(
                "Target result revision must be an exact persisted historical revision."
            )
        target = load_standard_proficiency_result_revision(
            workspace_root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            result_revision,
        )
        current = get_current_standard_proficiency_result_revision(
            workspace_root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
        )
    except CalculationResultSelectionScopeError:
        raise
    except StandardProficiencyStorageError as error:
        raise CalculationResultSelectionError(str(error)) from error

    snapshot = target.snapshot
    if (
        snapshot.class_id != class_id
        or snapshot.grade_item_id != grade_item_id
        or snapshot.student_id != student_id
        or snapshot.standard_id != standard_id
        or snapshot.result_revision != result_revision
    ):
        raise CalculationResultSelectionError(
            "Loaded result identity does not match requested selection scope."
        )

    return CalculationResultSelectionPreview(
        target=target,
        history=history,
        expected_current_result_revision=current,
    )


def commit_calculation_result_selection_preview(
    workspace_root: str | Path,
    preview: CalculationResultSelectionPreview,
) -> CalculationResultSelectionWorkflowResult:
    """Live-revalidate exact target/history, then mutate only current selection."""
    if not isinstance(preview, CalculationResultSelectionPreview):
        raise CalculationResultSelectionScopeError(
            "preview must be a CalculationResultSelectionPreview."
        )

    try:
        history = list_standard_proficiency_result_revisions(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.student_id,
            preview.standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise CalculationResultSelectionStaleError(str(error)) from error
    if history != preview.history:
        raise CalculationResultSelectionStaleError(
            "Persisted result history changed after selection preview."
        )

    try:
        target = load_standard_proficiency_result_revision(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.student_id,
            preview.standard_id,
            preview.target_revision,
        )
    except StandardProficiencyStorageError as error:
        raise CalculationResultSelectionStaleError(str(error)) from error
    if (
        target.result_sha256 != preview.target.result_sha256
        or target.content != preview.target.content
        or target.snapshot != preview.target.snapshot
    ):
        raise CalculationResultSelectionStaleError(
            "Target proficiency result changed after selection preview."
        )

    try:
        result = select_standard_proficiency_result_revision(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.student_id,
            preview.standard_id,
            preview.target_revision,
            expected_current_result_revision=(
                preview.expected_current_result_revision
            ),
        )
    except StandardProficiencyStorageConflictError as error:
        raise CalculationResultSelectionStaleError(str(error)) from error
    except StandardProficiencyStorageError as error:
        raise CalculationResultSelectionError(str(error)) from error

    if (
        result.stored.result_sha256 != preview.target.result_sha256
        or result.stored.snapshot != preview.target.snapshot
    ):
        raise CalculationResultSelectionError(
            "Canonical selector returned a different persisted target."
        )

    return CalculationResultSelectionWorkflowResult(
        preview=preview,
        selection_result=result,
        previous_current_result_revision=(
            preview.expected_current_result_revision
        ),
    )
