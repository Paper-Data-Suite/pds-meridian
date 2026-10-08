"""Teacher-guided proficiency continuation for Issue #110."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from meridian.calculation_preview_assembly_workflow import (
    BoundedCalculationPreview,
    CalculationPreviewAssemblyError,
    build_bounded_calculation_preview,
)
from meridian.calculation_result_persistence_workflow import (
    CalculationResultPersistenceError,
    CalculationResultPersistencePreview,
    CalculationResultPersistenceWorkflowResult,
    commit_calculation_result_persistence_preview,
    preview_calculation_result_persistence,
)
from meridian.calculation_result_selection_workflow import (
    CalculationResultSelectionError,
    CalculationResultSelectionPreview,
    CalculationResultSelectionWorkflowResult,
    commit_calculation_result_selection_preview,
    preview_calculation_result_selection,
)
from meridian.evidence import EvidenceItem
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.guided_projection import GuidedProjectionResult
from meridian.guided_standards import GuidedScaleChoice, GuidedStandardChoice
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyMappingValidationError,
    native_value_source_signature_from_item,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    StoredNativeValueMappingProfile,
    StoredProficiencyScale,
    list_mapping_profile_ids,
    load_current_mapping_profile,
    load_current_proficiency_scale,
)
from meridian.standards_evidence_storage import (
    StandardAggregationCandidateBinding,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    StoredStandardProficiencyCalculationPolicy,
    StoredStandardProficiencyResult,
    list_standard_proficiency_policy_ids,
    load_current_standard_proficiency_policy,
    load_current_standard_proficiency_result,
)
from meridian.teacher_evidence_review import TeacherEvidenceReviewItem


class GuidedProficiencyError(RuntimeError):
    """Base failure for guided proficiency continuation."""

    code = "guided_proficiency.error"


class GuidedProficiencyScopeError(GuidedProficiencyError, ValueError):
    """Raised when carried teacher context is invalid or stale."""

    code = "guided_proficiency.scope_invalid"


class GuidedProficiencyAmbiguityError(GuidedProficiencyError):
    """Raised when readable configured choices cannot be distinguished."""

    code = "guided_proficiency.ambiguous"


class GuidedProficiencyActionError(GuidedProficiencyError):
    """Raised when an existing proficiency service fails safely."""

    code = "guided_proficiency.action_failed"


@dataclass(frozen=True, slots=True)
class GuidedProficiencyPolicyChoice:
    """Teacher-facing current policy with hidden exact reference."""

    title: str
    strategy: str
    minimum_observations: int
    display_label: str
    reference: StandardProficiencyCalculationPolicyReference = field(repr=False)


@dataclass(frozen=True, slots=True)
class GuidedMappingProfileChoice:
    """Teacher-facing current mapping semantics with hidden exact reference."""

    display_label: str
    mapping_kind: str
    reference: NativeValueMappingProfileReference = field(repr=False)


@dataclass(frozen=True, slots=True)
class GuidedProficiencyContext:
    """Exact context for one explicit evidence-row proficiency continuation."""

    source: EvidenceSourceReference = field(repr=False)
    evidence_item: EvidenceItem = field(repr=False)
    scale: StoredProficiencyScale = field(repr=False)
    policies: tuple[GuidedProficiencyPolicyChoice, ...]
    mappings: tuple[GuidedMappingProfileChoice, ...]


PolicyIdsLoader: TypeAlias = Callable[[Path, str], tuple[str, ...]]
PolicyLoader: TypeAlias = Callable[
    [Path, str, str],
    StoredStandardProficiencyCalculationPolicy | None,
]
ProfileIdsLoader: TypeAlias = Callable[[Path, str, str], tuple[str, ...]]
ProfileLoader: TypeAlias = Callable[
    [Path, str, str, str],
    StoredNativeValueMappingProfile | None,
]
ScaleLoader: TypeAlias = Callable[
    [Path, str, str],
    StoredProficiencyScale | None,
]
PreviewBuilder: TypeAlias = Callable[..., BoundedCalculationPreview]
PersistencePreviewer: TypeAlias = Callable[..., CalculationResultPersistencePreview]
PersistenceCommitter: TypeAlias = Callable[
    ..., CalculationResultPersistenceWorkflowResult
]
SelectionPreviewer: TypeAlias = Callable[..., CalculationResultSelectionPreview]
SelectionCommitter: TypeAlias = Callable[
    ..., CalculationResultSelectionWorkflowResult
]
CurrentResultLoader: TypeAlias = Callable[
    [Path, str, str, str, str],
    StoredStandardProficiencyResult | None,
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class GuidedProficiencyDependencies:
    """Injectable seams over existing proficiency calculation authority."""

    policy_ids_loader: PolicyIdsLoader = list_standard_proficiency_policy_ids
    policy_loader: PolicyLoader = load_current_standard_proficiency_policy
    profile_ids_loader: ProfileIdsLoader = list_mapping_profile_ids
    profile_loader: ProfileLoader = load_current_mapping_profile
    scale_loader: ScaleLoader = load_current_proficiency_scale
    preview_builder: PreviewBuilder = build_bounded_calculation_preview
    persistence_previewer: PersistencePreviewer = (
        preview_calculation_result_persistence
    )
    persistence_committer: PersistenceCommitter = (
        commit_calculation_result_persistence_preview
    )
    selection_previewer: SelectionPreviewer = (
        preview_calculation_result_selection
    )
    selection_committer: SelectionCommitter = (
        commit_calculation_result_selection_preview
    )
    current_result_loader: CurrentResultLoader = (
        load_current_standard_proficiency_result
    )
    clock: Callable[[], datetime] = _utc_now


def _humanize(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _policy_choices(
    policies: tuple[StoredStandardProficiencyCalculationPolicy, ...],
) -> tuple[GuidedProficiencyPolicyChoice, ...]:
    labels: set[str] = set()
    choices: list[GuidedProficiencyPolicyChoice] = []
    for stored in policies:
        policy = stored.policy
        label = (
            f"{policy.title} · {_humanize(policy.strategy)} · "
            f"minimum {policy.minimum_performance_observations}"
        )
        if label in labels:
            raise GuidedProficiencyAmbiguityError(
                "Current proficiency policies cannot be safely distinguished "
                "without exposing internal identity."
            )
        labels.add(label)
        choices.append(
            GuidedProficiencyPolicyChoice(
                title=policy.title,
                strategy=policy.strategy,
                minimum_observations=policy.minimum_performance_observations,
                display_label=label,
                reference=stored.reference,
            )
        )
    return tuple(
        sorted(choices, key=lambda choice: choice.display_label.casefold())
    )


def _mapping_label(stored: StoredNativeValueMappingProfile) -> str:
    profile = stored.profile
    rule_count = len(profile.mapping_rules)
    if profile.mapping_kind == "raw_points":
        return (
            f"Raw points · {profile.points_possible} points possible · "
            f"{rule_count} ranges"
        )
    if profile.mapping_kind == "exact_native_scale":
        native = profile.native_scale
        if native is None:
            return f"Native scale mapping · {rule_count} rules"
        name = native.name or "Producer scale"
        return f"Native scale: {name} · {len(native.levels)} levels"
    return f"Exact value mapping · {rule_count} rules"


def _mapping_choices(
    profiles: tuple[StoredNativeValueMappingProfile, ...],
) -> tuple[GuidedMappingProfileChoice, ...]:
    labels: set[str] = set()
    choices: list[GuidedMappingProfileChoice] = []
    for stored in profiles:
        label = _mapping_label(stored)
        if label in labels:
            raise GuidedProficiencyAmbiguityError(
                "Current mapping profiles cannot be safely distinguished "
                "without exposing internal identity."
            )
        labels.add(label)
        choices.append(
            GuidedMappingProfileChoice(
                display_label=label,
                mapping_kind=stored.profile.mapping_kind,
                reference=stored.reference,
            )
        )
    return tuple(
        sorted(choices, key=lambda choice: choice.display_label.casefold())
    )


def _selected_evidence_item(
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
) -> EvidenceItem:
    items = tuple(
        item
        for item in prepared.authorized.stored.snapshot.inventory.items
        if item.item_id == evidence.item_id
    )
    if len(items) != 1:
        raise GuidedProficiencyScopeError(
            "Selected evidence no longer resolves exactly in the current projection."
        )
    item = items[0]
    if evidence.student_id is None or item.subject is None:
        raise GuidedProficiencyScopeError(
            "Guided proficiency requires student-specific evidence."
        )
    if item.subject.student_id != evidence.student_id:
        raise GuidedProficiencyScopeError(
            "Selected evidence no longer matches the roster student."
        )
    return item


def load_guided_proficiency_context(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    scale: GuidedScaleChoice,
    *,
    dependencies: GuidedProficiencyDependencies,
) -> GuidedProficiencyContext:
    """Resolve current scale/policy/profile choices for one selected evidence row."""

    root = Path(workspace_root)
    item = _selected_evidence_item(prepared, evidence)
    publication = prepared.authorized.current_context.publication
    stored_projection = prepared.authorized.stored
    source = EvidenceSourceReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored_projection.cache_key,
        snapshot_digest=stored_projection.snapshot_digest,
        item_id=evidence.item_id,
    )

    try:
        stored_scale = dependencies.scale_loader(
            root,
            scale.reference.class_id,
            scale.reference.scale_id,
        )
        if stored_scale is None or stored_scale.reference != scale.reference:
            raise GuidedProficiencyScopeError(
                "The selected proficiency scale changed before continuation."
            )

        policies = tuple(
            policy_stored
            for policy_id in dependencies.policy_ids_loader(
                root,
                publication.work.class_id,
            )
            if (
                policy_stored := dependencies.policy_loader(
                    root,
                    publication.work.class_id,
                    policy_id,
                )
            )
            is not None
            and policy_stored.policy.target_scale == scale.reference
        )

        signature = native_value_source_signature_from_item(item)
        profiles = tuple(
            profile_stored
            for profile_id in dependencies.profile_ids_loader(
                root,
                publication.work.class_id,
                scale.reference.scale_id,
            )
            if (
                profile_stored := dependencies.profile_loader(
                    root,
                    publication.work.class_id,
                    scale.reference.scale_id,
                    profile_id,
                )
            )
            is not None
            and profile_stored.profile.target_scale == scale.reference
            and profile_stored.profile.source_signature == signature
        )
    except GuidedProficiencyError:
        raise
    except (
        ProficiencyMappingStorageError,
        StandardProficiencyStorageError,
        ProficiencyMappingValidationError,
        OSError,
        ValueError,
    ) as error:
        raise GuidedProficiencyActionError(
            "Current proficiency configuration could not be loaded safely."
        ) from error

    return GuidedProficiencyContext(
        source=source,
        evidence_item=item,
        scale=stored_scale,
        policies=_policy_choices(policies),
        mappings=_mapping_choices(profiles),
    )


def build_guided_proficiency_preview(
    workspace_root: str | Path,
    prepared: GuidedProjectionResult,
    context: GuidedProficiencyContext,
    *,
    grade_item_id: str,
    student_id: str,
    standard: GuidedStandardChoice,
    policy: GuidedProficiencyPolicyChoice,
    mapping: GuidedMappingProfileChoice,
    dependencies: GuidedProficiencyDependencies,
) -> BoundedCalculationPreview:
    """Build the existing read-only #34 preview over one explicit binding."""

    binding = StandardAggregationCandidateBinding(
        source=context.source,
        authorized_snapshot=prepared.authorized,
        mapping_profile=mapping.reference,
        attempt=None,
    )
    try:
        return dependencies.preview_builder(
            Path(workspace_root),
            grade_item_id,
            student_id,
            standard.standard_id,
            context.scale.reference,
            (binding,),
            policy.reference,
        )
    except (CalculationPreviewAssemblyError, ValueError) as error:
        raise GuidedProficiencyActionError(
            "Proficiency preview could not be prepared safely."
        ) from error


def preview_guided_proficiency_result(
    workspace_root: str | Path,
    reviewed: BoundedCalculationPreview,
    *,
    teacher_attribution: str,
    dependencies: GuidedProficiencyDependencies,
) -> CalculationResultPersistencePreview:
    try:
        return dependencies.persistence_previewer(
            Path(workspace_root),
            reviewed,
            actor_id=teacher_attribution,
            calculated_at=dependencies.clock(),
        )
    except (CalculationResultPersistenceError, ValueError) as error:
        raise GuidedProficiencyActionError(
            "Proficiency result write preview could not be prepared safely."
        ) from error


def commit_guided_proficiency_result(
    workspace_root: str | Path,
    preview: CalculationResultPersistencePreview,
    *,
    dependencies: GuidedProficiencyDependencies,
) -> CalculationResultPersistenceWorkflowResult:
    try:
        return dependencies.persistence_committer(
            Path(workspace_root),
            preview,
        )
    except CalculationResultPersistenceError as error:
        raise GuidedProficiencyActionError(
            "Proficiency result could not be written safely."
        ) from error


def preview_guided_proficiency_selection(
    workspace_root: str | Path,
    reviewed: BoundedCalculationPreview,
    written_revision: int,
    *,
    dependencies: GuidedProficiencyDependencies,
) -> CalculationResultSelectionPreview:
    try:
        return dependencies.selection_previewer(
            Path(workspace_root),
            reviewed.class_id,
            reviewed.grade_item_id,
            reviewed.student_id,
            reviewed.standard_id,
            written_revision,
        )
    except (CalculationResultSelectionError, ValueError) as error:
        raise GuidedProficiencyActionError(
            "Proficiency result selection could not be previewed safely."
        ) from error


def commit_guided_proficiency_selection(
    workspace_root: str | Path,
    preview: CalculationResultSelectionPreview,
    *,
    dependencies: GuidedProficiencyDependencies,
) -> CalculationResultSelectionWorkflowResult:
    try:
        return dependencies.selection_committer(
            Path(workspace_root),
            preview,
        )
    except CalculationResultSelectionError as error:
        raise GuidedProficiencyActionError(
            "Proficiency result selection could not be changed safely."
        ) from error


def reload_current_guided_proficiency_result(
    workspace_root: str | Path,
    reviewed: BoundedCalculationPreview,
    *,
    dependencies: GuidedProficiencyDependencies,
) -> StoredStandardProficiencyResult:
    try:
        stored = dependencies.current_result_loader(
            Path(workspace_root),
            reviewed.class_id,
            reviewed.grade_item_id,
            reviewed.student_id,
            reviewed.standard_id,
        )
    except StandardProficiencyStorageError as error:
        raise GuidedProficiencyActionError(
            "Current proficiency result could not be reloaded safely."
        ) from error
    if stored is None:
        raise GuidedProficiencyScopeError(
            "The proficiency result is not current after selection."
        )
    return stored


def proficiency_level_label(
    context: GuidedProficiencyContext,
    level_id: str | None,
) -> str | None:
    if level_id is None:
        return None
    for level in context.scale.scale.levels:
        if level.level_id == level_id:
            return level.label
    raise GuidedProficiencyScopeError(
        "Calculated proficiency level does not exist on the selected scale."
    )


__all__ = (
    "GuidedMappingProfileChoice",
    "GuidedProficiencyActionError",
    "GuidedProficiencyAmbiguityError",
    "GuidedProficiencyContext",
    "GuidedProficiencyDependencies",
    "GuidedProficiencyError",
    "GuidedProficiencyPolicyChoice",
    "GuidedProficiencyScopeError",
    "build_guided_proficiency_preview",
    "commit_guided_proficiency_result",
    "commit_guided_proficiency_selection",
    "load_guided_proficiency_context",
    "preview_guided_proficiency_result",
    "preview_guided_proficiency_selection",
    "proficiency_level_label",
    "reload_current_guided_proficiency_result",
)
