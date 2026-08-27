from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from meridian.evidence import (
    NativePointValue,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
)
from meridian.proficiency_mapping import (
    NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
    NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    NativeValueMappingProfile,
    NativeValueSourceSignature,
    PointRangeMappingRule,
    ProficiencyLevel,
    ProficiencyScale,
    ScalarMappingRule,
    ScaledLevelMappingRule,
    map_native_value,
    proficiency_scale_reference,
)

NOW = datetime(2026, 8, 26, 17, tzinfo=UTC)
CLASS_ID = "synthetic_class_2026"


def target_scale() -> ProficiencyScale:
    return ProficiencyScale(
        PROFICIENCY_SCALE_SCHEMA_VERSION,
        PROFICIENCY_SCALE_RECORD_TYPE,
        CLASS_ID,
        "teacher_scale",
        1,
        None,
        "Teacher scale",
        "Explicit criterion-referenced proficiency.",
        (
            ProficiencyLevel("novice", 1, "Novice", "Early evidence."),
            ProficiencyLevel("growing", 2, "Growing", "Partial evidence."),
            ProficiencyLevel("ready", 3, "Ready", "Meets criterion."),
            ProficiencyLevel("extending", 4, "Extending", "Extends criterion."),
        ),
        "ready",
        MappingActor("teacher", "teacher_local"),
        None,
        NOW,
    )


def sig(
    producer: str, result_kind: str, target_kind: str
) -> NativeValueSourceSignature:
    return NativeValueSourceSignature(
        producer_module_id=producer,
        publication_kind="academic_result_set",
        manifest_contract_version=f"{producer}_academic_result_manifest_v1",
        producer_contract_version=f"{producer}_academic_work_v1",
        projection_id=f"{producer}.academic_result",
        projection_contract_version="1",
        producer_reader_distribution=(
            "pds-concord" if producer == "concord" else producer
        ),
        producer_reader_version={
            "scoreform": "0.10.0",
            "quillan": "0.10.0",
            "concord": "0.2.0",
        }[producer],
        result_kind=result_kind,
        target_kind=target_kind,
    )


def profile_base(
    profile_id: str,
    signature: NativeValueSourceSignature,
    kind: str,
    rules: tuple[object, ...],
    *,
    native_scale: NativeScale | None = None,
    points_possible: int | float | None = None,
) -> NativeValueMappingProfile:
    scale = target_scale()
    return NativeValueMappingProfile(
        NATIVE_VALUE_MAPPING_PROFILE_SCHEMA_VERSION,
        NATIVE_VALUE_MAPPING_PROFILE_RECORD_TYPE,
        CLASS_ID,
        scale.scale_id,
        profile_id,
        1,
        None,
        proficiency_scale_reference(scale),
        signature,
        kind,  # type: ignore[arg-type]
        native_scale,
        points_possible,
        rules,  # type: ignore[arg-type]
        MappingActor("teacher", "teacher_local"),
        None,
        NOW,
    )


def test_scoreform_points_are_not_percentage_normalized() -> None:
    scale = target_scale()
    signature = sig("scoreform", "attempt_points", "attempt")
    profile = profile_base(
        "scoreform_points_10",
        signature,
        "raw_points",
        (
            PointRangeMappingRule(0, True, 8, False, "growing"),
            PointRangeMappingRule(8, True, 10, True, "ready"),
        ),
        points_possible=10,
    )
    assert (
        map_native_value(NativePointValue(8, 10), signature, profile, scale).status
        == "mapped"
    )
    assert (
        map_native_value(
            NativePointValue(9.6, 12), signature, profile, scale
        ).status
        == "unsupported"
    )


def test_scoreform_result_kinds_do_not_share_scalar_profiles() -> None:
    scale = target_scale()
    correctness = sig("scoreform", "question_correctness", "question")
    profile = profile_base(
        "scoreform_correctness",
        correctness,
        "exact_scalar",
        (ScalarMappingRule(True, "ready"), ScalarMappingRule(False, "novice")),
    )
    assert (
        map_native_value(
            NativeScalarValue(True), correctness, profile, scale
        ).status
        == "mapped"
    )
    selected_response = replace(correctness, result_kind="selected_response")
    assert (
        map_native_value(
            NativeScalarValue(True), selected_response, profile, scale
        ).status
        == "unsupported"
    )
    assert (
        map_native_value(
            NativeStateValue("blank"), correctness, profile, scale
        ).status
        == "native_state"
    )


def test_quillan_024_scale_requires_explicit_exact_mapping() -> None:
    scale = target_scale()
    source = NativeScale(
        "assignment_rating",
        (
            NativeScaleLevel(0, "Needs work", "Limited evidence"),
            NativeScaleLevel(2, "Meets", "Meets assignment criterion"),
            NativeScaleLevel(4, "Exceeds", "Extends assignment criterion"),
        ),
    )
    signature = sig("quillan", "overall_standard_rating", "standard")
    profile = profile_base(
        "quillan_rating",
        signature,
        "exact_native_scale",
        (
            ScaledLevelMappingRule(0, "novice"),
            ScaledLevelMappingRule(2, "ready"),
            ScaledLevelMappingRule(4, "extending"),
        ),
        native_scale=source,
    )
    result = map_native_value(NativeScaledValue(2, source), signature, profile, scale)
    assert result.status == "mapped"
    assert result.proficiency_level_id == "ready"
    assert (
        map_native_value(
            NativeStateValue("unrated"), signature, profile, scale
        ).status
        == "native_state"
    )


def test_concord_scale_semantics_and_target_kind_remain_exact() -> None:
    scale = target_scale()
    source = NativeScale(
        scale_id="criterion_scale",
        levels=(
            NativeScaleLevel(
                1,
                "Low",
                meaning="criterion not yet demonstrated",
                position=1,
            ),
            NativeScaleLevel(2, "Meets", meaning="criterion demonstrated", position=2),
        ),
        order_is_meaningful=True,
        lineage_id="criterion_lineage",
        revision=2,
        scale_type="ordinal",
        status="active",
    )
    signature = sig("concord", "standard_backed_score", "core_student")
    profile = profile_base(
        "concord_standard",
        signature,
        "exact_native_scale",
        (
            ScaledLevelMappingRule(1, "growing"),
            ScaledLevelMappingRule(2, "ready"),
        ),
        native_scale=source,
    )
    assert (
        map_native_value(
            NativeScaledValue(2, source), signature, profile, scale
        ).status
        == "mapped"
    )
    group_signature = replace(signature, target_kind="core_group")
    assert (
        map_native_value(
            NativeScaledValue(2, source), group_signature, profile, scale
        ).status
        == "unsupported"
    )
    changed_lineage = NativeScale(
        scale_id=source.scale_id,
        levels=source.levels,
        order_is_meaningful=True,
        lineage_id="other_lineage",
        revision=2,
        scale_type="ordinal",
        status="active",
    )
    assert (
        map_native_value(
            NativeScaledValue(2, changed_lineage), signature, profile, scale
        ).status
        == "unsupported"
    )
