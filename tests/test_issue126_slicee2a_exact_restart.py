"""#126 E2A: exact-action restart tests; all student/teacher data synthetic."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_issue126_sliced2a_reassessment_review import _review, _scenario

from meridian.attempt_pair_recovery import (
    ActionReceiptWitness,
    DurablePairRecoveryAssessment,
)
from meridian.attempt_pair_restart import (
    AttemptPairRestartError,
    RestartPorts,
    prepare_exact_pair_restart,
    render_exact_pair_restart,
)
from meridian.attempt_reassessment_review import ReviewedReassessmentChoice
from meridian.teacher_action_contract import (
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_reassessment import ReassessmentActionOutcome
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)

_NOW = "2026-11-18T12:00:00+00:00"


class _Port:
    def __init__(self, original, world):
        self.original = original
        self.world = world

    def revalidate_basis(self, preview):
        self.world.events.append("revalidate")
        assert preview == self.original
        if self.world.stale_actor:
            raise ValueError("Authority expired")

    def observe(self, preview):
        self.world.events.append("observe")
        assert preview == self.original
        return CanonicalActionObservation(
            target_sha256=preview.target.candidate_sha256,
            current_revision=preview.target.expected_current_revision,
            current_sha256=preview.target.expected_current_sha256,
            current_basis="current",
        )

    def persist_exact(self, preview):
        self.world.immutable_writes += 1
        raise AssertionError("Recovery cannot write an immutable decision")

    def select_exact(self, preview, record):
        assert preview == self.original
        assert record.matches_target(preview.target)
        self.world.selections += 1
        self.world.pair_current = True
        return "created"


@dataclass
class _World:
    receipt: TeacherActionReceipt
    original: TeacherActionPreview
    prepared: object
    authoring: object
    review: object
    actor: object
    root: Path
    phase: str = "written"
    pair_current: bool = False
    stale_actor: bool = False
    changed_receipt: bool = False
    resume_error: bool = False
    resume_status: str = "applied"
    observer_exact: bool = True
    observer_error: bool = False
    invalid_postread: bool = False
    invalidate_fresh_action: bool = False
    events: list[str] | None = None
    immutable_writes: int = 0
    selections: int = 0
    resumes: int = 0

    def __post_init__(self):
        self.events = []


def _setup(tmp_path):
    interpretation, authoring, policy, actor, a, b = _scenario()
    review = _review(
        ReviewedReassessmentChoice("retain"),
        setup=(interpretation, authoring, policy, actor, a, b),
    )
    decision = review.decision
    source_binding = _identity(
        "reassessment_source",
        review.upstream_decision_sha256,
        review.policy_sha256,
        decision.work.module_id,
        decision.work.work_id,
    )
    identity = _identity(
        "reassessment_decision",
        decision.class_id,
        decision.grade_item_id,
        decision.work.module_id,
        decision.work.work_id,
        decision.student_id,
    )
    preview = TeacherActionPreview(
        action_id="b" * 32,
        kind="reassessment_decision",
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(tmp_path)),
            class_id=decision.class_id,
            grade_item_id=decision.grade_item_id,
            work_identity_sha256=_identity(
                "work",
                decision.class_id,
                decision.work.module_id,
                decision.work.work_id,
            ),
        ),
        actor=actor,
        target=TeacherActionTarget(
            family="reassessment_decision",
            identity_sha256=identity,
            revision=decision.decision_revision,
            candidate_sha256=review.reassessment_decision_sha256,
            expected_current_revision=review.expected_current_reassessment[0],
            expected_current_sha256=review.expected_current_reassessment[1],
        ),
        basis=(
            TeacherActionBasis(
                "actor_profile", _identity(actor.actor_id), actor.profile_sha256
            ),
            TeacherActionBasis("canonical_source", identity, source_binding),
        ),
        reviewed_decision_sha256=review.reassessment_decision_sha256,
    )
    record = TeacherActionRecord(
        "reassessment_decision",
        identity,
        decision.decision_revision,
        review.reassessment_decision_sha256,
        "created",
    )
    receipt = TeacherActionReceipt(
        preview=preview,
        generation=2,
        created_at=_NOW,
        updated_at=_NOW,
        phase="in_progress",
        checkpoints=(
            TeacherActionCheckpoint("receipt_prepared", "completed"),
            TeacherActionCheckpoint("write", "completed"),
        ),
        observed_records=(record,),
    )
    return _World(
        receipt=receipt,
        original=preview,
        prepared=NS(),
        authoring=authoring,
        review=review,
        actor=actor,
        root=tmp_path,
    )


def _assessment(world):
    if world.phase == "missing":
        return DurablePairRecoveryAssessment(
            "upstream_current_reassessment_missing",
            "upstream_current_reassessment_missing",
            ActionReceiptWitness("missing"),
            ActionReceiptWitness("missing"),
            True,
            False,
        )
    if world.phase == "ambiguous":
        return DurablePairRecoveryAssessment(
            "journal_ambiguous",
            "reassessment_written_not_current",
            ActionReceiptWitness("missing"),
            ActionReceiptWitness("ambiguous"),
            True,
            False,
        )
    if world.phase == "unknown":
        raise OSError("Unsafe journal or canonical read")
    if world.phase == "not_current":
        return DurablePairRecoveryAssessment(
            "upstream_not_current",
            "upstream_not_current",
            ActionReceiptWitness("missing"),
            ActionReceiptWitness("in_progress", world.original.action_id, ("write",)),
            False,
            False,
        )
    if world.phase == "current" or world.pair_current:
        return DurablePairRecoveryAssessment(
            (
                "pair_current_verified"
                if not world.invalid_postread
                else "canonical_unverifiable"
            ),
            "pair_current" if not world.invalid_postread else "unknown",
            ActionReceiptWitness("missing"),
            ActionReceiptWitness("in_progress", world.original.action_id, ("write",)),
            True,
            not world.invalid_postread,
        )
    return DurablePairRecoveryAssessment(
        "reassessment_written_not_current",
        "reassessment_written_not_current",
        ActionReceiptWitness("missing"),
        ActionReceiptWitness(
            "in_progress", world.original.action_id, ("receipt_prepared", "write")
        ),
        True,
        False,
    )


def _ports(world):
    def inspect(*args, **kwargs):
        world.events.append("inspect")
        return _assessment(world)

    def load(root, class_id, action_id):
        world.events.append("receipt")
        assert root == world.root
        assert class_id == world.authoring.candidate.class_id
        assert action_id == world.original.action_id
        if world.changed_receipt:
            return replace(world.receipt, generation=world.receipt.generation + 1)
        return world.receipt

    def fresh(*args, **kwargs):
        world.events.append("fresh_authority")
        preview = replace(
            world.original,
            action_id="c" * 32,
            reviewed_decision_sha256=(
                "a" * 64
                if world.invalidate_fresh_action
                else world.original.reviewed_decision_sha256
            ),
        )
        return PreparedGuidedAction(
            preview=preview,
            port=_Port(preview, world),
            store=TeacherActionReceiptStore(
                world.root, world.authoring.candidate.class_id
            ),
        )

    def resume(preview, port, store, *, confirmation):
        world.events.append("resume")
        world.resumes += 1
        assert confirmation == "RESUME"
        assert preview == world.original
        assert port.kind == "reassessment_decision"
        port.revalidate_basis(preview)
        if world.resume_error:
            raise OSError("selection result unknown")
        if world.resume_status not in ("applied", "already_applied"):
            return TeacherActionResult(
                action_id=preview.action_id,
                intent_sha256=preview.intent_sha256,
                target=preview.target,
                status="recovery_required",
                persisted=(),
                current_state="not_checked",
                current_record=None,
                selection_disposition="not_attempted",
                reason_code="resume_failed",
            )
        record = world.receipt.observed_records[0]
        # Selecting the target is the only academic mutation allowed on restart.
        port.select_exact(preview, record)
        return TeacherActionResult(
            action_id=preview.action_id,
            intent_sha256=preview.intent_sha256,
            target=preview.target,
            status="applied",
            persisted=(record,),
            current_state="matches",
            current_record=record,
            selection_disposition="created",
        )

    def observer(*args, **kwargs):
        world.events.append("observe_current")
        if world.observer_error:
            raise OSError("Resolver unavailable")
        return ReassessmentActionOutcome(
            "applied_current" if world.observer_exact else "current_unverified",
            "resolved" if world.observer_exact else "no_decision",
            world.observer_exact,
        )

    return RestartPorts(inspect, load, fresh, resume, observer)


def _prepare(world):
    return prepare_exact_pair_restart(
        world.root,
        prepared=world.prepared,
        authoring=world.authoring,
        review=world.review,
        actor=world.actor,
        ports=_ports(world),
    )


def test_prepare_is_read_only_and_uses_original_action_id(tmp_path):
    world = _setup(tmp_path)
    plan = _prepare(world)
    assert plan.original_receipt.action_id == "b" * 32
    assert world.events == ["inspect", "receipt"]
    assert world.immutable_writes == world.selections == 0
    text = render_exact_pair_restart(plan)
    assert "NOT YET SELECTED" in text
    assert "synthetic_student_02" not in text
    assert "bbbbbbbb" not in text


def test_one_confirmed_resume_never_writes_new_immutable_decision(tmp_path):
    world = _setup(tmp_path)
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "pair_current_verified"
    assert outcome.exact_pair_current and outcome.continue_to_standards_review
    assert world.immutable_writes == 0 and world.selections == 1
    assert world.resumes == 1
    assert world.events[-2:] == ["observe_current", "inspect"]


def test_canceled_restart_does_not_even_reprepare_port(tmp_path):
    world = _setup(tmp_path)
    outcome = _prepare(world).resume(confirmed=False)
    assert outcome.status == "canceled_before_selection"
    assert world.events == ["inspect", "receipt"]
    assert world.immutable_writes == world.selections == world.resumes == 0


def test_same_prepared_restart_cannot_run_twice(tmp_path):
    world = _setup(tmp_path)
    plan = _prepare(world)
    assert plan.resume(confirmed=True).status == "pair_current_verified"
    assert plan.resume(confirmed=True).status == "recovery_required"
    assert world.selections == world.resumes == 1


@pytest.mark.parametrize("phase", ["missing", "ambiguous", "current", "not_current"])
def test_nonrecoverable_canonical_or_journal_state_never_prepares(tmp_path, phase):
    world = _setup(tmp_path)
    world.phase = phase
    with pytest.raises(AttemptPairRestartError):
        _prepare(world)
    assert world.selections == world.resumes == 0


def test_original_receipt_generation_drift_blocks_before_selection(tmp_path):
    world = _setup(tmp_path)
    plan = _prepare(world)
    world.changed_receipt = True
    assert plan.resume(confirmed=True).status == "conflict_requires_review"
    assert world.selections == world.resumes == 0


def test_original_record_must_be_observed_in_journal(tmp_path):
    world = _setup(tmp_path)
    world.receipt = replace(world.receipt, observed_records=())
    with pytest.raises(AttemptPairRestartError):
        _prepare(world)


def test_write_checkpoint_must_exist_before_resume(tmp_path):
    world = _setup(tmp_path)
    world.receipt = replace(
        world.receipt,
        checkpoints=(
            TeacherActionCheckpoint("receipt_prepared", "completed"),
            TeacherActionCheckpoint("write", "unknown", "write_uncertain"),
        ),
    )
    with pytest.raises(AttemptPairRestartError):
        _prepare(world)


def test_actor_mismatch_blocks_preparation(tmp_path):
    world = _setup(tmp_path)
    other = replace(world.actor, actor_id="other_teacher")
    with pytest.raises(AttemptPairRestartError):
        prepare_exact_pair_restart(
            world.root,
            prepared=world.prepared,
            authoring=world.authoring,
            review=world.review,
            actor=other,
            ports=_ports(world),
        )


def test_freshly_prepared_action_must_match_original_except_id(tmp_path):
    world = _setup(tmp_path)
    world.invalidate_fresh_action = True
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "conflict_requires_review"
    assert world.resumes == world.selections == 0


def test_canonical_read_failure_before_selection_is_uncertain(tmp_path):
    world = _setup(tmp_path)
    plan = _prepare(world)
    world.phase = "unknown"
    assert plan.resume(confirmed=True).status == "current_unverified"
    assert world.resumes == world.selections == 0


def test_upstream_no_longer_current_blocks_selection(tmp_path):
    world = _setup(tmp_path)
    plan = _prepare(world)
    world.phase = "not_current"
    assert plan.resume(confirmed=True).status == "conflict_requires_review"
    assert world.resumes == world.selections == 0


def test_selection_exception_never_reported_as_rollback(tmp_path):
    world = _setup(tmp_path)
    world.resume_error = True
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "recovery_required"
    assert outcome.reason == "selection_outcome_unknown"
    assert world.immutable_writes == world.selections == 0


def test_recovery_service_denial_does_not_write_again(tmp_path):
    world = _setup(tmp_path)
    world.resume_status = "recovery_required"
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "recovery_required"
    assert world.immutable_writes == world.selections == 0


def test_postresume_readback_failure_cannot_claim_current_pair(tmp_path):
    world = _setup(tmp_path)
    world.observer_error = True
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "current_unverified"
    assert world.selections == 1
    assert not outcome.continue_to_standards_review


def test_resolver_denial_prevents_academic_continuation(tmp_path):
    world = _setup(tmp_path)
    world.observer_exact = False
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "current_unverified"
    assert world.selections == 1


def test_pair_postcondition_must_independently_verify_both(tmp_path):
    world = _setup(tmp_path)
    world.invalid_postread = True
    outcome = _prepare(world).resume(confirmed=True)
    assert outcome.status == "current_unverified"
    assert world.selections == 1


def test_recovery_proxy_refuses_immutable_writer_call(tmp_path):
    world = _setup(tmp_path)

    def malicious_service(preview, port, store, *, confirmation):
        port.persist_exact(preview)
        raise AssertionError("should never author")

    ports = _ports(world)
    ports = replace(ports, resume_service=malicious_service)
    plan = prepare_exact_pair_restart(
        world.root,
        prepared=world.prepared,
        authoring=world.authoring,
        review=world.review,
        actor=world.actor,
        ports=ports,
    )
    assert plan.resume(confirmed=True).status == "recovery_required"
    assert world.immutable_writes == 0


def test_wrong_source_hash_never_prepares(tmp_path):
    world = _setup(tmp_path)
    forged = replace(world.review, upstream_decision_sha256="f" * 64)
    with pytest.raises(ValueError):
        prepare_exact_pair_restart(
            world.root,
            prepared=world.prepared,
            authoring=world.authoring,
            review=forged,
            actor=world.actor,
            ports=_ports(world),
        )


def test_exact_port_rebinding_preserves_all_original_preview_fields(tmp_path):
    world = _setup(tmp_path)
    ports = _ports(world)
    plan = prepare_exact_pair_restart(
        world.root,
        prepared=world.prepared,
        authoring=world.authoring,
        review=world.review,
        actor=world.actor,
        ports=ports,
    )
    assert plan.original_receipt.preview.action_id == "b" * 32
    assert plan.resume(confirmed=True).status == "pair_current_verified"
    assert "fresh_authority" in world.events
    assert world.immutable_writes == 0
