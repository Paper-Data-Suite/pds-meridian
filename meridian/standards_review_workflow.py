"""Read-only teacher Standards Review projection over canonical #32/#33 state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pds_core.standards import StandardsLibrary

from meridian.attempt_selection import AttemptObservationReference
from meridian.evidence import NativeStateValue
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.evidence_eligibility_storage import (
    EvidenceEligibilityDependencyError,
    validate_authorized_evidence_source,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_current_grade_item_revision,
)
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_evidence import GradeItemAggregationBasis
from meridian.standards_evidence_storage import (
    CoreStandardResolution,
    StandardAggregationCandidateBinding,
    StandardsEvidenceDependencyError,
    StandardsEvidenceStorageError,
    resolve_current_standard_evidence_association,
    resolve_standard_aggregation_candidate,
    resolve_standard_aggregation_inputs,
)


class StandardsReviewWorkflowError(RuntimeError):
    """Base error for the teacher Standards Review projection."""

    code = "teacher_workflow.standards_review_error"


class StandardsReviewWorkflowScopeError(
    StandardsReviewWorkflowError, ValueError
):
    """Raised when the requested Standards Review scope is invalid."""

    code = "teacher_workflow.standards_review_invalid"


class StandardsReviewWorkflowDependencyError(StandardsReviewWorkflowError):
    """Raised when canonical #27-#33 dependencies cannot be reviewed."""

    code = "teacher_workflow.standards_review_dependency_invalid"


@dataclass(frozen=True, slots=True)
class StandardsReviewProjection:
    """One exact evidence-to-standard interpretation path."""

    class_id: str
    grade_item_id: str
    student_id: str
    standard_id: str
    source: EvidenceSourceReference
    producer_declared_standard_ids: tuple[str, ...]
    producer_declares_standard: bool
    standard_resolution: CoreStandardResolution
    association_status: str
    association_revision: int | None
    association_sha256: str | None
    association_disposition: str | None
    association_basis: str | None
    association_actor_kind: str | None
    association_actor_id: str | None
    association_rationale: str | None
    operative_associated: bool
    target_scale: ProficiencyScaleReference
    mapping_profile: NativeValueMappingProfileReference | None
    mapping_status: str | None
    mapped_proficiency_level_id: str | None
    native_state: NativeStateValue | None
    mapping_unsupported_reason: str | None
    result_kind: str
    target_kind: str
    subject_kind: str
    subject_student_id: str | None
    eligibility_state: str
    attempt_state: str
    reassessment_state: str
    aggregation_status: str
    aggregation_exclusion_reason: str | None
    membership_revision: int | None
    eligibility_revision: int | None
    attempt_selection_revision: int | None
    reassessment_revision: int | None
    calculation_performed: bool = False

    @property
    def item_id(self) -> str:
        return self.source.item_id

    @property
    def mapping_profile_supplied(self) -> bool:
        return self.mapping_profile is not None

    @property
    def contributes_performance(self) -> bool:
        return self.aggregation_status == "performance"

    @property
    def preserves_native_state(self) -> bool:
        return self.aggregation_status == "native_state"


def build_standards_review_projection(
    workspace_root: str | Path,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    item_id: str,
    target_scale: ProficiencyScaleReference,
    *,
    authorized_snapshot: AuthorizedProjectionSnapshot,
    mapping_profile: NativeValueMappingProfileReference | None = None,
    attempt: AttemptObservationReference | None = None,
    standards_library: StandardsLibrary | None = None,
) -> StandardsReviewProjection:
    """Project one exact source through #29-#33 without calculating proficiency."""
    _validate_request(
        authorized_snapshot,
        grade_item_id,
        student_id,
        standard_id,
        item_id,
        target_scale,
        mapping_profile,
    )
    stored_snapshot = authorized_snapshot.stored
    publication = stored_snapshot.snapshot.source.publication
    class_id = publication.work.class_id
    source = EvidenceSourceReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored_snapshot.cache_key,
        snapshot_digest=stored_snapshot.snapshot_digest,
        item_id=item_id,
    )

    try:
        evidence_item = validate_authorized_evidence_source(
            source,
            authorized_snapshot,
        )
    except EvidenceEligibilityDependencyError as error:
        raise StandardsReviewWorkflowDependencyError(str(error)) from error

    try:
        current_grade_item = load_current_grade_item_revision(
            workspace_root,
            class_id,
            grade_item_id,
        )
    except GradeItemStorageError as error:
        raise StandardsReviewWorkflowDependencyError(
            f"Current Grade Item could not be loaded: {error}"
        ) from error
    if current_grade_item is None:
        raise StandardsReviewWorkflowDependencyError(
            "Standards Review requires an explicitly selected Grade Item revision."
        )

    grade_item_basis = GradeItemAggregationBasis(
        class_id=class_id,
        grade_item_id=grade_item_id,
        grade_item_revision=current_grade_item.revision.grade_item_revision,
        grade_item_revision_sha256=current_grade_item.revision_sha256,
    )
    binding = StandardAggregationCandidateBinding(
        source=source,
        authorized_snapshot=authorized_snapshot,
        mapping_profile=mapping_profile,
        attempt=attempt,
    )

    try:
        association = resolve_current_standard_evidence_association(
            workspace_root,
            class_id,
            grade_item_id,
            source,
            standard_id,
            authorized_snapshot=authorized_snapshot,
            standards_library=standards_library,
        )
        candidate = resolve_standard_aggregation_candidate(
            workspace_root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            binding,
            standards_library=standards_library,
        )
        aggregation = resolve_standard_aggregation_inputs(
            workspace_root,
            grade_item_basis,
            student_id,
            standard_id,
            target_scale,
            (binding,),
            standards_library=standards_library,
        )
    except (
        StandardsEvidenceDependencyError,
        StandardsEvidenceStorageError,
    ) as error:
        raise StandardsReviewWorkflowDependencyError(str(error)) from error

    if len(aggregation.entries) != 1:
        raise StandardsReviewWorkflowDependencyError(
            "Single-source Standards Review must resolve exactly one aggregation entry."
        )
    entry = aggregation.entries[0]
    if entry.source != source:
        raise StandardsReviewWorkflowDependencyError(
            "Canonical aggregation entry does not match the reviewed source."
        )

    selected = association.selected
    decision = None if selected is None else selected.decision
    mapping = candidate.mapping_outcome

    producer_standard_ids = tuple(evidence_item.target.standard_ids)
    normalized_standard_id = aggregation.standard_id
    return StandardsReviewProjection(
        class_id=class_id,
        grade_item_id=grade_item_id,
        student_id=aggregation.student_id,
        standard_id=normalized_standard_id,
        source=source,
        producer_declared_standard_ids=producer_standard_ids,
        producer_declares_standard=(
            normalized_standard_id in producer_standard_ids
        ),
        standard_resolution=association.standard_resolution,
        association_status=association.status,
        association_revision=(
            None if decision is None else decision.association_revision
        ),
        association_sha256=(
            None if selected is None else selected.decision_sha256
        ),
        association_disposition=(
            None if decision is None else decision.disposition
        ),
        association_basis=None if decision is None else decision.basis,
        association_actor_kind=(
            None if decision is None else decision.actor.kind
        ),
        association_actor_id=(
            None if decision is None else decision.actor.actor_id
        ),
        association_rationale=(
            None if decision is None else decision.rationale
        ),
        operative_associated=association.operative_associated,
        target_scale=aggregation.target_scale,
        mapping_profile=None if mapping is None else mapping.profile,
        mapping_status=None if mapping is None else mapping.status,
        mapped_proficiency_level_id=(
            None if mapping is None else mapping.proficiency_level_id
        ),
        native_state=None if mapping is None else mapping.native_state,
        mapping_unsupported_reason=(
            None if mapping is None else mapping.unsupported_reason
        ),
        result_kind=candidate.result_kind,
        target_kind=candidate.target_kind,
        subject_kind=candidate.subject_kind,
        subject_student_id=candidate.subject_student_id,
        eligibility_state=candidate.eligibility_state,
        attempt_state=candidate.attempt_state,
        reassessment_state=candidate.reassessment_state,
        aggregation_status=entry.status,
        aggregation_exclusion_reason=entry.exclusion_reason,
        membership_revision=(
            None
            if entry.membership_reference is None
            else entry.membership_reference.revision
        ),
        eligibility_revision=(
            None
            if entry.eligibility_reference is None
            else entry.eligibility_reference.revision
        ),
        attempt_selection_revision=(
            None
            if entry.attempt_selection_reference is None
            else entry.attempt_selection_reference.revision
        ),
        reassessment_revision=(
            None
            if entry.reassessment_reference is None
            else entry.reassessment_reference.revision
        ),
    )


def _validate_request(
    authorized_snapshot: AuthorizedProjectionSnapshot,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    item_id: str,
    target_scale: ProficiencyScaleReference,
    mapping_profile: NativeValueMappingProfileReference | None,
) -> None:
    if not isinstance(authorized_snapshot, AuthorizedProjectionSnapshot):
        raise StandardsReviewWorkflowScopeError(
            "Standards Review requires an AuthorizedProjectionSnapshot."
        )
    for field_name, value in (
        ("grade_item_id", grade_item_id),
        ("student_id", student_id),
        ("standard_id", standard_id),
        ("item_id", item_id),
    ):
        if not isinstance(value, str) or not value:
            raise StandardsReviewWorkflowScopeError(
                f"{field_name} must be a nonempty string."
            )
    if not isinstance(target_scale, ProficiencyScaleReference):
        raise StandardsReviewWorkflowScopeError(
            "target_scale must be an exact ProficiencyScaleReference."
        )
    if (
        mapping_profile is not None
        and not isinstance(
            mapping_profile,
            NativeValueMappingProfileReference,
        )
    ):
        raise StandardsReviewWorkflowScopeError(
            "mapping_profile must be an exact profile reference or None."
        )
    publication = authorized_snapshot.stored.snapshot.source.publication
    if target_scale.class_id != publication.work.class_id:
        raise StandardsReviewWorkflowScopeError(
            "target_scale class must match the authorized publication class."
        )
    if (
        mapping_profile is not None
        and mapping_profile.class_id != publication.work.class_id
    ):
        raise StandardsReviewWorkflowScopeError(
            "mapping_profile class must match the authorized publication class."
        )
