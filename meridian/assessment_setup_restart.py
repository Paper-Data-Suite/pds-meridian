"""#124 E2D: read-only restart reconciliation for an exact durable setup.

No action creation, journal checkpoint, academic selection, RESUME, or mutation.
Every result is advisory, including a verified pending original action.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.assessment_setup_correlation import (
    AssessmentSetupCorrelation,
    create_assessment_setup_correlation,
    inspect_assessment_setup_correlation,
)
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import (
    AssessmentSetupRecoveryInspection,
    AssessmentSetupRecoveryReaders,
    inspect_assessment_setup_recovery,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)

RestartDisposition: TypeAlias = Literal[
    "requires_review",
    "reviewed_not_started",
    "original_grade_action_pending",
    "original_membership_action_pending",
    "ready_verified",
]
CorrelationReader: TypeAlias = Callable[
    [Path, str], tuple[AssessmentSetupCorrelation, ...]
]
ReceiptReader: TypeAlias = Callable[[Path, str], tuple[TeacherActionReceipt, ...]]
CanonicalReader: TypeAlias = Callable[
    [Path, AssessmentSetupPreview, tuple[TeacherActionReceipt, ...]],
    AssessmentSetupRecoveryInspection,
]


def _correlations(root: Path, class_id: str) -> tuple[AssessmentSetupCorrelation, ...]:
    return AssessmentSetupCorrelationStore(root, class_id).list_records()


def _receipts(root: Path, class_id: str) -> tuple[TeacherActionReceipt, ...]:
    return TeacherActionReceiptStore(root, class_id).list_receipts()


def _canonical(
    root: Path,
    preview: AssessmentSetupPreview,
    receipts: tuple[TeacherActionReceipt, ...],
) -> AssessmentSetupRecoveryInspection:
    # E1 and E2A must see the *same* receipt snapshot.
    readers = AssessmentSetupRecoveryReaders(receipts=lambda _root, _class: receipts)
    return inspect_assessment_setup_recovery(root, preview, readers=readers)


@dataclass(frozen=True, slots=True)
class AssessmentSetupRestartReaders:
    """Pure read ports, injectable for deterministic crash/actor-drift tests."""

    correlations: CorrelationReader = _correlations
    receipts: ReceiptReader = _receipts
    canonical: CanonicalReader = _canonical


@dataclass(frozen=True, slots=True)
class AssessmentSetupRestartInspection:
    """Advisory result. Never a reusable preparation token or authority."""

    disposition: RestartDisposition
    reason: str
    intent_sha256: str | None
    grade_action_id: str | None
    membership_action_id: str | None
    canonical_state: str | None

    @property
    def may_resume_automatically(self) -> bool:
        return False

    @property
    def may_create_new_action(self) -> bool:
        return False

    @property
    def may_select_academic_record(self) -> bool:
        # The #122 port/receipt/revision/actor/basis checks and a separately
        # approved RESUME have NOT been reconstructed or authorized here.
        return False


def inspect_stored_assessment_setup_restart(
    workspace_root: Path,
    preview: AssessmentSetupPreview,
    actor: TeacherActionActor,
    *,
    readers: AssessmentSetupRestartReaders = AssessmentSetupRestartReaders(),
) -> AssessmentSetupRestartInspection:
    """Reconcile exact E2B storage, canonical E1, and original #122 receipts.

    The complete class correlation inventory is mandatory: a missing exact
    fingerprint must never hide another intent claiming the same work/Grade
    Item. Re-read both inventories to refuse a moving snapshot. This does NOT
    form a transaction with canonical academic state; it authorizes no writes.
    """

    def verdict(
        disposition: RestartDisposition,
        reason: str,
        *,
        recorded: AssessmentSetupCorrelation | None = None,
        canonical_state: str | None = None,
    ) -> AssessmentSetupRestartInspection:
        return AssessmentSetupRestartInspection(
            disposition,
            reason,
            None if recorded is None else recorded.intent_sha256,
            None if recorded is None else recorded.grade_action_id,
            None if recorded is None else recorded.membership_action_id,
            canonical_state,
        )

    if (
        not isinstance(workspace_root, Path)
        or not workspace_root.is_absolute()
        or not isinstance(preview, AssessmentSetupPreview)
        or not isinstance(actor, TeacherActionActor)
        or not isinstance(readers, AssessmentSetupRestartReaders)
    ):
        return verdict("requires_review", "invalid_restart_context")
    try:
        baseline = create_assessment_setup_correlation(workspace_root, preview, actor)
        correlations = readers.correlations(workspace_root, preview.class_id)
        if not isinstance(correlations, tuple) or len(correlations) > 10000:
            return verdict("requires_review", "correlation_inventory_unbounded")
        if any(not isinstance(one, AssessmentSetupCorrelation) for one in correlations):
            return verdict("requires_review", "untyped_correlation_record")
        if len({one.intent_sha256 for one in correlations}) != len(correlations):
            return verdict("requires_review", "duplicate_correlation_intent")
        matches = tuple(
            one for one in correlations if one.intent_sha256 == baseline.intent_sha256
        )
        competing = tuple(
            one
            for one in correlations
            if one.grade_item_id == baseline.grade_item_id
            or (one.module_id, one.work_id) == (baseline.module_id, baseline.work_id)
        )
        if len(matches) != 1 or len(competing) != 1 or competing != matches:
            return verdict("requires_review", "missing_or_competing_durable_intent")
        record = matches[0]
        # Identity digest excludes action bindings; exact immutable intent
        # fields still have to match the reviewed current actor/context.
        if record.intent_sha256 != baseline.intent_sha256:
            return verdict("requires_review", "stored_intent_changed")
        receipts = readers.receipts(workspace_root, preview.class_id)
        if not isinstance(receipts, tuple) or len(receipts) > 10000:
            return verdict(
                "requires_review", "receipt_inventory_unbounded", recorded=record
            )
        recovery = readers.canonical(workspace_root, preview, receipts)
        if not isinstance(recovery, AssessmentSetupRecoveryInspection):
            return verdict(
                "requires_review", "invalid_canonical_inspection", recorded=record
            )
        advice = inspect_assessment_setup_correlation(record, recovery, receipts)
        # An inventory that changed during interpretation must not be used
        # even to describe a pending stage as exactly reconciled.
        if (
            readers.correlations(workspace_root, preview.class_id) != correlations
            or readers.receipts(workspace_root, preview.class_id) != receipts
        ):
            return verdict(
                "requires_review",
                "restart_inventory_changed",
                recorded=record,
                canonical_state=recovery.state,
            )
        if advice.advice == "requires_review":
            return verdict(
                "requires_review",
                advice.reason,
                recorded=record,
                canonical_state=recovery.state,
            )
        mapping: dict[str, RestartDisposition] = {
            "not_started": "reviewed_not_started",
            "original_grade_action_pending": "original_grade_action_pending",
            "original_membership_action_pending": "original_membership_action_pending",
            "ready_verified": "ready_verified",
        }
        disposition = mapping.get(advice.advice)
        if disposition is None:
            return verdict(
                "requires_review",
                "unknown_correlation_advice",
                recorded=record,
                canonical_state=recovery.state,
            )
        return verdict(
            disposition,
            advice.reason,
            recorded=record,
            canonical_state=recovery.state,
        )
    except Exception:
        # No log or exception type may turn unavailable/corrupt evidence into
        # an implicit claim of no prior write or a restart authorization.
        return verdict("requires_review", "restart_evidence_unavailable")


__all__ = (
    "AssessmentSetupRestartInspection",
    "AssessmentSetupRestartReaders",
    "RestartDisposition",
    "inspect_stored_assessment_setup_restart",
)
