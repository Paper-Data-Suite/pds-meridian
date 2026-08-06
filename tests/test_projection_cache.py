from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pds_core.academic_work_registrations import academic_work_registration_from_dict
from pds_core.publication_records import (
    PublicationWithdrawal,
    publication_record_from_dict,
)

from meridian.adapters import AdapterKey
from meridian.evidence import EvidenceInventory
from meridian.ingestion import (
    CanonicalPublicationContext,
    PublicationSeriesMember,
    PublicationSeriesObservation,
)
from meridian.projection_cache import (
    PROJECTION_SNAPSHOT_RECORD_TYPE,
    PROJECTION_SNAPSHOT_SCHEMA_VERSION,
    ProjectionAuthorizationObservation,
    ProjectionCacheIdentity,
    ProjectionCacheIntegrityError,
    ProjectionCacheValidationError,
    ProjectionExecutionIdentity,
    ProjectionSnapshot,
    ProjectionSourceObservation,
    projection_cache_key,
    projection_cache_path,
    projection_cache_relative_path,
    projection_snapshot_from_json_bytes,
    projection_snapshot_to_json_bytes,
)

CAPTURED = datetime(2026, 8, 6, 12, tzinfo=UTC)


def context(
    fixture_loader: Callable[[str], dict[str, Any]],
    *,
    state: str = "current_selectable",
) -> CanonicalPublicationContext:
    registration = academic_work_registration_from_dict(
        fixture_loader("core_v0_6/baseline_registration.json")
    )
    publication = publication_record_from_dict(
        fixture_loader("core_v0_6/baseline_publication.json")
    )
    withdrawal: PublicationWithdrawal | None = None
    if state in {"withdrawn_head", "withdrawn_historical"}:
        withdrawal = PublicationWithdrawal(
            "1",
            "publication_withdrawal",
            publication.publication_id,
            CAPTURED,
            "Synthetic withdrawal",
        )
    members = (PublicationSeriesMember(publication, withdrawal),)
    series = PublicationSeriesObservation(
        members,
        publication.publication_id,
        0,
        publication.publication_id,
        state,
        None,
    )
    return CanonicalPublicationContext(
        publication,
        registration,
        registration,
        series,
        withdrawal,
    )


def identities(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> tuple[
    ProjectionSourceObservation,
    ProjectionExecutionIdentity,
    ProjectionAuthorizationObservation,
]:
    source = ProjectionSourceObservation.from_context(context(fixture_loader))
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
    authorization = ProjectionAuthorizationObservation(
        "project_evidence",
        "grading_import",
        (),
        "district_policy",
        "1",
    )
    return source, execution, authorization


def snapshot(
    fixture_loader: Callable[[str], dict[str, Any]],
    *,
    captured_at: datetime = CAPTURED,
) -> ProjectionSnapshot:
    source, execution, authorization = identities(fixture_loader)
    identity = ProjectionCacheIdentity(
        PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        source,
        execution,
        authorization,
    )
    return ProjectionSnapshot(
        PROJECTION_SNAPSHOT_SCHEMA_VERSION,
        PROJECTION_SNAPSHOT_RECORD_TYPE,
        projection_cache_key(identity),
        captured_at,
        source,
        execution,
        authorization,
        EvidenceInventory(()),
    )


def test_snapshot_constants_and_round_trip(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    value = snapshot(fixture_loader)
    first = projection_snapshot_to_json_bytes(value)
    second = projection_snapshot_to_json_bytes(value)
    assert first == second
    assert first.endswith(b"\n")
    assert projection_snapshot_from_json_bytes(first) == value
    mapping = json.loads(first)
    assert set(mapping) == {
        "schema_version",
        "record_type",
        "cache_key",
        "captured_at",
        "source",
        "projection",
        "authorization",
        "inventory",
    }


def test_snapshot_parser_rejects_duplicate_keys(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    data = projection_snapshot_to_json_bytes(snapshot(fixture_loader))
    duplicated = data.replace(
        b'{\n  "authorization":',
        b'{\n  "schema_version": "1",\n  "authorization":',
        1,
    )
    with pytest.raises(ProjectionCacheValidationError, match="duplicate"):
        projection_snapshot_from_json_bytes(duplicated)


def test_snapshot_parser_rejects_noncanonical_equivalent_json(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    canonical = projection_snapshot_to_json_bytes(snapshot(fixture_loader))
    compact = json.dumps(json.loads(canonical), sort_keys=True).encode("utf-8")
    with pytest.raises(ProjectionCacheIntegrityError, match="canonical"):
        projection_snapshot_from_json_bytes(compact)


def test_cache_key_excludes_capture_time_and_inventory(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    first = snapshot(fixture_loader)
    later = replace(first, captured_at=datetime(2026, 8, 7, 12, tzinfo=UTC))
    assert first.cache_key == later.cache_key
    assert (
        projection_snapshot_to_json_bytes(first)
        != projection_snapshot_to_json_bytes(later)
    )


def test_material_identity_change_changes_cache_key(
    fixture_loader: Callable[[str], dict[str, Any]],
) -> None:
    source, execution, authorization = identities(fixture_loader)
    original = ProjectionCacheIdentity("1", source, execution, authorization)
    changed = ProjectionCacheIdentity(
        "1",
        source,
        replace(execution, producer_reader_version="1.0.1"),
        authorization,
    )
    assert projection_cache_key(original) != projection_cache_key(changed)


def test_canonical_cache_path_is_digest_bound(tmp_path: Path) -> None:
    publication = "pub_11111111111111111111111111111111"
    key = "a" * 64
    digest = "b" * 64
    relative = projection_cache_relative_path(publication, key, digest)
    assert relative == (
        "cache/meridian/projections/"
        f"{publication}/{key}/{digest}.json"
    )
    assert projection_cache_path(tmp_path, publication, key, digest) == (
        tmp_path
        / "cache"
        / "meridian"
        / "projections"
        / publication
        / key
        / f"{digest}.json"
    )


@pytest.mark.parametrize(
    "publication_id",
    [
        "../pub_11111111111111111111111111111111",
        "pub_gggggggggggggggggggggggggggggggg",
        "PUB_11111111111111111111111111111111",
    ],
)
def test_cache_path_rejects_invalid_publication_identity(
    tmp_path: Path,
    publication_id: str,
) -> None:
    with pytest.raises(ProjectionCacheValidationError):
        projection_cache_path(tmp_path, publication_id, "a" * 64, "b" * 64)
