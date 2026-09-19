"""Read-only standards-based Grade explanation for Meridian v0.3 Issue #54.

This module explains one exact persisted standards-based Grade result.  It never
recalculates proficiency or Grade state, never substitutes a current proficiency
result for the exact historical revision recorded by the Grade result, and never
mutates Grade policy, result selection, override, snapshot, or producer state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
    academic_period_proficiency_result_reference_to_dict,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyExplanation,
    AcademicPeriodProficiencyTraceTarget,
    academic_period_proficiency_explanation_to_dict,
    explain_academic_period_proficiency,
)
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_item_proficiency_explanation import ExplanationTraceError
from meridian.grade_policy import GradePolicyRevision
from meridian.grade_policy_activation import GradePolicyActivationDecision
from meridian.grade_preview_explanation import (
    GradePreviewBaseResultExplanation,
    GradePreviewBasisEntry,
    GradePreviewExplanation,
    GradePreviewIntegrityError,
    GradePreviewObservation,
    GradePreviewTarget,
    GradePreviewTargetError,
    explain_grade_preview_common,
    grade_preview_explanation_to_dict,
    grade_preview_observation_from_explanation,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeAction,
    StandardsGradeCalculationInput,
    StandardsGradeCalculationOutcome,
    StandardsGradeCalculationStatus,
    StandardsGradeSourceState,
    StandardsGradeUpstreamFreshnessStatus,
    calculate_standards_grade,
)
from meridian.standards_grade_result import (
    StandardsGradeResultSnapshot,
    standards_grade_result_reference,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference


@dataclass(frozen=True, slots=True)
class StandardsGradeScaleExplanation:
    """Exact target proficiency-scale reference used by the Grade policy."""

    reference: ProficiencyScaleReference

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ProficiencyScaleReference):
            raise GradePreviewTargetError(
                "target scale must be ProficiencyScaleReference."
            )


@dataclass(frozen=True, slots=True)
class StandardsGradeConversionExplanation:
    """One exact proficiency-level to Grade-value conversion from policy."""

    proficiency_level_id: str
    grade_value: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.proficiency_level_id, str)
            or not self.proficiency_level_id
        ):
            raise GradePreviewTargetError(
                "proficiency_level_id must be nonempty text."
            )
        if (
            not isinstance(self.grade_value, Decimal)
            or not self.grade_value.is_finite()
            or self.grade_value < 0
        ):
            raise GradePreviewTargetError(
                "conversion grade_value must be a nonnegative finite Decimal."
            )


@dataclass(frozen=True, slots=True)
class StandardsGradeStandardExplanation:
    """One policy-participating standard and its exact Grade consequence."""

    standard_id: str
    weight: Decimal
    source_state: StandardsGradeSourceState
    action: StandardsGradeAction
    result_reference: AcademicPeriodProficiencyResultReference | None
    result_algorithm_version: str | None
    result_calculation_fingerprint: str | None
    target_scale: ProficiencyScaleReference | None
    proficiency_level_id: str | None
    converted_grade_value: Decimal | None
    calculation_value: Decimal | None
    weighted_contribution: Decimal | None
    freshness_status: StandardsGradeUpstreamFreshnessStatus | None
    freshness_reasons: tuple[str, ...]
    reason_codes: tuple[str, ...]
    nested_proficiency_explanation: AcademicPeriodProficiencyExplanation | None

    def __post_init__(self) -> None:
        if not isinstance(self.standard_id, str) or not self.standard_id:
            raise GradePreviewTargetError("standard_id must be nonempty text.")
        if (
            not isinstance(self.weight, Decimal)
            or not self.weight.is_finite()
            or self.weight <= 0
        ):
            raise GradePreviewTargetError(
                "standard weight must be a positive finite Decimal."
            )
        if self.source_state not in {
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
        }:
            raise GradePreviewTargetError("unsupported standards source state.")
        if self.action not in {"contribute", "exclude", "blocking", "zero"}:
            raise GradePreviewTargetError("unsupported standards Grade action.")
        for field_name in (
            "converted_grade_value",
            "calculation_value",
            "weighted_contribution",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be a finite Decimal when present."
                )
        if self.freshness_status not in {None, "current", "stale"}:
            raise GradePreviewTargetError("unsupported standards freshness status.")
        freshness_reasons = _reason_codes(self.freshness_reasons)
        reason_codes = _reason_codes(self.reason_codes)
        if self.freshness_status == "current" and freshness_reasons:
            raise GradePreviewTargetError(
                "current nested proficiency must not carry freshness reasons."
            )
        if self.freshness_status == "stale" and not freshness_reasons:
            raise GradePreviewTargetError(
                "stale nested proficiency requires freshness reasons."
            )
        if self.result_reference is None:
            if self.nested_proficiency_explanation is not None:
                raise GradePreviewIntegrityError(
                    "standard without a result reference cannot carry nested trace."
                )
        elif self.nested_proficiency_explanation is None:
            raise GradePreviewIntegrityError(
                "standard with an exact result reference requires nested trace."
            )
        object.__setattr__(self, "freshness_reasons", freshness_reasons)
        object.__setattr__(self, "reason_codes", reason_codes)


@dataclass(frozen=True, slots=True)
class StandardsGradeReasonExplanation:
    """One structured top-level standards Grade reason."""

    code: str
    standard_id: str | None
    required_results: int | None
    actual_results: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise GradePreviewTargetError("standards reason code must be text.")
        if self.standard_id is not None and (
            not isinstance(self.standard_id, str) or not self.standard_id
        ):
            raise GradePreviewTargetError(
                "reason standard_id must be nonempty text when present."
            )
        if self.required_results is not None and (
            type(self.required_results) is not int or self.required_results < 1
        ):
            raise GradePreviewTargetError(
                "required_results must be a positive integer when present."
            )
        if self.actual_results is not None and (
            type(self.actual_results) is not int or self.actual_results < 0
        ):
            raise GradePreviewTargetError(
                "actual_results must be a nonnegative integer when present."
            )


@dataclass(frozen=True, slots=True)
class StandardsGradeFormulaExplanation:
    """Exact weighted-mean formula state persisted by #51."""

    aggregation_strategy: str
    minimum_calculated_results: int
    actual_calculated_result_count: int
    active_weight: Decimal | None
    weighted_numerator: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None

    def __post_init__(self) -> None:
        if self.aggregation_strategy != "weighted_mean":
            raise GradePreviewTargetError(
                "standards Grade aggregation_strategy must be weighted_mean."
            )
        if (
            type(self.minimum_calculated_results) is not int
            or self.minimum_calculated_results < 1
        ):
            raise GradePreviewTargetError(
                "minimum_calculated_results must be positive."
            )
        if (
            type(self.actual_calculated_result_count) is not int
            or self.actual_calculated_result_count < 0
        ):
            raise GradePreviewTargetError(
                "actual_calculated_result_count must be nonnegative."
            )
        for field_name in (
            "active_weight",
            "weighted_numerator",
            "unrounded_grade",
            "rounded_grade",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be a finite Decimal when present."
                )
        if self.active_weight is not None and self.active_weight <= 0:
            raise GradePreviewTargetError(
                "active_weight must be positive when present."
            )


@dataclass(frozen=True, slots=True)
class StandardsGradeBreakdownExplanation:
    """Family detail reusable by standalone and embedded hybrid previews."""

    status: StandardsGradeCalculationStatus
    target_scale: StandardsGradeScaleExplanation
    conversions: tuple[StandardsGradeConversionExplanation, ...]
    standards: tuple[StandardsGradeStandardExplanation, ...]
    formula: StandardsGradeFormulaExplanation
    reasons: tuple[StandardsGradeReasonExplanation, ...]

    def __post_init__(self) -> None:
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError("unsupported standards Grade status.")
        if not isinstance(self.target_scale, StandardsGradeScaleExplanation):
            raise GradePreviewTargetError(
                "target_scale must be StandardsGradeScaleExplanation."
            )
        conversions = tuple(self.conversions)
        standards = tuple(self.standards)
        reasons = tuple(self.reasons)
        if any(
            not isinstance(item, StandardsGradeConversionExplanation)
            for item in conversions
        ):
            raise GradePreviewTargetError(
                "conversions must contain StandardsGradeConversionExplanation values."
            )
        level_ids = tuple(item.proficiency_level_id for item in conversions)
        if len(set(level_ids)) != len(level_ids):
            raise GradePreviewTargetError(
                "standards conversion level IDs must not contain duplicates."
            )
        if any(
            not isinstance(item, StandardsGradeStandardExplanation)
            for item in standards
        ):
            raise GradePreviewTargetError(
                "standards must contain StandardsGradeStandardExplanation values."
            )
        if any(
            not isinstance(item, StandardsGradeReasonExplanation) for item in reasons
        ):
            raise GradePreviewTargetError(
                "reasons must contain StandardsGradeReasonExplanation values."
            )
        if not isinstance(self.formula, StandardsGradeFormulaExplanation):
            raise GradePreviewTargetError(
                "formula must be StandardsGradeFormulaExplanation."
            )
        if self.status == "calculated":
            if (
                self.formula.unrounded_grade is None
                or self.formula.rounded_grade is None
            ):
                raise GradePreviewIntegrityError(
                    "calculated standards explanation requires numeric Grade values."
                )
        elif (
            self.formula.unrounded_grade is not None
            or self.formula.rounded_grade is not None
        ):
            raise GradePreviewIntegrityError(
                "blocked/insufficient standards explanation must remain nonnumeric."
            )
        object.__setattr__(
            self,
            "conversions",
            tuple(sorted(conversions, key=lambda item: item.proficiency_level_id)),
        )
        object.__setattr__(self, "standards", standards)
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class StandardsGradePreviewExplanation:
    """Rich standards-based breakdown layered over common #54 explanation."""

    common: GradePreviewExplanation
    status: StandardsGradeCalculationStatus
    target_scale: StandardsGradeScaleExplanation
    conversions: tuple[StandardsGradeConversionExplanation, ...]
    standards: tuple[StandardsGradeStandardExplanation, ...]
    formula: StandardsGradeFormulaExplanation
    reasons: tuple[StandardsGradeReasonExplanation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.common, GradePreviewExplanation):
            raise GradePreviewTargetError("common must be GradePreviewExplanation.")
        if self.common.target.calculation_family != "standards_based":
            raise GradePreviewIntegrityError(
                "standards explanation requires standards_based common target."
            )
        breakdown = StandardsGradeBreakdownExplanation(
            status=self.status,
            target_scale=self.target_scale,
            conversions=self.conversions,
            standards=self.standards,
            formula=self.formula,
            reasons=self.reasons,
        )
        object.__setattr__(self, "conversions", breakdown.conversions)
        object.__setattr__(self, "standards", breakdown.standards)
        object.__setattr__(self, "reasons", breakdown.reasons)



def explain_standards_grade_breakdown(
    workspace_root: str | Path,
    inputs: StandardsGradeCalculationInput,
    outcome: StandardsGradeCalculationOutcome,
) -> StandardsGradeBreakdownExplanation:
    """Explain one exact standards calculation basis without current state."""

    if not isinstance(inputs, StandardsGradeCalculationInput):
        raise GradePreviewTargetError(
            "inputs must be StandardsGradeCalculationInput."
        )
    if not isinstance(outcome, StandardsGradeCalculationOutcome):
        raise GradePreviewTargetError(
            "outcome must be StandardsGradeCalculationOutcome."
        )
    try:
        exact_outcome = calculate_standards_grade(inputs)
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"embedded standards calculation is invalid: {error}"
        ) from error
    if exact_outcome != outcome:
        raise GradePreviewIntegrityError(
            "standards outcome does not reproduce from exact embedded inputs."
        )
    standard_explanations = tuple(
        _standard_explanation(workspace_root, result)
        for result in outcome.standard_results
    )
    formula = StandardsGradeFormulaExplanation(
        aggregation_strategy=outcome.aggregation_strategy,
        minimum_calculated_results=outcome.minimum_calculated_results,
        actual_calculated_result_count=outcome.actual_calculated_result_count,
        active_weight=outcome.active_weight,
        weighted_numerator=outcome.weighted_numerator,
        unrounded_grade=outcome.unrounded_grade,
        rounded_grade=outcome.rounded_grade,
    )
    reasons = tuple(
        StandardsGradeReasonExplanation(
            code=reason.code,
            standard_id=reason.standard_id,
            required_results=reason.required_results,
            actual_results=reason.actual_results,
        )
        for reason in outcome.reasons
    )
    return StandardsGradeBreakdownExplanation(
        status=outcome.status,
        target_scale=StandardsGradeScaleExplanation(
            inputs.configuration.target_scale
        ),
        conversions=tuple(
            StandardsGradeConversionExplanation(
                proficiency_level_id=item.proficiency_level_id,
                grade_value=item.grade_value,
            )
            for item in inputs.configuration.conversions
        ),
        standards=standard_explanations,
        formula=formula,
        reasons=reasons,
    )


def explain_standards_grade_preview(
    workspace_root: str | Path,
    snapshot: StandardsGradeResultSnapshot,
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    effective: EffectiveGradeResolution,
) -> StandardsGradePreviewExplanation:
    """Explain one exact persisted standards Grade result without mutation."""

    if not isinstance(snapshot, StandardsGradeResultSnapshot):
        raise GradePreviewTargetError(
            "snapshot must be StandardsGradeResultSnapshot."
        )
    try:
        snapshot.__post_init__()
        result_reference = standards_grade_result_reference(snapshot)
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"standards Grade result is invalid: {error}"
        ) from error

    target = GradePreviewTarget(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        target_period=snapshot.target_period,
        calendar_revision=snapshot.calendar_revision,
        calculation_family="standards_based",
    )
    source_reference = GradeOverrideSourceResultReference(
        "standards_based",
        result_reference,
    )
    outcome = snapshot.outcome
    common = explain_grade_preview_common(
        target=target,
        base_result=GradePreviewBaseResultExplanation(
            source_result=source_reference,
            algorithm_version=snapshot.algorithm_version,
            calculation_fingerprint=snapshot.calculation_fingerprint,
            inputs_sha256=snapshot.inputs_sha256,
            calculated_at=snapshot.calculated_at,
            unrounded_grade=outcome.unrounded_grade,
            rounded_grade=outcome.rounded_grade,
        ),
        policy=policy,
        activation=activation,
        effective=effective,
    )
    if snapshot.target_scale != snapshot.inputs.configuration.target_scale:
        raise GradePreviewIntegrityError(
            "standards Grade target scale does not match embedded policy basis."
        )
    breakdown = explain_standards_grade_breakdown(
        workspace_root,
        snapshot.inputs,
        outcome,
    )
    return StandardsGradePreviewExplanation(
        common=common,
        status=breakdown.status,
        target_scale=breakdown.target_scale,
        conversions=breakdown.conversions,
        standards=breakdown.standards,
        formula=breakdown.formula,
        reasons=breakdown.reasons,
    )


def standards_grade_observation(
    value: StandardsGradePreviewExplanation,
) -> GradePreviewObservation:
    """Project standards detail into the stable #54 observation handoff."""

    if not isinstance(value, StandardsGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be StandardsGradePreviewExplanation."
        )
    return grade_preview_observation_from_explanation(
        value.common,
        extra_basis_entries=standards_grade_basis_entries(value),
    )


def standards_grade_basis_entries(
    value: StandardsGradePreviewExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    """Return privacy-minimized semantic hashes for future snapshot comparison."""

    if not isinstance(value, StandardsGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be StandardsGradePreviewExplanation."
        )
    return _standards_grade_basis_entries(
        value.target_scale,
        value.conversions,
        value.standards,
        value.formula,
    )


def standards_grade_breakdown_basis_entries(
    value: StandardsGradeBreakdownExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    """Return comparison hashes for an embedded standards component."""

    if not isinstance(value, StandardsGradeBreakdownExplanation):
        raise GradePreviewTargetError(
            "value must be StandardsGradeBreakdownExplanation."
        )
    return _standards_grade_basis_entries(
        value.target_scale,
        value.conversions,
        value.standards,
        value.formula,
    )


def _standards_grade_basis_entries(
    target_scale: StandardsGradeScaleExplanation,
    conversions: tuple[StandardsGradeConversionExplanation, ...],
    standards: tuple[StandardsGradeStandardExplanation, ...],
    formula_value: StandardsGradeFormulaExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    formula = {
        "aggregation_strategy": formula_value.aggregation_strategy,
        "minimum_calculated_results": formula_value.minimum_calculated_results,
        "target_scale": _scale_reference_to_dict(target_scale.reference),
        "conversions": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "grade_value": _decimal_text(item.grade_value),
            }
            for item in conversions
        ],
    }
    participation = [
        {"standard_id": item.standard_id} for item in standards
    ]
    weighting = [
        {
            "standard_id": item.standard_id,
            "weight": _decimal_text(item.weight),
        }
        for item in standards
    ]
    evidence = [
        {
            "standard_id": item.standard_id,
            "source_state": item.source_state,
            "action": item.action,
            "result_reference": (
                academic_period_proficiency_result_reference_to_dict(
                    item.result_reference
                )
                if item.result_reference is not None
                else None
            ),
            "result_algorithm_version": item.result_algorithm_version,
            "result_calculation_fingerprint": (
                item.result_calculation_fingerprint
            ),
            "proficiency_level_id": item.proficiency_level_id,
            "freshness_status": item.freshness_status,
            "freshness_reasons": list(item.freshness_reasons),
            "reason_codes": list(item.reason_codes),
        }
        for item in standards
    ]
    return (
        GradePreviewBasisEntry(
            "formula",
            "standards_formula",
            _semantic_digest(formula),
        ),
        GradePreviewBasisEntry(
            "participation",
            "standards_participation",
            _semantic_digest(participation),
        ),
        GradePreviewBasisEntry(
            "evidence",
            "standards_proficiency_basis",
            _semantic_digest(evidence),
        ),
        GradePreviewBasisEntry(
            "weighting",
            "standards_weighting",
            _semantic_digest(weighting),
        ),
    )



def standards_grade_breakdown_to_dict(
    value: StandardsGradeBreakdownExplanation,
) -> dict[str, object]:
    """Serialize one embedded standards breakdown deterministically."""

    if not isinstance(value, StandardsGradeBreakdownExplanation):
        raise GradePreviewTargetError(
            "value must be StandardsGradeBreakdownExplanation."
        )
    return {
        "status": value.status,
        "target_scale": _scale_reference_to_dict(value.target_scale.reference),
        "conversions": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "grade_value": _decimal_text(item.grade_value),
            }
            for item in value.conversions
        ],
        "standards": [_standard_to_dict(item) for item in value.standards],
        "formula": _formula_to_dict(value.formula),
        "reasons": [_reason_to_dict(item) for item in value.reasons],
    }


def standards_grade_preview_explanation_to_dict(
    value: StandardsGradePreviewExplanation,
) -> dict[str, object]:
    """Serialize standards explanation detail to deterministic JSON-native data."""

    if not isinstance(value, StandardsGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be StandardsGradePreviewExplanation."
        )
    return {
        "common": grade_preview_explanation_to_dict(value.common),
        "status": value.status,
        "target_scale": _scale_reference_to_dict(value.target_scale.reference),
        "conversions": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "grade_value": _decimal_text(item.grade_value),
            }
            for item in value.conversions
        ],
        "standards": [_standard_to_dict(item) for item in value.standards],
        "formula": _formula_to_dict(value.formula),
        "reasons": [_reason_to_dict(item) for item in value.reasons],
    }


def _standard_explanation(
    workspace_root: str | Path,
    result: object,
) -> StandardsGradeStandardExplanation:
    from meridian.standards_grade import StandardsGradeStandardResult

    if not isinstance(result, StandardsGradeStandardResult):
        raise GradePreviewIntegrityError(
            "standards outcome contains an invalid standard result."
        )
    nested: AcademicPeriodProficiencyExplanation | None = None
    reference = result.result_reference
    if reference is not None:
        target = AcademicPeriodProficiencyTraceTarget(
            class_id=reference.class_id,
            school_year=reference.school_year,
            period_id=reference.period_id,
            student_id=reference.student_id,
            standard_id=reference.standard_id,
            selection="revision",
            result_revision=reference.result_revision,
        )
        try:
            nested = explain_academic_period_proficiency(workspace_root, target)
        except ExplanationTraceError as error:
            raise GradePreviewIntegrityError(
                "exact Academic Period proficiency result required by standards "
                f"Grade could not be verified: {error}"
            ) from error
        _verify_nested_proficiency(result, reference, nested)

    return StandardsGradeStandardExplanation(
        standard_id=result.standard_id,
        weight=result.weight,
        source_state=result.source_state,
        action=result.action,
        result_reference=reference,
        result_algorithm_version=result.result_algorithm_version,
        result_calculation_fingerprint=result.result_calculation_fingerprint,
        target_scale=result.target_scale,
        proficiency_level_id=result.proficiency_level_id,
        converted_grade_value=result.converted_grade_value,
        calculation_value=result.calculation_value,
        weighted_contribution=result.weighted_contribution,
        freshness_status=result.freshness_status,
        freshness_reasons=result.freshness_reasons,
        reason_codes=result.reason_codes,
        nested_proficiency_explanation=nested,
    )


def _verify_nested_proficiency(
    result: object,
    reference: AcademicPeriodProficiencyResultReference,
    nested: AcademicPeriodProficiencyExplanation,
) -> None:
    from meridian.standards_grade import StandardsGradeStandardResult

    if not isinstance(result, StandardsGradeStandardResult):
        raise GradePreviewIntegrityError(
            "nested proficiency verification received invalid standard result."
        )
    if (
        nested.class_id != reference.class_id
        or nested.student_id != reference.student_id
        or nested.standard_id != reference.standard_id
        or nested.result_revision != reference.result_revision
        or nested.result_sha256 != reference.result_sha256
    ):
        raise GradePreviewIntegrityError(
            "nested proficiency explanation does not match exact Grade reference."
        )
    if nested.algorithm_version != result.result_algorithm_version:
        raise GradePreviewIntegrityError(
            "nested proficiency algorithm version does not match Grade result."
        )
    if (
        nested.calculation_fingerprint
        != result.result_calculation_fingerprint
    ):
        raise GradePreviewIntegrityError(
            "nested proficiency fingerprint does not match Grade result."
        )
    scale = result.target_scale
    if scale is None:
        raise GradePreviewIntegrityError(
            "referenced proficiency result lacks exact target-scale metadata."
        )
    if (
        nested.class_id != scale.class_id
        or nested.scale.scale_id != scale.scale_id
        or nested.scale.scale_revision != scale.scale_revision
        or nested.scale.scale_sha256 != scale.scale_sha256
    ):
        raise GradePreviewIntegrityError(
            "nested proficiency scale does not match exact Grade result metadata."
        )
    if result.source_state == "calculated":
        if (
            nested.calculation.status != "calculated"
            or nested.calculation.proficiency_level_id
            != result.proficiency_level_id
        ):
            raise GradePreviewIntegrityError(
                "nested calculated proficiency does not match Grade result value."
            )
    elif nested.calculation.proficiency_level_id is not None:
        raise GradePreviewIntegrityError(
            "nonnumeric standards source cannot gain proficiency through trace."
        )


def _standard_to_dict(
    value: StandardsGradeStandardExplanation,
) -> dict[str, object]:
    return {
        "standard_id": value.standard_id,
        "weight": _decimal_text(value.weight),
        "source_state": value.source_state,
        "action": value.action,
        "result_reference": (
            academic_period_proficiency_result_reference_to_dict(
                value.result_reference
            )
            if value.result_reference is not None
            else None
        ),
        "result_algorithm_version": value.result_algorithm_version,
        "result_calculation_fingerprint": value.result_calculation_fingerprint,
        "target_scale": (
            _scale_reference_to_dict(value.target_scale)
            if value.target_scale is not None
            else None
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "converted_grade_value": _decimal_text(value.converted_grade_value),
        "calculation_value": _decimal_text(value.calculation_value),
        "weighted_contribution": _decimal_text(value.weighted_contribution),
        "freshness_status": value.freshness_status,
        "freshness_reasons": list(value.freshness_reasons),
        "reason_codes": list(value.reason_codes),
        "nested_proficiency_explanation": (
            academic_period_proficiency_explanation_to_dict(
                value.nested_proficiency_explanation
            )
            if value.nested_proficiency_explanation is not None
            else None
        ),
    }


def _formula_to_dict(value: StandardsGradeFormulaExplanation) -> dict[str, object]:
    return {
        "aggregation_strategy": value.aggregation_strategy,
        "minimum_calculated_results": value.minimum_calculated_results,
        "actual_calculated_result_count": value.actual_calculated_result_count,
        "active_weight": _decimal_text(value.active_weight),
        "weighted_numerator": _decimal_text(value.weighted_numerator),
        "unrounded_grade": _decimal_text(value.unrounded_grade),
        "rounded_grade": _decimal_text(value.rounded_grade),
    }


def _reason_to_dict(value: StandardsGradeReasonExplanation) -> dict[str, object]:
    return {
        "code": value.code,
        "standard_id": value.standard_id,
        "required_results": value.required_results,
        "actual_results": value.actual_results,
    }


def _scale_reference_to_dict(value: ProficiencyScaleReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    result = tuple(values)
    if any(not isinstance(value, str) or not value for value in result):
        raise GradePreviewTargetError("reason codes must be nonempty strings.")
    if len(set(result)) != len(result):
        raise GradePreviewTargetError("reason codes must not contain duplicates.")
    return result


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise GradePreviewTargetError("Grade explanation Decimal must be finite.")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    return text


def _semantic_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
