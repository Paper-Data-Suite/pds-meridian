"""Read-only teacher Grade Items workflow projection for issue #41."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef, module_work_ref_to_dict

from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    list_grade_item_membership_work_refs,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import (
    list_grade_item_ids,
    list_grade_item_revisions,
    load_current_grade_item_revision,
)

GradeItemSelectionState: TypeAlias = Literal[
    "no_selection",
    "selected_latest",
    "selected_historical",
]
GradeItemMembershipSelectionState: TypeAlias = Literal[
    "no_selection",
    "selected_latest",
    "selected_historical",
]
GradeItemMembershipBasisState: TypeAlias = Literal[
    "not_selected",
    "matches_current_grade_item",
    "historical_grade_item_basis",
    "no_current_grade_item",
]


class GradeItemsWorkflowError(RuntimeError):
    """Base error for the read-only Grade Items workflow projection."""

    code: str = "teacher_workflow.grade_items.error"


class GradeItemsWorkflowProjectionError(GradeItemsWorkflowError, ValueError):
    """Raised when a Grade Items projection would describe impossible state."""

    code = "teacher_workflow.grade_items.projection_invalid"


@dataclass(frozen=True, slots=True)
class GradeItemWeightingView:
    """Reserved weighting metadata, exposed without executing Grade policy."""

    category_id: str | None
    relative_weight: str | None

    def __post_init__(self) -> None:
        if self.category_id is None and self.relative_weight is None:
            raise GradeItemsWorkflowProjectionError(
                "weighting view must contain category_id or relative_weight."
            )


@dataclass(frozen=True, slots=True)
class GradeItemMembershipReviewRow:
    """One explicit Grade Item/work relationship and its selected state."""

    work: ModuleWorkRef
    revision_count: int
    latest_persisted_revision: int
    selected_revision: int | None
    selected_revision_sha256: str | None
    selection_state: GradeItemMembershipSelectionState
    decision: Literal["included", "excluded"] | None
    grade_item_revision_basis: int | None
    grade_item_revision_sha256_basis: str | None
    grade_item_basis_state: GradeItemMembershipBasisState
    registration_revision: int | None
    academic_period_school_year: str | None
    academic_period_id: str | None
    academic_period_calendar_revision: int | None
    actor_id: str | None
    decided_at: datetime | None

    def __post_init__(self) -> None:
        if self.revision_count <= 0 or self.latest_persisted_revision <= 0:
            raise GradeItemsWorkflowProjectionError(
                "membership history must contain at least one persisted revision."
            )
        if self.revision_count != self.latest_persisted_revision:
            raise GradeItemsWorkflowProjectionError(
                "contiguous membership history count must equal latest revision."
            )
        if self.selected_revision is None:
            if any(
                value is not None
                for value in (
                    self.selected_revision_sha256,
                    self.decision,
                    self.grade_item_revision_basis,
                    self.grade_item_revision_sha256_basis,
                    self.registration_revision,
                    self.academic_period_school_year,
                    self.academic_period_id,
                    self.academic_period_calendar_revision,
                    self.actor_id,
                    self.decided_at,
                )
            ):
                raise GradeItemsWorkflowProjectionError(
                    "unselected membership must not invent selected decision state."
                )
            if self.selection_state != "no_selection":
                raise GradeItemsWorkflowProjectionError(
                    "unselected membership must use no_selection state."
                )
            if self.grade_item_basis_state != "not_selected":
                raise GradeItemsWorkflowProjectionError(
                    "unselected membership must use not_selected Grade Item basis."
                )
            return

        if self.selected_revision > self.latest_persisted_revision:
            raise GradeItemsWorkflowProjectionError(
                "selected membership revision cannot exceed persisted history."
            )
        expected_selection = (
            "selected_latest"
            if self.selected_revision == self.latest_persisted_revision
            else "selected_historical"
        )
        if self.selection_state != expected_selection:
            raise GradeItemsWorkflowProjectionError(
                "membership selection_state does not match explicit selection."
            )
        if any(
            value is None
            for value in (
                self.selected_revision_sha256,
                self.decision,
                self.grade_item_revision_basis,
                self.grade_item_revision_sha256_basis,
                self.registration_revision,
                self.actor_id,
                self.decided_at,
            )
        ):
            raise GradeItemsWorkflowProjectionError(
                "selected membership requires exact decision provenance."
            )
        if self.grade_item_basis_state == "not_selected":
            raise GradeItemsWorkflowProjectionError(
                "selected membership cannot use not_selected Grade Item basis."
            )
        if self.decision == "included":
            if any(
                value is None
                for value in (
                    self.academic_period_school_year,
                    self.academic_period_id,
                    self.academic_period_calendar_revision,
                )
            ):
                raise GradeItemsWorkflowProjectionError(
                    "included membership requires exact Academic Period assignment."
                )
        elif any(
            value is not None
            for value in (
                self.academic_period_school_year,
                self.academic_period_id,
                self.academic_period_calendar_revision,
            )
        ):
            raise GradeItemsWorkflowProjectionError(
                "excluded membership must not expose an Academic Period assignment."
            )


@dataclass(frozen=True, slots=True)
class GradeItemReviewRow:
    """One logical Grade Item with explicit revision and membership selectors."""

    class_id: str
    grade_item_id: str
    revision_count: int
    latest_persisted_revision: int
    selected_revision: int | None
    selected_revision_sha256: str | None
    selection_state: GradeItemSelectionState
    title: str | None
    purpose: str | None
    status: Literal["active", "archived"] | None
    weighting: GradeItemWeightingView | None
    created_at: datetime | None
    revised_at: datetime | None
    memberships: tuple[GradeItemMembershipReviewRow, ...]

    def __post_init__(self) -> None:
        if self.revision_count <= 0 or self.latest_persisted_revision <= 0:
            raise GradeItemsWorkflowProjectionError(
                "Grade Item history must contain at least one persisted revision."
            )
        if self.revision_count != self.latest_persisted_revision:
            raise GradeItemsWorkflowProjectionError(
                "contiguous Grade Item history count must equal latest revision."
            )
        if self.selected_revision is None:
            if any(
                value is not None
                for value in (
                    self.selected_revision_sha256,
                    self.title,
                    self.purpose,
                    self.status,
                    self.weighting,
                    self.created_at,
                    self.revised_at,
                )
            ):
                raise GradeItemsWorkflowProjectionError(
                    "unselected Grade Item must not invent selected revision state."
                )
            if self.selection_state != "no_selection":
                raise GradeItemsWorkflowProjectionError(
                    "unselected Grade Item must use no_selection state."
                )
        else:
            if self.selected_revision > self.latest_persisted_revision:
                raise GradeItemsWorkflowProjectionError(
                    "selected Grade Item revision cannot exceed persisted history."
                )
            expected_selection = (
                "selected_latest"
                if self.selected_revision == self.latest_persisted_revision
                else "selected_historical"
            )
            if self.selection_state != expected_selection:
                raise GradeItemsWorkflowProjectionError(
                    "Grade Item selection_state does not match explicit selection."
                )
            if any(
                value is None
                for value in (
                    self.selected_revision_sha256,
                    self.title,
                    self.purpose,
                    self.status,
                    self.created_at,
                    self.revised_at,
                )
            ):
                raise GradeItemsWorkflowProjectionError(
                    "selected Grade Item requires exact revision projection state."
                )
        expected_memberships = tuple(
            sorted(
                self.memberships,
                key=lambda row: (row.work.module_id, row.work.work_id),
            )
        )
        if self.memberships != expected_memberships:
            raise GradeItemsWorkflowProjectionError(
                "memberships must use deterministic module/work order."
            )


@dataclass(frozen=True, slots=True)
class GradeItemsReview:
    """Deterministic class-scoped teacher review of canonical Grade Items."""

    schema_version: int
    class_id: str
    items: tuple[GradeItemReviewRow, ...]
    active_count: int
    archived_count: int
    unselected_count: int
    membership_relationship_count: int
    membership_included_count: int
    membership_excluded_count: int
    membership_unselected_count: int

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise GradeItemsWorkflowProjectionError("schema_version must be 1.")
        expected_items = tuple(sorted(self.items, key=lambda row: row.grade_item_id))
        if self.items != expected_items:
            raise GradeItemsWorkflowProjectionError(
                "Grade Items must use deterministic grade_item_id order."
            )
        active = sum(1 for row in self.items if row.status == "active")
        archived = sum(1 for row in self.items if row.status == "archived")
        unselected = sum(1 for row in self.items if row.selected_revision is None)
        memberships = tuple(
            membership for row in self.items for membership in row.memberships
        )
        included = sum(1 for row in memberships if row.decision == "included")
        excluded = sum(1 for row in memberships if row.decision == "excluded")
        membership_unselected = sum(
            1 for row in memberships if row.selected_revision is None
        )
        observed = (
            self.active_count,
            self.archived_count,
            self.unselected_count,
            self.membership_relationship_count,
            self.membership_included_count,
            self.membership_excluded_count,
            self.membership_unselected_count,
        )
        expected = (
            active,
            archived,
            unselected,
            len(memberships),
            included,
            excluded,
            membership_unselected,
        )
        if observed != expected:
            raise GradeItemsWorkflowProjectionError(
                "Grade Items review summary counts do not match projected rows."
            )


def project_grade_items_review(
    workspace_root: str | Path,
    class_id: str,
) -> GradeItemsReview:
    """Project explicit Grade Item and membership selectors without mutation."""
    rows = tuple(
        _project_grade_item(workspace_root, class_id, grade_item_id)
        for grade_item_id in sorted(list_grade_item_ids(workspace_root, class_id))
    )
    memberships = tuple(membership for row in rows for membership in row.memberships)
    return GradeItemsReview(
        schema_version=1,
        class_id=class_id,
        items=rows,
        active_count=sum(1 for row in rows if row.status == "active"),
        archived_count=sum(1 for row in rows if row.status == "archived"),
        unselected_count=sum(1 for row in rows if row.selected_revision is None),
        membership_relationship_count=len(memberships),
        membership_included_count=sum(
            1 for row in memberships if row.decision == "included"
        ),
        membership_excluded_count=sum(
            1 for row in memberships if row.decision == "excluded"
        ),
        membership_unselected_count=sum(
            1 for row in memberships if row.selected_revision is None
        ),
    )


def grade_items_review_to_dict(review: GradeItemsReview) -> dict[str, object]:
    """Convert one review to deterministic JSON-ready data."""
    return {
        "schema_version": review.schema_version,
        "class_id": review.class_id,
        "summary": {
            "active_count": review.active_count,
            "archived_count": review.archived_count,
            "unselected_count": review.unselected_count,
            "membership_relationship_count": review.membership_relationship_count,
            "membership_included_count": review.membership_included_count,
            "membership_excluded_count": review.membership_excluded_count,
            "membership_unselected_count": review.membership_unselected_count,
        },
        "items": [_grade_item_row_to_dict(row) for row in review.items],
    }


def _project_grade_item(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
) -> GradeItemReviewRow:
    history = list_grade_item_revisions(workspace_root, class_id, grade_item_id)
    if not history:
        raise GradeItemsWorkflowProjectionError(
            "Grade Item collection returned an identity without revision history."
        )
    latest = history[-1]
    selected = load_current_grade_item_revision(
        workspace_root, class_id, grade_item_id
    )
    if selected is None:
        selected_revision = None
        selected_revision_sha256 = None
        selection_state: GradeItemSelectionState = "no_selection"
        title = None
        purpose = None
        status = None
        weighting = None
        created_at = None
        revised_at = None
    else:
        revision = selected.revision
        selected_revision = revision.grade_item_revision
        selected_revision_sha256 = selected.revision_sha256
        selection_state = (
            "selected_latest"
            if selected_revision == latest
            else "selected_historical"
        )
        title = revision.title
        purpose = revision.purpose
        status = revision.status
        weighting = _weighting_view(revision.weighting)
        created_at = revision.created_at
        revised_at = revision.revised_at

    memberships = tuple(
        _project_membership(
            workspace_root,
            class_id,
            grade_item_id,
            work,
            selected_revision,
            selected_revision_sha256,
        )
        for work in sorted(
            list_grade_item_membership_work_refs(
                workspace_root, class_id, grade_item_id
            ),
            key=lambda value: (value.module_id, value.work_id),
        )
    )
    return GradeItemReviewRow(
        class_id=class_id,
        grade_item_id=grade_item_id,
        revision_count=len(history),
        latest_persisted_revision=latest,
        selected_revision=selected_revision,
        selected_revision_sha256=selected_revision_sha256,
        selection_state=selection_state,
        title=title,
        purpose=purpose,
        status=status,
        weighting=weighting,
        created_at=created_at,
        revised_at=revised_at,
        memberships=memberships,
    )


def _project_membership(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    selected_grade_item_revision: int | None,
    selected_grade_item_sha256: str | None,
) -> GradeItemMembershipReviewRow:
    history = list_grade_item_membership_revisions(
        workspace_root, class_id, grade_item_id, work
    )
    if not history:
        raise GradeItemsWorkflowProjectionError(
            "membership collection returned a relationship without revision history."
        )
    latest = history[-1]
    selected = load_current_grade_item_membership_decision(
        workspace_root, class_id, grade_item_id, work
    )
    if selected is None:
        return GradeItemMembershipReviewRow(
            work=work,
            revision_count=len(history),
            latest_persisted_revision=latest,
            selected_revision=None,
            selected_revision_sha256=None,
            selection_state="no_selection",
            decision=None,
            grade_item_revision_basis=None,
            grade_item_revision_sha256_basis=None,
            grade_item_basis_state="not_selected",
            registration_revision=None,
            academic_period_school_year=None,
            academic_period_id=None,
            academic_period_calendar_revision=None,
            actor_id=None,
            decided_at=None,
        )

    decision = selected.decision
    selection_state: GradeItemMembershipSelectionState = (
        "selected_latest"
        if decision.membership_revision == latest
        else "selected_historical"
    )
    if selected_grade_item_revision is None or selected_grade_item_sha256 is None:
        basis_state: GradeItemMembershipBasisState = "no_current_grade_item"
    elif (
        decision.grade_item_revision == selected_grade_item_revision
        and decision.grade_item_revision_sha256 == selected_grade_item_sha256
    ):
        basis_state = "matches_current_grade_item"
    else:
        basis_state = "historical_grade_item_basis"

    assignment = decision.academic_period
    if assignment is None:
        school_year = None
        period_id = None
        calendar_revision = None
    else:
        school_year = assignment.period.school_year
        period_id = assignment.period.period_id
        calendar_revision = assignment.calendar_revision
    return GradeItemMembershipReviewRow(
        work=work,
        revision_count=len(history),
        latest_persisted_revision=latest,
        selected_revision=decision.membership_revision,
        selected_revision_sha256=selected.decision_sha256,
        selection_state=selection_state,
        decision=decision.decision,
        grade_item_revision_basis=decision.grade_item_revision,
        grade_item_revision_sha256_basis=decision.grade_item_revision_sha256,
        grade_item_basis_state=basis_state,
        registration_revision=decision.work_reference.registration_revision,
        academic_period_school_year=school_year,
        academic_period_id=period_id,
        academic_period_calendar_revision=calendar_revision,
        actor_id=decision.actor_id,
        decided_at=decision.decided_at,
    )


def _weighting_view(value: object | None) -> GradeItemWeightingView | None:
    if value is None:
        return None
    category_id = getattr(value, "category_id")
    relative_weight = getattr(value, "relative_weight")
    return GradeItemWeightingView(
        category_id=category_id,
        relative_weight=(
            _decimal_text(relative_weight) if relative_weight is not None else None
        ),
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _grade_item_row_to_dict(row: GradeItemReviewRow) -> dict[str, object]:
    weighting = row.weighting
    return {
        "class_id": row.class_id,
        "grade_item_id": row.grade_item_id,
        "revision_count": row.revision_count,
        "latest_persisted_revision": row.latest_persisted_revision,
        "selected_revision": row.selected_revision,
        "selected_revision_sha256": row.selected_revision_sha256,
        "selection_state": row.selection_state,
        "title": row.title,
        "purpose": row.purpose,
        "status": row.status,
        "weighting": (
            None
            if weighting is None
            else {
                "category_id": weighting.category_id,
                "relative_weight": weighting.relative_weight,
            }
        ),
        "created_at": _datetime_text(row.created_at),
        "revised_at": _datetime_text(row.revised_at),
        "memberships": [
            _membership_row_to_dict(membership) for membership in row.memberships
        ],
    }


def _membership_row_to_dict(
    row: GradeItemMembershipReviewRow,
) -> dict[str, object]:
    return {
        "work": module_work_ref_to_dict(row.work),
        "revision_count": row.revision_count,
        "latest_persisted_revision": row.latest_persisted_revision,
        "selected_revision": row.selected_revision,
        "selected_revision_sha256": row.selected_revision_sha256,
        "selection_state": row.selection_state,
        "decision": row.decision,
        "grade_item_revision_basis": row.grade_item_revision_basis,
        "grade_item_revision_sha256_basis": row.grade_item_revision_sha256_basis,
        "grade_item_basis_state": row.grade_item_basis_state,
        "registration_revision": row.registration_revision,
        "academic_period": (
            None
            if row.academic_period_id is None
            else {
                "school_year": row.academic_period_school_year,
                "period_id": row.academic_period_id,
                "calendar_revision": row.academic_period_calendar_revision,
            }
        ),
        "actor_id": row.actor_id,
        "decided_at": _datetime_text(row.decided_at),
    }


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")
