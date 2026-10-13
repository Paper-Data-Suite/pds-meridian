"""Direct CLI for Slice 9 standards-profile and proficiency-growth reports."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.class_standards_profile import (
    ClassStandardsProfileError,
    build_current_class_standards_profile,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.student_proficiency_growth import (
    StudentProficiencyGrowthError,
    build_student_proficiency_growth,
)
from meridian.teacher_report import TeacherReportError, TeacherReportPreview
from meridian.teacher_report_render import (
    TeacherReportRenderFormat,
    render_teacher_report,
)


def register_standards_reporting_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the Slice 9 reports under ``meridian reports``."""

    standards = commands.add_parser(
        "standards",
        help="Class standards profile and one-student proficiency trajectory.",
        description=(
            "Read-only standards reporting over selected Academic Period proficiency "
            "authority. Missing judgments remain absent; historical attempts are "
            "never averaged."
        ),
    )
    subcommands = standards.add_subparsers(dest="standards_report_command")

    profile = subcommands.add_parser(
        "profile",
        help="Render the current class standards matrix and distributions.",
    )
    _add_scope(profile, include_student=False)
    profile.add_argument("--standard", action="append", default=[])
    profile.add_argument("--student", action="append", default=[])
    profile.add_argument("--level", action="append", default=[])
    profile.add_argument("--group")
    _add_output(profile, default_format="csv")
    profile.set_defaults(handler=_handle_profile, show_group_help=None)

    growth = subcommands.add_parser(
        "growth",
        help="Render one student's exact proficiency-result trajectory.",
    )
    _add_scope(growth, include_student=True)
    growth.add_argument("--standard", action="append", default=[])
    _add_output(growth, default_format="markdown")
    growth.set_defaults(handler=_handle_growth, show_group_help=None)

    standards.set_defaults(show_group_help=standards)


def _handle_profile(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        preview = build_current_class_standards_profile(
            args.workspace,
            class_id=args.class_id,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            calendar_revision=args.calendar_revision,
            generated_at=args.generated_at,
            standard_filter=tuple(args.standard),
            student_filter=tuple(args.student),
            proficiency_level_filter=tuple(args.level),
            profile_group_filter=args.group,
        )
        return _emit(
            preview,
            args.format,
            args.output,
        )
    except (
        ClassStandardsProfileError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_growth(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        preview = build_student_proficiency_growth(
            args.workspace,
            class_id=args.class_id,
            student_id=args.student_id,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            calendar_revision=args.calendar_revision,
            generated_at=args.generated_at,
            standard_filter=tuple(args.standard),
        )
        return _emit(
            preview,
            args.format,
            args.output,
        )
    except (
        StudentProficiencyGrowthError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _emit(
    preview: TeacherReportPreview,
    representation: TeacherReportRenderFormat,
    output: Path | None,
) -> int:
    payload = render_teacher_report(preview, representation)
    if output is None:
        sys.stdout.write(payload.decode("utf-8"))
    else:
        disposition = write_or_verify_local_artifact(output, payload)
        print(f"{disposition}: {output}")
    return 0


def _add_scope(
    parser: argparse.ArgumentParser,
    *,
    include_student: bool,
) -> None:
    parser.add_argument("class_id")
    if include_student:
        parser.add_argument("student_id")
    parser.add_argument("school_year")
    parser.add_argument("period_id")
    parser.add_argument("calendar_revision", type=_positive_integer)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Paper Data Suite workspace root; defaults to the current directory.",
    )
    parser.add_argument("--generated-at", type=_datetime_argument)


def _add_output(
    parser: argparse.ArgumentParser,
    *,
    default_format: TeacherReportRenderFormat,
) -> None:
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "csv", "tsv"),
        default=default_format,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Safely create or verify the exact local report artifact.",
    )


def _print_error(error: BaseException) -> int:
    code = getattr(error, "code", "standards_reporting.cli_error")
    print(f"error: {code}: {error}", file=sys.stderr)
    return 1


def _datetime_argument(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


__all__ = ["register_standards_reporting_cli"]
