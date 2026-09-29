from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

import meridian.standards_grade_explanation as explanation
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
)
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewBasisEntry,
    GradePreviewObservation,
    GradePreviewTarget,
)
from meridian.standards_grade import (
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import GradeOverrideSourceResultReference
from tests.test_issue99_profile_grade_integration import (
    CLASS_ID,
    PERIOD,
    STD_A,
    STD_B,
    STUDENT_ID,
    activation,
    all_meeting,
    policy,
    profile_config,
    scale,
    standard,
)


def _profile_basis(
    *,
    second_level: str | None = "meeting",
    second_status: str = "calculated",
):
    configuration = profile_config(
        conversions=(("meeting", "87"), ("exceeding", "97")),
        high_predicate=all_meeting(),
    )
    grade_policy = policy(configuration)
    inputs = create_standards_grade_calculation_input(
        policy=grade_policy,
        activation=activation(grade_policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(
            standard(configuration.standards[0], "meeting"),
            standard(
                configuration.standards[1],
                second_level,
                status=second_status,
            ),
        ),
        target_scale_definition=scale(),
    )
    return inputs, calculate_standards_grade(inputs)


def _stub_standard(result) -> explanation.StandardsGradeStandardExplanation:
    return explanation.StandardsGradeStandardExplanation(
        standard_id=result.standard_id,
        weight=result.weight,
        source_state=result.source_state,
        action=result.action,
        result_reference=None,
        result_algorithm_version=None,
        result_calculation_fingerprint=None,
        target_scale=None,
        proficiency_level_id=result.proficiency_level_id,
        converted_grade_value=result.converted_grade_value,
        calculation_value=result.calculation_value,
        weighted_contribution=result.weighted_contribution,
        freshness_status=None,
        freshness_reasons=(),
        reason_codes=result.reason_codes,
        nested_proficiency_explanation=None,
    )


def test_profile_breakdown_exposes_base_policy_predicates_band_and_adjustment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, outcome = _profile_basis()
    monkeypatch.setattr(
        explanation,
        "_standard_explanation",
        lambda _root, result: _stub_standard(result),
    )

    breakdown = explanation.explain_standards_grade_breakdown(
        ".",
        inputs,
        outcome,
    )
    formula = breakdown.formula

    assert formula.aggregation_strategy == "profile_constrained_mean"
    assert formula.base_unrounded_grade == Decimal("87")
    assert formula.unrounded_grade == Decimal("90")
    assert formula.rounded_grade == Decimal("90.00")
    assert formula.profile_constraints == inputs.configuration.profile_constraints
    assert formula.profile_evaluation == outcome.profile_evaluation
    assert formula.selected_profile_band_id == "high"
    assert formula.selected_profile_band_minimum_grade == Decimal("90")
    assert formula.selected_profile_band_maximum_grade == Decimal("100")
    assert formula.profile_adjustment == "floor"
    assert formula.profile_evaluation is not None
    predicate = formula.profile_evaluation.bands[0].predicates[0]
    assert predicate.status == "matched"
    assert predicate.at_or_above_standard_ids == (STD_A, STD_B)

    payload = explanation.standards_grade_breakdown_to_dict(breakdown)
    serialized_formula = payload["formula"]
    assert serialized_formula["base_unrounded_grade"] == "87"
    assert serialized_formula["selected_profile_band_id"] == "high"
    assert serialized_formula["profile_adjustment"] == "floor"
    assert serialized_formula["profile_constraints"]["fallback_band_id"] == (
        "fallback"
    )
    assert (
        serialized_formula["profile_evaluation"]["bands"][0]["predicates"][0][
            "status"
        ]
        == "matched"
    )

    keys = {
        (entry.dimension, entry.key)
        for entry in explanation.standards_grade_breakdown_basis_entries(
            breakdown
        )
    }
    assert keys == {
        ("formula", "standards_formula"),
        ("participation", "standards_participation"),
        ("evidence", "standards_proficiency_basis"),
        ("weighting", "standards_weighting"),
        ("formula", "standards_profile_policy"),
        ("formula", "standards_base_mean"),
        ("evidence", "standards_profile_predicates"),
        ("evidence", "standards_profile_band"),
        ("formula", "standards_profile_adjustment"),
    }


def test_indeterminate_profile_explanation_identifies_unknown_standard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, outcome = _profile_basis(
        second_level=None,
        second_status="missing",
    )
    monkeypatch.setattr(
        explanation,
        "_standard_explanation",
        lambda _root, result: _stub_standard(result),
    )

    breakdown = explanation.explain_standards_grade_breakdown(
        ".",
        inputs,
        outcome,
    )
    formula = breakdown.formula

    assert breakdown.status == "insufficient"
    assert formula.base_unrounded_grade == Decimal("87")
    assert formula.unrounded_grade is None
    assert formula.profile_evaluation is not None
    high = formula.profile_evaluation.bands[0]
    assert high.status == "indeterminate"
    assert high.predicates[0].unknown_standard_ids == (STD_B,)
    assert formula.selected_profile_band_id is None
    assert formula.profile_adjustment is None


def _observation(
    entry: GradePreviewBasisEntry,
    *,
    inputs_sha256: str = "c" * 64,
    calculation_fingerprint: str = "b" * 64,
) -> GradePreviewObservation:
    return GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=GradePreviewTarget(
            class_id=CLASS_ID,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            calculation_family="standards_based",
        ),
        base_result_reference=GradeOverrideSourceResultReference(
            "standards_based",
            StandardsGradeResultReference(
                class_id=CLASS_ID,
                student_id=STUDENT_ID,
                school_year=PERIOD.school_year,
                period_id=PERIOD.period_id,
                calendar_revision=1,
                result_revision=1,
                result_sha256="a" * 64,
            ),
        ),
        base_result_status="calculated",
        base_grade=Decimal("90"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        algorithm_version="2",
        calculation_fingerprint=calculation_fingerprint,
        inputs_sha256=inputs_sha256,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            1,
            "d" * 64,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "course_grade_policy",
            1,
            "e" * 64,
        ),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=Decimal("90"),
        effective_source="base",
        basis_entries=(entry,),
    )


@pytest.mark.parametrize(
    ("dimension", "key", "reason"),
    (
        ("formula", "standards_base_mean", "base_mean_changed"),
        ("formula", "standards_profile_policy", "profile_policy_changed"),
        (
            "evidence",
            "standards_profile_predicates",
            "profile_predicates_changed",
        ),
        ("evidence", "standards_profile_band", "profile_band_changed"),
        (
            "formula",
            "standards_profile_adjustment",
            "profile_adjustment_changed",
        ),
        (
            "formula",
            "hybrid_standards_profile_policy",
            "profile_policy_changed",
        ),
    ),
)
def test_profile_basis_keys_map_to_specific_preview_change_reasons(
    dimension: str,
    key: str,
    reason: str,
) -> None:
    previous = _observation(
        GradePreviewBasisEntry(
            dimension,  # type: ignore[arg-type]
            key,
            "1" * 64,
        )
    )
    current = replace(
        previous,
        inputs_sha256="f" * 64,
        calculation_fingerprint="9" * 64,
        basis_entries=(
            GradePreviewBasisEntry(
                dimension,  # type: ignore[arg-type]
                key,
                "2" * 64,
            ),
        ),
    )

    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(previous),
    )

    assert comparison.reasons == (reason,)
