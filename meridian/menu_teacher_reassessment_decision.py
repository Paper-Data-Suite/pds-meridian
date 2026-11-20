"""#126-F2B: one explicit teacher-reviewed two-domain reassessment menu.

This is a teacher interaction over #30/#31/#122, not a new writer or a
producer-certified correction classifier. Every selected attempt and academic
relationship is supplied by the teacher; no sequence/score is a decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    NativeAttemptInventoryRow,
    StudentAttemptInventoryRow,
)
from meridian.attempt_correction_interpretation import (
    AttemptInterpretationPreview,
    preview_attempt_interpretation,
)
from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_reassessment_review import (
    ProspectiveReassessmentReview,
    ReviewedReassessmentChoice,
    preview_reviewed_reassessment,
)
from meridian.attempt_resolution_coordinator import (
    PreparedMultiAttemptResolution,
    prepare_reviewed_multi_attempt_resolution,
    render_reviewed_multi_attempt_resolution,
)
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPlan,
    GuidedAttemptPolicyPreset,
    plan_guided_attempt_policy,
    preview_guided_attempt_decision,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_correction_decision import _saved_actor
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.reassessment import (
    ReassessmentCombination,
    ReplacementRelationship,
)
from meridian.reassessment_storage import (
    StoredReassessmentDecision,
    StoredReassessmentPolicy,
    list_reassessment_decision_revisions,
    load_current_reassessment_decision,
    load_current_reassessment_policy,
)
from meridian.teacher_action_contract import TeacherActionActor

# This is a configured policy identity, NOT an automatic policy selection.
# The public #31 current-policy loader must verify it is already selected.
REASSESSMENT_POLICY_ID = "teacher_reassessment"


@dataclass(frozen=True, slots=True)
class ReassessmentDecisionPorts:
    """Injectable edges; production delegates to existing canonical services."""

    actor_loader: Callable[[], TeacherActionActor] = _saved_actor
    intention_previewer: Callable[..., AttemptInterpretationPreview] = (
        preview_attempt_interpretation
    )
    policy_planner: Callable[..., GuidedAttemptPolicyPlan] = plan_guided_attempt_policy
    authoring_previewer: Callable[..., AttemptDecisionAuthoringPreview] = (
        preview_guided_attempt_decision
    )
    reassessment_policy_loader: Callable[..., StoredReassessmentPolicy | None] = (
        load_current_reassessment_policy
    )
    history_loader: Callable[..., tuple[int, ...]] = (
        list_reassessment_decision_revisions
    )
    current_loader: Callable[..., StoredReassessmentDecision | None] = (
        load_current_reassessment_decision
    )
    reassessment_previewer: Callable[..., ProspectiveReassessmentReview] = (
        preview_reviewed_reassessment
    )
    coordinator_preparer: Callable[..., PreparedMultiAttemptResolution] = (
        prepare_reviewed_multi_attempt_resolution
    )
    coordinator_renderer: Callable[[PreparedMultiAttemptResolution], str] = (
        render_reviewed_multi_attempt_resolution
    )
    reassessment_policy_id: str = REASSESSMENT_POLICY_ID


def _safe(value: object, maximum: int = 112) -> str:
    text = str(value)
    cleaned = "".join(
        ch if ch.isprintable() and ch not in {"\x1b", "\x7f"} else "?" for ch in text
    )
    return cleaned[:maximum] + ("..." if len(cleaned) > maximum else "")


def _label(item: NativeAttemptInventoryRow) -> str:
    points = (
        "points unavailable"
        if item.point_result is None
        else f"source points {item.point_result[0]}/{item.point_result[1]}"
    )
    return f"{_safe(item.attempt_label)} — {points}"


def _numbers(raw: str, upper: int, *, min_count: int = 1) -> tuple[int, ...] | None:
    """Teacher-entered exact displayed indexes, in teacher-supplied order."""
    parts = tuple(part.strip() for part in raw.split(","))
    if (
        not parts
        or any(not p.isascii() or not p.isdigit() or not p for p in parts)
        or len(parts) < min_count
    ):
        return None
    numbers = tuple(int(p) for p in parts)
    if len(set(numbers)) != len(numbers) or any(n < 1 or n > upper for n in numbers):
        return None
    return numbers


def _pick(
    title: str,
    prompt: str,
    options: tuple[NativeAttemptInventoryRow, ...],
    *,
    min_count: int,
    exactly_all: bool = False,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> tuple[NativeAttemptInventoryRow, ...] | None:
    while True:
        clear_fn()
        print_menu_header(output, title)
        write_lines(output, prompt, "")
        for index, item in enumerate(options, 1):
            write_lines(output, f"{index}. {_label(item)}")
        write_lines(
            output, "", "Enter comma-separated numbers in the order you intend."
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        if not raw or parse_navigation_choice(raw) is NavigationChoice.BACK:
            return None
        selected = _numbers(raw, len(options), min_count=min_count)
        if selected is not None and (not exactly_all or len(selected) == len(options)):
            return tuple(options[number - 1] for number in selected)
        write_lines(output, "Select distinct displayed attempts explicitly; B cancels.")


def _relationship(
    selected: tuple[NativeAttemptInventoryRow, ...],
    *,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> ReviewedReassessmentChoice | None:
    """Four explicit modes. No implicit arithmetic, preference, or chronology."""
    while True:
        clear_fn()
        print_menu_header(output, "Choose Reassessment Relationship")
        write_lines(
            output,
            "1. Retain all selected performances separately",
            "2. Replace specific earlier performance(s)",
            "3. Combine named performances (no automatic arithmetic)",
            "4. Explicit recency order and contributors",
            "",
            "Scores and attempt numbers do not determine your choice.",
        )
        print_standard_navigation(output)
        raw = read_choice(input_fn)
        if not raw or parse_navigation_choice(raw) is NavigationChoice.BACK:
            return None
        if raw == "1":
            return ReviewedReassessmentChoice("retain")
        if raw not in {"2", "3", "4"}:
            write_lines(output, "Choose 1-4, B, M, or Q.")
            continue
        if raw == "2":
            replacement = _pick(
                "Replacement Performance",
                "Choose ONE replacement performance.",
                selected,
                min_count=1,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            if replacement is None:
                return None
            if len(replacement) != 1:
                write_lines(output, "Choose exactly one replacement performance.")
                continue
            original = tuple(x for x in selected if x != replacement[0])
            replaced = _pick(
                "Performances Being Replaced",
                "Select specific old performance(s) to replace.",
                original,
                min_count=1,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            if replaced is None:
                return None
            return ReviewedReassessmentChoice(
                "replace",
                replacements=(
                    ReplacementRelationship(
                        replacement[0].attempt,
                        tuple(value.attempt for value in replaced),
                    ),
                ),
            )
        if raw == "3":
            members = _pick(
                "Explicit Combination Members",
                "Select at least two performances for one named group.",
                selected,
                min_count=2,
                input_fn=input_fn,
                output=output,
                clear_fn=clear_fn,
            )
            if members is None:
                return None
            return ReviewedReassessmentChoice(
                "combine",
                combinations=(
                    ReassessmentCombination(
                        "teacher_reviewed_combination_1",
                        tuple(value.attempt for value in members),
                    ),
                ),
            )
        ordered = _pick(
            "Explicit Recency Order",
            "List ALL selected performances in teacher-verified "
            "oldest-to-newest order.",
            selected,
            min_count=len(selected),
            exactly_all=True,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if ordered is None:
            return None
        contributors = _pick(
            "Explicit Recency Contributors",
            "Select the performance(s) that should contribute to academic use.",
            selected,
            min_count=1,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if contributors is None:
            return None
        return ReviewedReassessmentChoice(
            "recency",
            recency_order=tuple(x.attempt for x in ordered),
            recency_contributors=tuple(x.attempt for x in contributors),
        )


def _multi_preset(
    dependencies: GuidedAttemptDependencies,
) -> GuidedAttemptPolicyPreset | None:
    options = tuple(
        policy
        for policy in dependencies.policies
        if policy.minimum_selected <= 2
        and (policy.maximum_selected is None or policy.maximum_selected >= 2)
        and policy.minimum_selected >= 1
    )
    # Prefer the single qualified one-or-more preset, not an arbitrary policy.
    matches = tuple(
        policy
        for policy in options
        if policy.minimum_selected == 1 and policy.maximum_selected is None
    )
    return matches[0] if len(matches) == 1 else None


def run_teacher_reassessment_decision_menu(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    dependencies: GuidedAttemptDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: ReassessmentDecisionPorts | None = None,
) -> bool:
    """Return True to force canonical queue reload after any review or cancellation."""
    p = ports or ReassessmentDecisionPorts()
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or not isinstance(inventory, AssessmentAttemptInventory)
        or not isinstance(row, StudentAttemptInventoryRow)
        or row not in inventory.students
        or sum(student.student_id == row.student_id for student in inventory.students)
        != 1
        or inventory.source_status != "current"
        or inventory.membership_state != "included"
        or row.selection_status not in {"no_decision", "selected", "selected_none"}
        or len({item.attempt for item in row.attempts}) != len(row.attempts)
    ):
        clear_fn()
        print_menu_header(output, "Reassessment — Refresh Required")
        write_lines(
            output,
            "Exact current source, Grade Item, or student selection is unavailable.",
            "No academic decision was saved.",
        )
        return True
    eligible = tuple(item for item in row.attempts if item.operative_eligible)
    if len(eligible) < 2:
        clear_fn()
        print_menu_header(output, "Reassessment — Not Ready")
        write_lines(
            output,
            "At least two distinct operative eligible performances are required.",
            "Review assessment eligibility before proceeding. No action was saved.",
        )
        return True
    preset = _multi_preset(dependencies)
    if preset is None:
        clear_fn()
        print_menu_header(output, "Reassessment — Attempt Policy Needed")
        write_lines(
            output,
            "A qualified one-or-more #30 policy must be selected separately.",
            "No policy was changed here.",
        )
        return True
    chosen = _pick(
        "Select Separate Performances",
        "Select at least two exact eligible performances (do not infer from score).",
        eligible,
        min_count=2,
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if chosen is None:
        return True
    # Canonical candidates are source-order references, not ranked preferences.
    selected = tuple(item.attempt for item in eligible if item in chosen)
    relationship = _relationship(
        tuple(item for item in eligible if item in chosen),
        input_fn=input_fn,
        output=output,
        clear_fn=clear_fn,
    )
    if relationship is None:
        return True
    clear_fn()
    print_menu_header(output, "Teacher-Reviewed Reassessment Rationale")
    write_lines(
        output,
        f"Student: {_safe(row.display_label)}",
        "Explain the independent performances and relationship.",
        "This testimony does NOT certify producer correction provenance.",
        "",
    )
    # Literal free text, never parsed as B/M/Q or :notes command.
    rationale = read_choice(
        input_fn, "Teacher explanation (required; Enter cancels): "
    ).strip()
    if not rationale:
        write_lines(output, "Cancelled before writing. No decision or receipt created.")
        return True
    try:
        actor = p.actor_loader()
        interpretation = p.intention_previewer(
            inventory,
            student_id=row.student_id,
            treatment="teacher_reviewed_reassessment",
            selected_attempts=selected,
            teacher_rationale=rationale,
        )
        # The #30 candidate digest is bound into the exact #31 immutable record.
        # Freeze the reviewed timestamp for both preview and coordinator recompute.
        fixed = dependencies.clock()
        frozen = replace(dependencies, clock=lambda: fixed)
        plan = p.policy_planner(
            root,
            class_id=inventory.class_id,
            grade_item_id=inventory.grade_item_id,
            work=interpretation.source_snapshot.work,
            preset=preset,
            dependencies=frozen,
        )
        if plan.action != "ready" or plan.preset != preset:
            raise ValueError("Explicit #30 policy must be selected separately.")
        authoring = p.authoring_previewer(
            root,
            prepared=prepared,
            grade_item_id=interpretation.grade_item_id,
            student_id=interpretation.student_id,
            preset=preset,
            selected_attempts=interpretation.intended_selected_attempts,
            teacher_attribution=actor.actor_id,
            rationale=interpretation.suggested_canonical_rationale,
            dependencies=frozen,
        )
        policy = p.reassessment_policy_loader(
            root,
            inventory.class_id,
            inventory.grade_item_id,
            interpretation.source_snapshot.work,
            p.reassessment_policy_id,
        )
        if policy is None:
            raise ValueError("A separately selected exact #31 policy is required.")
        history = p.history_loader(
            root,
            inventory.class_id,
            inventory.grade_item_id,
            interpretation.source_snapshot.work,
            row.student_id,
        )
        current = p.current_loader(
            root,
            inventory.class_id,
            inventory.grade_item_id,
            interpretation.source_snapshot.work,
            row.student_id,
        )
        review = p.reassessment_previewer(
            interpretation=interpretation,
            authoring=authoring,
            policy=policy,
            history=history,
            current=current,
            choice=relationship,
            actor=actor,
            decided_at=fixed,
        )
        action = p.coordinator_preparer(
            root,
            prepared=prepared,
            interpretation=interpretation,
            review=review,
            preset=preset,
            actor=actor,
            dependencies=frozen,
        )
        render = p.coordinator_renderer(action)
    except Exception:
        clear_fn()
        print_menu_header(output, "Reassessment — Current Review Unavailable")
        write_lines(
            output,
            "Saved teacher identity, #30/#31 policies, current source or "
            "immutable history could not be verified.",
            "Select required policies separately or refresh the assessment.",
            "No write was initiated by this menu.",
        )
        return True
    clear_fn()
    print_menu_header(output, "Review and Use Reassessment Decision")
    write_lines(
        output,
        render,
        "",
        "1. Save and Use This Decision",
        "2. Cancel without saving",
        "",
    )
    print_standard_navigation(output)
    raw = read_choice(input_fn)
    if raw != "1":
        parse_navigation_choice(raw)
        write_lines(output, "Cancelled. No new #30/#31 decisions were saved.")
        return True
    try:
        outcome = action.apply(confirmed=True)
    except Exception:
        clear_fn()
        print_menu_header(output, "Reassessment — Outcome Uncertain")
        write_lines(
            output,
            "#30 and/or #31 may already have been written.",
            "Do not retry Save; review the original #122 receipts "
            "and canonical pointers.",
        )
        return True
    clear_fn()
    if (
        outcome.exact_pair_current
        and outcome.continue_to_standards_review
        and outcome.status in {"applied_current", "already_current"}
    ):
        print_menu_header(output, "Reassessment — Both Decisions Current Verified")
        write_lines(
            output,
            "Both exact #30 and #31 decisions were independently verified.",
            "History remains immutable; no Grade, Standards or "
            "producer result changed.",
            "Return to assessment or continue to Standards review.",
        )
    else:
        print_menu_header(output, "Reassessment — Recovery or Review Required")
        write_lines(
            output,
            f"Outcome: {_safe(outcome.status)}",
            "The complete pair has NOT been independently verified.",
            "Do not retry Save; reconcile the original #122 actions "
            "and canonical state.",
        )
    pause_for_user(input_fn)
    return True


__all__ = ("ReassessmentDecisionPorts", "run_teacher_reassessment_decision_menu")
