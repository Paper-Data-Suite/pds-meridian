"""Read-only New Evidence workflow projection for Meridian issue #41.

This module is the first substantive issue #41 application workflow. It composes
one already-authorized exact projection snapshot with the explicitly selected
Grade Item membership and evidence-eligibility state established by issues #28
and #29.

Slice 2 is intentionally read-only. It does not create or select Grade Item
membership, eligibility, attempt, reassessment, proficiency, or planning-signal
state. It also does not open producer workspaces or bypass projection-cache
authorization.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.routing_models import ModuleWorkRef

from meridian.evidence_eligibility import (
    EvidenceEligibilityDisposition,
    EvidenceSourceLifecycleState,
    EvidenceSourceReference,
)
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityResolution,
    EvidenceEligibilityResolutionStatus,
    resolve_current_evidence_eligibility,
)
from meridian.grade_item_membership_storage import (
    StoredGradeItemMembershipDecision,
    load_current_grade_item_membership_decision,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

NewEvidenceMembershipState: TypeAlias = Literal[
    "no_decision",
    "included",
    "excluded",
]
NewEvidenceRecommendedTask: TypeAlias = Literal["grade-items", "exclusions"]


class NewEvidenceWorkflowError(RuntimeError):
    """Base error for the read-only New Evidence workflow projection."""

    code: str = "teacher_workflow.new_evidence.error"


class NewEvidenceWorkflowScopeError(NewEvidenceWorkflowError, ValueError):
    """Raised when requested workflow scope contradicts the authorized source."""

    code = "teacher_workflow.new_evidence.scope_invalid"


@dataclass(frozen=True, slots=True)
class NewEvidenceStatusSummary:
    """Deterministic count of one visible workflow status."""

    status: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or not self.status:
            raise NewEvidenceWorkflowScopeError("status must be a nonempty string.")
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count < 1
        ):
            raise NewEvidenceWorkflowScopeError("count must be a positive integer.")


@dataclass(frozen=True, slots=True)
class NewEvidenceRow:
    """One provenance-safe teacher-facing evidence review row."""

    source: EvidenceSourceReference
    student_id: str | None
    target_kind: str
    target_id: str | None
    standard_ids: tuple[str, ...]
    result_kind: str
    membership_state: NewEvidenceMembershipState
    eligibility_status: EvidenceEligibilityResolutionStatus | None
    selected_eligibility_revision: int | None
    selected_eligibility_disposition: EvidenceEligibilityDisposition | None
    eligibility_source_state: EvidenceSourceLifecycleState | None
    operative_included: bool
    attention_required: bool
    recommended_task: NewEvidenceRecommendedTask | None

    def __post_init__(self) -> None:
        if not isinstance(self.source, EvidenceSourceReference):
            raise NewEvidenceWorkflowScopeError(
                "source must be an exact EvidenceSourceReference."
            )
        if self.membership_state not in {"no_decision", "included", "excluded"}:
            raise NewEvidenceWorkflowScopeError("membership_state is invalid.")
        if not isinstance(self.operative_included, bool):
            raise NewEvidenceWorkflowScopeError("operative_included must be boolean.")
        if not isinstance(self.attention_required, bool):
            raise NewEvidenceWorkflowScopeError("attention_required must be boolean.")
        if self.recommended_task not in {None, "grade-items", "exclusions"}:
            raise NewEvidenceWorkflowScopeError("recommended_task is invalid.")

        if self.membership_state != "included":
            if any(
                value is not None
                for value in (
                    self.eligibility_status,
                    self.selected_eligibility_revision,
                    self.selected_eligibility_disposition,
                    self.eligibility_source_state,
                )
            ) or self.operative_included:
                raise NewEvidenceWorkflowScopeError(
                    "Eligibility state must not be invented before included membership."
                )
        elif self.eligibility_status is None:
            raise NewEvidenceWorkflowScopeError(
                "Included membership rows require an eligibility resolution."
            )


@dataclass(frozen=True, slots=True)
class NewEvidenceReview:
    """Deterministic read-only New Evidence review over one exact projection."""

    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    publication_id: str
    cache_key: str
    snapshot_digest: str
    projection_source_status: str
    membership_state: NewEvidenceMembershipState
    membership_revision: int | None
    academic_period_id: str | None
    academic_period_calendar_revision: int | None
    rows: tuple[NewEvidenceRow, ...]
    status_summary: tuple[NewEvidenceStatusSummary, ...]
    attention_count: int

    def __post_init__(self) -> None:
        if self.work.class_id != self.class_id:
            raise NewEvidenceWorkflowScopeError(
                "work.class_id must match New Evidence class_id."
            )
        if self.membership_state == "included":
            if (
                self.membership_revision is None
                or self.academic_period_id is None
                or self.academic_period_calendar_revision is None
            ):
                raise NewEvidenceWorkflowScopeError(
                    "Included membership requires exact revision and "
                    "Academic Period basis."
                )
        elif self.membership_state == "excluded":
            if self.membership_revision is None:
                raise NewEvidenceWorkflowScopeError(
                    "Excluded membership requires its exact selected revision."
                )
            if (
                self.academic_period_id is not None
                or self.academic_period_calendar_revision is not None
            ):
                raise NewEvidenceWorkflowScopeError(
                    "Excluded membership must not expose an Academic Period assignment."
                )
        elif self.membership_state == "no_decision":
            if any(
                value is not None
                for value in (
                    self.membership_revision,
                    self.academic_period_id,
                    self.academic_period_calendar_revision,
                )
            ):
                raise NewEvidenceWorkflowScopeError(
                    "No-decision membership must not invent selected membership state."
                )
        else:
            raise NewEvidenceWorkflowScopeError("membership_state is invalid.")

        expected_attention = sum(1 for row in self.rows if row.attention_required)
        if self.attention_count != expected_attention:
            raise NewEvidenceWorkflowScopeError(
                "attention_count must equal the number of attention-required rows."
            )
        counts = Counter(_visible_status(row) for row in self.rows)
        expected_summary = tuple(
            NewEvidenceStatusSummary(status=status, count=count)
            for status, count in sorted(counts.items())
        )
        if self.status_summary != expected_summary:
            raise NewEvidenceWorkflowScopeError(
                "status_summary must exactly describe the deterministic row statuses."
            )


def project_new_evidence_review(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> NewEvidenceReview:
    """Project one exact authorized evidence snapshot into teacher review state.

    Authorization must already have occurred through the established projection
    cache boundary. This function never opens another projection snapshot and
    performs no writes.
    """

    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise NewEvidenceWorkflowScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )

    stored = authorized_snapshot.stored
    snapshot = stored.snapshot
    publication = snapshot.source.publication
    work = publication.work
    if work.class_id != class_id:
        raise NewEvidenceWorkflowScopeError(
            "Requested class_id does not match the authorized projection work."
        )

    membership = load_current_grade_item_membership_decision(
        workspace_root,
        class_id,
        grade_item_id,
        work,
    )
    membership_state = _membership_state(membership)

    rows = tuple(
        _project_row(
            workspace_root,
            class_id,
            grade_item_id,
            authorized_snapshot,
            membership_state,
            item,
        )
        for item in sorted(
            snapshot.inventory.items,
            key=lambda value: (
                value.subject.student_id if value.subject is not None else "",
                value.item_id,
            ),
        )
    )

    membership_revision: int | None = None
    academic_period_id: str | None = None
    calendar_revision: int | None = None
    if membership is not None:
        membership_revision = membership.decision.membership_revision
        assignment = membership.decision.academic_period
        if assignment is not None:
            academic_period_id = assignment.period.period_id
            calendar_revision = assignment.calendar_revision

    counts = Counter(_visible_status(row) for row in rows)
    summary = tuple(
        NewEvidenceStatusSummary(status=status, count=count)
        for status, count in sorted(counts.items())
    )

    return NewEvidenceReview(
        class_id=class_id,
        grade_item_id=grade_item_id,
        work=work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        projection_source_status=authorized_snapshot.assessment.source_status,
        membership_state=membership_state,
        membership_revision=membership_revision,
        academic_period_id=academic_period_id,
        academic_period_calendar_revision=calendar_revision,
        rows=rows,
        status_summary=summary,
        attention_count=sum(1 for row in rows if row.attention_required),
    )


def new_evidence_review_to_dict(review: NewEvidenceReview) -> dict[str, object]:
    """Return a deterministic JSON-ready projection without raw evidence values."""

    if not isinstance(review, NewEvidenceReview):
        raise TypeError("review must be a NewEvidenceReview.")
    review.__post_init__()
    return {
        "class_id": review.class_id,
        "grade_item_id": review.grade_item_id,
        "work": {
            "module_id": review.work.module_id,
            "class_id": review.work.class_id,
            "work_id": review.work.work_id,
        },
        "publication_id": review.publication_id,
        "cache_key": review.cache_key,
        "snapshot_digest": review.snapshot_digest,
        "projection_source_status": review.projection_source_status,
        "membership": {
            "state": review.membership_state,
            "revision": review.membership_revision,
            "academic_period_id": review.academic_period_id,
            "calendar_revision": review.academic_period_calendar_revision,
        },
        "attention_count": review.attention_count,
        "status_summary": [
            {"status": item.status, "count": item.count}
            for item in review.status_summary
        ],
        "rows": [_row_to_dict(row) for row in review.rows],
    }


def _membership_state(
    membership: StoredGradeItemMembershipDecision | None,
) -> NewEvidenceMembershipState:
    if membership is None:
        return "no_decision"
    return membership.decision.decision


def _project_row(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    membership_state: NewEvidenceMembershipState,
    item: object,
) -> NewEvidenceRow:
    from meridian.evidence import EvidenceItem

    if not isinstance(item, EvidenceItem):
        raise NewEvidenceWorkflowScopeError(
            "Authorized projection inventory contains an invalid evidence item."
        )

    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    source = EvidenceSourceReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
        item_id=item.item_id,
    )

    if membership_state == "no_decision":
        return _row_without_eligibility(
            item,
            source,
            membership_state,
            attention_required=True,
            recommended_task="grade-items",
        )
    if membership_state == "excluded":
        return _row_without_eligibility(
            item,
            source,
            membership_state,
            attention_required=False,
            recommended_task=None,
        )

    resolution = resolve_current_evidence_eligibility(
        workspace_root,
        class_id,
        grade_item_id,
        source,
        authorized_snapshot=authorized_snapshot,
    )
    return _row_from_resolution(item, source, resolution)


def _row_without_eligibility(
    item: object,
    source: EvidenceSourceReference,
    membership_state: NewEvidenceMembershipState,
    *,
    attention_required: bool,
    recommended_task: NewEvidenceRecommendedTask | None,
) -> NewEvidenceRow:
    from meridian.evidence import EvidenceItem

    if not isinstance(item, EvidenceItem):
        raise NewEvidenceWorkflowScopeError("item must be an EvidenceItem.")
    return NewEvidenceRow(
        source=source,
        student_id=item.subject.student_id if item.subject is not None else None,
        target_kind=item.target.target_kind,
        target_id=item.target.target_id,
        standard_ids=item.target.standard_ids,
        result_kind=item.result_kind,
        membership_state=membership_state,
        eligibility_status=None,
        selected_eligibility_revision=None,
        selected_eligibility_disposition=None,
        eligibility_source_state=None,
        operative_included=False,
        attention_required=attention_required,
        recommended_task=recommended_task,
    )


def _row_from_resolution(
    item: object,
    source: EvidenceSourceReference,
    resolution: EvidenceEligibilityResolution,
) -> NewEvidenceRow:
    from meridian.evidence import EvidenceItem

    if not isinstance(item, EvidenceItem):
        raise NewEvidenceWorkflowScopeError("item must be an EvidenceItem.")
    if not isinstance(resolution, EvidenceEligibilityResolution):
        raise NewEvidenceWorkflowScopeError(
            "eligibility resolver returned an invalid resolution."
        )

    selected = resolution.selected
    selected_revision = (
        selected.decision.eligibility_revision if selected is not None else None
    )
    selected_disposition = (
        selected.decision.disposition if selected is not None else None
    )
    source_state = (
        resolution.current_source_state.state
        if resolution.current_source_state is not None
        else None
    )
    attention_required, recommended_task = _attention_route(resolution.status)

    return NewEvidenceRow(
        source=source,
        student_id=item.subject.student_id if item.subject is not None else None,
        target_kind=item.target.target_kind,
        target_id=item.target.target_id,
        standard_ids=item.target.standard_ids,
        result_kind=item.result_kind,
        membership_state="included",
        eligibility_status=resolution.status,
        selected_eligibility_revision=selected_revision,
        selected_eligibility_disposition=selected_disposition,
        eligibility_source_state=source_state,
        operative_included=resolution.operative_included,
        attention_required=attention_required,
        recommended_task=recommended_task,
    )


def _attention_route(
    status: EvidenceEligibilityResolutionStatus,
) -> tuple[bool, NewEvidenceRecommendedTask | None]:
    if status in {"included", "excluded"}:
        return False, None
    if status == "membership_stale":
        return True, "grade-items"
    return True, "exclusions"


def _visible_status(row: NewEvidenceRow) -> str:
    if row.membership_state == "no_decision":
        return "membership_no_decision"
    if row.membership_state == "excluded":
        return "membership_excluded"
    if row.eligibility_status is None:  # defensive; model validation forbids this
        raise NewEvidenceWorkflowScopeError(
            "Included membership row is missing eligibility status."
        )
    return f"eligibility_{row.eligibility_status}"


def _row_to_dict(row: NewEvidenceRow) -> dict[str, object]:
    return {
        "source": {
            "publication_id": row.source.publication_id,
            "cache_key": row.source.cache_key,
            "snapshot_digest": row.source.snapshot_digest,
            "item_id": row.source.item_id,
        },
        "student_id": row.student_id,
        "target": {
            "kind": row.target_kind,
            "id": row.target_id,
            "standard_ids": list(row.standard_ids),
        },
        "result_kind": row.result_kind,
        "membership_state": row.membership_state,
        "eligibility_status": row.eligibility_status,
        "selected_eligibility_revision": row.selected_eligibility_revision,
        "selected_eligibility_disposition": row.selected_eligibility_disposition,
        "eligibility_source_state": row.eligibility_source_state,
        "operative_included": row.operative_included,
        "attention_required": row.attention_required,
        "recommended_task": row.recommended_task,
    }
