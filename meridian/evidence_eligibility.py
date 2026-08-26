"""Immutable canonical evidence-eligibility decision models."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    module_work_ref_from_dict,
    module_work_ref_to_dict,
    validate_module_work_ref,
)

EVIDENCE_ELIGIBILITY_SCHEMA_VERSION: Final[str] = "1"
EVIDENCE_ELIGIBILITY_RECORD_TYPE: Final[str] = (
    "meridian_evidence_eligibility_decision"
)
MAXIMUM_EVIDENCE_ELIGIBILITY_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_EVIDENCE_ELIGIBILITY_RATIONALE_LENGTH: Final[int] = 2000
MAXIMUM_EVIDENCE_ELIGIBILITY_REASON_CODE_LENGTH: Final[int] = 128
MAXIMUM_EVIDENCE_ELIGIBILITY_POLICY_VALUE_LENGTH: Final[int] = 256

EvidenceEligibilityDisposition: TypeAlias = Literal[
    "included",
    "excluded",
    "pending",
    "unsupported",
    "superseded",
    "withdrawn",
]
EvidenceEligibilityActorKind: TypeAlias = Literal["teacher", "policy", "system"]
EvidenceSourceLifecycleState: TypeAlias = Literal[
    "current", "superseded", "withdrawn", "withdrawn_superseded"
]

EVIDENCE_ELIGIBILITY_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "included",
        "excluded",
        "pending",
        "unsupported",
        "superseded",
        "withdrawn",
    }
)
EVIDENCE_ELIGIBILITY_ACTOR_KINDS: Final[frozenset[str]] = frozenset(
    {"teacher", "policy", "system"}
)
EVIDENCE_SOURCE_LIFECYCLE_STATES: Final[frozenset[str]] = frozenset(
    {"current", "superseded", "withdrawn", "withdrawn_superseded"}
)

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_PUBLICATION_ID: Final[re.Pattern[str]] = re.compile(r"^pub_[0-9a-f]{32}$")
_REASON_CODE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_OPAQUE_POLICY_VALUE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"
)

_SOURCE_KEYS: Final[frozenset[str]] = frozenset(
    {"work", "publication_id", "cache_key", "snapshot_digest", "item_id"}
)
_POLICY_KEYS: Final[frozenset[str]] = frozenset({"policy_id", "policy_version"})
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_SOURCE_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "state",
        "head_publication_id",
        "successor_publication_id",
        "withdrawn_at",
    }
)
_DECISION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "source",
        "membership_revision",
        "membership_revision_sha256",
        "eligibility_revision",
        "supersedes_revision",
        "disposition",
        "actor",
        "policy",
        "reason_codes",
        "rationale",
        "source_state",
        "decided_at",
    }
)


class EvidenceEligibilityError(ValueError):
    """Base error for canonical evidence-eligibility records."""


class EvidenceEligibilityValidationError(EvidenceEligibilityError):
    """Raised when evidence-eligibility data violates the contract."""


class EvidenceEligibilitySerializationError(EvidenceEligibilityError):
    """Raised when eligibility JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class EvidenceSourceReference:
    """Exact immutable projected evidence source identity."""

    work: ModuleWorkRef
    publication_id: str
    cache_key: str
    snapshot_digest: str
    item_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.work, ModuleWorkRef):
            raise EvidenceEligibilityValidationError(
                "work must be a Core ModuleWorkRef."
            )
        try:
            work = validate_module_work_ref(self.work)
        except RoutingModelError as error:
            raise EvidenceEligibilityValidationError(
                f"work is invalid: {error}"
            ) from error
        object.__setattr__(self, "work", work)
        publication_id = _publication_id(self.publication_id)
        object.__setattr__(self, "publication_id", publication_id)
        object.__setattr__(self, "cache_key", _sha256(self.cache_key, "cache_key"))
        object.__setattr__(
            self,
            "snapshot_digest",
            _sha256(self.snapshot_digest, "snapshot_digest"),
        )
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityPolicyReference:
    """Exact eligibility policy identity/revision provenance."""

    policy_id: str
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _opaque_policy_value(self.policy_id, "policy_id"),
        )
        object.__setattr__(
            self,
            "policy_version",
            _opaque_policy_value(self.policy_version, "policy_version"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceDecisionActor:
    """Machine-readable author kind plus opaque deployment actor identity."""

    kind: EvidenceEligibilityActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_ELIGIBILITY_ACTOR_KINDS:
            raise EvidenceEligibilityValidationError(
                "actor kind must be one of: policy, system, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_EVIDENCE_ELIGIBILITY_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class EvidenceSourceStateObservation:
    """Canonical Core publication lifecycle observed for one decision revision."""

    state: EvidenceSourceLifecycleState
    head_publication_id: str
    successor_publication_id: str | None
    withdrawn_at: datetime | None

    def __post_init__(self) -> None:
        if self.state not in EVIDENCE_SOURCE_LIFECYCLE_STATES:
            raise EvidenceEligibilityValidationError(
                "source lifecycle state is invalid."
            )
        head = _publication_id(self.head_publication_id)
        object.__setattr__(self, "head_publication_id", head)
        successor = self.successor_publication_id
        if successor is not None:
            successor = _publication_id(successor)
        object.__setattr__(self, "successor_publication_id", successor)
        withdrawn_at = self.withdrawn_at
        if withdrawn_at is not None:
            withdrawn_at = _aware_utc_datetime(withdrawn_at, "withdrawn_at")
        object.__setattr__(self, "withdrawn_at", withdrawn_at)

        if self.state == "current":
            if successor is not None or withdrawn_at is not None:
                raise EvidenceEligibilityValidationError(
                    "current source state cannot carry successor or withdrawal."
                )
        elif self.state == "superseded":
            if successor is None or withdrawn_at is not None:
                raise EvidenceEligibilityValidationError(
                    "superseded source state requires successor and no withdrawal."
                )
        elif self.state == "withdrawn":
            if successor is not None or withdrawn_at is None:
                raise EvidenceEligibilityValidationError(
                    "withdrawn source state requires withdrawal and no successor."
                )
        else:
            if successor is None or withdrawn_at is None:
                raise EvidenceEligibilityValidationError(
                    "withdrawn_superseded requires successor and withdrawal."
                )


@dataclass(frozen=True, slots=True)
class EvidenceEligibilityDecision:
    """One immutable contextual eligibility decision over one exact source."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    source: EvidenceSourceReference
    membership_revision: int
    membership_revision_sha256: str
    eligibility_revision: int
    supersedes_revision: int | None
    disposition: EvidenceEligibilityDisposition
    actor: EvidenceDecisionActor
    policy: EvidenceEligibilityPolicyReference | None
    reason_codes: tuple[str, ...]
    rationale: str | None
    source_state: EvidenceSourceStateObservation
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ELIGIBILITY_SCHEMA_VERSION:
            raise EvidenceEligibilityValidationError('schema_version must be "1".')
        if self.record_type != EVIDENCE_ELIGIBILITY_RECORD_TYPE:
            raise EvidenceEligibilityValidationError(
                'record_type must be "meridian_evidence_eligibility_decision".'
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        if not isinstance(self.source, EvidenceSourceReference):
            raise EvidenceEligibilityValidationError(
                "source must be an EvidenceSourceReference."
            )
        source = validate_evidence_source_reference(self.source)
        if source.work.class_id != class_id:
            raise EvidenceEligibilityValidationError(
                "source.work.class_id must match class_id."
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "membership_revision",
            _positive_int(self.membership_revision, "membership_revision"),
        )
        object.__setattr__(
            self,
            "membership_revision_sha256",
            _sha256(
                self.membership_revision_sha256,
                "membership_revision_sha256",
            ),
        )
        revision = _positive_int(self.eligibility_revision, "eligibility_revision")
        object.__setattr__(self, "eligibility_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise EvidenceEligibilityValidationError(
                    "eligibility revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise EvidenceEligibilityValidationError(
                "supersedes_revision must equal eligibility_revision - 1."
            )

        if self.disposition not in EVIDENCE_ELIGIBILITY_DISPOSITIONS:
            raise EvidenceEligibilityValidationError(
                "disposition must be one of: "
                + ", ".join(sorted(EVIDENCE_ELIGIBILITY_DISPOSITIONS))
                + "."
            )
        if not isinstance(self.actor, EvidenceDecisionActor):
            raise EvidenceEligibilityValidationError(
                "actor must be an EvidenceDecisionActor."
            )
        actor = validate_evidence_decision_actor(self.actor)
        object.__setattr__(self, "actor", actor)

        policy = self.policy
        if policy is not None:
            policy = validate_evidence_eligibility_policy_reference(policy)
        object.__setattr__(self, "policy", policy)

        reasons = _reason_codes(self.reason_codes)
        object.__setattr__(self, "reason_codes", reasons)
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_EVIDENCE_ELIGIBILITY_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        if not isinstance(self.source_state, EvidenceSourceStateObservation):
            raise EvidenceEligibilityValidationError(
                "source_state must be an EvidenceSourceStateObservation."
            )
        source_state = validate_evidence_source_state_observation(self.source_state)
        object.__setattr__(self, "source_state", source_state)
        object.__setattr__(
            self,
            "decided_at",
            _aware_utc_datetime(self.decided_at, "decided_at"),
        )
        _validate_disposition_semantics(self)


def validate_evidence_source_reference(
    value: EvidenceSourceReference,
) -> EvidenceSourceReference:
    """Fully revalidate one exact projected evidence source reference."""
    if not isinstance(value, EvidenceSourceReference):
        raise EvidenceEligibilityValidationError(
            "source must be an EvidenceSourceReference."
        )
    return EvidenceSourceReference(
        work=value.work,
        publication_id=value.publication_id,
        cache_key=value.cache_key,
        snapshot_digest=value.snapshot_digest,
        item_id=value.item_id,
    )


def validate_evidence_eligibility_policy_reference(
    value: EvidenceEligibilityPolicyReference,
) -> EvidenceEligibilityPolicyReference:
    """Fully revalidate one policy reference."""
    if not isinstance(value, EvidenceEligibilityPolicyReference):
        raise EvidenceEligibilityValidationError(
            "policy must be an EvidenceEligibilityPolicyReference."
        )
    return EvidenceEligibilityPolicyReference(
        policy_id=value.policy_id,
        policy_version=value.policy_version,
    )


def validate_evidence_decision_actor(
    value: EvidenceDecisionActor,
) -> EvidenceDecisionActor:
    """Fully revalidate one decision actor."""
    if not isinstance(value, EvidenceDecisionActor):
        raise EvidenceEligibilityValidationError(
            "actor must be an EvidenceDecisionActor."
        )
    return EvidenceDecisionActor(kind=value.kind, actor_id=value.actor_id)


def validate_evidence_source_state_observation(
    value: EvidenceSourceStateObservation,
) -> EvidenceSourceStateObservation:
    """Fully revalidate one source-state observation."""
    if not isinstance(value, EvidenceSourceStateObservation):
        raise EvidenceEligibilityValidationError(
            "source state must be an EvidenceSourceStateObservation."
        )
    return EvidenceSourceStateObservation(
        state=value.state,
        head_publication_id=value.head_publication_id,
        successor_publication_id=value.successor_publication_id,
        withdrawn_at=value.withdrawn_at,
    )


def validate_evidence_eligibility_decision(
    value: EvidenceEligibilityDecision,
) -> EvidenceEligibilityDecision:
    """Fully revalidate one eligibility decision."""
    if not isinstance(value, EvidenceEligibilityDecision):
        raise EvidenceEligibilityValidationError(
            "decision must be an EvidenceEligibilityDecision."
        )
    return EvidenceEligibilityDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        source=value.source,
        membership_revision=value.membership_revision,
        membership_revision_sha256=value.membership_revision_sha256,
        eligibility_revision=value.eligibility_revision,
        supersedes_revision=value.supersedes_revision,
        disposition=value.disposition,
        actor=value.actor,
        policy=value.policy,
        reason_codes=value.reason_codes,
        rationale=value.rationale,
        source_state=value.source_state,
        decided_at=value.decided_at,
    )


def validate_evidence_eligibility_transition(
    previous: EvidenceEligibilityDecision,
    candidate: EvidenceEligibilityDecision,
) -> EvidenceEligibilityDecision:
    """Validate a pure contiguous transition in one exact eligibility history."""
    old = validate_evidence_eligibility_decision(previous)
    new = validate_evidence_eligibility_decision(candidate)
    if new.class_id != old.class_id:
        raise EvidenceEligibilityValidationError(
            "candidate class_id must match previous."
        )
    if new.grade_item_id != old.grade_item_id:
        raise EvidenceEligibilityValidationError(
            "candidate grade_item_id must match previous."
        )
    if new.source != old.source:
        raise EvidenceEligibilityValidationError(
            "candidate exact evidence source must match previous."
        )
    if new.eligibility_revision != old.eligibility_revision + 1:
        raise EvidenceEligibilityValidationError(
            "candidate eligibility_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.eligibility_revision:
        raise EvidenceEligibilityValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.decided_at < old.decided_at:
        raise EvidenceEligibilityValidationError(
            "candidate decided_at must not be earlier than previous decided_at."
        )
    return new


def evidence_source_reference_to_dict(
    value: EvidenceSourceReference,
) -> dict[str, object]:
    """Convert an exact source reference to its canonical JSON-native shape."""
    source = validate_evidence_source_reference(value)
    return {
        "work": module_work_ref_to_dict(source.work),
        "publication_id": source.publication_id,
        "cache_key": source.cache_key,
        "snapshot_digest": source.snapshot_digest,
        "item_id": source.item_id,
    }


def evidence_source_reference_from_dict(data: object) -> EvidenceSourceReference:
    """Parse an exact source reference mapping."""
    mapping = _exact_mapping(data, _SOURCE_KEYS, "evidence source reference")
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except RoutingModelError as error:
        raise EvidenceEligibilityValidationError(str(error)) from error
    return EvidenceSourceReference(
        work=work,
        publication_id=_require_str(mapping["publication_id"], "publication_id"),
        cache_key=_require_str(mapping["cache_key"], "cache_key"),
        snapshot_digest=_require_str(mapping["snapshot_digest"], "snapshot_digest"),
        item_id=_require_str(mapping["item_id"], "item_id"),
    )


def evidence_source_reference_to_json_bytes(value: EvidenceSourceReference) -> bytes:
    """Return deterministic canonical bytes used to derive the storage source key."""
    return _canonical_json_bytes(evidence_source_reference_to_dict(value))


def evidence_source_key(value: EvidenceSourceReference) -> str:
    """Return the deterministic SHA-256 path key for one exact source reference."""
    return hashlib.sha256(evidence_source_reference_to_json_bytes(value)).hexdigest()


def evidence_eligibility_policy_reference_to_dict(
    value: EvidenceEligibilityPolicyReference,
) -> dict[str, object]:
    policy = validate_evidence_eligibility_policy_reference(value)
    return {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
    }


def evidence_eligibility_policy_reference_from_dict(
    data: object,
) -> EvidenceEligibilityPolicyReference:
    mapping = _exact_mapping(data, _POLICY_KEYS, "eligibility policy reference")
    return EvidenceEligibilityPolicyReference(
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_version=_require_str(mapping["policy_version"], "policy_version"),
    )


def evidence_decision_actor_to_dict(value: EvidenceDecisionActor) -> dict[str, object]:
    actor = validate_evidence_decision_actor(value)
    return {"kind": actor.kind, "actor_id": actor.actor_id}


def evidence_decision_actor_from_dict(data: object) -> EvidenceDecisionActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "evidence decision actor")
    return EvidenceDecisionActor(
        kind=cast(
            EvidenceEligibilityActorKind,
            _require_str(mapping["kind"], "kind"),
        ),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def evidence_source_state_observation_to_dict(
    value: EvidenceSourceStateObservation,
) -> dict[str, object]:
    state = validate_evidence_source_state_observation(value)
    return {
        "state": state.state,
        "head_publication_id": state.head_publication_id,
        "successor_publication_id": state.successor_publication_id,
        "withdrawn_at": (
            state.withdrawn_at.isoformat() if state.withdrawn_at is not None else None
        ),
    }


def evidence_source_state_observation_from_dict(
    data: object,
) -> EvidenceSourceStateObservation:
    mapping = _exact_mapping(data, _SOURCE_STATE_KEYS, "source state observation")
    successor = mapping["successor_publication_id"]
    if successor is not None:
        successor = _require_str(successor, "successor_publication_id")
    withdrawn = mapping["withdrawn_at"]
    withdrawn_at = (
        None if withdrawn is None else _datetime_from_text(withdrawn, "withdrawn_at")
    )
    return EvidenceSourceStateObservation(
        state=cast(
            EvidenceSourceLifecycleState,
            _require_str(mapping["state"], "state"),
        ),
        head_publication_id=_require_str(
            mapping["head_publication_id"], "head_publication_id"
        ),
        successor_publication_id=successor,
        withdrawn_at=withdrawn_at,
    )


def evidence_eligibility_decision_to_dict(
    value: EvidenceEligibilityDecision,
) -> dict[str, object]:
    """Convert one decision to its exact JSON-native shape."""
    decision = validate_evidence_eligibility_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "source": evidence_source_reference_to_dict(decision.source),
        "membership_revision": decision.membership_revision,
        "membership_revision_sha256": decision.membership_revision_sha256,
        "eligibility_revision": decision.eligibility_revision,
        "supersedes_revision": decision.supersedes_revision,
        "disposition": decision.disposition,
        "actor": evidence_decision_actor_to_dict(decision.actor),
        "policy": (
            evidence_eligibility_policy_reference_to_dict(decision.policy)
            if decision.policy is not None
            else None
        ),
        "reason_codes": list(decision.reason_codes),
        "rationale": decision.rationale,
        "source_state": evidence_source_state_observation_to_dict(
            decision.source_state
        ),
        "decided_at": decision.decided_at.isoformat(),
    }


def evidence_eligibility_decision_from_dict(
    data: object,
) -> EvidenceEligibilityDecision:
    """Parse one exact eligibility decision mapping."""
    mapping = _exact_mapping(data, _DECISION_KEYS, "evidence eligibility decision")
    policy_data = mapping["policy"]
    policy = (
        None
        if policy_data is None
        else evidence_eligibility_policy_reference_from_dict(policy_data)
    )
    reasons = mapping["reason_codes"]
    if not isinstance(reasons, list) or any(
        not isinstance(item, str) for item in reasons
    ):
        raise EvidenceEligibilityValidationError(
            "reason_codes must be a JSON array of strings."
        )
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None:
        supersedes = _positive_int(supersedes, "supersedes_revision")
    rationale = mapping["rationale"]
    if rationale is not None:
        rationale = _require_str(rationale, "rationale")
    return EvidenceEligibilityDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        source=evidence_source_reference_from_dict(mapping["source"]),
        membership_revision=_positive_int(
            mapping["membership_revision"], "membership_revision"
        ),
        membership_revision_sha256=_require_str(
            mapping["membership_revision_sha256"], "membership_revision_sha256"
        ),
        eligibility_revision=_positive_int(
            mapping["eligibility_revision"], "eligibility_revision"
        ),
        supersedes_revision=supersedes,
        disposition=cast(
            EvidenceEligibilityDisposition,
            _require_str(mapping["disposition"], "disposition"),
        ),
        actor=evidence_decision_actor_from_dict(mapping["actor"]),
        policy=policy,
        reason_codes=tuple(cast(list[str], reasons)),
        rationale=rationale,
        source_state=evidence_source_state_observation_from_dict(
            mapping["source_state"]
        ),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def evidence_eligibility_decision_to_json_bytes(
    value: EvidenceEligibilityDecision,
) -> bytes:
    """Serialize one decision to deterministic canonical UTF-8 JSON bytes."""
    return _canonical_json_bytes(evidence_eligibility_decision_to_dict(value))


def evidence_eligibility_decision_from_json_bytes(
    data: bytes,
) -> EvidenceEligibilityDecision:
    """Parse only canonical eligibility decision JSON bytes."""
    if type(data) is not bytes:
        raise EvidenceEligibilitySerializationError("data must be immutable bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceEligibilitySerializationError(
            "eligibility decision JSON must be valid UTF-8."
        ) from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except EvidenceEligibilitySerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise EvidenceEligibilitySerializationError(
            "eligibility decision bytes must contain valid JSON."
        ) from error
    try:
        decision = evidence_eligibility_decision_from_dict(decoded)
    except EvidenceEligibilityValidationError as error:
        raise EvidenceEligibilitySerializationError(str(error)) from error
    canonical = evidence_eligibility_decision_to_json_bytes(decision)
    if canonical != data:
        raise EvidenceEligibilitySerializationError(
            "eligibility decision JSON is valid but not canonically encoded."
        )
    return decision


def _validate_disposition_semantics(decision: EvidenceEligibilityDecision) -> None:
    disposition = decision.disposition
    actor_kind = decision.actor.kind
    policy = decision.policy
    reasons = decision.reason_codes
    source_state = decision.source_state.state

    if disposition in {"included", "excluded", "pending"}:
        if actor_kind not in {"teacher", "policy"}:
            raise EvidenceEligibilityValidationError(
                f"{disposition} eligibility requires teacher or policy authority."
            )
        if policy is None:
            raise EvidenceEligibilityValidationError(
                f"{disposition} eligibility requires an exact policy reference."
            )
    elif disposition == "unsupported":
        if policy is None:
            raise EvidenceEligibilityValidationError(
                "unsupported eligibility requires an exact policy/support reference."
            )
    else:
        if actor_kind != "system":
            raise EvidenceEligibilityValidationError(
                f"{disposition} source state requires system authority."
            )
        if policy is not None:
            raise EvidenceEligibilityValidationError(
                f"{disposition} source lifecycle must not claim policy causation."
            )

    if disposition == "included":
        if reasons:
            raise EvidenceEligibilityValidationError(
                "included eligibility must not carry exclusion reason codes."
            )
        if source_state in {"withdrawn", "withdrawn_superseded"}:
            raise EvidenceEligibilityValidationError(
                "included eligibility cannot be authored against withdrawn "
                "source state."
            )
    else:
        if not reasons:
            raise EvidenceEligibilityValidationError(
                f"{disposition} eligibility requires at least one reason code."
            )

    if disposition in {"excluded", "pending", "unsupported"} and source_state in {
        "withdrawn",
        "withdrawn_superseded",
    }:
        raise EvidenceEligibilityValidationError(
            "academic eligibility dispositions must not replace observed withdrawal."
        )
    if disposition == "superseded" and source_state != "superseded":
        raise EvidenceEligibilityValidationError(
            "superseded disposition requires superseded source state."
        )
    if disposition == "withdrawn" and source_state not in {
        "withdrawn",
        "withdrawn_superseded",
    }:
        raise EvidenceEligibilityValidationError(
            "withdrawn disposition requires withdrawn source state."
        )


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise EvidenceEligibilitySerializationError(
            "eligibility data cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceEligibilitySerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise EvidenceEligibilitySerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    expected: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise EvidenceEligibilityValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise EvidenceEligibilityValidationError(
            f"{label} keys must all be strings."
        )
    keys = frozenset(cast(Mapping[str, object], data))
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing!r}")
        if unknown:
            details.append(f"unknown={unknown!r}")
        raise EvidenceEligibilityValidationError(
            f"{label} must use the exact schema ({', '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceEligibilityValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise EvidenceEligibilityValidationError(str(error)) from error


def _publication_id(value: object) -> str:
    if not isinstance(value, str) or _PUBLICATION_ID.fullmatch(value) is None:
        raise EvidenceEligibilityValidationError(
            "publication_id must use pub_<32 lowercase hexadecimal characters>."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _opaque_policy_value(value: object, field_name: str) -> str:
    text = _bounded_text(
        value,
        field_name,
        MAXIMUM_EVIDENCE_ELIGIBILITY_POLICY_VALUE_LENGTH,
    )
    if _OPAQUE_POLICY_VALUE.fullmatch(text) is None:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be an opaque identifier without path separators."
        )
    return text


def _reason_codes(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise EvidenceEligibilityValidationError(
            "reason_codes must be an iterable of strings."
        )
    try:
        raw = tuple(cast(tuple[object, ...], value))
    except TypeError as error:
        raise EvidenceEligibilityValidationError(
            "reason_codes must be iterable."
        ) from error
    reasons: list[str] = []
    for item in raw:
        if not isinstance(item, str) or _REASON_CODE.fullmatch(item) is None:
            raise EvidenceEligibilityValidationError(
                "reason_codes must contain lowercase contract-safe identifiers."
            )
        if len(item) > MAXIMUM_EVIDENCE_ELIGIBILITY_REASON_CODE_LENGTH:
            raise EvidenceEligibilityValidationError(
                "reason code exceeds the maximum length."
            )
        reasons.append(item)
    if len(set(reasons)) != len(reasons):
        raise EvidenceEligibilityValidationError(
            "reason_codes must not contain duplicates."
        )
    return tuple(reasons)


def _bounded_text(value: object, field_name: str, maximum_length: int) -> str:
    if not isinstance(value, str):
        raise EvidenceEligibilityValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum_length:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be at most {maximum_length} characters."
        )
    if any(_is_control_character(character) for character in value):
        raise EvidenceEligibilityValidationError(
            f"{field_name} must not contain control characters."
        )
    return value


def _is_control_character(value: str) -> bool:
    return unicodedata.category(value).startswith("C") or value in {"\u2028", "\u2029"}


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise EvidenceEligibilityValidationError(
            f"{field_name} must be an ISO-8601 datetime."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise EvidenceEligibilityValidationError(f"{field_name} must be a string.")
    return value
