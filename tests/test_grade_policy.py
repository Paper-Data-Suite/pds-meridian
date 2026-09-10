from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyCategory,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradePolicyValidationError,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    HybridGradeConfiguration,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
    grade_policy_reference_from_dict,
    grade_policy_reference_to_dict,
    grade_policy_revision_from_dict,
    grade_policy_revision_from_json_bytes,
    grade_policy_revision_to_dict,
    grade_policy_revision_to_json_bytes,
    validate_grade_policy_revision_transition,
)
from meridian.proficiency_mapping import ProficiencyScaleReference

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
STANDARD_A = "https://standards.example/RL:9-10.1?edition=2026"
STANDARD_B = "https://standards.example/W:9-10.2?edition=2026"


def item_ref(
    grade_item_id: str,
    *,
    revision: int = 1,
    digest: str = SHA_A,
    class_id: str = CLASS_ID,
) -> GradePolicyItemReference:
    return GradePolicyItemReference(
        class_id,
        grade_item_id,
        revision,
        digest,
    )


def item(
    grade_item_id: str,
    *,
    category_id: str | None = None,
    weight: Decimal | None = None,
    revision: int = 1,
    class_id: str = CLASS_ID,
) -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        item_ref(
            grade_item_id,
            revision=revision,
            class_id=class_id,
        ),
        category_id,
        weight,
    )


def state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def reassessment() -> GradeReassessmentHandling:
    return GradeReassessmentHandling(
        "v02_attempt_and_reassessment_state",
        "blocking",
    )


def rounding() -> GradeRoundingPolicy:
    return GradeRoundingPolicy(
        Decimal("0.0100"),
        "half_up",
        "final",
    )


def total_points() -> ConventionalGradeConfiguration:
    return ConventionalGradeConfiguration(
        "total_points",
        (
            item("unit1_test"),
            item("essay_1"),
        ),
        (),
    )


def weighted_items() -> ConventionalGradeConfiguration:
    return ConventionalGradeConfiguration(
        "weighted_items",
        (
            item("unit1_test", weight=Decimal("0.600")),
            item("essay_1", weight=Decimal("0.400")),
        ),
        (),
    )


def weighted_categories() -> ConventionalGradeConfiguration:
    return ConventionalGradeConfiguration(
        "weighted_categories",
        (
            item("quiz_1", category_id="practice"),
            item("unit1_test", category_id="assessment"),
        ),
        (
            GradePolicyCategory(
                "practice",
                "Practice",
                Decimal("0.400"),
            ),
            GradePolicyCategory(
                "assessment",
                "Assessments",
                Decimal("0.600"),
            ),
        ),
    )


def scale_ref(*, class_id: str = CLASS_ID) -> ProficiencyScaleReference:
    return ProficiencyScaleReference(
        class_id,
        "course_scale",
        2,
        SHA_B,
    )


def standards_based(
    *,
    class_id: str = CLASS_ID,
) -> StandardsBasedGradeConfiguration:
    return StandardsBasedGradeConfiguration(
        target_scale=scale_ref(class_id=class_id),
        standards=(
            StandardGradeParticipation(
                STANDARD_B,
                Decimal("0.400"),
            ),
            StandardGradeParticipation(
                STANDARD_A,
                Decimal("0.600"),
            ),
        ),
        conversions=(
            ProficiencyGradeConversion("advanced", Decimal("100.00")),
            ProficiencyGradeConversion("proficient", Decimal("85.0")),
            ProficiencyGradeConversion("developing", Decimal("70")),
            ProficiencyGradeConversion("beginning", Decimal("55")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )


def hybrid() -> HybridGradeConfiguration:
    return HybridGradeConfiguration(
        conventional=weighted_categories(),
        standards_based=standards_based(),
        conventional_weight=Decimal("0.700"),
        standards_weight=Decimal("0.300"),
    )


def policy(
    family: str = "conventional",
    *,
    configuration: object | None = None,
    revision: int = 1,
    revised_at: datetime | None = None,
) -> GradePolicyRevision:
    if configuration is None:
        if family == "conventional":
            configuration = weighted_categories()
        elif family == "standards_based":
            configuration = standards_based()
        else:
            configuration = hybrid()
    if revised_at is None:
        revised_at = NOW + timedelta(hours=revision - 1)
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course Grade Policy",
        calculation_family=family,  # type: ignore[arg-type]
        configuration=configuration,  # type: ignore[arg-type]
        state_treatment=state_treatment(),
        reassessment_handling=reassessment(),
        rounding=rounding(),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=revised_at,
    )


def test_policy_is_frozen_and_slotted() -> None:
    value = policy()
    with pytest.raises(FrozenInstanceError):
        value.title = "Changed"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize(
    ("family", "configuration"),
    [
        ("conventional", total_points()),
        ("conventional", weighted_items()),
        ("conventional", weighted_categories()),
        ("standards_based", standards_based()),
        ("hybrid", hybrid()),
    ],
)
def test_supported_policy_families_round_trip_canonically(
    family: str,
    configuration: object,
) -> None:
    value = policy(family, configuration=configuration)
    encoded = grade_policy_revision_to_json_bytes(value)
    assert encoded.endswith(b"\n")
    assert grade_policy_revision_from_json_bytes(encoded) == value

    reference = grade_policy_reference(value)
    assert reference.policy_sha256 == hashlib.sha256(encoded).hexdigest()
    assert grade_policy_reference_from_dict(
        grade_policy_reference_to_dict(reference)
    ) == reference


def test_calculation_family_must_match_configuration_type() -> None:
    with pytest.raises(
        GradePolicyValidationError,
        match="configuration type must match calculation_family",
    ):
        policy("conventional", configuration=standards_based())

    with pytest.raises(
        GradePolicyValidationError,
        match="configuration type must match calculation_family",
    ):
        policy("hybrid", configuration=weighted_items())


def test_policy_revision_transition_is_linear_and_identity_stable() -> None:
    old = policy()
    new = policy(
        revision=2,
        configuration=weighted_items(),
    )
    assert validate_grade_policy_revision_transition(old, new) == new

    bad = grade_policy_revision_to_dict(new)
    bad["policy_id"] = "different_policy"
    with pytest.raises(GradePolicyValidationError):
        validate_grade_policy_revision_transition(
            old,
            grade_policy_revision_from_dict(bad),
        )

    skipped = replace(
        new,
        policy_revision=3,
        supersedes_revision=2,
    )
    with pytest.raises(GradePolicyValidationError):
        validate_grade_policy_revision_transition(old, skipped)


@pytest.mark.parametrize(
    "configuration",
    [
        lambda: ConventionalGradeConfiguration(
            "total_points",
            (item("a", weight=Decimal("1")),),
            (),
        ),
        lambda: ConventionalGradeConfiguration(
            "weighted_items",
            (
                item("a", weight=Decimal("0.4")),
                item("b", weight=Decimal("0.5")),
            ),
            (),
        ),
        lambda: ConventionalGradeConfiguration(
            "weighted_categories",
            (item("a", category_id="assessment"),),
            (
                GradePolicyCategory(
                    "assessment",
                    "Assessments",
                    Decimal("0.5"),
                ),
                GradePolicyCategory(
                    "practice",
                    "Practice",
                    Decimal("0.5"),
                ),
            ),
        ),
    ],
)
def test_conventional_configuration_fails_closed(
    configuration: object,
) -> None:
    with pytest.raises(GradePolicyValidationError):
        configuration()  # type: ignore[operator]


def test_duplicate_logical_grade_item_is_rejected_across_revisions() -> None:
    with pytest.raises(
        GradePolicyValidationError,
        match="duplicate logical items",
    ):
        ConventionalGradeConfiguration(
            "total_points",
            (
                item("same_item", revision=1),
                item("same_item", revision=2),
            ),
            (),
        )


def test_policy_collections_are_canonicalized_by_semantic_identity() -> None:
    conventional = weighted_categories()
    assert tuple(
        value.grade_item.grade_item_id
        for value in conventional.items
    ) == ("quiz_1", "unit1_test")
    assert tuple(
        value.category_id for value in conventional.categories
    ) == ("assessment", "practice")

    standards = standards_based()
    assert tuple(
        value.standard_id for value in standards.standards
    ) == tuple(sorted((STANDARD_A, STANDARD_B)))
    assert tuple(
        value.proficiency_level_id
        for value in standards.conversions
    ) == (
        "advanced",
        "beginning",
        "developing",
        "proficient",
    )


@pytest.mark.parametrize(
    "field_name",
    [
        "pending",
        "excused",
        "excluded",
        "not_applicable",
        "insufficient_evidence",
        "unavailable",
        "withdrawn",
        "invalid",
        "unresolved",
    ],
)
def test_only_supported_states_may_explicitly_become_zero(
    field_name: str,
) -> None:
    kwargs = {
        "missing": "blocking",
        "pending": "blocking",
        "incomplete": "blocking",
        "excused": "exclude",
        "excluded": "exclude",
        "not_applicable": "exclude",
        "insufficient_evidence": "blocking",
        "unavailable": "blocking",
        "withdrawn": "exclude",
        "invalid": "exclude",
        "unresolved": "blocking",
    }
    kwargs[field_name] = "zero"
    with pytest.raises(GradePolicyValidationError):
        GradeStateTreatment(**kwargs)  # type: ignore[arg-type]


def test_missing_and_incomplete_zero_are_explicitly_supported() -> None:
    value = replace(
        state_treatment(),
        missing="zero",
        incomplete="zero",
    )
    assert value.missing == "zero"
    assert value.incomplete == "zero"


def test_reassessment_contract_cannot_reselect_attempts() -> None:
    with pytest.raises(
        GradePolicyValidationError,
        match="v02_attempt_and_reassessment_state",
    ):
        GradeReassessmentHandling(
            "latest_attempt",  # type: ignore[arg-type]
            "blocking",
        )

    with pytest.raises(GradePolicyValidationError):
        GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "zero",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "quantum",
    [
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_rounding_requires_positive_finite_decimal(
    quantum: Decimal,
) -> None:
    with pytest.raises(GradePolicyValidationError):
        GradeRoundingPolicy(quantum, "half_up", "final")


def test_rounding_rejects_float_mode_and_stage_defaults() -> None:
    with pytest.raises(GradePolicyValidationError):
        GradeRoundingPolicy(
            0.01,  # type: ignore[arg-type]
            "half_up",
            "final",
        )
    with pytest.raises(GradePolicyValidationError):
        GradeRoundingPolicy(
            Decimal("0.01"),
            "bankers",  # type: ignore[arg-type]
            "final",
        )
    with pytest.raises(GradePolicyValidationError):
        GradeRoundingPolicy(
            Decimal("0.01"),
            "half_up",
            "per_item",  # type: ignore[arg-type]
        )


def test_standards_configuration_requires_complete_explicit_weighting() -> None:
    with pytest.raises(GradePolicyValidationError, match="sum exactly to 1"):
        StandardsBasedGradeConfiguration(
            target_scale=scale_ref(),
            standards=(
                StandardGradeParticipation(
                    STANDARD_A,
                    Decimal("0.9"),
                ),
            ),
            conversions=(
                ProficiencyGradeConversion(
                    "proficient",
                    Decimal("85"),
                ),
            ),
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
        )

    with pytest.raises(GradePolicyValidationError):
        StandardsBasedGradeConfiguration(
            target_scale=scale_ref(),
            standards=(
                StandardGradeParticipation(
                    STANDARD_A,
                    Decimal("1"),
                ),
            ),
            conversions=(
                ProficiencyGradeConversion("x", Decimal("80")),
                ProficiencyGradeConversion("x", Decimal("90")),
            ),
            aggregation_strategy="weighted_mean",
            minimum_calculated_results=1,
        )


def test_standards_minimum_result_count_is_bounded() -> None:
    with pytest.raises(
        GradePolicyValidationError,
        match="must not exceed participating standard count",
    ):
        replace(
            standards_based(),
            minimum_calculated_results=3,
        )


def test_hybrid_component_weights_must_sum_exactly_to_one() -> None:
    with pytest.raises(GradePolicyValidationError, match="sum exactly to 1"):
        HybridGradeConfiguration(
            weighted_items(),
            standards_based(),
            Decimal("0.8"),
            Decimal("0.3"),
        )


def test_policy_rejects_cross_class_grade_item_and_scale_references() -> None:
    foreign_item = ConventionalGradeConfiguration(
        "total_points",
        (item("foreign", class_id="other_class"),),
        (),
    )
    with pytest.raises(GradePolicyValidationError, match="Grade Item reference"):
        policy("conventional", configuration=foreign_item)

    with pytest.raises(GradePolicyValidationError, match="target_scale class_id"):
        policy(
            "standards_based",
            configuration=standards_based(class_id="other_class"),
        )


def test_decimal_values_are_canonical_text_not_binary_json_numbers() -> None:
    encoded = grade_policy_revision_to_json_bytes(
        policy("hybrid", configuration=hybrid())
    )
    assert b'"weight": "0.6"' in encoded
    assert b'"conventional_weight": "0.7"' in encoded
    assert b'"grade_value": "100"' in encoded
    assert b'"quantum": "0.01"' in encoded


def test_json_rejects_unknown_missing_duplicate_and_noncanonical_bytes() -> None:
    value = policy()
    encoded = grade_policy_revision_to_dict(value)

    unknown = {**encoded, "formula": "student_grade * 1.1"}
    with pytest.raises(GradePolicyValidationError):
        grade_policy_revision_from_dict(unknown)

    missing = dict(encoded)
    del missing["rounding"]
    with pytest.raises(GradePolicyValidationError):
        grade_policy_revision_from_dict(missing)

    canonical = grade_policy_revision_to_json_bytes(value).decode("utf-8")
    duplicate = canonical.replace(
        f'  "class_id": "{CLASS_ID}",',
        (
            f'  "class_id": "{CLASS_ID}",\n'
            f'  "class_id": "{CLASS_ID}",'
        ),
        1,
    ).encode("utf-8")
    with pytest.raises(Exception, match="duplicate JSON object key"):
        grade_policy_revision_from_json_bytes(duplicate)

    compact = json.dumps(
        grade_policy_revision_to_dict(value)
    ).encode("utf-8")
    with pytest.raises(Exception, match="canonical encoding"):
        grade_policy_revision_from_json_bytes(compact)


def test_configuration_schema_rejects_arbitrary_formula_language() -> None:
    encoded = grade_policy_revision_to_dict(policy())
    configuration = dict(encoded["configuration"])  # type: ignore[arg-type]
    configuration["formula"] = "sum(items)"
    encoded["configuration"] = configuration
    with pytest.raises(
        GradePolicyValidationError,
        match="exact schema",
    ):
        grade_policy_revision_from_dict(encoded)


def test_policy_schema_does_not_embed_activation_or_calculation_state() -> None:
    encoded = grade_policy_revision_to_dict(policy())
    assert "activation" not in encoded
    assert "grade_result" not in encoded
    assert "preview" not in encoded
    assert "snapshot" not in encoded
    assert "export" not in encoded
