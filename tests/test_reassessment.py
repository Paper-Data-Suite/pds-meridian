from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection import (
    AttemptNativeIdentity,
    AttemptObservationReference,
    AttemptProjectionReference,
    AttemptTargetReference,
)
from meridian.reassessment import (
    REASSESSMENT_DECISION_RECORD_TYPE,
    REASSESSMENT_DECISION_SCHEMA_VERSION,
    REASSESSMENT_POLICY_RECORD_TYPE,
    REASSESSMENT_POLICY_SCHEMA_VERSION,
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentCombination,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentPolicyReference,
    ReassessmentSerializationError,
    ReassessmentValidationError,
    ReplacementRelationship,
    reassessment_decision_from_json_bytes,
    reassessment_decision_to_json_bytes,
    reassessment_policy_from_json_bytes,
    reassessment_policy_to_json_bytes,
    reassessment_subject_key,
    validate_reassessment_decision_transition,
    validate_reassessment_policy_transition,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
ATTEMPT_DECISION_DIGEST = "4" * 64
POLICY_DIGEST = "5" * 64
NOW = datetime(2026, 8, 26, 4, tzinfo=UTC)


def attempt(number: int) -> AttemptObservationReference:
    return AttemptObservationReference(
        source_snapshot=AttemptProjectionReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
        ),
        student_id="student_1",
        target=AttemptTargetReference(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            owning_system=None,
            contract_version=None,
        ),
        native=AttemptNativeIdentity(identifier=None, sequence=number),
    )


def actor(kind: str = "teacher") -> ReassessmentActor:
    return ReassessmentActor(
        kind=kind,  # type: ignore[arg-type]
        actor_id=f"{kind}_local",
    )


def policy(
    *, revision: int = 1, modes: tuple[str, ...] = ("retain", "replace")
) -> ReassessmentPolicy:
    return ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        policy_id="teacher_reassessment",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        relationship_basis="explicit",
        allowed_modes=modes,  # type: ignore[arg-type]
        actor=actor(),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def decision(
    *,
    revision: int = 1,
    mode: str = "retain",
    contributing: tuple[AttemptObservationReference, ...] | None = None,
    replacements: tuple[ReplacementRelationship, ...] = (),
    combinations: tuple[ReassessmentCombination, ...] = (),
    recency: tuple[AttemptObservationReference, ...] = (),
) -> ReassessmentDecision:
    if contributing is None:
        contributing = (attempt(1), attempt(2))
    return ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        student_id="student_1",
        attempt_selection=AttemptSelectionDecisionReference(
            decision_revision=1,
            decision_sha256=ATTEMPT_DECISION_DIGEST,
        ),
        policy=ReassessmentPolicyReference(
            policy_id="teacher_reassessment",
            policy_revision=1,
            policy_revision_sha256=POLICY_DIGEST,
        ),
        mode=mode,  # type: ignore[arg-type]
        contributing_attempts=contributing,
        replacement_relationships=replacements,
        combinations=combinations,
        recency_order=recency,
        decision_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        actor=actor(),
        rationale=None,
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def test_policy_is_explicit_and_normalizes_mode_set() -> None:
    value = policy(modes=("recency", "retain", "replace"))
    assert value.relationship_basis == "explicit"
    assert value.allowed_modes == ("retain", "replace", "recency")
    with pytest.raises(ReassessmentValidationError, match="explicit"):
        replace(value, relationship_basis="latest")  # type: ignore[arg-type]
    with pytest.raises(ReassessmentValidationError, match="duplicates"):
        policy(modes=("retain", "retain"))
    with pytest.raises(ReassessmentValidationError, match="must not be empty"):
        policy(modes=())


def test_policy_and_decision_are_frozen_and_slotted() -> None:
    value = decision()
    with pytest.raises(FrozenInstanceError):
        value.student_id = "other"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")
    assert not hasattr(policy(), "__dict__")


def test_retain_mode_has_no_relationship_payload() -> None:
    value = decision()
    assert value.mode == "retain"
    assert value.contributing_attempts == (attempt(1), attempt(2))
    assert value.replacement_relationships == ()
    assert value.combinations == ()
    assert value.recency_order == ()
    with pytest.raises(ReassessmentValidationError, match="retain mode"):
        replace(
            value,
            replacement_relationships=(
                ReplacementRelationship(attempt(2), (attempt(1),)),
            ),
        )


def test_replace_mode_is_directed_and_preserves_replacement_as_contributor() -> None:
    relationship = ReplacementRelationship(attempt(2), (attempt(1),))
    value = decision(
        mode="replace",
        contributing=(attempt(2),),
        replacements=(relationship,),
    )
    assert value.replacement_relationships == (relationship,)
    with pytest.raises(ReassessmentValidationError, match="cannot replace itself"):
        ReplacementRelationship(attempt(1), (attempt(1),))


def test_replace_rejects_competing_targets_chains_and_cycles() -> None:
    first = ReplacementRelationship(attempt(2), (attempt(1),))
    competing = ReplacementRelationship(attempt(3), (attempt(1),))
    with pytest.raises(ReassessmentValidationError, match="only one replacement"):
        decision(
            mode="replace",
            contributing=(attempt(2), attempt(3)),
            replacements=(first, competing),
        )
    chain = ReplacementRelationship(attempt(3), (attempt(2),))
    with pytest.raises(ReassessmentValidationError, match="chains and cycles"):
        decision(
            mode="replace",
            contributing=(attempt(3),),
            replacements=(first, chain),
        )


def test_replace_rejects_replaced_attempt_that_still_contributes() -> None:
    relationship = ReplacementRelationship(attempt(2), (attempt(1),))
    with pytest.raises(ReassessmentValidationError, match="must not remain"):
        decision(
            mode="replace",
            contributing=(attempt(1), attempt(2)),
            replacements=(relationship,),
        )


def test_combine_mode_is_relationship_only_and_disjoint() -> None:
    first = ReassessmentCombination("combo_a", (attempt(1), attempt(2)))
    value = decision(
        mode="combine",
        contributing=(attempt(1), attempt(2), attempt(3)),
        combinations=(first,),
    )
    assert value.combinations == (first,)
    assert not hasattr(value, "average")
    with pytest.raises(ReassessmentValidationError, match="at least two"):
        ReassessmentCombination("combo_a", (attempt(1),))
    second = ReassessmentCombination("combo_b", (attempt(2), attempt(3)))
    with pytest.raises(ReassessmentValidationError, match="must not overlap"):
        decision(
            mode="combine",
            contributing=(attempt(1), attempt(2), attempt(3)),
            combinations=(first, second),
        )


def test_recency_is_explicit_order_and_requires_proper_suffix() -> None:
    value = decision(
        mode="recency",
        contributing=(attempt(2), attempt(3)),
        recency=(attempt(1), attempt(2), attempt(3)),
    )
    assert value.recency_order[0] == attempt(1)
    assert value.contributing_attempts == (attempt(2), attempt(3))
    with pytest.raises(ReassessmentValidationError, match="contiguous"):
        decision(
            mode="recency",
            contributing=(attempt(1), attempt(3)),
            recency=(attempt(1), attempt(2), attempt(3)),
        )
    with pytest.raises(ReassessmentValidationError, match="use retain"):
        decision(
            mode="recency",
            contributing=(attempt(1), attempt(2)),
            recency=(attempt(1), attempt(2)),
        )


def test_exact_attempt_selection_reference_is_revision_and_digest_bound() -> None:
    first = AttemptSelectionDecisionReference(1, "a" * 64)
    second = AttemptSelectionDecisionReference(2, "a" * 64)
    third = AttemptSelectionDecisionReference(1, "b" * 64)
    assert first != second
    assert first != third


def test_policy_and_decision_transitions_are_contiguous_and_identity_stable() -> None:
    first_policy = policy()
    second_policy = policy(revision=2, modes=("retain", "replace", "combine"))
    assert (
        validate_reassessment_policy_transition(first_policy, second_policy)
        == second_policy
    )
    with pytest.raises(ReassessmentValidationError, match="logical identity"):
        validate_reassessment_policy_transition(
            first_policy, replace(second_policy, policy_id="other_policy")
        )

    first_decision = decision()
    second_decision = decision(revision=2)
    assert (
        validate_reassessment_decision_transition(first_decision, second_decision)
        == second_decision
    )
    with pytest.raises(ReassessmentValidationError, match="logical identity"):
        validate_reassessment_decision_transition(
            first_decision, replace(second_decision, student_id="student_2")
        )


def test_transition_timestamps_are_nondecreasing() -> None:
    with pytest.raises(ReassessmentValidationError, match="earlier"):
        validate_reassessment_policy_transition(
            policy(), replace(policy(revision=2), revised_at=NOW - timedelta(seconds=1))
        )
    with pytest.raises(ReassessmentValidationError, match="earlier"):
        validate_reassessment_decision_transition(
            decision(),
            replace(decision(revision=2), decided_at=NOW - timedelta(seconds=1)),
        )


def test_timezone_is_normalized_to_utc() -> None:
    eastern = timezone(timedelta(hours=-4))
    value = replace(policy(), revised_at=NOW.astimezone(eastern))
    assert value.revised_at.tzinfo == UTC
    assert value.revised_at == NOW


def test_canonical_json_round_trip_and_duplicate_unknown_rejection() -> None:
    policy_bytes = reassessment_policy_to_json_bytes(policy())
    decision_bytes = reassessment_decision_to_json_bytes(decision())
    assert reassessment_policy_from_json_bytes(policy_bytes) == policy()
    assert reassessment_decision_from_json_bytes(decision_bytes) == decision()
    assert policy_bytes.endswith(b"\n")
    assert decision_bytes.endswith(b"\n")

    duplicate = (
        b'{"schema_version":"1","schema_version":"1"}'
    )
    with pytest.raises(ReassessmentSerializationError, match="duplicate JSON key"):
        reassessment_policy_from_json_bytes(duplicate)

    decoded = json.loads(policy_bytes)
    decoded["unexpected"] = True
    payload = (json.dumps(decoded, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(ReassessmentSerializationError, match="unknown"):
        reassessment_policy_from_json_bytes(payload)


def test_noncanonical_json_bytes_fail_closed() -> None:
    decoded = json.loads(reassessment_decision_to_json_bytes(decision()))
    noncanonical = json.dumps(decoded, sort_keys=False).encode()
    with pytest.raises(ReassessmentSerializationError, match="canonically"):
        reassessment_decision_from_json_bytes(noncanonical)


def test_subject_key_reuses_attempt_selection_scope_and_changes_by_student() -> None:
    first = reassessment_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_1")
    second = reassessment_subject_key(CLASS_ID, GRADE_ITEM_ID, WORK, "student_2")
    assert len(first) == 64
    assert first != second
