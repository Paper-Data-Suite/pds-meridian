"""Immutable canonical attempt-selection policy and decision models."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
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

from meridian.evidence_eligibility import (
    EvidenceEligibilityValidationError,
    EvidenceSourceReference,
    evidence_source_reference_from_dict,
    evidence_source_reference_to_dict,
    validate_evidence_source_reference,
)

ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION: Final[str] = "1"
ATTEMPT_SELECTION_POLICY_RECORD_TYPE: Final[str] = "meridian_attempt_selection_policy"
ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION: Final[str] = "1"
ATTEMPT_SELECTION_DECISION_RECORD_TYPE: Final[str] = (
    "meridian_attempt_selection_decision"
)
ATTEMPT_SELECTION_BASIS: Final[str] = "explicit"
MAXIMUM_ATTEMPT_SELECTION_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_ATTEMPT_SELECTION_RATIONALE_LENGTH: Final[int] = 2000
MAXIMUM_ATTEMPT_SELECTION_NATIVE_TEXT_LENGTH: Final[int] = 1024

_T = TypeVar("_T")

AttemptSelectionActorKind: TypeAlias = Literal["teacher", "policy"]
AttemptSelectionBasis: TypeAlias = Literal["explicit"]
AttemptApplicabilityStatus: TypeAlias = Literal[
    "applicable", "not_applicable", "unsupported_attempt_shape"
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_PUBLICATION_ID: Final[re.Pattern[str]] = re.compile(r"^pub_[0-9a-f]{32}$")

_PROJECTION_KEYS: Final[frozenset[str]] = frozenset(
    {"work", "publication_id", "cache_key", "snapshot_digest"}
)
_TARGET_KEYS: Final[frozenset[str]] = frozenset(
    {"target_kind", "target_id", "owning_system", "contract_version"}
)
_NATIVE_KEYS: Final[frozenset[str]] = frozenset({"identifier", "sequence"})
_ATTEMPT_KEYS: Final[frozenset[str]] = frozenset(
    {"source_snapshot", "student_id", "target", "native"}
)
_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {"source", "eligibility_revision", "eligibility_decision_sha256"}
)
_CANDIDATE_KEYS: Final[frozenset[str]] = frozenset(
    {"attempt", "eligible_evidence"}
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_POLICY_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"policy_id", "policy_revision", "policy_revision_sha256"}
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
        "selection_basis",
        "minimum_selected",
        "maximum_selected",
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
        "membership_revision",
        "membership_revision_sha256",
        "policy",
        "source_snapshot",
        "candidates",
        "selected_attempts",
        "decision_revision",
        "supersedes_revision",
        "actor",
        "rationale",
        "decided_at",
    }
)


class AttemptSelectionError(ValueError):
    """Base error for canonical attempt-selection models."""


class AttemptSelectionValidationError(AttemptSelectionError):
    """Raised when attempt-selection data violates the contract."""


class AttemptSelectionSerializationError(AttemptSelectionError):
    """Raised when attempt-selection JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class AttemptProjectionReference:
    """Exact immutable projection snapshot containing attempt evidence."""

    work: ModuleWorkRef
    publication_id: str
    cache_key: str
    snapshot_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "work", _work(self.work))
        object.__setattr__(
            self, "publication_id", _publication_id(self.publication_id)
        )
        object.__setattr__(self, "cache_key", _sha256(self.cache_key, "cache_key"))
        object.__setattr__(
            self,
            "snapshot_digest",
            _sha256(self.snapshot_digest, "snapshot_digest"),
        )


@dataclass(frozen=True, slots=True)
class AttemptTargetReference:
    """Explicit producer target boundary identifying one attempt."""

    target_kind: str
    target_id: str | None
    owning_system: str | None
    contract_version: str | None

    def __post_init__(self) -> None:
        if self.target_kind != "attempt":
            raise AttemptSelectionValidationError(
                'attempt target_kind must be exactly "attempt".'
            )
        for field_name in ("target_id", "owning_system", "contract_version"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _native_text(value, field_name),
                )


@dataclass(frozen=True, slots=True)
class AttemptNativeIdentity:
    """Exact producer-native attempt reference, without interpretation."""

    identifier: str | None
    sequence: int | None

    def __post_init__(self) -> None:
        identifier = self.identifier
        if identifier is not None:
            identifier = _native_text(identifier, "attempt identifier")
        sequence = self.sequence
        if sequence is not None:
            sequence = _positive_int(sequence, "attempt sequence")
        if identifier is None and sequence is None:
            raise AttemptSelectionValidationError(
                "attempt native identity requires identifier or sequence."
            )
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "sequence", sequence)


@dataclass(frozen=True, slots=True)
class AttemptObservationReference:
    """Exact producer-native attempt observation within one projection snapshot."""

    source_snapshot: AttemptProjectionReference
    student_id: str
    target: AttemptTargetReference
    native: AttemptNativeIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.source_snapshot, AttemptProjectionReference):
            raise AttemptSelectionValidationError(
                "source_snapshot must be an AttemptProjectionReference."
            )
        object.__setattr__(
            self,
            "source_snapshot",
            validate_attempt_projection_reference(self.source_snapshot),
        )
        object.__setattr__(
            self, "student_id", _identifier(self.student_id, "student_id")
        )
        if not isinstance(self.target, AttemptTargetReference):
            raise AttemptSelectionValidationError(
                "target must be an AttemptTargetReference."
            )
        object.__setattr__(
            self, "target", validate_attempt_target_reference(self.target)
        )
        if not isinstance(self.native, AttemptNativeIdentity):
            raise AttemptSelectionValidationError(
                "native must be an AttemptNativeIdentity."
            )
        object.__setattr__(
            self, "native", validate_attempt_native_identity(self.native)
        )


@dataclass(frozen=True, slots=True)
class AttemptEligibilityBasis:
    """Exact #29 eligibility revision that admitted one evidence source."""

    source: EvidenceSourceReference
    eligibility_revision: int
    eligibility_decision_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, EvidenceSourceReference):
            raise AttemptSelectionValidationError(
                "source must be an EvidenceSourceReference."
            )
        try:
            source = validate_evidence_source_reference(self.source)
        except EvidenceEligibilityValidationError as error:
            raise AttemptSelectionValidationError(str(error)) from error
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "eligibility_revision",
            _positive_int(self.eligibility_revision, "eligibility_revision"),
        )
        object.__setattr__(
            self,
            "eligibility_decision_sha256",
            _sha256(
                self.eligibility_decision_sha256,
                "eligibility_decision_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class AttemptCandidate:
    """One attempt and its exact operative-included #29 evidence basis."""

    attempt: AttemptObservationReference
    eligible_evidence: tuple[AttemptEligibilityBasis, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.attempt, AttemptObservationReference):
            raise AttemptSelectionValidationError(
                "attempt must be an AttemptObservationReference."
            )
        attempt = validate_attempt_observation_reference(self.attempt)
        object.__setattr__(self, "attempt", attempt)
        bases = _typed_tuple(
            self.eligible_evidence,
            AttemptEligibilityBasis,
            "eligible_evidence",
        )
        if not bases:
            raise AttemptSelectionValidationError(
                "attempt candidate requires at least one eligible evidence source."
            )
        validated = tuple(validate_attempt_eligibility_basis(value) for value in bases)
        source_snapshot = attempt.source_snapshot
        for basis in validated:
            source = basis.source
            if (
                source.work != source_snapshot.work
                or source.publication_id != source_snapshot.publication_id
                or source.cache_key != source_snapshot.cache_key
                or source.snapshot_digest != source_snapshot.snapshot_digest
            ):
                raise AttemptSelectionValidationError(
                    "candidate eligibility source must match attempt projection "
                    "snapshot."
                )
        if len({basis.source for basis in validated}) != len(validated):
            raise AttemptSelectionValidationError(
                "candidate eligible_evidence must not contain duplicate sources."
            )
        object.__setattr__(self, "eligible_evidence", validated)


@dataclass(frozen=True, slots=True)
class AttemptSelectionActor:
    """Explicit teacher/policy authorship for #30 state."""

    kind: AttemptSelectionActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"teacher", "policy"}:
            raise AttemptSelectionValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_ATTEMPT_SELECTION_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class AttemptSelectionPolicyReference:
    """Exact immutable selected policy revision and digest."""

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
class AttemptSelectionPolicy:
    """One immutable explicit-selection policy revision."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    selection_basis: AttemptSelectionBasis
    minimum_selected: int
    maximum_selected: int | None
    actor: AttemptSelectionActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION:
            raise AttemptSelectionValidationError('policy schema_version must be "1".')
        if self.record_type != ATTEMPT_SELECTION_POLICY_RECORD_TYPE:
            raise AttemptSelectionValidationError(
                'policy record_type must be "meridian_attempt_selection_policy".'
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
            raise AttemptSelectionValidationError("work.class_id must match class_id.")
        object.__setattr__(self, "work", work)
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        revision = _positive_int(self.policy_revision, "policy_revision")
        object.__setattr__(self, "policy_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise AttemptSelectionValidationError(
                    "policy revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise AttemptSelectionValidationError(
                "policy supersedes_revision must equal policy_revision - 1."
            )
        if self.selection_basis != ATTEMPT_SELECTION_BASIS:
            raise AttemptSelectionValidationError(
                'selection_basis must be exactly "explicit".'
            )
        minimum = _nonnegative_int(self.minimum_selected, "minimum_selected")
        maximum = self.maximum_selected
        if maximum is not None:
            maximum = _nonnegative_int(maximum, "maximum_selected")
            if minimum > maximum:
                raise AttemptSelectionValidationError(
                    "minimum_selected must not exceed maximum_selected."
                )
        object.__setattr__(self, "minimum_selected", minimum)
        object.__setattr__(self, "maximum_selected", maximum)
        if not isinstance(self.actor, AttemptSelectionActor):
            raise AttemptSelectionValidationError(
                "actor must be an AttemptSelectionActor."
            )
        object.__setattr__(self, "actor", validate_attempt_selection_actor(self.actor))
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_ATTEMPT_SELECTION_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self,
            "revised_at",
            _aware_utc_datetime(self.revised_at, "revised_at"),
        )


@dataclass(frozen=True, slots=True)
class AttemptSelectionDecision:
    """One immutable explicit attempt-selection decision for one student."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    work: ModuleWorkRef
    student_id: str
    membership_revision: int
    membership_revision_sha256: str
    policy: AttemptSelectionPolicyReference
    source_snapshot: AttemptProjectionReference
    candidates: tuple[AttemptCandidate, ...]
    selected_attempts: tuple[AttemptObservationReference, ...]
    decision_revision: int
    supersedes_revision: int | None
    actor: AttemptSelectionActor
    rationale: str | None
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION:
            raise AttemptSelectionValidationError(
                'decision schema_version must be "1".'
            )
        if self.record_type != ATTEMPT_SELECTION_DECISION_RECORD_TYPE:
            raise AttemptSelectionValidationError(
                'decision record_type must be "meridian_attempt_selection_decision".'
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
            raise AttemptSelectionValidationError("work.class_id must match class_id.")
        object.__setattr__(self, "work", work)
        student_id = _identifier(self.student_id, "student_id")
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(
            self,
            "membership_revision",
            _positive_int(self.membership_revision, "membership_revision"),
        )
        object.__setattr__(
            self,
            "membership_revision_sha256",
            _sha256(self.membership_revision_sha256, "membership_revision_sha256"),
        )
        if not isinstance(self.policy, AttemptSelectionPolicyReference):
            raise AttemptSelectionValidationError(
                "policy must be an AttemptSelectionPolicyReference."
            )
        object.__setattr__(
            self,
            "policy",
            validate_attempt_selection_policy_reference(self.policy),
        )
        if not isinstance(self.source_snapshot, AttemptProjectionReference):
            raise AttemptSelectionValidationError(
                "source_snapshot must be an AttemptProjectionReference."
            )
        snapshot = validate_attempt_projection_reference(self.source_snapshot)
        if snapshot.work != work:
            raise AttemptSelectionValidationError(
                "source_snapshot work must match decision work."
            )
        object.__setattr__(self, "source_snapshot", snapshot)
        candidates = _typed_tuple(self.candidates, AttemptCandidate, "candidates")
        validated_candidates = tuple(
            validate_attempt_candidate(value) for value in candidates
        )
        attempts = tuple(candidate.attempt for candidate in validated_candidates)
        if len(set(attempts)) != len(attempts):
            raise AttemptSelectionValidationError(
                "candidates must not contain duplicate attempt observations."
            )
        for candidate in validated_candidates:
            if (
                candidate.attempt.source_snapshot != snapshot
                or candidate.attempt.student_id != student_id
            ):
                raise AttemptSelectionValidationError(
                    "candidate scope must match decision snapshot and student."
                )
        object.__setattr__(self, "candidates", validated_candidates)
        selected = _typed_tuple(
            self.selected_attempts,
            AttemptObservationReference,
            "selected_attempts",
        )
        validated_selected = tuple(
            validate_attempt_observation_reference(value) for value in selected
        )
        if len(set(validated_selected)) != len(validated_selected):
            raise AttemptSelectionValidationError(
                "selected_attempts must not contain duplicates."
            )
        candidate_set = set(attempts)
        if any(value not in candidate_set for value in validated_selected):
            raise AttemptSelectionValidationError(
                "every selected attempt must exist in candidates."
            )
        object.__setattr__(self, "selected_attempts", validated_selected)
        revision = _positive_int(self.decision_revision, "decision_revision")
        object.__setattr__(self, "decision_revision", revision)
        supersedes = self.supersedes_revision
        if revision == 1:
            if supersedes is not None:
                raise AttemptSelectionValidationError(
                    "decision revision 1 must use supersedes_revision=null."
                )
        elif supersedes != revision - 1:
            raise AttemptSelectionValidationError(
                "decision supersedes_revision must equal decision_revision - 1."
            )
        if not isinstance(self.actor, AttemptSelectionActor):
            raise AttemptSelectionValidationError(
                "actor must be an AttemptSelectionActor."
            )
        object.__setattr__(self, "actor", validate_attempt_selection_actor(self.actor))
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale,
                "rationale",
                MAXIMUM_ATTEMPT_SELECTION_RATIONALE_LENGTH,
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self, "decided_at", _aware_utc_datetime(self.decided_at, "decided_at")
        )


def validate_attempt_projection_reference(
    value: AttemptProjectionReference,
) -> AttemptProjectionReference:
    if not isinstance(value, AttemptProjectionReference):
        raise AttemptSelectionValidationError(
            "value must be an AttemptProjectionReference."
        )
    return AttemptProjectionReference(
        work=value.work,
        publication_id=value.publication_id,
        cache_key=value.cache_key,
        snapshot_digest=value.snapshot_digest,
    )


def validate_attempt_target_reference(
    value: AttemptTargetReference,
) -> AttemptTargetReference:
    if not isinstance(value, AttemptTargetReference):
        raise AttemptSelectionValidationError(
            "value must be an AttemptTargetReference."
        )
    return AttemptTargetReference(
        target_kind=value.target_kind,
        target_id=value.target_id,
        owning_system=value.owning_system,
        contract_version=value.contract_version,
    )


def validate_attempt_native_identity(
    value: AttemptNativeIdentity,
) -> AttemptNativeIdentity:
    if not isinstance(value, AttemptNativeIdentity):
        raise AttemptSelectionValidationError("value must be an AttemptNativeIdentity.")
    return AttemptNativeIdentity(identifier=value.identifier, sequence=value.sequence)


def validate_attempt_observation_reference(
    value: AttemptObservationReference,
) -> AttemptObservationReference:
    if not isinstance(value, AttemptObservationReference):
        raise AttemptSelectionValidationError(
            "value must be an AttemptObservationReference."
        )
    return AttemptObservationReference(
        source_snapshot=value.source_snapshot,
        student_id=value.student_id,
        target=value.target,
        native=value.native,
    )


def validate_attempt_eligibility_basis(
    value: AttemptEligibilityBasis,
) -> AttemptEligibilityBasis:
    if not isinstance(value, AttemptEligibilityBasis):
        raise AttemptSelectionValidationError(
            "value must be an AttemptEligibilityBasis."
        )
    return AttemptEligibilityBasis(
        source=value.source,
        eligibility_revision=value.eligibility_revision,
        eligibility_decision_sha256=value.eligibility_decision_sha256,
    )


def validate_attempt_candidate(value: AttemptCandidate) -> AttemptCandidate:
    if not isinstance(value, AttemptCandidate):
        raise AttemptSelectionValidationError("value must be an AttemptCandidate.")
    return AttemptCandidate(
        attempt=value.attempt, eligible_evidence=value.eligible_evidence
    )


def validate_attempt_selection_actor(
    value: AttemptSelectionActor,
) -> AttemptSelectionActor:
    if not isinstance(value, AttemptSelectionActor):
        raise AttemptSelectionValidationError("value must be an AttemptSelectionActor.")
    return AttemptSelectionActor(kind=value.kind, actor_id=value.actor_id)


def validate_attempt_selection_policy_reference(
    value: AttemptSelectionPolicyReference,
) -> AttemptSelectionPolicyReference:
    if not isinstance(value, AttemptSelectionPolicyReference):
        raise AttemptSelectionValidationError(
            "value must be an AttemptSelectionPolicyReference."
        )
    return AttemptSelectionPolicyReference(
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        policy_revision_sha256=value.policy_revision_sha256,
    )


def validate_attempt_selection_policy(
    value: AttemptSelectionPolicy,
) -> AttemptSelectionPolicy:
    if not isinstance(value, AttemptSelectionPolicy):
        raise AttemptSelectionValidationError(
            "value must be an AttemptSelectionPolicy."
        )
    return AttemptSelectionPolicy(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        work=value.work,
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        supersedes_revision=value.supersedes_revision,
        selection_basis=value.selection_basis,
        minimum_selected=value.minimum_selected,
        maximum_selected=value.maximum_selected,
        actor=value.actor,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def validate_attempt_selection_decision(
    value: AttemptSelectionDecision,
) -> AttemptSelectionDecision:
    if not isinstance(value, AttemptSelectionDecision):
        raise AttemptSelectionValidationError(
            "value must be an AttemptSelectionDecision."
        )
    return AttemptSelectionDecision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        work=value.work,
        student_id=value.student_id,
        membership_revision=value.membership_revision,
        membership_revision_sha256=value.membership_revision_sha256,
        policy=value.policy,
        source_snapshot=value.source_snapshot,
        candidates=value.candidates,
        selected_attempts=value.selected_attempts,
        decision_revision=value.decision_revision,
        supersedes_revision=value.supersedes_revision,
        actor=value.actor,
        rationale=value.rationale,
        decided_at=value.decided_at,
    )


def validate_attempt_selection_policy_transition(
    previous: AttemptSelectionPolicy,
    candidate: AttemptSelectionPolicy,
) -> AttemptSelectionPolicy:
    old = validate_attempt_selection_policy(previous)
    new = validate_attempt_selection_policy(candidate)
    if (
        new.class_id != old.class_id
        or new.grade_item_id != old.grade_item_id
        or new.work != old.work
        or new.policy_id != old.policy_id
    ):
        raise AttemptSelectionValidationError(
            "candidate policy logical identity must match previous."
        )
    if new.policy_revision != old.policy_revision + 1:
        raise AttemptSelectionValidationError(
            "candidate policy_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.policy_revision:
        raise AttemptSelectionValidationError(
            "candidate policy supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise AttemptSelectionValidationError(
            "candidate revised_at must not be earlier than previous revised_at."
        )
    return new


def validate_attempt_selection_decision_transition(
    previous: AttemptSelectionDecision,
    candidate: AttemptSelectionDecision,
) -> AttemptSelectionDecision:
    old = validate_attempt_selection_decision(previous)
    new = validate_attempt_selection_decision(candidate)
    if (
        new.class_id != old.class_id
        or new.grade_item_id != old.grade_item_id
        or new.work != old.work
        or new.student_id != old.student_id
    ):
        raise AttemptSelectionValidationError(
            "candidate decision logical identity must match previous."
        )
    if new.decision_revision != old.decision_revision + 1:
        raise AttemptSelectionValidationError(
            "candidate decision_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.decision_revision:
        raise AttemptSelectionValidationError(
            "candidate decision supersedes_revision must identify previous revision."
        )
    if new.decided_at < old.decided_at:
        raise AttemptSelectionValidationError(
            "candidate decided_at must not be earlier than previous decided_at."
        )
    return new


def attempt_projection_reference_to_dict(
    value: AttemptProjectionReference,
) -> dict[str, object]:
    ref = validate_attempt_projection_reference(value)
    return {
        "work": module_work_ref_to_dict(ref.work),
        "publication_id": ref.publication_id,
        "cache_key": ref.cache_key,
        "snapshot_digest": ref.snapshot_digest,
    }


def attempt_projection_reference_from_dict(data: object) -> AttemptProjectionReference:
    mapping = _exact_mapping(data, _PROJECTION_KEYS, "attempt projection reference")
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except RoutingModelError as error:
        raise AttemptSelectionValidationError(str(error)) from error
    return AttemptProjectionReference(
        work=work,
        publication_id=_require_str(mapping["publication_id"], "publication_id"),
        cache_key=_require_str(mapping["cache_key"], "cache_key"),
        snapshot_digest=_require_str(mapping["snapshot_digest"], "snapshot_digest"),
    )


def attempt_target_reference_to_dict(
    value: AttemptTargetReference,
) -> dict[str, object]:
    ref = validate_attempt_target_reference(value)
    return {
        "target_kind": ref.target_kind,
        "target_id": ref.target_id,
        "owning_system": ref.owning_system,
        "contract_version": ref.contract_version,
    }


def attempt_target_reference_from_dict(data: object) -> AttemptTargetReference:
    mapping = _exact_mapping(data, _TARGET_KEYS, "attempt target reference")
    return AttemptTargetReference(
        target_kind=_require_str(mapping["target_kind"], "target_kind"),
        target_id=_optional_str(mapping["target_id"], "target_id"),
        owning_system=_optional_str(mapping["owning_system"], "owning_system"),
        contract_version=_optional_str(mapping["contract_version"], "contract_version"),
    )


def attempt_native_identity_to_dict(value: AttemptNativeIdentity) -> dict[str, object]:
    native = validate_attempt_native_identity(value)
    return {"identifier": native.identifier, "sequence": native.sequence}


def attempt_native_identity_from_dict(data: object) -> AttemptNativeIdentity:
    mapping = _exact_mapping(data, _NATIVE_KEYS, "attempt native identity")
    return AttemptNativeIdentity(
        identifier=_optional_str(mapping["identifier"], "identifier"),
        sequence=_optional_positive_int(mapping["sequence"], "sequence"),
    )


def attempt_observation_reference_to_dict(
    value: AttemptObservationReference,
) -> dict[str, object]:
    attempt = validate_attempt_observation_reference(value)
    return {
        "source_snapshot": attempt_projection_reference_to_dict(
            attempt.source_snapshot
        ),
        "student_id": attempt.student_id,
        "target": attempt_target_reference_to_dict(attempt.target),
        "native": attempt_native_identity_to_dict(attempt.native),
    }


def attempt_observation_reference_from_dict(
    data: object,
) -> AttemptObservationReference:
    mapping = _exact_mapping(data, _ATTEMPT_KEYS, "attempt observation reference")
    return AttemptObservationReference(
        source_snapshot=attempt_projection_reference_from_dict(
            mapping["source_snapshot"]
        ),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target=attempt_target_reference_from_dict(mapping["target"]),
        native=attempt_native_identity_from_dict(mapping["native"]),
    )


def attempt_eligibility_basis_to_dict(
    value: AttemptEligibilityBasis,
) -> dict[str, object]:
    basis = validate_attempt_eligibility_basis(value)
    return {
        "source": evidence_source_reference_to_dict(basis.source),
        "eligibility_revision": basis.eligibility_revision,
        "eligibility_decision_sha256": basis.eligibility_decision_sha256,
    }


def attempt_eligibility_basis_from_dict(data: object) -> AttemptEligibilityBasis:
    mapping = _exact_mapping(data, _BASIS_KEYS, "attempt eligibility basis")
    return AttemptEligibilityBasis(
        source=evidence_source_reference_from_dict(mapping["source"]),
        eligibility_revision=_positive_int(
            mapping["eligibility_revision"], "eligibility_revision"
        ),
        eligibility_decision_sha256=_require_str(
            mapping["eligibility_decision_sha256"], "eligibility_decision_sha256"
        ),
    )


def attempt_candidate_to_dict(value: AttemptCandidate) -> dict[str, object]:
    candidate = validate_attempt_candidate(value)
    return {
        "attempt": attempt_observation_reference_to_dict(candidate.attempt),
        "eligible_evidence": [
            attempt_eligibility_basis_to_dict(basis)
            for basis in candidate.eligible_evidence
        ],
    }


def attempt_candidate_from_dict(data: object) -> AttemptCandidate:
    mapping = _exact_mapping(data, _CANDIDATE_KEYS, "attempt candidate")
    evidence = mapping["eligible_evidence"]
    if not isinstance(evidence, list):
        raise AttemptSelectionValidationError("eligible_evidence must be a list.")
    return AttemptCandidate(
        attempt=attempt_observation_reference_from_dict(mapping["attempt"]),
        eligible_evidence=tuple(
            attempt_eligibility_basis_from_dict(item) for item in evidence
        ),
    )


def attempt_selection_actor_to_dict(value: AttemptSelectionActor) -> dict[str, object]:
    actor = validate_attempt_selection_actor(value)
    return {"kind": actor.kind, "actor_id": actor.actor_id}


def attempt_selection_actor_from_dict(data: object) -> AttemptSelectionActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "attempt-selection actor")
    return AttemptSelectionActor(
        kind=cast(AttemptSelectionActorKind, _require_str(mapping["kind"], "kind")),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def attempt_selection_policy_reference_to_dict(
    value: AttemptSelectionPolicyReference,
) -> dict[str, object]:
    ref = validate_attempt_selection_policy_reference(value)
    return {
        "policy_id": ref.policy_id,
        "policy_revision": ref.policy_revision,
        "policy_revision_sha256": ref.policy_revision_sha256,
    }


def attempt_selection_policy_reference_from_dict(
    data: object,
) -> AttemptSelectionPolicyReference:
    mapping = _exact_mapping(
        data, _POLICY_REFERENCE_KEYS, "attempt-selection policy reference"
    )
    return AttemptSelectionPolicyReference(
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_positive_int(mapping["policy_revision"], "policy_revision"),
        policy_revision_sha256=_require_str(
            mapping["policy_revision_sha256"], "policy_revision_sha256"
        ),
    )


def attempt_selection_policy_to_dict(
    value: AttemptSelectionPolicy,
) -> dict[str, object]:
    policy = validate_attempt_selection_policy(value)
    return {
        "schema_version": policy.schema_version,
        "record_type": policy.record_type,
        "class_id": policy.class_id,
        "grade_item_id": policy.grade_item_id,
        "work": module_work_ref_to_dict(policy.work),
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "selection_basis": policy.selection_basis,
        "minimum_selected": policy.minimum_selected,
        "maximum_selected": policy.maximum_selected,
        "actor": attempt_selection_actor_to_dict(policy.actor),
        "rationale": policy.rationale,
        "revised_at": policy.revised_at.isoformat(),
    }


def attempt_selection_policy_from_dict(data: object) -> AttemptSelectionPolicy:
    mapping = _exact_mapping(data, _POLICY_KEYS, "attempt-selection policy")
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except RoutingModelError as error:
        raise AttemptSelectionValidationError(str(error)) from error
    return AttemptSelectionPolicy(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        work=work,
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_positive_int(mapping["policy_revision"], "policy_revision"),
        supersedes_revision=_optional_positive_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        selection_basis=cast(
            AttemptSelectionBasis,
            _require_str(mapping["selection_basis"], "selection_basis"),
        ),
        minimum_selected=_nonnegative_int(
            mapping["minimum_selected"], "minimum_selected"
        ),
        maximum_selected=_optional_nonnegative_int(
            mapping["maximum_selected"], "maximum_selected"
        ),
        actor=attempt_selection_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def attempt_selection_decision_to_dict(
    value: AttemptSelectionDecision,
) -> dict[str, object]:
    decision = validate_attempt_selection_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "work": module_work_ref_to_dict(decision.work),
        "student_id": decision.student_id,
        "membership_revision": decision.membership_revision,
        "membership_revision_sha256": decision.membership_revision_sha256,
        "policy": attempt_selection_policy_reference_to_dict(decision.policy),
        "source_snapshot": attempt_projection_reference_to_dict(
            decision.source_snapshot
        ),
        "candidates": [
            attempt_candidate_to_dict(value) for value in decision.candidates
        ],
        "selected_attempts": [
            attempt_observation_reference_to_dict(value)
            for value in decision.selected_attempts
        ],
        "decision_revision": decision.decision_revision,
        "supersedes_revision": decision.supersedes_revision,
        "actor": attempt_selection_actor_to_dict(decision.actor),
        "rationale": decision.rationale,
        "decided_at": decision.decided_at.isoformat(),
    }


def attempt_selection_decision_from_dict(data: object) -> AttemptSelectionDecision:
    mapping = _exact_mapping(data, _DECISION_KEYS, "attempt-selection decision")
    try:
        work = module_work_ref_from_dict(mapping["work"])
    except RoutingModelError as error:
        raise AttemptSelectionValidationError(str(error)) from error
    candidates = mapping["candidates"]
    selected = mapping["selected_attempts"]
    if not isinstance(candidates, list):
        raise AttemptSelectionValidationError("candidates must be a list.")
    if not isinstance(selected, list):
        raise AttemptSelectionValidationError("selected_attempts must be a list.")
    return AttemptSelectionDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        work=work,
        student_id=_require_str(mapping["student_id"], "student_id"),
        membership_revision=_positive_int(
            mapping["membership_revision"], "membership_revision"
        ),
        membership_revision_sha256=_require_str(
            mapping["membership_revision_sha256"], "membership_revision_sha256"
        ),
        policy=attempt_selection_policy_reference_from_dict(mapping["policy"]),
        source_snapshot=attempt_projection_reference_from_dict(
            mapping["source_snapshot"]
        ),
        candidates=tuple(attempt_candidate_from_dict(item) for item in candidates),
        selected_attempts=tuple(
            attempt_observation_reference_from_dict(item) for item in selected
        ),
        decision_revision=_positive_int(
            mapping["decision_revision"], "decision_revision"
        ),
        supersedes_revision=_optional_positive_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        actor=attempt_selection_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def attempt_selection_policy_to_json_bytes(value: AttemptSelectionPolicy) -> bytes:
    return _canonical_json_bytes(attempt_selection_policy_to_dict(value))


def attempt_selection_policy_from_json_bytes(data: bytes) -> AttemptSelectionPolicy:
    decoded = _decode_json(data, "attempt-selection policy")
    policy = attempt_selection_policy_from_dict(decoded)
    if attempt_selection_policy_to_json_bytes(policy) != data:
        raise AttemptSelectionSerializationError(
            "attempt-selection policy bytes are not canonical."
        )
    return policy


def attempt_selection_decision_to_json_bytes(value: AttemptSelectionDecision) -> bytes:
    return _canonical_json_bytes(attempt_selection_decision_to_dict(value))


def attempt_selection_decision_from_json_bytes(data: bytes) -> AttemptSelectionDecision:
    decoded = _decode_json(data, "attempt-selection decision")
    decision = attempt_selection_decision_from_dict(decoded)
    if attempt_selection_decision_to_json_bytes(decision) != data:
        raise AttemptSelectionSerializationError(
            "attempt-selection decision bytes are not canonical."
        )
    return decision


def attempt_observation_reference_to_json_bytes(
    value: AttemptObservationReference,
) -> bytes:
    return _canonical_json_bytes(attempt_observation_reference_to_dict(value))


def attempt_subject_key(
    class_id: str,
    grade_item_id: str,
    work: ModuleWorkRef,
    student_id: str,
) -> str:
    payload = {
        "class_id": _identifier(class_id, "class_id"),
        "grade_item_id": _identifier(grade_item_id, "grade_item_id"),
        "work": module_work_ref_to_dict(_work(work)),
        "student_id": _identifier(student_id, "student_id"),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def selection_cardinality_allows(
    policy: AttemptSelectionPolicy,
    selected_count: int,
) -> bool:
    validated = validate_attempt_selection_policy(policy)
    count = _nonnegative_int(selected_count, "selected_count")
    if count < validated.minimum_selected:
        return False
    return validated.maximum_selected is None or count <= validated.maximum_selected


def _work(value: object) -> ModuleWorkRef:
    if not isinstance(value, ModuleWorkRef):
        raise AttemptSelectionValidationError("work must be a Core ModuleWorkRef.")
    try:
        return validate_module_work_ref(value)
    except RoutingModelError as error:
        raise AttemptSelectionValidationError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AttemptSelectionValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AttemptSelectionValidationError(str(error)) from error


def _publication_id(value: object) -> str:
    if not isinstance(value, str) or _PUBLICATION_ID.fullmatch(value) is None:
        raise AttemptSelectionValidationError(
            "publication_id must use the Core Publication Record identity format."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AttemptSelectionValidationError(
            f"{field_name} must contain 64 lowercase hexadecimal characters."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AttemptSelectionValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AttemptSelectionValidationError(
            f"{field_name} must be a nonnegative integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _optional_nonnegative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, field_name)


def _native_text(value: object, field_name: str) -> str:
    return _bounded_text(
        value,
        field_name,
        MAXIMUM_ATTEMPT_SELECTION_NATIVE_TEXT_LENGTH,
    )


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AttemptSelectionValidationError(f"{field_name} must be a string.")
    text = unicodedata.normalize("NFC", value)
    if text != text.strip() or not text:
        raise AttemptSelectionValidationError(
            f"{field_name} must contain trimmed nonempty text."
        )
    if len(text) > maximum:
        raise AttemptSelectionValidationError(
            f"{field_name} exceeds the maximum length of {maximum}."
        )
    if any(
        ord(character) < 32
        or ord(character) == 127
        or character in {"\u2028", "\u2029"}
        for character in text
    ):
        raise AttemptSelectionValidationError(
            f"{field_name} must be control-free single-line text."
        )
    return text


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AttemptSelectionValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise AttemptSelectionValidationError(
            f"{field_name} must be an ISO 8601 timestamp."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _typed_tuple(
    value: object,
    expected: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)):
        raise AttemptSelectionValidationError(f"{field_name} must be an iterable.")
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise AttemptSelectionValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(item, expected) for item in items):
        raise AttemptSelectionValidationError(
            f"{field_name} contains an invalid value type."
        )
    return cast(tuple[_T, ...], items)


def _exact_mapping(
    data: object, keys: frozenset[str], label: str
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise AttemptSelectionValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise AttemptSelectionValidationError(f"{label} keys must be strings.")
    actual = frozenset(cast(Mapping[str, object], data))
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise AttemptSelectionValidationError(
            f"{label} does not use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AttemptSelectionValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


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
        raise AttemptSelectionSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AttemptSelectionSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise AttemptSelectionSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise AttemptSelectionSerializationError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AttemptSelectionSerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except AttemptSelectionSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise AttemptSelectionSerializationError(
            f"{label} is not valid JSON."
        ) from error
