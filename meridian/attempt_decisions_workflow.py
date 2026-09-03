"""Read-only teacher projection for explicit attempt decisions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    AttemptCandidate,
    AttemptObservationReference,
    AttemptProjectionReference,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionResolution,
    resolve_current_attempt_selection,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

AttemptDecisionWorkflowStatus: TypeAlias = Literal[
    "not_applicable",
    "unsupported_attempt_shape",
    "no_decision",
    "selected_none",
    "selected",
    "stale",
]

_STALE_RESOLUTION_STATUSES = frozenset(
    {
        "policy_stale",
        "membership_stale",
        "eligibility_stale",
        "candidate_set_stale",
        "source_unverifiable",
    }
)


class AttemptDecisionWorkflowError(RuntimeError):
    """Base error for the teacher-facing Attempt Decisions projection."""

    code = "teacher_workflow.attempt_decisions.error"


class AttemptDecisionWorkflowScopeError(AttemptDecisionWorkflowError, ValueError):
    """Raised when attempt-decision projection inputs or results are invalid."""

    code = "teacher_workflow.attempt_decisions.invalid"


@dataclass(frozen=True, slots=True)
class AttemptDecisionCandidateRow:
    """One current candidate without score/ranking semantics."""

    attempt: AttemptObservationReference
    eligible_evidence_count: int
    selected_in_reviewed_decision: bool

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, AttemptObservationReference):
            raise AttemptDecisionWorkflowScopeError(
                "candidate attempt must be an AttemptObservationReference."
            )
        if (
            isinstance(self.eligible_evidence_count, bool)
            or not isinstance(self.eligible_evidence_count, int)
            or self.eligible_evidence_count <= 0
        ):
            raise AttemptDecisionWorkflowScopeError(
                "eligible_evidence_count must be a positive integer."
            )
        if not isinstance(self.selected_in_reviewed_decision, bool):
            raise AttemptDecisionWorkflowScopeError(
                "selected_in_reviewed_decision must be boolean."
            )

    @property
    def target_id(self) -> str | None:
        return self.attempt.target.target_id

    @property
    def native_identifier(self) -> str | None:
        return self.attempt.native.identifier

    @property
    def native_sequence(self) -> int | None:
        return self.attempt.native.sequence


@dataclass(frozen=True, slots=True)
class AttemptDecisionWorkflowProjection:
    """Deterministic teacher-facing state for one student/work attempt context."""

    status: AttemptDecisionWorkflowStatus
    resolution_status: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    student_id: str
    source_snapshot: AttemptProjectionReference
    candidates: tuple[AttemptDecisionCandidateRow, ...]
    reviewed_selected_attempts: tuple[AttemptObservationReference, ...]
    selected_decision_revision: int | None
    selected_decision_sha256: str | None
    current_policy_id: str | None
    current_policy_revision: int | None
    current_policy_sha256: str | None
    minimum_selected: int | None
    maximum_selected: int | None
    operative_selection: bool
    stale_reason: str | None

    def __post_init__(self) -> None:
        if self.status not in {
            "not_applicable",
            "unsupported_attempt_shape",
            "no_decision",
            "selected_none",
            "selected",
            "stale",
        }:
            raise AttemptDecisionWorkflowScopeError(
                "attempt-decision workflow status is invalid."
            )
        if not isinstance(self.work, ModuleWorkRef):
            raise AttemptDecisionWorkflowScopeError(
                "work must be a ModuleWorkRef."
            )
        if self.work.class_id != self.class_id:
            raise AttemptDecisionWorkflowScopeError(
                "work.class_id must match projection class_id."
            )
        if not isinstance(self.source_snapshot, AttemptProjectionReference):
            raise AttemptDecisionWorkflowScopeError(
                "source_snapshot must be an AttemptProjectionReference."
            )
        if self.source_snapshot.work != self.work:
            raise AttemptDecisionWorkflowScopeError(
                "source_snapshot work must match projection work."
            )
        if not isinstance(self.operative_selection, bool):
            raise AttemptDecisionWorkflowScopeError(
                "operative_selection must be boolean."
            )
        if self.status in {"selected", "selected_none"}:
            if not self.operative_selection:
                raise AttemptDecisionWorkflowScopeError(
                    "selected states must be operative."
                )
        elif self.operative_selection:
            raise AttemptDecisionWorkflowScopeError(
                "only selected states may be operative."
            )
        if self.status == "stale":
            if self.stale_reason is None:
                raise AttemptDecisionWorkflowScopeError(
                    "stale state requires an exact stale_reason."
                )
        elif self.stale_reason is not None:
            raise AttemptDecisionWorkflowScopeError(
                "non-stale state must not carry stale_reason."
            )

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def reviewed_selected_count(self) -> int:
        return len(self.reviewed_selected_attempts)


def project_attempt_decisions(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptDecisionWorkflowProjection:
    """Project current #30 attempt state without writing or selecting anything."""
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise AttemptDecisionWorkflowScopeError(
            "Attempt Decisions requires an AuthorizedProjectionSnapshot."
        )
    resolution = resolve_current_attempt_selection(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
        authorized_snapshot=authorized_snapshot,
    )
    source_snapshot = _source_snapshot_reference(authorized_snapshot)

    selected = resolution.selected
    reviewed_selected_attempts = (
        () if selected is None else selected.decision.selected_attempts
    )
    rows = tuple(
        _candidate_row(candidate, reviewed_selected_attempts)
        for candidate in resolution.current_candidates
    )

    current_policy = resolution.current_policy
    if current_policy is None:
        policy_id = None
        policy_revision = None
        policy_sha256 = None
        minimum_selected = None
        maximum_selected = None
    else:
        policy = current_policy.policy
        policy_id = policy.policy_id
        policy_revision = policy.policy_revision
        policy_sha256 = current_policy.policy_sha256
        minimum_selected = policy.minimum_selected
        maximum_selected = policy.maximum_selected

    status, stale_reason = _workflow_status(resolution)
    return AttemptDecisionWorkflowProjection(
        status=status,
        resolution_status=resolution.status,
        class_id=class_id,
        grade_item_id=grade_item_id,
        work=work,
        student_id=student_id,
        source_snapshot=source_snapshot,
        candidates=rows,
        reviewed_selected_attempts=reviewed_selected_attempts,
        selected_decision_revision=(
            None if selected is None else selected.decision.decision_revision
        ),
        selected_decision_sha256=(
            None if selected is None else selected.decision_sha256
        ),
        current_policy_id=policy_id,
        current_policy_revision=policy_revision,
        current_policy_sha256=policy_sha256,
        minimum_selected=minimum_selected,
        maximum_selected=maximum_selected,
        operative_selection=resolution.operative_selection,
        stale_reason=stale_reason,
    )


def _source_snapshot_reference(
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptProjectionReference:
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    return AttemptProjectionReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
    )


def _candidate_row(
    candidate: AttemptCandidate,
    reviewed_selected_attempts: tuple[AttemptObservationReference, ...],
) -> AttemptDecisionCandidateRow:
    return AttemptDecisionCandidateRow(
        attempt=candidate.attempt,
        eligible_evidence_count=len(candidate.eligible_evidence),
        selected_in_reviewed_decision=(
            candidate.attempt in reviewed_selected_attempts
        ),
    )


def _workflow_status(
    resolution: AttemptSelectionResolution,
) -> tuple[AttemptDecisionWorkflowStatus, str | None]:
    status = resolution.status
    if status in _STALE_RESOLUTION_STATUSES:
        return "stale", status
    if status in {
        "not_applicable",
        "unsupported_attempt_shape",
        "no_decision",
        "selected_none",
        "selected",
    }:
        return status, None
    raise AttemptDecisionWorkflowScopeError(
        f"Unsupported attempt-selection resolution status: {status!r}."
    )
