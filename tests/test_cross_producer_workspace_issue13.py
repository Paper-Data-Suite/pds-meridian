from __future__ import annotations

from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog

import meridian.ingestion as ingestion
from meridian.projection_cache import (
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
from tests.cross_producer_test_support import (
    SHARED_STUDENT_ID,
    exact_reader_version,
)
from tests.cross_producer_workspace_support import (
    CLASS_ID,
    CONCORD_SOURCE,
    build_mixed_workspace,
    prepare_all,
    project_and_cache_all,
    supersede_scoreform,
    withdraw_quillan,
)


def _never_clock() -> object:
    raise AssertionError("exact replay must not call the clock")


def test_real_core_workspace_projects_and_exactly_replays_three_producers(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    prepared = prepare_all(mixed)
    projected = project_and_cache_all(mixed, prepared)

    assert {
        value.prepared.canonical_context.publication.work.class_id
        for value in projected.values()
    } == {CLASS_ID}
    assert {
        value.prepared.adapter_match.descriptor.adapter_id
        for value in projected.values()
    } == {
        "scoreform.academic_result",
        "quillan.academic_result",
        "concord.academic_result",
    }

    assert mixed.publications["scoreform"].source_record is None
    assert mixed.publications["quillan"].source_record is None
    assert mixed.publications["concord"].source_record == CONCORD_SOURCE

    cache_keys = {
        value.cached.stored.cache_key
        for value in projected.values()
    }
    assert len(cache_keys) == 3

    for value in projected.values():
        assert value.cached.disposition == "created"
        assert value.cached.stored.snapshot.inventory == value.inventory
        assert all(
            item.eligibility.status == "unevaluated"
            for item in value.inventory.items
        )

        replay = cache_projected_inventory(
            mixed.root,
            value.prepared,
            value.inventory,
            authorizer=mixed.authorizer,
            clock=_never_clock,
        )
        assert replay.disposition == "existing"
        assert replay.stored.content == value.cached.stored.content
        assert (
            replay.stored.snapshot.captured_at
            == value.cached.stored.snapshot.captured_at
        )


def test_student_scope_keeps_exact_students_and_excludes_concord_group(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    prepared = prepare_all(
        mixed,
        requested_student_ids=(SHARED_STUDENT_ID,),
    )
    projected = project_and_cache_all(mixed, prepared)

    for module_id, value in projected.items():
        cached_items = value.cached.stored.snapshot.inventory.items
        assert cached_items, module_id
        assert all(item.subject is not None for item in cached_items)
        assert {
            item.subject.student_id
            for item in cached_items
            if item.subject is not None
        } == {SHARED_STUDENT_ID}

    concord = projected["concord"]
    assert any(item.subject is None for item in concord.inventory.items)
    assert not any(
        item.subject is None
        for item in concord.cached.stored.snapshot.inventory.items
    )
    assert [
        item.result_kind
        for item in concord.cached.stored.snapshot.inventory.items
    ] == ["standard_backed_score"]


def test_supersession_withdrawal_and_unchanged_cache_state_are_isolated(
    tmp_path: Path,
) -> None:
    mixed = build_mixed_workspace(tmp_path)
    projected = project_and_cache_all(mixed, prepare_all(mixed))
    original_bytes = {
        module_id: value.cached.stored.content
        for module_id, value in projected.items()
    }

    successor = supersede_scoreform(mixed)
    withdraw_quillan(mixed)
    rebuild_academic_catalog(mixed.root)

    scoreform_current = ingestion.discover_publication_candidates(
        mixed.root,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="scoreform",
                state="current",
                limit=10,
            )
        ),
    )
    assert [item.publication_id for item in scoreform_current.candidates] == [
        successor.publication_id
    ]

    quillan_current = ingestion.discover_publication_candidates(
        mixed.root,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="quillan",
                state="current",
                limit=10,
            )
        ),
    )
    assert quillan_current.candidates == ()

    expected = {
        "scoreform": ("superseded", "historical_only"),
        "quillan": ("withdrawn", "historical_only"),
        "concord": ("current", "reusable"),
    }
    for module_id, value in projected.items():
        loaded = load_authorized_projection_snapshot(
            mixed.root,
            mixed.publications[module_id].publication_id,
            value.cached.stored.cache_key,
            authorizer=mixed.authorizer,
            authorization_purpose_id="grading_import",
            producer_registry=mixed.producer_registry,
            adapter_registry=mixed.adapter_registry,
            distribution_version_resolver=exact_reader_version,
        )
        assert (
            loaded.assessment.source_status,
            loaded.assessment.reuse_status,
        ) == expected[module_id]
        assert loaded.stored.content == original_bytes[module_id]
        assert value.cached.stored.path.read_bytes() == original_bytes[module_id]

    assert projected["quillan"].cached.stored.snapshot.source.withdrawal is None
    assert (
        projected["concord"].cached.stored.snapshot.source.canonical_state
        == "current_selectable"
    )
