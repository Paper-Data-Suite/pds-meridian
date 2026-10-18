"""#122 exact single-action kernel; never an arbitrary command executor.

A domain port must bind an existing authoritative authoring/selection workflow.
This kernel supplies one confirmation, ordered journal stages, independent
canonical observations and conservative recovery. It never grants evidence
access or chooses an academic decision, grade, standard, or attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from meridian.teacher_action_contract import (
    ActionKind,
    ActionStage,
    ActionStatus,
    SelectionDisposition,
    StageDisposition,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceipt,
    TeacherActionReceiptError,
    TeacherActionReceiptStore,
    assess_teacher_action_recovery,
)

# Deliberately restrict the adapter surface to reviewed academic record kinds.
_SUPPORTED: frozenset[str] = frozenset(
    {
        "grade_item",
        "grade_item_membership",
        "eligibility",
        "attempt_policy",
        "attempt_decision",
        "standards_association",
        "proficiency_result",
    }
)
_STAGE_ORDER = (
    "preflight",
    "receipt_prepared",
    "write",
    "selection_preview",
    "selection_commit",
    "verification",
    "receipt_finalized",
)


class TeacherActionOrchestrationError(RuntimeError):
    """Internal invalid orchestration request; never canonical success."""


class TeacherActionConflictError(TeacherActionOrchestrationError):
    """Domain revalidation detected changed authority or reviewed meaning."""


@runtime_checkable
class TeacherActionDomainPort(Protocol):
    """One concrete academic family; domain implements canonical invariants.

    revalidate_basis checks actor, permission, publication, work, period, policy,
    and source fingerprints against the exact *reviewed* domain preview. It
    must not assume that the target current selector stays at its prewrite
    baseline after a successful selection. The kernel checks that pointer.

    persist_exact delegates to canonical immutable authoring with its own
    optimistic concurrency protections. select_exact MUST build and commit
    the exact persisted revision's existing CAS selection preview, including
    full current-dependency checks; never select "latest" or infer authority.
    observe independently reloads canonical history, current pointer/digest,
    and applicability. It must not consult the receipt or in-memory result.
    """

    kind: ActionKind

    def revalidate_basis(self, preview: TeacherActionPreview) -> None: ...

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation: ...

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord: ...

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition: ...


@dataclass(frozen=True, slots=True)
class _Truth:
    observation: CanonicalActionObservation
    record: TeacherActionRecord | None
    pointer: Literal["baseline", "target", "diverged", "unknown"]


def _inspect(preview: TeacherActionPreview, port: TeacherActionDomainPort) -> _Truth:
    observed = port.observe(preview)
    if not isinstance(observed, CanonicalActionObservation):
        raise TeacherActionOrchestrationError("Invalid canonical observation.")
    target = preview.target
    if not observed.target_history_verified:
        raise TeacherActionOrchestrationError("Canonical history is not verified.")
    if observed.target_sha256 is not None and (
        observed.target_sha256 != target.candidate_sha256
    ):
        raise TeacherActionConflictError("Reviewed immutable digest changed.")
    record = (
        None
        if observed.target_sha256 is None
        else TeacherActionRecord(
            target.family,
            target.identity_sha256,
            target.revision,
            target.candidate_sha256,
            "existing",
        )
    )
    if observed.current_basis == "unknown":
        pointer: Literal["baseline", "target", "diverged", "unknown"] = "unknown"
    elif (
        observed.current_revision == target.revision
        and observed.current_sha256 == target.candidate_sha256
    ):
        pointer = "target"
    elif (
        observed.current_revision == target.expected_current_revision
        and observed.current_sha256 == target.expected_current_sha256
    ):
        pointer = "baseline"
    else:
        pointer = "diverged"
    return _Truth(observed, record, pointer)


def _outcome(
    preview: TeacherActionPreview,
    status: ActionStatus,
    *,
    record: TeacherActionRecord | None = None,
    pointer: Literal["baseline", "target", "diverged", "unknown"] = "unknown",
    disposition: SelectionDisposition = "not_attempted",
    reason: str | None = None,
    verified: bool = False,
) -> TeacherActionResult:
    if verified and record is not None and pointer == "target":
        current_state: Literal["matches", "not_current", "unknown", "not_checked"] = (
            "matches"
        )
        current_record = record
    elif record is not None and pointer in ("baseline", "diverged"):
        current_state = "not_current"
        current_record = None
    elif record is not None:
        current_state = "unknown"
        current_record = None
    else:
        current_state = "not_checked"
        current_record = None
    return TeacherActionResult(
        action_id=preview.action_id,
        intent_sha256=preview.intent_sha256,
        target=preview.target,
        status=status,
        persisted=() if record is None else (record,),
        current_state=current_state,
        current_record=current_record,
        selection_disposition=disposition,
        reason_code=reason,
    )


def _recovery_outcome(
    preview: TeacherActionPreview,
    store: TeacherActionReceiptStore,
    port: TeacherActionDomainPort,
) -> TeacherActionResult:
    assessment = assess_teacher_action_recovery(store, preview, port.observe)
    if assessment.reason == "exact_current":
        record: TeacherActionRecord | None = TeacherActionRecord(
            preview.kind,
            preview.target.identity_sha256,
            preview.target.revision,
            preview.target.candidate_sha256,
            "existing",
        )
        return _outcome(
            preview,
            "already_applied",
            record=record,
            pointer="target",
            disposition="existing",
            verified=True,
        )
    record = (
        TeacherActionRecord(
            preview.kind,
            preview.target.identity_sha256,
            preview.target.revision,
            preview.target.candidate_sha256,
            "existing",
        )
        if assessment.target_verified_present
        else None
    )
    if assessment.status == "written_not_current":
        return _outcome(
            preview,
            "written_not_current",
            record=record,
            pointer="baseline",
            reason=assessment.reason,
        )
    if assessment.status == "current_unverified":
        return _outcome(
            preview,
            "current_unverified",
            record=record,
            pointer="unknown",
            reason=assessment.reason,
        )
    if assessment.status == "blocked_before_write":
        return _outcome(preview, "blocked_before_write", reason=assessment.reason)
    return _outcome(
        preview,
        assessment.status,
        record=record,
        pointer="unknown",
        reason=assessment.reason,
    )


def _failure(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    *,
    reason: str,
    attempted_mutation: bool,
    selection_attempted: bool = False,
    audit_failure: bool = False,
) -> TeacherActionResult:
    """After any possible mutation, inspect canonical state before reporting.

    A journal-write failure never produces a success response even if the
    selector appears current: external recovery must review both records.
    """
    if not attempted_mutation:
        return _outcome(preview, "blocked_before_write", reason=reason)
    try:
        truth = _inspect(preview, port)
    except TeacherActionConflictError:
        return _outcome(preview, "conflict_requires_review", reason="target_conflict")
    except Exception:
        return _outcome(preview, "recovery_required", reason="canonical_read_failed")
    if truth.record is None:
        return _outcome(preview, "recovery_required", reason="write_indeterminate")
    if audit_failure:
        return _outcome(
            preview,
            "recovery_required",
            record=truth.record,
            reason="receipt_write_failed",
        )
    if truth.observation.current_basis == "stale":
        return _outcome(
            preview,
            "conflict_requires_review",
            record=truth.record,
            reason="dependencies_changed",
        )
    if truth.pointer == "baseline":
        return _outcome(
            preview,
            "written_not_current",
            record=truth.record,
            pointer="baseline",
            reason=reason,
        )
    if truth.pointer == "diverged":
        return _outcome(
            preview,
            "conflict_requires_review",
            record=truth.record,
            pointer="diverged",
            reason="current_pointer_changed",
        )
    return _outcome(
        preview,
        "current_unverified",
        record=truth.record,
        reason="selection_or_verification_uncertain",
    )


def _append(
    store: TeacherActionReceiptStore,
    preview: TeacherActionPreview,
    receipt: TeacherActionReceipt,
    stage: ActionStage,
    *,
    record: TeacherActionRecord | None = None,
    disposition: StageDisposition = "completed",
    reason: str | None = None,
) -> TeacherActionReceipt:
    # A resumed selection may already have a later journal checkpoint. Never
    # move backwards; repeat only equal or forward stages in receipt order.
    if _STAGE_ORDER.index(stage) < _STAGE_ORDER.index(receipt.checkpoints[-1].stage):
        return receipt
    records = receipt.observed_records
    if record is not None and not any(
        item.matches_target(preview.target) for item in records
    ):
        records = (*records, record)
    return store.record_checkpoint(
        preview,
        expected_generation=receipt.generation,
        checkpoint=TeacherActionCheckpoint(stage, disposition, reason),
        observed_records=records,
    )


def _record_failure(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    stage: ActionStage,
    reason: str,
    *,
    attempted_mutation: bool = True,
    selection_attempted: bool = False,
) -> TeacherActionResult:
    """Best-effort attributable failure checkpoint, then canonical truth.

    If the receipt itself fails, a canonical write remains a recovery case;
    no failure checkpoint is invented and no success is claimed.
    """
    result = _failure(
        preview,
        port,
        reason=reason,
        attempted_mutation=attempted_mutation,
        selection_attempted=selection_attempted,
    )
    try:
        _append(
            store,
            preview,
            receipt,
            stage,
            record=result.persisted[0] if result.persisted else None,
            disposition="unknown" if attempted_mutation else "blocked",
            reason=reason,
        )
    except TeacherActionReceiptError:
        if attempted_mutation:
            return _failure(
                preview,
                port,
                reason="receipt_write_failed",
                attempted_mutation=True,
                selection_attempted=selection_attempted,
                audit_failure=True,
            )
    return result


def _check_request(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    store: TeacherActionReceiptStore,
) -> None:
    if not isinstance(preview, TeacherActionPreview):
        raise TeacherActionOrchestrationError("Invalid reviewed action.")
    if preview.kind not in _SUPPORTED or port.kind != preview.kind:
        raise TeacherActionOrchestrationError("Wrong domain adapter for action.")
    if not preview.make_current:
        raise TeacherActionOrchestrationError(
            "Write-only operations belong to the advanced authoring services."
        )
    if store.class_id != preview.scope.class_id:
        raise TeacherActionOrchestrationError("Journal and class scope differ.")


def apply_reviewed_teacher_action(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    store: TeacherActionReceiptStore,
    *,
    confirmation: str,
) -> TeacherActionResult:
    """Execute one already-reviewed academic choice after ONE APPLY.

    No prompt exists in this service. Cancellation is side-effect-free. Existing
    incomplete journal actions are assessed, not silently replayed.
    """
    _check_request(preview, port, store)
    if confirmation != "APPLY":
        return _outcome(preview, "blocked_before_write", reason="not_confirmed")
    try:
        port.revalidate_basis(preview)
        initial = _inspect(preview, port)
    except TeacherActionConflictError:
        return _outcome(preview, "conflict_requires_review", reason="preflight_stale")
    except Exception:
        return _outcome(preview, "blocked_before_write", reason="preflight_blocked")
    if initial.observation.current_basis != "current":
        return _outcome(preview, "conflict_requires_review", reason="basis_not_current")
    if initial.pointer in ("diverged", "unknown"):
        return _outcome(preview, "conflict_requires_review", reason="baseline_changed")
    try:
        old_receipt = store.load(preview.action_id)
    except TeacherActionReceiptError:
        return _outcome(preview, "recovery_required", reason="unsafe_receipt")
    if old_receipt is not None and old_receipt.preview != preview:
        return _outcome(preview, "conflict_requires_review", reason="intent_changed")
    if old_receipt is not None and old_receipt.phase != "prepared":
        return _recovery_outcome(preview, store, port)
    if initial.record is not None:
        # An absent (or prepared-only) journal cannot justify selecting a
        # preexisting canonical record with no proven prior operation.
        return _outcome(
            preview,
            "recovery_required",
            record=initial.record,
            reason="target_requires_reconciliation",
        )
    try:
        receipt = store.prepare(preview)
        # CAS claim fences concurrent action IDs before either writer starts.
        receipt = _append(store, preview, receipt, "receipt_prepared")
    except TeacherActionReceiptError:
        return _outcome(preview, "blocked_before_write", reason="receipt_unavailable")
    # The claim makes a restart conservative, rather than rewriting history.
    try:
        port.revalidate_basis(preview)
        before = _inspect(preview, port)
        if (
            before.record is not None
            or before.pointer != "baseline"
            or before.observation.current_basis != "current"
        ):
            return _outcome(
                preview, "conflict_requires_review", reason="prewrite_stale"
            )
    except Exception:
        return _outcome(preview, "conflict_requires_review", reason="prewrite_stale")
    try:
        written = port.persist_exact(preview)
        if not isinstance(written, TeacherActionRecord) or not written.matches_target(
            preview.target
        ):
            raise TeacherActionOrchestrationError("Authoring returned wrong revision.")
    except Exception:
        return _record_failure(
            preview,
            port,
            store,
            receipt,
            "write",
            "write_failed",
        )
    try:
        receipt = _append(store, preview, receipt, "write", record=written)
    except TeacherActionReceiptError:
        return _failure(
            preview,
            port,
            reason="receipt_write_failed",
            attempted_mutation=True,
            audit_failure=True,
        )
    return _finish_selection(preview, port, store, receipt, written)


def _finish_selection(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    store: TeacherActionReceiptStore,
    receipt: TeacherActionReceipt,
    record: TeacherActionRecord,
) -> TeacherActionResult:
    try:
        port.revalidate_basis(preview)
        truth = _inspect(preview, port)
        if (
            truth.record is None
            or truth.pointer != "baseline"
            or truth.observation.current_basis != "current"
        ):
            return _record_failure(
                preview,
                port,
                store,
                receipt,
                "selection_preview",
                "selection_basis_changed",
            )
        receipt = _append(store, preview, receipt, "selection_preview", record=record)
    except TeacherActionReceiptError:
        return _failure(
            preview,
            port,
            reason="receipt_write_failed",
            attempted_mutation=True,
            audit_failure=True,
        )
    except Exception:
        return _record_failure(
            preview,
            port,
            store,
            receipt,
            "selection_preview",
            "selection_preview_failed",
        )
    try:
        selection = port.select_exact(preview, record)
        if selection not in ("created", "updated", "existing"):
            raise TeacherActionOrchestrationError("Unknown selection disposition.")
    except Exception:
        return _record_failure(
            preview,
            port,
            store,
            receipt,
            "selection_commit",
            "selection_failed",
            selection_attempted=True,
        )
    try:
        receipt = _append(store, preview, receipt, "selection_commit", record=record)
    except TeacherActionReceiptError:
        return _failure(
            preview,
            port,
            reason="receipt_write_failed",
            attempted_mutation=True,
            selection_attempted=True,
            audit_failure=True,
        )
    try:
        port.revalidate_basis(preview)
        truth = _inspect(preview, port)
    except Exception:
        return _record_failure(
            preview,
            port,
            store,
            receipt,
            "verification",
            "verification_failed",
            selection_attempted=True,
        )
    if (
        truth.pointer != "target"
        or truth.record is None
        or truth.observation.current_basis != "current"
    ):
        return _record_failure(
            preview,
            port,
            store,
            receipt,
            "verification",
            "postcondition_failed",
            selection_attempted=True,
        )
    try:
        receipt = _append(store, preview, receipt, "verification", record=record)
        _append(store, preview, receipt, "receipt_finalized", record=record)
    except TeacherActionReceiptError:
        return _failure(
            preview,
            port,
            reason="receipt_write_failed",
            attempted_mutation=True,
            selection_attempted=True,
            audit_failure=True,
        )
    return _outcome(
        preview,
        "applied",
        record=record,
        pointer="target",
        disposition=selection,
        verified=True,
    )


def resume_exact_teacher_selection(
    preview: TeacherActionPreview,
    port: TeacherActionDomainPort,
    store: TeacherActionReceiptStore,
    *,
    confirmation: str,
) -> TeacherActionResult:
    """Separate EXPLICIT resume action; never write a new immutable revision."""
    _check_request(preview, port, store)
    if confirmation != "RESUME":
        return _outcome(preview, "blocked_before_write", reason="not_confirmed")
    try:
        port.revalidate_basis(preview)
        assessment = assess_teacher_action_recovery(store, preview, port.observe)
    except Exception:
        return _outcome(preview, "recovery_required", reason="recovery_unavailable")
    if assessment.reason == "exact_current":
        return _recovery_outcome(preview, store, port)
    if not assessment.can_resume_exact_selection:
        return _recovery_outcome(preview, store, port)
    try:
        receipt = store.load(preview.action_id)
        if receipt is None or receipt.preview != preview:
            raise TeacherActionOrchestrationError("Exact receipt is absent.")
        truth = _inspect(preview, port)
        if (
            truth.record is None
            or truth.pointer != "baseline"
            or truth.observation.current_basis != "current"
        ):
            raise TeacherActionConflictError("Reviewed state changed on resume.")
    except Exception:
        return _outcome(preview, "conflict_requires_review", reason="resume_stale")
    return _finish_selection(preview, port, store, receipt, truth.record)


__all__ = (
    "TeacherActionConflictError",
    "TeacherActionDomainPort",
    "TeacherActionOrchestrationError",
    "apply_reviewed_teacher_action",
    "resume_exact_teacher_selection",
)
