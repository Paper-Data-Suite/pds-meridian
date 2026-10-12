"""Direct CLI for the Issue #111 SIS gradebook reconciliation report."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    list_current_academic_period_proficiency_results,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingEntry,
    ExternalGradebookMappingError,
    compose_external_gradebook_mapping_revision,
    external_gradebook_mapping_from_json_bytes,
    external_gradebook_mapping_reference,
    external_gradebook_mapping_to_json_bytes,
    validate_external_gradebook_mapping_against_scale,
)
from meridian.proficiency_mapping import proficiency_scale_reference
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)
from meridian.report_export_commit import (
    ReportExportCommitError,
    write_or_verify_local_artifact,
)
from meridian.sis_gradebook_reconciliation import (
    SisGradebookReconciliationError,
    build_sis_gradebook_reconciliation,
    current_proficiency_observation,
)
from meridian.teacher_report import (
    TeacherReportError,
    teacher_report_preview_from_json_bytes,
    teacher_report_preview_to_json_bytes,
)
from meridian.teacher_report_render import render_teacher_report

_MAX_MAPPING_BYTES = 512 * 1024
_MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024


def register_sis_gradebook_reconciliation_cli(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register Slice 7 commands under ``meridian reports``."""

    reconciliation = commands.add_parser(
        "reconciliation",
        help="Create an external-gradebook mapping or reconcile selected standards.",
        description=(
            "Vendor-neutral reconciliation of selected Academic Period proficiency "
            "with an explicit teacher-owned external-gradebook mapping. No SIS/LMS "
            "write is performed."
        ),
    )
    subcommands = reconciliation.add_subparsers(dest="reconciliation_command")

    profile = subcommands.add_parser(
        "profile",
        help="Compose or explicitly write an immutable mapping-profile JSON file.",
    )
    profile.add_argument("class_id")
    profile.add_argument("school_year")
    profile.add_argument("period_id")
    profile.add_argument("profile_id")
    profile.add_argument("profile_revision", type=_positive_integer)
    profile.add_argument("scale_id")
    profile.add_argument("scale_revision", type=_positive_integer)
    profile.add_argument("--title", required=True)
    profile.add_argument("--system-label", required=True)
    profile.add_argument(
        "--map",
        nargs=2,
        action="append",
        required=True,
        metavar=("LEVEL_ID", "EXTERNAL_VALUE"),
    )
    profile.add_argument("--actor-id", required=True)
    profile.add_argument("--revised-at", required=True, type=_datetime_argument)
    profile.add_argument("--rationale")
    profile.add_argument("--output", type=Path)
    profile.add_argument(
        "--confirm-write",
        action="store_true",
        help="Create or verify the exact local mapping-profile file.",
    )
    _add_workspace_argument(profile)
    profile.set_defaults(handler=_handle_profile, show_group_help=None)

    preview = subcommands.add_parser(
        "preview",
        help="Render current standards reconciliation and an optional checkpoint.",
    )
    preview.add_argument("class_id")
    preview.add_argument("school_year")
    preview.add_argument("period_id")
    preview.add_argument("calendar_revision", type=_positive_integer)
    preview.add_argument("--mapping-profile", type=Path, required=True)
    preview.add_argument("--prior-checkpoint", type=Path)
    preview.add_argument(
        "--view",
        choices=("auto", "full", "changed-only"),
        default="auto",
        help=(
            "auto uses changed-only when a prior checkpoint is supplied; otherwise "
            "it shows the full current view."
        ),
    )
    preview.add_argument(
        "--format",
        choices=("json", "markdown", "csv", "tsv"),
        default="tsv",
    )
    preview.add_argument("--generated-at", type=_datetime_argument)
    preview.add_argument("--output", type=Path)
    preview.add_argument(
        "--checkpoint-output",
        type=Path,
        help=(
            "Write the complete canonical current reconciliation preview for use "
            "as the next exact checkpoint."
        ),
    )
    _add_workspace_argument(preview)
    preview.set_defaults(handler=_handle_preview, show_group_help=None)

    reconciliation.set_defaults(show_group_help=reconciliation)


def _handle_profile(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        stored_scale = load_proficiency_scale_revision(
            args.workspace,
            args.class_id,
            args.scale_id,
            args.scale_revision,
        )
        profile = compose_external_gradebook_mapping_revision(
            class_id=args.class_id,
            profile_id=args.profile_id,
            profile_revision=args.profile_revision,
            title=args.title,
            system_label=args.system_label,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            target_scale=proficiency_scale_reference(stored_scale.scale),
            entries=tuple(
                ExternalGradebookMappingEntry(level_id, external_value)
                for level_id, external_value in args.map
            ),
            actor_id=args.actor_id,
            revised_at=args.revised_at,
            rationale=args.rationale,
        )
        validate_external_gradebook_mapping_against_scale(
            profile,
            stored_scale.scale,
        )
        content = external_gradebook_mapping_to_json_bytes(profile)
        reference = external_gradebook_mapping_reference(profile)
        if args.output is not None and args.confirm_write:
            disposition = write_or_verify_local_artifact(args.output, content)
            print(f"{disposition}: {args.output} sha256={reference.profile_sha256}")
            return 0
        if args.output is not None and not args.confirm_write:
            print(
                "preview only: --output was supplied but --confirm-write was not; "
                "no file was written.",
                file=sys.stderr,
            )
        sys.stdout.write(content.decode("utf-8"))
        return 0
    except (
        ExternalGradebookMappingError,
        ProficiencyMappingStorageError,
        ReportExportCommitError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _handle_preview(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        profile = external_gradebook_mapping_from_json_bytes(
            _read_bounded_file(args.mapping_profile, _MAX_MAPPING_BYTES)
        )
        if (
            profile.class_id != args.class_id
            or profile.target_period
            != AcademicPeriodRef(args.school_year, args.period_id)
        ):
            raise SisGradebookReconciliationError(
                "mapping profile does not match requested class/period."
            )
        stored_scale = load_proficiency_scale_revision(
            args.workspace,
            profile.target_scale.class_id,
            profile.target_scale.scale_id,
            profile.target_scale.scale_revision,
        )
        if stored_scale.scale_sha256 != profile.target_scale.scale_sha256:
            raise SisGradebookReconciliationError(
                "mapping profile scale digest does not match canonical scale."
            )
        validate_external_gradebook_mapping_against_scale(
            profile,
            stored_scale.scale,
        )
        stored_results = list_current_academic_period_proficiency_results(
            args.workspace,
            args.class_id,
            args.school_year,
            args.period_id,
        )
        observations = tuple(
            current_proficiency_observation(item) for item in stored_results
        )
        prior = (
            None
            if args.prior_checkpoint is None
            else teacher_report_preview_from_json_bytes(
                _read_bounded_file(args.prior_checkpoint, _MAX_CHECKPOINT_BYTES)
            )
        )
        changed_only = args.view == "changed-only" or (
            args.view == "auto" and prior is not None
        )
        generated_at = (
            datetime.now(UTC) if args.generated_at is None else args.generated_at
        )
        built = build_sis_gradebook_reconciliation(
            class_id=args.class_id,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            calendar_revision=args.calendar_revision,
            target_scale=stored_scale.scale,
            mapping_profile=profile,
            current_observations=observations,
            generated_at=generated_at,
            prior_checkpoint=prior,
            changed_only=changed_only,
        )
        payload = render_teacher_report(built.display_preview, args.format)
        checkpoint = teacher_report_preview_to_json_bytes(built.checkpoint_preview)
        if (
            args.output is not None
            and args.checkpoint_output is not None
            and args.output.resolve() == args.checkpoint_output.resolve()
        ):
            raise SisGradebookReconciliationError(
                "report output and checkpoint output must use different paths."
            )
        if args.output is None:
            sys.stdout.write(payload.decode("utf-8"))
        else:
            write_or_verify_local_artifact(args.output, payload)
        if args.checkpoint_output is not None:
            write_or_verify_local_artifact(args.checkpoint_output, checkpoint)
        return 0
    except (
        AcademicPeriodProficiencyStorageError,
        ExternalGradebookMappingError,
        ProficiencyMappingStorageError,
        ReportExportCommitError,
        SisGradebookReconciliationError,
        TeacherReportError,
        OSError,
        ValueError,
    ) as error:
        return _print_error(error)


def _read_bounded_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("input path must identify a regular non-symlink file.")
    if path.stat().st_size > maximum:
        raise ValueError("input file exceeds the configured maximum size.")
    content = path.read_bytes()
    if len(content) > maximum:
        raise ValueError("input file exceeds the configured maximum size.")
    return content


def _print_error(error: BaseException) -> int:
    code = getattr(error, "code", "sis_reconciliation.cli_error")
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


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Paper Data Suite workspace root; defaults to the current directory.",
    )


__all__ = ["register_sis_gradebook_reconciliation_cli"]
