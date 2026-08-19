from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from meridian.evidence import EvidenceInventory, NativeScalarValue
from meridian.projection_cache import (
    ProjectionCacheNondeterminismError,
    cache_projected_inventory,
)
from tests.cross_producer_test_support import exact_reader_version
from tests.cross_producer_workspace_support import build_mixed_workspace, prepare_all


def _scoreform_projection(tmp_path: Path):
    mixed = build_mixed_workspace(tmp_path)
    prepared = prepare_all(mixed)["scoreform"]
    inventory = mixed.adapter_registry.invoke(
        prepared.projection_request,
        exact_reader_version,
    )
    return mixed, prepared, inventory


def test_replay_detects_negative_zero_serialization_difference(
    tmp_path: Path,
) -> None:
    mixed, prepared, projected = _scoreform_projection(tmp_path)
    first = projected.items[0]

    positive_zero = EvidenceInventory(
        (
            replace(first, value=NativeScalarValue(0.0)),
            *projected.items[1:],
        )
    )
    negative_zero = EvidenceInventory(
        (
            replace(first, value=NativeScalarValue(-0.0)),
            *projected.items[1:],
        )
    )

    # Python value equality collapses the signed-zero distinction even though
    # canonical JSON persistence preserves 0.0 and -0.0 as different bytes.
    assert positive_zero == negative_zero

    created = cache_projected_inventory(
        mixed.root,
        prepared,
        positive_zero,
        authorizer=mixed.authorizer,
    )
    assert created.disposition == "created"

    with pytest.raises(ProjectionCacheNondeterminismError) as caught:
        cache_projected_inventory(
            mixed.root,
            prepared,
            negative_zero,
            authorizer=mixed.authorizer,
        )

    assert caught.value.code == "cache.projection_nondeterministic"
    assert caught.value.cache_key == created.stored.cache_key
    assert caught.value.snapshot_digest == created.stored.snapshot_digest


def test_replay_detects_timezone_representation_difference(
    tmp_path: Path,
) -> None:
    mixed, prepared, projected = _scoreform_projection(tmp_path)
    first = projected.items[0]
    native = first.provenance.native
    timestamp = native.timestamps[0]

    shifted_value = timestamp.value.astimezone(
        timezone(timedelta(hours=5, minutes=45))
    )
    assert shifted_value == timestamp.value
    assert shifted_value.isoformat() != timestamp.value.isoformat()

    shifted_timestamp = replace(timestamp, value=shifted_value)
    shifted_native = replace(
        native,
        timestamps=(shifted_timestamp, *native.timestamps[1:]),
    )
    shifted_provenance = replace(first.provenance, native=shifted_native)
    shifted_inventory = EvidenceInventory(
        (
            replace(first, provenance=shifted_provenance),
            *projected.items[1:],
        )
    )

    # Datetime equality compares instants, while the persistence contract
    # retains the producer-native offset representation.
    assert projected == shifted_inventory

    created = cache_projected_inventory(
        mixed.root,
        prepared,
        projected,
        authorizer=mixed.authorizer,
    )
    assert created.disposition == "created"

    with pytest.raises(ProjectionCacheNondeterminismError) as caught:
        cache_projected_inventory(
            mixed.root,
            prepared,
            shifted_inventory,
            authorizer=mixed.authorizer,
        )

    assert caught.value.code == "cache.projection_nondeterministic"
    assert caught.value.cache_key == created.stored.cache_key


def test_cache_documentation_guards_canonical_replay_rule() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    architecture = Path(
        "docs/architecture/exact-projection-snapshots-and-cache.md"
    ).read_text(encoding="utf-8")

    assert "canonical serialized inventory bytes" in checker
    assert "canonical serialized inventory bytes" in architecture
    assert "Python object equality" in architecture
