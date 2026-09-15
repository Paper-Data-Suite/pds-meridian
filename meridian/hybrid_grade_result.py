"""Immutable result contract and freshness for bounded hybrid Grade calculation.

A hybrid Grade result is advisory Meridian calculation history. It is not a
teacher override, Grade preview presentation, ReportingSnapshot, export, or
official Grade.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    academic_period_ref_to_dict,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.conventional_grade import (
    CONVENTIONAL_GRADE_ALGORITHM_VERSION,
    ConventionalGradeSerializationError,
    ConventionalGradeValidationError,
    conventional_grade_calculation_input_from_dict,
    conventional_grade_calculation_input_to_dict,
)
from meridian.grade_policy import (
    GradePolicyReference,
    GradePolicyValidationError,
    HybridGradeConfiguration,
    grade_policy_reference_to_dict,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationReference,
    grade_policy_activation_reference_to_dict,
)
from meridian.hybrid_grade import (
    HYBRID_GRADE_ALGORITHM_VERSION,
    HybridGradeCalculationInput,
    HybridGradeCalculationOutcome,
    HybridGradeValidationError,
    calculate_hybrid_grade,
    hybrid_grade_calculation_input_sha256,
    hybrid_grade_calculation_input_to_dict,
    hybrid_grade_calculation_outcome_to_dict,
)
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    standards_grade_calculation_input_to_dict,
)
from meridian.standards_grade_result import (
    StandardsGradeResultSerializationError,
    StandardsGradeResultValidationError,
    standards_grade_calculation_input_from_dict,
)

HYBRID_GRADE_RESULT_SCHEMA_VERSION: Final[str] = "1"
HYBRID_GRADE_RESULT_RECORD_TYPE: Final[str] = "meridian_hybrid_grade_result"

HybridGradeFreshnessStatus: TypeAlias = Literal["current", "stale"]
HybridGradeStalenessReason: TypeAlias = Literal[
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "conventional_inputs_changed",
    "proficiency_results_changed",
    "algorithm_changed",
]

_STALENESS_REASON_ORDER: Final[tuple[HybridGradeStalenessReason, ...]] = (
    "calendar_scope_changed",
    "activation_changed",
    "policy_changed",
    "conventional_inputs_changed",
    "proficiency_results_changed",
    "algorithm_changed",
)
_STALENESS_REASON_SET: Final[frozenset[str]] = frozenset(_STALENESS_REASON_ORDER)
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
        "conventional",
        "standards_based",
    }
)
_CONFIGURATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "conventional",
        "standards_based",
        "conventional_weight",
        "standards_weight",
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


class HybridGradeResultError(ValueError):
    """Base error for immutable hybrid Grade result contracts."""


class HybridGradeResultValidationError(HybridGradeResultError):
    """Raised when result data violates the exact immutable contract."""


class HybridGradeResultSerializationError(HybridGradeResultError):
    """Raised when canonical hybrid Grade result JSON is invalid."""


@dataclass(frozen=True, slots=True)
class HybridGradeResultSnapshot:
    """Immutable persisted wrapper around one exact hybrid calculation."""

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
    inputs: HybridGradeCalculationInput
    inputs_sha256: str
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    outcome: HybridGradeCalculationOutcome
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != HYBRID_GRADE_RESULT_SCHEMA_VERSION:
            raise HybridGradeResultValidationError(
                "unsupported hybrid Grade result schema_version."
            )
        if self.record_type != HYBRID_GRADE_RESULT_RECORD_TYPE:
            raise HybridGradeResultValidationError(
                "record_type must identify a hybrid Grade result."
            )
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise HybridGradeResultValidationError(
                "target_period must be AcademicPeriodRef."
            )
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        revision = _positive_int(self.result_revision, "result_revision")
        supersedes = self.supersedes_revision
        if supersedes is not None:
            supersedes = _positive_int(supersedes, "supersedes_revision")
        if revision == 1 and supersedes is not None:
            raise HybridGradeResultValidationError(
                "result revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise HybridGradeResultValidationError(
                "result supersedes_revision must identify the prior revision."
            )
        if self.algorithm_version != HYBRID_GRADE_ALGORITHM_VERSION:
            raise HybridGradeResultValidationError(
                "unsupported hybrid Grade result algorithm_version."
            )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        if not isinstance(self.inputs, HybridGradeCalculationInput):
            raise HybridGradeResultValidationError(
                "inputs must be HybridGradeCalculationInput."
            )
        inputs_sha256 = _sha256(self.inputs_sha256, "inputs_sha256")
        if inputs_sha256 != hybrid_grade_calculation_input_sha256(self.inputs):
            raise HybridGradeResultValidationError(
                "inputs_sha256 must match the exact embedded hybrid inputs."
            )
        if (
            self.inputs.class_id != class_id
            or self.inputs.student_id != student_id
            or self.inputs.target_period != self.target_period
            or self.inputs.calendar_revision != calendar_revision
        ):
            raise HybridGradeResultValidationError(
                "result scope must match exact embedded hybrid inputs."
            )
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise HybridGradeResultValidationError(
                "activation_reference must be exact activation provenance."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise HybridGradeResultValidationError(
                "policy_reference must be exact Grade-policy provenance."
            )
        if self.activation_reference != self.inputs.activation_reference:
            raise HybridGradeResultValidationError(
                "result activation_reference must match embedded inputs."
            )
        if self.policy_reference != self.inputs.policy_reference:
            raise HybridGradeResultValidationError(
                "result policy_reference must match embedded inputs."
            )
        if not isinstance(self.outcome, HybridGradeCalculationOutcome):
            raise HybridGradeResultValidationError(
                "outcome must be HybridGradeCalculationOutcome."
            )
        exact_outcome = calculate_hybrid_grade(self.inputs)
        if self.outcome != exact_outcome:
            raise HybridGradeResultValidationError(
                "persisted outcome must exactly reproduce from embedded inputs."
            )
        if (
            self.outcome.algorithm_version != self.algorithm_version
            or self.outcome.calculation_fingerprint != fingerprint
            or self.outcome.activation_reference != self.activation_reference
            or self.outcome.policy_reference != self.policy_reference
        ):
            raise HybridGradeResultValidationError(
                "result metadata must match the exact pure hybrid outcome."
            )
        calculated_at = _aware_utc(self.calculated_at, "calculated_at")
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "result_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)
        object.__setattr__(self, "inputs_sha256", inputs_sha256)
        object.__setattr__(self, "calculated_at", calculated_at)


@dataclass(frozen=True, slots=True)
class HybridGradeResultReference:
    """Exact immutable hybrid Grade result revision and digest."""

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
class HybridGradeResultFreshness:
    """Pure diagnostic comparison to explicit current hybrid Grade state."""

    status: HybridGradeFreshnessStatus
    reasons: tuple[HybridGradeStalenessReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale"}:
            raise HybridGradeResultValidationError(
                "unsupported hybrid Grade freshness status."
            )
        reasons = _staleness_reasons(self.reasons)
        if self.status == "current" and reasons:
            raise HybridGradeResultValidationError(
                "current freshness status requires no staleness reasons."
            )
        if self.status == "stale" and not reasons:
            raise HybridGradeResultValidationError(
                "stale freshness status requires at least one reason."
            )
        object.__setattr__(self, "reasons", reasons)


def create_hybrid_grade_result_snapshot(
    inputs: HybridGradeCalculationInput,
    outcome: HybridGradeCalculationOutcome,
    *,
    result_revision: int,
    calculated_at: datetime,
) -> HybridGradeResultSnapshot:
    """Wrap one pure hybrid calculation in immutable result metadata."""

    if not isinstance(inputs, HybridGradeCalculationInput):
        raise HybridGradeResultValidationError(
            "inputs must be HybridGradeCalculationInput."
        )
    if not isinstance(outcome, HybridGradeCalculationOutcome):
        raise HybridGradeResultValidationError(
            "outcome must be HybridGradeCalculationOutcome."
        )
    revision = _positive_int(result_revision, "result_revision")
    return HybridGradeResultSnapshot(
        schema_version=HYBRID_GRADE_RESULT_SCHEMA_VERSION,
        record_type=HYBRID_GRADE_RESULT_RECORD_TYPE,
        class_id=inputs.class_id,
        student_id=inputs.student_id,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=hybrid_grade_calculation_input_sha256(inputs),
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        outcome=outcome,
        calculated_at=calculated_at,
    )


def validate_hybrid_grade_result_transition(
    previous: HybridGradeResultSnapshot,
    current: HybridGradeResultSnapshot,
) -> HybridGradeResultSnapshot:
    """Validate contiguous immutable history for one exact hybrid result family."""

    if not isinstance(previous, HybridGradeResultSnapshot):
        raise HybridGradeResultValidationError(
            "previous must be HybridGradeResultSnapshot."
        )
    if not isinstance(current, HybridGradeResultSnapshot):
        raise HybridGradeResultValidationError(
            "current must be HybridGradeResultSnapshot."
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
        raise HybridGradeResultValidationError(
            "hybrid Grade result logical identity cannot change."
        )
    if current.result_revision != previous.result_revision + 1:
        raise HybridGradeResultValidationError(
            "hybrid Grade result revisions must be contiguous."
        )
    if current.supersedes_revision != previous.result_revision:
        raise HybridGradeResultValidationError(
            "hybrid Grade result must supersede the immediately prior revision."
        )
    if current.calculated_at < previous.calculated_at:
        raise HybridGradeResultValidationError(
            "result calculated_at must be nondecreasing."
        )
    return current


def assess_hybrid_grade_result_freshness(
    result: HybridGradeResultSnapshot,
    current_inputs: HybridGradeCalculationInput,
    *,
    hybrid_algorithm_version: str = HYBRID_GRADE_ALGORITHM_VERSION,
    conventional_algorithm_version: str = CONVENTIONAL_GRADE_ALGORITHM_VERSION,
    standards_algorithm_version: str = STANDARDS_GRADE_ALGORITHM_VERSION,
) -> HybridGradeResultFreshness:
    """Purely compare one stored result with one explicit current hybrid basis."""

    if not isinstance(result, HybridGradeResultSnapshot):
        raise HybridGradeResultValidationError(
            "result must be HybridGradeResultSnapshot."
        )
    if not isinstance(current_inputs, HybridGradeCalculationInput):
        raise HybridGradeResultValidationError(
            "current_inputs must be HybridGradeCalculationInput."
        )
    if (
        current_inputs.class_id != result.class_id
        or current_inputs.student_id != result.student_id
    ):
        raise HybridGradeResultValidationError(
            "freshness comparison must preserve class/student identity."
        )
    current_hybrid_algorithm = _bounded_text(
        hybrid_algorithm_version,
        "hybrid_algorithm_version",
        256,
    )
    current_conventional_algorithm = _bounded_text(
        conventional_algorithm_version,
        "conventional_algorithm_version",
        256,
    )
    current_standards_algorithm = _bounded_text(
        standards_algorithm_version,
        "standards_algorithm_version",
        256,
    )

    reasons: list[HybridGradeStalenessReason] = []
    if (
        current_inputs.target_period != result.target_period
        or current_inputs.calendar_revision != result.calendar_revision
    ):
        reasons.append("calendar_scope_changed")
    if current_inputs.activation_reference != result.activation_reference:
        reasons.append("activation_changed")
    if current_inputs.policy_reference != result.policy_reference:
        reasons.append("policy_changed")

    same_authority = (
        current_inputs.activation_reference == result.activation_reference
        and current_inputs.policy_reference == result.policy_reference
    )
    if same_authority:
        if _conventional_basis_sha256(current_inputs) != _conventional_basis_sha256(
            result.inputs
        ):
            reasons.append("conventional_inputs_changed")
        if _proficiency_basis_sha256(current_inputs) != _proficiency_basis_sha256(
            result.inputs
        ):
            reasons.append("proficiency_results_changed")

    if (
        current_hybrid_algorithm != result.algorithm_version
        or current_conventional_algorithm
        != result.outcome.conventional_component.component_algorithm_version
        or current_standards_algorithm
        != result.outcome.standards_component.component_algorithm_version
    ):
        reasons.append("algorithm_changed")

    return HybridGradeResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def hybrid_grade_result_snapshot_to_dict(
    value: HybridGradeResultSnapshot,
) -> dict[str, object]:
    if not isinstance(value, HybridGradeResultSnapshot):
        raise HybridGradeResultSerializationError(
            "value must be HybridGradeResultSnapshot."
        )
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
        "inputs": hybrid_grade_calculation_input_to_dict(value.inputs),
        "inputs_sha256": value.inputs_sha256,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "outcome": hybrid_grade_calculation_outcome_to_dict(value.outcome),
        "calculated_at": value.calculated_at.isoformat(),
    }


def hybrid_grade_result_snapshot_to_json_bytes(
    value: HybridGradeResultSnapshot,
) -> bytes:
    return _canonical_json_bytes(hybrid_grade_result_snapshot_to_dict(value))


def hybrid_grade_result_snapshot_from_dict(
    data: object,
) -> HybridGradeResultSnapshot:
    mapping = _exact_mapping(data, _RESULT_KEYS, "hybrid Grade result snapshot")
    inputs = hybrid_grade_calculation_input_from_dict(mapping["inputs"])
    exact_outcome = calculate_hybrid_grade(inputs)
    if mapping["outcome"] != hybrid_grade_calculation_outcome_to_dict(exact_outcome):
        raise HybridGradeResultSerializationError(
            "stored hybrid outcome does not exactly reproduce from embedded inputs."
        )
    expected_activation = grade_policy_activation_reference_to_dict(
        inputs.activation_reference
    )
    expected_policy = grade_policy_reference_to_dict(inputs.policy_reference)
    if mapping["activation_reference"] != expected_activation:
        raise HybridGradeResultSerializationError(
            "stored activation_reference does not match embedded inputs."
        )
    if mapping["policy_reference"] != expected_policy:
        raise HybridGradeResultSerializationError(
            "stored policy_reference does not match embedded inputs."
        )
    value = HybridGradeResultSnapshot(
        schema_version=_required_str(mapping["schema_version"], "schema_version"),
        record_type=_required_str(mapping["record_type"], "record_type"),
        class_id=_required_str(mapping["class_id"], "class_id"),
        student_id=_required_str(mapping["student_id"], "student_id"),
        target_period=inputs.target_period,
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
        inputs=inputs,
        inputs_sha256=_required_str(mapping["inputs_sha256"], "inputs_sha256"),
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        outcome=exact_outcome,
        calculated_at=_datetime_from_text(mapping["calculated_at"], "calculated_at"),
    )
    if hybrid_grade_result_snapshot_to_dict(value) != mapping:
        raise HybridGradeResultSerializationError(
            "hybrid Grade result snapshot fields are not exactly self-consistent."
        )
    return value


def hybrid_grade_result_snapshot_from_json_bytes(
    data: bytes,
) -> HybridGradeResultSnapshot:
    decoded = _decode_json(data, "hybrid Grade result snapshot")
    try:
        value = hybrid_grade_result_snapshot_from_dict(decoded)
    except HybridGradeResultError:
        raise
    except (
        ConventionalGradeSerializationError,
        ConventionalGradeValidationError,
        StandardsGradeResultSerializationError,
        StandardsGradeResultValidationError,
        GradePolicyValidationError,
        HybridGradeValidationError,
        InvalidOperation,
        ValueError,
        TypeError,
    ) as error:
        raise HybridGradeResultSerializationError(
            f"invalid nested hybrid Grade result data: {error}"
        ) from error
    if hybrid_grade_result_snapshot_to_json_bytes(value) != data:
        raise HybridGradeResultSerializationError(
            "hybrid Grade result snapshot is not canonical JSON."
        )
    return value


def hybrid_grade_result_reference_to_dict(
    value: HybridGradeResultReference,
) -> dict[str, object]:
    if not isinstance(value, HybridGradeResultReference):
        raise HybridGradeResultSerializationError(
            "value must be HybridGradeResultReference."
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


def hybrid_grade_result_reference_from_dict(
    data: object,
) -> HybridGradeResultReference:
    mapping = _exact_mapping(
        data,
        _RESULT_REFERENCE_KEYS,
        "hybrid Grade result reference",
    )
    return HybridGradeResultReference(
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


def hybrid_grade_calculation_input_from_dict(
    data: object,
) -> HybridGradeCalculationInput:
    """Parse one exact hybrid input using the canonical component parsers."""

    mapping = _exact_mapping(data, _INPUT_KEYS, "hybrid Grade calculation input")
    try:
        conventional = conventional_grade_calculation_input_from_dict(
            mapping["conventional"]
        )
        standards = standards_grade_calculation_input_from_dict(
            mapping["standards_based"]
        )
        config_mapping = _exact_mapping(
            mapping["configuration"],
            _CONFIGURATION_KEYS,
            "hybrid configuration",
        )
        configuration = HybridGradeConfiguration(
            conventional=conventional.configuration,
            standards_based=standards.configuration,
            conventional_weight=_decimal_from_text(
                config_mapping["conventional_weight"], "conventional_weight"
            ),
            standards_weight=_decimal_from_text(
                config_mapping["standards_weight"], "standards_weight"
            ),
        )
        value = HybridGradeCalculationInput(
            class_id=conventional.class_id,
            student_id=conventional.student_id,
            target_period=conventional.target_period,
            calendar_revision=conventional.calendar_revision,
            activation_reference=conventional.activation_reference,
            policy_reference=conventional.policy_reference,
            configuration=configuration,
            state_treatment=conventional.state_treatment,
            rounding=conventional.rounding,
            conventional=conventional,
            standards_based=standards,
        )
    except (
        ConventionalGradeSerializationError,
        ConventionalGradeValidationError,
        StandardsGradeResultSerializationError,
        StandardsGradeResultValidationError,
        GradePolicyValidationError,
        HybridGradeValidationError,
        InvalidOperation,
        ValueError,
        TypeError,
    ) as error:
        raise HybridGradeResultSerializationError(
            f"invalid hybrid Grade calculation input: {error}"
        ) from error
    if hybrid_grade_calculation_input_to_dict(value) != mapping:
        raise HybridGradeResultSerializationError(
            "hybrid Grade calculation input fields are not exactly self-consistent."
        )
    return value


def hybrid_grade_calculation_input_from_json_bytes(
    data: bytes,
) -> HybridGradeCalculationInput:
    decoded = _decode_json(data, "hybrid Grade calculation input")
    value = hybrid_grade_calculation_input_from_dict(decoded)
    if _canonical_json_bytes(hybrid_grade_calculation_input_to_dict(value)) != data:
        raise HybridGradeResultSerializationError(
            "hybrid Grade calculation input is not canonical JSON."
        )
    return value


def _conventional_basis_sha256(value: HybridGradeCalculationInput) -> str:
    component = conventional_grade_calculation_input_to_dict(value.conventional)
    return hashlib.sha256(_canonical_json_bytes(component["items"])).hexdigest()


def _proficiency_basis_sha256(value: HybridGradeCalculationInput) -> str:
    component = standards_grade_calculation_input_to_dict(value.standards_based)
    return hashlib.sha256(_canonical_json_bytes(component["standards"])).hexdigest()


def _staleness_reasons(value: object) -> tuple[HybridGradeStalenessReason, ...]:
    if isinstance(value, (str, bytes)):
        raise HybridGradeResultValidationError(
            "freshness reasons must be an iterable of reason strings."
        )
    try:
        raw = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise HybridGradeResultValidationError(
            "freshness reasons must be iterable."
        ) from error
    if any(not isinstance(item, str) for item in raw):
        raise HybridGradeResultValidationError(
            "freshness reasons must contain only strings."
        )
    if any(item not in _STALENESS_REASON_SET for item in raw):
        raise HybridGradeResultValidationError(
            "freshness reasons contain an unsupported reason."
        )
    if len(set(raw)) != len(raw):
        raise HybridGradeResultValidationError(
            "freshness reasons must not contain duplicates."
        )
    present = set(cast(tuple[str, ...], raw))
    return tuple(reason for reason in _STALENESS_REASON_ORDER if reason in present)


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    field_name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise HybridGradeResultSerializationError(
            f"{field_name} must be an object."
        )
    mapping = dict(value)
    if frozenset(mapping) != keys:
        raise HybridGradeResultSerializationError(
            f"{field_name} does not use the exact schema."
        )
    return cast(dict[str, object], mapping)


def _decode_json(data: bytes, field_name: str) -> object:
    if type(data) is not bytes:
        raise HybridGradeResultSerializationError(
            f"{field_name} must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HybridGradeResultSerializationError(
            f"{field_name} must be valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except HybridGradeResultSerializationError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise HybridGradeResultSerializationError(
            f"{field_name} must be valid JSON."
        ) from error


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise HybridGradeResultSerializationError(
                f"JSON object contains duplicate key: {key}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise HybridGradeResultSerializationError(
        f"JSON contains invalid constant: {value}."
    )


def _required_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise HybridGradeResultSerializationError(
            f"{field_name} must be a string."
        )
    return value


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HybridGradeResultSerializationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, field_name)


def _decimal_from_text(value: object, field_name: str) -> Decimal:
    text = _required_str(value, field_name)
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise HybridGradeResultSerializationError(
            f"{field_name} must contain a Decimal string."
        ) from error
    if not result.is_finite():
        raise HybridGradeResultSerializationError(
            f"{field_name} must contain a finite Decimal."
        )
    return result


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _required_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise HybridGradeResultSerializationError(
            f"{field_name} must contain an ISO-8601 datetime."
        ) from error
    return _aware_utc(parsed, field_name)


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HybridGradeResultValidationError(
            f"{field_name} must be timezone-aware."
        )
    offset = value.utcoffset()
    if offset != timedelta(0):
        raise HybridGradeResultValidationError(
            f"{field_name} must use UTC offset +00:00."
        )
    return value.astimezone(UTC)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise HybridGradeResultValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise HybridGradeResultValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridGradeResultValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HybridGradeResultValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise HybridGradeResultValidationError(
            f"{field_name} must be a non-empty string of at most {maximum} characters."
        )
    return value


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
        raise HybridGradeResultSerializationError(
            "value cannot be encoded as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


__all__ = [
    "HYBRID_GRADE_RESULT_RECORD_TYPE",
    "HYBRID_GRADE_RESULT_SCHEMA_VERSION",
    "HybridGradeFreshnessStatus",
    "HybridGradeResultError",
    "HybridGradeResultFreshness",
    "HybridGradeResultReference",
    "HybridGradeResultSerializationError",
    "HybridGradeResultSnapshot",
    "HybridGradeResultValidationError",
    "HybridGradeStalenessReason",
    "assess_hybrid_grade_result_freshness",
    "create_hybrid_grade_result_snapshot",
    "hybrid_grade_calculation_input_from_dict",
    "hybrid_grade_calculation_input_from_json_bytes",
    "hybrid_grade_result_reference_from_dict",
    "hybrid_grade_result_reference_to_dict",
    "hybrid_grade_result_snapshot_from_dict",
    "hybrid_grade_result_snapshot_from_json_bytes",
    "hybrid_grade_result_snapshot_to_dict",
    "hybrid_grade_result_snapshot_to_json_bytes",
    "validate_hybrid_grade_result_transition",
]
