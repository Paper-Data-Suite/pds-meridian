from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptCandidate,
    AttemptEligibilityBasis,
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
    AttemptSelectionSerializationError,
    AttemptSelectionValidationError,
    AttemptTargetReference,
    attempt_observation_reference_to_json_bytes,
    attempt_selection_decision_from_json_bytes,
    attempt_selection_decision_to_json_bytes,
    attempt_selection_policy_from_json_bytes,
    attempt_selection_policy_to_json_bytes,
    attempt_subject_key,
    selection_cardinality_allows,
    validate_attempt_selection_decision_transition,
    validate_attempt_selection_policy_transition,
)
from meridian.evidence_eligibility import EvidenceSourceReference

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
POLICY_DIGEST = "5" * 64
ELIGIBILITY_DIGEST = "6" * 64
NOW = datetime(2026, 8, 26, 1, tzinfo=UTC)


def snapshot(*, digest: str = SNAPSHOT_DIGEST) -> AttemptProjectionReference:
    return AttemptProjectionReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=digest,
    )


def attempt(
    number: int = 1, *, digest: str = SNAPSHOT_DIGEST
) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=snapshot(digest=digest),
        student_id="student_1",
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=number),
    )


def basis(number: int = 1, item: int = 1) -> AttemptEligibilityBasis:
    return AttemptEligibilityBasis(
        source=EvidenceSourceReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            item_id=f"scoreform_item_{number}_{item}",
        ),
        eligibility_revision=1,
        eligibility_decision_sha256=ELIGIBILITY_DIGEST,
    )


def candidate(number: int = 1) -> AttemptCandidate:
    return AttemptCandidate(attempt=attempt(number), eligible_evidence=(basis(number),))


def actor(kind: str = "teacher") -> AttemptSelectionActor:
    return AttemptSelectionActor(
        kind=kind,  # type: ignore[arg-type]
        actor_id=f"{kind}_local",
    )


def policy(
    *, revision: int = 1, minimum: int = 0, maximum: int | None = 1
) -> AttemptSelectionPolicy:
    return AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id="teacher_explicit_attempts",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        selection_basis="explicit",
        minimum_selected=minimum,
        maximum_selected=maximum,
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def decision(
    *,
    revision: int = 1,
    candidates: tuple[AttemptCandidate, ...] | None = None,
    selected: tuple[AttemptObservationReference, ...] | None = None,
) -> AttemptSelectionDecision:
    values = (candidate(1), candidate(2)) if candidates is None else candidates
    chosen = (
        (values[0].attempt,)
        if selected is None and values
        else () if selected is None else selected
    )
    return AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id="student_1",
        membership_revision=1,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        policy=AttemptSelectionPolicyReference(
            policy_id="teacher_explicit_attempts",
            policy_revision=1,
            policy_revision_sha256=POLICY_DIGEST,
        ),
        source_snapshot=snapshot(),
        candidates=values,
        selected_attempts=chosen,
        decision_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        actor=actor(),
        rationale=None,
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def test_exact_attempt_identity_changes_with_snapshot() -> None:
    first = attempt(1)
    second = attempt(1, digest="7" * 64)
    assert first != second
    assert (
        attempt_observation_reference_to_json_bytes(first)
        != attempt_observation_reference_to_json_bytes(second)
    )


def test_native_identity_supports_identifier_or_sequence_but_not_empty() -> None:
    assert (
        AttemptNativeIdentity(identifier="native-attempt", sequence=None).identifier
        == "native-attempt"
    )
    assert AttemptNativeIdentity(identifier=None, sequence=2).sequence == 2
    with pytest.raises(AttemptSelectionValidationError, match="identifier or sequence"):
        AttemptNativeIdentity(identifier=None, sequence=None)


def test_attempt_target_must_be_explicit_attempt_boundary() -> None:
    with pytest.raises(AttemptSelectionValidationError, match="attempt"):
        AttemptTargetReference(
            target_kind="submission",
            target_id="submission_1",
            owning_system=None,
            contract_version=None,
        )


def test_candidate_requires_exact_nonduplicated_eligibility_basis() -> None:
    value = basis()
    with pytest.raises(AttemptSelectionValidationError, match="at least one"):
        AttemptCandidate(attempt=attempt(), eligible_evidence=())
    with pytest.raises(AttemptSelectionValidationError, match="duplicate"):
        AttemptCandidate(attempt=attempt(), eligible_evidence=(value, value))


def test_candidate_rejects_evidence_from_different_snapshot() -> None:
    wrong = replace(basis(), source=replace(basis().source, snapshot_digest="7" * 64))
    with pytest.raises(AttemptSelectionValidationError, match="projection snapshot"):
        AttemptCandidate(attempt=attempt(), eligible_evidence=(wrong,))


def test_policy_is_explicit_only_and_supports_none_one_or_set_cardinality() -> None:
    assert selection_cardinality_allows(policy(minimum=0, maximum=0), 0)
    assert selection_cardinality_allows(policy(minimum=0, maximum=1), 1)
    assert selection_cardinality_allows(policy(minimum=1, maximum=3), 2)
    assert selection_cardinality_allows(policy(minimum=0, maximum=None), 25)
    with pytest.raises(AttemptSelectionValidationError, match="explicit"):
        replace(policy(), selection_basis="latest")  # type: ignore[arg-type]


def test_policy_rejects_invalid_cardinality() -> None:
    with pytest.raises(AttemptSelectionValidationError, match="nonnegative"):
        policy(minimum=-1)
    with pytest.raises(AttemptSelectionValidationError, match="must not exceed"):
        policy(minimum=2, maximum=1)


def test_policy_and_decision_are_frozen_and_slotted() -> None:
    value = decision()
    with pytest.raises(FrozenInstanceError):
        value.student_id = "other"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")
    assert not hasattr(policy(), "__dict__")


def test_empty_selection_is_explicit_and_distinct_from_no_decision() -> None:
    value = decision(selected=())
    assert value.selected_attempts == ()
    assert value.candidates


def test_selected_attempts_must_be_unique_candidates() -> None:
    values = (candidate(1), candidate(2))
    with pytest.raises(AttemptSelectionValidationError, match="duplicates"):
        decision(candidates=values, selected=(values[0].attempt, values[0].attempt))
    with pytest.raises(AttemptSelectionValidationError, match="must exist"):
        decision(candidates=values, selected=(attempt(3),))


def test_multiple_selection_is_just_a_set_without_reassessment_fields() -> None:
    values = (candidate(1), candidate(2))
    value = decision(
        candidates=values,
        selected=tuple(candidate.attempt for candidate in values),
    )
    assert len(value.selected_attempts) == 2
    for forbidden in (
        "replaces",
        "replaced_by",
        "combine",
        "average",
        "recency",
        "highest",
    ):
        assert not hasattr(value, forbidden)


def test_policy_transition_is_contiguous_and_identity_stable() -> None:
    first = policy()
    second = policy(revision=2, minimum=1, maximum=2)
    assert validate_attempt_selection_policy_transition(first, second) == second
    with pytest.raises(AttemptSelectionValidationError, match="logical identity"):
        validate_attempt_selection_policy_transition(
            first, replace(second, policy_id="other")
        )
    with pytest.raises(AttemptSelectionValidationError, match="one greater"):
        validate_attempt_selection_policy_transition(
            first, replace(second, policy_revision=3, supersedes_revision=2)
        )


def test_decision_transition_is_contiguous_and_student_stable() -> None:
    first = decision()
    second = decision(revision=2, selected=())
    assert validate_attempt_selection_decision_transition(first, second) == second
    with pytest.raises(AttemptSelectionValidationError, match="logical identity"):
        validate_attempt_selection_decision_transition(
            first, replace(second, grade_item_id="other_item")
        )


def test_timestamp_must_be_aware_and_canonicalized_to_utc() -> None:
    with pytest.raises(AttemptSelectionValidationError, match="timezone-aware"):
        replace(policy(), revised_at=datetime(2026, 8, 26, 1))
    offset = NOW.astimezone(tz=timezone(timedelta(hours=-4)))
    assert replace(policy(), revised_at=offset).revised_at.tzinfo == UTC


def test_policy_and_decision_json_round_trip_are_exact() -> None:
    policy_value = policy(minimum=1, maximum=2)
    policy_bytes = attempt_selection_policy_to_json_bytes(policy_value)
    assert attempt_selection_policy_from_json_bytes(policy_bytes) == policy_value
    decision_value = decision()
    decision_bytes = attempt_selection_decision_to_json_bytes(decision_value)
    assert attempt_selection_decision_from_json_bytes(decision_bytes) == decision_value
    assert policy_bytes.endswith(b"\n") and decision_bytes.endswith(b"\n")


def test_json_rejects_duplicate_unknown_and_noncanonical_bytes() -> None:
    data = attempt_selection_policy_to_json_bytes(policy())
    decoded = json.loads(data)
    decoded["unexpected"] = True
    with pytest.raises(AttemptSelectionValidationError, match="unknown"):
        attempt_selection_policy_from_json_bytes(
            (json.dumps(decoded, sort_keys=True, indent=2) + "\n").encode()
        )
    duplicate = data.replace(
        b'{\n  "actor":',
        b'{\n  "policy_id": "duplicate",\n  "actor":',
        1,
    )
    with pytest.raises(AttemptSelectionSerializationError, match="duplicate"):
        attempt_selection_policy_from_json_bytes(duplicate)
    with pytest.raises(AttemptSelectionSerializationError, match="canonical"):
        attempt_selection_policy_from_json_bytes(data.replace(b"\n", b"\r\n"))


def test_subject_key_is_deterministic_and_scope_specific() -> None:
    first = attempt_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_1")
    assert first == attempt_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_1")
    assert first != attempt_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_2")
    assert len(first) == 64
    assert first == hashlib.sha256(
        json.dumps(
            {
                "class_id": CLASS_ID,
                "grade_item_id": GRADE_ITEM_ID,
                "student_id": "student_1",
                "work": {
                    "class_id": CLASS_ID,
                    "module_id": "scoreform",
                    "work_id": "test_1",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        ).encode() + b"\n"
    ).hexdigest()
