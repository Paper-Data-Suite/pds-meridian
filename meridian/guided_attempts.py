"""Teacher-guided attempt/reassessment continuation for Issue #110."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
    AttemptDecisionAuthoringResult,
    AttemptDecisionAuthoringWorkflowError,
    commit_attempt_decision_authoring_preview,
    preview_attempt_decision_authoring,
)
from meridian.attempt_decision_selection_workflow import (
    AttemptDecisionSelectionPreview,
    AttemptDecisionSelectionWorkflowError,
    AttemptDecisionSelectionWorkflowResult,
    commit_attempt_decision_selection_preview,
    preview_attempt_decision_selection,
)
from meridian.attempt_decisions_workflow import (
    AttemptDecisionWorkflowError,
    AttemptDecisionWorkflowProjection,
    project_attempt_decisions,
)
from meridian.attempt_policy_authoring_workflow import (
    AttemptPolicyAuthoringPreview,
    AttemptPolicyAuthoringResult,
    AttemptPolicyAuthoringWorkflowError,
    commit_attempt_policy_authoring_preview,
    preview_attempt_policy_authoring,
)
from meridian.attempt_policy_selection_workflow import (
    AttemptPolicySelectionPreview,
    AttemptPolicySelectionWorkflowError,
    AttemptPolicySelectionWorkflowResult,
    commit_attempt_policy_selection_preview,
    preview_attempt_policy_selection,
)
from meridian.attempt_selection import AttemptObservationReference
from meridian.attempt_selection_storage import (
    AttemptSelectionStorageError,
    StoredAttemptSelectionPolicy,
    list_attempt_selection_policy_revisions,
    load_attempt_selection_policy_revision,
    load_current_attempt_selection_policy,
)
from meridian.guided_projection import GuidedProjectionResult

GuidedAttemptPolicyAction: TypeAlias = Literal[
    "ready",
    "create",
    "revise",
    "select_existing",
]


class GuidedAttemptError(RuntimeError):
    """Base failure for guided attempt/reassessment continuation."""

    code = "guided_attempt.error"


class GuidedAttemptScopeError(GuidedAttemptError, ValueError):
    """Raised when carried teacher context is insufficient or inconsistent."""

    code = "guided_attempt.scope_invalid"


class GuidedAttemptActionError(GuidedAttemptError):
    """Raised when an existing attempt-domain service fails safely."""

    code = "guided_attempt.action_failed"


@dataclass(frozen=True, slots=True)
class GuidedAttemptPolicyPreset:
    """Teacher-facing policy meaning carrying stable internal policy identity."""

    title: str
    description: str
    policy_id: str
    minimum_selected: int
    maximum_selected: int | None


DEFAULT_GUIDED_ATTEMPT_POLICIES: Final[
    tuple[GuidedAttemptPolicyPreset, ...]
] = (
    GuidedAttemptPolicyPreset(
        title="Select exactly one attempt",
        description="Use one explicit attempt for this student.",
        policy_id="teacher_guided_exactly_one",
        minimum_selected=1,
        maximum_selected=1,
    ),
    GuidedAttemptPolicyPreset(
        title="Select one or more attempts",
        description="Use one or more explicit attempts for this student.",
        policy_id="teacher_guided_one_or_more",
        minimum_selected=1,
        maximum_selected=None,
    ),
    GuidedAttemptPolicyPreset(
        title="Allow no selected attempt",
        description="Allow zero or more explicit attempts.",
        policy_id="teacher_guided_optional",
        minimum_selected=0,
        maximum_selected=None,
    ),
)


@dataclass(frozen=True, slots=True)
class GuidedAttemptPolicyPlan:
    """Mechanically derived policy setup action after teacher preset choice."""

    action: GuidedAttemptPolicyAction
    preset: GuidedAttemptPolicyPreset
    target_revision: int | None

    def __post_init__(self) -> None:
        if self.action == "select_existing" and self.target_revision is None:
            raise GuidedAttemptScopeError(
                "Existing-policy selection requires an exact target revision."
            )
        if self.action != "select_existing" and self.target_revision is not None:
            raise GuidedAttemptScopeError(
                "Only existing-policy selection carries a target revision."
            )


@dataclass(frozen=True, slots=True)
class GuidedAttemptCandidate:
    """Teacher-readable attempt candidate carrying exact hidden observation."""

    label: str
    eligible_evidence_count: int
    attempt: AttemptObservationReference = field(repr=False)


@dataclass(frozen=True, slots=True)
class GuidedAttemptReview:
    """Teacher-facing projection of existing attempt-decision state."""

    status: str
    candidates: tuple[GuidedAttemptCandidate, ...]
    selected_count: int
    minimum_selected: int | None
    maximum_selected: int | None
    projection: AttemptDecisionWorkflowProjection = field(repr=False)


CurrentPolicyLoader: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, str],
    StoredAttemptSelectionPolicy | None,
]
PolicyHistoryLoader: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, str],
    tuple[int, ...],
]
PolicyRevisionLoader: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, str, int],
    StoredAttemptSelectionPolicy,
]
AttemptProjectionLoader: TypeAlias = Callable[
    [Path, str, str, ModuleWorkRef, str, GuidedProjectionResult],
    AttemptDecisionWorkflowProjection,
]


def _project_attempts(
    root: Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
    prepared: GuidedProjectionResult,
) -> AttemptDecisionWorkflowProjection:
    return project_attempt_decisions(
        root,
        class_id,
        grade_item_id,
        work,
        student_id,
        authorized_snapshot=prepared.authorized,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GuidedAttemptDependencies:
    """Injectable seams over existing attempt/reassessment domain services."""

    current_policy_loader: CurrentPolicyLoader = load_current_attempt_selection_policy
    policy_history_loader: PolicyHistoryLoader = list_attempt_selection_policy_revisions
    policy_revision_loader: PolicyRevisionLoader = (
        load_attempt_selection_policy_revision
    )
    attempt_projection_loader: AttemptProjectionLoader = _project_attempts
    policy_authoring_previewer: Callable[..., AttemptPolicyAuthoringPreview] = (
        preview_attempt_policy_authoring
    )
    policy_authoring_committer: Callable[
        ..., AttemptPolicyAuthoringResult
    ] = commit_attempt_policy_authoring_preview
    policy_selection_previewer: Callable[..., AttemptPolicySelectionPreview] = (
        preview_attempt_policy_selection
    )
    policy_selection_committer: Callable[
        ..., AttemptPolicySelectionWorkflowResult
    ] = commit_attempt_policy_selection_preview
    decision_authoring_previewer: Callable[
        ..., AttemptDecisionAuthoringPreview
    ] = preview_attempt_decision_authoring
    decision_authoring_committer: Callable[
        ..., AttemptDecisionAuthoringResult
    ] = commit_attempt_decision_authoring_preview
    decision_selection_previewer: Callable[
        ..., AttemptDecisionSelectionPreview
    ] = preview_attempt_decision_selection
    decision_selection_committer: Callable[
        ..., AttemptDecisionSelectionWorkflowResult
    ] = commit_attempt_decision_selection_preview
    clock: Callable[[], datetime] = _utc_now
    policies: tuple[GuidedAttemptPolicyPreset, ...] = field(
        default=DEFAULT_GUIDED_ATTEMPT_POLICIES
    )

    def __post_init__(self) -> None:
        if not self.policies:
            raise GuidedAttemptScopeError(
                "At least one guided attempt policy must be configured."
            )


def _policy_matches(
    stored: StoredAttemptSelectionPolicy,
    preset: GuidedAttemptPolicyPreset,
) -> bool:
    policy = stored.policy
    return (
        policy.minimum_selected == preset.minimum_selected
        and policy.maximum_selected == preset.maximum_selected
        and policy.selection_basis == "explicit"
    )


def plan_guided_attempt_policy(
    workspace_root: str | Path,
    *,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    preset: GuidedAttemptPolicyPreset,
    dependencies: GuidedAttemptDependencies,
) -> GuidedAttemptPolicyPlan:
    """Plan explicit policy setup without guessing among policy semantics."""

    root = Path(workspace_root)
    try:
        current = dependencies.current_policy_loader(
            root,
            class_id,
            grade_item_id,
            work,
            preset.policy_id,
        )
        history = dependencies.policy_history_loader(
            root,
            class_id,
            grade_item_id,
            work,
            preset.policy_id,
        )
    except (AttemptSelectionStorageError, OSError, ValueError) as error:
        raise GuidedAttemptActionError(
            "Attempt policy state could not be loaded safely."
        ) from error

    if current is not None and _policy_matches(current, preset):
        return GuidedAttemptPolicyPlan("ready", preset, None)

    if not history:
        return GuidedAttemptPolicyPlan("create", preset, None)

    try:
        latest = dependencies.policy_revision_loader(
            root,
            class_id,
            grade_item_id,
            work,
            preset.policy_id,
            history[-1],
        )
    except (AttemptSelectionStorageError, OSError, ValueError) as error:
        raise GuidedAttemptActionError(
            "Attempt policy history could not be loaded safely."
        ) from error

    if current is None and _policy_matches(latest, preset):
        return GuidedAttemptPolicyPlan(
            "select_existing",
            preset,
            history[-1],
        )
    return GuidedAttemptPolicyPlan("revise", preset, None)


def apply_guided_attempt_policy(
    workspace_root: str | Path,
    *,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    plan: GuidedAttemptPolicyPlan,
    teacher_attribution: str,
    dependencies: GuidedAttemptDependencies,
) -> None:
    """Apply an explicitly chosen preset through existing policy services."""

    if plan.action == "ready":
        return

    root = Path(workspace_root)
    try:
        if plan.action == "select_existing":
            if plan.target_revision is None:
                raise GuidedAttemptScopeError(
                    "Existing policy selection lost its exact target."
                )
            selection_preview = dependencies.policy_selection_previewer(
                root,
                class_id,
                grade_item_id,
                work,
                plan.preset.policy_id,
                plan.target_revision,
            )
            dependencies.policy_selection_committer(root, selection_preview)
            return

        operation = "create" if plan.action == "create" else "revise"
        preview = dependencies.policy_authoring_previewer(
            root,
            class_id,
            grade_item_id,
            work,
            plan.preset.policy_id,
            operation=operation,
            minimum_selected=plan.preset.minimum_selected,
            maximum_selected=plan.preset.maximum_selected,
            actor_id=teacher_attribution,
            revised_at=dependencies.clock(),
            rationale=plan.preset.description,
        )
        written = dependencies.policy_authoring_committer(root, preview)
        selection_preview = dependencies.policy_selection_previewer(
            root,
            class_id,
            grade_item_id,
            work,
            plan.preset.policy_id,
            written.written_revision,
        )
        dependencies.policy_selection_committer(root, selection_preview)
    except (
        AttemptPolicyAuthoringWorkflowError,
        AttemptPolicySelectionWorkflowError,
        AttemptSelectionStorageError,
        ValueError,
    ) as error:
        raise GuidedAttemptActionError(
            "Attempt policy could not be prepared safely."
        ) from error


def _candidate_label(attempt: AttemptObservationReference) -> str:
    if attempt.native.sequence is not None:
        return f"Attempt {attempt.native.sequence}"
    if attempt.native.identifier is not None:
        return f"Attempt · {attempt.native.identifier}"
    return "Attempt"


def load_guided_attempt_review(
    workspace_root: str | Path,
    *,
    prepared: GuidedProjectionResult,
    grade_item_id: str,
    student_id: str,
    dependencies: GuidedAttemptDependencies,
) -> GuidedAttemptReview:
    """Reload current attempt candidates after eligibility/policy changes."""

    work = prepared.authorized.current_context.publication.work
    try:
        projection = dependencies.attempt_projection_loader(
            Path(workspace_root),
            work.class_id,
            grade_item_id,
            work,
            student_id,
            prepared,
        )
    except (AttemptDecisionWorkflowError, OSError, ValueError) as error:
        raise GuidedAttemptActionError(
            "Attempt/reassessment state could not be reviewed safely."
        ) from error

    candidates = tuple(
        GuidedAttemptCandidate(
            label=_candidate_label(row.attempt),
            eligible_evidence_count=row.eligible_evidence_count,
            attempt=row.attempt,
        )
        for row in projection.candidates
    )
    return GuidedAttemptReview(
        status=projection.status,
        candidates=candidates,
        selected_count=projection.reviewed_selected_count,
        minimum_selected=projection.minimum_selected,
        maximum_selected=projection.maximum_selected,
        projection=projection,
    )


def preview_guided_attempt_decision(
    workspace_root: str | Path,
    *,
    prepared: GuidedProjectionResult,
    grade_item_id: str,
    student_id: str,
    preset: GuidedAttemptPolicyPreset,
    selected_attempts: tuple[AttemptObservationReference, ...],
    teacher_attribution: str,
    rationale: str | None,
    dependencies: GuidedAttemptDependencies,
) -> AttemptDecisionAuthoringPreview:
    """Preview one teacher-controlled explicit attempt decision."""

    work = prepared.authorized.current_context.publication.work
    try:
        return dependencies.decision_authoring_previewer(
            Path(workspace_root),
            work.class_id,
            grade_item_id,
            work,
            student_id,
            preset.policy_id,
            authorized_snapshot=prepared.authorized,
            selected_attempts=selected_attempts,
            actor_id=teacher_attribution,
            decided_at=dependencies.clock(),
            rationale=rationale,
        )
    except (AttemptDecisionAuthoringWorkflowError, ValueError) as error:
        raise GuidedAttemptActionError(
            "Attempt decision preview could not be prepared safely."
        ) from error


def commit_guided_attempt_decision(
    workspace_root: str | Path,
    *,
    prepared: GuidedProjectionResult,
    preview: AttemptDecisionAuthoringPreview,
    dependencies: GuidedAttemptDependencies,
) -> AttemptDecisionAuthoringResult:
    """Write the reviewed immutable attempt decision."""

    try:
        return dependencies.decision_authoring_committer(
            Path(workspace_root),
            preview,
            authorized_snapshot=prepared.authorized,
        )
    except AttemptDecisionAuthoringWorkflowError as error:
        raise GuidedAttemptActionError(
            "Attempt decision could not be written safely."
        ) from error


def preview_guided_attempt_selection(
    workspace_root: str | Path,
    *,
    prepared: GuidedProjectionResult,
    grade_item_id: str,
    student_id: str,
    written_revision: int,
    dependencies: GuidedAttemptDependencies,
) -> AttemptDecisionSelectionPreview:
    """Preview exact selection of the decision just written."""

    work = prepared.authorized.current_context.publication.work
    try:
        return dependencies.decision_selection_previewer(
            Path(workspace_root),
            work.class_id,
            grade_item_id,
            work,
            student_id,
            written_revision,
            authorized_snapshot=prepared.authorized,
        )
    except (AttemptDecisionSelectionWorkflowError, ValueError) as error:
        raise GuidedAttemptActionError(
            "Attempt decision selection could not be previewed safely."
        ) from error


def commit_guided_attempt_selection(
    workspace_root: str | Path,
    *,
    prepared: GuidedProjectionResult,
    preview: AttemptDecisionSelectionPreview,
    dependencies: GuidedAttemptDependencies,
) -> AttemptDecisionSelectionWorkflowResult:
    """Select one exact reviewed attempt decision through existing CAS."""

    try:
        return dependencies.decision_selection_committer(
            Path(workspace_root),
            preview,
            authorized_snapshot=prepared.authorized,
        )
    except AttemptDecisionSelectionWorkflowError as error:
        raise GuidedAttemptActionError(
            "Attempt decision selection could not be changed safely."
        ) from error


__all__ = (
    "DEFAULT_GUIDED_ATTEMPT_POLICIES",
    "GuidedAttemptActionError",
    "GuidedAttemptCandidate",
    "GuidedAttemptDependencies",
    "GuidedAttemptError",
    "GuidedAttemptPolicyPlan",
    "GuidedAttemptPolicyPreset",
    "GuidedAttemptReview",
    "GuidedAttemptScopeError",
    "apply_guided_attempt_policy",
    "commit_guided_attempt_decision",
    "commit_guided_attempt_selection",
    "load_guided_attempt_review",
    "plan_guided_attempt_policy",
    "preview_guided_attempt_decision",
    "preview_guided_attempt_selection",
)
