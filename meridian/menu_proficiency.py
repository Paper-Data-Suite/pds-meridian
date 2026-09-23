"""Teacher-facing read-only proficiency review for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
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


@dataclass(frozen=True, slots=True)
class ProficiencyMenuDependencies:
    workspace_resolver: WorkspaceResolver
    grade_item_loader: GradeItemLoader
    academic_period_loader: AcademicPeriodLoader
    planning_loader: PlanningLoader


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


def run_proficiency_menu(
    *,
    dependencies: ProficiencyMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_proficiency_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Review Proficiency")
        write_lines(
            stream,
            "1. Review current Grade Item proficiency",
            "2. Review current Academic Period proficiency",
            "3. Review planning-signal readiness",
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
        write_lines(stream, "", "Please choose 1-3, B, M, or Q.")
        pause_for_user(input_fn)
