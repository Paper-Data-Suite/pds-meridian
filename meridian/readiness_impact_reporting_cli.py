"""Direct CLI for Slice 11 Marking-Period Readiness and Assessment Impact."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from meridian.assessment_impact import (
    AssessmentImpactError,
    build_assessment_impact,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.marking_period_readiness import (
    MarkingPeriodReadinessError,
    build_marking_period_readiness,
)
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
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


def register_readiness_impact_reporting_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register Slice 11 report commands beneath ``meridian reports``."""

    readiness = commands.add_parser(
        "readiness",
        help="Run the Marking-Period Readiness pre-close audit.",
        description=(
            "Build a whole-class, read-only pre-close audit from one exact "
            "ReportingSnapshot build request. The report does not finalize Grades "
            "or assert that an SIS is ready."
        ),
    )
    readiness.add_argument(
        "build_request",
        type=Path,
        help=(
            "Canonical ReportingSnapshot build-request JSON covering exactly one "
            "Grade family row for every current roster student."
        ),
    )
    _add_prior_checkpoint(readiness)
    _add_projection_authorization(readiness)
    _add_common_output(readiness, default_format="markdown")
    readiness.set_defaults(handler=_handle_readiness, show_group_help=None)

    impact = commands.add_parser(
        "impact",
        help="Show Grade Item / Assessment participation and result lineage.",
        description=(
            "Describe what one current Grade Item participates in across the "
            "class. The report is provenance-based and makes no causal claim "
            "about Grade or proficiency changes."
        ),
    )
    impact.add_argument("grade_item_id")
    impact.add_argument(
        "build_request",
        type=Path,
        help=(
            "Canonical ReportingSnapshot build-request JSON covering exactly one "
            "Grade family row for every current roster student."
        ),
    )
    _add_prior_checkpoint(impact)
    _add_projection_authorization(impact)
    _add_common_output(impact, default_format="markdown")
    impact.set_defaults(handler=_handle_impact, show_group_help=None)


def _handle_readiness(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    try:
        request = load_reporting_snapshot_build_request_file(args.build_request)
        prior = _prior_reference(
            request.definition_reference.class_id,
            args.prior_snapshot_id,
            args.prior_snapshot_sha256,
        )
        preview = build_marking_period_readiness(
            args.workspace,
            build_request=request,
            authorizations=_projection_authorizations(args.projection_auth),
            prior_checkpoint=prior,
            generated_at=args.generated_at,
            dependencies=dependencies,
        )
        return _emit(preview, args.format, args.output)
    except (
        MarkingPeriodReadinessError,
        ReportingSnapshotWorkflowError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_impact(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    try:
        request = load_reporting_snapshot_build_request_file(args.build_request)
        prior = _prior_reference(
            request.definition_reference.class_id,
            args.prior_snapshot_id,
            args.prior_snapshot_sha256,
        )
        preview = build_assessment_impact(
            args.workspace,
            grade_item_id=args.grade_item_id,
            build_request=request,
            authorizations=_projection_authorizations(args.projection_auth),
            prior_checkpoint=prior,
            generated_at=args.generated_at,
            dependencies=dependencies,
        )
        return _emit(preview, args.format, args.output)
    except (
        AssessmentImpactError,
        ReportingSnapshotWorkflowError,
        ReportExportCommitError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _add_prior_checkpoint(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--prior-snapshot-id",
        help="Optional exact prior ReportingSnapshot ID for comparison.",
    )
    parser.add_argument(
        "--prior-snapshot-sha256",
        type=_sha256,
        help="Exact SHA-256 for --prior-snapshot-id.",
    )


def _add_projection_authorization(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
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


def _prior_reference(
    class_id: str,
    snapshot_id: str | None,
    snapshot_sha256: str | None,
) -> ReportingSnapshotReference | None:
    if snapshot_id is None and snapshot_sha256 is None:
        return None
    if snapshot_id is None or snapshot_sha256 is None:
        raise ValueError(
            "--prior-snapshot-id and --prior-snapshot-sha256 must be supplied together."
        )
    return ReportingSnapshotReference(
        class_id=class_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
    )


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


def _print_error(error: BaseException) -> int:
    code = getattr(error, "code", "slice11_reporting.cli_error")
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


def _sha256(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise argparse.ArgumentTypeError(
            "expected a lowercase 64-character SHA-256 digest"
        )
    return value


__all__ = ["register_readiness_impact_reporting_cli"]
