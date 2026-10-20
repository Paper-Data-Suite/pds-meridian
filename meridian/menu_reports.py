"""Teacher-first discovery, execution, preview, and local report copies."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.menu_benchmark_planner import run_benchmark_planner_menu
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.report_guided_selection import (
    REPORT_GUIDES,
    ReportChoiceCatalog,
    ReportPreparedSelection,
    collect_guided_report_selection,
)
from meridian.report_live_catalog import LiveReportChoiceCatalog
from meridian.report_menu_execution import (
    LiveReportMenuExecutor,
    ReportMenuExecutionError,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_report import TeacherReportPreview
from meridian.teacher_report_render import render_teacher_report

# Reports 1-8 retain their historical identity and position; report 9 is append-only.
REPORT_MENU_TITLES: Final[tuple[str, ...]] = (
    "SIS Gradebook Reconciliation",
    "Student Current Grade Justification",
    "Class Standards Profile",
    "Student Proficiency Growth / Trajectory",
    "Evidence Coverage / Sufficiency",
    "Grade Checkpoint Comparison",
    "Marking-Period Readiness",
    "Grade Item / Assessment Impact",
    "Benchmark Analysis & Instructional Response",
)

SelectionHandler = Callable[[ReportPreparedSelection], TeacherReportPreview | None]


def _show_preview(
    preview: TeacherReportPreview,
    *,
    prepared: ReportPreparedSelection,
    revalidate: Callable[[ReportPreparedSelection, TeacherReportPreview | None], None]
    | None,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> bool:
    """Show a bounded preview; return True when selections should be changed."""

    expanded = False
    while True:
        clear_fn()
        print_menu_header(output, "Report preview")
        write_lines(
            output,
            preview.title,
            (
                f"Class {preview.class_id} · "
                f"{preview.target_period.school_year} / "
                f"{preview.target_period.period_id}"
            ),
            "READ-ONLY preview · nothing was posted or synchronized",
            "",
        )
        for line in preview.summary:
            print(line, file=output)
        limit = len(preview.rows) if expanded else min(10, len(preview.rows))
        if preview.rows:
            print(file=output)
            print(" | ".join(column.title for column in preview.columns), file=output)
            for row in preview.rows[:limit]:
                print(
                    " | ".join("" if value is None else value for value in row.values),
                    file=output,
                )
            if limit < len(preview.rows):
                print(f"… {len(preview.rows) - limit} more row(s)", file=output)
        if preview.diagnostics:
            print(file=output)
            for item in preview.diagnostics:
                print(f"{item.severity.upper()}: {item.message}", file=output)
        write_lines(
            output,
            "",
            "1. View all rows" if not expanded else "1. Show compact preview",
            "2. Save a local teacher copy",
            "3. Preview again",
            "4. Change selections",
            "P. Write / revisit benchmark teaching plan"
            if preview.report_kind == "benchmark_analysis_instructional_response"
            else "",
            "D. Details / Audit Trail",
            "",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            return False
        if choice == "1":
            expanded = not expanded
            continue
        if choice == "2":
            _save_copy(
                preview,
                prepared=prepared,
                revalidate=revalidate,
                input_fn=input_fn,
                output=output,
            )
            continue
        if choice == "3":
            return False
        if choice == "4":
            return True
        if (
            choice.casefold() == "p"
            and preview.report_kind == "benchmark_analysis_instructional_response"
        ):
            run_benchmark_planner_menu(
                report=preview,
                prepared=prepared,
                revalidate=revalidate,
                input_fn=input_fn,
                output=output,
            )
            continue
        if choice.casefold() == "d":
            write_lines(
                output,
                "",
                f"Preview SHA-256: {preview.preview_sha256}",
                f"Generated: {preview.generated_at.isoformat()}",
                f"Source references: {len(preview.source_references)}",
            )
            for source in preview.source_references:
                print(
                    f"  {source.source_kind}: {source.source_id} "
                    f"({source.source_sha256[:12]}…)",
                    file=output,
                )
            input_fn("Press Enter to return to the preview...")
            continue
        options = (
            "Choose 1-4, P, D, B, M, or Q."
            if preview.report_kind == "benchmark_analysis_instructional_response"
            else "Choose 1-4, D, B, M, or Q."
        )
        write_lines(output, "", options)


def _save_copy(
    preview: TeacherReportPreview,
    *,
    prepared: ReportPreparedSelection,
    revalidate: Callable[[ReportPreparedSelection, TeacherReportPreview | None], None]
    | None,
    input_fn: InputFunction,
    output: TextIO,
) -> None:
    format_choice = (
        input_fn("Format (markdown/csv/tsv/json, or B): ").strip().casefold()
    )
    navigation = parse_navigation_choice(format_choice)
    if navigation is NavigationChoice.BACK or not format_choice:
        return
    aliases = {"md": "markdown"}
    representation = aliases.get(format_choice, format_choice)
    if representation not in {"markdown", "csv", "tsv", "json"}:
        print("Choose markdown, csv, tsv, or json.", file=output)
        input_fn("Press Enter to return to the preview...")
        return
    destination = input_fn(
        "Full path for this local teacher copy (existing files are not replaced): "
    ).strip()
    if not destination:
        return
    try:
        if revalidate is not None:
            revalidate(prepared, preview)
        payload = render_teacher_report(preview, representation)  # type: ignore[arg-type]
        disposition = write_or_verify_local_artifact(Path(destination), payload)
    except (ReportExportCommitError, ReportMenuExecutionError, OSError, ValueError):
        print(
            "The local copy was not saved. Choose an existing real folder and a "
            "new filename, then refresh the report if its sources changed.",
            file=output,
        )
        input_fn("Press Enter to return to the preview...")
        return
    print(
        f"Local teacher copy {disposition}. Nothing was sent to an external system.",
        file=output,
    )
    input_fn("Press Enter to return to the preview...")


def _report_detail(
    *,
    index: int,
    catalog: ReportChoiceCatalog | None,
    on_prepared: SelectionHandler | None,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    revalidate: Callable[[ReportPreparedSelection, TeacherReportPreview | None], None]
    | None = None,
) -> None:
    guide = REPORT_GUIDES[index]
    while True:
        clear_fn()
        print_menu_header(output, "About this report")
        write_lines(
            output,
            guide.question,
            "",
            guide.explanation,
            "",
            "You will choose:",
        )
        labels = {
            "class": "Class",
            "period": "Marking period",
            "student": "Student",
            "grade_item": "Assignment or assessment",
            "checkpoint": "Earlier grade checkpoint",
            "mapping": "Teacher's external gradebook mapping",
        }
        for item in guide.scopes:
            print(f"  - {labels[item]}", file=output)
        write_lines(
            output,
            "",
            "1. Choose report details",
            "T. Advanced command information",
            "",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            return
        if choice.casefold() == "t":
            write_lines(
                output,
                "",
                "For advanced use:",
                guide.advanced_command,
                "This generates no report by itself.",
                "",
            )
            input_fn("Press Enter to return to this report...")
            continue
        if choice == "1":
            if catalog is None:
                write_lines(
                    output,
                    "",
                    "Verified class choices are not available.",
                    "Try checking your workspace and academic calendar.",
                    "No report was generated or saved.",
                    "",
                )
                input_fn("Press Enter to return to this report...")
                continue
            prepared = collect_guided_report_selection(
                guide,
                catalog=catalog,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            if prepared is None:
                continue
            clear_fn()
            print_menu_header(output, "Confirm report context")
            for scope, option in prepared.choices:
                label = scope.replace("_", " ").title()
                print(f"{label}: {option.display}", file=output)
            write_lines(
                output,
                "",
                "This creates a read-only preview. It does not change academic records",
                "or write to an external gradebook.",
                "",
                "1. Generate preview",
            )
            print_standard_navigation(output)
            confirmation = read_choice(input_fn)
            navigation = parse_navigation_choice(confirmation)
            if navigation is NavigationChoice.BACK or not confirmation:
                continue
            if confirmation != "1":
                write_lines(output, "", "Choose 1, B, M, or Q.")
                input_fn("Press Enter to return to this report...")
                continue
            try:
                preview = None if on_prepared is None else on_prepared(prepared)
            except (ReportMenuExecutionError, OSError, RuntimeError, ValueError):
                write_lines(
                    output,
                    "",
                    "The report could not be generated from verified current records.",
                    "Refresh the choices, choose another exact checkpoint, or return",
                    "to report selection. No report was saved.",
                )
                input_fn("Press Enter to return to this report...")
                continue
            if preview is None:
                # Injection-only callbacks may observe the prepared selection.
                continue
            if _show_preview(
                preview,
                prepared=prepared,
                revalidate=revalidate,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            ):
                continue
            continue
        write_lines(output, "", "Choose 1, T, B, M, or Q.")


def run_reports_menu(
    *,
    navigation_context: TeacherNavigationContext | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
    catalog: ReportChoiceCatalog | None = None,
    on_prepared: SelectionHandler | None = None,
    executor: LiveReportMenuExecutor | None = None,
) -> None:
    """Show nine teacher-facing questions, preserving Core B/M/Q semantics."""
    stream = sys.stdout if output is None else output
    active_catalog = LiveReportChoiceCatalog() if catalog is None else catalog
    live_executor = (
        (executor or LiveReportMenuExecutor()) if on_prepared is None else None
    )
    active_handler = live_executor.build if live_executor is not None else on_prepared
    revalidate = live_executor.revalidate if live_executor is not None else None
    while True:
        clear_fn()
        print_menu_header(stream, "Reports")
        write_lines(
            stream,
            "What would you like to find out?",
            "Choose a question to see what the report shows.",
            "",
        )
        for index, guide in enumerate(REPORT_GUIDES, start=1):
            print(f"{index}. {guide.question}", file=stream)
            print(f"   {REPORT_MENU_TITLES[index - 1]}", file=stream)
        write_lines(
            stream,
            "",
            "Guided choices use your existing class and reporting records.",
            "Reports are read-only and do not write to an external gradebook.",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or not choice:
            return
        if choice in {str(number) for number in range(1, 10)}:
            _report_detail(
                index=int(choice) - 1,
                catalog=active_catalog,
                on_prepared=active_handler,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
                revalidate=revalidate,
            )
            continue
        write_lines(stream, "", "Please choose 1-9, B, M, or Q.")


__all__ = ("REPORT_MENU_TITLES", "run_reports_menu")
