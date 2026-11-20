"""#126-F1/F2A/F2B/F3A assessment queue, history and recovery entry.

The queue remains a read-only #125/#30/#31 projection; original native
observations are never ranked or inferred as corrections. One explicit
teacher-reviewed #30 correction and #30/#31 reassessment actions are delegated.
F3A exposes bounded canonical history and existing class journal review.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_attempt_inventory import (
    PAGE_SIZE,
    AssessmentAttemptInventory,
    StudentAttemptInventoryRow,
    project_assessment_attempt_inventory,
)
from meridian.guided_attempts import GuidedAttemptDependencies
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityGradeItemChoice,
    discover_guided_eligibility_grade_items,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_attempts import _choose_grade_item
from meridian.menu_teacher_correction_decision import (
    run_teacher_correction_decision_menu,
)
from meridian.menu_teacher_correction_history import (
    run_bound_teacher_recovery_menu,
    run_teacher_corrections_history_menu,
)
from meridian.menu_teacher_reassessment_decision import (
    run_teacher_reassessment_decision_menu,
)
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_session import TeacherSessionContext


class CorrectionsMenuError(ValueError):
    """Requested read-only source/roster context cannot be established."""


def _discover_grade_items(
    root: Path,
    work: ModuleWorkRef,
    dependencies: GuidedEligibilityDependencies,
) -> tuple[GuidedEligibilityGradeItemChoice, ...]:
    return discover_guided_eligibility_grade_items(
        root, work, dependencies=dependencies
    )


def _load_inventory(
    root: Path,
    grade_item_id: str,
    prepared: GuidedProjectionResult,
    class_label: str,
    assessment_title: str,
) -> AssessmentAttemptInventory:
    return project_assessment_attempt_inventory(
        root,
        grade_item_id=grade_item_id,
        prepared=prepared,
        class_label=class_label,
        assessment_title=assessment_title,
    )


@dataclass(frozen=True, slots=True)
class CorrectionsMenuPorts:
    """Bounded assessment loaders plus explicit guarded correction action."""

    grade_items_loader: Callable[
        [Path, ModuleWorkRef, GuidedEligibilityDependencies],
        tuple[GuidedEligibilityGradeItemChoice, ...],
    ] = _discover_grade_items
    inventory_loader: Callable[
        [Path, str, GuidedProjectionResult, str, str],
        AssessmentAttemptInventory,
    ] = _load_inventory
    correction_handler: Callable[..., bool] = run_teacher_correction_decision_menu
    reassessment_handler: Callable[..., bool] = run_teacher_reassessment_decision_menu
    decision_history_handler: Callable[..., None] = run_teacher_corrections_history_menu
    recovery_handler: Callable[..., None] = run_bound_teacher_recovery_menu


def _safe(value: object, *, limit: int = 112) -> str:
    """Never send untrusted roster/producer terminal control bytes to output."""
    raw = str(value)
    result = "".join(
        ch if ch.isprintable() and ch not in {"\x1b", "\x7f"} else "?" for ch in raw
    )
    return result[:limit] + ("..." if len(result) > limit else "")


def _status(row: StudentAttemptInventoryRow) -> str:
    if row.selection_status in {"selected", "selected_none"}:
        return f"#30: {row.selection_status.replace('_', ' ')}"
    return f"#30: {_safe(row.selection_status or 'unavailable')}"


def _queue_rows(
    inventory: AssessmentAttemptInventory, *, attention_only: bool
) -> tuple[StudentAttemptInventoryRow, ...]:
    return tuple(
        student
        for student in inventory.students
        if not attention_only or student.needs_attention
    )


def _page_count(rows: tuple[StudentAttemptInventoryRow, ...]) -> int:
    return max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)


def _print_queue(
    output: TextIO,
    inventory: AssessmentAttemptInventory,
    *,
    attention_only: bool,
    page: int,
) -> tuple[StudentAttemptInventoryRow, ...]:
    rows = _queue_rows(inventory, attention_only=attention_only)
    start = (page - 1) * PAGE_SIZE
    current = rows[start : start + PAGE_SIZE]
    print_menu_header(output, "Review Corrections & Attempts")
    write_lines(
        output,
        f"Class: {_safe(inventory.class_label or 'Current class')}",
        f"Assessment: {_safe(inventory.assessment_title or 'Selected assessment')}",
        f"Source: {_safe(inventory.source_status)}; "
        f"Grade Item: {_safe(inventory.membership_state)}",
        f"Authorized students: {len(inventory.students)}; "
        f"attention: {inventory.attention_count}",
        f"Shared/unmatched evidence: "
        f"{inventory.shared_item_count}/{inventory.unmatched_item_count}",
        "Native attempts and scores do not establish a correction or retake.",
        "Queue navigation is read-only. No academic decision is saved.",
        "An explicit per-student Save and Use confirmation is required.",
        "",
        ("ATTENTION NEEDED" if attention_only else "ALL AUTHORIZED STUDENTS")
        + f" — page {page}/{_page_count(rows)}",
    )
    if inventory.outside_requested_authorization_scope_count:
        write_lines(
            output,
            "Additional roster identities are outside authorization scope "
            "(identities hidden).",
        )
    if inventory.unresolved_global_exception_codes:
        write_lines(output, "Source/roster exceptions require separate review.")
    if not current:
        write_lines(output, "No students in this view.")
    for index, row in enumerate(current, start=1):
        write_lines(
            output,
            f"{index}. {_safe(row.display_label)}",
            f"   {len(row.attempts)} native attempts; {_status(row)}"
            + ("; attention needed" if row.needs_attention else ""),
        )
    write_lines(
        output,
        "",
        "A. All authorized students" if attention_only else "E. Attention needed",
        "N. Next page    P. Previous page    R. Refresh current source",
        "I. Review interrupted saves (class-wide journal)",
        "",
    )
    print_standard_navigation(output)
    return current


def _attempt_lines(row: StudentAttemptInventoryRow) -> tuple[str, ...]:
    lines: list[str] = []
    if not row.attempts:
        lines.append("No native attempt established. Never assume a zero score.")
    for attempt in row.attempts:
        selection = (
            "selected for current interpretation"
            if attempt.current_selected
            else "eligible; not currently selected"
            if attempt.operative_eligible
            else "historical/not operative"
        )
        lines.append(f"{_safe(attempt.attempt_label)} — {selection}")
        if attempt.point_result is not None:
            lines.append(
                "  Source-reported points: "
                f"{attempt.point_result[0]}/{attempt.point_result[1]}"
            )
        else:
            lines.append("  Source-reported points: unavailable")
        lines.append(
            "  Producer-reported origin: "
            + _safe(attempt.result_origin or "unavailable")
        )
        if attempt.scan_review_failure_reference:
            lines.append(
                "  Scan-review reference exists (not proof of correction cause)."
            )
    return tuple(lines)


def _show_student(
    output: TextIO,
    input_fn: InputFunction,
    clear_fn: ClearFunction,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    attempt_dependencies: GuidedAttemptDependencies,
    correction_handler: Callable[..., bool],
    reassessment_handler: Callable[..., bool],
    decision_history_handler: Callable[..., None] | None = None,
    recovery_handler: Callable[..., None] | None = None,
    session_context: TeacherSessionContext | None = None,
) -> bool:
    """Return True when canonical assessment must be reloaded; M/Q propagate."""
    while True:
        clear_fn()
        print_menu_header(output, "Review Student Attempts")
        write_lines(
            output,
            f"Assessment: {_safe(inventory.assessment_title or 'Selected assessment')}",
            f"Student: {_safe(row.display_label)}",
            _status(row),
            "#31: " + _safe(row.reassessment_status or "not resolved / not applicable"),
            "Relationship: not established from score, order or scan origin.",
            "",
            *_attempt_lines(row),
        )
        if row.attention:
            write_lines(
                output,
                "",
                "Attention: "
                + "; ".join(_safe(x.replace("_", " ")) for x in row.attention),
            )
        write_lines(
            output,
            "",
            "H. Source attempt history    T. Technical Details",
            "D. Canonical #30/#31 decision history (read only)",
            "I. Review interrupted saves (class-wide journal)",
            "R. Refresh assessment review",
            "C. Review teacher-verified correction (explicit single-attempt use)",
            "S. Review genuine reassessment (explicit #30 and #31)",
            "",
        )
        print_standard_navigation(output)
        choice = read_choice(input_fn)
        if choice == "" or parse_navigation_choice(choice) is NavigationChoice.BACK:
            return False
        if choice.casefold() == "r":
            return True
        if choice.casefold() == "c":
            return correction_handler(
                workspace_root,
                prepared,
                inventory,
                row,
                attempt_dependencies,
                input_fn,
                output,
                clear_fn,
            )
        if choice.casefold() == "s":
            return reassessment_handler(
                workspace_root,
                prepared,
                inventory,
                row,
                attempt_dependencies,
                input_fn,
                output,
                clear_fn,
            )
        if choice.casefold() == "d":
            if decision_history_handler is None:
                write_lines(output, "Decision history requires a bound assessment.")
                return True
            decision_history_handler(
                workspace_root,
                prepared,
                inventory,
                row,
                input_fn,
                output,
                clear_fn,
            )
            return True
        if choice.casefold() == "i":
            if recovery_handler is None or session_context is None:
                write_lines(output, "Recovery requires a bound class session.")
                return True
            recovery_handler(
                workspace_root,
                prepared,
                inventory,
                session_context,
                input_fn,
                output,
                clear_fn,
            )
            return True
        if choice.casefold() == "h":
            clear_fn()
            print_menu_header(output, "Source Attempt History (READ ONLY)")
            write_lines(
                output,
                f"Student: {_safe(row.display_label)}",
                "Original native observations are preserved even when inoperative.",
                "An attempt sequence is not a Core publication revision.",
                "",
                *_attempt_lines(row),
                "",
                "No history or current selection was changed.",
            )
            pause_for_user(input_fn)
            continue
        if choice.casefold() == "t":
            clear_fn()
            print_menu_header(output, "Technical Details (READ ONLY)")
            write_lines(
                output,
                f"Student identity: {ascii(row.student_id)}",
                f"Work: {ascii((inventory.work_module_id, inventory.work_id))}",
                f"Publication ID: {ascii(inventory.publication_id)}",
                f"Cache key: {ascii(inventory.cache_key)}",
                f"Snapshot digest: {ascii(inventory.snapshot_digest)}",
                f"#30 resolution: {ascii(row.selection_resolution_status)}",
                f"#30 decision revision: {row.selected_decision_revision!r}",
            )
            for attempt in row.attempts:
                write_lines(
                    output,
                    f"Native target: {ascii(attempt.attempt.target.target_id)}; "
                    f"sequence: {attempt.attempt.native.sequence!r}",
                    f"Item IDs: {ascii(attempt.item_ids)}",
                )
            write_lines(output, "", "Technical identifiers are not academic decisions.")
            pause_for_user(input_fn)
            continue
        write_lines(output, "Choose C, S, D, I, H, T, R, B, M, or Q.")
        pause_for_user(input_fn)


def _check_inventory(
    inventory: AssessmentAttemptInventory,
    prepared: GuidedProjectionResult,
    grade_item_id: str,
) -> None:
    """Reject even a test-injected projection of another authorization scope."""
    if not isinstance(inventory, AssessmentAttemptInventory):
        raise CorrectionsMenuError("Invalid authorized inventory result.")
    publication = prepared.authorized.current_context.publication
    snapshot = prepared.authorized.stored
    if (
        inventory.class_id != publication.work.class_id
        or inventory.work_module_id != publication.work.module_id
        or inventory.work_id != publication.work.work_id
        or inventory.grade_item_id != grade_item_id
        or inventory.publication_id != publication.publication_id
        or inventory.cache_key != snapshot.cache_key
        or inventory.snapshot_digest != snapshot.snapshot_digest
    ):
        raise CorrectionsMenuError(
            "Assessment inventory source/scope differs from review."
        )
    if len({row.student_id for row in inventory.students}) != len(inventory.students):
        raise CorrectionsMenuError("Duplicate authorized roster identity.")
    if (
        inventory.source_status != "current" or inventory.membership_state != "included"
    ) and any(
        row.selection_status is not None or row.reassessment_status is not None
        for row in inventory.students
    ):
        raise CorrectionsMenuError("Stale source was presented as a current selection.")


def run_assessment_corrections_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    class_label: str,
    assessment_title: str,
    session_context: TeacherSessionContext,
    dependencies: GuidedEligibilityDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    ports: CorrectionsMenuPorts | None = None,
    attempt_dependencies: GuidedAttemptDependencies | None = None,
) -> None:
    """Enter from exact authorized assessment; never ask for IDs or save a decision."""
    services = ports or CorrectionsMenuPorts()
    active_attempt_dependencies = attempt_dependencies or GuidedAttemptDependencies()
    try:
        publication = prepared.authorized.current_context.publication
        work = publication.work
        if (
            not isinstance(workspace_root, Path)
            or not workspace_root.is_absolute()
            or session_context.active_work != work
            or session_context.active_class_id != work.class_id
            or session_context.active_publication_id != publication.publication_id
        ):
            raise CorrectionsMenuError("Selected assessment context changed.")
        items = services.grade_items_loader(workspace_root, work, dependencies)
        if not isinstance(items, tuple) or any(
            not hasattr(item, "grade_item_id") for item in items
        ):
            raise CorrectionsMenuError("Current Grade Item choices unavailable.")
    except Exception:
        clear_fn()
        print_menu_header(output, "Corrections & Attempts — Review Unavailable")
        write_lines(
            output,
            "Current assessment, authorization, or Grade Item context "
            "could not be verified.",
            "Return to Evidence Review and reload the assessment.",
            "Nothing was saved or changed.",
        )
        pause_for_user(input_fn)
        return
    if not items:
        clear_fn()
        print_menu_header(output, "Corrections & Attempts — Setup Required")
        write_lines(
            output,
            "No current included Grade Item matches this assessment.",
            "Use Published Assessment Setup; this screen creates nothing.",
        )
        pause_for_user(input_fn)
        return
    grade_item = _choose_grade_item(
        items, session_context, input_fn=input_fn, output=output, clear_fn=clear_fn
    )
    if grade_item is None:
        return
    page = 1
    attention_only = True
    reload_needed = True
    inventory: AssessmentAttemptInventory | None = None
    while True:
        if reload_needed:
            try:
                if (
                    session_context.active_work != work
                    or session_context.active_publication_id
                    != publication.publication_id
                    or session_context.active_grade_item_id != grade_item.grade_item_id
                ):
                    raise CorrectionsMenuError("Selected assessment context changed.")
                loaded = services.inventory_loader(
                    workspace_root,
                    grade_item.grade_item_id,
                    prepared,
                    class_label,
                    assessment_title,
                )
                _check_inventory(loaded, prepared, grade_item.grade_item_id)
                inventory = loaded
            except Exception:
                clear_fn()
                print_menu_header(output, "Corrections & Attempts — Refresh Required")
                write_lines(
                    output,
                    "Current source, eligibility, or roster information "
                    "is unavailable.",
                    "Return to Evidence Review to reload authorization "
                    "and resolve prerequisites.",
                    "No attempt decision or receipt was created.",
                )
                pause_for_user(input_fn)
                return
            reload_needed = False
        assert inventory is not None
        rows = _queue_rows(inventory, attention_only=attention_only)
        page = min(page, _page_count(rows))
        clear_fn()
        window = _print_queue(
            output, inventory, attention_only=attention_only, page=page
        )
        choice = read_choice(input_fn)
        if choice == "" or parse_navigation_choice(choice) is NavigationChoice.BACK:
            return
        lower = choice.casefold()
        if lower in {"a", "e"}:
            attention_only = lower != "a"
            page = 1
            continue
        if lower == "r":
            reload_needed = True
            continue
        if lower == "i":
            services.recovery_handler(
                workspace_root,
                prepared,
                inventory,
                session_context,
                input_fn,
                output,
                clear_fn,
            )
            reload_needed = True
            continue
        if lower == "n":
            page = min(page + 1, _page_count(rows))
            continue
        if lower == "p":
            page = max(1, page - 1)
            continue
        if choice.isascii() and choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(window):
                row = window[index - 1]
                session_context.select_student(row.student_id)
                reload_needed = _show_student(
                    output,
                    input_fn,
                    clear_fn,
                    inventory,
                    row,
                    workspace_root=workspace_root,
                    prepared=prepared,
                    attempt_dependencies=active_attempt_dependencies,
                    correction_handler=services.correction_handler,
                    reassessment_handler=services.reassessment_handler,
                    decision_history_handler=services.decision_history_handler,
                    recovery_handler=services.recovery_handler,
                    session_context=session_context,
                )
                continue
        write_lines(output, "Choose a listed student, A/E, N, P, R, I, B, M, or Q.")
        pause_for_user(input_fn)


__all__ = (
    "CorrectionsMenuError",
    "CorrectionsMenuPorts",
    "run_assessment_corrections_menu",
)
