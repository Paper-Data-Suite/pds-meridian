"""Read-only class-local recovery inbox for teacher saves interrupted by restart."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, TextIO

from pds_core.class_metadata import ClassMetadataError, load_class_metadata
from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routes import class_metadata_path
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_eligibility import EvidenceSourceReference
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
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.teacher_action_contract import teacher_action_outcome_message
from meridian.teacher_action_orchestration import TeacherActionConflictError
from meridian.teacher_action_receipts import (
    TeacherActionReceiptError,
    TeacherActionReceiptStore,
)
from meridian.teacher_action_recovery_inventory import (
    RecoveryInboxEntry,
    TeacherActionRecoveryInventoryError,
    read_recovery_inbox,
)
from meridian.teacher_action_restart_eligibility import (
    inspect_restart_eligibility,
    load_fresh_restart_authorization,
    resume_restart_eligibility,
)
from meridian.teacher_action_restart_grade_item import (
    inspect_restart_grade_item,
    resume_restart_grade_item,
)
from meridian.teacher_action_restart_membership import (
    inspect_restart_membership,
    resume_restart_membership,
)
from meridian.teacher_session import TeacherSessionContext


def _validate_class(root: Path, class_id: str) -> None:
    metadata = load_class_metadata(class_metadata_path(root, class_id))
    if metadata.class_id != class_id:
        raise ValueError("Class metadata does not match the requested class.")


def _show_entry(output: TextIO, entry: RecoveryInboxEntry) -> None:
    print_menu_header(output, "Review Saved Action Checkpoint")
    write_lines(
        output,
        f"Action: {entry.title}",
        f"Last journal stage: {entry.stage.replace('_', ' ')}",
        f"Stage disposition: {entry.disposition}",
        f"Journal updated: {entry.recorded_at}",
        f"Review: {entry.description}",
        "",
        "This is a JOURNAL observation, not confirmation of current status.",
        "No canonical academic state has been independently verified here.",
        "Do not repeat Save based solely on this checkpoint.",
        "Return to the relevant workflow and inspect the current decision.",
        "No write, selection or permission change was requested.",
    )


def _offer_grade_item_resume(
    root: Path,
    store: TeacherActionReceiptStore,
    entry: RecoveryInboxEntry,
    *,
    input_fn: InputFunction,
    output: TextIO,
) -> None:
    """Only verified, exact creation recovery may present an active control."""
    try:
        inspection = inspect_restart_grade_item(root, store, entry.receipt)
    except (
        TeacherActionConflictError,
        TeacherActionReceiptError,
        ValueError,
        OSError,
    ):
        write_lines(
            output,
            "",
            "Exact Grade Item recovery could not be verified safely.",
            "No selection changed. Review current Grade Item state manually.",
        )
        return
    if not inspection.can_resume:
        write_lines(
            output,
            "",
            "Exact Grade Item resume is not authorized by current state.",
            "No selection changed. Review current Grade Item state manually.",
        )
        return
    write_lines(
        output,
        "",
        f"Saved Grade Item: {inspection.title}",
        "The exact immutable revision exists, and its original",
        "unselected CAS baseline and teacher attribution were reverified.",
        "Type RESUME to select ONLY this saved Grade Item revision.",
        "Any other input leaves it unselected.",
    )
    if read_choice(input_fn, "Confirmation: ") != "RESUME":
        write_lines(output, "", "Canceled; no selection changed.")
        return
    try:
        result = resume_restart_grade_item(
            root, store, entry.receipt, confirmation="RESUME"
        )
        write_lines(output, "", teacher_action_outcome_message(result))
    except (
        TeacherActionConflictError,
        TeacherActionReceiptError,
        ValueError,
        OSError,
    ):
        write_lines(
            output,
            "",
            "Exact selection was blocked or could not be verified.",
            "Review current canonical Grade Item state before any retry.",
        )


def _offer_membership_resume(
    root: Path,
    store: TeacherActionReceiptStore,
    entry: RecoveryInboxEntry,
    *,
    input_fn: InputFunction,
    output: TextIO,
) -> None:
    """Only an exact, current-dependency-verified relationship is selectable."""
    try:
        inspection = inspect_restart_membership(root, store, entry.receipt)
    except (RuntimeError, ValueError, OSError):
        write_lines(
            output,
            "",
            "Exact work relationship could not be verified safely.",
            "No selection changed. Review current relationships manually.",
        )
        return
    if not inspection.can_resume:
        write_lines(
            output,
            "",
            "The saved relationship cannot be resumed under current conditions.",
            "No selection changed. Review current relationships manually.",
        )
        return
    write_lines(
        output,
        "",
        "Saved work relationship: Verified exact included decision",
        "Its Grade Item, work registration and academic period were rechecked.",
        "The original current-selection baseline still matches.",
        "Type RESUME to select ONLY this previously saved relationship.",
        "Any other input leaves the current selection unchanged.",
    )
    if read_choice(input_fn, "Confirmation: ") != "RESUME":
        write_lines(output, "", "Canceled; no selection changed.")
        return
    try:
        result = resume_restart_membership(
            root, store, entry.receipt, confirmation="RESUME"
        )
        write_lines(output, "", teacher_action_outcome_message(result))
    except (RuntimeError, ValueError, OSError):
        write_lines(
            output,
            "",
            "Exact relationship selection was blocked or could not be verified.",
            "Review canonical Grade Item membership before retrying.",
        )


def _offer_eligibility_resume(
    root: Path,
    store: TeacherActionReceiptStore,
    entry: RecoveryInboxEntry,
    *,
    diagnostics: DiagnosticsDependencies | None,
    input_fn: InputFunction,
    output: TextIO,
) -> None:
    """Fresh evidence authorization is mandatory; a receipt is NOT a grant."""
    if diagnostics is None or diagnostics.authorizer is None:
        write_lines(
            output,
            "",
            "Exact evidence access is not available in this session.",
            "Use A. Set Up Evidence Access, then reopen recovery.",
            "No eligibility selection was changed.",
        )
        return

    def authorized_loader(
        root: Path, source: EvidenceSourceReference
    ) -> AuthorizedProjectionSnapshot:
        return load_fresh_restart_authorization(root, source, diagnostics)

    try:
        inspection = inspect_restart_eligibility(
            root, store, entry.receipt, authorized_loader=authorized_loader
        )
    except (RuntimeError, ValueError, OSError):
        write_lines(
            output,
            "",
            (
                "The saved eligibility and its current authorization "
                "could not be verified."
            ),
            "No selection changed. Review current evidence before retrying.",
        )
        return
    if not inspection.can_resume:
        write_lines(
            output,
            "",
            "Exact eligibility resume is unavailable under current source state.",
            "No selection changed. Review current evidence manually.",
        )
        return
    write_lines(
        output,
        "",
        (
            "The exact saved eligibility decision and current evidence "
            "access were rechecked."
        ),
        "The original current-selection baseline still matches.",
        "Type RESUME to select ONLY this previously saved eligibility decision.",
        "Any other input leaves it unselected.",
    )
    if read_choice(input_fn, "Confirmation: ") != "RESUME":
        write_lines(output, "", "Canceled; no selection changed.")
        return
    try:
        result = resume_restart_eligibility(
            root,
            store,
            entry.receipt,
            confirmation="RESUME",
            authorized_loader=authorized_loader,
        )
        write_lines(output, "", teacher_action_outcome_message(result))
    except (RuntimeError, ValueError, OSError):
        write_lines(
            output,
            "",
            "Exact eligibility selection was blocked or could not be verified.",
            "Refresh current authorized evidence before attempting recovery.",
        )


def run_teacher_action_recovery_menu(
    *,
    session_context: TeacherSessionContext,
    diagnostics: DiagnosticsDependencies | None = None,
    workspace_resolver: Callable[[], Path] = resolve_workspace_root,
    class_validator: Callable[[Path, str], None] = _validate_class,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    """Display exact journal records after restart, without replay authority."""
    stream = sys.stdout if output is None else output
    clear_fn()
    print_menu_header(stream, "Review Interrupted Saves")
    class_id = session_context.active_class_id
    if class_id is None:
        class_id = read_choice(input_fn, "Class ID (blank to cancel): ").strip()
        if not class_id:
            return
        if parse_navigation_choice(class_id) is NavigationChoice.BACK:
            return
    try:
        root = workspace_resolver()
        class_validator(root, class_id)
        store = TeacherActionReceiptStore(root, class_id)
        inbox = read_recovery_inbox(store)
    except (
        WorkspaceRootError,
        ClassMetadataError,
        TeacherActionReceiptError,
        TeacherActionRecoveryInventoryError,
        ValueError,
        OSError,
    ) as error:
        write_lines(
            stream,
            "",
            "The recovery journal could not be reviewed completely or safely.",
            "No academic record was changed. Inspect the journal before retrying.",
            f"Details: {error}",
        )
        pause_for_user(input_fn)
        return
    page = 0
    page_size = 10
    while True:
        clear_fn()
        print_menu_header(stream, "Review Interrupted Saves")
        write_lines(
            stream,
            f"Class: {inbox.class_id}",
            f"Checkpoints needing review: {inbox.review_count}",
            f"Finalized receipts: {inbox.completed_receipt_count}",
            "",
            "This screen reads journal metadata only; it does not verify",
            "canonical academic state or authorize another write.",
            "",
        )
        if not inbox.entries:
            write_lines(stream, "No action receipts were found for this class.")
        start = page * page_size
        visible = inbox.entries[start : start + page_size]
        if inbox.entries:
            write_lines(
                stream,
                f"Showing {start + 1}-{start + len(visible)} of {len(inbox.entries)}",
            )
        for index, entry in enumerate(visible, 1):
            print(f"{index}. {entry.title} — {entry.description}", file=stream)
        write_lines(stream, "", "N. Next page    P. Previous page")
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        navigation = parse_navigation_choice(choice)
        if navigation is NavigationChoice.BACK or choice == "":
            return
        if choice.casefold() == "n":
            if (page + 1) * page_size < len(inbox.entries):
                page += 1
            continue
        if choice.casefold() == "p":
            page = max(0, page - 1)
            continue
        if choice.isascii() and choice.isdigit():
            ordinal = int(choice)
            if 1 <= ordinal <= len(visible):
                clear_fn()
                entry = visible[ordinal - 1]
                _show_entry(stream, entry)
                if entry.kind == "grade_item":
                    _offer_grade_item_resume(
                        root, store, entry, input_fn=input_fn, output=stream
                    )
                elif entry.kind == "grade_item_membership":
                    _offer_membership_resume(
                        root, store, entry, input_fn=input_fn, output=stream
                    )
                elif entry.kind == "eligibility":
                    _offer_eligibility_resume(
                        root,
                        store,
                        entry,
                        diagnostics=diagnostics,
                        input_fn=input_fn,
                        output=stream,
                    )
                write_lines(stream, "")
                pause_for_user(input_fn)
                continue
        write_lines(
            stream,
            "",
            f"Choose 1-{len(visible)}, N, P, or B to return.",
        )
        pause_for_user(input_fn)


__all__ = ("run_teacher_action_recovery_menu",)
