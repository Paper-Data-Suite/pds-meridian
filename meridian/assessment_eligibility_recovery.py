"""#125-E2: exact batch reconciliation and selection-only #122 restart.

A sealed E1 progress link is only an action *locator*. Neither it nor a prior
outcome can authorize evidence access, imply academic success, or replay an
immutable authoring request. Reconcile canonical truth and fresh authorization
for EVERY selected source before displaying any batch accounting. Only #122's
existing ``resume_restart_eligibility`` may change a selector in this module.

Unsealed rows are candidates for a new, independently reviewed/confirmed plan,
not automatic retries of an old confirmation. This module never authors them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from meridian.assessment_eligibility_execution import _plan_digest
from meridian.assessment_eligibility_plan import (
    BatchEligibilityPlanItem,
    BatchEligibilityReviewPlan,
)
from meridian.assessment_eligibility_progress import (
    BatchEligibilityProgressStore,
    SealedBatchActionLink,
    inspect_sealed_batch_item,
)
from meridian.assessment_eligibility_review import MAXIMUM_EVIDENCE_ITEMS
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.teacher_action_contract import TeacherActionResult
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)
from meridian.teacher_action_restart_eligibility import (
    ActorChecker,
    AuthorizedLoader,
    resume_restart_eligibility,
)

RecoveryItemStatus: TypeAlias = Literal[
    "already_applied",
    "written_not_current",
    "blocked_before_write",
    "current_unverified",
    "conflict_requires_review",
    "recovery_required",
    "not_attempted",
    "unchanged",
    "deferred",
    "blocked",
    "applied",
]
_UNSAFE = frozenset(
    {
        "blocked_before_write",
        "current_unverified",
        "conflict_requires_review",
        "recovery_required",
    }
)
_ALLOWED = frozenset(
    {
        "already_applied",
        "written_not_current",
        "blocked_before_write",
        "current_unverified",
        "conflict_requires_review",
        "recovery_required",
        "not_attempted",
        "unchanged",
        "deferred",
        "blocked",
        "applied",
    }
)


class BatchEligibilityRecoveryError(RuntimeError):
    """Cannot perform private batch reconciliation under verified authority."""

    code = "teacher_workflow.assessment_eligibility.recovery_invalid"


@dataclass(frozen=True, slots=True)
class ReconciledBatchItem:
    """One selected exact item; status comes from an authorized canonical read."""

    source_item_id: str
    status: RecoveryItemStatus
    reason: str
    action_id: str | None
    may_resume_exact_selection: bool = False
    resumed_in_this_request: bool = False

    def __post_init__(self) -> None:
        if not self.source_item_id or self.status not in _ALLOWED:
            raise BatchEligibilityRecoveryError("Invalid item recovery status.")
        if self.status in {"applied", "already_applied", "written_not_current"} and (
            self.action_id is None
        ):
            raise BatchEligibilityRecoveryError("Verified action lacks exact ID.")
        if self.status in {"not_attempted", "unchanged", "deferred", "blocked"} and (
            self.action_id is not None
        ):
            raise BatchEligibilityRecoveryError("Non-action has a sealed ID.")
        if self.may_resume_exact_selection and (
            self.status != "written_not_current" or self.action_id is None
        ):
            raise BatchEligibilityRecoveryError("Unsafe selection resume flag.")
        if self.resumed_in_this_request and self.status not in {
            "applied",
            "already_applied",
        }:
            raise BatchEligibilityRecoveryError("Unverified selection completion.")
        if self.action_id is not None and (
            len(self.action_id) != 32
            or any(char not in "0123456789abcdef" for char in self.action_id)
        ):
            raise BatchEligibilityRecoveryError("Invalid sealed action ID.")


@dataclass(frozen=True, slots=True)
class BatchEligibilityRecoveryReport:
    """Complete ordered accounting, not an assessment-level eligibility flag."""

    plan_sha256: str
    items: tuple[ReconciledBatchItem, ...]
    stopped: bool = False
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            len(self.plan_sha256) != 64
            or not isinstance(self.items, tuple)
            or self.stopped != (self.stop_reason is not None)
            or len({x.source_item_id for x in self.items}) != len(self.items)
        ):
            raise BatchEligibilityRecoveryError("Invalid batch recovery report.")

    @property
    def counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(Counter(row.status for row in self.items).items()))

    @property
    def verified_action_count(self) -> int:
        return sum(x.status in {"already_applied", "applied"} for x in self.items)

    @property
    def unstarted_action_count(self) -> int:
        return sum(x.status == "not_attempted" for x in self.items)

    @property
    def selection_resume_count(self) -> int:
        return sum(x.may_resume_exact_selection for x in self.items)

    @property
    def requires_attention(self) -> bool:
        return any(
            x.status in _UNSAFE or x.status == "written_not_current" for x in self.items
        )


def _validate_plan(plan: BatchEligibilityReviewPlan) -> None:
    if (
        not isinstance(plan, BatchEligibilityReviewPlan)
        or _plan_digest(plan) != plan.plan_sha256
        or not plan.items
        or len(plan.items) > MAXIMUM_EVIDENCE_ITEMS
        or len({x.source.item_id for x in plan.items}) != len(plan.items)
    ):
        raise BatchEligibilityRecoveryError("Reviewed batch plan is not exact.")
    for item in plan.items:
        source = item.source
        if (
            source.work != plan.work
            or source.publication_id != plan.publication_id
            or source.cache_key != plan.cache_key
            or source.snapshot_digest != plan.snapshot_digest
            or item.witness.source != source
            or item.witness.membership_sha256 != plan.membership_sha256
            or item.witness.membership_revision != plan.membership_revision
        ):
            raise BatchEligibilityRecoveryError("Selected provenance differs.")


def _authorize_every_item(
    root: Path,
    plan: BatchEligibilityReviewPlan,
    authorized_loader: AuthorizedLoader,
) -> None:
    """Fail as a whole if any selected source is no longer authorized/current."""
    for item in plan.items:
        source: EvidenceSourceReference = item.source
        try:
            authorized = authorized_loader(root, source)
            publication = authorized.current_context.publication
            stored = authorized.stored
            snapshot = stored.snapshot
            permitted_items = {
                evidence.item_id for evidence in snapshot.inventory.items
            }
            if (
                not authorized.cache_read_authorization.allowed
                or not authorized.current_projection_authorization.allowed
                or source.item_id not in permitted_items
                or not authorized.assessment.reusable_for_current_use
                or publication.work != plan.work
                or publication.publication_id != source.publication_id
                or stored.cache_key != source.cache_key
                or stored.snapshot_digest != source.snapshot_digest
                or snapshot.source.publication != publication
            ):
                raise ValueError("Changed publication/projection authority")
        except Exception as error:
            # Do not return a partially revealed roster or result inventory.
            raise BatchEligibilityRecoveryError(
                "Fresh exact-source authorization is required for the whole review."
            ) from error


def _unsealed_item(item: BatchEligibilityPlanItem) -> ReconciledBatchItem:
    status: RecoveryItemStatus = (
        "not_attempted"
        if item.status == "action"
        else cast(RecoveryItemStatus, item.status)
    )
    return ReconciledBatchItem(
        item.source.item_id,
        status,
        (
            "no_sealed_action"
            if item.status == "action"
            else (item.status_reason or item.status)
        ),
        None,
    )


def reconcile_sealed_eligibility_batch(
    workspace_root: str | Path,
    plan: BatchEligibilityReviewPlan,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker,
) -> BatchEligibilityRecoveryReport:
    """Read-only, authorization-first assessment of an exact preexisting plan.

    No stored link or receipt is trusted as permission or academic state. A
    source without a sealed link is *unattempted by this plan*, not verified
    absent from canonical eligibility history or authorized for reauthoring.
    """
    _validate_plan(plan)
    if not callable(authorized_loader) or not callable(actor_checker):
        raise BatchEligibilityRecoveryError("Fresh domain readers are mandatory.")
    store = BatchEligibilityProgressStore(workspace_root, plan.class_id)
    _authorize_every_item(store.root, plan, authorized_loader)
    rows: list[ReconciledBatchItem] = []
    for item in plan.items:
        if item.status != "action":
            rows.append(_unsealed_item(item))
            continue
        try:
            inspection = inspect_sealed_batch_item(
                store.root,
                plan,
                item,
                authorized_loader=authorized_loader,
                actor_checker=actor_checker,
            )
            rows.append(
                ReconciledBatchItem(
                    item.source.item_id,
                    cast(RecoveryItemStatus, inspection.status),
                    inspection.reason,
                    inspection.action_id,
                    inspection.can_resume_exact_selection,
                )
            )
        except Exception:
            # A malformed or unsafe link is not equivalent to no attempt.
            rows.append(
                ReconciledBatchItem(
                    item.source.item_id,
                    "recovery_required",
                    "sealed_link_unreadable",
                    None,
                )
            )
    return BatchEligibilityRecoveryReport(plan.plan_sha256, tuple(rows))


def _revalidate_link_receipt(
    root: Path,
    plan: BatchEligibilityReviewPlan,
    item: BatchEligibilityPlanItem,
    action_id: str,
) -> tuple[SealedBatchActionLink, TeacherActionReceiptStore, TeacherActionReceipt]:
    """Do not use an earlier in-memory report as restart permission."""
    link_store = BatchEligibilityProgressStore(root, plan.class_id)
    link = link_store.load(plan, item)
    if link is None or link.action_id != action_id:
        raise BatchEligibilityRecoveryError("Exact sealed action link changed.")
    receipts = TeacherActionReceiptStore(link_store.root, plan.class_id)
    receipt = receipts.load(link.action_id)
    if receipt is None:
        raise BatchEligibilityRecoveryError("Exact #122 receipt is missing.")
    preview = receipt.preview
    target = preview.target
    if (
        preview.action_id != link.action_id
        or preview.intent_sha256 != link.intent_sha256
        or preview.actor != plan.actor
        or target.family != "eligibility"
        or target.identity_sha256 != link.target_identity_sha256
        or target.revision != link.target_revision
        or target.candidate_sha256 != link.target_sha256
        or target.expected_current_revision != link.expected_current_revision
        or target.expected_current_sha256 != link.expected_current_sha256
    ):
        raise BatchEligibilityRecoveryError("Sealed #122 receipt intent diverged.")
    return link, receipts, receipt


def resume_sealed_eligibility_batch(
    workspace_root: str | Path,
    plan: BatchEligibilityReviewPlan,
    *,
    confirmed: bool,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker,
) -> BatchEligibilityRecoveryReport:
    """Explicitly resume only #122 eligible *selector* operations.

    Cancellation has zero I/O. On confirmation, inspect the entire selected
    scope before mutation. Any uncertain/corrupt action stops all resume work.
    Each selected item is re-inspected immediately before its #122 RESUME.
    No immutable authoring API is reachable from this function.
    """
    _validate_plan(plan)
    if type(confirmed) is not bool:
        raise BatchEligibilityRecoveryError("Explicit boolean confirmation required.")
    if not confirmed:
        return BatchEligibilityRecoveryReport(
            plan.plan_sha256,
            tuple(_unsealed_item(item) for item in plan.items),
            stopped=True,
            stop_reason="cancelled_without_io",
        )
    report = reconcile_sealed_eligibility_batch(
        workspace_root,
        plan,
        authorized_loader=authorized_loader,
        actor_checker=actor_checker,
    )
    if any(
        row.status in _UNSAFE
        or (row.status == "written_not_current" and not row.may_resume_exact_selection)
        for row in report.items
    ):
        return BatchEligibilityRecoveryReport(
            plan.plan_sha256, report.items, True, "uncertain_action_requires_review"
        )
    outcomes = list(report.items)
    root = BatchEligibilityProgressStore(workspace_root, plan.class_id).root
    for index, (item, initial) in enumerate(zip(plan.items, outcomes, strict=True)):
        if not initial.may_resume_exact_selection:
            continue
        try:
            inspection = inspect_sealed_batch_item(
                root,
                plan,
                item,
                authorized_loader=authorized_loader,
                actor_checker=actor_checker,
            )
            if (
                inspection.status != "written_not_current"
                or not inspection.can_resume_exact_selection
                or inspection.action_id != initial.action_id
            ):
                raise BatchEligibilityRecoveryError(
                    "Exact item changed after batch preflight."
                )
            _, receipts, receipt = _revalidate_link_receipt(
                root, plan, item, initial.action_id or ""
            )
            result = resume_restart_eligibility(
                root,
                receipts,
                receipt,
                confirmation="RESUME",
                authorized_loader=authorized_loader,
                actor_checker=actor_checker,
            )
            if (
                not isinstance(result, TeacherActionResult)
                or result.action_id != initial.action_id
                or result.intent_sha256 != receipt.preview.intent_sha256
                or result.target != receipt.preview.target
                or not result.succeeded
                or result.current_state != "matches"
            ):
                raise BatchEligibilityRecoveryError(
                    "#122 did not verify exact selector completion."
                )
            outcomes[index] = ReconciledBatchItem(
                item.source.item_id,
                cast(RecoveryItemStatus, result.status),
                "exact_selection_verified",
                initial.action_id,
                resumed_in_this_request=True,
            )
        except Exception:
            # Selection may have happened before an exception; never retry it.
            outcomes[index] = ReconciledBatchItem(
                item.source.item_id,
                "recovery_required",
                "resume_result_uncertain",
                initial.action_id,
            )
            return BatchEligibilityRecoveryReport(
                plan.plan_sha256,
                tuple(outcomes),
                True,
                "exact_resume_unverified",
            )
    return BatchEligibilityRecoveryReport(plan.plan_sha256, tuple(outcomes))


def render_batch_recovery_report(report: BatchEligibilityRecoveryReport) -> str:
    """Teacher copy: explain counts without claiming assessment-wide eligibility."""
    if not isinstance(report, BatchEligibilityRecoveryReport):
        raise TypeError("Expected reconciled batch report.")
    lines = [
        "ASSESSMENT ELIGIBILITY — EXACT BATCH RECOVERY",
        f"Verified current individual actions: {report.verified_action_count}",
        f"No sealed action: {report.unstarted_action_count}",
        f"Eligible for exact selection resume: {report.selection_resume_count}",
        "Statuses: " + ", ".join(f"{s} {n}" for s, n in report.counts),
        "A batch receipt or sealed link is not an academic eligibility decision.",
    ]
    if report.stopped:
        lines.append("Stopped: " + (report.stop_reason or "Unknown"))
    if report.requires_attention:
        lines.append("Review unresolved action(s) individually; do not repeat Apply.")
    if report.unstarted_action_count:
        lines.append(
            "Unstarted items require a fresh authorized review and confirmation."
        )
    return "\n".join(lines)


__all__ = (
    "BatchEligibilityRecoveryError",
    "BatchEligibilityRecoveryReport",
    "ReconciledBatchItem",
    "reconcile_sealed_eligibility_batch",
    "render_batch_recovery_report",
    "resume_sealed_eligibility_batch",
)
