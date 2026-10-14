"""CLI for Student Current Grade Justification — Issue #111 Slice 8."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.student_grade_justification import (
    StudentGradeJustificationError,
    build_current_student_grade_justification,
    build_snapshot_student_grade_justification,
)
from meridian.teacher_report import TeacherReportError, TeacherReportPreview
from meridian.teacher_report_render import (
    TeacherReportRenderFormat,
    render_teacher_report,
)


def register_student_grade_justification_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    justify = commands.add_parser(
        "justify",
        help="Explain one student's current or frozen Grade.",
        description=(
            "Read-only Student Grade Justification using existing Meridian Grade "
            "explanation authority. Historical mode uses exact ReportingSnapshot "
            "state. Raw protected student work is not reproduced."
        ),
    )
    subcommands = justify.add_subparsers(dest="grade_justification_command")

    current = subcommands.add_parser(
        "current",
        help="Explain one current selected Grade.",
        description=(
            "Current standards-based Grade justification is directly available. "
            "Conventional/hybrid current justification requires an explicit "
            "authorized work-evidence provider and is never opened implicitly."
        ),
    )
    current.add_argument("class_id")
    current.add_argument("student_id")
    current.add_argument("school_year")
    current.add_argument("period_id")
    current.add_argument("calendar_revision", type=_positive_integer)
    current.add_argument(
        "--family",
        choices=("conventional", "standards_based", "hybrid"),
        default="standards_based",
    )
    current.add_argument(
        "--format",
        choices=("json", "markdown", "csv", "tsv"),
        default="markdown",
    )
    current.add_argument("--generated-at", type=_datetime_argument)
    current.add_argument(
        "--output",
        type=Path,
        help="Safely create or verify the exact local report artifact.",
    )
    _add_workspace_argument(current)
    current.set_defaults(handler=_handle_current, show_group_help=None)

    snapshot = subcommands.add_parser(
        "snapshot",
        help="Explain one exact Grade row from a frozen ReportingSnapshot.",
    )
    snapshot.add_argument("class_id")
    snapshot.add_argument("snapshot_id")
    snapshot.add_argument("snapshot_sha256", type=_sha256_argument)
    snapshot.add_argument("student_id")
    snapshot.add_argument(
        "--family",
        choices=("conventional", "standards_based", "hybrid"),
    )
    snapshot.add_argument(
        "--format",
        choices=("json", "markdown", "csv", "tsv"),
        default="markdown",
    )
    snapshot.add_argument("--generated-at", type=_datetime_argument)
    snapshot.add_argument(
        "--output",
        type=Path,
        help="Safely create or verify the exact local report artifact.",
    )
    _add_workspace_argument(snapshot)
    snapshot.set_defaults(handler=_handle_snapshot, show_group_help=None)

    justify.set_defaults(show_group_help=justify)


def _handle_current(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        target = GradePreviewTarget(
            class_id=args.class_id,
            student_id=args.student_id,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            calendar_revision=args.calendar_revision,
            calculation_family=args.family,
        )
        report = build_current_student_grade_justification(
            args.workspace,
            target,
            generated_at=args.generated_at,
        )
        return _emit(report, args.format, args.output)
    except (
        ReportExportCommitError,
        StudentGradeJustificationError,
        TeacherReportError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_snapshot(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        reference = ReportingSnapshotReference(
            class_id=args.class_id,
            snapshot_id=args.snapshot_id,
            snapshot_sha256=args.snapshot_sha256,
        )
        report = build_snapshot_student_grade_justification(
            args.workspace,
            reference,
            args.student_id,
            calculation_family=args.family,
            generated_at=args.generated_at,
        )
        return _emit(report, args.format, args.output)
    except (
        ReportExportCommitError,
        StudentGradeJustificationError,
        TeacherReportError,
        ValueError,
    ) as error:
        return _print_error(error)


def _emit(
    report: TeacherReportPreview,
    representation: TeacherReportRenderFormat,
    output: Path | None,
) -> int:
    payload = render_teacher_report(report, representation)
    if output is None:
        sys.stdout.write(payload.decode("utf-8"))
    else:
        disposition = write_or_verify_local_artifact(output, payload)
        print(f"{disposition}: {output}")
    return 0


def _print_error(error: BaseException) -> int:
    code = getattr(error, "code", "student_grade_justification.cli_error")
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


def _sha256_argument(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise argparse.ArgumentTypeError(
            "expected a lowercase 64-character SHA-256 digest"
        )
    return value


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Paper Data Suite workspace root; defaults to the current directory.",
    )


__all__ = ["register_student_grade_justification_cli"]
