"""Explicit #39 preview-generation stage for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
    GroupingSignalDerivationValidationError,
)
from meridian.grouping_signal_preview_generation import (
    GroupingSignalPreviewGenerationError,
    GroupingSignalPreviewGenerationResult,
    generate_grouping_signal_preview,
)


class PlanningSignalPreviewGenerationError(RuntimeError):
    """Base failure for the explicit #39 preview-generation stage."""

    code = "teacher_workflow.create_planning_signal.preview_error"


class PlanningSignalPreviewGenerationScopeError(
    PlanningSignalPreviewGenerationError,
    ValueError,
):
    """Raised when the exact #38 preview source reference is invalid."""

    code = "teacher_workflow.create_planning_signal.preview_invalid"


class PlanningSignalPreviewGenerationDependencyError(
    PlanningSignalPreviewGenerationError
):
    """Raised when canonical #39 generation cannot read/verify dependencies."""

    code = "teacher_workflow.create_planning_signal.preview_dependency_error"


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewGenerationWorkflowResult:
    """One exact immutable #39 preview write and teacher-task summary."""

    derivation_reference: GroupingSignalDerivationReference
    generation_result: GroupingSignalPreviewGenerationResult

    def __post_init__(self) -> None:
        if not isinstance(
            self.derivation_reference,
            GroupingSignalDerivationReference,
        ):
            raise PlanningSignalPreviewGenerationScopeError(
                "derivation_reference must be an exact #38 reference."
            )
        if not isinstance(
            self.generation_result,
            GroupingSignalPreviewGenerationResult,
        ):
            raise PlanningSignalPreviewGenerationScopeError(
                "generation_result must be a canonical #39 generation result."
            )
        if (
            self.generation_result.stored.snapshot.derivation_reference
            != self.derivation_reference
        ):
            raise PlanningSignalPreviewGenerationError(
                "Persisted #39 preview does not bind the exact requested "
                "#38 derivation."
            )

    @property
    def write_disposition(self) -> str:
        return self.generation_result.write_disposition

    @property
    def preview_reference(self) -> object:
        return self.generation_result.stored.reference

    @property
    def preview_id(self) -> str:
        return self.generation_result.stored.snapshot.preview_id

    @property
    def preview_sha256(self) -> str:
        return self.generation_result.stored.preview_sha256

    @property
    def preview_fingerprint(self) -> str:
        return self.generation_result.stored.snapshot.preview_fingerprint

    @property
    def currentness_state(self) -> str:
        return self.generation_result.stored.snapshot.currentness.state

    @property
    def currentness_reason_codes(self) -> tuple[str, ...]:
        return self.generation_result.stored.snapshot.currentness.reason_codes

    @property
    def diagnostic_count(self) -> int:
        return len(self.generation_result.stored.snapshot.diagnostics)

    @property
    def warning_diagnostic_ids(self) -> tuple[str, ...]:
        return tuple(
            item.diagnostic_id
            for item in self.generation_result.stored.snapshot.diagnostics
            if item.severity == "warning"
        )

    @property
    def blocking_diagnostic_ids(self) -> tuple[str, ...]:
        return tuple(
            item.diagnostic_id
            for item in self.generation_result.stored.snapshot.diagnostics
            if item.severity == "blocking"
        )

    @property
    def roster_student_count(self) -> int:
        return self.generation_result.stored.snapshot.coverage.roster_student_count

    @property
    def contributing_student_count(self) -> int:
        return (
            self.generation_result.stored.snapshot.coverage.contributing_student_count
        )

    @property
    def noncontributing_student_count(self) -> int:
        return (
            self.generation_result.stored.snapshot.coverage.noncontributing_student_count
        )

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


def generate_planning_signal_preview(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
    derivation_sha256: str,
) -> PlanningSignalPreviewGenerationWorkflowResult:
    """Persist canonical #39 preview state for one exact persisted #38 source."""
    try:
        reference = GroupingSignalDerivationReference(
            class_id=class_id,
            derivation_id=derivation_id,
            derivation_sha256=derivation_sha256,
        )
    except (GroupingSignalDerivationValidationError, ValueError) as error:
        raise PlanningSignalPreviewGenerationScopeError(str(error)) from error

    try:
        result = generate_grouping_signal_preview(
            workspace_root,
            reference,
        )
    except GroupingSignalPreviewGenerationError as error:
        raise PlanningSignalPreviewGenerationDependencyError(str(error)) from error

    return PlanningSignalPreviewGenerationWorkflowResult(
        derivation_reference=reference,
        generation_result=result,
    )
