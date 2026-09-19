from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    grade_policy_reference,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_preview_explanation import (
    GradePreviewBaseResultExplanation,
    GradePreviewBasisEntry,
    GradePreviewComparisonError,
    GradePreviewIntegrityError,
    GradePreviewTarget,
    GradePreviewTargetError,
    explain_grade_preview_common,
    grade_preview_explanation_to_dict,
    grade_preview_observation_from_explanation,
    grade_preview_observation_sha256,
    grade_preview_observation_to_dict,
    grade_preview_observation_to_json_bytes,
)
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    teacher_grade_override_reference,
)

CLASS_ID = "english_12"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)


def _policy(*, policy_id: str = "course_grade") -> GradePolicyRevision:
    item = GradePolicyItemReference(
        class_id=CLASS_ID,
        grade_item_id="essay_1",
        grade_item_revision=1,
        grade_item_revision_sha256="1" * 64,
    )
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=policy_id,
        policy_revision=1,
        supersedes_revision=None,
        title="Quarter 1 conventional Grade",
        calculation_family="conventional",
        configuration=ConventionalGradeConfiguration(
            mode="total_points",
            items=(
                GradePolicyItemParticipation(
                    grade_item=item,
                    category_id=None,
                    weight=None,
                    possible_points=Decimal("10"),
                ),
            ),
            categories=(),
        ),
        state_treatment=GradeStateTreatment(
            missing="exclude",
            pending="exclude",
            incomplete="exclude",
            excused="exclude",
            excluded="exclude",
            not_applicable="exclude",
            insufficient_evidence="exclude",
            unavailable="exclude",
            withdrawn="exclude",
            invalid="exclude",
            unresolved="exclude",
        ),
        reassessment_handling=GradeReassessmentHandling(
            selection_authority="v02_attempt_and_reassessment_state",
            unresolved_handling="exclude",
        ),
        rounding=GradeRoundingPolicy(
            quantum=Decimal("0.1"),
            mode="half_up",
            application_stage="final",
        ),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Quarter policy.",
        revised_at=NOW,
    )


def _activation(policy: GradePolicyRevision) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(policy),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Use this policy for Q1.",
        decided_at=NOW,
    )


def _source_reference(
    *,
    revision: int = 1,
    digest: str = "a" * 64,
) -> GradeOverrideSourceResultReference:
    return GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id=STUDENT_ID,
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=revision,
            result_sha256=digest,
        ),
    )


def _base_result(
    source: GradeOverrideSourceResultReference,
    *,
    unrounded: Decimal | None = Decimal("88.24"),
    rounded: Decimal | None = Decimal("88.2"),
) -> GradePreviewBaseResultExplanation:
    return GradePreviewBaseResultExplanation(
        source_result=source,
        algorithm_version="1",
        calculation_fingerprint="b" * 64,
        inputs_sha256="c" * 64,
        calculated_at=NOW,
        unrounded_grade=unrounded,
        rounded_grade=rounded,
    )


def _effective_base(
    source: GradeOverrideSourceResultReference,
) -> EffectiveGradeResolution:
    return EffectiveGradeResolution(
        base_result_family="conventional",
        base_result_reference=source,
        base_result_status="calculated",
        base_grade=Decimal("88.2"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        selected_override_reference=None,
        override_decision=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=Decimal("88.2"),
        effective_source="base",
    )


def _target() -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )


def test_common_preview_projects_exact_policy_rounding_and_base_grade() -> None:
    policy = _policy()
    activation = _activation(policy)
    source = _source_reference()

    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=activation,
        effective=_effective_base(source),
    )

    assert explanation.base_result.source_result == source
    assert explanation.base_grade == Decimal("88.2")
    assert explanation.base_result.unrounded_grade == Decimal("88.24")
    assert explanation.policy.title == "Quarter 1 conventional Grade"
    assert explanation.policy.rounding.quantum == Decimal("0.1")
    assert explanation.policy.rounding.mode == "half_up"
    assert explanation.effective_grade == Decimal("88.2")
    assert explanation.effective_source == "base"
    assert explanation.override_applicability == "no_override"


def test_common_preview_exposes_all_state_treatments_in_canonical_order() -> None:
    policy = _policy()
    source = _source_reference()
    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=_effective_base(source),
    )

    states = tuple(rule.state for rule in explanation.policy.state_treatment)
    assert states == (
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
    assert all(
        rule.consequence == "exclude"
        for rule in explanation.policy.state_treatment
    )


def test_applicable_override_preserves_exact_replacement_without_rerounding() -> None:
    policy = _policy()
    source = _source_reference()
    decision = TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        supersedes_revision=None,
        decision="override",
        source_result=source,
        replacement_grade=Decimal("105.25"),
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Documented teacher override.",
        decided_at=NOW,
    )
    reference = teacher_grade_override_reference(decision)
    effective = EffectiveGradeResolution(
        base_result_family="conventional",
        base_result_reference=source,
        base_result_status="calculated",
        base_grade=Decimal("88.2"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        selected_override_reference=reference,
        override_decision=decision,
        override_applicability="applicable",
        override_reasons=(),
        effective_grade=Decimal("105.25"),
        effective_source="override",
    )

    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=effective,
    )

    assert explanation.selected_override is not None
    assert explanation.selected_override.reference == reference
    assert explanation.selected_override.actor_id == "teacher_local"
    assert explanation.selected_override.rationale == "Documented teacher override."
    assert explanation.selected_override.replacement_grade == Decimal("105.25")
    assert explanation.policy.rounding.quantum == Decimal("0.1")
    assert explanation.effective_grade == Decimal("105.25")
    assert explanation.effective_source == "override"


def test_stale_selected_base_remains_explainable_without_effective_grade() -> None:
    policy = _policy()
    source = _source_reference()
    effective = EffectiveGradeResolution(
        base_result_family="conventional",
        base_result_reference=source,
        base_result_status="calculated",
        base_grade=Decimal("88.2"),
        base_freshness_status="stale",
        base_freshness_reasons=("policy_changed",),
        selected_override_reference=None,
        override_decision=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=None,
        effective_source="none",
    )

    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=effective,
    )

    assert explanation.base_grade == Decimal("88.2")
    assert explanation.base_freshness_status == "stale"
    assert explanation.base_freshness_reasons == ("policy_changed",)
    assert explanation.effective_grade is None
    assert explanation.effective_source == "none"


def test_exact_activation_must_reference_supplied_policy() -> None:
    policy = _policy()
    other = _policy(policy_id="other_policy")
    source = _source_reference()

    with pytest.raises(GradePreviewIntegrityError):
        explain_grade_preview_common(
            target=_target(),
            base_result=_base_result(source),
            policy=policy,
            activation=_activation(other),
            effective=_effective_base(source),
        )


def test_effective_base_grade_must_match_persisted_rounded_grade() -> None:
    policy = _policy()
    source = _source_reference()

    with pytest.raises(GradePreviewIntegrityError):
        explain_grade_preview_common(
            target=_target(),
            base_result=_base_result(source, rounded=Decimal("88.3")),
            policy=policy,
            activation=_activation(policy),
            effective=_effective_base(source),
        )


def test_source_scope_mismatch_fails_closed() -> None:
    policy = _policy()
    wrong_source = GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id="different_student",
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=1,
            result_sha256="a" * 64,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError):
        explain_grade_preview_common(
            target=_target(),
            base_result=_base_result(wrong_source),
            policy=policy,
            activation=_activation(policy),
            effective=_effective_base(wrong_source),
        )


def test_observation_is_deterministic_and_snapshot_neutral() -> None:
    policy = _policy()
    source = _source_reference()
    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=_effective_base(source),
    )
    extra = (
        GradePreviewBasisEntry("weighting", "item:essay_1", "e" * 64),
        GradePreviewBasisEntry("formula", "mode", "d" * 64),
    )

    observation = grade_preview_observation_from_explanation(
        explanation,
        extra_basis_entries=extra,
    )
    again = grade_preview_observation_from_explanation(
        explanation,
        extra_basis_entries=extra,
    )

    assert observation == again
    assert grade_preview_observation_to_json_bytes(observation) == (
        grade_preview_observation_to_json_bytes(again)
    )
    assert grade_preview_observation_sha256(observation) == (
        grade_preview_observation_sha256(again)
    )
    assert tuple(
        (entry.dimension, entry.key) for entry in observation.basis_entries
    ) == tuple(
        sorted(
            (entry.dimension, entry.key) for entry in observation.basis_entries
        )
    )
    assert {entry.dimension for entry in observation.basis_entries} >= {
        "activation",
        "policy",
        "state_treatment",
        "reassessment",
        "rounding",
        "algorithm",
        "formula",
        "weighting",
    }


def test_observation_serializes_decimal_as_exact_canonical_text() -> None:
    policy = _policy()
    source = _source_reference()
    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=_effective_base(source),
    )
    observation = grade_preview_observation_from_explanation(explanation)
    data = grade_preview_observation_to_dict(observation)
    explanation_data = grade_preview_explanation_to_dict(explanation)

    assert data["base_grade"] == "88.2"
    assert data["effective_grade"] == "88.2"
    assert explanation_data["base_result"] == {
        "source_result": {
            "family": "conventional",
            "reference": {
                "class_id": CLASS_ID,
                "student_id": STUDENT_ID,
                "school_year": PERIOD.school_year,
                "period_id": PERIOD.period_id,
                "calendar_revision": 1,
                "result_revision": 1,
                "result_sha256": "a" * 64,
            },
        },
        "algorithm_version": "1",
        "calculation_fingerprint": "b" * 64,
        "inputs_sha256": "c" * 64,
        "calculated_at": NOW.isoformat(),
        "unrounded_grade": "88.24",
        "rounded_grade": "88.2",
    }


def test_duplicate_basis_dimension_key_is_rejected() -> None:
    policy = _policy()
    source = _source_reference()
    explanation = explain_grade_preview_common(
        target=_target(),
        base_result=_base_result(source),
        policy=policy,
        activation=_activation(policy),
        effective=_effective_base(source),
    )
    duplicate = GradePreviewBasisEntry(
        "algorithm",
        "conventional",
        "f" * 64,
    )

    with pytest.raises(GradePreviewComparisonError, match="duplicate dimension/key"):
        grade_preview_observation_from_explanation(
            explanation,
            extra_basis_entries=(duplicate,),
        )


def test_target_rejects_nonpositive_calendar_revision() -> None:
    with pytest.raises(GradePreviewTargetError):
        replace(_target(), calendar_revision=0)
