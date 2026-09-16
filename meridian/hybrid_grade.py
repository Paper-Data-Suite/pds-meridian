"""Pure bounded hybrid Grade calculation for Meridian v0.3.

The hybrid layer composes one exact conventional component and one exact
standards-based component under one activated ``hybrid`` Grade-policy revision.
It does not select Grade policies or activations, discover evidence, recalculate
proficiency, apply overrides, create previews or ReportingSnapshots, or write an
official Grade.
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

from meridian.conventional_grade import (
    CONVENTIONAL_GRADE_ALGORITHM_VERSION,
    ConventionalGradeCalculationInput,
    ConventionalGradeCalculationOutcome,
    calculate_conventional_grade,
    conventional_grade_calculation_input_to_dict,
)
from meridian.grade_policy import (
    GradePolicyReference,
    GradePolicyRevision,
    GradeRoundingPolicy,
    GradeStateTreatment,
    HybridGradeConfiguration,
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
from meridian.standards_grade import (
    STANDARDS_GRADE_ALGORITHM_VERSION,
    StandardsGradeCalculationInput,
    StandardsGradeCalculationOutcome,
    calculate_standards_grade,
    standards_grade_calculation_input_to_dict,
)

HYBRID_GRADE_ALGORITHM_VERSION: Final[str] = "1"

HybridGradeComponentKind: TypeAlias = Literal["conventional", "standards_based"]
HybridGradeComponentSourceStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "insufficient",
]
HybridGradeComponentAction: TypeAlias = Literal[
    "contribute",
    "exclude",
    "blocking",
]
HybridGradeCalculationStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "insufficient",
]

_COMPONENT_KINDS: Final[frozenset[str]] = frozenset(
    {"conventional", "standards_based"}
)
_COMPONENT_STATUSES: Final[frozenset[str]] = frozenset(
    {"calculated", "blocked", "insufficient"}
)
_COMPONENT_ACTIONS: Final[frozenset[str]] = frozenset(
    {"contribute", "exclude", "blocking"}
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


class HybridGradeError(ValueError):
    """Base error for bounded hybrid Grade calculation contracts."""


class HybridGradeValidationError(HybridGradeError):
    """Raised when the exact hybrid calculation basis violates the contract."""


@dataclass(frozen=True, slots=True)
class HybridGradeCalculationInput:
    """Complete immutable pure basis for one hybrid Academic Period Grade."""

    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    configuration: HybridGradeConfiguration
    state_treatment: GradeStateTreatment
    rounding: GradeRoundingPolicy
    conventional: ConventionalGradeCalculationInput
    standards_based: StandardsGradeCalculationInput

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        student_id = _identifier(self.student_id, "student_id")
        period = _academic_period_ref(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        if not isinstance(
            self.activation_reference,
            GradePolicyActivationReference,
        ):
            raise HybridGradeValidationError(
                "activation_reference must be GradePolicyActivationReference."
            )
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise HybridGradeValidationError(
                "policy_reference must be GradePolicyReference."
            )
        if not isinstance(self.configuration, HybridGradeConfiguration):
            raise HybridGradeValidationError(
                "configuration must be HybridGradeConfiguration."
            )
        if not isinstance(self.state_treatment, GradeStateTreatment):
            raise HybridGradeValidationError(
                "state_treatment must be GradeStateTreatment."
            )
        if not isinstance(self.rounding, GradeRoundingPolicy):
            raise HybridGradeValidationError(
                "rounding must be GradeRoundingPolicy."
            )
        if not isinstance(self.conventional, ConventionalGradeCalculationInput):
            raise HybridGradeValidationError(
                "conventional must be ConventionalGradeCalculationInput."
            )
        if not isinstance(self.standards_based, StandardsGradeCalculationInput):
            raise HybridGradeValidationError(
                "standards_based must be StandardsGradeCalculationInput."
            )

        activation = self.activation_reference
        if (
            activation.class_id != class_id
            or activation.school_year != period.school_year
            or activation.period_id != period.period_id
        ):
            raise HybridGradeValidationError(
                "activation_reference must match the exact hybrid class and period."
            )
        if self.policy_reference.class_id != class_id:
            raise HybridGradeValidationError(
                "policy_reference.class_id must match hybrid class_id."
            )

        for name, component in (
            ("conventional", self.conventional),
            ("standards_based", self.standards_based),
        ):
            if (
                component.class_id != class_id
                or component.student_id != student_id
                or component.target_period != period
                or component.calendar_revision != calendar_revision
            ):
                raise HybridGradeValidationError(
                    f"{name} component must match the exact hybrid scope."
                )
            if component.activation_reference != activation:
                raise HybridGradeValidationError(
                    f"{name} component must use the exact hybrid activation."
                )
            if component.policy_reference != self.policy_reference:
                raise HybridGradeValidationError(
                    f"{name} component must use the exact hybrid Grade policy."
                )
            if component.state_treatment != self.state_treatment:
                raise HybridGradeValidationError(
                    f"{name} component must use the hybrid state treatment."
                )
            if component.rounding != self.rounding:
                raise HybridGradeValidationError(
                    f"{name} component must use the hybrid rounding policy."
                )

        if self.conventional.configuration != self.configuration.conventional:
            raise HybridGradeValidationError(
                "conventional component configuration must exactly match the "
                "hybrid policy."
            )
        if (
            self.standards_based.configuration
            != self.configuration.standards_based
        ):
            raise HybridGradeValidationError(
                "standards component configuration must exactly match the "
                "hybrid policy."
            )

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)


@dataclass(frozen=True, slots=True)
class HybridGradeComponentResult:
    """One exact bounded component after hybrid-level state handling."""

    component_kind: HybridGradeComponentKind
    configured_weight: Decimal
    source_status: HybridGradeComponentSourceStatus
    action: HybridGradeComponentAction
    component_algorithm_version: str
    component_calculation_fingerprint: str
    unrounded_grade: Decimal | None
    weighted_contribution: Decimal | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.component_kind not in _COMPONENT_KINDS:
            raise HybridGradeValidationError("unsupported hybrid component kind.")
        object.__setattr__(
            self,
            "configured_weight",
            _positive_decimal(self.configured_weight, "configured_weight"),
        )
        if self.source_status not in _COMPONENT_STATUSES:
            raise HybridGradeValidationError("unsupported component source_status.")
        if self.action not in _COMPONENT_ACTIONS:
            raise HybridGradeValidationError("unsupported hybrid component action.")
        object.__setattr__(
            self,
            "component_algorithm_version",
            _bounded_text(
                self.component_algorithm_version,
                "component_algorithm_version",
                256,
            ),
        )
        object.__setattr__(
            self,
            "component_calculation_fingerprint",
            _sha256(
                self.component_calculation_fingerprint,
                "component_calculation_fingerprint",
            ),
        )
        if self.unrounded_grade is not None:
            _finite_decimal(self.unrounded_grade, "unrounded_grade")
        if self.weighted_contribution is not None:
            _finite_decimal(
                self.weighted_contribution,
                "weighted_contribution",
            )
        reasons = _reason_codes(self.reason_codes)

        if self.source_status == "calculated":
            if (
                self.action != "contribute"
                or self.unrounded_grade is None
                or self.weighted_contribution is None
            ):
                raise HybridGradeValidationError(
                    "calculated component requires one exact numeric contribution."
                )
        elif self.source_status == "blocked":
            if (
                self.action != "blocking"
                or self.unrounded_grade is not None
                or self.weighted_contribution is not None
            ):
                raise HybridGradeValidationError(
                    "blocked component must remain nonnumeric and blocking."
                )
        else:
            if self.action not in {"exclude", "blocking"}:
                raise HybridGradeValidationError(
                    "insufficient component must be excluded or blocking."
                )
            if (
                self.unrounded_grade is not None
                or self.weighted_contribution is not None
            ):
                raise HybridGradeValidationError(
                    "insufficient component must remain nonnumeric."
                )
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class HybridGradeReason:
    """One deterministic structured hybrid-result reason."""

    code: str
    component_kind: HybridGradeComponentKind | None = None

    def __post_init__(self) -> None:
        code = _reason_code(self.code)
        component = self.component_kind
        if component is not None and component not in _COMPONENT_KINDS:
            raise HybridGradeValidationError("unsupported reason component kind.")
        if code == "blocking_component" and component is None:
            raise HybridGradeValidationError(
                "blocking_component reason requires a component kind."
            )
        if code == "no_calculable_components" and component is not None:
            raise HybridGradeValidationError(
                "no_calculable_components reason must not identify one component."
            )
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class HybridGradeCalculationOutcome:
    """Pure advisory hybrid Grade calculation; never an official Grade."""

    status: HybridGradeCalculationStatus
    algorithm_version: str
    calculation_fingerprint: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    student_id: str
    conventional_component: HybridGradeComponentResult
    standards_component: HybridGradeComponentResult
    active_weight: Decimal | None
    weighted_numerator: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None
    reasons: tuple[HybridGradeReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise HybridGradeValidationError("unsupported hybrid calculation status.")
        if self.algorithm_version != HYBRID_GRADE_ALGORITHM_VERSION:
            raise HybridGradeValidationError(
                "unsupported hybrid Grade algorithm_version."
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
            raise HybridGradeValidationError("invalid activation_reference.")
        if not isinstance(self.policy_reference, GradePolicyReference):
            raise HybridGradeValidationError("invalid policy_reference.")
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        if not isinstance(
            self.conventional_component,
            HybridGradeComponentResult,
        ) or self.conventional_component.component_kind != "conventional":
            raise HybridGradeValidationError(
                "conventional_component must identify the conventional component."
            )
        if not isinstance(
            self.standards_component,
            HybridGradeComponentResult,
        ) or self.standards_component.component_kind != "standards_based":
            raise HybridGradeValidationError(
                "standards_component must identify the standards_based component."
            )
        if (
            self.conventional_component.configured_weight
            + self.standards_component.configured_weight
            != Decimal("1")
        ):
            raise HybridGradeValidationError(
                "hybrid component weights must sum exactly to one."
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
            raise HybridGradeValidationError(
                "active_weight must be positive when present."
            )
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, HybridGradeReason) for reason in reasons):
            raise HybridGradeValidationError(
                "reasons must contain only HybridGradeReason values."
            )

        components = (self.conventional_component, self.standards_component)
        blocking = tuple(item for item in components if item.action == "blocking")
        active = tuple(item for item in components if item.action == "contribute")
        if self.status == "calculated":
            if blocking or not active:
                raise HybridGradeValidationError(
                    "calculated hybrid outcome requires active, nonblocking components."
                )
            if any(
                value is None
                for value in (
                    self.active_weight,
                    self.weighted_numerator,
                    self.unrounded_grade,
                    self.rounded_grade,
                )
            ):
                raise HybridGradeValidationError(
                    "calculated hybrid outcome requires complete numeric values."
                )
            expected_weight = _sum_exact(
                item.configured_weight for item in active
            )
            expected_numerator = _sum_exact(
                item.weighted_contribution
                for item in active
                if item.weighted_contribution is not None
            )
            if self.active_weight != expected_weight:
                raise HybridGradeValidationError(
                    "active_weight must equal the exact active component weights."
                )
            if self.weighted_numerator != expected_numerator:
                raise HybridGradeValidationError(
                    "weighted_numerator must equal exact component contributions."
                )
            if reasons:
                raise HybridGradeValidationError(
                    "calculated hybrid outcome must not carry top-level reasons."
                )
        elif self.status == "blocked":
            if not blocking:
                raise HybridGradeValidationError(
                    "blocked hybrid outcome requires a blocking component."
                )
            if any(
                value is not None
                for value in (
                    self.active_weight,
                    self.weighted_numerator,
                    self.unrounded_grade,
                    self.rounded_grade,
                )
            ):
                raise HybridGradeValidationError(
                    "blocked hybrid outcome must not carry final numeric values."
                )
            expected_reasons = tuple(
                HybridGradeReason("blocking_component", item.component_kind)
                for item in blocking
            )
            if reasons != expected_reasons:
                raise HybridGradeValidationError(
                    "blocked hybrid reasons must identify every blocking component."
                )
        else:
            if blocking or active:
                raise HybridGradeValidationError(
                    "insufficient hybrid outcome requires no active/blocking component."
                )
            if any(
                value is not None
                for value in (
                    self.active_weight,
                    self.weighted_numerator,
                    self.unrounded_grade,
                    self.rounded_grade,
                )
            ):
                raise HybridGradeValidationError(
                    "insufficient hybrid outcome must not carry final numeric values."
                )
            if reasons != (HybridGradeReason("no_calculable_components"),):
                raise HybridGradeValidationError(
                    "insufficient hybrid outcome requires no_calculable_components."
                )
        object.__setattr__(self, "reasons", reasons)


def create_hybrid_grade_calculation_input(
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    conventional: ConventionalGradeCalculationInput,
    standards_based: StandardsGradeCalculationInput,
) -> HybridGradeCalculationInput:
    """Bind one exact activated hybrid policy to both exact component bases."""

    try:
        validated_policy = validate_grade_policy_revision(policy)
    except ValueError as error:
        raise HybridGradeValidationError(str(error)) from error
    try:
        validated_activation = validate_grade_policy_activation_decision(activation)
    except ValueError as error:
        raise HybridGradeValidationError(str(error)) from error
    if validated_policy.calculation_family != "hybrid" or not isinstance(
        validated_policy.configuration,
        HybridGradeConfiguration,
    ):
        raise HybridGradeValidationError(
            "hybrid calculation requires an exact hybrid Grade policy."
        )
    if validated_activation.decision != "activate":
        raise HybridGradeValidationError(
            "hybrid calculation requires an activated policy decision."
        )
    exact_policy_reference = grade_policy_reference(validated_policy)
    if validated_activation.policy_reference != exact_policy_reference:
        raise HybridGradeValidationError(
            "activation must reference the exact supplied hybrid Grade policy."
        )
    exact_period = _academic_period_ref(target_period)
    if (
        validated_activation.class_id != validated_policy.class_id
        or validated_activation.target_period != exact_period
        or validated_activation.calendar_revision != calendar_revision
    ):
        raise HybridGradeValidationError(
            "activation must match the exact hybrid class/period/calendar revision."
        )
    return HybridGradeCalculationInput(
        class_id=validated_policy.class_id,
        student_id=student_id,
        target_period=exact_period,
        calendar_revision=calendar_revision,
        activation_reference=grade_policy_activation_reference(validated_activation),
        policy_reference=exact_policy_reference,
        configuration=validated_policy.configuration,
        state_treatment=validated_policy.state_treatment,
        rounding=validated_policy.rounding,
        conventional=conventional,
        standards_based=standards_based,
    )


def hybrid_grade_calculation_input_to_dict(
    value: HybridGradeCalculationInput,
) -> dict[str, object]:
    """Serialize one exact hybrid calculation basis to JSON-native data."""

    if not isinstance(value, HybridGradeCalculationInput):
        raise HybridGradeValidationError(
            "value must be HybridGradeCalculationInput."
        )
    conventional = conventional_grade_calculation_input_to_dict(value.conventional)
    standards = standards_grade_calculation_input_to_dict(value.standards_based)
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
            "conventional": conventional["configuration"],
            "standards_based": standards["configuration"],
            "conventional_weight": _decimal_to_text(
                value.configuration.conventional_weight
            ),
            "standards_weight": _decimal_to_text(
                value.configuration.standards_weight
            ),
        },
        "state_treatment": conventional["state_treatment"],
        "rounding": conventional["rounding"],
        "conventional": conventional,
        "standards_based": standards,
    }


def hybrid_grade_calculation_input_to_json_bytes(
    value: HybridGradeCalculationInput,
) -> bytes:
    """Return canonical UTF-8 JSON bytes for one exact hybrid basis."""

    return _canonical_json_bytes(hybrid_grade_calculation_input_to_dict(value))


def hybrid_grade_calculation_input_sha256(
    value: HybridGradeCalculationInput,
) -> str:
    """Return SHA-256 over one exact canonical hybrid input basis."""

    return hashlib.sha256(
        hybrid_grade_calculation_input_to_json_bytes(value)
    ).hexdigest()


def hybrid_grade_calculation_fingerprint(
    inputs: HybridGradeCalculationInput,
) -> str:
    """Return a stable digest over hybrid authority and component algorithms."""

    if not isinstance(inputs, HybridGradeCalculationInput):
        raise HybridGradeValidationError(
            "inputs must be HybridGradeCalculationInput."
        )
    payload = {
        "algorithm_version": HYBRID_GRADE_ALGORITHM_VERSION,
        "component_algorithms": {
            "conventional": CONVENTIONAL_GRADE_ALGORITHM_VERSION,
            "standards_based": STANDARDS_GRADE_ALGORITHM_VERSION,
        },
        "basis": hybrid_grade_calculation_input_to_dict(inputs),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def calculate_hybrid_grade(
    inputs: HybridGradeCalculationInput,
) -> HybridGradeCalculationOutcome:
    """Purely calculate one bounded hybrid Academic Period Grade."""

    if not isinstance(inputs, HybridGradeCalculationInput):
        raise HybridGradeValidationError(
            "inputs must be HybridGradeCalculationInput."
        )
    fingerprint = hybrid_grade_calculation_fingerprint(inputs)
    conventional_outcome = calculate_conventional_grade(inputs.conventional)
    standards_outcome = calculate_standards_grade(inputs.standards_based)

    conventional_component = _component_result(
        "conventional",
        inputs.configuration.conventional_weight,
        conventional_outcome,
        inputs.state_treatment,
    )
    standards_component = _component_result(
        "standards_based",
        inputs.configuration.standards_weight,
        standards_outcome,
        inputs.state_treatment,
    )
    components = (conventional_component, standards_component)
    blocking = tuple(item for item in components if item.action == "blocking")
    if blocking:
        return _outcome(
            inputs,
            fingerprint,
            conventional_component,
            standards_component,
            status="blocked",
            active_weight=None,
            weighted_numerator=None,
            unrounded_grade=None,
            rounded_grade=None,
            reasons=tuple(
                HybridGradeReason("blocking_component", item.component_kind)
                for item in blocking
            ),
        )

    active = tuple(item for item in components if item.action == "contribute")
    if not active:
        return _outcome(
            inputs,
            fingerprint,
            conventional_component,
            standards_component,
            status="insufficient",
            active_weight=None,
            weighted_numerator=None,
            unrounded_grade=None,
            rounded_grade=None,
            reasons=(HybridGradeReason("no_calculable_components"),),
        )

    with localcontext() as context:
        context.prec = _calculation_precision(inputs, active)
        active_weight = _sum_exact(
            item.configured_weight for item in active
        )
        weighted_numerator = _sum_exact(
            item.weighted_contribution
            for item in active
            if item.weighted_contribution is not None
        )
        unrounded_grade = weighted_numerator / active_weight
        rounded_grade = _round_final_grade(unrounded_grade, inputs.rounding)

    return _outcome(
        inputs,
        fingerprint,
        conventional_component,
        standards_component,
        status="calculated",
        active_weight=active_weight,
        weighted_numerator=weighted_numerator,
        unrounded_grade=unrounded_grade,
        rounded_grade=rounded_grade,
        reasons=(),
    )


def hybrid_grade_calculation_outcome_to_dict(
    value: HybridGradeCalculationOutcome,
) -> dict[str, object]:
    """Serialize a pure hybrid outcome for diagnostics and persistence reuse."""

    if not isinstance(value, HybridGradeCalculationOutcome):
        raise HybridGradeValidationError(
            "value must be HybridGradeCalculationOutcome."
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
        "student_id": value.student_id,
        "conventional_component": _component_result_to_dict(
            value.conventional_component
        ),
        "standards_component": _component_result_to_dict(value.standards_component),
        "active_weight": _optional_decimal_text(value.active_weight),
        "weighted_numerator": _optional_decimal_text(value.weighted_numerator),
        "unrounded_grade": _optional_decimal_text(value.unrounded_grade),
        "rounded_grade": _optional_decimal_text(value.rounded_grade),
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def hybrid_grade_calculation_outcome_to_json_bytes(
    value: HybridGradeCalculationOutcome,
) -> bytes:
    """Return canonical UTF-8 JSON bytes for one pure hybrid outcome."""

    return _canonical_json_bytes(hybrid_grade_calculation_outcome_to_dict(value))


def _component_result(
    kind: HybridGradeComponentKind,
    weight: Decimal,
    outcome: ConventionalGradeCalculationOutcome | StandardsGradeCalculationOutcome,
    treatment: GradeStateTreatment,
) -> HybridGradeComponentResult:
    reason_codes = tuple(reason.code for reason in outcome.reasons)
    if outcome.status == "calculated":
        if outcome.unrounded_grade is None:
            raise HybridGradeValidationError(
                "calculated component unexpectedly lacks an unrounded Grade."
            )
        contribution = _multiply_exact(outcome.unrounded_grade, weight)
        return HybridGradeComponentResult(
            component_kind=kind,
            configured_weight=weight,
            source_status="calculated",
            action="contribute",
            component_algorithm_version=outcome.algorithm_version,
            component_calculation_fingerprint=outcome.calculation_fingerprint,
            unrounded_grade=outcome.unrounded_grade,
            weighted_contribution=contribution,
            reason_codes=reason_codes,
        )
    if outcome.status == "blocked":
        return HybridGradeComponentResult(
            component_kind=kind,
            configured_weight=weight,
            source_status="blocked",
            action="blocking",
            component_algorithm_version=outcome.algorithm_version,
            component_calculation_fingerprint=outcome.calculation_fingerprint,
            unrounded_grade=None,
            weighted_contribution=None,
            reason_codes=reason_codes,
        )

    consequence = treatment.insufficient_evidence
    if consequence not in {"exclude", "blocking"}:
        raise HybridGradeValidationError(
            "insufficient hybrid component treatment must be exclude or blocking."
        )
    return HybridGradeComponentResult(
        component_kind=kind,
        configured_weight=weight,
        source_status="insufficient",
        action=cast(HybridGradeComponentAction, consequence),
        component_algorithm_version=outcome.algorithm_version,
        component_calculation_fingerprint=outcome.calculation_fingerprint,
        unrounded_grade=None,
        weighted_contribution=None,
        reason_codes=reason_codes,
    )


def _outcome(
    inputs: HybridGradeCalculationInput,
    fingerprint: str,
    conventional_component: HybridGradeComponentResult,
    standards_component: HybridGradeComponentResult,
    *,
    status: HybridGradeCalculationStatus,
    active_weight: Decimal | None,
    weighted_numerator: Decimal | None,
    unrounded_grade: Decimal | None,
    rounded_grade: Decimal | None,
    reasons: tuple[HybridGradeReason, ...],
) -> HybridGradeCalculationOutcome:
    return HybridGradeCalculationOutcome(
        status=status,
        algorithm_version=HYBRID_GRADE_ALGORITHM_VERSION,
        calculation_fingerprint=fingerprint,
        target_period=inputs.target_period,
        calendar_revision=inputs.calendar_revision,
        activation_reference=inputs.activation_reference,
        policy_reference=inputs.policy_reference,
        student_id=inputs.student_id,
        conventional_component=conventional_component,
        standards_component=standards_component,
        active_weight=active_weight,
        weighted_numerator=weighted_numerator,
        unrounded_grade=unrounded_grade,
        rounded_grade=rounded_grade,
        reasons=reasons,
    )


def _component_result_to_dict(value: HybridGradeComponentResult) -> dict[str, object]:
    return {
        "component_kind": value.component_kind,
        "configured_weight": _decimal_to_text(value.configured_weight),
        "source_status": value.source_status,
        "action": value.action,
        "component_algorithm_version": value.component_algorithm_version,
        "component_calculation_fingerprint": (
            value.component_calculation_fingerprint
        ),
        "unrounded_grade": _optional_decimal_text(value.unrounded_grade),
        "weighted_contribution": _optional_decimal_text(
            value.weighted_contribution
        ),
        "reason_codes": list(value.reason_codes),
    }


def _reason_to_dict(value: HybridGradeReason) -> dict[str, object]:
    return {
        "code": value.code,
        "component_kind": value.component_kind,
    }


def _sum_exact(values: Iterable[Decimal]) -> Decimal:
    exact_values = tuple(
        _finite_decimal(value, "sum value")
        for value in values
    )
    if not exact_values:
        return Decimal("0")
    with localcontext() as context:
        context.prec = max(
            64,
            sum(_decimal_precision(value) for value in exact_values) + 16,
        )
        return sum(exact_values, Decimal("0"))


def _multiply_exact(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = max(
            64,
            _decimal_precision(left) + _decimal_precision(right) + 16,
        )
        return left * right


def _calculation_precision(
    inputs: HybridGradeCalculationInput,
    active: tuple[HybridGradeComponentResult, ...],
) -> int:
    digits = [
        _decimal_precision(inputs.rounding.quantum),
        _decimal_precision(inputs.configuration.conventional_weight),
        _decimal_precision(inputs.configuration.standards_weight),
    ]
    digits.extend(
        _decimal_precision(item.unrounded_grade)
        for item in active
        if item.unrounded_grade is not None
    )
    return max(64, max(digits, default=1) * 4 + 32)


def _round_final_grade(value: Decimal, policy: GradeRoundingPolicy) -> Decimal:
    try:
        rounding = _ROUNDING[policy.mode]
    except KeyError as error:
        raise HybridGradeValidationError(
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


def _decimal_precision(value: Decimal) -> int:
    finite = _finite_decimal(value, "Decimal value")
    normalized = finite.normalize()
    exponent = normalized.as_tuple().exponent
    if not isinstance(exponent, int):
        raise HybridGradeValidationError(
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


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_to_text(value)


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
        raise HybridGradeValidationError(
            "value cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _academic_period_ref(value: AcademicPeriodRef) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise HybridGradeValidationError(
            "target_period must be an AcademicPeriodRef."
        )
    try:
        return validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise HybridGradeValidationError(str(error)) from error


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise HybridGradeValidationError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise HybridGradeValidationError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HybridGradeValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise HybridGradeValidationError(
            f"{field_name} must be an exact finite Decimal."
        )
    return value


def _positive_decimal(value: object, field_name: str) -> Decimal:
    decimal_value = _finite_decimal(value, field_name)
    if decimal_value <= 0:
        raise HybridGradeValidationError(
            f"{field_name} must be greater than zero."
        )
    return decimal_value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HybridGradeValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise HybridGradeValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip():
        raise HybridGradeValidationError(
            f"{field_name} must be nonblank without surrounding whitespace."
        )
    if len(value) > maximum:
        raise HybridGradeValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise HybridGradeValidationError(
            f"{field_name} must be single-line and control-free."
        )
    return value


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise HybridGradeValidationError("reason code is invalid.")
    return value


def _reason_codes(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise HybridGradeValidationError("reason_codes must be an iterable.")
    try:
        values = tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise HybridGradeValidationError(
            "reason_codes must be an iterable."
        ) from error
    return tuple(_reason_code(item) for item in values)
