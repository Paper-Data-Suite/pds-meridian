"""Immutable proficiency scales and producer-native value mapping profiles."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.evidence import (
    EvidenceItem,
    EvidenceValue,
    NativePointValue,
    NativeScalar,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
)

PROFICIENCY_SCALE_SCHEMA_VERSION: Final[str] = "1"
PROFICIENCY_SCALE_RECORD_TYPE: Final[str] = "meridian_proficiency_scale"
NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION: Final[str] = "1"
NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE: Final[str] = (
    "meridian_native_value_mapping_profile"
)
MAXIMUM_PROFICIENCY_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_PROFICIENCY_TITLE_LENGTH: Final[int] = 256
MAXIMUM_PROFICIENCY_ACTOR_ID_LENGTH: Final[int] = 256

MappingActorKind: TypeAlias = Literal["teacher", "policy"]
MappingKind: TypeAlias = Literal["exact_scalar", "exact_native_scale", "raw_points"]
MappingStatus: TypeAlias = Literal["mapped", "unmapped", "unsupported", "native_state"]
UnsupportedReason: TypeAlias = Literal[
    "source_signature_mismatch",
    "value_kind_mismatch",
    "native_scale_mismatch",
    "points_possible_mismatch",
]

_MAPPING_KINDS: Final[tuple[MappingKind, ...]] = (
    "exact_scalar",
    "exact_native_scale",
    "raw_points",
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT_CODE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)
_DISTRIBUTION_NAME: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$"
)

_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"level_id", "position", "label", "description"}
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_SCALE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "scale_id",
        "scale_revision",
        "supersedes_revision",
        "title",
        "description",
        "levels",
        "proficiency_threshold_level_id",
        "actor",
        "rationale",
        "revised_at",
    }
)
_SCALE_REF_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_SOURCE_SIGNATURE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "producer_module_id",
        "publication_kind",
        "manifest_contract_version",
        "producer_contract_version",
        "projection_id",
        "projection_contract_version",
        "producer_reader_distribution",
        "producer_reader_version",
        "result_kind",
        "target_kind",
    }
)
_SCALAR_KEYS: Final[frozenset[str]] = frozenset({"type", "value"})
_NATIVE_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"value", "label", "description", "meaning", "position"}
)
_NATIVE_SCALE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "scale_id",
        "contract_version",
        "order_is_meaningful",
        "lineage_id",
        "name",
        "revision",
        "scale_type",
        "status",
        "supersedes_scale_id",
        "levels",
    }
)
_RULE_SCALAR_KEYS: Final[frozenset[str]] = frozenset(
    {"rule_type", "native_value", "proficiency_level_id"}
)
_RULE_SCALED_KEYS: Final[frozenset[str]] = frozenset(
    {"rule_type", "native_value", "proficiency_level_id"}
)
_RULE_POINTS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "rule_type",
        "minimum_earned",
        "minimum_inclusive",
        "maximum_earned",
        "maximum_inclusive",
        "proficiency_level_id",
    }
)
_PROFILE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "scale_id",
        "profile_id",
        "profile_revision",
        "supersedes_revision",
        "target_scale",
        "source_signature",
        "mapping_kind",
        "native_scale",
        "points_possible",
        "mapping_rules",
        "actor",
        "rationale",
        "revised_at",
    }
)
_PROFILE_REF_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "scale_id",
        "profile_id",
        "profile_revision",
        "profile_sha256",
    }
)
_STATE_KEYS: Final[frozenset[str]] = frozenset({"code", "label", "description"})
_OUTCOME_KEYS: Final[frozenset[str]] = frozenset(
    {
        "status",
        "profile",
        "target_scale",
        "proficiency_level_id",
        "native_state",
        "unsupported_reason",
    }
)

_T = TypeVar("_T")


class ProficiencyMappingError(ValueError):
    """Base error for proficiency-scale and mapping-profile contracts."""


class ProficiencyMappingValidationError(ProficiencyMappingError):
    """Raised when proficiency mapping data violates the domain contract."""


class ProficiencyMappingSerializationError(ProficiencyMappingError):
    """Raised when proficiency mapping JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class MappingActor:
    """Explicit authorship metadata for scale/profile revisions."""

    kind: MappingActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"teacher", "policy"}:
            raise ProficiencyMappingValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_PROFICIENCY_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProficiencyLevel:
    """One ordered criterion-referenced category on a Meridian scale."""

    level_id: str
    position: int
    label: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "level_id", _identifier(self.level_id, "level_id"))
        object.__setattr__(self, "position", _positive_int(self.position, "position"))
        object.__setattr__(
            self,
            "label",
            _bounded_text(self.label, "label", MAXIMUM_PROFICIENCY_TITLE_LENGTH),
        )
        object.__setattr__(
            self,
            "description",
            _bounded_text(
                self.description,
                "description",
                MAXIMUM_PROFICIENCY_TEXT_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProficiencyScale:
    """One immutable teacher-defined proficiency-scale revision."""

    schema_version: str
    record_type: str
    class_id: str
    scale_id: str
    scale_revision: int
    supersedes_revision: int | None
    title: str
    description: str
    levels: tuple[ProficiencyLevel, ...]
    proficiency_threshold_level_id: str
    actor: MappingActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != PROFICIENCY_SCALE_SCHEMA_VERSION:
            raise ProficiencyMappingValidationError(
                "unsupported proficiency-scale schema_version."
            )
        if self.record_type != PROFICIENCY_SCALE_RECORD_TYPE:
            raise ProficiencyMappingValidationError(
                "record_type must identify a Meridian proficiency scale."
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "scale_id", _identifier(self.scale_id, "scale_id"))
        revision = _positive_int(self.scale_revision, "scale_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision, "supersedes_revision"
        )
        _validate_revision_pair(revision, supersedes, "scale")
        object.__setattr__(self, "scale_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(
            self,
            "title",
            _bounded_text(self.title, "title", MAXIMUM_PROFICIENCY_TITLE_LENGTH),
        )
        object.__setattr__(
            self,
            "description",
            _bounded_text(
                self.description,
                "description",
                MAXIMUM_PROFICIENCY_TEXT_LENGTH,
            ),
        )
        levels = _typed_tuple(self.levels, ProficiencyLevel, "levels")
        if not levels:
            raise ProficiencyMappingValidationError("levels must not be empty.")
        if len({level.level_id for level in levels}) != len(levels):
            raise ProficiencyMappingValidationError(
                "proficiency level IDs must not contain duplicates."
            )
        positions = tuple(level.position for level in levels)
        if len(set(positions)) != len(positions):
            raise ProficiencyMappingValidationError(
                "proficiency level positions must not contain duplicates."
            )
        if positions != tuple(range(1, len(levels) + 1)):
            raise ProficiencyMappingValidationError(
                "proficiency levels must be ordered by contiguous positions "
                "starting at 1."
            )
        threshold = _identifier(
            self.proficiency_threshold_level_id,
            "proficiency_threshold_level_id",
        )
        if threshold not in {level.level_id for level in levels}:
            raise ProficiencyMappingValidationError(
                "proficiency_threshold_level_id must identify one scale level."
            )
        if not isinstance(self.actor, MappingActor):
            raise ProficiencyMappingValidationError("actor must be a MappingActor.")
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_PROFICIENCY_TEXT_LENGTH,
        )
        object.__setattr__(self, "levels", levels)
        object.__setattr__(self, "proficiency_threshold_level_id", threshold)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(
            self,
            "revised_at",
            _aware_utc_datetime(self.revised_at, "revised_at"),
        )


@dataclass(frozen=True, slots=True)
class ProficiencyScaleReference:
    """Exact immutable proficiency-scale revision and digest."""

    class_id: str
    scale_id: str
    scale_revision: int
    scale_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "scale_id", _identifier(self.scale_id, "scale_id"))
        object.__setattr__(
            self,
            "scale_revision",
            _positive_int(self.scale_revision, "scale_revision"),
        )
        object.__setattr__(
            self,
            "scale_sha256",
            _sha256(self.scale_sha256, "scale_sha256"),
        )


@dataclass(frozen=True, slots=True)
class NativeValueSourceSignature:
    """Exact producer/result semantic family supported by one mapping profile."""

    producer_module_id: str
    publication_kind: str
    manifest_contract_version: str
    producer_contract_version: str | None
    projection_id: str
    projection_contract_version: str
    producer_reader_distribution: str
    producer_reader_version: str
    result_kind: str
    target_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "producer_module_id",
            _identifier(self.producer_module_id, "producer_module_id"),
        )
        object.__setattr__(
            self,
            "publication_kind",
            _contract_code(self.publication_kind, "publication_kind"),
        )
        object.__setattr__(
            self,
            "manifest_contract_version",
            _bounded_text(
                self.manifest_contract_version,
                "manifest_contract_version",
                MAXIMUM_PROFICIENCY_TITLE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "producer_contract_version",
            _optional_bounded_text(
                self.producer_contract_version,
                "producer_contract_version",
                MAXIMUM_PROFICIENCY_TITLE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "projection_id",
            _contract_code(self.projection_id, "projection_id"),
        )
        object.__setattr__(
            self,
            "projection_contract_version",
            _bounded_text(
                self.projection_contract_version,
                "projection_contract_version",
                MAXIMUM_PROFICIENCY_TITLE_LENGTH,
            ),
        )
        distribution = _bounded_text(
            self.producer_reader_distribution,
            "producer_reader_distribution",
            MAXIMUM_PROFICIENCY_TITLE_LENGTH,
        )
        if _DISTRIBUTION_NAME.fullmatch(distribution) is None:
            raise ProficiencyMappingValidationError(
                "producer_reader_distribution is not a valid distribution name."
            )
        object.__setattr__(self, "producer_reader_distribution", distribution)
        object.__setattr__(
            self,
            "producer_reader_version",
            _bounded_text(
                self.producer_reader_version,
                "producer_reader_version",
                MAXIMUM_PROFICIENCY_TITLE_LENGTH,
            ),
        )
        object.__setattr__(
            self, "result_kind", _contract_code(self.result_kind, "result_kind")
        )
        object.__setattr__(
            self, "target_kind", _contract_code(self.target_kind, "target_kind")
        )


@dataclass(frozen=True, slots=True, eq=False)
class ScalarMappingRule:
    """Exact scalar-to-proficiency mapping rule."""

    native_value: NativeScalar
    proficiency_level_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "native_value", _native_scalar(self.native_value, "native_value")
        )
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ScalarMappingRule) and (
            _scalar_key(self.native_value) == _scalar_key(other.native_value)
            and self.proficiency_level_id == other.proficiency_level_id
        )

    def __hash__(self) -> int:
        return hash((_scalar_key(self.native_value), self.proficiency_level_id))


@dataclass(frozen=True, slots=True, eq=False)
class ScaledLevelMappingRule:
    """Exact native-scale-level-to-proficiency mapping rule."""

    native_value: NativeScalar
    proficiency_level_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "native_value", _native_scalar(self.native_value, "native_value")
        )
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ScaledLevelMappingRule) and (
            _scalar_key(self.native_value) == _scalar_key(other.native_value)
            and self.proficiency_level_id == other.proficiency_level_id
        )

    def __hash__(self) -> int:
        return hash((_scalar_key(self.native_value), self.proficiency_level_id))


@dataclass(frozen=True, slots=True)
class PointRangeMappingRule:
    """Explicit earned-point interval mapped to one proficiency level."""

    minimum_earned: int | float | None
    minimum_inclusive: bool
    maximum_earned: int | float | None
    maximum_inclusive: bool
    proficiency_level_id: str

    def __post_init__(self) -> None:
        minimum = _optional_finite_number(self.minimum_earned, "minimum_earned")
        maximum = _optional_finite_number(self.maximum_earned, "maximum_earned")
        if not isinstance(self.minimum_inclusive, bool):
            raise ProficiencyMappingValidationError(
                "minimum_inclusive must be boolean."
            )
        if not isinstance(self.maximum_inclusive, bool):
            raise ProficiencyMappingValidationError(
                "maximum_inclusive must be boolean."
            )
        if minimum is None and self.minimum_inclusive:
            raise ProficiencyMappingValidationError(
                "an open lower bound cannot be inclusive."
            )
        if maximum is None and self.maximum_inclusive:
            raise ProficiencyMappingValidationError(
                "an open upper bound cannot be inclusive."
            )
        if minimum is not None and maximum is not None:
            if minimum > maximum:
                raise ProficiencyMappingValidationError(
                    "minimum_earned must not exceed maximum_earned."
                )
            if minimum == maximum and not (
                self.minimum_inclusive and self.maximum_inclusive
            ):
                raise ProficiencyMappingValidationError(
                    "equal point bounds require an inclusive singleton range."
                )
        object.__setattr__(self, "minimum_earned", minimum)
        object.__setattr__(self, "maximum_earned", maximum)
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )


MappingRule: TypeAlias = (
    ScalarMappingRule | ScaledLevelMappingRule | PointRangeMappingRule
)


@dataclass(frozen=True, slots=True)
class NativeValueMappingProfile:
    """One immutable explicit native-value mapping-profile revision."""

    schema_version: str
    record_type: str
    class_id: str
    scale_id: str
    profile_id: str
    profile_revision: int
    supersedes_revision: int | None
    target_scale: ProficiencyScaleReference
    source_signature: NativeValueSourceSignature
    mapping_kind: MappingKind
    native_scale: NativeScale | None
    points_possible: int | float | None
    mapping_rules: tuple[MappingRule, ...]
    actor: MappingActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION:
            raise ProficiencyMappingValidationError(
                "unsupported mapping-profile schema_version."
            )
        if self.record_type != NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE:
            raise ProficiencyMappingValidationError(
                "record_type must identify a Meridian native-value mapping profile."
            )
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "scale_id", _identifier(self.scale_id, "scale_id"))
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        revision = _positive_int(self.profile_revision, "profile_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision, "supersedes_revision"
        )
        _validate_revision_pair(revision, supersedes, "profile")
        object.__setattr__(self, "profile_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise ProficiencyMappingValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if (
            self.target_scale.class_id != self.class_id
            or self.target_scale.scale_id != self.scale_id
        ):
            raise ProficiencyMappingValidationError(
                "target_scale must match the profile class and scale family."
            )
        if not isinstance(self.source_signature, NativeValueSourceSignature):
            raise ProficiencyMappingValidationError(
                "source_signature must be a NativeValueSourceSignature."
            )
        if self.mapping_kind not in set(_MAPPING_KINDS):
            raise ProficiencyMappingValidationError("unsupported mapping_kind.")
        if self.native_scale is not None and not isinstance(
            self.native_scale, NativeScale
        ):
            raise ProficiencyMappingValidationError(
                "native_scale must be a NativeScale or None."
            )
        points_possible = _optional_finite_number(
            self.points_possible, "points_possible"
        )
        if points_possible is not None and points_possible <= 0:
            raise ProficiencyMappingValidationError(
                "points_possible must be greater than zero."
            )
        rules = _mapping_rules(self.mapping_rules)
        if not rules:
            raise ProficiencyMappingValidationError(
                "mapping_rules must contain at least one explicit rule."
            )
        if self.mapping_kind == "exact_scalar":
            if self.native_scale is not None or points_possible is not None:
                raise ProficiencyMappingValidationError(
                    "exact_scalar profiles must not bind a native scale or "
                    "points possible."
                )
            if any(not isinstance(rule, ScalarMappingRule) for rule in rules):
                raise ProficiencyMappingValidationError(
                    "exact_scalar profiles require only ScalarMappingRule values."
                )
            keys = [
                _scalar_key(cast(ScalarMappingRule, rule).native_value)
                for rule in rules
            ]
            if len(set(keys)) != len(keys):
                raise ProficiencyMappingValidationError(
                    "exact scalar mapping rules must not duplicate native values."
                )
        elif self.mapping_kind == "exact_native_scale":
            if self.native_scale is None or points_possible is not None:
                raise ProficiencyMappingValidationError(
                    "exact_native_scale profiles require a native scale and no "
                    "points possible."
                )
            if any(not isinstance(rule, ScaledLevelMappingRule) for rule in rules):
                raise ProficiencyMappingValidationError(
                    "exact_native_scale profiles require only "
                    "ScaledLevelMappingRule values."
                )
            native_keys = {
                _scalar_key(level.value) for level in self.native_scale.levels
            }
            keys = [
                _scalar_key(cast(ScaledLevelMappingRule, rule).native_value)
                for rule in rules
            ]
            if len(set(keys)) != len(keys):
                raise ProficiencyMappingValidationError(
                    "native-scale mapping rules must not duplicate native values."
                )
            if any(key not in native_keys for key in keys):
                raise ProficiencyMappingValidationError(
                    "every native-scale rule must identify an exact bound scale level."
                )
        else:
            if self.native_scale is not None or points_possible is None:
                raise ProficiencyMappingValidationError(
                    "raw_points profiles require points_possible and no native scale."
                )
            if any(not isinstance(rule, PointRangeMappingRule) for rule in rules):
                raise ProficiencyMappingValidationError(
                    "raw_points profiles require only PointRangeMappingRule values."
                )
            _validate_point_range_sequence(
                tuple(cast(PointRangeMappingRule, rule) for rule in rules)
            )
        if not isinstance(self.actor, MappingActor):
            raise ProficiencyMappingValidationError("actor must be a MappingActor.")
        object.__setattr__(self, "points_possible", points_possible)
        object.__setattr__(self, "mapping_rules", rules)
        object.__setattr__(
            self,
            "rationale",
            _optional_bounded_text(
                self.rationale,
                "rationale",
                MAXIMUM_PROFICIENCY_TEXT_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "revised_at",
            _aware_utc_datetime(self.revised_at, "revised_at"),
        )


@dataclass(frozen=True, slots=True)
class NativeValueMappingProfileReference:
    """Exact immutable mapping-profile revision and digest."""

    class_id: str
    scale_id: str
    profile_id: str
    profile_revision: int
    profile_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(self, "scale_id", _identifier(self.scale_id, "scale_id"))
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self,
            "profile_revision",
            _positive_int(self.profile_revision, "profile_revision"),
        )
        object.__setattr__(
            self,
            "profile_sha256",
            _sha256(self.profile_sha256, "profile_sha256"),
        )


@dataclass(frozen=True, slots=True)
class NativeValueMappingOutcome:
    """Pure typed interpretation result for one native value/profile pair."""

    status: MappingStatus
    profile: NativeValueMappingProfileReference
    target_scale: ProficiencyScaleReference
    proficiency_level_id: str | None = None
    native_state: NativeStateValue | None = None
    unsupported_reason: UnsupportedReason | None = None

    def __post_init__(self) -> None:
        if self.status not in {"mapped", "unmapped", "unsupported", "native_state"}:
            raise ProficiencyMappingValidationError(
                "unsupported mapping outcome status."
            )
        if not isinstance(self.profile, NativeValueMappingProfileReference):
            raise ProficiencyMappingValidationError(
                "profile must be a NativeValueMappingProfileReference."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise ProficiencyMappingValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        if self.native_state is not None and not isinstance(
            self.native_state, NativeStateValue
        ):
            raise ProficiencyMappingValidationError(
                "native_state must be a NativeStateValue or None."
            )
        if self.status == "mapped":
            if (
                level_id is None
                or self.native_state is not None
                or self.unsupported_reason is not None
            ):
                raise ProficiencyMappingValidationError(
                    "mapped outcomes require only a proficiency level."
                )
        elif self.status == "native_state":
            if (
                self.native_state is None
                or level_id is not None
                or self.unsupported_reason is not None
            ):
                raise ProficiencyMappingValidationError(
                    "native_state outcomes require only the exact native state."
                )
        elif self.status == "unsupported":
            if (
                self.unsupported_reason is None
                or level_id is not None
                or self.native_state is not None
            ):
                raise ProficiencyMappingValidationError(
                    "unsupported outcomes require only an unsupported reason."
                )
        else:
            if (
                level_id is not None
                or self.native_state is not None
                or self.unsupported_reason is not None
            ):
                raise ProficiencyMappingValidationError(
                    "unmapped outcomes must not carry a mapped value or reason."
                )
        object.__setattr__(self, "proficiency_level_id", level_id)


def validate_proficiency_scale(value: ProficiencyScale) -> ProficiencyScale:
    if not isinstance(value, ProficiencyScale):
        raise ProficiencyMappingValidationError(
            "value must be a ProficiencyScale."
        )
    value.__post_init__()
    return value


def validate_proficiency_scale_transition(
    previous: ProficiencyScale,
    current: ProficiencyScale,
) -> ProficiencyScale:
    validate_proficiency_scale(previous)
    validate_proficiency_scale(current)
    if (previous.class_id, previous.scale_id) != (current.class_id, current.scale_id):
        raise ProficiencyMappingValidationError(
            "proficiency-scale logical identity cannot change across revisions."
        )
    if current.scale_revision != previous.scale_revision + 1:
        raise ProficiencyMappingValidationError(
            "proficiency-scale revisions must be contiguous."
        )
    if current.supersedes_revision != previous.scale_revision:
        raise ProficiencyMappingValidationError(
            "proficiency-scale supersedes_revision must identify the prior revision."
        )
    if current.revised_at < previous.revised_at:
        raise ProficiencyMappingValidationError(
            "proficiency-scale revised_at must be nondecreasing."
        )
    return current


def validate_native_value_mapping_profile(
    value: NativeValueMappingProfile,
) -> NativeValueMappingProfile:
    if not isinstance(value, NativeValueMappingProfile):
        raise ProficiencyMappingValidationError(
            "value must be a NativeValueMappingProfile."
        )
    value.__post_init__()
    return value


def validate_native_value_mapping_profile_transition(
    previous: NativeValueMappingProfile,
    current: NativeValueMappingProfile,
) -> NativeValueMappingProfile:
    validate_native_value_mapping_profile(previous)
    validate_native_value_mapping_profile(current)
    if (
        previous.class_id,
        previous.scale_id,
        previous.profile_id,
    ) != (current.class_id, current.scale_id, current.profile_id):
        raise ProficiencyMappingValidationError(
            "mapping-profile logical identity cannot change across revisions."
        )
    if current.profile_revision != previous.profile_revision + 1:
        raise ProficiencyMappingValidationError(
            "mapping-profile revisions must be contiguous."
        )
    if current.supersedes_revision != previous.profile_revision:
        raise ProficiencyMappingValidationError(
            "mapping-profile supersedes_revision must identify the prior revision."
        )
    if current.revised_at < previous.revised_at:
        raise ProficiencyMappingValidationError(
            "mapping-profile revised_at must be nondecreasing."
        )
    return current


def validate_native_value_mapping_profile_against_scale(
    profile: NativeValueMappingProfile,
    scale: ProficiencyScale,
) -> NativeValueMappingProfile:
    """Validate target-level references and monotonic rules against exact scale."""
    validate_native_value_mapping_profile(profile)
    validate_proficiency_scale(scale)
    expected = proficiency_scale_reference(scale)
    if profile.target_scale != expected:
        raise ProficiencyMappingValidationError(
            "mapping profile does not bind this exact proficiency-scale revision."
        )
    positions = {level.level_id: level.position for level in scale.levels}
    rule_levels = tuple(rule.proficiency_level_id for rule in profile.mapping_rules)
    if any(level_id not in positions for level_id in rule_levels):
        raise ProficiencyMappingValidationError(
            "mapping rules must reference levels on the exact target scale."
        )
    if profile.mapping_kind == "exact_native_scale":
        native_scale = profile.native_scale
        if native_scale is None:  # defensive; model rejects this
            raise ProficiencyMappingValidationError("native scale is required.")
        if native_scale.order_is_meaningful:
            by_native = {
                _scalar_key(cast(ScaledLevelMappingRule, rule).native_value): positions[
                    rule.proficiency_level_id
                ]
                for rule in profile.mapping_rules
            }
            mapped_positions = [
                by_native[key]
                for key in (_scalar_key(level.value) for level in native_scale.levels)
                if key in by_native
            ]
            if mapped_positions != sorted(mapped_positions):
                raise ProficiencyMappingValidationError(
                    "ordered native-scale mappings must not invert proficiency order."
                )
    elif profile.mapping_kind == "raw_points":
        range_positions = [
            positions[cast(PointRangeMappingRule, rule).proficiency_level_id]
            for rule in profile.mapping_rules
        ]
        if range_positions != sorted(range_positions):
            raise ProficiencyMappingValidationError(
                "higher earned-point ranges must not map to lower proficiency levels."
            )
    return profile


def native_value_source_signature_from_item(
    item: EvidenceItem,
) -> NativeValueSourceSignature:
    """Derive the exact generic source-semantic signature from one evidence item."""
    if not isinstance(item, EvidenceItem):
        raise ProficiencyMappingValidationError("item must be an EvidenceItem.")
    provenance = item.provenance
    return NativeValueSourceSignature(
        producer_module_id=provenance.producer_module_id,
        publication_kind=provenance.publication_kind,
        manifest_contract_version=provenance.manifest_contract_version,
        producer_contract_version=provenance.producer_contract_version,
        projection_id=provenance.projection.projection_id,
        projection_contract_version=provenance.projection.projection_contract_version,
        producer_reader_distribution=provenance.projection.producer_reader_distribution,
        producer_reader_version=provenance.projection.producer_reader_version,
        result_kind=item.result_kind,
        target_kind=item.target.target_kind,
    )


def proficiency_scale_reference(scale: ProficiencyScale) -> ProficiencyScaleReference:
    validate_proficiency_scale(scale)
    return ProficiencyScaleReference(
        class_id=scale.class_id,
        scale_id=scale.scale_id,
        scale_revision=scale.scale_revision,
        scale_sha256=hashlib.sha256(proficiency_scale_to_json_bytes(scale)).hexdigest(),
    )


def native_value_mapping_profile_reference(
    profile: NativeValueMappingProfile,
) -> NativeValueMappingProfileReference:
    validate_native_value_mapping_profile(profile)
    return NativeValueMappingProfileReference(
        class_id=profile.class_id,
        scale_id=profile.scale_id,
        profile_id=profile.profile_id,
        profile_revision=profile.profile_revision,
        profile_sha256=hashlib.sha256(
            native_value_mapping_profile_to_json_bytes(profile)
        ).hexdigest(),
    )


def map_native_value(
    value: EvidenceValue,
    source_signature: NativeValueSourceSignature,
    profile: NativeValueMappingProfile,
    scale: ProficiencyScale,
) -> NativeValueMappingOutcome:
    """Purely map one exact native value through one exact profile and scale."""
    if not isinstance(
        value,
        (NativeScalarValue, NativePointValue, NativeScaledValue, NativeStateValue),
    ):
        raise ProficiencyMappingValidationError(
            "value is not a supported EvidenceValue."
        )
    if not isinstance(source_signature, NativeValueSourceSignature):
        raise ProficiencyMappingValidationError(
            "source_signature must be a NativeValueSourceSignature."
        )
    validate_native_value_mapping_profile_against_scale(profile, scale)
    profile_ref = native_value_mapping_profile_reference(profile)
    scale_ref = proficiency_scale_reference(scale)
    if source_signature != profile.source_signature:
        return NativeValueMappingOutcome(
            status="unsupported",
            profile=profile_ref,
            target_scale=scale_ref,
            unsupported_reason="source_signature_mismatch",
        )
    if isinstance(value, NativeStateValue):
        return NativeValueMappingOutcome(
            status="native_state",
            profile=profile_ref,
            target_scale=scale_ref,
            native_state=value,
        )
    if profile.mapping_kind == "exact_scalar":
        if not isinstance(value, NativeScalarValue):
            return _unsupported(profile_ref, scale_ref, "value_kind_mismatch")
        key = _scalar_key(value.value)
        for rule in profile.mapping_rules:
            scalar_rule = cast(ScalarMappingRule, rule)
            if _scalar_key(scalar_rule.native_value) == key:
                return _mapped(profile_ref, scale_ref, scalar_rule.proficiency_level_id)
        return _unmapped(profile_ref, scale_ref)
    if profile.mapping_kind == "exact_native_scale":
        if not isinstance(value, NativeScaledValue):
            return _unsupported(profile_ref, scale_ref, "value_kind_mismatch")
        if value.scale != profile.native_scale:
            return _unsupported(profile_ref, scale_ref, "native_scale_mismatch")
        key = _scalar_key(value.value)
        for rule in profile.mapping_rules:
            scaled_rule = cast(ScaledLevelMappingRule, rule)
            if _scalar_key(scaled_rule.native_value) == key:
                return _mapped(profile_ref, scale_ref, scaled_rule.proficiency_level_id)
        return _unmapped(profile_ref, scale_ref)
    if not isinstance(value, NativePointValue):
        return _unsupported(profile_ref, scale_ref, "value_kind_mismatch")
    if _number_key(value.possible) != _number_key(
        cast(int | float, profile.points_possible)
    ):
        return _unsupported(profile_ref, scale_ref, "points_possible_mismatch")
    matches = [
        cast(PointRangeMappingRule, rule)
        for rule in profile.mapping_rules
        if _point_range_contains(cast(PointRangeMappingRule, rule), value.earned)
    ]
    if not matches:
        return _unmapped(profile_ref, scale_ref)
    if len(matches) != 1:  # defensive; profile validation forbids overlap
        raise ProficiencyMappingValidationError(
            "raw-point mapping unexpectedly matched more than one range."
        )
    return _mapped(profile_ref, scale_ref, matches[0].proficiency_level_id)


def map_evidence_item(
    item: EvidenceItem,
    profile: NativeValueMappingProfile,
    scale: ProficiencyScale,
) -> NativeValueMappingOutcome:
    """Map one evidence item without changing eligibility/selection semantics."""
    return map_native_value(
        item.value,
        native_value_source_signature_from_item(item),
        profile,
        scale,
    )


def proficiency_scale_to_dict(value: ProficiencyScale) -> dict[str, object]:
    scale = validate_proficiency_scale(value)
    return {
        "schema_version": scale.schema_version,
        "record_type": scale.record_type,
        "class_id": scale.class_id,
        "scale_id": scale.scale_id,
        "scale_revision": scale.scale_revision,
        "supersedes_revision": scale.supersedes_revision,
        "title": scale.title,
        "description": scale.description,
        "levels": [_proficiency_level_to_dict(level) for level in scale.levels],
        "proficiency_threshold_level_id": scale.proficiency_threshold_level_id,
        "actor": _actor_to_dict(scale.actor),
        "rationale": scale.rationale,
        "revised_at": _datetime_to_text(scale.revised_at),
    }


def proficiency_scale_from_dict(data: object) -> ProficiencyScale:
    mapping = _exact_mapping(data, _SCALE_KEYS, "proficiency scale")
    return ProficiencyScale(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        scale_revision=_require_int(mapping["scale_revision"], "scale_revision"),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        title=_require_str(mapping["title"], "title"),
        description=_require_str(mapping["description"], "description"),
        levels=tuple(
            _proficiency_level_from_dict(item)
            for item in _require_list(mapping["levels"], "levels")
        ),
        proficiency_threshold_level_id=_require_str(
            mapping["proficiency_threshold_level_id"],
            "proficiency_threshold_level_id",
        ),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def proficiency_scale_to_json_bytes(value: ProficiencyScale) -> bytes:
    return _canonical_json_bytes(proficiency_scale_to_dict(value))


def proficiency_scale_from_json_bytes(data: bytes) -> ProficiencyScale:
    value = proficiency_scale_from_dict(_decode_json(data, "proficiency scale"))
    if proficiency_scale_to_json_bytes(value) != data:
        raise ProficiencyMappingSerializationError(
            "proficiency-scale bytes are not canonically encoded."
        )
    return value


def native_value_mapping_profile_to_dict(
    value: NativeValueMappingProfile,
) -> dict[str, object]:
    profile = validate_native_value_mapping_profile(value)
    return {
        "schema_version": profile.schema_version,
        "record_type": profile.record_type,
        "class_id": profile.class_id,
        "scale_id": profile.scale_id,
        "profile_id": profile.profile_id,
        "profile_revision": profile.profile_revision,
        "supersedes_revision": profile.supersedes_revision,
        "target_scale": _scale_ref_to_dict(profile.target_scale),
        "source_signature": _source_signature_to_dict(profile.source_signature),
        "mapping_kind": profile.mapping_kind,
        "native_scale": (
            None
            if profile.native_scale is None
            else _native_scale_to_dict(profile.native_scale)
        ),
        "points_possible": profile.points_possible,
        "mapping_rules": [
            _mapping_rule_to_dict(rule) for rule in profile.mapping_rules
        ],
        "actor": _actor_to_dict(profile.actor),
        "rationale": profile.rationale,
        "revised_at": _datetime_to_text(profile.revised_at),
    }


def native_value_mapping_profile_from_dict(data: object) -> NativeValueMappingProfile:
    mapping = _exact_mapping(data, _PROFILE_KEYS, "native-value mapping profile")
    mapping_kind = _mapping_kind(mapping["mapping_kind"])
    native_scale_data = mapping["native_scale"]
    return NativeValueMappingProfile(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        profile_revision=_require_int(mapping["profile_revision"], "profile_revision"),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        target_scale=_scale_ref_from_dict(mapping["target_scale"]),
        source_signature=_source_signature_from_dict(mapping["source_signature"]),
        mapping_kind=mapping_kind,
        native_scale=(
            None
            if native_scale_data is None
            else _native_scale_from_dict(native_scale_data)
        ),
        points_possible=_optional_finite_number(
            mapping["points_possible"], "points_possible"
        ),
        mapping_rules=tuple(
            _mapping_rule_from_dict(item, mapping_kind)
            for item in _require_list(mapping["mapping_rules"], "mapping_rules")
        ),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def native_value_mapping_profile_to_json_bytes(
    value: NativeValueMappingProfile,
) -> bytes:
    return _canonical_json_bytes(native_value_mapping_profile_to_dict(value))


def native_value_mapping_profile_from_json_bytes(
    data: bytes,
) -> NativeValueMappingProfile:
    value = native_value_mapping_profile_from_dict(
        _decode_json(data, "native-value mapping profile")
    )
    if native_value_mapping_profile_to_json_bytes(value) != data:
        raise ProficiencyMappingSerializationError(
            "mapping-profile bytes are not canonically encoded."
        )
    return value


def native_value_mapping_outcome_to_dict(
    value: NativeValueMappingOutcome,
) -> dict[str, object]:
    if not isinstance(value, NativeValueMappingOutcome):
        raise ProficiencyMappingValidationError(
            "value must be a NativeValueMappingOutcome."
        )
    return {
        "status": value.status,
        "profile": _profile_ref_to_dict(value.profile),
        "target_scale": _scale_ref_to_dict(value.target_scale),
        "proficiency_level_id": value.proficiency_level_id,
        "native_state": (
            None if value.native_state is None else _state_to_dict(value.native_state)
        ),
        "unsupported_reason": value.unsupported_reason,
    }


def native_value_mapping_outcome_from_dict(data: object) -> NativeValueMappingOutcome:
    mapping = _exact_mapping(data, _OUTCOME_KEYS, "native-value mapping outcome")
    status = _mapping_status(mapping["status"])
    reason = _optional_unsupported_reason(mapping["unsupported_reason"])
    native_state_data = mapping["native_state"]
    return NativeValueMappingOutcome(
        status=status,
        profile=_profile_ref_from_dict(mapping["profile"]),
        target_scale=_scale_ref_from_dict(mapping["target_scale"]),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"], "proficiency_level_id"
        ),
        native_state=(
            None if native_state_data is None else _state_from_dict(native_state_data)
        ),
        unsupported_reason=reason,
    )


def _mapped(
    profile: NativeValueMappingProfileReference,
    scale: ProficiencyScaleReference,
    level_id: str,
) -> NativeValueMappingOutcome:
    return NativeValueMappingOutcome(
        status="mapped",
        profile=profile,
        target_scale=scale,
        proficiency_level_id=level_id,
    )


def _unmapped(
    profile: NativeValueMappingProfileReference,
    scale: ProficiencyScaleReference,
) -> NativeValueMappingOutcome:
    return NativeValueMappingOutcome(
        status="unmapped", profile=profile, target_scale=scale
    )


def _unsupported(
    profile: NativeValueMappingProfileReference,
    scale: ProficiencyScaleReference,
    reason: UnsupportedReason,
) -> NativeValueMappingOutcome:
    return NativeValueMappingOutcome(
        status="unsupported",
        profile=profile,
        target_scale=scale,
        unsupported_reason=reason,
    )


def _point_range_contains(rule: PointRangeMappingRule, earned: int | float) -> bool:
    lower_ok = rule.minimum_earned is None or (
        earned > rule.minimum_earned
        or (earned == rule.minimum_earned and rule.minimum_inclusive)
    )
    upper_ok = rule.maximum_earned is None or (
        earned < rule.maximum_earned
        or (earned == rule.maximum_earned and rule.maximum_inclusive)
    )
    return lower_ok and upper_ok


def _validate_point_range_sequence(rules: tuple[PointRangeMappingRule, ...]) -> None:
    for index, rule in enumerate(rules):
        if index == 0:
            continue
        previous = rules[index - 1]
        if previous.maximum_earned is None:
            raise ProficiencyMappingValidationError(
                "an open-ended point range must be the final rule."
            )
        if rule.minimum_earned is None:
            raise ProficiencyMappingValidationError(
                "only the first point range may have an open lower bound."
            )
        if rule.minimum_earned < previous.maximum_earned:
            raise ProficiencyMappingValidationError(
                "raw-point mapping ranges must be ordered and nonoverlapping."
            )
        if (
            rule.minimum_earned == previous.maximum_earned
            and rule.minimum_inclusive
            and previous.maximum_inclusive
        ):
            raise ProficiencyMappingValidationError(
                "raw-point mapping ranges must not overlap at a shared boundary."
            )


def _mapping_rules(value: object) -> tuple[MappingRule, ...]:
    if isinstance(value, (str, bytes)):
        raise ProficiencyMappingValidationError("mapping_rules must be an iterable.")
    try:
        values = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ProficiencyMappingValidationError(
            "mapping_rules must be an iterable."
        ) from error
    if any(
        not isinstance(
            rule,
            (ScalarMappingRule, ScaledLevelMappingRule, PointRangeMappingRule),
        )
        for rule in values
    ):
        raise ProficiencyMappingValidationError(
            "mapping_rules contains an unsupported rule type."
        )
    return cast(tuple[MappingRule, ...], values)


def _proficiency_level_to_dict(value: ProficiencyLevel) -> dict[str, object]:
    return {
        "level_id": value.level_id,
        "position": value.position,
        "label": value.label,
        "description": value.description,
    }


def _proficiency_level_from_dict(data: object) -> ProficiencyLevel:
    mapping = _exact_mapping(data, _LEVEL_KEYS, "proficiency level")
    return ProficiencyLevel(
        level_id=_require_str(mapping["level_id"], "level_id"),
        position=_require_int(mapping["position"], "position"),
        label=_require_str(mapping["label"], "label"),
        description=_require_str(mapping["description"], "description"),
    )


def _actor_to_dict(value: MappingActor) -> dict[str, object]:
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> MappingActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "mapping actor")
    kind = _mapping_actor_kind(mapping["kind"])
    return MappingActor(
        kind=kind,
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def _scale_ref_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _scale_ref_from_dict(data: object) -> ProficiencyScaleReference:
    mapping = _exact_mapping(data, _SCALE_REF_KEYS, "proficiency-scale reference")
    return ProficiencyScaleReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        scale_revision=_require_int(mapping["scale_revision"], "scale_revision"),
        scale_sha256=_require_str(mapping["scale_sha256"], "scale_sha256"),
    )


def _profile_ref_to_dict(
    value: NativeValueMappingProfileReference,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "profile_id": value.profile_id,
        "profile_revision": value.profile_revision,
        "profile_sha256": value.profile_sha256,
    }


def _profile_ref_from_dict(data: object) -> NativeValueMappingProfileReference:
    mapping = _exact_mapping(data, _PROFILE_REF_KEYS, "mapping-profile reference")
    return NativeValueMappingProfileReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        profile_id=_require_str(mapping["profile_id"], "profile_id"),
        profile_revision=_require_int(mapping["profile_revision"], "profile_revision"),
        profile_sha256=_require_str(mapping["profile_sha256"], "profile_sha256"),
    )


def _source_signature_to_dict(value: NativeValueSourceSignature) -> dict[str, object]:
    return {
        "producer_module_id": value.producer_module_id,
        "publication_kind": value.publication_kind,
        "manifest_contract_version": value.manifest_contract_version,
        "producer_contract_version": value.producer_contract_version,
        "projection_id": value.projection_id,
        "projection_contract_version": value.projection_contract_version,
        "producer_reader_distribution": value.producer_reader_distribution,
        "producer_reader_version": value.producer_reader_version,
        "result_kind": value.result_kind,
        "target_kind": value.target_kind,
    }


def _source_signature_from_dict(data: object) -> NativeValueSourceSignature:
    mapping = _exact_mapping(data, _SOURCE_SIGNATURE_KEYS, "source signature")
    return NativeValueSourceSignature(
        producer_module_id=_require_str(
            mapping["producer_module_id"], "producer_module_id"
        ),
        publication_kind=_require_str(mapping["publication_kind"], "publication_kind"),
        manifest_contract_version=_require_str(
            mapping["manifest_contract_version"], "manifest_contract_version"
        ),
        producer_contract_version=_optional_str(
            mapping["producer_contract_version"], "producer_contract_version"
        ),
        projection_id=_require_str(mapping["projection_id"], "projection_id"),
        projection_contract_version=_require_str(
            mapping["projection_contract_version"], "projection_contract_version"
        ),
        producer_reader_distribution=_require_str(
            mapping["producer_reader_distribution"],
            "producer_reader_distribution",
        ),
        producer_reader_version=_require_str(
            mapping["producer_reader_version"], "producer_reader_version"
        ),
        result_kind=_require_str(mapping["result_kind"], "result_kind"),
        target_kind=_require_str(mapping["target_kind"], "target_kind"),
    )


def _mapping_rule_to_dict(value: MappingRule) -> dict[str, object]:
    if isinstance(value, ScalarMappingRule):
        return {
            "rule_type": "scalar",
            "native_value": _scalar_to_dict(value.native_value),
            "proficiency_level_id": value.proficiency_level_id,
        }
    if isinstance(value, ScaledLevelMappingRule):
        return {
            "rule_type": "scaled_level",
            "native_value": _scalar_to_dict(value.native_value),
            "proficiency_level_id": value.proficiency_level_id,
        }
    return {
        "rule_type": "point_range",
        "minimum_earned": value.minimum_earned,
        "minimum_inclusive": value.minimum_inclusive,
        "maximum_earned": value.maximum_earned,
        "maximum_inclusive": value.maximum_inclusive,
        "proficiency_level_id": value.proficiency_level_id,
    }


def _mapping_rule_from_dict(data: object, kind: MappingKind) -> MappingRule:
    if kind == "exact_scalar":
        mapping = _exact_mapping(data, _RULE_SCALAR_KEYS, "scalar mapping rule")
        if mapping["rule_type"] != "scalar":
            raise ProficiencyMappingSerializationError(
                "scalar rule_type must be scalar."
            )
        return ScalarMappingRule(
            native_value=_scalar_from_dict(mapping["native_value"], "native_value"),
            proficiency_level_id=_require_str(
                mapping["proficiency_level_id"], "proficiency_level_id"
            ),
        )
    if kind == "exact_native_scale":
        mapping = _exact_mapping(data, _RULE_SCALED_KEYS, "scaled mapping rule")
        if mapping["rule_type"] != "scaled_level":
            raise ProficiencyMappingSerializationError(
                "scaled rule_type must be scaled_level."
            )
        return ScaledLevelMappingRule(
            native_value=_scalar_from_dict(mapping["native_value"], "native_value"),
            proficiency_level_id=_require_str(
                mapping["proficiency_level_id"], "proficiency_level_id"
            ),
        )
    mapping = _exact_mapping(data, _RULE_POINTS_KEYS, "point-range mapping rule")
    if mapping["rule_type"] != "point_range":
        raise ProficiencyMappingSerializationError(
            "point range rule_type must be point_range."
        )
    return PointRangeMappingRule(
        minimum_earned=_optional_finite_number(
            mapping["minimum_earned"], "minimum_earned"
        ),
        minimum_inclusive=_require_bool(
            mapping["minimum_inclusive"], "minimum_inclusive"
        ),
        maximum_earned=_optional_finite_number(
            mapping["maximum_earned"], "maximum_earned"
        ),
        maximum_inclusive=_require_bool(
            mapping["maximum_inclusive"], "maximum_inclusive"
        ),
        proficiency_level_id=_require_str(
            mapping["proficiency_level_id"], "proficiency_level_id"
        ),
    )


def _native_scale_to_dict(value: NativeScale) -> dict[str, object]:
    return {
        "scale_id": value.scale_id,
        "contract_version": value.contract_version,
        "order_is_meaningful": value.order_is_meaningful,
        "lineage_id": value.lineage_id,
        "name": value.name,
        "revision": value.revision,
        "scale_type": value.scale_type,
        "status": value.status,
        "supersedes_scale_id": value.supersedes_scale_id,
        "levels": [
            {
                "value": _scalar_to_dict(level.value),
                "label": level.label,
                "description": level.description,
                "meaning": level.meaning,
                "position": level.position,
            }
            for level in value.levels
        ],
    }


def _native_scale_from_dict(data: object) -> NativeScale:
    mapping = _exact_mapping(data, _NATIVE_SCALE_KEYS, "native scale")
    levels: list[NativeScaleLevel] = []
    for item in _require_list(mapping["levels"], "levels"):
        level = _exact_mapping(item, _NATIVE_LEVEL_KEYS, "native scale level")
        levels.append(
            NativeScaleLevel(
                value=_scalar_from_dict(level["value"], "native level value"),
                label=_optional_str(level["label"], "native level label"),
                description=_optional_str(
                    level["description"], "native level description"
                ),
                meaning=_optional_str(level["meaning"], "native level meaning"),
                position=_optional_int(level["position"], "native level position"),
            )
        )
    return NativeScale(
        scale_id=_require_str(mapping["scale_id"], "native scale_id"),
        contract_version=_optional_str(
            mapping["contract_version"], "native contract_version"
        ),
        order_is_meaningful=_require_bool(
            mapping["order_is_meaningful"], "order_is_meaningful"
        ),
        lineage_id=_optional_str(mapping["lineage_id"], "native lineage_id"),
        name=_optional_str(mapping["name"], "native name"),
        revision=_optional_int(mapping["revision"], "native revision"),
        scale_type=_optional_str(mapping["scale_type"], "native scale_type"),
        status=_optional_str(mapping["status"], "native status"),
        supersedes_scale_id=_optional_str(
            mapping["supersedes_scale_id"], "native supersedes_scale_id"
        ),
        levels=tuple(levels),
    )


def _state_to_dict(value: NativeStateValue) -> dict[str, object]:
    return {"code": value.code, "label": value.label, "description": value.description}


def _state_from_dict(data: object) -> NativeStateValue:
    mapping = _exact_mapping(data, _STATE_KEYS, "native state")
    return NativeStateValue(
        code=_require_str(mapping["code"], "native state code"),
        label=_optional_str(mapping["label"], "native state label"),
        description=_optional_str(mapping["description"], "native state description"),
    )


def _scalar_to_dict(value: NativeScalar) -> dict[str, object]:
    if type(value) is bool:
        scalar_type = "boolean"
    elif type(value) is int:
        scalar_type = "integer"
    elif type(value) is float:
        scalar_type = "float"
    elif type(value) is str:
        scalar_type = "string"
    else:  # pragma: no cover
        raise ProficiencyMappingSerializationError("unsupported native scalar type.")
    return {"type": scalar_type, "value": value}


def _scalar_from_dict(data: object, label: str) -> NativeScalar:
    mapping = _exact_mapping(data, _SCALAR_KEYS, label)
    scalar_type = _require_str(mapping["type"], f"{label}.type")
    value = mapping["value"]
    if scalar_type == "boolean" and type(value) is bool:
        return value
    if scalar_type == "integer" and type(value) is int:
        return value
    if scalar_type == "float" and type(value) is float and math.isfinite(value):
        return value
    if scalar_type == "string" and type(value) is str:
        return value
    raise ProficiencyMappingSerializationError(
        f"{label} scalar type and value do not agree exactly."
    )


def _native_scalar(value: object, field_name: str) -> NativeScalar:
    if isinstance(value, str):
        return _bounded_text(
            value, field_name, MAXIMUM_PROFICIENCY_TEXT_LENGTH
        )
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProficiencyMappingValidationError(
                f"{field_name} must be finite."
            )
        return value
    raise ProficiencyMappingValidationError(
        f"{field_name} must be a string, integer, finite float, or boolean."
    )


def _scalar_key(value: NativeScalar) -> tuple[str, NativeScalar]:
    return type(value).__name__, value


def _number_key(value: int | float) -> tuple[str, int | float]:
    return type(value).__name__, value


def _finite_number(value: object, field_name: str) -> int | float:
    if type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProficiencyMappingValidationError(
                f"{field_name} must be finite."
            )
        return value
    raise ProficiencyMappingValidationError(
        f"{field_name} must be a finite number."
    )


def _optional_finite_number(value: object, field_name: str) -> int | float | None:
    if value is None:
        return None
    return _finite_number(value, field_name)


def _mapping_actor_kind(value: object) -> MappingActorKind:
    if value not in {"teacher", "policy"}:
        raise ProficiencyMappingValidationError("unsupported actor kind.")
    return value


def _mapping_kind(value: object) -> MappingKind:
    if value not in set(_MAPPING_KINDS):
        raise ProficiencyMappingValidationError("unsupported mapping_kind.")
    return value


def _mapping_status(value: object) -> MappingStatus:
    if value not in {"mapped", "unmapped", "unsupported", "native_state"}:
        raise ProficiencyMappingValidationError(
            "unsupported mapping outcome status."
        )
    return value


def _optional_unsupported_reason(value: object) -> UnsupportedReason | None:
    if value is None:
        return None
    if value not in {
        "source_signature_mismatch",
        "value_kind_mismatch",
        "native_scale_mismatch",
        "points_possible_mismatch",
    }:
        raise ProficiencyMappingValidationError("unsupported mapping reason.")
    return value


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProficiencyMappingValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ProficiencyMappingValidationError(str(error)) from error


def _contract_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _CONTRACT_CODE.fullmatch(value) is None:
        raise ProficiencyMappingValidationError(
            f"{field_name} must be a lowercase contract identifier."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProficiencyMappingValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _validate_revision_pair(revision: int, supersedes: int | None, label: str) -> None:
    if revision == 1 and supersedes is not None:
        raise ProficiencyMappingValidationError(
            f"{label} revision 1 must not supersede a prior revision."
        )
    if revision > 1 and supersedes != revision - 1:
        raise ProficiencyMappingValidationError(
            f"{label} supersedes_revision must identify the immediately prior revision."
        )


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProficiencyMappingValidationError(f"{field_name} must be a string.")
    if value != value.strip() or not value:
        raise ProficiencyMappingValidationError(
            f"{field_name} must be nonempty without surrounding whitespace."
        )
    if len(value) > maximum:
        raise ProficiencyMappingValidationError(
            f"{field_name} exceeds the maximum length of {maximum}."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProficiencyMappingValidationError(
            f"{field_name} must not contain control characters."
        )
    return value


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, maximum)


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProficiencyMappingValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_to_text(value: datetime) -> str:
    canonical = _aware_utc_datetime(value, "timestamp")
    return canonical.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    if not text.endswith("Z"):
        raise ProficiencyMappingValidationError(
            f"{field_name} must use canonical UTC Z."
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise ProficiencyMappingValidationError(f"{field_name} is invalid.") from error
    if _datetime_to_text(parsed) != text:
        raise ProficiencyMappingValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    return parsed.astimezone(UTC)


def _typed_tuple(
    values: object, item_type: type[_T], field_name: str
) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes)):
        raise ProficiencyMappingValidationError(f"{field_name} must be an iterable.")
    try:
        result = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise ProficiencyMappingValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(value, item_type) for value in result):
        raise ProficiencyMappingValidationError(
            f"{field_name} contains an invalid item type."
        )
    return cast(tuple[_T, ...], result)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ProficiencyMappingValidationError(
            f"{field_name} must be 64 lowercase hexadecimal characters."
        )
    return value


def _exact_mapping(
    value: object, keys: frozenset[str], label: str
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProficiencyMappingSerializationError(f"{label} must be a JSON object.")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ProficiencyMappingSerializationError(
            f"{label} does not use exact schema (missing={missing}, unknown={unknown})."
        )
    return cast(dict[str, object], value)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProficiencyMappingValidationError(f"{field_name} must be a string.")
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProficiencyMappingValidationError(f"{field_name} must be an integer.")
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ProficiencyMappingValidationError(f"{field_name} must be boolean.")
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ProficiencyMappingSerializationError(
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
        raise ProficiencyMappingSerializationError(
            "proficiency mapping state cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProficiencyMappingSerializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ProficiencyMappingSerializationError(
        f"non-finite JSON value is invalid: {value}"
    )


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ProficiencyMappingSerializationError(f"{label} input must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProficiencyMappingSerializationError(f"{label} must be UTF-8.") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ProficiencyMappingSerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ProficiencyMappingSerializationError(
            f"{label} JSON is invalid."
        ) from error
