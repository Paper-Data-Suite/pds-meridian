"""Pure standards-based Grade calculation for Meridian v0.3.

The module consumes already-calculated, explicitly selected Academic Period
proficiency results. It does not discover producer evidence, recalculate
proficiency, select Grade policies or activations, apply overrides, create
ReportingSnapshots, or write an official Grade.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    localcontext,
)
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GradePolicyReference,
    GradePolicyRevision,
    GradeRoundingPolicy,
    GradeStateConsequence,
    GradeStateTreatment,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
    grade_policy_reference_to_dict,
    validate_grade_policy_revision,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
    grade_policy_activation_reference,
    grade_policy_activation_reference_to_dict,
    validate_grade_policy_activation_decision,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_evidence import normalize_standard_id

STANDARDS_GRADE_ALGORITHM_VERSION: Final[str] = "1"

StandardsGradeSourceState: TypeAlias = Literal[
    "calculated",
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
StandardsGradeAction: TypeAlias = Literal[
    "contribute",
    "exclude",
    "blocking",
    "zero",
]
StandardsGradeCalculationStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "insufficient",
]
StandardsGradeUpstreamFreshnessStatus: TypeAlias = Literal["current", "stale"]

_NON_CALCULATED_STATES: Final[tuple[str, ...]] = (
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
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROUNDING = {
    "half_even": ROUND_HALF_EVEN,
    "half_up": ROUND_HALF_UP,
    "half_down": ROUND_HALF_DOWN,
    "up": ROUND_UP,
    "down": ROUND_DOWN,
    "ceiling": ROUND_CEILING,
    "floor": ROUND_FLOOR,
}


class StandardsGradeError(ValueError):
    """Base error for pure standards-based Grade calculation contracts."""


class StandardsGradeValidationError(StandardsGradeError):
    """Raised when the exact standards Grade basis violates the contract."""


@dataclass(frozen=True, slots=True)
class StandardsGradeStandardInput:
    """Exact selected proficiency basis for one policy-participating standard."""

    participation: StandardGradeParticipation
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    status: StandardsGradeSourceState
    result_reference: AcademicPeriodProficiencyResultReference | None
    result_calculation_fingerprint: str | None
    result_algorithm_version: str | None
    proficiency_level_id: str | None
    target_scale: ProficiencyScaleReference | None
    freshness_status: StandardsGradeUpstreamFreshnessStatus | None
    freshness_reasons: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.participation, StandardGradeParticipation):
            raise StandardsGradeValidationError(
                "participation must be StandardGradeParticipation."
            )
        student_id = _identifier(self.student_id, "student_id")
        period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if self.status != "calculated" and self.status not in _NON_CALCULATED_STATES:
            raise StandardsGradeValidationError(
                "status is not a supported standards Grade source state."
            )

        reference = self.result_reference
        fingerprint = self.result_calculation_fingerprint
        algorithm_version = self.result_algorithm_version
        target_scale = self.target_scale
        freshness_status = self.freshness_status
        freshness_reasons = _reason_codes(self.freshness_reasons)
        reason_codes = _reason_codes(self.reason_codes)
        level_id = self.proficiency_level_id

        if reference is None:
            if any(
                value is not None
                for value in (
                    fingerprint,
                    algorithm_version,
                    target_scale,
                    freshness_status,
                    level_id,
                )
            ) or freshness_reasons:
                raise StandardsGradeValidationError(
                    "missing result_reference must not carry selected-result metadata."
                )
            if self.status == "calculated":
                raise StandardsGradeValidationError(
                    "calculated source requires an exact selected result reference."
                )
        else:
            if not isinstance(reference, AcademicPeriodProficiencyResultReference):
                raise StandardsGradeValidationError(
                    "result_reference must be AcademicPeriodProficiencyResultReference."
                )
            if reference.student_id != student_id:
                raise StandardsGradeValidationError(
                    "result_reference student_id must match input student_id."
                )
            if (
                reference.school_year != period.school_year
                or reference.period_id != period.period_id
            ):
                raise StandardsGradeValidationError(
                    "result_reference period must match input target_period."
                )
            if reference.standard_id != self.participation.standard_id:
                raise StandardsGradeValidationError(
                    "result_reference standard_id must match participation."
                )
            fingerprint = _sha256(
                fingerprint,
                "result_calculation_fingerprint",
            )
            algorithm_version = _bounded_text(
                algorithm_version,
                "result_algorithm_version",
                256,
            )
            if not isinstance(target_scale, ProficiencyScaleReference):
                raise StandardsGradeValidationError(
                    "selected result metadata requires exact target_scale."
                )
            if freshness_status not in {"current", "stale"}:
                raise StandardsGradeValidationError(
                    "selected result metadata requires current or stale freshness."
                )
            if freshness_status == "current" and freshness_reasons:
                raise StandardsGradeValidationError(
                    "current selected result must not carry freshness reasons."
                )
            if freshness_status == "stale" and not freshness_reasons:
                raise StandardsGradeValidationError(
                    "stale selected result requires at least one freshness reason."
                )
            if self.status == "calculated":
                level_id = _identifier(level_id, "proficiency_level_id")
            elif level_id is not None:
                raise StandardsGradeValidationError(
                    "non-calculated source must not carry a proficiency level."
                )

        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "result_calculation_fingerprint", fingerprint)
        object.__setattr__(self, "result_algorithm_version", algorithm_version)
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "freshness_reasons", freshness_reasons)
        object.__setattr__(self, "reason_codes", reason_codes)


@dataclass(frozen=True, slots=True)
class StandardsGradeCalculationInput:
    """Complete immutable pure basis for one standards-based Academic Period Grade."""

    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    configuration: StandardsBasedGradeConfiguration
    state_treatment: GradeStateTreatment
    rounding: GradeRoundingPolicy
    standards: tuple[StandardsGradeStandardInput, ...]

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        target_period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise StandardsGradeValidationError(
                "activation_reference must be GradePolicyActivationReference."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise StandardsGradeValidationError(
                "policy_reference must be GradePolicyReference."
            )
        if not isinstance(self.configuration, StandardsBasedGradeConfiguration):
            raise StandardsGradeValidationError(
                "configuration must be StandardsBasedGradeConfiguration."
            )
        if not isinstance(self.state_treatment, GradeStateTreatment):
            raise StandardsGradeValidationError(
                "state_treatment must be GradeStateTreatment."
            )
        if not isinstance(self.rounding, GradeRoundingPolicy):
            raise StandardsGradeValidationError(
                "rounding must be GradeRoundingPolicy."
            )
        if self.activation_reference.class_id != class_id:
            raise StandardsGradeValidationError(
                "activation_reference class_id must match calculation class_id."
            )
        if (
            self.activation_reference.school_year != target_period.school_year
            or self.activation_reference.period_id != target_period.period_id
        ):
            raise StandardsGradeValidationError(
                "activation_reference must match the exact target period."
            )
        if self.policy_reference.class_id != class_id:
            raise StandardsGradeValidationError(
                "policy_reference.class_id must match calculation class_id."
            )
        if self.configuration.target_scale.class_id != class_id:
            raise StandardsGradeValidationError(
                "target proficiency scale must belong to calculation class."
            )

        try:
            standards = tuple(self.standards)
        except TypeError as error:
            raise StandardsGradeValidationError(
                "standards must be an iterable of StandardsGradeStandardInput values."
            ) from error
        if any(not isinstance(item, StandardsGradeStandardInput) for item in standards):
            raise StandardsGradeValidationError(
                "standards must contain only StandardsGradeStandardInput values."
            )

        by_id: dict[str, StandardsGradeStandardInput] = {}
        for item in standards:
            standard_id = item.participation.standard_id
            if standard_id in by_id:
                raise StandardsGradeValidationError(
                    "calculation input contains duplicate standard IDs."
                )
            if item.student_id != student_id:
                raise StandardsGradeValidationError(
                    "standard input student_id must match calculation student_id."
                )
            if item.target_period != target_period:
                raise StandardsGradeValidationError(
                    "standard input target_period must match calculation target_period."
                )
            if item.calendar_revision != calendar_revision:
                raise StandardsGradeValidationError(
                    "standard input calendar_revision must match calculation scope."
                )
            reference = item.result_reference
            if reference is not None and reference.class_id != class_id:
                raise StandardsGradeValidationError(
                    "selected proficiency result must belong to calculation class."
                )
            by_id[standard_id] = item

        configured = {
            participation.standard_id: participation
            for participation in self.configuration.standards
        }
        if set(by_id) != set(configured):
            raise StandardsGradeValidationError(
                "calculation standards must exactly match policy participation."
            )
        for standard_id, expected in configured.items():
            if by_id[standard_id].participation != expected:
                raise StandardsGradeValidationError(
                    "standard participation must exactly match policy authority."
                )

        canonical = tuple(
            sorted(standards, key=lambda item: item.participation.standard_id)
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "standards", canonical)


@dataclass(frozen=True, slots=True)
class StandardsGradeReason:
    """One deterministic structured calculation reason."""

    code: str
    standard_id: str | None = None
    required_results: int | None = None
    actual_results: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _reason_code(self.code))
        if self.standard_id is not None:
            object.__setattr__(
                self,
                "standard_id",
                _standard_id(self.standard_id),
            )
        if self.required_results is not None:
            object.__setattr__(
                self,
                "required_results",
                _positive_int(self.required_results, "required_results"),
            )
        if self.actual_results is not None:
            object.__setattr__(
                self,
                "actual_results",
                _nonnegative_int(self.actual_results, "actual_results"),
            )


@dataclass(frozen=True, slots=True)
class StandardsGradeStandardResult:
    """Exact per-standard conversion and policy consequence."""

    standard_id: str
    weight: Decimal
    source_state: StandardsGradeSourceState
    action: StandardsGradeAction
    result_reference: AcademicPeriodProficiencyResultReference | None
    result_calculation_fingerprint: str | None
    result_algorithm_version: str | None
    target_scale: ProficiencyScaleReference | None
    proficiency_level_id: str | None
    converted_grade_value: Decimal | None
    calculation_value: Decimal | None
    weighted_contribution: Decimal | None
    freshness_status: StandardsGradeUpstreamFreshnessStatus | None
    freshness_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "standard_id", _standard_id(self.standard_id))
        object.__setattr__(self, "weight", _positive_decimal(self.weight, "weight"))
        if (
            self.source_state != "calculated"
            and self.source_state not in _NON_CALCULATED_STATES
        ):
            raise StandardsGradeValidationError("invalid source_state.")
        if self.action not in {"contribute", "exclude", "blocking", "zero"}:
            raise StandardsGradeValidationError("invalid standards Grade action.")
        if self.result_reference is not None and not isinstance(
            self.result_reference,
            AcademicPeriodProficiencyResultReference,
        ):
            raise StandardsGradeValidationError(
                "result_reference must be AcademicPeriodProficiencyResultReference."
            )
        if self.result_calculation_fingerprint is not None:
            object.__setattr__(
                self,
                "result_calculation_fingerprint",
                _sha256(
                    self.result_calculation_fingerprint,
                    "result_calculation_fingerprint",
                ),
            )
        if self.result_algorithm_version is not None:
            object.__setattr__(
                self,
                "result_algorithm_version",
                _bounded_text(
                    self.result_algorithm_version,
                    "result_algorithm_version",
                    256,
                ),
            )
        if self.target_scale is not None and not isinstance(
            self.target_scale,
            ProficiencyScaleReference,
        ):
            raise StandardsGradeValidationError(
                "target_scale must be ProficiencyScaleReference or None."
            )
        if self.result_reference is None:
            if any(
                value is not None
                for value in (
                    self.result_calculation_fingerprint,
                    self.result_algorithm_version,
                    self.target_scale,
                    self.freshness_status,
                )
            ):
                raise StandardsGradeValidationError(
                    "absent result_reference must not carry selected-result metadata."
                )
        elif any(
            value is None
            for value in (
                self.result_calculation_fingerprint,
                self.result_algorithm_version,
                self.target_scale,
                self.freshness_status,
            )
        ):
            raise StandardsGradeValidationError(
                "selected result provenance must be complete."
            )
        if self.proficiency_level_id is not None:
            object.__setattr__(
                self,
                "proficiency_level_id",
                _identifier(self.proficiency_level_id, "proficiency_level_id"),
            )
        for field_name in (
            "converted_grade_value",
            "calculation_value",
            "weighted_contribution",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _finite_decimal(value, field_name)
        if self.freshness_status not in {None, "current", "stale"}:
            raise StandardsGradeValidationError("invalid freshness_status.")
        freshness_reasons = _reason_codes(self.freshness_reasons)
        if self.freshness_status == "current" and freshness_reasons:
            raise StandardsGradeValidationError(
                "current result must not carry freshness reasons."
            )
        if self.freshness_status == "stale" and not freshness_reasons:
            raise StandardsGradeValidationError(
                "stale result requires freshness reasons."
            )
        if self.freshness_status is None and freshness_reasons:
            raise StandardsGradeValidationError(
                "absent freshness status must not carry freshness reasons."
            )
        if self.source_state == "calculated":
            if (
                self.action != "contribute"
                or self.result_reference is None
                or self.result_calculation_fingerprint is None
                or self.result_algorithm_version is None
                or self.target_scale is None
                or self.proficiency_level_id is None
                or self.converted_grade_value is None
                or self.calculation_value is None
                or self.weighted_contribution is None
                or self.freshness_status != "current"
            ):
                raise StandardsGradeValidationError(
                    "calculated standard result requires one current numeric "
                    "contribution."
                )
        elif self.action == "zero":
            if (
                self.converted_grade_value is not None
                or self.calculation_value != Decimal("0")
                or self.weighted_contribution != Decimal("0")
            ):
                raise StandardsGradeValidationError(
                    "zero action requires an explicit numeric zero consequence."
                )
        elif any(
            value is not None
            for value in (
                self.converted_grade_value,
                self.calculation_value,
                self.weighted_contribution,
            )
        ):
            raise StandardsGradeValidationError(
                "nonnumeric action must not carry numeric Grade values."
            )
        object.__setattr__(self, "freshness_reasons", freshness_reasons)
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))


@dataclass(frozen=True, slots=True)
class StandardsGradeCalculationOutcome:
    """Pure advisory standards-based Grade calculation; never an official Grade."""

    status: StandardsGradeCalculationStatus
    algorithm_version: str
    calculation_fingerprint: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    target_scale: ProficiencyScaleReference
    aggregation_strategy: str
    student_id: str
    actual_calculated_result_count: int
    minimum_calculated_results: int
    active_weight: Decimal | None
    weighted_numerator: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None
    standard_results: tuple[StandardsGradeStandardResult, ...]
    reasons: tuple[StandardsGradeReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise StandardsGradeValidationError("invalid calculation status.")
        if self.algorithm_version != STANDARDS_GRADE_ALGORITHM_VERSION:
            raise StandardsGradeValidationError(
                "unsupported standards Grade algorithm_version."
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
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise StandardsGradeValidationError("invalid activation_reference.")
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise StandardsGradeValidationError("invalid policy_reference.")
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardsGradeValidationError("invalid target_scale.")
        if self.aggregation_strategy != "weighted_mean":
            raise StandardsGradeValidationError(
                "standards Grade aggregation_strategy must be weighted_mean."
            )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(
            self,
            "actual_calculated_result_count",
            _nonnegative_int(
                self.actual_calculated_result_count,
                "actual_calculated_result_count",
            ),
        )
        object.__setattr__(
            self,
            "minimum_calculated_results",
            _positive_int(
                self.minimum_calculated_results,
                "minimum_calculated_results",
            ),
        )
        for field_name in (
            "active_weight",
            "weighted_numerator",
            "unrounded_grade",
            "rounded_grade",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _finite_decimal(value, field_name)
        if self.active_weight is not None and self.active_weight <= 0:
            raise StandardsGradeValidationError(
                "active_weight must be positive when present."
            )
        if any(
            not isinstance(item, StandardsGradeStandardResult)
            for item in self.standard_results
        ):
            raise StandardsGradeValidationError(
                "standard_results contains an invalid entry."
            )
        if any(not isinstance(reason, StandardsGradeReason) for reason in self.reasons):
            raise StandardsGradeValidationError("reasons contains an invalid entry.")
        if self.status == "calculated":
            if any(
                value is None
                for value in (
                    self.active_weight,
                    self.weighted_numerator,
                    self.unrounded_grade,
                    self.rounded_grade,
                )
            ):
                raise StandardsGradeValidationError(
                    "calculated outcome requires complete numeric values."
                )
        elif self.unrounded_grade is not None or self.rounded_grade is not None:
            raise StandardsGradeValidationError(
                "non-calculated outcome must not carry a final Grade."
            )


def create_standards_grade_calculation_input(
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    standards: tuple[StandardsGradeStandardInput, ...],
) -> StandardsGradeCalculationInput:
    """Bind exact activated standards Grade policy authority to resolved inputs."""

    try:
        validated_policy = validate_grade_policy_revision(policy)
    except ValueError as error:
        raise StandardsGradeValidationError(str(error)) from error
    try:
        validated_activation = validate_grade_policy_activation_decision(activation)
    except ValueError as error:
        raise StandardsGradeValidationError(str(error)) from error
    if validated_policy.calculation_family != "standards_based" or not isinstance(
        validated_policy.configuration,
        StandardsBasedGradeConfiguration,
    ):
        raise StandardsGradeValidationError(
            "standards Grade calculation requires an exact standards_based policy."
        )
    if validated_activation.decision != "activate":
        raise StandardsGradeValidationError(
            "standards Grade calculation requires an activated policy decision."
        )
    exact_policy_reference = grade_policy_reference(validated_policy)
    if validated_activation.policy_reference != exact_policy_reference:
        raise StandardsGradeValidationError(
            "activation must reference the exact supplied Grade-policy revision."
        )
    exact_period = _academic_period_ref(target_period)
    if (
        validated_activation.class_id != validated_policy.class_id
        or validated_activation.target_period != exact_period
        or validated_activation.calendar_revision != calendar_revision
    ):
        raise StandardsGradeValidationError(
            "activation must match the exact calculation class/period/calendar "
            "revision."
        )
    return StandardsGradeCalculationInput(
        class_id=validated_policy.class_id,
        student_id=student_id,
        target_period=exact_period,
        calendar_revision=calendar_revision,
        activation_reference=grade_policy_activation_reference(validated_activation),
        policy_reference=exact_policy_reference,
        configuration=validated_policy.configuration,
        state_treatment=validated_policy.state_treatment,
        rounding=validated_policy.rounding,
        standards=standards,
    )


def standards_grade_calculation_input_to_dict(
    value: StandardsGradeCalculationInput,
) -> dict[str, object]:
    """Serialize the exact pure calculation basis to deterministic JSON-native data."""

    if not isinstance(value, StandardsGradeCalculationInput):
        raise StandardsGradeValidationError(
            "value must be StandardsGradeCalculationInput."
        )
    return _calculation_input_to_dict(value)


def standards_grade_calculation_input_to_json_bytes(
    value: StandardsGradeCalculationInput,
) -> bytes:
    """Return canonical bytes for one exact standards Grade calculation basis."""

    return _canonical_json_bytes(standards_grade_calculation_input_to_dict(value))


def standards_grade_calculation_input_sha256(
    value: StandardsGradeCalculationInput,
) -> str:
    """Return the canonical SHA-256 digest of one exact calculation basis."""

    return hashlib.sha256(
        standards_grade_calculation_input_to_json_bytes(value)
    ).hexdigest()


def standards_grade_calculation_fingerprint(
    inputs: StandardsGradeCalculationInput,
) -> str:
    """Return a stable digest over the exact standards Grade calculation basis."""

    if not isinstance(inputs, StandardsGradeCalculationInput):
        raise StandardsGradeValidationError(
            "inputs must be StandardsGradeCalculationInput."
        )
    payload = {
        "algorithm_version": STANDARDS_GRADE_ALGORITHM_VERSION,
        "basis": standards_grade_calculation_input_to_dict(inputs),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def calculate_standards_grade(
    inputs: StandardsGradeCalculationInput,
) -> StandardsGradeCalculationOutcome:
    """Purely calculate one standards-based Academic Period Grade."""

    if not isinstance(inputs, StandardsGradeCalculationInput):
        raise StandardsGradeValidationError(
            "inputs must be StandardsGradeCalculationInput."
        )
    fingerprint = standards_grade_calculation_fingerprint(inputs)
    conversion = {
        item.proficiency_level_id: item.grade_value
        for item in inputs.configuration.conversions
    }
    standard_results = tuple(
        _resolve_standard_result(
            item,
            inputs.configuration.target_scale,
            conversion,
            inputs.state_treatment,
        )
        for item in inputs.standards
    )
    actual_calculated = sum(
        1
        for result in standard_results
        if result.source_state == "calculated" and result.action == "contribute"
    )
    blocking = tuple(
        StandardsGradeReason("blocking_standard", result.standard_id)
        for result in standard_results
        if result.action == "blocking"
    )

    if blocking:
        return _outcome(
            inputs,
            fingerprint,
            standard_results,
            actual_calculated,
            status="blocked",
            active_weight=None,
            weighted_numerator=None,
            unrounded_grade=None,
            rounded_grade=None,
            reasons=blocking,
        )

    if actual_calculated < inputs.configuration.minimum_calculated_results:
        reason = StandardsGradeReason(
            "below_minimum_calculated_results",
            required_results=inputs.configuration.minimum_calculated_results,
            actual_results=actual_calculated,
        )
        return _outcome(
            inputs,
            fingerprint,
            standard_results,
            actual_calculated,
            status="insufficient",
            active_weight=None,
            weighted_numerator=None,
            unrounded_grade=None,
            rounded_grade=None,
            reasons=(reason,),
        )

    active = tuple(
        result
        for result in standard_results
        if result.action in {"contribute", "zero"}
    )
    if not active:
        return _outcome(
            inputs,
            fingerprint,
            standard_results,
            actual_calculated,
            status="insufficient",
            active_weight=None,
            weighted_numerator=None,
            unrounded_grade=None,
            rounded_grade=None,
            reasons=(StandardsGradeReason("no_calculable_standards"),),
        )

    with localcontext() as context:
        context.prec = _calculation_precision(inputs)
        active_weight = sum(
            (result.weight for result in active),
            Decimal("0"),
        )
        weighted_numerator = sum(
            (
                result.weighted_contribution
                for result in active
                if result.weighted_contribution is not None
            ),
            Decimal("0"),
        )
        unrounded_grade = weighted_numerator / active_weight
        rounded_grade = _round_final_grade(unrounded_grade, inputs.rounding)

    return _outcome(
        inputs,
        fingerprint,
        standard_results,
        actual_calculated,
        status="calculated",
        active_weight=active_weight,
        weighted_numerator=weighted_numerator,
        unrounded_grade=unrounded_grade,
        rounded_grade=rounded_grade,
        reasons=(),
    )


def _resolve_standard_result(
    item: StandardsGradeStandardInput,
    exact_scale: ProficiencyScaleReference,
    conversion: dict[str, Decimal],
    treatment: GradeStateTreatment,
) -> StandardsGradeStandardResult:
    participation = item.participation
    reason_codes = item.reason_codes

    if item.status == "calculated":
        if item.freshness_status != "current":
            return _state_result(
                item,
                source_state="unresolved",
                treatment=treatment,
                reason_codes=reason_codes + ("upstream_result_stale",),
            )
        if item.target_scale != exact_scale:
            return _state_result(
                item,
                source_state="unresolved",
                treatment=treatment,
                reason_codes=reason_codes + ("proficiency_scale_mismatch",),
            )
        level_id = item.proficiency_level_id
        if level_id is None or level_id not in conversion:
            return _state_result(
                item,
                source_state="invalid",
                treatment=treatment,
                reason_codes=reason_codes + ("proficiency_level_not_in_conversion",),
            )
        converted = conversion[level_id]
        contribution = _multiply_exact(converted, participation.weight)
        return StandardsGradeStandardResult(
            standard_id=participation.standard_id,
            weight=participation.weight,
            source_state="calculated",
            action="contribute",
            result_reference=item.result_reference,
            result_calculation_fingerprint=item.result_calculation_fingerprint,
            result_algorithm_version=item.result_algorithm_version,
            target_scale=item.target_scale,
            proficiency_level_id=level_id,
            converted_grade_value=converted,
            calculation_value=converted,
            weighted_contribution=contribution,
            freshness_status=item.freshness_status,
            freshness_reasons=item.freshness_reasons,
            reason_codes=reason_codes,
        )

    return _state_result(
        item,
        source_state=item.status,
        treatment=treatment,
        reason_codes=reason_codes,
    )


def _state_result(
    item: StandardsGradeStandardInput,
    *,
    source_state: StandardsGradeSourceState,
    treatment: GradeStateTreatment,
    reason_codes: tuple[str, ...],
) -> StandardsGradeStandardResult:
    if source_state == "calculated":
        raise StandardsGradeValidationError(
            "calculated source state must use explicit conversion resolution."
        )
    consequence = _state_consequence(treatment, source_state)
    calculation_value = Decimal("0") if consequence == "zero" else None
    contribution = (
        Decimal("0") * item.participation.weight
        if consequence == "zero"
        else None
    )
    return StandardsGradeStandardResult(
        standard_id=item.participation.standard_id,
        weight=item.participation.weight,
        source_state=source_state,
        action=consequence,
        result_reference=item.result_reference,
        result_calculation_fingerprint=item.result_calculation_fingerprint,
        result_algorithm_version=item.result_algorithm_version,
        target_scale=item.target_scale,
        proficiency_level_id=None,
        converted_grade_value=None,
        calculation_value=calculation_value,
        weighted_contribution=contribution,
        freshness_status=item.freshness_status,
        freshness_reasons=item.freshness_reasons,
        reason_codes=reason_codes,
    )


def _state_consequence(
    treatment: GradeStateTreatment,
    state: StandardsGradeSourceState,
) -> GradeStateConsequence:
    if state == "calculated":
        raise StandardsGradeValidationError(
            "calculated source state does not use non-Grade state treatment."
        )
    return cast(GradeStateConsequence, getattr(treatment, state))


def _outcome(
    inputs: StandardsGradeCalculationInput,
    fingerprint: str,
    standard_results: tuple[StandardsGradeStandardResult, ...],
    actual_calculated: int,
    *,
    status: StandardsGradeCalculationStatus,
    active_weight: Decimal | None,
    weighted_numerator: Decimal | None,
    unrounded_grade: Decimal | None,
    rounded_grade: Decimal | None,
    reasons: tuple[StandardsGradeReason, ...],
) -> StandardsGradeCalculationOutcome:
    return StandardsGradeCalculationOutcome(
        status=status,
        algorithm_version=STANDARDS_GRADE_ALGORITHM_VERSION,
        calculation_fingerprint=fingerprint,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        target_scale=inputs.configuration.target_scale,
        aggregation_strategy=inputs.configuration.aggregation_strategy,
        student_id=inputs.student_id,
        actual_calculated_result_count=actual_calculated,
        minimum_calculated_results=inputs.configuration.minimum_calculated_results,
        active_weight=active_weight,
        weighted_numerator=weighted_numerator,
        unrounded_grade=unrounded_grade,
        rounded_grade=rounded_grade,
        standard_results=standard_results,
        reasons=reasons,
    )


def _calculation_input_to_dict(
    value: StandardsGradeCalculationInput,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "configuration": {
            "target_scale": _scale_reference_to_dict(value.configuration.target_scale),
            "standards": [
                {
                    "standard_id": item.standard_id,
                    "weight": _decimal_to_text(item.weight),
                }
                for item in value.configuration.standards
            ],
            "conversions": [
                {
                    "proficiency_level_id": item.proficiency_level_id,
                    "grade_value": _decimal_to_text(item.grade_value),
                }
                for item in value.configuration.conversions
            ],
            "aggregation_strategy": value.configuration.aggregation_strategy,
            "minimum_calculated_results": (
                value.configuration.minimum_calculated_results
            ),
        },
        "state_treatment": {
            field_name: getattr(value.state_treatment, field_name)
            for field_name in _NON_CALCULATED_STATES
        },
        "rounding": {
            "quantum": _decimal_to_text(value.rounding.quantum),
            "mode": value.rounding.mode,
            "application_stage": value.rounding.application_stage,
        },
        "standards": [_standard_input_to_dict(item) for item in value.standards],
    }


def _standard_input_to_dict(value: StandardsGradeStandardInput) -> dict[str, object]:
    return {
        "participation": {
            "standard_id": value.participation.standard_id,
            "weight": _decimal_to_text(value.participation.weight),
        },
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "status": value.status,
        "result_reference": (
            None
            if value.result_reference is None
            else _result_reference_to_dict(value.result_reference)
        ),
        "result_calculation_fingerprint": value.result_calculation_fingerprint,
        "result_algorithm_version": value.result_algorithm_version,
        "proficiency_level_id": value.proficiency_level_id,
        "target_scale": (
            None
            if value.target_scale is None
            else _scale_reference_to_dict(value.target_scale)
        ),
        "freshness_status": value.freshness_status,
        "freshness_reasons": list(value.freshness_reasons),
        "reason_codes": list(value.reason_codes),
    }


def _result_reference_to_dict(
    value: AcademicPeriodProficiencyResultReference,
) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "school_year": value.school_year,
        "period_id": value.period_id,
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "result_sha256": value.result_sha256,
    }


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(
            64,
            _decimal_precision(left) + _decimal_precision(right) + 16,
        )
        return left * right


def _round_final_grade(value: Decimal, policy: GradeRoundingPolicy) -> Decimal:
    try:
        rounding = _ROUNDING[policy.mode]
    except KeyError as error:
        raise StandardsGradeValidationError(
            "unsupported Grade rounding mode."
        ) from error
    with localcontext() as context:
        context.prec = max(
            64,
            _decimal_precision(value)
            + _decimal_precision(policy.quantum)
            + 16,
        )
        return value.quantize(policy.quantum, rounding=rounding)


def _calculation_precision(inputs: StandardsGradeCalculationInput) -> int:
    digits = [_decimal_precision(inputs.rounding.quantum)]
    digits.extend(
        _decimal_precision(item.weight)
        for item in inputs.configuration.standards
    )
    digits.extend(
        _decimal_precision(item.grade_value)
        for item in inputs.configuration.conversions
    )
    return max(64, max(digits, default=1) * 4 + 32)


def _decimal_precision(value: Decimal) -> int:
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int):
        raise StandardsGradeValidationError(
            "finite Decimal unexpectedly has a non-integer exponent."
        )
    return max(
        1,
        len(normalized.as_tuple().digits) + abs(exponent),
    )


def _decimal_to_text(value: Decimal) -> str:
    finite = _finite_decimal(value, "Decimal value")
    text = format(finite, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


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
        raise StandardsGradeValidationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _academic_period_ref(value: AcademicPeriodRef) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise StandardsGradeValidationError(
            "target_period must be an AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise StandardsGradeValidationError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsGradeValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardsGradeValidationError(str(error)) from error


def _standard_id(value: object) -> str:
    if not isinstance(value, str):
        raise StandardsGradeValidationError("standard_id must be a string.")
    try:
        return normalize_standard_id(value)
    except ValueError as error:
        raise StandardsGradeValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StandardsGradeValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StandardsGradeValidationError(
            f"{field_name} must be a nonnegative integer."
        )
    return value


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise StandardsGradeValidationError(
            f"{field_name} must be an exact finite Decimal."
        )
    return value


def _positive_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _finite_decimal(value, field_name)
    if decimal_value <= 0:
        raise StandardsGradeValidationError(
            f"{field_name} must be greater than zero."
        )
    return decimal_value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardsGradeValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise StandardsGradeValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise StandardsGradeValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise StandardsGradeValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise StandardsGradeValidationError(
            f"{field_name} must be single-line and control-free."
        )
    return value


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise StandardsGradeValidationError("reason code is invalid.")
    return value


def _reason_codes(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise StandardsGradeValidationError("reason codes must be an iterable.")
    try:
        values = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise StandardsGradeValidationError(
            "reason codes must be an iterable."
        ) from error
    result = tuple(_reason_code(item) for item in values)
    if len(set(result)) != len(result):
        raise StandardsGradeValidationError("reason codes must not contain duplicates.")
    return result
