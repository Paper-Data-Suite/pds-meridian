"""#126 Slice A: source-fact and academic-selection baseline (synthetic only).

This does not implement correction classification or claim a verified scan
relationship. It proves that the existing canonical models can represent
different explicit teacher decisions over the *same* producer attempt facts.
No workspace, producer record, or current pointer is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import get_args

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicyReference,
    AttemptTargetReference,
)
from meridian.attempt_selection_storage import AttemptSelectionResolutionStatus
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.reassessment import (
    REASSESSMENT_DECISION_RECORD_TYPE,
    REASSESSMENT_DECISION_SCHEMA_VERSION,
    REASSESSMENT_RELATIONSHIP_BASIS,
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentDecision,
    ReassessmentPolicyReference,
)
from meridian.reassessment_storage import ReassessmentResolutionStatus

_WORK = ModuleWorkRef("scoreform", "synthetic_class_126", "scan_review_126")
_GRADE_ITEM = "synthetic_grade_item_126"
_STUDENT = "synthetic_student_01"
_PUBLICATION = "pub_" + "a" * 32
_CACHE = "b" * 64
_SNAPSHOT = "c" * 64
_MEMBERSHIP = "d" * 64
_POLICY = "e" * 64
_ELIGIBILITY = "f" * 64
_NOW = datetime(2026, 11, 17, 21, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _SyntheticScoreFormObservation:
    """Test-only points; NOT part of a Meridian attempt's academic identity."""

    attempt: AttemptObservationReference
    correct: int


def _attempt(number: int, *, snapshot: str = _SNAPSHOT) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=AttemptProjectionReference(
            work=_WORK,
            publication_id=_PUBLICATION,
            cache_key=_CACHE,
            snapshot_digest=snapshot,
        ),
        student_id=_STUDENT,
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=number),
    )


def _candidate(number: int) -> AttemptCandidate:
    return AttemptCandidate(
        attempt=_attempt(number),
        eligible_evidence=(
            AttemptEligibilityBasis(
                source=EvidenceSourceReference(
                    work=_WORK,
                    publication_id=_PUBLICATION,
                    cache_key=_CACHE,
                    snapshot_digest=_SNAPSHOT,
                    item_id=f"synthetic_question_{number}_1",
                ),
                eligibility_revision=1,
                eligibility_decision_sha256=_ELIGIBILITY,
            ),
        ),
    )


def _decision(
    selected: tuple[AttemptObservationReference, ...],
) -> AttemptSelectionDecision:
    return AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=_WORK.class_id,
        grade_item_id=_GRADE_ITEM,
        work=_WORK,
        student_id=_STUDENT,
        membership_revision=1,
        membership_revision_sha256=_MEMBERSHIP,
        policy=AttemptSelectionPolicyReference(
            policy_id="teacher_explicit_attempts",
            policy_revision=1,
            policy_revision_sha256=_POLICY,
        ),
        source_snapshot=_attempt(1).source_snapshot,
        candidates=(_candidate(1), _candidate(2)),
        selected_attempts=selected,
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor(kind="teacher", actor_id="synthetic_teacher"),
        rationale="Synthetic teacher-reviewed decision",
        decided_at=_NOW,
    )


@pytest.mark.parametrize("original_correct,second_correct", [(0, 6), (6, 0)])
def test_same_native_attempt_facts_permit_distinct_explicit_decisions(
    original_correct: int, second_correct: int
) -> None:
    """Neither native sequence nor a numeric outcome identifies a correction."""
    observations = (
        _SyntheticScoreFormObservation(_attempt(1), original_correct),
        _SyntheticScoreFormObservation(_attempt(2), second_correct),
    )
    corrected_result_use = _decision((observations[1].attempt,))
    genuine_multi_attempt_review = _decision(
        (observations[0].attempt, observations[1].attempt)
    )

    assert corrected_result_use.candidates == genuine_multi_attempt_review.candidates
    assert corrected_result_use.selected_attempts == (observations[1].attempt,)
    assert genuine_multi_attempt_review.selected_attempts == tuple(
        row.attempt for row in observations
    )
    assert corrected_result_use.selected_attempts != (
        genuine_multi_attempt_review.selected_attempts
    )
    assert corrected_result_use.source_snapshot == (
        genuine_multi_attempt_review.source_snapshot
    )
    # These are alternative explicit decisions, not concurrent current pointers.
    # Nothing in the native sequence or score verifies a correction relationship.


def test_attempt_identity_remains_exact_to_producer_snapshot() -> None:
    first = _attempt(2)
    different_snapshot = _attempt(2, snapshot="9" * 64)
    assert first != different_snapshot
    assert first.native.sequence == different_snapshot.native.sequence == 2
    assert first.source_snapshot != different_snapshot.source_snapshot


def test_reassessment_needs_explicit_interpretation() -> None:
    multi = _decision((_attempt(1), _attempt(2)))
    assert not hasattr(multi, "mode")
    assert REASSESSMENT_RELATIONSHIP_BASIS == "explicit"

    interpretation = ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=_WORK.class_id,
        grade_item_id=_GRADE_ITEM,
        work=_WORK,
        student_id=_STUDENT,
        attempt_selection=AttemptSelectionDecisionReference(
            decision_revision=1,
            decision_sha256="1" * 64,
        ),
        policy=ReassessmentPolicyReference(
            policy_id="teacher_reassessment",
            policy_revision=1,
            policy_revision_sha256="2" * 64,
        ),
        mode="retain",
        contributing_attempts=multi.selected_attempts,
        replacement_relationships=(),
        combinations=(),
        recency_order=(),
        decision_revision=1,
        supersedes_revision=None,
        actor=ReassessmentActor(kind="teacher", actor_id="synthetic_teacher"),
        rationale="Retain separately observed performances",
        decided_at=_NOW,
    )
    assert interpretation.mode == "retain"
    assert interpretation.contributing_attempts == multi.selected_attempts
    assert interpretation.attempt_selection.decision_sha256 == "1" * 64


def test_canonical_resolution_vocabularies_retain_uncertainty() -> None:
    attempt_statuses = set(get_args(AttemptSelectionResolutionStatus))
    assert {
        "no_decision",
        "selected_none",
        "selected",
        "policy_stale",
        "membership_stale",
        "eligibility_stale",
        "candidate_set_stale",
        "source_unverifiable",
        "unsupported_attempt_shape",
    } <= attempt_statuses

    reassessment_statuses = set(get_args(ReassessmentResolutionStatus))
    assert {
        "not_applicable",
        "attempt_selection_unresolved",
        "selected_none",
        "single_selected",
        "no_decision",
        "resolved",
        "attempt_selection_stale",
        "policy_stale",
    } <= reassessment_statuses
