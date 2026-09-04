"""Explicit #38 persistence stage for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationSnapshot,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    GroupingSignalDerivationWriteResult,
    StoredGroupingSignalDerivation,
    write_grouping_signal_derivation,
)
from meridian.planning_signal_workflow import (
    PlanningSignalReadinessProjection,
    PlanningSignalWorkflowError,
    project_planning_signal_readiness,
)


class PlanningSignalDerivationPersistenceError(RuntimeError):
    """Base failure for the explicit #38 persistence stage."""

    code = "teacher_workflow.create_planning_signal.derivation_error"


class PlanningSignalDerivationPersistenceScopeError(
    PlanningSignalDerivationPersistenceError,
    ValueError,
):
    """Raised when the reviewed readiness state cannot be persisted."""

    code = "teacher_workflow.create_planning_signal.derivation_invalid"


class PlanningSignalDerivationPersistenceStaleError(
    PlanningSignalDerivationPersistenceError
):
    """Raised when current readiness differs from what the teacher reviewed."""

    code = "teacher_workflow.create_planning_signal.derivation_stale"


@dataclass(frozen=True, slots=True)
class PlanningSignalDerivationPersistencePreview:
    """Exact reviewed generated #38 candidate, not yet persisted."""

    readiness: PlanningSignalReadinessProjection
    candidate: GroupingSignalDerivationSnapshot

    @property
    def class_id(self) -> str:
        return self.candidate.class_id

    @property
    def policy_id(self) -> str:
        return self.readiness.policy_id

    @property
    def derivation_id(self) -> str:
        return self.candidate.derivation_id

    @property
    def calculation_fingerprint(self) -> str:
        return self.candidate.calculation_fingerprint

    @property
    def roster_student_count(self) -> int:
        return len(self.candidate.roster_basis.student_ids)

    @property
    def contributing_student_count(self) -> int:
        return sum(
            item.disposition == "contributing"
            for item in self.candidate.student_derivations
        )

    @property
    def noncontributing_student_count(self) -> int:
        return sum(
            item.disposition == "noncontributing"
            for item in self.candidate.student_derivations
        )

    @property
    def derivation_write_action(self) -> str:
        return "not_performed"

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
class PlanningSignalDerivationPersistenceResult:
    """One exact immutable #38 write; later planning stages remain untouched."""

    preview: PlanningSignalDerivationPersistencePreview
    write_result: GroupingSignalDerivationWriteResult

    @property
    def stored(self) -> StoredGroupingSignalDerivation:
        return self.write_result.stored

    @property
    def write_disposition(self) -> str:
        return self.write_result.disposition

    @property
    def derivation_id(self) -> str:
        return self.stored.snapshot.derivation_id

    @property
    def derivation_sha256(self) -> str:
        return self.stored.derivation_sha256

    @property
    def calculation_fingerprint(self) -> str:
        return self.stored.snapshot.calculation_fingerprint

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


def preview_planning_signal_derivation_persistence(
    readiness: PlanningSignalReadinessProjection,
) -> PlanningSignalDerivationPersistencePreview:
    """Freeze one exact ready #38 candidate without writing it."""
    if not isinstance(readiness, PlanningSignalReadinessProjection):
        raise PlanningSignalDerivationPersistenceScopeError(
            "readiness must be a PlanningSignalReadinessProjection."
        )
    if not readiness.ready_for_derivation_persistence:
        raise PlanningSignalDerivationPersistenceScopeError(
            "Create Planning Signal readiness is blocked; no #38 derivation "
            "may be persisted."
        )
    candidate = readiness.generation.snapshot
    if candidate is None:
        raise PlanningSignalDerivationPersistenceScopeError(
            "Ready planning-signal state is missing its #38 candidate."
        )
    if candidate.class_id != readiness.class_id:
        raise PlanningSignalDerivationPersistenceScopeError(
            "Ready #38 candidate class does not match workflow class."
        )
    policy = readiness.policy
    if policy is None or candidate.policy_reference != policy.reference:
        raise PlanningSignalDerivationPersistenceScopeError(
            "Ready #38 candidate does not bind the selected #37 policy."
        )
    return PlanningSignalDerivationPersistencePreview(
        readiness=readiness,
        candidate=candidate,
    )


def commit_planning_signal_derivation_persistence_preview(
    workspace_root: str | Path,
    preview: PlanningSignalDerivationPersistencePreview,
) -> PlanningSignalDerivationPersistenceResult:
    """Rebuild exact readiness and persist only the reviewed #38 candidate."""
    if not isinstance(preview, PlanningSignalDerivationPersistencePreview):
        raise PlanningSignalDerivationPersistenceScopeError(
            "preview must be a PlanningSignalDerivationPersistencePreview."
        )

    try:
        fresh = project_planning_signal_readiness(
            workspace_root,
            preview.class_id,
            preview.policy_id,
        )
    except PlanningSignalWorkflowError as error:
        raise PlanningSignalDerivationPersistenceStaleError(str(error)) from error

    if not fresh.ready_for_derivation_persistence:
        raise PlanningSignalDerivationPersistenceStaleError(
            "Planning-signal readiness became blocked after derivation preview."
        )
    if fresh.policy != preview.readiness.policy:
        raise PlanningSignalDerivationPersistenceStaleError(
            "Selected #37 grouping-signal policy changed after derivation preview."
        )
    if fresh.generation.snapshot != preview.candidate:
        raise PlanningSignalDerivationPersistenceStaleError(
            "Current #38 derivation candidate changed after derivation preview."
        )

    try:
        write_result = write_grouping_signal_derivation(
            workspace_root,
            preview.candidate,
        )
    except GroupingSignalDerivationStorageError as error:
        raise PlanningSignalDerivationPersistenceError(str(error)) from error

    if write_result.stored.snapshot != preview.candidate:
        raise PlanningSignalDerivationPersistenceError(
            "Persisted #38 derivation differs from the exact reviewed candidate."
        )

    return PlanningSignalDerivationPersistenceResult(
        preview=preview,
        write_result=write_result,
    )
