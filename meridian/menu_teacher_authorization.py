"""Teacher-facing, explicitly confirmed evidence-authorization setup.

Class selection uses existing Core workspace class directories. Exact current
publication scope comes only from Core-backed Meridian discovery. The menu never
accepts typed student/publication IDs, inspects manifest payloads, or grants
permissions on discovery alone. Saved grants take effect only after confirmation.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final, TextIO, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.diagnostics import (
    DiagnosticsDependencies,
    DiagnosticsError,
    default_diagnostics_dependencies,
)
from meridian.ingestion import PublicationIngestionError
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
from meridian.publication_authorization import (
    PublicationAuthorizationConfigurationError,
    TeacherLocalPublicationAuthorizer,
)
from meridian.publication_authorization_setup import (
    PublicationAccessPlan,
    PublicationAuthorizationSetupError,
    commit_publication_access,
    preview_publication_access,
)
from meridian.teacher_evidence_inbox import (
    TeacherEvidenceInbox,
    TeacherEvidenceInboxError,
    TeacherEvidenceInboxItem,
    load_teacher_evidence_inbox,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
EvidenceListLoader: TypeAlias = Callable[
    [Path, DiagnosticsDependencies], TeacherEvidenceInbox
]

# Corresponds to the three current built-in academic-result adapters; other
# providers must not be granted access until their contract is supported.
_SUPPORTED_PRODUCERS: Final[tuple[tuple[str, str], ...]] = (
    ("scoreform", "ScoreForm"),
    ("quillan", "Quillan"),
    ("concord", "Concord"),
)


def _classes(root: Path) -> tuple[str, ...]:
    """Read existing Core class directories without changing the workspace."""
    folder = root / "classes"
    if folder.is_symlink():
        raise PublicationAuthorizationSetupError(
            "The class directory is linked; class selection cannot be trusted."
        )
    if not folder.exists():
        return ()
    if not folder.is_dir():
        raise PublicationAuthorizationSetupError("The class directory is invalid.")
    found: list[str] = []
    for entry in folder.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            key = validate_identifier(entry.name)
        except (IdentifierValidationError, ValueError, TypeError):
            continue
        if key == entry.name:
            found.append(key)
    return tuple(sorted(found))


def _current_items(
    root: Path,
    diagnostics: DiagnosticsDependencies,
    loader: EvidenceListLoader,
    class_id: str,
) -> tuple[TeacherEvidenceInboxItem, ...]:
    """Only canonical, distinguishable current publications may be granted."""
    inbox = loader(root, diagnostics)
    return tuple(
        item
        for item in inbox.items
        if item.work.class_id == class_id
        and item.canonical_state == "current_selectable"
        and item.status_code not in {
            "ambiguous_presentation",
            "work_title_unavailable",
        }
        and item.work.module_id in dict(_SUPPORTED_PRODUCERS)
    )


def _read_navigation(choice: str) -> bool:
    """Return True for Back; Main/Quit propagate as Core navigation."""
    navigation = parse_navigation_choice(choice)
    return navigation is NavigationChoice.BACK or choice == ""


def _select_publication(
    root: Path,
    class_id: str,
    diagnostics: DiagnosticsDependencies,
    loader: EvidenceListLoader,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> TeacherEvidenceInboxItem | None:
    while True:
        clear_fn()
        print_menu_header(output, "Authorize One Current Publication")
        try:
            items = _current_items(root, diagnostics, loader, class_id)
        except (
            DiagnosticsError,
            PublicationIngestionError,
            TeacherEvidenceInboxError,
            ValueError,
            OSError,
        ):
            write_lines(
                output,
                "The current publication list is unavailable or invalid.",
                "No access has been granted. Correct discovery and try again.",
            )
            pause_for_user(input_fn)
            return None
        if not items:
            write_lines(
                output,
                "No distinct, current supported publications are available.",
                "Use producer-wide access only if that broader scope is intended.",
            )
            pause_for_user(input_fn)
            return None
        write_lines(
            output, f"Class: {class_id}", "Select one existing evidence set.", ""
        )
        for index, item in enumerate(items, start=1):
            print(f"{index}. {item.work_title} — {item.producer_label}", file=output)
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if _read_navigation(choice):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(items):
            return items[int(choice) - 1]
        write_lines(output, "", "Select a listed publication or B to go back.")
        pause_for_user(input_fn)


def _revalidate_selected_publication(
    root: Path,
    diagnostics: DiagnosticsDependencies,
    loader: EvidenceListLoader,
    chosen: TeacherEvidenceInboxItem,
) -> bool:
    """Prevent stale menus from granting a changed/withdrawn publication."""
    candidates = _current_items(root, diagnostics, loader, chosen.work.class_id)
    return any(
        item.publication_id == chosen.publication_id
        and item.work == chosen.work
        and item.work_title == chosen.work_title
        and item.producer_label == chosen.producer_label
        for item in candidates
    )


def _confirm_plan(
    plan: PublicationAccessPlan,
    *,
    selected: TeacherEvidenceInboxItem | None,
    diagnostics: DiagnosticsDependencies,
    loader: EvidenceListLoader,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> TeacherLocalPublicationAuthorizer | None:
    clear_fn()
    print_menu_header(output, "Confirm Evidence Access")
    write_lines(
        output,
        f"Class: {plan.class_id}",
        "Source(s): " + ", ".join(
            dict(_SUPPORTED_PRODUCERS).get(key, key)
            for key in plan.producer_module_ids
        ),
        (
            f"Assignment: {selected.work_title}"
            if selected is not None else "Assignments: current and future"
        ),
        f"Scope: {plan.scope_label}",
        "Purpose: evidence review and teacher reporting",
        "Includes protected student evidence for the authorized scope.",
        "Does not publish, grade, or change any student work.",
        "",
        "Type AUTHORIZE to save this access grant, or B to cancel.",
    )
    confirmation = read_choice(input_fn, "Confirmation: ")
    if confirmation != "AUTHORIZE":
        _read_navigation(confirmation)
        write_lines(output, "Access was not changed.")
        pause_for_user(input_fn)
        return None
    try:
        if selected is not None and not _revalidate_selected_publication(
            plan.workspace_root, diagnostics, loader, selected
        ):
            raise PublicationAuthorizationSetupError(
                "Publication changed or is no longer current; refresh and review again."
            )
        authorized = commit_publication_access(plan, confirmation=confirmation)
    except (
        PublicationAuthorizationSetupError,
        PublicationAuthorizationConfigurationError,
        DiagnosticsError,
        PublicationIngestionError,
        TeacherEvidenceInboxError,
        OSError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "Authorization could not be completed safely.",
            str(error),
            "Review the current policy before retrying.",
        )
        pause_for_user(input_fn)
        return None
    write_lines(
        output,
        "Authorization is configured for the selected scope.",
        "Return to Review New Evidence to open authorized results.",
    )
    pause_for_user(input_fn)
    return authorized


def _setup_class(
    root: Path,
    class_id: str,
    diagnostics: DiagnosticsDependencies,
    loader: EvidenceListLoader,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> TeacherLocalPublicationAuthorizer | None:
    while True:
        clear_fn()
        print_menu_header(output, "Set Up Evidence Access")
        write_lines(
            output,
            f"Class: {class_id}",
            "Choose exactly which results Meridian may read.",
            "",
            "1. All current and future ScoreForm results",
            "2. All current and future Quillan results",
            "3. All current and future Concord results",
            "4. All current and future results from all three sources",
            "5. Only one existing published evidence set",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if _read_navigation(choice):
            return None
        selected: TeacherEvidenceInboxItem | None = None
        if choice in {"1", "2", "3", "4"}:
            producers = (
                ("concord", "quillan", "scoreform")
                if choice == "4"
                else (_SUPPORTED_PRODUCERS[int(choice) - 1][0],)
            )
            publication_ids: tuple[str, ...] = ()
            future = True
        elif choice == "5":
            selected = _select_publication(
                root, class_id, diagnostics, loader,
                input_fn=input_fn, output=output, clear_fn=clear_fn,
            )
            if selected is None:
                continue
            producers = (selected.work.module_id,)
            publication_ids = (selected.publication_id,)
            future = False
        else:
            write_lines(output, "", "Please choose 1-5, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        try:
            plan = preview_publication_access(
                root,
                class_id=class_id,
                producer_module_ids=producers,
                publication_ids=publication_ids,
                include_future_publications=future,
            )
        except (PublicationAuthorizationSetupError, OSError, ValueError) as error:
            write_lines(output, "", "Access setup is blocked:", str(error))
            pause_for_user(input_fn)
            continue
        return _confirm_plan(
            plan, selected=selected, diagnostics=diagnostics, loader=loader,
            input_fn=input_fn, output=output, clear_fn=clear_fn,
        )


def run_teacher_evidence_authorization_menu(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
    workspace_resolver: WorkspaceResolver = resolve_workspace_root,
    inbox_loader: EvidenceListLoader = load_teacher_evidence_inbox,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> TeacherLocalPublicationAuthorizer | None:
    """Manage access and return a *loaded* provider to activate this session."""
    stream = sys.stdout if output is None else output
    active = diagnostics or default_diagnostics_dependencies()
    try:
        root = workspace_resolver().resolve(strict=True)
        if not root.is_dir():
            raise PublicationAuthorizationSetupError("Workspace is not a directory.")
        classes = _classes(root)
    except (WorkspaceRootError, PublicationAuthorizationSetupError, OSError) as error:
        clear_fn()
        print_menu_header(stream, "Evidence Access Unavailable")
        write_lines(stream, str(error), "No access has been granted.")
        pause_for_user(input_fn)
        return None
    while True:
        clear_fn()
        print_menu_header(stream, "Set Up Evidence Access")
        if not classes:
            write_lines(
                stream,
                "No existing PDS classes were found in this workspace.",
                "Create or select a class in Paper Data Suite first.",
            )
            pause_for_user(input_fn)
            return None
        write_lines(stream, "Select a class to authorize.", "")
        for index, class_id in enumerate(classes, start=1):
            print(f"{index}. {class_id}", file=stream)
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        if _read_navigation(choice):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(classes):
            return _setup_class(
                root, classes[int(choice) - 1], active, inbox_loader,
                input_fn=input_fn, output=stream, clear_fn=clear_fn,
            )
        write_lines(stream, "", "Please select an existing class or B to go back.")
        pause_for_user(input_fn)


__all__ = ["run_teacher_evidence_authorization_menu"]
