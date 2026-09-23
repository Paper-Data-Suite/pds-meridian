"""Bounded development CLI surface for Meridian ReportingSnapshot state."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef, academic_period_ref_to_dict

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.diagnostics import (
    DiagnosticsDependencies,
    default_diagnostics_dependencies,
)
from meridian.grade_preview_comparison import grade_preview_comparison_to_dict
from meridian.grade_preview_explanation import GradePreviewError
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
    grade_report_preview_to_dict,
    grade_report_preview_to_json_bytes,
)
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    ProjectionCacheError,
    load_authorized_projection_snapshot,
)
from meridian.report_export_cli import register_report_export_cli
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
    ReportingSnapshotReference,
    ReportingSnapshotValidationError,
    reporting_definition_reference,
    reporting_definition_reference_to_dict,
    reporting_definition_revision_to_dict,
    reporting_snapshot_reference_to_dict,
)
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonError,
    compare_reporting_snapshot_to_grade_report_preview,
    load_reporting_snapshot_for_comparison,
)
from meridian.reporting_snapshot_freeze import (
    ReportingSnapshotFreezeError,
    freeze_reporting_snapshot,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshot,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotProjectionInputReference,
    ReportingSnapshotRequestValidationError,
    reporting_snapshot_build_request_from_json_bytes,
    reporting_snapshot_build_request_sha256,
    reporting_snapshot_to_dict,
)
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionError,
    ReportingSnapshotSelectionReference,
    get_current_reporting_snapshot_selection_reference,
    load_current_reporting_snapshot_selection,
    reporting_snapshot_selection_reference_to_dict,
    reporting_snapshot_selection_to_dict,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    list_reporting_definition_ids,
    list_reporting_definition_revisions,
    list_reporting_snapshot_ids,
    load_reporting_definition_revision,
    load_reporting_snapshot,
    write_reporting_definition_revision,
)


class ReportingSnapshotCliError(RuntimeError):
    """Stable CLI-facing error preserving the underlying #55 semantic code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


MAXIMUM_BUILD_REQUEST_BYTES = 2 * 1024 * 1024


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
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


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


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")


def _add_projection_authorization_argument(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument(
        "--projection-auth",
        action="append",
        nargs=4,
        default=[],
        metavar=("PUBLICATION_ID", "CACHE_KEY", "PURPOSE_ID", "STUDENTS"),
        help=(
            "Authorize one exact projection cache identity. STUDENTS is a "
            "comma-separated exact student scope, or '-' for an empty scope. "
            "Repeat for every available projection referenced by the build request."
        ),
    )


def add_reporting_snapshot_cli(
    groups: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the bounded issue #55 ReportingSnapshot development commands."""

    reporting = groups.add_parser(
        "reporting",
        help="Inspect and manage Meridian ReportingSnapshot development state.",
        description=(
            "Bounded issue #55 development commands for immutable report definitions, "
            "frozen ReportingSnapshots, and explicit current-use selection. This is "
            "local advisory reporting state, not an official district/SIS Grade."
        ),
    )
    commands = reporting.add_subparsers(dest="reporting_command")

    definitions = commands.add_parser(
        "definitions",
        help="List, inspect, or write immutable report-definition revisions.",
    )
    definition_commands = definitions.add_subparsers(dest="definition_command")

    definition_list = definition_commands.add_parser(
        "list",
        help="List stored immutable report-definition revisions for one class.",
    )
    definition_list.add_argument("class_id")
    _add_workspace_argument(definition_list)
    _add_format_argument(definition_list)
    definition_list.set_defaults(
        handler=_handle_definition_list,
        show_group_help=None,
    )

    definition_inspect = definition_commands.add_parser(
        "inspect",
        help="Inspect one exact digest-bound report-definition revision.",
    )
    definition_inspect.add_argument("class_id")
    definition_inspect.add_argument("definition_id")
    definition_inspect.add_argument("definition_revision", type=_positive_integer)
    definition_inspect.add_argument("definition_sha256", type=_sha256_argument)
    _add_workspace_argument(definition_inspect)
    _add_format_argument(definition_inspect)
    definition_inspect.set_defaults(
        handler=_handle_definition_inspect,
        show_group_help=None,
    )

    definition_write = definition_commands.add_parser(
        "write",
        help="Preview or persist one immutable report-definition revision.",
        description=(
            "Construct one exact v1 teacher Grade-report definition. Omit "
            "--confirm-write to preview the canonical definition and digest only."
        ),
    )
    definition_write.add_argument("class_id")
    definition_write.add_argument("definition_id")
    definition_write.add_argument("definition_revision", type=_positive_integer)
    definition_write.add_argument("school_year")
    definition_write.add_argument("period_id")
    definition_write.add_argument("--purpose", required=True)
    definition_write.add_argument("--title", required=True)
    definition_write.add_argument("--actor-id", required=True)
    definition_write.add_argument(
        "--revised-at",
        required=True,
        type=_datetime_argument,
    )
    definition_write.add_argument(
        "--supersedes-revision",
        type=_positive_integer,
    )
    definition_write.add_argument("--rationale")
    definition_write.add_argument(
        "--confirm-write",
        action="store_true",
        help="Persist the exact previewed definition revision.",
    )
    _add_workspace_argument(definition_write)
    _add_format_argument(definition_write)
    definition_write.set_defaults(
        handler=_handle_definition_write,
        show_group_help=None,
    )
    definitions.set_defaults(show_group_help=definitions)

    snapshots = commands.add_parser(
        "snapshots",
        help="List or inspect immutable frozen ReportingSnapshots.",
    )
    snapshot_commands = snapshots.add_subparsers(dest="snapshot_command")

    snapshot_list = snapshot_commands.add_parser(
        "list",
        help="List stored frozen ReportingSnapshots for one class.",
    )
    snapshot_list.add_argument("class_id")
    _add_workspace_argument(snapshot_list)
    _add_format_argument(snapshot_list)
    snapshot_list.set_defaults(handler=_handle_snapshot_list, show_group_help=None)

    snapshot_inspect = snapshot_commands.add_parser(
        "inspect",
        help="Inspect one exact digest-bound frozen ReportingSnapshot.",
    )
    snapshot_inspect.add_argument("class_id")
    snapshot_inspect.add_argument("snapshot_id")
    snapshot_inspect.add_argument("snapshot_sha256", type=_sha256_argument)
    _add_workspace_argument(snapshot_inspect)
    _add_format_argument(snapshot_inspect)
    snapshot_inspect.set_defaults(
        handler=_handle_snapshot_inspect,
        show_group_help=None,
    )

    snapshot_freeze = snapshot_commands.add_parser(
        "freeze",
        help="Preview or freeze one exact live Grade report as a ReportingSnapshot.",
        description=(
            "Reconstruct the explicit #54 Grade-report request from one canonical "
            "#55 build-request JSON document. Conventional/hybrid projection "
            "inputs are reopened only through exact authorization-gated cache "
            "identities. Omit --confirm-freeze for a read-only live preview."
        ),
    )
    snapshot_freeze.add_argument("snapshot_id")
    snapshot_freeze.add_argument("build_request", type=Path)
    snapshot_freeze.add_argument(
        "--created-at",
        required=True,
        type=_datetime_argument,
    )
    _add_projection_authorization_argument(snapshot_freeze)
    snapshot_freeze.add_argument(
        "--confirm-freeze",
        action="store_true",
        help="Commit the immutable snapshot after whole-report revalidation.",
    )
    _add_workspace_argument(snapshot_freeze)
    _add_format_argument(snapshot_freeze)
    snapshot_freeze.set_defaults(
        handler=_handle_snapshot_freeze,
        show_group_help=None,
    )

    snapshot_compare = snapshot_commands.add_parser(
        "compare",
        help="Compare one frozen snapshot with a live current Grade report.",
        description=(
            "Load one exact digest-bound ReportingSnapshot, reconstruct a live "
            "#54 report observation through authorized current inputs, and reuse "
            "the issue #54 semantic comparison engine. This command is read-only."
        ),
    )
    snapshot_compare.add_argument("class_id")
    snapshot_compare.add_argument("snapshot_id")
    snapshot_compare.add_argument("snapshot_sha256", type=_sha256_argument)
    snapshot_compare.add_argument(
        "--current-build-request",
        type=Path,
        help=(
            "Optional explicit current row/evidence request. Omit to reobserve the "
            "frozen snapshot's original explicit row set."
        ),
    )
    _add_projection_authorization_argument(snapshot_compare)
    _add_workspace_argument(snapshot_compare)
    _add_format_argument(snapshot_compare)
    snapshot_compare.set_defaults(
        handler=_handle_snapshot_compare,
        show_group_help=None,
    )
    snapshots.set_defaults(show_group_help=snapshots)

    selection = commands.add_parser(
        "selection",
        help="Inspect or explicitly change current-use ReportingSnapshot selection.",
    )
    selection_commands = selection.add_subparsers(dest="selection_command")

    selection_show = selection_commands.add_parser(
        "show",
        help="Inspect explicit current-use selection for one reporting scope.",
    )
    selection_show.add_argument("class_id")
    selection_show.add_argument("definition_id")
    selection_show.add_argument("school_year")
    selection_show.add_argument("period_id")
    selection_show.add_argument("calendar_revision", type=_positive_integer)
    _add_workspace_argument(selection_show)
    _add_format_argument(selection_show)
    selection_show.set_defaults(handler=_handle_selection_show, show_group_help=None)

    selection_select = selection_commands.add_parser(
        "select",
        help="Preview or explicitly select one exact snapshot for current use.",
        description=(
            "Current-use selection is separate mutable authority. Newest snapshot, "
            "timestamps, and predecessor relationships never select implicitly."
        ),
    )
    selection_select.add_argument("class_id")
    selection_select.add_argument("snapshot_id")
    selection_select.add_argument("snapshot_sha256", type=_sha256_argument)
    selection_select.add_argument("--actor-id", required=True)
    selection_select.add_argument(
        "--decided-at",
        required=True,
        type=_datetime_argument,
    )
    selection_select.add_argument("--rationale")
    expected = selection_select.add_mutually_exclusive_group(required=True)
    expected.add_argument(
        "--expect-none",
        action="store_true",
        help="Require that the exact reporting scope currently has no selection.",
    )
    expected.add_argument(
        "--expected-selection-revision",
        type=_positive_integer,
        help="Exact selector revision previously observed for digest-bound CAS.",
    )
    selection_select.add_argument(
        "--expected-selection-sha256",
        type=_sha256_argument,
        help="Exact digest paired with --expected-selection-revision.",
    )
    selection_select.add_argument(
        "--confirm-select",
        action="store_true",
        help="Commit the selection after exact current-state revalidation.",
    )
    _add_workspace_argument(selection_select)
    _add_format_argument(selection_select)
    selection_select.set_defaults(
        handler=_handle_selection_select,
        show_group_help=None,
    )
    selection.set_defaults(show_group_help=selection)
    register_report_export_cli(commands)
    reporting.set_defaults(show_group_help=reporting)


def _translate_error(error: Exception, fallback_code: str) -> ReportingSnapshotCliError:
    code = getattr(error, "code", fallback_code)
    return ReportingSnapshotCliError(str(code), str(error))


def _definition_candidate(args: argparse.Namespace) -> ReportingDefinitionRevision:
    try:
        return ReportingDefinitionRevision(
            schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
            record_type=REPORTING_DEFINITION_RECORD_TYPE,
            class_id=args.class_id,
            definition_id=args.definition_id,
            definition_revision=args.definition_revision,
            supersedes_revision=args.supersedes_revision,
            report_kind="grade_report",
            purpose=args.purpose,
            title=args.title,
            target_period=AcademicPeriodRef(args.school_year, args.period_id),
            intended_audience="teacher",
            actor=ReportingActor("teacher", args.actor_id),
            rationale=args.rationale,
            revised_at=args.revised_at,
        )
    except (ReportingSnapshotValidationError, ValueError, TypeError) as error:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.definition_invalid",
            str(error),
        ) from error


def _handle_definition_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        families = []
        definition_ids = list_reporting_definition_ids(
            args.workspace, args.class_id
        )
        for definition_id in definition_ids:
            revisions = list_reporting_definition_revisions(
                args.workspace,
                args.class_id,
                definition_id,
            )
            references = []
            for revision in revisions:
                stored = load_reporting_definition_revision(
                    args.workspace,
                    args.class_id,
                    definition_id,
                    revision,
                )
                references.append(
                    reporting_definition_reference_to_dict(
                        reporting_definition_reference(stored.definition)
                    )
                )
            families.append(
                {
                    "definition_id": definition_id,
                    "revisions": references,
                }
            )
    except ReportingSnapshotStorageError as error:
        raise _translate_error(error, "reporting_snapshot.error") from error

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_definitions",
        "class_id": args.class_id,
        "families": families,
        "current_definition_inference": "none",
    }
    if args.format == "json":
        _print_json(payload)
        return 0

    print("Meridian reporting definitions")
    print(f"class: {args.class_id}")
    print("authority: immutable stored revisions; no implicit current definition")
    if not families:
        print("definitions: none")
        return 0
    for family in families:
        family_revisions = family["revisions"]
        assert isinstance(family_revisions, list)
        revision_text = ", ".join(
            str(reference["definition_revision"])
            for reference in family_revisions
            if isinstance(reference, dict)
        )
        print(f"  {family['definition_id']}: revisions {revision_text}")
    return 0


def _handle_definition_inspect(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        stored = load_reporting_definition_revision(
            args.workspace,
            args.class_id,
            args.definition_id,
            args.definition_revision,
        )
    except ReportingSnapshotStorageError as error:
        raise _translate_error(error, "reporting_snapshot.error") from error
    if stored.definition_sha256 != args.definition_sha256:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.integrity_failed",
            "Requested reporting-definition digest does not match stored bytes.",
        )
    reference = reporting_definition_reference(stored.definition)
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_definition",
        "reference": reporting_definition_reference_to_dict(reference),
        "definition": reporting_definition_revision_to_dict(stored.definition),
        "relative_path": stored.relative_path,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian reporting definition")
    print(
        f"definition: {reference.definition_id} revision "
        f"{reference.definition_revision}"
    )
    print(f"sha256: {reference.definition_sha256}")
    print(f"class: {reference.class_id}")
    print(
        "target period: "
        f"{stored.definition.target_period.school_year}/"
        f"{stored.definition.target_period.period_id}"
    )
    print("authority: local Meridian report definition; not an official Grade")
    return 0


def _handle_definition_write(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    candidate = _definition_candidate(args)
    reference = reporting_definition_reference(candidate)
    disposition = "preview_only"
    if args.confirm_write:
        try:
            result = write_reporting_definition_revision(args.workspace, candidate)
        except ReportingSnapshotStorageError as error:
            raise _translate_error(error, "reporting_snapshot.error") from error
        disposition = result.disposition
        reference = reporting_definition_reference(result.stored.definition)

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_definition_write",
        "disposition": disposition,
        "reference": reporting_definition_reference_to_dict(reference),
        "definition": reporting_definition_revision_to_dict(candidate),
        "write_confirmed": bool(args.confirm_write),
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian reporting definition write")
    print(f"disposition: {disposition}")
    print(
        f"definition: {reference.definition_id} revision "
        f"{reference.definition_revision}"
    )
    print(f"sha256: {reference.definition_sha256}")
    if not args.confirm_write:
        print("NO REPORTING DEFINITION WRITTEN")
    print(
        "authority: local Meridian reporting state; "
        "not an official district/SIS Grade"
    )
    return 0


def _handle_snapshot_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        snapshots = []
        for snapshot_id in list_reporting_snapshot_ids(args.workspace, args.class_id):
            stored = load_reporting_snapshot(args.workspace, args.class_id, snapshot_id)
            snapshot = stored.snapshot
            snapshots.append(
                {
                    "reference": reporting_snapshot_reference_to_dict(stored.reference),
                    "definition_reference": reporting_definition_reference_to_dict(
                        snapshot.definition_reference
                    ),
                    "target_period": academic_period_ref_to_dict(
                        snapshot.target_period
                    ),
                    "calendar_revision": snapshot.calendar_revision,
                    "created_at": snapshot.created_at.astimezone(UTC).isoformat(),
                }
            )
    except ReportingSnapshotStorageError as error:
        raise _translate_error(error, "reporting_snapshot.error") from error

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_snapshots",
        "class_id": args.class_id,
        "snapshots": snapshots,
        "current_use_inference": "none",
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Frozen Meridian ReportingSnapshots")
    print(f"class: {args.class_id}")
    print("listing order is not current-use authority")
    if not snapshots:
        print("snapshots: none")
        return 0
    for item in snapshots:
        reference = item["reference"]
        assert isinstance(reference, dict)
        print(
            f"  {reference['snapshot_id']} | sha256={reference['snapshot_sha256']} | "
            f"created_at={item['created_at']}"
        )
    return 0


def _handle_snapshot_inspect(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    try:
        stored = load_reporting_snapshot(
            args.workspace,
            args.class_id,
            args.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise _translate_error(error, "reporting_snapshot.error") from error
    if stored.snapshot_sha256 != args.snapshot_sha256:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.integrity_failed",
            "Requested ReportingSnapshot digest does not match stored bytes.",
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "frozen_reporting_snapshot",
        "reference": reporting_snapshot_reference_to_dict(stored.reference),
        "snapshot": reporting_snapshot_to_dict(stored.snapshot),
        "relative_path": stored.relative_path,
        "official_system_authority": False,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    snapshot = stored.snapshot
    print("Frozen Meridian ReportingSnapshot")
    print(f"snapshot: {snapshot.snapshot_id}")
    print(f"sha256: {stored.snapshot_sha256}")
    print(
        "definition: "
        f"{snapshot.definition_reference.definition_id} revision "
        f"{snapshot.definition_reference.definition_revision}"
    )
    print(
        "target period: "
        f"{snapshot.target_period.school_year}/{snapshot.target_period.period_id} "
        f"calendar revision {snapshot.calendar_revision}"
    )
    print(f"rows: {len(snapshot.report_preview.rows)}")
    print(
        "authority: frozen local reporting observation; "
        "not an official district/SIS Grade"
    )
    return 0


def _read_build_request_file(path: Path) -> ReportingSnapshotBuildRequest:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            "Build-request JSON file cannot be resolved.",
        ) from error
    if path.is_symlink() or not resolved.is_file():
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            "Build-request JSON must be one regular non-symlink file.",
        )
    try:
        size = resolved.stat().st_size
    except OSError as error:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            "Build-request JSON size cannot be inspected.",
        ) from error
    if size > MAXIMUM_BUILD_REQUEST_BYTES:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            "Build-request JSON exceeds the bounded CLI input limit.",
        )
    try:
        data = resolved.read_bytes()
        return reporting_snapshot_build_request_from_json_bytes(data)
    except (OSError, ReportingSnapshotRequestValidationError) as error:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            f"Build-request JSON is invalid: {error}",
        ) from error


def _projection_authorizations(
    raw_values: list[list[str]],
) -> dict[tuple[str, str], tuple[str, tuple[str, ...]]]:
    rows = tuple(raw_values)
    result: dict[tuple[str, str], tuple[str, tuple[str, ...]]] = {}
    for raw in rows:
        try:
            publication_id, cache_key, purpose_id, students_text = tuple(raw)
        except (TypeError, ValueError) as error:
            raise ReportingSnapshotCliError(
                "reporting_snapshot.request_invalid",
                "Each --projection-auth requires exactly four values.",
            ) from error
        if not all(
            isinstance(value, str)
            for value in (publication_id, cache_key, purpose_id, students_text)
        ):
            raise ReportingSnapshotCliError(
                "reporting_snapshot.request_invalid",
                "Projection authorization values must be text.",
            )
        try:
            exact_cache_key = _sha256_argument(cache_key)
        except argparse.ArgumentTypeError as error:
            raise ReportingSnapshotCliError(
                "reporting_snapshot.request_invalid",
                str(error),
            ) from error
        if not publication_id or not purpose_id:
            raise ReportingSnapshotCliError(
                "reporting_snapshot.request_invalid",
                "Projection publication and purpose identifiers must be nonempty.",
            )
        if students_text == "-":
            students: tuple[str, ...] = ()
        else:
            parts = tuple(students_text.split(","))
            if not parts or any(not item for item in parts):
                raise ReportingSnapshotCliError(
                    "reporting_snapshot.request_invalid",
                    "Projection student scope must use nonempty comma-separated IDs.",
                )
            students = tuple(sorted(parts))
            if len(set(students)) != len(students):
                raise ReportingSnapshotCliError(
                    "reporting_snapshot.request_invalid",
                    "Projection student scope must not contain duplicates.",
                )
        key = (publication_id, exact_cache_key)
        if key in result:
            raise ReportingSnapshotCliError(
                "reporting_snapshot.request_invalid",
                "Projection authorization must not duplicate "
                "publication/cache identity.",
            )
        result[key] = (purpose_id, students)
    return result


def _effective_dependencies(
    supplied: DiagnosticsDependencies | None,
) -> DiagnosticsDependencies:
    return supplied if supplied is not None else default_diagnostics_dependencies()


def _load_live_projection(
    workspace: Path,
    reference: ReportingSnapshotProjectionInputReference,
    authorizations: dict[tuple[str, str], tuple[str, tuple[str, ...]]],
    dependencies: DiagnosticsDependencies | None,
) -> AuthorizedProjectionSnapshot:
    key = (reference.publication_id, reference.cache_key)
    authorization = authorizations.get(key)
    if authorization is None:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.source_unavailable",
            "Missing --projection-auth for an available build-request projection.",
        )
    effective = _effective_dependencies(dependencies)
    authorizer = effective.authorizer
    if authorizer is None:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.source_unavailable",
            "Live reporting projection access requires a deployment authorizer.",
        )
    registry = effective.producer_registry
    if effective.producer_registry_state != "available" or registry is None:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.source_unavailable",
            "Live reporting projection access requires an available producer registry.",
        )
    purpose_id, student_ids = authorization
    try:
        authorized = load_authorized_projection_snapshot(
            workspace,
            reference.publication_id,
            reference.cache_key,
            authorizer=authorizer,
            authorization_purpose_id=purpose_id,
            requested_student_ids=student_ids,
            producer_registry=registry,
            adapter_registry=effective.adapter_registry,
            distribution_version_resolver=effective.distribution_version_resolver,
        )
    except ProjectionCacheError as error:
        raise _translate_error(
            error,
            "reporting_snapshot.source_unavailable",
        ) from error
    if authorized.stored.snapshot_digest != reference.snapshot_digest:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.integrity_failed",
            "Authorized projection digest does not match build-request identity.",
        )
    return authorized


def _preview_requests_from_build_request(
    workspace: Path,
    build_request: ReportingSnapshotBuildRequest,
    raw_authorizations: list[list[str]],
    dependencies: DiagnosticsDependencies | None,
) -> tuple[GradeReportPreviewRequest, ...]:
    authorizations = _projection_authorizations(raw_authorizations)
    used: set[tuple[str, str]] = set()
    requests: list[GradeReportPreviewRequest] = []
    for grade_request in build_request.grade_requests:
        evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None
        if grade_request.work_evidence is None:
            evidence = None
        else:
            specs: list[ConventionalGradeWorkEvidenceSpec] = []
            for item in grade_request.work_evidence:
                snapshots: list[AuthorizedProjectionSnapshot] = []
                for reference in item.projection_snapshots:
                    key = (reference.publication_id, reference.cache_key)
                    snapshots.append(
                        _load_live_projection(
                            workspace,
                            reference,
                            authorizations,
                            dependencies,
                        )
                    )
                    used.add(key)
                specs.append(
                    ConventionalGradeWorkEvidenceSpec(
                        grade_item_id=item.grade_item_id,
                        work=item.work,
                        status=item.status,
                        authorized_snapshots=tuple(snapshots),
                    )
                )
            evidence = tuple(specs)
        requests.append(
            GradeReportPreviewRequest(
                target=grade_request.target,
                work_evidence=evidence,
            )
        )
    unused = sorted(set(authorizations) - used)
    if unused:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.request_invalid",
            "One or more --projection-auth values are not referenced by the request.",
        )
    return tuple(requests)


def _require_compare_request_scope(
    snapshot: ReportingSnapshot,
    request: ReportingSnapshotBuildRequest,
) -> None:
    class_id = getattr(snapshot, "class_id", None)
    target_period = getattr(snapshot, "target_period", None)
    calendar_revision = getattr(snapshot, "calendar_revision", None)
    for grade_request in request.grade_requests:
        target = grade_request.target
        if (
            target.class_id != class_id
            or target.target_period != target_period
            or target.calendar_revision != calendar_revision
        ):
            raise ReportingSnapshotCliError(
                "reporting_snapshot.comparison_invalid",
                "Current comparison request is outside the frozen snapshot scope.",
            )


def _handle_snapshot_freeze(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    build_request = _read_build_request_file(args.build_request)
    live_requests = _preview_requests_from_build_request(
        args.workspace,
        build_request,
        args.projection_auth,
        dependencies,
    )
    build_digest = reporting_snapshot_build_request_sha256(build_request)
    if args.confirm_freeze:
        try:
            stored = freeze_reporting_snapshot(
                args.workspace,
                snapshot_id=args.snapshot_id,
                build_request=build_request,
                preview_requests=live_requests,
                created_at=args.created_at,
            )
        except ReportingSnapshotFreezeError as error:
            raise _translate_error(error, "reporting_snapshot.error") from error
        payload: dict[str, object] = {
            "schema_version": 1,
            "surface": "reporting_snapshot_freeze",
            "disposition": "committed_or_exact_replay",
            "build_request_sha256": build_digest,
            "snapshot_reference": reporting_snapshot_reference_to_dict(
                stored.reference
            ),
            "report_preview_sha256": stored.snapshot.report_preview_sha256,
            "row_count": len(stored.snapshot.report_preview.rows),
            "freeze_confirmed": True,
            "official_system_authority": False,
        }
    else:
        try:
            preview = explain_grade_report_preview(args.workspace, live_requests)
        except GradePreviewError as error:
            raise _translate_error(error, "reporting_snapshot.error") from error
        preview_bytes = grade_report_preview_to_json_bytes(preview)
        payload = {
            "schema_version": 1,
            "surface": "reporting_snapshot_freeze",
            "disposition": "preview_only",
            "snapshot_id": args.snapshot_id,
            "build_request_sha256": build_digest,
            "live_grade_report": grade_report_preview_to_dict(preview),
            "live_grade_report_sha256": hashlib.sha256(preview_bytes).hexdigest(),
            "freeze_confirmed": False,
            "official_system_authority": False,
        }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian ReportingSnapshot freeze")
    print(f"disposition: {payload['disposition']}")
    print(f"build request sha256: {build_digest}")
    if args.confirm_freeze:
        reference = payload["snapshot_reference"]
        assert isinstance(reference, dict)
        print(
            "frozen snapshot: "
            f"{reference['snapshot_id']} ({reference['snapshot_sha256']})"
        )
    else:
        print("live/current Grade report observed; NO REPORTING SNAPSHOT WRITTEN")
    print(
        "authority: live/frozen Meridian reporting state; "
        "not an official district/SIS Grade"
    )
    return 0


def _handle_snapshot_compare(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    reference = ReportingSnapshotReference(
        class_id=args.class_id,
        snapshot_id=args.snapshot_id,
        snapshot_sha256=args.snapshot_sha256,
    )
    try:
        stored = load_reporting_snapshot_for_comparison(args.workspace, reference)
    except ReportingSnapshotComparisonError as error:
        raise _translate_error(error, "reporting_snapshot.comparison_error") from error
    current_request = (
        stored.snapshot.build_request
        if args.current_build_request is None
        else _read_build_request_file(args.current_build_request)
    )
    _require_compare_request_scope(stored.snapshot, current_request)
    live_requests = _preview_requests_from_build_request(
        args.workspace,
        current_request,
        args.projection_auth,
        dependencies,
    )
    try:
        current_preview = explain_grade_report_preview(args.workspace, live_requests)
        comparisons = compare_reporting_snapshot_to_grade_report_preview(
            stored.snapshot,
            current_preview,
        )
    except (GradePreviewError, ReportingSnapshotComparisonError) as error:
        raise _translate_error(error, "reporting_snapshot.comparison_error") from error
    rows = [grade_preview_comparison_to_dict(item) for item in comparisons]
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_snapshot_live_comparison",
        "snapshot_reference": reporting_snapshot_reference_to_dict(reference),
        "live_grade_report": grade_report_preview_to_dict(current_preview),
        "comparisons": rows,
        "comparison_engine": "issue_54_grade_preview_comparison",
        "read_only": True,
        "official_system_authority": False,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Frozen ReportingSnapshot versus live/current Grade report")
    print(f"snapshot: {reference.snapshot_id} ({reference.snapshot_sha256})")
    print("comparison engine: existing issue #54 Grade-preview comparison")
    if not rows:
        print("comparisons: none")
    else:
        for row in rows:
            relationship = row["relationship"]
            reasons = row["reasons"]
            assert isinstance(reasons, list)
            reason_text = ", ".join(str(item) for item in reasons) or "none"
            print(f"  {relationship} | reasons={reason_text}")
    print("read-only: yes; no snapshot or Grade state changed")
    print("authority: comparison is not an official district/SIS Grade")
    return 0


def _handle_selection_show(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    period = AcademicPeriodRef(args.school_year, args.period_id)
    try:
        stored = load_current_reporting_snapshot_selection(
            args.workspace,
            args.class_id,
            args.definition_id,
            period,
            args.calendar_revision,
        )
    except ReportingSnapshotSelectionError as error:
        raise _translate_error(error, "reporting_snapshot.selection_error") from error

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_snapshot_current_use_selection",
        "scope": {
            "class_id": args.class_id,
            "definition_id": args.definition_id,
            "target_period": academic_period_ref_to_dict(period),
            "calendar_revision": args.calendar_revision,
        },
        "selection": (
            None
            if stored is None
            else reporting_snapshot_selection_to_dict(stored.selection)
        ),
        "selection_reference": (
            None
            if stored is None
            else reporting_snapshot_selection_reference_to_dict(stored.reference)
        ),
        "official_system_authority": False,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian ReportingSnapshot current-use selection")
    if stored is None:
        print("currently selected snapshot for reporting use: none")
    else:
        reference = stored.selection.snapshot_reference
        print(
            "currently selected snapshot for reporting use: "
            f"{reference.snapshot_id} ({reference.snapshot_sha256})"
        )
        print(f"selection revision: {stored.selection.selection_revision}")
        print(f"selection sha256: {stored.selection_sha256}")
    print(
        "authority: local reporting-use selection; "
        "not an official district/SIS Grade"
    )
    return 0


def _selection_expected_reference(
    args: argparse.Namespace,
    snapshot_reference: ReportingSnapshotReference,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> ReportingSnapshotSelectionReference | None:
    if args.expect_none:
        if args.expected_selection_sha256 is not None:
            raise ReportingSnapshotCliError(
                "reporting_snapshot.selection_invalid",
                "--expect-none cannot be combined with --expected-selection-sha256.",
            )
        return None
    if args.expected_selection_revision is None:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.selection_invalid",
            "Expected selector revision is required unless --expect-none is used.",
        )
    if args.expected_selection_sha256 is None:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.selection_invalid",
            "--expected-selection-sha256 is required with selector revision.",
        )
    return ReportingSnapshotSelectionReference(
        class_id=snapshot_reference.class_id,
        definition_id=definition_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        selection_revision=args.expected_selection_revision,
        selection_sha256=args.expected_selection_sha256,
    )


def _handle_selection_select(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    requested_reference = ReportingSnapshotReference(
        class_id=args.class_id,
        snapshot_id=args.snapshot_id,
        snapshot_sha256=args.snapshot_sha256,
    )
    try:
        target = load_reporting_snapshot(
            args.workspace,
            requested_reference.class_id,
            requested_reference.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise _translate_error(error, "reporting_snapshot.error") from error
    if target.reference != requested_reference:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.integrity_failed",
            "Requested ReportingSnapshot digest does not match stored bytes.",
        )
    snapshot = target.snapshot
    expected = _selection_expected_reference(
        args,
        requested_reference,
        snapshot.definition_reference.definition_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    try:
        observed = get_current_reporting_snapshot_selection_reference(
            args.workspace,
            snapshot.class_id,
            snapshot.definition_reference.definition_id,
            snapshot.target_period,
            snapshot.calendar_revision,
        )
    except ReportingSnapshotSelectionError as error:
        raise _translate_error(error, "reporting_snapshot.selection_error") from error
    if observed != expected:
        raise ReportingSnapshotCliError(
            "reporting_snapshot.selection_conflict",
            "Current ReportingSnapshot selection differs from expected CAS state.",
        )

    disposition = "preview_only"
    selection_reference = observed
    if args.confirm_select:
        try:
            result = select_reporting_snapshot(
                args.workspace,
                requested_reference,
                actor=ReportingActor("teacher", args.actor_id),
                rationale=args.rationale,
                decided_at=args.decided_at,
                expected_current=expected,
            )
        except ReportingSnapshotSelectionError as error:
            raise _translate_error(
                error, "reporting_snapshot.selection_error"
            ) from error
        disposition = result.disposition
        selection_reference = result.selection.reference

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "reporting_snapshot_selection_change",
        "disposition": disposition,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            requested_reference
        ),
        "expected_current": (
            None
            if expected is None
            else reporting_snapshot_selection_reference_to_dict(expected)
        ),
        "resulting_selection_reference": (
            None
            if selection_reference is None
            else reporting_snapshot_selection_reference_to_dict(selection_reference)
        ),
        "selection_confirmed": bool(args.confirm_select),
        "official_system_authority": False,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian ReportingSnapshot current-use selection")
    print(f"disposition: {disposition}")
    print(
        "target snapshot: "
        f"{requested_reference.snapshot_id} ({requested_reference.snapshot_sha256})"
    )
    if not args.confirm_select:
        print("NO CURRENT-USE SELECTION WRITTEN")
    print(
        "authority: local reporting-use selection; "
        "not an official district/SIS Grade"
    )
    return 0


def _print_json(value: dict[str, object]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


__all__ = [
    "ReportingSnapshotCliError",
    "add_reporting_snapshot_cli",
]
