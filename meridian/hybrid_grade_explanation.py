"""Read-only hybrid Grade explanation for Meridian v0.3 Issue #54.

The hybrid explanation is derived from the exact conventional and standards
calculation bases embedded in one persisted hybrid Grade result. It never reads
or substitutes independently selected current component Grade results.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from meridian.conventional_grade import calculate_conventional_grade
from meridian.conventional_grade_explanation import (
    ConventionalGradeBreakdownExplanation,
    conventional_grade_breakdown_basis_entries,
    conventional_grade_breakdown_to_dict,
    explain_conventional_grade_breakdown,
)
from meridian.effective_grade import EffectiveGradeResolution
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
from meridian.hybrid_grade import (
    HybridGradeCalculationStatus,
    HybridGradeComponentAction,
    HybridGradeComponentKind,
    HybridGradeComponentSourceStatus,
    HybridGradeReason,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    HybridGradeResultSnapshot,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_explanation import (
    StandardsGradeBreakdownExplanation,
    explain_standards_grade_breakdown,
    standards_grade_breakdown_basis_entries,
    standards_grade_breakdown_to_dict,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference


@dataclass(frozen=True, slots=True)
class HybridGradeComponentExplanation:
    """One exact hybrid component plus its embedded family breakdown."""

    component_kind: HybridGradeComponentKind
    configured_weight: Decimal
    source_status: HybridGradeComponentSourceStatus
    action: HybridGradeComponentAction
    component_algorithm_version: str
    component_calculation_fingerprint: str
    unrounded_grade: Decimal | None
    weighted_contribution: Decimal | None
    reason_codes: tuple[str, ...]
    breakdown: (
        ConventionalGradeBreakdownExplanation
        | StandardsGradeBreakdownExplanation
    )

    def __post_init__(self) -> None:
        if self.component_kind not in {"conventional", "standards_based"}:
            raise GradePreviewTargetError("unsupported hybrid component kind.")
        if (
            not isinstance(self.configured_weight, Decimal)
            or not self.configured_weight.is_finite()
            or self.configured_weight <= 0
        ):
            raise GradePreviewTargetError(
                "hybrid component weight must be a positive finite Decimal."
            )
        if self.source_status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError(
                "unsupported hybrid component source status."
            )
        if self.action not in {"contribute", "exclude", "blocking"}:
            raise GradePreviewTargetError("unsupported hybrid component action.")
        if (
            not isinstance(self.component_algorithm_version, str)
            or not self.component_algorithm_version
        ):
            raise GradePreviewTargetError(
                "component algorithm version must be nonempty text."
            )
        _sha256(
            self.component_calculation_fingerprint,
            "component calculation fingerprint",
        )
        for field_name in ("unrounded_grade", "weighted_contribution"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be a finite Decimal when present."
                )
        reasons = _reason_codes(self.reason_codes)
        if self.component_kind == "conventional":
            if not isinstance(
                self.breakdown,
                ConventionalGradeBreakdownExplanation,
            ):
                raise GradePreviewIntegrityError(
                    "conventional hybrid component requires conventional breakdown."
                )
            if self.breakdown.status != self.source_status:
                raise GradePreviewIntegrityError(
                    "conventional breakdown status must match hybrid component."
                )
        else:
            if not isinstance(self.breakdown, StandardsGradeBreakdownExplanation):
                raise GradePreviewIntegrityError(
                    "standards hybrid component requires standards breakdown."
                )
            if self.breakdown.status != self.source_status:
                raise GradePreviewIntegrityError(
                    "standards breakdown status must match hybrid component."
                )
        if self.source_status == "calculated":
            if (
                self.action != "contribute"
                or self.unrounded_grade is None
                or self.weighted_contribution is None
            ):
                raise GradePreviewIntegrityError(
                    "calculated hybrid component requires numeric contribution."
                )
        elif self.source_status == "blocked":
            if (
                self.action != "blocking"
                or self.unrounded_grade is not None
                or self.weighted_contribution is not None
            ):
                raise GradePreviewIntegrityError(
                    "blocked hybrid component must remain nonnumeric."
                )
        elif (
            self.action not in {"exclude", "blocking"}
            or self.unrounded_grade is not None
            or self.weighted_contribution is not None
        ):
            raise GradePreviewIntegrityError(
                "insufficient hybrid component must be nonnumeric and excluded "
                "or blocking."
            )
        object.__setattr__(self, "reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class HybridGradeFormulaExplanation:
    """Exact top-level hybrid combination and rounding inputs."""

    active_weight: Decimal | None
    weighted_numerator: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None

    def __post_init__(self) -> None:
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
                "hybrid active_weight must be positive when present."
            )


@dataclass(frozen=True, slots=True)
class HybridGradeReasonExplanation:
    """One structured top-level hybrid reason."""

    code: str
    component_kind: HybridGradeComponentKind | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise GradePreviewTargetError("hybrid reason code must be nonempty text.")
        if self.component_kind not in {None, "conventional", "standards_based"}:
            raise GradePreviewTargetError(
                "hybrid reason component kind is unsupported."
            )


@dataclass(frozen=True, slots=True)
class HybridGradePreviewExplanation:
    """Rich hybrid breakdown layered over the common #54 explanation."""

    common: GradePreviewExplanation
    status: HybridGradeCalculationStatus
    conventional_component: HybridGradeComponentExplanation
    standards_component: HybridGradeComponentExplanation
    formula: HybridGradeFormulaExplanation
    reasons: tuple[HybridGradeReasonExplanation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.common, GradePreviewExplanation):
            raise GradePreviewTargetError("common must be GradePreviewExplanation.")
        if self.common.target.calculation_family != "hybrid":
            raise GradePreviewIntegrityError(
                "hybrid explanation requires hybrid common target."
            )
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError("unsupported hybrid Grade status.")
        if (
            not isinstance(
                self.conventional_component,
                HybridGradeComponentExplanation,
            )
            or self.conventional_component.component_kind != "conventional"
        ):
            raise GradePreviewIntegrityError(
                "conventional_component must identify conventional detail."
            )
        if (
            not isinstance(
                self.standards_component,
                HybridGradeComponentExplanation,
            )
            or self.standards_component.component_kind != "standards_based"
        ):
            raise GradePreviewIntegrityError(
                "standards_component must identify standards detail."
            )
        if (
            self.conventional_component.configured_weight
            + self.standards_component.configured_weight
            != Decimal("1")
        ):
            raise GradePreviewIntegrityError(
                "hybrid component weights must sum exactly to one."
            )
        if not isinstance(self.formula, HybridGradeFormulaExplanation):
            raise GradePreviewTargetError(
                "formula must be HybridGradeFormulaExplanation."
            )
        reasons = tuple(self.reasons)
        if any(
            not isinstance(reason, HybridGradeReasonExplanation)
            for reason in reasons
        ):
            raise GradePreviewTargetError(
                "reasons must contain HybridGradeReasonExplanation values."
            )
        if self.status == "calculated":
            if any(
                value is None
                for value in (
                    self.formula.active_weight,
                    self.formula.weighted_numerator,
                    self.formula.unrounded_grade,
                    self.formula.rounded_grade,
                )
            ):
                raise GradePreviewIntegrityError(
                    "calculated hybrid explanation requires complete numeric math."
                )
        elif any(
            value is not None
            for value in (
                self.formula.active_weight,
                self.formula.weighted_numerator,
                self.formula.unrounded_grade,
                self.formula.rounded_grade,
            )
        ):
            raise GradePreviewIntegrityError(
                "blocked/insufficient hybrid explanation must remain nonnumeric."
            )
        object.__setattr__(self, "reasons", reasons)


def explain_hybrid_grade_preview(
    workspace_root: str | Path,
    snapshot: HybridGradeResultSnapshot,
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    effective: EffectiveGradeResolution,
) -> HybridGradePreviewExplanation:
    """Explain one exact persisted hybrid Grade result without mutation."""

    if not isinstance(snapshot, HybridGradeResultSnapshot):
        raise GradePreviewTargetError(
            "snapshot must be HybridGradeResultSnapshot."
        )
    try:
        snapshot.__post_init__()
        content = hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"hybrid Grade result is invalid: {error}"
        ) from error
    result_reference = HybridGradeResultReference(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        school_year=snapshot.target_period.school_year,
        period_id=snapshot.target_period.period_id,
        calendar_revision=snapshot.calendar_revision,
        result_revision=snapshot.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )
    source_reference = GradeOverrideSourceResultReference(
        "hybrid",
        result_reference,
    )
    target = GradePreviewTarget(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        target_period=snapshot.target_period,
        calendar_revision=snapshot.calendar_revision,
        calculation_family="hybrid",
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

    try:
        conventional_outcome = calculate_conventional_grade(
            snapshot.inputs.conventional
        )
        standards_outcome = calculate_standards_grade(
            snapshot.inputs.standards_based
        )
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"embedded hybrid component basis is invalid: {error}"
        ) from error

    conventional_breakdown = explain_conventional_grade_breakdown(
        workspace_root,
        snapshot.inputs.conventional,
        conventional_outcome,
    )
    standards_breakdown = explain_standards_grade_breakdown(
        workspace_root,
        snapshot.inputs.standards_based,
        standards_outcome,
    )
    conventional_component = _component_explanation(
        outcome.conventional_component,
        conventional_breakdown,
        expected_algorithm=conventional_outcome.algorithm_version,
        expected_fingerprint=conventional_outcome.calculation_fingerprint,
    )
    standards_component = _component_explanation(
        outcome.standards_component,
        standards_breakdown,
        expected_algorithm=standards_outcome.algorithm_version,
        expected_fingerprint=standards_outcome.calculation_fingerprint,
    )
    reasons = tuple(_reason_explanation(reason) for reason in outcome.reasons)
    return HybridGradePreviewExplanation(
        common=common,
        status=outcome.status,
        conventional_component=conventional_component,
        standards_component=standards_component,
        formula=HybridGradeFormulaExplanation(
            active_weight=outcome.active_weight,
            weighted_numerator=outcome.weighted_numerator,
            unrounded_grade=outcome.unrounded_grade,
            rounded_grade=outcome.rounded_grade,
        ),
        reasons=reasons,
    )


def hybrid_grade_observation(
    value: HybridGradePreviewExplanation,
) -> GradePreviewObservation:
    """Project hybrid detail into the stable #54 observation handoff."""

    if not isinstance(value, HybridGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be HybridGradePreviewExplanation."
        )
    return grade_preview_observation_from_explanation(
        value.common,
        extra_basis_entries=hybrid_grade_basis_entries(value),
    )


def hybrid_grade_basis_entries(
    value: HybridGradePreviewExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    """Return privacy-minimized hybrid semantic hashes for later comparison."""

    if not isinstance(value, HybridGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be HybridGradePreviewExplanation."
        )
    conventional_breakdown = value.conventional_component.breakdown
    standards_breakdown = value.standards_component.breakdown
    if not isinstance(
        conventional_breakdown,
        ConventionalGradeBreakdownExplanation,
    ):
        raise GradePreviewIntegrityError(
            "conventional component breakdown type changed unexpectedly."
        )
    if not isinstance(standards_breakdown, StandardsGradeBreakdownExplanation):
        raise GradePreviewIntegrityError(
            "standards component breakdown type changed unexpectedly."
        )
    conventional = conventional_grade_breakdown_basis_entries(
        conventional_breakdown
    )
    standards = standards_grade_breakdown_basis_entries(standards_breakdown)
    conventional_by_dimension = {item.dimension: item for item in conventional}
    standards_by_dimension = {item.dimension: item for item in standards}
    component_identity = {
        "conventional": {
            "algorithm_version": (
                value.conventional_component.component_algorithm_version
            ),
            "calculation_fingerprint": (
                value.conventional_component.component_calculation_fingerprint
            ),
            "source_status": value.conventional_component.source_status,
            "action": value.conventional_component.action,
        },
        "standards_based": {
            "algorithm_version": (
                value.standards_component.component_algorithm_version
            ),
            "calculation_fingerprint": (
                value.standards_component.component_calculation_fingerprint
            ),
            "source_status": value.standards_component.source_status,
            "action": value.standards_component.action,
        },
    }
    formula = {
        "component_identity": component_identity,
        "conventional_formula_sha256": (
            conventional_by_dimension["formula"].sha256
        ),
        "standards_formula_sha256": standards_by_dimension["formula"].sha256,
    }
    participation = {
        "conventional": conventional_by_dimension["participation"].sha256,
        "standards_based": standards_by_dimension["participation"].sha256,
    }
    evidence = {
        "conventional": conventional_by_dimension["evidence"].sha256,
        "standards_based": standards_by_dimension["evidence"].sha256,
    }
    weighting = {
        "conventional_weight": _decimal_text(
            value.conventional_component.configured_weight
        ),
        "standards_weight": _decimal_text(
            value.standards_component.configured_weight
        ),
        "conventional_component_weighting": (
            conventional_by_dimension["weighting"].sha256
        ),
        "standards_component_weighting": (
            standards_by_dimension["weighting"].sha256
        ),
    }
    return (
        GradePreviewBasisEntry(
            "formula",
            "hybrid_formula",
            _semantic_digest(formula),
        ),
        GradePreviewBasisEntry(
            "participation",
            "hybrid_participation",
            _semantic_digest(participation),
        ),
        GradePreviewBasisEntry(
            "evidence",
            "hybrid_component_basis",
            _semantic_digest(evidence),
        ),
        GradePreviewBasisEntry(
            "weighting",
            "hybrid_weighting",
            _semantic_digest(weighting),
        ),
    )


def hybrid_grade_preview_explanation_to_dict(
    value: HybridGradePreviewExplanation,
) -> dict[str, object]:
    """Serialize hybrid explanation detail to deterministic JSON-native data."""

    if not isinstance(value, HybridGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be HybridGradePreviewExplanation."
        )
    return {
        "common": grade_preview_explanation_to_dict(value.common),
        "status": value.status,
        "conventional_component": _component_to_dict(
            value.conventional_component
        ),
        "standards_component": _component_to_dict(value.standards_component),
        "formula": _formula_to_dict(value.formula),
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def hybrid_grade_preview_explanation_to_json_bytes(
    value: HybridGradePreviewExplanation,
) -> bytes:
    """Return deterministic JSON bytes without lossy Decimal conversion."""

    return _canonical_json_bytes(hybrid_grade_preview_explanation_to_dict(value))


def _component_explanation(
    component: object,
    breakdown: ConventionalGradeBreakdownExplanation
    | StandardsGradeBreakdownExplanation,
    *,
    expected_algorithm: str,
    expected_fingerprint: str,
) -> HybridGradeComponentExplanation:
    from meridian.hybrid_grade import HybridGradeComponentResult

    if not isinstance(component, HybridGradeComponentResult):
        raise GradePreviewIntegrityError(
            "hybrid outcome contains an invalid component result."
        )
    if component.component_algorithm_version != expected_algorithm:
        raise GradePreviewIntegrityError(
            "hybrid component algorithm does not match embedded calculation."
        )
    if component.component_calculation_fingerprint != expected_fingerprint:
        raise GradePreviewIntegrityError(
            "hybrid component fingerprint does not match embedded calculation."
        )
    return HybridGradeComponentExplanation(
        component_kind=component.component_kind,
        configured_weight=component.configured_weight,
        source_status=component.source_status,
        action=component.action,
        component_algorithm_version=component.component_algorithm_version,
        component_calculation_fingerprint=(
            component.component_calculation_fingerprint
        ),
        unrounded_grade=component.unrounded_grade,
        weighted_contribution=component.weighted_contribution,
        reason_codes=component.reason_codes,
        breakdown=breakdown,
    )


def _reason_explanation(
    reason: HybridGradeReason,
) -> HybridGradeReasonExplanation:
    if not isinstance(reason, HybridGradeReason):
        raise GradePreviewIntegrityError(
            "hybrid outcome contains an invalid top-level reason."
        )
    return HybridGradeReasonExplanation(
        code=reason.code,
        component_kind=reason.component_kind,
    )


def _component_to_dict(
    value: HybridGradeComponentExplanation,
) -> dict[str, object]:
    if value.component_kind == "conventional":
        if not isinstance(
            value.breakdown,
            ConventionalGradeBreakdownExplanation,
        ):
            raise GradePreviewIntegrityError(
                "conventional component breakdown type changed unexpectedly."
            )
        breakdown = conventional_grade_breakdown_to_dict(value.breakdown)
    else:
        if not isinstance(value.breakdown, StandardsGradeBreakdownExplanation):
            raise GradePreviewIntegrityError(
                "standards component breakdown type changed unexpectedly."
            )
        breakdown = standards_grade_breakdown_to_dict(value.breakdown)
    return {
        "component_kind": value.component_kind,
        "configured_weight": _decimal_text(value.configured_weight),
        "source_status": value.source_status,
        "action": value.action,
        "component_algorithm_version": value.component_algorithm_version,
        "component_calculation_fingerprint": (
            value.component_calculation_fingerprint
        ),
        "unrounded_grade": _decimal_text(value.unrounded_grade),
        "weighted_contribution": _decimal_text(value.weighted_contribution),
        "reason_codes": list(value.reason_codes),
        "breakdown": breakdown,
    }


def _formula_to_dict(value: HybridGradeFormulaExplanation) -> dict[str, object]:
    return {
        "active_weight": _decimal_text(value.active_weight),
        "weighted_numerator": _decimal_text(value.weighted_numerator),
        "unrounded_grade": _decimal_text(value.unrounded_grade),
        "rounded_grade": _decimal_text(value.rounded_grade),
    }


def _reason_to_dict(value: HybridGradeReasonExplanation) -> dict[str, object]:
    return {
        "code": value.code,
        "component_kind": value.component_kind,
    }


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    reasons = tuple(values)
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise GradePreviewTargetError(
            "hybrid reason codes must contain nonempty text."
        )
    if len(set(reasons)) != len(reasons):
        raise GradePreviewTargetError(
            "hybrid reason codes must not contain duplicates."
        )
    return reasons


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise GradePreviewTargetError("Grade value must be a finite Decimal.")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _semantic_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GradePreviewTargetError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
