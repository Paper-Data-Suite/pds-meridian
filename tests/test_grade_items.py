from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemValidationError,
    GradeItemWeightingMetadata,
    GradeItemWorkReference,
    grade_item_revision_from_dict,
    grade_item_revision_from_json_bytes,
    grade_item_revision_to_dict,
    grade_item_revision_to_json_bytes,
    grade_item_weighting_from_dict,
    grade_item_weighting_to_dict,
    grade_item_work_reference_from_dict,
    grade_item_work_reference_to_dict,
    validate_grade_item_revision_transition,
)

CREATED = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


def revision(
    number: int = 1,
    *,
    title: str = "Unit 1 Assessment",
    purpose: str = "standards_proficiency",
    status: str = "active",
    weighting: GradeItemWeightingMetadata | None = None,
    revised_at: datetime | None = None,
) -> GradeItemRevision:
    if revised_at is None:
        revised_at = CREATED if number == 1 else CREATED + timedelta(hours=number - 1)
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id="english10_p2",
        grade_item_id="unit1_assessment",
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title=title,
        purpose=purpose,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        weighting=weighting,
        created_at=CREATED,
        revised_at=revised_at,
    )


def test_revision_is_frozen_and_slotted() -> None:
    item = revision()
    with pytest.raises(FrozenInstanceError):
        item.title = "Changed"  # type: ignore[misc]
    assert not hasattr(item, "__dict__")


def test_revision_normalizes_aware_datetimes_to_utc() -> None:
    offset = timezone(timedelta(hours=-4))
    local = datetime(2026, 8, 25, 14, 0, tzinfo=offset)
    item = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id="english10_p2",
        grade_item_id="unit1_assessment",
        grade_item_revision=1,
        supersedes_revision=None,
        title="Unit 1 Assessment",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=local,
        revised_at=local,
    )
    assert item.created_at == CREATED
    assert item.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("record_type", "grade_item"),
        ("class_id", "bad/class"),
        ("grade_item_id", "bad item"),
        ("grade_item_revision", 0),
        ("title", ""),
        ("title", " title"),
        ("title", "title\nnext"),
        ("purpose", "all_numeric"),
        ("status", "deleted"),
    ],
)
def test_revision_rejects_invalid_fields(field: str, value: object) -> None:
    kwargs = grade_item_revision_to_dict(revision())
    kwargs[field] = value
    with pytest.raises(GradeItemValidationError):
        grade_item_revision_from_dict(kwargs)


def test_supersession_rules() -> None:
    data = grade_item_revision_to_dict(revision())
    data["supersedes_revision"] = 1
    with pytest.raises(GradeItemValidationError):
        grade_item_revision_from_dict(data)

    data = grade_item_revision_to_dict(revision(2))
    data["supersedes_revision"] = None
    with pytest.raises(GradeItemValidationError):
        grade_item_revision_from_dict(data)


def test_revision_one_requires_equal_created_and_revised_time() -> None:
    with pytest.raises(GradeItemValidationError):
        revision(1, revised_at=CREATED + timedelta(seconds=1))


def test_transition_requires_same_identity_linear_revision_and_time() -> None:
    old = revision()
    new = revision(2, title="Retitled")
    assert validate_grade_item_revision_transition(old, new) == new

    data = grade_item_revision_to_dict(new)
    data["class_id"] = "english10_p4"
    with pytest.raises(GradeItemValidationError):
        validate_grade_item_revision_transition(
            old, grade_item_revision_from_dict(data)
        )

    data = grade_item_revision_to_dict(new)
    data["grade_item_id"] = "other_item"
    with pytest.raises(GradeItemValidationError):
        validate_grade_item_revision_transition(
            old, grade_item_revision_from_dict(data)
        )

    skipped = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=old.class_id,
        grade_item_id=old.grade_item_id,
        grade_item_revision=3,
        supersedes_revision=2,
        title="Skipped",
        purpose="standards_proficiency",
        status="active",
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED + timedelta(hours=3),
    )
    with pytest.raises(GradeItemValidationError):
        validate_grade_item_revision_transition(old, skipped)


def test_weighting_accepts_category_weight_or_both() -> None:
    category = GradeItemWeightingMetadata(category_id="assessment")
    weight = GradeItemWeightingMetadata(relative_weight=Decimal("1.5000"))
    both = GradeItemWeightingMetadata(
        category_id="assessment", relative_weight=Decimal("2.2500")
    )
    assert grade_item_weighting_to_dict(category) == {
        "category_id": "assessment",
        "relative_weight": None,
    }
    assert grade_item_weighting_to_dict(weight)["relative_weight"] == "1.5"
    assert grade_item_weighting_to_dict(both)["relative_weight"] == "2.25"
    assert weight.relative_weight == Decimal("1.5")


@pytest.mark.parametrize(
    "value",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")],
)
def test_weighting_rejects_nonpositive_or_nonfinite_decimal(value: Decimal) -> None:
    with pytest.raises(GradeItemValidationError):
        GradeItemWeightingMetadata(relative_weight=value)


def test_weighting_rejects_empty_and_float() -> None:
    with pytest.raises(GradeItemValidationError):
        GradeItemWeightingMetadata()
    with pytest.raises(GradeItemValidationError):
        GradeItemWeightingMetadata(relative_weight=1.5)  # type: ignore[arg-type]


def test_weighting_round_trip_uses_decimal_text() -> None:
    original = GradeItemWeightingMetadata(
        category_id="assessment", relative_weight=Decimal("0.0100")
    )
    encoded = grade_item_weighting_to_dict(original)
    assert encoded["relative_weight"] == "0.01"
    assert grade_item_weighting_from_dict(encoded) == original


def test_work_reference_round_trip_is_exact_and_producer_neutral() -> None:
    reference = GradeItemWorkReference(
        work=ModuleWorkRef(
            module_id="scoreform",
            class_id="english10_p2",
            work_id="unit1_test",
        ),
        registration_revision=3,
    )
    encoded = grade_item_work_reference_to_dict(reference)
    assert encoded == {
        "work": {
            "module_id": "scoreform",
            "class_id": "english10_p2",
            "work_id": "unit1_test",
        },
        "registration_revision": 3,
    }
    assert grade_item_work_reference_from_dict(encoded) == reference


def test_work_reference_rejects_invalid_registration_revision() -> None:
    with pytest.raises(GradeItemValidationError):
        GradeItemWorkReference(
            work=ModuleWorkRef(
                module_id="quillan",
                class_id="english10_p2",
                work_id="essay1",
            ),
            registration_revision=0,
        )


def test_revision_schema_does_not_embed_work_membership() -> None:
    encoded = grade_item_revision_to_dict(revision())
    assert "work_references" not in encoded
    assert "membership" not in encoded
    assert "student_ids" not in encoded


def test_canonical_json_round_trip_and_decimal_determinism() -> None:
    item = revision(
        weighting=GradeItemWeightingMetadata(
            category_id="assessment", relative_weight=Decimal("1.500")
        )
    )
    encoded = grade_item_revision_to_json_bytes(item)
    assert encoded.endswith(b"\n")
    assert b'"relative_weight": "1.5"' in encoded
    assert grade_item_revision_from_json_bytes(encoded) == item
    assert grade_item_revision_to_json_bytes(
        revision(
            weighting=GradeItemWeightingMetadata(
                category_id="assessment", relative_weight=Decimal("1.5")
            )
        )
    ) == encoded


def test_json_rejects_unknown_missing_duplicate_and_noncanonical_bytes() -> None:
    encoded = grade_item_revision_to_dict(revision())
    unknown = {**encoded, "students": []}
    with pytest.raises(GradeItemValidationError):
        grade_item_revision_from_dict(unknown)

    missing = dict(encoded)
    del missing["purpose"]
    with pytest.raises(GradeItemValidationError):
        grade_item_revision_from_dict(missing)

    canonical = grade_item_revision_to_json_bytes(revision()).decode("utf-8")
    duplicate = canonical.replace(
        '  "class_id": "english10_p2",',
        '  "class_id": "english10_p2",\n  "class_id": "english10_p2",',
    ).encode("utf-8")
    with pytest.raises(Exception, match="duplicate JSON object key"):
        grade_item_revision_from_json_bytes(duplicate)

    compact = json.dumps(grade_item_revision_to_dict(revision())).encode("utf-8")
    with pytest.raises(Exception, match="canonical encoding"):
        grade_item_revision_from_json_bytes(compact)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(GradeItemValidationError):
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id="english10_p2",
            grade_item_id="unit1_assessment",
            grade_item_revision=1,
            supersedes_revision=None,
            title="Unit 1 Assessment",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=datetime(2026, 8, 25, 18, 0),
            revised_at=datetime(2026, 8, 25, 18, 0),
        )
