"""#126 E3B: production #31/#122 adapter over actual native #30/#31 files.

All student identities and the publication/roster/actor inputs are synthetic.
The production adapter, immutable stores, CAS selectors and receipt store are real.
The unavailable live producer/roster/identity providers are explicit test seams.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_attempt_selection_storage import (
    CLASS_ID,
    GRADE_ITEM_ID,
    MEMBERSHIP_DIGEST,
    WORK,
)
from test_issue126_slicee3a_native_interruption_matrix import _world
from test_reassessment_storage import policy as reassessment_policy

import meridian.attempt_selection_storage as storage30
import meridian.reassessment_storage as storage31
import meridian.teacher_action_reassessment as domain
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_receipts import (
    TeacherActionReceiptError,
    assess_teacher_action_recovery,
)


@dataclass
class Rig:
    world: object
    prepared: object
    review: ProspectiveReassessmentReview
    actor: TeacherActionActor
    gates: dict[str, object]

    def prepare(self):
        return domain.prepare_reviewed_reassessment_action(
            self.world.root,
            prepared=self.prepared,
            review=self.review,
            actor=self.actor,
        )

    def history(self):
        return self.world.thirty_one_history()


def _rig(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, selected30=True):
    world = _world(monkeypatch, tmp_path, selected30=selected30)
    first, second = world.first, world.second
    actor = world.preview.actor
    publication = NS(work=WORK, publication_id=first.source_snapshot.publication_id)
    prepared = NS(
        authorized=NS(
            assessment=NS(reusable_for_current_use=True),
            current_context=NS(publication=publication),
            stored=NS(snapshot=NS(source=NS(publication=publication))),
        )
    )
    review = ProspectiveReassessmentReview(
        decision=second,
        upstream_decision_sha256=second.attempt_selection.decision_sha256,
        reassessment_decision_sha256=world.preview.target.candidate_sha256,
        policy_sha256=second.policy.policy_revision_sha256,
        expected_current_reassessment=(None, None),
        history_before=(),
        student_label="Synthetic Student",
        teacher_treatment="teacher_reviewed_reassessment",
    )
    gates: dict[str, object] = {
        "actor": True,
        "membership": True,
        "membership_digest": MEMBERSHIP_DIGEST,
        "membership_valid": True,
        "calendar": "f" * 64,
    }

    def actor_now(_actor):
        if not gates["actor"]:
            raise RuntimeError("Synthetic profile fingerprint changed")

    def membership(*_args):
        if not gates["membership"]:
            return None
        period = NS(school_year="2026-2027", period_id="mp1")
        assignment = NS(period=period, calendar_revision=1)
        return NS(
            decision=NS(
                decision="included",
                membership_revision=first.membership_revision,
                academic_period=assignment,
            ),
            decision_sha256=gates["membership_digest"],
        )

    def membership_dependencies(*_args):
        if not gates["membership_valid"]:
            raise RuntimeError("Synthetic membership authority changed")

    monkeypatch.setattr(domain, "GuidedProjectionResult", NS)
    monkeypatch.setattr(domain, "_actor_now", actor_now)
    monkeypatch.setattr(
        domain, "load_current_grade_item_membership_decision", membership
    )
    monkeypatch.setattr(
        domain, "validate_grade_item_membership_dependencies", membership_dependencies
    )
    monkeypatch.setattr(domain, "_calendar_digest", lambda *_args: gates["calendar"])
    # The source-side E3A test fixture already supplies synthetic Core #29 and
    # roster facts. The #31 writer/selector and #122 journal remain unmocked.
    return Rig(world, prepared, review, actor, gates)


def _apply(rig):
    action = rig.prepare()
    return action, action.apply(confirmed=True)


def test_production_adapter_full_write_select_observe_and_receipt(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action, result = _apply(rig)
    assert action.preview.kind == "reassessment_decision"
    assert result.status == "applied"
    observation = domain.observe_reviewed_reassessment_action(
        rig.world.root, prepared=rig.prepared, review=rig.review, result=result
    )
    assert observation.exact_current
    assert observation.status == "applied_current"
    assert (
        rig.world.current31().decision_sha256 == rig.review.reassessment_decision_sha256
    )
    assert rig.world.resolution().operative_reassessment
    assert rig.history() == (1,)
    receipt = action.store.load(action.preview.action_id)
    assert receipt is not None and receipt.preview == action.preview
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
    assert storage30.list_attempt_selection_decision_revisions(
        rig.world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    ) == (1,)


def test_production_adapter_cancel_creates_no_action_receipt(monkeypatch, tmp_path):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    result = action.apply(confirmed=False)
    assert result.status == "blocked_before_write"
    assert action.store.load(action.preview.action_id) is None
    assert rig.history() == ()
    assert rig.world.current31() is None


def test_real_upstream_30_missing_blocks_before_preparation(monkeypatch, tmp_path):
    rig = _rig(monkeypatch, tmp_path, selected30=False)
    with pytest.raises(domain.ReassessmentActionError):
        rig.prepare()
    assert rig.history() == ()


def test_wrong_review_digest_blocks_before_preparation(monkeypatch, tmp_path):
    rig = _rig(monkeypatch, tmp_path)
    rig.review = replace(rig.review, reassessment_decision_sha256="0" * 64)
    with pytest.raises(domain.ReassessmentActionError):
        rig.prepare()
    assert rig.history() == ()


def test_foreign_actor_blocks_before_preparation(monkeypatch, tmp_path):
    rig = _rig(monkeypatch, tmp_path)
    rig.actor = TeacherActionActor("foreign_teacher", rig.actor.profile_sha256, "saved")
    with pytest.raises(domain.ReassessmentActionError):
        rig.prepare()
    assert rig.history() == ()


@pytest.mark.parametrize(
    "gate",
    ["actor", "membership", "membership_digest", "membership_valid", "calendar"],
)
def test_changed_teacher_membership_or_period_blocks_before_write(
    monkeypatch, tmp_path, gate
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    rig.gates[gate] = (
        "0" * 64 if gate.endswith("digest") or gate == "calendar" else False
    )
    result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == ()
    assert rig.world.current31() is None


def test_real_31_policy_revision_drift_blocks_before_write(monkeypatch, tmp_path):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    storage31.write_reassessment_policy_revision(
        rig.world.root, reassessment_policy(revision=2)
    )
    storage31.select_reassessment_policy_revision(
        rig.world.root,
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        "teacher_reassessment",
        2,
        expected_current_policy_revision=1,
    )
    result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == ()


def test_real_30_pointer_removed_after_review_blocks_before_write(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    pointer = storage30.attempt_selection_decision_current_path(
        rig.world.root, CLASS_ID, GRADE_ITEM_ID, WORK, "student_1"
    )
    pointer.unlink()
    result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == ()


def test_real_31_writer_interrupted_after_immutable_write_never_claims_success(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    original = domain.write_reassessment_decision_revision

    def interruption(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Simulated interruption after immutable #31 revision")

    with monkeypatch.context() as m:
        m.setattr(domain, "write_reassessment_decision_revision", interruption)
        result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == (1,)
    assert rig.world.current31() is None
    witness = assess_teacher_action_recovery(
        action.store, action.preview, action.port.observe
    )
    assert witness.reason in {"eligible_to_resume", "receipt_canonical_divergence"}


def test_production_adapter_original_action_restart_after_pointer_failure(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()

    with monkeypatch.context() as m:
        m.setattr(
            domain,
            "select_reassessment_decision_revision",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("CAS interrupted")),
        )
        interrupted = action.apply(confirmed=True)
    assert interrupted.status not in {"applied", "already_applied"}
    assert rig.history() == (1,)
    assert rig.world.current31() is None
    restarted = action.resume(confirmed=True)
    assert restarted.status in {"applied", "already_applied"}
    assert rig.world.current31() is not None
    assert rig.history() == (1,)


def test_production_adapter_after_cas_exception_requires_canonical_reconciliation(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    original = domain.select_reassessment_decision_revision

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Injected interruption after CAS")

    with monkeypatch.context() as m:
        m.setattr(domain, "select_reassessment_decision_revision", interrupted)
        result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == (1,)
    assert rig.world.current31() is not None
    witness = assess_teacher_action_recovery(
        action.store, action.preview, action.port.observe
    )
    assert witness.reason == "exact_current"
    again = action.resume(confirmed=True)
    assert again.status == "already_applied"
    assert rig.history() == (1,)


def test_production_adapter_receipt_checkpoint_failure_preserves_written_target(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    original = action.store.record_checkpoint

    def fail_write_checkpoint(*args, **kwargs):
        if kwargs["checkpoint"].stage == "write":
            raise TeacherActionReceiptError("Injected receipt write failure")
        return original(*args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(action.store, "record_checkpoint", fail_write_checkpoint)
        result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    assert rig.history() == (1,)
    assert rig.world.current31() is None
    assert action.store.load(action.preview.action_id) is not None


def test_production_adapter_repeated_apply_is_reconciled_without_duplicate_write(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action, result = _apply(rig)
    assert result.status == "applied"
    repeat = action.apply(confirmed=True)
    assert repeat.status == "already_applied"
    assert rig.history() == (1,)
    assert rig.world.current31() is not None


def test_external_source_withdrawal_blocks_original_action_restart(
    monkeypatch, tmp_path
):
    rig = _rig(monkeypatch, tmp_path)
    action = rig.prepare()
    with monkeypatch.context() as m:
        m.setattr(
            domain,
            "select_reassessment_decision_revision",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("CAS interrupted")),
        )
        result = action.apply(confirmed=True)
    assert result.status not in {"applied", "already_applied"}
    rig.prepared.authorized.assessment.reusable_for_current_use = False
    restarted = action.resume(confirmed=True)
    assert restarted.status not in {"applied", "already_applied"}
    assert rig.history() == (1,)
    assert rig.world.current31() is None
