"""Class-first guided teacher evidence inbox menu for Issue #110."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.diagnostics import (
    DiagnosticsDependencies,
    DiagnosticsError,
    default_diagnostics_dependencies,
)
from meridian.guided_projection import (
    GuidedProjectionAuthorizationDeniedError,
    GuidedProjectionAuthorizationUnavailableError,
    GuidedProjectionCurrentUseBlockedError,
    GuidedProjectionError,
    GuidedProjectionResult,
    GuidedProjectionSelectionStaleError,
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
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
from meridian.teacher_evidence_inbox import (
    TeacherEvidenceClassGroup,
    TeacherEvidenceInbox,
    TeacherEvidenceInboxError,
    TeacherEvidenceInboxItem,
    load_teacher_evidence_inbox,
)
from meridian.teacher_session import TeacherSessionContext

WorkspaceResolver: TypeAlias = Callable[[], Path]
TeacherEvidenceInboxLoader: TypeAlias = Callable[
    [Path, DiagnosticsDependencies],
    TeacherEvidenceInbox,
]
GuidedProjectionPreparer: TypeAlias = Callable[
    [Path, ModuleWorkRef, str],
    GuidedProjectionResult,
]


@dataclass(frozen=True, slots=True)
class TeacherEvidenceInboxMenuDependencies:
    """Read-only dependencies for the guided Review New Evidence route."""

    workspace_resolver: WorkspaceResolver
    diagnostics: DiagnosticsDependencies
    inbox_loader: TeacherEvidenceInboxLoader
    projection_preparer: GuidedProjectionPreparer


def default_teacher_evidence_inbox_menu_dependencies(
    *,
    diagnostics: DiagnosticsDependencies | None = None,
) -> TeacherEvidenceInboxMenuDependencies:
    """Compose the normal read-only inbox discovery boundary."""

    active = diagnostics or default_diagnostics_dependencies()

    projection_dependencies = default_guided_projection_dependencies(
        diagnostics=active
    )

    def load(
        root: Path,
        active_diagnostics: DiagnosticsDependencies,
    ) -> TeacherEvidenceInbox:
        return load_teacher_evidence_inbox(root, active_diagnostics)

    def prepare(
        root: Path,
        work: ModuleWorkRef,
        publication_id: str,
    ) -> GuidedProjectionResult:
        return prepare_guided_evidence_projection(
            root,
            work,
            publication_id,
            dependencies=projection_dependencies,
        )

    return TeacherEvidenceInboxMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        diagnostics=active,
        inbox_loader=load,
        projection_preparer=prepare,
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _group_counts(group: TeacherEvidenceClassGroup) -> tuple[int, int]:
    ready = sum(item.actionability == "ready" for item in group.items)
    blocked = len(group.items) - ready
    return ready, blocked


def _render_class_list(
    output: TextIO,
    inbox: TeacherEvidenceInbox,
    session: TeacherSessionContext,
) -> None:
    print_menu_header(output, "Review New Evidence")
    if not inbox.groups:
        write_lines(
            output,
            "No current academic evidence publications were found.",
            "",
        )
        print_standard_navigation(output)
        return

    write_lines(output, "Choose a class.", "")
    for index, group in enumerate(inbox.groups, start=1):
        ready, blocked = _group_counts(group)
        selected = session.active_class_id == group.class_id
        suffix = " · Current class" if selected else ""
        print(f"{index}. {group.class_label}{suffix}", file=output)
        summary = [
            _plural(len(group.items), "evidence set"),
            f"{ready} ready",
        ]
        if blocked:
            summary.append(f"{blocked} needs attention")
        print(f"   {' · '.join(summary)}", file=output)
    write_lines(output, "")
    print_standard_navigation(output)


def _render_assignment_list(
    output: TextIO,
    group: TeacherEvidenceClassGroup,
    session: TeacherSessionContext,
) -> None:
    print_menu_header(output, "Review New Evidence")
    write_lines(
        output,
        f"Class: {group.class_label}",
        "Choose evidence to continue.",
        "",
    )
    for index, item in enumerate(group.items, start=1):
        selected = (
            session.active_work == item.work
            and session.active_publication_id == item.publication_id
        )
        suffix = " · Selected for this session" if selected else ""
        print(f"{index}. {item.work_title}", file=output)
        print(
            f"   {item.producer_label} · {item.status_label}{suffix}",
            file=output,
        )
    write_lines(output, "")
    print_standard_navigation(output)


def _status_explanation(item: TeacherEvidenceInboxItem) -> tuple[str, ...]:
    explanations = {
        "refresh_needed": (
            "This evidence changed after the list was discovered.",
            "Return to the evidence list and refresh before using it.",
        ),
        "publication_unavailable": (
            "This evidence source is no longer available in canonical PDS state.",
            "Nothing was opened or changed.",
        ),
        "no_longer_current": (
            "This evidence source is no longer current.",
            "Use a current evidence source instead.",
        ),
        "reader_unavailable": (
            "Meridian does not currently have the required reader installed.",
            "This evidence remains visible, but it cannot be opened safely.",
        ),
        "reader_not_compatible": (
            "The installed reader is not compatible with this evidence.",
            "This evidence remains visible, but it cannot be opened safely.",
        ),
        "not_supported": (
            "Meridian does not support this evidence contract yet.",
            "This evidence remains visible, but it cannot be opened safely.",
        ),
        "compatibility_unavailable": (
            "Meridian could not verify reader compatibility safely.",
            "This evidence remains visible, but it cannot be opened.",
        ),
        "work_title_unavailable": (
            "The assignment name is unavailable from canonical PDS state.",
            "Meridian will not substitute an internal work identifier.",
        ),
        "ambiguous_presentation": (
            "More than one current evidence source has the same visible class,",
            "assignment, and source. Meridian will not ask you to distinguish",
            "them by an internal Publication ID.",
        ),
    }
    return explanations.get(
        item.status_code,
        (
            "This evidence source is not ready for guided review.",
            "Nothing was opened or changed.",
        ),
    )


def _show_blocked_item(
    *,
    item: TeacherEvidenceInboxItem,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Evidence Not Ready")
    write_lines(
        output,
        f"Class: {item.class_label}",
        f"Assignment: {item.work_title}",
        f"Source: {item.producer_label}",
        f"Status: {item.status_label}",
        "",
        *_status_explanation(item),
    )
    pause_for_user(input_fn)


def _show_prepared_selection(
    *,
    item: TeacherEvidenceInboxItem,
    prepared: GuidedProjectionResult,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Evidence Ready")
    write_lines(
        output,
        f"Class: {item.class_label}",
        f"Assignment: {item.work_title}",
        f"Source: {item.producer_label}",
        f"Evidence rows available: {prepared.evidence_count}",
        "",
        "Authorized evidence is prepared for review.",
        "Meridian resolved the publication and projection internally.",
    )
    pause_for_user(input_fn)


def _show_projection_failure(
    *,
    item: TeacherEvidenceInboxItem,
    error: GuidedProjectionError,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    if isinstance(error, GuidedProjectionAuthorizationUnavailableError):
        lines = (
            "Evidence access is not configured for this Meridian process.",
            "No protected evidence was opened.",
        )
    elif isinstance(error, GuidedProjectionAuthorizationDeniedError):
        lines = (
            "Access to this evidence was denied by the configured policy.",
            "No protected evidence was opened.",
        )
    elif isinstance(error, GuidedProjectionSelectionStaleError):
        lines = (
            "This evidence selection is no longer current.",
            "Return to the list and choose the current evidence source.",
        )
    elif isinstance(error, GuidedProjectionCurrentUseBlockedError):
        lines = (
            "The prepared evidence is no longer valid for current review.",
            "Return to the list and refresh before continuing.",
        )
    else:
        lines = (
            "This evidence could not be prepared safely.",
            "No evidence workflow state was changed.",
        )

    clear_fn()
    print_menu_header(output, "Evidence Not Ready")
    write_lines(
        output,
        f"Class: {item.class_label}",
        f"Assignment: {item.work_title}",
        f"Source: {item.producer_label}",
        "",
        *lines,
    )
    pause_for_user(input_fn)


def _run_class_evidence_menu(
    *,
    root: Path,
    group: TeacherEvidenceClassGroup,
    dependencies: TeacherEvidenceInboxMenuDependencies,
    session_context: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    while True:
        clear_fn()
        _render_assignment_list(output, group, session_context)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return

        if choice.isdigit():
            selected_index = int(choice)
            if 1 <= selected_index <= len(group.items):
                item = group.items[selected_index - 1]
                if item.actionability == "blocked":
                    _show_blocked_item(
                        item=item,
                        input_fn=input_fn,
                        output=output,
                        clear_fn=clear_fn,
                    )
                    continue

                try:
                    prepared = dependencies.projection_preparer(
                        root,
                        item.work,
                        item.publication_id,
                    )
                except GuidedProjectionError as error:
                    _show_projection_failure(
                        item=item,
                        error=error,
                        input_fn=input_fn,
                        output=output,
                        clear_fn=clear_fn,
                    )
                    continue

                session_context.select_work(item.work)
                session_context.select_publication(item.publication_id)
                _show_prepared_selection(
                    item=item,
                    prepared=prepared,
                    input_fn=input_fn,
                    output=output,
                    clear_fn=clear_fn,
                )
                continue

        write_lines(
            output,
            "",
            f"Please choose 1-{len(group.items)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


def run_teacher_evidence_inbox_menu(
    *,
    dependencies: TeacherEvidenceInboxMenuDependencies,
    session_context: TeacherSessionContext,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Run class-first guided Review New Evidence navigation."""

    stream = sys.stdout if output is None else output
    while True:
        try:
            root = dependencies.workspace_resolver()
            inbox = dependencies.inbox_loader(root, dependencies.diagnostics)
        except WorkspaceRootError:
            clear_fn()
            print_menu_header(stream, "Review New Evidence")
            write_lines(
                stream,
                "The Paper Data Suite workspace could not be resolved.",
                "No evidence was opened or changed.",
            )
            pause_for_user(input_fn)
            return
        except (
            DiagnosticsError,
            PublicationIngestionError,
            TeacherEvidenceInboxError,
            ValueError,
        ):
            clear_fn()
            print_menu_header(stream, "Review New Evidence")
            write_lines(
                stream,
                "Current evidence could not be listed safely.",
                "No evidence was opened or changed.",
                "Use the exact CLI diagnostics only if technical "
                "investigation is needed.",
            )
            pause_for_user(input_fn)
            return

        clear_fn()
        _render_class_list(stream, inbox, session_context)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return

        if choice.isdigit():
            selected_index = int(choice)
            if 1 <= selected_index <= len(inbox.groups):
                group = inbox.groups[selected_index - 1]
                session_context.select_class(group.class_id)
                _run_class_evidence_menu(
                    root=root,
                    group=group,
                    dependencies=dependencies,
                    session_context=session_context,
                    input_fn=input_fn,
                    output=stream,
                    clear_fn=clear_fn,
                )
                continue

        write_lines(
            stream,
            "",
            f"Please choose 1-{len(inbox.groups)}, B, M, or Q.",
        )
        pause_for_user(input_fn)


__all__ = (
    "TeacherEvidenceInboxMenuDependencies",
    "default_teacher_evidence_inbox_menu_dependencies",
    "run_teacher_evidence_inbox_menu",
)
