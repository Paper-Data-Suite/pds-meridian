"""Teacher standards-association authoring for Standards Review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_evidence import (
    STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
    STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
    StandardEvidenceActor,
    StandardEvidenceAssociationDecision,
    StandardsEvidenceValidationError,
)
from meridian.standards_evidence_storage import (
    StandardEvidenceAssociationRevisionWriteResult,
    StandardsEvidenceDependencyError,
    StandardsEvidenceStorageConflictError,
    get_current_standard_evidence_association_revision,
    list_standard_evidence_association_revisions,
    load_standard_evidence_association_revision,
    validate_standard_evidence_association_dependencies,
    write_standard_evidence_association_revision,
)
from meridian.standards_review_workflow import StandardsReviewProjection

StandardsAssociationAuthoringOperation: TypeAlias = Literal["create", "revise"]
StandardsAssociationDisposition: TypeAlias = Literal[
    "associated",
    "not_associated",
]
StandardsAssociationBasis: TypeAlias = Literal[
    "producer_declared",
    "explicit",
]


class StandardsAssociationAuthoringError(RuntimeError):
    """Base workflow failure for standards-association authoring."""

    code = "teacher_workflow.standards_review.association_authoring_error"


class StandardsAssociationAuthoringScopeError(
    StandardsAssociationAuthoringError, ValueError
):
    """Raised for an invalid teacher association-authoring request."""

    code = "teacher_workflow.standards_review.association_authoring_invalid"


class StandardsAssociationAuthoringStaleError(
    StandardsAssociationAuthoringError
):
    """Raised when reviewed #27/#28/#33 state changed before write."""

    code = "teacher_workflow.standards_review.association_authoring_stale"


@dataclass(frozen=True, slots=True)
class StandardsAssociationAuthoringPreview:
    """Exact immutable candidate plus its reviewed CAS/dependency basis."""

    projection: StandardsReviewProjection
    operation: StandardsAssociationAuthoringOperation
    candidate: StandardEvidenceAssociationDecision
    history: tuple[int, ...]
    latest_revision_sha256: str | None
    expected_current_association_revision: int | None
    grade_item_revision: int
    grade_item_revision_sha256: str
    membership_revision: int
    membership_revision_sha256: str
    standard_resolved: bool
    standard_active: bool | None

    @property
    def candidate_revision(self) -> int:
        return self.candidate.association_revision

    @property
    def candidate_disposition(self) -> str:
        return self.candidate.disposition

    @property
    def candidate_basis(self) -> str:
        return self.candidate.basis

    @property
    def selection_action(self) -> str:
        return "not_performed"


@dataclass(frozen=True, slots=True)
class StandardsAssociationAuthoringResult:
    """Immutable #33 write result with explicit non-selection evidence."""

    write_result: StandardEvidenceAssociationRevisionWriteResult
    selected_revision_before_write: int | None
    selected_revision_after_write: int | None

    @property
    def written_revision(self) -> int:
        return self.write_result.stored.decision.association_revision

    @property
    def written_disposition(self) -> str:
        return self.write_result.stored.decision.disposition

    @property
    def written_basis(self) -> str:
        return self.write_result.stored.decision.basis

    @property
    def selection_changed_during_write(self) -> bool:
        return (
            self.selected_revision_before_write
            != self.selected_revision_after_write
        )

    @property
    def selection_action(self) -> str:
        return "not_performed"


def preview_standards_association_authoring(
    workspace_root: str | Path,
    projection: StandardsReviewProjection,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    operation: StandardsAssociationAuthoringOperation,
    disposition: StandardsAssociationDisposition,
    basis: StandardsAssociationBasis,
    actor_id: str,
    rationale: str | None,
    decided_at: datetime,
) -> StandardsAssociationAuthoringPreview:
    """Build one exact #33 association revision candidate without mutation."""
    _validate_request(
        projection,
        authorized_snapshot,
        operation,
        disposition,
        basis,
        actor_id,
    )

    history = list_standard_evidence_association_revisions(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        projection.source,
        projection.standard_id,
    )
    if operation == "create" and history:
        raise StandardsAssociationAuthoringScopeError(
            "create requires an association family with no persisted revisions."
        )
    if operation == "revise" and not history:
        raise StandardsAssociationAuthoringScopeError(
            "revise requires at least one persisted association revision."
        )

    latest_sha256: str | None = None
    if history:
        latest = load_standard_evidence_association_revision(
            workspace_root,
            projection.class_id,
            projection.grade_item_id,
            projection.source,
            projection.standard_id,
            history[-1],
        )
        latest_sha256 = latest.decision_sha256

    next_revision = 1 if not history else history[-1] + 1
    try:
        candidate = StandardEvidenceAssociationDecision(
            schema_version=STANDARD_EVIDENCE_ASSOCIATION_SCHEMA_VERSION,
            record_type=STANDARD_EVIDENCE_ASSOCIATION_RECORD_TYPE,
            class_id=projection.class_id,
            grade_item_id=projection.grade_item_id,
            source=projection.source,
            standard_id=projection.standard_id,
            association_revision=next_revision,
            supersedes_revision=(
                None if next_revision == 1 else next_revision - 1
            ),
            disposition=disposition,
            basis=basis,
            actor=StandardEvidenceActor(
                kind="teacher",
                actor_id=actor_id,
            ),
            rationale=rationale,
            decided_at=decided_at,
        )
    except StandardsEvidenceValidationError as error:
        raise StandardsAssociationAuthoringScopeError(str(error)) from error

    try:
        dependencies = validate_standard_evidence_association_dependencies(
            workspace_root,
            candidate,
            authorized_snapshot,
        )
    except (
        StandardsEvidenceDependencyError,
        StandardsEvidenceStorageConflictError,
    ) as error:
        raise StandardsAssociationAuthoringScopeError(str(error)) from error

    selected = get_current_standard_evidence_association_revision(
        workspace_root,
        projection.class_id,
        projection.grade_item_id,
        projection.source,
        projection.standard_id,
    )
    return StandardsAssociationAuthoringPreview(
        projection=projection,
        operation=operation,
        candidate=candidate,
        history=history,
        latest_revision_sha256=latest_sha256,
        expected_current_association_revision=selected,
        grade_item_revision=(
            dependencies.grade_item.revision.grade_item_revision
        ),
        grade_item_revision_sha256=(
            dependencies.grade_item.revision_sha256
        ),
        membership_revision=(
            dependencies.membership.decision.membership_revision
        ),
        membership_revision_sha256=(
            dependencies.membership.decision_sha256
        ),
        standard_resolved=dependencies.standard_resolution.resolved,
        standard_active=dependencies.standard_resolution.active,
    )


def commit_standards_association_authoring_preview(
    workspace_root: str | Path,
    preview: StandardsAssociationAuthoringPreview,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> StandardsAssociationAuthoringResult:
    """Revalidate exact previewed dependencies and write without selecting."""
    if not isinstance(preview, StandardsAssociationAuthoringPreview):
        raise StandardsAssociationAuthoringScopeError(
            "preview must be a StandardsAssociationAuthoringPreview."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise StandardsAssociationAuthoringScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    _validate_authorized_source(preview, authorized_snapshot)

    history = list_standard_evidence_association_revisions(
        workspace_root,
        preview.candidate.class_id,
        preview.candidate.grade_item_id,
        preview.candidate.source,
        preview.candidate.standard_id,
    )
    if history != preview.history:
        raise StandardsAssociationAuthoringStaleError(
            "Association revision history changed after preview."
        )
    if history:
        latest = load_standard_evidence_association_revision(
            workspace_root,
            preview.candidate.class_id,
            preview.candidate.grade_item_id,
            preview.candidate.source,
            preview.candidate.standard_id,
            history[-1],
        )
        if latest.decision_sha256 != preview.latest_revision_sha256:
            raise StandardsAssociationAuthoringStaleError(
                "Latest association revision content changed after preview."
            )

    try:
        dependencies = validate_standard_evidence_association_dependencies(
            workspace_root,
            preview.candidate,
            authorized_snapshot,
        )
    except (
        StandardsEvidenceDependencyError,
        StandardsEvidenceStorageConflictError,
    ) as error:
        raise StandardsAssociationAuthoringStaleError(str(error)) from error

    if (
        dependencies.grade_item.revision.grade_item_revision
        != preview.grade_item_revision
        or dependencies.grade_item.revision_sha256
        != preview.grade_item_revision_sha256
    ):
        raise StandardsAssociationAuthoringStaleError(
            "Selected Grade Item revision changed after association preview."
        )
    if (
        dependencies.membership.decision.membership_revision
        != preview.membership_revision
        or dependencies.membership.decision_sha256
        != preview.membership_revision_sha256
    ):
        raise StandardsAssociationAuthoringStaleError(
            "Grade Item membership changed after association preview."
        )
    if (
        dependencies.standard_resolution.resolved
        != preview.standard_resolved
        or dependencies.standard_resolution.active
        != preview.standard_active
    ):
        raise StandardsAssociationAuthoringStaleError(
            "Core Standard resolution changed after association preview."
        )

    selected_before = get_current_standard_evidence_association_revision(
        workspace_root,
        preview.candidate.class_id,
        preview.candidate.grade_item_id,
        preview.candidate.source,
        preview.candidate.standard_id,
    )
    if selected_before != preview.expected_current_association_revision:
        raise StandardsAssociationAuthoringStaleError(
            "Current association selection changed after preview."
        )

    write_result = write_standard_evidence_association_revision(
        workspace_root,
        preview.candidate,
        authorized_snapshot=authorized_snapshot,
    )
    selected_after = get_current_standard_evidence_association_revision(
        workspace_root,
        preview.candidate.class_id,
        preview.candidate.grade_item_id,
        preview.candidate.source,
        preview.candidate.standard_id,
    )
    return StandardsAssociationAuthoringResult(
        write_result=write_result,
        selected_revision_before_write=selected_before,
        selected_revision_after_write=selected_after,
    )


def _validate_request(
    projection: StandardsReviewProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    operation: StandardsAssociationAuthoringOperation,
    disposition: StandardsAssociationDisposition,
    basis: StandardsAssociationBasis,
    actor_id: str,
) -> None:
    if not isinstance(projection, StandardsReviewProjection):
        raise StandardsAssociationAuthoringScopeError(
            "projection must be a StandardsReviewProjection."
        )
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise StandardsAssociationAuthoringScopeError(
            "authorized_snapshot must be an AuthorizedProjectionSnapshot."
        )
    if operation not in {"create", "revise"}:
        raise StandardsAssociationAuthoringScopeError(
            "operation must be create or revise."
        )
    if disposition not in {"associated", "not_associated"}:
        raise StandardsAssociationAuthoringScopeError(
            "disposition must be associated or not_associated."
        )
    if basis not in {"producer_declared", "explicit"}:
        raise StandardsAssociationAuthoringScopeError(
            "basis must be producer_declared or explicit."
        )
    if not isinstance(actor_id, str) or not actor_id:
        raise StandardsAssociationAuthoringScopeError(
            "actor_id must be a nonempty explicit teacher identifier."
        )
    _validate_authorized_source_projection(
        projection,
        authorized_snapshot,
    )


def _validate_authorized_source(
    preview: StandardsAssociationAuthoringPreview,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> None:
    _validate_authorized_source_projection(
        preview.projection,
        authorized_snapshot,
    )


def _validate_authorized_source_projection(
    projection: StandardsReviewProjection,
    authorized_snapshot: AuthorizedProjectionSnapshot,
) -> None:
    stored = authorized_snapshot.stored
    publication = stored.snapshot.source.publication
    source = projection.source
    if (
        publication.work != source.work
        or publication.publication_id != source.publication_id
        or stored.cache_key != source.cache_key
        or stored.snapshot_digest != source.snapshot_digest
    ):
        raise StandardsAssociationAuthoringStaleError(
            "Authorized projection does not match the reviewed evidence source."
        )
