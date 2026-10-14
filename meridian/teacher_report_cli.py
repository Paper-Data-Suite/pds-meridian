"""Direct CLI shell for the Issue #111 teacher-report suite."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from meridian.benchmark_plan_storage import (
    BENCHMARK_PLAN_RECORD_TYPE,
    BENCHMARK_PLAN_SCHEMA_VERSION,
    BenchmarkPlanCurrentness,
    BenchmarkPlanRevision,
    list_benchmark_plan_revisions,
    load_benchmark_plan_revision,
    load_latest_benchmark_plan_revision,
    write_benchmark_plan_revision,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_checkpoint_reporting_cli import (
    register_evidence_checkpoint_reporting_cli,
)
from meridian.readiness_impact_reporting_cli import (
    register_readiness_impact_reporting_cli,
)
from meridian.report_guided_selection import (
    ReportOption,
    ReportPreparedSelection,
    ReportScope,
)
from meridian.report_menu_execution import (
    LiveReportMenuExecutor,
    ReportMenuExecutionDependencies,
)
from meridian.sis_reconciliation_cli import (
    register_sis_gradebook_reconciliation_cli,
)
from meridian.standards_reporting_cli import register_standards_reporting_cli
from meridian.student_grade_justification_cli import (
    register_student_grade_justification_cli,
)
from meridian.teacher_report import (
    TEACHER_REPORT_KINDS,
    TeacherReportPreview,
    teacher_report_preview_from_json_bytes,
)
from meridian.teacher_report_output import write_teacher_report_file
from meridian.teacher_report_render import (
    TeacherReportRenderFormat,
    render_teacher_report,
)

_LABELS = (
    "SIS Gradebook Reconciliation",
    "Student Current Grade Justification",
    "Class Standards Profile",
    "Student Proficiency Growth / Trajectory",
    "Evidence Coverage / Sufficiency",
    "Grade Checkpoint Comparison",
    "Marking-Period Readiness",
    "Grade Item / Assessment Impact",
    "Benchmark Analysis & Instructional Response Planner",
)


def add_teacher_reports_cli(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    reports = groups.add_parser(
        "reports",
        help="Preview and render read-only teacher reports.",
        description=(
            "Teacher reports are deterministic read-only views over "
            "Meridian authority. "
            "They do not create Grades or proficiency and do not write to an SIS/LMS."
        ),
    )
    commands = reports.add_subparsers(dest="teacher_report_command")
    kinds = commands.add_parser("kinds", help="List Issue #111 report families.")
    kinds.add_argument("--format", choices=("text", "json"), default="text")
    kinds.set_defaults(handler=_handle_report_kinds, show_group_help=None)
    register_sis_gradebook_reconciliation_cli(commands)
    register_student_grade_justification_cli(commands)
    register_standards_reporting_cli(commands)
    register_evidence_checkpoint_reporting_cli(commands)
    register_readiness_impact_reporting_cli(commands)
    benchmark = commands.add_parser(
        "benchmark",
        help="Render a verified Benchmark Analysis planner preview.",
        description=(
            "Render one canonical benchmark planner preview produced from "
            "authorized evidence. JSON, Markdown, CSV, and TSV are deterministic; "
            "no academic record or external system is changed."
        ),
    )
    benchmark.add_argument(
        "--input",
        type=Path,
        help="Canonical benchmark teacher-report JSON file to render.",
    )
    benchmark.add_argument(
        "--workspace",
        type=Path,
        help="Workspace used to build a fresh authorized planner preview.",
    )
    benchmark.add_argument("--class-id")
    benchmark.add_argument("--period-id")
    benchmark.add_argument("--grade-item-id")
    benchmark.add_argument(
        "--checkpoint-id",
        help="Optional exact checkpoint; otherwise the one current checkpoint is used.",
    )
    benchmark.add_argument(
        "--load-plan-id",
        help="Load a saved planner from --workspace and --class-id.",
    )
    benchmark.add_argument(
        "--plan-revision",
        type=int,
        help="Exact saved revision to load; default is the latest revision.",
    )
    benchmark.add_argument(
        "--save-plan-id",
        help="Stable plan identity to save after live revalidation.",
    )
    benchmark.add_argument(
        "--teacher-id", help="Teacher attribution for a saved plan."
    )
    benchmark.add_argument(
        "--confirm-save",
        action="store_true",
        help="Explicitly confirm writing one immutable planner revision.",
    )
    benchmark.add_argument(
        "--format",
        choices=("json", "markdown", "csv", "tsv"),
        default="markdown",
    )
    benchmark.add_argument(
        "--output",
        help=(
            "Optional new local output path; existing different files are not "
            "replaced."
        ),
    )
    benchmark.set_defaults(handler=_handle_benchmark, show_group_help=None)
    reports.set_defaults(show_group_help=reports)


def _handle_report_kinds(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    rows = [
        {
            "report_kind": kind,
            "title": title,
            "generator_status": "available",
        }
        for kind, title in zip(TEACHER_REPORT_KINDS, _LABELS, strict=True)
    ]
    if args.format == "json":
        print(
            json.dumps(
                {
                    "surface": "teacher_reports",
                    "framework_schema_version": "1",
                    "academic_mutation": False,
                    "external_system_write": False,
                    "report_kinds": rows,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    print("Meridian Teacher Reports")
    print()
    for index, row in enumerate(rows, start=1):
        print(f"{index}. {row['title']}")
    print()
    print("All nine report-specific generators are available.")
    print("Reports are read-only and do not write to an SIS/LMS.")
    return 0


def _handle_benchmark(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    source = cast(Path | None, args.input)
    workspace = cast(Path | None, args.workspace)
    required_live_values = (args.class_id, args.period_id, args.grade_item_id)
    load_plan_id = cast(str | None, args.load_plan_id)
    selected_modes = sum(
        (source is not None, load_plan_id is not None, args.period_id is not None)
    )
    if selected_modes != 1:
        raise ValueError(
            "choose exactly one source: --input, --load-plan-id, or live "
            "--period-id/--grade-item-id selectors."
        )
    executor: LiveReportMenuExecutor | None = None
    prepared: ReportPreparedSelection | None = None
    currentness: BenchmarkPlanCurrentness = "unverified"
    if source is not None:
        if (
            args.period_id is not None
            or args.grade_item_id is not None
            or args.checkpoint_id is not None
            or args.plan_revision is not None
        ):
            raise ValueError(
                "--input cannot be combined with live workspace selectors."
            )
        if source.is_symlink() or not source.is_file():
            raise ValueError("input must be a regular non-linked file.")
        if source.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("input exceeds the benchmark preview size limit.")
        content = source.read_bytes()
        if len(content) > 16 * 1024 * 1024:
            raise ValueError("input exceeds the benchmark preview size limit.")
        preview = teacher_report_preview_from_json_bytes(content)
        if preview.report_kind != "benchmark_analysis_instructional_response":
            raise ValueError("input is not a benchmark analysis planner preview.")
    elif load_plan_id is not None:
        if workspace is None or args.class_id is None:
            raise ValueError(
                "--load-plan-id requires --workspace and --class-id."
            )
        if any(
            value is not None
            for value in (args.period_id, args.grade_item_id, args.checkpoint_id)
        ):
            raise ValueError(
                "--load-plan-id cannot be combined with live report selectors."
            )
        if args.plan_revision is None:
            loaded = load_latest_benchmark_plan_revision(
                workspace, args.class_id, load_plan_id
            )
        else:
            loaded = load_benchmark_plan_revision(
                workspace,
                args.class_id,
                load_plan_id,
                args.plan_revision,
            )
        preview = loaded.revision.report
        currentness = loaded.revision.currentness
    else:
        if workspace is None or any(
            value is None for value in required_live_values
        ):
            raise ValueError(
                "provide --input, or provide --workspace, --class-id, "
                "--period-id, and --grade-item-id."
            )
        live_workspace = workspace
        choices: list[tuple[ReportScope, ReportOption]] = [
            ("class", ReportOption(args.class_id, args.class_id)),
            ("period", ReportOption(args.period_id, args.period_id)),
            (
                "grade_item",
                ReportOption(args.grade_item_id, args.grade_item_id),
            ),
        ]
        if args.checkpoint_id is not None:
            choices.append(
                (
                    "checkpoint",
                    ReportOption(args.checkpoint_id, args.checkpoint_id),
                )
            )
        prepared = ReportPreparedSelection(
            "benchmark_analysis_instructional_response",
            tuple(choices),
        )
        executor = LiveReportMenuExecutor(
            ReportMenuExecutionDependencies(
                workspace_resolver=lambda: live_workspace,
                diagnostics=dependencies,
            )
        )
        preview = executor.build(prepared)
        currentness = "current"

    if args.save_plan_id is not None:
        if workspace is None or args.class_id is None or args.teacher_id is None:
            raise ValueError(
                "--save-plan-id requires --workspace, --class-id, and --teacher-id."
            )
        if not args.confirm_save:
            raise ValueError(
                "saving a planner requires explicit --confirm-save."
            )
        if executor is not None and prepared is not None:
            executor.revalidate(prepared, preview)
        revisions = list_benchmark_plan_revisions(
            workspace, args.class_id, args.save_plan_id
        )
        previous = (
            None
            if not revisions
            else load_benchmark_plan_revision(
                workspace, args.class_id, args.save_plan_id, revisions[-1]
            )
        )
        now = datetime.now(UTC)
        saved = write_benchmark_plan_revision(
            workspace,
            BenchmarkPlanRevision(
                BENCHMARK_PLAN_SCHEMA_VERSION,
                BENCHMARK_PLAN_RECORD_TYPE,
                args.save_plan_id,
                1 if previous is None else previous.revision.plan_revision + 1,
                args.teacher_id,
                args.class_id,
                _benchmark_assessment_id(preview),
                now if previous is None else previous.revision.created_at,
                now,
                True,
                currentness,
                preview,
                (
                    None
                    if previous is None
                    else previous.revision_sha256
                ),
            ),
        )
        print(
            f"planner revision {saved.stored.revision.plan_revision} "
            f"{saved.disposition}: {saved.stored.revision_sha256}",
            file=sys.stderr,
        )
    elif args.confirm_save or args.teacher_id is not None:
        raise ValueError(
            "--confirm-save and --teacher-id require --save-plan-id."
        )
    representation = cast(TeacherReportRenderFormat, args.format)
    if args.output:
        result = write_teacher_report_file(
            args.output, preview, representation
        )
        print(f"{result.disposition}: {args.output} ({result.payload_sha256})")
    else:
        print(render_teacher_report(preview, representation).decode("utf-8"), end="")
    return 0


def _benchmark_assessment_id(preview: TeacherReportPreview) -> str:
    values: set[str] = {
        row.values[3]
        for row in preview.rows
        if len(row.values) >= 4
        and row.values[0] == "1. Assessment Data"
        and row.values[2] == "Assessment ID"
        and row.values[3] is not None
    }
    if len(values) != 1:
        raise ValueError("benchmark preview has no unambiguous assessment identity.")
    return next(iter(values))


__all__ = ["add_teacher_reports_cli"]
