"""Read-only publication support diagnostics for Meridian."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pds_core.publication_compatibility import (
    PublicationCompatibilityError,
    PublicationProducerDiscoveryError,
    PublicationProducerProfileError,
    PublicationProducerRegistry,
    PublicationProducerRegistryError,
    discover_publication_producer_profiles,
    evaluate_publication_compatibility,
)
from pds_core.routing_models import ModuleRecordRef

from meridian.adapters import (
    AdapterCapabilityUnsupportedError,
    AdapterKey,
    AdapterNotFoundError,
    AdapterRegistry,
    AdapterRegistryError,
    AdapterValidationError,
    DistributionVersionResolver,
    ProducerReaderUnavailableError,
    ProducerReaderVersionUnsupportedError,
    adapter_key_from_core,
    installed_distribution_version,
    resolve_producer_reader_version,
)
from meridian.evidence import (
    EligibilityStatus,
    EvidenceItem,
    NativePointValue,
    NativeScalar,
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.ingestion import (
    CandidateDriftField,
    CanonicalPublicationContext,
    PublicationAuthorizer,
    PublicationCandidate,
    PublicationDiscoveryRequest,
    PublicationIngestionError,
    compare_candidate_to_canonical,
    discover_publication_candidates,
    load_canonical_publication_context,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheAssessment,
    load_authorized_projection_snapshot,
)

__all__ = [
    "DIAGNOSTIC_OUTPUT_VERSION",
    "AdapterDiagnosticState",
    "CompatibilityDiagnosticState",
    "DiagnosticsDependencies",
    "DiagnosticsDependencyState",
    "DiagnosticsError",
    "ProducerProfileDiagnosticState",
    "PublicationListDiagnostic",
    "PublicationObservationDiagnostic",
    "PublicationSupportDiagnostic",
    "PublicationVerificationDiagnostic",
    "EvidenceFilters",
    "EvidenceInspectionDiagnostic",
    "EvidenceExplanationDiagnostic",
    "DiagnosticsAuthorizationProviderRequiredError",
    "DiagnosticsProducerRegistryUnavailableError",
    "ReaderDiagnosticState",
    "SupportDiagnosticState",
    "build_builtin_adapter_registry",
    "default_diagnostics_dependencies",
    "diagnose_publication_support",
    "list_publication_diagnostics",
    "publication_list_to_dict",
    "publication_verification_to_dict",
    "evidence_inspection_to_dict",
    "evidence_explanation_to_dict",
    "inspect_evidence_diagnostic",
    "explain_evidence_diagnostic",
    "verify_publication_diagnostic",
]

DIAGNOSTIC_OUTPUT_VERSION: Final[str] = "1"

DiagnosticsDependencyState = Literal[
    "available", "discovery_failed", "registry_invalid"
]
ProducerProfileDiagnosticState = Literal[
    "available", "missing", "discovery_failed", "registry_invalid", "evaluation_failed"
]
CompatibilityDiagnosticState = Literal["compatible", "incompatible", "not_evaluated"]
AdapterDiagnosticState = Literal[
    "supported", "missing", "capability_unsupported", "invalid", "not_evaluated"
]
ReaderDiagnosticState = Literal[
    "ready", "unavailable", "version_unsupported", "not_evaluated"
]
SupportDiagnosticState = Literal[
    "support_ready",
    "support_unavailable",
    "support_unsupported",
    "support_unverifiable",
]

_DEPENDENCY_STATES = frozenset({"available", "discovery_failed", "registry_invalid"})
_PROFILE_STATES = frozenset(
    {
        "available",
        "missing",
        "discovery_failed",
        "registry_invalid",
        "evaluation_failed",
    }
)
_COMPATIBILITY_STATES = frozenset({"compatible", "incompatible", "not_evaluated"})
_ADAPTER_STATES = frozenset(
    {"supported", "missing", "capability_unsupported", "invalid", "not_evaluated"}
)
_READER_STATES = frozenset(
    {"ready", "unavailable", "version_unsupported", "not_evaluated"}
)
_SUPPORT_STATES = frozenset(
    {
        "support_ready",
        "support_unavailable",
        "support_unsupported",
        "support_unverifiable",
    }
)


class DiagnosticsError(RuntimeError):
    """Base failure for read-only diagnostic orchestration."""

    code: str = "diagnostics.error"


class DiagnosticsDependencyError(DiagnosticsError):
    """Raised when explicit Meridian diagnostic dependencies are invalid."""

    code = "diagnostics.dependencies_invalid"


class DiagnosticsAuthorizationProviderRequiredError(DiagnosticsError):
    """Raised before cache access when no deployment authorizer is configured."""

    code = "diagnostics.authorization_provider_required"


class DiagnosticsProducerRegistryUnavailableError(DiagnosticsError):
    """Raised when cache assessment cannot use a valid producer registry."""

    code = "diagnostics.producer_registry_unavailable"

    def __init__(self, reason_code: str) -> None:
        super().__init__("Producer compatibility metadata is unavailable.")
        self.reason_code = reason_code


def _filter_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise DiagnosticsDependencyError(
                f"{field_name} values must be nonempty strings."
            )
        normalized.append(value)
    return tuple(sorted(set(normalized)))


@dataclass(frozen=True, slots=True)
class EvidenceFilters:
    """Exact read-only evidence filters; dimensions combine with logical AND."""

    item_ids: tuple[str, ...] = ()
    student_ids: tuple[str, ...] = ()
    target_kinds: tuple[str, ...] = ()
    standard_ids: tuple[str, ...] = ()
    result_kinds: tuple[str, ...] = ()
    eligibility_statuses: tuple[EligibilityStatus, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_ids", _filter_strings(self.item_ids, "item_id"))
        object.__setattr__(
            self, "student_ids", _filter_strings(self.student_ids, "student_id")
        )
        object.__setattr__(
            self, "target_kinds", _filter_strings(self.target_kinds, "target_kind")
        )
        object.__setattr__(
            self, "standard_ids", _filter_strings(self.standard_ids, "standard_id")
        )
        object.__setattr__(
            self, "result_kinds", _filter_strings(self.result_kinds, "result_kind")
        )
        statuses = tuple(sorted(set(self.eligibility_statuses)))
        if any(
            status not in {"unevaluated", "eligible", "ineligible"}
            for status in statuses
        ):
            raise DiagnosticsDependencyError("eligibility_status is invalid.")
        object.__setattr__(self, "eligibility_statuses", statuses)


@dataclass(frozen=True, slots=True)
class EvidenceInspectionDiagnostic:
    """Authorized persisted evidence plus an order-preserving exact filter view."""

    authorized: AuthorizedProjectionSnapshot
    items: tuple[EvidenceItem, ...]


@dataclass(frozen=True, slots=True)
class EvidenceExplanationDiagnostic:
    """Authorized current-use assessment and existing item eligibility states."""

    authorized: AuthorizedProjectionSnapshot


def _evidence_dependencies(
    dependencies: DiagnosticsDependencies,
) -> tuple[PublicationProducerRegistry, PublicationAuthorizer]:
    if not isinstance(dependencies, DiagnosticsDependencies):
        raise DiagnosticsDependencyError("dependencies are invalid.")
    if dependencies.authorizer is None:
        raise DiagnosticsAuthorizationProviderRequiredError(
            "Evidence diagnostics require a deployment-provided authorizer."
        )
    if dependencies.producer_registry_state != "available":
        reason = dependencies.producer_registry_reason_code
        if reason is None:
            reason = "diagnostics.profile_discovery_failed"
        raise DiagnosticsProducerRegistryUnavailableError(reason)
    registry = dependencies.producer_registry
    if registry is None:
        raise DiagnosticsProducerRegistryUnavailableError(
            "ingestion.profile_registry_invalid"
        )
    return registry, dependencies.authorizer


def _load_authorized_evidence(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
    *,
    authorization_purpose_id: str,
    requested_student_ids: tuple[str, ...],
    dependencies: DiagnosticsDependencies,
) -> AuthorizedProjectionSnapshot:
    registry, authorizer = _evidence_dependencies(dependencies)
    return load_authorized_projection_snapshot(
        workspace_root,
        publication_id,
        cache_key,
        authorizer=authorizer,
        authorization_purpose_id=authorization_purpose_id,
        requested_student_ids=requested_student_ids,
        producer_registry=registry,
        adapter_registry=dependencies.adapter_registry,
        distribution_version_resolver=dependencies.distribution_version_resolver,
    )


def _matches_filters(item: EvidenceItem, filters: EvidenceFilters) -> bool:
    if filters.item_ids and item.item_id not in filters.item_ids:
        return False
    if filters.student_ids and (
        item.subject is None
        or item.subject.student_id not in filters.student_ids
    ):
        return False
    if filters.target_kinds and item.target.target_kind not in filters.target_kinds:
        return False
    if filters.standard_ids and not set(filters.standard_ids).intersection(
        item.target.standard_ids
    ):
        return False
    if filters.result_kinds and item.result_kind not in filters.result_kinds:
        return False
    if (
        filters.eligibility_statuses
        and item.eligibility.status not in filters.eligibility_statuses
    ):
        return False
    return True


def inspect_evidence_diagnostic(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
    *,
    authorization_purpose_id: str,
    requested_student_ids: tuple[str, ...],
    filters: EvidenceFilters,
    dependencies: DiagnosticsDependencies,
) -> EvidenceInspectionDiagnostic:
    """Load one exact authorized snapshot and return a nonmutating filtered view."""
    if not isinstance(filters, EvidenceFilters):
        raise DiagnosticsDependencyError("filters must be EvidenceFilters.")
    authorized = _load_authorized_evidence(
        workspace_root,
        publication_id,
        cache_key,
        authorization_purpose_id=authorization_purpose_id,
        requested_student_ids=requested_student_ids,
        dependencies=dependencies,
    )
    items = tuple(
        item
        for item in authorized.stored.snapshot.inventory.items
        if _matches_filters(item, filters)
    )
    return EvidenceInspectionDiagnostic(authorized=authorized, items=items)


def explain_evidence_diagnostic(
    workspace_root: str | Path,
    publication_id: str,
    cache_key: str,
    *,
    authorization_purpose_id: str,
    requested_student_ids: tuple[str, ...],
    dependencies: DiagnosticsDependencies,
) -> EvidenceExplanationDiagnostic:
    """Explain current-use and existing eligibility without recalculating policy."""
    authorized = _load_authorized_evidence(
        workspace_root,
        publication_id,
        cache_key,
        authorization_purpose_id=authorization_purpose_id,
        requested_student_ids=requested_student_ids,
        dependencies=dependencies,
    )
    return EvidenceExplanationDiagnostic(authorized=authorized)


def _scalar_to_dict(value: NativeScalar) -> dict[str, object]:
    if type(value) is bool:
        kind = "boolean"
    elif type(value) is int:
        kind = "integer"
    elif type(value) is float:
        kind = "float"
    else:
        kind = "string"
    return {"type": kind, "value": value}


def _value_to_dict(item: EvidenceItem) -> dict[str, object]:
    value = item.value
    if isinstance(value, NativeScalarValue):
        return {"kind": "scalar", "value": _scalar_to_dict(value.value)}
    if isinstance(value, NativePointValue):
        return {
            "kind": "points",
            "earned": _scalar_to_dict(value.earned),
            "possible": _scalar_to_dict(value.possible),
        }
    if isinstance(value, NativeScaledValue):
        scale: dict[str, object] = {
            "scale_id": value.scale.scale_id,
            "contract_version": value.scale.contract_version,
            "order_is_meaningful": value.scale.order_is_meaningful,
            "levels": [
                {
                    "value": _scalar_to_dict(level.value),
                    "label": level.label,
                    "description": level.description,
                    **(
                        {
                            "meaning": level.meaning,
                            "position": level.position,
                        }
                        if level.meaning is not None or level.position is not None
                        else {}
                    ),
                }
                for level in value.scale.levels
            ],
        }
        if any(
            field is not None
            for field in (
                value.scale.lineage_id,
                value.scale.name,
                value.scale.revision,
                value.scale.scale_type,
                value.scale.status,
                value.scale.supersedes_scale_id,
            )
        ):
            scale.update(
                {
                    "lineage_id": value.scale.lineage_id,
                    "name": value.scale.name,
                    "revision": value.scale.revision,
                    "scale_type": value.scale.scale_type,
                    "status": value.scale.status,
                    "supersedes_scale_id": value.scale.supersedes_scale_id,
                }
            )
        return {
            "kind": "scaled",
            "value": _scalar_to_dict(value.value),
            "scale": scale,
        }
    if isinstance(value, NativeStateValue):
        return {
            "kind": "state",
            "code": value.code,
            "label": value.label,
            "description": value.description,
        }
    raise DiagnosticsDependencyError("evidence value variant is unsupported.")


def _eligibility_to_dict(item: EvidenceItem) -> dict[str, object]:
    eligibility = item.eligibility
    return {
        "status": eligibility.status,
        "policy_id": eligibility.policy_id,
        "policy_version": eligibility.policy_version,
        "reason_codes": list(eligibility.reason_codes),
    }


def _target_to_dict(item: EvidenceItem) -> dict[str, object]:
    target = item.target
    parent = target.parent_target
    if parent is None:
        parent_mapping: dict[str, object] | None = None
    else:
        parent_mapping = {
            "target_kind": parent.target_kind,
            "target_id": parent.target_id,
        }
        if parent.owning_system is not None or parent.contract_version is not None:
            parent_mapping["owning_system"] = parent.owning_system
            parent_mapping["contract_version"] = parent.contract_version

    result: dict[str, object] = {
        "target_kind": target.target_kind,
        "target_id": target.target_id,
        "parent_target": parent_mapping,
        "standard_ids": list(target.standard_ids),
        "sequence": target.sequence,
    }
    if target.owning_system is not None or target.contract_version is not None:
        result["owning_system"] = target.owning_system
        result["contract_version"] = target.contract_version
    return result


def _evidence_item_to_dict(item: EvidenceItem) -> dict[str, object]:
    return {
        "item_id": item.item_id,
        "student_id": (
            item.subject.student_id if item.subject is not None else None
        ),
        "target": _target_to_dict(item),
        "result_kind": item.result_kind,
        "value": _value_to_dict(item),
        "eligibility": _eligibility_to_dict(item),
    }


def _assessment_to_dict(value: ProjectionCacheAssessment) -> dict[str, object]:
    return {
        "source_status": value.source_status,
        "reuse_status": value.reuse_status,
        "reason_codes": list(value.reason_codes),
        "observed_canonical_state": value.observed_canonical_state,
        "current_canonical_state": value.current_canonical_state,
        "observed_head_publication_id": value.observed_head_publication_id,
        "current_head_publication_id": value.current_head_publication_id,
        "observed_current_registration_revision": (
            value.observed_current_registration_revision
        ),
        "current_registration_revision": value.current_registration_revision,
    }


def evidence_inspection_to_dict(
    value: EvidenceInspectionDiagnostic,
) -> dict[str, object]:
    snapshot = value.authorized.stored.snapshot
    return {
        "diagnostic_output_version": DIAGNOSTIC_OUTPUT_VERSION,
        "kind": "evidence_inspection",
        "publication_id": snapshot.source.publication.publication_id,
        "cache_key": snapshot.cache_key,
        "purpose_id": snapshot.authorization.purpose_id,
        "requested_student_ids": list(snapshot.authorization.requested_student_ids),
        "assessment": _assessment_to_dict(value.authorized.assessment),
        "items": [_evidence_item_to_dict(item) for item in value.items],
    }


def evidence_explanation_to_dict(
    value: EvidenceExplanationDiagnostic,
) -> dict[str, object]:
    snapshot = value.authorized.stored.snapshot
    items = snapshot.inventory.items
    return {
        "diagnostic_output_version": DIAGNOSTIC_OUTPUT_VERSION,
        "kind": "evidence_explanation",
        "publication_id": snapshot.source.publication.publication_id,
        "cache_key": snapshot.cache_key,
        "purpose_id": snapshot.authorization.purpose_id,
        "requested_student_ids": list(snapshot.authorization.requested_student_ids),
        "assessment": _assessment_to_dict(value.authorized.assessment),
        "eligibility": [
            {
                "item_id": item.item_id,
                **_eligibility_to_dict(item),
            }
            for item in items
        ],
    }


def _codes(values: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values)))


@dataclass(frozen=True, slots=True)
class DiagnosticsDependencies:
    """Explicit dependencies used by read-only diagnostics."""

    producer_registry: PublicationProducerRegistry | None
    adapter_registry: AdapterRegistry
    authorizer: PublicationAuthorizer | None = None
    distribution_version_resolver: DistributionVersionResolver = (
        installed_distribution_version
    )
    producer_registry_state: DiagnosticsDependencyState = "available"
    producer_registry_reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.producer_registry_state not in _DEPENDENCY_STATES:
            raise DiagnosticsDependencyError("producer_registry_state is invalid.")
        if not isinstance(self.adapter_registry, AdapterRegistry):
            raise DiagnosticsDependencyError(
                "adapter_registry must be an AdapterRegistry."
            )
        if self.producer_registry_state == "available":
            if not isinstance(self.producer_registry, PublicationProducerRegistry):
                raise DiagnosticsDependencyError(
                    "available producer registry state requires a registry."
                )
            if self.producer_registry_reason_code is not None:
                raise DiagnosticsDependencyError(
                    "available producer registry state must not have a reason code."
                )
        else:
            if self.producer_registry is not None:
                raise DiagnosticsDependencyError(
                    "failed producer registry state must not retain a registry."
                )
            if not self.producer_registry_reason_code:
                raise DiagnosticsDependencyError(
                    "failed producer registry state requires a reason code."
                )
        if not callable(self.distribution_version_resolver):
            raise DiagnosticsDependencyError(
                "distribution_version_resolver must be callable."
            )


@dataclass(frozen=True, slots=True)
class PublicationSupportDiagnostic:
    """Exact metadata-only support/readiness state for one canonical publication."""

    profile_state: ProducerProfileDiagnosticState
    compatibility_state: CompatibilityDiagnosticState
    compatibility_codes: tuple[str, ...]
    adapter_state: AdapterDiagnosticState
    adapter_key: AdapterKey | None
    adapter_id: str | None
    adapter_interface_version: str | None
    projection_contract_version: str | None
    adapter_supported_capabilities: tuple[str, ...]
    reader_state: ReaderDiagnosticState
    reader_distribution: str | None
    installed_reader_version: str | None
    supported_reader_versions: tuple[str, ...]
    overall_state: SupportDiagnosticState
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.profile_state not in _PROFILE_STATES:
            raise DiagnosticsDependencyError("profile_state is invalid.")
        if self.compatibility_state not in _COMPATIBILITY_STATES:
            raise DiagnosticsDependencyError("compatibility_state is invalid.")
        if self.adapter_state not in _ADAPTER_STATES:
            raise DiagnosticsDependencyError("adapter_state is invalid.")
        if self.reader_state not in _READER_STATES:
            raise DiagnosticsDependencyError("reader_state is invalid.")
        if self.overall_state not in _SUPPORT_STATES:
            raise DiagnosticsDependencyError("overall_state is invalid.")
        if self.compatibility_codes != _codes(self.compatibility_codes):
            raise DiagnosticsDependencyError(
                "compatibility_codes must be unique and deterministically ordered."
            )
        if self.reason_codes != _codes(self.reason_codes):
            raise DiagnosticsDependencyError(
                "reason_codes must be unique and deterministically ordered."
            )
        if self.adapter_supported_capabilities != tuple(
            sorted(set(self.adapter_supported_capabilities))
        ):
            raise DiagnosticsDependencyError(
                "adapter_supported_capabilities must be unique and ordered."
            )
        if self.supported_reader_versions != tuple(
            sorted(set(self.supported_reader_versions))
        ):
            raise DiagnosticsDependencyError(
                "supported_reader_versions must be unique and ordered."
            )


@dataclass(frozen=True, slots=True)
class PublicationObservationDiagnostic:
    """One catalog observation reconciled with canonical state when possible."""

    candidate: PublicationCandidate
    canonical_context: CanonicalPublicationContext | None
    canonical_error_code: str | None
    drift_fields: tuple[CandidateDriftField, ...]
    support: PublicationSupportDiagnostic | None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, PublicationCandidate):
            raise DiagnosticsDependencyError("candidate is invalid.")
        if self.canonical_context is None:
            if self.canonical_error_code is None:
                raise DiagnosticsDependencyError(
                    "missing canonical context requires an error code."
                )
            if self.drift_fields or self.support is not None:
                raise DiagnosticsDependencyError(
                    "unavailable canonical context cannot have drift/support details."
                )
        else:
            if (
                self.canonical_context.publication.publication_id
                != self.candidate.publication_id
            ):
                raise DiagnosticsDependencyError(
                    "candidate and canonical context identify different publications."
                )
            if self.canonical_error_code not in {None, "ingestion.candidate_drift"}:
                raise DiagnosticsDependencyError(
                    "canonical_error_code is invalid for an available context."
                )
            if bool(self.drift_fields) != (
                self.canonical_error_code == "ingestion.candidate_drift"
            ):
                raise DiagnosticsDependencyError(
                    "candidate drift fields and error code disagree."
                )
            if not isinstance(self.support, PublicationSupportDiagnostic):
                raise DiagnosticsDependencyError(
                    "available canonical context requires support diagnostics."
                )

    @property
    def publication_id(self) -> str:
        return self.candidate.publication_id


@dataclass(frozen=True, slots=True)
class PublicationListDiagnostic:
    request: PublicationDiscoveryRequest
    observations: tuple[PublicationObservationDiagnostic, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, PublicationDiscoveryRequest):
            raise DiagnosticsDependencyError("request is invalid.")
        observations = tuple(self.observations)
        if any(
            not isinstance(item, PublicationObservationDiagnostic)
            for item in observations
        ):
            raise DiagnosticsDependencyError("observations contain an invalid value.")
        expected = tuple(range(len(observations)))
        actual = tuple(item.candidate.ordinal for item in observations)
        if actual != expected:
            raise DiagnosticsDependencyError(
                "observations must preserve discovery result order."
            )
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True, slots=True)
class PublicationVerificationDiagnostic:
    context: CanonicalPublicationContext
    support: PublicationSupportDiagnostic

    def __post_init__(self) -> None:
        if not isinstance(self.context, CanonicalPublicationContext):
            raise DiagnosticsDependencyError("context is invalid.")
        if not isinstance(self.support, PublicationSupportDiagnostic):
            raise DiagnosticsDependencyError("support is invalid.")


def build_builtin_adapter_registry() -> AdapterRegistry:
    """Construct the explicit built-in adapter registry without reader imports."""
    from meridian.concord_adapter import ConcordAcademicResultAdapter
    from meridian.quillan_adapter import QuillanAcademicResultAdapter
    from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter

    return AdapterRegistry(
        (
            ScoreFormAcademicResultAdapter(),
            QuillanAcademicResultAdapter(),
            ConcordAcademicResultAdapter(),
        )
    )


def default_diagnostics_dependencies(
    *,
    authorizer: PublicationAuthorizer | None = None,
    distribution_version_resolver: DistributionVersionResolver = (
        installed_distribution_version
    ),
) -> DiagnosticsDependencies:
    """Discover Core producer profiles only for an actual data-command invocation."""
    try:
        adapter_registry = build_builtin_adapter_registry()
    except (AdapterRegistryError, AdapterValidationError) as error:
        raise DiagnosticsDependencyError(
            "built-in adapter registry is invalid."
        ) from error
    try:
        profiles = discover_publication_producer_profiles()
    except PublicationProducerDiscoveryError:
        return DiagnosticsDependencies(
            producer_registry=None,
            adapter_registry=adapter_registry,
            authorizer=authorizer,
            distribution_version_resolver=distribution_version_resolver,
            producer_registry_state="discovery_failed",
            producer_registry_reason_code="diagnostics.profile_discovery_failed",
        )
    except (PublicationProducerRegistryError, PublicationCompatibilityError):
        return DiagnosticsDependencies(
            producer_registry=None,
            adapter_registry=adapter_registry,
            authorizer=authorizer,
            distribution_version_resolver=distribution_version_resolver,
            producer_registry_state="registry_invalid",
            producer_registry_reason_code="ingestion.profile_registry_invalid",
        )
    try:
        registry = PublicationProducerRegistry(profiles)
    except (PublicationProducerRegistryError, PublicationCompatibilityError):
        return DiagnosticsDependencies(
            producer_registry=None,
            adapter_registry=adapter_registry,
            authorizer=authorizer,
            distribution_version_resolver=distribution_version_resolver,
            producer_registry_state="registry_invalid",
            producer_registry_reason_code="ingestion.profile_registry_invalid",
        )
    return DiagnosticsDependencies(
        producer_registry=registry,
        adapter_registry=adapter_registry,
        authorizer=authorizer,
        distribution_version_resolver=distribution_version_resolver,
    )


def diagnose_publication_support(
    context: CanonicalPublicationContext,
    dependencies: DiagnosticsDependencies,
) -> PublicationSupportDiagnostic:
    """Evaluate metadata compatibility, exact adapter support, and reader readiness."""
    if not isinstance(context, CanonicalPublicationContext):
        raise DiagnosticsDependencyError(
            "context must be canonical publication context."
        )
    if not isinstance(dependencies, DiagnosticsDependencies):
        raise DiagnosticsDependencyError("dependencies are invalid.")

    reasons: set[str] = set()
    compatibility_codes: tuple[str, ...] = ()

    profile_state: ProducerProfileDiagnosticState
    compatibility_state: CompatibilityDiagnosticState = "not_evaluated"
    if dependencies.producer_registry_state == "discovery_failed":
        profile_state = "discovery_failed"
        if dependencies.producer_registry_reason_code:
            reasons.add(dependencies.producer_registry_reason_code)
    elif dependencies.producer_registry_state == "registry_invalid":
        profile_state = "registry_invalid"
        if dependencies.producer_registry_reason_code:
            reasons.add(dependencies.producer_registry_reason_code)
    else:
        registry = dependencies.producer_registry
        if registry is None:  # defensive: validated above
            raise DiagnosticsDependencyError("producer registry unexpectedly missing.")
        try:
            profile = registry.get(context.publication.work.module_id)
        except (PublicationProducerRegistryError, PublicationCompatibilityError):
            profile = None
            profile_state = "evaluation_failed"
            reasons.add("ingestion.profile_evaluation_failed")
        else:
            if profile is None:
                profile_state = "missing"
                reasons.add("ingestion.profile_missing")
            else:
                profile_state = "available"
                try:
                    compatibility = evaluate_publication_compatibility(
                        context.publication,
                        profile,
                        context.referenced_registration,
                    )
                except (PublicationProducerProfileError, PublicationCompatibilityError):
                    profile_state = "evaluation_failed"
                    reasons.add("ingestion.profile_evaluation_failed")
                else:
                    compatibility_codes = tuple(compatibility.codes)
                    if compatibility.compatible:
                        compatibility_state = "compatible"
                    else:
                        compatibility_state = "incompatible"
                        reasons.add("ingestion.profile_incompatible")
                        reasons.update(compatibility_codes)

    adapter_state: AdapterDiagnosticState
    adapter_key: AdapterKey | None = None
    adapter_id: str | None = None
    adapter_interface_version: str | None = None
    projection_contract_version: str | None = None
    adapter_supported_capabilities: tuple[str, ...] = ()
    reader_state: ReaderDiagnosticState = "not_evaluated"
    reader_distribution: str | None = None
    installed_reader_version: str | None = None
    supported_reader_versions: tuple[str, ...] = ()

    try:
        adapter_key = adapter_key_from_core(
            context.publication, context.referenced_registration
        )
        match = dependencies.adapter_registry.select(
            context.publication, context.referenced_registration
        )
    except AdapterNotFoundError:
        adapter_state = "missing"
        reasons.add("adapters.not_found")
        match = None
    except AdapterCapabilityUnsupportedError:
        adapter_state = "capability_unsupported"
        reasons.add("adapters.capability_unsupported")
        match = None
    except (AdapterRegistryError, AdapterValidationError):
        adapter_state = "invalid"
        reasons.add("adapters.registry_invalid")
        match = None
    else:
        adapter_state = "supported"
        assert match is not None
        descriptor = match.descriptor
        adapter_id = descriptor.adapter_id
        adapter_interface_version = descriptor.adapter_interface_version
        projection_contract_version = descriptor.projection_contract_version
        adapter_supported_capabilities = tuple(
            sorted(descriptor.supported_capabilities)
        )
        reader_distribution = descriptor.producer_reader_distribution
        supported_reader_versions = tuple(
            sorted(descriptor.supported_producer_reader_versions)
        )
        try:
            installed_reader_version = resolve_producer_reader_version(
                descriptor, dependencies.distribution_version_resolver
            )
        except ProducerReaderUnavailableError:
            reader_state = "unavailable"
            reasons.add("adapters.reader_unavailable")
        except ProducerReaderVersionUnsupportedError as error:
            reader_state = "version_unsupported"
            installed_reader_version = error.installed_version
            reasons.add("adapters.reader_version_unsupported")
        except (AdapterValidationError, AdapterRegistryError):
            reader_state = "not_evaluated"
            reasons.add("adapters.registry_invalid")
        except Exception:
            reader_state = "not_evaluated"
            reasons.add("diagnostics.reader_resolution_failed")
        else:
            reader_state = "ready"

    if profile_state in {"discovery_failed", "registry_invalid", "evaluation_failed"}:
        overall_state: SupportDiagnosticState = "support_unverifiable"
    elif compatibility_state == "incompatible" or profile_state == "missing":
        overall_state = "support_unsupported"
    elif adapter_state in {"missing", "capability_unsupported"}:
        overall_state = "support_unsupported"
    elif adapter_state in {"invalid", "not_evaluated"}:
        overall_state = "support_unverifiable"
    elif reader_state == "unavailable":
        overall_state = "support_unavailable"
    elif reader_state == "version_unsupported":
        overall_state = "support_unsupported"
    elif reader_state != "ready" or compatibility_state != "compatible":
        overall_state = "support_unverifiable"
    else:
        overall_state = "support_ready"

    return PublicationSupportDiagnostic(
        profile_state=profile_state,
        compatibility_state=compatibility_state,
        compatibility_codes=_codes(compatibility_codes),
        adapter_state=adapter_state,
        adapter_key=adapter_key,
        adapter_id=adapter_id,
        adapter_interface_version=adapter_interface_version,
        projection_contract_version=projection_contract_version,
        adapter_supported_capabilities=adapter_supported_capabilities,
        reader_state=reader_state,
        reader_distribution=reader_distribution,
        installed_reader_version=installed_reader_version,
        supported_reader_versions=supported_reader_versions,
        overall_state=overall_state,
        reason_codes=_codes(reasons),
    )


def list_publication_diagnostics(
    workspace_root: str | Path,
    request: PublicationDiscoveryRequest,
    dependencies: DiagnosticsDependencies,
) -> PublicationListDiagnostic:
    """List bounded candidates and reconcile each against canonical Core state."""
    discovery = discover_publication_candidates(workspace_root, request)
    observations: list[PublicationObservationDiagnostic] = []
    for candidate in discovery.candidates:
        try:
            context = load_canonical_publication_context(
                workspace_root, candidate.publication_id
            )
        except PublicationIngestionError as error:
            observations.append(
                PublicationObservationDiagnostic(
                    candidate=candidate,
                    canonical_context=None,
                    canonical_error_code=error.code,
                    drift_fields=(),
                    support=None,
                )
            )
            continue
        drift = compare_candidate_to_canonical(candidate, context)
        observations.append(
            PublicationObservationDiagnostic(
                candidate=candidate,
                canonical_context=context,
                canonical_error_code=("ingestion.candidate_drift" if drift else None),
                drift_fields=drift,
                support=diagnose_publication_support(context, dependencies),
            )
        )
    return PublicationListDiagnostic(request=request, observations=tuple(observations))


def verify_publication_diagnostic(
    workspace_root: str | Path,
    publication_id: str,
    dependencies: DiagnosticsDependencies,
) -> PublicationVerificationDiagnostic:
    """Diagnose one exact canonical publication without consulting the catalog."""
    context = load_canonical_publication_context(workspace_root, publication_id)
    return PublicationVerificationDiagnostic(
        context=context,
        support=diagnose_publication_support(context, dependencies),
    )


def _adapter_key_to_dict(key: AdapterKey | None) -> dict[str, object] | None:
    if key is None:
        return None
    return {
        "producer_module_id": key.producer_module_id,
        "publication_kind": key.publication_kind,
        "manifest_contract_version": key.manifest_contract_version,
        "producer_contract_version": key.producer_contract_version,
        "source_record_kind": key.source_record_kind,
        "source_record_contract_version": key.source_record_contract_version,
    }


def _support_to_dict(value: PublicationSupportDiagnostic) -> dict[str, object]:
    return {
        "overall_state": value.overall_state,
        "reason_codes": list(value.reason_codes),
        "producer_profile": {
            "state": value.profile_state,
            "compatibility_state": value.compatibility_state,
            "compatibility_codes": list(value.compatibility_codes),
        },
        "adapter": {
            "state": value.adapter_state,
            "key": _adapter_key_to_dict(value.adapter_key),
            "adapter_id": value.adapter_id,
            "adapter_interface_version": value.adapter_interface_version,
            "projection_contract_version": value.projection_contract_version,
            "supported_capabilities": list(value.adapter_supported_capabilities),
        },
        "reader": {
            "state": value.reader_state,
            "distribution": value.reader_distribution,
            "installed_version": value.installed_reader_version,
            "supported_versions": list(value.supported_reader_versions),
        },
    }


def _source_record_to_dict(
    value: ModuleRecordRef | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "module_id": value.module_id,
        "record_kind": value.record_kind,
        "record_id": value.record_id,
        "contract_version": value.contract_version,
    }


def _context_to_dict(context: CanonicalPublicationContext) -> dict[str, object]:
    publication = context.publication
    referenced = context.referenced_registration
    current = context.current_registration
    return {
        "publication_id": publication.publication_id,
        "work": {
            "module_id": publication.work.module_id,
            "class_id": publication.work.class_id,
            "work_id": publication.work.work_id,
        },
        "source_record": _source_record_to_dict(publication.source_record),
        "publication_kind": publication.publication_kind,
        "capabilities": list(publication.capabilities),
        "record_set": {
            "record_set_id": publication.record_set_id,
            "revision": publication.record_set_revision,
        },
        "manifest": {
            "contract_version": publication.manifest_contract_version,
            "digest_algorithm": publication.manifest_digest_algorithm,
            "digest": publication.manifest_digest,
            "access": "not_requested",
            "bytes_checked": False,
        },
        "referenced_registration_revision": (
            referenced.registration_revision if referenced is not None else None
        ),
        "current_registration_revision": (
            current.registration_revision if current is not None else None
        ),
        "series": {
            "target_index": context.series.target_index,
            "member_count": len(context.series.members),
            "head_publication_id": context.series.head_publication_id,
            "successor_publication_id": context.series.successor_publication_id,
        },
        "withdrawn": context.withdrawal is not None,
        "canonical_state": context.canonical_state,
    }


def _catalog_summary(candidate: PublicationCandidate) -> dict[str, object]:
    row = candidate.catalog_publication
    return {
        "ordinal": candidate.ordinal,
        "publication_id": candidate.publication_id,
        "producer_module_id": row.work.module_id,
        "class_id": row.work.class_id,
        "work_id": row.work.work_id,
        "publication_kind": row.publication_kind,
        "record_set_id": row.record_set_id,
        "record_set_revision": row.record_set_revision,
        "manifest_contract_version": row.manifest_contract_version,
    }


def publication_list_to_dict(value: PublicationListDiagnostic) -> dict[str, object]:
    return {
        "diagnostic_output_version": DIAGNOSTIC_OUTPUT_VERSION,
        "kind": "publication_list",
        "observations": [
            {
                "catalog": _catalog_summary(item.candidate),
                "canonical": (
                    _context_to_dict(item.canonical_context)
                    if item.canonical_context is not None
                    else None
                ),
                "canonical_error_code": item.canonical_error_code,
                "drift_fields": list(item.drift_fields),
                "support": (
                    _support_to_dict(item.support) if item.support is not None else None
                ),
            }
            for item in value.observations
        ],
    }


def publication_verification_to_dict(
    value: PublicationVerificationDiagnostic,
) -> dict[str, object]:
    return {
        "diagnostic_output_version": DIAGNOSTIC_OUTPUT_VERSION,
        "kind": "publication_verification",
        "canonical": _context_to_dict(value.context),
        "support": _support_to_dict(value.support),
    }
