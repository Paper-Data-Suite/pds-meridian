"""#126-E1: bounded, read-only, cross-process #30/#31 reconciliation.

Canonical resolvers determine current academic truth. The class-scoped #122
journal is examined only as untrusted recovery evidence. This module never
writes, selects, reauthors, resumes or treats a receipt as an academic result.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_resolution_coordinator import (
    MultiAttemptPorts,
    MultiAttemptRecoveryAssessment,
    assess_multi_attempt_recovery,
)
from meridian.attempt_selection import attempt_selection_decision_to_json_bytes
from meridian.guided_projection import GuidedProjectionResult
from meridian.reassessment import reassessment_decision_to_json_bytes
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)

ReceiptStatus: TypeAlias = Literal[
    "missing", "prepared", "in_progress", "ambiguous", "unverifiable"
]
PairRecoveryStatus: TypeAlias = Literal[
    "pair_current_verified",
    "upstream_not_current",
    "upstream_current_reassessment_missing",
    "reassessment_written_not_current",
    "canonical_unverifiable",
    "conflict_requires_review",
    "journal_ambiguous",
    "journal_unverifiable",
]


class AttemptPairRecoveryError(ValueError):
    """The recovery request is not bound to one exact reviewed student pair."""

    code = "teacher_workflow.attempt_resolution.pair_recovery_invalid"


@dataclass(frozen=True, slots=True)
class ActionReceiptWitness:
    """Read-only journal observation, never proof of an academic write."""

    status: ReceiptStatus
    action_id: str | None = field(default=None, repr=False)
    checkpoint_stages: tuple[str, ...] = ()

    @property
    def permits_automatic_replay(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class DurablePairRecoveryAssessment:
    """Exact canonical pair state plus independently scoped receipt observations."""

    status: PairRecoveryStatus
    canonical_status: str
    upstream_receipt: ActionReceiptWitness
    reassessment_receipt: ActionReceiptWitness
    exact_upstream_current: bool
    exact_reassessment_current: bool
    reason: str | None = None

    @property
    def may_continue_to_standards(self) -> bool:
        return (
            self.status == "pair_current_verified"
            and self.exact_upstream_current
            and self.exact_reassessment_current
        )

    @property
    def can_resume_automatically(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class PairRecoveryPorts:
    """Test seams. Production defaults remain independent canonical readers."""

    canonical_inspector: Callable[..., MultiAttemptRecoveryAssessment] = (
        assess_multi_attempt_recovery
    )
    receipt_reader: Callable[[Path, str], tuple[TeacherActionReceipt, ...]] = (
        lambda root, class_id: TeacherActionReceiptStore(root, class_id).list_receipts()
    )


def _validate_binding(
    root: Path,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
) -> tuple[str, str]:
    if not isinstance(root, Path) or not root.is_absolute():
        raise AttemptPairRecoveryError("Absolute workspace path required.")
    if not isinstance(authoring, AttemptDecisionAuthoringPreview) or not isinstance(
        review, ProspectiveReassessmentReview
    ):
        raise AttemptPairRecoveryError("Exact typed #30 and #31 reviews are required.")
    first, second = authoring.candidate, review.decision
    first_hash = hashlib.sha256(
        attempt_selection_decision_to_json_bytes(first)
    ).hexdigest()
    second_hash = hashlib.sha256(
        reassessment_decision_to_json_bytes(second)
    ).hexdigest()
    if (
        first_hash != review.upstream_decision_sha256
        or second_hash != review.reassessment_decision_sha256
        or first.class_id != second.class_id
        or first.grade_item_id != second.grade_item_id
        or first.work != second.work
        or first.student_id != second.student_id
        or first.actor.kind != "teacher"
        or second.actor.kind != "teacher"
        or first.actor.actor_id != second.actor.actor_id
        or first.rationale != second.rationale
        or len(first.selected_attempts) < 2
        or first.decision_revision != second.attempt_selection.decision_revision
        or first_hash != second.attempt_selection.decision_sha256
        or second.policy.policy_revision_sha256 != review.policy_sha256
    ):
        raise AttemptPairRecoveryError(
            "Exact student, teacher, source, revision or immutable digest differs."
        )
    return first_hash, second_hash


def _receipt_witness(
    receipts: tuple[TeacherActionReceipt, ...],
    *,
    root: Path,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    family: Literal["attempt_decision", "reassessment_decision"],
    expected_hash: str,
) -> ActionReceiptWitness:
    first, second = authoring.candidate, review.decision
    scope = first.class_id
    target = first if family == "attempt_decision" else second
    expected_identity = _identity(
        family,
        scope,
        first.grade_item_id,
        first.work.module_id,
        first.work.work_id,
        first.student_id,
    )
    source_binding = (
        _identity(
            "attempt_source",
            first.source_snapshot.publication_id,
            first.source_snapshot.cache_key,
            first.source_snapshot.snapshot_digest,
            first.membership_revision_sha256,
            first.policy.policy_revision_sha256,
        )
        if family == "attempt_decision"
        else _identity(
            "reassessment_source",
            review.upstream_decision_sha256,
            review.policy_sha256,
            first.work.module_id,
            first.work.work_id,
        )
    )
    expected_revision = target.decision_revision
    baseline_revision = (
        authoring.reviewed_current_decision_revision
        if family == "attempt_decision"
        else review.expected_current_reassessment[0]
    )
    observed: list[TeacherActionReceipt] = []
    # Inspect ONLY exact candidate digests; unrelated class journal entries do
    # not disclose their student names, or change this one student's result.
    for receipt in receipts:
        preview = receipt.preview
        if preview.kind != family or preview.target.candidate_sha256 != expected_hash:
            continue
        basis = {value.role: value for value in preview.basis}
        if (
            preview.scope.class_id != scope
            or preview.scope.grade_item_id != first.grade_item_id
            or preview.scope.workspace_sha256 != _identity("workspace", str(root))
            or preview.scope.work_identity_sha256
            != _identity("work", scope, first.work.module_id, first.work.work_id)
            or preview.actor.actor_id != first.actor.actor_id
            or preview.target.identity_sha256 != expected_identity
            or preview.target.revision != expected_revision
            or preview.target.expected_current_revision != baseline_revision
            or (
                family == "reassessment_decision"
                and (
                    preview.target.expected_current_sha256
                    != review.expected_current_reassessment[1]
                )
            )
            or "canonical_source" not in basis
            or basis["canonical_source"].identity_sha256 != expected_identity
            or basis["canonical_source"].content_sha256 != source_binding
            or "actor_profile" not in basis
            or basis["actor_profile"].identity_sha256 != _identity(first.actor.actor_id)
            or basis["actor_profile"].content_sha256 != preview.actor.profile_sha256
        ):
            return ActionReceiptWitness("unverifiable")
        observed.append(receipt)
    if len(observed) > 1:
        return ActionReceiptWitness("ambiguous")
    if not observed:
        return ActionReceiptWitness("missing")
    receipt = observed[0]
    return ActionReceiptWitness(
        "prepared" if receipt.phase == "prepared" else "in_progress",
        receipt.action_id,
        tuple(check.stage for check in receipt.checkpoints),
    )


def inspect_durable_pair_recovery(
    root: Path,
    *,
    prepared: GuidedProjectionResult,
    authoring: AttemptDecisionAuthoringPreview,
    review: ProspectiveReassessmentReview,
    canonical_ports: MultiAttemptPorts | None = None,
    ports: PairRecoveryPorts | None = None,
) -> DurablePairRecoveryAssessment:
    """Inspect current #30/#31 and bounded #122 receipts without any mutation.

    A missing journal is NOT evidence that a write never happened. A stored
    receipt is NOT evidence that a pointer is current. A failed read is unknown.
    Never auto-replay after a process restart; rereview and recover exact
    original action/receipt authority in E2 before enabling any modification.
    """
    first_hash, second_hash = _validate_binding(root, authoring, review)
    services = ports or PairRecoveryPorts()
    unknown = ActionReceiptWitness("unverifiable")
    try:
        canonical = services.canonical_inspector(
            root,
            prepared=prepared,
            authoring=authoring,
            review=review,
            ports=canonical_ports,
        )
        if not isinstance(canonical, MultiAttemptRecoveryAssessment):
            raise TypeError("Canonical inspector returned an invalid result.")
    except Exception:
        return DurablePairRecoveryAssessment(
            "canonical_unverifiable",
            "unknown",
            unknown,
            unknown,
            False,
            False,
            "canonical_read_failed",
        )
    try:
        receipts = services.receipt_reader(root, authoring.candidate.class_id)
        if not isinstance(receipts, tuple):
            raise TypeError("Full bounded journal enumeration required.")
        upstream = _receipt_witness(
            receipts,
            root=root,
            authoring=authoring,
            review=review,
            family="attempt_decision",
            expected_hash=first_hash,
        )
        reassessment = _receipt_witness(
            receipts,
            root=root,
            authoring=authoring,
            review=review,
            family="reassessment_decision",
            expected_hash=second_hash,
        )
    except Exception:
        return DurablePairRecoveryAssessment(
            "journal_unverifiable",
            canonical.status,
            unknown,
            unknown,
            canonical.exact_upstream_current,
            canonical.exact_reassessment_current,
            "journal_read_failed",
        )
    if "unverifiable" in (upstream.status, reassessment.status):
        status: PairRecoveryStatus = "journal_unverifiable"
        reason: str | None = "receipt_binding_mismatch"
    elif "ambiguous" in (upstream.status, reassessment.status):
        status = "journal_ambiguous"
        reason = "multiple_exact_action_receipts"
    else:
        mapping: dict[str, PairRecoveryStatus] = {
            "pair_current": "pair_current_verified",
            "upstream_not_current": "upstream_not_current",
            "upstream_current_reassessment_missing": (
                "upstream_current_reassessment_missing"
            ),
            "reassessment_written_not_current": "reassessment_written_not_current",
            "current_unverified": "canonical_unverifiable",
            "conflict_requires_review": "conflict_requires_review",
        }
        status = mapping.get(canonical.status, "canonical_unverifiable")
        reason = canonical.reason
    return DurablePairRecoveryAssessment(
        status,
        canonical.status,
        upstream,
        reassessment,
        canonical.exact_upstream_current,
        canonical.exact_reassessment_current,
        reason,
    )


def render_durable_pair_recovery(value: DurablePairRecoveryAssessment) -> str:
    """Safe, terse recovery message. No student, receipt or native identifiers."""
    if not isinstance(value, DurablePairRecoveryAssessment):
        raise TypeError("Expected typed pair recovery assessment.")
    return "\n".join(
        (
            "Meridian — Interrupted Multi-Attempt Review (READ ONLY)",
            f"Canonical pair status: {value.canonical_status.replace('_', ' ')}",
            f"Recovery: {value.status.replace('_', ' ')}",
            f"#30 journal: {value.upstream_receipt.status.replace('_', ' ')}",
            f"#31 journal: {value.reassessment_receipt.status.replace('_', ' ')}",
            "Receipts are recovery clues, not proof of selected academic state.",
            "No action was written, resumed, selected, graded or published.",
            "Automatic replay: unavailable. Reconcile original action before resuming.",
        )
    )


__all__ = (
    "ActionReceiptWitness",
    "AttemptPairRecoveryError",
    "DurablePairRecoveryAssessment",
    "PairRecoveryPorts",
    "inspect_durable_pair_recovery",
    "render_durable_pair_recovery",
)
