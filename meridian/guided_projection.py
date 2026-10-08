"""Guided authorized projection preparation for Issue #110."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, TypeAlias

from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.routing_models import ModuleWorkRef

from meridian.adapters import AdapterError
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence import EvidenceInventory
from meridian.ingestion import (
    PreparedPublicationInvocation,
    PublicationAuthorizationDeniedError,
    PublicationCandidate,
    PublicationDiscoveryRequest,
    PublicationIngestionError,
    discover_publication_candidates,
    prepare_publication_invocation,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheAuthorizationDeniedError,
    ProjectionCacheDisposition,
    ProjectionCacheError,
    ProjectionCacheWriteResult,
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)

GUIDED_EVIDENCE_REVIEW_PURPOSE_ID: Final[str] = "review_evidence"
_GUIDED_CANDIDATE_LIMIT: Final[int] = 256

CandidateResolver: TypeAlias = Callable[
    [Path, ModuleWorkRef, str],
    PublicationCandidate,
]
InvocationPreparer: TypeAlias = Callable[
    [
        Path,
        PublicationCandidate,
        DiagnosticsDependencies,
        str,
        tuple[str, ...],
    ],
    PreparedPublicationInvocation,
]
ProjectionRunner: TypeAlias = Callable[
    [PreparedPublicationInvocation, DiagnosticsDependencies],
    EvidenceInventory,
]
CacheWriter: TypeAlias = Callable[
    [
        Path,
        PreparedPublicationInvocation,
        EvidenceInventory,
        DiagnosticsDependencies,
    ],
    ProjectionCacheWriteResult,
]
CacheLoader: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        DiagnosticsDependencies,
        str,
        tuple[str, ...],
    ],
    AuthorizedProjectionSnapshot,
]


class GuidedProjectionError(RuntimeError):
    """Base failure for teacher-guided projection preparation."""

    code = "guided_projection.error"


class GuidedProjectionAuthorizationUnavailableError(GuidedProjectionError):
    """Raised when the deployment has no authorization capability."""

    code = "guided_projection.authorization_unavailable"


class GuidedProjectionAuthorizationDeniedError(GuidedProjectionError):
    """Raised when the deployment denies the selected evidence use."""

    code = "guided_projection.authorization_denied"


class GuidedProjectionSupportUnavailableError(GuidedProjectionError):
    """Raised when producer compatibility support cannot be established."""

    code = "guided_projection.support_unavailable"


class GuidedProjectionSelectionStaleError(GuidedProjectionError):
    """Raised when the selected publication is no longer a current candidate."""

    code = "guided_projection.selection_stale"


class GuidedProjectionPreparationError(GuidedProjectionError):
    """Raised when existing ingestion/projection/cache services fail safely."""

    code = "guided_projection.preparation_failed"


class GuidedProjectionCurrentUseBlockedError(GuidedProjectionError):
    """Raised when the authorized snapshot is not reusable for current use."""

    code = "guided_projection.current_use_blocked"


def _require_authorized_dependencies(
    diagnostics: DiagnosticsDependencies,
) -> tuple[object, object]:
    authorizer = diagnostics.authorizer
    if authorizer is None:
        raise GuidedProjectionAuthorizationUnavailableError(
            "Evidence authorization is not configured for this Meridian process."
        )
    if (
        diagnostics.producer_registry_state != "available"
        or diagnostics.producer_registry is None
    ):
        raise GuidedProjectionSupportUnavailableError(
            "Producer compatibility metadata is unavailable."
        )
    return diagnostics.producer_registry, authorizer


def _resolve_current_candidate(
    workspace_root: Path,
    work: ModuleWorkRef,
    publication_id: str,
) -> PublicationCandidate:
    request = PublicationDiscoveryRequest(
        PublicationCatalogQuery(
            class_id=work.class_id,
            module_id=work.module_id,
            work_id=work.work_id,
            publication_kind="academic_result_set",
            state="current",
            limit=_GUIDED_CANDIDATE_LIMIT,
        )
    )
    discovery = discover_publication_candidates(workspace_root, request)
    matches = tuple(
        candidate
        for candidate in discovery.candidates
        if candidate.publication_id == publication_id
    )
    if len(matches) != 1:
        raise GuidedProjectionSelectionStaleError(
            "The selected evidence source is no longer a current catalog candidate."
        )
    candidate = matches[0]
    if candidate.catalog_publication.work != work:
        raise GuidedProjectionSelectionStaleError(
            "The selected evidence source no longer matches the selected work."
        )
    return candidate


def _prepare_invocation(
    workspace_root: Path,
    candidate: PublicationCandidate,
    diagnostics: DiagnosticsDependencies,
    purpose_id: str,
    student_ids: tuple[str, ...],
) -> PreparedPublicationInvocation:
    producer_registry, authorizer = _require_authorized_dependencies(diagnostics)
    return prepare_publication_invocation(
        workspace_root,
        candidate,
        producer_registry=producer_registry,  # type: ignore[arg-type]
        adapter_registry=diagnostics.adapter_registry,
        authorizer=authorizer,  # type: ignore[arg-type]
        authorization_purpose_id=purpose_id,
        requested_student_ids=student_ids,
        distribution_version_resolver=diagnostics.distribution_version_resolver,
    )


def _run_projection(
    prepared: PreparedPublicationInvocation,
    diagnostics: DiagnosticsDependencies,
) -> EvidenceInventory:
    return diagnostics.adapter_registry.invoke(
        prepared.projection_request,
        diagnostics.distribution_version_resolver,
    )


def _write_cache(
    workspace_root: Path,
    prepared: PreparedPublicationInvocation,
    inventory: EvidenceInventory,
    diagnostics: DiagnosticsDependencies,
) -> ProjectionCacheWriteResult:
    _, authorizer = _require_authorized_dependencies(diagnostics)
    return cache_projected_inventory(
        workspace_root,
        prepared,
        inventory,
        authorizer=authorizer,  # type: ignore[arg-type]
    )


def _load_cache(
    workspace_root: Path,
    publication_id: str,
    cache_key: str,
    diagnostics: DiagnosticsDependencies,
    purpose_id: str,
    student_ids: tuple[str, ...],
) -> AuthorizedProjectionSnapshot:
    producer_registry, authorizer = _require_authorized_dependencies(diagnostics)
    return load_authorized_projection_snapshot(
        workspace_root,
        publication_id,
        cache_key,
        authorizer=authorizer,  # type: ignore[arg-type]
        authorization_purpose_id=purpose_id,
        requested_student_ids=student_ids,
        producer_registry=producer_registry,  # type: ignore[arg-type]
        adapter_registry=diagnostics.adapter_registry,
        distribution_version_resolver=diagnostics.distribution_version_resolver,
    )


@dataclass(frozen=True, slots=True)
class GuidedProjectionServices:
    """Injectable orchestration seams over existing projection services."""

    candidate_resolver: CandidateResolver = _resolve_current_candidate
    invocation_preparer: InvocationPreparer = _prepare_invocation
    projection_runner: ProjectionRunner = _run_projection
    cache_writer: CacheWriter = _write_cache
    cache_loader: CacheLoader = _load_cache


@dataclass(frozen=True, slots=True)
class GuidedProjectionDependencies:
    """Existing diagnostic/deployment dependencies plus orchestration seams."""

    diagnostics: DiagnosticsDependencies
    services: GuidedProjectionServices = field(default_factory=GuidedProjectionServices)


@dataclass(frozen=True, slots=True)
class GuidedProjectionResult:
    """Authorized current evidence context with cache identity kept internal."""

    purpose_id: str
    requested_student_ids: tuple[str, ...]
    cache_disposition: ProjectionCacheDisposition
    authorized: AuthorizedProjectionSnapshot = field(repr=False)

    @property
    def evidence_count(self) -> int:
        return len(self.authorized.stored.snapshot.inventory.items)


def default_guided_projection_dependencies(
    *,
    diagnostics: DiagnosticsDependencies,
) -> GuidedProjectionDependencies:
    return GuidedProjectionDependencies(diagnostics=diagnostics)


def prepare_guided_evidence_projection(
    workspace_root: str | Path,
    work: ModuleWorkRef,
    publication_id: str,
    *,
    dependencies: GuidedProjectionDependencies,
) -> GuidedProjectionResult:
    """Prepare whole-assignment evidence without teacher-entered infrastructure IDs."""

    if not isinstance(work, ModuleWorkRef):
        raise GuidedProjectionPreparationError(
            "The selected work context is invalid."
        )
    if not isinstance(publication_id, str) or not publication_id:
        raise GuidedProjectionPreparationError(
            "The selected publication context is invalid."
        )

    diagnostics = dependencies.diagnostics
    services = dependencies.services
    purpose_id = GUIDED_EVIDENCE_REVIEW_PURPOSE_ID
    student_ids: tuple[str, ...] = ()

    _require_authorized_dependencies(diagnostics)

    try:
        root = Path(workspace_root)
        candidate = services.candidate_resolver(root, work, publication_id)
        prepared = services.invocation_preparer(
            root,
            candidate,
            diagnostics,
            purpose_id,
            student_ids,
        )
        inventory = services.projection_runner(prepared, diagnostics)
        cached = services.cache_writer(
            root,
            prepared,
            inventory,
            diagnostics,
        )
        authorized = services.cache_loader(
            root,
            publication_id,
            cached.stored.cache_key,
            diagnostics,
            purpose_id,
            student_ids,
        )
    except GuidedProjectionError:
        raise
    except PublicationAuthorizationDeniedError as error:
        raise GuidedProjectionAuthorizationDeniedError(
            "The deployment denied access to the selected evidence."
        ) from error
    except ProjectionCacheAuthorizationDeniedError as error:
        raise GuidedProjectionAuthorizationDeniedError(
            "The deployment denied access to the prepared evidence."
        ) from error
    except (
        PublicationIngestionError,
        AdapterError,
        ProjectionCacheError,
        ValueError,
    ) as error:
        raise GuidedProjectionPreparationError(
            "The selected evidence could not be prepared safely."
        ) from error

    current_publication = authorized.current_context.publication
    if (
        current_publication.publication_id != publication_id
        or current_publication.work != work
    ):
        raise GuidedProjectionCurrentUseBlockedError(
            "Prepared evidence no longer matches the selected work."
        )
    if not authorized.assessment.reusable_for_current_use:
        raise GuidedProjectionCurrentUseBlockedError(
            "Prepared evidence is not reusable for current review."
        )

    return GuidedProjectionResult(
        purpose_id=purpose_id,
        requested_student_ids=student_ids,
        cache_disposition=cached.disposition,
        authorized=authorized,
    )


__all__ = (
    "GUIDED_EVIDENCE_REVIEW_PURPOSE_ID",
    "GuidedProjectionAuthorizationDeniedError",
    "GuidedProjectionAuthorizationUnavailableError",
    "GuidedProjectionCurrentUseBlockedError",
    "GuidedProjectionDependencies",
    "GuidedProjectionError",
    "GuidedProjectionPreparationError",
    "GuidedProjectionResult",
    "GuidedProjectionSelectionStaleError",
    "GuidedProjectionServices",
    "GuidedProjectionSupportUnavailableError",
    "default_guided_projection_dependencies",
    "prepare_guided_evidence_projection",
)
