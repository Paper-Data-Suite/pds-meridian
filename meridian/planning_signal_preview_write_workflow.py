"""Explicit confirmation boundary for #39 preview writes in Issue #41."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
    GroupingSignalDerivationValidationError,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    StoredGroupingSignalDerivation,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_policy import GroupingSignalDerivationPolicyReference
from meridian.planning_signal_preview_generation_workflow import (
    PlanningSignalPreviewGenerationError,
    PlanningSignalPreviewGenerationWorkflowResult,
    generate_planning_signal_preview,
)


class PlanningSignalPreviewWriteError(RuntimeError):
    """Base error for the explicit #39 preview-write confirmation stage."""

    code = "teacher_workflow.create_planning_signal.preview_write_error"


class PlanningSignalPreviewWriteScopeError(
    PlanningSignalPreviewWriteError,
    ValueError,
):
    """Raised when the exact persisted #38 preview source is invalid."""

    code = "teacher_workflow.create_planning_signal.preview_write_invalid"


class PlanningSignalPreviewWriteDependencyError(PlanningSignalPreviewWriteError):
    """Raised when the exact persisted #38 source cannot be read safely."""

    code = "teacher_workflow.create_planning_signal.preview_write_dependency_error"


class PlanningSignalPreviewWriteStaleError(PlanningSignalPreviewWriteError):
    """Raised when exact #38 state changes between preview and confirmation."""

    code = "teacher_workflow.create_planning_signal.preview_write_stale"


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewWritePreview:
    """Read-only intent to create #39 from one exact persisted #38 derivation."""

    policy_id: str
    stored_derivation: StoredGroupingSignalDerivation

    def __post_init__(self) -> None:
        if not isinstance(self.stored_derivation, StoredGroupingSignalDerivation):
            raise PlanningSignalPreviewWriteScopeError(
                "stored_derivation must be an exact persisted #38 derivation."
            )
        if self.stored_derivation.snapshot.policy_reference.policy_id != self.policy_id:
            raise PlanningSignalPreviewWriteScopeError(
                "Exact #38 derivation is not bound to the requested #37 policy family."
            )

    @property
    def class_id(self) -> str:
        return self.stored_derivation.snapshot.class_id

    @property
    def derivation_reference(self) -> GroupingSignalDerivationReference:
        return self.stored_derivation.reference

    @property
    def policy_reference(self) -> GroupingSignalDerivationPolicyReference:
        return self.stored_derivation.snapshot.policy_reference

    @property
    def derivation_id(self) -> str:
        return self.stored_derivation.snapshot.derivation_id

    @property
    def derivation_sha256(self) -> str:
        return self.stored_derivation.derivation_sha256

    @property
    def calculation_fingerprint(self) -> str:
        return self.stored_derivation.snapshot.calculation_fingerprint

    @property
    def roster_student_count(self) -> int:
        return len(self.stored_derivation.snapshot.roster_basis.student_ids)

    @property
    def contributing_student_count(self) -> int:
        return sum(
            row.disposition == "contributing"
            for row in self.stored_derivation.snapshot.student_derivations
        )

    @property
    def noncontributing_student_count(self) -> int:
        return sum(
            row.disposition == "noncontributing"
            for row in self.stored_derivation.snapshot.student_derivations
        )

    @property
    def preview_write_action(self) -> str:
        return "not_performed"

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


@dataclass(frozen=True, slots=True)
class PlanningSignalPreviewWriteResult:
    """One confirmed immutable #39 write; all later stages remain untouched."""

    preview: PlanningSignalPreviewWritePreview
    generation: PlanningSignalPreviewGenerationWorkflowResult

    @property
    def write_disposition(self) -> str:
        return self.generation.write_disposition

    @property
    def preview_id(self) -> str:
        return self.generation.preview_id

    @property
    def preview_sha256(self) -> str:
        return self.generation.preview_sha256

    @property
    def preview_fingerprint(self) -> str:
        return self.generation.preview_fingerprint

    @property
    def currentness_state(self) -> str:
        return self.generation.currentness_state

    @property
    def currentness_reason_codes(self) -> tuple[str, ...]:
        return self.generation.currentness_reason_codes

    @property
    def diagnostic_count(self) -> int:
        return self.generation.diagnostic_count

    @property
    def warning_diagnostic_ids(self) -> tuple[str, ...]:
        return self.generation.warning_diagnostic_ids

    @property
    def blocking_diagnostic_ids(self) -> tuple[str, ...]:
        return self.generation.blocking_diagnostic_ids

    @property
    def roster_student_count(self) -> int:
        return self.generation.roster_student_count

    @property
    def contributing_student_count(self) -> int:
        return self.generation.contributing_student_count

    @property
    def noncontributing_student_count(self) -> int:
        return self.generation.noncontributing_student_count

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


def preview_planning_signal_preview_write(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    derivation_id: str,
    derivation_sha256: str,
) -> PlanningSignalPreviewWritePreview:
    """Validate the exact persisted #38 source without creating #39 state."""
    reference = _derivation_reference(
        class_id,
        derivation_id,
        derivation_sha256,
    )
    exact_policy_id = _identifier(policy_id, "policy_id")
    try:
        stored = load_grouping_signal_derivation_reference(
            workspace_root,
            reference,
        )
    except GroupingSignalDerivationStorageError as error:
        raise PlanningSignalPreviewWriteDependencyError(
            "Could not load the exact persisted #38 derivation selected "
            "for #39 preview generation."
        ) from error

    if stored.reference != reference:
        raise PlanningSignalPreviewWriteDependencyError(
            "Persisted #38 derivation does not match the requested exact reference."
        )
    if stored.snapshot.policy_reference.policy_id != exact_policy_id:
        raise PlanningSignalPreviewWriteScopeError(
            "Exact #38 derivation is bound to a different #37 policy family."
        )
    return PlanningSignalPreviewWritePreview(
        policy_id=exact_policy_id,
        stored_derivation=stored,
    )


def commit_planning_signal_preview_write(
    workspace_root: str | Path,
    preview: PlanningSignalPreviewWritePreview,
) -> PlanningSignalPreviewWriteResult:
    """Revalidate the exact #38 source and delegate the canonical #39 write."""
    if not isinstance(preview, PlanningSignalPreviewWritePreview):
        raise PlanningSignalPreviewWriteScopeError(
            "preview must be a PlanningSignalPreviewWritePreview."
        )
    try:
        fresh = load_grouping_signal_derivation_reference(
            workspace_root,
            preview.derivation_reference,
        )
    except GroupingSignalDerivationStorageError as error:
        raise PlanningSignalPreviewWriteStaleError(
            "Exact #38 derivation could not be revalidated before #39 generation."
        ) from error

    if (
        fresh.snapshot != preview.stored_derivation.snapshot
        or fresh.derivation_sha256 != preview.derivation_sha256
    ):
        raise PlanningSignalPreviewWriteStaleError(
            "Exact persisted #38 derivation changed after preview-write review."
        )
    if fresh.snapshot.policy_reference != preview.policy_reference:
        raise PlanningSignalPreviewWriteStaleError(
            "Bound #37 policy provenance changed after preview-write review."
        )

    try:
        generation = generate_planning_signal_preview(
            workspace_root,
            preview.class_id,
            preview.derivation_id,
            preview.derivation_sha256,
        )
    except PlanningSignalPreviewGenerationError as error:
        raise PlanningSignalPreviewWriteDependencyError(str(error)) from error

    if generation.derivation_reference != preview.derivation_reference:
        raise PlanningSignalPreviewWriteError(
            "Canonical #39 result does not bind the exact reviewed #38 source."
        )
    return PlanningSignalPreviewWriteResult(
        preview=preview,
        generation=generation,
    )


def _derivation_reference(
    class_id: str,
    derivation_id: str,
    derivation_sha256: str,
) -> GroupingSignalDerivationReference:
    try:
        return GroupingSignalDerivationReference(
            class_id=class_id,
            derivation_id=derivation_id,
            derivation_sha256=derivation_sha256,
        )
    except (GroupingSignalDerivationValidationError, ValueError) as error:
        raise PlanningSignalPreviewWriteScopeError(str(error)) from error


def _identifier(value: str, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise PlanningSignalPreviewWriteScopeError(str(error)) from error
