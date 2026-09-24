"""Teacher-facing ReportingSnapshot workflows for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

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
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
    ReportingSnapshotReference,
    reporting_definition_reference,
)
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionError,
    ReportingSnapshotSelectionReference,
    get_current_reporting_snapshot_selection_reference,
    load_current_reporting_snapshot_selection,
    select_reporting_snapshot,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    list_reporting_definition_revisions,
    list_reporting_snapshot_ids,
    load_reporting_definition_revision,
    load_reporting_snapshot,
    write_reporting_definition_revision,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
Clock: TypeAlias = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class SnapshotListItem:
    snapshot_id: str
    definition_id: str
    definition_revision: int
    school_year: str
    period_id: str
    calendar_revision: int
    row_count: int
    created_at: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class SnapshotPresentation:
    item: SnapshotListItem
    current_for_scope: bool


@dataclass(frozen=True, slots=True)
class SnapshotSelectionPresentation:
    class_id: str
    definition_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    snapshot_id: str | None
    snapshot_sha256: str | None
    selection_revision: int | None
    selection_sha256: str | None


@dataclass(frozen=True, slots=True)
class ReportingDefinitionPlan:
    class_id: str
    definition_id: str
    definition_revision: int
    definition_sha256: str
    title: str
    purpose: str
    school_year: str
    period_id: str
    actor_id: str
    rationale: str | None
    candidate: ReportingDefinitionRevision = field(repr=False)


@dataclass(frozen=True, slots=True)
class SnapshotSelectionPlan:
    class_id: str
    snapshot_id: str
    snapshot_sha256: str
    definition_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    row_count: int
    actor_id: str
    rationale: str | None
    decided_at: datetime
    current_snapshot_id: str | None
    current_selection_revision: int | None
    target_reference: ReportingSnapshotReference = field(repr=False)
    expected_current: ReportingSnapshotSelectionReference | None = field(
        repr=False
    )


SnapshotLister: TypeAlias = Callable[
    [Path, str],
    tuple[SnapshotListItem, ...],
]
SnapshotInspector: TypeAlias = Callable[
    [Path, str, str],
    SnapshotPresentation,
]
SnapshotSelectionLoader: TypeAlias = Callable[
    [Path, str, str, AcademicPeriodRef, int],
    SnapshotSelectionPresentation,
]
SnapshotSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str | None, datetime],
    SnapshotSelectionPlan,
]
SnapshotSelectionCommitter: TypeAlias = Callable[
    [Path, SnapshotSelectionPlan],
    str,
]
ReportingDefinitionPreviewer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        str,
        str,
        AcademicPeriodRef,
        str,
        str | None,
        datetime,
    ],
    ReportingDefinitionPlan,
]
ReportingDefinitionCommitter: TypeAlias = Callable[
    [Path, ReportingDefinitionPlan],
    str,
]


@dataclass(frozen=True, slots=True)
class SnapshotMenuDependencies:
    workspace_resolver: WorkspaceResolver
    clock: Clock
    lister: SnapshotLister
    inspector: SnapshotInspector
    selection_loader: SnapshotSelectionLoader
    selection_previewer: SnapshotSelectionPreviewer
    selection_committer: SnapshotSelectionCommitter
    definition_previewer: ReportingDefinitionPreviewer
    definition_committer: ReportingDefinitionCommitter


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _item(stored: object) -> SnapshotListItem:
    snapshot = stored.snapshot  # type: ignore[attr-defined]
    return SnapshotListItem(
        snapshot_id=snapshot.snapshot_id,
        definition_id=snapshot.definition_reference.definition_id,
        definition_revision=snapshot.definition_reference.definition_revision,
        school_year=snapshot.target_period.school_year,
        period_id=snapshot.target_period.period_id,
        calendar_revision=snapshot.calendar_revision,
        row_count=len(snapshot.report_preview.rows),
        created_at=snapshot.created_at.astimezone(UTC).isoformat(),
        snapshot_sha256=stored.snapshot_sha256,  # type: ignore[attr-defined]
    )


def _list_snapshots(
    root: Path,
    class_id: str,
) -> tuple[SnapshotListItem, ...]:
    return tuple(
        _item(load_reporting_snapshot(root, class_id, snapshot_id))
        for snapshot_id in list_reporting_snapshot_ids(root, class_id)
    )


def _inspect_snapshot(
    root: Path,
    class_id: str,
    snapshot_id: str,
) -> SnapshotPresentation:
    stored = load_reporting_snapshot(root, class_id, snapshot_id)
    snapshot = stored.snapshot
    selected = get_current_reporting_snapshot_selection_reference(
        root,
        class_id,
        snapshot.definition_reference.definition_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    current = False
    if selected is not None:
        current_state = load_current_reporting_snapshot_selection(
            root,
            class_id,
            snapshot.definition_reference.definition_id,
            snapshot.target_period,
            snapshot.calendar_revision,
        )
        current = bool(
            current_state is not None
            and current_state.selection.snapshot_reference == stored.reference
        )
    return SnapshotPresentation(
        item=_item(stored),
        current_for_scope=current,
    )


def _load_selection(
    root: Path,
    class_id: str,
    definition_id: str,
    period: AcademicPeriodRef,
    calendar_revision: int,
) -> SnapshotSelectionPresentation:
    stored = load_current_reporting_snapshot_selection(
        root,
        class_id,
        definition_id,
        period,
        calendar_revision,
    )
    if stored is None:
        return SnapshotSelectionPresentation(
            class_id=class_id,
            definition_id=definition_id,
            school_year=period.school_year,
            period_id=period.period_id,
            calendar_revision=calendar_revision,
            snapshot_id=None,
            snapshot_sha256=None,
            selection_revision=None,
            selection_sha256=None,
        )
    reference = stored.selection.snapshot_reference
    return SnapshotSelectionPresentation(
        class_id=class_id,
        definition_id=definition_id,
        school_year=period.school_year,
        period_id=period.period_id,
        calendar_revision=calendar_revision,
        snapshot_id=reference.snapshot_id,
        snapshot_sha256=reference.snapshot_sha256,
        selection_revision=stored.selection.selection_revision,
        selection_sha256=stored.selection_sha256,
    )


def _preview_selection(
    root: Path,
    class_id: str,
    snapshot_id: str,
    actor_id: str,
    rationale: str | None,
    decided_at: datetime,
) -> SnapshotSelectionPlan:
    stored = load_reporting_snapshot(root, class_id, snapshot_id)
    snapshot = stored.snapshot
    expected = get_current_reporting_snapshot_selection_reference(
        root,
        class_id,
        snapshot.definition_reference.definition_id,
        snapshot.target_period,
        snapshot.calendar_revision,
    )
    current_snapshot_id: str | None = None
    current_revision: int | None = None
    if expected is not None:
        current = load_current_reporting_snapshot_selection(
            root,
            class_id,
            snapshot.definition_reference.definition_id,
            snapshot.target_period,
            snapshot.calendar_revision,
        )
        if current is None or current.reference != expected:
            raise ReportingSnapshotSelectionError(
                "Current ReportingSnapshot selector changed during preview."
            )
        current_snapshot_id = current.selection.snapshot_reference.snapshot_id
        current_revision = current.selection.selection_revision
    return SnapshotSelectionPlan(
        class_id=class_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_sha256=stored.snapshot_sha256,
        definition_id=snapshot.definition_reference.definition_id,
        school_year=snapshot.target_period.school_year,
        period_id=snapshot.target_period.period_id,
        calendar_revision=snapshot.calendar_revision,
        row_count=len(snapshot.report_preview.rows),
        actor_id=actor_id,
        rationale=rationale,
        decided_at=decided_at,
        current_snapshot_id=current_snapshot_id,
        current_selection_revision=current_revision,
        target_reference=stored.reference,
        expected_current=expected,
    )


def _commit_selection(
    root: Path,
    plan: SnapshotSelectionPlan,
) -> str:
    result = select_reporting_snapshot(
        root,
        plan.target_reference,
        actor=ReportingActor("teacher", plan.actor_id),
        rationale=plan.rationale,
        decided_at=plan.decided_at,
        expected_current=plan.expected_current,
    )
    return result.disposition


def _preview_definition(
    root: Path,
    class_id: str,
    definition_id: str,
    title: str,
    purpose: str,
    period: AcademicPeriodRef,
    actor_id: str,
    rationale: str | None,
    revised_at: datetime,
) -> ReportingDefinitionPlan:
    history = list_reporting_definition_revisions(
        root,
        class_id,
        definition_id,
    )
    revision = 1 if not history else history[-1] + 1
    candidate = ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=class_id,
        definition_id=definition_id,
        definition_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        report_kind="grade_report",
        purpose=purpose,
        title=title,
        target_period=period,
        intended_audience="teacher",
        actor=ReportingActor("teacher", actor_id),
        rationale=rationale,
        revised_at=revised_at,
    )
    if history:
        previous = load_reporting_definition_revision(
            root,
            class_id,
            definition_id,
            history[-1],
        ).definition
        if candidate.revised_at < previous.revised_at:
            raise ValueError(
                "new reporting definition cannot predate its prior revision"
            )
    reference = reporting_definition_reference(candidate)
    return ReportingDefinitionPlan(
        class_id=class_id,
        definition_id=definition_id,
        definition_revision=revision,
        definition_sha256=reference.definition_sha256,
        title=title,
        purpose=purpose,
        school_year=period.school_year,
        period_id=period.period_id,
        actor_id=actor_id,
        rationale=rationale,
        candidate=candidate,
    )


def _commit_definition(
    root: Path,
    plan: ReportingDefinitionPlan,
) -> str:
    result = write_reporting_definition_revision(root, plan.candidate)
    return result.disposition


def default_snapshot_menu_dependencies() -> SnapshotMenuDependencies:
    return SnapshotMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        clock=_utc_now,
        lister=_list_snapshots,
        inspector=_inspect_snapshot,
        selection_loader=_load_selection,
        selection_previewer=_preview_selection,
        selection_committer=_commit_selection,
        definition_previewer=_preview_definition,
        definition_committer=_commit_definition,
    )


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise ValueError("calendar revision must be a positive integer")
    return result


def _list(
    *,
    deps: SnapshotMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Frozen ReportingSnapshots")
    class_id = read_choice(input_fn, "Class ID: ")
    try:
        values = deps.lister(deps.workspace_resolver(), class_id)
    except (WorkspaceRootError, ReportingSnapshotStorageError, ValueError) as error:
        write_lines(
            output,
            "",
            "ReportingSnapshots could not be listed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Frozen ReportingSnapshots")
    write_lines(
        output,
        f"Class: {class_id}",
        "Listing order is not current-use authority.",
        "",
    )
    if not values:
        print("No frozen ReportingSnapshots.", file=output)
    for index, value in enumerate(values[:10], start=1):
        print(
            f"{index}. {value.snapshot_id} — "
            f"{value.school_year}/{value.period_id} — "
            f"{value.row_count} rows",
            file=output,
        )
    remaining = len(values) - 10
    if remaining > 0:
        print(f"... {remaining} more snapshots not shown.", file=output)
    write_lines(output, "")
    pause_for_user(input_fn)


def _inspect(
    *,
    deps: SnapshotMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Inspect ReportingSnapshot")
    class_id = read_choice(input_fn, "Class ID: ")
    snapshot_id = read_choice(input_fn, "Snapshot ID: ")
    try:
        value = deps.inspector(
            deps.workspace_resolver(),
            class_id,
            snapshot_id,
        )
    except (
        WorkspaceRootError,
        ReportingSnapshotStorageError,
        ReportingSnapshotSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "The ReportingSnapshot could not be inspected safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    while True:
        clear_fn()
        item = value.item
        print_menu_header(output, "Frozen ReportingSnapshot")
        write_lines(
            output,
            f"Snapshot: {item.snapshot_id}",
            f"Definition: {item.definition_id}",
            f"Academic Period: {item.school_year} / {item.period_id}",
            f"Rows: {item.row_count}",
            f"Created: {item.created_at}",
            (
                "Current for this reporting scope: "
                f"{'yes' if value.current_for_scope else 'no'}"
            ),
            "",
            "This is frozen local Meridian reporting state.",
            "T. Technical details / provenance",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice.casefold() == "t":
            clear_fn()
            print_menu_header(
                output,
                "ReportingSnapshot — Technical details / provenance",
            )
            write_lines(
                output,
                f"snapshot_id: {item.snapshot_id}",
                f"snapshot_sha256: {item.snapshot_sha256}",
                f"definition_id: {item.definition_id}",
                f"definition_revision: {item.definition_revision}",
                f"calendar_revision: {item.calendar_revision}",
            )
            pause_for_user(input_fn)
            continue
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        write_lines(output, "", "Please choose T, B, M, or Q.")
        pause_for_user(input_fn)


def _show_current(
    *,
    deps: SnapshotMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Current ReportingSnapshot Selection")
    class_id = read_choice(input_fn, "Class ID: ")
    definition_id = read_choice(input_fn, "Reporting definition ID: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    try:
        calendar_revision = _positive_int(
            read_choice(input_fn, "Calendar revision: ")
        )
        value = deps.selection_loader(
            deps.workspace_resolver(),
            class_id,
            definition_id,
            AcademicPeriodRef(school_year, period_id),
            calendar_revision,
        )
    except (
        WorkspaceRootError,
        ReportingSnapshotSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Current reporting-use selection could not be loaded safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Current ReportingSnapshot Selection")
    if value.snapshot_id is None:
        write_lines(
            output,
            "Currently selected snapshot for reporting use: none",
        )
    else:
        write_lines(
            output,
            f"Snapshot: {value.snapshot_id}",
            f"Selection revision: {value.selection_revision}",
        )
    write_lines(
        output,
        "",
        "This selector is local reporting-use authority only.",
        "It is not an official SIS/district Grade.",
    )
    pause_for_user(input_fn)


def _select(
    *,
    deps: SnapshotMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Select ReportingSnapshot")
    class_id = read_choice(input_fn, "Class ID: ")
    snapshot_id = read_choice(input_fn, "Snapshot ID: ")
    actor_id = read_choice(input_fn, "Teacher actor ID: ")
    rationale_text = read_choice(input_fn, "Rationale (optional): ")
    rationale = rationale_text or None
    try:
        plan = deps.selection_previewer(
            deps.workspace_resolver(),
            class_id,
            snapshot_id,
            actor_id,
            rationale,
            deps.clock(),
        )
    except (
        WorkspaceRootError,
        ReportingSnapshotStorageError,
        ReportingSnapshotSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "ReportingSnapshot selection preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review ReportingSnapshot Selection")
    write_lines(
        output,
        f"Snapshot: {plan.snapshot_id}",
        f"Snapshot sha256: {plan.snapshot_sha256}",
        f"Definition: {plan.definition_id}",
        f"Academic Period: {plan.school_year} / {plan.period_id}",
        f"Rows: {plan.row_count}",
        f"Teacher: {plan.actor_id}",
        (
            "Currently selected snapshot: "
            f"{plan.current_snapshot_id or 'none'}"
        ),
        "",
        "Type SELECT to make this exact snapshot current for reporting use.",
    )
    confirmation = read_choice(input_fn, "Confirmation: ")
    if confirmation != "SELECT":
        write_lines(
            output,
            "",
            "Current ReportingSnapshot selection was not changed.",
        )
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.selection_committer(
            deps.workspace_resolver(),
            plan,
        )
    except (
        WorkspaceRootError,
        ReportingSnapshotSelectionError,
    ) as error:
        write_lines(
            output,
            "",
            "The reviewed ReportingSnapshot selection could not be committed.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"ReportingSnapshot selection: {disposition}.",
        "No official SIS/district Grade was changed.",
    )
    pause_for_user(input_fn)


def _author_definition(
    *,
    deps: SnapshotMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Author Reporting Definition")
    class_id = read_choice(input_fn, "Class ID: ")
    definition_id = read_choice(input_fn, "Reporting definition ID: ")
    title = read_choice(input_fn, "Report title: ")
    purpose = read_choice(input_fn, "Report purpose: ")
    school_year = read_choice(input_fn, "School year (YYYY-YYYY): ")
    period_id = read_choice(input_fn, "Academic Period ID: ")
    actor_id = read_choice(input_fn, "Teacher actor ID: ")
    rationale_text = read_choice(input_fn, "Rationale (optional): ")
    rationale = rationale_text or None
    try:
        plan = deps.definition_previewer(
            deps.workspace_resolver(),
            class_id,
            definition_id,
            title,
            purpose,
            AcademicPeriodRef(school_year, period_id),
            actor_id,
            rationale,
            deps.clock(),
        )
    except (WorkspaceRootError, ReportingSnapshotStorageError, ValueError) as error:
        write_lines(
            output,
            "",
            "Reporting Definition preview could not be prepared safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return

    clear_fn()
    print_menu_header(output, "Review Reporting Definition Before Write")
    write_lines(
        output,
        f"Definition: {plan.definition_id}",
        f"Revision: {plan.definition_revision}",
        f"Definition sha256: {plan.definition_sha256}",
        f"Title: {plan.title}",
        f"Purpose: {plan.purpose}",
        f"Academic Period: {plan.school_year} / {plan.period_id}",
        f"Teacher: {plan.actor_id}",
        f"Rationale: {plan.rationale or 'none'}",
        "",
        "Writing this revision does not select or freeze a ReportingSnapshot.",
        "Type WRITE to create this exact immutable definition revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No Reporting Definition was written.")
        pause_for_user(input_fn)
        return
    try:
        disposition = deps.definition_committer(
            deps.workspace_resolver(),
            plan,
        )
    except (WorkspaceRootError, ReportingSnapshotStorageError) as error:
        write_lines(
            output,
            "",
            "The reviewed Reporting Definition could not be committed safely.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Reporting Definition revision: {disposition}.",
        "No ReportingSnapshot or official school-system Grade was changed.",
    )
    pause_for_user(input_fn)


def run_snapshots_menu(
    *,
    dependencies: SnapshotMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_snapshot_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Snapshots")
        write_lines(
            stream,
            "1. List frozen ReportingSnapshots",
            "2. Inspect a ReportingSnapshot",
            "3. Show current reporting-use selection",
            "4. Select an existing ReportingSnapshot",
            "5. Author a Reporting Definition revision",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _list(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "2":
            _inspect(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "3":
            _show_current(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "4":
            _select(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        if choice == "5":
            _author_definition(
                deps=deps,
                input_fn=input_fn,
                output=stream,
                clear_fn=clear_fn,
            )
            continue
        write_lines(stream, "", "Please choose 1-5, B, M, or Q.")
        pause_for_user(input_fn)
