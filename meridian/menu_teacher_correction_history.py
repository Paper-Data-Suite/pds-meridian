"""#126-F3A: authorized, read-only #30/#31 history and bounded #122 entry.

A canonical historical pointer is not proof that its source remains operative.
This screen does not write decisions, resume #31, or infer new authorizations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    StudentAttemptInventoryRow,
)
from meridian.attempt_selection import AttemptProjectionReference
from meridian.attempt_selection_storage import (
    StoredAttemptSelectionDecision,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_decision,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_action_recovery import run_teacher_action_recovery_menu
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.reassessment_storage import (
    StoredReassessmentDecision,
    list_reassessment_decision_revisions,
    load_current_reassessment_decision,
    load_reassessment_decision_revision,
)
from meridian.teacher_session import TeacherSessionContext

MAX_HISTORY_PER_FAMILY = 128
HISTORY_PAGE_SIZE = 12


class CorrectionHistoryError(ValueError):
    """A history record, scope or canonical selector is not safely readable."""


@dataclass(frozen=True, slots=True)
class HistoryRow:
    kind: str
    revision: int
    sha256: str
    pointer_selected: bool
    source_is_reviewed_publication: bool | None
    description: str
    linked_attempt_revision: int | None = None


@dataclass(frozen=True, slots=True)
class CorrectionHistory:
    student_label: str
    attempt_rows: tuple[HistoryRow, ...]
    reassessment_rows: tuple[HistoryRow, ...]
    stored_attempt_pointer: int | None
    stored_reassessment_pointer: int | None


@dataclass(frozen=True, slots=True)
class CorrectionHistoryPorts:
    """Only existing canonical history loaders, never author or select ports."""

    list_attempts: Callable[..., tuple[int, ...]] = (
        list_attempt_selection_decision_revisions
    )
    read_attempt: Callable[..., StoredAttemptSelectionDecision] = (
        load_attempt_selection_decision_revision
    )
    current_attempt: Callable[..., StoredAttemptSelectionDecision | None] = (
        load_current_attempt_selection_decision
    )
    list_reassessments: Callable[..., tuple[int, ...]] = (
        list_reassessment_decision_revisions
    )
    read_reassessment: Callable[..., StoredReassessmentDecision] = (
        load_reassessment_decision_revision
    )
    current_reassessment: Callable[..., StoredReassessmentDecision | None] = (
        load_current_reassessment_decision
    )


def _safe(value: object, *, maximum: int = 130) -> str:
    raw = str(value)
    result = "".join(
        char if char.isprintable() and char not in {"\x1b", "\x7f"} else "?"
        for char in raw
    )
    return result[:maximum] + ("..." if len(result) > maximum else "")


def _scope(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
) -> ModuleWorkRef:
    if not isinstance(root, Path) or not root.is_absolute():
        raise CorrectionHistoryError("Absolute workspace required.")
    if not isinstance(prepared, GuidedProjectionResult):
        raise CorrectionHistoryError("Authorized assessment required.")
    if not isinstance(inventory, AssessmentAttemptInventory) or not isinstance(
        row, StudentAttemptInventoryRow
    ):
        raise CorrectionHistoryError("Typed assessment and student required.")
    if (
        sum(item.student_id == row.student_id for item in inventory.students) != 1
        or row not in inventory.students
    ):
        raise CorrectionHistoryError("Student is outside this assessment view.")
    try:
        authority = prepared.authorized
        publication = authority.current_context.publication
        stored = authority.stored
        reusable = authority.assessment.reusable_for_current_use
    except AttributeError as error:
        raise CorrectionHistoryError("Current authorization is unavailable.") from error
    work = publication.work
    if (
        reusable is not True
        or inventory.source_status != "current"
        or inventory.membership_state != "included"
        or work.class_id != inventory.class_id
        or work.module_id != inventory.work_module_id
        or work.work_id != inventory.work_id
        or publication.publication_id != inventory.publication_id
        or stored.cache_key != inventory.cache_key
        or stored.snapshot_digest != inventory.snapshot_digest
    ):
        raise CorrectionHistoryError(
            "Source, Grade Item or authorization changed since assessment review."
        )
    return work


def _checked_revisions(value: object) -> tuple[int, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) > MAX_HISTORY_PER_FAMILY
        or any(type(item) is not int for item in value)
        or value != tuple(range(1, len(value) + 1))
    ):
        raise CorrectionHistoryError("Decision history is incomplete or over limit.")
    return cast(tuple[int, ...], value)


def load_correction_decision_history(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    *,
    ports: CorrectionHistoryPorts | None = None,
) -> CorrectionHistory:
    """Verify full immutable revisions/current pointers for one authorized student.

    A stored current pointer is a historical storage fact, never an operative
    eligibility, source or reassessment certification. Source history is retained.
    """
    work = _scope(root, prepared, inventory, row)
    readers = ports or CorrectionHistoryPorts()
    args = (root, inventory.class_id, inventory.grade_item_id, work, row.student_id)
    try:
        attempt_revs = _checked_revisions(readers.list_attempts(*args))
        reassessment_revs = _checked_revisions(readers.list_reassessments(*args))
        current_attempt = readers.current_attempt(*args)
        current_reassessment = readers.current_reassessment(*args)
        attempt_current = (
            None
            if current_attempt is None
            else current_attempt.decision.decision_revision
        )
        reassessment_current = (
            None
            if current_reassessment is None
            else current_reassessment.decision.decision_revision
        )
        if row.selection_status in {"selected", "selected_none"} and (
            attempt_current != row.selected_decision_revision
        ):
            raise CorrectionHistoryError(
                "Current #30 pointer changed since the assessment review."
            )
        if row.selection_status == "no_decision" and attempt_current is not None:
            raise CorrectionHistoryError(
                "Current #30 pointer was created since the assessment review."
            )
        if row.reassessment_status == "resolved" and reassessment_current is None:
            raise CorrectionHistoryError(
                "Current #31 pointer changed since the assessment review."
            )
        if attempt_current is not None and attempt_current not in attempt_revs:
            raise CorrectionHistoryError("#30 pointer is outside verified history.")
        if (
            reassessment_current is not None
            and reassessment_current not in reassessment_revs
        ):
            raise CorrectionHistoryError("#31 pointer is outside verified history.")
        snapshot = AttemptProjectionReference(
            work=work,
            publication_id=inventory.publication_id,
            cache_key=inventory.cache_key,
            snapshot_digest=inventory.snapshot_digest,
        )
        attempt_rows: list[HistoryRow] = []
        attempt_digests: dict[int, str] = {}
        for revision in attempt_revs:
            saved = readers.read_attempt(*args, revision)
            decision = saved.decision
            if (
                decision.class_id != inventory.class_id
                or decision.grade_item_id != inventory.grade_item_id
                or decision.work != work
                or decision.student_id != row.student_id
                or decision.decision_revision != revision
            ):
                raise CorrectionHistoryError(
                    "#30 history identity does not match scope."
                )
            attempt_digests[revision] = saved.decision_sha256
            attempt_rows.append(
                HistoryRow(
                    kind="attempt",
                    revision=revision,
                    sha256=saved.decision_sha256,
                    pointer_selected=attempt_current == revision,
                    source_is_reviewed_publication=decision.source_snapshot == snapshot,
                    description=(
                        f"{len(decision.selected_attempts)} explicitly selected"
                    ),
                )
            )
            if (
                current_attempt is not None
                and attempt_current == revision
                and (saved.decision_sha256 != current_attempt.decision_sha256)
            ):
                raise CorrectionHistoryError("#30 current digest differs from history.")
        reassessment_rows: list[HistoryRow] = []
        for revision in reassessment_revs:
            saved_rel = readers.read_reassessment(*args, revision)
            decision_rel = saved_rel.decision
            if (
                decision_rel.class_id != inventory.class_id
                or decision_rel.grade_item_id != inventory.grade_item_id
                or decision_rel.work != work
                or decision_rel.student_id != row.student_id
                or decision_rel.decision_revision != revision
            ):
                raise CorrectionHistoryError(
                    "#31 history identity does not match scope."
                )
            upstream = decision_rel.attempt_selection
            relation_matches = (
                attempt_digests.get(upstream.decision_revision)
                == upstream.decision_sha256
            )
            if not relation_matches:
                raise CorrectionHistoryError(
                    "#31 history references missing or different #30 identity."
                )
            reassessment_rows.append(
                HistoryRow(
                    kind="reassessment",
                    revision=revision,
                    sha256=saved_rel.decision_sha256,
                    pointer_selected=reassessment_current == revision,
                    source_is_reviewed_publication=None,
                    description=(
                        f"{decision_rel.mode}; "
                        f"{len(decision_rel.contributing_attempts)} contributors"
                    ),
                    linked_attempt_revision=upstream.decision_revision,
                )
            )
            if (
                current_reassessment is not None
                and reassessment_current == revision
                and saved_rel.decision_sha256 != current_reassessment.decision_sha256
            ):
                raise CorrectionHistoryError("#31 current digest differs from history.")
    except CorrectionHistoryError:
        raise
    except Exception as error:
        raise CorrectionHistoryError(
            "Canonical decision history could not be verified safely."
        ) from error
    return CorrectionHistory(
        student_label=row.display_label,
        attempt_rows=tuple(attempt_rows),
        reassessment_rows=tuple(reassessment_rows),
        stored_attempt_pointer=attempt_current,
        stored_reassessment_pointer=reassessment_current,
    )


def _present(
    output: TextIO,
    history: CorrectionHistory,
    *,
    page: int,
    technical: bool,
) -> int:
    all_rows = history.attempt_rows + history.reassessment_rows
    count = max(1, (len(all_rows) + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    if page >= count:
        page = count - 1
    print_menu_header(output, "Student Decision History (READ ONLY)")
    write_lines(
        output,
        f"Student: {_safe(history.student_label)}",
        f"Verified immutable records: {len(all_rows)}",
        f"Stored #30 pointer: {history.stored_attempt_pointer or 'none'}",
        f"Stored #31 pointer: {history.stored_reassessment_pointer or 'none'}",
        "A stored pointer is NOT an operative academic-use certification.",
        "Historical source/selection must not be treated as current evidence.",
        "",
        f"Decision records — page {page + 1}/{count}",
    )
    if not all_rows:
        write_lines(output, "No canonical #30/#31 decisions have been stored.")
    for record in all_rows[page * HISTORY_PAGE_SIZE : (page + 1) * HISTORY_PAGE_SIZE]:
        label = (
            "#30 Attempt decision" if record.kind == "attempt" else "#31 Reassessment"
        )
        marker = "stored pointer" if record.pointer_selected else "historical"
        write_lines(
            output,
            f"{label}, revision {record.revision}: {marker}",
            f"  {_safe(record.description)}",
        )
        if record.source_is_reviewed_publication is False:
            write_lines(output, "  Different historical source snapshot.")
        if record.linked_attempt_revision is not None:
            write_lines(
                output,
                f"  References exact #30 revision {record.linked_attempt_revision}.",
            )
        if technical:
            write_lines(output, f"  Exact digest: {record.sha256}")
    write_lines(
        output,
        "",
        "N. Next page    P. Previous page    T. Toggle Technical Details",
    )
    print_standard_navigation(output)
    return page


def run_teacher_corrections_history_menu(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: CorrectionHistoryPorts | None = None,
) -> None:
    """Read one authorized student's immutable histories, with bounded paging."""
    page = 0
    technical = False
    try:
        current = load_correction_decision_history(
            root, prepared, inventory, row, ports=ports
        )
    except CorrectionHistoryError:
        clear_fn()
        print_menu_header(output, "Student History — Refresh Required")
        write_lines(
            output,
            "Current authorization, pointer or historical integrity could "
            "not be verified.",
            "Return to the assessment and refresh its source before retrying.",
            "Nothing was selected, written, or recovered.",
        )
        pause_for_user(input_fn)
        return
    # Pagination and Technical Details use the SAME validated inspection snapshot.
    # Returning to the assessment forces another full authorized projection.
    while True:
        clear_fn()
        page = _present(output, current, page=page, technical=technical)
        choice = read_choice(input_fn)
        if choice == "" or parse_navigation_choice(choice) is NavigationChoice.BACK:
            return
        lower = choice.casefold()
        if lower == "n":
            page += 1
        elif lower == "p":
            page = max(0, page - 1)
        elif lower == "t":
            technical = not technical
        else:
            write_lines(output, "Choose T, N, P, B, M, or Q.")


def run_bound_teacher_recovery_menu(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    session_context: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Open existing class #122 inbox, never synthesize a #31 resume control."""
    try:
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or not isinstance(prepared, GuidedProjectionResult)
            or not isinstance(inventory, AssessmentAttemptInventory)
        ):
            raise CorrectionHistoryError("Invalid bound class recovery context.")
        publication = prepared.authorized.current_context.publication
        if (
            session_context.active_class_id != inventory.class_id
            or session_context.active_work != publication.work
            or session_context.active_publication_id != inventory.publication_id
            or session_context.active_grade_item_id != inventory.grade_item_id
        ):
            raise CorrectionHistoryError("Class recovery context changed.")
    except (CorrectionHistoryError, AttributeError):
        clear_fn()
        print_menu_header(output, "Interrupted Saves — Refresh Required")
        write_lines(
            output,
            "Return to the assessment and reload the bound class context.",
            "No action was opened or changed.",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Interrupted Saves — Class Journal")
    write_lines(
        output,
        "This opens the EXISTING class-wide #122 receipt review.",
        "A receipt is NOT proof that an academic decision is current.",
        "#30 original-action resume requires separate canonical verification.",
        "A #31 recovery/continuation choice is NOT yet available in this menu.",
        "The journal may contain actions for other students in this class.",
        "",
        "1. Open class receipt review",
        "2. Cancel",
    )
    print_standard_navigation(output)
    choice = read_choice(input_fn)
    if choice != "1":
        parse_navigation_choice(choice)
        return
    run_teacher_action_recovery_menu(
        session_context=session_context,
        workspace_resolver=lambda: root,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


__all__ = (
    "CorrectionHistory",
    "CorrectionHistoryError",
    "CorrectionHistoryPorts",
    "HistoryRow",
    "load_correction_decision_history",
    "run_teacher_corrections_history_menu",
    "run_bound_teacher_recovery_menu",
)
