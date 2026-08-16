from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from pds_core.academic_work_registrations import academic_work_registration_from_dict
from pds_core.publication_records import publication_record_from_dict

from meridian.evidence import (
    EvidenceEligibility,
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    EvidenceTargetIdentity,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    ProjectionIdentity,
    StudentSubject,
)
from meridian.evidence_serialization import (
    EvidenceSerializationError,
    evidence_inventory_from_dict,
    evidence_inventory_to_dict,
)

NOW = datetime(2026, 8, 6, 12, tzinfo=UTC)


def inventory(fixture_loader: Callable[[str], dict[str, Any]]) -> EvidenceInventory:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    projection = ProjectionIdentity(
        "synthetic_projection",
        "1",
        "synthetic-reader",
        "1.0.0",
    )
    provenance = EvidenceProvenance(
        publication,
        registration,
        None,
        projection,
        NativeProvenance(
            references=(NativeReference("attempt", "attempt_1", sequence=1),)
        ),
    )
    scale = NativeScale(
        "synthetic_scale",
        (
            NativeScaleLevel(1, "Developing"),
            NativeScaleLevel(2, "Meeting"),
        ),
        contract_version="1",
    )
    values = (
        NativeScalarValue(True),
        NativeScalarValue(1),
        NativeScalarValue(1.0),
        NativeScalarValue("1"),
        NativePointValue(earned=8, possible=10),
        NativeScaledValue(value=2, scale=scale),
        NativeStateValue("blank", "Blank"),
    )
    return EvidenceInventory(
        tuple(
            EvidenceItem(
                f"evidence_{index}",
                StudentSubject("student_1"),
                EvidenceTarget("attempt", "attempt_1", sequence=1),
                "synthetic_result",
                value,
                provenance,
                EvidenceEligibility.unevaluated(),
            )
            for index, value in enumerate(values, start=1)
        )
    )


def test_inventory_round_trip_preserves_exact_scalar_types(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    original = inventory(fixture_loader)
    restored = evidence_inventory_from_dict(evidence_inventory_to_dict(original))
    assert restored == original
    scalars = [
        item.value.value
        for item in restored.items[:4]
        if isinstance(item.value, NativeScalarValue)
    ]
    assert [type(value) for value in scalars] == [bool, int, float, str]
    assert scalars == [True, 1, 1.0, "1"]


def test_producer_native_text_round_trips_without_normalization(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    original = inventory(fixture_loader)
    scale_id = " synthetic / scale "
    target_id = "Body / 1"
    reference_id = "Observation / A"
    standard_id = "Standard / A"
    label = "Emerging / Developing"
    description = "First line\nSecond line"
    scale = NativeScale(
        scale_id,
        (NativeScaleLevel(0, label, description),),
    )
    source = original.items[5]
    item = replace(
        source,
        target=EvidenceTarget(
            "review_unit",
            target_id,
            parent_target=EvidenceTargetIdentity("submission", " Submission / A "),
            standard_ids=(standard_id,),
            sequence=1,
        ),
        value=NativeScaledValue(0, scale),
        provenance=replace(
            source.provenance,
            native=NativeProvenance((NativeReference("observation", reference_id),)),
        ),
    )
    expected = EvidenceInventory((item,))

    restored = evidence_inventory_from_dict(evidence_inventory_to_dict(expected))

    assert restored == expected
    restored_item = restored.items[0]
    assert restored_item.target.target_id == target_id
    assert restored_item.target.standard_ids == (standard_id,)
    assert restored_item.provenance.native.references[0].identifier == reference_id
    assert isinstance(restored_item.value, NativeScaledValue)
    assert restored_item.value.scale.scale_id == scale_id
    assert restored_item.value.scale.levels[0].label == label
    assert restored_item.value.scale.levels[0].description == description


def test_mapping_uses_closed_evidence_value_discriminators(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    data = evidence_inventory_to_dict(inventory(fixture_loader))
    items = data["items"]
    assert isinstance(items, list)
    assert [item["value"]["kind"] for item in items] == [
        "scalar",
        "scalar",
        "scalar",
        "scalar",
        "points",
        "scaled",
        "state",
    ]


def test_unknown_and_missing_fields_fail_closed(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    data = evidence_inventory_to_dict(inventory(fixture_loader))
    with pytest.raises(EvidenceSerializationError, match="key set"):
        evidence_inventory_from_dict({**data, "unknown": True})
    with pytest.raises(EvidenceSerializationError, match="key set"):
        evidence_inventory_from_dict({})


def test_scalar_type_tag_must_agree_exactly(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    data = evidence_inventory_to_dict(inventory(fixture_loader))
    items = data["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    value = first["value"]
    assert isinstance(value, dict)
    value["scalar_type"] = "integer"
    with pytest.raises(EvidenceSerializationError, match="agree exactly"):
        evidence_inventory_from_dict(data)


def test_nonfinite_point_values_fail_before_model_construction(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    data = evidence_inventory_to_dict(inventory(fixture_loader))
    items = data["items"]
    assert isinstance(items, list)
    points = items[4]
    assert isinstance(points, dict)
    value = points["value"]
    assert isinstance(value, dict)
    value["earned"] = float("nan")
    with pytest.raises(EvidenceSerializationError, match="finite"):
        evidence_inventory_from_dict(data)


def test_inventory_order_is_contract_significant(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    original = inventory(fixture_loader)
    mapping = evidence_inventory_to_dict(original)
    items = mapping["items"]
    assert isinstance(items, list)
    mapping["items"] = list(reversed(items))
    restored = evidence_inventory_from_dict(mapping)
    assert [item.item_id for item in restored.items] == list(
        reversed([item.item_id for item in original.items])
    )
