"""#126-E2B: an explicit new #31 action is never an implicit #30 replay."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from test_issue126_sliceb_attempt_inventory import _build, _case
from test_issue126_sliced2b2_multi_attempt_coordinator import _rig

from meridian.attempt_pair_new_continuation import (
    AttemptPairNewContinuationError,
    NewContinuationPorts,
    prepare_new_pair_continuation,
    render_new_pair_continuation,
)
from meridian.attempt_pair_recovery import PairRecoveryPorts
from meridian.attempt_resolution_coordinator import assess_multi_attempt_recovery
from meridian.teacher_action_contract import (
    TeacherActionBasis,
    TeacherActionCheckpoint,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_reassessment import ReassessmentActionOutcome
from meridian.teacher_action_receipts import TeacherActionReceipt

_AT = "2026-11-18T15:00:00+00:00"


def _preview(ctx, kind, *, action_id=None, digest=None):
    first, second = ctx.authoring.candidate, ctx.review.decision
    target = first if kind == "attempt_decision" else second
    source_hash = (
        ctx.review.upstream_decision_sha256
        if kind == "attempt_decision"
        else ctx.review.reassessment_decision_sha256
    )
    if digest is not None:
        source_hash = digest
    identity = _identity(
        kind,
        first.class_id,
        first.grade_item_id,
        first.work.module_id,
        first.work.work_id,
        first.student_id,
    )
    binding = (
        _identity(
            "attempt_source",
            first.source_snapshot.publication_id,
            first.source_snapshot.cache_key,
            first.source_snapshot.snapshot_digest,
            first.membership_revision_sha256,
            first.policy.policy_revision_sha256,
        )
        if kind == "attempt_decision"
        else _identity(
            "reassessment_source",
            ctx.review.upstream_decision_sha256,
            ctx.review.policy_sha256,
            first.work.module_id,
            first.work.work_id,
        )
    )
    old_rev, old_sha = (
        (
            ctx.authoring.reviewed_current_decision_revision,
            ctx.authoring.latest_persisted_decision_sha256,
        )
        if kind == "attempt_decision"
        else ctx.review.expected_current_reassessment
    )
    return TeacherActionPreview(
        action_id=action_id or ("a" * 32 if kind == "attempt_decision" else "c" * 32),
        kind=kind,
        scope=TeacherActionScope(
            workspace_sha256=_identity("workspace", str(ctx.root)),
            class_id=first.class_id,
            grade_item_id=first.grade_item_id,
            work_identity_sha256=_identity(
                "work", first.class_id, first.work.module_id, first.work.work_id
            ),
        ),
        actor=ctx.actor,
        target=TeacherActionTarget(
            family=kind,
            identity_sha256=identity,
            revision=target.decision_revision,
            candidate_sha256=source_hash,
            expected_current_revision=old_rev,
            expected_current_sha256=old_sha,
        ),
        basis=(
            TeacherActionBasis(
                "actor_profile",
                _identity(ctx.actor.actor_id),
                ctx.actor.profile_sha256,
            ),
            TeacherActionBasis("canonical_source", identity, binding),
        ),
        reviewed_decision_sha256=source_hash,
    )


def _record(preview):
    target = preview.target
    return TeacherActionRecord(
        target.family,
        target.identity_sha256,
        target.revision,
        target.candidate_sha256,
        "created",
    )


def _receipt(preview, *, written=True, include_record=True):
    return TeacherActionReceipt(
        preview=preview,
        generation=2 if written else 1,
        created_at=_AT,
        updated_at=_AT,
        phase="in_progress" if written else "prepared",
        checkpoints=(
            TeacherActionCheckpoint("receipt_prepared", "completed"),
            *((TeacherActionCheckpoint("write", "completed"),) if written else ()),
        ),
        observed_records=(_record(preview),) if written and include_record else (),
    )


class _New31Action:
    def __init__(self, ctx, probe):
        self.ctx = ctx
        self.probe = probe
        self.preview = _preview(ctx, "reassessment_decision")
        self.calls = 0

    def apply(self, *, confirmed):
        assert confirmed is True
        self.calls += 1
        self.probe["execution"] += 1
        if self.probe["exception"]:
            raise OSError("Writer may have started; status unknown")
        disposition = self.probe["result_status"]
        record = _record(self.preview)
        if disposition in ("applied", "already_applied"):
            self.ctx.world.history = (self.ctx.review.decision.decision_revision,)
            self.ctx.world.reassessment_current = True
            self.probe["receipts"].append(_receipt(self.preview))
            current_record = record if self.probe["valid_record"] else None
            return (
                TeacherActionResult(
                    action_id=self.preview.action_id,
                    intent_sha256=self.preview.intent_sha256,
                    target=self.preview.target,
                    status=disposition,
                    persisted=(record,),
                    current_state="matches" if current_record else "unknown",
                    current_record=current_record,
                    selection_disposition="created"
                    if disposition == "applied"
                    else "existing",
                )
                if current_record
                else _result(self.preview, "current_unverified", record=record)
            )
        if disposition == "written_not_current":
            self.ctx.world.history = (self.ctx.review.decision.decision_revision,)
            self.probe["receipts"].append(_receipt(self.preview))
            return _result(self.preview, disposition, record=record)
        return _result(self.preview, disposition)


def _result(preview, status, *, record=None):
    if status == "written_not_current":
        state = "not_current"
        persisted = (record,)
    elif status == "current_unverified":
        state = "unknown"
        persisted = (record,)
    else:
        state = "not_checked"
        persisted = ()
    return TeacherActionResult(
        action_id=preview.action_id,
        intent_sha256=preview.intent_sha256,
        target=preview.target,
        status=status,
        persisted=persisted,
        current_state=state,
        current_record=None,
        selection_disposition="not_attempted",
        reason_code="stopped_after_review",
    )


def _setup(monkeypatch):
    ctx = _rig(monkeypatch)
    ctx.world.upstream_current = True
    original = _receipt(_preview(ctx, "attempt_decision"))
    probe = {
        "receipts": [original],
        "execution": 0,
        "prepares": 0,
        "exception": False,
        "result_status": "applied",
        "valid_record": True,
        "observer_exact": True,
        "observer_error": False,
        "inspector_error": False,
        "source_error": False,
        "action_mutator": None,
    }
    action = _New31Action(ctx, probe)
    inventory = _build(_case())
    native_ports = replace(ctx.ports, inventory_loader=lambda *args, **kw: inventory)
    pair_ports = PairRecoveryPorts(
        canonical_inspector=assess_multi_attempt_recovery,
        receipt_reader=lambda root, class_id: tuple(probe["receipts"]),
    )

    def inspect(*args, **kwargs):
        if probe["inspector_error"]:
            raise OSError("journal unreadable")
        from meridian.attempt_pair_recovery import inspect_durable_pair_recovery

        return inspect_durable_pair_recovery(*args, **kwargs)

    def read_receipts(root, class_id):
        return tuple(probe["receipts"])

    def prepare(*args, **kwargs):
        probe["prepares"] += 1
        mutator = probe["action_mutator"]
        return action if mutator is None else mutator(action)

    def observe(*args, **kwargs):
        if probe["observer_error"]:
            raise OSError("Cannot independently read #31")
        exact = probe["observer_exact"]
        return ReassessmentActionOutcome(
            "applied_current" if exact else "current_unverified",
            "resolved" if exact else "no_decision",
            exact,
        )

    ports = NewContinuationPorts(inspect, read_receipts, prepare, observe)
    return NS(
        ctx=ctx,
        probe=probe,
        action=action,
        ports=ports,
        pair_ports=pair_ports,
        canonical_ports=native_ports,
        interpretation=ctx.interpretation,
    )


def _prepare(s):
    ctx = s.ctx
    return prepare_new_pair_continuation(
        ctx.root,
        prepared=ctx.prepared,
        interpretation=s.interpretation,
        authoring=ctx.authoring,
        review=ctx.review,
        actor=ctx.actor,
        canonical_ports=s.canonical_ports,
        pair_ports=s.pair_ports,
        ports=s.ports,
    )


def test_preparation_requires_original_upstream_and_creates_no_writes(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    assert plan.action is s.action
    assert plan.attempted is False
    assert s.probe["prepares"] == 1
    assert s.probe["execution"] == 0
    assert s.ctx.world.upstream_writes == 0
    assert s.ctx.world.reassessment_writes == 0
    assert "NOT SAVED" in render_new_pair_continuation(plan)
    assert s.ctx.review.decision.student_id not in render_new_pair_continuation(plan)


def test_one_confirmed_new_31_only_write_yields_verified_pair(monkeypatch):
    s = _setup(monkeypatch)
    result = _prepare(s).apply(confirmed=True)
    assert result.status == "pair_current_verified"
    assert result.exact_pair_current and result.continue_to_standards_review
    assert s.probe["execution"] == 1
    assert s.ctx.world.upstream_writes == 0


def test_cancel_creates_no_receipt_or_academic_write(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    before = tuple(s.probe["receipts"])
    assert plan.apply(confirmed=False).status == "canceled_before_write"
    assert tuple(s.probe["receipts"]) == before
    assert s.probe["execution"] == 0
    assert plan.apply(confirmed=True).status == "recovery_required"


def test_one_use_new_action_never_replays(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    assert plan.apply(confirmed=True).status == "pair_current_verified"
    assert plan.apply(confirmed=True).status == "recovery_required"
    assert s.probe["execution"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "upstream_missing",
        "policy_changed",
        "source_withdrawn",
        "31_existing",
        "31_pair_current",
        "inspector_failure",
        "wrong_actor",
    ],
)
def test_preparation_denies_changed_canonical_basis(monkeypatch, mutation):
    s = _setup(monkeypatch)
    if mutation == "upstream_missing":
        s.ctx.world.upstream_current = False
    elif mutation == "policy_changed":
        s.ctx.world.policy_current = False
    elif mutation == "source_withdrawn":
        from dataclasses import replace as dc_replace

        from meridian.attempt_resolution_coordinator import MultiAttemptPorts

        original = s.canonical_ports
        broken = dc_replace(
            original,
            inventory_loader=lambda *args, **kw: dc_replace(
                _build(_case()), source_status="withdrawn"
            ),
        )
        assert isinstance(broken, MultiAttemptPorts)
        s.canonical_ports = broken
    elif mutation == "31_existing":
        s.ctx.world.history = (s.ctx.review.decision.decision_revision,)
    elif mutation == "31_pair_current":
        s.ctx.world.history = (s.ctx.review.decision.decision_revision,)
        s.ctx.world.reassessment_current = True
    elif mutation == "inspector_failure":
        s.probe["inspector_error"] = True
    elif mutation == "wrong_actor":
        s.ctx.actor = replace(s.ctx.actor, actor_id="other_teacher")
    with pytest.raises(AttemptPairNewContinuationError):
        _prepare(s)
    assert s.probe["execution"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "upstream_receipt_absent",
        "upstream_receipt_prepared",
        "no_write_record",
        "wrong_receipt_actor",
        "same_student_other_31",
        "same_student_same_31",
        "bad_receipt_inventory",
        "journal_read_error",
    ],
)
def test_preparation_denies_unsafe_or_competing_receipts(monkeypatch, mutation):
    s = _setup(monkeypatch)
    if mutation == "upstream_receipt_absent":
        s.probe["receipts"] = []
    elif mutation == "upstream_receipt_prepared":
        s.probe["receipts"] = [
            _receipt(_preview(s.ctx, "attempt_decision"), written=False)
        ]
    elif mutation == "no_write_record":
        s.probe["receipts"] = [
            _receipt(_preview(s.ctx, "attempt_decision"), include_record=False)
        ]
    elif mutation == "wrong_receipt_actor":
        original = s.probe["receipts"][0]
        preview = replace(
            original.preview,
            actor=replace(original.preview.actor, actor_id="other_teacher"),
        )
        s.probe["receipts"] = [_receipt(preview)]
    elif mutation in ("same_student_other_31", "same_student_same_31"):
        digest = "f" * 64 if mutation == "same_student_other_31" else None
        s.probe["receipts"].append(
            _receipt(_preview(s.ctx, "reassessment_decision", digest=digest))
        )
    elif mutation == "bad_receipt_inventory":
        original = s.ports
        s.ports = replace(original, receipt_reader=lambda *args: ("not a receipt",))
    elif mutation == "journal_read_error":
        original = s.ports

        def fail(*args):
            raise OSError("unsafe directory")

        s.ports = replace(original, receipt_reader=fail)
    with pytest.raises(AttemptPairNewContinuationError):
        _prepare(s)
    assert s.probe["execution"] == 0


def test_unrelated_student_reassessment_receipt_is_not_scope_collision(monkeypatch):
    s = _setup(monkeypatch)
    different = _preview(s.ctx, "reassessment_decision", digest="f" * 64)
    wrong = replace(
        different,
        target=replace(different.target, identity_sha256="e" * 64),
    )
    s.probe["receipts"].append(_receipt(wrong))
    assert _prepare(s).action is s.action


def test_precommit_upstream_drift_stops_before_first_31_write(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    s.ctx.world.upstream_current = False
    assert plan.apply(confirmed=True).status == "conflict_requires_review"
    assert s.probe["execution"] == 0


def test_precommit_new_receipt_stops_before_first_write(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    s.probe["receipts"].append(
        _receipt(_preview(s.ctx, "reassessment_decision", digest="f" * 64))
    )
    assert plan.apply(confirmed=True).status == "conflict_requires_review"
    assert s.probe["execution"] == 0


def test_forged_new_action_digest_stops_preparation(monkeypatch):
    s = _setup(monkeypatch)

    def mutate(action):
        action.preview = replace(
            action.preview,
            reviewed_decision_sha256="f" * 64,
        )
        return action

    s.probe["action_mutator"] = mutate
    with pytest.raises(AttemptPairNewContinuationError):
        _prepare(s)


def test_new_action_author_and_scope_rechecked_at_execution(monkeypatch):
    s = _setup(monkeypatch)
    plan = _prepare(s)
    s.action.preview = replace(
        s.action.preview,
        target=replace(
            s.action.preview.target,
            expected_current_revision=9,
            expected_current_sha256="f" * 64,
        ),
    )
    assert plan.apply(confirmed=True).status == "conflict_requires_review"
    assert s.probe["execution"] == 0


def test_exception_after_31_started_is_uncertain_not_no_write(monkeypatch):
    s = _setup(monkeypatch)
    s.probe["exception"] = True
    plan = _prepare(s)
    assert plan.apply(confirmed=True).status == "recovery_required"
    assert plan.apply(confirmed=True).status == "recovery_required"
    assert s.probe["execution"] == 1


@pytest.mark.parametrize(
    "status, expected",
    [
        ("written_not_current", "written_not_current"),
        ("conflict_requires_review", "conflict_requires_review"),
        ("blocked_before_write", "blocked_before_write"),
        ("recovery_required", "recovery_required"),
    ],
)
def test_nonapplied_31_cannot_be_reported_current(monkeypatch, status, expected):
    s = _setup(monkeypatch)
    s.probe["result_status"] = status
    outcome = _prepare(s).apply(confirmed=True)
    assert outcome.status == expected
    assert not outcome.exact_pair_current
    assert not outcome.continue_to_standards_review


@pytest.mark.parametrize(
    "failure",
    [
        "observer_fail",
        "observer_disagrees",
        "postread_fail",
        "result_not_verified",
    ],
)
def test_independent_postwrite_checks_fail_closed(monkeypatch, failure):
    s = _setup(monkeypatch)
    if failure == "observer_fail":
        s.probe["observer_error"] = True
    elif failure == "observer_disagrees":
        s.probe["observer_exact"] = False
    elif failure == "postread_fail":
        original_inspector = s.ports.inspector

        def fail_post(*args, **kwargs):
            if s.ctx.world.reassessment_current:
                raise OSError("Postwrite canonical unavailable")
            return original_inspector(*args, **kwargs)

        s.ports = replace(s.ports, inspector=fail_post)
    elif failure == "result_not_verified":
        s.probe["valid_record"] = False
    outcome = _prepare(s).apply(confirmed=True)
    assert outcome.status == "current_unverified"
    assert not outcome.continue_to_standards_review


def test_renderer_rejects_untyped_value():
    with pytest.raises(TypeError):
        render_new_pair_continuation(object())
