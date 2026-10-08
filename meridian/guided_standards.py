"""Teacher-guided Standard association continuation for Issue #110."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from pds_core.standards import StandardsReadError, StandardsValidationError
from pds_core.standards_selection import (
    StandardSelectionItem,
    list_standards_for_selection,
    load_standards_for_selection,
    resolve_standard_selection,
)

from meridian.guided_projection import GuidedProjectionResult
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredProficiencyScale,
    list_proficiency_scale_ids,
    load_current_proficiency_scale,
)
from meridian.standards_association_authoring_workflow import (
    StandardsAssociationAuthoringError,
    StandardsAssociationAuthoringPreview,
    StandardsAssociationAuthoringResult,
    StandardsAssociationBasis,
    StandardsAssociationDisposition,
    commit_standards_association_authoring_preview,
    preview_standards_association_authoring,
)
from meridian.standards_association_selection_workflow import (
    StandardsAssociationSelectionError,
    StandardsAssociationSelectionPreview,
    StandardsAssociationSelectionWorkflowResult,
    commit_standards_association_selection_preview,
    preview_standards_association_selection,
)
from meridian.standards_evidence_storage import (
    StandardsEvidenceStorageError,
    list_standard_evidence_association_revisions,
)
from meridian.standards_review_workflow import (
    StandardsReviewProjection,
    StandardsReviewWorkflowError,
    build_standards_review_projection,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem


class GuidedStandardsError(RuntimeError):
    """Base failure for guided Standard association continuation."""

    code = "guided_standards.error"


class GuidedStandardsScopeError(GuidedStandardsError, ValueError):
    """Raised when carried teacher context is invalid."""

    code = "guided_standards.scope_invalid"


class GuidedStandardsActionError(GuidedStandardsError):
    """Raised when existing Standards services fail safely."""

    code = "guided_standards.action_failed"


class GuidedStandardsAmbiguityError(GuidedStandardsError):
    """Raised when teacher-facing scale presentation is ambiguous."""

    code = "guided_standards.ambiguous"


@dataclass(frozen=True, slots=True)
class GuidedStandardChoice:
    """Teacher-facing Standard label with hidden durable identity."""

    standard_id: str
    label: str
    code: str
    short_name: str
    source: str
    producer_declared: bool


@dataclass(frozen=True, slots=True)
class GuidedStandardChoices:
    """Producer-declared and broader active Standard choices."""

    declared: tuple[GuidedStandardChoice, ...]
    active: tuple[GuidedStandardChoice, ...]
    unresolved_declared_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuidedScaleChoice:
    """Teacher-facing scale title/context with exact hidden reference."""

    title: str
    context: str
    display_label: str
    reference: ProficiencyScaleReference


StandardsChoicesLoader: TypeAlias = Callable[
    [Path, TeacherEvidenceReviewItem],
    GuidedStandardChoices,
]
ScaleChoicesLoader: TypeAlias = Callable[[Path, str], tuple[GuidedScaleChoice, ...]]
AssociationHistoryLoader: TypeAlias = Callable[..., tuple[int, ...]]
AuthoringPreviewer: TypeAlias = Callable[..., StandardsAssociationAuthoringPreview]
AuthoringCommitter: TypeAlias = Callable[..., StandardsAssociationAuthoringResult]
SelectionPreviewer: TypeAlias = Callable[..., StandardsAssociationSelectionPreview]
SelectionCommitter: TypeAlias = Callable[
    ..., StandardsAssociationSelectionWorkflowResult
]


def _choice(
    item: StandardSelectionItem,
    *,
    producer_declared: bool,
) -> GuidedStandardChoice:
    return GuidedStandardChoice(
        standard_id=item.standard_id,
        label=item.label,
        code=item.code,
        short_name=item.short_name,
        source=item.source,
        producer_declared=producer_declared,
    )


def _load_standard_choices(
    root: Path,
    evidence: TeacherEvidenceReviewItem,
) -> GuidedStandardChoices:
    library = load_standards_for_selection(root)
    declared: list[GuidedStandardChoice] = []
    unresolved: list[str] = []
    declared_ids = set(evidence.standard_ids)

    for standard_id in evidence.standard_ids:
        try:
            item = resolve_standard_selection(library, standard_id)
        except StandardsValidationError:
            unresolved.append(standard_id)
            continue
        declared.append(_choice(item, producer_declared=True))

    active = tuple(
        _choice(
            item,
            producer_declared=item.standard_id in declared_ids,
        )
        for item in list_standards_for_selection(library, active=True)
    )
    return GuidedStandardChoices(
        declared=tuple(declared),
        active=active,
        unresolved_declared_ids=tuple(unresolved),
    )


def _scale_context(stored: StoredProficiencyScale) -> str:
    labels = " → ".join(level.label for level in stored.scale.levels)
    threshold = next(
        level.label
        for level in stored.scale.levels
        if level.level_id == stored.scale.proficiency_threshold_level_id
    )
    return f"{labels} · threshold {threshold}"


def _load_scale_choices(
    root: Path,
    class_id: str,
) -> tuple[GuidedScaleChoice, ...]:
    choices: list[GuidedScaleChoice] = []
    labels: set[str] = set()

    for scale_id in list_proficiency_scale_ids(root, class_id):
        stored = load_current_proficiency_scale(root, class_id, scale_id)
        if stored is None:
            continue
        context = _scale_context(stored)
        display = f"{stored.scale.title} · {context}"
        if display in labels:
            raise GuidedStandardsAmbiguityError(
                "Current proficiency scales cannot be safely distinguished "
                "without exposing internal identity."
            )
        labels.add(display)
        choices.append(
            GuidedScaleChoice(
                title=stored.scale.title,
                context=context,
                display_label=display,
                reference=stored.reference,
            )
        )
    return tuple(sorted(choices, key=lambda choice: choice.display_label.casefold()))


@dataclass(frozen=True, slots=True)
class GuidedStandardsDependencies:
    """Injectable seams over Core selection and existing #33 services."""

    standards_choices_loader: StandardsChoicesLoader = _load_standard_choices
    scale_choices_loader: ScaleChoicesLoader = _load_scale_choices
    association_history_loader: AssociationHistoryLoader = (
        list_standard_evidence_association_revisions
    )
    authoring_previewer: AuthoringPreviewer = (
        preview_standards_association_authoring
    )
    authoring_committer: AuthoringCommitter = (
        commit_standards_association_authoring_preview
    )
    selection_previewer: SelectionPreviewer = (
        preview_standards_association_selection
    )
    selection_committer: SelectionCommitter = (
        commit_standards_association_selection_preview
    )
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def load_guided_standard_choices(
    workspace_root: str | Path,
    evidence: TeacherEvidenceReviewItem,
    *,
    dependencies: GuidedStandardsDependencies,
) -> GuidedStandardChoices:
    try:
        return dependencies.standards_choices_loader(
            Path(workspace_root),
            evidence,
        )
    except (StandardsReadError, StandardsValidationError, OSError) as error:
        raise GuidedStandardsActionError(
            "The shared Standards library could not be loaded safely."
        ) from error


def load_guided_scale_choices(
    workspace_root: str | Path,
    class_id: str,
    *,
    dependencies: GuidedStandardsDependencies,
) -> tuple[GuidedScaleChoice, ...]:
    try:
        return dependencies.scale_choices_loader(Path(workspace_root), class_id)
    except (ProficiencyMappingStorageError, OSError, ValueError) as error:
        raise GuidedStandardsActionError(
            "Current proficiency scales could not be loaded safely."
        ) from error


def build_guided_standards_projection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    *,
    grade_item_id: str,
    student_id: str,
    evidence: TeacherEvidenceReviewItem,
    standard: GuidedStandardChoice,
    scale: GuidedScaleChoice,
    dependencies: GuidedStandardsDependencies,
) -> StandardsReviewProjection:
    """Build exact #33 review projection with selected teacher context."""

    if evidence.student_id != student_id:
        raise GuidedStandardsScopeError(
            "Selected roster student no longer matches the evidence row."
        )
    try:
        return build_standards_review_projection(
            Path(workspace_root),
            grade_item_id,
            student_id,
            standard.standard_id,
            evidence.item_id,
            scale.reference,
            authorized_snapshot=prepared.authorized,
        )
    except (StandardsReviewWorkflowError, ValueError) as error:
        raise GuidedStandardsActionError(
            "Standard review could not be projected safely."
        ) from error


def preview_guided_standard_association(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    projection: StandardsReviewProjection,
    *,
    disposition: StandardsAssociationDisposition,
    basis: StandardsAssociationBasis,
    teacher_attribution: str,
    rationale: str | None,
    dependencies: GuidedStandardsDependencies,
) -> StandardsAssociationAuthoringPreview:
    """Preview create/revise using exact current association family history."""

    try:
        history = dependencies.association_history_loader(
            Path(workspace_root),
            projection.class_id,
            projection.grade_item_id,
            projection.source,
            projection.standard_id,
        )
        operation = "create" if not history else "revise"
        return dependencies.authoring_previewer(
            Path(workspace_root),
            projection,
            authorized_snapshot=prepared.authorized,
            operation=operation,
            disposition=disposition,
            basis=basis,
            actor_id=teacher_attribution,
            rationale=rationale,
            decided_at=dependencies.clock(),
        )
    except (
        StandardsEvidenceStorageError,
        StandardsAssociationAuthoringError,
        ValueError,
    ) as error:
        raise GuidedStandardsActionError(
            "Standard association preview could not be prepared safely."
        ) from error


def commit_guided_standard_association(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    preview: StandardsAssociationAuthoringPreview,
    *,
    dependencies: GuidedStandardsDependencies,
) -> StandardsAssociationAuthoringResult:
    try:
        return dependencies.authoring_committer(
            Path(workspace_root),
            preview,
            authorized_snapshot=prepared.authorized,
        )
    except StandardsAssociationAuthoringError as error:
        raise GuidedStandardsActionError(
            "Standard association could not be written safely."
        ) from error


def preview_guided_standard_selection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    projection: StandardsReviewProjection,
    written_revision: int,
    *,
    dependencies: GuidedStandardsDependencies,
) -> StandardsAssociationSelectionPreview:
    try:
        return dependencies.selection_previewer(
            Path(workspace_root),
            projection,
            authorized_snapshot=prepared.authorized,
            association_revision=written_revision,
        )
    except (StandardsAssociationSelectionError, ValueError) as error:
        raise GuidedStandardsActionError(
            "Standard association selection could not be previewed safely."
        ) from error


def commit_guided_standard_selection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    preview: StandardsAssociationSelectionPreview,
    *,
    dependencies: GuidedStandardsDependencies,
) -> StandardsAssociationSelectionWorkflowResult:
    try:
        return dependencies.selection_committer(
            Path(workspace_root),
            preview,
            authorized_snapshot=prepared.authorized,
        )
    except StandardsAssociationSelectionError as error:
        raise GuidedStandardsActionError(
            "Standard association selection could not be changed safely."
        ) from error


def reload_guided_standards_projection(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    *,
    grade_item_id: str,
    student_id: str,
    evidence: TeacherEvidenceReviewItem,
    standard: GuidedStandardChoice,
    scale: GuidedScaleChoice,
) -> StandardsReviewProjection:
    try:
        return build_standards_review_projection(
            Path(workspace_root),
            grade_item_id,
            student_id,
            standard.standard_id,
            evidence.item_id,
            scale.reference,
            authorized_snapshot=prepared.authorized,
        )
    except (StandardsReviewWorkflowError, ValueError) as error:
        raise GuidedStandardsActionError(
            "Current Standard association state could not be reloaded safely."
        ) from error


__all__ = (
    "GuidedScaleChoice",
    "GuidedStandardChoice",
    "GuidedStandardChoices",
    "GuidedStandardsActionError",
    "GuidedStandardsAmbiguityError",
    "GuidedStandardsDependencies",
    "GuidedStandardsError",
    "GuidedStandardsScopeError",
    "build_guided_standards_projection",
    "commit_guided_standard_association",
    "commit_guided_standard_selection",
    "load_guided_scale_choices",
    "load_guided_standard_choices",
    "preview_guided_standard_association",
    "preview_guided_standard_selection",
    "reload_guided_standards_projection",
)
