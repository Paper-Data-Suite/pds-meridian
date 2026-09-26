"""Teacher-facing read-only Grade preview menu for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.current_grade_preview import explain_current_grade_preview
from meridian.grade_policy import GradeCalculationFamily
from meridian.grade_preview_explanation import (
    GradePreviewError,
    GradePreviewExplanation,
    GradePreviewTarget,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
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


class GradeMenuEvidenceUnavailableError(RuntimeError):
    """Raised when a Grade family needs explicit authorized work evidence."""


@dataclass(frozen=True, slots=True)
class GradePreviewPresentation:
    class_id: str
    student_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    family: GradeCalculationFamily
    policy_title: str
    base_status: str
    base_grade: str | None
    freshness_status: str
    freshness_reasons: tuple[str, ...]
    override_applicability: str
    effective_grade: str | None
    effective_source: str
    calculation_fingerprint: str
    inputs_sha256: str
    policy_id: str
    policy_revision: int
    policy_sha256: str
    activation_revision: int
    activation_sha256: str
    override_revision: int | None
    override_sha256: str | None


@dataclass(frozen=True, slots=True)
class GradeReportRowPresentation:
    student_id: str
    status: str
    unavailable_reason: str | None
    base_status: str | None
    freshness_status: str | None
    effective_grade: str | None
    effective_source: str | None


@dataclass(frozen=True, slots=True)
class GradeReportPresentation:
    class_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    family: GradeCalculationFamily
    requested_count: int
    available_count: int
    unavailable_count: int
    stale_count: int
    override_count: int
    rows: tuple[GradeReportRowPresentation, ...]


CurrentGradeLoader: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    GradePreviewPresentation,
]
GradeReportLoader: TypeAlias = Callable[
    [
        Path,
        str,
        tuple[str, ...],
        AcademicPeriodRef,
        int,
        GradeCalculationFamily,
    ],
    GradeReportPresentation,
]


@dataclass(frozen=True, slots=True)
class GradeMenuDependencies:
    workspace_resolver: WorkspaceResolver
    current_grade_loader: CurrentGradeLoader
    report_loader: GradeReportLoader


def _decimal_text(value: object | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _presentation(common: GradePreviewExplanation) -> GradePreviewPresentation:
    target = common.target
    policy = common.policy
    activation = policy.activation_reference
    policy_ref = policy.policy_reference
    override = common.selected_override
    return GradePreviewPresentation(
        class_id=target.class_id,
        student_id=target.student_id,
        school_year=target.target_period.school_year,
        period_id=target.target_period.period_id,
        calendar_revision=target.calendar_revision,
        family=target.calculation_family,
        policy_title=policy.title,
        base_status=common.base_result_status,
        base_grade=_decimal_text(common.base_grade),
        freshness_status=common.base_freshness_status,
        freshness_reasons=common.base_freshness_reasons,
        override_applicability=common.override_applicability,
        effective_grade=_decimal_text(common.effective_grade),
        effective_source=common.effective_source,
        calculation_fingerprint=common.base_result.calculation_fingerprint,
        inputs_sha256=common.base_result.inputs_sha256,
        policy_id=policy_ref.policy_id,
        policy_revision=policy_ref.policy_revision,
        policy_sha256=policy_ref.policy_sha256,
        activation_revision=activation.activation_revision,
        activation_sha256=activation.activation_sha256,
        override_revision=(
            override.reference.override_revision
            if override is not None
            else None
        ),
        override_sha256=(
            override.reference.override_sha256
            if override is not None
            else None
        ),
    )


def _evidence(
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
        raise GradeMenuEvidenceUnavailableError(
            f"{family.replace('_', ' ')} Grade preview requires an explicit "
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


def _load_current(
    root: Path,
    class_id: str,
    student_id: str,
    period: AcademicPeriodRef,
    calendar_revision: int,
    family: GradeCalculationFamily,
    *,
    provider: WorkEvidenceProvider | None,
) -> GradePreviewPresentation:
    target = GradePreviewTarget(
        class_id=class_id,
        student_id=student_id,
        target_period=period,
        calendar_revision=calendar_revision,
        calculation_family=family,
    )
    work_evidence = _evidence(
        provider,
        root,
        class_id,
        student_id,
        period,
        calendar_revision,
        family,
    )
    explanation = explain_current_grade_preview(
        root,
        target,
        work_evidence=work_evidence,
    )
    return _presentation(explanation.common)


def _load_report(
    root: Path,
    class_id: str,
    student_ids: tuple[str, ...],
    period: AcademicPeriodRef,
    calendar_revision: int,
    family: GradeCalculationFamily,
    *,
    provider: WorkEvidenceProvider | None,
) -> GradeReportPresentation:
    requests: list[GradeReportPreviewRequest] = []
    for student_id in student_ids:
        target = GradePreviewTarget(
            class_id=class_id,
            student_id=student_id,
            target_period=period,
            calendar_revision=calendar_revision,
            calculation_family=family,
        )
        work_evidence = _evidence(
            provider,
            root,
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
        )
        requests.append(
            GradeReportPreviewRequest(
                target=target,
                work_evidence=work_evidence,
            )
        )
    preview = explain_grade_report_preview(root, tuple(requests))
    summary = preview.summary
    rows: list[GradeReportRowPresentation] = []
    for row in preview.rows:
        common = row.explanation.common if row.explanation is not None else None
        rows.append(
            GradeReportRowPresentation(
                student_id=row.target.student_id,
                status=row.status,
                unavailable_reason=row.unavailable_reason,
                base_status=(
                    common.base_result_status if common is not None else None
                ),
                freshness_status=(
                    common.base_freshness_status if common is not None else None
                ),
                effective_grade=(
                    _decimal_text(common.effective_grade)
                    if common is not None
                    else None
                ),
                effective_source=(
                    common.effective_source if common is not None else None
                ),
            )
        )
    return GradeReportPresentation(
        class_id=class_id,
        school_year=period.school_year,
        period_id=period.period_id,
        calendar_revision=calendar_revision,
        family=family,
        requested_count=summary.requested_count,
        available_count=summary.available_count,
        unavailable_count=summary.unavailable_count,
        stale_count=summary.stale_count,
        override_count=summary.effective_override_count,
        rows=tuple(rows),
    )


def default_grade_menu_dependencies(
    *,
    work_evidence_provider: WorkEvidenceProvider | None = None,
) -> GradeMenuDependencies:
    def current(
        root: Path,
        class_id: str,
        student_id: str,
        period: AcademicPeriodRef,
        calendar_revision: int,
        family: GradeCalculationFamily,
    ) -> GradePreviewPresentation:
        return _load_current(
            root,
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
            provider=work_evidence_provider,
        )

    def report(
        root: Path,
        class_id: str,
        student_ids: tuple[str, ...],
        period: AcademicPeriodRef,
        calendar_revision: int,
        family: GradeCalculationFamily,
    ) -> GradeReportPresentation:
        return _load_report(
            root,
            class_id,
            student_ids,
            period,
            calendar_revision,
            family,
            provider=work_evidence_provider,
        )

    return GradeMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        current_grade_loader=current,
        report_loader=report,
    )


def _family(value: str) -> GradeCalculationFamily | None:
    choices: dict[str, GradeCalculationFamily] = {
        "1": "conventional",
        "2": "standards_based",
        "3": "hybrid",
    }
    return choices.get(value)


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError("calendar revision must be a positive integer")
    return result


def _student_ids(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(",") if part.strip())
    if not values:
        raise ValueError("at least one student ID is required")
    if len(set(values)) != len(values):
        raise ValueError("student IDs must not contain duplicates")
    return values


def _grade_text(value: str | None) -> str:
    return value if value is not None else "not numeric"


def _render_current(output: TextIO, value: GradePreviewPresentation) -> None:
    print_menu_header(output, "Current Grade Preview")
    write_lines(
        output,
        f"Student: {value.student_id}",
        f"Academic Period: {value.school_year} / {value.period_id}",
        f"Calculation family: {value.family.replace('_', ' ')}",
        f"Policy: {value.policy_title}",
        f"Base result: {value.base_status.replace('_', ' ')}",
        f"Base Grade: {_grade_text(value.base_grade)}",
        f"Freshness: {value.freshness_status}",
        f"Effective Grade: {_grade_text(value.effective_grade)}",
        f"Effective source: {value.effective_source}",
        f"Override: {value.override_applicability.replace('_', ' ')}",
    )
    if value.freshness_reasons:
        write_lines(output, "", "Freshness reasons:")
        for reason in value.freshness_reasons:
            print(f"  - {reason.replace('_', ' ')}", file=output)


def _render_current_technical(
    output: TextIO,
    value: GradePreviewPresentation,
) -> None:
    print_menu_header(
        output,
        "Current Grade Preview — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.class_id}",
        f"student_id: {value.student_id}",
        f"calendar_revision: {value.calendar_revision}",
        f"policy_id: {value.policy_id}",
        f"policy_revision: {value.policy_revision}",
        f"policy_sha256: {value.policy_sha256}",
        f"activation_revision: {value.activation_revision}",
        f"activation_sha256: {value.activation_sha256}",
        f"calculation_fingerprint: {value.calculation_fingerprint}",
        f"inputs_sha256: {value.inputs_sha256}",
        f"override_revision: {value.override_revision or 'none'}",
        f"override_sha256: {value.override_sha256 or 'none'}",
    )


def _render_report(output: TextIO, value: GradeReportPresentation) -> None:
    print_menu_header(output, "Grade Report Preview")
    write_lines(
        output,
        f"Academic Period: {value.school_year} / {value.period_id}",
        f"Calculation family: {value.family.replace('_', ' ')}",
        (
            "Rows: "
            f"{value.requested_count} requested, "
            f"{value.available_count} available, "
            f"{value.unavailable_count} unavailable"
        ),
        f"Stale selected Grades: {value.stale_count}",
        f"Effective Grades from overrides: {value.override_count}",
        "",
    )
    for index, row in enumerate(value.rows[:10], start=1):
        if row.status == "unavailable":
            detail = (row.unavailable_reason or "unavailable").replace("_", " ")
        else:
            detail = (
                f"{_grade_text(row.effective_grade)} "
                f"({row.effective_source or 'none'})"
            )
            if row.freshness_status == "stale":
                detail += " — stale"
        print(f"{index}. {row.student_id}: {detail}", file=output)
    remaining = len(value.rows) - 10
    if remaining > 0:
        print(f"... {remaining} more rows not shown on this screen.", file=output)


def _render_report_technical(
    output: TextIO,
    value: GradeReportPresentation,
) -> None:
    print_menu_header(
        output,
        "Grade Report Preview — Technical details / provenance",
    )
    write_lines(
        output,
        f"class_id: {value.class_id}",
        f"school_year: {value.school_year}",
        f"period_id: {value.period_id}",
        f"calendar_revision: {value.calendar_revision}",
        f"calculation_family: {value.family}",
    )
    for row in value.rows:
        print(
            f"  {row.student_id}: status={row.status}; "
            f"base={row.base_status or 'none'}; "
            f"freshness={row.freshness_status or 'none'}",
            file=output,
        )


def _period_scope(
    input_fn: InputFunction,
) -> tuple[str, str, AcademicPeriodRef, int, GradeCalculationFamily]:
    class_id = read_choice(input_fn, "Class ID: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    calendar_revision = _positive_int(
        read_choice(input_fn, "Calendar revision: ")
    )
    print("1. Conventional")
    print("2. Standards based")
    print("3. Hybrid")
    family = _family(read_choice(input_fn, "Calculation family: "))
    if family is None:
        raise ValueError("calculation family must be 1, 2, or 3")
    return (
        class_id,
        school_year,
        AcademicPeriodRef(school_year, period_id),
        calendar_revision,
        family,
    )


def _show_current(
    *,
    deps: GradeMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Preview Current Grade")
    try:
        class_id, _year, period, calendar_revision, family = _period_scope(
            input_fn
        )
        student_id = read_choice(input_fn, "Student ID: ")
        value = deps.current_grade_loader(
            deps.workspace_resolver(),
            class_id,
            student_id,
            period,
            calendar_revision,
            family,
        )
    except (
        WorkspaceRootError,
        GradeMenuEvidenceUnavailableError,
        GradePreviewError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "The requested current Grade could not be previewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _render_current(output, value)
        write_lines(
            output,
            "",
            "Read-only preview; no Grade, override, or snapshot was written.",
            "T. Technical details / provenance",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _render_current_technical(output, value)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _show_report(
    *,
    deps: GradeMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Preview Grade Report")
    try:
        class_id, _year, period, calendar_revision, family = _period_scope(
            input_fn
        )
        student_ids = _student_ids(
            read_choice(input_fn, "Student IDs, comma-separated: ")
        )
        value = deps.report_loader(
            deps.workspace_resolver(),
            class_id,
            student_ids,
            period,
            calendar_revision,
            family,
        )
    except (
        WorkspaceRootError,
        GradeMenuEvidenceUnavailableError,
        GradePreviewError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "The requested Grade report could not be previewed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    while True:
        clear_fn()
        _render_report(output, value)
        write_lines(
            output,
            "",
            "Read-only preview; no ReportingSnapshot was frozen.",
            "T. Technical details / provenance",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            _render_report_technical(output, value)
            write_lines(output, "")
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def run_grade_preview_menu(
    *,
    dependencies: GradeMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_grade_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Preview Grades")
        write_lines(
            stream,
            "1. Preview one current Grade",
            "2. Preview a bounded Grade report",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _show_current(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "2":
            _show_report(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1, 2, B, M, or Q.")
        pause_for_user(input_fn)
