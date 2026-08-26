from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceEligibilitySerializationError,
    EvidenceEligibilityValidationError,
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
    evidence_eligibility_decision_from_json_bytes,
    evidence_eligibility_decision_to_dict,
    evidence_eligibility_decision_to_json_bytes,
    evidence_source_key,
    evidence_source_reference_to_json_bytes,
    validate_evidence_eligibility_transition,
)

CLASS_ID = "synthetic_class_2026"
ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
DECIDED = datetime(2026, 8, 25, 18, tzinfo=UTC)


def source(*, item_id: str = "scoreform_item_1") -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id=item_id,
    )


def state(
    name: str = "current",
) -> EvidenceSourceStateObservation:
    if name == "current":
        return EvidenceSourceStateObservation(
            state="current",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=None,
        )
    if name == "superseded":
        return EvidenceSourceStateObservation(
            state="superseded",
            head_publication_id="pub_" + "5" * 32,
            successor_publication_id="pub_" + "5" * 32,
            withdrawn_at=None,
        )
    if name == "withdrawn":
        return EvidenceSourceStateObservation(
            state="withdrawn",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=DECIDED - timedelta(hours=1),
        )
    return EvidenceSourceStateObservation(
        state="withdrawn_superseded",
        head_publication_id="pub_" + "5" * 32,
        successor_publication_id="pub_" + "5" * 32,
        withdrawn_at=DECIDED - timedelta(hours=1),
    )


def policy() -> EvidenceEligibilityPolicyReference:
    return EvidenceEligibilityPolicyReference(
        policy_id="teacher_local_eligibility",
        policy_version="1",
    )


def actor(kind: str = "teacher") -> EvidenceDecisionActor:
    return EvidenceDecisionActor(
        kind=kind,  # type: ignore[arg-type]
        actor_id=f"{kind}_local",
    )


def decision(
    disposition: str = "included",
    *,
    revision: int = 1,
    source_value: EvidenceSourceReference | None = None,
    source_state: EvidenceSourceStateObservation | None = None,
    actor_value: EvidenceDecisionActor | None = None,
    policy_value: EvidenceEligibilityPolicyReference | None | object = ...,
    reason_codes: tuple[str, ...] | None = None,
) -> EvidenceEligibilityDecision:
    if source_value is None:
        source_value = source()
    if source_state is None:
        if disposition == "superseded":
            source_state = state("superseded")
        elif disposition == "withdrawn":
            source_state = state("withdrawn")
        else:
            source_state = state()
    if actor_value is None:
        actor_value = actor(
            "system" if disposition in {"superseded", "withdrawn"} else "teacher"
        )
    if policy_value is ...:
        policy_value = None if disposition in {"superseded", "withdrawn"} else policy()
    if reason_codes is None:
        reason_codes = (
            () if disposition == "included" else (f"eligibility.{disposition}",)
        )
    return EvidenceEligibilityDecision(
        schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
        record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=ITEM_ID,
        source=source_value,
        membership_revision=1,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        eligibility_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        disposition=disposition,  # type: ignore[arg-type]
        actor=actor_value,
        policy=policy_value,  # type: ignore[arg-type]
        reason_codes=reason_codes,
        rationale=None,
        source_state=source_state,
        decided_at=DECIDED + timedelta(minutes=revision - 1),
    )


def test_source_reference_is_exact_and_source_key_is_deterministic() -> None:
    value = source()
    first = evidence_source_key(value)
    second = evidence_source_key(source())
    assert first == second
    assert first == hashlib.sha256(
        evidence_source_reference_to_json_bytes(value)
    ).hexdigest()
    assert len(first) == 64


def test_item_id_alone_is_not_exact_source_identity() -> None:
    original = source()
    changed_snapshot = EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key="6" * 64,
        snapshot_digest="7" * 64,
        item_id=original.item_id,
    )
    assert changed_snapshot != original
    assert evidence_source_key(changed_snapshot) != evidence_source_key(original)


@pytest.mark.parametrize(
    "field,value",
    [
        ("publication_id", "publication_1"),
        ("cache_key", "abc"),
        ("snapshot_digest", "abc"),
        ("item_id", "../unsafe"),
    ],
)
def test_source_reference_rejects_invalid_identity(field: str, value: str) -> None:
    kwargs = {
        "work": WORK,
        "publication_id": PUBLICATION_ID,
        "cache_key": CACHE_KEY,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "item_id": "scoreform_item_1",
    }
    kwargs[field] = value
    with pytest.raises(EvidenceEligibilityValidationError):
        EvidenceSourceReference(**kwargs)  # type: ignore[arg-type]


def test_decisions_are_frozen_and_slotted() -> None:
    value = decision()
    with pytest.raises(FrozenInstanceError):
        value.disposition = "excluded"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize(
    "disposition",
    ["included", "excluded", "pending", "unsupported", "superseded", "withdrawn"],
)
def test_all_required_dispositions_are_first_class(disposition: str) -> None:
    assert decision(disposition).disposition == disposition


def test_withdrawn_and_superseded_require_system_authority() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="system authority"):
        decision("withdrawn", actor_value=actor("teacher"))
    with pytest.raises(EvidenceEligibilityValidationError, match="system authority"):
        decision("superseded", actor_value=actor("policy"))


def test_source_lifecycle_dispositions_do_not_claim_policy_causation() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="policy causation"):
        decision("withdrawn", policy_value=policy())
    with pytest.raises(EvidenceEligibilityValidationError, match="policy causation"):
        decision("superseded", policy_value=policy())


def test_academic_dispositions_require_policy_and_non_system_authority() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="policy reference"):
        decision("excluded", policy_value=None)
    with pytest.raises(EvidenceEligibilityValidationError, match="teacher or policy"):
        decision("pending", actor_value=actor("system"))


def test_included_has_no_reasons_and_cannot_be_authored_against_withdrawal() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="must not carry"):
        decision("included", reason_codes=("eligibility.manual",))
    with pytest.raises(EvidenceEligibilityValidationError, match="withdrawn"):
        decision("included", source_state=state("withdrawn"))


def test_nonincluded_dispositions_require_reason_codes() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="reason code"):
        decision("excluded", reason_codes=())
    with pytest.raises(EvidenceEligibilityValidationError, match="reason code"):
        decision("pending", reason_codes=())
    with pytest.raises(EvidenceEligibilityValidationError, match="reason code"):
        decision("unsupported", reason_codes=())


def test_pending_is_not_excluded_and_unsupported_is_not_zero() -> None:
    assert decision("pending") != decision("excluded")
    unsupported = decision("unsupported")
    assert unsupported.disposition == "unsupported"
    assert not hasattr(unsupported, "score")
    assert not hasattr(unsupported, "value")


def test_source_state_shape_is_strict() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="successor"):
        EvidenceSourceStateObservation(
            state="superseded",
            head_publication_id="pub_" + "5" * 32,
            successor_publication_id=None,
            withdrawn_at=None,
        )
    with pytest.raises(EvidenceEligibilityValidationError, match="withdrawal"):
        EvidenceSourceStateObservation(
            state="withdrawn",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=None,
        )


def test_revision_one_and_later_supersession_rules() -> None:
    with pytest.raises(EvidenceEligibilityValidationError, match="revision 1"):
        replace(decision(), supersedes_revision=1)
    with pytest.raises(
        EvidenceEligibilityValidationError, match="eligibility_revision - 1"
    ):
        replace(decision("excluded", revision=2), supersedes_revision=None)


def test_transition_is_contiguous_and_preserves_exact_source() -> None:
    first = decision()
    second = decision("excluded", revision=2)
    assert validate_evidence_eligibility_transition(first, second) == second
    with pytest.raises(
        EvidenceEligibilityValidationError, match="exact evidence source"
    ):
        validate_evidence_eligibility_transition(
            first,
            decision("excluded", revision=2, source_value=source(item_id="other_item")),
        )


def test_transition_allows_membership_and_policy_context_to_change() -> None:
    first = decision()
    second = replace(
        decision("excluded", revision=2),
        membership_revision=2,
        membership_revision_sha256="8" * 64,
        policy=EvidenceEligibilityPolicyReference(
            policy_id="teacher_local_eligibility",
            policy_version="2",
        ),
    )
    assert validate_evidence_eligibility_transition(first, second) == second


def test_naive_decision_timestamp_is_rejected() -> None:
    value = evidence_eligibility_decision_to_dict(decision())
    value["decided_at"] = "2026-08-25T18:00:00"
    payload = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(EvidenceEligibilitySerializationError, match="timezone-aware"):
        evidence_eligibility_decision_from_json_bytes(payload)


def test_canonical_json_round_trip_is_exact() -> None:
    value = decision("excluded")
    payload = evidence_eligibility_decision_to_json_bytes(value)
    assert payload.endswith(b"\n")
    assert evidence_eligibility_decision_from_json_bytes(payload) == value
    assert evidence_eligibility_decision_to_json_bytes(
        evidence_eligibility_decision_from_json_bytes(payload)
    ) == payload


def test_noncanonical_duplicate_missing_and_unknown_json_are_rejected() -> None:
    payload = evidence_eligibility_decision_to_json_bytes(decision())
    noncanonical = json.dumps(json.loads(payload), separators=(",", ":")).encode()
    with pytest.raises(EvidenceEligibilitySerializationError, match="canonically"):
        evidence_eligibility_decision_from_json_bytes(noncanonical)

    text = payload.decode()
    duplicate = text.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n  "class_id": "synthetic_class_2026",',
        1,
    ).encode()
    with pytest.raises(EvidenceEligibilitySerializationError, match="duplicate"):
        evidence_eligibility_decision_from_json_bytes(duplicate)

    mapping = json.loads(payload)
    mapping.pop("rationale")
    missing = (json.dumps(mapping, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(EvidenceEligibilitySerializationError, match="missing"):
        evidence_eligibility_decision_from_json_bytes(missing)

    mapping = json.loads(payload)
    mapping["extra"] = True
    unknown = (json.dumps(mapping, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(EvidenceEligibilitySerializationError, match="unknown"):
        evidence_eligibility_decision_from_json_bytes(unknown)
