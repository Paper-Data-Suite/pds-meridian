"""Bounded direct CLI for Meridian v0.3 report-export state."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from meridian.diagnostics import DiagnosticsDependencies
from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileReference,
    ExportProfileRevision,
    ExportRepresentation,
    export_profile_reference,
    export_profile_reference_to_dict,
    export_profile_revision_to_dict,
)
from meridian.export_profile_storage import (
    ExportProfileSelectionReference,
    ExportProfileStorageError,
    export_profile_selection_reference_to_dict,
    export_profile_selection_to_dict,
    get_current_export_profile_selection_reference,
    list_export_profile_ids,
    list_export_profile_revisions,
    load_current_export_profile_selection,
    load_export_profile_reference,
    load_export_profile_revision,
    select_export_profile,
    write_export_profile_revision,
)
from meridian.report_export_commit import (
    ReportExportCommitError,
    commit_report_export,
    copyable_text_destination,
    file_export_destination,
)
from meridian.report_export_preview import (
    BuiltExportPreview,
    ReportExportPreviewError,
    build_export_preview,
    export_preview_to_dict,
)
from meridian.report_export_receipt import (
    ReportExportActor,
    ReportExportReceiptError,
    export_receipt_to_dict,
    list_export_receipt_ids,
    load_export_receipt,
)
from meridian.reporting_snapshot import ReportingSnapshotReference


class ReportExportCliError(RuntimeError):
    """Stable CLI-facing #56 error with one structured code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def register_report_export_cli(
    reporting_commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register issue #56 subcommands under ``meridian reporting``."""

    profiles = reporting_commands.add_parser(
        "export-profiles",
        help="List, inspect, write, and select immutable Export Profiles.",
        description=(
            "Manage class-local immutable Export Profile revisions. Profile "
            "selection is separate mutable convenience state; exports always bind "
            "one exact digest-bound profile revision."
        ),
    )
    profile_commands = profiles.add_subparsers(dest="export_profile_command")

    profile_list = profile_commands.add_parser(
        "list",
        help="List verified Export Profile families and immutable revisions.",
    )
    profile_list.add_argument("class_id")
    _add_workspace_argument(profile_list)
    _add_format_argument(profile_list)
    profile_list.set_defaults(
        handler=_handle_profile_list,
        show_group_help=None,
    )

    profile_inspect = profile_commands.add_parser(
        "inspect",
        help="Inspect one exact digest-bound Export Profile revision.",
    )
    profile_inspect.add_argument("class_id")
    profile_inspect.add_argument("profile_id")
    profile_inspect.add_argument("profile_revision", type=_positive_integer)
    profile_inspect.add_argument("profile_sha256", type=_sha256_argument)
    _add_workspace_argument(profile_inspect)
    _add_format_argument(profile_inspect)
    profile_inspect.set_defaults(
        handler=_handle_profile_inspect,
        show_group_help=None,
    )

    profile_write = profile_commands.add_parser(
        "write",
        help="Preview or persist one immutable Export Profile revision.",
        description=(
            "Construct one bounded v1 Export Profile. Omit --confirm-write to "
            "preview the exact canonical profile and digest without mutation."
        ),
    )
    profile_write.add_argument("class_id")
    profile_write.add_argument("profile_id")
    profile_write.add_argument("profile_revision", type=_positive_integer)
    profile_write.add_argument("--title", required=True)
    profile_write.add_argument("--purpose", required=True)
    profile_write.add_argument(
        "--column",
        nargs=2,
        action="append",
        required=True,
        metavar=("SOURCE_FIELD", "OUTPUT_NAME"),
        help="Select one exact source field and output header; repeat in order.",
    )
    profile_write.add_argument(
        "--output-format",
        choices=("csv", "tsv"),
        required=True,
    )
    profile_write.add_argument(
        "--include-header",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    profile_write.add_argument(
        "--line-ending",
        choices=("lf", "crlf"),
        default="lf",
    )
    profile_write.add_argument(
        "--utf8-bom",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    profile_write.add_argument("--actor-id", required=True)
    profile_write.add_argument(
        "--revised-at",
        required=True,
        type=_datetime_argument,
    )
    profile_write.add_argument(
        "--supersedes-revision",
        type=_positive_integer,
    )
    profile_write.add_argument("--rationale")
    profile_write.add_argument(
        "--confirm-write",
        action="store_true",
        help="Persist this exact immutable profile revision.",
    )
    _add_workspace_argument(profile_write)
    _add_format_argument(profile_write)
    profile_write.set_defaults(
        handler=_handle_profile_write,
        show_group_help=None,
    )

    profile_current = profile_commands.add_parser(
        "current",
        help="Inspect the explicit current Export Profile selection.",
    )
    profile_current.add_argument("class_id")
    profile_current.add_argument("profile_id")
    _add_workspace_argument(profile_current)
    _add_format_argument(profile_current)
    profile_current.set_defaults(
        handler=_handle_profile_current,
        show_group_help=None,
    )

    profile_select = profile_commands.add_parser(
        "select",
        help="Preview or CAS-select one exact stored profile revision.",
    )
    profile_select.add_argument("class_id")
    profile_select.add_argument("profile_id")
    profile_select.add_argument("profile_revision", type=_positive_integer)
    profile_select.add_argument("profile_sha256", type=_sha256_argument)
    profile_select.add_argument("--actor-id", required=True)
    profile_select.add_argument(
        "--decided-at",
        required=True,
        type=_datetime_argument,
    )
    profile_select.add_argument("--rationale")
    expected = profile_select.add_mutually_exclusive_group(required=True)
    expected.add_argument("--expect-none", action="store_true")
    expected.add_argument(
        "--expected-selection-revision",
        type=_positive_integer,
    )
    profile_select.add_argument(
        "--expected-selection-sha256",
        type=_sha256_argument,
    )
    profile_select.add_argument(
        "--confirm-select",
        action="store_true",
        help="CAS-select the exact profile after current-state verification.",
    )
    _add_workspace_argument(profile_select)
    _add_format_argument(profile_select)
    profile_select.set_defaults(
        handler=_handle_profile_select,
        show_group_help=None,
    )
    profiles.set_defaults(show_group_help=profiles)

    exports = reporting_commands.add_parser(
        "exports",
        help="Preview or explicitly commit a local snapshot-backed report export.",
        description=(
            "Build exports only from one exact frozen ReportingSnapshot and one "
            "exact immutable Export Profile. Local export is not SIS/LMS posting "
            "and carries no external-system acceptance claim."
        ),
    )
    export_commands = exports.add_subparsers(dest="report_export_command")

    export_preview = export_commands.add_parser(
        "preview",
        help="Show the exact outgoing logical rows and serialized payload.",
    )
    _add_exact_export_source_arguments(export_preview)
    export_preview.add_argument(
        "--payload-only",
        action="store_true",
        help="Write only the exact payload bytes to stdout; requires text format.",
    )
    _add_workspace_argument(export_preview)
    _add_format_argument(export_preview)
    export_preview.set_defaults(
        handler=_handle_export_preview,
        show_group_help=None,
    )

    export_commit = export_commands.add_parser(
        "commit",
        help="Preview or explicitly commit one teacher-approved exact export.",
        description=(
            "Rebuild one exact export and require the teacher-reviewed preview "
            "SHA-256. Omit --confirm-export for a read-only commit preview."
        ),
    )
    _add_exact_export_source_arguments(export_commit)
    export_commit.add_argument(
        "--approved-preview-sha256",
        required=True,
        type=_sha256_argument,
    )
    export_commit.add_argument("--export-id", required=True)
    export_commit.add_argument("--actor-id", required=True)
    export_commit.add_argument(
        "--exported-at",
        required=True,
        type=_datetime_argument,
    )
    export_commit.add_argument("--rationale")
    destination = export_commit.add_mutually_exclusive_group(required=True)
    destination.add_argument("--file", type=Path)
    destination.add_argument("--copyable-text", action="store_true")
    export_commit.add_argument(
        "--confirm-export",
        action="store_true",
        help="Create/verify the local payload and immutable ExportReceipt.",
    )
    export_commit.add_argument(
        "--payload-only",
        action="store_true",
        help=(
            "For copyable-text export, write only exact payload bytes to stdout; "
            "requires --confirm-export and text format."
        ),
    )
    _add_workspace_argument(export_commit)
    _add_format_argument(export_commit)
    export_commit.set_defaults(
        handler=_handle_export_commit,
        show_group_help=None,
    )
    exports.set_defaults(show_group_help=exports)

    receipts = reporting_commands.add_parser(
        "export-receipts",
        help="List or inspect immutable local ExportReceipts.",
    )
    receipt_commands = receipts.add_subparsers(dest="export_receipt_command")

    receipt_list = receipt_commands.add_parser(
        "list",
        help="List verified immutable ExportReceipts for one class.",
    )
    receipt_list.add_argument("class_id")
    _add_workspace_argument(receipt_list)
    _add_format_argument(receipt_list)
    receipt_list.set_defaults(
        handler=_handle_receipt_list,
        show_group_help=None,
    )

    receipt_inspect = receipt_commands.add_parser(
        "inspect",
        help="Inspect one exact digest-bound immutable ExportReceipt.",
    )
    receipt_inspect.add_argument("class_id")
    receipt_inspect.add_argument("export_id")
    receipt_inspect.add_argument("receipt_sha256", type=_sha256_argument)
    _add_workspace_argument(receipt_inspect)
    _add_format_argument(receipt_inspect)
    receipt_inspect.set_defaults(
        handler=_handle_receipt_inspect,
        show_group_help=None,
    )
    receipts.set_defaults(show_group_help=receipts)


def _add_exact_export_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("class_id")
    parser.add_argument("snapshot_id")
    parser.add_argument("snapshot_sha256", type=_sha256_argument)
    parser.add_argument("profile_id")
    parser.add_argument("profile_revision", type=_positive_integer)
    parser.add_argument("profile_sha256", type=_sha256_argument)


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Paper Data Suite workspace root; defaults to the current directory.",
    )


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")


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


def _handle_profile_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        families: list[dict[str, object]] = []
        for profile_id in list_export_profile_ids(args.workspace, args.class_id):
            revision_references: list[dict[str, object]] = []
            for revision in list_export_profile_revisions(
                args.workspace,
                args.class_id,
                profile_id,
            ):
                stored = load_export_profile_revision(
                    args.workspace,
                    args.class_id,
                    profile_id,
                    revision,
                )
                revision_references.append(
                    export_profile_reference_to_dict(stored.reference)
                )
            stored_current = load_current_export_profile_selection(
                args.workspace,
                args.class_id,
                profile_id,
            )
            families.append(
                {
                    "profile_id": profile_id,
                    "revisions": revision_references,
                    "current_selection": (
                        None
                        if stored_current is None
                        else export_profile_selection_to_dict(
                            stored_current.selection
                        )
                    ),
                    "current_selection_sha256": (
                        None
                        if stored_current is None
                        else stored_current.selection_sha256
                    ),
                }
            )
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error

    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "export_profiles",
        "class_id": args.class_id,
        "families": families,
        "newest_revision_inference": "none",
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian Export Profiles")
    print(f"class: {args.class_id}")
    print("authority: immutable revisions + explicit current selector")
    if not families:
        print("profiles: none")
        return 0
    for family in families:
        revisions_data = family["revisions"]
        assert isinstance(revisions_data, list)
        revision_text = ", ".join(
            str(item["profile_revision"])
            for item in revisions_data
            if isinstance(item, dict)
        )
        current_data = family["current_selection"]
        current_text = "none"
        if isinstance(current_data, dict):
            selected = current_data["profile_reference"]
            if isinstance(selected, dict):
                current_text = str(selected["profile_revision"])
        print(
            f"  {family['profile_id']}: revisions {revision_text}; "
            f"current={current_text}"
        )
    return 0


def _handle_profile_inspect(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    reference = ExportProfileReference(
        args.class_id,
        args.profile_id,
        args.profile_revision,
        args.profile_sha256,
    )
    try:
        stored = load_export_profile_reference(args.workspace, reference)
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error
    payload = {
        "schema_version": 1,
        "surface": "export_profile",
        "reference": export_profile_reference_to_dict(stored.reference),
        "profile": export_profile_revision_to_dict(stored.profile),
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian Export Profile")
    print(
        f"exact profile: {stored.profile.profile_id}@"
        f"{stored.profile.profile_revision}"
    )
    print(f"profile SHA-256: {stored.profile_sha256}")
    print(f"title: {stored.profile.title}")
    print(f"purpose: {stored.profile.purpose}")
    print(f"format: {stored.profile.representation.format}")
    print("columns:")
    for column in stored.profile.columns:
        print(f"  {column.output_name} <- {column.source_field}")
    print("This local profile does not write an external school system.")
    return 0


def _profile_candidate(args: argparse.Namespace) -> ExportProfileRevision:
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=args.class_id,
        profile_id=args.profile_id,
        profile_revision=args.profile_revision,
        supersedes_revision=args.supersedes_revision,
        title=args.title,
        purpose=args.purpose,
        columns=tuple(
            ExportColumn(source_field, output_name)
            for source_field, output_name in args.column
        ),
        representation=ExportRepresentation(
            format=args.output_format,
            include_header=args.include_header,
            line_ending=args.line_ending,
            utf8_bom=args.utf8_bom,
        ),
        actor=ExportProfileActor("teacher", args.actor_id),
        rationale=args.rationale,
        revised_at=args.revised_at,
    )


def _handle_profile_write(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        candidate = _profile_candidate(args)
        reference = export_profile_reference(candidate)
    except ValueError as error:
        raise ReportExportCliError("export_profile.invalid", str(error)) from error
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "export_profile_write",
        "write_confirmed": args.confirm_write,
        "reference": export_profile_reference_to_dict(reference),
        "profile": export_profile_revision_to_dict(candidate),
        "selection_action": "not_performed",
    }
    if not args.confirm_write:
        _render_profile_write(payload, args.format, disposition=None)
        return 0
    try:
        result = write_export_profile_revision(args.workspace, candidate)
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error
    _render_profile_write(payload, args.format, disposition=result.disposition)
    return 0


def _render_profile_write(
    payload: dict[str, object],
    output_format: str,
    *,
    disposition: str | None,
) -> None:
    if output_format == "json":
        result = dict(payload)
        result["write_disposition"] = disposition
        _print_json(result)
        return
    reference = payload["reference"]
    assert isinstance(reference, dict)
    print("Export Profile revision preview")
    print(
        f"exact profile: {reference['profile_id']}@"
        f"{reference['profile_revision']}"
    )
    print(f"profile SHA-256: {reference['profile_sha256']}")
    if disposition is None:
        print("confirmation supplied: no")
        print("NO EXPORT PROFILE REVISION WRITTEN")
    else:
        print("confirmation supplied: yes")
        print(f"profile write disposition: {disposition}")
    print("NO CURRENT PROFILE SELECTION CHANGED")
    print("NO REPORT EXPORT PERFORMED")


def _handle_profile_current(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        current = load_current_export_profile_selection(
            args.workspace,
            args.class_id,
            args.profile_id,
        )
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "export_profile_current",
        "class_id": args.class_id,
        "profile_id": args.profile_id,
        "selection": (
            None
            if current is None
            else export_profile_selection_to_dict(current.selection)
        ),
        "selection_sha256": None if current is None else current.selection_sha256,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian Export Profile current selection")
    print(f"class/profile: {args.class_id}/{args.profile_id}")
    if current is None:
        print("selection: none")
    else:
        selected = current.selection.profile_reference
        print(
            f"selected profile: {selected.profile_id}@"
            f"{selected.profile_revision}"
        )
        print(f"profile SHA-256: {selected.profile_sha256}")
        print(f"selection revision: {current.selection.selection_revision}")
        print(f"selection SHA-256: {current.selection_sha256}")
    return 0


def _expected_selection(
    args: argparse.Namespace,
) -> ExportProfileSelectionReference | None:
    if args.expect_none:
        if args.expected_selection_sha256 is not None:
            raise ReportExportCliError(
                "export_profile.selection_invalid",
                "--expect-none cannot be combined with selection SHA-256.",
            )
        return None
    revision = args.expected_selection_revision
    digest = args.expected_selection_sha256
    if revision is None or digest is None:
        raise ReportExportCliError(
            "export_profile.selection_invalid",
            "Expected selection requires both revision and SHA-256.",
        )
    return ExportProfileSelectionReference(
        args.class_id,
        args.profile_id,
        revision,
        digest,
    )


def _handle_profile_select(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    target = ExportProfileReference(
        args.class_id,
        args.profile_id,
        args.profile_revision,
        args.profile_sha256,
    )
    expected = _expected_selection(args)
    try:
        load_export_profile_reference(args.workspace, target)
        actual = get_current_export_profile_selection_reference(
            args.workspace,
            args.class_id,
            args.profile_id,
        )
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error
    if actual != expected:
        raise ReportExportCliError(
            "export_profile.selection_conflict",
            "Observed current Export Profile selector does not match CAS expectation.",
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "surface": "export_profile_selection",
        "selection_confirmed": args.confirm_select,
        "target": export_profile_reference_to_dict(target),
        "expected_current": (
            None
            if expected is None
            else export_profile_selection_reference_to_dict(expected)
        ),
    }
    if not args.confirm_select:
        _render_profile_select(payload, args.format, result=None)
        return 0
    try:
        result = select_export_profile(
            args.workspace,
            target,
            actor=ExportProfileActor("teacher", args.actor_id),
            rationale=args.rationale,
            decided_at=args.decided_at,
            expected_current=expected,
        )
    except ExportProfileStorageError as error:
        raise _translated(error, "export_profile.storage_error") from error
    result_data: dict[str, object] = {
        "disposition": result.disposition,
        "selection": export_profile_selection_to_dict(result.selection.selection),
        "selection_sha256": result.selection.selection_sha256,
    }
    _render_profile_select(payload, args.format, result=result_data)
    return 0


def _render_profile_select(
    payload: dict[str, object],
    output_format: str,
    *,
    result: dict[str, object] | None,
) -> None:
    if output_format == "json":
        data = dict(payload)
        data["result"] = result
        _print_json(data)
        return
    target = payload["target"]
    assert isinstance(target, dict)
    print("Export Profile selection preview")
    print(
        f"target: {target['profile_id']}@{target['profile_revision']} "
        f"sha256={target['profile_sha256']}"
    )
    if result is None:
        print("confirmation supplied: no")
        print("NO CURRENT PROFILE SELECTION CHANGED")
    else:
        print("confirmation supplied: yes")
        print(f"selection disposition: {result['disposition']}")
        print(f"selection SHA-256: {result['selection_sha256']}")
    print("NO REPORT EXPORT PERFORMED")


def _exact_refs(args: argparse.Namespace) -> tuple[
    ReportingSnapshotReference,
    ExportProfileReference,
]:
    return (
        ReportingSnapshotReference(
            args.class_id,
            args.snapshot_id,
            args.snapshot_sha256,
        ),
        ExportProfileReference(
            args.class_id,
            args.profile_id,
            args.profile_revision,
            args.profile_sha256,
        ),
    )


def _build_from_args(args: argparse.Namespace) -> BuiltExportPreview:
    snapshot, profile = _exact_refs(args)
    try:
        return build_export_preview(args.workspace, snapshot, profile)
    except ReportExportPreviewError as error:
        raise _translated(error, "report_export.preview_error") from error


def _handle_export_preview(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    built = _build_from_args(args)
    if args.payload_only:
        if args.format != "text":
            raise ReportExportCliError(
                "report_export.cli_invalid",
                "--payload-only requires --format text.",
            )
        _write_exact_stdout_bytes(built.payload)
        return 0
    _render_export_preview(built, args.format, commit_context=None)
    return 0


def _render_export_preview(
    built: BuiltExportPreview,
    output_format: str,
    *,
    commit_context: dict[str, object] | None,
) -> None:
    if output_format == "json":
        payload: dict[str, object] = {
            "schema_version": 1,
            "surface": "report_export_preview",
            "preview": export_preview_to_dict(built.preview),
            "payload_text": built.payload.decode("utf-8"),
            "external_system_write": "not_performed",
            "external_system_acceptance": "not_claimed",
        }
        if commit_context is not None:
            payload["commit"] = commit_context
        _print_json(payload)
        return
    preview = built.preview
    print("Meridian local report export preview")
    print(
        f"frozen ReportingSnapshot: {preview.snapshot_reference.snapshot_id} "
        f"sha256={preview.snapshot_reference.snapshot_sha256}"
    )
    print(
        f"ExportProfile: {preview.profile_reference.profile_id}@"
        f"{preview.profile_reference.profile_revision} "
        f"sha256={preview.profile_reference.profile_sha256}"
    )
    roster = preview.roster_observation_reference
    print(
        "roster observation: "
        + ("none" if roster is None else roster.observation_sha256)
    )
    print(f"format: {preview.representation.format}")
    print(f"rows: {preview.row_count}")
    print(f"payload bytes: {preview.payload_byte_length}")
    print(f"payload SHA-256: {preview.payload_sha256}")
    print(f"preview SHA-256: {preview.preview_sha256}")
    if preview.diagnostics:
        print("diagnostics:")
        for diagnostic in preview.diagnostics:
            print(f"  {diagnostic.code}: {diagnostic.count}")
    else:
        print("diagnostics: none")
    if commit_context is not None:
        print(
            "export confirmation supplied: "
            f"{'yes' if commit_context['confirmed'] else 'no'}"
        )
    print("outgoing payload:")
    _write_display_payload(built.payload)
    print("external-system write: no")
    print("external-system acceptance claim: no")


def _handle_export_commit(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    if args.payload_only and (
        args.format != "text"
        or not args.copyable_text
        or not args.confirm_export
    ):
        raise ReportExportCliError(
            "report_export.cli_invalid",
            "--payload-only requires confirmed copyable-text export in text format.",
        )
    built = _build_from_args(args)
    if built.preview.preview_sha256 != args.approved_preview_sha256:
        raise ReportExportCliError(
            "report_export.preview_mismatch",
            "Rebuilt preview SHA-256 does not match teacher-approved preview.",
        )
    if not args.confirm_export:
        context = {
            "confirmed": False,
            "export_id": args.export_id,
            "destination_kind": "file" if args.file is not None else "copyable_text",
            "receipt_write": "not_performed",
        }
        _render_export_preview(built, args.format, commit_context=context)
        return 0

    actor = ReportExportActor("teacher", args.actor_id)
    destination = (
        file_export_destination(args.file)
        if args.file is not None
        else copyable_text_destination()
    )
    try:
        result = commit_report_export(
            args.workspace,
            export_id=args.export_id,
            approved_preview=built.preview,
            destination=destination,
            actor=actor,
            rationale=args.rationale,
            exported_at=args.exported_at,
        )
    except ReportExportCommitError as error:
        raise _translated(error, "report_export.commit_error") from error

    if args.payload_only:
        _write_exact_stdout_bytes(result.preview.payload)
        return 0
    receipt = result.receipt
    if args.format == "json":
        _print_json(
            {
                "schema_version": 1,
                "surface": "report_export_committed",
                "artifact_disposition": result.artifact_disposition,
                "receipt_sha256": receipt.receipt_sha256,
                "receipt": export_receipt_to_dict(receipt.receipt),
                "copyable_text": result.copyable_text,
                "external_system_write": "not_performed",
                "external_system_acceptance": "not_claimed",
            }
        )
        return 0
    print("Meridian local report export committed")
    print(f"export ID: {receipt.receipt.export_id}")
    print(f"artifact disposition: {result.artifact_disposition}")
    print(f"payload SHA-256: {receipt.receipt.payload_sha256}")
    print(f"receipt SHA-256: {receipt.receipt_sha256}")
    if result.destination_path is not None:
        print(f"local destination: {result.destination_path}")
    if result.copyable_text is not None:
        print("copyable payload:")
        _write_display_payload(result.preview.payload)
    print("external-system write: no")
    print("external-system acceptance claim: no")
    return 0


def _handle_receipt_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        rows = []
        for export_id in list_export_receipt_ids(args.workspace, args.class_id):
            stored = load_export_receipt(args.workspace, args.class_id, export_id)
            rows.append(
                {
                    "export_id": export_id,
                    "receipt_sha256": stored.receipt_sha256,
                    "snapshot_id": stored.receipt.snapshot_reference.snapshot_id,
                    "profile_id": stored.receipt.profile_reference.profile_id,
                    "profile_revision": (
                        stored.receipt.profile_reference.profile_revision
                    ),
                    "destination_kind": stored.receipt.destination.kind,
                    "exported_at": stored.receipt.exported_at.isoformat(),
                }
            )
    except ReportExportReceiptError as error:
        raise _translated(error, "report_export.receipt_error") from error
    payload = {
        "schema_version": 1,
        "surface": "report_export_receipts",
        "class_id": args.class_id,
        "receipts": rows,
    }
    if args.format == "json":
        _print_json(payload)
        return 0
    print("Meridian immutable ExportReceipts")
    print(f"class: {args.class_id}")
    if not rows:
        print("receipts: none")
        return 0
    for row in rows:
        print(
            f"  {row['export_id']} | {row['destination_kind']} | "
            f"receipt={row['receipt_sha256']}"
        )
    return 0


def _handle_receipt_inspect(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        stored = load_export_receipt(
            args.workspace,
            args.class_id,
            args.export_id,
        )
    except ReportExportReceiptError as error:
        raise _translated(error, "report_export.receipt_error") from error
    if stored.receipt_sha256 != args.receipt_sha256:
        raise ReportExportCliError(
            "report_export.receipt_integrity_failed",
            "Requested receipt SHA-256 does not match immutable stored receipt.",
        )
    if args.format == "json":
        _print_json(
            {
                "schema_version": 1,
                "surface": "report_export_receipt",
                "receipt_sha256": stored.receipt_sha256,
                "receipt": export_receipt_to_dict(stored.receipt),
            }
        )
        return 0
    receipt = stored.receipt
    print("Meridian immutable ExportReceipt")
    print(f"export ID: {receipt.export_id}")
    print(f"receipt SHA-256: {stored.receipt_sha256}")
    print(
        f"frozen ReportingSnapshot: {receipt.snapshot_reference.snapshot_id} "
        f"sha256={receipt.snapshot_reference.snapshot_sha256}"
    )
    print(
        f"ExportProfile: {receipt.profile_reference.profile_id}@"
        f"{receipt.profile_reference.profile_revision}"
    )
    print(f"payload SHA-256: {receipt.payload_sha256}")
    print(f"destination kind: {receipt.destination.kind}")
    print("external-system write: no")
    print("external-system acceptance claim: no")
    return 0


def _translated(error: Exception, fallback_code: str) -> ReportExportCliError:
    code = getattr(error, "code", fallback_code)
    return ReportExportCliError(str(code), str(error))


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _write_display_payload(payload: bytes) -> None:
    text = payload.decode("utf-8")
    sys.stdout.write(text)
    if not text.endswith(("\n", "\r")):
        sys.stdout.write("\n")


def _write_exact_stdout_bytes(payload: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(payload.decode("utf-8"))
        sys.stdout.flush()
        return
    stream.write(payload)
    stream.flush()


__all__ = ["ReportExportCliError", "register_report_export_cli"]
