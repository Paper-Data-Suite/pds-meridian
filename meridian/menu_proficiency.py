"""Teacher-facing read-only proficiency review for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
)
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef, RoutingModelError
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.academic_period_calculation_assembly_workflow import (
    AcademicPeriodCalculationAssemblyError,
    AcademicPeriodCalculationCandidateSpec,
    AcademicPeriodMembershipSpec,
    BoundedAcademicPeriodCalculationPreview,
    build_bounded_academic_period_calculation_preview,
)
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
from meridian.academic_period_result_persistence_workflow import (
    AcademicPeriodResultPersistenceError,
    AcademicPeriodResultPersistencePreview,
    AcademicPeriodResultPersistenceWorkflowResult,
    commit_academic_period_result_persistence_preview,
    preview_academic_period_result_persistence,
)
from meridian.academic_period_result_selection_workflow import (
    AcademicPeriodResultSelectionError,
    AcademicPeriodResultSelectionPreview,
    AcademicPeriodResultSelectionWorkflowResult,
    commit_academic_period_result_selection_preview,
    preview_academic_period_result_selection,
)
from meridian.calculation_preview_assembly_workflow import (
    BoundedCalculationPreview,
    CalculationPreviewAssemblyError,
    CalculationPreviewAssemblyScopeError,
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
from meridian.diagnostics import (
    DiagnosticsAuthorizationProviderRequiredError,
    DiagnosticsDependencies,
    DiagnosticsError,
    EvidenceFilters,
    default_diagnostics_dependencies,
    inspect_evidence_diagnostic,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceError,
    GradeItemProficiencyTraceTarget,
    ProficiencyLevelExplanation,
    explain_grade_item_proficiency,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.planning_signal_workflow import (
    PlanningSignalWorkflowError,
    project_planning_signal_readiness,
)
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)
from meridian.projection_cache import ProjectionCacheError
from meridian.standards_evidence_storage import (
    StandardAggregationCandidateBinding,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]


@dataclass(frozen=True, slots=True)
class GradeItemProficiencyPresentation:
    class_id: str
    grade_item_id: str
    grade_item_title: str
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    policy_title: str
    scale_title: str
    status: str
    proficiency_label: str | None
    performance_count: int
    native_state_count: int
    excluded_count: int


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyPresentation:
    class_id: str
    school_year: str
    period_id: str
    period_label: str
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    policy_title: str
    scale_title: str
    status: str
    proficiency_label: str | None
    calculated_count: int
    insufficient_count: int
    missing_count: int
    period_scope_mismatch_count: int


@dataclass(frozen=True, slots=True)
class PlanningReadinessPresentation:
    class_id: str
    policy_id: str
    policy_title: str | None
    period_text: str | None
    standard_id: str | None
    dimension_id: str | None
    status: str
    blocker_codes: tuple[str, ...]
    ready: bool
    roster_count: int | None
    contributing_count: int | None
    noncontributing_count: int | None
    policy_revision: int | None
    policy_sha256: str | None
    derivation_id: str | None
    calculation_fingerprint: str | None


GradeItemLoader: TypeAlias = Callable[
    [Path, str, str, str, str],
    GradeItemProficiencyPresentation,
]
AcademicPeriodLoader: TypeAlias = Callable[
    [Path, str, str, str, str, str],
    AcademicPeriodProficiencyPresentation,
]
PlanningLoader: TypeAlias = Callable[
    [Path, str, str],
    PlanningReadinessPresentation,
]
Clock: TypeAlias = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CalculationBindingSpec:
    publication_id: str
    cache_key: str
    item_id: str
    mapping_profile: NativeValueMappingProfileReference | None


GradeItemPreviewBuilder: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        str,
        str,
        ProficiencyScaleReference,
        tuple[CalculationBindingSpec, ...],
        StandardProficiencyCalculationPolicyReference,
        str,
        tuple[str, ...],
    ],
    BoundedCalculationPreview,
]
GradeItemPersistencePreviewer: TypeAlias = Callable[
    [Path, BoundedCalculationPreview, str, datetime],
    CalculationResultPersistencePreview,
]
GradeItemPersistenceCommitter: TypeAlias = Callable[
    [Path, CalculationResultPersistencePreview],
    CalculationResultPersistenceWorkflowResult,
]
GradeItemSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, int],
    CalculationResultSelectionPreview,
]
GradeItemSelectionCommitter: TypeAlias = Callable[
    [Path, CalculationResultSelectionPreview],
    CalculationResultSelectionWorkflowResult,
]
AcademicPeriodPreviewBuilder: TypeAlias = Callable[
    [
        Path,
        AcademicPeriodProficiencyTarget,
        str,
        str,
        tuple[AcademicPeriodCalculationCandidateSpec, ...],
        AcademicPeriodProficiencyAggregationPolicyReference,
    ],
    BoundedAcademicPeriodCalculationPreview,
]
AcademicPeriodPersistencePreviewer: TypeAlias = Callable[
    [Path, BoundedAcademicPeriodCalculationPreview, str, datetime],
    AcademicPeriodResultPersistencePreview,
]
AcademicPeriodPersistenceCommitter: TypeAlias = Callable[
    [Path, AcademicPeriodResultPersistencePreview],
    AcademicPeriodResultPersistenceWorkflowResult,
]
AcademicPeriodSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, str, int],
    AcademicPeriodResultSelectionPreview,
]
AcademicPeriodSelectionCommitter: TypeAlias = Callable[
    [Path, AcademicPeriodResultSelectionPreview],
    AcademicPeriodResultSelectionWorkflowResult,
]


@dataclass(frozen=True, slots=True)
class ProficiencyMenuDependencies:
    workspace_resolver: WorkspaceResolver
    grade_item_loader: GradeItemLoader
    academic_period_loader: AcademicPeriodLoader
    planning_loader: PlanningLoader


@dataclass(frozen=True, slots=True)
class GradeItemProficiencyActionDependencies:
    clock: Clock
    diagnostics: DiagnosticsDependencies
    preview_builder: GradeItemPreviewBuilder
    persistence_previewer: GradeItemPersistencePreviewer
    persistence_committer: GradeItemPersistenceCommitter
    selection_previewer: GradeItemSelectionPreviewer
    selection_committer: GradeItemSelectionCommitter


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyActionDependencies:
    clock: Clock
    preview_builder: AcademicPeriodPreviewBuilder
    persistence_previewer: AcademicPeriodPersistencePreviewer
    persistence_committer: AcademicPeriodPersistenceCommitter
    selection_previewer: AcademicPeriodSelectionPreviewer
    selection_committer: AcademicPeriodSelectionCommitter


def _level_label(
    level_id: str | None,
    levels: tuple[ProficiencyLevelExplanation, ...],
) -> str | None:
    if level_id is None:
        return None
    for level in levels:
        if level.level_id == level_id:
            return level.label
    return level_id


def _load_grade_item(
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> GradeItemProficiencyPresentation:
    target = GradeItemProficiencyTraceTarget(
        class_id=class_id,
        grade_item_id=grade_item_id,
        student_id=student_id,
        standard_id=standard_id,
        selection="current",
    )
    value = explain_grade_item_proficiency(root, target)
    return GradeItemProficiencyPresentation(
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        grade_item_title=value.grade_item.title,
        student_id=value.student_id,
        standard_id=value.standard_id,
        result_revision=value.result_revision,
        result_sha256=value.result_sha256,
        policy_title=value.policy.title,
        scale_title=value.scale.title,
        status=value.calculation.status,
        proficiency_label=_level_label(
            value.calculation.proficiency_level_id,
            value.scale.levels,
        ),
        performance_count=value.calculation.performance_observation_count,
        native_state_count=value.calculation.native_state_count,
        excluded_count=value.calculation.excluded_count,
    )


def _load_academic_period(
    root: Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> AcademicPeriodProficiencyPresentation:
    target = AcademicPeriodProficiencyTraceTarget(
        class_id=class_id,
        school_year=school_year,
        period_id=period_id,
        student_id=student_id,
        standard_id=standard_id,
        selection="current",
    )
    value = explain_academic_period_proficiency(root, target)
    return AcademicPeriodProficiencyPresentation(
        class_id=value.class_id,
        school_year=value.target_period.school_year,
        period_id=value.target_period.period_id,
        period_label=value.target_period.label,
        student_id=value.student_id,
        standard_id=value.standard_id,
        result_revision=value.result_revision,
        result_sha256=value.result_sha256,
        policy_title=value.policy.title,
        scale_title=value.scale.title,
        status=value.calculation.status,
        proficiency_label=_level_label(
            value.calculation.proficiency_level_id,
            value.scale.levels,
        ),
        calculated_count=value.calculation.calculated_result_count,
        insufficient_count=value.calculation.insufficient_result_count,
        missing_count=value.calculation.missing_result_count,
        period_scope_mismatch_count=(
            value.calculation.period_scope_mismatch_count
        ),
    )


def _load_planning(
    root: Path,
    class_id: str,
    policy_id: str,
) -> PlanningReadinessPresentation:
    value = project_planning_signal_readiness(root, class_id, policy_id)
    policy = value.policy
    if policy is None:
        return PlanningReadinessPresentation(
            class_id=value.class_id,
            policy_id=value.policy_id,
            policy_title=None,
            period_text=None,
            standard_id=None,
            dimension_id=None,
            status=value.generation_status,
            blocker_codes=value.blocker_codes,
            ready=value.ready_for_derivation_persistence,
            roster_count=value.roster_student_count,
            contributing_count=value.contributing_student_count,
            noncontributing_count=value.noncontributing_student_count,
            policy_revision=None,
            policy_sha256=None,
            derivation_id=value.candidate_derivation_id,
            calculation_fingerprint=(
                value.candidate_calculation_fingerprint
            ),
        )
    period = policy.target_period.period
    return PlanningReadinessPresentation(
        class_id=value.class_id,
        policy_id=value.policy_id,
        policy_title=policy.title,
        period_text=f"{period.school_year} / {period.period_id}",
        standard_id=policy.standard_id,
        dimension_id=policy.dimension_id,
        status=value.generation_status,
        blocker_codes=value.blocker_codes,
        ready=value.ready_for_derivation_persistence,
        roster_count=value.roster_student_count,
        contributing_count=value.contributing_student_count,
        noncontributing_count=value.noncontributing_student_count,
        policy_revision=policy.reference.policy_revision,
        policy_sha256=policy.reference.policy_sha256,
        derivation_id=value.candidate_derivation_id,
        calculation_fingerprint=value.candidate_calculation_fingerprint,
    )


def default_proficiency_menu_dependencies() -> ProficiencyMenuDependencies:
    return ProficiencyMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        grade_item_loader=_load_grade_item,
        academic_period_loader=_load_academic_period,
        planning_loader=_load_planning,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _build_grade_item_preview(
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    binding_specs: tuple[CalculationBindingSpec, ...],
    policy_reference: StandardProficiencyCalculationPolicyReference,
    purpose_id: str,
    requested_student_ids: tuple[str, ...],
    *,
    diagnostics: DiagnosticsDependencies,
) -> BoundedCalculationPreview:
    bindings: list[StandardAggregationCandidateBinding] = []
    for spec in binding_specs:
        inspection = inspect_evidence_diagnostic(
            root,
            spec.publication_id,
            spec.cache_key,
            authorization_purpose_id=purpose_id,
            requested_student_ids=requested_student_ids,
            filters=EvidenceFilters(item_ids=(spec.item_id,)),
            dependencies=diagnostics,
        )
        if len(inspection.items) != 1:
            raise CalculationPreviewAssemblyScopeError(
                "Each Grade Item proficiency binding must resolve to exactly "
                "one authorized evidence item."
            )
        item = inspection.items[0]
        if item.item_id != spec.item_id:
            raise CalculationPreviewAssemblyScopeError(
                "Authorized binding item identity changed during review."
            )
        authorized = inspection.authorized
        stored = authorized.stored
        publication = stored.snapshot.source.publication
        if publication.work.class_id != class_id:
            raise CalculationPreviewAssemblyScopeError(
                "Every Grade Item proficiency binding must belong to the "
                "requested class."
            )
        source = EvidenceSourceReference(
            work=publication.work,
            publication_id=publication.publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=spec.item_id,
        )
        bindings.append(
            StandardAggregationCandidateBinding(
                source=source,
                authorized_snapshot=authorized,
                mapping_profile=spec.mapping_profile,
                attempt=None,
            )
        )
    return build_bounded_calculation_preview(
        root,
        grade_item_id,
        student_id,
        standard_id,
        target_scale,
        tuple(bindings),
        policy_reference,
    )


def _preview_result_persistence(
    root: Path,
    reviewed: BoundedCalculationPreview,
    actor_id: str,
    calculated_at: datetime,
) -> CalculationResultPersistencePreview:
    return preview_calculation_result_persistence(
        root,
        reviewed,
        actor_id=actor_id,
        calculated_at=calculated_at,
    )


def default_grade_item_proficiency_action_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
) -> GradeItemProficiencyActionDependencies:
    active = diagnostics or default_diagnostics_dependencies()

    def build(
        root: Path,
        class_id: str,
        grade_item_id: str,
        student_id: str,
        standard_id: str,
        target_scale: ProficiencyScaleReference,
        binding_specs: tuple[CalculationBindingSpec, ...],
        policy_reference: StandardProficiencyCalculationPolicyReference,
        purpose_id: str,
        requested_student_ids: tuple[str, ...],
    ) -> BoundedCalculationPreview:
        return _build_grade_item_preview(
            root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            target_scale,
            binding_specs,
            policy_reference,
            purpose_id,
            requested_student_ids,
            diagnostics=active,
        )

    return GradeItemProficiencyActionDependencies(
        clock=_utc_now,
        diagnostics=active,
        preview_builder=build,
        persistence_previewer=_preview_result_persistence,
        persistence_committer=commit_calculation_result_persistence_preview,
        selection_previewer=preview_calculation_result_selection,
        selection_committer=commit_calculation_result_selection_preview,
    )


def _preview_academic_period_result_persistence(
    root: Path,
    reviewed: BoundedAcademicPeriodCalculationPreview,
    actor_id: str,
    calculated_at: datetime,
) -> AcademicPeriodResultPersistencePreview:
    return preview_academic_period_result_persistence(
        root,
        reviewed,
        actor_id=actor_id,
        calculated_at=calculated_at,
    )


def default_academic_period_proficiency_action_dependencies(
) -> AcademicPeriodProficiencyActionDependencies:
    return AcademicPeriodProficiencyActionDependencies(
        clock=_utc_now,
        preview_builder=build_bounded_academic_period_calculation_preview,
        persistence_previewer=_preview_academic_period_result_persistence,
        persistence_committer=commit_academic_period_result_persistence_preview,
        selection_previewer=preview_academic_period_result_selection,
        selection_committer=commit_academic_period_result_selection_preview,
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _proficiency_text(status: str, label: str | None) -> str:
    if status == "calculated" and label is not None:
        return label
    return _humanize(status)


def _show_grade_item(
    value: GradeItemProficiencyPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(output, "Grade Item Proficiency")
    proficiency = _proficiency_text(value.status, value.proficiency_label)
    write_lines(
        output,
        f"Grade Item: {value.grade_item_title}",
        f"Student: {value.student_id}",
        f"Standard: {value.standard_id}",
        f"Current proficiency: {proficiency}",
        f"Policy: {value.policy_title}",
        f"Scale: {value.scale_title}",
        "",
        (
            "Evidence: "
            f"{value.performance_count} performance, "
            f"{value.native_state_count} native-state, "
            f"{value.excluded_count} excluded"
        ),
    )


def _show_grade_item_technical(
    value: GradeItemProficiencyPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(
        output,
        "Grade Item Proficiency — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.class_id}",
        f"grade_item_id: {value.grade_item_id}",
        f"student_id: {value.student_id}",
        f"standard_id: {value.standard_id}",
        f"result_revision: {value.result_revision}",
        f"result_sha256: {value.result_sha256}",
    )


def _show_academic_period(
    value: AcademicPeriodProficiencyPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(output, "Academic Period Proficiency")
    proficiency = _proficiency_text(value.status, value.proficiency_label)
    write_lines(
        output,
        f"Academic Period: {value.period_label}",
        f"Student: {value.student_id}",
        f"Standard: {value.standard_id}",
        f"Current proficiency: {proficiency}",
        f"Policy: {value.policy_title}",
        f"Scale: {value.scale_title}",
        "",
        (
            "Grade Items: "
            f"{value.calculated_count} calculated, "
            f"{value.insufficient_count} insufficient, "
            f"{value.missing_count} missing, "
            f"{value.period_scope_mismatch_count} outside period scope"
        ),
    )


def _show_academic_period_technical(
    value: AcademicPeriodProficiencyPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(
        output,
        "Academic Period Proficiency — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.class_id}",
        f"school_year: {value.school_year}",
        f"period_id: {value.period_id}",
        f"student_id: {value.student_id}",
        f"standard_id: {value.standard_id}",
        f"result_revision: {value.result_revision}",
        f"result_sha256: {value.result_sha256}",
    )


def _show_planning(
    value: PlanningReadinessPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(output, "Planning Signal Readiness")
    if value.policy_title is None:
        write_lines(
            output,
            "No grouping-signal policy is currently selected for this policy ID.",
            "Select a policy before deriving a planning signal.",
        )
    else:
        write_lines(
            output,
            f"Policy: {value.policy_title}",
            f"Academic Period: {value.period_text or 'unavailable'}",
            f"Standard: {value.standard_id or 'unavailable'}",
            f"Dimension: {value.dimension_id or 'unavailable'}",
            f"Readiness: {_humanize(value.status)}",
        )
        if value.roster_count is not None:
            contributing = value.contributing_count or 0
            noncontributing = value.noncontributing_count or 0
            write_lines(
                output,
                "",
                (
                    "Students: "
                    f"{value.roster_count} rostered, "
                    f"{contributing} contributing, "
                    f"{noncontributing} noncontributing"
                ),
            )
    if value.blocker_codes:
        write_lines(output, "", "Needs attention:")
        for code in value.blocker_codes:
            print(f"  - {_humanize(code)}", file=output)
    if value.ready:
        write_lines(
            output,
            "",
            "A derivation candidate is ready for the planning workflow.",
            "Nothing has been written or exported from this review.",
        )


def _show_planning_technical(
    value: PlanningReadinessPresentation,
    *,
    output: TextIO,
) -> None:
    print_menu_header(
        output,
        "Planning Signal Readiness — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.class_id}",
        f"policy_id: {value.policy_id}",
        f"policy_revision: {value.policy_revision or 'none'}",
        f"policy_sha256: {value.policy_sha256 or 'none'}",
        f"candidate_derivation_id: {value.derivation_id or 'none'}",
        (
            "candidate_calculation_fingerprint: "
            f"{value.calculation_fingerprint or 'none'}"
        ),
    )


def _review_grade_item(
    *,
    deps: ProficiencyMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Grade Item Proficiency")
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        value = deps.grade_item_loader(
            deps.workspace_resolver(),
            class_id,
            grade_item_id,
            student_id,
            standard_id,
        )
    except (WorkspaceRootError, ExplanationTraceError, ValueError) as error:
        write_lines(
            output,
            "",
            "Current Grade Item proficiency could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _show_grade_item(value, output=output)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _show_grade_item_technical(value, output=output)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _review_academic_period(
    *,
    deps: ProficiencyMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Academic Period Proficiency")
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        value = deps.academic_period_loader(
            deps.workspace_resolver(),
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
    except (WorkspaceRootError, ExplanationTraceError, ValueError) as error:
        write_lines(
            output,
            "",
            "Current Academic Period proficiency could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _show_academic_period(value, output=output)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _show_academic_period_technical(value, output=output)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _review_planning(
    *,
    deps: ProficiencyMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Planning Signal Readiness")
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return
    policy_id = read_choice(input_fn, "Grouping-signal policy ID: ")
    try:
        value = deps.planning_loader(
            deps.workspace_resolver(),
            class_id,
            policy_id,
        )
    except (WorkspaceRootError, PlanningSignalWorkflowError, ValueError) as error:
        write_lines(
            output,
            "",
            "Planning-signal readiness could not be reviewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _show_planning(value, output=output)
        write_lines(output, "", "T. Technical details / provenance")
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _show_planning_technical(value, output=output)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _positive_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a positive integer") from error
    if result < 1:
        raise ValueError(f"{label} must be a positive integer")
    return result


def _nonnegative_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a nonnegative integer") from error
    if result < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return result


def _student_scope(raw: str, student_id: str) -> tuple[str, ...]:
    if not raw.strip():
        return (student_id,)
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    if len(set(values)) != len(values):
        raise ValueError("authorization Student IDs must not contain duplicates")
    return tuple(sorted(values))


def _mapping_profile(
    *,
    input_fn: InputFunction,
    output: TextIO,
    class_id: str,
) -> NativeValueMappingProfileReference | None:
    choice = read_choice(
        input_fn,
        "Use an exact mapping profile for this binding? (yes/no): ",
    ).casefold()
    if choice in {"n", "no"}:
        return None
    if choice not in {"y", "yes"}:
        raise ValueError("mapping-profile choice must be yes or no")
    scale_id = read_choice(input_fn, "Mapping-profile scale ID: ")
    profile_id = read_choice(input_fn, "Mapping-profile ID: ")
    revision = _positive_int(
        read_choice(input_fn, "Mapping-profile revision: "),
        "mapping-profile revision",
    )
    digest = read_choice(input_fn, "Mapping-profile sha256: ")
    write_lines(
        output,
        "Mapping profile is explicit for this evidence binding.",
    )
    return NativeValueMappingProfileReference(
        class_id=class_id,
        scale_id=scale_id,
        profile_id=profile_id,
        profile_revision=revision,
        profile_sha256=digest,
    )


def _calculation_request(
    *,
    deps: ProficiencyMenuDependencies,
    actions: GradeItemProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> tuple[Path, BoundedCalculationPreview] | None:
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return None
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return None
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")

    scale_id = read_choice(input_fn, "Target proficiency scale ID: ")
    scale_revision = _positive_int(
        read_choice(input_fn, "Target scale revision: "),
        "target scale revision",
    )
    scale_sha256 = read_choice(input_fn, "Target scale sha256: ")
    target_scale = ProficiencyScaleReference(
        class_id=class_id,
        scale_id=scale_id,
        scale_revision=scale_revision,
        scale_sha256=scale_sha256,
    )

    policy_id = read_choice(input_fn, "Calculation policy ID: ")
    policy_revision = _positive_int(
        read_choice(input_fn, "Calculation policy revision: "),
        "calculation policy revision",
    )
    policy_sha256 = read_choice(input_fn, "Calculation policy sha256: ")
    policy_reference = StandardProficiencyCalculationPolicyReference(
        class_id=class_id,
        policy_id=policy_id,
        policy_revision=policy_revision,
        policy_sha256=policy_sha256,
    )

    purpose_id = read_choice(input_fn, "Authorization purpose ID: ")
    scope = _student_scope(
        read_choice(
            input_fn,
            "Authorization Student IDs, comma-separated "
            "(blank for target student): ",
        ),
        student_id,
    )

    binding_count = _nonnegative_int(
        read_choice(input_fn, "Number of explicit evidence bindings: "),
        "binding count",
    )
    specs: list[CalculationBindingSpec] = []
    for index in range(1, binding_count + 1):
        write_lines(output, "", f"Evidence binding {index} of {binding_count}")
        publication_id = read_choice(input_fn, "Publication ID: ")
        cache_key = read_choice(input_fn, "Projection cache key: ")
        item_id = read_choice(input_fn, "Evidence item ID: ")
        mapping = _mapping_profile(
            input_fn=input_fn,
            output=output,
            class_id=class_id,
        )
        specs.append(
            CalculationBindingSpec(
                publication_id=publication_id,
                cache_key=cache_key,
                item_id=item_id,
                mapping_profile=mapping,
            )
        )

    root = deps.workspace_resolver()
    preview = actions.preview_builder(
        root,
        class_id,
        grade_item_id,
        student_id,
        standard_id,
        target_scale,
        tuple(specs),
        policy_reference,
        purpose_id,
        scope,
    )
    return root, preview


def _show_calculation_preview(
    value: BoundedCalculationPreview,
    *,
    output: TextIO,
) -> None:
    calculation = value.calculation
    outcome = calculation.outcome
    print_menu_header(output, "Grade Item Proficiency Preview")
    write_lines(
        output,
        f"Grade Item: {value.grade_item_id}",
        f"Student: {value.student_id}",
        f"Standard: {value.standard_id}",
        f"Policy: {calculation.policy_title}",
        f"Strategy: {_humanize(calculation.strategy)}",
        f"Status: {_humanize(outcome.status)}",
        (
            "Proficiency level: "
            f"{outcome.proficiency_level_id or 'not calculated'}"
        ),
        (
            "Evidence: "
            f"{outcome.performance_observation_count} performance, "
            f"{outcome.native_state_count} native-state, "
            f"{outcome.excluded_count} excluded"
        ),
        f"Explicit bindings: {value.binding_count}",
        (
            "Current result revision: none"
            if calculation.current_result_revision is None
            else (
                "Current result revision: "
                f"{calculation.current_result_revision}"
            )
        ),
        f"Next immutable result revision: {calculation.next_result_revision}",
        "",
        "This is a read-only calculation preview.",
        "No result revision or current selection has changed.",
    )


def _preview_grade_item_calculation(
    *,
    deps: ProficiencyMenuDependencies,
    actions: GradeItemProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Preview Grade Item Proficiency")
    try:
        loaded = _calculation_request(
            deps=deps,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        _root, preview = loaded
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected proficiency evidence is unavailable in this process.",
            "No calculation was performed.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        CalculationPreviewAssemblyError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Grade Item proficiency preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    _show_calculation_preview(preview, output=output)
    write_lines(
        output,
        "",
        f"Inputs sha256: {preview.calculation.inputs_sha256}",
        (
            "Calculation fingerprint: "
            f"{preview.calculation.calculation_fingerprint}"
        ),
    )
    pause_for_user(input_fn)


def _write_grade_item_result(
    *,
    deps: ProficiencyMenuDependencies,
    actions: GradeItemProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Write Grade Item Proficiency Result")
    try:
        loaded = _calculation_request(
            deps=deps,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, reviewed = loaded
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        preview = actions.persistence_previewer(
            root,
            reviewed,
            actor_id,
            actions.clock(),
        )
    except DiagnosticsAuthorizationProviderRequiredError:
        write_lines(
            output,
            "",
            "Protected proficiency evidence is unavailable in this process.",
            "No result revision was written.",
            "A deployment-provided authorization capability is required.",
        )
        pause_for_user(input_fn)
        return
    except (
        WorkspaceRootError,
        DiagnosticsError,
        ProjectionCacheError,
        CalculationPreviewAssemblyError,
        CalculationResultPersistenceError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Result-write preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Proficiency Result Before Write")
    _show_calculation_preview(reviewed, output=output)
    write_lines(
        output,
        "",
        f"Candidate result revision: {preview.candidate_revision}",
        f"Candidate status: {_humanize(preview.candidate_status)}",
        (
            "Candidate proficiency level: "
            f"{preview.candidate_proficiency_level_id or 'not calculated'}"
        ),
        (
            "Candidate calculation fingerprint: "
            f"{preview.candidate_calculation_fingerprint}"
        ),
        (
            "Current selected result revision: none"
            if preview.selected_revision_before is None
            else (
                "Current selected result revision: "
                f"{preview.selected_revision_before}"
            )
        ),
        "",
        "Writing this immutable result will NOT select it as current.",
        "Type WRITE to create this exact result revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No proficiency result revision was written.")
        pause_for_user(input_fn)
        return

    try:
        result = actions.persistence_committer(root, preview)
    except CalculationResultPersistenceError as error:
        write_lines(
            output,
            "",
            "The reviewed proficiency result could not be written safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Proficiency result revision: {result.write_result.disposition}.",
        f"Written revision: {result.written_revision}.",
        f"Written status: {_humanize(result.written_status)}.",
        f"Result sha256: {result.written_result_sha256}",
        "Current result selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_grade_item_result(
    *,
    deps: ProficiencyMenuDependencies,
    actions: GradeItemProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Grade Item Proficiency Result")
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        revision = _positive_int(
            read_choice(input_fn, "Result revision to select: "),
            "result revision",
        )
        root = deps.workspace_resolver()
        preview = actions.selection_previewer(
            root,
            class_id,
            grade_item_id,
            student_id,
            standard_id,
            revision,
        )
    except (
        WorkspaceRootError,
        CalculationResultSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Result selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Proficiency Result Selection")
    latest_text = "yes" if preview.target_is_latest else "no"
    write_lines(
        output,
        f"Grade Item: {preview.grade_item_id}",
        f"Student: {preview.student_id}",
        f"Standard: {preview.standard_id}",
        f"Target result revision: {preview.target_revision}",
        f"Target status: {_humanize(preview.target_status)}",
        (
            "Target proficiency level: "
            f"{preview.target_proficiency_level_id or 'not calculated'}"
        ),
        f"Target sha256: {preview.target_result_sha256}",
        (
            "Current result revision: none"
            if preview.expected_current_result_revision is None
            else (
                "Current result revision: "
                f"{preview.expected_current_result_revision}"
            )
        ),
        f"Target is latest authored result: {latest_text}",
        "",
        "Type SELECT to make this exact historical result current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current proficiency result was not changed.")
        pause_for_user(input_fn)
        return

    try:
        result = actions.selection_committer(root, preview)
    except CalculationResultSelectionError as error:
        write_lines(
            output,
            "",
            "The reviewed result could not be selected safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Result selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
        f"Selected status: {_humanize(result.selected_status)}.",
    )
    pause_for_user(input_fn)


def _yes_no(
    value: str,
    label: str,
) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"y", "yes"}:
        return True
    if normalized in {"n", "no"}:
        return False
    raise ValueError(f"{label} must be yes or no")


def _academic_period_calculation_request(
    *,
    deps: ProficiencyMenuDependencies,
    actions: AcademicPeriodProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
) -> tuple[Path, BoundedAcademicPeriodCalculationPreview] | None:
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return None
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return None
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    calendar_revision = _positive_int(
        read_choice(input_fn, "Academic Period calendar revision: "),
        "calendar revision",
    )
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")

    policy_id = read_choice(input_fn, "Academic Period proficiency policy ID: ")
    policy_revision = _positive_int(
        read_choice(input_fn, "Policy revision: "),
        "policy revision",
    )
    policy_sha256 = read_choice(input_fn, "Policy sha256: ")

    target = AcademicPeriodProficiencyTarget(
        period=AcademicPeriodRef(
            school_year=school_year,
            period_id=period_id,
        ),
        calendar_revision=calendar_revision,
    )
    policy_reference = AcademicPeriodProficiencyAggregationPolicyReference(
        class_id=class_id,
        policy_id=policy_id,
        policy_revision=policy_revision,
        policy_sha256=policy_sha256,
    )

    candidate_count = _nonnegative_int(
        read_choice(input_fn, "Number of explicit Grade Item candidates: "),
        "candidate count",
    )
    candidates: list[AcademicPeriodCalculationCandidateSpec] = []
    for index in range(1, candidate_count + 1):
        write_lines(output, "", f"Grade Item candidate {index} of {candidate_count}")
        grade_item_id = read_choice(input_fn, "Grade Item ID: ")
        grade_item_revision = _positive_int(
            read_choice(input_fn, "Grade Item revision: "),
            "Grade Item revision",
        )
        grade_item_sha256 = read_choice(input_fn, "Grade Item revision sha256: ")

        membership_count = _nonnegative_int(
            read_choice(input_fn, "Number of exact membership bindings: "),
            "membership count",
        )
        memberships: list[AcademicPeriodMembershipSpec] = []
        for membership_index in range(1, membership_count + 1):
            write_lines(
                output,
                "",
                (
                    "Membership binding "
                    f"{membership_index} of {membership_count}"
                ),
            )
            module_id = read_choice(input_fn, "Work module ID: ")
            work_id = read_choice(input_fn, "Work ID: ")
            membership_revision = _positive_int(
                read_choice(input_fn, "Membership revision: "),
                "membership revision",
            )
            membership_sha256 = read_choice(
                input_fn,
                "Membership revision sha256: ",
            )
            memberships.append(
                AcademicPeriodMembershipSpec(
                    work=ModuleWorkRef(
                        module_id=module_id,
                        class_id=class_id,
                        work_id=work_id,
                    ),
                    membership_revision=membership_revision,
                    membership_sha256=membership_sha256,
                )
            )

        has_result = _yes_no(
            read_choice(
                input_fn,
                "Bind an exact Grade Item proficiency result? (yes/no): ",
            ),
            "Grade Item result choice",
        )
        result_revision: int | None = None
        result_sha256: str | None = None
        if has_result:
            result_revision = _positive_int(
                read_choice(input_fn, "Grade Item proficiency result revision: "),
                "Grade Item proficiency result revision",
            )
            result_sha256 = read_choice(
                input_fn,
                "Grade Item proficiency result sha256: ",
            )

        candidates.append(
            AcademicPeriodCalculationCandidateSpec(
                grade_item_id=grade_item_id,
                grade_item_revision=grade_item_revision,
                grade_item_revision_sha256=grade_item_sha256,
                memberships=tuple(memberships),
                result_revision=result_revision,
                result_sha256=result_sha256,
            )
        )

    root = deps.workspace_resolver()
    preview = actions.preview_builder(
        root,
        target,
        student_id,
        standard_id,
        tuple(candidates),
        policy_reference,
    )
    return root, preview


def _show_academic_period_calculation_preview(
    value: BoundedAcademicPeriodCalculationPreview,
    *,
    output: TextIO,
) -> None:
    calculation = value.calculation
    outcome = calculation.outcome
    print_menu_header(output, "Academic Period Proficiency Preview")
    write_lines(
        output,
        f"Academic Period: {calculation.target_period_title}",
        f"Student: {calculation.student_id}",
        f"Standard: {calculation.standard_id}",
        f"Policy: {calculation.policy_title}",
        f"Strategy: {_humanize(calculation.strategy)}",
        f"Scale: {value.inputs.target_scale.scale_id}",
        f"Status: {_humanize(outcome.status)}",
        (
            "Proficiency level: "
            f"{outcome.proficiency_level_id or 'not calculated'}"
        ),
        (
            "Grade Items: "
            f"{outcome.calculated_result_count} calculated, "
            f"{outcome.insufficient_result_count} insufficient, "
            f"{outcome.missing_result_count} missing, "
            f"{outcome.period_scope_mismatch_count} outside period scope"
        ),
        f"Explicit candidates: {value.candidate_count}",
        (
            "Current result revision: none"
            if calculation.current_result_revision is None
            else (
                "Current result revision: "
                f"{calculation.current_result_revision}"
            )
        ),
        f"Next immutable result revision: {calculation.next_result_revision}",
        "",
        "This is a read-only Academic Period calculation preview.",
        "No result revision or current selection has changed.",
    )


def _preview_academic_period_calculation(
    *,
    deps: ProficiencyMenuDependencies,
    actions: AcademicPeriodProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Preview Academic Period Proficiency")
    try:
        loaded = _academic_period_calculation_request(
            deps=deps,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        _root, preview = loaded
    except (
        WorkspaceRootError,
        AcademicPeriodValidationError,
        RoutingModelError,
        AcademicPeriodCalculationAssemblyError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Academic Period proficiency preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    _show_academic_period_calculation_preview(preview, output=output)
    write_lines(
        output,
        "",
        f"Inputs sha256: {preview.calculation.inputs_sha256}",
        (
            "Calculation fingerprint: "
            f"{preview.calculation.calculation_fingerprint}"
        ),
    )
    pause_for_user(input_fn)


def _write_academic_period_result(
    *,
    deps: ProficiencyMenuDependencies,
    actions: AcademicPeriodProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Write Academic Period Proficiency Result")
    try:
        loaded = _academic_period_calculation_request(
            deps=deps,
            actions=actions,
            input_fn=input_fn,
            output=output,
        )
        if loaded is None:
            return
        root, reviewed = loaded
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        preview = actions.persistence_previewer(
            root,
            reviewed,
            actor_id,
            actions.clock(),
        )
    except (
        WorkspaceRootError,
        AcademicPeriodValidationError,
        RoutingModelError,
        AcademicPeriodCalculationAssemblyError,
        AcademicPeriodResultPersistenceError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Academic Period result-write preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Academic Period Result Before Write")
    _show_academic_period_calculation_preview(reviewed, output=output)
    write_lines(
        output,
        "",
        f"Candidate result revision: {preview.candidate_revision}",
        f"Candidate status: {_humanize(preview.candidate_status)}",
        (
            "Candidate proficiency level: "
            f"{preview.candidate_proficiency_level_id or 'not calculated'}"
        ),
        (
            "Candidate calculation fingerprint: "
            f"{preview.candidate_calculation_fingerprint}"
        ),
        (
            "Current selected result revision: none"
            if preview.selected_revision_before is None
            else (
                "Current selected result revision: "
                f"{preview.selected_revision_before}"
            )
        ),
        "",
        "Writing this immutable result will NOT select it as current.",
        "Type WRITE to create this exact Academic Period result revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(
            output,
            "",
            "No Academic Period proficiency result revision was written.",
        )
        pause_for_user(input_fn)
        return

    try:
        result = actions.persistence_committer(root, preview)
    except AcademicPeriodResultPersistenceError as error:
        write_lines(
            output,
            "",
            "The reviewed Academic Period result could not be written safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Academic Period result revision: {result.write_result.disposition}.",
        f"Written revision: {result.written_revision}.",
        f"Written status: {_humanize(result.written_status)}.",
        f"Result sha256: {result.written_result_sha256}",
        "Current result selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_academic_period_result(
    *,
    deps: ProficiencyMenuDependencies,
    actions: AcademicPeriodProficiencyActionDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Academic Period Proficiency Result")
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        revision = _positive_int(
            read_choice(input_fn, "Result revision to select: "),
            "result revision",
        )
        root = deps.workspace_resolver()
        preview = actions.selection_previewer(
            root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
            revision,
        )
    except (
        WorkspaceRootError,
        AcademicPeriodResultSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Academic Period result selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Academic Period Result Selection")
    latest_text = "yes" if preview.target_is_latest else "no"
    write_lines(
        output,
        f"Academic Period: {preview.school_year} / {preview.period_id}",
        f"Student: {preview.student_id}",
        f"Standard: {preview.standard_id}",
        f"Target result revision: {preview.target_revision}",
        f"Target status: {_humanize(preview.target_status)}",
        (
            "Target proficiency level: "
            f"{preview.target_proficiency_level_id or 'not calculated'}"
        ),
        f"Target sha256: {preview.target_result_sha256}",
        (
            "Current result revision: none"
            if preview.expected_current_result_revision is None
            else (
                "Current result revision: "
                f"{preview.expected_current_result_revision}"
            )
        ),
        f"Target is latest authored result: {latest_text}",
        "",
        "Type SELECT to make this exact historical result current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(
            output,
            "",
            "Current Academic Period proficiency result was not changed.",
        )
        pause_for_user(input_fn)
        return

    try:
        result = actions.selection_committer(root, preview)
    except AcademicPeriodResultSelectionError as error:
        write_lines(
            output,
            "",
            "The reviewed Academic Period result could not be selected safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Academic Period result selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_revision}.",
        f"Selected status: {_humanize(result.selected_status)}.",
    )
    pause_for_user(input_fn)


def run_proficiency_menu(
    *,
    dependencies: ProficiencyMenuDependencies | None = None,
    action_dependencies: GradeItemProficiencyActionDependencies | None = None,
    period_action_dependencies: (
        AcademicPeriodProficiencyActionDependencies | None
    ) = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_proficiency_menu_dependencies()
    actions = (
        action_dependencies
        or default_grade_item_proficiency_action_dependencies()
    )
    period_actions = (
        period_action_dependencies
        or default_academic_period_proficiency_action_dependencies()
    )
    while True:
        clear_fn()
        print_menu_header(stream, "Review Proficiency")
        write_lines(
            stream,
            "1. Review current Grade Item proficiency",
            "2. Review current Academic Period proficiency",
            "3. Review planning-signal readiness",
            "4. Preview Grade Item proficiency calculation",
            "5. Write Grade Item proficiency result",
            "6. Select Grade Item proficiency result",
            "7. Preview Academic Period proficiency calculation",
            "8. Write Academic Period proficiency result",
            "9. Select Academic Period proficiency result",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_grade_item(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "2":
            _review_academic_period(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "3":
            _review_planning(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "4":
            _preview_grade_item_calculation(
                deps=deps,
                actions=actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "5":
            _write_grade_item_result(
                deps=deps,
                actions=actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "6":
            _select_grade_item_result(
                deps=deps,
                actions=actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "7":
            _preview_academic_period_calculation(
                deps=deps,
                actions=period_actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "8":
            _write_academic_period_result(
                deps=deps,
                actions=period_actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "9":
            _select_academic_period_result(
                deps=deps,
                actions=period_actions,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-9, B, M, or Q.")
        pause_for_user(input_fn)
