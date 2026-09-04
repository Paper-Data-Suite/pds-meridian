"""Explicit immutable Grade Item standards-proficiency result persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meridian.calculation_preview_assembly_workflow import (
    BoundedCalculationPreview,
    CalculationPreviewAssemblyError,
    build_bounded_calculation_preview,
)
from meridian.standards_proficiency import (
    MAXIMUM_STANDARD_PROFICIENCY_ACTOR_ID_LENGTH,
    StandardProficiencyResultSnapshot,
    StandardProficiencyValidationError,
    create_standard_proficiency_result_snapshot,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyResultWriteResult,
    StandardProficiencyStorageError,
    get_current_standard_proficiency_result_revision,
    list_standard_proficiency_result_revisions,
    load_standard_proficiency_result_revision,
    write_standard_proficiency_result_revision,
)


class CalculationResultPersistenceError(RuntimeError):
    """Base teacher-workflow failure for explicit #34 result persistence."""

    code = "teacher_workflow.calculation_preview.result_persistence_error"


class CalculationResultPersistenceScopeError(
    CalculationResultPersistenceError,
    ValueError,
):
    """Raised when explicit result-persistence workflow context is invalid."""

    code = "teacher_workflow.calculation_preview.result_persistence_invalid"


class CalculationResultPersistenceStaleError(
    CalculationResultPersistenceError
):
    """Raised when reviewed calculation/history changes before result write."""

    code = "teacher_workflow.calculation_preview.result_persistence_stale"


@dataclass(frozen=True, slots=True)
class CalculationResultPersistencePreview:
    """Exact reviewed calculation and immutable next-result candidate."""

    actor_id: str
    reviewed: BoundedCalculationPreview
    candidate: StandardProficiencyResultSnapshot
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
class CalculationResultPersistenceWorkflowResult:
    """Immutable result write receipt; selection remains independent."""

    preview: CalculationResultPersistencePreview
    write_result: StandardProficiencyResultWriteResult
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


def preview_calculation_result_persistence(
    workspace_root: str | Path,
    reviewed: BoundedCalculationPreview,
    *,
    actor_id: str,
    calculated_at: datetime,
) -> CalculationResultPersistencePreview:
    """Freeze one exact reviewed #34 calculation as the next result revision."""
    actor = _actor_id(actor_id)
    if not isinstance(reviewed, BoundedCalculationPreview):
        raise CalculationResultPersistenceScopeError(
            "reviewed must be a BoundedCalculationPreview."
        )
    if reviewed.result_write_performed or reviewed.result_selection_performed:
        raise CalculationResultPersistenceScopeError(
            "reviewed calculation must be a read-only Calculation Preview."
        )

    history, latest_digest, selected = _result_state(
        workspace_root,
        reviewed,
    )
    if history != reviewed.calculation.result_history:
        raise CalculationResultPersistenceStaleError(
            "Persisted result history changed after Calculation Preview."
        )
    if selected != reviewed.calculation.current_result_revision:
        raise CalculationResultPersistenceStaleError(
            "Current result selection changed after Calculation Preview."
        )

    try:
        candidate = create_standard_proficiency_result_snapshot(
            reviewed.inputs,
            reviewed.calculation.outcome,
            result_revision=reviewed.calculation.next_result_revision,
            calculated_at=calculated_at,
        )
    except StandardProficiencyValidationError as error:
        raise CalculationResultPersistenceScopeError(str(error)) from error

    return CalculationResultPersistencePreview(
        actor_id=actor,
        reviewed=reviewed,
        candidate=candidate,
        history_before=history,
        latest_result_sha256_before=latest_digest,
        selected_revision_before=selected,
    )


def commit_calculation_result_persistence_preview(
    workspace_root: str | Path,
    preview: CalculationResultPersistencePreview,
) -> CalculationResultPersistenceWorkflowResult:
    """Live-revalidate the exact reviewed calculation, then write only it."""
    if not isinstance(preview, CalculationResultPersistencePreview):
        raise CalculationResultPersistenceScopeError(
            "preview must be a CalculationResultPersistencePreview."
        )

    reviewed = preview.reviewed
    try:
        fresh = build_bounded_calculation_preview(
            workspace_root,
            reviewed.grade_item_id,
            reviewed.student_id,
            reviewed.standard_id,
            reviewed.inputs.target_scale,
            reviewed.bindings,
            reviewed.calculation.policy_reference,
        )
    except CalculationPreviewAssemblyError as error:
        raise CalculationResultPersistenceStaleError(str(error)) from error

    if fresh.grade_item_basis != reviewed.grade_item_basis:
        raise CalculationResultPersistenceStaleError(
            "Selected Grade Item basis changed after result persistence preview."
        )
    if fresh.source_keys != reviewed.source_keys:
        raise CalculationResultPersistenceStaleError(
            "Explicit evidence binding identity changed after preview."
        )
    if fresh.inputs != reviewed.inputs:
        raise CalculationResultPersistenceStaleError(
            "Exact standards aggregation inputs changed after preview."
        )
    if (
        fresh.calculation.policy_reference
        != reviewed.calculation.policy_reference
    ):
        raise CalculationResultPersistenceStaleError(
            "Calculation-policy reference changed after preview."
        )
    if fresh.calculation.outcome != reviewed.calculation.outcome:
        raise CalculationResultPersistenceStaleError(
            "Pure proficiency calculation outcome changed after preview."
        )

    history, latest_digest, _ = _result_state(
        workspace_root,
        fresh,
    )
    if history != preview.history_before:
        raise CalculationResultPersistenceStaleError(
            "Persisted result history changed after persistence preview."
        )
    if latest_digest != preview.latest_result_sha256_before:
        raise CalculationResultPersistenceStaleError(
            "Latest persisted result digest changed after persistence preview."
        )

    try:
        candidate = create_standard_proficiency_result_snapshot(
            fresh.inputs,
            fresh.calculation.outcome,
            result_revision=preview.candidate.result_revision,
            calculated_at=preview.candidate.calculated_at,
        )
    except StandardProficiencyValidationError as error:
        raise CalculationResultPersistenceStaleError(str(error)) from error
    if candidate != preview.candidate:
        raise CalculationResultPersistenceStaleError(
            "Revalidated result candidate differs from the reviewed candidate."
        )

    try:
        write_result = write_standard_proficiency_result_revision(
            workspace_root,
            preview.candidate,
        )
        selected_after = get_current_standard_proficiency_result_revision(
            workspace_root,
            preview.candidate.class_id,
            preview.candidate.grade_item_id,
            preview.candidate.student_id,
            preview.candidate.standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise CalculationResultPersistenceStaleError(str(error)) from error

    if write_result.stored.snapshot != preview.candidate:
        raise CalculationResultPersistenceStaleError(
            "Persisted result snapshot differs from exact previewed candidate."
        )

    return CalculationResultPersistenceWorkflowResult(
        preview=preview,
        write_result=write_result,
        selected_revision_after_write=selected_after,
    )


def _result_state(
    workspace_root: str | Path,
    reviewed: BoundedCalculationPreview,
) -> tuple[tuple[int, ...], str | None, int | None]:
    try:
        history = list_standard_proficiency_result_revisions(
            workspace_root,
            reviewed.class_id,
            reviewed.grade_item_id,
            reviewed.student_id,
            reviewed.standard_id,
        )
        latest_digest = (
            None
            if not history
            else load_standard_proficiency_result_revision(
                workspace_root,
                reviewed.class_id,
                reviewed.grade_item_id,
                reviewed.student_id,
                reviewed.standard_id,
                history[-1],
            ).result_sha256
        )
        selected = get_current_standard_proficiency_result_revision(
            workspace_root,
            reviewed.class_id,
            reviewed.grade_item_id,
            reviewed.student_id,
            reviewed.standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise CalculationResultPersistenceStaleError(str(error)) from error
    return history, latest_digest, selected


def _actor_id(value: str) -> str:
    if not isinstance(value, str):
        raise CalculationResultPersistenceScopeError(
            "actor_id must be a string."
        )
    normalized = value.strip()
    if not normalized:
        raise CalculationResultPersistenceScopeError(
            "actor_id must be nonempty."
        )
    if len(normalized) > MAXIMUM_STANDARD_PROFICIENCY_ACTOR_ID_LENGTH:
        raise CalculationResultPersistenceScopeError(
            "actor_id exceeds the standards-proficiency actor bound."
        )
    return normalized
