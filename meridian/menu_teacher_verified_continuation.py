"""#126-F3B1: fresh, canonical #30/#31 gate before Standards continuation.

History and receipts are observations, not academic authority. Only a freshly
re-authorized projection and independently resolved operative selections may
enter the existing Standards menu. This module never writes academic records,
selects a policy, or resumes a #31 action.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    StudentAttemptInventoryRow,
    project_assessment_attempt_inventory,
)
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityReview,
    project_assessment_eligibility_review,
)
from meridian.diagnostics import default_diagnostics_dependencies
from meridian.guided_eligibility import GuidedEligibilityDependencies
from meridian.guided_projection import (
    GuidedProjectionResult,
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
)
from meridian.guided_standards import GuidedStandardsDependencies
from meridian.menu_teacher_correction_history import (
    CorrectionHistory,
    load_correction_decision_history,
)
from meridian.menu_teacher_standards import run_guided_standard_menu
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_evidence_review import (
    TeacherEvidenceReview,
    TeacherEvidenceReviewItem,
    project_teacher_evidence_review,
)
from meridian.teacher_session import TeacherSessionContext

MAX_STANDARDS_EVIDENCE_CHOICES = 5_000
STANDARD_EVIDENCE_PAGE_SIZE = 10


class VerifiedContinuationError(ValueError):
    """Current academic use cannot be proved from independently fresh authority."""


def _fresh_projection(
    root: Path, work: ModuleWorkRef, publication_id: str
) -> GuidedProjectionResult:
    diagnostics = default_diagnostics_dependencies()
    dependencies = default_guided_projection_dependencies(diagnostics=diagnostics)
    return prepare_guided_evidence_projection(
        root, work, publication_id, dependencies=dependencies
    )


def _inventory(
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


def _eligibility(
    root: Path, grade_item_id: str, prepared: GuidedProjectionResult
) -> AssessmentEligibilityReview:
    return project_assessment_eligibility_review(
        root, grade_item_id=grade_item_id, prepared=prepared
    )


def _standards(
    root: Path,
    prepared: GuidedProjectionResult,
    evidence: TeacherEvidenceReviewItem,
    student_label: str,
    session: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Reuse the existing #110/#122 author/select UX; no setup side effect."""
    run_guided_standard_menu(
        workspace_root=root,
        prepared=prepared,
        evidence=evidence,
        subject_label=student_label,
        session_context=session,
        dependencies=GuidedStandardsDependencies(),
        eligibility_dependencies=GuidedEligibilityDependencies(),
        grade_item_bridge_dependencies=None,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )


@dataclass(frozen=True, slots=True)
class VerifiedContinuationPorts:
    """Read-only production services and one existing Standards-menu handoff."""

    fresh_projection: Callable[..., GuidedProjectionResult] = _fresh_projection
    inventory: Callable[..., AssessmentAttemptInventory] = _inventory
    history: Callable[..., CorrectionHistory] = load_correction_decision_history
    eligibility: Callable[..., AssessmentEligibilityReview] = _eligibility
    evidence: Callable[..., TeacherEvidenceReview] = project_teacher_evidence_review
    standards: Callable[..., None] = _standards


@dataclass(frozen=True, slots=True)
class VerifiedStudentCurrentUse:
    """An ephemeral, strictly exact read-only status; never a portable grant."""

    prepared: GuidedProjectionResult
    inventory: AssessmentAttemptInventory
    row: StudentAttemptInventoryRow
    history: CorrectionHistory
    included_item_ids: frozenset[str]
    selected_attempt_count: int


def _safe(value: object, maximum: int = 140) -> str:
    raw = str(value)
    readable = "".join(
        ch if ch.isprintable() and ch not in {"\x1b", "\x7f"} else "?" for ch in raw
    )
    return readable[:maximum] + ("..." if len(readable) > maximum else "")


def verify_student_current_use(
    root: Path,
    original_prepared: GuidedProjectionResult,
    original_inventory: AssessmentAttemptInventory,
    original_row: StudentAttemptInventoryRow,
    *,
    ports: VerifiedContinuationPorts | None = None,
) -> VerifiedStudentCurrentUse:
    """Reload authority and read both canonical domains without any mutation.

    No stale original projection, mere #122 receipt, or older revision can open
    an operative Standards flow. Historical excluded attempts may remain visible
    but their source items are NEVER eligible choices here.
    """
    p = ports or VerifiedContinuationPorts()
    if not isinstance(root, Path) or not root.is_absolute():
        raise VerifiedContinuationError("Absolute workspace root required.")
    if not isinstance(original_inventory, AssessmentAttemptInventory) or not isinstance(
        original_row, StudentAttemptInventoryRow
    ):
        raise VerifiedContinuationError("Exact original roster review is required.")
    if (
        sum(
            x.student_id == original_row.student_id for x in original_inventory.students
        )
        != 1
        or original_row not in original_inventory.students
    ):
        raise VerifiedContinuationError("Student not in original authorized review.")
    try:
        first_authority = original_prepared.authorized
        work = first_authority.current_context.publication.work
        publication_id = first_authority.current_context.publication.publication_id
        if (
            work.class_id != original_inventory.class_id
            or work.module_id != original_inventory.work_module_id
            or work.work_id != original_inventory.work_id
            or publication_id != original_inventory.publication_id
        ):
            raise VerifiedContinuationError("Original work/publication scope differs.")
        fresh = p.fresh_projection(root, work, publication_id)
        current_authority = fresh.authorized
        published = current_authority.current_context.publication
        if (
            current_authority.assessment.reusable_for_current_use is not True
            or published.work != work
            or published.publication_id != publication_id
        ):
            raise VerifiedContinuationError(
                "Fresh publication is not authorized/current."
            )
        inventory = p.inventory(
            root,
            original_inventory.grade_item_id,
            fresh,
            original_inventory.class_label or "",
            original_inventory.assessment_title or "",
        )
        if (
            not isinstance(inventory, AssessmentAttemptInventory)
            or inventory.source_status != "current"
            or inventory.membership_state != "included"
            or inventory.class_id != work.class_id
            or inventory.grade_item_id != original_inventory.grade_item_id
            or inventory.work_module_id != work.module_id
            or inventory.work_id != work.work_id
            or inventory.publication_id != publication_id
            or inventory.cache_key != current_authority.stored.cache_key
            or inventory.snapshot_digest != current_authority.stored.snapshot_digest
        ):
            raise VerifiedContinuationError("Fresh canonical inventory source differs.")
        matched = tuple(
            row
            for row in inventory.students
            if row.student_id == original_row.student_id
        )
        if len(matched) != 1:
            raise VerifiedContinuationError("Student no longer uniquely authorized.")
        row = matched[0]
        if (
            row.selection_status != "selected"
            or row.selection_resolution_status != "selected"
            or row.selected_decision_revision is None
        ):
            raise VerifiedContinuationError("No operative exact #30 selection.")
        chosen = tuple(x for x in row.attempts if x.current_selected)
        if not chosen or any(not x.operative_eligible for x in chosen):
            raise VerifiedContinuationError(
                "Selected attempts are not eligible/current."
            )
        history = p.history(root, fresh, inventory, row)
        if not isinstance(history, CorrectionHistory):
            raise VerifiedContinuationError("Canonical decision history unavailable.")
        if history.stored_attempt_pointer != row.selected_decision_revision:
            raise VerifiedContinuationError("#30 current pointer differs.")
        selected_history = tuple(h for h in history.attempt_rows if h.pointer_selected)
        if (
            len(selected_history) != 1
            or selected_history[0].revision != row.selected_decision_revision
            or selected_history[0].source_is_reviewed_publication is not True
        ):
            raise VerifiedContinuationError("#30 historical source/current mismatch.")
        if len(chosen) > 1:
            current_relations = tuple(
                h for h in history.reassessment_rows if h.pointer_selected
            )
            if (
                row.reassessment_status != "resolved"
                or history.stored_reassessment_pointer is None
                or len(current_relations) != 1
                or current_relations[0].linked_attempt_revision
                != row.selected_decision_revision
            ):
                raise VerifiedContinuationError(
                    "Exact #31 relationship is unresolved or does not match #30."
                )
        elif row.reassessment_status is not None:
            raise VerifiedContinuationError(
                "Unexpected #31 relationship for one selected attempt."
            )
        eligibility = p.eligibility(root, inventory.grade_item_id, fresh)
        if (
            not isinstance(eligibility, AssessmentEligibilityReview)
            or eligibility.work != work
            or eligibility.publication_id != publication_id
            or eligibility.grade_item_id != inventory.grade_item_id
            or eligibility.cache_key != inventory.cache_key
            or eligibility.snapshot_digest != inventory.snapshot_digest
            or eligibility.source_status != "current"
            or eligibility.membership_state != "included"
        ):
            raise VerifiedContinuationError("Current operative eligibility differs.")
        roster = tuple(
            student
            for student in eligibility.students
            if student.student_id == row.student_id
            and student.within_requested_authorization
        )
        if len(roster) != 1:
            raise VerifiedContinuationError("Student is outside eligibility scope.")
        selected_item_ids = {
            item_id for attempt in chosen for item_id in attempt.item_ids
        }
        included = frozenset(
            item.source.item_id
            for item in roster[0].items
            if item.operative_included and item.source.item_id in selected_item_ids
        )
        if not included:
            raise VerifiedContinuationError("No operative included selected evidence.")
        if any(not set(attempt.item_ids).intersection(included) for attempt in chosen):
            raise VerifiedContinuationError(
                "A selected attempt lacks its own operative included evidence."
            )
    except VerifiedContinuationError:
        raise
    except Exception as error:
        raise VerifiedContinuationError(
            "Fresh authorization or canonical status could not be verified."
        ) from error
    return VerifiedStudentCurrentUse(
        prepared=fresh,
        inventory=inventory,
        row=row,
        history=history,
        included_item_ids=included,
        selected_attempt_count=len(chosen),
    )


def _review_evidence(
    root: Path,
    state: VerifiedStudentCurrentUse,
    ports: VerifiedContinuationPorts,
) -> tuple[TeacherEvidenceReviewItem, ...]:
    review = ports.evidence(root, state.prepared)
    if (
        not isinstance(review, TeacherEvidenceReview)
        or review.work != state.prepared.authorized.current_context.publication.work
        or review.publication_id != state.inventory.publication_id
    ):
        raise VerifiedContinuationError("Evidence preview differs from fresh source.")
    found = tuple(
        person
        for person in review.students
        if person.student_id == state.row.student_id
    )
    if len(found) != 1:
        raise VerifiedContinuationError("Evidence student no longer unique.")
    rows = tuple(
        item
        for item in found[0].items
        if item.item_id in state.included_item_ids
        and item.student_id == state.row.student_id
    )
    if (
        not rows
        or len(rows) > MAX_STANDARDS_EVIDENCE_CHOICES
        or len({item.item_id for item in rows}) != len(rows)
    ):
        raise VerifiedContinuationError("No unique included selected evidence choices.")
    return rows


def run_verified_standards_continuation(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    session_context: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: VerifiedContinuationPorts | None = None,
) -> bool:
    """Teacher chooses exact included evidence, then existing Standards UX runs.

    Returns True to force assessment refresh. A selection here is a navigation
    choice only, never a new academic decision or automatic Standards link.
    """
    p = ports or VerifiedContinuationPorts()
    try:
        if (
            session_context.active_class_id != inventory.class_id
            or session_context.active_grade_item_id != inventory.grade_item_id
            or session_context.active_student_id != row.student_id
            or session_context.active_publication_id != inventory.publication_id
        ):
            raise VerifiedContinuationError("Teacher session context changed.")
        state = verify_student_current_use(root, prepared, inventory, row, ports=p)
        choices = _review_evidence(root, state, p)
    except VerifiedContinuationError:
        clear_fn()
        print_menu_header(output, "Standards Continuation — Refresh Required")
        write_lines(
            output,
            "Current source, authorization, eligibility, #30 or #31 is not verified.",
            "Return to the assessment and review current decisions or recovery.",
            "No Standard, Grade, producer or attempt record was changed here.",
        )
        pause_for_user(input_fn)
        return True
    page = 0
    while True:
        start = page * STANDARD_EVIDENCE_PAGE_SIZE
        visible = choices[start : start + STANDARD_EVIDENCE_PAGE_SIZE]
        clear_fn()
        print_menu_header(output, "Continue to Standards Review")
        write_lines(
            output,
            f"Student: {_safe(state.row.display_label)}",
            f"Operative attempts verified: {state.selected_attempt_count}",
            f"Included evidence choices: {len(choices)}",
            "Only source items from independently verified selected attempts appear.",
            "Select evidence to open EXISTING Standards review; nothing is graded",
            "or associated by choosing a row here.",
            "",
            f"Showing {start + 1}-{start + len(visible)} of {len(choices)}",
        )
        for i, item in enumerate(visible, 1):
            write_lines(
                output,
                f"{i}. {_safe(item.evidence_label)} — {_safe(item.value_label)}"
                + ("; Standards declared" if item.standard_ids else ""),
            )
        write_lines(output, "", "N. Next page    P. Previous page")
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        if raw == "" or parse_navigation_choice(raw) is NavigationChoice.BACK:
            return True
        lower = raw.casefold()
        if lower == "n" and start + STANDARD_EVIDENCE_PAGE_SIZE < len(choices):
            page += 1
            continue
        if lower == "p":
            page = max(0, page - 1)
            continue
        if raw.isascii() and raw.isdigit() and 1 <= int(raw) <= len(visible):
            chosen = visible[int(raw) - 1]
            # The existing menu has its own authorization and write validation.
            # Do not invent an eligibility, Standard, or proficiency decision.
            p.standards(
                root,
                state.prepared,
                chosen,
                state.row.display_label,
                session_context,
                input_fn,
                output,
                clear_fn,
            )
            return True
        write_lines(output, "Choose a listed source item, N, P, B, M, or Q.")
        pause_for_user(input_fn)


def run_read_only_reassessment_recovery_check(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    session_context: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: VerifiedContinuationPorts | None = None,
) -> bool:
    """Describe exact current/historical #31, but never infer replay authority."""
    p = ports or VerifiedContinuationPorts()
    try:
        if (
            session_context.active_class_id != inventory.class_id
            or session_context.active_grade_item_id != inventory.grade_item_id
            or session_context.active_student_id != row.student_id
            or session_context.active_publication_id != inventory.publication_id
        ):
            raise VerifiedContinuationError("Teacher session context changed.")
        fresh = p.fresh_projection(
            root,
            prepared.authorized.current_context.publication.work,
            inventory.publication_id,
        )
        updated = p.inventory(
            root,
            inventory.grade_item_id,
            fresh,
            inventory.class_label or "",
            inventory.assessment_title or "",
        )
        if (
            not isinstance(updated, AssessmentAttemptInventory)
            or updated.source_status != "current"
            or updated.membership_state != "included"
            or updated.class_id != inventory.class_id
            or updated.grade_item_id != inventory.grade_item_id
            or updated.publication_id != inventory.publication_id
            or updated.cache_key != fresh.authorized.stored.cache_key
            or updated.snapshot_digest != fresh.authorized.stored.snapshot_digest
            or fresh.authorized.assessment.reusable_for_current_use is not True
        ):
            raise VerifiedContinuationError("Current reassessment source unavailable.")
        students = tuple(x for x in updated.students if x.student_id == row.student_id)
        if len(students) != 1:
            raise VerifiedContinuationError("Student is not currently authorized.")
        current = students[0]
        history = p.history(root, fresh, updated, current)
        if not isinstance(history, CorrectionHistory):
            raise VerifiedContinuationError("Canonical history could not be verified.")
        selected = tuple(x for x in current.attempts if x.current_selected)
        linked = tuple(
            x
            for x in history.reassessment_rows
            if x.linked_attempt_revision == current.selected_decision_revision
        )
    except Exception:
        clear_fn()
        print_menu_header(output, "Reassessment Recovery — Unverifiable")
        write_lines(
            output,
            "Current source, #30/#31 decisions or history could not be verified.",
            "Do not retry Save or replay any receipt.",
            "No action was changed or selected.",
        )
        pause_for_user(input_fn)
        return True
    clear_fn()
    print_menu_header(output, "Reassessment Recovery — Canonical Inspection")
    write_lines(
        output,
        f"Student: {_safe(current.display_label)}",
        f"#30: {_safe(current.selection_status or 'unavailable')}",
        f"#31: {_safe(current.reassessment_status or 'not applicable')}",
        f"Historical #31 revisions: {len(history.reassessment_rows)}",
        "",
    )
    if (
        len(selected) > 1
        and current.selection_status == "selected"
        and current.reassessment_status == "resolved"
        and history.stored_reassessment_pointer is not None
        and any(x.pointer_selected for x in linked)
    ):
        write_lines(output, "Both domains report current; revalidate before Standards.")
    elif (
        len(selected) > 1
        and current.selection_status == "selected"
        and linked
        and not any(x.pointer_selected for x in linked)
    ):
        write_lines(
            output,
            "A historical #31 revision links to the current #30 revision,",
            "but is NOT verified as current. Original receipt and CAS are",
            "required for an exact restart; history alone grants nothing.",
        )
    else:
        write_lines(
            output,
            "No exact operative #30/#31 pair was established by this inspection.",
            "Do not infer a fresh write or retry from journal absence.",
        )
    write_lines(
        output,
        "",
        "This is READ ONLY; no original-receipt restart is performed.",
        "I. Review Interrupted Saves opens the class-wide #122 journal.",
        "Return to the assessment to refresh current authorization.",
    )
    pause_for_user(input_fn)
    return True


__all__ = (
    "VerifiedContinuationError",
    "VerifiedContinuationPorts",
    "VerifiedStudentCurrentUse",
    "run_read_only_reassessment_recovery_check",
    "run_verified_standards_continuation",
    "verify_student_current_use",
)
