from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.standards_grade_explanation as explanation
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_item_proficiency_explanation import ExplanationTraceError
from meridian.grade_policy import (
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
)
from meridian.grade_policy_activation import GradePolicyActivationDecision
from meridian.grade_preview_explanation import GradePreviewIntegrityError
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeStandardInput,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from meridian.standards_grade_result import (
    create_standards_grade_result_snapshot,
    standards_grade_result_reference,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 18, 18, 0, tzinfo=UTC)
SCALE = ProficiencyScaleReference(CLASS_ID, "course_scale", 1, "a" * 64)


def _treatment(*, missing: str = "blocking") -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="exclude",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="blocking",
        unresolved="blocking",
    )


def _configuration(
    *standards: tuple[str, str],
    minimum: int = 1,
    advanced_value: str = "105",
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=SCALE,
        standards=tuple(
            StandardGradeParticipation(standard_id, Decimal(weight))
            for standard_id, weight in standards
        ),
        conversions=(
            ProficiencyGradeConversion("beginning", Decimal("60")),
            ProficiencyGradeConversion("developing", Decimal("75")),
            ProficiencyGradeConversion("proficient", Decimal("88")),
            ProficiencyGradeConversion("advanced", Decimal(advanced_value)),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=minimum,
    )


def _policy(
    config: StandardsBasedGradeConfiguration,
    *,
    state_treatment: GradeStateTreatment | None = None,
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="standards_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Standards Grade Policy",
        calculation_family="standards_based",
        configuration=config,
        state_treatment=state_treatment or _treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Explain standards Grade.",
        revised_at=NOW,
    )


def _activation(policy: GradePolicyRevision) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version="1",
        record_type="meridian_grade_policy_activation",
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(policy),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )


def _result_reference(
    standard_id: str,
    *,
    revision: int = 1,
    digest: str = "b" * 64,
) -> AcademicPeriodProficiencyResultReference:
    return AcademicPeriodProficiencyResultReference(
        CLASS_ID,
        PERIOD.school_year,
        PERIOD.period_id,
        STUDENT_ID,
        standard_id,
        revision,
        digest,
    )


def _calculated(
    participation: StandardGradeParticipation,
    level_id: str,
    *,
    revision: int = 1,
    digest: str = "b" * 64,
    fingerprint: str = "c" * 64,
    freshness: str = "current",
    freshness_reasons: tuple[str, ...] = (),
) -> StandardsGradeStandardInput:
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="calculated",
        result_reference=_result_reference(
            participation.standard_id,
            revision=revision,
            digest=digest,
        ),
        result_calculation_fingerprint=fingerprint,
        result_algorithm_version="1",
        proficiency_level_id=level_id,
        target_scale=SCALE,
        freshness_status=freshness,  # type: ignore[arg-type]
        freshness_reasons=freshness_reasons,
    )


def _state(
    participation: StandardGradeParticipation,
    status: str,
) -> StandardsGradeStandardInput:
    return StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=status,  # type: ignore[arg-type]
        result_reference=None,
        result_calculation_fingerprint=None,
        result_algorithm_version=None,
        proficiency_level_id=None,
        target_scale=None,
        freshness_status=None,
    )


def _snapshot(
    policy: GradePolicyRevision,
    *standards: StandardsGradeStandardInput,
):
    inputs = create_standards_grade_calculation_input(
        policy=policy,
        activation=_activation(policy),
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=tuple(standards),
    )
    outcome = calculate_standards_grade(inputs)
    return create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )


def _effective(snapshot) -> EffectiveGradeResolution:
    source = GradeOverrideSourceResultReference(
        "standards_based",
        standards_grade_result_reference(snapshot),
    )
    calculated = snapshot.outcome.status == "calculated"
    return EffectiveGradeResolution(
        base_result_family="standards_based",
        base_result_reference=source,
        base_result_status=snapshot.outcome.status,
        base_grade=snapshot.outcome.rounded_grade,
        base_freshness_status="current",
        base_freshness_reasons=(),
        selected_override_reference=None,
        override_decision=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=(snapshot.outcome.rounded_grade if calculated else None),
        effective_source="base" if calculated else "none",
    )


def _nested_for(
    standard_input: StandardsGradeStandardInput,
    *,
    digest: str | None = None,
    fingerprint: str | None = None,
):
    reference = standard_input.result_reference
    assert reference is not None
    return SimpleNamespace(
        class_id=reference.class_id,
        student_id=reference.student_id,
        standard_id=reference.standard_id,
        result_revision=reference.result_revision,
        result_sha256=digest or reference.result_sha256,
        algorithm_version=standard_input.result_algorithm_version,
        calculation_fingerprint=(
            fingerprint or standard_input.result_calculation_fingerprint
        ),
        scale=SimpleNamespace(
            scale_id=SCALE.scale_id,
            scale_revision=SCALE.scale_revision,
            scale_sha256=SCALE.scale_sha256,
        ),
        calculation=SimpleNamespace(
            status="calculated",
            proficiency_level_id=standard_input.proficiency_level_id,
        ),
    )


def test_weighted_mean_explains_exact_historical_proficiency_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "0.75"), ("std.b", "0.25"), minimum=2)
    policy = _policy(config)
    first = _calculated(config.standards[0], "advanced", revision=3)
    second = _calculated(config.standards[1], "beginning", revision=2, digest="d" * 64)
    snapshot = _snapshot(policy, first, second)
    requested = []
    by_standard = {
        "std.a": _nested_for(first),
        "std.b": _nested_for(second),
    }

    def nested(_root, target):
        requested.append(target)
        return by_standard[target.standard_id]

    monkeypatch.setattr(explanation, "explain_academic_period_proficiency", nested)

    value = explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=_activation(policy),
        effective=_effective(snapshot),
    )

    assert value.status == "calculated"
    assert value.formula.aggregation_strategy == "weighted_mean"
    assert value.formula.active_weight == Decimal("1.00")
    assert value.formula.weighted_numerator == Decimal("93.75")
    assert value.formula.rounded_grade == Decimal("93.75")
    assert tuple(item.proficiency_level_id for item in value.standards) == (
        "advanced",
        "beginning",
    )
    assert tuple(item.converted_grade_value for item in value.standards) == (
        Decimal("105"),
        Decimal("60"),
    )
    assert [(item.selection, item.result_revision) for item in requested] == [
        ("revision", 3),
        ("revision", 2),
    ]
    assert all(
        item.nested_proficiency_explanation is not None
        for item in value.standards
    )


def test_full_conversion_table_is_exposed_even_for_unused_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "1"), minimum=1, advanced_value="107")
    policy = _policy(config)
    standard = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, standard)
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(standard),
    )

    value = explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=_activation(policy),
        effective=_effective(snapshot),
    )

    conversions = {
        item.proficiency_level_id: item.grade_value for item in value.conversions
    }
    assert conversions["advanced"] == Decimal("107")
    assert conversions["proficient"] == Decimal("88")


def test_missing_zero_is_distinct_from_calculated_proficiency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "0.6"), ("std.b", "0.4"), minimum=1)
    policy = _policy(config, state_treatment=_treatment(missing="zero"))
    calculated = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, calculated, _state(config.standards[1], "missing"))
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(calculated),
    )

    value = explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=_activation(policy),
        effective=_effective(snapshot),
    )

    missing = next(item for item in value.standards if item.standard_id == "std.b")
    assert missing.source_state == "missing"
    assert missing.action == "zero"
    assert missing.proficiency_level_id is None
    assert missing.converted_grade_value is None
    assert missing.calculation_value == Decimal("0")
    assert missing.weighted_contribution == Decimal("0")
    assert missing.result_reference is None
    assert missing.nested_proficiency_explanation is None


def test_blocking_standard_remains_nonnumeric_and_serializes_without_nested_trace(
) -> None:
    config = _configuration(("std.a", "1"), minimum=1)
    policy = _policy(config)
    snapshot = _snapshot(policy, _state(config.standards[0], "missing"))

    value = explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=_activation(policy),
        effective=_effective(snapshot),
    )
    payload = explanation.standards_grade_preview_explanation_to_dict(value)

    assert value.status == "blocked"
    assert value.formula.unrounded_grade is None
    assert value.formula.rounded_grade is None
    assert value.standards[0].action == "blocking"
    assert payload["status"] == "blocked"
    assert payload["standards"][0]["nested_proficiency_explanation"] is None


def test_nested_digest_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "1"), minimum=1)
    policy = _policy(config)
    standard = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, standard)
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(standard, digest="f" * 64),
    )

    with pytest.raises(GradePreviewIntegrityError, match="exact Grade reference"):
        explanation.explain_standards_grade_preview(
            ".",
            snapshot,
            policy=policy,
            activation=_activation(policy),
            effective=_effective(snapshot),
        )


def test_nested_fingerprint_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "1"), minimum=1)
    policy = _policy(config)
    standard = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, standard)
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(standard, fingerprint="e" * 64),
    )

    with pytest.raises(GradePreviewIntegrityError, match="fingerprint"):
        explanation.explain_standards_grade_preview(
            ".",
            snapshot,
            policy=policy,
            activation=_activation(policy),
            effective=_effective(snapshot),
        )


def test_nested_storage_or_integrity_error_is_grade_preview_integrity_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "1"), minimum=1)
    policy = _policy(config)
    standard = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, standard)

    def broken(*args, **kwargs):
        raise ExplanationTraceError("corrupt historical #35 result")

    monkeypatch.setattr(explanation, "explain_academic_period_proficiency", broken)

    with pytest.raises(GradePreviewIntegrityError, match="could not be verified"):
        explanation.explain_standards_grade_preview(
            ".",
            snapshot,
            policy=policy,
            activation=_activation(policy),
            effective=_effective(snapshot),
        )


def test_observation_carries_standards_comparison_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configuration(("std.a", "1"), minimum=1)
    policy = _policy(config)
    standard = _calculated(config.standards[0], "proficient")
    snapshot = _snapshot(policy, standard)
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(standard),
    )
    value = explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=_activation(policy),
        effective=_effective(snapshot),
    )

    observation = explanation.standards_grade_observation(value)
    keys = {(item.dimension, item.key) for item in observation.basis_entries}

    assert ("formula", "standards_formula") in keys
    assert ("participation", "standards_participation") in keys
    assert ("evidence", "standards_proficiency_basis") in keys
    assert ("weighting", "standards_weighting") in keys


def test_unused_conversion_change_changes_formula_basis_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_a = _configuration(("std.a", "1"), minimum=1, advanced_value="105")
    policy_a = _policy(config_a)
    standard_a = _calculated(config_a.standards[0], "proficient")
    snapshot_a = _snapshot(policy_a, standard_a)

    config_b = _configuration(("std.a", "1"), minimum=1, advanced_value="107")
    policy_b = _policy(config_b)
    standard_b = _calculated(config_b.standards[0], "proficient")
    snapshot_b = _snapshot(policy_b, standard_b)

    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(
            standard_a if args[1].standard_id == "std.a" else standard_b
        ),
    )
    first = explanation.explain_standards_grade_preview(
        ".",
        snapshot_a,
        policy=policy_a,
        activation=_activation(policy_a),
        effective=_effective(snapshot_a),
    )
    monkeypatch.setattr(
        explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: _nested_for(standard_b),
    )
    second = explanation.explain_standards_grade_preview(
        ".",
        snapshot_b,
        policy=policy_b,
        activation=_activation(policy_b),
        effective=_effective(snapshot_b),
    )

    first_formula = next(
        item.sha256
        for item in explanation.standards_grade_basis_entries(first)
        if item.dimension == "formula"
    )
    second_formula = next(
        item.sha256
        for item in explanation.standards_grade_basis_entries(second)
        if item.dimension == "formula"
    )
    assert first_formula != second_formula
