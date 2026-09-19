"""Snapshot-neutral Grade-preview comparison contracts for Meridian v0.3.

Issue #54 compares the compact deterministic ``GradePreviewObservation`` emitted
by the current preview layer with a data-only basis extracted from a future
ReportingSnapshot.  This module does not read workspace state, persist snapshots,
or infer an official Grade.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, TypeAlias

from pds_core.academic_periods import academic_period_ref_to_dict

from meridian.grade_preview_explanation import (
    GradePreviewBasisEntry,
    GradePreviewComparisonError,
    GradePreviewObservation,
    GradePreviewTarget,
    grade_preview_observation_to_dict,
)

GradePreviewComparisonRelationship: TypeAlias = Literal[
    "new",
    "removed",
    "comparable",
]
GradePreviewChangeReason: TypeAlias = Literal[
    "calculation_family_changed",
    "base_result_changed",
    "base_status_changed",
    "base_grade_changed",
    "policy_changed",
    "formula_changed",
    "membership_or_participation_changed",
    "evidence_or_proficiency_basis_changed",
    "weighting_changed",
    "state_handling_changed",
    "rounding_changed",
    "algorithm_changed",
    "override_changed",
    "override_applicability_changed",
    "freshness_changed",
    "effective_grade_changed",
    "effective_source_changed",
]

_CHANGE_REASON_ORDER: Final[tuple[GradePreviewChangeReason, ...]] = (
    "calculation_family_changed",
    "base_result_changed",
    "base_status_changed",
    "base_grade_changed",
    "policy_changed",
    "formula_changed",
    "membership_or_participation_changed",
    "evidence_or_proficiency_basis_changed",
    "weighting_changed",
    "state_handling_changed",
    "rounding_changed",
    "algorithm_changed",
    "override_changed",
    "override_applicability_changed",
    "freshness_changed",
    "effective_grade_changed",
    "effective_source_changed",
)
_CHANGE_REASON_SET: Final[frozenset[str]] = frozenset(_CHANGE_REASON_ORDER)


@dataclass(frozen=True, slots=True)
class PriorReportingSnapshotGradeBasis:
    """Data-only prior ReportingSnapshot Grade basis consumed by #54.

    Future issue #55 may extract this value from its own immutable snapshot
    contract.  The #54 comparison engine intentionally knows only the frozen
    observation, not any ReportingSnapshot storage or lifecycle details.
    """

    observation: GradePreviewObservation

    def __post_init__(self) -> None:
        if not isinstance(self.observation, GradePreviewObservation):
            raise GradePreviewComparisonError(
                "prior snapshot basis must contain a GradePreviewObservation."
            )


@dataclass(frozen=True, slots=True)
class GradePreviewComparison:
    """Deterministic semantic difference between current and prior Grade bases."""

    relationship: GradePreviewComparisonRelationship
    prior_target: GradePreviewTarget | None
    current_target: GradePreviewTarget | None
    changed: bool
    reasons: tuple[GradePreviewChangeReason, ...]
    effective_grade_delta: Decimal | None

    def __post_init__(self) -> None:
        if self.relationship not in {"new", "removed", "comparable"}:
            raise GradePreviewComparisonError(
                "comparison relationship must be new, removed, or comparable."
            )
        reasons = tuple(self.reasons)
        if any(reason not in _CHANGE_REASON_SET for reason in reasons):
            raise GradePreviewComparisonError(
                "comparison reasons contain an unsupported reason."
            )
        if len(set(reasons)) != len(reasons):
            raise GradePreviewComparisonError(
                "comparison reasons must not contain duplicates."
            )
        canonical = tuple(
            reason for reason in _CHANGE_REASON_ORDER if reason in set(reasons)
        )
        if reasons != canonical:
            raise GradePreviewComparisonError(
                "comparison reasons must use deterministic canonical order."
            )
        if self.relationship == "new":
            if self.prior_target is not None or self.current_target is None:
                raise GradePreviewComparisonError(
                    "new comparison requires only a current target."
                )
            if not self.changed or reasons or self.effective_grade_delta is not None:
                raise GradePreviewComparisonError(
                    "new comparison must be changed without reasons or delta."
                )
        elif self.relationship == "removed":
            if self.prior_target is None or self.current_target is not None:
                raise GradePreviewComparisonError(
                    "removed comparison requires only a prior target."
                )
            if not self.changed or reasons or self.effective_grade_delta is not None:
                raise GradePreviewComparisonError(
                    "removed comparison must be changed without reasons or delta."
                )
        else:
            if self.prior_target is None or self.current_target is None:
                raise GradePreviewComparisonError(
                    "comparable comparison requires prior and current targets."
                )
            _require_same_logical_scope(self.prior_target, self.current_target)
            if self.changed != bool(reasons):
                raise GradePreviewComparisonError(
                    "comparable changed flag must match semantic reasons."
                )
            if self.effective_grade_delta is not None:
                _finite_decimal(
                    self.effective_grade_delta,
                    "effective_grade_delta",
                )
        object.__setattr__(self, "reasons", reasons)


def prior_reporting_snapshot_grade_basis_from_observation(
    observation: GradePreviewObservation,
) -> PriorReportingSnapshotGradeBasis:
    """Adapt one frozen #54 observation into the prior-snapshot comparison input."""

    if not isinstance(observation, GradePreviewObservation):
        raise GradePreviewComparisonError(
            "observation must be a GradePreviewObservation."
        )
    return PriorReportingSnapshotGradeBasis(observation)


def compare_grade_preview_basis(
    current: GradePreviewObservation | None,
    prior: PriorReportingSnapshotGradeBasis | None,
) -> GradePreviewComparison:
    """Compare current and prior Grade bases without workspace reads or mutation."""

    if current is None and prior is None:
        raise GradePreviewComparisonError(
            "comparison requires a current observation or prior snapshot basis."
        )
    if current is not None and not isinstance(current, GradePreviewObservation):
        raise GradePreviewComparisonError(
            "current must be GradePreviewObservation or None."
        )
    if prior is not None and not isinstance(prior, PriorReportingSnapshotGradeBasis):
        raise GradePreviewComparisonError(
            "prior must be PriorReportingSnapshotGradeBasis or None."
        )
    if prior is None:
        assert current is not None
        return GradePreviewComparison(
            relationship="new",
            prior_target=None,
            current_target=current.target,
            changed=True,
            reasons=(),
            effective_grade_delta=None,
        )
    if current is None:
        return GradePreviewComparison(
            relationship="removed",
            prior_target=prior.observation.target,
            current_target=None,
            changed=True,
            reasons=(),
            effective_grade_delta=None,
        )

    previous = prior.observation
    _require_same_logical_scope(previous.target, current.target)
    reasons = _comparison_reasons(previous, current)
    _require_material_changes_are_explained(previous, current, reasons)
    delta = _effective_delta(previous.effective_grade, current.effective_grade)
    return GradePreviewComparison(
        relationship="comparable",
        prior_target=previous.target,
        current_target=current.target,
        changed=bool(reasons),
        reasons=reasons,
        effective_grade_delta=delta,
    )


def prior_reporting_snapshot_grade_basis_to_dict(
    value: PriorReportingSnapshotGradeBasis,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one prior comparison basis."""

    if not isinstance(value, PriorReportingSnapshotGradeBasis):
        raise GradePreviewComparisonError(
            "value must be PriorReportingSnapshotGradeBasis."
        )
    return {"observation": grade_preview_observation_to_dict(value.observation)}


def prior_reporting_snapshot_grade_basis_to_json_bytes(
    value: PriorReportingSnapshotGradeBasis,
) -> bytes:
    """Return canonical UTF-8 JSON bytes for one prior comparison basis."""

    return _canonical_json_bytes(prior_reporting_snapshot_grade_basis_to_dict(value))


def grade_preview_comparison_to_dict(
    value: GradePreviewComparison,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one semantic comparison."""

    if not isinstance(value, GradePreviewComparison):
        raise GradePreviewComparisonError("value must be GradePreviewComparison.")
    return {
        "relationship": value.relationship,
        "prior_target": _target_to_dict(value.prior_target),
        "current_target": _target_to_dict(value.current_target),
        "changed": value.changed,
        "reasons": list(value.reasons),
        "effective_grade_delta": _optional_decimal_text(
            value.effective_grade_delta
        ),
    }


def grade_preview_comparison_to_json_bytes(
    value: GradePreviewComparison,
) -> bytes:
    """Return canonical UTF-8 JSON bytes for one semantic comparison."""

    return _canonical_json_bytes(grade_preview_comparison_to_dict(value))


def _comparison_reasons(
    previous: GradePreviewObservation,
    current: GradePreviewObservation,
) -> tuple[GradePreviewChangeReason, ...]:
    present: set[GradePreviewChangeReason] = set()
    if previous.target.calculation_family != current.target.calculation_family:
        present.add("calculation_family_changed")
    if previous.base_result_reference != current.base_result_reference:
        present.add("base_result_changed")
    if previous.base_result_status != current.base_result_status:
        present.add("base_status_changed")
    if previous.base_grade != current.base_grade:
        present.add("base_grade_changed")
    if (
        previous.activation_reference != current.activation_reference
        or previous.policy_reference != current.policy_reference
        or _basis_changed(previous, current, {"activation", "policy"})
    ):
        present.add("policy_changed")
    if _basis_changed(previous, current, {"formula"}):
        present.add("formula_changed")
    if _basis_changed(previous, current, {"participation"}):
        present.add("membership_or_participation_changed")
    if _basis_changed(previous, current, {"evidence"}):
        present.add("evidence_or_proficiency_basis_changed")
    if _basis_changed(previous, current, {"weighting"}):
        present.add("weighting_changed")
    if _basis_changed(previous, current, {"state_treatment", "reassessment"}):
        present.add("state_handling_changed")
    if _basis_changed(previous, current, {"rounding"}):
        present.add("rounding_changed")
    if (
        previous.algorithm_version != current.algorithm_version
        or _basis_changed(previous, current, {"algorithm"})
    ):
        present.add("algorithm_changed")
    if (
        previous.selected_override_reference
        != current.selected_override_reference
        or previous.override_replacement_grade
        != current.override_replacement_grade
    ):
        present.add("override_changed")
    if previous.override_applicability != current.override_applicability:
        present.add("override_applicability_changed")
    if (
        previous.base_freshness_status != current.base_freshness_status
        or previous.base_freshness_reasons != current.base_freshness_reasons
    ):
        present.add("freshness_changed")
    if previous.effective_grade != current.effective_grade:
        present.add("effective_grade_changed")
    if previous.effective_source != current.effective_source:
        present.add("effective_source_changed")
    return tuple(reason for reason in _CHANGE_REASON_ORDER if reason in present)


def _basis_changed(
    previous: GradePreviewObservation,
    current: GradePreviewObservation,
    dimensions: set[str],
) -> bool:
    return _basis_subset(previous.basis_entries, dimensions) != _basis_subset(
        current.basis_entries,
        dimensions,
    )


def _basis_subset(
    entries: tuple[GradePreviewBasisEntry, ...],
    dimensions: set[str],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (entry.dimension, entry.key, entry.sha256)
        for entry in entries
        if entry.dimension in dimensions
    )


def _require_material_changes_are_explained(
    previous: GradePreviewObservation,
    current: GradePreviewObservation,
    reasons: tuple[GradePreviewChangeReason, ...],
) -> None:
    semantic_reasons = {
        "calculation_family_changed",
        "policy_changed",
        "formula_changed",
        "membership_or_participation_changed",
        "evidence_or_proficiency_basis_changed",
        "weighting_changed",
        "state_handling_changed",
        "rounding_changed",
        "algorithm_changed",
    }
    if previous.inputs_sha256 != current.inputs_sha256 and not (
        semantic_reasons.intersection(reasons)
    ):
        raise GradePreviewComparisonError(
            "Grade inputs changed without a mapped semantic comparison reason."
        )
    if previous.calculation_fingerprint != current.calculation_fingerprint and not (
        semantic_reasons.intersection(reasons)
    ):
        raise GradePreviewComparisonError(
            "Grade calculation fingerprint changed without a mapped semantic reason."
        )


def _require_same_logical_scope(
    previous: GradePreviewTarget,
    current: GradePreviewTarget,
) -> None:
    if not isinstance(previous, GradePreviewTarget) or not isinstance(
        current,
        GradePreviewTarget,
    ):
        raise GradePreviewComparisonError(
            "comparison targets must be GradePreviewTarget values."
        )
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
    if previous_scope != current_scope:
        raise GradePreviewComparisonError(
            "prior and current Grade bases must identify the same logical scope."
        )


def _effective_delta(
    previous: Decimal | None,
    current: Decimal | None,
) -> Decimal | None:
    if previous is None or current is None:
        return None
    return _finite_decimal(current - previous, "effective_grade_delta")


def _target_to_dict(value: GradePreviewTarget | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
    }


def _finite_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise GradePreviewComparisonError(f"{field_name} must be a finite Decimal.")
    return value


def _optional_decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    decimal = _finite_decimal(value, "Decimal value")
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        return "0"
    return text


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "GradePreviewChangeReason",
    "GradePreviewComparison",
    "GradePreviewComparisonRelationship",
    "PriorReportingSnapshotGradeBasis",
    "compare_grade_preview_basis",
    "grade_preview_comparison_to_dict",
    "grade_preview_comparison_to_json_bytes",
    "prior_reporting_snapshot_grade_basis_from_observation",
    "prior_reporting_snapshot_grade_basis_to_dict",
    "prior_reporting_snapshot_grade_basis_to_json_bytes",
]
