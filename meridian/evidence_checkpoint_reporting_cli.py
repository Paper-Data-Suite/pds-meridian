"""Direct CLI for Slice 10 Evidence Coverage and Grade Checkpoints."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_coverage import (
    EvidenceCoverageError,
    build_current_evidence_coverage,
)
from meridian.grade_checkpoint_comparison import (
    GradeCheckpointComparisonError,
    build_snapshot_to_current_grade_checkpoint_comparison,
    build_snapshot_to_snapshot_grade_checkpoint_comparison,
)
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_record import ReportingSnapshotBuildRequest
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotProjectionAuthorization,
    ReportingSnapshotWorkflowError,
    load_reporting_snapshot_build_request_file,
)
from meridian.teacher_report import TeacherReportError, TeacherReportPreview
from meridian.teacher_report_render import (
    TeacherReportRenderFormat,
    render_teacher_report,
)


def register_evidence_checkpoint_reporting_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register Slice 10 reports beneath ``meridian reports``."""

    evidence = commands.add_parser(
        "evidence",
        help="Evidence Coverage / Missing & Incomplete Evidence.",
        description=(
            "Show attention-worthy evidence gaps using only Meridian's existing "
            "selected results and provenance. Absence is not treated as proof "
            "that a student failed to submit work."
        ),
    )
    evidence.add_argument("class_id")
    evidence.add_argument("school_year")
    evidence.add_argument("period_id")
    evidence.add_argument("calendar_revision", type=_positive_integer)
    evidence.add_argument("--student", action="append", default=[])
    evidence.add_argument("--standard", action="append", default=[])
    evidence.add_argument("--grade-item", action="append", default=[])
    evidence.add_argument("--attention", action="append", default=[])
    evidence.add_argument("--producer", action="append", default=[])
    evidence.add_argument("--attention-only", action="store_true")
    _add_common_output(evidence, default_format="csv")
    evidence.set_defaults(handler=_handle_evidence, show_group_help=None)

    checkpoint = commands.add_parser(
        "checkpoint",
        help="Compare exact Grade checkpoints without a second diff engine.",
        description=(
            "Compare ReportingSnapshots to another snapshot or to a live current "
            "Grade report using Meridian's existing GradePreviewComparison engine."
        ),
    )
    checkpoint_commands = checkpoint.add_subparsers(dest="checkpoint_report_command")

    snapshots = checkpoint_commands.add_parser(
        "snapshots",
        help="Compare two exact immutable ReportingSnapshots.",
    )
    snapshots.add_argument("class_id")
    snapshots.add_argument("prior_snapshot_id")
    snapshots.add_argument("prior_snapshot_sha256", type=_sha256)
    snapshots.add_argument("current_snapshot_id")
    snapshots.add_argument("current_snapshot_sha256", type=_sha256)
    _add_common_output(snapshots, default_format="markdown")
    snapshots.set_defaults(handler=_handle_checkpoint_snapshots, show_group_help=None)

    current = checkpoint_commands.add_parser(
        "current",
        help="Compare one exact ReportingSnapshot with live/current Grade state.",
        description=(
            "By default the prior snapshot's exact build request defines the live "
            "row set. Conventional/hybrid comparisons require explicit projection "
            "authorization for every available projection referenced by that request."
        ),
    )
    current.add_argument("class_id")
    current.add_argument("prior_snapshot_id")
    current.add_argument("prior_snapshot_sha256", type=_sha256)
    current.add_argument(
        "--current-build-request",
        type=Path,
        help=(
            "Optional canonical ReportingSnapshot build-request JSON for the live "
            "comparison. Omit to reuse the prior snapshot's exact request."
        ),
    )
    current.add_argument(
        "--projection-auth",
        action="append",
        nargs=4,
        default=[],
        metavar=("PUBLICATION_ID", "CACHE_KEY", "PURPOSE_ID", "STUDENTS"),
        help=(
            "Authorize one exact projection. STUDENTS is comma-separated or '-' "
            "for an empty scope. Repeat for every required projection."
        ),
    )
    _add_common_output(current, default_format="markdown")
    current.set_defaults(handler=_handle_checkpoint_current, show_group_help=None)

    checkpoint.set_defaults(show_group_help=checkpoint)


def _handle_evidence(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        preview = build_current_evidence_coverage(
            args.workspace,
            class_id=args.class_id,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            calendar_revision=args.calendar_revision,
            generated_at=args.generated_at,
            student_filter=tuple(args.student),
            standard_filter=tuple(args.standard),
            grade_item_filter=tuple(args.grade_item),
            attention_filter=tuple(args.attention),
            producer_filter=tuple(args.producer),
            attention_only=args.attention_only,
        )
        return _emit(preview, args.format, args.output)
    except (
        EvidenceCoverageError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_checkpoint_snapshots(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        preview = build_snapshot_to_snapshot_grade_checkpoint_comparison(
            args.workspace,
            prior_reference=ReportingSnapshotReference(
                args.class_id,
                args.prior_snapshot_id,
                args.prior_snapshot_sha256,
            ),
            current_reference=ReportingSnapshotReference(
                args.class_id,
                args.current_snapshot_id,
                args.current_snapshot_sha256,
            ),
            generated_at=args.generated_at,
        )
        return _emit(preview, args.format, args.output)
    except (
        GradeCheckpointComparisonError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_checkpoint_current(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    try:
        request: ReportingSnapshotBuildRequest | None = None
        if args.current_build_request is not None:
            request = load_reporting_snapshot_build_request_file(
                args.current_build_request
            )
        authorizations = _projection_authorizations(args.projection_auth)
        preview = build_snapshot_to_current_grade_checkpoint_comparison(
            args.workspace,
            prior_reference=ReportingSnapshotReference(
                args.class_id,
                args.prior_snapshot_id,
                args.prior_snapshot_sha256,
            ),
            current_build_request=request,
            authorizations=authorizations,
            generated_at=args.generated_at,
            dependencies=dependencies,
        )
        return _emit(preview, args.format, args.output)
    except (
        GradeCheckpointComparisonError,
        ReportingSnapshotWorkflowError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _projection_authorizations(
    values: list[list[str]],
) -> tuple[ReportingSnapshotProjectionAuthorization, ...]:
    result: list[ReportingSnapshotProjectionAuthorization] = []
    seen: set[tuple[str, str]] = set()
    for raw in values:
        if len(raw) != 4:
            raise ValueError("Each --projection-auth requires exactly four values.")
        publication_id, cache_key, purpose_id, students_text = raw
        exact_cache = _sha256(cache_key)
        students = (
            () if students_text == "-" else tuple(sorted(students_text.split(",")))
        )
        if any(not item for item in students):
            raise ValueError(
                "Projection student scope must use nonempty comma-separated IDs."
            )
        authorization = ReportingSnapshotProjectionAuthorization(
            publication_id=publication_id,
            cache_key=exact_cache,
            purpose_id=purpose_id,
            student_ids=students,
        )
        if authorization.key in seen:
            raise ValueError(
                "Projection authorization must not duplicate publication/cache "
                "identity."
            )
        seen.add(authorization.key)
        result.append(authorization)
    return tuple(sorted(result, key=lambda item: item.key))


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


def _add_common_output(
    parser: argparse.ArgumentParser,
    *,
    default_format: TeacherReportRenderFormat,
) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Paper Data Suite workspace root; defaults to current directory.",
    )
    parser.add_argument("--generated-at", type=_datetime_argument)
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
    code = getattr(error, "code", "slice10_reporting.cli_error")
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


def _sha256(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise argparse.ArgumentTypeError(
            "expected a lowercase 64-character SHA-256 digest"
        )
    return value


__all__ = ["register_evidence_checkpoint_reporting_cli"]
