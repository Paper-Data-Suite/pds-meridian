from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradePolicyValidationError,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    grade_policy_reference,
    grade_policy_revision_from_dict,
    grade_policy_revision_from_json_bytes,
    grade_policy_revision_to_dict,
    grade_policy_revision_to_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
SHA = "a" * 64
NOW = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)


def item_reference(item_id: str = "unit_test") -> GradePolicyItemReference:
    return GradePolicyItemReference(CLASS_ID, item_id, 1, SHA)


def participation(
    *,
    category_id: str | None = None,
    weight: Decimal | None = None,
    possible_points: Decimal | None = None,
) -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        grade_item=item_reference(),
        category_id=category_id,
        weight=weight,
        possible_points=possible_points,
    )


def treatment() -> GradeStateTreatment:
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


def policy(configuration: ConventionalGradeConfiguration) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course Grade Policy",
        calculation_family="conventional",
        configuration=configuration,
        state_treatment=treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def test_total_points_requires_exact_policy_owned_possible_points() -> None:
    valid = ConventionalGradeConfiguration(
        "total_points",
        (participation(possible_points=Decimal("10.00")),),
        (),
    )
    assert valid.items[0].possible_points == Decimal("10")

    with pytest.raises(GradePolicyValidationError, match="possible_points"):
        ConventionalGradeConfiguration(
            "total_points",
            (participation(),),
            (),
        )


def test_weighted_items_reject_policy_possible_points() -> None:
    valid = ConventionalGradeConfiguration(
        "weighted_items",
        (participation(weight=Decimal("1")),),
        (),
    )
    assert valid.items[0].possible_points is None

    with pytest.raises(GradePolicyValidationError, match="possible_points"):
        ConventionalGradeConfiguration(
            "weighted_items",
            (
                participation(
                    weight=Decimal("1"),
                    possible_points=Decimal("10"),
                ),
            ),
            (),
        )


def test_weighted_categories_require_category_and_possible_points() -> None:
    from meridian.grade_policy import GradePolicyCategory

    valid = ConventionalGradeConfiguration(
        "weighted_categories",
        (
            participation(
                category_id="assessment",
                possible_points=Decimal("25"),
            ),
        ),
        (GradePolicyCategory("assessment", "Assessment", Decimal("1")),),
    )
    assert valid.items[0].possible_points == Decimal("25")

    with pytest.raises(GradePolicyValidationError, match="possible_points"):
        ConventionalGradeConfiguration(
            "weighted_categories",
            (participation(category_id="assessment"),),
            (GradePolicyCategory("assessment", "Assessment", Decimal("1")),),
        )


@pytest.mark.parametrize(
    "value",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("Infinity"),
        10.0,
    ],
)
def test_possible_points_must_be_positive_finite_decimal(value: object) -> None:
    with pytest.raises(GradePolicyValidationError):
        participation(possible_points=value)  # type: ignore[arg-type]


def test_possible_points_round_trip_canonically_and_bind_policy_digest() -> None:
    first = policy(
        ConventionalGradeConfiguration(
            "total_points",
            (participation(possible_points=Decimal("10.00")),),
            (),
        )
    )
    encoded = grade_policy_revision_to_json_bytes(first)
    assert b'"possible_points": "10"' in encoded
    assert grade_policy_revision_from_json_bytes(encoded) == first
    assert grade_policy_reference(first).policy_sha256 == hashlib.sha256(
        encoded
    ).hexdigest()

    second_data = grade_policy_revision_to_dict(first)
    configuration = dict(second_data["configuration"])  # type: ignore[arg-type]
    items = list(configuration["items"])  # type: ignore[arg-type]
    changed_item = dict(items[0])  # type: ignore[arg-type]
    changed_item["possible_points"] = "11"
    items[0] = changed_item
    configuration["items"] = items
    second_data["configuration"] = configuration
    second = grade_policy_revision_from_dict(second_data)
    assert grade_policy_reference(second).policy_sha256 != grade_policy_reference(
        first
    ).policy_sha256


def test_participation_schema_requires_possible_points_key_even_when_null() -> None:
    value = policy(
        ConventionalGradeConfiguration(
            "weighted_items",
            (participation(weight=Decimal("1")),),
            (),
        )
    )
    data = grade_policy_revision_to_dict(value)
    configuration = dict(data["configuration"])  # type: ignore[arg-type]
    items = list(configuration["items"])  # type: ignore[arg-type]
    item_data = dict(items[0])  # type: ignore[arg-type]
    del item_data["possible_points"]
    items[0] = item_data
    configuration["items"] = items
    data["configuration"] = configuration
    with pytest.raises(GradePolicyValidationError, match="exact schema"):
        grade_policy_revision_from_dict(data)
