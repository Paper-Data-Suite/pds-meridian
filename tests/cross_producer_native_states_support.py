"""Producer-native state acceptance support for Meridian issue #44."""

from __future__ import annotations

from meridian.adapters import (
    AdapterProjectionRequest,
    AdapterRegistry,
)
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
)
from meridian.attempt_selection_storage import (
    AttemptCandidateDerivation,
    AttemptSelectionResolution,
    resolve_current_attempt_selection,
    select_attempt_selection_decision_revision,
    select_attempt_selection_policy_revision,
    write_attempt_selection_decision_revision,
    write_attempt_selection_policy_revision,
)
from meridian.evidence import EvidenceInventory
from meridian.quillan_adapter import QuillanAcademicResultAdapter
from tests.cross_producer_attempts_support import Issue44AttemptWorkspace
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    GRADE_ITEM_ID,
    NOW,
)
from tests.cross_producer_test_support import SHARED_STUDENT_ID
from tests.quillan_test_support import (
    quillan_manifest_bytes,
    quillan_publication,
    quillan_registration,
)


def select_scoreform_attempt_sequences(
    scenario: Issue44AttemptWorkspace,
    derivation: AttemptCandidateDerivation,
    sequences: tuple[int, ...],
) -> AttemptSelectionResolution:
    """Persist/select exactly the requested ScoreForm attempt identities."""
    work = scenario.mixed.publications["scoreform"].work
    selected = tuple(
        candidate.attempt
        for candidate in derivation.candidates
        if candidate.attempt.native.sequence in sequences
    )
    selected_sequences = tuple(attempt.native.sequence for attempt in selected)
    if selected_sequences != sequences:
        raise AssertionError("Requested attempt sequence is not an exact candidate.")

    suffix = "none" if not sequences else "_".join(str(value) for value in sequences)
    policy = AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        policy_id=f"issue44_select_{suffix}",
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=len(selected),
        maximum_selected=len(selected),
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Issue #44 explicit attempt-state acceptance.",
        revised_at=NOW,
    )
    stored_policy = write_attempt_selection_policy_revision(
        scenario.mixed.root,
        policy,
    ).stored
    select_attempt_selection_policy_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )

    decision = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=SHARED_STUDENT_ID,
        membership_revision=1,
        membership_revision_sha256=scenario.membership_digests["scoreform"],
        policy=AttemptSelectionPolicyReference(
            policy.policy_id,
            policy.policy_revision,
            stored_policy.policy_sha256,
        ),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=selected,
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="No score, attempt number, or timestamp inferred this selection.",
        decided_at=NOW,
    )
    write_attempt_selection_decision_revision(
        scenario.mixed.root,
        decision,
        authorized_snapshot=scenario.authorized["scoreform"],
    )
    select_attempt_selection_decision_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=scenario.authorized["scoreform"],
        expected_current_decision_revision=None,
    )
    return resolve_current_attempt_selection(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=scenario.authorized["scoreform"],
    )


def project_quillan_with_rating(rating_value: int) -> EvidenceInventory:
    """Project a released Quillan fixture with one exact native rating value."""
    manifest = quillan_manifest_bytes(rating_value=rating_value)
    request = AdapterProjectionRequest(
        quillan_publication(manifest),
        quillan_registration(),
        None,
        manifest,
    )
    return AdapterRegistry((QuillanAcademicResultAdapter(),)).invoke(
        request,
        lambda _: "0.10.0",
    )
