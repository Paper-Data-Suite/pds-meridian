from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pds_core.academic_work_registrations import (
    AcademicWorkRegistration,
    academic_work_registration_from_dict,
)
from pds_core.publication_records import PublicationRecord, publication_record_from_dict

import meridian.diagnostics as diagnostics
import meridian.projection_cache as cache
from meridian.adapters import AdapterKey
from meridian.evidence import (
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    NativeProvenance,
    NativeReference,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    ProjectionIdentity,
    StudentSubject,
)
from meridian.evidence_serialization import (
    evidence_inventory_from_dict,
    evidence_inventory_to_dict,
)
from meridian.projection_cache import (
    PROJECTION_SNAPSHOT_RECORD_TYPE,
    PROJECTION_SNAPSHOT_SCHEMA_VERSION,
    ProjectionAuthorizationObservation,
    ProjectionCacheIdentity,
    ProjectionCacheValidationError,
    ProjectionExecutionIdentity,
    ProjectionSnapshot,
    ProjectionSourceObservation,
    projection_cache_key,
)

NOW = datetime(2026, 8, 18, 0, tzinfo=UTC)


def core_values(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> tuple[AcademicWorkRegistration, PublicationRecord]:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    return registration, publication


def item(
    fixture_loader: Callable[[str], dict[str, Any]],
    *,
    item_id: str,
    subject: StudentSubject | None,
    target: EvidenceTarget,
    scale: NativeScale | None = None,
    scale_value: object = 1,
    projection: ProjectionIdentity | None = None,
) -> EvidenceItem:
    registration, publication = core_values(fixture_loader)
    evidence_projection = projection or ProjectionIdentity(
        "synthetic_projection",
        "1",
        "synthetic-reader",
        "1.0.0",
    )
    provenance = EvidenceProvenance(
        publication,
        registration,
        None,
        evidence_projection,
        NativeProvenance((NativeReference("score_record", item_id),)),
    )
    native_scale = scale or NativeScale(
        "legacy_scale",
        (NativeScaleLevel(1, "Observed"),),
        contract_version="1",
    )
    return EvidenceItem(
        item_id,
        subject,
        target,
        "synthetic_score",
        NativeScaledValue(scale_value, native_scale),
        provenance,
    )


def source_and_execution(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> tuple[ProjectionSourceObservation, ProjectionExecutionIdentity]:
    registration, publication = core_values(fixture_loader)
    source = ProjectionSourceObservation(
        publication=publication,
        referenced_registration=registration,
        current_registration=registration,
        withdrawal=None,
        series_publication_ids=(publication.publication_id,),
        target_index=0,
        head_publication_id=publication.publication_id,
        successor_publication_id=None,
        canonical_state="current_selectable",
    )
    execution = ProjectionExecutionIdentity(
        AdapterKey(
            "synthetic_producer",
            "academic_result_set",
            "fixture_manifest_1",
            "fixture_contract_1",
            "assignment",
            "fixture_contract_1",
        ),
        "synthetic.adapter",
        "1",
        "1",
        "synthetic-reader",
        "1.0.0",
    )
    return source, execution


def test_non_student_subject_is_truthful_and_student_lookup_excludes_it(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    group_item = item(
        fixture_loader,
        item_id="group_score_1",
        subject=None,
        target=EvidenceTarget(
            "concord_group",
            "group_1",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
    )
    student_item = item(
        fixture_loader,
        item_id="student_score_1",
        subject=StudentSubject("student_1"),
        target=EvidenceTarget(
            "core_student",
            "student_1",
            owning_system="core",
        ),
    )
    inventory = EvidenceInventory((group_item, student_item))

    assert group_item.subject is None
    assert inventory.for_student("student_1") == (student_item,)


def test_extended_target_round_trip_preserves_legacy_mapping_shape(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    legacy = item(
        fixture_loader,
        item_id="legacy_target",
        subject=StudentSubject("student_1"),
        target=EvidenceTarget("attempt", "attempt_1", sequence=1),
    )
    legacy_mapping = evidence_inventory_to_dict(EvidenceInventory((legacy,)))
    legacy_items = legacy_mapping["items"]
    assert isinstance(legacy_items, list)
    legacy_target = legacy_items[0]["target"]
    assert isinstance(legacy_target, dict)
    assert set(legacy_target) == {
        "target_kind",
        "target_id",
        "parent_target",
        "standard_ids",
        "sequence",
    }

    extended = item(
        fixture_loader,
        item_id="group_target",
        subject=None,
        target=EvidenceTarget(
            "concord_group",
            "group_1",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
    )
    mapping = evidence_inventory_to_dict(EvidenceInventory((extended,)))
    items = mapping["items"]
    assert isinstance(items, list)
    assert items[0]["subject"] is None
    target = items[0]["target"]
    assert isinstance(target, dict)
    assert target["owning_system"] == "concord"
    assert target["contract_version"] == "concord_group_v1"

    restored = evidence_inventory_from_dict(mapping)
    assert restored == EvidenceInventory((extended,))


def test_rich_native_scale_round_trip_preserves_exact_metadata_and_legacy_shape(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    legacy = item(
        fixture_loader,
        item_id="legacy_scale_item",
        subject=StudentSubject("student_1"),
        target=EvidenceTarget("criterion", "criterion_1"),
    )
    legacy_mapping = evidence_inventory_to_dict(EvidenceInventory((legacy,)))
    legacy_items = legacy_mapping["items"]
    assert isinstance(legacy_items, list)
    legacy_value = legacy_items[0]["value"]
    assert isinstance(legacy_value, dict)
    legacy_scale = legacy_value["scale"]
    assert isinstance(legacy_scale, dict)
    assert set(legacy_scale) == {
        "scale_id",
        "contract_version",
        "order_is_meaningful",
        "levels",
    }

    rich_scale = NativeScale(
        "scale_2",
        (
            NativeScaleLevel(
                value="developing",
                label="Developing",
                description="Evidence is emerging.",
                meaning="Partial command of the criterion.",
                position=1,
            ),
            NativeScaleLevel(
                value="meeting",
                label="Meeting",
                description="Evidence is consistent.",
                meaning="Meets the criterion.",
                position=3,
            ),
        ),
        lineage_id="scale_lineage_1",
        name="Teacher-defined rubric",
        revision=2,
        scale_type="ordinal",
        status="active",
        supersedes_scale_id="scale_1",
    )
    rich = item(
        fixture_loader,
        item_id="rich_scale_item",
        subject=StudentSubject("student_1"),
        target=EvidenceTarget(
            "criterion",
            "criterion_1",
            owning_system="concord",
            contract_version="concord_criterion_v1",
        ),
        scale=rich_scale,
        scale_value="meeting",
    )
    mapping = evidence_inventory_to_dict(EvidenceInventory((rich,)))
    restored = evidence_inventory_from_dict(mapping)
    assert restored == EvidenceInventory((rich,))

    restored_value = restored.items[0].value
    assert isinstance(restored_value, NativeScaledValue)
    scale = restored_value.scale
    assert scale.lineage_id == "scale_lineage_1"
    assert scale.name == "Teacher-defined rubric"
    assert scale.revision == 2
    assert scale.scale_type == "ordinal"
    assert scale.status == "active"
    assert scale.supersedes_scale_id == "scale_1"
    assert scale.levels[0].meaning == "Partial command of the criterion."
    assert scale.levels[0].position == 1
    assert scale.levels[1].position == 3


def test_student_scoped_cache_rejects_non_student_evidence(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    source, execution = source_and_execution(fixture_loader)
    group_item = item(
        fixture_loader,
        item_id="group_score_1",
        subject=None,
        target=EvidenceTarget(
            "concord_group",
            "group_1",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
        projection=execution.evidence_projection_identity,
    )
    assert cache._scoped_inventory(
        EvidenceInventory((group_item,)),
        ("student_1",),
    ).items == ()

    scoped = ProjectionAuthorizationObservation(
        "project_evidence",
        "grading_import",
        ("student_1",),
        "district_policy",
        "1",
    )
    identity = ProjectionCacheIdentity(
        PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        source,
        execution,
        scoped,
    )

    with pytest.raises(
        ProjectionCacheValidationError,
        match="outside the authorized student scope",
    ):
        ProjectionSnapshot(
            PROJECTION_SNAPSHOT_SCHEMA_VERSION,
            PROJECTION_SNAPSHOT_RECORD_TYPE,
            projection_cache_key(identity),
            NOW,
            source,
            execution,
            scoped,
            EvidenceInventory((group_item,)),
        )

    unscoped = ProjectionAuthorizationObservation(
        "project_evidence",
        "grading_import",
        (),
        "district_policy",
        "1",
    )
    unscoped_identity = ProjectionCacheIdentity(
        PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        source,
        execution,
        unscoped,
    )
    snapshot = ProjectionSnapshot(
        PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        PROJECTION_SNAPSHOT_RECORD_TYPE,
        projection_cache_key(unscoped_identity),
        NOW,
        source,
        execution,
        unscoped,
        EvidenceInventory((group_item,)),
    )
    assert snapshot.inventory.items == (group_item,)


def test_diagnostics_do_not_individualize_non_student_evidence(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    group_item = item(
        fixture_loader,
        item_id="group_score_1",
        subject=None,
        target=EvidenceTarget(
            "concord_group",
            "group_1",
            owning_system="concord",
            contract_version="concord_group_v1",
        ),
    )
    filters = diagnostics.EvidenceFilters(student_ids=("student_1",))

    assert not diagnostics._matches_filters(group_item, filters)

    rendered = diagnostics._evidence_item_to_dict(group_item)
    assert rendered["student_id"] is None
    target = rendered["target"]
    assert isinstance(target, dict)
    assert target["owning_system"] == "concord"
    assert target["contract_version"] == "concord_group_v1"
