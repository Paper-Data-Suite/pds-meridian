"""#126-D2B1: #31 only becomes operative after exact current #30 authority."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from test_issue126_sliced2a_reassessment_review import _review, _scenario

from meridian.attempt_reassessment_review import ReviewedReassessmentChoice
from meridian.teacher_action_contract import TeacherActionRecord
from meridian.teacher_action_reassessment import (
    ReassessmentActionError,
    observe_reviewed_reassessment_action,
    prepare_reviewed_reassessment_action,
)


def _rig(monkeypatch, tmp_path, *, mode="retain"):
    import meridian.teacher_action_reassessment as domain

    interpretation, authoring, policy, actor, a, b = _scenario()
    if mode == "replace":
        from meridian.reassessment import ReplacementRelationship

        choice = ReviewedReassessmentChoice(
            "replace", replacements=(ReplacementRelationship(b, (a,)),)
        )
    else:
        choice = ReviewedReassessmentChoice("retain")
    review = _review(choice, setup=(interpretation, authoring, policy, actor, a, b))
    work = authoring.candidate.work
    publication = NS(
        work=work, publication_id=interpretation.source_snapshot.publication_id
    )
    prepared = NS(
        authorized=NS(
            assessment=NS(reusable_for_current_use=True),
            current_context=NS(publication=publication),
            stored=NS(snapshot=NS(source=NS(publication=publication))),
        )
    )
    selection = NS(
        status="selected",
        operative_selection=True,
        selected=NS(
            decision=authoring.candidate,
            decision_sha256=review.upstream_decision_sha256,
        ),
    )
    period = NS(school_year="2026-2027", period_id="mp1")
    membership = NS(
        decision=NS(
            decision="included",
            membership_revision=authoring.candidate.membership_revision,
            academic_period=NS(period=period, calendar_revision=1),
        ),
        decision_sha256=authoring.candidate.membership_revision_sha256,
    )
    world = NS(
        selection=selection,
        policy=policy,
        membership=membership,
        history=[],
        target_digest=None,
        current_rev=None,
        current_digest=None,
        writes=0,
        selects=0,
        resolved=None,
    )
    monkeypatch.setattr(domain, "GuidedProjectionResult", NS)
    monkeypatch.setattr(domain, "_actor_now", lambda actor: None)
    monkeypatch.setattr(domain, "_calendar_digest", lambda *args: "9" * 64)
    monkeypatch.setattr(
        domain, "validate_grade_item_membership_dependencies", lambda *args: None
    )
    monkeypatch.setattr(
        domain,
        "load_current_grade_item_membership_decision",
        lambda *args: world.membership,
    )
    monkeypatch.setattr(
        domain,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: world.selection,
    )
    monkeypatch.setattr(
        domain, "load_current_reassessment_policy", lambda *args: world.policy
    )
    monkeypatch.setattr(
        domain,
        "list_reassessment_decision_revisions",
        lambda *args: tuple(world.history),
    )

    def load_target(*args):
        assert world.target_digest is not None
        return NS(decision_sha256=world.target_digest)

    def load_current(*args):
        return (
            None
            if world.current_rev is None
            else NS(
                decision=NS(decision_revision=world.current_rev),
                decision_sha256=world.current_digest,
            )
        )

    def write(*args, **kwargs):
        world.writes += 1
        world.history.append(review.decision.decision_revision)
        world.target_digest = review.reassessment_decision_sha256
        return NS(
            disposition="created",
            stored=NS(decision_sha256=world.target_digest),
        )

    def select(*args, **kwargs):
        world.selects += 1
        assert kwargs["expected_current_decision_revision"] is None
        world.current_rev = review.decision.decision_revision
        world.current_digest = review.reassessment_decision_sha256
        return NS(
            disposition="created",
            stored=NS(decision_sha256=world.current_digest),
        )

    monkeypatch.setattr(domain, "load_reassessment_decision_revision", load_target)
    monkeypatch.setattr(domain, "load_current_reassessment_decision", load_current)
    monkeypatch.setattr(domain, "write_reassessment_decision_revision", write)
    monkeypatch.setattr(domain, "select_reassessment_decision_revision", select)
    monkeypatch.setattr(
        domain, "resolve_current_reassessment", lambda *a, **k: world.resolved
    )
    return domain, world, prepared, review, actor


def _prepare(monkeypatch, tmp_path, **kwargs):
    _, world, prepared, review, actor = _rig(monkeypatch, tmp_path, **kwargs)
    action = prepare_reviewed_reassessment_action(
        tmp_path, prepared=prepared, review=review, actor=actor
    )
    return world, prepared, review, action


def test_action_family_registered_in_canonical_122_kernel():
    from meridian.teacher_action_contract import _KINDS
    from meridian.teacher_action_orchestration import _SUPPORTED

    assert "reassessment_decision" in _KINDS
    assert "reassessment_decision" in _SUPPORTED


def test_prepare_is_read_only_and_exact(monkeypatch, tmp_path):
    world, prepared, review, action = _prepare(monkeypatch, tmp_path)
    assert action.preview.kind == "reassessment_decision"
    assert action.preview.target.candidate_sha256 == review.reassessment_decision_sha256
    assert action.preview.target.expected_current_revision is None
    assert world.writes == world.selects == 0
    assert prepared.authorized is not None


def test_adapter_writes_exact_revision_then_cas_selects(monkeypatch, tmp_path):
    world, _, review, action = _prepare(monkeypatch, tmp_path)
    action.port.revalidate_basis(action.preview)
    observed = action.port.observe(action.preview)
    assert observed.target_sha256 is None
    assert observed.current_revision is None
    record = action.port.persist_exact(action.preview)
    assert record.sha256 == review.reassessment_decision_sha256
    assert record.write_disposition == "created"
    selected = action.port.select_exact(action.preview, record)
    assert selected == "created"
    current = action.port.observe(action.preview)
    assert current.current_sha256 == review.reassessment_decision_sha256
    assert world.writes == world.selects == 1


def test_before_upstream_current_no_31_action(monkeypatch, tmp_path):
    _, world, prepared, review, actor = _rig(monkeypatch, tmp_path)
    world.selection = NS(status="no_decision", operative_selection=False, selected=None)
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )
    assert world.writes == 0


def test_upstream_digest_drift_rejected(monkeypatch, tmp_path):
    _, world, prepared, review, actor = _rig(monkeypatch, tmp_path)
    world.selection.selected.decision_sha256 = "f" * 64
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )


def test_policy_drift_rejected_before_action(monkeypatch, tmp_path):
    _, world, prepared, review, actor = _rig(monkeypatch, tmp_path)
    world.policy = NS(policy_sha256="0" * 64)
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )


def test_membership_drift_rejected_before_action(monkeypatch, tmp_path):
    _, world, prepared, review, actor = _rig(monkeypatch, tmp_path)
    world.membership.decision_sha256 = "0" * 64
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )


def test_exact_source_drift_rejected(monkeypatch, tmp_path):
    _, _, prepared, review, actor = _rig(monkeypatch, tmp_path)
    prepared.authorized.current_context.publication = NS(
        work=review.decision.work, publication_id="pub_" + "0" * 32
    )
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )


def test_withdrawn_projection_blocks_reassessment(monkeypatch, tmp_path):
    _, _, prepared, review, actor = _rig(monkeypatch, tmp_path)
    prepared.authorized.assessment.reusable_for_current_use = False
    with pytest.raises(ReassessmentActionError):
        prepare_reviewed_reassessment_action(
            tmp_path, prepared=prepared, review=review, actor=actor
        )


def test_current_cas_conflict_detected_after_preparation(monkeypatch, tmp_path):
    world, _, _, action = _prepare(monkeypatch, tmp_path)
    world.current_rev = 90
    world.current_digest = "9" * 64
    with pytest.raises(Exception):
        action.port.revalidate_basis(action.preview)
    assert world.writes == world.selects == 0


def test_immutable_target_collision_detected(monkeypatch, tmp_path):
    world, _, review, action = _prepare(monkeypatch, tmp_path)
    world.history.append(review.decision.decision_revision)
    world.target_digest = "f" * 64
    with pytest.raises(Exception):
        action.port.revalidate_basis(action.preview)
    assert world.writes == 0


def test_independent_reassessment_readback_required(monkeypatch, tmp_path):
    world, prepared, review, action = _prepare(monkeypatch, tmp_path)
    record = TeacherActionRecord(
        "reassessment_decision",
        action.preview.target.identity_sha256,
        review.decision.decision_revision,
        review.reassessment_decision_sha256,
        "created",
    )
    from meridian.teacher_action_contract import TeacherActionResult

    result = TeacherActionResult(
        action_id=action.preview.action_id,
        intent_sha256=action.preview.intent_sha256,
        target=action.preview.target,
        status="applied",
        persisted=(record,),
        current_state="matches",
        current_record=record,
        selection_disposition="created",
    )
    first = observe_reviewed_reassessment_action(
        tmp_path, prepared=prepared, review=review, result=result
    )
    assert first.status == "current_unverified"
    assert not first.exact_current
    world.resolved = NS(
        status="resolved",
        operative_reassessment=True,
        selected=NS(
            decision=review.decision,
            decision_sha256=review.reassessment_decision_sha256,
        ),
        contributing_attempts=review.decision.contributing_attempts,
        replacement_relationships=review.decision.replacement_relationships,
        combinations=review.decision.combinations,
        recency_order=review.decision.recency_order,
    )
    second = observe_reviewed_reassessment_action(
        tmp_path, prepared=prepared, review=review, result=result
    )
    assert second.status == "applied_current" and second.exact_current


def test_incomplete_write_never_claimed_current(monkeypatch, tmp_path):
    _, prepared, review, action = _prepare(monkeypatch, tmp_path)
    from meridian.teacher_action_contract import TeacherActionResult

    result = TeacherActionResult(
        action_id=action.preview.action_id,
        intent_sha256=action.preview.intent_sha256,
        target=action.preview.target,
        status="recovery_required",
        persisted=(),
        current_state="not_checked",
        current_record=None,
        selection_disposition="not_attempted",
        reason_code="write_failed",
    )
    observed = observe_reviewed_reassessment_action(
        tmp_path, prepared=prepared, review=review, result=result
    )
    assert observed.status == "recovery_required"
    assert not observed.exact_current


def test_canceled_action_never_calls_reassessment_writer(monkeypatch, tmp_path):
    world, _, _, action = _prepare(monkeypatch, tmp_path)
    outcome = action.apply(confirmed=False)
    assert outcome.status == "blocked_before_write"
    assert world.writes == world.selects == 0


def test_replacement_mode_also_uses_same_guarded_path(monkeypatch, tmp_path):
    _, _, review, action = _prepare(monkeypatch, tmp_path, mode="replace")
    assert review.decision.mode == "replace"
    assert action.preview.target.candidate_sha256 == review.reassessment_decision_sha256
