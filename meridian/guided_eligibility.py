"""Teacher-guided eligibility continuation for Issue #110."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.grade_items_workflow import (
    GradeItemsReview,
    GradeItemsWorkflowError,
    project_grade_items_review,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.new_evidence_eligibility_selection_workflow import (
    NewEvidenceEligibilitySelectionError,
    NewEvidenceEligibilitySelectionPreview,
    NewEvidenceEligibilitySelectionWorkflowResult,
    commit_new_evidence_eligibility_selection_preview,
    preview_new_evidence_eligibility_selection,
)
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringError,
    NewEvidenceEligibilityAuthoringPreview,
    NewEvidenceEligibilityAuthoringResult,
    TeacherEligibilityDisposition,
    commit_new_evidence_eligibility_preview,
    preview_new_evidence_eligibility_revision,
)
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    NewEvidenceWorkflowError,
    project_new_evidence_review,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

_GUIDED_MANUAL_REASON: Final[tuple[str, ...]] = ("eligibility.manual",)


class GuidedEligibilityError(RuntimeError):
    """Base failure for guided teacher eligibility continuation."""

    code = "guided_eligibility.error"


class GuidedEligibilityGradeItemAmbiguityError(GuidedEligibilityError):
    """Raised when Grade Item presentation cannot distinguish choices."""

    code = "guided_eligibility.grade_item_ambiguous"


class GuidedEligibilityScopeError(GuidedEligibilityError, ValueError):
    """Raised when carried context is not exact enough for eligibility."""

    code = "guided_eligibility.scope_invalid"


class GuidedEligibilityActionError(GuidedEligibilityError):
    """Raised when existing read/author/select services fail."""

    code = "guided_eligibility.action_failed"


@dataclass(frozen=True, slots=True)
class GuidedEligibilityPolicyChoice:
    """Teacher-facing policy label carrying exact existing policy identity."""

    title: str
    policy_id: str
    policy_version: str


DEFAULT_GUIDED_ELIGIBILITY_POLICIES: Final[
    tuple[GuidedEligibilityPolicyChoice, ...]
] = (
    GuidedEligibilityPolicyChoice(
        title="Teacher review",
        policy_id="teacher_local_eligibility",
        policy_version="1",
    ),
)


@dataclass(frozen=True, slots=True)
class GuidedEligibilityGradeItemChoice:
    """Teacher-facing Grade Item presentation with hidden exact identity."""

    grade_item_id: str
    title: str
    purpose: str | None
    display_label: str


@dataclass(frozen=True, slots=True)
class GuidedEligibilityContext:
    """Exact current eligibility basis for one selected evidence row."""

    grade_item: GuidedEligibilityGradeItemChoice
    review: NewEvidenceReview
    row: NewEvidenceRow

    @property
    def current_status(self) -> str:
        return self.row.eligibility_status or "no_decision"


GradeItemsLoader: TypeAlias = Callable[[Path, str], GradeItemsReview]
EvidenceReviewLoader: TypeAlias = Callable[
    [Path, str, str, AuthorizedProjectionSnapshot],
    NewEvidenceReview,
]
AuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        NewEvidenceReview,
        AuthorizedProjectionSnapshot,
        str,
        TeacherEligibilityDisposition,
        str,
        str,
        str,
        tuple[str, ...],
        str | None,
        datetime,
    ],
    NewEvidenceEligibilityAuthoringPreview,
]
AuthoringCommitter: TypeAlias = Callable[
    [
        Path,
        NewEvidenceEligibilityAuthoringPreview,
        AuthorizedProjectionSnapshot,
    ],
    NewEvidenceEligibilityAuthoringResult,
]
SelectionPreviewer: TypeAlias = Callable[
    [
        Path,
        NewEvidenceReview,
        AuthorizedProjectionSnapshot,
        str,
        int,
    ],
    NewEvidenceEligibilitySelectionPreview,
]
SelectionCommitter: TypeAlias = Callable[
    [
        Path,
        NewEvidenceEligibilitySelectionPreview,
        AuthorizedProjectionSnapshot,
    ],
    NewEvidenceEligibilitySelectionWorkflowResult,
]
Clock: TypeAlias = Callable[[], datetime]


def _load_evidence_review(
    root: Path,
    class_id: str,
    grade_item_id: str,
    authorized: AuthorizedProjectionSnapshot,
) -> NewEvidenceReview:
    return project_new_evidence_review(
        root,
        class_id,
        grade_item_id,
        authorized,
    )


def _preview_authoring(
    root: Path,
    review: NewEvidenceReview,
    authorized: AuthorizedProjectionSnapshot,
    item_id: str,
    disposition: TeacherEligibilityDisposition,
    actor_id: str,
    policy_id: str,
    policy_version: str,
    reason_codes: tuple[str, ...],
    rationale: str | None,
    decided_at: datetime,
) -> NewEvidenceEligibilityAuthoringPreview:
    return preview_new_evidence_eligibility_revision(
        root,
        review,
        authorized,
        item_id=item_id,
        disposition=disposition,
        actor_id=actor_id,
        policy_id=policy_id,
        policy_version=policy_version,
        reason_codes=reason_codes,
        rationale=rationale,
        decided_at=decided_at,
    )


def _commit_authoring(
    root: Path,
    preview: NewEvidenceEligibilityAuthoringPreview,
    authorized: AuthorizedProjectionSnapshot,
) -> NewEvidenceEligibilityAuthoringResult:
    return commit_new_evidence_eligibility_preview(
        root,
        preview,
        authorized,
    )


def _preview_selection(
    root: Path,
    review: NewEvidenceReview,
    authorized: AuthorizedProjectionSnapshot,
    item_id: str,
    eligibility_revision: int,
) -> NewEvidenceEligibilitySelectionPreview:
    return preview_new_evidence_eligibility_selection(
        root,
        review,
        authorized,
        item_id=item_id,
        eligibility_revision=eligibility_revision,
    )


def _commit_selection(
    root: Path,
    preview: NewEvidenceEligibilitySelectionPreview,
    authorized: AuthorizedProjectionSnapshot,
) -> NewEvidenceEligibilitySelectionWorkflowResult:
    return commit_new_evidence_eligibility_selection_preview(
        root,
        preview,
        authorized,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GuidedEligibilityDependencies:
    """Injectable seams over existing read, author, and selection services."""

    grade_items_loader: GradeItemsLoader = project_grade_items_review
    evidence_review_loader: EvidenceReviewLoader = _load_evidence_review
    authoring_previewer: AuthoringPreviewer = _preview_authoring
    authoring_committer: AuthoringCommitter = _commit_authoring
    selection_previewer: SelectionPreviewer = _preview_selection
    selection_committer: SelectionCommitter = _commit_selection
    clock: Clock = _utc_now
    policies: tuple[GuidedEligibilityPolicyChoice, ...] = field(
        default=DEFAULT_GUIDED_ELIGIBILITY_POLICIES
    )

    def __post_init__(self) -> None:
        if not self.policies:
            raise GuidedEligibilityScopeError(
                "At least one guided eligibility policy must be configured."
            )


def _matching_membership(row: object, work: ModuleWorkRef) -> object | None:
    memberships = tuple(getattr(row, "memberships", ()))
    matches = tuple(
        membership
        for membership in memberships
        if getattr(membership, "work", None) == work
    )
    if len(matches) > 1:
        raise GuidedEligibilityScopeError(
            "A Grade Item contains duplicate membership relationships for this work."
        )
    return matches[0] if matches else None


def discover_guided_eligibility_grade_items(
    workspace_root: str | Path,
    work: ModuleWorkRef,
    *,
    dependencies: GuidedEligibilityDependencies,
) -> tuple[GuidedEligibilityGradeItemChoice, ...]:
    """Return explicitly included current Grade Items for one exact work."""

    if not isinstance(work, ModuleWorkRef):
        raise GuidedEligibilityScopeError("work must be a ModuleWorkRef.")

    try:
        review = dependencies.grade_items_loader(Path(workspace_root), work.class_id)
    except (GradeItemsWorkflowError, OSError, ValueError) as error:
        raise GuidedEligibilityActionError(
            "Grade Item state could not be reviewed safely."
        ) from error

    raw: list[tuple[str, str, str | None]] = []
    for row in review.items:
        if (
            row.selected_revision is None
            or row.status != "active"
            or row.title is None
        ):
            continue
        membership = _matching_membership(row, work)
        if membership is None:
            continue
        if (
            getattr(membership, "selected_revision", None) is None
            or getattr(membership, "decision", None) != "included"
            or getattr(membership, "grade_item_basis_state", None)
            != "matches_current_grade_item"
        ):
            continue
        raw.append((row.grade_item_id, row.title, row.purpose))

    if not raw:
        return ()

    title_counts: dict[str, int] = {}
    for _, title, _ in raw:
        title_counts[title] = title_counts.get(title, 0) + 1

    choices: list[GuidedEligibilityGradeItemChoice] = []
    labels: set[str] = set()
    for grade_item_id, title, purpose in raw:
        label = title
        if title_counts[title] > 1:
            label = f"{title} · {purpose or 'Other purpose'}"
        if label in labels:
            raise GuidedEligibilityGradeItemAmbiguityError(
                "Current included Grade Items cannot be safely distinguished "
                "without exposing internal identity."
            )
        labels.add(label)
        choices.append(
            GuidedEligibilityGradeItemChoice(
                grade_item_id=grade_item_id,
                title=title,
                purpose=purpose,
                display_label=label,
            )
        )

    return tuple(
        sorted(
            choices,
            key=lambda choice: (
                choice.display_label.casefold(),
                choice.grade_item_id,
            ),
        )
    )


def load_guided_eligibility_context(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    grade_item: GuidedEligibilityGradeItemChoice,
    *,
    item_id: str,
    dependencies: GuidedEligibilityDependencies,
) -> GuidedEligibilityContext:
    """Reload current Grade Item/eligibility state for one hidden evidence item."""

    try:
        authorized = prepared.authorized
        work = authorized.current_context.publication.work
        review = dependencies.evidence_review_loader(
            Path(workspace_root),
            work.class_id,
            grade_item.grade_item_id,
            authorized,
        )
    except (NewEvidenceWorkflowError, OSError, ValueError) as error:
        raise GuidedEligibilityActionError(
            "Eligibility review state could not be loaded safely."
        ) from error

    if review.work != work or review.membership_state != "included":
        raise GuidedEligibilityScopeError(
            "Eligibility requires a current included Grade Item relationship."
        )

    matches = tuple(row for row in review.rows if row.source.item_id == item_id)
    if len(matches) != 1:
        raise GuidedEligibilityScopeError(
            "The selected evidence row is no longer available in this Grade Item."
        )
    return GuidedEligibilityContext(
        grade_item=grade_item,
        review=review,
        row=matches[0],
    )


def _reason_codes(
    disposition: TeacherEligibilityDisposition,
) -> tuple[str, ...]:
    if disposition == "included":
        return ()
    return _GUIDED_MANUAL_REASON


def preview_guided_eligibility(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    context: GuidedEligibilityContext,
    *,
    disposition: TeacherEligibilityDisposition,
    teacher_attribution: str,
    policy: GuidedEligibilityPolicyChoice,
    rationale: str | None,
    dependencies: GuidedEligibilityDependencies,
) -> NewEvidenceEligibilityAuthoringPreview:
    """Preview an existing eligibility write without exposing identity prompts."""

    try:
        return dependencies.authoring_previewer(
            Path(workspace_root),
            context.review,
            prepared.authorized,
            context.row.source.item_id,
            disposition,
            teacher_attribution,
            policy.policy_id,
            policy.policy_version,
            _reason_codes(disposition),
            rationale,
            dependencies.clock(),
        )
    except (NewEvidenceEligibilityAuthoringError, ValueError) as error:
        raise GuidedEligibilityActionError(
            "Eligibility write preview could not be prepared safely."
        ) from error


def commit_guided_eligibility(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    preview: NewEvidenceEligibilityAuthoringPreview,
    *,
    dependencies: GuidedEligibilityDependencies,
) -> NewEvidenceEligibilityAuthoringResult:
    """Commit the exact preview through the existing immutable-write service."""

    try:
        return dependencies.authoring_committer(
            Path(workspace_root),
            preview,
            prepared.authorized,
        )
    except NewEvidenceEligibilityAuthoringError as error:
        raise GuidedEligibilityActionError(
            "Eligibility decision could not be written safely."
        ) from error


def preview_guided_eligibility_selection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    context: GuidedEligibilityContext,
    written_revision: int,
    *,
    dependencies: GuidedEligibilityDependencies,
) -> NewEvidenceEligibilitySelectionPreview:
    """Preview selection of the exact revision just written by this flow."""

    try:
        return dependencies.selection_previewer(
            Path(workspace_root),
            context.review,
            prepared.authorized,
            context.row.source.item_id,
            written_revision,
        )
    except (NewEvidenceEligibilitySelectionError, ValueError) as error:
        raise GuidedEligibilityActionError(
            "Eligibility selection preview could not be prepared safely."
        ) from error


def commit_guided_eligibility_selection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    preview: NewEvidenceEligibilitySelectionPreview,
    *,
    dependencies: GuidedEligibilityDependencies,
) -> NewEvidenceEligibilitySelectionWorkflowResult:
    """Select the exact preview through the existing CAS-protected service."""

    try:
        return dependencies.selection_committer(
            Path(workspace_root),
            preview,
            prepared.authorized,
        )
    except NewEvidenceEligibilitySelectionError as error:
        raise GuidedEligibilityActionError(
            "Eligibility selection could not be changed safely."
        ) from error


__all__ = (
    "DEFAULT_GUIDED_ELIGIBILITY_POLICIES",
    "GuidedEligibilityActionError",
    "GuidedEligibilityContext",
    "GuidedEligibilityDependencies",
    "GuidedEligibilityError",
    "GuidedEligibilityGradeItemAmbiguityError",
    "GuidedEligibilityGradeItemChoice",
    "GuidedEligibilityPolicyChoice",
    "GuidedEligibilityScopeError",
    "commit_guided_eligibility",
    "commit_guided_eligibility_selection",
    "discover_guided_eligibility_grade_items",
    "load_guided_eligibility_context",
    "preview_guided_eligibility",
    "preview_guided_eligibility_selection",
)
