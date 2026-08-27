"""Canonical standards-evidence associations and bounded aggregation inputs.

This module deliberately stops at calculation inputs.  It associates exact evidence
with durable Core standard IDs and preserves operative observations; it never chooses
an evidence policy or calculates proficiency.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.evidence import NativeStateValue
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    evidence_source_key,
    evidence_source_reference_from_dict,
    evidence_source_reference_to_dict,
    validate_evidence_source_reference,
)
from meridian.proficiency_mapping import (
    NativeValueMappingOutcome,
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)

STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION: Final[str] = "1"
STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE: Final[str] = (
    "meridian_standard_evidence_association"
)
STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION: Final[str] = "1"
STANDARD_AGGREGATION_INPUTS_RECORD_TYPE: Final[str] = (
    "meridian_standard_aggregation_inputs"
)
MAXIMUM_STANDARD_EVIDENCE_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_STANDARD_EVIDENCE_RATIONALE_LENGTH: Final[int] = 2000
MAXIMUM_STANDARD_AGGREGATION_CANDIDATES: Final[int] = 1000

StandardEvidenceAssociationDisposition: TypeAlias = Literal[
    "associated", "not_associated"
]
StandardEvidenceAssociationBasis: TypeAlias = Literal["producer_declared", "explicit"]
StandardEvidenceActorKind: TypeAlias = Literal["teacher", "policy"]
StandardAggregationEntryStatus: TypeAlias = Literal[
    "performance", "native_state", "excluded"
]
StandardAggregationExclusionReason: TypeAlias = Literal[
    "association_unresolved",
    "not_associated",
    "eligibility_unresolved",
    "eligibility_not_included",
    "attempt_selection_unresolved",
    "attempt_not_selected",
    "reassessment_unresolved",
    "reassessment_noncontributing",
    "mapping_not_supplied",
    "mapping_unmapped",
    "mapping_unsupported",
    "scale_mismatch",
    "source_unverifiable",
    "standard_unresolved",
    "nonstudent_target",
    "student_mismatch",
]
ResolvedAssociationState: TypeAlias = Literal[
    "associated",
    "not_associated",
    "no_decision",
    "source_unverifiable",
    "standard_unresolved",
]
ResolvedEligibilityState: TypeAlias = Literal["included", "not_included", "unresolved"]
ResolvedAttemptState: TypeAlias = Literal[
    "not_applicable", "selected", "not_selected", "unresolved"
]
ResolvedReassessmentState: TypeAlias = Literal[
    "not_applicable", "contributing", "noncontributing", "unresolved"
]
SubjectKind: TypeAlias = Literal["student", "nonstudent"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_ASSOCIATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
        "source",
        "standard_id",
        "association_revision",
        "supersedes_revision",
        "disposition",
        "basis",
        "actor",
        "rationale",
        "decided_at",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_AGGREGATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "grade_item",
        "student_id",
        "standard_id",
        "target_scale",
        "entries",
    }
)
_GRADE_ITEM_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "grade_item_revision_sha256",
    }
)
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "source",
        "result_kind",
        "target_kind",
        "status",
        "exclusion_reason",
        "membership_reference",
        "eligibility_reference",
        "attempt_selection_reference",
        "reassessment_reference",
        "association_reference",
        "mapping_profile_reference",
        "mapping_status",
        "proficiency_level_id",
        "native_state",
    }
)
_DECISION_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"decision_kind", "revision", "decision_sha256"}
)
_ASSOCIATION_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "grade_item_id",
        "source",
        "standard_id",
        "association_revision",
        "decision_sha256",
    }
)
_PROFILE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "scale_id",
        "profile_id",
        "profile_revision",
        "profile_sha256",
    }
)
_NATIVE_STATE_KEYS: Final[frozenset[str]] = frozenset({"code", "label", "description"})
_T = TypeVar("_T")


class StandardsEvidenceError(ValueError):
    """Base error for standards-evidence contracts."""


class StandardsEvidenceValidationError(StandardsEvidenceError):
    """Raised when a standards-evidence value violates its contract."""


class StandardsEvidenceSerializationError(StandardsEvidenceError):
    """Raised for invalid or noncanonical standards-evidence JSON."""


@dataclass(frozen=True, slots=True)
class StandardEvidenceActor:
    """Teacher/policy ownership without inferred deployment identity."""

    kind: StandardEvidenceActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"teacher", "policy"}:
            raise StandardsEvidenceValidationError(
                "association actor kind must be teacher or policy."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_STANDARD_EVIDENCE_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationDecision:
    """One immutable academic decision for an exact source/standard family."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    source: EvidenceSourceReference
    standard_id: str
    association_revision: int
    supersedes_revision: int | None
    disposition: StandardEvidenceAssociationDisposition
    basis: StandardEvidenceAssociationBasis
    actor: StandardEvidenceActor
    rationale: str | None
    decided_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION:
            raise StandardsEvidenceValidationError('schema_version must be "1".')
        if self.record_type != STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE:
            raise StandardsEvidenceValidationError(
                "record_type must identify a standards-evidence association."
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self, "grade_item_id", _identifier(self.grade_item_id, "grade_item_id")
        )
        if not isinstance(self.source, EvidenceSourceReference):
            raise StandardsEvidenceValidationError(
                "source must be an EvidenceSourceReference."
            )
        source = validate_evidence_source_reference(self.source)
        if source.work.class_id != class_id:
            raise StandardsEvidenceValidationError(
                "source work class_id must match association class_id."
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "standard_id", _standard_id(self.standard_id))
        revision = _positive_int(self.association_revision, "association_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision, "supersedes_revision"
        )
        if revision == 1 and supersedes is not None:
            raise StandardsEvidenceValidationError(
                "association revision 1 must not supersede another revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise StandardsEvidenceValidationError(
                "supersedes_revision must identify the immediately prior revision."
            )
        object.__setattr__(self, "association_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        if self.disposition not in {"associated", "not_associated"}:
            raise StandardsEvidenceValidationError(
                "disposition must be associated or not_associated."
            )
        if self.basis not in {"producer_declared", "explicit"}:
            raise StandardsEvidenceValidationError(
                "basis must be producer_declared or explicit."
            )
        if not isinstance(self.actor, StandardEvidenceActor):
            raise StandardsEvidenceValidationError(
                "actor must be a StandardEvidenceActor."
            )
        object.__setattr__(
            self,
            "actor",
            StandardEvidenceActor(self.actor.kind, self.actor.actor_id),
        )
        rationale = self.rationale
        if rationale is not None:
            rationale = _bounded_text(
                rationale, "rationale", MAXIMUM_STANDARD_EVIDENCE_RATIONALE_LENGTH
            )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self, "decided_at", _aware_utc_datetime(self.decided_at, "decided_at")
        )


@dataclass(frozen=True, slots=True)
class StandardEvidenceAssociationReference:
    """Exact immutable association decision provenance."""

    class_id: str
    grade_item_id: str
    source: EvidenceSourceReference
    standard_id: str
    association_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(
            self, "grade_item_id", _identifier(self.grade_item_id, "grade_item_id")
        )
        source = validate_evidence_source_reference(self.source)
        if source.work.class_id != class_id:
            raise StandardsEvidenceValidationError(
                "association reference source class must match class_id."
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "standard_id", _standard_id(self.standard_id))
        object.__setattr__(
            self,
            "association_revision",
            _positive_int(self.association_revision, "association_revision"),
        )
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class GradeItemAggregationBasis:
    """Exact Grade Item revision/digest bound by one aggregation input set."""

    class_id: str
    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self, "grade_item_id", _identifier(self.grade_item_id, "grade_item_id")
        )
        object.__setattr__(
            self,
            "grade_item_revision",
            _positive_int(self.grade_item_revision, "grade_item_revision"),
        )
        object.__setattr__(
            self,
            "grade_item_revision_sha256",
            _sha256(self.grade_item_revision_sha256, "grade_item_revision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class AggregationDecisionReference:
    """Exact digest-bound upstream #28-#31 decision reference."""

    decision_kind: Literal[
        "membership", "eligibility", "attempt_selection", "reassessment"
    ]
    revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        if self.decision_kind not in {
            "membership",
            "eligibility",
            "attempt_selection",
            "reassessment",
        }:
            raise StandardsEvidenceValidationError("unsupported decision_kind.")
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        object.__setattr__(
            self,
            "decision_sha256",
            _sha256(self.decision_sha256, "decision_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ResolvedStandardAggregationCandidate:
    """One already-resolved candidate supplied to the pure bounded builder."""

    source: EvidenceSourceReference
    standard_id: str
    result_kind: str
    target_kind: str
    subject_kind: SubjectKind
    subject_student_id: str | None
    association_state: ResolvedAssociationState
    eligibility_state: ResolvedEligibilityState
    attempt_state: ResolvedAttemptState
    reassessment_state: ResolvedReassessmentState
    membership_reference: AggregationDecisionReference | None = None
    eligibility_reference: AggregationDecisionReference | None = None
    attempt_selection_reference: AggregationDecisionReference | None = None
    reassessment_reference: AggregationDecisionReference | None = None
    association_reference: StandardEvidenceAssociationReference | None = None
    mapping_outcome: NativeValueMappingOutcome | None = None

    def __post_init__(self) -> None:
        source = validate_evidence_source_reference(self.source)
        object.__setattr__(self, "source", source)
        standard_id = _standard_id(self.standard_id)
        object.__setattr__(self, "standard_id", standard_id)
        object.__setattr__(self, "result_kind", _code(self.result_kind, "result_kind"))
        object.__setattr__(self, "target_kind", _code(self.target_kind, "target_kind"))
        if self.subject_kind not in {"student", "nonstudent"}:
            raise StandardsEvidenceValidationError("unsupported subject_kind.")
        if self.subject_kind == "student":
            if self.subject_student_id is None:
                raise StandardsEvidenceValidationError(
                    "student subjects require subject_student_id."
                )
            object.__setattr__(
                self,
                "subject_student_id",
                _identifier(self.subject_student_id, "subject_student_id"),
            )
        elif self.subject_student_id is not None:
            raise StandardsEvidenceValidationError(
                "nonstudent subjects must not carry subject_student_id."
            )
        if self.association_state not in {
            "associated",
            "not_associated",
            "no_decision",
            "source_unverifiable",
            "standard_unresolved",
        }:
            raise StandardsEvidenceValidationError("unsupported association_state.")
        if self.eligibility_state not in {"included", "not_included", "unresolved"}:
            raise StandardsEvidenceValidationError("unsupported eligibility_state.")
        if self.attempt_state not in {
            "not_applicable",
            "selected",
            "not_selected",
            "unresolved",
        }:
            raise StandardsEvidenceValidationError("unsupported attempt_state.")
        if self.reassessment_state not in {
            "not_applicable",
            "contributing",
            "noncontributing",
            "unresolved",
        }:
            raise StandardsEvidenceValidationError("unsupported reassessment_state.")
        reference_kinds = {
            "membership_reference": "membership",
            "eligibility_reference": "eligibility",
            "attempt_selection_reference": "attempt_selection",
            "reassessment_reference": "reassessment",
        }
        for field_name, expected_kind in reference_kinds.items():
            reference = getattr(self, field_name)
            if reference is not None and not isinstance(
                reference, AggregationDecisionReference
            ):
                raise StandardsEvidenceValidationError(
                    f"{field_name} must be an AggregationDecisionReference or None."
                )
            if reference is not None and reference.decision_kind != expected_kind:
                raise StandardsEvidenceValidationError(
                    f"{field_name} must contain a {expected_kind} reference."
                )
        if self.eligibility_state == "included" and self.eligibility_reference is None:
            raise StandardsEvidenceValidationError(
                "included eligibility requires an exact eligibility reference."
            )
        if (
            self.attempt_state in {"selected", "not_selected"}
            and self.attempt_selection_reference is None
        ):
            raise StandardsEvidenceValidationError(
                "resolved attempt state requires an exact attempt-selection reference."
            )
        if (
            self.reassessment_state in {"contributing", "noncontributing"}
            and self.reassessment_reference is None
        ):
            raise StandardsEvidenceValidationError(
                "resolved reassessment state requires an exact reassessment reference."
            )
        if self.association_reference is not None:
            reference = self.association_reference
            if not isinstance(reference, StandardEvidenceAssociationReference):
                raise StandardsEvidenceValidationError(
                    "association_reference has an invalid type."
                )
            if reference.source != source or reference.standard_id != standard_id:
                raise StandardsEvidenceValidationError(
                    "association_reference must match candidate source and standard."
                )
        if self.association_state == "no_decision":
            if self.association_reference is not None:
                raise StandardsEvidenceValidationError(
                    "no_decision must not carry an association reference."
                )
        elif self.association_state in {"associated", "not_associated"}:
            if self.association_reference is None:
                raise StandardsEvidenceValidationError(
                    "selected association state requires an exact association "
                    "reference."
                )
        if self.mapping_outcome is not None and not isinstance(
            self.mapping_outcome, NativeValueMappingOutcome
        ):
            raise StandardsEvidenceValidationError(
                "mapping_outcome must be a NativeValueMappingOutcome or None."
            )


@dataclass(frozen=True, slots=True)
class StandardAggregationInputEntry:
    """One preserved input observation or explicitly explained exclusion."""

    source: EvidenceSourceReference
    result_kind: str
    target_kind: str
    status: StandardAggregationEntryStatus
    exclusion_reason: StandardAggregationExclusionReason | None
    membership_reference: AggregationDecisionReference | None
    eligibility_reference: AggregationDecisionReference | None
    attempt_selection_reference: AggregationDecisionReference | None
    reassessment_reference: AggregationDecisionReference | None
    association_reference: StandardEvidenceAssociationReference | None
    mapping_profile_reference: NativeValueMappingProfileReference | None
    mapping_status: Literal["mapped", "native_state", "unmapped", "unsupported"] | None
    proficiency_level_id: str | None
    native_state: NativeStateValue | None

    def __post_init__(self) -> None:
        source = validate_evidence_source_reference(self.source)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "result_kind", _code(self.result_kind, "result_kind"))
        object.__setattr__(self, "target_kind", _code(self.target_kind, "target_kind"))
        if self.status not in {"performance", "native_state", "excluded"}:
            raise StandardsEvidenceValidationError("unsupported aggregation status.")
        if self.mapping_status not in {
            "mapped",
            "native_state",
            "unmapped",
            "unsupported",
            None,
        }:
            raise StandardsEvidenceValidationError("unsupported mapping_status.")
        reference_kinds = {
            "membership_reference": "membership",
            "eligibility_reference": "eligibility",
            "attempt_selection_reference": "attempt_selection",
            "reassessment_reference": "reassessment",
        }
        for field_name, expected_kind in reference_kinds.items():
            reference = getattr(self, field_name)
            if reference is not None and not isinstance(
                reference, AggregationDecisionReference
            ):
                raise StandardsEvidenceValidationError(
                    f"{field_name} must be an AggregationDecisionReference or None."
                )
            if reference is not None and reference.decision_kind != expected_kind:
                raise StandardsEvidenceValidationError(
                    f"{field_name} must contain a {expected_kind} reference."
                )
        if self.association_reference is not None:
            if not isinstance(
                self.association_reference, StandardEvidenceAssociationReference
            ):
                raise StandardsEvidenceValidationError(
                    "association_reference has an invalid type."
                )
            if self.association_reference.source != source:
                raise StandardsEvidenceValidationError(
                    "association_reference must match the exact entry source."
                )
        if self.mapping_profile_reference is not None and not isinstance(
            self.mapping_profile_reference, NativeValueMappingProfileReference
        ):
            raise StandardsEvidenceValidationError(
                "mapping_profile_reference has an invalid type."
            )
        if (self.mapping_profile_reference is None) != (self.mapping_status is None):
            raise StandardsEvidenceValidationError(
                "mapping profile and mapping status must be present together."
            )
        if self.native_state is not None and not isinstance(
            self.native_state, NativeStateValue
        ):
            raise StandardsEvidenceValidationError(
                "native_state must be a NativeStateValue or None."
            )
        reasons = {
            "association_unresolved",
            "not_associated",
            "eligibility_unresolved",
            "eligibility_not_included",
            "attempt_selection_unresolved",
            "attempt_not_selected",
            "reassessment_unresolved",
            "reassessment_noncontributing",
            "mapping_not_supplied",
            "mapping_unmapped",
            "mapping_unsupported",
            "scale_mismatch",
            "source_unverifiable",
            "standard_unresolved",
            "nonstudent_target",
            "student_mismatch",
        }
        if self.exclusion_reason is not None and self.exclusion_reason not in reasons:
            raise StandardsEvidenceValidationError("unsupported exclusion_reason.")
        if self.status == "excluded":
            if self.exclusion_reason is None:
                raise StandardsEvidenceValidationError(
                    "excluded entries require an exclusion reason."
                )
            if self.proficiency_level_id is not None or self.native_state is not None:
                raise StandardsEvidenceValidationError(
                    "excluded entries cannot carry an operative value."
                )
        elif self.exclusion_reason is not None:
            raise StandardsEvidenceValidationError(
                "operative entries cannot carry an exclusion reason."
            )
        if self.status == "performance":
            if self.proficiency_level_id is None or self.native_state is not None:
                raise StandardsEvidenceValidationError(
                    "performance requires only proficiency_level_id."
                )
            object.__setattr__(
                self,
                "proficiency_level_id",
                _identifier(self.proficiency_level_id, "proficiency_level_id"),
            )
            if self.mapping_status != "mapped":
                raise StandardsEvidenceValidationError(
                    "performance requires mapped provenance."
                )
            if (
                self.mapping_profile_reference is None
                or self.association_reference is None
                or self.membership_reference is None
                or self.eligibility_reference is None
            ):
                raise StandardsEvidenceValidationError(
                    "performance requires exact mapping, association, membership, "
                    "and eligibility provenance."
                )
        elif self.status == "native_state":
            if self.native_state is None or self.proficiency_level_id is not None:
                raise StandardsEvidenceValidationError(
                    "native_state requires only the exact native state."
                )
            if self.mapping_status != "native_state":
                raise StandardsEvidenceValidationError(
                    "native_state requires native_state mapping provenance."
                )
            if (
                self.mapping_profile_reference is None
                or self.association_reference is None
                or self.membership_reference is None
                or self.eligibility_reference is None
            ):
                raise StandardsEvidenceValidationError(
                    "native_state requires exact mapping, association, membership, "
                    "and eligibility provenance."
                )
        elif self.exclusion_reason == "mapping_not_supplied":
            if (
                self.mapping_profile_reference is not None
                or self.mapping_status is not None
            ):
                raise StandardsEvidenceValidationError(
                    "mapping_not_supplied must not carry mapping provenance."
                )
        elif self.exclusion_reason == "mapping_unmapped":
            if (
                self.mapping_profile_reference is None
                or self.mapping_status != "unmapped"
            ):
                raise StandardsEvidenceValidationError(
                    "mapping_unmapped requires an exact profile and unmapped status."
                )
        elif self.exclusion_reason == "mapping_unsupported":
            if (
                self.mapping_profile_reference is None
                or self.mapping_status != "unsupported"
            ):
                raise StandardsEvidenceValidationError(
                    "mapping_unsupported requires an exact profile and "
                    "unsupported status."
                )


@dataclass(frozen=True, slots=True)
class StandardAggregationInputs:
    """Deterministic, bounded inputs for a later #34 calculation."""

    schema_version: str
    record_type: str
    grade_item: GradeItemAggregationBasis
    student_id: str
    standard_id: str
    target_scale: ProficiencyScaleReference
    entries: tuple[StandardAggregationInputEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION:
            raise StandardsEvidenceValidationError(
                "unsupported aggregation-input schema_version."
            )
        if self.record_type != STANDARD_AGGREGATION_INPUTS_RECORD_TYPE:
            raise StandardsEvidenceValidationError(
                "record_type must identify standard aggregation inputs."
            )
        if not isinstance(self.grade_item, GradeItemAggregationBasis):
            raise StandardsEvidenceValidationError(
                "grade_item must be a GradeItemAggregationBasis."
            )
        student_id = _identifier(self.student_id, "student_id")
        object.__setattr__(self, "student_id", student_id)
        standard_id = _standard_id(self.standard_id)
        object.__setattr__(self, "standard_id", standard_id)
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardsEvidenceValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != self.grade_item.class_id:
            raise StandardsEvidenceValidationError(
                "target scale class must match Grade Item class."
            )
        entries = _typed_tuple(self.entries, StandardAggregationInputEntry, "entries")
        if len(entries) > MAXIMUM_STANDARD_AGGREGATION_CANDIDATES:
            raise StandardsEvidenceValidationError(
                "aggregation candidate count exceeds the finite maximum."
            )
        keys = tuple(evidence_source_key(entry.source) for entry in entries)
        if len(set(keys)) != len(keys):
            raise StandardsEvidenceValidationError(
                "duplicate exact source/standard aggregation candidate."
            )
        if keys != tuple(sorted(keys)):
            raise StandardsEvidenceValidationError(
                "aggregation entries must use deterministic source-key ordering."
            )
        for entry in entries:
            if entry.source.work.class_id != self.grade_item.class_id:
                raise StandardsEvidenceValidationError(
                    "aggregation entry source class must match Grade Item class."
                )
            reference = entry.association_reference
            if reference is not None and (
                reference.source != entry.source
                or reference.standard_id != standard_id
                or reference.class_id != self.grade_item.class_id
                or reference.grade_item_id != self.grade_item.grade_item_id
            ):
                raise StandardsEvidenceValidationError(
                    "aggregation association reference must match entry and scope."
                )
        object.__setattr__(self, "entries", entries)

    @property
    def sha256(self) -> str:
        """Stable digest suitable for exact binding by issue #34."""
        return hashlib.sha256(
            standard_aggregation_inputs_to_json_bytes(self)
        ).hexdigest()


def validate_standard_evidence_association_decision(
    value: StandardEvidenceAssociationDecision,
) -> StandardEvidenceAssociationDecision:
    if not isinstance(value, StandardEvidenceAssociationDecision):
        raise StandardsEvidenceValidationError(
            "decision must be a StandardEvidenceAssociationDecision."
        )
    return StandardEvidenceAssociationDecision(
        value.schema_version,
        value.record_type,
        value.class_id,
        value.grade_item_id,
        value.source,
        value.standard_id,
        value.association_revision,
        value.supersedes_revision,
        value.disposition,
        value.basis,
        value.actor,
        value.rationale,
        value.decided_at,
    )


def validate_standard_evidence_association_transition(
    previous: StandardEvidenceAssociationDecision,
    candidate: StandardEvidenceAssociationDecision,
) -> StandardEvidenceAssociationDecision:
    """Validate one pure contiguous transition without I/O or wall-clock use."""
    old = validate_standard_evidence_association_decision(previous)
    new = validate_standard_evidence_association_decision(candidate)
    if (
        new.class_id,
        new.grade_item_id,
        new.source,
        new.standard_id,
    ) != (old.class_id, old.grade_item_id, old.source, old.standard_id):
        raise StandardsEvidenceValidationError(
            "association transition must preserve its exact logical identity."
        )
    if new.association_revision != old.association_revision + 1:
        raise StandardsEvidenceValidationError(
            "association revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.association_revision:
        raise StandardsEvidenceValidationError(
            "association supersedes_revision must identify previous."
        )
    if new.decided_at < old.decided_at:
        raise StandardsEvidenceValidationError(
            "association decided_at must not precede the previous revision."
        )
    return new


def standard_evidence_association_to_dict(
    value: StandardEvidenceAssociationDecision,
) -> dict[str, object]:
    decision = validate_standard_evidence_association_decision(value)
    return {
        "schema_version": decision.schema_version,
        "record_type": decision.record_type,
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "source": evidence_source_reference_to_dict(decision.source),
        "standard_id": decision.standard_id,
        "association_revision": decision.association_revision,
        "supersedes_revision": decision.supersedes_revision,
        "disposition": decision.disposition,
        "basis": decision.basis,
        "actor": {"kind": decision.actor.kind, "actor_id": decision.actor.actor_id},
        "rationale": decision.rationale,
        "decided_at": _datetime_to_text(decision.decided_at),
    }


def standard_evidence_association_from_dict(
    data: object,
) -> StandardEvidenceAssociationDecision:
    mapping = _exact_mapping(data, _ASSOCIATION_KEYS, "association decision")
    actor_data = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "association actor")
    return StandardEvidenceAssociationDecision(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        source=evidence_source_reference_from_dict(mapping["source"]),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        association_revision=_require_int(
            mapping["association_revision"], "association_revision"
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        disposition=cast(
            StandardEvidenceAssociationDisposition,
            _require_str(mapping["disposition"], "disposition"),
        ),
        basis=cast(
            StandardEvidenceAssociationBasis,
            _require_str(mapping["basis"], "basis"),
        ),
        actor=StandardEvidenceActor(
            kind=cast(
                StandardEvidenceActorKind,
                _require_str(actor_data["kind"], "actor.kind"),
            ),
            actor_id=_require_str(actor_data["actor_id"], "actor.actor_id"),
        ),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
    )


def standard_evidence_association_to_json_bytes(
    value: StandardEvidenceAssociationDecision,
) -> bytes:
    return _canonical_json_bytes(standard_evidence_association_to_dict(value))


def standard_evidence_association_from_json_bytes(
    data: bytes,
) -> StandardEvidenceAssociationDecision:
    decoded = _decode_json(data, "association decision")
    result = standard_evidence_association_from_dict(decoded)
    if standard_evidence_association_to_json_bytes(result) != data:
        raise StandardsEvidenceSerializationError(
            "association decision is not canonically encoded."
        )
    return result


def standard_evidence_association_reference(
    decision: StandardEvidenceAssociationDecision,
) -> StandardEvidenceAssociationReference:
    value = validate_standard_evidence_association_decision(decision)
    return StandardEvidenceAssociationReference(
        value.class_id,
        value.grade_item_id,
        value.source,
        value.standard_id,
        value.association_revision,
        hashlib.sha256(standard_evidence_association_to_json_bytes(value)).hexdigest(),
    )


def standard_evidence_association_key(
    class_id: str,
    grade_item_id: str,
    source: EvidenceSourceReference,
    standard_id: str,
) -> str:
    """Hash the complete logical family; raw standard IDs never become paths."""
    scope = {
        "class_id": _identifier(class_id, "class_id"),
        "grade_item_id": _identifier(grade_item_id, "grade_item_id"),
        "source": evidence_source_reference_to_dict(source),
        "standard_id": _standard_id(standard_id),
    }
    return hashlib.sha256(_canonical_json_bytes(scope)).hexdigest()


def build_standard_aggregation_inputs(
    grade_item: GradeItemAggregationBasis,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    candidates: Iterable[ResolvedStandardAggregationCandidate],
) -> StandardAggregationInputs:
    """Build deterministic inputs from an explicit finite resolved candidate set."""
    if not isinstance(grade_item, GradeItemAggregationBasis):
        raise StandardsEvidenceValidationError(
            "grade_item must be a GradeItemAggregationBasis."
        )
    student = _identifier(student_id, "student_id")
    standard = _standard_id(standard_id)
    if not isinstance(target_scale, ProficiencyScaleReference):
        raise StandardsEvidenceValidationError(
            "target_scale must be a ProficiencyScaleReference."
        )
    if target_scale.class_id != grade_item.class_id:
        raise StandardsEvidenceValidationError(
            "target scale class must match Grade Item class."
        )
    if isinstance(candidates, (str, bytes)):
        raise StandardsEvidenceValidationError("candidates must be an iterable.")
    try:
        resolved = tuple(candidates)
    except TypeError as error:
        raise StandardsEvidenceValidationError(
            "candidates must be an iterable."
        ) from error
    if len(resolved) > MAXIMUM_STANDARD_AGGREGATION_CANDIDATES:
        raise StandardsEvidenceValidationError(
            "aggregation candidate count exceeds the finite maximum of "
            f"{MAXIMUM_STANDARD_AGGREGATION_CANDIDATES}."
        )
    if any(
        not isinstance(item, ResolvedStandardAggregationCandidate) for item in resolved
    ):
        raise StandardsEvidenceValidationError(
            "candidates must contain ResolvedStandardAggregationCandidate values."
        )
    keys: set[str] = set()
    entries: list[StandardAggregationInputEntry] = []
    for candidate in resolved:
        if candidate.source.work.class_id != grade_item.class_id:
            raise StandardsEvidenceValidationError(
                "candidate source class must match aggregation class."
            )
        if candidate.standard_id != standard:
            raise StandardsEvidenceValidationError(
                "candidate standard must match aggregation standard."
            )
        key = evidence_source_key(candidate.source)
        if key in keys:
            raise StandardsEvidenceValidationError(
                "duplicate exact source/standard aggregation candidate."
            )
        keys.add(key)
        entries.append(_entry_for_candidate(candidate, student, target_scale))
    entries.sort(key=lambda item: evidence_source_key(item.source))
    return StandardAggregationInputs(
        STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item,
        student,
        standard,
        target_scale,
        tuple(entries),
    )


def standard_aggregation_inputs_to_dict(
    value: StandardAggregationInputs,
) -> dict[str, object]:
    if not isinstance(value, StandardAggregationInputs):
        raise StandardsEvidenceValidationError(
            "value must be StandardAggregationInputs."
        )
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "grade_item": {
            "class_id": value.grade_item.class_id,
            "grade_item_id": value.grade_item.grade_item_id,
            "grade_item_revision": value.grade_item.grade_item_revision,
            "grade_item_revision_sha256": value.grade_item.grade_item_revision_sha256,
        },
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "entries": [_aggregation_entry_to_dict(item) for item in value.entries],
    }


def standard_aggregation_inputs_to_json_bytes(
    value: StandardAggregationInputs,
) -> bytes:
    return _canonical_json_bytes(standard_aggregation_inputs_to_dict(value))


def standard_aggregation_inputs_from_dict(data: object) -> StandardAggregationInputs:
    mapping = _exact_mapping(data, _AGGREGATION_KEYS, "aggregation inputs")
    basis = _exact_mapping(
        mapping["grade_item"], _GRADE_ITEM_BASIS_KEYS, "Grade Item basis"
    )
    scale = _exact_mapping(
        mapping["target_scale"], _SCALE_REFERENCE_KEYS, "target scale reference"
    )
    entries_data = mapping["entries"]
    if not isinstance(entries_data, list):
        raise StandardsEvidenceSerializationError("entries must be a JSON array.")
    return StandardAggregationInputs(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        grade_item=GradeItemAggregationBasis(
            _require_str(basis["class_id"], "grade_item.class_id"),
            _require_str(basis["grade_item_id"], "grade_item.grade_item_id"),
            _require_int(
                basis["grade_item_revision"], "grade_item.grade_item_revision"
            ),
            _require_str(
                basis["grade_item_revision_sha256"],
                "grade_item.grade_item_revision_sha256",
            ),
        ),
        student_id=_require_str(mapping["student_id"], "student_id"),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        target_scale=ProficiencyScaleReference(
            _require_str(scale["class_id"], "target_scale.class_id"),
            _require_str(scale["scale_id"], "target_scale.scale_id"),
            _require_int(scale["scale_revision"], "target_scale.scale_revision"),
            _require_str(scale["scale_sha256"], "target_scale.scale_sha256"),
        ),
        entries=tuple(_aggregation_entry_from_dict(item) for item in entries_data),
    )


def standard_aggregation_inputs_from_json_bytes(
    data: bytes,
) -> StandardAggregationInputs:
    decoded = _decode_json(data, "aggregation inputs")
    result = standard_aggregation_inputs_from_dict(decoded)
    if standard_aggregation_inputs_to_json_bytes(result) != data:
        raise StandardsEvidenceSerializationError(
            "aggregation inputs are not canonically encoded."
        )
    return result


def standard_aggregation_inputs_sha256(value: StandardAggregationInputs) -> str:
    return hashlib.sha256(standard_aggregation_inputs_to_json_bytes(value)).hexdigest()


def _entry_for_candidate(
    candidate: ResolvedStandardAggregationCandidate,
    student_id: str,
    target_scale: ProficiencyScaleReference,
) -> StandardAggregationInputEntry:
    reason: StandardAggregationExclusionReason | None = None
    if candidate.association_state == "source_unverifiable":
        reason = "source_unverifiable"
    elif candidate.association_state == "standard_unresolved":
        reason = "standard_unresolved"
    elif candidate.subject_kind == "nonstudent":
        reason = "nonstudent_target"
    elif candidate.subject_student_id != student_id:
        reason = "student_mismatch"
    elif candidate.association_state == "no_decision":
        reason = "association_unresolved"
    elif candidate.association_state == "not_associated":
        reason = "not_associated"
    elif candidate.eligibility_state == "unresolved":
        reason = "eligibility_unresolved"
    elif candidate.eligibility_state == "not_included":
        reason = "eligibility_not_included"
    elif candidate.attempt_state == "unresolved":
        reason = "attempt_selection_unresolved"
    elif candidate.attempt_state == "not_selected":
        reason = "attempt_not_selected"
    elif candidate.reassessment_state == "unresolved":
        reason = "reassessment_unresolved"
    elif candidate.reassessment_state == "noncontributing":
        reason = "reassessment_noncontributing"
    elif candidate.mapping_outcome is None:
        reason = "mapping_not_supplied"
    elif candidate.mapping_outcome.target_scale != target_scale:
        reason = "scale_mismatch"
    elif candidate.mapping_outcome.status == "unmapped":
        reason = "mapping_unmapped"
    elif candidate.mapping_outcome.status == "unsupported":
        reason = "mapping_unsupported"

    outcome = candidate.mapping_outcome
    if reason is not None:
        return StandardAggregationInputEntry(
            source=candidate.source,
            result_kind=candidate.result_kind,
            target_kind=candidate.target_kind,
            status="excluded",
            exclusion_reason=reason,
            membership_reference=candidate.membership_reference,
            eligibility_reference=candidate.eligibility_reference,
            attempt_selection_reference=candidate.attempt_selection_reference,
            reassessment_reference=candidate.reassessment_reference,
            association_reference=candidate.association_reference,
            mapping_profile_reference=(
                outcome.profile if outcome is not None else None
            ),
            mapping_status=(outcome.status if outcome is not None else None),
            proficiency_level_id=None,
            native_state=None,
        )
    if outcome is None:  # pragma: no cover - handled above
        raise StandardsEvidenceValidationError("operative candidate lacks mapping.")
    if outcome.status == "mapped":
        return StandardAggregationInputEntry(
            source=candidate.source,
            result_kind=candidate.result_kind,
            target_kind=candidate.target_kind,
            status="performance",
            exclusion_reason=None,
            membership_reference=candidate.membership_reference,
            eligibility_reference=candidate.eligibility_reference,
            attempt_selection_reference=candidate.attempt_selection_reference,
            reassessment_reference=candidate.reassessment_reference,
            association_reference=candidate.association_reference,
            mapping_profile_reference=outcome.profile,
            mapping_status=outcome.status,
            proficiency_level_id=outcome.proficiency_level_id,
            native_state=None,
        )
    if outcome.status == "native_state":
        return StandardAggregationInputEntry(
            source=candidate.source,
            result_kind=candidate.result_kind,
            target_kind=candidate.target_kind,
            status="native_state",
            exclusion_reason=None,
            membership_reference=candidate.membership_reference,
            eligibility_reference=candidate.eligibility_reference,
            attempt_selection_reference=candidate.attempt_selection_reference,
            reassessment_reference=candidate.reassessment_reference,
            association_reference=candidate.association_reference,
            mapping_profile_reference=outcome.profile,
            mapping_status=outcome.status,
            proficiency_level_id=None,
            native_state=outcome.native_state,
        )
    raise StandardsEvidenceValidationError("unexpected operative mapping outcome.")


def _aggregation_entry_to_dict(
    value: StandardAggregationInputEntry,
) -> dict[str, object]:
    return {
        "source": evidence_source_reference_to_dict(value.source),
        "result_kind": value.result_kind,
        "target_kind": value.target_kind,
        "status": value.status,
        "exclusion_reason": value.exclusion_reason,
        "membership_reference": _decision_reference_to_dict(value.membership_reference),
        "eligibility_reference": _decision_reference_to_dict(
            value.eligibility_reference
        ),
        "attempt_selection_reference": _decision_reference_to_dict(
            value.attempt_selection_reference
        ),
        "reassessment_reference": _decision_reference_to_dict(
            value.reassessment_reference
        ),
        "association_reference": _association_reference_to_dict(
            value.association_reference
        ),
        "mapping_profile_reference": _profile_reference_to_dict(
            value.mapping_profile_reference
        ),
        "mapping_status": value.mapping_status,
        "proficiency_level_id": value.proficiency_level_id,
        "native_state": _native_state_to_dict(value.native_state),
    }


def _aggregation_entry_from_dict(data: object) -> StandardAggregationInputEntry:
    mapping = _exact_mapping(data, _ENTRY_KEYS, "aggregation entry")
    return StandardAggregationInputEntry(
        source=evidence_source_reference_from_dict(mapping["source"]),
        result_kind=_require_str(mapping["result_kind"], "result_kind"),
        target_kind=_require_str(mapping["target_kind"], "target_kind"),
        status=cast(
            StandardAggregationEntryStatus,
            _require_str(mapping["status"], "status"),
        ),
        exclusion_reason=cast(
            StandardAggregationExclusionReason | None,
            _optional_str(mapping["exclusion_reason"], "exclusion_reason"),
        ),
        membership_reference=_decision_reference_from_dict(
            mapping["membership_reference"]
        ),
        eligibility_reference=_decision_reference_from_dict(
            mapping["eligibility_reference"]
        ),
        attempt_selection_reference=_decision_reference_from_dict(
            mapping["attempt_selection_reference"]
        ),
        reassessment_reference=_decision_reference_from_dict(
            mapping["reassessment_reference"]
        ),
        association_reference=_association_reference_from_dict(
            mapping["association_reference"]
        ),
        mapping_profile_reference=_profile_reference_from_dict(
            mapping["mapping_profile_reference"]
        ),
        mapping_status=cast(
            Literal["mapped", "native_state", "unmapped", "unsupported"] | None,
            _optional_str(mapping["mapping_status"], "mapping_status"),
        ),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"], "proficiency_level_id"
        ),
        native_state=_native_state_from_dict(mapping["native_state"]),
    )


def _decision_reference_to_dict(
    value: AggregationDecisionReference | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "decision_kind": value.decision_kind,
        "revision": value.revision,
        "decision_sha256": value.decision_sha256,
    }


def _decision_reference_from_dict(
    data: object,
) -> AggregationDecisionReference | None:
    if data is None:
        return None
    mapping = _exact_mapping(data, _DECISION_REFERENCE_KEYS, "decision reference")
    return AggregationDecisionReference(
        cast(
            Literal["membership", "eligibility", "attempt_selection", "reassessment"],
            _require_str(mapping["decision_kind"], "decision_kind"),
        ),
        _require_int(mapping["revision"], "revision"),
        _require_str(mapping["decision_sha256"], "decision_sha256"),
    )


def _association_reference_to_dict(
    value: StandardEvidenceAssociationReference | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "source": evidence_source_reference_to_dict(value.source),
        "standard_id": value.standard_id,
        "association_revision": value.association_revision,
        "decision_sha256": value.decision_sha256,
    }


def _association_reference_from_dict(
    data: object,
) -> StandardEvidenceAssociationReference | None:
    if data is None:
        return None
    mapping = _exact_mapping(data, _ASSOCIATION_REFERENCE_KEYS, "association reference")
    return StandardEvidenceAssociationReference(
        _require_str(mapping["class_id"], "association.class_id"),
        _require_str(mapping["grade_item_id"], "association.grade_item_id"),
        evidence_source_reference_from_dict(mapping["source"]),
        _require_str(mapping["standard_id"], "association.standard_id"),
        _require_int(
            mapping["association_revision"], "association.association_revision"
        ),
        _require_str(mapping["decision_sha256"], "association.decision_sha256"),
    )


def _profile_reference_to_dict(
    value: NativeValueMappingProfileReference | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "profile_id": value.profile_id,
        "profile_revision": value.profile_revision,
        "profile_sha256": value.profile_sha256,
    }


def _profile_reference_from_dict(
    data: object,
) -> NativeValueMappingProfileReference | None:
    if data is None:
        return None
    mapping = _exact_mapping(data, _PROFILE_REFERENCE_KEYS, "mapping profile reference")
    return NativeValueMappingProfileReference(
        _require_str(mapping["class_id"], "profile.class_id"),
        _require_str(mapping["scale_id"], "profile.scale_id"),
        _require_str(mapping["profile_id"], "profile.profile_id"),
        _require_int(mapping["profile_revision"], "profile.profile_revision"),
        _require_str(mapping["profile_sha256"], "profile.profile_sha256"),
    )


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _native_state_to_dict(value: NativeStateValue | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"code": value.code, "label": value.label, "description": value.description}


def _native_state_from_dict(data: object) -> NativeStateValue | None:
    if data is None:
        return None
    mapping = _exact_mapping(data, _NATIVE_STATE_KEYS, "native state")
    return NativeStateValue(
        _require_str(mapping["code"], "native_state.code"),
        _optional_str(mapping["label"], "native_state.label"),
        _optional_str(mapping["description"], "native_state.description"),
    )


def _standard_id(value: object) -> str:
    return normalize_standard_id(value)


def normalize_standard_id(value: object) -> str:
    """Match Core v0.6.3 durable standard-ID required-text semantics."""
    if not isinstance(value, str):
        raise StandardsEvidenceValidationError("standard_id must be a string.")
    normalized = value.strip()
    if not normalized:
        raise StandardsEvidenceValidationError("standard_id must not be blank.")
    return normalized


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsEvidenceValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardsEvidenceValidationError(str(error)) from error


def _code(value: object, field_name: str) -> str:
    text = _bounded_text(value, field_name, 256)
    if re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", text) is None:
        raise StandardsEvidenceValidationError(f"{field_name} must be a contract code.")
    return text


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StandardsEvidenceValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardsEvidenceValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise StandardsEvidenceValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise StandardsEvidenceValidationError(
            f"{field_name} must be nonempty without surrounding whitespace."
        )
    if len(value) > maximum:
        raise StandardsEvidenceValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise StandardsEvidenceValidationError(
            f"{field_name} must not contain control characters."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise StandardsEvidenceValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _datetime_to_text(value: datetime) -> str:
    return (
        _aware_utc_datetime(value, "timestamp")
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    if not text.endswith("Z"):
        raise StandardsEvidenceValidationError(f"{field_name} must use UTC Z.")
    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise StandardsEvidenceValidationError(f"{field_name} is invalid.") from error
    if _datetime_to_text(result) != text:
        raise StandardsEvidenceValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    return result.astimezone(UTC)


def _typed_tuple(
    values: object, item_type: type[_T], field_name: str
) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes)):
        raise StandardsEvidenceValidationError(f"{field_name} must be an iterable.")
    try:
        result = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise StandardsEvidenceValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(item, item_type) for item in result):
        raise StandardsEvidenceValidationError(
            f"{field_name} contains an invalid item."
        )
    return cast(tuple[_T, ...], result)


def _exact_mapping(
    value: object, keys: frozenset[str], label: str
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StandardsEvidenceSerializationError(f"{label} must be a JSON object.")
    actual = frozenset(value)
    if actual != keys:
        raise StandardsEvidenceSerializationError(
            f"{label} does not use exact schema "
            f"(missing={sorted(keys - actual)}, unknown={sorted(actual - keys)})."
        )
    return cast(dict[str, object], value)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsEvidenceValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StandardsEvidenceValidationError(f"{field_name} must be an integer.")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True
        )
    except (TypeError, ValueError) as error:
        raise StandardsEvidenceSerializationError(
            "standards-evidence value cannot be serialized canonically."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StandardsEvidenceSerializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StandardsEvidenceSerializationError(
        f"non-finite JSON value is invalid: {value}"
    )


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise StandardsEvidenceSerializationError(f"{label} input must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StandardsEvidenceSerializationError(f"{label} must be UTF-8.") from error
    try:
        return json.loads(
            text, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except StandardsEvidenceSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StandardsEvidenceSerializationError(
            f"{label} JSON is invalid."
        ) from error
