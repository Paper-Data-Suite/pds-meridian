"""#126 E1: read-only reboot reconciliation; all students and IDs synthetic."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_issue126_sliced2b2_multi_attempt_coordinator import _rig

from meridian.attempt_pair_recovery import (
    AttemptPairRecoveryError,
    PairRecoveryPorts,
    inspect_durable_pair_recovery,
    render_durable_pair_recovery,
)
from meridian.attempt_resolution_coordinator import assess_multi_attempt_recovery
from meridian.teacher_action_guided import _identity


def _receipt(context, family, *, phase="in_progress", **changes):
    first = context.authoring.candidate
    review = context.review
    second = review.decision
    target = first if family == "attempt_decision" else second
    digest = (
        review.upstream_decision_sha256
        if family == "attempt_decision"
        else review.reassessment_decision_sha256
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
    identity = _identity(
        family,
        first.class_id,
        first.grade_item_id,
        first.work.module_id,
        first.work.work_id,
        first.student_id,
    )
    expected = (
        context.authoring.reviewed_current_decision_revision
        if family == "attempt_decision"
        else review.expected_current_reassessment[0]
    )
    actor = NS(actor_id=first.actor.actor_id, profile_sha256="c" * 64)
    scope = NS(
        class_id=first.class_id,
        grade_item_id=first.grade_item_id,
        workspace_sha256=_identity("workspace", str(context.root)),
        work_identity_sha256=_identity(
            "work",
            first.class_id,
            first.work.module_id,
            first.work.work_id,
        ),
    )
    preview = NS(
        kind=family,
        actor=actor,
        scope=scope,
        target=NS(
            candidate_sha256=digest,
            identity_sha256=identity,
            revision=target.decision_revision,
            expected_current_revision=expected,
            expected_current_sha256=(
                review.expected_current_reassessment[1]
                if family == "reassessment_decision"
                else None
            ),
        ),
        basis=(
            NS(
                role="actor_profile",
                identity_sha256=_identity(first.actor.actor_id),
                content_sha256=actor.profile_sha256,
            ),
            NS(
                role="canonical_source",
                identity_sha256=identity,
                content_sha256=source_binding,
            ),
        ),
    )
    for key, val in changes.items():
        if key.startswith("scope_"):
            setattr(scope, key[6:], val)
        elif key.startswith("target_"):
            setattr(preview.target, key[7:], val)
        elif key.startswith("actor_"):
            setattr(actor, key[6:], val)
        elif key == "source_binding":
            preview.basis[1].content_sha256 = val
        else:
            raise ValueError("Unknown synthetic receipt variation")
    return NS(
        preview=preview,
        action_id="a" * 32 if family == "attempt_decision" else "b" * 32,
        phase=phase,
        checkpoints=(NS(stage="receipt_prepared"), NS(stage="write")),
    )


def _assess(context, receipts=(), *, fail_read=False):
    def read(_root, class_id):
        assert class_id == context.authoring.candidate.class_id
        if fail_read:
            raise OSError("Journal unreadable")
        return tuple(receipts)

    return inspect_durable_pair_recovery(
        context.root,
        prepared=context.prepared,
        authoring=context.authoring,
        review=context.review,
        canonical_ports=context.ports,
        ports=PairRecoveryPorts(
            canonical_inspector=assess_multi_attempt_recovery,
            receipt_reader=read,
        ),
    )


def test_empty_journal_cannot_prove_no_write(monkeypatch):
    c = _rig(monkeypatch)
    result = _assess(c)
    assert result.status == "upstream_not_current"
    assert result.upstream_receipt.status == "missing"
    assert result.reassessment_receipt.status == "missing"
    assert not result.can_resume_automatically
    assert not result.may_continue_to_standards


def test_upstream_current_no_31_is_incomplete_after_restart(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    result = _assess(c, (_receipt(c, "attempt_decision"),))
    assert result.status == "upstream_current_reassessment_missing"
    assert result.exact_upstream_current
    assert not result.exact_reassessment_current
    assert result.upstream_receipt.status == "in_progress"
    assert result.reassessment_receipt.status == "missing"
    assert not result.may_continue_to_standards


def test_31_written_without_selection_is_not_pair_current(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.history = (1,)
    result = _assess(
        c,
        (
            _receipt(c, "attempt_decision"),
            _receipt(c, "reassessment_decision"),
        ),
    )
    assert result.status == "reassessment_written_not_current"
    assert not result.may_continue_to_standards


def test_verified_both_current_with_valid_receipts(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.reassessment_current = True
    c.world.history = (1,)
    result = _assess(
        c,
        (
            _receipt(c, "attempt_decision", phase="prepared"),
            _receipt(c, "reassessment_decision"),
        ),
    )
    assert result.status == "pair_current_verified"
    assert result.upstream_receipt.status == "prepared"
    assert result.reassessment_receipt.status == "in_progress"
    assert result.may_continue_to_standards
    assert not result.can_resume_automatically


def test_pair_current_without_receipts_is_canonical_not_journal_truth(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.reassessment_current = True
    c.world.history = (1,)
    result = _assess(c)
    assert result.status == "pair_current_verified"
    assert result.may_continue_to_standards
    assert result.upstream_receipt.status == "missing"


def test_ambiguous_double_receipt_requires_review(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    r = _receipt(c, "attempt_decision")
    result = _assess(c, (r, r))
    assert result.status == "journal_ambiguous"
    assert not result.may_continue_to_standards


@pytest.mark.parametrize(
    "variation",
    [
        {"scope_workspace_sha256": "f" * 64},
        {"target_identity_sha256": "e" * 64},
        {"source_binding": "d" * 64},
        {"actor_actor_id": "other_teacher"},
        {"target_expected_current_revision": 99},
    ],
)
def test_wrong_receipt_binding_not_trusted(monkeypatch, variation):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    result = _assess(c, (_receipt(c, "attempt_decision", **variation),))
    assert result.status == "journal_unverifiable"
    assert result.upstream_receipt.status == "unverifiable"
    assert not result.can_resume_automatically


def test_broken_journal_enumeration_fails_closed(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    result = _assess(c, fail_read=True)
    assert result.status == "journal_unverifiable"
    assert result.reason == "journal_read_failed"


def test_missing_canonical_read_cannot_be_replaced_by_receipt(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reader_failure = True
    result = _assess(c, (_receipt(c, "attempt_decision"),))
    assert result.status == "canonical_unverifiable"
    assert not result.exact_upstream_current


def test_policy_drift_prevents_false_pair_success(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.policy_current = False
    result = _assess(c, (_receipt(c, "attempt_decision"),))
    assert result.status == "conflict_requires_review"


def test_unrelated_receipts_are_ignored(monkeypatch):
    c = _rig(monkeypatch)
    r = _receipt(c, "attempt_decision")
    r.preview.target.candidate_sha256 = "0" * 64
    result = _assess(c, (r,))
    assert result.upstream_receipt.status == "missing"


def test_different_31_baseline_causes_journal_rejection(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    r = _receipt(c, "reassessment_decision", target_expected_current_sha256="0" * 64)
    result = _assess(c, (r,))
    assert result.status == "journal_unverifiable"
    assert result.reassessment_receipt.status == "unverifiable"


def test_reviewed_hash_drift_cannot_use_journal(monkeypatch):
    c = _rig(monkeypatch)
    forged = replace(c.review, upstream_decision_sha256="0" * 64)
    with pytest.raises(AttemptPairRecoveryError):
        inspect_durable_pair_recovery(
            c.root,
            prepared=c.prepared,
            authoring=c.authoring,
            review=forged,
        )


def test_invalid_root_rejected_before_inspection(monkeypatch):
    c = _rig(monkeypatch)
    with pytest.raises(AttemptPairRecoveryError):
        inspect_durable_pair_recovery(
            Path("relative"),
            prepared=c.prepared,
            authoring=c.authoring,
            review=c.review,
        )


def test_renderer_does_not_print_private_subject_or_action_id(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    result = _assess(c, (_receipt(c, "attempt_decision"),))
    text = render_durable_pair_recovery(result)
    assert "READ ONLY" in text
    assert "synthetic_student_02" not in text
    assert "aaaaaaaa" not in text
    assert "Automatic replay: unavailable" in text
    assert c.world.upstream_writes == 0
    assert c.world.reassessment_writes == 0


def test_durable_recovery_is_repeatable_and_non_mutating(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    receipts = (_receipt(c, "attempt_decision"),)
    first = _assess(c, receipts)
    second = _assess(c, receipts)
    assert first == second
    assert c.world.upstream_writes == c.world.reassessment_writes == 0
