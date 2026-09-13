"""Pure conventional points/percentage Grade calculation for Meridian v0.3.

The module consumes an already-resolved, exact academic basis.  It does not
scan a workspace, authorize producer evidence, select Grade policies or
activations, select attempts, change reassessment state, apply overrides,
create ReportingSnapshots, or write an official Grade.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
)
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.evidence import NativePointValue
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyCategory,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyReference,
    GradePolicyRevision,
    GradeRoundingPolicy,
    GradeStateConsequence,
    GradeStateTreatment,
    grade_policy_reference,
    grade_policy_reference_from_dict,
    grade_policy_reference_to_dict,
    validate_grade_policy_revision,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
    grade_policy_activation_reference,
    grade_policy_activation_reference_from_dict,
    grade_policy_activation_reference_to_dict,
    validate_grade_policy_activation_decision,
)

CONVENTIONAL_GRADE_ALGORITHM_VERSION: Final[str] = "1"
MAXIMUM_CONVENTIONAL_GRADE_PROVENANCE_KEY_LENGTH: Final[int] = 512
CONVENTIONAL_GRADE_RESULT_SCHEMA_VERSION: Final[str] = "1"
CONVENTIONAL_GRADE_RESULT_RECORD_TYPE: Final[str] = (
    "meridian_conventional_grade_result"
)

ConventionalGradeFreshnessStatus: TypeAlias = Literal["current", "stale"]
ConventionalGradeStalenessReason: TypeAlias = Literal[
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "inputs_changed",
    "algorithm_changed",
]

ConventionalGradeItemState: TypeAlias = Literal[
    "points",
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
]
ConventionalGradeItemAction: TypeAlias = Literal[
    "contribute",
    "exclude",
    "blocking",
    "zero",
]
ConventionalGradeCalculationStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "insufficient",
]
ConventionalGradeCategoryStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "noncalculable",
]
ConventionalGradeProvenanceKind: TypeAlias = Literal[
    "source",
    "membership",
    "eligibility",
    "attempt_selection",
    "reassessment",
]

_NON_POINT_STATES: Final[tuple[str, ...]] = (
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
_STALENESS_REASON_ORDER: Final[tuple[ConventionalGradeStalenessReason, ...]] = (
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "inputs_changed",
    "algorithm_changed",
)
_STALENESS_REASON_SET: Final[frozenset[str]] = frozenset(_STALENESS_REASON_ORDER)
_PROVENANCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "source",
        "membership",
        "eligibility",
        "attempt_selection",
        "reassessment",
    }
)
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")
_ROUNDING = {
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    "half_down": ROUND_HALF_DOWN,
    "up": ROUND_UP,
    "down": ROUND_DOWN,
    "ceiling": ROUND_CEILING,
    "floor": ROUND_FLOOR,
}


class ConventionalGradeError(ValueError):
    """Base error for pure conventional Grade calculation contracts."""


class ConventionalGradeValidationError(ConventionalGradeError):
    """Raised when the exact calculation basis violates the contract."""


class ConventionalGradeSerializationError(ConventionalGradeError):
    """Raised when canonical calculation serialization cannot be produced."""


@dataclass(frozen=True, slots=True)
class ConventionalGradeProvenanceReference:
    """Privacy-minimal exact upstream reference used to explain one item input."""

    kind: ConventionalGradeProvenanceKind
    reference_key: str
    reference_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in _PROVENANCE_KINDS:
            raise ConventionalGradeValidationError(
                "provenance kind is not supported."
            )
        object.__setattr__(
            self,
            "reference_key",
            _bounded_reference_key(self.reference_key),
        )
        object.__setattr__(
            self,
            "reference_sha256",
            _sha256(self.reference_sha256, "reference_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ConventionalGradeItemInput:
    """Closed exact conventional input for one policy-participating Grade Item."""

    participation: GradePolicyItemParticipation
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    status: ConventionalGradeItemState
    earned: Decimal | None
    possible: Decimal | None
    reason_codes: tuple[str, ...] = ()
    provenance: tuple[ConventionalGradeProvenanceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.participation, GradePolicyItemParticipation):
            raise ConventionalGradeValidationError(
                "participation must be GradePolicyItemParticipation."
            )
        student_id = _identifier(self.student_id, "student_id")
        period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if self.status != "points" and self.status not in _NON_POINT_STATES:
            raise ConventionalGradeValidationError(
                "status is not a supported conventional Grade Item state."
            )

        earned = self.earned
        possible = self.possible
        if self.status == "points":
            if earned is None or possible is None:
                raise ConventionalGradeValidationError(
                    "points input requires earned and possible Decimals."
                )
            earned = _finite_decimal(earned, "earned")
            possible = _positive_decimal(possible, "possible")
        elif earned is not None or possible is not None:
            raise ConventionalGradeValidationError(
                "non-points input must not carry earned or possible values."
            )

        reasons = _reason_codes(self.reason_codes)
        provenance = _provenance(self.provenance)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "earned", earned)
        object.__setattr__(self, "possible", possible)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "provenance", provenance)

    @property
    def percentage(self) -> Decimal | None:
        """Return the exact unrounded item percentage when numeric."""

        if self.status != "points" or self.earned is None or self.possible is None:
            return None
        return self.earned / self.possible * Decimal("100")


@dataclass(frozen=True, slots=True)
class ConventionalGradeCalculationInput:
    """Complete immutable pure basis for one conventional Academic Period Grade."""

    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    configuration: ConventionalGradeConfiguration
    state_treatment: GradeStateTreatment
    rounding: GradeRoundingPolicy
    items: tuple[ConventionalGradeItemInput, ...]

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        target_period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if not isinstance(
            self.activation_reference,
            GradePolicyActivationReference,
        ):
            raise ConventionalGradeValidationError(
                "activation_reference must be GradePolicyActivationReference."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise ConventionalGradeValidationError(
                "policy_reference must be GradePolicyReference."
            )
        if not isinstance(self.configuration, ConventionalGradeConfiguration):
            raise ConventionalGradeValidationError(
                "configuration must be ConventionalGradeConfiguration."
            )
        if not isinstance(self.state_treatment, GradeStateTreatment):
            raise ConventionalGradeValidationError(
                "state_treatment must be GradeStateTreatment."
            )
        if not isinstance(self.rounding, GradeRoundingPolicy):
            raise ConventionalGradeValidationError(
                "rounding must be GradeRoundingPolicy."
            )

        activation = self.activation_reference
        if (
            activation.class_id != class_id
            or activation.school_year != target_period.school_year
            or activation.period_id != target_period.period_id
        ):
            raise ConventionalGradeValidationError(
                "activation_reference must match the exact class and target period."
            )
        if self.policy_reference.class_id != class_id:
            raise ConventionalGradeValidationError(
                "policy_reference.class_id must match calculation class_id."
            )

        try:
            items = tuple(self.items)
        except TypeError as error:
            raise ConventionalGradeValidationError(
                "items must be an iterable of ConventionalGradeItemInput values."
            ) from error
        if any(not isinstance(item, ConventionalGradeItemInput) for item in items):
            raise ConventionalGradeValidationError(
                "items must contain only ConventionalGradeItemInput values."
            )
        typed_items = items
        by_key: dict[tuple[str, str], ConventionalGradeItemInput] = {}
        for item in typed_items:
            key = _participation_key(item.participation)
            if key in by_key:
                raise ConventionalGradeValidationError(
                    "calculation input contains duplicate logical Grade Items."
                )
            if item.participation.grade_item.class_id != class_id:
                raise ConventionalGradeValidationError(
                    "item participation class_id must match calculation class_id."
                )
            if item.student_id != student_id:
                raise ConventionalGradeValidationError(
                    "item student_id must match calculation student_id."
                )
            if item.target_period != target_period:
                raise ConventionalGradeValidationError(
                    "item target_period must match calculation target_period."
                )
            if item.calendar_revision != calendar_revision:
                raise ConventionalGradeValidationError(
                    "item calendar_revision must match calculation calendar_revision."
                )
            by_key[key] = item

        configured = {
            _participation_key(participation): participation
            for participation in self.configuration.items
        }
        if set(by_key) != set(configured):
            raise ConventionalGradeValidationError(
                "calculation items must exactly match policy-participating Grade Items."
            )
        for key, expected in configured.items():
            if by_key[key].participation != expected:
                raise ConventionalGradeValidationError(
                    "calculation item participation must exactly match "
                    "policy authority."
                )

        canonical_items = tuple(
            sorted(
                typed_items,
                key=lambda item: (
                    item.participation.grade_item.grade_item_id,
                    item.participation.grade_item.grade_item_revision,
                ),
            )
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "items", canonical_items)


@dataclass(frozen=True, slots=True)
class ConventionalGradeReason:
    """One deterministic structured reason for blocked/insufficient calculation."""

    code: str
    grade_item: GradePolicyItemReference | None = None
    category_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _reason_code(self.code))
        if self.grade_item is not None and not isinstance(
            self.grade_item,
            GradePolicyItemReference,
        ):
            raise ConventionalGradeValidationError(
                "grade_item must be GradePolicyItemReference or null."
            )
        if self.category_id is not None:
            object.__setattr__(
                self,
                "category_id",
                _identifier(self.category_id, "category_id"),
            )


@dataclass(frozen=True, slots=True)
class ConventionalGradeItemResult:
    """Exact per-item result after source classification and policy consequence."""

    grade_item: GradePolicyItemReference
    source_state: ConventionalGradeItemState
    action: ConventionalGradeItemAction
    category_id: str | None
    weight: Decimal | None
    policy_possible_points: Decimal | None
    earned: Decimal | None
    possible: Decimal | None
    percentage: Decimal | None
    contribution: Decimal | None
    reason_codes: tuple[str, ...]
    provenance: tuple[ConventionalGradeProvenanceReference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.grade_item, GradePolicyItemReference):
            raise ConventionalGradeValidationError(
                "grade_item must be GradePolicyItemReference."
            )
        if self.source_state != "points" and self.source_state not in _NON_POINT_STATES:
            raise ConventionalGradeValidationError("invalid item-result source_state.")
        if self.action not in {"contribute", "exclude", "blocking", "zero"}:
            raise ConventionalGradeValidationError("invalid item-result action.")
        if self.category_id is not None:
            object.__setattr__(
                self,
                "category_id",
                _identifier(self.category_id, "category_id"),
            )
        for field_name in (
            "weight",
            "policy_possible_points",
            "possible",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _positive_decimal(value, field_name)
        for field_name in ("earned", "percentage", "contribution"):
            value = getattr(self, field_name)
            if value is not None:
                _finite_decimal(value, field_name)
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))
        object.__setattr__(self, "provenance", _provenance(self.provenance))


@dataclass(frozen=True, slots=True)
class ConventionalGradeCategoryResult:
    """Deterministic points-based category calculation and configured weight."""

    category_id: str
    weight: Decimal
    status: ConventionalGradeCategoryStatus
    included_grade_item_ids: tuple[str, ...]
    excluded_grade_item_ids: tuple[str, ...]
    earned: Decimal | None
    possible: Decimal | None
    fraction: Decimal | None
    contribution: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "category_id",
            _identifier(self.category_id, "category_id"),
        )
        object.__setattr__(self, "weight", _positive_decimal(self.weight, "weight"))
        if self.status not in {"calculated", "blocked", "noncalculable"}:
            raise ConventionalGradeValidationError("invalid category status.")
        object.__setattr__(
            self,
            "included_grade_item_ids",
            _identifier_tuple(self.included_grade_item_ids, "included_grade_item_ids"),
        )
        object.__setattr__(
            self,
            "excluded_grade_item_ids",
            _identifier_tuple(self.excluded_grade_item_ids, "excluded_grade_item_ids"),
        )
        if self.earned is not None:
            _finite_decimal(self.earned, "earned")
        if self.possible is not None:
            _positive_decimal(self.possible, "possible")
        if self.fraction is not None:
            _finite_decimal(self.fraction, "fraction")
        if self.contribution is not None:
            _finite_decimal(self.contribution, "contribution")
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ConventionalGradeCalculationOutcome:
    """Pure advisory conventional Grade calculation; never an official Grade."""

    status: ConventionalGradeCalculationStatus
    algorithm_version: str
    calculation_fingerprint: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    mode: str
    student_id: str
    item_results: tuple[ConventionalGradeItemResult, ...]
    category_results: tuple[ConventionalGradeCategoryResult, ...]
    total_earned: Decimal | None
    total_possible: Decimal | None
    final_fraction: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None
    reasons: tuple[ConventionalGradeReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise ConventionalGradeValidationError("invalid calculation status.")
        if self.algorithm_version != CONVENTIONAL_GRADE_ALGORITHM_VERSION:
            raise ConventionalGradeValidationError(
                "unsupported conventional Grade algorithm_version."
            )
        object.__setattr__(
            self,
            "calculation_fingerprint",
            _sha256(self.calculation_fingerprint, "calculation_fingerprint"),
        )
        object.__setattr__(
            self,
            "target_period",
            _academic_period_ref(self.target_period),
        )
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        if not isinstance(
            self.activation_reference,
            GradePolicyActivationReference,
        ):
            raise ConventionalGradeValidationError(
                "activation_reference must be GradePolicyActivationReference."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise ConventionalGradeValidationError(
                "policy_reference must be GradePolicyReference."
            )
        if self.mode not in {"total_points", "weighted_items", "weighted_categories"}:
            raise ConventionalGradeValidationError("invalid conventional Grade mode.")
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        _typed_tuple(
            self.item_results,
            ConventionalGradeItemResult,
            "item_results",
        )
        _typed_tuple(
            self.category_results,
            ConventionalGradeCategoryResult,
            "category_results",
        )
        _typed_tuple(self.reasons, ConventionalGradeReason, "reasons")
        for field_name in (
            "total_earned",
            "final_fraction",
            "unrounded_grade",
            "rounded_grade",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _finite_decimal(value, field_name)
        if self.total_possible is not None:
            _positive_decimal(self.total_possible, "total_possible")
        if self.status == "calculated":
            if (
                self.final_fraction is None
                or self.unrounded_grade is None
                or self.rounded_grade is None
            ):
                raise ConventionalGradeValidationError(
                    "calculated outcome requires exact final numeric values."
                )
        elif self.unrounded_grade is not None or self.rounded_grade is not None:
            raise ConventionalGradeValidationError(
                "nonnumeric outcome must not carry a final Grade."
            )


@dataclass(frozen=True, slots=True)
class ConventionalGradeResultSnapshot:
    """Immutable persisted wrapper around one exact conventional calculation."""

    schema_version: str
    record_type: str
    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    result_revision: int
    supersedes_revision: int | None
    algorithm_version: str
    calculation_fingerprint: str
    inputs: ConventionalGradeCalculationInput
    inputs_sha256: str
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    outcome: ConventionalGradeCalculationOutcome
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != CONVENTIONAL_GRADE_RESULT_SCHEMA_VERSION:
            raise ConventionalGradeValidationError(
                "unsupported conventional Grade result schema_version."
            )
        if self.record_type != CONVENTIONAL_GRADE_RESULT_RECORD_TYPE:
            raise ConventionalGradeValidationError(
                "record_type must identify a conventional Grade result."
            )
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        target_period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        revision = _positive_int(self.result_revision, "result_revision")
        supersedes = self.supersedes_revision
        if supersedes is not None:
            supersedes = _positive_int(supersedes, "supersedes_revision")
        if revision == 1 and supersedes is not None:
            raise ConventionalGradeValidationError(
                "result revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise ConventionalGradeValidationError(
                "result supersedes_revision must identify the prior revision."
            )
        if self.algorithm_version != CONVENTIONAL_GRADE_ALGORITHM_VERSION:
            raise ConventionalGradeValidationError(
                "unsupported conventional Grade result algorithm_version."
            )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        if not isinstance(self.inputs, ConventionalGradeCalculationInput):
            raise ConventionalGradeValidationError(
                "inputs must be ConventionalGradeCalculationInput."
            )
        exact_inputs_sha256 = conventional_grade_calculation_input_sha256(
            self.inputs
        )
        inputs_sha256 = _sha256(self.inputs_sha256, "inputs_sha256")
        if inputs_sha256 != exact_inputs_sha256:
            raise ConventionalGradeValidationError(
                "inputs_sha256 must match the exact embedded calculation inputs."
            )
        if (
            self.inputs.class_id != class_id
            or self.inputs.student_id != student_id
            or self.inputs.target_period != target_period
            or self.inputs.calendar_revision != calendar_revision
        ):
            raise ConventionalGradeValidationError(
                "result scope must match the exact embedded calculation inputs."
            )
        if not isinstance(
            self.activation_reference,
            GradePolicyActivationReference,
        ):
            raise ConventionalGradeValidationError(
                "activation_reference must be exact activation provenance."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise ConventionalGradeValidationError(
                "policy_reference must be exact Grade-policy provenance."
            )
        if self.activation_reference != self.inputs.activation_reference:
            raise ConventionalGradeValidationError(
                "result activation_reference must match embedded inputs."
            )
        if self.policy_reference != self.inputs.policy_reference:
            raise ConventionalGradeValidationError(
                "result policy_reference must match embedded inputs."
            )
        if not isinstance(self.outcome, ConventionalGradeCalculationOutcome):
            raise ConventionalGradeValidationError(
                "outcome must be ConventionalGradeCalculationOutcome."
            )
        exact_outcome = calculate_conventional_grade(self.inputs)
        if self.outcome != exact_outcome:
            raise ConventionalGradeValidationError(
                "persisted outcome must exactly reproduce from embedded inputs."
            )
        if (
            self.outcome.algorithm_version != self.algorithm_version
            or self.outcome.calculation_fingerprint != fingerprint
            or self.outcome.activation_reference != self.activation_reference
            or self.outcome.policy_reference != self.policy_reference
        ):
            raise ConventionalGradeValidationError(
                "result metadata must match the exact pure calculation outcome."
            )
        calculated_at = _aware_utc_datetime(
            self.calculated_at,
            "calculated_at",
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "result_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)
        object.__setattr__(self, "inputs_sha256", inputs_sha256)
        object.__setattr__(self, "calculated_at", calculated_at)


@dataclass(frozen=True, slots=True)
class ConventionalGradeResultReference:
    """Exact immutable conventional Grade result revision and digest."""

    class_id: str
    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    result_revision: int
    result_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            _identifier(self.class_id, "class_id"),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(
            self,
            "school_year",
            _identifier(self.school_year, "school_year"),
        )
        object.__setattr__(
            self,
            "period_id",
            _identifier(self.period_id, "period_id"),
        )
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        object.__setattr__(
            self,
            "result_revision",
            _positive_int(self.result_revision, "result_revision"),
        )
        object.__setattr__(
            self,
            "result_sha256",
            _sha256(self.result_sha256, "result_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ConventionalGradeResultFreshness:
    """Pure diagnostic comparison to explicit current calculation state."""

    status: ConventionalGradeFreshnessStatus
    reasons: tuple[ConventionalGradeStalenessReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale"}:
            raise ConventionalGradeValidationError(
                "unsupported conventional Grade freshness status."
            )
        reasons = _staleness_reasons(self.reasons)
        if self.status == "current" and reasons:
            raise ConventionalGradeValidationError(
                "current freshness status requires no staleness reasons."
            )
        if self.status == "stale" and not reasons:
            raise ConventionalGradeValidationError(
                "stale freshness status requires at least one reason."
            )
        object.__setattr__(self, "reasons", reasons)


def resolve_conventional_grade_item_input(
    *,
    participation: GradePolicyItemParticipation,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    point_observations: tuple[NativePointValue, ...],
    no_point_state: ConventionalGradeItemState,
    reason_codes: tuple[str, ...] = (),
    provenance: tuple[ConventionalGradeProvenanceReference, ...] = (),
) -> ConventionalGradeItemInput:
    """Purely enforce v1's zero/one/multiple operative point-observation rule."""

    if not isinstance(participation, GradePolicyItemParticipation):
        raise ConventionalGradeValidationError(
            "participation must be GradePolicyItemParticipation."
        )
    try:
        observations = tuple(point_observations)
    except TypeError as error:
        raise ConventionalGradeValidationError(
            "point_observations must be an iterable of NativePointValue values."
        ) from error
    if any(not isinstance(value, NativePointValue) for value in observations):
        raise ConventionalGradeValidationError(
            "point_observations must contain only NativePointValue values."
        )
    if len(observations) > 1:
        return ConventionalGradeItemInput(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            status="unresolved",
            earned=None,
            possible=None,
            reason_codes=reason_codes + ("multiple_point_observations",),
            provenance=provenance,
        )
    if not observations:
        if no_point_state == "points":
            raise ConventionalGradeValidationError(
                "zero point observations require an explicit non-points state."
            )
        return ConventionalGradeItemInput(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            status=no_point_state,
            earned=None,
            possible=None,
            reason_codes=reason_codes,
            provenance=provenance,
        )

    observation = observations[0]
    earned = _native_number_to_decimal(observation.earned)
    possible = _native_number_to_decimal(observation.possible)
    policy_possible = participation.possible_points
    if policy_possible is not None and possible != policy_possible:
        return ConventionalGradeItemInput(
            participation=participation,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            status="unresolved",
            earned=None,
            possible=None,
            reason_codes=reason_codes + ("possible_points_mismatch",),
            provenance=provenance,
        )
    return ConventionalGradeItemInput(
        participation=participation,
        student_id=student_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        status="points",
        earned=earned,
        possible=possible,
        reason_codes=reason_codes,
        provenance=provenance,
    )


def create_conventional_grade_calculation_input(
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    items: tuple[ConventionalGradeItemInput, ...],
) -> ConventionalGradeCalculationInput:
    """Bind exact activated conventional policy authority to resolved item inputs."""

    try:
        validated_policy = validate_grade_policy_revision(policy)
    except ValueError as error:
        raise ConventionalGradeValidationError(str(error)) from error
    try:
        validated_activation = validate_grade_policy_activation_decision(activation)
    except ValueError as error:
        raise ConventionalGradeValidationError(str(error)) from error
    if validated_policy.calculation_family != "conventional" or not isinstance(
        validated_policy.configuration,
        ConventionalGradeConfiguration,
    ):
        raise ConventionalGradeValidationError(
            "conventional calculation requires an exact conventional Grade policy."
        )
    if validated_activation.decision != "activate":
        raise ConventionalGradeValidationError(
            "conventional calculation requires an activated policy decision."
        )
    exact_policy_reference = grade_policy_reference(validated_policy)
    if validated_activation.policy_reference != exact_policy_reference:
        raise ConventionalGradeValidationError(
            "activation must reference the exact supplied Grade-policy revision."
        )
    exact_period = _academic_period_ref(target_period)
    if (
        validated_activation.class_id != validated_policy.class_id
        or validated_activation.target_period != exact_period
        or validated_activation.calendar_revision != calendar_revision
    ):
        raise ConventionalGradeValidationError(
            "activation must match the exact calculation class/period/calendar "
            "revision."
        )
    return ConventionalGradeCalculationInput(
        class_id=validated_policy.class_id,
        student_id=student_id,
        target_period=exact_period,
        calendar_revision=calendar_revision,
        activation_reference=grade_policy_activation_reference(validated_activation),
        policy_reference=exact_policy_reference,
        configuration=validated_policy.configuration,
        state_treatment=validated_policy.state_treatment,
        rounding=validated_policy.rounding,
        items=items,
    )


def conventional_grade_calculation_fingerprint(
    inputs: ConventionalGradeCalculationInput,
) -> str:
    """Return a stable digest over the exact pure academic calculation basis."""

    if not isinstance(inputs, ConventionalGradeCalculationInput):
        raise ConventionalGradeValidationError(
            "inputs must be ConventionalGradeCalculationInput."
        )
    payload = {
        "algorithm_version": CONVENTIONAL_GRADE_ALGORITHM_VERSION,
        "basis": conventional_grade_calculation_input_to_dict(inputs),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def calculate_conventional_grade(
    inputs: ConventionalGradeCalculationInput,
) -> ConventionalGradeCalculationOutcome:
    """Purely calculate one conventional Academic Period Grade."""

    if not isinstance(inputs, ConventionalGradeCalculationInput):
        raise ConventionalGradeValidationError(
            "inputs must be ConventionalGradeCalculationInput."
        )
    fingerprint = conventional_grade_calculation_fingerprint(inputs)
    item_results = tuple(
        _resolve_item_result(item, inputs.state_treatment)
        for item in inputs.items
    )
    blocking_reasons = tuple(
        ConventionalGradeReason(
            code="blocking_item",
            grade_item=result.grade_item,
            category_id=result.category_id,
        )
        for result in item_results
        if result.action == "blocking"
    )

    mode = inputs.configuration.mode
    category_results: tuple[ConventionalGradeCategoryResult, ...] = ()
    total_earned: Decimal | None = None
    total_possible: Decimal | None = None
    final_fraction: Decimal | None = None
    reasons: tuple[ConventionalGradeReason, ...] = blocking_reasons

    if mode == "total_points":
        total_earned, total_possible = _total_points(item_results)
        if not blocking_reasons and total_possible is not None:
            final_fraction = cast(Decimal, total_earned) / total_possible
    elif mode == "weighted_items":
        if not blocking_reasons:
            contributions = [
                result.contribution
                for result in item_results
                if result.action in {"contribute", "zero"}
                and result.contribution is not None
            ]
            if contributions:
                final_fraction = sum(contributions, Decimal("0"))
    else:
        category_results = _weighted_category_results(
            inputs.configuration,
            item_results,
        )
        if not blocking_reasons:
            contributions = [
                category.contribution
                for category in category_results
                if category.status == "calculated"
                and category.contribution is not None
            ]
            if contributions:
                final_fraction = sum(contributions, Decimal("0"))

    status: ConventionalGradeCalculationStatus
    unrounded_grade: Decimal | None = None
    rounded_grade: Decimal | None = None
    if blocking_reasons:
        status = "blocked"
    elif final_fraction is None:
        status = "insufficient"
        reasons = reasons + (ConventionalGradeReason("no_calculable_items"),)
    else:
        status = "calculated"
        unrounded_grade = final_fraction * Decimal("100")
        rounded_grade = _round_final_grade(unrounded_grade, inputs.rounding)

    return ConventionalGradeCalculationOutcome(
        status=status,
        algorithm_version=CONVENTIONAL_GRADE_ALGORITHM_VERSION,
        calculation_fingerprint=fingerprint,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        mode=mode,
        student_id=inputs.student_id,
        item_results=item_results,
        category_results=category_results,
        total_earned=total_earned,
        total_possible=total_possible,
        final_fraction=final_fraction,
        unrounded_grade=unrounded_grade,
        rounded_grade=rounded_grade,
        reasons=reasons,
    )


def conventional_grade_calculation_input_to_dict(
    value: ConventionalGradeCalculationInput,
) -> dict[str, object]:
    """Serialize the exact pure calculation basis to deterministic JSON-native data."""

    if not isinstance(value, ConventionalGradeCalculationInput):
        raise ConventionalGradeValidationError(
            "value must be ConventionalGradeCalculationInput."
        )
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "configuration": _configuration_to_dict(value.configuration),
        "state_treatment": _state_treatment_to_dict(value.state_treatment),
        "rounding": _rounding_to_dict(value.rounding),
        "items": [_item_input_to_dict(item) for item in value.items],
    }


def conventional_grade_calculation_input_to_json_bytes(
    value: ConventionalGradeCalculationInput,
) -> bytes:
    """Return canonical UTF-8 bytes for one pure conventional calculation basis."""

    return _canonical_json_bytes(conventional_grade_calculation_input_to_dict(value))


def conventional_grade_calculation_outcome_to_dict(
    value: ConventionalGradeCalculationOutcome,
) -> dict[str, object]:
    """Serialize a pure outcome for diagnostics, tests, and persistence reuse."""

    if not isinstance(value, ConventionalGradeCalculationOutcome):
        raise ConventionalGradeValidationError(
            "value must be ConventionalGradeCalculationOutcome."
        )
    return {
        "status": value.status,
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "mode": value.mode,
        "student_id": value.student_id,
        "item_results": [_item_result_to_dict(item) for item in value.item_results],
        "category_results": [
            _category_result_to_dict(category) for category in value.category_results
        ],
        "total_earned": _optional_decimal_text(value.total_earned),
        "total_possible": _optional_decimal_text(value.total_possible),
        "final_fraction": _optional_decimal_text(value.final_fraction),
        "unrounded_grade": _optional_decimal_text(value.unrounded_grade),
        "rounded_grade": _optional_decimal_text(value.rounded_grade),
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def conventional_grade_calculation_outcome_to_json_bytes(
    value: ConventionalGradeCalculationOutcome,
) -> bytes:
    """Return canonical UTF-8 bytes for one pure outcome."""

    return _canonical_json_bytes(conventional_grade_calculation_outcome_to_dict(value))


def _resolve_item_result(
    item: ConventionalGradeItemInput,
    treatment: GradeStateTreatment,
) -> ConventionalGradeItemResult:
    participation = item.participation
    status = item.status
    reasons = item.reason_codes
    earned = item.earned
    possible = item.possible

    if status == "points":
        if earned is None or possible is None:  # defensive; model forbids this
            raise ConventionalGradeValidationError(
                "points input unexpectedly lacks numeric values."
            )
        if (
            participation.possible_points is not None
            and possible != participation.possible_points
        ):
            status = "unresolved"
            earned = None
            possible = None
            reasons = reasons + ("possible_points_mismatch",)
        else:
            percentage = earned / possible * Decimal("100")
            contribution = None
            if participation.weight is not None:
                contribution = earned / possible * participation.weight
            return ConventionalGradeItemResult(
                grade_item=participation.grade_item,
                source_state="points",
                action="contribute",
                category_id=participation.category_id,
                weight=participation.weight,
                policy_possible_points=participation.possible_points,
                earned=earned,
                possible=possible,
                percentage=percentage,
                contribution=contribution,
                reason_codes=reasons,
                provenance=item.provenance,
            )

    consequence = _state_consequence(treatment, status)
    if consequence == "zero":
        if participation.weight is not None:
            return ConventionalGradeItemResult(
                grade_item=participation.grade_item,
                source_state=status,
                action="zero",
                category_id=participation.category_id,
                weight=participation.weight,
                policy_possible_points=None,
                earned=None,
                possible=None,
                percentage=Decimal("0"),
                contribution=Decimal("0"),
                reason_codes=reasons,
                provenance=item.provenance,
            )
        policy_possible = participation.possible_points
        if policy_possible is None:
            raise ConventionalGradeValidationError(
                "points-based zero consequence requires policy possible_points."
            )
        return ConventionalGradeItemResult(
            grade_item=participation.grade_item,
            source_state=status,
            action="zero",
            category_id=participation.category_id,
            weight=None,
            policy_possible_points=policy_possible,
            earned=Decimal("0"),
            possible=policy_possible,
            percentage=Decimal("0"),
            contribution=None,
            reason_codes=reasons,
            provenance=item.provenance,
        )
    return ConventionalGradeItemResult(
        grade_item=participation.grade_item,
        source_state=status,
        action=cast(ConventionalGradeItemAction, consequence),
        category_id=participation.category_id,
        weight=participation.weight,
        policy_possible_points=participation.possible_points,
        earned=None,
        possible=None,
        percentage=None,
        contribution=None,
        reason_codes=reasons,
        provenance=item.provenance,
    )


def _state_consequence(
    treatment: GradeStateTreatment,
    state: ConventionalGradeItemState,
) -> GradeStateConsequence:
    if state == "points":
        raise ConventionalGradeValidationError(
            "points do not use non-Grade state treatment."
        )
    values: dict[str, GradeStateConsequence] = {
        "missing": treatment.missing,
        "pending": treatment.pending,
        "incomplete": treatment.incomplete,
        "excused": treatment.excused,
        "excluded": treatment.excluded,
        "not_applicable": treatment.not_applicable,
        "insufficient_evidence": treatment.insufficient_evidence,
        "unavailable": treatment.unavailable,
        "withdrawn": treatment.withdrawn,
        "invalid": treatment.invalid,
        "unresolved": treatment.unresolved,
    }
    return values[state]


def _total_points(
    items: tuple[ConventionalGradeItemResult, ...],
) -> tuple[Decimal | None, Decimal | None]:
    numeric = [
        item
        for item in items
        if item.action in {"contribute", "zero"}
        and item.earned is not None
        and item.possible is not None
    ]
    if not numeric:
        return None, None
    return (
        sum((cast(Decimal, item.earned) for item in numeric), Decimal("0")),
        sum((cast(Decimal, item.possible) for item in numeric), Decimal("0")),
    )


def _weighted_category_results(
    configuration: ConventionalGradeConfiguration,
    items: tuple[ConventionalGradeItemResult, ...],
) -> tuple[ConventionalGradeCategoryResult, ...]:
    results: list[ConventionalGradeCategoryResult] = []
    for category in configuration.categories:
        members = tuple(
            item for item in items if item.category_id == category.category_id
        )
        blocked = tuple(item for item in members if item.action == "blocking")
        numeric = tuple(
            item
            for item in members
            if item.action in {"contribute", "zero"}
            and item.earned is not None
            and item.possible is not None
        )
        excluded = tuple(
            item for item in members if item.action == "exclude"
        )
        if blocked:
            results.append(
                ConventionalGradeCategoryResult(
                    category_id=category.category_id,
                    weight=category.weight,
                    status="blocked",
                    included_grade_item_ids=tuple(
                        item.grade_item.grade_item_id for item in numeric
                    ),
                    excluded_grade_item_ids=tuple(
                        item.grade_item.grade_item_id for item in excluded
                    ),
                    earned=None,
                    possible=None,
                    fraction=None,
                    contribution=None,
                    reason_codes=("blocking_item",),
                )
            )
            continue
        if not numeric:
            results.append(
                ConventionalGradeCategoryResult(
                    category_id=category.category_id,
                    weight=category.weight,
                    status="noncalculable",
                    included_grade_item_ids=(),
                    excluded_grade_item_ids=tuple(
                        item.grade_item.grade_item_id for item in excluded
                    ),
                    earned=None,
                    possible=None,
                    fraction=None,
                    contribution=None,
                    reason_codes=("no_calculable_items",),
                )
            )
            continue
        earned = sum(
            (cast(Decimal, item.earned) for item in numeric),
            Decimal("0"),
        )
        possible = sum(
            (cast(Decimal, item.possible) for item in numeric),
            Decimal("0"),
        )
        fraction = earned / possible
        results.append(
            ConventionalGradeCategoryResult(
                category_id=category.category_id,
                weight=category.weight,
                status="calculated",
                included_grade_item_ids=tuple(
                    item.grade_item.grade_item_id for item in numeric
                ),
                excluded_grade_item_ids=tuple(
                    item.grade_item.grade_item_id for item in excluded
                ),
                earned=earned,
                possible=possible,
                fraction=fraction,
                contribution=fraction * category.weight,
                reason_codes=(),
            )
        )
    return tuple(results)


def _round_final_grade(value: Decimal, policy: GradeRoundingPolicy) -> Decimal:
    if policy.application_stage != "final":  # defensive; Grade-policy v1 forbids it
        raise ConventionalGradeValidationError(
            "conventional Grade v1 supports final-only rounding."
        )
    rounding = _ROUNDING.get(policy.mode)
    if rounding is None:  # defensive; Grade-policy validation forbids it
        raise ConventionalGradeValidationError("unsupported Grade rounding mode.")
    return value.quantize(policy.quantum, rounding=rounding)


def conventional_grade_calculation_input_sha256(
    value: ConventionalGradeCalculationInput,
) -> str:
    """Return SHA-256 over the canonical exact calculation-input bytes."""

    return hashlib.sha256(
        conventional_grade_calculation_input_to_json_bytes(value)
    ).hexdigest()


def conventional_grade_calculation_input_from_dict(
    data: object,
) -> ConventionalGradeCalculationInput:
    """Parse one exact closed conventional calculation-input mapping."""

    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "class_id",
                "student_id",
                "target_period",
                "calendar_revision",
                "activation_reference",
                "policy_reference",
                "configuration",
                "state_treatment",
                "rounding",
                "items",
            }
        ),
        "conventional Grade calculation input",
    )
    items_data = _require_list(mapping["items"], "items")
    return ConventionalGradeCalculationInput(
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(
            mapping["policy_reference"]
        ),
        configuration=_configuration_from_dict(mapping["configuration"]),
        state_treatment=_state_treatment_from_dict(mapping["state_treatment"]),
        rounding=_rounding_from_dict(mapping["rounding"]),
        items=tuple(_item_input_from_dict(item) for item in items_data),
    )


def conventional_grade_calculation_input_from_json_bytes(
    data: bytes,
) -> ConventionalGradeCalculationInput:
    """Parse only canonical conventional calculation-input JSON bytes."""

    decoded = _decode_json(data, "conventional Grade calculation input")
    value = conventional_grade_calculation_input_from_dict(decoded)
    if conventional_grade_calculation_input_to_json_bytes(value) != data:
        raise ConventionalGradeSerializationError(
            "conventional Grade calculation input is not canonical JSON."
        )
    return value


def conventional_grade_calculation_outcome_from_dict(
    data: object,
) -> ConventionalGradeCalculationOutcome:
    """Parse one exact closed conventional calculation outcome."""

    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "status",
                "algorithm_version",
                "calculation_fingerprint",
                "target_period",
                "calendar_revision",
                "activation_reference",
                "policy_reference",
                "mode",
                "student_id",
                "item_results",
                "category_results",
                "total_earned",
                "total_possible",
                "final_fraction",
                "unrounded_grade",
                "rounded_grade",
                "reasons",
            }
        ),
        "conventional Grade calculation outcome",
    )
    return ConventionalGradeCalculationOutcome(
        status=cast(
            ConventionalGradeCalculationStatus,
            _require_str(mapping["status"], "status"),
        ),
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        calculation_fingerprint=_require_str(
            mapping["calculation_fingerprint"],
            "calculation_fingerprint",
        ),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(
            mapping["policy_reference"]
        ),
        mode=_require_str(mapping["mode"], "mode"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        item_results=tuple(
            _item_result_from_dict(item)
            for item in _require_list(mapping["item_results"], "item_results")
        ),
        category_results=tuple(
            _category_result_from_dict(item)
            for item in _require_list(
                mapping["category_results"],
                "category_results",
            )
        ),
        total_earned=_optional_decimal_from_text(
            mapping["total_earned"],
            "total_earned",
        ),
        total_possible=_optional_decimal_from_text(
            mapping["total_possible"],
            "total_possible",
        ),
        final_fraction=_optional_decimal_from_text(
            mapping["final_fraction"],
            "final_fraction",
        ),
        unrounded_grade=_optional_decimal_from_text(
            mapping["unrounded_grade"],
            "unrounded_grade",
        ),
        rounded_grade=_optional_decimal_from_text(
            mapping["rounded_grade"],
            "rounded_grade",
        ),
        reasons=tuple(
            _reason_from_dict(item)
            for item in _require_list(mapping["reasons"], "reasons")
        ),
    )


def conventional_grade_calculation_outcome_from_json_bytes(
    data: bytes,
) -> ConventionalGradeCalculationOutcome:
    """Parse only canonical conventional calculation-outcome JSON bytes."""

    decoded = _decode_json(data, "conventional Grade calculation outcome")
    value = conventional_grade_calculation_outcome_from_dict(decoded)
    if conventional_grade_calculation_outcome_to_json_bytes(value) != data:
        raise ConventionalGradeSerializationError(
            "conventional Grade calculation outcome is not canonical JSON."
        )
    return value


def create_conventional_grade_result_snapshot(
    inputs: ConventionalGradeCalculationInput,
    outcome: ConventionalGradeCalculationOutcome,
    *,
    result_revision: int,
    calculated_at: datetime,
) -> ConventionalGradeResultSnapshot:
    """Wrap one pure calculation in explicit immutable result metadata."""

    if not isinstance(inputs, ConventionalGradeCalculationInput):
        raise ConventionalGradeValidationError(
            "inputs must be ConventionalGradeCalculationInput."
        )
    if not isinstance(outcome, ConventionalGradeCalculationOutcome):
        raise ConventionalGradeValidationError(
            "outcome must be ConventionalGradeCalculationOutcome."
        )
    revision = _positive_int(result_revision, "result_revision")
    return ConventionalGradeResultSnapshot(
        schema_version=CONVENTIONAL_GRADE_RESULT_SCHEMA_VERSION,
        record_type=CONVENTIONAL_GRADE_RESULT_RECORD_TYPE,
        class_id=inputs.class_id,
        student_id=inputs.student_id,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=conventional_grade_calculation_input_sha256(inputs),
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        outcome=outcome,
        calculated_at=calculated_at,
    )


def validate_conventional_grade_result_transition(
    previous: ConventionalGradeResultSnapshot,
    current: ConventionalGradeResultSnapshot,
) -> ConventionalGradeResultSnapshot:
    """Validate contiguous immutable history for one exact result family."""

    if not isinstance(previous, ConventionalGradeResultSnapshot):
        raise ConventionalGradeValidationError(
            "previous must be ConventionalGradeResultSnapshot."
        )
    if not isinstance(current, ConventionalGradeResultSnapshot):
        raise ConventionalGradeValidationError(
            "current must be ConventionalGradeResultSnapshot."
        )
    previous.__post_init__()
    current.__post_init__()
    previous_scope = (
        previous.class_id,
        previous.student_id,
        previous.target_period,
        previous.calendar_revision,
    )
    current_scope = (
        current.class_id,
        current.student_id,
        current.target_period,
        current.calendar_revision,
    )
    if current_scope != previous_scope:
        raise ConventionalGradeValidationError(
            "conventional Grade result logical identity cannot change."
        )
    if current.result_revision != previous.result_revision + 1:
        raise ConventionalGradeValidationError(
            "conventional Grade result revisions must be contiguous."
        )
    if current.supersedes_revision != previous.result_revision:
        raise ConventionalGradeValidationError(
            "result supersedes_revision must identify the prior revision."
        )
    if current.calculated_at < previous.calculated_at:
        raise ConventionalGradeValidationError(
            "result calculated_at must be nondecreasing."
        )
    return current


def conventional_grade_result_snapshot_to_dict(
    value: ConventionalGradeResultSnapshot,
) -> dict[str, object]:
    """Serialize one immutable conventional Grade result snapshot."""

    if not isinstance(value, ConventionalGradeResultSnapshot):
        raise ConventionalGradeValidationError(
            "value must be ConventionalGradeResultSnapshot."
        )
    value.__post_init__()
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "result_revision": value.result_revision,
        "supersedes_revision": value.supersedes_revision,
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "inputs": conventional_grade_calculation_input_to_dict(value.inputs),
        "inputs_sha256": value.inputs_sha256,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "outcome": conventional_grade_calculation_outcome_to_dict(value.outcome),
        "calculated_at": value.calculated_at.isoformat(),
    }


def conventional_grade_result_snapshot_from_dict(
    data: object,
) -> ConventionalGradeResultSnapshot:
    """Parse one exact closed conventional Grade result snapshot."""

    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "schema_version",
                "record_type",
                "class_id",
                "student_id",
                "target_period",
                "calendar_revision",
                "result_revision",
                "supersedes_revision",
                "algorithm_version",
                "calculation_fingerprint",
                "inputs",
                "inputs_sha256",
                "activation_reference",
                "policy_reference",
                "outcome",
                "calculated_at",
            }
        ),
        "conventional Grade result snapshot",
    )
    return ConventionalGradeResultSnapshot(
        schema_version=_require_str(
            mapping["schema_version"],
            "schema_version",
        ),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        result_revision=_require_int(
            mapping["result_revision"],
            "result_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        calculation_fingerprint=_require_str(
            mapping["calculation_fingerprint"],
            "calculation_fingerprint",
        ),
        inputs=conventional_grade_calculation_input_from_dict(mapping["inputs"]),
        inputs_sha256=_require_str(mapping["inputs_sha256"], "inputs_sha256"),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(
            mapping["policy_reference"]
        ),
        outcome=conventional_grade_calculation_outcome_from_dict(
            mapping["outcome"]
        ),
        calculated_at=_datetime_from_text(
            mapping["calculated_at"],
            "calculated_at",
        ),
    )


def conventional_grade_result_snapshot_to_json_bytes(
    value: ConventionalGradeResultSnapshot,
) -> bytes:
    """Return canonical bytes for one immutable conventional Grade result."""

    return _canonical_json_bytes(conventional_grade_result_snapshot_to_dict(value))


def conventional_grade_result_snapshot_from_json_bytes(
    data: bytes,
) -> ConventionalGradeResultSnapshot:
    """Parse only canonical immutable conventional Grade result bytes."""

    decoded = _decode_json(data, "conventional Grade result snapshot")
    value = conventional_grade_result_snapshot_from_dict(decoded)
    if conventional_grade_result_snapshot_to_json_bytes(value) != data:
        raise ConventionalGradeSerializationError(
            "conventional Grade result snapshot is not canonical JSON."
        )
    return value


def conventional_grade_result_reference(
    value: ConventionalGradeResultSnapshot,
) -> ConventionalGradeResultReference:
    """Return an exact digest-bound reference to one result revision."""

    if not isinstance(value, ConventionalGradeResultSnapshot):
        raise ConventionalGradeValidationError(
            "value must be ConventionalGradeResultSnapshot."
        )
    content = conventional_grade_result_snapshot_to_json_bytes(value)
    return ConventionalGradeResultReference(
        class_id=value.class_id,
        student_id=value.student_id,
        school_year=value.target_period.school_year,
        period_id=value.target_period.period_id,
        calendar_revision=value.calendar_revision,
        result_revision=value.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )


def conventional_grade_result_reference_to_dict(
    value: ConventionalGradeResultReference,
) -> dict[str, object]:
    if not isinstance(value, ConventionalGradeResultReference):
        raise ConventionalGradeValidationError(
            "value must be ConventionalGradeResultReference."
        )
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "school_year": value.school_year,
        "period_id": value.period_id,
        "calendar_revision": value.calendar_revision,
        "result_revision": value.result_revision,
        "result_sha256": value.result_sha256,
    }


def conventional_grade_result_reference_from_dict(
    data: object,
) -> ConventionalGradeResultReference:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "class_id",
                "student_id",
                "school_year",
                "period_id",
                "calendar_revision",
                "result_revision",
                "result_sha256",
            }
        ),
        "conventional Grade result reference",
    )
    return ConventionalGradeResultReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        school_year=_require_str(mapping["school_year"], "school_year"),
        period_id=_require_str(mapping["period_id"], "period_id"),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        result_revision=_require_int(
            mapping["result_revision"],
            "result_revision",
        ),
        result_sha256=_require_str(mapping["result_sha256"], "result_sha256"),
    )


def assess_conventional_grade_result_freshness(
    result: ConventionalGradeResultSnapshot,
    current_inputs: ConventionalGradeCalculationInput,
    *,
    algorithm_version: str = CONVENTIONAL_GRADE_ALGORITHM_VERSION,
) -> ConventionalGradeResultFreshness:
    """Compare immutable history to explicit current state without mutation."""

    if not isinstance(result, ConventionalGradeResultSnapshot):
        raise ConventionalGradeValidationError(
            "result must be ConventionalGradeResultSnapshot."
        )
    result.__post_init__()
    if not isinstance(current_inputs, ConventionalGradeCalculationInput):
        raise ConventionalGradeValidationError(
            "current_inputs must be ConventionalGradeCalculationInput."
        )
    if (
        current_inputs.class_id != result.class_id
        or current_inputs.student_id != result.student_id
    ):
        raise ConventionalGradeValidationError(
            "freshness comparison must preserve class/student identity."
        )
    current_algorithm = _bounded_reference_key(algorithm_version)
    reasons: list[ConventionalGradeStalenessReason] = []
    if (
        current_inputs.target_period != result.target_period
        or current_inputs.calendar_revision != result.calendar_revision
    ):
        reasons.append("calendar_scope_changed")
    if current_inputs.activation_reference != result.activation_reference:
        reasons.append("activation_changed")
    if current_inputs.policy_reference != result.policy_reference:
        reasons.append("policy_changed")
    if _material_inputs_sha256(current_inputs) != _material_inputs_sha256(
        result.inputs
    ):
        reasons.append("inputs_changed")
    if current_algorithm != result.algorithm_version:
        reasons.append("algorithm_changed")
    return ConventionalGradeResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def _material_inputs_sha256(value: ConventionalGradeCalculationInput) -> str:
    body = {
        "configuration": _configuration_to_dict(value.configuration),
        "state_treatment": _state_treatment_to_dict(value.state_treatment),
        "rounding": _rounding_to_dict(value.rounding),
        "items": [
            {
                "participation": _participation_to_dict(item.participation),
                "status": item.status,
                "earned": _optional_decimal_text(item.earned),
                "possible": _optional_decimal_text(item.possible),
                "reason_codes": list(item.reason_codes),
                "provenance": [
                    {
                        "kind": ref.kind,
                        "reference_key": ref.reference_key,
                        "reference_sha256": ref.reference_sha256,
                    }
                    for ref in item.provenance
                ],
            }
            for item in value.items
        ],
    }
    return hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def _configuration_to_dict(
    value: ConventionalGradeConfiguration,
) -> dict[str, object]:
    return {
        "mode": value.mode,
        "items": [_participation_to_dict(item) for item in value.items],
        "categories": [
            {
                "category_id": category.category_id,
                "title": category.title,
                "weight": _decimal_text(category.weight),
            }
            for category in value.categories
        ],
    }


def _participation_to_dict(
    value: GradePolicyItemParticipation,
) -> dict[str, object]:
    return {
        "grade_item": _grade_item_reference_to_dict(value.grade_item),
        "category_id": value.category_id,
        "weight": _optional_decimal_text(value.weight),
        "possible_points": _optional_decimal_text(value.possible_points),
    }


def _grade_item_reference_to_dict(
    value: GradePolicyItemReference,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "grade_item_revision_sha256": value.grade_item_revision_sha256,
    }


def _state_treatment_to_dict(value: GradeStateTreatment) -> dict[str, object]:
    return {
        "missing": value.missing,
        "pending": value.pending,
        "incomplete": value.incomplete,
        "excused": value.excused,
        "excluded": value.excluded,
        "not_applicable": value.not_applicable,
        "insufficient_evidence": value.insufficient_evidence,
        "unavailable": value.unavailable,
        "withdrawn": value.withdrawn,
        "invalid": value.invalid,
        "unresolved": value.unresolved,
    }


def _rounding_to_dict(value: GradeRoundingPolicy) -> dict[str, object]:
    return {
        "quantum": _decimal_text(value.quantum),
        "mode": value.mode,
        "application_stage": value.application_stage,
    }


def _item_input_to_dict(value: ConventionalGradeItemInput) -> dict[str, object]:
    return {
        "participation": _participation_to_dict(value.participation),
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "status": value.status,
        "earned": _optional_decimal_text(value.earned),
        "possible": _optional_decimal_text(value.possible),
        "percentage": _optional_decimal_text(value.percentage),
        "reason_codes": list(value.reason_codes),
        "provenance": [
            {
                "kind": reference.kind,
                "reference_key": reference.reference_key,
                "reference_sha256": reference.reference_sha256,
            }
            for reference in value.provenance
        ],
    }


def _item_result_to_dict(value: ConventionalGradeItemResult) -> dict[str, object]:
    return {
        "grade_item": _grade_item_reference_to_dict(value.grade_item),
        "source_state": value.source_state,
        "action": value.action,
        "category_id": value.category_id,
        "weight": _optional_decimal_text(value.weight),
        "policy_possible_points": _optional_decimal_text(value.policy_possible_points),
        "earned": _optional_decimal_text(value.earned),
        "possible": _optional_decimal_text(value.possible),
        "percentage": _optional_decimal_text(value.percentage),
        "contribution": _optional_decimal_text(value.contribution),
        "reason_codes": list(value.reason_codes),
        "provenance": [
            {
                "kind": reference.kind,
                "reference_key": reference.reference_key,
                "reference_sha256": reference.reference_sha256,
            }
            for reference in value.provenance
        ],
    }


def _category_result_to_dict(
    value: ConventionalGradeCategoryResult,
) -> dict[str, object]:
    return {
        "category_id": value.category_id,
        "weight": _decimal_text(value.weight),
        "status": value.status,
        "included_grade_item_ids": list(value.included_grade_item_ids),
        "excluded_grade_item_ids": list(value.excluded_grade_item_ids),
        "earned": _optional_decimal_text(value.earned),
        "possible": _optional_decimal_text(value.possible),
        "fraction": _optional_decimal_text(value.fraction),
        "contribution": _optional_decimal_text(value.contribution),
        "reason_codes": list(value.reason_codes),
    }


def _reason_to_dict(value: ConventionalGradeReason) -> dict[str, object]:
    return {
        "code": value.code,
        "grade_item": (
            _grade_item_reference_to_dict(value.grade_item)
            if value.grade_item is not None
            else None
        ),
        "category_id": value.category_id,
    }


def _configuration_from_dict(data: object) -> ConventionalGradeConfiguration:
    mapping = _exact_mapping(
        data,
        frozenset({"mode", "items", "categories"}),
        "conventional Grade configuration",
    )
    items = tuple(
        _participation_from_dict(item)
        for item in _require_list(mapping["items"], "configuration.items")
    )
    categories = tuple(
        _category_from_dict(item)
        for item in _require_list(
            mapping["categories"],
            "configuration.categories",
        )
    )
    return ConventionalGradeConfiguration(
        mode=cast(
            Literal["total_points", "weighted_items", "weighted_categories"],
            _require_str(mapping["mode"], "configuration.mode"),
        ),
        items=items,
        categories=categories,
    )


def _participation_from_dict(data: object) -> GradePolicyItemParticipation:
    mapping = _exact_mapping(
        data,
        frozenset(
            {"grade_item", "category_id", "weight", "possible_points"}
        ),
        "Grade policy item participation",
    )
    return GradePolicyItemParticipation(
        grade_item=_grade_item_reference_from_dict(mapping["grade_item"]),
        category_id=_optional_str(mapping["category_id"], "category_id"),
        weight=_optional_decimal_from_text(mapping["weight"], "weight"),
        possible_points=_optional_decimal_from_text(
            mapping["possible_points"],
            "possible_points",
        ),
    )


def _grade_item_reference_from_dict(data: object) -> GradePolicyItemReference:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "class_id",
                "grade_item_id",
                "grade_item_revision",
                "grade_item_revision_sha256",
            }
        ),
        "Grade policy item reference",
    )
    return GradePolicyItemReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        grade_item_revision=_require_int(
            mapping["grade_item_revision"],
            "grade_item_revision",
        ),
        grade_item_revision_sha256=_require_str(
            mapping["grade_item_revision_sha256"],
            "grade_item_revision_sha256",
        ),
    )


def _category_from_dict(data: object) -> GradePolicyCategory:
    mapping = _exact_mapping(
        data,
        frozenset({"category_id", "title", "weight"}),
        "Grade policy category",
    )
    return GradePolicyCategory(
        category_id=_require_str(mapping["category_id"], "category_id"),
        title=_require_str(mapping["title"], "title"),
        weight=_decimal_from_text(mapping["weight"], "weight"),
    )


def _state_treatment_from_dict(data: object) -> GradeStateTreatment:
    mapping = _exact_mapping(
        data,
        frozenset(_NON_POINT_STATES),
        "Grade state treatment",
    )
    return GradeStateTreatment(
        missing=cast(
            GradeStateConsequence,
            _require_str(mapping["missing"], "missing"),
        ),
        pending=cast(
            GradeStateConsequence,
            _require_str(mapping["pending"], "pending"),
        ),
        incomplete=cast(
            GradeStateConsequence,
            _require_str(mapping["incomplete"], "incomplete"),
        ),
        excused=cast(
            GradeStateConsequence,
            _require_str(mapping["excused"], "excused"),
        ),
        excluded=cast(
            GradeStateConsequence,
            _require_str(mapping["excluded"], "excluded"),
        ),
        not_applicable=cast(
            GradeStateConsequence,
            _require_str(mapping["not_applicable"], "not_applicable"),
        ),
        insufficient_evidence=cast(
            GradeStateConsequence,
            _require_str(
                mapping["insufficient_evidence"],
                "insufficient_evidence",
            ),
        ),
        unavailable=cast(
            GradeStateConsequence,
            _require_str(mapping["unavailable"], "unavailable"),
        ),
        withdrawn=cast(
            GradeStateConsequence,
            _require_str(mapping["withdrawn"], "withdrawn"),
        ),
        invalid=cast(
            GradeStateConsequence,
            _require_str(mapping["invalid"], "invalid"),
        ),
        unresolved=cast(
            GradeStateConsequence,
            _require_str(mapping["unresolved"], "unresolved"),
        ),
    )


def _rounding_from_dict(data: object) -> GradeRoundingPolicy:
    mapping = _exact_mapping(
        data,
        frozenset({"quantum", "mode", "application_stage"}),
        "Grade rounding policy",
    )
    return GradeRoundingPolicy(
        quantum=_decimal_from_text(mapping["quantum"], "quantum"),
        mode=cast(
            Literal[
                "half_even",
                "half_up",
                "half_down",
                "up",
                "down",
                "ceiling",
                "floor",
            ],
            _require_str(mapping["mode"], "rounding.mode"),
        ),
        application_stage=cast(
            Literal["final"],
            _require_str(
                mapping["application_stage"],
                "application_stage",
            ),
        ),
    )


def _item_input_from_dict(data: object) -> ConventionalGradeItemInput:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "participation",
                "student_id",
                "target_period",
                "calendar_revision",
                "status",
                "earned",
                "possible",
                "percentage",
                "reason_codes",
                "provenance",
            }
        ),
        "conventional Grade item input",
    )
    value = ConventionalGradeItemInput(
        participation=_participation_from_dict(mapping["participation"]),
        student_id=_require_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        status=cast(
            ConventionalGradeItemState,
            _require_str(mapping["status"], "status"),
        ),
        earned=_optional_decimal_from_text(mapping["earned"], "earned"),
        possible=_optional_decimal_from_text(
            mapping["possible"],
            "possible",
        ),
        reason_codes=_string_tuple(mapping["reason_codes"], "reason_codes"),
        provenance=_provenance_from_data(mapping["provenance"]),
    )
    encoded_percentage = _optional_decimal_from_text(
        mapping["percentage"],
        "percentage",
    )
    if encoded_percentage != value.percentage:
        raise ConventionalGradeValidationError(
            "serialized item percentage does not match exact earned/possible."
        )
    return value


def _item_result_from_dict(data: object) -> ConventionalGradeItemResult:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "grade_item",
                "source_state",
                "action",
                "category_id",
                "weight",
                "policy_possible_points",
                "earned",
                "possible",
                "percentage",
                "contribution",
                "reason_codes",
                "provenance",
            }
        ),
        "conventional Grade item result",
    )
    return ConventionalGradeItemResult(
        grade_item=_grade_item_reference_from_dict(mapping["grade_item"]),
        source_state=cast(
            ConventionalGradeItemState,
            _require_str(mapping["source_state"], "source_state"),
        ),
        action=cast(
            ConventionalGradeItemAction,
            _require_str(mapping["action"], "action"),
        ),
        category_id=_optional_str(mapping["category_id"], "category_id"),
        weight=_optional_decimal_from_text(mapping["weight"], "weight"),
        policy_possible_points=_optional_decimal_from_text(
            mapping["policy_possible_points"],
            "policy_possible_points",
        ),
        earned=_optional_decimal_from_text(mapping["earned"], "earned"),
        possible=_optional_decimal_from_text(
            mapping["possible"],
            "possible",
        ),
        percentage=_optional_decimal_from_text(
            mapping["percentage"],
            "percentage",
        ),
        contribution=_optional_decimal_from_text(
            mapping["contribution"],
            "contribution",
        ),
        reason_codes=_string_tuple(mapping["reason_codes"], "reason_codes"),
        provenance=_provenance_from_data(mapping["provenance"]),
    )


def _category_result_from_dict(
    data: object,
) -> ConventionalGradeCategoryResult:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "category_id",
                "weight",
                "status",
                "included_grade_item_ids",
                "excluded_grade_item_ids",
                "earned",
                "possible",
                "fraction",
                "contribution",
                "reason_codes",
            }
        ),
        "conventional Grade category result",
    )
    return ConventionalGradeCategoryResult(
        category_id=_require_str(mapping["category_id"], "category_id"),
        weight=_decimal_from_text(mapping["weight"], "weight"),
        status=cast(
            ConventionalGradeCategoryStatus,
            _require_str(mapping["status"], "status"),
        ),
        included_grade_item_ids=_string_tuple(
            mapping["included_grade_item_ids"],
            "included_grade_item_ids",
        ),
        excluded_grade_item_ids=_string_tuple(
            mapping["excluded_grade_item_ids"],
            "excluded_grade_item_ids",
        ),
        earned=_optional_decimal_from_text(mapping["earned"], "earned"),
        possible=_optional_decimal_from_text(
            mapping["possible"],
            "possible",
        ),
        fraction=_optional_decimal_from_text(
            mapping["fraction"],
            "fraction",
        ),
        contribution=_optional_decimal_from_text(
            mapping["contribution"],
            "contribution",
        ),
        reason_codes=_string_tuple(mapping["reason_codes"], "reason_codes"),
    )


def _reason_from_dict(data: object) -> ConventionalGradeReason:
    mapping = _exact_mapping(
        data,
        frozenset({"code", "grade_item", "category_id"}),
        "conventional Grade reason",
    )
    grade_item_data = mapping["grade_item"]
    return ConventionalGradeReason(
        code=_require_str(mapping["code"], "code"),
        grade_item=(
            None
            if grade_item_data is None
            else _grade_item_reference_from_dict(grade_item_data)
        ),
        category_id=_optional_str(mapping["category_id"], "category_id"),
    )


def _provenance_from_data(
    data: object,
) -> tuple[ConventionalGradeProvenanceReference, ...]:
    return tuple(
        _provenance_reference_from_dict(item)
        for item in _require_list(data, "provenance")
    )


def _provenance_reference_from_dict(
    data: object,
) -> ConventionalGradeProvenanceReference:
    mapping = _exact_mapping(
        data,
        frozenset({"kind", "reference_key", "reference_sha256"}),
        "conventional Grade provenance reference",
    )
    return ConventionalGradeProvenanceReference(
        kind=cast(
            ConventionalGradeProvenanceKind,
            _require_str(mapping["kind"], "kind"),
        ),
        reference_key=_require_str(
            mapping["reference_key"],
            "reference_key",
        ),
        reference_sha256=_require_str(
            mapping["reference_sha256"],
            "reference_sha256",
        ),
    )


def _period_from_dict(data: object) -> AcademicPeriodRef:
    try:
        return academic_period_ref_from_dict(data)
    except ValueError as error:
        raise ConventionalGradeValidationError(str(error)) from error


def _activation_reference_from_dict(
    data: object,
) -> GradePolicyActivationReference:
    try:
        return grade_policy_activation_reference_from_dict(data)
    except ValueError as error:
        raise ConventionalGradeValidationError(str(error)) from error


def _policy_reference_from_dict(data: object) -> GradePolicyReference:
    try:
        return grade_policy_reference_from_dict(data)
    except ValueError as error:
        raise ConventionalGradeValidationError(str(error)) from error


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ConventionalGradeSerializationError(
            f"{label} data must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConventionalGradeSerializationError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ConventionalGradeSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ConventionalGradeSerializationError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ConventionalGradeSerializationError(
                f"duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ConventionalGradeSerializationError(
        f"nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise ConventionalGradeValidationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in data):
        raise ConventionalGradeValidationError(
            f"{label} keys must be strings."
        )
    mapping = cast(Mapping[str, object], data)
    actual = frozenset(mapping.keys())
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ConventionalGradeValidationError(
            f"{label} must use exact keys ({'; '.join(details)})."
        )
    return mapping


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ConventionalGradeValidationError(
            f"{field_name} must be a list."
        )
    return value


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConventionalGradeValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConventionalGradeValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _decimal_from_text(value: object, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise ConventionalGradeValidationError(
            f"{field_name} must be canonical decimal text."
        )
    try:
        decimal = Decimal(value)
    except Exception as error:
        raise ConventionalGradeValidationError(
            f"{field_name} is not valid decimal text."
        ) from error
    if not decimal.is_finite() or _decimal_text(decimal) != value:
        raise ConventionalGradeValidationError(
            f"{field_name} must use canonical finite decimal text."
        )
    return decimal


def _optional_decimal_from_text(
    value: object,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None
    return _decimal_from_text(value, field_name)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_str(item, field_name)
        for item in _require_list(value, field_name)
    )


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ConventionalGradeValidationError(
            f"{field_name} must be an ISO-8601 datetime."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConventionalGradeValidationError(
            f"{field_name} must be timezone-aware datetime."
        )
    normalized = value.astimezone(UTC)
    if normalized != value:
        raise ConventionalGradeValidationError(
            f"{field_name} must be normalized to UTC."
        )
    return normalized


def _staleness_reasons(
    values: Iterable[ConventionalGradeStalenessReason],
) -> tuple[ConventionalGradeStalenessReason, ...]:
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise ConventionalGradeValidationError(
            "freshness reasons must be iterable."
        ) from error
    if any(reason not in _STALENESS_REASON_SET for reason in reasons):
        raise ConventionalGradeValidationError(
            "freshness reasons contain an unsupported value."
        )
    if len(set(reasons)) != len(reasons):
        raise ConventionalGradeValidationError(
            "freshness reasons must not contain duplicates."
        )
    expected = tuple(
        reason for reason in _STALENESS_REASON_ORDER if reason in reasons
    )
    if reasons != expected:
        raise ConventionalGradeValidationError(
            "freshness reasons are not in deterministic order."
        )
    return reasons


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
        raise ConventionalGradeSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _native_number_to_decimal(value: int | float) -> Decimal:
    if type(value) is int:
        return Decimal(value)
    if type(value) is float and math.isfinite(value):
        return Decimal(str(value))
    raise ConventionalGradeValidationError(
        "native point value must be an integer or finite float."
    )


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ConventionalGradeValidationError(
            f"{field_name} must be a Decimal."
        )
    if not value.is_finite():
        raise ConventionalGradeValidationError(
            f"{field_name} must be finite."
        )
    return value


def _positive_decimal(value: object, field_name: str) -> Decimal:
    decimal = _finite_decimal(value, field_name)
    if decimal <= 0:
        raise ConventionalGradeValidationError(
            f"{field_name} must be greater than zero."
        )
    return decimal


def _decimal_text(value: Decimal) -> str:
    _finite_decimal(value, "decimal")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        return "0"
    return text


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConventionalGradeValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ConventionalGradeValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConventionalGradeValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _academic_period_ref(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise ConventionalGradeValidationError(
            "target_period must be an AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise ConventionalGradeValidationError(
            f"target_period is invalid: {error}"
        ) from error


def _bounded_reference_key(value: object) -> str:
    if not isinstance(value, str):
        raise ConventionalGradeValidationError("reference_key must be a string.")
    if not value or value != value.strip():
        raise ConventionalGradeValidationError(
            "reference_key must be nonblank without surrounding whitespace."
        )
    if len(value) > MAXIMUM_CONVENTIONAL_GRADE_PROVENANCE_KEY_LENGTH:
        raise ConventionalGradeValidationError("reference_key is too long.")
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ConventionalGradeValidationError(
            "reference_key must be single-line and control-free."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ConventionalGradeValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise ConventionalGradeValidationError(
            "reason code must be a lowercase underscore identifier."
        )
    return value


def _reason_codes(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ConventionalGradeValidationError(
            "reason_codes must be an iterable."
        )
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ConventionalGradeValidationError(
            "reason_codes must be an iterable."
        ) from error
    validated = tuple(_reason_code(item) for item in items)
    return tuple(sorted(set(validated)))


def _provenance(value: object) -> tuple[ConventionalGradeProvenanceReference, ...]:
    if isinstance(value, (str, bytes)):
        raise ConventionalGradeValidationError(
            "provenance must be an iterable."
        )
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ConventionalGradeValidationError(
            "provenance must be an iterable."
        ) from error
    if any(
        not isinstance(item, ConventionalGradeProvenanceReference)
        for item in items
    ):
        raise ConventionalGradeValidationError(
            "provenance contains an invalid reference."
        )
    typed = cast(tuple[ConventionalGradeProvenanceReference, ...], items)
    keys = tuple(
        (item.kind, item.reference_key, item.reference_sha256) for item in typed
    )
    if len(set(keys)) != len(keys):
        raise ConventionalGradeValidationError(
            "provenance must not contain duplicate exact references."
        )
    return tuple(
        sorted(
            typed,
            key=lambda item: (
                item.kind,
                item.reference_key,
                item.reference_sha256,
            ),
        )
    )


def _identifier_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ConventionalGradeValidationError(
            f"{field_name} must be an iterable."
        )
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ConventionalGradeValidationError(
            f"{field_name} must be an iterable."
        ) from error
    validated = tuple(_identifier(item, field_name) for item in items)
    if len(set(validated)) != len(validated):
        raise ConventionalGradeValidationError(
            f"{field_name} must not contain duplicates."
        )
    return tuple(sorted(validated))


def _participation_key(
    value: GradePolicyItemParticipation,
) -> tuple[str, str]:
    return value.grade_item.class_id, value.grade_item.grade_item_id


def _typed_tuple(
    value: object,
    expected: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if isinstance(value, (str, bytes)):
        raise ConventionalGradeValidationError(
            f"{field_name} must be an iterable."
        )
    try:
        items = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise ConventionalGradeValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(item, expected) for item in items):
        raise ConventionalGradeValidationError(
            f"{field_name} contains an invalid value."
        )
    return cast(tuple[_T, ...], items)
