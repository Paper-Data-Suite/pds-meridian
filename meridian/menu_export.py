"""Teacher-facing Export Profile and report-export menu for Meridian."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileReference,
    ExportProfileRevision,
    ExportRepresentation,
)
from meridian.export_profile_storage import (
    ExportProfileSelectionReference,
    ExportProfileStorageError,
    get_current_export_profile_selection_reference,
    list_export_profile_ids,
    list_export_profile_revisions,
    load_current_export_profile,
    load_current_export_profile_selection,
    load_export_profile_revision,
    select_export_profile,
    write_export_profile_revision,
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
)
from meridian.report_export_receipt import (
    ReportExportActor,
    ReportExportReceiptError,
    list_export_receipt_ids,
    load_export_receipt,
)
from meridian.reporting_snapshot import ReportingSnapshotReference

WorkspaceResolver: TypeAlias = Callable[[], Path]
Clock: TypeAlias = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ExportProfileListItem:
    profile_id: str
    title: str
    latest_revision: int
    current_revision: int | None


@dataclass(frozen=True, slots=True)
class ExportProfilePresentation:
    class_id: str
    profile_id: str
    title: str
    purpose: str
    revision: int
    profile_sha256: str
    columns: tuple[tuple[str, str], ...]
    format: str
    include_header: bool
    line_ending: str
    utf8_bom: bool


@dataclass(frozen=True, slots=True)
class ExportProfileWritePlan:
    profile: ExportProfileRevision = field(repr=False)
    presentation: ExportProfilePresentation


@dataclass(frozen=True, slots=True)
class ExportProfileSelectionPlan:
    target: ExportProfileReference
    title: str
    expected_current: ExportProfileSelectionReference | None


@dataclass(frozen=True, slots=True)
class ExportPreviewPresentation:
    built: BuiltExportPreview = field(repr=False)
    class_id: str
    snapshot_id: str
    snapshot_sha256: str
    profile_id: str
    profile_revision: int
    profile_sha256: str
    format: str
    row_count: int
    payload_byte_length: int
    payload_sha256: str
    preview_sha256: str
    diagnostic_lines: tuple[str, ...]
    payload_text: str


@dataclass(frozen=True, slots=True)
class ExportCommitResult:
    export_id: str
    receipt_sha256: str
    artifact_disposition: str
    destination_kind: str
    destination_name: str | None
    copyable_text: str | None


@dataclass(frozen=True, slots=True)
class ExportReceiptPresentation:
    export_id: str
    receipt_sha256: str
    snapshot_id: str
    profile_id: str
    profile_revision: int
    row_count: int
    payload_sha256: str
    destination_kind: str
    destination_name: str | None
    actor_id: str
    exported_at: str


ProfileLister: TypeAlias = Callable[
    [Path, str],
    tuple[ExportProfileListItem, ...],
]
ProfileLoader: TypeAlias = Callable[
    [Path, str, str],
    ExportProfilePresentation | None,
]
ProfileWritePreviewer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        str,
        str,
        tuple[tuple[str, str], ...],
        str,
        bool,
        str,
        bool,
        str,
        str | None,
        datetime,
    ],
    ExportProfileWritePlan,
]
ProfileWriter: TypeAlias = Callable[[Path, ExportProfileWritePlan], str]
ProfileSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str],
    ExportProfileSelectionPlan,
]
ProfileSelector: TypeAlias = Callable[
    [Path, ExportProfileSelectionPlan, str, str | None, datetime],
    str,
]
PreviewBuilder: TypeAlias = Callable[
    [Path, str, str, str, str],
    ExportPreviewPresentation,
]
ExportCommitter: TypeAlias = Callable[
    [
        Path,
        ExportPreviewPresentation,
        str,
        str,
        str | None,
        str,
        str | None,
        datetime,
    ],
    ExportCommitResult,
]
ReceiptLister: TypeAlias = Callable[[Path, str], tuple[str, ...]]
ReceiptLoader: TypeAlias = Callable[
    [Path, str, str],
    ExportReceiptPresentation,
]


@dataclass(frozen=True, slots=True)
class ExportMenuDependencies:
    workspace_resolver: WorkspaceResolver
    clock: Clock
    profile_lister: ProfileLister
    profile_loader: ProfileLoader
    profile_write_previewer: ProfileWritePreviewer
    profile_writer: ProfileWriter
    profile_selection_previewer: ProfileSelectionPreviewer
    profile_selector: ProfileSelector
    preview_builder: PreviewBuilder
    export_committer: ExportCommitter
    receipt_lister: ReceiptLister
    receipt_loader: ReceiptLoader


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _profile_presentation(stored: object) -> ExportProfilePresentation:
    profile = stored.profile  # type: ignore[attr-defined]
    return ExportProfilePresentation(
        class_id=profile.class_id,
        profile_id=profile.profile_id,
        title=profile.title,
        purpose=profile.purpose,
        revision=profile.profile_revision,
        profile_sha256=stored.profile_sha256,  # type: ignore[attr-defined]
        columns=tuple(
            (column.source_field, column.output_name)
            for column in profile.columns
        ),
        format=profile.representation.format,
        include_header=profile.representation.include_header,
        line_ending=profile.representation.line_ending,
        utf8_bom=profile.representation.utf8_bom,
    )


def _list_profiles(
    root: Path,
    class_id: str,
) -> tuple[ExportProfileListItem, ...]:
    rows: list[ExportProfileListItem] = []
    for profile_id in list_export_profile_ids(root, class_id):
        revisions = list_export_profile_revisions(root, class_id, profile_id)
        latest = load_export_profile_revision(
            root,
            class_id,
            profile_id,
            revisions[-1],
        )
        current = load_current_export_profile_selection(
            root,
            class_id,
            profile_id,
        )
        rows.append(
            ExportProfileListItem(
                profile_id=profile_id,
                title=latest.profile.title,
                latest_revision=revisions[-1],
                current_revision=(
                    None
                    if current is None
                    else current.selection.profile_reference.profile_revision
                ),
            )
        )
    return tuple(rows)


def _load_current_profile(
    root: Path,
    class_id: str,
    profile_id: str,
) -> ExportProfilePresentation | None:
    stored = load_current_export_profile(root, class_id, profile_id)
    return None if stored is None else _profile_presentation(stored)


def _preview_profile_write(
    root: Path,
    class_id: str,
    profile_id: str,
    title: str,
    purpose: str,
    columns: tuple[tuple[str, str], ...],
    format_name: str,
    include_header: bool,
    line_ending: str,
    utf8_bom: bool,
    actor_id: str,
    rationale: str | None,
    revised_at: datetime,
) -> ExportProfileWritePlan:
    revisions = list_export_profile_revisions(root, class_id, profile_id)
    revision = 1 if not revisions else revisions[-1] + 1
    profile = ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=class_id,
        profile_id=profile_id,
        profile_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title=title,
        purpose=purpose,
        columns=tuple(ExportColumn(*value) for value in columns),
        representation=ExportRepresentation(
            format=format_name,  # type: ignore[arg-type]
            include_header=include_header,
            line_ending=line_ending,  # type: ignore[arg-type]
            utf8_bom=utf8_bom,
        ),
        actor=ExportProfileActor("teacher", actor_id),
        rationale=rationale,
        revised_at=revised_at,
    )
    from meridian.export_profile import export_profile_reference

    reference = export_profile_reference(profile)
    presentation = ExportProfilePresentation(
        class_id=class_id,
        profile_id=profile_id,
        title=title,
        purpose=purpose,
        revision=revision,
        profile_sha256=reference.profile_sha256,
        columns=columns,
        format=format_name,
        include_header=include_header,
        line_ending=line_ending,
        utf8_bom=utf8_bom,
    )
    return ExportProfileWritePlan(profile=profile, presentation=presentation)


def _write_profile(
    root: Path,
    plan: ExportProfileWritePlan,
) -> str:
    return write_export_profile_revision(root, plan.profile).disposition


def _preview_profile_selection(
    root: Path,
    class_id: str,
    profile_id: str,
) -> ExportProfileSelectionPlan:
    revisions = list_export_profile_revisions(root, class_id, profile_id)
    if not revisions:
        raise ValueError("No Export Profile revisions exist for this profile.")
    stored = load_export_profile_revision(
        root,
        class_id,
        profile_id,
        revisions[-1],
    )
    return ExportProfileSelectionPlan(
        target=stored.reference,
        title=stored.profile.title,
        expected_current=get_current_export_profile_selection_reference(
            root,
            class_id,
            profile_id,
        ),
    )


def _select_profile(
    root: Path,
    plan: ExportProfileSelectionPlan,
    actor_id: str,
    rationale: str | None,
    decided_at: datetime,
) -> str:
    result = select_export_profile(
        root,
        plan.target,
        actor=ExportProfileActor("teacher", actor_id),
        rationale=rationale,
        decided_at=decided_at,
        expected_current=plan.expected_current,
    )
    return result.disposition


def _build_preview(
    root: Path,
    class_id: str,
    snapshot_id: str,
    snapshot_sha256: str,
    profile_id: str,
) -> ExportPreviewPresentation:
    current = load_current_export_profile(root, class_id, profile_id)
    if current is None:
        raise ValueError(
            "No Export Profile revision is explicitly selected for this profile."
        )
    built = build_export_preview(
        root,
        ReportingSnapshotReference(
            class_id,
            snapshot_id,
            snapshot_sha256,
        ),
        current.reference,
    )
    preview = built.preview
    return ExportPreviewPresentation(
        built=built,
        class_id=class_id,
        snapshot_id=preview.snapshot_reference.snapshot_id,
        snapshot_sha256=preview.snapshot_reference.snapshot_sha256,
        profile_id=preview.profile_reference.profile_id,
        profile_revision=preview.profile_reference.profile_revision,
        profile_sha256=preview.profile_reference.profile_sha256,
        format=preview.representation.format,
        row_count=preview.row_count,
        payload_byte_length=preview.payload_byte_length,
        payload_sha256=preview.payload_sha256,
        preview_sha256=preview.preview_sha256,
        diagnostic_lines=tuple(
            f"{item.code}: {item.count}" for item in preview.diagnostics
        ),
        payload_text=built.payload.decode("utf-8"),
    )


def _commit_export(
    root: Path,
    preview: ExportPreviewPresentation,
    export_id: str,
    actor_id: str,
    rationale: str | None,
    destination_kind: str,
    destination_text: str | None,
    exported_at: datetime,
) -> ExportCommitResult:
    destination = (
        file_export_destination(Path(destination_text or ""))
        if destination_kind == "file"
        else copyable_text_destination()
    )
    result = commit_report_export(
        root,
        export_id=export_id,
        approved_preview=preview.built.preview,
        destination=destination,
        actor=ReportExportActor("teacher", actor_id),
        rationale=rationale,
        exported_at=exported_at,
    )
    receipt = result.receipt
    return ExportCommitResult(
        export_id=receipt.receipt.export_id,
        receipt_sha256=receipt.receipt_sha256,
        artifact_disposition=result.artifact_disposition,
        destination_kind=receipt.receipt.destination.kind,
        destination_name=receipt.receipt.destination.basename,
        copyable_text=result.copyable_text,
    )


def _load_receipt(
    root: Path,
    class_id: str,
    export_id: str,
) -> ExportReceiptPresentation:
    stored = load_export_receipt(root, class_id, export_id)
    receipt = stored.receipt
    return ExportReceiptPresentation(
        export_id=receipt.export_id,
        receipt_sha256=stored.receipt_sha256,
        snapshot_id=receipt.snapshot_reference.snapshot_id,
        profile_id=receipt.profile_reference.profile_id,
        profile_revision=receipt.profile_reference.profile_revision,
        row_count=receipt.row_count,
        payload_sha256=receipt.payload_sha256,
        destination_kind=receipt.destination.kind,
        destination_name=receipt.destination.basename,
        actor_id=receipt.actor.actor_id,
        exported_at=receipt.exported_at.astimezone(UTC).isoformat(),
    )


def default_export_menu_dependencies() -> ExportMenuDependencies:
    return ExportMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        clock=_utc_now,
        profile_lister=_list_profiles,
        profile_loader=_load_current_profile,
        profile_write_previewer=_preview_profile_write,
        profile_writer=_write_profile,
        profile_selection_previewer=_preview_profile_selection,
        profile_selector=_select_profile,
        preview_builder=_build_preview,
        export_committer=_commit_export,
        receipt_lister=list_export_receipt_ids,
        receipt_loader=_load_receipt,
    )


def _yes_no(value: str, label: str) -> bool:
    lowered = value.strip().casefold()
    if lowered in {"y", "yes"}:
        return True
    if lowered in {"n", "no"}:
        return False
    raise ValueError(f"{label} must be yes or no")


def _columns(value: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for raw in value.split(";"):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(
                "columns must use source_field=Output Name separated by semicolons"
            )
        source, output = item.split("=", 1)
        source = source.strip()
        output = output.strip()
        if not source or not output:
            raise ValueError("column source and output name must be nonblank")
        rows.append((source, output))
    if not rows:
        raise ValueError("at least one Export Profile column is required")
    return tuple(rows)


def _show_profile(value: ExportProfilePresentation, output: TextIO) -> None:
    print_menu_header(output, "Current Export Profile")
    write_lines(
        output,
        f"Profile: {value.title}",
        f"Purpose: {value.purpose}",
        f"Revision: {value.revision}",
        f"Format: {value.format.upper()}",
        f"Header row: {'yes' if value.include_header else 'no'}",
        f"Line ending: {value.line_ending}",
        f"UTF-8 BOM: {'yes' if value.utf8_bom else 'no'}",
        "",
        "Columns:",
    )
    for source, name in value.columns:
        print(f"  {name} <- {source}", file=output)


def _profiles(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Export Profiles")
    class_id = read_choice(input_fn, "Class ID: ")
    try:
        values = deps.profile_lister(deps.workspace_resolver(), class_id)
    except (WorkspaceRootError, ExportProfileStorageError, ValueError) as error:
        write_lines(output, "", f"Profiles could not be listed safely: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Export Profiles")
    if not values:
        print("No Export Profiles.", file=output)
    for index, item in enumerate(values, start=1):
        current = (
            "not selected"
            if item.current_revision is None
            else f"current r{item.current_revision}"
        )
        print(
            f"{index}. {item.title} — latest r{item.latest_revision}; {current}",
            file=output,
        )
    write_lines(output, "")
    pause_for_user(input_fn)


def _inspect_profile(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Inspect Current Export Profile")
    class_id = read_choice(input_fn, "Class ID: ")
    profile_id = read_choice(input_fn, "Export Profile ID: ")
    try:
        value = deps.profile_loader(
            deps.workspace_resolver(),
            class_id,
            profile_id,
        )
    except (WorkspaceRootError, ExportProfileStorageError, ValueError) as error:
        write_lines(output, "", f"Profile could not be loaded safely: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    if value is None:
        print_menu_header(output, "Current Export Profile")
        write_lines(output, "No revision is explicitly selected.")
        pause_for_user(input_fn)
        return
    _show_profile(value, output)
    write_lines(output, "", "T. Technical details / provenance")
    choice = read_choice(input_fn)
    if choice.casefold() == "t":
        write_lines(
            output,
            "",
            f"class_id: {value.class_id}",
            f"profile_id: {value.profile_id}",
            f"profile_sha256: {value.profile_sha256}",
        )
        pause_for_user(input_fn)


def _author_profile(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Export Profile")
    class_id = read_choice(input_fn, "Class ID: ")
    profile_id = read_choice(input_fn, "Profile ID: ")
    title = read_choice(input_fn, "Profile title: ")
    purpose = read_choice(input_fn, "Purpose: ")
    write_lines(
        output,
        "",
        "Columns use: source_field=Output Name; source_field=Output Name",
    )
    try:
        columns = _columns(read_choice(input_fn, "Columns: "))
        format_name = read_choice(input_fn, "Format (csv/tsv): ").casefold()
        include_header = _yes_no(
            read_choice(input_fn, "Include header? (yes/no): "),
            "include header",
        )
        line_ending = read_choice(input_fn, "Line ending (lf/crlf): ").casefold()
        utf8_bom = _yes_no(
            read_choice(input_fn, "UTF-8 BOM? (yes/no): "),
            "UTF-8 BOM",
        )
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        rationale_text = read_choice(input_fn, "Rationale (optional): ")
        plan = deps.profile_write_previewer(
            deps.workspace_resolver(),
            class_id,
            profile_id,
            title,
            purpose,
            columns,
            format_name,
            include_header,
            line_ending,
            utf8_bom,
            actor_id,
            rationale_text or None,
            deps.clock(),
        )
    except (
        WorkspaceRootError,
        ExportProfileStorageError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Export Profile preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Export Profile Before Write")
    _show_profile(plan.presentation, output)
    write_lines(
        output,
        "",
        f"Profile sha256: {plan.presentation.profile_sha256}",
        "Writing this revision will NOT select it.",
        "Type WRITE to create this exact immutable revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No Export Profile revision was written.")
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.profile_writer(deps.workspace_resolver(), plan)
    except (WorkspaceRootError, ExportProfileStorageError) as error:
        write_lines(output, "", f"Profile write failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Export Profile revision: {disposition}.",
        "It is not current until explicitly selected.",
    )
    pause_for_user(input_fn)


def _select_profile_latest(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select Latest Export Profile Revision")
    class_id = read_choice(input_fn, "Class ID: ")
    profile_id = read_choice(input_fn, "Export Profile ID: ")
    actor_id = read_choice(input_fn, "Teacher actor ID: ")
    rationale_text = read_choice(input_fn, "Rationale (optional): ")
    try:
        plan = deps.profile_selection_previewer(
            deps.workspace_resolver(),
            class_id,
            profile_id,
        )
    except (WorkspaceRootError, ExportProfileStorageError, ValueError) as error:
        write_lines(output, "", f"Selection preview failed safely: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Export Profile Selection")
    write_lines(
        output,
        f"Profile: {plan.title}",
        f"Target revision: {plan.target.profile_revision}",
        f"Target sha256: {plan.target.profile_sha256}",
        (
            "Currently selected revision: none"
            if plan.expected_current is None
            else (
                "Currently selected revision: "
                f"{plan.expected_current.selection_revision}"
            )
        ),
        "",
        "Type SELECT to make this exact revision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current Export Profile was not changed.")
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.profile_selector(
            deps.workspace_resolver(),
            plan,
            actor_id,
            rationale_text or None,
            deps.clock(),
        )
    except (WorkspaceRootError, ExportProfileStorageError) as error:
        write_lines(output, "", f"Profile selection failed safely: {error}")
        pause_for_user(input_fn)
        return
    write_lines(output, "", f"Export Profile selection: {disposition}.")
    pause_for_user(input_fn)


def _prepare_export(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Prepare Report Export")
    class_id = read_choice(input_fn, "Class ID: ")
    profile_id = read_choice(input_fn, "Selected Export Profile ID: ")
    snapshot_id = read_choice(input_fn, "ReportingSnapshot ID: ")
    snapshot_sha256 = read_choice(input_fn, "ReportingSnapshot sha256: ")
    try:
        value = deps.preview_builder(
            deps.workspace_resolver(),
            class_id,
            snapshot_id,
            snapshot_sha256,
            profile_id,
        )
    except (
        WorkspaceRootError,
        ExportProfileStorageError,
        ReportExportPreviewError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Export preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Outgoing Export")
    write_lines(
        output,
        f"Rows: {value.row_count}",
        f"Format: {value.format.upper()}",
        f"Payload bytes: {value.payload_byte_length}",
        f"Diagnostics: {len(value.diagnostic_lines)}",
        "",
    )
    for line in value.diagnostic_lines:
        print(f"  {line}", file=output)
    write_lines(
        output,
        "",
        "Outgoing payload:",
        value.payload_text,
        "",
        f"Preview sha256: {value.preview_sha256}",
        f"Payload sha256: {value.payload_sha256}",
        "No external-system write has occurred.",
        "",
        "1. Export to file",
        "2. Produce copyable text",
        "B. Cancel",
    )
    choice = read_choice(input_fn)
    nav = parse_navigation_choice(choice)
    if nav is NavigationChoice.BACK or choice == "":
        return
    if choice not in {"1", "2"}:
        write_lines(output, "", "No export was performed.")
        pause_for_user(input_fn)
        return

    export_id = read_choice(input_fn, "Export ID: ")
    actor_id = read_choice(input_fn, "Teacher actor ID: ")
    rationale_text = read_choice(input_fn, "Rationale (optional): ")
    destination_kind = "file" if choice == "1" else "copyable_text"
    destination_text = (
        read_choice(input_fn, "Destination file path: ")
        if destination_kind == "file"
        else None
    )
    write_lines(
        output,
        "",
        f"Exact approved preview: {value.preview_sha256}",
        "Type EXPORT to revalidate and deliver this exact preview.",
    )
    if read_choice(input_fn, "Confirmation: ") != "EXPORT":
        write_lines(output, "", "No report export was performed.")
        pause_for_user(input_fn)
        return

    try:
        result = deps.export_committer(
            deps.workspace_resolver(),
            value,
            export_id,
            actor_id,
            rationale_text or None,
            destination_kind,
            destination_text,
            deps.clock(),
        )
    except (
        WorkspaceRootError,
        ReportExportCommitError,
        ReportExportReceiptError,
        ValueError,
    ) as error:
        write_lines(output, "", f"Export failed safely: {error}")
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Report Export Result")
    write_lines(
        output,
        f"Export: {result.export_id}",
        f"Artifact: {result.artifact_disposition}",
        f"Destination kind: {result.destination_kind}",
        (
            f"Destination file: {result.destination_name}"
            if result.destination_name is not None
            else "Destination file: none"
        ),
        f"Receipt sha256: {result.receipt_sha256}",
    )
    if result.copyable_text is not None:
        write_lines(output, "", "Copyable text:", result.copyable_text)
    write_lines(
        output,
        "",
        "This confirms only the local Meridian export and receipt.",
        "No external-system import or acceptance is claimed.",
    )
    pause_for_user(input_fn)


def _receipts(
    deps: ExportMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Export Receipts")
    class_id = read_choice(input_fn, "Class ID: ")
    try:
        ids = deps.receipt_lister(deps.workspace_resolver(), class_id)
    except (WorkspaceRootError, ReportExportReceiptError) as error:
        write_lines(output, "", f"Receipts could not be listed safely: {error}")
        pause_for_user(input_fn)
        return
    if not ids:
        write_lines(output, "", "No ExportReceipts.")
        pause_for_user(input_fn)
        return
    write_lines(output, "")
    for index, export_id in enumerate(ids[:10], start=1):
        print(f"{index}. {export_id}", file=output)
    export_id = read_choice(input_fn, "Export ID to inspect (blank to cancel): ")
    if not export_id:
        return
    try:
        receipt = deps.receipt_loader(
            deps.workspace_resolver(),
            class_id,
            export_id,
        )
    except (WorkspaceRootError, ReportExportReceiptError) as error:
        write_lines(output, "", f"Receipt could not be loaded safely: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "ExportReceipt")
    write_lines(
        output,
        f"Export: {receipt.export_id}",
        f"Snapshot: {receipt.snapshot_id}",
        f"Profile: {receipt.profile_id} r{receipt.profile_revision}",
        f"Rows: {receipt.row_count}",
        (
            "Destination: "
            f"{receipt.destination_kind}"
            + (
                ""
                if receipt.destination_name is None
                else f" ({receipt.destination_name})"
            )
        ),
        f"Teacher: {receipt.actor_id}",
        f"Exported: {receipt.exported_at}",
        "",
        "This receipt proves local export provenance only.",
        "It does not prove external-system acknowledgement or import.",
        "",
        "T. Technical details / provenance",
    )
    if read_choice(input_fn).casefold() == "t":
        write_lines(
            output,
            "",
            f"receipt_sha256: {receipt.receipt_sha256}",
            f"payload_sha256: {receipt.payload_sha256}",
        )
        pause_for_user(input_fn)


def run_export_menu(
    *,
    dependencies: ExportMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_export_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Export")
        write_lines(
            stream,
            "1. List Export Profiles",
            "2. Inspect current Export Profile",
            "3. Author Export Profile revision",
            "4. Select latest Export Profile revision",
            "5. Preview and export a ReportingSnapshot",
            "6. Review ExportReceipts",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        actions = {
            "1": _profiles,
            "2": _inspect_profile,
            "3": _author_profile,
            "4": _select_profile_latest,
            "5": _prepare_export,
            "6": _receipts,
        }
        action = actions.get(choice)
        if action is None:
            write_lines(stream, "", "Please choose 1-6, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        action(deps, input_fn, stream, clear_fn)
