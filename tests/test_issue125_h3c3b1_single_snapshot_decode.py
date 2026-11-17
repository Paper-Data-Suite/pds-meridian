"""#125-H3C3B1: avoid a second snapshot JSON decode during authorized reads.

These use synthetic producer data. Authorization remains an independent
requirement; the byte/digest and direct-constructor integrity gates stay live.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_projection_cache_storage import (
    NOW,
    RecordingAuthorizer,
    SyntheticAdapter,
    one_item,
    prepared,
    profile_registry,
)

import meridian.projection_cache as cache
from meridian.adapters import AdapterRegistry


def _create_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[object, object, Path]:
    value, _, manifest = prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cache,
        "load_canonical_publication_context",
        lambda root, publication_id: value.canonical_context,
    )
    created = cache.cache_projected_inventory(
        tmp_path,
        value,
        one_item(value),
        authorizer=RecordingAuthorizer(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        cache,
        "verify_publication_manifest",
        lambda root, publication: manifest,
    )
    return value, created.stored, manifest


def test_authorized_read_decodes_snapshot_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    value, stored, _ = _create_snapshot(monkeypatch, tmp_path)
    actual_parser = cache.projection_snapshot_from_json_bytes
    decoded: list[bytes] = []

    def counted_parser(content: bytes) -> cache.ProjectionSnapshot:
        decoded.append(content)
        return actual_parser(content)

    monkeypatch.setattr(cache, "projection_snapshot_from_json_bytes", counted_parser)
    authorized = cache.load_authorized_projection_snapshot(
        tmp_path,
        value.canonical_context.publication.publication_id,
        stored.cache_key,
        authorizer=RecordingAuthorizer(),
        authorization_purpose_id="grading_import",
        producer_registry=profile_registry(),
        adapter_registry=AdapterRegistry((SyntheticAdapter(),)),
        distribution_version_resolver=lambda name: "1.0.0",
    )
    assert authorized.assessment.reusable_for_current_use
    assert authorized.stored.snapshot_digest == stored.snapshot_digest
    assert decoded == [stored.content], "One validated parse per authorized load"


def test_direct_constructor_still_rejects_noncanonical_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, stored, _ = _create_snapshot(monkeypatch, tmp_path)
    changed = stored.content.replace(b"\n", b"\r\n", 1)
    assert changed != stored.content
    with pytest.raises(cache.ProjectionCacheValidationError, match="canonical"):
        cache.StoredProjectionSnapshot(
            snapshot=stored.snapshot,
            cache_key=stored.cache_key,
            snapshot_digest=hashlib.sha256(changed).hexdigest(),
            path=stored.path,
            relative_path=stored.relative_path,
            content=changed,
        )

    with pytest.raises(cache.ProjectionCacheValidationError, match="snapshot_digest"):
        cache.StoredProjectionSnapshot(
            snapshot=stored.snapshot,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            path=stored.path,
            relative_path=stored.relative_path,
            content=changed,
        )

    changed_snapshot = replace(
        stored.snapshot,
        captured_at=stored.snapshot.captured_at + timedelta(seconds=1),
    )
    with pytest.raises(cache.ProjectionCacheValidationError, match="canonical"):
        cache.StoredProjectionSnapshot(
            snapshot=changed_snapshot,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            path=stored.path,
            relative_path=stored.relative_path,
            content=stored.content,
        )
