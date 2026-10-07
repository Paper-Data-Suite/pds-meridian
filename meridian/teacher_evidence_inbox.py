"""Read-only teacher evidence inbox projection for Issue #110."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import (
    DiagnosticsDependencies,
    PublicationListDiagnostic,
    PublicationObservationDiagnostic,
    list_publication_diagnostics,
)
from meridian.ingestion import CandidateDriftField, PublicationDiscoveryRequest

TeacherEvidenceActionability: TypeAlias = Literal["ready", "blocked"]
TeacherEvidenceStatusCode: TypeAlias = Literal[
    "ready_to_review",
    "refresh_needed",
    "publication_unavailable",
    "no_longer_current",
    "reader_unavailable",
    "reader_not_compatible",
    "not_supported",
    "compatibility_unavailable",
    "work_title_unavailable",
    "ambiguous_presentation",
]

_PRODUCER_LABELS = {
    "scoreform": "ScoreForm",
    "quillan": "Quillan",
    "concord": "Concord",
}

_STATUS_LABELS: dict[TeacherEvidenceStatusCode, str] = {
    "ready_to_review": "Ready to review",
    "refresh_needed": "Refresh needed",
    "publication_unavailable": "Publication unavailable",
    "no_longer_current": "No longer current",
    "reader_unavailable": "Reader unavailable",
    "reader_not_compatible": "Reader not compatible",
    "not_supported": "Not supported",
    "compatibility_unavailable": "Compatibility unavailable",
    "work_title_unavailable": "Assignment name unavailable",
    "ambiguous_presentation": "Needs a clearer display label",
}

_UNKNOWN_WORK_TITLE = "Assignment name unavailable"
_UNKNOWN_PRODUCER_LABEL = "Other producer"


class TeacherEvidenceInboxError(RuntimeError):
    """Base failure for the read-only teacher evidence inbox projection."""


class TeacherEvidenceInboxValidationError(TeacherEvidenceInboxError, ValueError):
    """Raised when inbox inputs or projected presentation are invalid."""


def _display_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TeacherEvidenceInboxValidationError(f"{field_name} must be a string.")
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        raise TeacherEvidenceInboxValidationError(
            f"{field_name} must be non-empty single-line text."
        )
    return value


@dataclass(frozen=True, slots=True)
class TeacherEvidenceInboxItem:
    """Teacher-facing publication candidate plus hidden exact identity."""

    publication_id: str
    work: ModuleWorkRef
    school_year: str | None
    class_label: str
    work_title: str
    producer_label: str
    actionability: TeacherEvidenceActionability
    status_code: TeacherEvidenceStatusCode
    canonical_state: str | None
    canonical_error_code: str | None
    drift_fields: tuple[CandidateDriftField, ...]
    support_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _display_text(self.publication_id, "publication_id")
        if not isinstance(self.work, ModuleWorkRef):
            raise TeacherEvidenceInboxValidationError("work must be a ModuleWorkRef.")
        _display_text(self.class_label, "class_label")
        _display_text(self.work_title, "work_title")
        _display_text(self.producer_label, "producer_label")
        if self.actionability not in {"ready", "blocked"}:
            raise TeacherEvidenceInboxValidationError("actionability is invalid.")
        if self.status_code not in _STATUS_LABELS:
            raise TeacherEvidenceInboxValidationError("status_code is invalid.")
        if self.actionability == "ready" and self.status_code != "ready_to_review":
            raise TeacherEvidenceInboxValidationError(
                "ready items must use ready_to_review status."
            )
        if self.actionability == "blocked" and self.status_code == "ready_to_review":
            raise TeacherEvidenceInboxValidationError(
                "blocked items cannot use ready_to_review status."
            )

    @property
    def status_label(self) -> str:
        """Return bounded teacher-facing status text."""
        return _STATUS_LABELS[self.status_code]


@dataclass(frozen=True, slots=True)
class TeacherEvidenceClassGroup:
    """One exact class scope rendered with its teacher-created class ID."""

    class_id: str
    school_year: str | None
    class_label: str
    items: tuple[TeacherEvidenceInboxItem, ...]

    def __post_init__(self) -> None:
        _display_text(self.class_id, "class_id")
        _display_text(self.class_label, "class_label")
        if not self.items:
            raise TeacherEvidenceInboxValidationError(
                "class group must contain at least one inbox item."
            )
        if any(item.work.class_id != self.class_id for item in self.items):
            raise TeacherEvidenceInboxValidationError(
                "class group items must share exact class identity."
            )
        if any(item.school_year != self.school_year for item in self.items):
            raise TeacherEvidenceInboxValidationError(
                "class group items must share school-year context."
            )
        if any(item.class_label != self.class_label for item in self.items):
            raise TeacherEvidenceInboxValidationError(
                "class group items must share one presentation label."
            )


@dataclass(frozen=True, slots=True)
class TeacherEvidenceInbox:
    """Deterministic class-grouped read model; never a persistent queue."""

    groups: tuple[TeacherEvidenceClassGroup, ...]

    @property
    def items(self) -> tuple[TeacherEvidenceInboxItem, ...]:
        return tuple(item for group in self.groups for item in group.items)

    @property
    def ready_count(self) -> int:
        return sum(item.actionability == "ready" for item in self.items)

    @property
    def blocked_count(self) -> int:
        return sum(item.actionability == "blocked" for item in self.items)


def teacher_evidence_discovery_request(
    *,
    school_year: str | None = None,
    class_id: str | None = None,
    limit: int = 100,
) -> PublicationDiscoveryRequest:
    """Build the bounded current academic-results query used by the inbox."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise TeacherEvidenceInboxValidationError("limit must be a positive integer.")
    return PublicationDiscoveryRequest(
        PublicationCatalogQuery(
            school_year=school_year,
            class_id=class_id,
            publication_kind="academic_result_set",
            state="current",
            limit=limit,
        )
    )


def load_teacher_evidence_inbox(
    workspace_root: str | Path,
    dependencies: DiagnosticsDependencies,
    *,
    school_year: str | None = None,
    class_id: str | None = None,
    limit: int = 100,
) -> TeacherEvidenceInbox:
    """Discover current publications and project a teacher-facing read model."""
    diagnostic = list_publication_diagnostics(
        workspace_root,
        teacher_evidence_discovery_request(
            school_year=school_year,
            class_id=class_id,
            limit=limit,
        ),
        dependencies,
    )
    return project_teacher_evidence_inbox(diagnostic)


def project_teacher_evidence_inbox(
    diagnostic: PublicationListDiagnostic,
) -> TeacherEvidenceInbox:
    """Project diagnostics without opening manifests or writing inbox state."""
    if not isinstance(diagnostic, PublicationListDiagnostic):
        raise TeacherEvidenceInboxValidationError(
            "diagnostic must be a PublicationListDiagnostic."
        )

    projected = [
        _project_observation(
            observation,
            school_year=observation.candidate.catalog_publication.school_year,
        )
        for observation in diagnostic.observations
    ]
    projected = _block_ambiguous_presentations(projected)
    return _group_items(tuple(projected))


def _producer_label(module_id: str) -> str:
    return _PRODUCER_LABELS.get(module_id, _UNKNOWN_PRODUCER_LABEL)


def _work_title(observation: PublicationObservationDiagnostic) -> str | None:
    context = observation.canonical_context
    if context is None or context.referenced_registration is None:
        return None
    try:
        return _display_text(context.referenced_registration.title, "work_title")
    except TeacherEvidenceInboxValidationError:
        return None


def _project_observation(
    observation: PublicationObservationDiagnostic,
    *,
    school_year: str | None,
) -> TeacherEvidenceInboxItem:
    context = observation.canonical_context
    work = (
        context.publication.work
        if context is not None
        else observation.candidate.catalog_publication.work
    )
    title = _work_title(observation)
    status = _status_code(observation, work_title=title)

    return TeacherEvidenceInboxItem(
        publication_id=observation.publication_id,
        work=work,
        school_year=school_year,
        class_label=work.class_id,
        work_title=title or _UNKNOWN_WORK_TITLE,
        producer_label=_producer_label(work.module_id),
        actionability="ready" if status == "ready_to_review" else "blocked",
        status_code=status,
        canonical_state=(context.canonical_state if context is not None else None),
        canonical_error_code=observation.canonical_error_code,
        drift_fields=observation.drift_fields,
        support_reason_codes=(
            observation.support.reason_codes
            if observation.support is not None
            else ()
        ),
    )


def _status_code(
    observation: PublicationObservationDiagnostic,
    *,
    work_title: str | None,
) -> TeacherEvidenceStatusCode:
    context = observation.canonical_context
    if context is None:
        return "publication_unavailable"
    if observation.canonical_error_code == "ingestion.candidate_drift":
        return "refresh_needed"
    if context.canonical_state != "current_selectable":
        return "no_longer_current"
    if work_title is None:
        return "work_title_unavailable"

    support = observation.support
    if support is None:
        return "compatibility_unavailable"
    if support.reader_state == "unavailable":
        return "reader_unavailable"
    if support.reader_state == "version_unsupported":
        return "reader_not_compatible"
    if support.overall_state == "support_unsupported":
        return "not_supported"
    if support.overall_state in {"support_unavailable", "support_unverifiable"}:
        return "compatibility_unavailable"
    if support.overall_state != "support_ready":
        return "compatibility_unavailable"
    return "ready_to_review"


def _block_ambiguous_presentations(
    items: list[TeacherEvidenceInboxItem],
) -> list[TeacherEvidenceInboxItem]:
    indexes: dict[tuple[str | None, str, str, str], list[int]] = {}
    for index, item in enumerate(items):
        if item.actionability != "ready":
            continue
        key = (
            item.school_year,
            item.class_label,
            item.work_title,
            item.producer_label,
        )
        indexes.setdefault(key, []).append(index)

    ambiguous = {
        index
        for matching in indexes.values()
        if len(matching) > 1
        for index in matching
    }
    return [
        (
            replace(
                item,
                actionability="blocked",
                status_code="ambiguous_presentation",
            )
            if index in ambiguous
            else item
        )
        for index, item in enumerate(items)
    ]


def _group_items(
    items: tuple[TeacherEvidenceInboxItem, ...],
) -> TeacherEvidenceInbox:
    order: list[tuple[str | None, str]] = []
    groups: dict[tuple[str | None, str], list[TeacherEvidenceInboxItem]] = {}

    for item in items:
        key = (item.school_year, item.work.class_id)
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(item)

    return TeacherEvidenceInbox(
        groups=tuple(
            TeacherEvidenceClassGroup(
                class_id=class_id,
                school_year=school_year,
                class_label=class_id,
                items=tuple(groups[(school_year, class_id)]),
            )
            for school_year, class_id in order
        )
    )


__all__ = (
    "TeacherEvidenceActionability",
    "TeacherEvidenceClassGroup",
    "TeacherEvidenceInbox",
    "TeacherEvidenceInboxError",
    "TeacherEvidenceInboxItem",
    "TeacherEvidenceInboxValidationError",
    "TeacherEvidenceStatusCode",
    "load_teacher_evidence_inbox",
    "project_teacher_evidence_inbox",
    "teacher_evidence_discovery_request",
)
