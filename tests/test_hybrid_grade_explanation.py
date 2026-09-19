from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import meridian.hybrid_grade_explanation as hybrid_explanation
from meridian.conventional_grade import calculate_conventional_grade
from meridian.conventional_grade_explanation import (
    ConventionalGradeBreakdownExplanation,
    ConventionalGradeFormulaExplanation,
    explain_conventional_grade_breakdown,
)
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_preview_explanation import GradePreviewIntegrityError
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_explanation import (
    explain_hybrid_grade_preview,
    hybrid_grade_observation,
    hybrid_grade_preview_explanation_to_json_bytes,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_explanation import (
    StandardsGradeBreakdownExplanation,
    StandardsGradeConversionExplanation,
    StandardsGradeFormulaExplanation,
    StandardsGradeScaleExplanation,
    explain_standards_grade_breakdown,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference
from tests.issue52_hybrid_test_support import (
    NOW,
    activation,
    conventional_input,
    hybrid_input,
    policy,
    standards_input,
    treatment,
)


def _snapshot(
    *,
    conventional_earned: str | None = "92",
    conventional_state: str = "points",
    standards_status: str = "calculated",
    standards_grade_value: str = "88",
    conventional_weight: str = "0.7",
    standards_weight: str = "0.3",
    quantum: str = "0.01",
    state_treatment=None,
):
    value = policy(
        conventional_weight=conventional_weight,
        standards_weight=standards_weight,
        standards_grade_value=standards_grade_value,
        state_treatment=state_treatment,
        quantum=quantum,
    )
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(
            value,
            decision,
            earned=conventional_earned,
            state=conventional_state,
        ),
        standards_input(value, decision, status=standards_status),
    )
    outcome = calculate_hybrid_grade(inputs)
    snapshot = create_hybrid_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    return value, decision, snapshot


def _effective(snapshot) -> EffectiveGradeResolution:
    content = hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    reference = HybridGradeResultReference(
        class_id=snapshot.class_id,
        student_id=snapshot.student_id,
        school_year=snapshot.target_period.school_year,
        period_id=snapshot.target_period.period_id,
        calendar_revision=snapshot.calendar_revision,
        result_revision=snapshot.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )
    source = GradeOverrideSourceResultReference("hybrid", reference)
    grade = snapshot.outcome.rounded_grade
    return EffectiveGradeResolution(
        base_result_family="hybrid",
        base_result_reference=source,
        base_result_status=snapshot.outcome.status,
        base_grade=grade,
        base_freshness_status="current",
        base_freshness_reasons=(),
        selected_override_reference=None,
        override_decision=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=grade,
        effective_source="base" if grade is not None else "none",
    )


def _conventional_breakdown(outcome) -> ConventionalGradeBreakdownExplanation:
    return ConventionalGradeBreakdownExplanation(
        status=outcome.status,
        mode=outcome.mode,
        items=(),
        categories=(),
        formula=ConventionalGradeFormulaExplanation(
            mode=outcome.mode,
            total_earned=outcome.total_earned,
            total_possible=outcome.total_possible,
            final_fraction=outcome.final_fraction,
            unrounded_grade=outcome.unrounded_grade,
            rounded_grade=outcome.rounded_grade,
        ),
        reasons=(),
    )


def _standards_breakdown(inputs, outcome) -> StandardsGradeBreakdownExplanation:
    return StandardsGradeBreakdownExplanation(
        status=outcome.status,
        target_scale=StandardsGradeScaleExplanation(
            inputs.configuration.target_scale
        ),
        conversions=tuple(
            StandardsGradeConversionExplanation(
                item.proficiency_level_id,
                item.grade_value,
            )
            for item in inputs.configuration.conversions
        ),
        standards=(),
        formula=StandardsGradeFormulaExplanation(
            aggregation_strategy=outcome.aggregation_strategy,
            minimum_calculated_results=outcome.minimum_calculated_results,
            actual_calculated_result_count=(
                outcome.actual_calculated_result_count
            ),
            active_weight=outcome.active_weight,
            weighted_numerator=outcome.weighted_numerator,
            unrounded_grade=outcome.unrounded_grade,
            rounded_grade=outcome.rounded_grade,
        ),
        reasons=(),
    )


def _stub_component_builders(
    monkeypatch: pytest.MonkeyPatch,
    snapshot,
) -> dict[str, object]:
    calls: dict[str, object] = {}

    def conventional_builder(root, inputs, outcome):
        calls["conventional_root"] = root
        calls["conventional_inputs"] = inputs
        calls["conventional_outcome"] = outcome
        return _conventional_breakdown(outcome)

    def standards_builder(root, inputs, outcome):
        calls["standards_root"] = root
        calls["standards_inputs"] = inputs
        calls["standards_outcome"] = outcome
        return _standards_breakdown(inputs, outcome)

    monkeypatch.setattr(
        hybrid_explanation,
        "explain_conventional_grade_breakdown",
        conventional_builder,
    )
    monkeypatch.setattr(
        hybrid_explanation,
        "explain_standards_grade_breakdown",
        standards_builder,
    )
    return calls


def test_hybrid_uses_exact_embedded_components_and_unrounded_math(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot()
    calls = _stub_component_builders(monkeypatch, snapshot)

    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    assert calls["conventional_inputs"] is snapshot.inputs.conventional
    assert calls["standards_inputs"] is snapshot.inputs.standards_based
    assert explanation.conventional_component.unrounded_grade == Decimal("92")
    assert explanation.standards_component.unrounded_grade == Decimal("88")
    assert explanation.conventional_component.weighted_contribution == Decimal(
        "64.4"
    )
    assert explanation.standards_component.weighted_contribution == Decimal(
        "26.4"
    )
    assert explanation.formula.weighted_numerator == Decimal("90.8")
    assert explanation.formula.unrounded_grade == Decimal("90.8")
    assert explanation.formula.rounded_grade == Decimal("90.80")
    assert explanation.common.base_grade == Decimal("90.80")


def test_hybrid_final_rounding_does_not_use_component_rounded_grades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot(
        conventional_earned="60",
        standards_grade_value="61.5",
        quantum="1",
    )
    _stub_component_builders(monkeypatch, snapshot)

    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    assert explanation.formula.weighted_numerator == Decimal("60.45")
    assert explanation.formula.unrounded_grade == Decimal("60.45")
    assert explanation.formula.rounded_grade == Decimal("60")
    assert explanation.standards_component.breakdown.formula.rounded_grade == (
        Decimal("62")
    )


def test_insufficient_component_exclusion_is_visible_and_renormalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = treatment(missing="exclude", insufficient_evidence="exclude")
    value, decision, snapshot = _snapshot(
        conventional_earned="82",
        standards_status="missing",
        state_treatment=state,
    )
    _stub_component_builders(monkeypatch, snapshot)

    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    assert explanation.status == "calculated"
    assert explanation.standards_component.source_status == "insufficient"
    assert explanation.standards_component.action == "exclude"
    assert explanation.formula.active_weight == Decimal("0.7")
    assert explanation.formula.weighted_numerator == Decimal("57.4")
    assert explanation.formula.unrounded_grade == Decimal("82")
    assert explanation.formula.rounded_grade == Decimal("82.00")


def test_blocking_component_keeps_hybrid_nonnumeric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot(standards_status="missing")
    _stub_component_builders(monkeypatch, snapshot)

    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    assert explanation.status == "blocked"
    assert explanation.standards_component.action == "blocking"
    assert explanation.formula.active_weight is None
    assert explanation.formula.unrounded_grade is None
    assert explanation.formula.rounded_grade is None
    assert explanation.common.effective_source == "none"
    assert explanation.reasons[0].code == "blocking_component"
    assert explanation.reasons[0].component_kind == "standards_based"


def test_component_fingerprint_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot()
    _stub_component_builders(monkeypatch, snapshot)
    exact = calculate_conventional_grade(snapshot.inputs.conventional)
    changed = replace(exact, calculation_fingerprint="f" * 64)
    monkeypatch.setattr(
        hybrid_explanation,
        "calculate_conventional_grade",
        lambda inputs: changed,
    )

    with pytest.raises(GradePreviewIntegrityError, match="fingerprint"):
        explain_hybrid_grade_preview(
            Path("unused"),
            snapshot,
            policy=value,
            activation=decision,
            effective=_effective(snapshot),
        )


def test_observation_has_four_hybrid_comparison_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot()
    _stub_component_builders(monkeypatch, snapshot)
    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    observation = hybrid_grade_observation(explanation)
    hybrid_entries = tuple(
        entry for entry in observation.basis_entries if entry.key.startswith("hybrid_")
    )

    assert tuple(entry.dimension for entry in hybrid_entries) == (
        "evidence",
        "formula",
        "participation",
        "weighting",
    )
    assert tuple(entry.key for entry in hybrid_entries) == (
        "hybrid_component_basis",
        "hybrid_formula",
        "hybrid_participation",
        "hybrid_weighting",
    )


def test_json_preserves_decimal_text_and_nested_breakdowns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = _snapshot()
    _stub_component_builders(monkeypatch, snapshot)
    explanation = explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=_effective(snapshot),
    )

    encoded = hybrid_grade_preview_explanation_to_json_bytes(explanation)

    assert encoded.endswith(b"\n")
    assert b'"weighted_numerator": "90.8"' in encoded
    assert b'"configured_weight": "0.7"' in encoded
    assert b'"breakdown"' in encoded


def test_conventional_breakdown_rejects_nonreproducing_outcome() -> None:
    value, decision, snapshot = _snapshot()
    del value, decision
    exact = calculate_conventional_grade(snapshot.inputs.conventional)
    changed = replace(exact, rounded_grade=Decimal("99"))

    with pytest.raises(GradePreviewIntegrityError, match="does not reproduce"):
        explain_conventional_grade_breakdown(
            Path("unused"),
            snapshot.inputs.conventional,
            changed,
        )


def test_standards_breakdown_rejects_nonreproducing_outcome() -> None:
    value, decision, snapshot = _snapshot()
    del value, decision
    exact = calculate_standards_grade(snapshot.inputs.standards_based)
    changed = replace(exact, rounded_grade=Decimal("99"))

    with pytest.raises(GradePreviewIntegrityError, match="does not reproduce"):
        explain_standards_grade_breakdown(
            Path("unused"),
            snapshot.inputs.standards_based,
            changed,
        )
