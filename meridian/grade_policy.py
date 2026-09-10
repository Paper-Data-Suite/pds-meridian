"""Immutable versioned Grade-policy domain contracts for Meridian v0.3.

This module defines policy configuration only. It does not discover evidence,
select attempts, calculate Grades, apply overrides, create ReportingSnapshots,
or write to external school systems.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_evidence import normalize_standard_id

GRADE_POLICY_SCHEMA_VERSION: Final[str] = "1"
GRADE_POLICY_RECORD_TYPE: Final[str] = "meridian_grade_policy"

MAXIMUM_GRADE_POLICY_TITLE_LENGTH: Final[int] = 256
MAXIMUM_GRADE_POLICY_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_GRADE_POLICY_ACTOR_ID_LENGTH: Final[int] = 256

GradeCalculationFamily: TypeAlias = Literal[
    "conventional",
    "standards_based",
    "hybrid",
]
ConventionalGradeMode: TypeAlias = Literal[
    "total_points",
    "weighted_items",
    "weighted_categories",
]
GradePolicyActorKind: TypeAlias = Literal["teacher", "policy"]
GradeStateConsequence: TypeAlias = Literal["exclude", "blocking", "zero"]
GradeReassessmentSelectionAuthority: TypeAlias = Literal[
    "v02_attempt_and_reassessment_state"
]
GradeReassessmentUnresolvedHandling: TypeAlias = Literal["exclude", "blocking"]
GradeRoundingMode: TypeAlias = Literal[
    "half_even",
    "half_up",
    "half_down",
    "up",
    "down",
    "ceiling",
    "floor",
]
GradeRoundingStage: TypeAlias = Literal["final"]
StandardsGradeAggregationStrategy: TypeAlias = Literal["weighted_mean"]

_CALCULATION_FAMILIES: Final[frozenset[str]] = frozenset(
    {"conventional", "standards_based", "hybrid"}
)
_CONVENTIONAL_MODES: Final[frozenset[str]] = frozenset(
    {"total_points", "weighted_items", "weighted_categories"}
)
_ACTOR_KINDS: Final[frozenset[str]] = frozenset({"teacher", "policy"})
_ROUNDING_MODES: Final[frozenset[str]] = frozenset(
    {
        "half_even",
        "half_up",
        "half_down",
        "up",
        "down",
        "ceiling",
        "floor",
    }
)
_ROUNDING_STAGES: Final[frozenset[str]] = frozenset({"final"})
_AGGREGATION_STRATEGIES: Final[frozenset[str]] = frozenset({"weighted_mean"})
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")

_STATE_FIELDS: Final[tuple[str, ...]] = (
    "missing",
    "pending",
    "incomplete",
    "excused",
    "excluded",
    "not_applicable",
    "insufficient_evidence",
    "unavailable",
    "withdrawn",
    "invalid",
    "unresolved",
)
_STATE_ALLOWED: Final[dict[str, frozenset[str]]] = {
    "missing": frozenset({"exclude", "blocking", "zero"}),
    "pending": frozenset({"exclude", "blocking"}),
    "incomplete": frozenset({"exclude", "blocking", "zero"}),
    "excused": frozenset({"exclude"}),
    "excluded": frozenset({"exclude"}),
    "not_applicable": frozenset({"exclude"}),
    "insufficient_evidence": frozenset({"exclude", "blocking"}),
    "unavailable": frozenset({"exclude", "blocking"}),
    "withdrawn": frozenset({"exclude", "blocking"}),
    "invalid": frozenset({"exclude", "blocking"}),
    "unresolved": frozenset({"exclude", "blocking"}),
}

_ITEM_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "grade_item_revision_sha256",
    }
)
_ITEM_PARTICIPATION_KEYS: Final[frozenset[str]] = frozenset(
    {"grade_item", "category_id", "weight"}
)
_CATEGORY_KEYS: Final[frozenset[str]] = frozenset(
    {"category_id", "title", "weight"}
)
_CONVENTIONAL_KEYS: Final[frozenset[str]] = frozenset(
    {"mode", "items", "categories"}
)
_STANDARD_PARTICIPATION_KEYS: Final[frozenset[str]] = frozenset(
    {"standard_id", "weight"}
)
_CONVERSION_KEYS: Final[frozenset[str]] = frozenset(
    {"proficiency_level_id", "grade_value"}
)
_STANDARDS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "target_scale",
        "standards",
        "conversions",
        "aggregation_strategy",
        "minimum_calculated_results",
    }
)
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_HYBRID_KEYS: Final[frozenset[str]] = frozenset(
    {
        "conventional",
        "standards_based",
        "conventional_weight",
        "standards_weight",
    }
)
_STATE_KEYS: Final[frozenset[str]] = frozenset(_STATE_FIELDS)
_REASSESSMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"selection_authority", "unresolved_handling"}
)
_ROUNDING_KEYS: Final[frozenset[str]] = frozenset(
    {"quantum", "mode", "application_stage"}
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_POLICY_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "policy_id", "policy_revision", "policy_sha256"}
)
_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "title",
        "calculation_family",
        "configuration",
        "state_treatment",
        "reassessment_handling",
        "rounding",
        "actor",
        "rationale",
        "revised_at",
    }
)


class GradePolicyError(ValueError):
    """Base error for Grade-policy model and serialization failures."""


class GradePolicyValidationError(GradePolicyError):
    """Raised when Grade-policy data violates the domain contract."""


class GradePolicySerializationError(GradePolicyError):
    """Raised when Grade-policy JSON is invalid or noncanonical."""


@dataclass(frozen=True, slots=True)
class GradePolicyActor:
    """Explicit authorship metadata for one immutable policy revision."""

    kind: GradePolicyActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in _ACTOR_KINDS:
            raise GradePolicyValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_GRADE_POLICY_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class GradePolicyItemReference:
    """Exact immutable Grade Item revision and canonical-byte digest."""

    class_id: str
    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "grade_item_revision",
            _positive_int(self.grade_item_revision, "grade_item_revision"),
        )
        object.__setattr__(
            self,
            "grade_item_revision_sha256",
            _sha256(
                self.grade_item_revision_sha256,
                "grade_item_revision_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class GradePolicyItemParticipation:
    """One exact Grade Item's explicit participation in a Grade policy."""

    grade_item: GradePolicyItemReference
    category_id: str | None
    weight: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.grade_item, GradePolicyItemReference):
            raise GradePolicyValidationError(
                "grade_item must be a GradePolicyItemReference."
            )
        category = self.category_id
        if category is not None:
            category = _identifier(category, "category_id")
        weight = self.weight
        if weight is not None:
            weight = _positive_decimal(weight, "weight")
        object.__setattr__(self, "category_id", category)
        object.__setattr__(self, "weight", weight)


@dataclass(frozen=True, slots=True)
class GradePolicyCategory:
    """One exact conventional Grade category and its policy-owned weight."""

    category_id: str
    title: str
    weight: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "category_id",
            _identifier(self.category_id, "category_id"),
        )
        object.__setattr__(
            self,
            "title",
            _bounded_text(
                self.title,
                "title",
                MAXIMUM_GRADE_POLICY_TITLE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "weight",
            _positive_decimal(self.weight, "weight"),
        )


@dataclass(frozen=True, slots=True)
class ConventionalGradeConfiguration:
    """Bounded v1 conventional Grade-policy configuration."""

    mode: ConventionalGradeMode
    items: tuple[GradePolicyItemParticipation, ...]
    categories: tuple[GradePolicyCategory, ...]

    def __post_init__(self) -> None:
        if self.mode not in _CONVENTIONAL_MODES:
            raise GradePolicyValidationError(
                "conventional mode must be one of: "
                "total_points, weighted_categories, weighted_items."
            )
        items = _typed_tuple(
            self.items,
            GradePolicyItemParticipation,
            "items",
        )
        if not items:
            raise GradePolicyValidationError(
                "conventional configuration must include at least one Grade Item."
            )
        _reject_duplicate_grade_items(items)
        items = tuple(
            sorted(
                items,
                key=lambda item: (
                    item.grade_item.grade_item_id,
                    item.grade_item.grade_item_revision,
                ),
            )
        )
        categories = _typed_tuple(
            self.categories,
            GradePolicyCategory,
            "categories",
        )
        categories = tuple(
            sorted(categories, key=lambda category: category.category_id)
        )
        category_ids = tuple(category.category_id for category in categories)
        if len(set(category_ids)) != len(category_ids):
            raise GradePolicyValidationError(
                "category IDs must not contain duplicates."
            )

        if self.mode == "total_points":
            if categories:
                raise GradePolicyValidationError(
                    "total_points configuration must not define categories."
                )
            for item in items:
                if item.category_id is not None or item.weight is not None:
                    raise GradePolicyValidationError(
                        "total_points items must not define category_id or weight."
                    )
        elif self.mode == "weighted_items":
            if categories:
                raise GradePolicyValidationError(
                    "weighted_items configuration must not define categories."
                )
            weights: list[Decimal] = []
            for item in items:
                if item.category_id is not None or item.weight is None:
                    raise GradePolicyValidationError(
                        "weighted_items items require weight and no category_id."
                    )
                weights.append(item.weight)
            _require_complete_weighting(weights, "weighted item")
        else:
            if not categories:
                raise GradePolicyValidationError(
                    "weighted_categories configuration requires categories."
                )
            _require_complete_weighting(
                [category.weight for category in categories],
                "category",
            )
            defined = set(category_ids)
            used: set[str] = set()
            for item in items:
                if item.category_id is None or item.weight is not None:
                    raise GradePolicyValidationError(
                        "weighted_categories items require category_id and no "
                        "item weight."
                    )
                if item.category_id not in defined:
                    raise GradePolicyValidationError(
                        "Grade Item category_id must identify a defined category."
                    )
                used.add(item.category_id)
            if used != defined:
                raise GradePolicyValidationError(
                    "every weighted category must contain at least one Grade Item."
                )

        object.__setattr__(self, "items", items)
        object.__setattr__(self, "categories", categories)


@dataclass(frozen=True, slots=True)
class StandardGradeParticipation:
    """One exact standard's explicit contribution weight."""

    standard_id: str
    weight: Decimal

    def __post_init__(self) -> None:
        try:
            standard_id = normalize_standard_id(self.standard_id)
        except ValueError as error:
            raise GradePolicyValidationError(str(error)) from error
        object.__setattr__(self, "standard_id", standard_id)
        object.__setattr__(
            self,
            "weight",
            _positive_decimal(self.weight, "weight"),
        )


@dataclass(frozen=True, slots=True)
class ProficiencyGradeConversion:
    """Explicit proficiency-level to conventional Grade-value conversion."""

    proficiency_level_id: str
    grade_value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )
        object.__setattr__(
            self,
            "grade_value",
            _nonnegative_decimal(self.grade_value, "grade_value"),
        )


@dataclass(frozen=True, slots=True)
class StandardsBasedGradeConfiguration:
    """Bounded v1 standards-based Grade-policy configuration."""

    target_scale: ProficiencyScaleReference
    standards: tuple[StandardGradeParticipation, ...]
    conversions: tuple[ProficiencyGradeConversion, ...]
    aggregation_strategy: StandardsGradeAggregationStrategy
    minimum_calculated_results: int

    def __post_init__(self) -> None:
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise GradePolicyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        standards = _typed_tuple(
            self.standards,
            StandardGradeParticipation,
            "standards",
        )
        if not standards:
            raise GradePolicyValidationError(
                "standards-based configuration must include at least one standard."
            )
        standards = tuple(
            sorted(standards, key=lambda item: item.standard_id)
        )
        standard_ids = tuple(item.standard_id for item in standards)
        if len(set(standard_ids)) != len(standard_ids):
            raise GradePolicyValidationError(
                "standard IDs must not contain duplicates."
            )
        _require_complete_weighting(
            [item.weight for item in standards],
            "standard",
        )

        conversions = _typed_tuple(
            self.conversions,
            ProficiencyGradeConversion,
            "conversions",
        )
        if not conversions:
            raise GradePolicyValidationError(
                "standards-based configuration requires proficiency conversions."
            )
        conversions = tuple(
            sorted(
                conversions,
                key=lambda item: item.proficiency_level_id,
            )
        )
        level_ids = tuple(item.proficiency_level_id for item in conversions)
        if len(set(level_ids)) != len(level_ids):
            raise GradePolicyValidationError(
                "proficiency conversion level IDs must not contain duplicates."
            )

        if self.aggregation_strategy not in _AGGREGATION_STRATEGIES:
            raise GradePolicyValidationError(
                "aggregation_strategy must be weighted_mean."
            )
        minimum = _positive_int(
            self.minimum_calculated_results,
            "minimum_calculated_results",
        )
        if minimum > len(standards):
            raise GradePolicyValidationError(
                "minimum_calculated_results must not exceed participating "
                "standard count."
            )

        object.__setattr__(self, "standards", standards)
        object.__setattr__(self, "conversions", conversions)
        object.__setattr__(self, "minimum_calculated_results", minimum)


@dataclass(frozen=True, slots=True)
class HybridGradeConfiguration:
    """Bounded v1 conventional plus standards-based hybrid configuration."""

    conventional: ConventionalGradeConfiguration
    standards_based: StandardsBasedGradeConfiguration
    conventional_weight: Decimal
    standards_weight: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.conventional, ConventionalGradeConfiguration):
            raise GradePolicyValidationError(
                "hybrid conventional must be ConventionalGradeConfiguration."
            )
        if not isinstance(
            self.standards_based,
            StandardsBasedGradeConfiguration,
        ):
            raise GradePolicyValidationError(
                "hybrid standards_based must be StandardsBasedGradeConfiguration."
            )
        conventional_weight = _positive_decimal(
            self.conventional_weight,
            "conventional_weight",
        )
        standards_weight = _positive_decimal(
            self.standards_weight,
            "standards_weight",
        )
        _require_complete_weighting(
            [conventional_weight, standards_weight],
            "hybrid component",
        )
        object.__setattr__(
            self,
            "conventional_weight",
            conventional_weight,
        )
        object.__setattr__(self, "standards_weight", standards_weight)


@dataclass(frozen=True, slots=True)
class GradeStateTreatment:
    """Explicit consequence for every supported unresolved/non-Grade state."""

    missing: GradeStateConsequence
    pending: GradeStateConsequence
    incomplete: GradeStateConsequence
    excused: GradeStateConsequence
    excluded: GradeStateConsequence
    not_applicable: GradeStateConsequence
    insufficient_evidence: GradeStateConsequence
    unavailable: GradeStateConsequence
    withdrawn: GradeStateConsequence
    invalid: GradeStateConsequence
    unresolved: GradeStateConsequence

    def __post_init__(self) -> None:
        for field_name in _STATE_FIELDS:
            value = getattr(self, field_name)
            if value not in _STATE_ALLOWED[field_name]:
                allowed = ", ".join(sorted(_STATE_ALLOWED[field_name]))
                raise GradePolicyValidationError(
                    f"{field_name} treatment must be one of: {allowed}."
                )


@dataclass(frozen=True, slots=True)
class GradeReassessmentHandling:
    """Grade-layer handling that preserves v0.2 selection authority."""

    selection_authority: GradeReassessmentSelectionAuthority
    unresolved_handling: GradeReassessmentUnresolvedHandling

    def __post_init__(self) -> None:
        if self.selection_authority != "v02_attempt_and_reassessment_state":
            raise GradePolicyValidationError(
                "selection_authority must be "
                "v02_attempt_and_reassessment_state."
            )
        if self.unresolved_handling not in {"exclude", "blocking"}:
            raise GradePolicyValidationError(
                "unresolved reassessment handling must be exclude or blocking."
            )


@dataclass(frozen=True, slots=True)
class GradeRoundingPolicy:
    """Exact Decimal rounding semantics for the final Grade result."""

    quantum: Decimal
    mode: GradeRoundingMode
    application_stage: GradeRoundingStage

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "quantum",
            _positive_decimal(self.quantum, "quantum"),
        )
        if self.mode not in _ROUNDING_MODES:
            raise GradePolicyValidationError(
                "rounding mode is not supported by Grade policy v1."
            )
        if self.application_stage not in _ROUNDING_STAGES:
            raise GradePolicyValidationError(
                "application_stage must be final."
            )


GradePolicyConfiguration: TypeAlias = (
    ConventionalGradeConfiguration
    | StandardsBasedGradeConfiguration
    | HybridGradeConfiguration
)


@dataclass(frozen=True, slots=True)
class GradePolicyRevision:
    """One immutable semantic revision of a Meridian Grade-policy family."""

    schema_version: str
    record_type: str
    class_id: str
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    title: str
    calculation_family: GradeCalculationFamily
    configuration: GradePolicyConfiguration
    state_treatment: GradeStateTreatment
    reassessment_handling: GradeReassessmentHandling
    rounding: GradeRoundingPolicy
    actor: GradePolicyActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_POLICY_SCHEMA_VERSION:
            raise GradePolicyValidationError(
                'schema_version must be "1".'
            )
        if self.record_type != GRADE_POLICY_RECORD_TYPE:
            raise GradePolicyValidationError(
                'record_type must be "meridian_grade_policy".'
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
            MAXIMUM_GRADE_POLICY_TITLE_LENGTH,
        )
        if self.calculation_family not in _CALCULATION_FAMILIES:
            raise GradePolicyValidationError(
                "calculation_family must be one of: "
                "conventional, hybrid, standards_based."
            )
        _validate_configuration_family(
            self.calculation_family,
            self.configuration,
        )
        _validate_configuration_class(class_id, self.configuration)
        if not isinstance(self.state_treatment, GradeStateTreatment):
            raise GradePolicyValidationError(
                "state_treatment must be a GradeStateTreatment."
            )
        if not isinstance(
            self.reassessment_handling,
            GradeReassessmentHandling,
        ):
            raise GradePolicyValidationError(
                "reassessment_handling must be GradeReassessmentHandling."
            )
        if not isinstance(self.rounding, GradeRoundingPolicy):
            raise GradePolicyValidationError(
                "rounding must be a GradeRoundingPolicy."
            )
        if not isinstance(self.actor, GradePolicyActor):
            raise GradePolicyValidationError(
                "actor must be a GradePolicyActor."
            )
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_GRADE_POLICY_TEXT_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "policy_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class GradePolicyReference:
    """Exact immutable Grade-policy revision and canonical-byte digest."""

    class_id: str
    policy_id: str
    policy_revision: int
    policy_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "policy_id",
            _identifier(self.policy_id, "policy_id"),
        )
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


def validate_grade_policy_revision(
    value: GradePolicyRevision,
) -> GradePolicyRevision:
    """Fully revalidate one Grade-policy revision."""

    if not isinstance(value, GradePolicyRevision):
        raise GradePolicyValidationError(
            "grade policy revision must be a GradePolicyRevision."
        )
    return GradePolicyRevision(
        schema_version=value.schema_version,
        record_type=value.record_type,
        class_id=value.class_id,
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        supersedes_revision=value.supersedes_revision,
        title=value.title,
        calculation_family=value.calculation_family,
        configuration=value.configuration,
        state_treatment=value.state_treatment,
        reassessment_handling=value.reassessment_handling,
        rounding=value.rounding,
        actor=value.actor,
        rationale=value.rationale,
        revised_at=value.revised_at,
    )


def validate_grade_policy_revision_transition(
    previous: GradePolicyRevision,
    candidate: GradePolicyRevision,
) -> GradePolicyRevision:
    """Validate a pure linear transition between immutable policy revisions."""

    old = validate_grade_policy_revision(previous)
    new = validate_grade_policy_revision(candidate)
    if new.class_id != old.class_id:
        raise GradePolicyValidationError(
            "candidate class_id must match previous."
        )
    if new.policy_id != old.policy_id:
        raise GradePolicyValidationError(
            "candidate policy_id must match previous."
        )
    if new.policy_revision != old.policy_revision + 1:
        raise GradePolicyValidationError(
            "candidate policy_revision must be exactly one greater than previous."
        )
    if new.supersedes_revision != old.policy_revision:
        raise GradePolicyValidationError(
            "candidate supersedes_revision must identify previous revision."
        )
    if new.revised_at < old.revised_at:
        raise GradePolicyValidationError(
            "candidate revised_at must not be earlier than previous revised_at."
        )
    return new


def grade_policy_reference(value: GradePolicyRevision) -> GradePolicyReference:
    """Return the exact digest-bound reference for one policy revision."""

    revision = validate_grade_policy_revision(value)
    digest = hashlib.sha256(
        grade_policy_revision_to_json_bytes(revision)
    ).hexdigest()
    return GradePolicyReference(
        class_id=revision.class_id,
        policy_id=revision.policy_id,
        policy_revision=revision.policy_revision,
        policy_sha256=digest,
    )


def grade_policy_reference_to_dict(
    value: GradePolicyReference,
) -> dict[str, object]:
    """Convert an exact policy reference to JSON-native data."""

    if not isinstance(value, GradePolicyReference):
        raise GradePolicyValidationError(
            "policy reference must be a GradePolicyReference."
        )
    validated = GradePolicyReference(
        value.class_id,
        value.policy_id,
        value.policy_revision,
        value.policy_sha256,
    )
    return {
        "class_id": validated.class_id,
        "policy_id": validated.policy_id,
        "policy_revision": validated.policy_revision,
        "policy_sha256": validated.policy_sha256,
    }


def grade_policy_reference_from_dict(data: object) -> GradePolicyReference:
    """Parse an exact Grade-policy reference."""

    mapping = _exact_mapping(
        data,
        _POLICY_REFERENCE_KEYS,
        "Grade policy reference",
    )
    return GradePolicyReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        policy_sha256=_require_str(
            mapping["policy_sha256"],
            "policy_sha256",
        ),
    )


def grade_policy_revision_to_dict(
    value: GradePolicyRevision,
) -> dict[str, object]:
    """Convert a validated Grade-policy revision to exact JSON-native data."""

    policy = validate_grade_policy_revision(value)
    return {
        "schema_version": policy.schema_version,
        "record_type": policy.record_type,
        "class_id": policy.class_id,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "title": policy.title,
        "calculation_family": policy.calculation_family,
        "configuration": _configuration_to_dict(policy.configuration),
        "state_treatment": _state_treatment_to_dict(policy.state_treatment),
        "reassessment_handling": _reassessment_to_dict(
            policy.reassessment_handling
        ),
        "rounding": _rounding_to_dict(policy.rounding),
        "actor": _actor_to_dict(policy.actor),
        "rationale": policy.rationale,
        "revised_at": policy.revised_at.isoformat(),
    }


def grade_policy_revision_from_dict(data: object) -> GradePolicyRevision:
    """Parse one exact Grade-policy revision mapping."""

    mapping = _exact_mapping(data, _POLICY_KEYS, "Grade policy revision")
    family_text = _require_str(
        mapping["calculation_family"],
        "calculation_family",
    )
    if family_text not in _CALCULATION_FAMILIES:
        raise GradePolicyValidationError(
            "calculation_family must be one of: "
            "conventional, hybrid, standards_based."
        )
    family = cast(GradeCalculationFamily, family_text)
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None and (
        isinstance(supersedes, bool) or not isinstance(supersedes, int)
    ):
        raise GradePolicyValidationError(
            "supersedes_revision must be an integer or null."
        )
    rationale = mapping["rationale"]
    if rationale is not None and not isinstance(rationale, str):
        raise GradePolicyValidationError(
            "rationale must be a string or null."
        )
    return GradePolicyRevision(
        schema_version=_require_str(
            mapping["schema_version"],
            "schema_version",
        ),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        supersedes_revision=supersedes,
        title=_require_str(mapping["title"], "title"),
        calculation_family=family,
        configuration=_configuration_from_dict(
            family,
            mapping["configuration"],
        ),
        state_treatment=_state_treatment_from_dict(
            mapping["state_treatment"]
        ),
        reassessment_handling=_reassessment_from_dict(
            mapping["reassessment_handling"]
        ),
        rounding=_rounding_from_dict(mapping["rounding"]),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=rationale,
        revised_at=_datetime_from_text(
            mapping["revised_at"],
            "revised_at",
        ),
    )


def grade_policy_revision_to_json_bytes(value: GradePolicyRevision) -> bytes:
    """Return deterministic canonical UTF-8 bytes for one policy revision."""

    return _canonical_json_bytes(grade_policy_revision_to_dict(value))


def grade_policy_revision_from_json_bytes(data: bytes) -> GradePolicyRevision:
    """Parse exact canonical Grade-policy revision bytes."""

    decoded = _decode_json(data, "Grade policy revision")
    policy = grade_policy_revision_from_dict(decoded)
    if grade_policy_revision_to_json_bytes(policy) != data:
        raise GradePolicySerializationError(
            "Grade policy revision bytes are not the canonical encoding."
        )
    return policy


def _configuration_to_dict(
    value: GradePolicyConfiguration,
) -> dict[str, object]:
    if isinstance(value, ConventionalGradeConfiguration):
        return _conventional_to_dict(value)
    if isinstance(value, StandardsBasedGradeConfiguration):
        return _standards_to_dict(value)
    if isinstance(value, HybridGradeConfiguration):
        return _hybrid_to_dict(value)
    raise GradePolicyValidationError(
        "configuration is not a supported Grade policy configuration."
    )


def _configuration_from_dict(
    family: GradeCalculationFamily,
    data: object,
) -> GradePolicyConfiguration:
    if family == "conventional":
        return _conventional_from_dict(data)
    if family == "standards_based":
        return _standards_from_dict(data)
    return _hybrid_from_dict(data)


def _item_reference_to_dict(
    value: GradePolicyItemReference,
) -> dict[str, object]:
    if not isinstance(value, GradePolicyItemReference):
        raise GradePolicyValidationError(
            "grade_item must be a GradePolicyItemReference."
        )
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "grade_item_revision_sha256": value.grade_item_revision_sha256,
    }


def _item_reference_from_dict(data: object) -> GradePolicyItemReference:
    mapping = _exact_mapping(
        data,
        _ITEM_REFERENCE_KEYS,
        "Grade policy item reference",
    )
    return GradePolicyItemReference(
        class_id=_require_str(mapping["class_id"], "grade_item.class_id"),
        grade_item_id=_require_str(
            mapping["grade_item_id"],
            "grade_item.grade_item_id",
        ),
        grade_item_revision=_require_int(
            mapping["grade_item_revision"],
            "grade_item.grade_item_revision",
        ),
        grade_item_revision_sha256=_require_str(
            mapping["grade_item_revision_sha256"],
            "grade_item.grade_item_revision_sha256",
        ),
    )


def _item_participation_to_dict(
    value: GradePolicyItemParticipation,
) -> dict[str, object]:
    if not isinstance(value, GradePolicyItemParticipation):
        raise GradePolicyValidationError(
            "item must be GradePolicyItemParticipation."
        )
    return {
        "grade_item": _item_reference_to_dict(value.grade_item),
        "category_id": value.category_id,
        "weight": (
            _decimal_text(value.weight, "weight")
            if value.weight is not None
            else None
        ),
    }


def _item_participation_from_dict(
    data: object,
) -> GradePolicyItemParticipation:
    mapping = _exact_mapping(
        data,
        _ITEM_PARTICIPATION_KEYS,
        "Grade policy item participation",
    )
    category = mapping["category_id"]
    if category is not None and not isinstance(category, str):
        raise GradePolicyValidationError(
            "category_id must be a string or null."
        )
    weight = _optional_decimal_from_text(mapping["weight"], "weight")
    return GradePolicyItemParticipation(
        grade_item=_item_reference_from_dict(mapping["grade_item"]),
        category_id=category,
        weight=weight,
    )


def _category_to_dict(value: GradePolicyCategory) -> dict[str, object]:
    if not isinstance(value, GradePolicyCategory):
        raise GradePolicyValidationError(
            "category must be a GradePolicyCategory."
        )
    return {
        "category_id": value.category_id,
        "title": value.title,
        "weight": _decimal_text(value.weight, "weight"),
    }


def _category_from_dict(data: object) -> GradePolicyCategory:
    mapping = _exact_mapping(data, _CATEGORY_KEYS, "Grade policy category")
    return GradePolicyCategory(
        category_id=_require_str(mapping["category_id"], "category_id"),
        title=_require_str(mapping["title"], "title"),
        weight=_decimal_from_text(mapping["weight"], "weight"),
    )


def _conventional_to_dict(
    value: ConventionalGradeConfiguration,
) -> dict[str, object]:
    if not isinstance(value, ConventionalGradeConfiguration):
        raise GradePolicyValidationError(
            "configuration must be ConventionalGradeConfiguration."
        )
    return {
        "mode": value.mode,
        "items": [_item_participation_to_dict(item) for item in value.items],
        "categories": [_category_to_dict(item) for item in value.categories],
    }


def _conventional_from_dict(data: object) -> ConventionalGradeConfiguration:
    mapping = _exact_mapping(
        data,
        _CONVENTIONAL_KEYS,
        "conventional Grade configuration",
    )
    items = _require_list(mapping["items"], "items")
    categories = _require_list(mapping["categories"], "categories")
    mode = _require_str(mapping["mode"], "mode")
    return ConventionalGradeConfiguration(
        mode=cast(ConventionalGradeMode, mode),
        items=tuple(_item_participation_from_dict(item) for item in items),
        categories=tuple(_category_from_dict(item) for item in categories),
    )


def _standard_participation_to_dict(
    value: StandardGradeParticipation,
) -> dict[str, object]:
    if not isinstance(value, StandardGradeParticipation):
        raise GradePolicyValidationError(
            "standard must be StandardGradeParticipation."
        )
    return {
        "standard_id": value.standard_id,
        "weight": _decimal_text(value.weight, "weight"),
    }


def _standard_participation_from_dict(
    data: object,
) -> StandardGradeParticipation:
    mapping = _exact_mapping(
        data,
        _STANDARD_PARTICIPATION_KEYS,
        "standard Grade participation",
    )
    return StandardGradeParticipation(
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        weight=_decimal_from_text(mapping["weight"], "weight"),
    )


def _conversion_to_dict(
    value: ProficiencyGradeConversion,
) -> dict[str, object]:
    if not isinstance(value, ProficiencyGradeConversion):
        raise GradePolicyValidationError(
            "conversion must be ProficiencyGradeConversion."
        )
    return {
        "proficiency_level_id": value.proficiency_level_id,
        "grade_value": _decimal_text(
            value.grade_value,
            "grade_value",
            allow_zero=True,
        ),
    }


def _conversion_from_dict(data: object) -> ProficiencyGradeConversion:
    mapping = _exact_mapping(
        data,
        _CONVERSION_KEYS,
        "proficiency Grade conversion",
    )
    return ProficiencyGradeConversion(
        proficiency_level_id=_require_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        grade_value=_decimal_from_text(
            mapping["grade_value"],
            "grade_value",
            allow_zero=True,
        ),
    )


def _proficiency_scale_reference_to_dict(
    value: ProficiencyScaleReference,
) -> dict[str, object]:
    if not isinstance(value, ProficiencyScaleReference):
        raise GradePolicyValidationError(
            "target_scale must be ProficiencyScaleReference."
        )
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _proficiency_scale_reference_from_dict(
    data: object,
) -> ProficiencyScaleReference:
    mapping = _exact_mapping(
        data,
        _SCALE_REFERENCE_KEYS,
        "proficiency scale reference",
    )
    try:
        return ProficiencyScaleReference(
            class_id=_require_str(mapping["class_id"], "target_scale.class_id"),
            scale_id=_require_str(mapping["scale_id"], "target_scale.scale_id"),
            scale_revision=_require_int(
                mapping["scale_revision"],
                "target_scale.scale_revision",
            ),
            scale_sha256=_require_str(
                mapping["scale_sha256"],
                "target_scale.scale_sha256",
            ),
        )
    except ValueError as error:
        raise GradePolicyValidationError(
            f"target_scale is invalid: {error}"
        ) from error


def _standards_to_dict(
    value: StandardsBasedGradeConfiguration,
) -> dict[str, object]:
    if not isinstance(value, StandardsBasedGradeConfiguration):
        raise GradePolicyValidationError(
            "configuration must be StandardsBasedGradeConfiguration."
        )
    return {
        "target_scale": _proficiency_scale_reference_to_dict(
            value.target_scale
        ),
        "standards": [
            _standard_participation_to_dict(item)
            for item in value.standards
        ],
        "conversions": [
            _conversion_to_dict(item) for item in value.conversions
        ],
        "aggregation_strategy": value.aggregation_strategy,
        "minimum_calculated_results": value.minimum_calculated_results,
    }


def _standards_from_dict(data: object) -> StandardsBasedGradeConfiguration:
    mapping = _exact_mapping(
        data,
        _STANDARDS_KEYS,
        "standards-based Grade configuration",
    )
    standards = _require_list(mapping["standards"], "standards")
    conversions = _require_list(mapping["conversions"], "conversions")
    target_scale = _proficiency_scale_reference_from_dict(
        mapping["target_scale"]
    )
    strategy = _require_str(
        mapping["aggregation_strategy"],
        "aggregation_strategy",
    )
    return StandardsBasedGradeConfiguration(
        target_scale=target_scale,
        standards=tuple(
            _standard_participation_from_dict(item)
            for item in standards
        ),
        conversions=tuple(
            _conversion_from_dict(item) for item in conversions
        ),
        aggregation_strategy=cast(
            StandardsGradeAggregationStrategy,
            strategy,
        ),
        minimum_calculated_results=_require_int(
            mapping["minimum_calculated_results"],
            "minimum_calculated_results",
        ),
    )


def _hybrid_to_dict(value: HybridGradeConfiguration) -> dict[str, object]:
    if not isinstance(value, HybridGradeConfiguration):
        raise GradePolicyValidationError(
            "configuration must be HybridGradeConfiguration."
        )
    return {
        "conventional": _conventional_to_dict(value.conventional),
        "standards_based": _standards_to_dict(value.standards_based),
        "conventional_weight": _decimal_text(
            value.conventional_weight,
            "conventional_weight",
        ),
        "standards_weight": _decimal_text(
            value.standards_weight,
            "standards_weight",
        ),
    }


def _hybrid_from_dict(data: object) -> HybridGradeConfiguration:
    mapping = _exact_mapping(
        data,
        _HYBRID_KEYS,
        "hybrid Grade configuration",
    )
    return HybridGradeConfiguration(
        conventional=_conventional_from_dict(mapping["conventional"]),
        standards_based=_standards_from_dict(mapping["standards_based"]),
        conventional_weight=_decimal_from_text(
            mapping["conventional_weight"],
            "conventional_weight",
        ),
        standards_weight=_decimal_from_text(
            mapping["standards_weight"],
            "standards_weight",
        ),
    )


def _state_treatment_to_dict(
    value: GradeStateTreatment,
) -> dict[str, object]:
    if not isinstance(value, GradeStateTreatment):
        raise GradePolicyValidationError(
            "state_treatment must be GradeStateTreatment."
        )
    return {field_name: getattr(value, field_name) for field_name in _STATE_FIELDS}


def _state_treatment_from_dict(data: object) -> GradeStateTreatment:
    mapping = _exact_mapping(data, _STATE_KEYS, "Grade state treatment")
    values: dict[str, GradeStateConsequence] = {}
    for field_name in _STATE_FIELDS:
        values[field_name] = cast(
            GradeStateConsequence,
            _require_str(mapping[field_name], field_name),
        )
    return GradeStateTreatment(
        missing=values["missing"],
        pending=values["pending"],
        incomplete=values["incomplete"],
        excused=values["excused"],
        excluded=values["excluded"],
        not_applicable=values["not_applicable"],
        insufficient_evidence=values["insufficient_evidence"],
        unavailable=values["unavailable"],
        withdrawn=values["withdrawn"],
        invalid=values["invalid"],
        unresolved=values["unresolved"],
    )


def _reassessment_to_dict(
    value: GradeReassessmentHandling,
) -> dict[str, object]:
    if not isinstance(value, GradeReassessmentHandling):
        raise GradePolicyValidationError(
            "reassessment_handling must be GradeReassessmentHandling."
        )
    return {
        "selection_authority": value.selection_authority,
        "unresolved_handling": value.unresolved_handling,
    }


def _reassessment_from_dict(data: object) -> GradeReassessmentHandling:
    mapping = _exact_mapping(
        data,
        _REASSESSMENT_KEYS,
        "Grade reassessment handling",
    )
    return GradeReassessmentHandling(
        selection_authority=cast(
            GradeReassessmentSelectionAuthority,
            _require_str(
                mapping["selection_authority"],
                "selection_authority",
            ),
        ),
        unresolved_handling=cast(
            GradeReassessmentUnresolvedHandling,
            _require_str(
                mapping["unresolved_handling"],
                "unresolved_handling",
            ),
        ),
    )


def _rounding_to_dict(value: GradeRoundingPolicy) -> dict[str, object]:
    if not isinstance(value, GradeRoundingPolicy):
        raise GradePolicyValidationError(
            "rounding must be GradeRoundingPolicy."
        )
    return {
        "quantum": _decimal_text(value.quantum, "quantum"),
        "mode": value.mode,
        "application_stage": value.application_stage,
    }


def _rounding_from_dict(data: object) -> GradeRoundingPolicy:
    mapping = _exact_mapping(data, _ROUNDING_KEYS, "Grade rounding policy")
    return GradeRoundingPolicy(
        quantum=_decimal_from_text(mapping["quantum"], "quantum"),
        mode=cast(
            GradeRoundingMode,
            _require_str(mapping["mode"], "mode"),
        ),
        application_stage=cast(
            GradeRoundingStage,
            _require_str(
                mapping["application_stage"],
                "application_stage",
            ),
        ),
    )


def _actor_to_dict(value: GradePolicyActor) -> dict[str, object]:
    if not isinstance(value, GradePolicyActor):
        raise GradePolicyValidationError("actor must be GradePolicyActor.")
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> GradePolicyActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "Grade policy actor")
    return GradePolicyActor(
        kind=cast(
            GradePolicyActorKind,
            _require_str(mapping["kind"], "kind"),
        ),
        actor_id=_require_str(mapping["actor_id"], "actor_id"),
    )


def _validate_configuration_family(
    family: GradeCalculationFamily,
    configuration: GradePolicyConfiguration,
) -> None:
    valid = (
        (
            family == "conventional"
            and isinstance(configuration, ConventionalGradeConfiguration)
        )
        or (
            family == "standards_based"
            and isinstance(configuration, StandardsBasedGradeConfiguration)
        )
        or (
            family == "hybrid"
            and isinstance(configuration, HybridGradeConfiguration)
        )
    )
    if not valid:
        raise GradePolicyValidationError(
            "configuration type must match calculation_family."
        )


def _validate_configuration_class(
    class_id: str,
    configuration: GradePolicyConfiguration,
) -> None:
    if isinstance(configuration, ConventionalGradeConfiguration):
        _validate_conventional_class(class_id, configuration)
        return
    if isinstance(configuration, StandardsBasedGradeConfiguration):
        _validate_standards_class(class_id, configuration)
        return
    if isinstance(configuration, HybridGradeConfiguration):
        _validate_conventional_class(class_id, configuration.conventional)
        _validate_standards_class(class_id, configuration.standards_based)
        return
    raise GradePolicyValidationError(
        "configuration is not a supported Grade policy configuration."
    )


def _validate_conventional_class(
    class_id: str,
    configuration: ConventionalGradeConfiguration,
) -> None:
    for item in configuration.items:
        if item.grade_item.class_id != class_id:
            raise GradePolicyValidationError(
                "Grade Item reference class_id must match policy class_id."
            )


def _validate_standards_class(
    class_id: str,
    configuration: StandardsBasedGradeConfiguration,
) -> None:
    if configuration.target_scale.class_id != class_id:
        raise GradePolicyValidationError(
            "target_scale class_id must match policy class_id."
        )


def _reject_duplicate_grade_items(
    items: tuple[GradePolicyItemParticipation, ...],
) -> None:
    keys = [
        (
            item.grade_item.class_id,
            item.grade_item.grade_item_id,
        )
        for item in items
    ]
    if len(set(keys)) != len(keys):
        raise GradePolicyValidationError(
            "Grade Item participation must not contain duplicate logical items."
        )


def _require_complete_weighting(
    values: list[Decimal],
    label: str,
) -> None:
    if not values:
        raise GradePolicyValidationError(
            f"{label} weighting must not be empty."
        )
    if sum(values, Decimal("0")) != Decimal("1"):
        raise GradePolicyValidationError(
            f"{label} weights must sum exactly to 1."
        )


def _validate_revision_pair(
    revision: int,
    supersedes: int | None,
) -> None:
    if revision == 1:
        if supersedes is not None:
            raise GradePolicyValidationError(
                "policy revision 1 must use supersedes_revision=null."
            )
    elif supersedes != revision - 1:
        raise GradePolicyValidationError(
            "supersedes_revision must equal policy_revision - 1."
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
        raise GradePolicySerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise GradePolicySerializationError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GradePolicySerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except GradePolicySerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise GradePolicySerializationError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GradePolicySerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise GradePolicySerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise GradePolicyValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise GradePolicyValidationError(
            f"{label} keys must be strings."
        )
    actual = frozenset(cast(Mapping[str, object], data).keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise GradePolicyValidationError(
            f"{label} must use the exact schema ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradePolicyValidationError(str(error)) from error


def _bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise GradePolicyValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise GradePolicyValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise GradePolicyValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(
        unicodedata.category(character) in {"Cc", "Zl", "Zp"}
        for character in value
    ):
        raise GradePolicyValidationError(
            f"{field_name} must be single-line and free of control characters."
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


def _positive_int(value: object, field_name: str) -> int:
    integer = _require_int(value, field_name)
    if integer <= 0:
        raise GradePolicyValidationError(
            f"{field_name} must be greater than zero."
        )
    return integer


def _optional_positive_int(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _positive_decimal(value: object, field_name: str) -> Decimal:
    return _decimal_value(
        value,
        field_name,
        allow_zero=False,
    )


def _nonnegative_decimal(value: object, field_name: str) -> Decimal:
    return _decimal_value(
        value,
        field_name,
        allow_zero=True,
    )


def _decimal_value(
    value: object,
    field_name: str,
    *,
    allow_zero: bool,
) -> Decimal:
    if not isinstance(value, Decimal):
        raise GradePolicyValidationError(
            f"{field_name} must be a Decimal."
        )
    if not value.is_finite():
        raise GradePolicyValidationError(
            f"{field_name} must be finite."
        )
    if value < 0 or (not allow_zero and value == 0):
        requirement = "nonnegative" if allow_zero else "greater than zero"
        raise GradePolicyValidationError(
            f"{field_name} must be {requirement}."
        )
    return Decimal(
        _decimal_text(
            value,
            field_name,
            allow_zero=allow_zero,
        )
    )


def _decimal_text(
    value: Decimal,
    field_name: str,
    *,
    allow_zero: bool = False,
) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise GradePolicyValidationError(
            f"{field_name} must be a finite Decimal."
        )
    if value < 0 or (not allow_zero and value == 0):
        requirement = "nonnegative" if allow_zero else "greater than zero"
        raise GradePolicyValidationError(
            f"{field_name} must be {requirement}."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        text = "0"
    return text


def _decimal_from_text(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = False,
) -> Decimal:
    if not isinstance(value, str):
        raise GradePolicyValidationError(
            f"{field_name} must be decimal text."
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise GradePolicyValidationError(
            f"{field_name} must be valid decimal text."
        ) from error
    return _decimal_value(
        parsed,
        field_name,
        allow_zero=allow_zero,
    )


def _optional_decimal_from_text(
    value: object,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None
    return _decimal_from_text(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradePolicyValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GradePolicyValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise GradePolicyValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise GradePolicyValidationError(
            f"{field_name} must be a valid ISO datetime string."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePolicyValidationError(
            f"{field_name} must be a string."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GradePolicyValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise GradePolicyValidationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


def _typed_tuple(
    value: object,
    expected_type: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if not isinstance(value, tuple):
        raise GradePolicyValidationError(
            f"{field_name} must be a tuple."
        )
    if any(not isinstance(item, expected_type) for item in value):
        raise GradePolicyValidationError(
            f"{field_name} contains an invalid value."
        )
    return cast(tuple[_T, ...], value)
