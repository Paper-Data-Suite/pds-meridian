from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import DiagnosticsDependencies
from meridian.guided_projection import (
    GUIDED_EVIDENCE_REVIEW_PURPOSE_ID,
    GuidedProjectionAuthorizationUnavailableError,
    GuidedProjectionCurrentUseBlockedError,
    GuidedProjectionDependencies,
    GuidedProjectionSelectionStaleError,
    GuidedProjectionServices,
    prepare_guided_evidence_projection,
)

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
PUBLICATION_ID = "pub_11111111111111111111111111111111"
CACHE_KEY = "a" * 64


def _diagnostics(*, authorizer: object | None = object()) -> DiagnosticsDependencies:
    return cast(
        DiagnosticsDependencies,
        SimpleNamespace(
            authorizer=authorizer,
            producer_registry_state="available",
            producer_registry=object(),
            adapter_registry=object(),
            distribution_version_resolver=object(),
        ),
    )


def test_guided_projection_owns_purpose_and_whole_assignment_scope() -> None:
    calls: list[tuple[object, ...]] = []
    candidate = object()
    prepared = object()
    inventory = object()
    cached = SimpleNamespace(
        disposition="created",
        stored=SimpleNamespace(cache_key=CACHE_KEY),
    )
    authorized = SimpleNamespace(
        current_context=SimpleNamespace(
            publication=SimpleNamespace(
                publication_id=PUBLICATION_ID,
                work=WORK,
            )
        ),
        assessment=SimpleNamespace(reusable_for_current_use=True),
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(
                inventory=SimpleNamespace(items=("one", "two")),
            )
        ),
    )

    services = GuidedProjectionServices(
        candidate_resolver=lambda root, work, publication_id: (
            calls.append(("candidate", root, work, publication_id))
            or cast(object, candidate)
        ),
        invocation_preparer=lambda root, selected, diagnostics, purpose, students: (
            calls.append(
                ("prepare", root, selected, diagnostics, purpose, students)
            )
            or cast(object, prepared)
        ),
        projection_runner=lambda selected, diagnostics: (
            calls.append(("project", selected, diagnostics))
            or cast(object, inventory)
        ),
        cache_writer=lambda root, selected, projected, diagnostics: (
            calls.append(("cache", root, selected, projected, diagnostics))
            or cast(object, cached)
        ),
        cache_loader=lambda root, pub, key, diag, purpose, students: (
            calls.append(
                (
                    "load",
                    root,
                    pub,
                    key,
                    diag,
                    purpose,
                    students,
                )
            )
            or cast(object, authorized)
        ),
    )
    dependencies = GuidedProjectionDependencies(
        diagnostics=_diagnostics(),
        services=services,
    )

    result = prepare_guided_evidence_projection(
        Path("workspace"),
        WORK,
        PUBLICATION_ID,
        dependencies=dependencies,
    )

    assert result.purpose_id == GUIDED_EVIDENCE_REVIEW_PURPOSE_ID
    assert result.purpose_id == "review_evidence"
    assert result.requested_student_ids == ()
    assert result.cache_disposition == "created"
    assert result.evidence_count == 2
    assert not hasattr(result, "cache_key")

    prepare_call = next(call for call in calls if call[0] == "prepare")
    assert prepare_call[-2:] == ("review_evidence", ())
    load_call = next(call for call in calls if call[0] == "load")
    assert load_call[3] == CACHE_KEY
    assert load_call[-2:] == ("review_evidence", ())


def test_missing_authorizer_fails_before_discovery_or_projection() -> None:
    called = False

    def candidate_resolver(
        _root: Path,
        _work: ModuleWorkRef,
        _publication_id: str,
    ) -> object:
        nonlocal called
        called = True
        return object()

    dependencies = GuidedProjectionDependencies(
        diagnostics=_diagnostics(authorizer=None),
        services=GuidedProjectionServices(
            candidate_resolver=cast(object, candidate_resolver)
        ),
    )

    with pytest.raises(GuidedProjectionAuthorizationUnavailableError):
        prepare_guided_evidence_projection(
            Path("workspace"),
            WORK,
            PUBLICATION_ID,
            dependencies=dependencies,
        )

    assert called is False


def test_stale_selected_publication_is_not_guessed_or_replaced() -> None:
    def stale(
        _root: Path,
        _work: ModuleWorkRef,
        _publication_id: str,
    ) -> object:
        raise GuidedProjectionSelectionStaleError("stale")

    dependencies = GuidedProjectionDependencies(
        diagnostics=_diagnostics(),
        services=GuidedProjectionServices(candidate_resolver=cast(object, stale)),
    )

    with pytest.raises(GuidedProjectionSelectionStaleError):
        prepare_guided_evidence_projection(
            Path("workspace"),
            WORK,
            PUBLICATION_ID,
            dependencies=dependencies,
        )


def test_nonreusable_authorized_snapshot_fails_closed() -> None:
    candidate = object()
    prepared = object()
    inventory = object()
    cached = SimpleNamespace(
        disposition="existing",
        stored=SimpleNamespace(cache_key=CACHE_KEY),
    )
    authorized = SimpleNamespace(
        current_context=SimpleNamespace(
            publication=SimpleNamespace(
                publication_id=PUBLICATION_ID,
                work=WORK,
            )
        ),
        assessment=SimpleNamespace(reusable_for_current_use=False),
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(inventory=SimpleNamespace(items=())),
        ),
    )
    services = GuidedProjectionServices(
        candidate_resolver=lambda *_args: cast(object, candidate),
        invocation_preparer=lambda *_args: cast(object, prepared),
        projection_runner=lambda *_args: cast(object, inventory),
        cache_writer=lambda *_args: cast(object, cached),
        cache_loader=lambda *_args: cast(object, authorized),
    )

    with pytest.raises(GuidedProjectionCurrentUseBlockedError):
        prepare_guided_evidence_projection(
            Path("workspace"),
            WORK,
            PUBLICATION_ID,
            dependencies=GuidedProjectionDependencies(
                diagnostics=_diagnostics(),
                services=services,
            ),
        )


def test_guided_projection_reuses_existing_ingestion_and_cache_services() -> None:
    source = Path("meridian/guided_projection.py").read_text(encoding="utf-8")

    for required in (
        "discover_publication_candidates(",
        "prepare_publication_invocation(",
        ".adapter_registry.invoke(",
        "cache_projected_inventory(",
        "load_authorized_projection_snapshot(",
    ):
        assert required in source

    for forbidden in (
        "_verify_manifest(",
        "_read_manifest_bytes(",
        "projection_cache_key(",
        "verify_publication_manifest(",
    ):
        assert forbidden not in source
