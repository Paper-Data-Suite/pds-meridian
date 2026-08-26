"""Immutable reassessment and replacement policy/decision models."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routing_models import (
    ModuleWorkRef,
    RoutingModelError,
    module_work_ref_from_dict,
    module_work_ref_to_dict,
    validate_module_work_ref,
)

from meridian.attempt_selection import (
    AttemptObservationReference,
    AttemptSelectionValidationError,
    attempt_observation_reference_from_dict,
    attempt_observation_reference_to_dict,
    attempt_subject_key,
    validate_attempt_observation_reference,
)

REASSESSMENT_POLICY_SCHEMA_VERSION: Final[str] = "1"
REASSESSMENT_POLICY_RECORD_TYPE: Final[str] = "meridian_reassessment_policy"
REASSESSMENT_DECISION_SCHEMA_VERSION: Final[str] = "1"
REASSESSMENT_DECISION_RECORD_TYPE: Final[str] = "meridian_reassessment_decision"
REASSESSMENT_RELATIONSHIP_BASIS: Final[str] = "explicit"
MAXIMUM_REASSESSMENT_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_REASSESSMENT_RATIONALE_LENGTH: Final[int] = 2000

ReassessmentActorKind: TypeAlias = Literal["teacher", "policy"]
ReassessmentRelationshipBasis: TypeAlias = Literal["explicit"]
ReassessmentMode: TypeAlias = Literal["retain", "replace", "combine", "recency"]

_MODE_ORDER: Final[tuple[ReassessmentMode, ...]] = (
    "retain",
    "replace",
    "combine",
    "recency",
)
_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "work",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "relationship_basis",
        "allowed_modes",
        "actor",
        "rationale",
        "revised_at",
    }
)
_DECISION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "work",
        "student_id",
        "attempt_selection",
        "policy",
        "mode",
        "contributing_attempts",
        "replacement_relationships",
        "combinations",
        "recency_order",
        "decision_revision",
        "supersedes_revision",
        "actor",
        "rationale",
        "decided_at",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_ATTEMPT_SELECTION_REF_KEYS: Final[frozenset[str]] = frozenset(
    {"decision_revision", "decision_sha256"}
)
_POLICY_REF_KEYS: Final[frozenset[str]] = frozenset(
    {"policy_id", "policy_revision", "policy_revision_sha256"}
)
_REPLACEMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"replacement_attempt", "replaced_attempts"}
)
_COMBINATION_KEYS: Final[frozenset[str]] = frozenset({"combination_id", "members"})

_T = TypeVar("_T")


class ReassessmentError(ValueError):
    """Base error for reassessment models."""


class ReassessmentValidationError(ReassessmentError):
    """Raised when reassessment data violates the contract."""


class ReassessmentSerializationError(ReassessmentError):
    """Raised when reassessment JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class ReassessmentActor:
    """Explicit authorship for reassessment policy and decision state."""

    kind: ReassessmentActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"teacher", "policy"}:
            raise ReassessmentValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_REASSESSMENT_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class AttemptSelectionDecisionReference:
    """Exact immutable #30 decision revision interpreted by #31."""

    decision_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_revision",
            _positive_int(self.decision_revision, "decision_revision"),
        )
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReassessmentPolicyReference:
    """Exact immutable reassessment policy revision and digest."""

    policy_id: str
    policy_revision: int
    policy_revision_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self,
            "policy_revision",
            _positive_int(self.policy_revision, "policy_revision"),
        )
        object.__setattr__(
            self,
            "policy_revision_sha256",
            _sha256(self.policy_revision_sha256, "policy_revision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ReplacementRelationship:
    """One explicit directed academic replacement relationship."""

    replacement_attempt: AttemptObservationReference
    replaced_attempts: tuple[AttemptObservationReference, ...]

    def __post_init__(self) -> None:
        replacement = _attempt(self.replacement_attempt, "replacement_attempt")
        replaced = _attempt_tuple(self.replaced_attempts, "replaced_attempts")
        if not replaced:
            raise ReassessmentValidationError(
                "replacement relationship requires at least one replaced attempt."
            )
        if len(set(replaced)) != len(replaced):
            raise ReassessmentValidationError(
                "replaced_attempts must not contain duplicates."
            )
        if replacement in replaced:
            raise ReassessmentValidationError("an attempt cannot replace itself.")
        object.__setattr__(self, "replacement_attempt", replacement)
        object.__setattr__(self, "replaced_attempts", replaced)


@dataclass(frozen=True, slots=True)
class ReassessmentCombination:
    """One explicit semantic combination group without numeric reduction."""

    combination_id: str
    members: tuple[AttemptObservationReference, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "combination_id",
            _identifier(self.combination_id, "combination_id"),
        )
        members = _attempt_tuple(self.members, "members")
        if len(members) < 2:
            raise ReassessmentValidationError(
                "combination requires at least two attempt members."
            )
        if len(set(members)) != len(members):
            raise ReassessmentValidationError(
                "combination members must not contain duplicates."
            )
        object.__setattr__(self, "members", members)


@dataclass(frozen=True, slots=True)
class ReassessmentPolicy:
    """One immutable explicit reassessment policy revision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    relationship_basis: ReassessmentRelationshipBasis
    allowed_modes: tuple[ReassessmentMode, ...]
    actor: ReassessmentActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REASSESSMENT_POLICY_SCHEMA_VERSION:
            raise ReassessmentValidationError('policy schema_version must be "1".')
        if self.record_type != REASSESSMENT_POLICY_RECORD_TYPE:
            raise ReassessmentValidationError(
                'policy record_type must be "meridian_reassessment_policy".'
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        work = _work(self.work)
        if work.class_id != class_id:
            raise ReassessmentValidationError("work.class_id must match class_id.")
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        revision = _positive_int(self.policy_revision, "policy_revision")
        object.__setattr__(self, "policy_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise ReassessmentValidationError(
                    "policy revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise ReassessmentValidationError(
                "policy supersedes_revision must equal policy_revision - 1."
            )
        if self.relationship_basis != REASSESSMENT_RELATIONSHIP_BASIS:
            raise ReassessmentValidationError(
                'relationship_basis must be exactly "explicit".'
            )
        modes = _mode_tuple(self.allowed_modes)
        if not modes:
            raise ReassessmentValidationError("allowed_modes must not be empty.")
        object.__setattr__(self, "allowed_modes", modes)
        if not isinstance(self.actor, ReassessmentActor):
            raise ReassessmentValidationError(
                "actor must be a ReassessmentActor."
            )
        object.__setattr__(self, "actor", validate_reassessment_actor(self.actor))
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_REASSESSMENT_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self,
            "revised_at",
            _aware_utc_datetime(self.revised_at, "revised_at"),
        )


@dataclass(frozen=True, slots=True)
class ReassessmentDecision:
    """One immutable student-scoped reassessment relationship decision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    student_id: str
    attempt_selection: AttemptSelectionDecisionReference
    policy: ReassessmentPolicyReference
    mode: ReassessmentMode
    contributing_attempts: tuple[AttemptObservationReference, ...]
    replacement_relationships: tuple[ReplacementRelationship, ...]
    combinations: tuple[ReassessmentCombination, ...]
    recency_order: tuple[AttemptObservationReference, ...]
    decision_revision: int
    supersedes_revision: int | None
    actor: ReassessmentActor
    rationale: str | None
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != REASSESSMENT_DECISION_SCHEMA_VERSION:
            raise ReassessmentValidationError('decision schema_version must be "1".')
        if self.record_type != REASSESSMENT_DECISION_RECORD_TYPE:
            raise ReassessmentValidationError(
                'decision record_type must be "meridian_reassessment_decision".'
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        work = _work(self.work)
        if work.class_id != class_id:
            raise ReassessmentValidationError("work.class_id must match class_id.")
        object.__setattr__(self, "work", work)
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        if not isinstance(
            self.attempt_selection, AttemptSelectionDecisionReference
        ):
            raise ReassessmentValidationError(
                "attempt_selection must be an AttemptSelectionDecisionReference."
            )
        object.__setattr__(
            self,
            "attempt_selection",
            validate_attempt_selection_decision_reference(self.attempt_selection),
        )
        if not isinstance(self.policy, ReassessmentPolicyReference):
            raise ReassessmentValidationError(
                "policy must be a ReassessmentPolicyReference."
            )
        object.__setattr__(
            self, "policy", validate_reassessment_policy_reference(self.policy)
        )
        if self.mode not in set(_MODE_ORDER):
            raise ReassessmentValidationError(
                "mode must be one of: combine, recency, replace, retain."
            )
        contributing = _attempt_tuple(
            self.contributing_attempts, "contributing_attempts"
        )
        if not contributing:
            raise ReassessmentValidationError(
                "reassessment decision requires at least one contributing attempt."
            )
        if len(set(contributing)) != len(contributing):
            raise ReassessmentValidationError(
                "contributing_attempts must not contain duplicates."
            )
        object.__setattr__(self, "contributing_attempts", contributing)
        replacements = _typed_tuple(
            self.replacement_relationships,
            ReplacementRelationship,
            "replacement_relationships",
        )
        replacements = tuple(
            validate_replacement_relationship(value) for value in replacements
        )
        object.__setattr__(self, "replacement_relationships", replacements)
        combinations = _typed_tuple(
            self.combinations, ReassessmentCombination, "combinations"
        )
        combinations = tuple(
            validate_reassessment_combination(value) for value in combinations
        )
        object.__setattr__(self, "combinations", combinations)
        recency = _attempt_tuple(self.recency_order, "recency_order")
        if len(set(recency)) != len(recency):
            raise ReassessmentValidationError(
                "recency_order must not contain duplicates."
            )
        object.__setattr__(self, "recency_order", recency)
        _validate_mode_shape(
            self.mode,
            contributing,
            replacements,
            combinations,
            recency,
        )
        revision = _positive_int(self.decision_revision, "decision_revision")
        object.__setattr__(self, "decision_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise ReassessmentValidationError(
                    "decision revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise ReassessmentValidationError(
                "decision supersedes_revision must equal decision_revision - 1."
            )
        if not isinstance(self.actor, ReassessmentActor):
            raise ReassessmentValidationError(
                "actor must be a ReassessmentActor."
            )
        object.__setattr__(self, "actor", validate_reassessment_actor(self.actor))
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_REASSESSMENT_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self,
            "decided_at",
            _aware_utc_datetime(self.decided_at, "decided_at"),
        )


def validate_reassessment_actor(value: ReassessmentActor) -> ReassessmentActor:
    if not isinstance(value, ReassessmentActor):
        raise ReassessmentValidationError("value must be a ReassessmentActor.")
    return ReassessmentActor(kind=value.kind, actor_id=value.actor_id)


def validate_attempt_selection_decision_reference(
    value: AttemptSelectionDecisionReference,
) -> AttemptSelectionDecisionReference:
    if not isinstance(value, AttemptSelectionDecisionReference):
        raise ReassessmentValidationError(
            "value must be an AttemptSelectionDecisionReference."
        )
    return AttemptSelectionDecisionReference(
        decision_revision=value.decision_revision,
        decision_sha256=value.decision_sha256,
    )


def validate_reassessment_policy_reference(
    value: ReassessmentPolicyReference,
) -> ReassessmentPolicyReference:
    if not isinstance(value, ReassessmentPolicyReference):
        raise ReassessmentValidationError(
            "value must be a ReassessmentPolicyReference."
        )
    return ReassessmentPolicyReference(
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        policy_revision_sha256=value.policy_revision_sha256,
    )


def validate_replacement_relationship(
    value: ReplacementRelationship,
) -> ReplacementRelationship:
    if not isinstance(value, ReplacementRelationship):
        raise ReassessmentValidationError(
            "value must be a ReplacementRelationship."
        )
    return ReplacementRelationship(
        replacement_attempt=value.replacement_attempt,
        replaced_attempts=value.replaced_attempts,
    )


def validate_reassessment_combination(
    value: ReassessmentCombination,
) -> ReassessmentCombination:
    if not isinstance(value, ReassessmentCombination):
        raise ReassessmentValidationError(
            "value must be a ReassessmentCombination."
        )
    return ReassessmentCombination(
        combination_id=value.combination_id,
        members=value.members,
    )


def validate_reassessment_policy(value: ReassessmentPolicy) -> ReassessmentPolicy:
    if not isinstance(value, ReassessmentPolicy):
        raise ReassessmentValidationError("value must be a ReassessmentPolicy.")
    return ReassessmentPolicy(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        work=value.work,
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        supersedes_revision=value.supersedes_revision,
        relationship_basis=value.relationship_basis,
        allowed_modes=value.allowed_modes,
        actor=value.actor,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def validate_reassessment_decision(
    value: ReassessmentDecision,
) -> ReassessmentDecision:
    if not isinstance(value, ReassessmentDecision):
        raise ReassessmentValidationError("value must be a ReassessmentDecision.")
    return ReassessmentDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        work=value.work,
        student_id=value.student_id,
        attempt_selection=value.attempt_selection,
        policy=value.policy,
        mode=value.mode,
        contributing_attempts=value.contributing_attempts,
        replacement_relationships=value.replacement_relationships,
        combinations=value.combinations,
        recency_order=value.recency_order,
        decision_revision=value.decision_revision,
        supersedes_revision=value.supersedes_revision,
        actor=value.actor,
        rationale=value.rationale,
        decided_at=value.decided_at,
    )


def validate_reassessment_policy_transition(
    previous: ReassessmentPolicy,
    candidate: ReassessmentPolicy,
) -> ReassessmentPolicy:
    old = validate_reassessment_policy(previous)
    new = validate_reassessment_policy(candidate)
    if (
        new.class_id != old.class_id
        or new.grade_item_id != old.grade_item_id
        or new.work != old.work
        or new.policy_id != old.policy_id
    ):
        raise ReassessmentValidationError(
            "candidate policy logical identity must match previous."
        )
    if new.policy_revision != old.policy_revision + 1:
        raise ReassessmentValidationError(
            "candidate policy_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.policy_revision:
        raise ReassessmentValidationError(
            "candidate policy supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise ReassessmentValidationError(
            "candidate revised_at must not be earlier than previous revised_at."
        )
    return new


def validate_reassessment_decision_transition(
    previous: ReassessmentDecision,
    candidate: ReassessmentDecision,
) -> ReassessmentDecision:
    old = validate_reassessment_decision(previous)
    new = validate_reassessment_decision(candidate)
    if (
        new.class_id != old.class_id
        or new.grade_item_id != old.grade_item_id
        or new.work != old.work
        or new.student_id != old.student_id
    ):
        raise ReassessmentValidationError(
            "candidate decision logical identity must match previous."
        )
    if new.decision_revision != old.decision_revision + 1:
        raise ReassessmentValidationError(
            "candidate decision_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.decision_revision:
        raise ReassessmentValidationError(
            "candidate decision supersedes_revision must identify previous revision."
        )
    if new.decided_at < old.decided_at:
        raise ReassessmentValidationError(
            "candidate decided_at must not be earlier than previous decided_at."
        )
    return new


def reassessment_actor_to_dict(value: ReassessmentActor) -> dict[str, object]:
    actor = validate_reassessment_actor(value)
    return {"kind": actor.kind, "actor_id": actor.actor_id}


def reassessment_actor_from_dict(data: object) -> ReassessmentActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "reassessment actor")
    return ReassessmentActor(
        kind=_reassessment_actor_kind(mapping["kind"]),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def attempt_selection_decision_reference_to_dict(
    value: AttemptSelectionDecisionReference,
) -> dict[str, object]:
    ref = validate_attempt_selection_decision_reference(value)
    return {
        "decision_revision": ref.decision_revision,
        "decision_sha256": ref.decision_sha256,
    }


def attempt_selection_decision_reference_from_dict(
    data: object,
) -> AttemptSelectionDecisionReference:
    mapping = _exact_mapping(
        data, _ATTEMPT_SELECTION_REF_KEYS, "attempt-selection decision reference"
    )
    return AttemptSelectionDecisionReference(
        decision_revision=_positive_int(
            mapping["decision_revision"], "decision_revision"
        ),
        decision_sha256=_require_str(
            mapping["decision_sha256"], "decision_sha256"
        ),
    )


def reassessment_policy_reference_to_dict(
    value: ReassessmentPolicyReference,
) -> dict[str, object]:
    ref = validate_reassessment_policy_reference(value)
    return {
        "policy_id": ref.policy_id,
        "policy_revision": ref.policy_revision,
        "policy_revision_sha256": ref.policy_revision_sha256,
    }


def reassessment_policy_reference_from_dict(
    data: object,
) -> ReassessmentPolicyReference:
    mapping = _exact_mapping(data, _POLICY_REF_KEYS, "reassessment policy reference")
    return ReassessmentPolicyReference(
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_positive_int(mapping["policy_revision"], "policy_revision"),
        policy_revision_sha256=_require_str(
            mapping["policy_revision_sha256"], "policy_revision_sha256"
        ),
    )


def replacement_relationship_to_dict(
    value: ReplacementRelationship,
) -> dict[str, object]:
    relationship = validate_replacement_relationship(value)
    return {
        "replacement_attempt": attempt_observation_reference_to_dict(
            relationship.replacement_attempt
        ),
        "replaced_attempts": [
            attempt_observation_reference_to_dict(attempt)
            for attempt in relationship.replaced_attempts
        ],
    }


def replacement_relationship_from_dict(data: object) -> ReplacementRelationship:
    mapping = _exact_mapping(data, _REPLACEMENT_KEYS, "replacement relationship")
    return ReplacementRelationship(
        replacement_attempt=attempt_observation_reference_from_dict(
            mapping["replacement_attempt"]
        ),
        replaced_attempts=tuple(
            attempt_observation_reference_from_dict(value)
            for value in _require_list(
                mapping["replaced_attempts"], "replaced_attempts"
            )
        ),
    )


def reassessment_combination_to_dict(
    value: ReassessmentCombination,
) -> dict[str, object]:
    combination = validate_reassessment_combination(value)
    return {
        "combination_id": combination.combination_id,
        "members": [
            attempt_observation_reference_to_dict(attempt)
            for attempt in combination.members
        ],
    }


def reassessment_combination_from_dict(data: object) -> ReassessmentCombination:
    mapping = _exact_mapping(data, _COMBINATION_KEYS, "reassessment combination")
    return ReassessmentCombination(
        combination_id=_require_str(mapping["combination_id"], "combination_id"),
        members=tuple(
            attempt_observation_reference_from_dict(value)
            for value in _require_list(mapping["members"], "members")
        ),
    )


def reassessment_policy_to_dict(value: ReassessmentPolicy) -> dict[str, object]:
    policy = validate_reassessment_policy(value)
    return {
        "schema_version": policy.schema_version,
        "record_type": policy.record_type,
        "class_id": policy.class_id,
        "grade_item_id": policy.grade_item_id,
        "work": module_work_ref_to_dict(policy.work),
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "relationship_basis": policy.relationship_basis,
        "allowed_modes": list(policy.allowed_modes),
        "actor": reassessment_actor_to_dict(policy.actor),
        "rationale": policy.rationale,
        "revised_at": _datetime_to_text(policy.revised_at),
    }


def reassessment_policy_from_dict(data: object) -> ReassessmentPolicy:
    mapping = _exact_mapping(data, _POLICY_KEYS, "reassessment policy")
    return ReassessmentPolicy(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        work=_work_from_dict(mapping["work"]),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_positive_int(mapping["policy_revision"], "policy_revision"),
        supersedes_revision=_optional_positive_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        relationship_basis=_relationship_basis(mapping["relationship_basis"]),
        allowed_modes=tuple(
            _mode(value)
            for value in _require_list(mapping["allowed_modes"], "allowed_modes")
        ),
        actor=reassessment_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def reassessment_decision_to_dict(value: ReassessmentDecision) -> dict[str, object]:
    decision = validate_reassessment_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "work": module_work_ref_to_dict(decision.work),
        "student_id": decision.student_id,
        "attempt_selection": attempt_selection_decision_reference_to_dict(
            decision.attempt_selection
        ),
        "policy": reassessment_policy_reference_to_dict(decision.policy),
        "mode": decision.mode,
        "contributing_attempts": [
            attempt_observation_reference_to_dict(attempt)
            for attempt in decision.contributing_attempts
        ],
        "replacement_relationships": [
            replacement_relationship_to_dict(value)
            for value in decision.replacement_relationships
        ],
        "combinations": [
            reassessment_combination_to_dict(value) for value in decision.combinations
        ],
        "recency_order": [
            attempt_observation_reference_to_dict(attempt)
            for attempt in decision.recency_order
        ],
        "decision_revision": decision.decision_revision,
        "supersedes_revision": decision.supersedes_revision,
        "actor": reassessment_actor_to_dict(decision.actor),
        "rationale": decision.rationale,
        "decided_at": _datetime_to_text(decision.decided_at),
    }


def reassessment_decision_from_dict(data: object) -> ReassessmentDecision:
    mapping = _exact_mapping(data, _DECISION_KEYS, "reassessment decision")
    return ReassessmentDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        work=_work_from_dict(mapping["work"]),
        student_id=_require_str(mapping["student_id"], "student_id"),
        attempt_selection=attempt_selection_decision_reference_from_dict(
            mapping["attempt_selection"]
        ),
        policy=reassessment_policy_reference_from_dict(mapping["policy"]),
        mode=_mode(mapping["mode"]),
        contributing_attempts=tuple(
            attempt_observation_reference_from_dict(value)
            for value in _require_list(
                mapping["contributing_attempts"], "contributing_attempts"
            )
        ),
        replacement_relationships=tuple(
            replacement_relationship_from_dict(value)
            for value in _require_list(
                mapping["replacement_relationships"], "replacement_relationships"
            )
        ),
        combinations=tuple(
            reassessment_combination_from_dict(value)
            for value in _require_list(mapping["combinations"], "combinations")
        ),
        recency_order=tuple(
            attempt_observation_reference_from_dict(value)
            for value in _require_list(mapping["recency_order"], "recency_order")
        ),
        decision_revision=_positive_int(
            mapping["decision_revision"], "decision_revision"
        ),
        supersedes_revision=_optional_positive_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        actor=reassessment_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def reassessment_policy_to_json_bytes(value: ReassessmentPolicy) -> bytes:
    return _canonical_json_bytes(reassessment_policy_to_dict(value))


def reassessment_policy_from_json_bytes(data: bytes) -> ReassessmentPolicy:
    decoded = _decode_json(data, "reassessment policy")
    policy = reassessment_policy_from_dict(decoded)
    if reassessment_policy_to_json_bytes(policy) != data:
        raise ReassessmentSerializationError(
            "reassessment policy bytes are not canonically encoded."
        )
    return policy


def reassessment_decision_to_json_bytes(value: ReassessmentDecision) -> bytes:
    return _canonical_json_bytes(reassessment_decision_to_dict(value))


def reassessment_decision_from_json_bytes(data: bytes) -> ReassessmentDecision:
    decoded = _decode_json(data, "reassessment decision")
    decision = reassessment_decision_from_dict(decoded)
    if reassessment_decision_to_json_bytes(decision) != data:
        raise ReassessmentSerializationError(
            "reassessment decision bytes are not canonically encoded."
        )
    return decision


def reassessment_subject_key(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> str:
    """Reuse #30's deterministic student path-key contract."""

    return attempt_subject_key(class_id, grade_item_id, work, student_id)


def _validate_mode_shape(
    mode: ReassessmentMode,
    contributing: tuple[AttemptObservationReference, ...],
    replacements: tuple[ReplacementRelationship, ...],
    combinations: tuple[ReassessmentCombination, ...],
    recency: tuple[AttemptObservationReference, ...],
) -> None:
    if mode == "retain":
        if replacements or combinations or recency:
            raise ReassessmentValidationError(
                "retain mode must not include replacement, combination, or "
                "recency relationships."
            )
        return
    if mode == "replace":
        if not replacements or combinations or recency:
            raise ReassessmentValidationError(
                "replace mode requires replacement_relationships only."
            )
        replacement_attempts = tuple(
            relationship.replacement_attempt for relationship in replacements
        )
        if len(set(replacement_attempts)) != len(replacement_attempts):
            raise ReassessmentValidationError(
                "replacement attempts must not be duplicated across relationships."
            )
        replaced_attempts = tuple(
            attempt
            for relationship in replacements
            for attempt in relationship.replaced_attempts
        )
        if len(set(replaced_attempts)) != len(replaced_attempts):
            raise ReassessmentValidationError(
                "a replaced attempt may have only one replacement in v1."
            )
        replaced_set = set(replaced_attempts)
        if any(attempt in replaced_set for attempt in replacement_attempts):
            raise ReassessmentValidationError(
                "replacement chains and cycles are not permitted in v1."
            )
        contributors = set(contributing)
        if any(attempt not in contributors for attempt in replacement_attempts):
            raise ReassessmentValidationError(
                "every replacement attempt must remain contributing."
            )
        if any(attempt in contributors for attempt in replaced_attempts):
            raise ReassessmentValidationError(
                "replaced attempts must not remain contributing."
            )
        return
    if mode == "combine":
        if replacements or not combinations or recency:
            raise ReassessmentValidationError(
                "combine mode requires combinations only."
            )
        ids = tuple(value.combination_id for value in combinations)
        if len(set(ids)) != len(ids):
            raise ReassessmentValidationError(
                "combination IDs must not be duplicated."
            )
        members = tuple(attempt for value in combinations for attempt in value.members)
        if len(set(members)) != len(members):
            raise ReassessmentValidationError(
                "combination groups must not overlap in v1."
            )
        contributors = set(contributing)
        if any(attempt not in contributors for attempt in members):
            raise ReassessmentValidationError(
                "combination members must remain contributing."
            )
        return
    if replacements or combinations:
        raise ReassessmentValidationError(
            "recency mode must not include replacement or combination relationships."
        )
    if len(recency) < 2:
        raise ReassessmentValidationError(
            "recency mode requires at least two explicitly ordered attempts."
        )
    if len(contributing) >= len(recency):
        raise ReassessmentValidationError(
            "recency mode must narrow the explicit order; use retain to keep all."
        )
    if tuple(recency[-len(contributing) :]) != contributing:
        raise ReassessmentValidationError(
            "recency contributing_attempts must be a contiguous most-recent suffix."
        )


def _attempt(value: object, field_name: str) -> AttemptObservationReference:
    if not isinstance(value, AttemptObservationReference):
        raise ReassessmentValidationError(
            f"{field_name} must be an AttemptObservationReference."
        )
    try:
        return validate_attempt_observation_reference(value)
    except AttemptSelectionValidationError as error:
        raise ReassessmentValidationError(str(error)) from error


def _attempt_tuple(
    values: object,
    field_name: str,
) -> tuple[AttemptObservationReference, ...]:
    typed = _typed_tuple(values, AttemptObservationReference, field_name)
    return tuple(_attempt(value, field_name) for value in typed)


def _mode_tuple(values: object) -> tuple[ReassessmentMode, ...]:
    if isinstance(values, (str, bytes)):
        raise ReassessmentValidationError(
            "allowed_modes must be an iterable of reassessment modes."
        )
    try:
        raw = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise ReassessmentValidationError(
            "allowed_modes must be an iterable of reassessment modes."
        ) from error
    modes = tuple(_mode(value) for value in raw)
    if len(set(modes)) != len(modes):
        raise ReassessmentValidationError("allowed_modes must not contain duplicates.")
    selected = set(modes)
    return tuple(mode for mode in _MODE_ORDER if mode in selected)


def _reassessment_actor_kind(value: object) -> ReassessmentActorKind:
    if value not in {"teacher", "policy"}:
        raise ReassessmentValidationError(
            "actor kind must be one of: policy, teacher."
        )
    return value


def _relationship_basis(value: object) -> ReassessmentRelationshipBasis:
    if value != REASSESSMENT_RELATIONSHIP_BASIS:
        raise ReassessmentValidationError(
            'relationship_basis must be exactly "explicit".'
        )
    return "explicit"


def _mode(value: object) -> ReassessmentMode:
    if value not in set(_MODE_ORDER):
        raise ReassessmentValidationError(
            "reassessment mode must be one of: combine, recency, replace, retain."
        )
    return value


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise ReassessmentValidationError("work must be a Core ModuleWorkRef.")
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise ReassessmentValidationError(str(error)) from error


def _work_from_dict(value: object) -> ModuleWorkRef:
    try:
        return module_work_ref_from_dict(value)
    except (RoutingModelError, TypeError, ValueError) as error:
        raise ReassessmentValidationError(f"work is invalid: {error}") from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReassessmentValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReassessmentValidationError(str(error)) from error


def _sha256(value: object, field_name: str) -> str:
    text = _require_str(value, field_name)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ReassessmentValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return text


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ReassessmentValidationError(f"{field_name} must be a positive integer.")
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    text = _require_str(value, field_name)
    if not text or len(text) > maximum:
        raise ReassessmentValidationError(
            f"{field_name} must contain 1..{maximum} characters."
        )
    if any(ord(ch) < 32 and ch not in "\t\n" for ch in text):
        raise ReassessmentValidationError(
            f"{field_name} contains disallowed control characters."
        )
    return text


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReassessmentValidationError(
            f"{field_name} must be timezone-aware datetime."
        )
    return value.astimezone(UTC)


def _datetime_to_text(value: datetime) -> str:
    canonical = _aware_utc_datetime(value, "timestamp")
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    if not text.endswith("Z"):
        raise ReassessmentValidationError(f"{field_name} must use canonical UTC Z.")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise ReassessmentValidationError(f"{field_name} is invalid.") from error
    canonical = _datetime_to_text(parsed)
    if canonical != text:
        raise ReassessmentValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    return parsed.astimezone(UTC)


def _typed_tuple(
    values: object, item_type: type[_T], field_name: str
) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes)):
        raise ReassessmentValidationError(f"{field_name} must be an iterable.")
    try:
        result = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise ReassessmentValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(value, item_type) for value in result):
        raise ReassessmentValidationError(
            f"{field_name} contains an invalid item type."
        )
    return cast(tuple[_T, ...], result)


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReassessmentSerializationError(f"{label} must be a JSON object.")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise ReassessmentSerializationError(
            f"{label} does not use exact schema ({', '.join(details)})."
        )
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReassessmentValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ReassessmentSerializationError(f"{field_name} must be a JSON array.")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ReassessmentSerializationError(
            "reassessment state cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReassessmentSerializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReassessmentSerializationError(f"non-finite JSON value is invalid: {value}")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ReassessmentSerializationError(f"{label} input must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReassessmentSerializationError(f"{label} must be UTF-8.") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReassessmentSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ReassessmentSerializationError(f"{label} JSON is invalid.") from error
