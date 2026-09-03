"""Explicit immutable Academic Period proficiency result persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meridian.academic_period_calculation_assembly_workflow import (
    AcademicPeriodCalculationAssemblyError,
    BoundedAcademicPeriodCalculationPreview,
    build_bounded_academic_period_calculation_preview,
)
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencyValidationError,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyResultWriteResult,
    AcademicPeriodProficiencyStorageError,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_result_revisions,
    load_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_result_revision,
)

_MAXIMUM_WORKFLOW_ACTOR_ID_LENGTH = 256


class AcademicPeriodResultPersistenceError(RuntimeError):
    """Base teacher-workflow failure for explicit #35 result persistence."""

    code = "teacher_workflow.calculation_preview.academic_period_result_error"


class AcademicPeriodResultPersistenceScopeError(
    AcademicPeriodResultPersistenceError,
    ValueError,
):
    """Raised when explicit #35 result-persistence workflow context is invalid."""

    code = "teacher_workflow.calculation_preview.academic_period_result_invalid"


class AcademicPeriodResultPersistenceStaleError(
    AcademicPeriodResultPersistenceError
):
    """Raised when reviewed #35 calculation/history changes before write."""

    code = "teacher_workflow.calculation_preview.academic_period_result_stale"


@dataclass(frozen=True, slots=True)
class AcademicPeriodResultPersistencePreview:
    """Exact reviewed #35 calculation and immutable next-result candidate."""

    actor_id: str
    reviewed: BoundedAcademicPeriodCalculationPreview
    candidate: AcademicPeriodProficiencyResultSnapshot
    history_before: tuple[int, ...]
    latest_result_sha256_before: str | None
    selected_revision_before: int | None

    @property
    def candidate_revision(self) -> int:
        return self.candidate.result_revision

    @property
    def candidate_status(self) -> str:
        return self.candidate.outcome.status

    @property
    def candidate_proficiency_level_id(self) -> str | None:
        return self.candidate.outcome.proficiency_level_id

    @property
    def candidate_calculation_fingerprint(self) -> str:
        return self.candidate.calculation_fingerprint

    @property
    def selection_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class AcademicPeriodResultPersistenceWorkflowResult:
    """Immutable #35 result write receipt; selection remains independent."""

    preview: AcademicPeriodResultPersistencePreview
    write_result: AcademicPeriodProficiencyResultWriteResult
    selected_revision_after_write: int | None

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.snapshot.result_revision

    @property
    def written_result_sha256(self) -> str:
        return self.write_result.stored.result_sha256

    @property
    def written_status(self) -> str:
        return self.write_result.stored.snapshot.outcome.status

    @property
    def written_proficiency_level_id(self) -> str | None:
        return self.write_result.stored.snapshot.outcome.proficiency_level_id

    @property
    def selection_changed_during_write(self) -> bool:
        return (
            self.selected_revision_after_write
            != self.preview.selected_revision_before
        )

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_academic_period_result_persistence(
    workspace_root: str | Path,
    reviewed: BoundedAcademicPeriodCalculationPreview,
    *,
    actor_id: str,
    calculated_at: datetime,
) -> AcademicPeriodResultPersistencePreview:
    """Freeze one exact reviewed #35 calculation as the next result revision."""
    actor = _actor_id(actor_id)
    if not isinstance(reviewed, BoundedAcademicPeriodCalculationPreview):
        raise AcademicPeriodResultPersistenceScopeError(
            "reviewed must be a BoundedAcademicPeriodCalculationPreview."
        )
    if reviewed.result_write_performed or reviewed.result_selection_performed:
        raise AcademicPeriodResultPersistenceScopeError(
            "reviewed Academic Period calculation must be read-only."
        )

    history, latest_digest, selected = _result_state(
        workspace_root,
        reviewed,
    )
    if history != reviewed.calculation.result_history:
        raise AcademicPeriodResultPersistenceStaleError(
            "Persisted Academic Period result history changed after preview."
        )
    if selected != reviewed.calculation.current_result_revision:
        raise AcademicPeriodResultPersistenceStaleError(
            "Current Academic Period result selection changed after preview."
        )

    try:
        candidate = create_academic_period_proficiency_result_snapshot(
            reviewed.inputs,
            reviewed.calculation.outcome,
            result_revision=reviewed.calculation.next_result_revision,
            calculated_at=calculated_at,
        )
    except AcademicPeriodProficiencyValidationError as error:
        raise AcademicPeriodResultPersistenceScopeError(str(error)) from error

    return AcademicPeriodResultPersistencePreview(
        actor_id=actor,
        reviewed=reviewed,
        candidate=candidate,
        history_before=history,
        latest_result_sha256_before=latest_digest,
        selected_revision_before=selected,
    )


def commit_academic_period_result_persistence_preview(
    workspace_root: str | Path,
    preview: AcademicPeriodResultPersistencePreview,
) -> AcademicPeriodResultPersistenceWorkflowResult:
    """Live-revalidate exact #35 calculation, then write only that snapshot."""
    if not isinstance(preview, AcademicPeriodResultPersistencePreview):
        raise AcademicPeriodResultPersistenceScopeError(
            "preview must be an AcademicPeriodResultPersistencePreview."
        )

    reviewed = preview.reviewed
    try:
        fresh = build_bounded_academic_period_calculation_preview(
            workspace_root,
            reviewed.target_period,
            reviewed.inputs.student_id,
            reviewed.inputs.standard_id,
            reviewed.candidate_specs,
            reviewed.calculation.policy_reference,
        )
    except AcademicPeriodCalculationAssemblyError as error:
        raise AcademicPeriodResultPersistenceStaleError(str(error)) from error

    if fresh.target_period != reviewed.target_period:
        raise AcademicPeriodResultPersistenceStaleError(
            "Academic Period target changed after result persistence preview."
        )
    if fresh.candidate_specs != reviewed.candidate_specs:
        raise AcademicPeriodResultPersistenceStaleError(
            "Exact Academic Period candidate specifications changed after preview."
        )
    if fresh.inputs != reviewed.inputs:
        raise AcademicPeriodResultPersistenceStaleError(
            "Exact Academic Period aggregation inputs changed after preview."
        )
    if (
        fresh.calculation.policy_reference
        != reviewed.calculation.policy_reference
    ):
        raise AcademicPeriodResultPersistenceStaleError(
            "Academic Period calculation-policy reference changed after preview."
        )
    if fresh.calculation.outcome != reviewed.calculation.outcome:
        raise AcademicPeriodResultPersistenceStaleError(
            "Pure Academic Period proficiency outcome changed after preview."
        )

    history, latest_digest, _ = _result_state(workspace_root, fresh)
    if history != preview.history_before:
        raise AcademicPeriodResultPersistenceStaleError(
            "Persisted Academic Period result history changed after "
            "persistence preview."
        )
    if latest_digest != preview.latest_result_sha256_before:
        raise AcademicPeriodResultPersistenceStaleError(
            "Latest Academic Period result digest changed after persistence preview."
        )

    try:
        candidate = create_academic_period_proficiency_result_snapshot(
            fresh.inputs,
            fresh.calculation.outcome,
            result_revision=preview.candidate.result_revision,
            calculated_at=preview.candidate.calculated_at,
        )
    except AcademicPeriodProficiencyValidationError as error:
        raise AcademicPeriodResultPersistenceStaleError(str(error)) from error
    if candidate != preview.candidate:
        raise AcademicPeriodResultPersistenceStaleError(
            "Revalidated Academic Period result differs from reviewed candidate."
        )

    try:
        write_result = write_academic_period_proficiency_result_revision(
            workspace_root,
            preview.candidate,
        )
        selected_after = get_current_academic_period_proficiency_result_revision(
            workspace_root,
            preview.candidate.class_id,
            preview.candidate.target_period.period.school_year,
            preview.candidate.target_period.period.period_id,
            preview.candidate.student_id,
            preview.candidate.standard_id,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultPersistenceStaleError(str(error)) from error

    if write_result.stored.snapshot != preview.candidate:
        raise AcademicPeriodResultPersistenceStaleError(
            "Persisted Academic Period result differs from previewed candidate."
        )

    return AcademicPeriodResultPersistenceWorkflowResult(
        preview=preview,
        write_result=write_result,
        selected_revision_after_write=selected_after,
    )


def _result_state(
    workspace_root: str | Path,
    reviewed: BoundedAcademicPeriodCalculationPreview,
) -> tuple[tuple[int, ...], str | None, int | None]:
    period = reviewed.target_period.period
    try:
        history = list_academic_period_proficiency_result_revisions(
            workspace_root,
            reviewed.inputs.class_id,
            period.school_year,
            period.period_id,
            reviewed.inputs.student_id,
            reviewed.inputs.standard_id,
        )
        latest_digest = (
            None
            if not history
            else load_academic_period_proficiency_result_revision(
                workspace_root,
                reviewed.inputs.class_id,
                period.school_year,
                period.period_id,
                reviewed.inputs.student_id,
                reviewed.inputs.standard_id,
                history[-1],
            ).result_sha256
        )
        selected = get_current_academic_period_proficiency_result_revision(
            workspace_root,
            reviewed.inputs.class_id,
            period.school_year,
            period.period_id,
            reviewed.inputs.student_id,
            reviewed.inputs.standard_id,
        )
    except AcademicPeriodProficiencyStorageError as error:
        raise AcademicPeriodResultPersistenceStaleError(str(error)) from error
    return history, latest_digest, selected


def _actor_id(value: str) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodResultPersistenceScopeError(
            "actor_id must be a string."
        )
    normalized = value.strip()
    if not normalized:
        raise AcademicPeriodResultPersistenceScopeError(
            "actor_id must be nonempty."
        )
    if len(normalized) > _MAXIMUM_WORKFLOW_ACTOR_ID_LENGTH:
        raise AcademicPeriodResultPersistenceScopeError(
            "actor_id exceeds the teacher-workflow bound."
        )
    return normalized
