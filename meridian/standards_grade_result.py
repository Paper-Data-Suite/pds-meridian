"""Immutable result contract and freshness for standards-based Grade calculation.

A standards Grade result is advisory Meridian calculation history. It is not a
teacher override, Grade preview presentation, ReportingSnapshot, export, or
official Grade.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GradePolicyReference,
    GradeRoundingMode,
    GradeRoundingPolicy,
    GradeRoundingStage,
    GradeStateConsequence,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference_from_dict,
    grade_policy_reference_to_dict,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationReference,
    grade_policy_activation_reference_from_dict,
    grade_policy_activation_reference_to_dict,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    StandardsGradeAction,
    StandardsGradeCalculationInput,
    StandardsGradeCalculationOutcome,
    StandardsGradeCalculationStatus,
    StandardsGradeReason,
    StandardsGradeSourceState,
    StandardsGradeStandardInput,
    StandardsGradeStandardResult,
    StandardsGradeUpstreamFreshnessStatus,
    calculate_standards_grade,
    standards_grade_calculation_input_sha256,
    standards_grade_calculation_input_to_dict,
)

STANDARDS_GRADE_RESULT_SCHEMA_VERSION: Final[str] = "1"
STANDARDS_GRADE_RESULT_RECORD_TYPE: Final[str] = "meridian_standards_grade_result"

StandardsGradeFreshnessStatus: TypeAlias = Literal["current", "stale"]
StandardsGradeStalenessReason: TypeAlias = Literal[
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "proficiency_results_changed",
    "algorithm_changed",
]

_STALENESS_REASON_ORDER: Final[tuple[StandardsGradeStalenessReason, ...]] = (
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "proficiency_results_changed",
    "algorithm_changed",
)
_STALENESS_REASON_SET: Final[frozenset[str]] = frozenset(_STALENESS_REASON_ORDER)
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
_INPUT_KEYS: Final[frozenset[str]] = frozenset(
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
        "standards",
    }
)
_STANDARD_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "participation",
        "student_id",
        "target_period",
        "calendar_revision",
        "status",
        "result_reference",
        "result_calculation_fingerprint",
        "result_algorithm_version",
        "proficiency_level_id",
        "target_scale",
        "freshness_status",
        "freshness_reasons",
        "reason_codes",
    }
)
_STANDARD_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "standard_id",
        "weight",
        "source_state",
        "action",
        "result_reference",
        "result_calculation_fingerprint",
        "result_algorithm_version",
        "target_scale",
        "proficiency_level_id",
        "converted_grade_value",
        "calculation_value",
        "weighted_contribution",
        "freshness_status",
        "freshness_reasons",
        "reason_codes",
    }
)
_OUTCOME_KEYS: Final[frozenset[str]] = frozenset(
    {
        "status",
        "algorithm_version",
        "calculation_fingerprint",
        "target_period",
        "calendar_revision",
        "activation_reference",
        "policy_reference",
        "target_scale",
        "aggregation_strategy",
        "student_id",
        "actual_calculated_result_count",
        "minimum_calculated_results",
        "active_weight",
        "weighted_numerator",
        "unrounded_grade",
        "rounded_grade",
        "standard_results",
        "reasons",
    }
)
_RESULT_KEYS: Final[frozenset[str]] = frozenset(
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
        "target_scale",
        "outcome",
        "calculated_at",
    }
)
_RESULT_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "student_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "result_revision",
        "result_sha256",
    }
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_REASON_CODE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")


class StandardsGradeResultError(ValueError):
    """Base error for immutable standards Grade result contracts."""


class StandardsGradeResultValidationError(StandardsGradeResultError):
    """Raised when result data violates the exact immutable contract."""


class StandardsGradeResultSerializationError(StandardsGradeResultError):
    """Raised when canonical standards Grade result JSON is invalid."""


@dataclass(frozen=True, slots=True)
class StandardsGradeResultSnapshot:
    """Immutable persisted wrapper around one exact standards calculation."""

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
    inputs: StandardsGradeCalculationInput
    inputs_sha256: str
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    target_scale: ProficiencyScaleReference
    outcome: StandardsGradeCalculationOutcome
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != STANDARDS_GRADE_RESULT_SCHEMA_VERSION:
            raise StandardsGradeResultValidationError(
                "unsupported standards Grade result schema_version."
            )
        if self.record_type != STANDARDS_GRADE_RESULT_RECORD_TYPE:
            raise StandardsGradeResultValidationError(
                "record_type must identify a standards Grade result."
            )
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        target_period = _period(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        revision = _positive_int(self.result_revision, "result_revision")
        supersedes = self.supersedes_revision
        if supersedes is not None:
            supersedes = _positive_int(supersedes, "supersedes_revision")
        if revision == 1 and supersedes is not None:
            raise StandardsGradeResultValidationError(
                "result revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise StandardsGradeResultValidationError(
                "result supersedes_revision must identify the prior revision."
            )
        if self.algorithm_version != STANDARDS_GRADE_ALGORITHM_VERSION:
            raise StandardsGradeResultValidationError(
                "unsupported standards Grade result algorithm_version."
            )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        if not isinstance(self.inputs, StandardsGradeCalculationInput):
            raise StandardsGradeResultValidationError(
                "inputs must be StandardsGradeCalculationInput."
            )
        inputs_sha256 = _sha256(self.inputs_sha256, "inputs_sha256")
        if inputs_sha256 != standards_grade_calculation_input_sha256(self.inputs):
            raise StandardsGradeResultValidationError(
                "inputs_sha256 must match the exact embedded calculation inputs."
            )
        if (
            self.inputs.class_id != class_id
            or self.inputs.student_id != student_id
            or self.inputs.target_period != target_period
            or self.inputs.calendar_revision != calendar_revision
        ):
            raise StandardsGradeResultValidationError(
                "result scope must match exact embedded calculation inputs."
            )
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise StandardsGradeResultValidationError(
                "activation_reference must be exact activation provenance."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise StandardsGradeResultValidationError(
                "policy_reference must be exact Grade-policy provenance."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardsGradeResultValidationError(
                "target_scale must be exact proficiency-scale provenance."
            )
        if self.activation_reference != self.inputs.activation_reference:
            raise StandardsGradeResultValidationError(
                "result activation_reference must match embedded inputs."
            )
        if self.policy_reference != self.inputs.policy_reference:
            raise StandardsGradeResultValidationError(
                "result policy_reference must match embedded inputs."
            )
        if self.target_scale != self.inputs.configuration.target_scale:
            raise StandardsGradeResultValidationError(
                "result target_scale must match embedded inputs."
            )
        if not isinstance(self.outcome, StandardsGradeCalculationOutcome):
            raise StandardsGradeResultValidationError(
                "outcome must be StandardsGradeCalculationOutcome."
            )
        exact_outcome = calculate_standards_grade(self.inputs)
        if self.outcome != exact_outcome:
            raise StandardsGradeResultValidationError(
                "persisted outcome must exactly reproduce from embedded inputs."
            )
        if (
            self.outcome.algorithm_version != self.algorithm_version
            or self.outcome.calculation_fingerprint != fingerprint
            or self.outcome.activation_reference != self.activation_reference
            or self.outcome.policy_reference != self.policy_reference
            or self.outcome.target_scale != self.target_scale
        ):
            raise StandardsGradeResultValidationError(
                "result metadata must match the exact pure calculation outcome."
            )
        calculated_at = _aware_utc(self.calculated_at, "calculated_at")
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
class StandardsGradeResultReference:
    """Exact immutable standards Grade result revision and digest."""

    class_id: str
    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    result_revision: int
    result_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
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
class StandardsGradeResultFreshness:
    """Pure diagnostic comparison to explicit current standards Grade state."""

    status: StandardsGradeFreshnessStatus
    reasons: tuple[StandardsGradeStalenessReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale"}:
            raise StandardsGradeResultValidationError(
                "unsupported standards Grade freshness status."
            )
        reasons = _staleness_reasons(self.reasons)
        if self.status == "current" and reasons:
            raise StandardsGradeResultValidationError(
                "current freshness status requires no staleness reasons."
            )
        if self.status == "stale" and not reasons:
            raise StandardsGradeResultValidationError(
                "stale freshness status requires at least one reason."
            )
        object.__setattr__(self, "reasons", reasons)


def create_standards_grade_result_snapshot(
    inputs: StandardsGradeCalculationInput,
    outcome: StandardsGradeCalculationOutcome,
    *,
    result_revision: int,
    calculated_at: datetime,
) -> StandardsGradeResultSnapshot:
    """Wrap one pure calculation in immutable result metadata."""

    if not isinstance(inputs, StandardsGradeCalculationInput):
        raise StandardsGradeResultValidationError(
            "inputs must be StandardsGradeCalculationInput."
        )
    if not isinstance(outcome, StandardsGradeCalculationOutcome):
        raise StandardsGradeResultValidationError(
            "outcome must be StandardsGradeCalculationOutcome."
        )
    revision = _positive_int(result_revision, "result_revision")
    return StandardsGradeResultSnapshot(
        schema_version=STANDARDS_GRADE_RESULT_SCHEMA_VERSION,
        record_type=STANDARDS_GRADE_RESULT_RECORD_TYPE,
        class_id=inputs.class_id,
        student_id=inputs.student_id,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=standards_grade_calculation_input_sha256(inputs),
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        target_scale=inputs.configuration.target_scale,
        outcome=outcome,
        calculated_at=calculated_at,
    )


def validate_standards_grade_result_transition(
    previous: StandardsGradeResultSnapshot,
    current: StandardsGradeResultSnapshot,
) -> StandardsGradeResultSnapshot:
    """Validate contiguous immutable history for one exact result family."""

    if not isinstance(previous, StandardsGradeResultSnapshot):
        raise StandardsGradeResultValidationError(
            "previous must be StandardsGradeResultSnapshot."
        )
    if not isinstance(current, StandardsGradeResultSnapshot):
        raise StandardsGradeResultValidationError(
            "current must be StandardsGradeResultSnapshot."
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
        raise StandardsGradeResultValidationError(
            "standards Grade result logical identity cannot change."
        )
    if current.result_revision != previous.result_revision + 1:
        raise StandardsGradeResultValidationError(
            "standards Grade result revisions must be contiguous."
        )
    if current.supersedes_revision != previous.result_revision:
        raise StandardsGradeResultValidationError(
            "result supersedes_revision must identify the prior revision."
        )
    if current.calculated_at < previous.calculated_at:
        raise StandardsGradeResultValidationError(
            "result calculated_at must be nondecreasing."
        )
    return current


def standards_grade_result_snapshot_to_dict(
    value: StandardsGradeResultSnapshot,
) -> dict[str, object]:
    if not isinstance(value, StandardsGradeResultSnapshot):
        raise StandardsGradeResultValidationError(
            "value must be StandardsGradeResultSnapshot."
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
        "inputs": standards_grade_calculation_input_to_dict(value.inputs),
        "inputs_sha256": value.inputs_sha256,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "outcome": standards_grade_calculation_outcome_to_dict(value.outcome),
        "calculated_at": value.calculated_at.isoformat(),
    }


def standards_grade_result_snapshot_from_dict(
    data: object,
) -> StandardsGradeResultSnapshot:
    mapping = _exact_mapping(data, _RESULT_KEYS, "standards Grade result snapshot")
    return StandardsGradeResultSnapshot(
        schema_version=_required_str(mapping["schema_version"], "schema_version"),
        record_type=_required_str(mapping["record_type"], "record_type"),
        class_id=_required_str(mapping["class_id"], "class_id"),
        student_id=_required_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_required_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        result_revision=_required_int(mapping["result_revision"], "result_revision"),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"], "supersedes_revision"
        ),
        algorithm_version=_required_str(
            mapping["algorithm_version"], "algorithm_version"
        ),
        calculation_fingerprint=_required_str(
            mapping["calculation_fingerprint"], "calculation_fingerprint"
        ),
        inputs=standards_grade_calculation_input_from_dict(mapping["inputs"]),
        inputs_sha256=_required_str(mapping["inputs_sha256"], "inputs_sha256"),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(mapping["policy_reference"]),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        outcome=standards_grade_calculation_outcome_from_dict(mapping["outcome"]),
        calculated_at=_datetime_from_text(mapping["calculated_at"], "calculated_at"),
    )


def standards_grade_result_snapshot_to_json_bytes(
    value: StandardsGradeResultSnapshot,
) -> bytes:
    return _canonical_json_bytes(standards_grade_result_snapshot_to_dict(value))


def standards_grade_result_snapshot_from_json_bytes(
    data: bytes,
) -> StandardsGradeResultSnapshot:
    decoded = _decode_json(data, "standards Grade result snapshot")
    value = standards_grade_result_snapshot_from_dict(decoded)
    if standards_grade_result_snapshot_to_json_bytes(value) != data:
        raise StandardsGradeResultSerializationError(
            "standards Grade result snapshot is not canonical JSON."
        )
    return value


def standards_grade_result_reference(
    value: StandardsGradeResultSnapshot,
) -> StandardsGradeResultReference:
    content = standards_grade_result_snapshot_to_json_bytes(value)
    return StandardsGradeResultReference(
        class_id=value.class_id,
        student_id=value.student_id,
        school_year=value.target_period.school_year,
        period_id=value.target_period.period_id,
        calendar_revision=value.calendar_revision,
        result_revision=value.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )


def standards_grade_result_reference_to_dict(
    value: StandardsGradeResultReference,
) -> dict[str, object]:
    if not isinstance(value, StandardsGradeResultReference):
        raise StandardsGradeResultValidationError(
            "value must be StandardsGradeResultReference."
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


def standards_grade_result_reference_from_dict(
    data: object,
) -> StandardsGradeResultReference:
    mapping = _exact_mapping(
        data,
        _RESULT_REFERENCE_KEYS,
        "standards Grade result reference",
    )
    return StandardsGradeResultReference(
        class_id=_required_str(mapping["class_id"], "class_id"),
        student_id=_required_str(mapping["student_id"], "student_id"),
        school_year=_required_str(mapping["school_year"], "school_year"),
        period_id=_required_str(mapping["period_id"], "period_id"),
        calendar_revision=_required_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        result_revision=_required_int(mapping["result_revision"], "result_revision"),
        result_sha256=_required_str(mapping["result_sha256"], "result_sha256"),
    )


def assess_standards_grade_result_freshness(
    result: StandardsGradeResultSnapshot,
    current_inputs: StandardsGradeCalculationInput,
    *,
    algorithm_version: str = STANDARDS_GRADE_ALGORITHM_VERSION,
) -> StandardsGradeResultFreshness:
    """Compare immutable history to explicit current state without mutation."""

    if not isinstance(result, StandardsGradeResultSnapshot):
        raise StandardsGradeResultValidationError(
            "result must be StandardsGradeResultSnapshot."
        )
    result.__post_init__()
    if not isinstance(current_inputs, StandardsGradeCalculationInput):
        raise StandardsGradeResultValidationError(
            "current_inputs must be StandardsGradeCalculationInput."
        )
    if (
        current_inputs.class_id != result.class_id
        or current_inputs.student_id != result.student_id
    ):
        raise StandardsGradeResultValidationError(
            "freshness comparison must preserve class/student identity."
        )
    current_algorithm = _bounded_text(algorithm_version, "algorithm_version", 256)
    reasons: list[StandardsGradeStalenessReason] = []
    if (
        current_inputs.target_period != result.target_period
        or current_inputs.calendar_revision != result.calendar_revision
    ):
        reasons.append("calendar_scope_changed")
    if current_inputs.activation_reference != result.activation_reference:
        reasons.append("activation_changed")
    if current_inputs.policy_reference != result.policy_reference:
        reasons.append("policy_changed")
    if _proficiency_basis_sha256(current_inputs) != _proficiency_basis_sha256(
        result.inputs
    ):
        reasons.append("proficiency_results_changed")
    if current_algorithm != result.algorithm_version:
        reasons.append("algorithm_changed")
    return StandardsGradeResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def standards_grade_calculation_outcome_to_dict(
    value: StandardsGradeCalculationOutcome,
) -> dict[str, object]:
    if not isinstance(value, StandardsGradeCalculationOutcome):
        raise StandardsGradeResultValidationError(
            "value must be StandardsGradeCalculationOutcome."
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
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "aggregation_strategy": value.aggregation_strategy,
        "student_id": value.student_id,
        "actual_calculated_result_count": value.actual_calculated_result_count,
        "minimum_calculated_results": value.minimum_calculated_results,
        "active_weight": _optional_decimal_text(value.active_weight),
        "weighted_numerator": _optional_decimal_text(value.weighted_numerator),
        "unrounded_grade": _optional_decimal_text(value.unrounded_grade),
        "rounded_grade": _optional_decimal_text(value.rounded_grade),
        "standard_results": [
            _standard_result_to_dict(item) for item in value.standard_results
        ],
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def standards_grade_calculation_outcome_from_dict(
    data: object,
) -> StandardsGradeCalculationOutcome:
    mapping = _exact_mapping(data, _OUTCOME_KEYS, "standards Grade outcome")
    return StandardsGradeCalculationOutcome(
        status=cast(
            StandardsGradeCalculationStatus,
            _required_str(mapping["status"], "status"),
        ),
        algorithm_version=_required_str(
            mapping["algorithm_version"], "algorithm_version"
        ),
        calculation_fingerprint=_required_str(
            mapping["calculation_fingerprint"], "calculation_fingerprint"
        ),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_required_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(mapping["policy_reference"]),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        aggregation_strategy=_required_str(
            mapping["aggregation_strategy"], "aggregation_strategy"
        ),
        student_id=_required_str(mapping["student_id"], "student_id"),
        actual_calculated_result_count=_required_int(
            mapping["actual_calculated_result_count"],
            "actual_calculated_result_count",
            allow_zero=True,
        ),
        minimum_calculated_results=_required_int(
            mapping["minimum_calculated_results"], "minimum_calculated_results"
        ),
        active_weight=_optional_decimal(mapping["active_weight"], "active_weight"),
        weighted_numerator=_optional_decimal(
            mapping["weighted_numerator"], "weighted_numerator"
        ),
        unrounded_grade=_optional_decimal(
            mapping["unrounded_grade"], "unrounded_grade"
        ),
        rounded_grade=_optional_decimal(mapping["rounded_grade"], "rounded_grade"),
        standard_results=tuple(
            _standard_result_from_dict(item)
            for item in _required_list(mapping["standard_results"], "standard_results")
        ),
        reasons=tuple(
            _reason_from_dict(item)
            for item in _required_list(mapping["reasons"], "reasons")
        ),
    )


def standards_grade_calculation_outcome_to_json_bytes(
    value: StandardsGradeCalculationOutcome,
) -> bytes:
    return _canonical_json_bytes(standards_grade_calculation_outcome_to_dict(value))


def standards_grade_calculation_outcome_from_json_bytes(
    data: bytes,
) -> StandardsGradeCalculationOutcome:
    decoded = _decode_json(data, "standards Grade calculation outcome")
    value = standards_grade_calculation_outcome_from_dict(decoded)
    if standards_grade_calculation_outcome_to_json_bytes(value) != data:
        raise StandardsGradeResultSerializationError(
            "standards Grade calculation outcome is not canonical JSON."
        )
    return value


def standards_grade_calculation_input_from_dict(
    data: object,
) -> StandardsGradeCalculationInput:
    mapping = _exact_mapping(data, _INPUT_KEYS, "standards Grade calculation input")
    configuration = _configuration_from_dict(mapping["configuration"])
    return StandardsGradeCalculationInput(
        class_id=_required_str(mapping["class_id"], "class_id"),
        student_id=_required_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_required_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        activation_reference=_activation_reference_from_dict(
            mapping["activation_reference"]
        ),
        policy_reference=_policy_reference_from_dict(mapping["policy_reference"]),
        configuration=configuration,
        state_treatment=_state_treatment_from_dict(mapping["state_treatment"]),
        rounding=_rounding_from_dict(mapping["rounding"]),
        standards=tuple(
            _standard_input_from_dict(item)
            for item in _required_list(mapping["standards"], "standards")
        ),
    )


def standards_grade_calculation_input_from_json_bytes(
    data: bytes,
) -> StandardsGradeCalculationInput:
    decoded = _decode_json(data, "standards Grade calculation input")
    value = standards_grade_calculation_input_from_dict(decoded)
    from meridian.standards_grade import standards_grade_calculation_input_to_json_bytes

    if standards_grade_calculation_input_to_json_bytes(value) != data:
        raise StandardsGradeResultSerializationError(
            "standards Grade calculation input is not canonical JSON."
        )
    return value


def _configuration_from_dict(data: object) -> StandardsBasedGradeConfiguration:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "target_scale",
                "standards",
                "conversions",
                "aggregation_strategy",
                "minimum_calculated_results",
            }
        ),
        "standards Grade configuration",
    )
    return StandardsBasedGradeConfiguration(
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        standards=tuple(
            StandardGradeParticipation(
                standard_id=_required_str(item["standard_id"], "standard_id"),
                weight=_required_decimal(item["weight"], "weight"),
            )
            for item in (
                _exact_mapping(
                    value,
                    frozenset({"standard_id", "weight"}),
                    "standard participation",
                )
                for value in _required_list(mapping["standards"], "standards")
            )
        ),
        conversions=tuple(
            ProficiencyGradeConversion(
                proficiency_level_id=_required_str(
                    item["proficiency_level_id"], "proficiency_level_id"
                ),
                grade_value=_required_decimal(item["grade_value"], "grade_value"),
            )
            for item in (
                _exact_mapping(
                    value,
                    frozenset({"proficiency_level_id", "grade_value"}),
                    "proficiency conversion",
                )
                for value in _required_list(mapping["conversions"], "conversions")
            )
        ),
        aggregation_strategy=cast(
            Literal["weighted_mean"],
            _required_str(mapping["aggregation_strategy"], "aggregation_strategy"),
        ),
        minimum_calculated_results=_required_int(
            mapping["minimum_calculated_results"], "minimum_calculated_results"
        ),
    )


def _state_treatment_from_dict(data: object) -> GradeStateTreatment:
    mapping = _exact_mapping(
        data,
        frozenset(_NON_CALCULATED_STATES),
        "Grade state treatment",
    )
    def consequence(field_name: str) -> GradeStateConsequence:
        return cast(
            GradeStateConsequence,
            _required_str(mapping[field_name], field_name),
        )

    return GradeStateTreatment(
        missing=consequence("missing"),
        pending=consequence("pending"),
        incomplete=consequence("incomplete"),
        excused=consequence("excused"),
        excluded=consequence("excluded"),
        not_applicable=consequence("not_applicable"),
        insufficient_evidence=consequence("insufficient_evidence"),
        unavailable=consequence("unavailable"),
        withdrawn=consequence("withdrawn"),
        invalid=consequence("invalid"),
        unresolved=consequence("unresolved"),
    )


def _rounding_from_dict(data: object) -> GradeRoundingPolicy:
    mapping = _exact_mapping(
        data,
        frozenset({"quantum", "mode", "application_stage"}),
        "Grade rounding policy",
    )
    return GradeRoundingPolicy(
        quantum=_required_decimal(mapping["quantum"], "quantum"),
        mode=cast(
            GradeRoundingMode,
            _required_str(mapping["mode"], "mode"),
        ),
        application_stage=cast(
            GradeRoundingStage,
            _required_str(mapping["application_stage"], "application_stage"),
        ),
    )


def _standard_input_from_dict(data: object) -> StandardsGradeStandardInput:
    mapping = _exact_mapping(data, _STANDARD_INPUT_KEYS, "standards Grade input entry")
    participation = _exact_mapping(
        mapping["participation"],
        frozenset({"standard_id", "weight"}),
        "standard participation",
    )
    reference_data = mapping["result_reference"]
    scale_data = mapping["target_scale"]
    freshness = mapping["freshness_status"]
    return StandardsGradeStandardInput(
        participation=StandardGradeParticipation(
            standard_id=_required_str(participation["standard_id"], "standard_id"),
            weight=_required_decimal(participation["weight"], "weight"),
        ),
        student_id=_required_str(mapping["student_id"], "student_id"),
        target_period=_period_from_dict(mapping["target_period"]),
        calendar_revision=_required_int(
            mapping["calendar_revision"], "calendar_revision"
        ),
        status=cast(
            StandardsGradeSourceState,
            _required_str(mapping["status"], "status"),
        ),
        result_reference=(
            None
            if reference_data is None
            else _proficiency_result_reference(reference_data)
        ),
        result_calculation_fingerprint=_optional_str(
            mapping["result_calculation_fingerprint"],
            "result_calculation_fingerprint",
        ),
        result_algorithm_version=_optional_str(
            mapping["result_algorithm_version"], "result_algorithm_version"
        ),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"], "proficiency_level_id"
        ),
        target_scale=(
            None
            if scale_data is None
            else _scale_reference_from_dict(scale_data)
        ),
        freshness_status=(
            None
            if freshness is None
            else cast(
                StandardsGradeUpstreamFreshnessStatus,
                _required_str(freshness, "freshness_status"),
            )
        ),
        freshness_reasons=_string_tuple(
            mapping["freshness_reasons"], "freshness_reasons"
        ),
        reason_codes=_string_tuple(mapping["reason_codes"], "reason_codes"),
    )


def _standard_result_to_dict(value: StandardsGradeStandardResult) -> dict[str, object]:
    return {
        "standard_id": value.standard_id,
        "weight": _decimal_text(value.weight),
        "source_state": value.source_state,
        "action": value.action,
        "result_reference": (
            None
            if value.result_reference is None
            else _proficiency_result_reference_to_dict(value.result_reference)
        ),
        "result_calculation_fingerprint": value.result_calculation_fingerprint,
        "result_algorithm_version": value.result_algorithm_version,
        "target_scale": (
            None
            if value.target_scale is None
            else _scale_reference_to_dict(value.target_scale)
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "converted_grade_value": _optional_decimal_text(value.converted_grade_value),
        "calculation_value": _optional_decimal_text(value.calculation_value),
        "weighted_contribution": _optional_decimal_text(value.weighted_contribution),
        "freshness_status": value.freshness_status,
        "freshness_reasons": list(value.freshness_reasons),
        "reason_codes": list(value.reason_codes),
    }


def _standard_result_from_dict(data: object) -> StandardsGradeStandardResult:
    mapping = _exact_mapping(
        data,
        _STANDARD_RESULT_KEYS,
        "standards Grade result entry",
    )
    reference_data = mapping["result_reference"]
    scale_data = mapping["target_scale"]
    freshness = mapping["freshness_status"]
    return StandardsGradeStandardResult(
        standard_id=_required_str(mapping["standard_id"], "standard_id"),
        weight=_required_decimal(mapping["weight"], "weight"),
        source_state=cast(
            StandardsGradeSourceState,
            _required_str(mapping["source_state"], "source_state"),
        ),
        action=cast(
            StandardsGradeAction,
            _required_str(mapping["action"], "action"),
        ),
        result_reference=(
            None
            if reference_data is None
            else _proficiency_result_reference(reference_data)
        ),
        result_calculation_fingerprint=_optional_str(
            mapping["result_calculation_fingerprint"],
            "result_calculation_fingerprint",
        ),
        result_algorithm_version=_optional_str(
            mapping["result_algorithm_version"], "result_algorithm_version"
        ),
        target_scale=(
            None
            if scale_data is None
            else _scale_reference_from_dict(scale_data)
        ),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"], "proficiency_level_id"
        ),
        converted_grade_value=_optional_decimal(
            mapping["converted_grade_value"], "converted_grade_value"
        ),
        calculation_value=_optional_decimal(
            mapping["calculation_value"], "calculation_value"
        ),
        weighted_contribution=_optional_decimal(
            mapping["weighted_contribution"], "weighted_contribution"
        ),
        freshness_status=(
            None
            if freshness is None
            else cast(
                StandardsGradeUpstreamFreshnessStatus,
                _required_str(freshness, "freshness_status"),
            )
        ),
        freshness_reasons=_string_tuple(
            mapping["freshness_reasons"], "freshness_reasons"
        ),
        reason_codes=_string_tuple(mapping["reason_codes"], "reason_codes"),
    )


def _reason_to_dict(value: StandardsGradeReason) -> dict[str, object]:
    return {
        "code": value.code,
        "standard_id": value.standard_id,
        "required_results": value.required_results,
        "actual_results": value.actual_results,
    }


def _reason_from_dict(data: object) -> StandardsGradeReason:
    mapping = _exact_mapping(
        data,
        frozenset({"code", "standard_id", "required_results", "actual_results"}),
        "standards Grade reason",
    )
    return StandardsGradeReason(
        code=_required_str(mapping["code"], "code"),
        standard_id=_optional_str(mapping["standard_id"], "standard_id"),
        required_results=_optional_int(mapping["required_results"], "required_results"),
        actual_results=_optional_int(
            mapping["actual_results"], "actual_results", allow_zero=True
        ),
    )


def _proficiency_basis_sha256(value: StandardsGradeCalculationInput) -> str:
    body = {
        "target_scale": _scale_reference_to_dict(value.configuration.target_scale),
        "standards": [
            {
                "standard_id": item.participation.standard_id,
                "status": item.status,
                "result_reference": (
                    None
                    if item.result_reference is None
                    else _proficiency_result_reference_to_dict(item.result_reference)
                ),
                "result_calculation_fingerprint": item.result_calculation_fingerprint,
                "result_algorithm_version": item.result_algorithm_version,
                "proficiency_level_id": item.proficiency_level_id,
                "target_scale": (
                    None
                    if item.target_scale is None
                    else _scale_reference_to_dict(item.target_scale)
                ),
                "freshness_status": item.freshness_status,
                "freshness_reasons": list(item.freshness_reasons),
                "reason_codes": list(item.reason_codes),
            }
            for item in value.standards
        ],
    }
    return hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def _proficiency_result_reference(
    data: object,
) -> AcademicPeriodProficiencyResultReference:
    mapping = _exact_mapping(
        data,
        frozenset(
            {
                "class_id",
                "school_year",
                "period_id",
                "student_id",
                "standard_id",
                "result_revision",
                "result_sha256",
            }
        ),
        "Academic Period proficiency result reference",
    )
    return AcademicPeriodProficiencyResultReference(
        class_id=_required_str(mapping["class_id"], "class_id"),
        school_year=_required_str(mapping["school_year"], "school_year"),
        period_id=_required_str(mapping["period_id"], "period_id"),
        student_id=_required_str(mapping["student_id"], "student_id"),
        standard_id=_required_str(mapping["standard_id"], "standard_id"),
        result_revision=_required_int(mapping["result_revision"], "result_revision"),
        result_sha256=_required_str(mapping["result_sha256"], "result_sha256"),
    )


def _proficiency_result_reference_to_dict(
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


def _scale_reference_from_dict(data: object) -> ProficiencyScaleReference:
    mapping = _exact_mapping(
        data,
        frozenset({"class_id", "scale_id", "scale_revision", "scale_sha256"}),
        "proficiency-scale reference",
    )
    return ProficiencyScaleReference(
        class_id=_required_str(mapping["class_id"], "class_id"),
        scale_id=_required_str(mapping["scale_id"], "scale_id"),
        scale_revision=_required_int(mapping["scale_revision"], "scale_revision"),
        scale_sha256=_required_str(mapping["scale_sha256"], "scale_sha256"),
    )


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _activation_reference_from_dict(data: object) -> GradePolicyActivationReference:
    try:
        return grade_policy_activation_reference_from_dict(data)
    except ValueError as error:
        raise StandardsGradeResultSerializationError(str(error)) from error


def _policy_reference_from_dict(data: object) -> GradePolicyReference:
    try:
        return grade_policy_reference_from_dict(data)
    except ValueError as error:
        raise StandardsGradeResultSerializationError(str(error)) from error


def _period_from_dict(data: object) -> AcademicPeriodRef:
    try:
        return academic_period_ref_from_dict(data)
    except (AcademicPeriodValidationError, ValueError, TypeError) as error:
        raise StandardsGradeResultSerializationError(str(error)) from error


def _period(value: AcademicPeriodRef) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise StandardsGradeResultValidationError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise StandardsGradeResultValidationError(str(error)) from error


def _staleness_reasons(value: object) -> tuple[StandardsGradeStalenessReason, ...]:
    if isinstance(value, (str, bytes)):
        raise StandardsGradeResultValidationError(
            "staleness reasons must be an iterable."
        )
    try:
        raw = tuple(cast(tuple[object, ...], value))
    except TypeError as error:
        raise StandardsGradeResultValidationError(
            "staleness reasons must be an iterable."
        ) from error
    if any(
        not isinstance(reason, str) or reason not in _STALENESS_REASON_SET
        for reason in raw
    ):
        raise StandardsGradeResultValidationError(
            "staleness reason is not supported."
        )
    if len(set(raw)) != len(raw):
        raise StandardsGradeResultValidationError(
            "staleness reasons must not contain duplicates."
        )
    raw_strings = cast(tuple[str, ...], raw)
    ordered = tuple(
        reason for reason in _STALENESS_REASON_ORDER if reason in raw_strings
    )
    return ordered


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
        raise StandardsGradeResultSerializationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise StandardsGradeResultSerializationError(f"{label} must be bytes.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StandardsGradeResultSerializationError(
            f"{label} must be valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except StandardsGradeResultSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise StandardsGradeResultSerializationError(
            f"{label} must be valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StandardsGradeResultSerializationError(
                f"duplicate JSON object key: {key}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StandardsGradeResultSerializationError(
        f"non-standard JSON numeric constant is not allowed: {value}."
    )


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise StandardsGradeResultSerializationError(f"{label} must be an object.")
    if any(not isinstance(key, str) for key in value):
        raise StandardsGradeResultSerializationError(
            f"{label} keys must be strings."
        )
    mapping = dict(cast(Mapping[str, object], value))
    actual = frozenset(mapping)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise StandardsGradeResultSerializationError(
            f"{label} does not use the exact schema; missing={missing}, "
            f"unknown={unknown}."
        )
    return mapping


def _required_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, field_name)


def _required_int(value: object, field_name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be an integer."
        )
    if value < 0 if allow_zero else value <= 0:
        qualifier = "nonnegative" if allow_zero else "positive"
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be {qualifier}."
        )
    return value


def _optional_int(
    value: object,
    field_name: str,
    *,
    allow_zero: bool = False,
) -> int | None:
    if value is None:
        return None
    return _required_int(value, field_name, allow_zero=allow_zero)


def _required_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be canonical Decimal text."
        )
    try:
        decimal_value = Decimal(value)
    except InvalidOperation as error:
        raise StandardsGradeResultSerializationError(
            f"{field_name} is not valid Decimal text."
        ) from error
    if not decimal_value.is_finite() or _decimal_text(decimal_value) != value:
        raise StandardsGradeResultSerializationError(
            f"{field_name} is not canonical finite Decimal text."
        )
    return decimal_value


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _required_decimal(value, field_name)


def _decimal_text(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise StandardsGradeResultValidationError(
            "Decimal value must be exact and finite."
        )
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    values = _required_list(value, field_name)
    if any(not isinstance(item, str) for item in values):
        raise StandardsGradeResultSerializationError(
            f"{field_name} must contain strings only."
        )
    return tuple(cast(list[str], values))


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardsGradeResultValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardsGradeResultValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StandardsGradeResultValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardsGradeResultValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StandardsGradeResultValidationError(
            f"{field_name} must be nonblank text without surrounding whitespace."
        )
    if len(value) > maximum or any(character in value for character in "\n\r\x00"):
        raise StandardsGradeResultValidationError(f"{field_name} is invalid.")
    return value


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StandardsGradeResultValidationError(
            f"{field_name} must be timezone-aware datetime."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _required_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise StandardsGradeResultSerializationError(
            f"{field_name} must be ISO-8601 datetime text."
        ) from error
    if parsed.tzinfo is None:
        raise StandardsGradeResultSerializationError(
            f"{field_name} must include timezone information."
        )
    return parsed


__all__ = [
    "STANDARDS_GRADE_RESULT_RECORD_TYPE",
    "STANDARDS_GRADE_RESULT_SCHEMA_VERSION",
    "StandardsGradeFreshnessStatus",
    "StandardsGradeResultFreshness",
    "StandardsGradeResultReference",
    "StandardsGradeResultSerializationError",
    "StandardsGradeResultSnapshot",
    "StandardsGradeResultValidationError",
    "StandardsGradeStalenessReason",
    "assess_standards_grade_result_freshness",
    "create_standards_grade_result_snapshot",
    "standards_grade_calculation_input_from_dict",
    "standards_grade_calculation_input_from_json_bytes",
    "standards_grade_calculation_outcome_from_dict",
    "standards_grade_calculation_outcome_from_json_bytes",
    "standards_grade_calculation_outcome_to_dict",
    "standards_grade_calculation_outcome_to_json_bytes",
    "standards_grade_result_reference",
    "standards_grade_result_reference_from_dict",
    "standards_grade_result_reference_to_dict",
    "standards_grade_result_snapshot_from_dict",
    "standards_grade_result_snapshot_from_json_bytes",
    "standards_grade_result_snapshot_to_dict",
    "standards_grade_result_snapshot_to_json_bytes",
    "validate_standards_grade_result_transition",
]
