"""Read-only teacher Exclusions projection over canonical #29 eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityResolution,
    resolve_current_evidence_eligibility,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

EvidenceAcademicDisposition: TypeAlias = Literal[
    "included",
    "excluded",
    "pending",
    "unsupported",
    "superseded",
    "withdrawn",
]
ExclusionReviewState: TypeAlias = Literal[
    "no_decision",
    "current",
    "stale",
    "source_blocked",
    "source_unverifiable",
]


class ExclusionsWorkflowError(RuntimeError):
    """Base error for the teacher Exclusions projection."""

    code = "teacher_workflow.exclusions_error"


class ExclusionsWorkflowScopeError(ExclusionsWorkflowError, ValueError):
    """Raised when an Exclusions projection request is invalid."""

    code = "teacher_workflow.exclusions_invalid"


@dataclass(frozen=True, slots=True)
class ExclusionReviewRow:
    """One exact evidence source and its selected academic/source state."""

    source: EvidenceSourceReference
    student_id: str | None
    selected_disposition: EvidenceAcademicDisposition | None
    selected_eligibility_revision: int | None
    selected_decision_sha256: str | None
    reviewed_membership_revision: int | None
    current_membership_revision: int | None
    reason_codes: tuple[str, ...]
    rationale: str | None
    actor_kind: str | None
    actor_id: str | None
    policy_id: str | None
    policy_version: str | None
    reviewed_source_state: str | None
    source_state: str | None
    successor_publication_id: str | None
    head_publication_id: str | None
    operative_included: bool
    review_state: ExclusionReviewState

    @property
    def item_id(self) -> str:
        return self.source.item_id

    @property
    def source_is_withdrawn(self) -> bool:
        return self.source_state in {"withdrawn", "withdrawn_superseded"}

    @property
    def source_is_superseded(self) -> bool:
        return self.source_state in {"superseded", "withdrawn_superseded"}


@dataclass(frozen=True, slots=True)
class ExclusionsProjection:
    """Deterministic read-only Exclusions view for one Grade Item snapshot."""

    class_id: str
    grade_item_id: str
    rows: tuple[ExclusionReviewRow, ...]

    @property
    def counts(self) -> dict[str, int]:
        result = {
            "included": 0,
            "excluded": 0,
            "pending": 0,
            "unsupported": 0,
            "superseded": 0,
            "withdrawn": 0,
            "no_decision": 0,
            "stale": 0,
            "source_blocked": 0,
            "source_unverifiable": 0,
        }
        for row in self.rows:
            if row.selected_disposition is None:
                if row.review_state == "no_decision":
                    result["no_decision"] += 1
            else:
                result[row.selected_disposition] += 1
            if row.review_state in {
                "stale",
                "source_blocked",
                "source_unverifiable",
            }:
                result[row.review_state] += 1
        return result


def build_exclusions_projection(
    workspace_root: str | Path,
    grade_item_id: str,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> ExclusionsProjection:
    """Project #29 eligibility without mutating decisions or source lifecycle."""
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise ExclusionsWorkflowScopeError(
            "Exclusions review requires an AuthorizedProjectionSnapshot."
        )
    stored = authorized_snapshot.stored
    snapshot = stored.snapshot
    publication = snapshot.source.publication
    class_id = publication.work.class_id

    inventory_items = tuple(snapshot.inventory.items)
    item_ids = tuple(item.item_id for item in inventory_items)
    if len(set(item_ids)) != len(item_ids):
        raise ExclusionsWorkflowScopeError(
            "Authorized evidence inventory contains duplicate item_id values."
        )

    rows: list[ExclusionReviewRow] = []
    for item in inventory_items:
        source = EvidenceSourceReference(
            work=publication.work,
            publication_id=publication.publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=item.item_id,
        )
        resolution = resolve_current_evidence_eligibility(
            workspace_root,
            class_id,
            grade_item_id,
            source,
            authorized_snapshot=authorized_snapshot,
        )
        rows.append(_row_from_resolution(item, source, resolution))

    return ExclusionsProjection(
        class_id=class_id,
        grade_item_id=grade_item_id,
        rows=tuple(sorted(rows, key=_row_sort_key)),
    )


def _row_from_resolution(
    item: object,
    source: EvidenceSourceReference,
    resolution: EvidenceEligibilityResolution,
) -> ExclusionReviewRow:
    selected = resolution.selected
    decision = None if selected is None else selected.decision
    selected_disposition = (
        None if decision is None else decision.disposition
    )
    if selected_disposition is not None and selected_disposition not in {
        "included",
        "excluded",
        "pending",
        "unsupported",
        "superseded",
        "withdrawn",
    }:
        raise ExclusionsWorkflowScopeError(
            "Selected eligibility disposition is outside the #29 contract."
        )

    source_state = (
        None
        if resolution.current_source_state is None
        else resolution.current_source_state.state
    )
    if resolution.status == "no_decision":
        review_state: ExclusionReviewState = "no_decision"
    elif resolution.status in {"membership_stale"}:
        review_state = "stale"
    elif resolution.status == "source_unverifiable":
        review_state = "source_unverifiable"
    elif resolution.status == "included_source_withdrawn":
        review_state = "source_blocked"
    else:
        review_state = "current"

    subject = getattr(item, "subject", None)
    student_id = None if subject is None else getattr(subject, "student_id", None)
    return ExclusionReviewRow(
        source=source,
        student_id=student_id,
        selected_disposition=selected_disposition,
        selected_eligibility_revision=(
            None if decision is None else decision.eligibility_revision
        ),
        selected_decision_sha256=(
            None if selected is None else selected.decision_sha256
        ),
        reviewed_membership_revision=(
            None if decision is None else decision.membership_revision
        ),
        current_membership_revision=resolution.current_membership_revision,
        reason_codes=(() if decision is None else decision.reason_codes),
        rationale=(None if decision is None else decision.rationale),
        actor_kind=(None if decision is None else decision.actor.kind),
        actor_id=(None if decision is None else decision.actor.actor_id),
        policy_id=(
            None
            if decision is None or decision.policy is None
            else decision.policy.policy_id
        ),
        policy_version=(
            None
            if decision is None or decision.policy is None
            else decision.policy.policy_version
        ),
        reviewed_source_state=(
            None if decision is None else decision.source_state.state
        ),
        source_state=source_state,
        successor_publication_id=(
            None
            if resolution.current_source_state is None
            else resolution.current_source_state.successor_publication_id
        ),
        head_publication_id=(
            None
            if resolution.current_source_state is None
            else resolution.current_source_state.head_publication_id
        ),
        operative_included=resolution.operative_included,
        review_state=review_state,
    )


def _row_sort_key(row: ExclusionReviewRow) -> tuple[str, str]:
    return (row.student_id or "", row.item_id)
