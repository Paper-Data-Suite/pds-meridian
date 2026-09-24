"""Teacher-facing read-only explanation menu for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.conventional_grade_explanation import (
    ConventionalGradePreviewExplanation,
    conventional_grade_observation,
)
from meridian.current_grade_preview import (
    CurrentGradePreviewExplanation,
    explain_current_grade_preview,
)
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceError,
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
)
from meridian.grade_policy import GradeCalculationFamily
from meridian.grade_preview_comparison import compare_grade_preview_basis
from meridian.grade_preview_explanation import (
    GradePreviewComparisonError,
    GradePreviewError,
    GradePreviewObservation,
    GradePreviewTarget,
)
from meridian.hybrid_grade_explanation import (
    HybridGradePreviewExplanation,
    hybrid_grade_observation,
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
from meridian.planning_signal_derivation_explanation import (
    PlanningSignalDerivationTraceTarget,
    explain_planning_signal_derivation,
)
from meridian.planning_signal_export_explanation import (
    PlanningSignalExportTraceTarget,
    explain_planning_signal_export,
)
from meridian.planning_signal_preview_review_explanation import (
    PlanningSignalPreviewReviewTraceTarget,
    explain_planning_signal_preview_review,
)
from meridian.report_export_receipt import (
    ReportExportReceiptError,
    load_export_receipt,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonError,
    load_reporting_snapshot_for_comparison,
    reporting_snapshot_prior_grade_basis,
)
from meridian.standards_grade_explanation import (
    StandardsGradePreviewExplanation,
    standards_grade_observation,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
WorkEvidenceProvider: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    tuple[ConventionalGradeWorkEvidenceSpec, ...],
]


class ExplainEvidenceUnavailableError(RuntimeError):
    """Raised when a Grade explanation needs explicit authorized evidence."""


@dataclass(frozen=True, slots=True)
class ExplanationPresentation:
    title: str
    lines: tuple[str, ...]
    technical_lines: tuple[str, ...]


CurrentGradeExplainer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    ExplanationPresentation,
]
SnapshotComparisonExplainer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        str,
        str,
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    ExplanationPresentation,
]
GradeItemExplainer: TypeAlias = Callable[
    [Path, str, str, str, str],
    ExplanationPresentation,
]
AcademicPeriodExplainer: TypeAlias = Callable[
    [Path, str, str, str, str, str],
    ExplanationPresentation,
]
PlanningDerivationExplainer: TypeAlias = Callable[
    [Path, str, str],
    ExplanationPresentation,
]
PlanningPreviewExplainer: TypeAlias = Callable[
    [Path, str, str],
    ExplanationPresentation,
]
PlanningExportExplainer: TypeAlias = Callable[
    [Path, str, str],
    ExplanationPresentation,
]
ExportReceiptExplainer: TypeAlias = Callable[
    [Path, str, str],
    ExplanationPresentation,
]


@dataclass(frozen=True, slots=True)
class ExplainMenuDependencies:
    workspace_resolver: WorkspaceResolver
    current_grade: CurrentGradeExplainer
    snapshot_comparison: SnapshotComparisonExplainer
    grade_item_proficiency: GradeItemExplainer
    academic_period_proficiency: AcademicPeriodExplainer
    planning_derivation: PlanningDerivationExplainer
    planning_preview_review: PlanningPreviewExplainer
    planning_export: PlanningExportExplainer
    export_receipt: ExportReceiptExplainer


def _decimal(value: object | None) -> str:
    return "not numeric" if value is None else format(value, "f")


def _human(value: str) -> str:
    return value.replace("_", " ")


def _family(value: str) -> GradeCalculationFamily:
    choices: dict[str, GradeCalculationFamily] = {
        "1": "conventional",
        "2": "standards_based",
        "3": "hybrid",
    }
    try:
        return choices[value]
    except KeyError as error:
        raise ValueError("calculation family must be 1, 2, or 3") from error


def _positive_int(value: str, label: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError(f"{label} must be a positive integer")
    return result


def _work_evidence(
    provider: WorkEvidenceProvider | None,
    root: Path,
    class_id: str,
    student_id: str,
    period: AcademicPeriodRef,
    calendar_revision: int,
    family: GradeCalculationFamily,
) -> tuple[ConventionalGradeWorkEvidenceSpec, ...] | None:
    if family == "standards_based":
        return None
    if provider is None:
        raise ExplainEvidenceUnavailableError(
            f"{_human(family)} Grade explanation requires an explicit "
            "authorized work-evidence provider. No protected evidence was opened."
        )
    return provider(
        root,
        class_id,
        student_id,
        period,
        calendar_revision,
        family,
    )


def _current_explanation(
    root: Path,
    class_id: str,
    student_id: str,
    period: AcademicPeriodRef,
    calendar_revision: int,
    family: GradeCalculationFamily,
    *,
    provider: WorkEvidenceProvider | None,
) -> CurrentGradePreviewExplanation:
    target = GradePreviewTarget(
        class_id=class_id,
        student_id=student_id,
        target_period=period,
        calendar_revision=calendar_revision,
        calculation_family=family,
    )
    return explain_current_grade_preview(
        root,
        target,
        work_evidence=_work_evidence(
            provider,
            root,
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
        ),
    )


def _current_grade_presentation(explanation: object) -> ExplanationPresentation:
    common = explanation.common  # type: ignore[attr-defined]
    policy = common.policy
    lines = [
        f"Student: {common.target.student_id}",
        (
            "Academic Period: "
            f"{common.target.target_period.school_year} / "
            f"{common.target.target_period.period_id}"
        ),
        f"Calculation family: {_human(common.target.calculation_family)}",
        f"Policy: {policy.title}",
        f"Base result: {_human(common.base_result_status)}",
        f"Base Grade: {_decimal(common.base_grade)}",
        f"Freshness: {_human(common.base_freshness_status)}",
        f"Effective Grade: {_decimal(common.effective_grade)}",
        f"Effective source: {_human(common.effective_source)}",
        f"Override: {_human(common.override_applicability)}",
        (
            "Rounding: "
            f"{format(policy.rounding.quantum, 'f')} "
            f"({_human(policy.rounding.mode)}, final)"
        ),
    ]
    if common.base_freshness_reasons:
        lines.append(
            "Freshness reasons: "
            + ", ".join(_human(item) for item in common.base_freshness_reasons)
        )

    if isinstance(explanation, ConventionalGradePreviewExplanation):
        actions = [item.action for item in explanation.items]
        lines.extend(
            [
                f"Grade Items considered: {len(explanation.items)}",
                f"Contributing: {actions.count('contribute')}",
                f"Excluded: {actions.count('exclude')}",
                f"Blocking: {actions.count('blocking')}",
                f"Zero by policy: {actions.count('zero')}",
            ]
        )
    elif isinstance(explanation, StandardsGradePreviewExplanation):
        actions = [item.action for item in explanation.standards]
        lines.extend(
            [
                f"Standards considered: {len(explanation.standards)}",
                f"Contributing: {actions.count('contribute')}",
                f"Excluded: {actions.count('exclude')}",
                f"Blocking: {actions.count('blocking')}",
                f"Zero by policy: {actions.count('zero')}",
            ]
        )
    elif isinstance(explanation, HybridGradePreviewExplanation):
        lines.extend(
            [
                f"Hybrid status: {_human(explanation.status)}",
                (
                    "Conventional component: "
                    f"{_human(explanation.conventional_component.source_status)}"
                ),
                (
                    "Standards component: "
                    f"{_human(explanation.standards_component.source_status)}"
                ),
            ]
        )

    policy_ref = policy.policy_reference
    activation = policy.activation_reference
    technical = (
        f"class_id: {common.target.class_id}",
        f"student_id: {common.target.student_id}",
        f"calendar_revision: {common.target.calendar_revision}",
        f"policy_id: {policy_ref.policy_id}",
        f"policy_revision: {policy_ref.policy_revision}",
        f"policy_sha256: {policy_ref.policy_sha256}",
        f"activation_revision: {activation.activation_revision}",
        f"activation_sha256: {activation.activation_sha256}",
        (
            "calculation_fingerprint: "
            f"{common.base_result.calculation_fingerprint}"
        ),
        f"inputs_sha256: {common.base_result.inputs_sha256}",
    )
    return ExplanationPresentation(
        title="Current Grade Explanation",
        lines=tuple(lines),
        technical_lines=technical,
    )


def _current_loader(
    provider: WorkEvidenceProvider | None,
) -> CurrentGradeExplainer:
    def load(
        root: Path,
        class_id: str,
        student_id: str,
        period: AcademicPeriodRef,
        calendar_revision: int,
        family: GradeCalculationFamily,
    ) -> ExplanationPresentation:
        explanation = _current_explanation(
            root,
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
            provider=provider,
        )
        return _current_grade_presentation(explanation)

    return load


def _observation(
    explanation: CurrentGradePreviewExplanation,
) -> GradePreviewObservation:
    if isinstance(explanation, ConventionalGradePreviewExplanation):
        return conventional_grade_observation(explanation)
    if isinstance(explanation, StandardsGradePreviewExplanation):
        return standards_grade_observation(explanation)
    if isinstance(explanation, HybridGradePreviewExplanation):
        return hybrid_grade_observation(explanation)
    raise GradePreviewError("Unsupported current Grade explanation family.")


def _comparison_loader(
    provider: WorkEvidenceProvider | None,
) -> SnapshotComparisonExplainer:
    def load(
        root: Path,
        class_id: str,
        snapshot_id: str,
        snapshot_sha256: str,
        student_id: str,
        period: AcademicPeriodRef,
        calendar_revision: int,
        family: GradeCalculationFamily,
    ) -> ExplanationPresentation:
        current = _current_explanation(
            root,
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
            provider=provider,
        )
        current_observation = _observation(current)
        stored = load_reporting_snapshot_for_comparison(
            root,
            ReportingSnapshotReference(
                class_id,
                snapshot_id,
                snapshot_sha256,
            ),
        )
        prior = reporting_snapshot_prior_grade_basis(
            stored.snapshot,
            current_observation.target,
        )
        comparison = compare_grade_preview_basis(current_observation, prior)
        delta = (
            "not available"
            if comparison.effective_grade_delta is None
            else format(comparison.effective_grade_delta, "f")
        )
        reasons = (
            "none"
            if not comparison.reasons
            else ", ".join(_human(item) for item in comparison.reasons)
        )
        return ExplanationPresentation(
            title="Prior / Current Grade Comparison",
            lines=(
                f"Student: {student_id}",
                f"Relationship: {_human(comparison.relationship)}",
                f"Changed: {'yes' if comparison.changed else 'no'}",
                f"Reasons: {reasons}",
                f"Effective Grade delta: {delta}",
            ),
            technical_lines=(
                f"snapshot_id: {snapshot_id}",
                f"snapshot_sha256: {snapshot_sha256}",
                f"class_id: {class_id}",
                f"calendar_revision: {calendar_revision}",
                f"calculation_family: {family}",
                (
                    "current_calculation_fingerprint: "
                    f"{current.common.base_result.calculation_fingerprint}"
                ),
            ),
        )

    return load


def _grade_item(
    root: Path,
    class_id: str,
    grade_item_id: str,
    student_id: str,
    standard_id: str,
) -> ExplanationPresentation:
    value = explain_grade_item_proficiency(
        root,
        GradeItemProficiencyTraceTarget(
            class_id=class_id,
            grade_item_id=grade_item_id,
            student_id=student_id,
            standard_id=standard_id,
            selection="current",
        ),
    )
    level = next(
        (
            item.label
            for item in value.scale.levels
            if item.level_id == value.calculation.proficiency_level_id
        ),
        None,
    )
    return ExplanationPresentation(
        title="Grade Item Proficiency Explanation",
        lines=(
            f"Grade Item: {value.grade_item.title}",
            f"Student: {value.student_id}",
            f"Standard: {value.standard_id}",
            f"Result: {_human(value.calculation.status)}",
            f"Proficiency: {level or 'not calculated'}",
            f"Policy: {value.policy.title}",
            (
                "Evidence: "
                f"{value.calculation.performance_observation_count} performance, "
                f"{value.calculation.native_state_count} native state, "
                f"{value.calculation.excluded_count} excluded"
            ),
            f"Selection state: {_human(value.selection_state)}",
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"grade_item_id: {value.grade_item_id}",
            f"result_revision: {value.result_revision}",
            f"result_sha256: {value.result_sha256}",
            f"inputs_sha256: {value.inputs_sha256}",
            f"calculation_fingerprint: {value.calculation_fingerprint}",
            f"policy_id: {value.policy.policy_id}",
            f"policy_sha256: {value.policy.policy_sha256}",
            f"scale_id: {value.scale.scale_id}",
            f"scale_sha256: {value.scale.scale_sha256}",
        ),
    )


def _academic_period(
    root: Path,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> ExplanationPresentation:
    value = explain_academic_period_proficiency(
        root,
        AcademicPeriodProficiencyTraceTarget(
            class_id=class_id,
            school_year=school_year,
            period_id=period_id,
            student_id=student_id,
            standard_id=standard_id,
            selection="current",
        ),
    )
    level = next(
        (
            item.label
            for item in value.scale.levels
            if item.level_id == value.calculation.proficiency_level_id
        ),
        None,
    )
    calculation = value.calculation
    return ExplanationPresentation(
        title="Academic Period Proficiency Explanation",
        lines=(
            f"Academic Period: {value.target_period.label}",
            f"Student: {value.student_id}",
            f"Standard: {value.standard_id}",
            f"Result: {_human(calculation.status)}",
            f"Proficiency: {level or 'not calculated'}",
            f"Policy: {value.policy.title}",
            (
                "Grade Items: "
                f"{calculation.calculated_result_count} calculated, "
                f"{calculation.insufficient_result_count} insufficient, "
                f"{calculation.missing_result_count} missing, "
                f"{calculation.period_scope_mismatch_count} outside period scope"
            ),
            f"Selection state: {_human(value.selection_state)}",
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"result_revision: {value.result_revision}",
            f"result_sha256: {value.result_sha256}",
            f"inputs_sha256: {value.inputs_sha256}",
            f"calculation_fingerprint: {value.calculation_fingerprint}",
            f"policy_id: {value.policy.policy_id}",
            f"policy_sha256: {value.policy.policy_sha256}",
            f"scale_id: {value.scale.scale_id}",
            f"scale_sha256: {value.scale.scale_sha256}",
        ),
    )


def _planning_derivation(
    root: Path,
    class_id: str,
    derivation_id: str,
) -> ExplanationPresentation:
    value = explain_planning_signal_derivation(
        root,
        PlanningSignalDerivationTraceTarget(
            class_id=class_id,
            derivation_id=derivation_id,
        ),
    )
    contributing = sum(
        item.disposition == "contributing" for item in value.students
    )
    return ExplanationPresentation(
        title="Planning Derivation Explanation",
        lines=(
            f"Policy: {value.policy.title}",
            (
                "Academic Period: "
                f"{value.policy.target_period.label}"
            ),
            f"Standard: {value.policy.standard_id}",
            f"Dimension: {value.dimension_id}",
            f"Bands: {value.band_count}",
            f"Roster students: {len(value.students)}",
            f"Contributing students: {contributing}",
            f"Noncontributing students: {len(value.students) - contributing}",
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"derivation_id: {value.derivation_id}",
            f"derivation_sha256: {value.derivation_sha256}",
            f"algorithm_version: {value.algorithm_version}",
            f"calculation_fingerprint: {value.calculation_fingerprint}",
            f"policy_id: {value.policy.policy_id}",
            f"policy_revision: {value.policy.policy_revision}",
            f"policy_sha256: {value.policy.policy_sha256}",
        ),
    )


def _planning_preview(
    root: Path,
    class_id: str,
    preview_id: str,
) -> ExplanationPresentation:
    value = explain_planning_signal_preview_review(
        root,
        PlanningSignalPreviewReviewTraceTarget(
            class_id=class_id,
            preview_id=preview_id,
            review_selection="selected",
        ),
    )
    review_text = (
        "none selected"
        if value.review is None
        else _human(value.review.decision)
    )
    coverage = value.coverage
    return ExplanationPresentation(
        title="Planning Preview / Review Explanation",
        lines=(
            f"Policy: {value.policy_title}",
            f"Academic Period: {value.school_year} / {value.period_id}",
            f"Standard: {value.standard_id}",
            f"Dimension: {value.dimension_id}",
            f"Path state: {_human(value.path_state)}",
            f"Live currentness: {_human(value.live_currentness.state)}",
            f"Selected review: {review_text}",
            (
                "Coverage: "
                f"{coverage.contributing_student_count} contributing, "
                f"{coverage.noncontributing_student_count} noncontributing"
            ),
            (
                "Export eligible: "
                f"{'yes' if value.export_eligibility.eligible else 'no'}"
            ),
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"preview_id: {value.preview_id}",
            f"preview_sha256: {value.preview_sha256}",
            (
                "derivation_id: "
                f"{value.derivation_reference.derivation_id}"
            ),
            (
                "derivation_sha256: "
                f"{value.derivation_reference.derivation_sha256}"
            ),
            f"policy_id: {value.policy_id}",
            f"policy_revision: {value.policy_revision}",
            f"policy_sha256: {value.policy_sha256}",
            (
                "live_currentness_reasons: "
                + (
                    ", ".join(value.live_currentness.reason_codes)
                    if value.live_currentness.reason_codes
                    else "none"
                )
            ),
        ),
    )


def _planning_export(
    root: Path,
    class_id: str,
    signal_set_id: str,
) -> ExplanationPresentation:
    value = explain_planning_signal_export(
        root,
        PlanningSignalExportTraceTarget(
            class_id=class_id,
            signal_set_id=signal_set_id,
        ),
    )
    exported = sum(item.exported for item in value.students)
    return ExplanationPresentation(
        title="Planning Export Explanation",
        lines=(
            f"Signal set: {value.signal_set_id}",
            f"Dimension: {value.dimension_id}",
            f"Bands: {value.band_count}",
            f"Students exported: {exported}",
            f"Students omitted: {len(value.students) - exported}",
            f"Review decision: {_human(value.review_decision)}",
            (
                "Preview currentness: "
                f"{_human(value.preview_currentness_state)}"
            ),
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"core_contract: {value.core_contract}",
            f"core_signal_digest: {value.core_signal_digest}",
            f"receipt_sha256: {value.receipt_sha256}",
            f"derivation_id: {value.derivation_id}",
            f"derivation_sha256: {value.derivation_sha256}",
            f"preview_id: {value.preview_id}",
            f"preview_sha256: {value.preview_sha256}",
            f"review_revision: {value.review_revision}",
            f"review_sha256: {value.review_sha256}",
        ),
    )


def _export_receipt(
    root: Path,
    class_id: str,
    export_id: str,
) -> ExplanationPresentation:
    stored = load_export_receipt(root, class_id, export_id)
    value = stored.receipt
    return ExplanationPresentation(
        title="ExportReceipt Provenance",
        lines=(
            f"Export: {value.export_id}",
            f"Snapshot: {value.snapshot_reference.snapshot_id}",
            (
                "Export Profile: "
                f"{value.profile_reference.profile_id} "
                f"r{value.profile_reference.profile_revision}"
            ),
            f"Rows: {value.row_count}",
            f"Destination kind: {_human(value.destination.kind)}",
            (
                "Destination file: "
                f"{value.destination.basename or 'none'}"
            ),
            f"Teacher: {value.actor.actor_id}",
            (
                "Scope: local Meridian export provenance; "
                "external acceptance is not claimed."
            ),
        ),
        technical_lines=(
            f"class_id: {value.class_id}",
            f"receipt_sha256: {stored.receipt_sha256}",
            f"preview_sha256: {value.preview_sha256}",
            f"payload_sha256: {value.payload_sha256}",
            f"payload_byte_length: {value.payload_byte_length}",
            f"snapshot_sha256: {value.snapshot_reference.snapshot_sha256}",
            f"profile_sha256: {value.profile_reference.profile_sha256}",
        ),
    )


def default_explain_menu_dependencies(
    *,
    work_evidence_provider: WorkEvidenceProvider | None = None,
) -> ExplainMenuDependencies:
    return ExplainMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        current_grade=_current_loader(work_evidence_provider),
        snapshot_comparison=_comparison_loader(work_evidence_provider),
        grade_item_proficiency=_grade_item,
        academic_period_proficiency=_academic_period,
        planning_derivation=_planning_derivation,
        planning_preview_review=_planning_preview,
        planning_export=_planning_export,
        export_receipt=_export_receipt,
    )


def _show(
    value: ExplanationPresentation,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    while True:
        clear_fn()
        print_menu_header(output, value.title)
        write_lines(output, *value.lines)
        write_lines(
            output,
            "",
            "Read-only explanation; no Meridian state was changed.",
            "T. Technical details / provenance",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            print_menu_header(
                output,
                f"{value.title} — Technical details / provenance",
            )
            write_lines(output, *value.technical_lines, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _grade_scope(
    input_fn: InputFunction,
) -> tuple[str, str, AcademicPeriodRef, int, GradeCalculationFamily]:
    class_id = read_choice(input_fn, "Class ID: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    calendar_revision = _positive_int(
        read_choice(input_fn, "Calendar revision: "),
        "calendar revision",
    )
    print("1. Conventional")
    print("2. Standards based")
    print("3. Hybrid")
    family = _family(read_choice(input_fn, "Calculation family: "))
    return (
        class_id,
        school_year,
        AcademicPeriodRef(school_year, period_id),
        calendar_revision,
        family,
    )


def _run_current(
    deps: ExplainMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Explain Current Grade")
    try:
        class_id, _year, period, revision, family = _grade_scope(input_fn)
        student_id = read_choice(input_fn, "Student ID: ")
        value = deps.current_grade(
            deps.workspace_resolver(),
            class_id,
            student_id,
            period,
            revision,
            family,
        )
    except (
        WorkspaceRootError,
        ExplainEvidenceUnavailableError,
        GradePreviewError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Explanation unavailable: {error}")
        pause_for_user(input_fn)
        return
    _show(value, input_fn=input_fn, output=output, clear_fn=clear_fn)


def _run_comparison(
    deps: ExplainMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Compare Current Grade to ReportingSnapshot")
    try:
        class_id, _year, period, revision, family = _grade_scope(input_fn)
        student_id = read_choice(input_fn, "Student ID: ")
        snapshot_id = read_choice(input_fn, "ReportingSnapshot ID: ")
        snapshot_sha256 = read_choice(input_fn, "ReportingSnapshot sha256: ")
        value = deps.snapshot_comparison(
            deps.workspace_resolver(),
            class_id,
            snapshot_id,
            snapshot_sha256,
            student_id,
            period,
            revision,
            family,
        )
    except (
        WorkspaceRootError,
        ExplainEvidenceUnavailableError,
        GradePreviewError,
        GradePreviewComparisonError,
        ReportingSnapshotComparisonError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Comparison unavailable: {error}")
        pause_for_user(input_fn)
        return
    _show(value, input_fn=input_fn, output=output, clear_fn=clear_fn)


def _run_grade_item(
    deps: ExplainMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Explain Grade Item Proficiency")
    class_id = read_choice(input_fn, "Class ID: ")
    grade_item_id = read_choice(input_fn, "Grade Item ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        value = deps.grade_item_proficiency(
            deps.workspace_resolver(),
            class_id,
            grade_item_id,
            student_id,
            standard_id,
        )
    except (WorkspaceRootError, ExplanationTraceError, ValueError) as error:
        write_lines(output, "", f"Explanation unavailable: {error}")
        pause_for_user(input_fn)
        return
    _show(value, input_fn=input_fn, output=output, clear_fn=clear_fn)


def _run_academic_period(
    deps: ExplainMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Explain Academic Period Proficiency")
    class_id = read_choice(input_fn, "Class ID: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    student_id = read_choice(input_fn, "Student ID: ")
    standard_id = read_choice(input_fn, "Standard ID: ")
    try:
        value = deps.academic_period_proficiency(
            deps.workspace_resolver(),
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
    except (WorkspaceRootError, ExplanationTraceError, ValueError) as error:
        write_lines(output, "", f"Explanation unavailable: {error}")
        pause_for_user(input_fn)
        return
    _show(value, input_fn=input_fn, output=output, clear_fn=clear_fn)


def _run_two_id(
    deps: ExplainMenuDependencies,
    loader_name: str,
    title: str,
    id_label: str,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, title)
    class_id = read_choice(input_fn, "Class ID: ")
    value_id = read_choice(input_fn, f"{id_label}: ")
    loader = getattr(deps, loader_name)
    try:
        value = loader(deps.workspace_resolver(), class_id, value_id)
    except (
        WorkspaceRootError,
        ExplanationTraceError,
        ReportExportReceiptError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Explanation unavailable: {error}")
        pause_for_user(input_fn)
        return
    _show(value, input_fn=input_fn, output=output, clear_fn=clear_fn)


def run_explain_menu(
    *,
    dependencies: ExplainMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_explain_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Explain")
        write_lines(
            stream,
            "1. Current Grade",
            "2. Prior / current Grade comparison",
            "3. Grade Item proficiency",
            "4. Academic Period proficiency",
            "5. Planning derivation",
            "6. Planning preview / review",
            "7. Planning export",
            "8. ExportReceipt provenance",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _run_current(deps, input_fn, stream, clear_fn)
            continue
        if choice == "2":
            _run_comparison(deps, input_fn, stream, clear_fn)
            continue
        if choice == "3":
            _run_grade_item(deps, input_fn, stream, clear_fn)
            continue
        if choice == "4":
            _run_academic_period(deps, input_fn, stream, clear_fn)
            continue
        routes = {
            "5": (
                "planning_derivation",
                "Explain Planning Derivation",
                "Derivation ID",
            ),
            "6": (
                "planning_preview_review",
                "Explain Planning Preview / Review",
                "Preview ID",
            ),
            "7": (
                "planning_export",
                "Explain Planning Export",
                "Signal Set ID",
            ),
            "8": (
                "export_receipt",
                "Explain ExportReceipt",
                "Export ID",
            ),
        }
        route = routes.get(choice)
        if route is None:
            write_lines(stream, "", "Please choose 1-8, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        _run_two_id(
            deps,
            route[0],
            route[1],
            route[2],
            input_fn,
            stream,
            clear_fn,
        )
