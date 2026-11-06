"""#125-F1: class/work/Grade Item bound, one-confirmation batch eligibility menu.

An inbox review is a discovery surface, not an authorization grant. Every
academic action uses a newly checked exact plan and the existing #122 bridge.
No generic confirmation, implicit zero, attempt selection, or Grade write.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Literal, TextIO, cast

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.assessment_eligibility_execution import render_batch_execution_outcome
from meridian.assessment_eligibility_plan import (
    BatchEligibilityReviewPlan,
    BatchEligibilitySelection,
    BatchItemException,
    BatchStudentException,
    DispositionOrDefer,
    build_batch_eligibility_plan,
    capture_batch_pointer_witnesses,
    render_batch_eligibility_plan,
)
from meridian.assessment_eligibility_progress import execute_batch_with_sealed_progress
from meridian.assessment_eligibility_recovery import (
    reconcile_sealed_eligibility_batch,
    render_batch_recovery_report,
    resume_sealed_eligibility_batch,
)
from meridian.assessment_eligibility_review import (
    AssessmentEligibilityReview,
    project_assessment_eligibility_review,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    discover_guided_eligibility_grade_items,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_eligibility import (
    _choose_disposition,
    _choose_grade_item,
    _choose_policy,
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
from meridian.teacher_action_guided import _actor_now, resolve_menu_actor
from meridian.teacher_action_restart_eligibility import load_fresh_restart_authorization
from meridian.teacher_session import TeacherSessionContext

_PAGE = 20
_MANUAL_REASON = ("eligibility.manual",)


def _back(raw: str) -> bool:
    """B is local back; Core's M/Q exceptions propagate to enclosing menu."""
    return not raw or parse_navigation_choice(raw) is NavigationChoice.BACK


def _enumerate_candidates(
    review: AssessmentEligibilityReview,
) -> tuple[tuple[str, str, str], ...]:
    """Exact candidate rows only; never include unknown/shared evidence."""
    return tuple(
        (item.source.item_id, student.display_label, item.evidence_label)
        for student in review.students
        if student.within_requested_authorization
        for item in student.items
        if item.candidate_for_explicit_review
    )


def _choose_source_ids(
    review: AssessmentEligibilityReview,
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[str, ...] | None:
    """Opt-in to explicit bounded IDs; no silent select-all on Enter."""
    candidates = _enumerate_candidates(review)
    if not candidates:
        clear_fn()
        print_menu_header(output, "Batch Eligibility — No Safe Candidates")
        write_lines(
            output,
            "There are no unselected, exception-free candidate items.",
            "An existing decision requires an individual reviewed replacement.",
            "No missing-result zero or lifecycle exclusion was inferred.",
        )
        pause_for_user(input_fn)
        return None
    while True:
        clear_fn()
        print_menu_header(output, "Choose Exact Batch Scope")
        write_lines(
            output,
            f"Safe no-decision evidence items: {len(candidates)}",
            f"Core roster students: {len(review.students)}",
            f"Observed exceptions: {review.exception_count}",
            "",
            "A. Explicitly select every safe candidate",
            "S. Select the safe items of specific students",
            "I. Select individual evidence items by numbered pages",
            "V. Review roster and exception counts",
            "",
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn).strip()
        if _back(raw):
            return None
        if raw.casefold() == "a":
            return tuple(item_id for item_id, _, _ in candidates)
        if raw.casefold() == "v":
            write_lines(
                output,
                f"No result (not zero): {review.no_result_student_count}",
                f"Outside authorization: {review.outside_authorization_scope_count}",
                f"Unmatched items: {len(review.unmatched_items)}",
                f"Shared items: {len(review.shared_items)}",
                "Ineligible/ambiguous items cannot be selected implicitly.",
            )
            pause_for_user(input_fn)
            continue
        if raw.casefold() == "s":
            students = tuple(
                s
                for s in review.students
                if any(item.candidate_for_explicit_review for item in s.items)
                and s.within_requested_authorization
            )
            clear_fn()
            print_menu_header(output, "Select Students")
            for number, student in enumerate(students, 1):
                count = sum(
                    item.candidate_for_explicit_review for item in student.items
                )
                print(
                    f"{number}. {student.display_label} ({count} safe items)",
                    file=output,
                )
            write_lines(
                output,
                "",
                "Enter comma-separated student numbers (e.g., 1,3,6).",
                "B. Back",
            )
            selected = _numbers(read_choice(input_fn), len(students), allow_many=True)
            if selected is None:
                continue
            wanted = {students[i - 1].student_id for i in selected}
            exact = tuple(
                item.source.item_id
                for student in students
                if student.student_id in wanted
                for item in student.items
                if item.candidate_for_explicit_review
            )
            if exact:
                return exact
            write_lines(output, "No safe evidence items were selected.")
            pause_for_user(input_fn)
            continue
        if raw.casefold() == "i":
            selected = _choose_paged_items(
                candidates, input_fn=input_fn, output=output, clear_fn=clear_fn
            )
            if selected:
                return selected
            continue
        write_lines(output, "Choose A, S, I, V, B, M, or Q.")
        pause_for_user(input_fn)


def _numbers(raw: str, maximum: int, *, allow_many: bool) -> tuple[int, ...] | None:
    """Strict menu-local integer parsing; never interpret B as an item index."""
    if _back(raw.strip()):
        return None
    parts = raw.strip().split(",") if allow_many else [raw.strip()]
    if not parts or any(
        not p.strip().isascii() or not p.strip().isdigit() for p in parts
    ):
        return None
    values = tuple(int(p.strip()) for p in parts)
    if (
        not values
        or any(n < 1 or n > maximum for n in values)
        or len(set(values)) != len(values)
    ):
        return None
    return values


def _choose_paged_items(
    candidates: tuple[tuple[str, str, str], ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[str, ...] | None:
    page = 0
    selected: set[int] = set()
    while True:
        start = page * _PAGE
        end = min(len(candidates), start + _PAGE)
        clear_fn()
        print_menu_header(output, "Select Individual Evidence")
        write_lines(output, f"Page {page + 1}/{(len(candidates) - 1) // _PAGE + 1}")
        for number in range(start, end):
            _, student, label = candidates[number]
            flag = " [selected]" if number in selected else ""
            print(f"{number + 1}. {student} — {label}{flag}", file=output)
        write_lines(
            output,
            "",
            "Enter item numbers separated by commas to toggle selection.",
            "N. Next  P. Previous  D. Done  B. Cancel selection",
        )
        raw = read_choice(input_fn).strip()
        if _back(raw):
            return None
        if raw.casefold() == "n" and end < len(candidates):
            page += 1
            continue
        if raw.casefold() == "p" and page:
            page -= 1
            continue
        if raw.casefold() == "d":
            return (
                tuple(candidates[i][0] for i in sorted(selected)) if selected else None
            )
        values = _numbers(raw, len(candidates), allow_many=True)
        if values is not None:
            for n in values:
                index = n - 1
                if index in selected:
                    selected.remove(index)
                else:
                    selected.add(index)
            continue
        write_lines(output, "Use listed item numbers, N, P, D, or B.")
        pause_for_user(input_fn)


DecisionChoice = Literal[
    "included", "excluded", "pending", "unsupported", "defer", "back"
]


def _choice_or_defer(
    *, input_fn: InputFunction, output: TextIO, clear_fn: ClearFunction
) -> DecisionChoice:
    clear_fn()
    print_menu_header(output, "Exception Decision")
    write_lines(
        output,
        "1. Include  2. Exclude  3. Pending  4. Unsupported",
        "D. Defer these exact items (no eligibility decision)",
        "B. Back",
    )
    raw = read_choice(input_fn).strip()
    if _back(raw):
        return "back"
    return cast(
        DecisionChoice,
        {
            "1": "included",
            "2": "excluded",
            "3": "pending",
            "4": "unsupported",
            "d": "defer",
        }.get(raw.casefold(), "back"),
    )


def _choose_exception_target(
    labels: tuple[str, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> int | None:
    """Page long exception queues without printing every student/item."""
    if not labels:
        return None
    page = 0
    while True:
        start = page * _PAGE
        end = min(len(labels), start + _PAGE)
        clear_fn()
        print_menu_header(output, "Choose Exact Exception Target")
        write_lines(output, f"Page {page + 1}/{(len(labels) - 1) // _PAGE + 1}")
        for index in range(start, end):
            print(f"{index + 1}. {labels[index]}", file=output)
        write_lines(output, "N. Next  P. Previous  B. Back")
        raw = read_choice(input_fn).strip()
        if _back(raw):
            return None
        if raw.casefold() == "n" and end < len(labels):
            page += 1
            continue
        if raw.casefold() == "p" and page:
            page -= 1
            continue
        selected = _numbers(raw, len(labels), allow_many=False)
        if selected is not None:
            return selected[0] - 1
        write_lines(output, "Choose a target number, N, P, or B.")
        pause_for_user(input_fn)


def _exceptions(
    review: AssessmentEligibilityReview,
    selected: tuple[str, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[tuple[BatchStudentException, ...], tuple[BatchItemException, ...]] | None:
    """Student overrides and exact item overrides, no hidden automatic exceptions."""
    selected_ids = set(selected)
    students = tuple(
        s
        for s in review.students
        if any(item.source.item_id in selected_ids for item in s.items)
    )
    candidate_items = tuple(
        (item.source.item_id, s.display_label, item.evidence_label)
        for s in students
        for item in s.items
        if item.source.item_id in selected_ids
    )
    by_student: dict[str, BatchStudentException] = {}
    by_item: dict[str, BatchItemException] = {}
    while True:
        clear_fn()
        print_menu_header(output, "Batch Exceptions")
        write_lines(
            output,
            f"Exact selected evidence items: {len(selected)}",
            f"Student overrides: {len(by_student)}",
            f"Individual item overrides: {len(by_item)}",
            "",
            "1. Override a selected student's items",
            "2. Override one exact selected evidence item",
            "3. Clear all overrides",
            "D. Done reviewing exceptions",
            "B. Cancel this batch",
        )
        raw = read_choice(input_fn).strip()
        if _back(raw):
            return None
        if raw.casefold() == "d":
            return tuple(by_student.values()), tuple(by_item.values())
        if raw == "3":
            by_student.clear()
            by_item.clear()
            continue
        if raw not in {"1", "2"}:
            write_lines(output, "Choose 1, 2, 3, D, B, M, or Q.")
            pause_for_user(input_fn)
            continue
        labels = (
            tuple(s.display_label for s in students)
            if raw == "1"
            else tuple(f"{name} — {evidence}" for _, name, evidence in candidate_items)
        )
        selected_index = _choose_exception_target(
            labels, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if selected_index is None:
            continue
        decision = _choice_or_defer(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if decision == "back":
            continue
        disposition = cast(
            DispositionOrDefer, None if decision == "defer" else decision
        )
        reasons = () if disposition in {None, "included"} else _MANUAL_REASON
        if raw == "1":
            student = students[selected_index]
            by_student[student.student_id] = BatchStudentException(
                student_id=student.student_id,
                disposition=disposition,
                reason_codes=reasons,
            )
        else:
            item_id = candidate_items[selected_index][0]
            by_item[item_id] = BatchItemException(
                item_id=item_id,
                disposition=disposition,
                reason_codes=reasons,
            )


def _show_recovery(
    root: Path,
    plan: BatchEligibilityReviewPlan,
    *,
    diagnostics: DiagnosticsDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Same-request exact plan recovery; no blind second Apply."""
    loader = partial(load_fresh_restart_authorization, diagnostics=diagnostics)
    while True:
        try:
            report = reconcile_sealed_eligibility_batch(
                root, plan, authorized_loader=loader, actor_checker=_actor_now
            )
        except Exception:
            write_lines(
                output,
                "Exact recovery could not verify current authorization or records.",
                "Use the Advanced individual-action recovery screen.",
            )
            pause_for_user(input_fn)
            return
        clear_fn()
        print_menu_header(output, "Incomplete Batch — Exact Recovery")
        write_lines(output, render_batch_recovery_report(report), "")
        if not report.selection_resume_count:
            pause_for_user(input_fn)
            return
        write_lines(
            output,
            "S. Review exact selection-only RESUME (no eligibility authoring)",
            "B. Back",
        )
        raw = read_choice(input_fn).strip()
        if _back(raw):
            return
        if raw.casefold() != "s":
            continue
        write_lines(
            output,
            "",
            "Type RESUME to select only the verified exact written revisions.",
            "Any other response cancels; no selections will be changed.",
        )
        if read_choice(input_fn, "Confirmation: ").strip() != "RESUME":
            return
        try:
            outcome = resume_sealed_eligibility_batch(
                root,
                plan,
                confirmed=True,
                authorized_loader=loader,
                actor_checker=_actor_now,
            )
            write_lines(output, render_batch_recovery_report(outcome))
        except Exception:
            write_lines(output, "Recovery stopped. Inspect exact action receipts.")
        pause_for_user(input_fn)
        return


def run_assessment_eligibility_menu(
    *,
    workspace_root: Path,
    prepared: GuidedProjectionResult,
    class_label: str,
    assessment_title: str,
    session_context: TeacherSessionContext,
    dependencies: GuidedEligibilityDependencies,
    diagnostics: DiagnosticsDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    """Enter from authorized #110 inbox, preserving class/work/publication context."""
    work = prepared.authorized.current_context.publication.work
    try:
        grade_items = discover_guided_eligibility_grade_items(
            workspace_root,
            work,
            dependencies=dependencies,
        )
    except Exception:
        write_lines(output, "Current Grade Items could not be verified.")
        pause_for_user(input_fn)
        return
    if not grade_items:
        clear_fn()
        print_menu_header(output, "Assessment Eligibility — Setup Required")
        write_lines(
            output,
            "No current included Grade Item matches this assessment.",
            "Use Published Assessment Setup first; none was created here.",
        )
        pause_for_user(input_fn)
        return
    grade_item = _choose_grade_item(
        grade_items,
        session_context,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if grade_item is None:
        return
    try:
        review = project_assessment_eligibility_review(
            workspace_root,
            grade_item_id=grade_item.grade_item_id,
            prepared=prepared,
            class_label=class_label,
            assessment_title=assessment_title,
        )
    except Exception:
        write_lines(
            output,
            "Assessment review is unavailable or no longer authorized.",
            "No eligibility state was changed.",
        )
        pause_for_user(input_fn)
        return
    selected = _choose_source_ids(
        review, input_fn=input_fn, output=output, clear_fn=clear_fn
    )
    if selected is None:
        return
    common = _choose_disposition(input_fn=input_fn, output=output, clear_fn=clear_fn)
    if common is None:
        return
    policy = _choose_policy(
        dependencies.policies,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if policy is None:
        return
    overrides = _exceptions(
        review, selected, input_fn=input_fn, output=output, clear_fn=clear_fn
    )
    if overrides is None:
        return
    clear_fn()
    print_menu_header(output, "Eligibility Attribution")
    write_lines(
        output,
        "Enter the saved teacher attribution used for this exact batch.",
    )
    teacher = read_choice(input_fn, "Teacher attribution: ").strip()
    if not teacher or teacher.casefold() in {"b", "m", "q"}:
        return
    rationale_text = read_choice(input_fn, "Common rationale (optional): ").strip()
    rationale = rationale_text or None
    try:
        actor = resolve_menu_actor(teacher, input_fn)
        selection = BatchEligibilitySelection(
            selected_item_ids=selected,
            disposition=common,
            reason_codes=() if common == "included" else _MANUAL_REASON,
            rationale=rationale,
            student_exceptions=overrides[0],
            item_exceptions=overrides[1],
        )
        witnesses = capture_batch_pointer_witnesses(
            workspace_root, review, prepared.authorized, selected
        )
        plan = build_batch_eligibility_plan(
            review,
            selection,
            actor=actor,
            policy=policy,
            witnesses=witnesses,
            qualified_policies=dependencies.policies,
        )
    except Exception:
        write_lines(
            output,
            "Batch plan could not be prepared against current authority.",
            "Nothing was written. Refresh the assessment before retrying.",
        )
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Exact Batch")
    write_lines(
        output,
        render_batch_eligibility_plan(plan),
        "",
        "Each item is a separate canonical #122 action; the batch is not atomic.",
        "Type APPLY to execute ONLY this exact reviewed plan.",
        "B, Enter, or any other response cancels with zero academic writes.",
    )
    if read_choice(input_fn, "Confirmation: ").strip() != "APPLY":
        write_lines(output, "Cancelled. No eligibility actions or receipts created.")
        return
    try:
        result = execute_batch_with_sealed_progress(
            workspace_root,
            plan,
            confirmed=True,
            prepared=prepared,
            grade_item=grade_item,
            dependencies=dependencies,
        )
    except Exception:
        write_lines(
            output,
            "Batch execution stopped; some items may have been attempted.",
            "Do not repeat Apply. Inspect canonical recovery before new decisions.",
        )
        _show_recovery(
            workspace_root,
            plan,
            diagnostics=diagnostics,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        return
    clear_fn()
    print_menu_header(output, "Assessment Eligibility — Results")
    write_lines(output, render_batch_execution_outcome(result), "")
    if result.stopped or any(
        item.status
        in {
            "written_not_current",
            "current_unverified",
            "conflict_requires_review",
            "recovery_required",
            "not_attempted",
        }
        for item in result.items
    ):
        write_lines(
            output,
            "R. Review incomplete batch (canonical recovery only)",
            "B. Back to assessment review",
        )
        raw = read_choice(input_fn).strip()
        if raw.casefold() == "r":
            _show_recovery(
                workspace_root,
                plan,
                diagnostics=diagnostics,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
        else:
            _back(raw)
    else:
        pause_for_user(input_fn)


__all__ = ("run_assessment_eligibility_menu",)
