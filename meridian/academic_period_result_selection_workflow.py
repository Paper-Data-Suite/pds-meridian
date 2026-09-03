"""Explicit current selection of one persisted Academic Period result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyResultSelectionResult,
    AcademicPeriodProficiencyStorageConflictError,
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_result_revisions,
    load_academic_period_proficiency_result_revision,
    select_academic_period_proficiency_result_revision,
)


class AcademicPeriodResultSelectionError(RuntimeError):
    """Base teacher-workflow failure for #35 result current selection."""

    code = "teacher_workflow.calculation_preview.academic_period_selection_error"


class AcademicPeriodResultSelectionScopeError(
    AcademicPeriodResultSelectionError,
    ValueError,
):
    """Raised when an exact #35 result-selection scope is invalid."""

    code = "teacher_workflow.calculation_preview.academic_period_selection_invalid"


class AcademicPeriodResultSelectionStaleError(
    AcademicPeriodResultSelectionError
):
    """Raised when reviewed #35 history/target/current state changes."""

    code = "teacher_workflow.calculation_preview.academic_period_selection_stale"


@dataclass(frozen=True, slots=True)
class AcademicPeriodResultSelectionPreview:
    """Exact persisted historical #35 result targeted for current selection."""

    target: StoredAcademicPeriodProficiencyResult
    history: tuple[int, ...]
    expected_current_result_revision: int | None

    @property
    def class_id(self) -> str:
        return self.target.snapshot.class_id

    @property
    def school_year(self) -> str:
        return self.target.snapshot.target_period.period.school_year

    @property
    def period_id(self) -> str:
        return self.target.snapshot.target_period.period.period_id

    @property
    def calendar_revision(self) -> int:
        return self.target.snapshot.target_period.calendar_revision

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
class AcademicPeriodResultSelectionWorkflowResult:
    """Canonical #35 current-pointer selection receipt."""

    preview: AcademicPeriodResultSelectionPreview
    selection_result: AcademicPeriodProficiencyResultSelectionResult
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


def preview_academic_period_result_selection(
    workspace_root: str | Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
    result_revision: int,
) -> AcademicPeriodResultSelectionPreview:
    """Freeze exact #35 history, target result, and current pointer."""
    if not isinstance(result_revision, int) or isinstance(result_revision, bool):
        raise AcademicPeriodResultSelectionScopeError(
            "result_revision must be a positive integer."
        )
    if result_revision <= 0:
        raise AcademicPeriodResultSelectionScopeError(
            "result_revision must be a positive integer."
        )

    try:
        history = list_academic_period_proficiency_result_revisions(
            workspace_root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
        if result_revision not in history:
            raise AcademicPeriodResultSelectionScopeError(
                "Target Academic Period result revision must be an exact "
                "persisted historical revision."
            )
        target = load_academic_period_proficiency_result_revision(
            workspace_root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
            result_revision,
        )
        current = get_current_academic_period_proficiency_result_revision(
            workspace_root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
    except AcademicPeriodResultSelectionScopeError:
        raise
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultSelectionError(str(error)) from error

    snapshot = target.snapshot
    period = snapshot.target_period.period
    if (
        snapshot.class_id != class_id
        or period.school_year != school_year
        or period.period_id != period_id
        or snapshot.student_id != student_id
        or snapshot.standard_id != standard_id
        or snapshot.result_revision != result_revision
    ):
        raise AcademicPeriodResultSelectionError(
            "Loaded Academic Period result identity does not match requested "
            "selection scope."
        )

    return AcademicPeriodResultSelectionPreview(
        target=target,
        history=history,
        expected_current_result_revision=current,
    )


def commit_academic_period_result_selection_preview(
    workspace_root: str | Path,
    preview: AcademicPeriodResultSelectionPreview,
) -> AcademicPeriodResultSelectionWorkflowResult:
    """Live-revalidate exact #35 target/history, then mutate only selection."""
    if not isinstance(preview, AcademicPeriodResultSelectionPreview):
        raise AcademicPeriodResultSelectionScopeError(
            "preview must be an AcademicPeriodResultSelectionPreview."
        )

    try:
        history = list_academic_period_proficiency_result_revisions(
            workspace_root,
            preview.class_id,
            preview.school_year,
            preview.period_id,
            preview.student_id,
            preview.standard_id,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultSelectionStaleError(str(error)) from error
    if history != preview.history:
        raise AcademicPeriodResultSelectionStaleError(
            "Persisted Academic Period result history changed after "
            "selection preview."
        )

    try:
        target = load_academic_period_proficiency_result_revision(
            workspace_root,
            preview.class_id,
            preview.school_year,
            preview.period_id,
            preview.student_id,
            preview.standard_id,
            preview.target_revision,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultSelectionStaleError(str(error)) from error
    if (
        target.result_sha256 != preview.target.result_sha256
        or target.content != preview.target.content
        or target.snapshot != preview.target.snapshot
    ):
        raise AcademicPeriodResultSelectionStaleError(
            "Target Academic Period proficiency result changed after "
            "selection preview."
        )

    try:
        result = select_academic_period_proficiency_result_revision(
            workspace_root,
            preview.class_id,
            preview.school_year,
            preview.period_id,
            preview.student_id,
            preview.standard_id,
            preview.target_revision,
            expected_current_result_revision=(
                preview.expected_current_result_revision
            ),
        )
    except AcademicPeriodProficiencyStorageConflictError as error:
        raise AcademicPeriodResultSelectionStaleError(str(error)) from error
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultSelectionError(str(error)) from error

    if (
        result.stored.result_sha256 != preview.target.result_sha256
        or result.stored.snapshot != preview.target.snapshot
    ):
        raise AcademicPeriodResultSelectionError(
            "Canonical Academic Period selector returned a different "
            "persisted target."
        )

    return AcademicPeriodResultSelectionWorkflowResult(
        preview=preview,
        selection_result=result,
        previous_current_result_revision=(
            preview.expected_current_result_revision
        ),
    )
