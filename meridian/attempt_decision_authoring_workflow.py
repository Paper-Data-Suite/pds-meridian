"""Immutable authoring workflow for explicit student attempt decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    AttemptObservationReference,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicyReference,
    AttemptSelectionValidationError,
    selection_cardinality_allows,
    validate_attempt_selection_decision_transition,
)
from meridian.attempt_selection_storage import (
    AttemptSelectionDecisionWriteResult,
    derive_attempt_candidates,
    get_current_attempt_selection_decision_revision,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_policy,
    write_attempt_selection_decision_revision,
)
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot


class AttemptDecisionAuthoringWorkflowError(RuntimeError):
    """Base error for teacher attempt-decision authoring."""

    code = "teacher_workflow.attempt_decisions.decision_authoring_error"


class AttemptDecisionAuthoringScopeError(
    AttemptDecisionAuthoringWorkflowError, ValueError
):
    """Raised when an attempt-decision authoring request is invalid."""

    code = "teacher_workflow.attempt_decisions.decision_authoring_invalid"


class AttemptDecisionAuthoringStaleError(
    AttemptDecisionAuthoringWorkflowError
):
    """Raised when reviewed decision dependencies changed before commit."""

    code = "teacher_workflow.attempt_decisions.decision_authoring_stale"


@dataclass(frozen=True, slots=True)
class AttemptDecisionAuthoringPreview:
    """Exact reviewed basis for one immutable student decision revision."""

    candidate: AttemptSelectionDecision
    history: tuple[int, ...]
    latest_persisted_decision_sha256: str | None
    reviewed_current_decision_revision: int | None
    expected_membership_revision: int
    expected_membership_sha256: str
    expected_policy_revision: int
    expected_policy_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, AttemptSelectionDecision):
            raise AttemptDecisionAuthoringScopeError(
                "candidate must be an AttemptSelectionDecision."
            )
        if tuple(sorted(self.history)) != self.history:
            raise AttemptDecisionAuthoringScopeError(
                "decision history must be deterministically ordered."
            )
        if self.history:
            expected = tuple(range(1, self.history[-1] + 1))
            if self.history != expected:
                raise AttemptDecisionAuthoringScopeError(
                    "decision history must be contiguous from revision 1."
                )
            if self.candidate.decision_revision != self.history[-1] + 1:
                raise AttemptDecisionAuthoringScopeError(
                    "candidate must immediately follow persisted history."
                )
            if self.latest_persisted_decision_sha256 is None:
                raise AttemptDecisionAuthoringScopeError(
                    "existing history requires the latest decision digest."
                )
        else:
            if self.candidate.decision_revision != 1:
                raise AttemptDecisionAuthoringScopeError(
                    "initial candidate must be decision revision 1."
                )
            if self.latest_persisted_decision_sha256 is not None:
                raise AttemptDecisionAuthoringScopeError(
                    "initial candidate cannot carry a previous decision digest."
                )
        if (
            self.candidate.membership_revision
            != self.expected_membership_revision
            or self.candidate.membership_revision_sha256
            != self.expected_membership_sha256
        ):
            raise AttemptDecisionAuthoringScopeError(
                "candidate membership basis must match reviewed membership."
            )
        if (
            self.candidate.policy.policy_revision
            != self.expected_policy_revision
            or self.candidate.policy.policy_revision_sha256
            != self.expected_policy_sha256
        ):
            raise AttemptDecisionAuthoringScopeError(
                "candidate policy basis must match reviewed current policy."
            )

    @property
    def class_id(self) -> str:
        return self.candidate.class_id

    @property
    def grade_item_id(self) -> str:
        return self.candidate.grade_item_id

    @property
    def work(self) -> ModuleWorkRef:
        return self.candidate.work

    @property
    def student_id(self) -> str:
        return self.candidate.student_id

    @property
    def decision_revision(self) -> int:
        return self.candidate.decision_revision

    @property
    def selected_count(self) -> int:
        return len(self.candidate.selected_attempts)

    @property
    def candidate_count(self) -> int:
        return len(self.candidate.candidates)


@dataclass(frozen=True, slots=True)
class AttemptDecisionAuthoringResult:
    """Result of one immutable attempt-decision revision write."""

    write_result: AttemptSelectionDecisionWriteResult

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.decision.decision_revision

    @property
    def write_disposition(self) -> str:
        return self.write_result.disposition

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_attempt_decision_authoring(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    policy_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    selected_attempts: tuple[AttemptObservationReference, ...],
    actor_id: str,
    decided_at: datetime,
    rationale: str | None = None,
) -> AttemptDecisionAuthoringPreview:
    """Build one exact explicit decision revision without writing it."""
    membership = load_current_grade_item_membership_decision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    if membership is None or membership.decision.decision != "included":
        raise AttemptDecisionAuthoringScopeError(
            "Attempt decision authoring requires an explicitly selected "
            "included Grade Item membership."
        )

    policy = load_current_attempt_selection_policy(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        policy_id,
    )
    if policy is None:
        raise AttemptDecisionAuthoringScopeError(
            "Attempt decision authoring requires an explicitly selected "
            "attempt-selection policy revision."
        )

    derivation = derive_attempt_candidates(
        workspace_root,
        class_id,
        grade_item_id,
        student_id,
        authorized_snapshot,
    )
    if derivation.status != "applicable":
        raise AttemptDecisionAuthoringScopeError(
            "Attempt decision authoring requires applicable current candidates; "
            f"derivation status is {derivation.status!r}."
        )
    if derivation.source_snapshot.work != work:
        raise AttemptDecisionAuthoringScopeError(
            "Authorized projection work does not match attempt-decision work."
        )

    supplied = tuple(selected_attempts)
    if any(
        not isinstance(value, AttemptObservationReference)
        for value in supplied
    ):
        raise AttemptDecisionAuthoringScopeError(
            "selected_attempts must contain only exact attempt references."
        )
    if len(set(supplied)) != len(supplied):
        raise AttemptDecisionAuthoringScopeError(
            "selected_attempts must not contain duplicates."
        )
    candidate_attempts = tuple(
        candidate.attempt for candidate in derivation.candidates
    )
    candidate_set = set(candidate_attempts)
    if any(value not in candidate_set for value in supplied):
        raise AttemptDecisionAuthoringScopeError(
            "Every selected attempt must exist in the exact current candidate set."
        )
    supplied_set = set(supplied)
    normalized_selected = tuple(
        attempt for attempt in candidate_attempts if attempt in supplied_set
    )
    if not selection_cardinality_allows(
        policy.policy,
        len(normalized_selected),
    ):
        raise AttemptDecisionAuthoringScopeError(
            "Selected attempt count violates the current explicit policy "
            "cardinality."
        )

    history = list_attempt_selection_decision_revisions(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
    )
    previous = None
    if history:
        previous = load_attempt_selection_decision_revision(
            workspace_root,
            class_id,
            grade_item_id,
            work,
            student_id,
            history[-1],
        )

    revision = 1 if previous is None else history[-1] + 1
    try:
        candidate = AttemptSelectionDecision(
            schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
            record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            student_id=student_id,
            membership_revision=membership.decision.membership_revision,
            membership_revision_sha256=membership.decision_sha256,
            policy=AttemptSelectionPolicyReference(
                policy_id=policy.policy.policy_id,
                policy_revision=policy.policy.policy_revision,
                policy_revision_sha256=policy.policy_sha256,
            ),
            source_snapshot=derivation.source_snapshot,
            candidates=derivation.candidates,
            selected_attempts=normalized_selected,
            decision_revision=revision,
            supersedes_revision=None if previous is None else history[-1],
            actor=AttemptSelectionActor(
                kind="teacher",
                actor_id=actor_id,
            ),
            rationale=rationale,
            decided_at=decided_at,
        )
        if previous is not None:
            validate_attempt_selection_decision_transition(
                previous.decision,
                candidate,
            )
    except AttemptSelectionValidationError as error:
        raise AttemptDecisionAuthoringScopeError(str(error)) from error

    current_decision = get_current_attempt_selection_decision_revision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
        student_id,
    )
    return AttemptDecisionAuthoringPreview(
        candidate=candidate,
        history=history,
        latest_persisted_decision_sha256=(
            None if previous is None else previous.decision_sha256
        ),
        reviewed_current_decision_revision=current_decision,
        expected_membership_revision=membership.decision.membership_revision,
        expected_membership_sha256=membership.decision_sha256,
        expected_policy_revision=policy.policy.policy_revision,
        expected_policy_sha256=policy.policy_sha256,
    )


def commit_attempt_decision_authoring_preview(
    workspace_root: str | Path,
    preview: AttemptDecisionAuthoringPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> AttemptDecisionAuthoringResult:
    """Live-revalidate reviewed dependencies and write only immutable history."""
    if not isinstance(preview, AttemptDecisionAuthoringPreview):
        raise AttemptDecisionAuthoringScopeError(
            "preview must be an AttemptDecisionAuthoringPreview."
        )

    history = list_attempt_selection_decision_revisions(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.student_id,
    )
    if history != preview.history:
        raise AttemptDecisionAuthoringStaleError(
            "Attempt-decision revision history changed after preview."
        )
    if history:
        latest = load_attempt_selection_decision_revision(
            workspace_root,
            preview.class_id,
            preview.grade_item_id,
            preview.work,
            preview.student_id,
            history[-1],
        )
        if latest.decision_sha256 != preview.latest_persisted_decision_sha256:
            raise AttemptDecisionAuthoringStaleError(
                "Latest attempt-decision digest changed after preview."
            )
    elif preview.latest_persisted_decision_sha256 is not None:
        raise AttemptDecisionAuthoringStaleError(
            "Attempt-decision history no longer matches the reviewed preview."
        )

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
    )
    if (
        membership is None
        or membership.decision.decision != "included"
        or membership.decision.membership_revision
        != preview.expected_membership_revision
        or membership.decision_sha256 != preview.expected_membership_sha256
    ):
        raise AttemptDecisionAuthoringStaleError(
            "Current Grade Item membership changed after preview."
        )

    policy = load_current_attempt_selection_policy(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.work,
        preview.candidate.policy.policy_id,
    )
    if (
        policy is None
        or policy.policy.policy_revision != preview.expected_policy_revision
        or policy.policy_sha256 != preview.expected_policy_sha256
    ):
        raise AttemptDecisionAuthoringStaleError(
            "Current attempt-selection policy changed after preview."
        )

    derivation = derive_attempt_candidates(
        workspace_root,
        preview.class_id,
        preview.grade_item_id,
        preview.student_id,
        authorized_snapshot,
    )
    if (
        derivation.status != "applicable"
        or derivation.source_snapshot != preview.candidate.source_snapshot
        or derivation.candidates != preview.candidate.candidates
    ):
        raise AttemptDecisionAuthoringStaleError(
            "Current attempt candidate or eligibility basis changed after preview."
        )

    if not selection_cardinality_allows(
        policy.policy,
        len(preview.candidate.selected_attempts),
    ):
        raise AttemptDecisionAuthoringStaleError(
            "Current policy cardinality no longer permits the reviewed selection."
        )

    write_result = write_attempt_selection_decision_revision(
        workspace_root,
        preview.candidate,
        authorized_snapshot=authorized_snapshot,
    )
    return AttemptDecisionAuthoringResult(write_result=write_result)
