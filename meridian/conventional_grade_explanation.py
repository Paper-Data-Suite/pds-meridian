"""Read-only conventional Grade explanation for Meridian v0.3 Issue #54.

This module explains one exact persisted conventional Grade result. It does not
select a Grade result, recalculate academic state, alter Grade Item selection,
apply a new override, create a ReportingSnapshot, or export data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeCalculationOutcome,
    ConventionalGradeCalculationStatus,
    ConventionalGradeCategoryStatus,
    ConventionalGradeItemAction,
    ConventionalGradeItemState,
    ConventionalGradeProvenanceKind,
    ConventionalGradeResultSnapshot,
    calculate_conventional_grade,
    conventional_grade_result_reference,
)
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_grade_item_revision,
)
from meridian.grade_items import GradeItemPurpose, GradeItemStatus
from meridian.grade_policy import (
    ConventionalGradeMode,
    GradePolicyItemReference,
    GradePolicyRevision,
)
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
    grade_preview_observation_from_explanation,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

ConventionalGradeExplanationReasonCode: TypeAlias = str
ConventionalGradeFormulaKind: TypeAlias = Literal[
    "total_points",
    "weighted_items",
    "weighted_categories",
]


@dataclass(frozen=True, slots=True)
class ConventionalGradeProvenanceExplanation:
    """One exact privacy-minimal upstream reference recorded by #50."""

    kind: ConventionalGradeProvenanceKind
    reference_key: str
    reference_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in {
            "source",
            "membership",
            "eligibility",
            "attempt_selection",
            "reassessment",
        }:
            raise GradePreviewTargetError(
                "unsupported conventional provenance kind."
            )
        if not isinstance(self.reference_key, str) or not self.reference_key:
            raise GradePreviewTargetError(
                "conventional provenance reference_key must be nonempty text."
            )
        _sha256(self.reference_sha256, "conventional provenance digest")


@dataclass(frozen=True, slots=True)
class ConventionalGradeItemIdentityExplanation:
    """Exact historical Grade Item identity named by the Grade policy."""

    reference: GradePolicyItemReference
    title: str
    purpose: GradeItemPurpose
    status: GradeItemStatus

    def __post_init__(self) -> None:
        if not isinstance(self.reference, GradePolicyItemReference):
            raise GradePreviewTargetError(
                "Grade Item explanation requires GradePolicyItemReference."
            )
        if not isinstance(self.title, str) or not self.title:
            raise GradePreviewTargetError("Grade Item title must be nonempty text.")
        if self.purpose not in {
            "standards_proficiency",
            "conventional_grade",
            "standards_and_conventional",
            "reporting_only",
        }:
            raise GradePreviewTargetError("unsupported Grade Item purpose.")
        if self.status not in {"active", "archived"}:
            raise GradePreviewTargetError("unsupported Grade Item status.")


@dataclass(frozen=True, slots=True)
class ConventionalGradeItemExplanation:
    """One exact policy-participating Grade Item and its Grade consequence."""

    grade_item: ConventionalGradeItemIdentityExplanation
    category_id: str | None
    weight: Decimal | None
    policy_possible_points: Decimal | None
    source_state: ConventionalGradeItemState
    action: ConventionalGradeItemAction
    earned: Decimal | None
    possible: Decimal | None
    percentage: Decimal | None
    contribution: Decimal | None
    reason_codes: tuple[str, ...]
    provenance: tuple[ConventionalGradeProvenanceExplanation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.grade_item, ConventionalGradeItemIdentityExplanation):
            raise GradePreviewTargetError(
                "grade_item must be ConventionalGradeItemIdentityExplanation."
            )
        for field_name in (
            "weight",
            "policy_possible_points",
            "possible",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be a positive finite Decimal when present."
                )
        for field_name in ("earned", "percentage", "contribution"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be a finite Decimal when present."
                )
        if self.source_state not in {
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
        }:
            raise GradePreviewTargetError("unsupported conventional source state.")
        if self.action not in {"contribute", "exclude", "blocking", "zero"}:
            raise GradePreviewTargetError("unsupported conventional Grade action.")
        reasons = _reason_codes(self.reason_codes)
        provenance = tuple(self.provenance)
        if any(
            not isinstance(item, ConventionalGradeProvenanceExplanation)
            for item in provenance
        ):
            raise GradePreviewTargetError(
                "provenance must contain ConventionalGradeProvenanceExplanation."
            )
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True)
class ConventionalGradeCategoryExplanation:
    """One configured weighted category and exact calculated category result."""

    category_id: str
    title: str
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
        if not isinstance(self.category_id, str) or not self.category_id:
            raise GradePreviewTargetError("category_id must be nonempty text.")
        if not isinstance(self.title, str) or not self.title:
            raise GradePreviewTargetError("category title must be nonempty text.")
        if (
            not isinstance(self.weight, Decimal)
            or not self.weight.is_finite()
            or self.weight <= 0
        ):
            raise GradePreviewTargetError("category weight must be positive Decimal.")
        if self.status not in {"calculated", "blocked", "noncalculable"}:
            raise GradePreviewTargetError("unsupported category status.")
        if len(set(self.included_grade_item_ids)) != len(
            self.included_grade_item_ids
        ):
            raise GradePreviewTargetError(
                "included_grade_item_ids must not contain duplicates."
            )
        if len(set(self.excluded_grade_item_ids)) != len(
            self.excluded_grade_item_ids
        ):
            raise GradePreviewTargetError(
                "excluded_grade_item_ids must not contain duplicates."
            )
        for field_name in ("earned", "fraction", "contribution"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"category {field_name} must be finite Decimal when present."
                )
        if self.possible is not None and (
            not isinstance(self.possible, Decimal)
            or not self.possible.is_finite()
            or self.possible <= 0
        ):
            raise GradePreviewTargetError(
                "category possible must be positive Decimal when present."
            )
        object.__setattr__(self, "reason_codes", _reason_codes(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ConventionalGradeReasonExplanation:
    """One structured top-level conventional Grade reason."""

    code: ConventionalGradeExplanationReasonCode
    grade_item: GradePolicyItemReference | None
    category_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise GradePreviewTargetError("reason code must be nonempty text.")
        if self.grade_item is not None and not isinstance(
            self.grade_item,
            GradePolicyItemReference,
        ):
            raise GradePreviewTargetError(
                "reason grade_item must be GradePolicyItemReference or None."
            )
        if self.category_id is not None and (
            not isinstance(self.category_id, str) or not self.category_id
        ):
            raise GradePreviewTargetError(
                "reason category_id must be nonempty text when present."
            )


@dataclass(frozen=True, slots=True)
class ConventionalGradeFormulaExplanation:
    """Exact family formula values persisted by #50."""

    mode: ConventionalGradeFormulaKind
    total_earned: Decimal | None
    total_possible: Decimal | None
    final_fraction: Decimal | None
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None

    def __post_init__(self) -> None:
        if self.mode not in {
            "total_points",
            "weighted_items",
            "weighted_categories",
        }:
            raise GradePreviewTargetError("unsupported conventional Grade mode.")
        for field_name in (
            "total_earned",
            "final_fraction",
            "unrounded_grade",
            "rounded_grade",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise GradePreviewTargetError(
                    f"{field_name} must be finite Decimal when present."
                )
        if self.total_possible is not None and (
            not isinstance(self.total_possible, Decimal)
            or not self.total_possible.is_finite()
            or self.total_possible <= 0
        ):
            raise GradePreviewTargetError(
                "total_possible must be positive Decimal when present."
            )


@dataclass(frozen=True, slots=True)
class ConventionalGradeBreakdownExplanation:
    """Family detail reusable by standalone and embedded hybrid previews."""

    status: ConventionalGradeCalculationStatus
    mode: ConventionalGradeMode
    items: tuple[ConventionalGradeItemExplanation, ...]
    categories: tuple[ConventionalGradeCategoryExplanation, ...]
    formula: ConventionalGradeFormulaExplanation
    reasons: tuple[ConventionalGradeReasonExplanation, ...]

    def __post_init__(self) -> None:
        if self.status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError("unsupported conventional Grade status.")
        if self.mode not in {
            "total_points",
            "weighted_items",
            "weighted_categories",
        }:
            raise GradePreviewTargetError("unsupported conventional Grade mode.")
        items = tuple(self.items)
        categories = tuple(self.categories)
        reasons = tuple(self.reasons)
        if any(
            not isinstance(item, ConventionalGradeItemExplanation) for item in items
        ):
            raise GradePreviewTargetError(
                "items must contain ConventionalGradeItemExplanation values."
            )
        if any(
            not isinstance(category, ConventionalGradeCategoryExplanation)
            for category in categories
        ):
            raise GradePreviewTargetError(
                "categories must contain ConventionalGradeCategoryExplanation."
            )
        if any(
            not isinstance(reason, ConventionalGradeReasonExplanation)
            for reason in reasons
        ):
            raise GradePreviewTargetError(
                "reasons must contain ConventionalGradeReasonExplanation values."
            )
        if not isinstance(self.formula, ConventionalGradeFormulaExplanation):
            raise GradePreviewTargetError(
                "formula must be ConventionalGradeFormulaExplanation."
            )
        if self.formula.mode != self.mode:
            raise GradePreviewIntegrityError(
                "conventional formula mode must match explanation mode."
            )
        if self.mode == "weighted_categories" and not categories:
            raise GradePreviewIntegrityError(
                "weighted_categories explanation requires category results."
            )
        if self.mode != "weighted_categories" and categories:
            raise GradePreviewIntegrityError(
                "non-category conventional mode must not expose categories."
            )
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "categories", categories)
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class ConventionalGradePreviewExplanation:
    """Rich conventional breakdown layered over the common #54 explanation."""

    common: GradePreviewExplanation
    mode: ConventionalGradeMode
    items: tuple[ConventionalGradeItemExplanation, ...]
    categories: tuple[ConventionalGradeCategoryExplanation, ...]
    formula: ConventionalGradeFormulaExplanation
    reasons: tuple[ConventionalGradeReasonExplanation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.common, GradePreviewExplanation):
            raise GradePreviewTargetError("common must be GradePreviewExplanation.")
        if self.common.target.calculation_family != "conventional":
            raise GradePreviewIntegrityError(
                "conventional explanation requires conventional common target."
            )
        breakdown = ConventionalGradeBreakdownExplanation(
            status=self.common.base_result_status,  # type: ignore[arg-type]
            mode=self.mode,
            items=self.items,
            categories=self.categories,
            formula=self.formula,
            reasons=self.reasons,
        )
        object.__setattr__(self, "items", breakdown.items)
        object.__setattr__(self, "categories", breakdown.categories)
        object.__setattr__(self, "reasons", breakdown.reasons)



def explain_conventional_grade_breakdown(
    workspace_root: str | Path,
    inputs: ConventionalGradeCalculationInput,
    outcome: ConventionalGradeCalculationOutcome,
) -> ConventionalGradeBreakdownExplanation:
    """Explain one exact conventional calculation basis without current state."""

    if not isinstance(inputs, ConventionalGradeCalculationInput):
        raise GradePreviewTargetError(
            "inputs must be ConventionalGradeCalculationInput."
        )
    if not isinstance(outcome, ConventionalGradeCalculationOutcome):
        raise GradePreviewTargetError(
            "outcome must be ConventionalGradeCalculationOutcome."
        )
    try:
        exact_outcome = calculate_conventional_grade(inputs)
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"embedded conventional calculation is invalid: {error}"
        ) from error
    if exact_outcome != outcome:
        raise GradePreviewIntegrityError(
            "conventional outcome does not reproduce from exact embedded inputs."
        )
    item_explanations = tuple(
        _item_explanation(workspace_root, result)
        for result in outcome.item_results
    )
    category_titles = {
        category.category_id: category.title
        for category in inputs.configuration.categories
    }
    category_explanations = tuple(
        _category_explanation(category, category_titles)
        for category in outcome.category_results
    )
    reason_explanations = tuple(
        ConventionalGradeReasonExplanation(
            code=reason.code,
            grade_item=reason.grade_item,
            category_id=reason.category_id,
        )
        for reason in outcome.reasons
    )
    formula = ConventionalGradeFormulaExplanation(
        mode=outcome.mode,  # type: ignore[arg-type]
        total_earned=outcome.total_earned,
        total_possible=outcome.total_possible,
        final_fraction=outcome.final_fraction,
        unrounded_grade=outcome.unrounded_grade,
        rounded_grade=outcome.rounded_grade,
    )
    return ConventionalGradeBreakdownExplanation(
        status=outcome.status,
        mode=outcome.mode,  # type: ignore[arg-type]
        items=item_explanations,
        categories=category_explanations,
        formula=formula,
        reasons=reason_explanations,
    )


def explain_conventional_grade_preview(
    workspace_root: str | Path,
    snapshot: ConventionalGradeResultSnapshot,
    *,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    effective: EffectiveGradeResolution,
) -> ConventionalGradePreviewExplanation:
    """Explain one exact persisted conventional Grade result without mutation."""

    if not isinstance(snapshot, ConventionalGradeResultSnapshot):
        raise GradePreviewTargetError(
            "snapshot must be ConventionalGradeResultSnapshot."
        )
    try:
        snapshot.__post_init__()
        result_reference = conventional_grade_result_reference(snapshot)
    except ValueError as error:
        raise GradePreviewIntegrityError(
            f"conventional Grade result is invalid: {error}"
        ) from error

    source_reference = GradeOverrideSourceResultReference(
        "conventional",
        result_reference,
    )
    target = GradePreviewTarget(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        target_period=snapshot.target_period,
        calendar_revision=snapshot.calendar_revision,
        calculation_family="conventional",
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

    breakdown = explain_conventional_grade_breakdown(
        workspace_root,
        snapshot.inputs,
        outcome,
    )
    return ConventionalGradePreviewExplanation(
        common=common,
        mode=breakdown.mode,
        items=breakdown.items,
        categories=breakdown.categories,
        formula=breakdown.formula,
        reasons=breakdown.reasons,
    )


def conventional_grade_observation(
    value: ConventionalGradePreviewExplanation,
) -> GradePreviewObservation:
    """Project conventional detail into the stable #54 observation handoff."""

    if not isinstance(value, ConventionalGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be ConventionalGradePreviewExplanation."
        )
    return grade_preview_observation_from_explanation(
        value.common,
        extra_basis_entries=conventional_grade_basis_entries(value),
    )


def conventional_grade_basis_entries(
    value: ConventionalGradePreviewExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    """Return privacy-minimized semantic hashes used by later comparison."""

    if not isinstance(value, ConventionalGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be ConventionalGradePreviewExplanation."
        )
    return _conventional_grade_basis_entries(
        value.mode, value.items, value.categories
    )


def conventional_grade_breakdown_basis_entries(
    value: ConventionalGradeBreakdownExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    """Return comparison hashes for an embedded conventional component."""

    if not isinstance(value, ConventionalGradeBreakdownExplanation):
        raise GradePreviewTargetError(
            "value must be ConventionalGradeBreakdownExplanation."
        )
    return _conventional_grade_basis_entries(
        value.mode, value.items, value.categories
    )


def _conventional_grade_basis_entries(
    mode: ConventionalGradeMode,
    items: tuple[ConventionalGradeItemExplanation, ...],
    categories: tuple[ConventionalGradeCategoryExplanation, ...],
) -> tuple[GradePreviewBasisEntry, ...]:
    participation = [
        {
            "reference": _item_reference_to_dict(item.grade_item.reference),
            "category_id": item.category_id,
            "policy_possible_points": _decimal_text(item.policy_possible_points),
        }
        for item in items
    ]
    weighting = {
        "items": [
            {
                "grade_item_id": item.grade_item.reference.grade_item_id,
                "weight": _decimal_text(item.weight),
            }
            for item in items
        ],
        "categories": [
            {
                "category_id": category.category_id,
                "weight": _decimal_text(category.weight),
            }
            for category in categories
        ],
    }
    evidence = [
        {
            "grade_item_id": item.grade_item.reference.grade_item_id,
            "source_state": item.source_state,
            "action": item.action,
            "earned": _decimal_text(item.earned),
            "possible": _decimal_text(item.possible),
            "reason_codes": list(item.reason_codes),
            "provenance": [
                {
                    "kind": reference.kind,
                    "reference_key": reference.reference_key,
                    "reference_sha256": reference.reference_sha256,
                }
                for reference in item.provenance
            ],
        }
        for item in items
    ]
    return (
        GradePreviewBasisEntry(
            "formula",
            "conventional_formula",
            _semantic_digest({"mode": mode}),
        ),
        GradePreviewBasisEntry(
            "participation",
            "conventional_participation",
            _semantic_digest(participation),
        ),
        GradePreviewBasisEntry(
            "evidence",
            "conventional_evidence_basis",
            _semantic_digest(evidence),
        ),
        GradePreviewBasisEntry(
            "weighting",
            "conventional_weighting",
            _semantic_digest(weighting),
        ),
    )



def conventional_grade_breakdown_to_dict(
    value: ConventionalGradeBreakdownExplanation,
) -> dict[str, object]:
    """Serialize one embedded conventional breakdown deterministically."""

    if not isinstance(value, ConventionalGradeBreakdownExplanation):
        raise GradePreviewTargetError(
            "value must be ConventionalGradeBreakdownExplanation."
        )
    return {
        "status": value.status,
        "mode": value.mode,
        "items": [_item_to_dict(item) for item in value.items],
        "categories": [_category_to_dict(item) for item in value.categories],
        "formula": _formula_to_dict(value.formula),
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def conventional_grade_preview_explanation_to_dict(
    value: ConventionalGradePreviewExplanation,
) -> dict[str, object]:
    """Serialize conventional explanation detail to deterministic JSON-native data."""

    if not isinstance(value, ConventionalGradePreviewExplanation):
        raise GradePreviewTargetError(
            "value must be ConventionalGradePreviewExplanation."
        )
    from meridian.grade_preview_explanation import grade_preview_explanation_to_dict

    return {
        "common": grade_preview_explanation_to_dict(value.common),
        "mode": value.mode,
        "items": [_item_to_dict(item) for item in value.items],
        "categories": [_category_to_dict(item) for item in value.categories],
        "formula": _formula_to_dict(value.formula),
        "reasons": [_reason_to_dict(reason) for reason in value.reasons],
    }


def _item_explanation(
    workspace_root: str | Path,
    result: object,
) -> ConventionalGradeItemExplanation:
    from meridian.conventional_grade import ConventionalGradeItemResult

    if not isinstance(result, ConventionalGradeItemResult):
        raise GradePreviewIntegrityError(
            "conventional outcome contains an invalid Grade Item result."
        )
    reference = result.grade_item
    try:
        stored = load_grade_item_revision(
            workspace_root,
            reference.class_id,
            reference.grade_item_id,
            reference.grade_item_revision,
        )
    except GradeItemStorageError as error:
        raise GradePreviewIntegrityError(
            "exact Grade Item revision required by conventional Grade could not "
            f"be verified: {error}"
        ) from error
    if stored.revision_sha256 != reference.grade_item_revision_sha256:
        raise GradePreviewIntegrityError(
            "exact Grade Item revision digest does not match Grade policy."
        )
    revision = stored.revision
    if (
        revision.class_id != reference.class_id
        or revision.grade_item_id != reference.grade_item_id
        or revision.grade_item_revision != reference.grade_item_revision
    ):
        raise GradePreviewIntegrityError(
            "loaded Grade Item revision identity does not match Grade policy."
        )
    provenance = tuple(
        ConventionalGradeProvenanceExplanation(
            kind=item.kind,
            reference_key=item.reference_key,
            reference_sha256=item.reference_sha256,
        )
        for item in result.provenance
    )
    return ConventionalGradeItemExplanation(
        grade_item=ConventionalGradeItemIdentityExplanation(
            reference=reference,
            title=revision.title,
            purpose=revision.purpose,
            status=revision.status,
        ),
        category_id=result.category_id,
        weight=result.weight,
        policy_possible_points=result.policy_possible_points,
        source_state=result.source_state,
        action=result.action,
        earned=result.earned,
        possible=result.possible,
        percentage=result.percentage,
        contribution=result.contribution,
        reason_codes=result.reason_codes,
        provenance=provenance,
    )


def _category_explanation(
    result: object,
    titles: dict[str, str],
) -> ConventionalGradeCategoryExplanation:
    from meridian.conventional_grade import ConventionalGradeCategoryResult

    if not isinstance(result, ConventionalGradeCategoryResult):
        raise GradePreviewIntegrityError(
            "conventional outcome contains an invalid category result."
        )
    title = titles.get(result.category_id)
    if title is None:
        raise GradePreviewIntegrityError(
            "conventional category result is absent from exact policy configuration."
        )
    return ConventionalGradeCategoryExplanation(
        category_id=result.category_id,
        title=title,
        weight=result.weight,
        status=result.status,
        included_grade_item_ids=result.included_grade_item_ids,
        excluded_grade_item_ids=result.excluded_grade_item_ids,
        earned=result.earned,
        possible=result.possible,
        fraction=result.fraction,
        contribution=result.contribution,
        reason_codes=result.reason_codes,
    )


def _item_to_dict(value: ConventionalGradeItemExplanation) -> dict[str, object]:
    return {
        "grade_item": {
            "reference": _item_reference_to_dict(value.grade_item.reference),
            "title": value.grade_item.title,
            "purpose": value.grade_item.purpose,
            "status": value.grade_item.status,
        },
        "category_id": value.category_id,
        "weight": _decimal_text(value.weight),
        "policy_possible_points": _decimal_text(value.policy_possible_points),
        "source_state": value.source_state,
        "action": value.action,
        "earned": _decimal_text(value.earned),
        "possible": _decimal_text(value.possible),
        "percentage": _decimal_text(value.percentage),
        "contribution": _decimal_text(value.contribution),
        "reason_codes": list(value.reason_codes),
        "provenance": [
            {
                "kind": item.kind,
                "reference_key": item.reference_key,
                "reference_sha256": item.reference_sha256,
            }
            for item in value.provenance
        ],
    }


def _category_to_dict(
    value: ConventionalGradeCategoryExplanation,
) -> dict[str, object]:
    return {
        "category_id": value.category_id,
        "title": value.title,
        "weight": _decimal_text(value.weight),
        "status": value.status,
        "included_grade_item_ids": list(value.included_grade_item_ids),
        "excluded_grade_item_ids": list(value.excluded_grade_item_ids),
        "earned": _decimal_text(value.earned),
        "possible": _decimal_text(value.possible),
        "fraction": _decimal_text(value.fraction),
        "contribution": _decimal_text(value.contribution),
        "reason_codes": list(value.reason_codes),
    }


def _formula_to_dict(
    value: ConventionalGradeFormulaExplanation,
) -> dict[str, object]:
    return {
        "mode": value.mode,
        "total_earned": _decimal_text(value.total_earned),
        "total_possible": _decimal_text(value.total_possible),
        "final_fraction": _decimal_text(value.final_fraction),
        "unrounded_grade": _decimal_text(value.unrounded_grade),
        "rounded_grade": _decimal_text(value.rounded_grade),
    }


def _reason_to_dict(
    value: ConventionalGradeReasonExplanation,
) -> dict[str, object]:
    return {
        "code": value.code,
        "grade_item": (
            _item_reference_to_dict(value.grade_item)
            if value.grade_item is not None
            else None
        ),
        "category_id": value.category_id,
    }


def _item_reference_to_dict(value: GradePolicyItemReference) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "grade_item_revision_sha256": value.grade_item_revision_sha256,
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
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise GradePreviewTargetError(f"{field_name} must be SHA-256 text.")
    if any(character not in "0123456789abcdef" for character in value):
        raise GradePreviewTargetError(
            f"{field_name} must be lowercase SHA-256 text."
        )
    return value
