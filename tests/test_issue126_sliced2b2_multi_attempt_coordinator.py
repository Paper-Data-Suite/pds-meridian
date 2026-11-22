"""#126-D2B2: synthetic two-record coordination, uncertainty and recovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_issue126_sliced2a_reassessment_review import _review, _scenario

import meridian.attempt_resolution_coordinator as domain
from meridian.attempt_reassessment_review import ReviewedReassessmentChoice
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
)


class FakeAction:
    def __init__(self, preview, world, kind):
        self.preview = preview
        self.world = world
        self.kind = kind
        self.calls = []

    def apply(self, *, confirmed):
        self.calls.append(("apply", confirmed))
        if not confirmed:
            return NS(status="blocked_before_write")
        if self.kind == "upstream":
            self.world.upstream_writes += 1
            if self.world.upstream_exception:
                raise RuntimeError("uncertain #30 write")
            if self.world.upstream_status in ("applied", "already_applied"):
                self.world.upstream_current = True
            return NS(
                status=self.world.upstream_status,
                current_state=self.world.upstream_current_state,
                current_record=NS(matches_target=lambda target: True),
                reason_code=None
                if self.world.upstream_status == "applied"
                else "blocked",
            )
        self.world.reassessment_writes += 1
        if self.world.reassessment_exception:
            raise RuntimeError("#31 writer interrupted")
        self.world.history = (self.world.review.decision.decision_revision,)
        if self.world.reassessment_status in ("applied", "already_applied"):
            self.world.reassessment_current = True
        return NS(
            status=self.world.reassessment_status,
            reason_code=None
            if self.world.reassessment_status == "applied"
            else "interrupted",
        )

    def resume(self, *, confirmed):
        self.calls.append(("resume", confirmed))
        if not confirmed:
            raise RuntimeError("cannot resume without confirmation")
        self.world.reassessment_current = True
        return NS(status="applied", reason_code=None)


def _rig(monkeypatch, *, override_ports=None):
    interpretation, authoring, policy, actor, a, b = _scenario()
    review = _review(
        ReviewedReassessmentChoice("retain"),
        setup=(interpretation, authoring, policy, actor, a, b),
    )
    preset = GuidedAttemptPolicyPreset(
        "Use multiple", "Keep explicit attempts", "teacher_guided_one_or_more", 1, None
    )
    dependencies = GuidedAttemptDependencies(policies=(preset,))
    pub = NS(
        work=interpretation.source_snapshot.work,
        publication_id=interpretation.source_snapshot.publication_id,
    )
    prepared = NS(
        authorized=NS(
            current_context=NS(publication=pub),
            assessment=NS(reusable_for_current_use=True),
        )
    )
    monkeypatch.setattr(domain, "GuidedProjectionResult", NS)
    world = NS(
        review=review,
        upstream_current=False,
        reassessment_current=False,
        upstream_writes=0,
        reassessment_writes=0,
        upstream_exception=False,
        reassessment_exception=False,
        upstream_status="applied",
        upstream_current_state="matches",
        reassessment_status="applied",
        history=(),
        source_current=True,
        policy_current=True,
        reader_failure=False,
        reassessment_reader_failure=False,
        reassessment_preparation_failure=False,
        events=[],
    )
    digest = review.upstream_decision_sha256
    action30 = FakeAction(
        NS(
            kind="attempt_decision",
            actor=actor,
            scope=NS(
                class_id=interpretation.class_id,
                grade_item_id=interpretation.grade_item_id,
            ),
            target=NS(
                candidate_sha256=digest,
                revision=authoring.candidate.decision_revision,
                expected_current_revision=interpretation.selected_revision_at_preview,
            ),
        ),
        world,
        "upstream",
    )
    action31 = FakeAction(
        NS(
            kind="reassessment_decision",
            actor=actor,
            target=NS(
                candidate_sha256=review.reassessment_decision_sha256,
                revision=review.decision.decision_revision,
            ),
        ),
        world,
        "reassessment",
    )
    from test_issue126_sliceb_attempt_inventory import _build, _case

    inventory = _build(_case())

    def inventory_loader(*args, **kwargs):
        world.events.append("inventory")
        if not world.source_current:
            return replace(inventory, source_status="withdrawn")
        return inventory

    def policy_planner(*args, **kwargs):
        world.events.append("30_policy")
        return NS(action="ready", preset=preset)

    def policy_loader(*args):
        world.events.append("31_policy")
        return policy if world.policy_current else None

    def upstream_action_preparer(*args, **kwargs):
        world.events.append("30_prepare")
        return action30

    def upstream_loader(*args, **kwargs):
        world.events.append("30_read")
        if world.reader_failure:
            raise OSError("cannot inspect #30 current")
        return NS(
            status="selected" if world.upstream_current else "no_decision",
            operative_selection=world.upstream_current,
            resolution_status="selected" if world.upstream_current else "no_decision",
            source_snapshot=authoring.candidate.source_snapshot,
            selected_decision_revision=authoring.candidate.decision_revision,
            selected_decision_sha256=digest,
            reviewed_selected_attempts=authoring.candidate.selected_attempts,
        )

    def reassessment_action_preparer(*args, **kwargs):
        world.events.append("31_prepare")
        if world.reassessment_preparation_failure:
            raise ValueError("#31 CAS baseline drift")
        assert world.upstream_current, "#31 prepared before #30 current"
        return action31

    def reassessment_observer(*args, **kwargs):
        world.events.append("31_observe")
        if world.reassessment_reader_failure:
            raise OSError("#31 readback unavailable")
        return NS(
            status="applied_current"
            if world.reassessment_current
            else "current_unverified",
            exact_current=world.reassessment_current,
        )

    def reassessment_loader(*args, **kwargs):
        world.events.append("31_read")
        if world.reassessment_reader_failure:
            raise OSError("#31 source unreadable")
        return NS(
            status="resolved" if world.reassessment_current else "no_decision",
            operative_reassessment=world.reassessment_current,
            selected=NS(
                decision=review.decision,
                decision_sha256=review.reassessment_decision_sha256,
            )
            if world.reassessment_current
            else None,
            contributing_attempts=review.decision.contributing_attempts,
            replacement_relationships=review.decision.replacement_relationships,
            combinations=review.decision.combinations,
            recency_order=review.decision.recency_order,
        )

    ports = domain.MultiAttemptPorts(
        inventory_loader=inventory_loader,
        policy_planner=policy_planner,
        authoring_previewer=lambda *a, **k: authoring,
        upstream_action_preparer=upstream_action_preparer,
        upstream_loader=upstream_loader,
        reassessment_policy_loader=policy_loader,
        reassessment_history_loader=lambda *a: world.history,
        reassessment_current_loader=lambda *a: (
            NS(
                decision=NS(decision_revision=review.decision.decision_revision),
                decision_sha256=review.reassessment_decision_sha256,
            )
            if world.reassessment_current
            else None
        ),
        reassessment_target_loader=lambda *a: NS(
            decision=review.decision,
            decision_sha256=review.reassessment_decision_sha256,
        ),
        reassessment_action_preparer=reassessment_action_preparer,
        reassessment_observer=reassessment_observer,
        reassessment_loader=reassessment_loader,
    )
    if override_ports is not None:
        ports = override_ports(ports, world)
    context = NS(
        root=Path.cwd(),
        prepared=prepared,
        interpretation=interpretation,
        authoring=authoring,
        review=review,
        preset=preset,
        actor=actor,
        dependencies=dependencies,
        ports=ports,
        world=world,
        action30=action30,
        action31=action31,
    )
    return context


def _prepare(c):
    return domain.prepare_reviewed_multi_attempt_resolution(
        c.root,
        prepared=c.prepared,
        interpretation=c.interpretation,
        review=c.review,
        preset=c.preset,
        actor=c.actor,
        dependencies=c.dependencies,
        ports=c.ports,
    )


def _recover(c):
    return domain.assess_multi_attempt_recovery(
        c.root,
        prepared=c.prepared,
        authoring=c.authoring,
        review=c.review,
        ports=c.ports,
    )


def test_preparation_does_not_author_select_or_write(monkeypatch):
    c = _rig(monkeypatch)
    plan = _prepare(c)
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (0, 0)
    assert "31_prepare" not in c.world.events
    label = domain.render_reviewed_multi_attempt_resolution(plan)
    assert "NOT SAVED" in label and "NOT an atomic" in label
    assert "synthetic_student_02" not in label


def test_cancel_has_no_30_or_31_mutation(monkeypatch):
    c = _rig(monkeypatch)
    result = _prepare(c).apply(confirmed=False)
    assert result.status == "canceled_before_write"
    assert not result.continue_to_standards_review
    assert c.world.upstream_writes == c.world.reassessment_writes == 0
    assert c.action30.calls == [("apply", False)]
    assert not c.action31.calls


def test_confirmed_pair_requires_exact_two_independent_reads(monkeypatch):
    c = _rig(monkeypatch)
    result = _prepare(c).apply(confirmed=True)
    assert result.status == "applied_current"
    assert result.exact_pair_current and result.continue_to_standards_review
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (1, 1)
    assert c.world.events.index("30_read") < c.world.events.index("31_prepare")
    assert c.world.events[-2:] == ["30_read", "31_read"]


def test_upstream_failure_prevents_any_reassessment_write(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_status = "written_not_current"
    result = _prepare(c).apply(confirmed=True)
    assert result.status == "upstream_not_current"
    assert c.world.reassessment_writes == 0
    assert "31_prepare" not in c.world.events


def test_upstream_exception_is_unknown_and_never_replayed(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_exception = True
    plan = _prepare(c)
    result = plan.apply(confirmed=True)
    assert result.status == "recovery_required"
    assert plan.apply(confirmed=True).status == "recovery_required"
    assert c.world.upstream_writes == 1
    assert c.world.reassessment_writes == 0


def test_upstream_122_verified_target_is_not_sufficient_without_canonical_read(
    monkeypatch,
):
    c = _rig(monkeypatch)
    c.world.reader_failure = True
    result = _prepare(c).apply(confirmed=True)
    assert result.status == "current_unverified"
    assert c.world.reassessment_writes == 0


def test_31_preparation_failure_after_30_reports_partial_without_retry(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_preparation_failure = True
    plan = _prepare(c)
    result = plan.apply(confirmed=True)
    assert result.status == "upstream_current_reassessment_incomplete"
    assert not result.exact_pair_current
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (1, 0)
    assert plan.apply(confirmed=True).status == "recovery_required"
    assert c.world.upstream_writes == 1


def test_in_process_resume_after_30_never_reauthors_30(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_preparation_failure = True
    plan = _prepare(c)
    assert (
        plan.apply(confirmed=True).status == "upstream_current_reassessment_incomplete"
    )
    c.world.reassessment_preparation_failure = False
    resumed = plan.resume(confirmed=True)
    assert resumed.status == "applied_current"
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (1, 1)
    assert c.action30.calls == [("apply", True)]


def test_31_write_not_current_requires_exact_resume(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_status = "written_not_current"
    plan = _prepare(c)
    result = plan.apply(confirmed=True)
    assert result.status == "reassessment_written_not_current"
    assert c.world.reassessment_writes == 1
    outcome = plan.resume(confirmed=True)
    assert outcome.status == "applied_current"
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (1, 1)
    assert c.action31.calls == [("apply", True), ("resume", True)]


def test_31_exception_is_partial_not_rollback(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_exception = True
    result = _prepare(c).apply(confirmed=True)
    assert result.status == "upstream_current_reassessment_incomplete"
    assert c.world.upstream_current
    assert c.world.reassessment_writes == 1
    assert not result.continue_to_standards_review


def test_31_readback_fails_after_both_writers_not_success(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_reader_failure = True
    result = _prepare(c).apply(confirmed=True)
    assert result.status == "current_unverified"
    assert not result.exact_pair_current
    assert (c.world.upstream_writes, c.world.reassessment_writes) == (1, 1)


def test_source_withdrawal_before_confirm_blocks_all_writes(monkeypatch):
    c = _rig(monkeypatch)
    plan = _prepare(c)
    c.world.source_current = False
    result = plan.apply(confirmed=True)
    assert result.status == "conflict_requires_review"
    assert c.world.upstream_writes == c.world.reassessment_writes == 0


def test_policy_change_before_confirm_blocks_all_writes(monkeypatch):
    c = _rig(monkeypatch)
    plan = _prepare(c)
    c.world.policy_current = False
    result = plan.apply(confirmed=True)
    assert result.status == "conflict_requires_review"
    assert c.world.upstream_writes == c.world.reassessment_writes == 0


def test_recovery_assessment_upstream_not_current_is_read_only(monkeypatch):
    c = _rig(monkeypatch)
    assessment = _recover(c)
    assert assessment.status == "upstream_not_current"
    assert not assessment.can_replay_automatically
    assert c.world.upstream_writes == c.world.reassessment_writes == 0


def test_recovery_assessment_missing_31_after_30(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    assessment = _recover(c)
    assert assessment.status == "upstream_current_reassessment_missing"
    assert (
        assessment.exact_upstream_current and not assessment.exact_reassessment_current
    )
    assert c.world.upstream_writes == c.world.reassessment_writes == 0


def test_recovery_assessment_written_not_current_31(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.history = (c.review.decision.decision_revision,)
    assessment = _recover(c)
    assert assessment.status == "reassessment_written_not_current"
    assert not assessment.can_replay_automatically


def test_recovery_assessment_verified_pair(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = c.world.reassessment_current = True
    c.world.history = (c.review.decision.decision_revision,)
    assessment = _recover(c)
    assert assessment.status == "pair_current"
    assert assessment.exact_upstream_current and assessment.exact_reassessment_current


def test_recovery_assessment_policy_or_pointer_drift_requires_review(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.policy_current = False
    assessment = _recover(c)
    assert assessment.status == "conflict_requires_review"


def test_recovery_assessment_unreadable_canonical_is_uncertain(monkeypatch):
    c = _rig(monkeypatch)
    c.world.upstream_current = True
    c.world.reassessment_reader_failure = True
    assessment = _recover(c)
    assert assessment.status == "current_unverified"


def test_wrong_future_31_hash_prevents_even_30_preparation(monkeypatch):
    c = _rig(monkeypatch)
    c.review = replace(c.review, reassessment_decision_sha256="f" * 64)
    with pytest.raises(domain.MultiAttemptResolutionError):
        _prepare(c)
    assert c.world.upstream_writes == 0


def test_resume_needs_exact_upstream_and_explicit_confirmation(monkeypatch):
    c = _rig(monkeypatch)
    c.world.reassessment_preparation_failure = True
    plan = _prepare(c)
    assert plan.resume(confirmed=True).status == "recovery_required"
    plan.apply(confirmed=True)
    assert plan.resume(confirmed=False).status == "recovery_required"
    c.world.upstream_current = False
    assert plan.resume(confirmed=True).status == "conflict_requires_review"
    assert c.world.reassessment_writes == 0
