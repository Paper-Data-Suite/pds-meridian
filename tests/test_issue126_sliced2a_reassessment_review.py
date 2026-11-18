"""#126 D2A: future #31 relationship is explicit, exact, and never saved."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_issue126_sliceb_attempt_inventory import _attempt, _build, _case

from meridian.attempt_correction_interpretation import (
    preview_attempt_interpretation,
)
from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
)
from meridian.attempt_reassessment_review import (
    AttemptReassessmentReviewError,
    ReviewedReassessmentChoice,
    preview_reviewed_reassessment,
    render_reviewed_reassessment,
)
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicyReference,
    attempt_selection_decision_to_json_bytes,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.reassessment import (
    REASSESSMENT_POLICY_RECORD_TYPE,
    REASSESSMENT_POLICY_SCHEMA_VERSION,
    ReassessmentActor,
    ReassessmentCombination,
    ReassessmentPolicy,
    ReplacementRelationship,
    reassessment_policy_to_json_bytes,
)
from meridian.reassessment_storage import (
    StoredReassessmentPolicy,
    reassessment_policy_revision_relative_path,
)
from meridian.teacher_action_contract import TeacherActionActor

_NOW = datetime(2026, 11, 18, 2, tzinfo=UTC)


def _scenario():
    view = _build(_case())
    student = "synthetic_student_02"
    a, b = (_attempt(student, n) for n in (1, 2))
    interpretation = preview_attempt_interpretation(
        view,
        student_id=student,
        treatment="teacher_reviewed_reassessment",
        selected_attempts=(a, b),
        teacher_rationale="Separate sittings; explicitly reviewed by the teacher",
    )
    source = interpretation.source_snapshot
    candidates = tuple(
        AttemptCandidate(
            attempt=attempt,
            eligible_evidence=(
                AttemptEligibilityBasis(
                    source=EvidenceSourceReference(
                        work=source.work,
                        publication_id=source.publication_id,
                        cache_key=source.cache_key,
                        snapshot_digest=source.snapshot_digest,
                        item_id=f"synthetic_att_{number}_item",
                    ),
                    eligibility_revision=1,
                    eligibility_decision_sha256="f" * 64,
                ),
            ),
        )
        for number, attempt in enumerate((a, b), 1)
    )
    decision = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=view.class_id,
        grade_item_id=view.grade_item_id,
        work=source.work,
        student_id=student,
        membership_revision=1,
        membership_revision_sha256="d" * 64,
        policy=AttemptSelectionPolicyReference(
            policy_id="teacher_guided_one_or_more",
            policy_revision=1,
            policy_revision_sha256="e" * 64,
        ),
        source_snapshot=source,
        candidates=candidates,
        selected_attempts=(a, b),
        decision_revision=2,
        supersedes_revision=1,
        actor=AttemptSelectionActor(kind="teacher", actor_id="synthetic_teacher"),
        rationale=interpretation.suggested_canonical_rationale,
        decided_at=_NOW,
    )
    authoring = AttemptDecisionAuthoringPreview(
        candidate=decision,
        history=(1,),
        latest_persisted_decision_sha256="a" * 64,
        reviewed_current_decision_revision=1,
        expected_membership_revision=1,
        expected_membership_sha256="d" * 64,
        expected_policy_revision=1,
        expected_policy_sha256="e" * 64,
    )
    policy = ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=view.class_id,
        grade_item_id=view.grade_item_id,
        work=source.work,
        policy_id="teacher_reassessment",
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=("retain", "replace", "combine", "recency"),
        actor=ReassessmentActor(kind="teacher", actor_id="synthetic_teacher"),
        rationale="Four explicitly available relationships",
        revised_at=_NOW,
    )
    content = reassessment_policy_to_json_bytes(policy)
    stored = StoredReassessmentPolicy(
        policy=policy,
        policy_sha256=hashlib.sha256(content).hexdigest(),
        path=Path("1.json"),
        relative_path=reassessment_policy_revision_relative_path(
            view.class_id,
            view.grade_item_id,
            source.work,
            policy.policy_id,
            policy.policy_revision,
        ),
        content=content,
    )
    actor = TeacherActionActor("synthetic_teacher", "c" * 64, "saved")
    return interpretation, authoring, stored, actor, a, b


def _review(choice, *, setup=None, **overrides):
    interpretation, authoring, policy, actor, _, _ = (
        _scenario() if setup is None else setup
    )
    kwargs = dict(
        interpretation=interpretation,
        authoring=authoring,
        policy=policy,
        history=(),
        current=None,
        choice=choice,
        actor=actor,
        decided_at=_NOW,
    )
    kwargs.update(overrides)
    return preview_reviewed_reassessment(**kwargs)


def test_retain_two_exact_attempts_no_math_or_writes():
    setup = _scenario()
    before = repr(setup)
    reviewed = _review(ReviewedReassessmentChoice("retain"), setup=setup)
    assert repr(setup) == before
    assert reviewed.decision.mode == "retain"
    assert (
        reviewed.decision.contributing_attempts == setup[1].candidate.selected_attempts
    )
    assert (
        reviewed.decision.attempt_selection.decision_sha256
        == hashlib.sha256(
            attempt_selection_decision_to_json_bytes(setup[1].candidate)
        ).hexdigest()
    )
    assert reviewed.decision.decision_revision == 1
    assert reviewed.expected_current_reassessment == (None, None)
    assert not reviewed.may_execute_without_revalidation
    text = render_reviewed_reassessment(reviewed)
    assert "NOT SAVED" in text and "NOT atomic" in text
    assert "synthetic_student_02" not in text


def test_replace_requires_teacher_specified_replaced_identity():
    setup = _scenario()
    a, b = setup[-2:]
    reviewed = _review(
        ReviewedReassessmentChoice(
            "replace", replacements=(ReplacementRelationship(b, (a,)),)
        ),
        setup=setup,
    )
    assert reviewed.decision.contributing_attempts == (b,)
    assert reviewed.decision.replacement_relationships[0].replaced_attempts == (a,)
    assert reviewed.decision.mode == "replace"


def test_combine_preserves_selected_and_requires_explicit_group():
    setup = _scenario()
    a, b = setup[-2:]
    reviewed = _review(
        ReviewedReassessmentChoice(
            "combine", combinations=(ReassessmentCombination("group_1", (a, b)),)
        ),
        setup=setup,
    )
    assert reviewed.decision.mode == "combine"
    assert reviewed.decision.contributing_attempts == (a, b)
    assert reviewed.decision.combinations[0].members == (a, b)


def test_recency_requires_explicit_order_and_suffix_not_timestamps():
    setup = _scenario()
    a, b = setup[-2:]
    reviewed = _review(
        ReviewedReassessmentChoice(
            "recency", recency_order=(a, b), recency_contributors=(b,)
        ),
        setup=setup,
    )
    assert reviewed.decision.mode == "recency"
    assert reviewed.decision.recency_order == (a, b)
    assert reviewed.decision.contributing_attempts == (b,)
    with pytest.raises(AttemptReassessmentReviewError):
        _review(ReviewedReassessmentChoice("recency"), setup=setup)
    with pytest.raises(AttemptReassessmentReviewError):
        _review(
            ReviewedReassessmentChoice(
                "recency", recency_order=(a, b), recency_contributors=(a,)
            ),
            setup=setup,
        )


def test_foreign_source_attempt_cannot_be_added_to_relationship():
    setup = _scenario()
    a, b = setup[-2:]
    foreign = _attempt("synthetic_student_03", 1)
    for choice in (
        ReviewedReassessmentChoice(
            "replace", replacements=(ReplacementRelationship(b, (foreign,)),)
        ),
        ReviewedReassessmentChoice(
            "combine", combinations=(ReassessmentCombination("group_1", (a, foreign)),)
        ),
        ReviewedReassessmentChoice(
            "recency", recency_order=(a, foreign), recency_contributors=(foreign,)
        ),
    ):
        with pytest.raises(AttemptReassessmentReviewError):
            _review(choice, setup=setup)


def test_correction_and_unresolved_are_not_multi_relationships():
    setup = _scenario()
    interpretation = replace(setup[0], treatment="teacher_reviewed_correction")
    with pytest.raises(AttemptReassessmentReviewError, match="separate performances"):
        _review(
            ReviewedReassessmentChoice("retain"),
            setup=setup,
            interpretation=interpretation,
        )
    with pytest.raises(AttemptReassessmentReviewError):
        _review(
            ReviewedReassessmentChoice("retain"),
            setup=setup,
            interpretation=replace(setup[0], treatment="unresolved"),
        )


def test_candidate_scope_and_rationale_mismatch_prevent_preparation():
    setup = _scenario()
    invalid = replace(
        setup[1],
        candidate=replace(setup[1].candidate, rationale="Not the teacher story"),
    )
    with pytest.raises(AttemptReassessmentReviewError, match="Exact #30"):
        _review(ReviewedReassessmentChoice("retain"), setup=setup, authoring=invalid)
    foreign_story = replace(setup[0], student_id="synthetic_student_03")
    with pytest.raises(AttemptReassessmentReviewError):
        _review(
            ReviewedReassessmentChoice("retain"),
            setup=setup,
            interpretation=foreign_story,
        )


def test_policy_allowlist_and_subject_check_fail_closed():
    setup = _scenario()
    altered_policy = replace(setup[2].policy, allowed_modes=("retain",))
    content = reassessment_policy_to_json_bytes(altered_policy)
    changed_stored = StoredReassessmentPolicy(
        policy=altered_policy,
        policy_sha256=hashlib.sha256(content).hexdigest(),
        path=setup[2].path,
        relative_path=setup[2].relative_path,
        content=content,
    )
    with pytest.raises(AttemptReassessmentReviewError, match="policy"):
        _review(
            ReviewedReassessmentChoice("combine"), setup=setup, policy=changed_stored
        )
    changed_author = TeacherActionActor("another_teacher", "c" * 64, "saved")
    with pytest.raises(AttemptReassessmentReviewError, match="Exact #30"):
        _review(ReviewedReassessmentChoice("retain"), setup=setup, actor=changed_author)


def test_revision_history_must_be_contiguous_and_current_pointer_consistent():
    setup = _scenario()
    for bad in ((2,), (1, 3), (0,), (True,), (1, 1)):
        with pytest.raises(AttemptReassessmentReviewError, match="contiguous"):
            _review(ReviewedReassessmentChoice("retain"), setup=setup, history=bad)
    valid = _review(ReviewedReassessmentChoice("retain"), setup=setup, history=(1, 2))
    assert valid.decision.decision_revision == 3
    assert valid.decision.supersedes_revision == 2


def test_replacement_not_in_selected_and_invalid_recency_blocked():
    setup = _scenario()
    a, b = setup[-2:]
    with pytest.raises(AttemptReassessmentReviewError):
        _review(
            ReviewedReassessmentChoice(
                "replace",
                replacements=(
                    ReplacementRelationship(a, (b,)),
                    ReplacementRelationship(b, (a,)),
                ),
            ),
            setup=setup,
        )
    with pytest.raises(AttemptReassessmentReviewError):
        _review(
            ReviewedReassessmentChoice(
                "recency", recency_order=(b, a), recency_contributors=(b,)
            ),
            setup=setup,
        )


def test_existing_current_selection_cannot_be_forged_from_untyped_input():
    setup = _scenario()
    with pytest.raises(AttemptReassessmentReviewError, match="current #31"):
        _review(ReviewedReassessmentChoice("retain"), setup=setup, current="unknown")


def test_strict_future_digest_changes_with_exact_reviewed_intent():
    setup = _scenario()
    plan1 = _review(ReviewedReassessmentChoice("retain"), setup=setup)
    revised = replace(setup[1].candidate, decided_at=_NOW.replace(hour=3))
    plan2 = _review(
        ReviewedReassessmentChoice("retain"),
        setup=setup,
        authoring=replace(setup[1], candidate=revised),
    )
    assert plan1.upstream_decision_sha256 != plan2.upstream_decision_sha256
    assert plan1.reassessment_decision_sha256 != plan2.reassessment_decision_sha256
