"""Teacher-controlled policy for deriving contextual grouping-signal bands.

This module defines only immutable Meridian policy state.  It does not resolve
student results, assign students to bands, create Core grouping signals, preview
class distributions, export files, or form Concord groups.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
    academic_period_proficiency_aggregation_policy_reference_from_dict,
    academic_period_proficiency_aggregation_policy_reference_to_dict,
    academic_period_proficiency_target_from_dict,
    academic_period_proficiency_target_to_dict,
    validate_academic_period_proficiency_aggregation_policy,
)
from meridian.proficiency_mapping import (
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
    validate_proficiency_scale,
)
from meridian.standards_evidence import normalize_standard_id

GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION: Final[str] = "1"
GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE: Final[str] = (
    "meridian_grouping_signal_derivation_policy"
)
MAXIMUM_GROUPING_SIGNAL_POLICY_TITLE_LENGTH: Final[int] = 256
MAXIMUM_GROUPING_SIGNAL_POLICY_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_GROUPING_SIGNAL_POLICY_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES: Final[int] = 256 * 1024

GroupingSignalAcademicBasisKind: TypeAlias = Literal[
    "academic_period_proficiency"
]
GroupingSignalTieHandling: TypeAlias = Literal["same_level_same_band"]
GroupingSignalResultHandling: TypeAlias = Literal["noncontributing", "blocking"]
GroupingSignalPolicyActorKind: TypeAlias = Literal["teacher", "policy"]

_BASIS_KINDS: Final[tuple[GroupingSignalAcademicBasisKind, ...]] = (
    "academic_period_proficiency",
)
_TIE_HANDLINGS: Final[tuple[GroupingSignalTieHandling, ...]] = (
    "same_level_same_band",
)
_RESULT_HANDLINGS: Final[tuple[GroupingSignalResultHandling, ...]] = (
    "noncontributing",
    "blocking",
)
_ACTOR_KINDS: Final[tuple[GroupingSignalPolicyActorKind, ...]] = (
    "teacher",
    "policy",
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "title",
        "academic_basis",
        "dimension_id",
        "band_count",
        "band_definitions",
        "tie_handling",
        "missing_result_handling",
        "insufficient_result_handling",
        "actor",
        "rationale",
        "revised_at",
    }
)
_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "basis_kind",
        "target_period",
        "standard_id",
        "source_policy",
        "target_scale",
    }
)
_BAND_KEYS: Final[frozenset[str]] = frozenset(
    {"band", "minimum_scale_position", "maximum_scale_position"}
)
_POLICY_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "policy_id", "policy_revision", "policy_sha256"}
)
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})


class GroupingSignalPolicyError(ValueError):
    """Base error for grouping-signal derivation policy contracts."""


class GroupingSignalPolicyValidationError(GroupingSignalPolicyError):
    """Raised when grouping-signal policy data violates its contract."""


class GroupingSignalPolicySerializationError(GroupingSignalPolicyError):
    """Raised when grouping-signal policy JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GroupingSignalPolicyActor:
    """Explicit authorship for one immutable derivation-policy revision."""

    kind: GroupingSignalPolicyActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise GroupingSignalPolicyValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_GROUPING_SIGNAL_POLICY_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class GroupingSignalAcademicBasis:
    """Exact #35 Academic Period proficiency interpretation used by the policy."""

    basis_kind: GroupingSignalAcademicBasisKind
    target_period: AcademicPeriodProficiencyTarget
    standard_id: str
    source_policy: AcademicPeriodProficiencyAggregationPolicyReference
    target_scale: ProficiencyScaleReference

    def __post_init__(self) -> None:
        basis_kind = _basis_kind(self.basis_kind)
        if not isinstance(self.target_period, AcademicPeriodProficiencyTarget):
            raise GroupingSignalPolicyValidationError(
                "target_period must be an AcademicPeriodProficiencyTarget."
            )
        # The public #35 serializer revalidates the exact period target.
        try:
            academic_period_proficiency_target_to_dict(self.target_period)
            standard_id = normalize_standard_id(self.standard_id)
        except ValueError as error:
            raise GroupingSignalPolicyValidationError(str(error)) from error
        if not isinstance(
            self.source_policy,
            AcademicPeriodProficiencyAggregationPolicyReference,
        ):
            raise GroupingSignalPolicyValidationError(
                "source_policy must be an exact Academic Period proficiency "
                "policy reference."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise GroupingSignalPolicyValidationError(
                "target_scale must be an exact ProficiencyScaleReference."
            )
        if self.source_policy.class_id != self.target_scale.class_id:
            raise GroupingSignalPolicyValidationError(
                "academic basis source_policy and target_scale class_id must match."
            )
        object.__setattr__(self, "basis_kind", basis_kind)
        object.__setattr__(self, "standard_id", standard_id)

    @property
    def class_id(self) -> str:
        """Return the class scope shared by the exact policy and scale references."""
        return self.source_policy.class_id


@dataclass(frozen=True, slots=True)
class GroupingSignalBandDefinition:
    """One contextual band over a contiguous source-scale position range."""

    band: int
    minimum_scale_position: int
    maximum_scale_position: int

    def __post_init__(self) -> None:
        band = _positive_int(self.band, "band")
        minimum = _positive_int(
            self.minimum_scale_position,
            "minimum_scale_position",
        )
        maximum = _positive_int(
            self.maximum_scale_position,
            "maximum_scale_position",
        )
        if minimum > maximum:
            raise GroupingSignalPolicyValidationError(
                "minimum_scale_position must not exceed maximum_scale_position."
            )
        object.__setattr__(self, "band", band)
        object.__setattr__(self, "minimum_scale_position", minimum)
        object.__setattr__(self, "maximum_scale_position", maximum)


@dataclass(frozen=True, slots=True)
class GroupingSignalDerivationPolicy:
    """One immutable teacher-controlled contextual-band policy revision."""

    schema_version: str
    record_type: str
    class_id: str
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    title: str
    academic_basis: GroupingSignalAcademicBasis
    dimension_id: str
    band_count: int
    band_definitions: tuple[GroupingSignalBandDefinition, ...]
    tie_handling: GroupingSignalTieHandling
    missing_result_handling: GroupingSignalResultHandling
    insufficient_result_handling: GroupingSignalResultHandling
    actor: GroupingSignalPolicyActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION:
            raise GroupingSignalPolicyValidationError(
                "unsupported grouping-signal derivation policy schema_version."
            )
        if self.record_type != GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE:
            raise GroupingSignalPolicyValidationError(
                "record_type must identify a grouping-signal derivation policy."
            )
        class_id = _identifier(self.class_id, "class_id")
        policy_id = _identifier(self.policy_id, "policy_id")
        revision = _positive_int(self.policy_revision, "policy_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_revision_pair(revision, supersedes)
        title = _bounded_text(
            self.title,
            "title",
            MAXIMUM_GROUPING_SIGNAL_POLICY_TITLE_LENGTH,
        )
        if not isinstance(self.academic_basis, GroupingSignalAcademicBasis):
            raise GroupingSignalPolicyValidationError(
                "academic_basis must be a GroupingSignalAcademicBasis."
            )
        if self.academic_basis.class_id != class_id:
            raise GroupingSignalPolicyValidationError(
                "academic_basis class_id must match policy class_id."
            )
        dimension_id = _identifier(self.dimension_id, "dimension_id")
        band_count = _positive_int(self.band_count, "band_count")
        if band_count < 2:
            raise GroupingSignalPolicyValidationError(
                "band_count must be at least 2."
            )
        definitions = _band_definitions(self.band_definitions, band_count)
        tie_handling = _tie_handling(self.tie_handling)
        missing = _result_handling(
            self.missing_result_handling,
            "missing_result_handling",
        )
        insufficient = _result_handling(
            self.insufficient_result_handling,
            "insufficient_result_handling",
        )
        if not isinstance(self.actor, GroupingSignalPolicyActor):
            raise GroupingSignalPolicyValidationError(
                "actor must be a GroupingSignalPolicyActor."
            )
        actor = GroupingSignalPolicyActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_GROUPING_SIGNAL_POLICY_TEXT_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "policy_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "dimension_id", dimension_id)
        object.__setattr__(self, "band_count", band_count)
        object.__setattr__(self, "band_definitions", definitions)
        object.__setattr__(self, "tie_handling", tie_handling)
        object.__setattr__(self, "missing_result_handling", missing)
        object.__setattr__(self, "insufficient_result_handling", insufficient)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class GroupingSignalDerivationPolicyReference:
    """Exact immutable derivation-policy revision and canonical-byte digest."""

    class_id: str
    policy_id: str
    policy_revision: int
    policy_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self,
            "policy_revision",
            _positive_int(self.policy_revision, "policy_revision"),
        )
        object.__setattr__(
            self,
            "policy_sha256",
            _sha256(self.policy_sha256, "policy_sha256"),
        )


def is_grouping_signal_academic_basis_kind(value: object) -> bool:
    """Return whether ``value`` is a supported v1 academic basis kind."""
    return isinstance(value, str) and value in _BASIS_KINDS


def is_grouping_signal_tie_handling(value: object) -> bool:
    """Return whether ``value`` is the supported v1 tie policy."""
    return isinstance(value, str) and value in _TIE_HANDLINGS


def is_grouping_signal_result_handling(value: object) -> bool:
    """Return whether ``value`` is a supported missing/insufficient policy."""
    return isinstance(value, str) and value in _RESULT_HANDLINGS


def validate_grouping_signal_academic_basis_dependencies(
    basis: GroupingSignalAcademicBasis,
    source_policy: AcademicPeriodProficiencyAggregationPolicy,
    target_scale: ProficiencyScale,
) -> GroupingSignalAcademicBasis:
    """Validate one basis against exact persisted #35 policy and scale revisions."""
    if not isinstance(basis, GroupingSignalAcademicBasis):
        raise GroupingSignalPolicyValidationError(
            "basis must be a GroupingSignalAcademicBasis."
        )
    try:
        validated_policy = validate_academic_period_proficiency_aggregation_policy(
            source_policy
        )
        validated_scale = validate_proficiency_scale(target_scale)
        expected_policy_reference = (
            academic_period_proficiency_aggregation_policy_reference(
                validated_policy
            )
        )
        expected_scale_reference = proficiency_scale_reference(validated_scale)
    except ValueError as error:
        raise GroupingSignalPolicyValidationError(str(error)) from error
    if basis.source_policy != expected_policy_reference:
        raise GroupingSignalPolicyValidationError(
            "academic basis does not bind the supplied exact #35 policy revision."
        )
    if basis.target_scale != expected_scale_reference:
        raise GroupingSignalPolicyValidationError(
            "academic basis does not bind the supplied exact proficiency scale."
        )
    if validated_policy.target_scale != expected_scale_reference:
        raise GroupingSignalPolicyValidationError(
            "source #35 policy does not bind the academic basis target scale."
        )
    return basis


def validate_grouping_signal_derivation_policy_against_scale(
    policy: GroupingSignalDerivationPolicy,
    target_scale: ProficiencyScale,
) -> GroupingSignalDerivationPolicy:
    """Validate scale-dependent band constraints against the exact bound scale."""
    value = validate_grouping_signal_derivation_policy(policy)
    try:
        validated_scale = validate_proficiency_scale(target_scale)
        expected_scale_reference = proficiency_scale_reference(validated_scale)
    except ValueError as error:
        raise GroupingSignalPolicyValidationError(str(error)) from error
    if value.academic_basis.target_scale != expected_scale_reference:
        raise GroupingSignalPolicyValidationError(
            "derivation policy does not bind the supplied exact proficiency scale."
        )
    level_count = len(validated_scale.levels)
    if value.band_count > level_count:
        raise GroupingSignalPolicyValidationError(
            "band_count must not exceed the number of source scale levels."
        )
    if value.band_definitions[-1].maximum_scale_position != level_count:
        raise GroupingSignalPolicyValidationError(
            "band definitions must form a complete partition of source scale "
            "positions."
        )
    return value


def validate_grouping_signal_derivation_policy_dependencies(
    policy: GroupingSignalDerivationPolicy,
    source_policy: AcademicPeriodProficiencyAggregationPolicy,
    target_scale: ProficiencyScale,
) -> GroupingSignalDerivationPolicy:
    """Validate all exact academic dependencies needed before policy persistence."""
    value = validate_grouping_signal_derivation_policy(policy)
    validate_grouping_signal_academic_basis_dependencies(
        value.academic_basis,
        source_policy,
        target_scale,
    )
    return validate_grouping_signal_derivation_policy_against_scale(
        value,
        target_scale,
    )


def validate_grouping_signal_derivation_policy(
    value: GroupingSignalDerivationPolicy,
) -> GroupingSignalDerivationPolicy:
    """Revalidate one immutable derivation-policy revision."""
    if not isinstance(value, GroupingSignalDerivationPolicy):
        raise GroupingSignalPolicyValidationError(
            "value must be a GroupingSignalDerivationPolicy."
        )
    value.__post_init__()
    return value


def validate_grouping_signal_derivation_policy_transition(
    previous: GroupingSignalDerivationPolicy,
    candidate: GroupingSignalDerivationPolicy,
) -> GroupingSignalDerivationPolicy:
    """Require one explicit contiguous immutable policy successor revision."""
    before = validate_grouping_signal_derivation_policy(previous)
    after = validate_grouping_signal_derivation_policy(candidate)
    if (before.class_id, before.policy_id) != (after.class_id, after.policy_id):
        raise GroupingSignalPolicyValidationError(
            "policy transition cannot change logical identity."
        )
    if after.policy_revision != before.policy_revision + 1:
        raise GroupingSignalPolicyValidationError(
            "policy revisions must be contiguous."
        )
    if after.supersedes_revision != before.policy_revision:
        raise GroupingSignalPolicyValidationError(
            "supersedes_revision must identify the immediately prior revision."
        )
    if after.revised_at < before.revised_at:
        raise GroupingSignalPolicyValidationError(
            "policy revised_at must be nondecreasing across revisions."
        )
    return after


def grouping_signal_derivation_policy_reference(
    policy: GroupingSignalDerivationPolicy,
) -> GroupingSignalDerivationPolicyReference:
    """Return an exact digest-bound reference to one policy revision."""
    value = validate_grouping_signal_derivation_policy(policy)
    return GroupingSignalDerivationPolicyReference(
        class_id=value.class_id,
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        policy_sha256=grouping_signal_derivation_policy_sha256(value),
    )


def grouping_signal_derivation_policy_sha256(
    value: GroupingSignalDerivationPolicy,
) -> str:
    """Return SHA-256 over exact canonical policy JSON bytes."""
    return hashlib.sha256(
        grouping_signal_derivation_policy_to_json_bytes(value)
    ).hexdigest()


def grouping_signal_derivation_policy_to_dict(
    value: GroupingSignalDerivationPolicy,
) -> dict[str, object]:
    """Convert one validated policy revision to exact JSON-native data."""
    policy = validate_grouping_signal_derivation_policy(value)
    return {
        "schema_version": policy.schema_version,
        "record_type": policy.record_type,
        "class_id": policy.class_id,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "title": policy.title,
        "academic_basis": grouping_signal_academic_basis_to_dict(
            policy.academic_basis
        ),
        "dimension_id": policy.dimension_id,
        "band_count": policy.band_count,
        "band_definitions": [
            grouping_signal_band_definition_to_dict(item)
            for item in policy.band_definitions
        ],
        "tie_handling": policy.tie_handling,
        "missing_result_handling": policy.missing_result_handling,
        "insufficient_result_handling": policy.insufficient_result_handling,
        "actor": _actor_to_dict(policy.actor),
        "rationale": policy.rationale,
        "revised_at": _datetime_to_text(policy.revised_at),
    }


def grouping_signal_derivation_policy_from_dict(
    data: object,
) -> GroupingSignalDerivationPolicy:
    """Parse one exact policy mapping with a closed field set."""
    mapping = _exact_mapping(data, _POLICY_KEYS, "grouping-signal policy")
    definitions_data = _require_list(
        mapping["band_definitions"],
        "band_definitions",
    )
    tie = _require_str(mapping["tie_handling"], "tie_handling")
    missing = _require_str(
        mapping["missing_result_handling"],
        "missing_result_handling",
    )
    insufficient = _require_str(
        mapping["insufficient_result_handling"],
        "insufficient_result_handling",
    )
    return GroupingSignalDerivationPolicy(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(mapping["policy_revision"], "policy_revision"),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        title=_require_str(mapping["title"], "title"),
        academic_basis=grouping_signal_academic_basis_from_dict(
            mapping["academic_basis"]
        ),
        dimension_id=_require_str(mapping["dimension_id"], "dimension_id"),
        band_count=_require_int(mapping["band_count"], "band_count"),
        band_definitions=tuple(
            grouping_signal_band_definition_from_dict(item)
            for item in definitions_data
        ),
        tie_handling=cast(GroupingSignalTieHandling, tie),
        missing_result_handling=cast(GroupingSignalResultHandling, missing),
        insufficient_result_handling=cast(
            GroupingSignalResultHandling,
            insufficient,
        ),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(
            _require_str(mapping["revised_at"], "revised_at"),
            "revised_at",
        ),
    )


def grouping_signal_derivation_policy_to_json_bytes(
    value: GroupingSignalDerivationPolicy,
) -> bytes:
    """Serialize one policy revision as deterministic canonical JSON bytes."""
    payload = _canonical_json_bytes(grouping_signal_derivation_policy_to_dict(value))
    if len(payload) > MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES:
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy exceeds the bounded canonical JSON size."
        )
    return payload


def grouping_signal_derivation_policy_from_json_bytes(
    data: bytes,
) -> GroupingSignalDerivationPolicy:
    """Load only canonical UTF-8 JSON bytes for one policy revision."""
    if not isinstance(data, bytes):
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy JSON must be bytes."
        )
    if len(data) > MAXIMUM_GROUPING_SIGNAL_POLICY_BYTES:
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy exceeds the bounded canonical JSON size."
        )
    parsed = _parse_json_bytes(data)
    value = grouping_signal_derivation_policy_from_dict(parsed)
    if grouping_signal_derivation_policy_to_json_bytes(value) != data:
        raise GroupingSignalPolicySerializationError(
            "grouping-signal derivation policy is not canonical JSON."
        )
    return value


def grouping_signal_academic_basis_to_dict(
    value: GroupingSignalAcademicBasis,
) -> dict[str, object]:
    """Convert one exact academic basis to JSON-native data."""
    if not isinstance(value, GroupingSignalAcademicBasis):
        raise GroupingSignalPolicyValidationError(
            "value must be a GroupingSignalAcademicBasis."
        )
    value.__post_init__()
    return {
        "basis_kind": value.basis_kind,
        "target_period": academic_period_proficiency_target_to_dict(
            value.target_period
        ),
        "standard_id": value.standard_id,
        "source_policy": (
            academic_period_proficiency_aggregation_policy_reference_to_dict(
                value.source_policy
            )
        ),
        "target_scale": _scale_reference_to_dict(value.target_scale),
    }


def grouping_signal_academic_basis_from_dict(
    data: object,
) -> GroupingSignalAcademicBasis:
    """Parse one exact academic-basis mapping."""
    mapping = _exact_mapping(data, _BASIS_KEYS, "grouping-signal academic basis")
    basis_kind = _require_str(mapping["basis_kind"], "basis_kind")
    return GroupingSignalAcademicBasis(
        basis_kind=cast(GroupingSignalAcademicBasisKind, basis_kind),
        target_period=academic_period_proficiency_target_from_dict(
            mapping["target_period"]
        ),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        source_policy=(
            academic_period_proficiency_aggregation_policy_reference_from_dict(
                mapping["source_policy"]
            )
        ),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
    )


def grouping_signal_band_definition_to_dict(
    value: GroupingSignalBandDefinition,
) -> dict[str, object]:
    """Convert one band definition to JSON-native data."""
    if not isinstance(value, GroupingSignalBandDefinition):
        raise GroupingSignalPolicyValidationError(
            "value must be a GroupingSignalBandDefinition."
        )
    value.__post_init__()
    return {
        "band": value.band,
        "minimum_scale_position": value.minimum_scale_position,
        "maximum_scale_position": value.maximum_scale_position,
    }


def grouping_signal_band_definition_from_dict(
    data: object,
) -> GroupingSignalBandDefinition:
    """Parse one exact band-definition mapping."""
    mapping = _exact_mapping(data, _BAND_KEYS, "grouping-signal band definition")
    return GroupingSignalBandDefinition(
        band=_require_int(mapping["band"], "band"),
        minimum_scale_position=_require_int(
            mapping["minimum_scale_position"],
            "minimum_scale_position",
        ),
        maximum_scale_position=_require_int(
            mapping["maximum_scale_position"],
            "maximum_scale_position",
        ),
    )


def grouping_signal_derivation_policy_reference_to_dict(
    value: GroupingSignalDerivationPolicyReference,
) -> dict[str, object]:
    """Convert one exact derivation-policy reference to JSON-native data."""
    if not isinstance(value, GroupingSignalDerivationPolicyReference):
        raise GroupingSignalPolicyValidationError(
            "value must be a GroupingSignalDerivationPolicyReference."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": value.policy_sha256,
    }


def grouping_signal_derivation_policy_reference_from_dict(
    data: object,
) -> GroupingSignalDerivationPolicyReference:
    """Parse one exact derivation-policy reference mapping."""
    mapping = _exact_mapping(
        data,
        _POLICY_REFERENCE_KEYS,
        "grouping-signal policy reference",
    )
    return GroupingSignalDerivationPolicyReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(mapping["policy_revision"], "policy_revision"),
        policy_sha256=_require_str(mapping["policy_sha256"], "policy_sha256"),
    )


def _band_definitions(
    value: object,
    band_count: int,
) -> tuple[GroupingSignalBandDefinition, ...]:
    if not isinstance(value, tuple):
        raise GroupingSignalPolicyValidationError(
            "band_definitions must be a tuple."
        )
    definitions: list[GroupingSignalBandDefinition] = []
    for item in value:
        if not isinstance(item, GroupingSignalBandDefinition):
            raise GroupingSignalPolicyValidationError(
                "band_definitions must contain GroupingSignalBandDefinition values."
            )
        item.__post_init__()
        definitions.append(item)
    if len(definitions) != band_count:
        raise GroupingSignalPolicyValidationError(
            "band_definitions count must equal band_count."
        )
    ordered = tuple(sorted(definitions, key=lambda item: item.band))
    bands = tuple(item.band for item in ordered)
    if bands != tuple(range(1, band_count + 1)):
        raise GroupingSignalPolicyValidationError(
            "band definitions must use each band exactly once from 1..band_count."
        )
    if ordered[0].minimum_scale_position != 1:
        raise GroupingSignalPolicyValidationError(
            "band definitions must start at source scale position 1."
        )
    previous_maximum = 0
    for item in ordered:
        if item.minimum_scale_position != previous_maximum + 1:
            raise GroupingSignalPolicyValidationError(
                "band definitions must be nonoverlapping and contiguous across "
                "source scale positions."
            )
        previous_maximum = item.maximum_scale_position
    return ordered


def _basis_kind(value: object) -> GroupingSignalAcademicBasisKind:
    if value not in _BASIS_KINDS:
        raise GroupingSignalPolicyValidationError(
            "unsupported grouping-signal academic basis kind."
        )
    return value


def _tie_handling(value: object) -> GroupingSignalTieHandling:
    if value not in _TIE_HANDLINGS:
        raise GroupingSignalPolicyValidationError(
            "tie_handling must be same_level_same_band for v1."
        )
    return value


def _result_handling(
    value: object,
    field_name: str,
) -> GroupingSignalResultHandling:
    if value not in _RESULT_HANDLINGS:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be one of: blocking, noncontributing."
        )
    return value


def _actor_to_dict(value: GroupingSignalPolicyActor) -> dict[str, object]:
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> GroupingSignalPolicyActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "grouping-signal policy actor")
    kind = _require_str(mapping["kind"], "kind")
    return GroupingSignalPolicyActor(
        kind=cast(GroupingSignalPolicyActorKind, kind),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    if not isinstance(value, ProficiencyScaleReference):
        raise GroupingSignalPolicyValidationError(
            "value must be a ProficiencyScaleReference."
        )
    value.__post_init__()
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _scale_reference_from_dict(data: object) -> ProficiencyScaleReference:
    mapping = _exact_mapping(
        data,
        _SCALE_REFERENCE_KEYS,
        "proficiency-scale reference",
    )
    return ProficiencyScaleReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        scale_revision=_require_int(mapping["scale_revision"], "scale_revision"),
        scale_sha256=_require_str(mapping["scale_sha256"], "scale_sha256"),
    )


def _validate_revision_pair(revision: int, supersedes: int | None) -> None:
    if revision == 1 and supersedes is not None:
        raise GroupingSignalPolicyValidationError(
            "policy revision 1 must not supersede another revision."
        )
    if revision > 1 and supersedes != revision - 1:
        raise GroupingSignalPolicyValidationError(
            "supersedes_revision must identify the immediately prior revision."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GroupingSignalPolicyValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a string."
        )
    normalized = value.strip()
    if not normalized:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must not be blank."
        )
    if len(normalized) > maximum:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} exceeds the maximum length of {maximum}."
        )
    return normalized


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, maximum)


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_to_text(value: datetime) -> str:
    canonical = _aware_utc_datetime(value, "timestamp")
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(text: str, field_name: str) -> datetime:
    if not text.endswith("Z"):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} is invalid."
        ) from error
    if _datetime_to_text(parsed) != text:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    return parsed.astimezone(UTC)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a lowercase SHA-256 hex digest."
        )
    return value


def _exact_mapping(
    data: object,
    expected_keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise GroupingSignalPolicyValidationError(f"{label} must be a JSON object.")
    if any(not isinstance(key, str) for key in data):
        raise GroupingSignalPolicyValidationError(f"{label} keys must be strings.")
    mapping = cast(dict[str, object], data)
    actual_keys = frozenset(mapping)
    missing = sorted(expected_keys - actual_keys)
    unknown = sorted(actual_keys - expected_keys)
    if missing:
        raise GroupingSignalPolicyValidationError(
            f"{label} is missing required fields: {', '.join(missing)}."
        )
    if unknown:
        raise GroupingSignalPolicyValidationError(
            f"{label} contains unknown fields: {', '.join(unknown)}."
        )
    return mapping


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise GroupingSignalPolicyValidationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


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
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _parse_json_bytes(data: bytes) -> object:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy JSON must be valid UTF-8."
        ) from error

    def object_pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GroupingSignalPolicySerializationError(
                    f"duplicate JSON object key: {key}."
                )
            result[key] = value
        return result

    def parse_constant(value: str) -> object:
        raise GroupingSignalPolicySerializationError(
            f"non-standard JSON numeric constant is not allowed: {value}."
        )

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=object_pairs_hook,
            parse_constant=parse_constant,
        )
    except GroupingSignalPolicySerializationError:
        raise
    except json.JSONDecodeError as error:
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy JSON is invalid."
        ) from error
    if not isinstance(parsed, dict):
        raise GroupingSignalPolicySerializationError(
            "grouping-signal policy JSON must contain a JSON object."
        )
    return parsed
