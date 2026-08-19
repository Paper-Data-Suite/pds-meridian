from __future__ import annotations

from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path

import pytest

import meridian.projection_cache as cache
from meridian.evidence import EvidenceInventory, NativeScalarValue
from meridian.projection_cache import (
    ProjectionCacheNondeterminismError,
    cache_projected_inventory,
)
from tests.cross_producer_test_support import (
    SECONDARY_STUDENT_ID,
    SHARED_STUDENT_ID,
    exact_reader_version,
)
from tests.cross_producer_workspace_support import (
    build_mixed_workspace,
    prepare_all,
    project_and_cache_all,
)


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

def test_cache_scope_mismatch_fails_before_protected_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    prepared = prepare_all(
        mixed,
        requested_student_ids=(SECONDARY_STUDENT_ID,),
    )
    projected = project_and_cache_all(mixed, prepared)

    marker_names: list[str] = []
    for value in projected.values():
        markers = tuple(value.cached.stored.path.parent.glob(".scope-*"))
        assert len(markers) == 1
        marker_names.append(markers[0].name)

    assert all(SHARED_STUDENT_ID not in name for name in marker_names)
    assert all(SECONDARY_STUDENT_ID not in name for name in marker_names)

    opened_paths: list[Path] = []
    original = cache._read_bounded

    def tracked(path: Path, **kwargs: object) -> bytes:
        opened_paths.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(cache, "_read_bounded", tracked)

    for module_id, value in projected.items():
        with pytest.raises(cache.ProjectionCacheAuthorizationError) as caught:
            cache.load_authorized_projection_snapshot(
                mixed.root,
                mixed.publications[module_id].publication_id,
                value.cached.stored.cache_key,
                authorizer=mixed.authorizer,
                authorization_purpose_id="grading_import",
                requested_student_ids=(SHARED_STUDENT_ID,),
                producer_registry=mixed.producer_registry,
                adapter_registry=mixed.adapter_registry,
                distribution_version_resolver=exact_reader_version,
            )
        assert caught.value.cache_key == value.cached.stored.cache_key
        assert caught.value.publication_id == (
            mixed.publications[module_id].publication_id
        )

    assert opened_paths == []


def test_cache_scope_authorization_rule_is_documentation_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")
    architecture = Path(
        "docs/architecture/exact-projection-snapshots-and-cache.md"
    ).read_text(encoding="utf-8")

    assert "authorization_scope_digest" in checker
    assert "authorization_scope_digest" in architecture
    assert "before opening snapshot bytes" in checker
    assert "before opening snapshot bytes" in architecture

def test_cache_purpose_mismatch_fails_before_protected_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    prepared = prepare_all(
        mixed,
        requested_student_ids=(SHARED_STUDENT_ID,),
    )
    projected = project_and_cache_all(mixed, prepared)

    opened_paths: list[Path] = []
    original = cache._read_bounded

    def tracked(path: Path, **kwargs: object) -> bytes:
        opened_paths.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(cache, "_read_bounded", tracked)

    for module_id, value in projected.items():
        with pytest.raises(cache.ProjectionCacheAuthorizationError) as caught:
            cache.load_authorized_projection_snapshot(
                mixed.root,
                mixed.publications[module_id].publication_id,
                value.cached.stored.cache_key,
                authorizer=mixed.authorizer,
                authorization_purpose_id="reporting_preview",
                requested_student_ids=(SHARED_STUDENT_ID,),
                producer_registry=mixed.producer_registry,
                adapter_registry=mixed.adapter_registry,
                distribution_version_resolver=exact_reader_version,
            )
        assert caught.value.cache_key == value.cached.stored.cache_key
        assert caught.value.publication_id == (
            mixed.publications[module_id].publication_id
        )

    assert opened_paths == []

def test_release_facing_descriptions_do_not_claim_unimplemented_grading() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    cli = Path("meridian/cli.py").read_text(encoding="utf-8")
    readme = Path("README").read_text(encoding="utf-8")

    expected = (
        "Publication ingestion and typed evidence diagnostics for Paper Data Suite"
    )
    assert f'description = "{expected}"' in pyproject
    assert "Policy-driven grading, evidence aggregation, and reporting" not in pyproject
    assert "publication-ingestion and typed-evidence" in cli
    assert "grading-policy" not in cli
    assert (
        "ScoreForm v0.10.0, Quillan v0.9.0, and Concord v0.2.0 adapters"
        in readme
    )

def test_durable_release_audit_is_indexed_and_validation_guarded() -> None:
    audit = Path("docs/development/v0.1.1-release-audit.md").read_text(
        encoding="utf-8"
    )
    index = Path("docs/README.md").read_text(encoding="utf-8")
    checker = Path("scripts/check_documentation.py").read_text(encoding="utf-8")

    assert "Substantive audit: **passed**" in audit
    assert "275/275" in audit
    assert "v0.1.1-release-audit.md" in index
    assert "v0.1.1-release-audit.md" in checker
    assert "all eight GitHub Actions matrix jobs" in checker

def test_release_candidate_version_and_changelog_are_finalized() -> None:
    version_source = Path("meridian/_version.py").read_text(encoding="utf-8")
    package_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    audit = Path("docs/development/v0.1.1-release-audit.md").read_text(
        encoding="utf-8"
    )

    assert '__version__: Final[str] = "0.1.1"' in version_source
    assert 'EXPECTED_VERSION = "0.1.1"' in package_checker
    assert 'EXPECTED_VERSION = "0.1.1"' in sdist_checker
    assert "## 0.1.1 — 2026-08-18" in changelog
    assert "## Unreleased" not in changelog
    assert "canonical serialized" in changelog
    assert "before protected snapshot bytes are opened" in changelog

    for relative in (
        "README",
        "docs/README.md",
        "docs/development/package-foundation.md",
        "docs/architecture/typed-evidence-inventory.md",
    ):
        assert "0.1.1.dev0" not in Path(relative).read_text(encoding="utf-8")

    assert "Starting package version: `0.1.1.dev0`" in audit
    assert "Release-candidate version: `0.1.1`" in audit
    assert "- [x] promote version metadata" in audit
    assert "- [x] finalize the changelog" in audit
