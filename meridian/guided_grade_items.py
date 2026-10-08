"""Teacher-guided Grade Item bridge for Issue #110."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_period_queries import list_academic_periods
from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    load_current_academic_period_calendar,
)
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.academic_work_registration_storage import (
    AcademicWorkRegistrationStorageError,
    load_current_academic_work_registration,
)
from pds_core.class_metadata import (
    ClassMetadataError,
    class_metadata_path,
    load_class_metadata,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_authoring_workflow import (
    GradeItemAuthoringPreview,
    GradeItemAuthoringResult,
    GradeItemAuthoringWorkflowError,
    commit_grade_item_authoring_preview,
    preview_grade_item_authoring,
)
from meridian.grade_item_membership_authoring_workflow import (
    GradeItemMembershipAuthoringError,
    GradeItemMembershipAuthoringPreview,
    GradeItemMembershipAuthoringResult,
    commit_grade_item_membership_authoring_preview,
    preview_grade_item_membership_authoring,
)
from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionPreview,
    GradeItemMembershipSelectionWorkflowError,
    GradeItemMembershipSelectionWorkflowResult,
    commit_grade_item_membership_selection_preview,
    preview_grade_item_membership_selection,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    list_grade_item_membership_revisions,
)
from meridian.grade_item_memberships import GradeItemAcademicPeriodAssignment
from meridian.grade_item_selection_workflow import (
    GradeItemSelectionPreview,
    GradeItemSelectionWorkflowError,
    GradeItemSelectionWorkflowResult,
    commit_grade_item_selection_preview,
    preview_grade_item_selection,
)
from meridian.grade_items import GradeItemPurpose
from meridian.grade_items_workflow import (
    GradeItemsReview,
    GradeItemsWorkflowError,
    project_grade_items_review,
)

BridgeMembershipOperation: TypeAlias = Literal["create", "revise"]


class GuidedGradeItemBridgeError(RuntimeError):
    """Base failure for the guided Grade Item bridge."""

    code = "guided_grade_item_bridge.error"


class GuidedGradeItemBridgeScopeError(GuidedGradeItemBridgeError, ValueError):
    """Raised when required Core or Grade Item context is absent."""

    code = "guided_grade_item_bridge.scope_invalid"


class GuidedGradeItemBridgeAmbiguityError(GuidedGradeItemBridgeError):
    """Raised when teacher-facing Grade Item choices are ambiguous."""

    code = "guided_grade_item_bridge.ambiguous"


class GuidedGradeItemBridgeActionError(GuidedGradeItemBridgeError):
    """Raised when an existing author/select service fails safely."""

    code = "guided_grade_item_bridge.action_failed"


@dataclass(frozen=True, slots=True)
class GuidedGradeItemChoice:
    """Teacher-facing current active Grade Item with hidden exact identity."""

    grade_item_id: str
    title: str
    purpose: str
    display_label: str
    selected_revision: int


@dataclass(frozen=True, slots=True)
class GuidedAcademicPeriodChoice:
    """Teacher-facing current calendar period with hidden exact assignment."""

    label: str
    period_type: str
    date_range: str
    display_label: str
    assignment: GradeItemAcademicPeriodAssignment


@dataclass(frozen=True, slots=True)
class GuidedGradeItemBridgeContext:
    """Current exact dependencies required for an included work membership."""

    work: ModuleWorkRef
    registration_revision: int
    work_title: str
    existing_grade_items: tuple[GuidedGradeItemChoice, ...]
    existing_grade_item_ids: tuple[str, ...]
    periods: tuple[GuidedAcademicPeriodChoice, ...]


ReviewLoader: TypeAlias = Callable[[Path, str], GradeItemsReview]
Clock: TypeAlias = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GuidedGradeItemBridgeDependencies:
    """Injectable seams over existing Grade Item/member authority."""

    review_loader: ReviewLoader = project_grade_items_review
    grade_item_authoring_previewer: Callable[..., GradeItemAuthoringPreview] = (
        preview_grade_item_authoring
    )
    grade_item_authoring_committer: Callable[..., GradeItemAuthoringResult] = (
        commit_grade_item_authoring_preview
    )
    grade_item_selection_previewer: Callable[..., GradeItemSelectionPreview] = (
        preview_grade_item_selection
    )
    grade_item_selection_committer: Callable[
        ..., GradeItemSelectionWorkflowResult
    ] = commit_grade_item_selection_preview
    membership_authoring_previewer: Callable[
        ..., GradeItemMembershipAuthoringPreview
    ] = preview_grade_item_membership_authoring
    membership_authoring_committer: Callable[
        ..., GradeItemMembershipAuthoringResult
    ] = commit_grade_item_membership_authoring_preview
    membership_selection_previewer: Callable[
        ..., GradeItemMembershipSelectionPreview
    ] = preview_grade_item_membership_selection
    membership_selection_committer: Callable[
        ..., GradeItemMembershipSelectionWorkflowResult
    ] = commit_grade_item_membership_selection_preview
    clock: Clock = _utc_now


def _purpose_label(purpose: str) -> str:
    return {
        "standards_proficiency": "Standards proficiency",
        "conventional_grade": "Conventional grade",
        "standards_and_conventional": "Standards + conventional",
        "reporting_only": "Reporting only",
    }.get(purpose, purpose.replace("_", " ").capitalize())


def _grade_item_choices(review: GradeItemsReview) -> tuple[GuidedGradeItemChoice, ...]:
    raw = tuple(
        row
        for row in review.items
        if (
            row.selected_revision is not None
            and row.title is not None
            and row.purpose is not None
            and row.status == "active"
        )
    )
    title_counts: dict[str, int] = {}
    for row in raw:
        assert row.title is not None
        title_counts[row.title] = title_counts.get(row.title, 0) + 1

    choices: list[GuidedGradeItemChoice] = []
    labels: set[str] = set()
    for row in raw:
        assert row.title is not None
        assert row.purpose is not None
        assert row.selected_revision is not None
        label = row.title
        if title_counts[row.title] > 1:
            label = f"{row.title} · {_purpose_label(row.purpose)}"
        if label in labels:
            raise GuidedGradeItemBridgeAmbiguityError(
                "Active Grade Items cannot be safely distinguished without "
                "exposing internal identity."
            )
        labels.add(label)
        choices.append(
            GuidedGradeItemChoice(
                grade_item_id=row.grade_item_id,
                title=row.title,
                purpose=row.purpose,
                display_label=label,
                selected_revision=row.selected_revision,
            )
        )
    return tuple(
        sorted(
            choices,
            key=lambda choice: choice.display_label.casefold(),
        )
    )


def load_guided_grade_item_bridge_context(
    workspace_root: str | Path,
    work: ModuleWorkRef,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GuidedGradeItemBridgeContext:
    """Resolve current work registration, calendar periods, and Grade Items."""

    root = Path(workspace_root)
    try:
        registration = load_current_academic_work_registration(root, work)
        metadata = load_class_metadata(class_metadata_path(root, work.class_id))
        calendar = load_current_academic_period_calendar(
            root,
            metadata.school_year,
        )
        review = dependencies.review_loader(root, work.class_id)
    except (
        AcademicWorkRegistrationStorageError,
        AcademicPeriodCalendarStorageError,
        ClassMetadataError,
        GradeItemsWorkflowError,
        OSError,
        ValueError,
    ) as error:
        raise GuidedGradeItemBridgeActionError(
            "Grade Item bridge context could not be loaded safely."
        ) from error

    if registration is None:
        raise GuidedGradeItemBridgeScopeError(
            "A current Academic Work Registration is required."
        )
    if registration.lifecycle == "cancelled":
        raise GuidedGradeItemBridgeScopeError(
            "Cancelled academic work cannot be included in a Grade Item."
        )
    if calendar is None:
        raise GuidedGradeItemBridgeScopeError(
            "A current Academic Period Calendar is required."
        )

    periods = tuple(
        GuidedAcademicPeriodChoice(
            label=period.label,
            period_type=period.period_type,
            date_range=(
                f"{period.start_date.isoformat()} to "
                f"{period.end_date.isoformat()}"
            ),
            display_label=(
                f"{period.label} · {period.period_type.replace('_', ' ')} · "
                f"{period.start_date.isoformat()} to {period.end_date.isoformat()}"
            ),
            assignment=GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(
                    school_year=calendar.school_year,
                    period_id=period.period_id,
                ),
                calendar_revision=calendar.calendar_revision,
            ),
        )
        for period in list_academic_periods(calendar)
        if period.lifecycle != "cancelled"
    )
    if not periods:
        raise GuidedGradeItemBridgeScopeError(
            "The current Academic Period Calendar has no usable periods."
        )

    return GuidedGradeItemBridgeContext(
        work=work,
        registration_revision=registration.registration_revision,
        work_title=registration.title,
        existing_grade_items=_grade_item_choices(review),
        existing_grade_item_ids=tuple(row.grade_item_id for row in review.items),
        periods=periods,
    )


def derive_grade_item_id(
    title: str,
    existing_ids: tuple[str, ...],
) -> str:
    """Derive a bounded internal Grade Item identity from teacher-visible title."""

    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_text.casefold())
    stem = "_".join(words)[:40].strip("_") or "grade_item"
    base = f"gi_{stem}"
    existing = set(existing_ids)
    if base not in existing:
        return base
    suffix = 2
    while True:
        candidate = f"{base[:52]}_{suffix}"
        if candidate not in existing:
            return candidate
        suffix += 1


def preview_new_grade_item(
    workspace_root: str | Path,
    context: GuidedGradeItemBridgeContext,
    *,
    title: str,
    purpose: GradeItemPurpose,
    teacher_attribution: str,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemAuthoringPreview:
    """Preview one unweighted active Grade Item with an internal derived ID."""

    grade_item_id = derive_grade_item_id(
        title,
        context.existing_grade_item_ids,
    )
    try:
        return dependencies.grade_item_authoring_previewer(
            Path(workspace_root),
            context.work.class_id,
            grade_item_id,
            operation="create",
            actor_id=teacher_attribution,
            revised_at=dependencies.clock(),
            title=title,
            purpose=purpose,
            weighting=None,
            weighting_action="preserve",
        )
    except (GradeItemAuthoringWorkflowError, ValueError) as error:
        raise GuidedGradeItemBridgeActionError(
            "New Grade Item preview could not be prepared safely."
        ) from error


def commit_new_grade_item(
    workspace_root: str | Path,
    preview: GradeItemAuthoringPreview,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemAuthoringResult:
    try:
        return dependencies.grade_item_authoring_committer(
            Path(workspace_root),
            preview,
        )
    except GradeItemAuthoringWorkflowError as error:
        raise GuidedGradeItemBridgeActionError(
            "New Grade Item could not be written safely."
        ) from error


def select_new_grade_item(
    workspace_root: str | Path,
    written: GradeItemAuthoringResult,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemSelectionWorkflowResult:
    candidate = written.preview.candidate
    try:
        preview = dependencies.grade_item_selection_previewer(
            Path(workspace_root),
            candidate.class_id,
            candidate.grade_item_id,
            candidate.grade_item_revision,
        )
        return dependencies.grade_item_selection_committer(
            Path(workspace_root),
            preview,
        )
    except (GradeItemSelectionWorkflowError, ValueError) as error:
        raise GuidedGradeItemBridgeActionError(
            "New Grade Item could not be made current safely."
        ) from error


def preview_membership_link(
    workspace_root: str | Path,
    context: GuidedGradeItemBridgeContext,
    grade_item: GuidedGradeItemChoice,
    period: GuidedAcademicPeriodChoice,
    *,
    teacher_attribution: str,
    rationale: str | None,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemMembershipAuthoringPreview:
    """Preview create/revise of one explicit included work relationship."""

    try:
        history = list_grade_item_membership_revisions(
            workspace_root,
            context.work.class_id,
            grade_item.grade_item_id,
            context.work,
        )
        operation: BridgeMembershipOperation = "create" if not history else "revise"
        return dependencies.membership_authoring_previewer(
            Path(workspace_root),
            context.work.class_id,
            grade_item.grade_item_id,
            context.work,
            operation=operation,
            grade_item_revision=grade_item.selected_revision,
            registration_revision=context.registration_revision,
            decision="included",
            actor_id=teacher_attribution,
            decided_at=dependencies.clock(),
            academic_period=period.assignment,
            rationale=rationale,
        )
    except (
        GradeItemMembershipAuthoringError,
        GradeItemMembershipStorageError,
        ValueError,
    ) as error:
        raise GuidedGradeItemBridgeActionError(
            "Grade Item relationship preview could not be prepared safely."
        ) from error


def commit_membership_link(
    workspace_root: str | Path,
    preview: GradeItemMembershipAuthoringPreview,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemMembershipAuthoringResult:
    try:
        return dependencies.membership_authoring_committer(
            Path(workspace_root),
            preview,
        )
    except GradeItemMembershipAuthoringError as error:
        raise GuidedGradeItemBridgeActionError(
            "Grade Item relationship could not be written safely."
        ) from error


def select_membership_link(
    workspace_root: str | Path,
    written: GradeItemMembershipAuthoringResult,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> GradeItemMembershipSelectionWorkflowResult:
    decision = written.write_result.stored.decision
    try:
        preview = dependencies.membership_selection_previewer(
            Path(workspace_root),
            decision.class_id,
            decision.grade_item_id,
            decision.work_reference.work,
            decision.membership_revision,
        )
        return dependencies.membership_selection_committer(
            Path(workspace_root),
            preview,
        )
    except (GradeItemMembershipSelectionWorkflowError, ValueError) as error:
        raise GuidedGradeItemBridgeActionError(
            "Grade Item relationship could not be made current safely."
        ) from error


def verify_current_membership_link(
    workspace_root: str | Path,
    context: GuidedGradeItemBridgeContext,
    grade_item_id: str,
    *,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> bool:
    try:
        review = dependencies.review_loader(
            Path(workspace_root),
            context.work.class_id,
        )
    except (GradeItemsWorkflowError, OSError, ValueError) as error:
        raise GuidedGradeItemBridgeActionError(
            "Grade Item relationship could not be reloaded safely."
        ) from error

    row = next(
        (item for item in review.items if item.grade_item_id == grade_item_id),
        None,
    )
    if row is None or row.selected_revision is None:
        return False
    matches = tuple(
        membership
        for membership in row.memberships
        if membership.work == context.work
    )
    return (
        len(matches) == 1
        and matches[0].decision == "included"
        and matches[0].grade_item_basis_state == "matches_current_grade_item"
        and matches[0].registration_revision == context.registration_revision
    )


__all__ = (
    "GuidedAcademicPeriodChoice",
    "GuidedGradeItemBridgeActionError",
    "GuidedGradeItemBridgeAmbiguityError",
    "GuidedGradeItemBridgeContext",
    "GuidedGradeItemBridgeDependencies",
    "GuidedGradeItemBridgeError",
    "GuidedGradeItemBridgeScopeError",
    "GuidedGradeItemChoice",
    "commit_membership_link",
    "commit_new_grade_item",
    "derive_grade_item_id",
    "load_guided_grade_item_bridge_context",
    "preview_membership_link",
    "preview_new_grade_item",
    "select_membership_link",
    "select_new_grade_item",
    "verify_current_membership_link",
)
