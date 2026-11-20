"""#126-F3B2: explicit, original-receipt-only #31 selection restart.

Reconstruct an exact immutable #30/#31 pair from canonical storage, refresh
assessment authorization, and delegate the single reviewed selection to #126-E2A.
Never create either decision, manufacture a receipt, or replay a missing write.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from pds_core.menu_navigation import parse_navigation_choice

from meridian.assessment_attempt_inventory import (
    AssessmentAttemptInventory,
    StudentAttemptInventoryRow,
)
from meridian.attempt_decision_authoring_workflow import AttemptDecisionAuthoringPreview
from meridian.attempt_pair_restart import (
    PreparedPairRestart,
    prepare_exact_pair_restart,
    render_exact_pair_restart,
)
from meridian.attempt_reassessment_review import ProspectiveReassessmentReview
from meridian.attempt_selection import (
    AttemptProjectionReference,
    attempt_selection_decision_to_json_bytes,
)
from meridian.attempt_selection_storage import (
    StoredAttemptSelectionDecision,
    list_attempt_selection_decision_revisions,
    load_attempt_selection_decision_revision,
    load_current_attempt_selection_decision,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_correction_decision import _saved_actor
from meridian.menu_teacher_correction_history import (
    CorrectionHistory,
    load_correction_decision_history,
)
from meridian.menu_teacher_verified_continuation import _fresh_projection, _inventory
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.reassessment import reassessment_decision_to_json_bytes
from meridian.reassessment_storage import (
    StoredReassessmentDecision,
    list_reassessment_decision_revisions,
    load_current_reassessment_decision,
    load_reassessment_decision_revision,
)
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)
from meridian.teacher_session import TeacherSessionContext


class PairRestartMenuError(ValueError):
    """Do not offer recovery without one exact independently bound pair."""


def _receipts(root: Path, class_id: str) -> tuple[TeacherActionReceipt, ...]:
    return TeacherActionReceiptStore(root, class_id).list_receipts()


@dataclass(frozen=True, slots=True)
class PairRestartContextPorts:
    """Canonical read-only dependencies; no writer/selector in this adapter."""

    attempt_history: Callable[..., tuple[int, ...]] = (
        list_attempt_selection_decision_revisions
    )
    read_attempt: Callable[..., StoredAttemptSelectionDecision] = (
        load_attempt_selection_decision_revision
    )
    current_attempt: Callable[..., StoredAttemptSelectionDecision | None] = (
        load_current_attempt_selection_decision
    )
    reassessment_history: Callable[..., tuple[int, ...]] = (
        list_reassessment_decision_revisions
    )
    read_reassessment: Callable[..., StoredReassessmentDecision] = (
        load_reassessment_decision_revision
    )
    current_reassessment: Callable[..., StoredReassessmentDecision | None] = (
        load_current_reassessment_decision
    )
    receipts: Callable[[Path, str], tuple[TeacherActionReceipt, ...]] = _receipts


def _revisions(value: object) -> tuple[int, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) > 128
        or value != tuple(range(1, len(value) + 1))
        or any(type(item) is not int for item in value)
    ):
        raise PairRestartMenuError("Incomplete canonical decision revision history.")
    return cast(tuple[int, ...], value)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_exact_written_pair(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    history: CorrectionHistory,
    actor: TeacherActionActor,
    *,
    ports: PairRestartContextPorts | None = None,
) -> tuple[AttemptDecisionAuthoringPreview, ProspectiveReassessmentReview]:
    """Reconstruct historical reviewed inputs; no mutation or replay authority.

    The E2A restart service independently checks original receipt, current
    source, policy, #30 pointer, immutable #31 revision, and CAS before use.
    """
    p = ports or PairRestartContextPorts()
    if not isinstance(root, Path) or not root.is_absolute():
        raise PairRestartMenuError("Absolute workspace path required.")
    if not isinstance(actor, TeacherActionActor):
        raise PairRestartMenuError("Saved verified teacher attribution required.")
    if not isinstance(history, CorrectionHistory):
        raise PairRestartMenuError("Current validated decision history required.")
    publication = prepared.authorized.current_context.publication
    stored = prepared.authorized.stored
    source = AttemptProjectionReference(
        work=publication.work,
        publication_id=publication.publication_id,
        cache_key=stored.cache_key,
        snapshot_digest=stored.snapshot_digest,
    )
    selected = tuple(item.attempt for item in row.attempts if item.current_selected)
    selected_count = len(selected)
    if (
        prepared.authorized.assessment.reusable_for_current_use is not True
        or inventory.source_status != "current"
        or inventory.membership_state != "included"
        or publication.work.class_id != inventory.class_id
        or publication.work.module_id != inventory.work_module_id
        or publication.work.work_id != inventory.work_id
        or inventory.publication_id != source.publication_id
        or inventory.cache_key != source.cache_key
        or inventory.snapshot_digest != source.snapshot_digest
        or sum(item.student_id == row.student_id for item in inventory.students) != 1
        or row not in inventory.students
        or row.selection_status != "selected"
        or row.reassessment_status == "resolved"
        or selected_count < 2
        or len(set(selected)) != selected_count
        or any(
            not item.operative_eligible
            for item in row.attempts
            if item.current_selected
        )
        or history.stored_attempt_pointer != row.selected_decision_revision
        or history.stored_reassessment_pointer is not None
    ):
        raise PairRestartMenuError(
            "Current authorized multi-attempt state is ineligible."
        )
    # A single exact historical, unselected #31 target may be recovered.
    links = tuple(
        item
        for item in history.reassessment_rows
        if item.linked_attempt_revision == row.selected_decision_revision
    )
    if len(links) != 1 or links[0].pointer_selected:
        raise PairRestartMenuError("No unique written-but-not-current #31 pair.")
    args = (
        root,
        inventory.class_id,
        inventory.grade_item_id,
        publication.work,
        row.student_id,
    )
    try:
        attempts = _revisions(p.attempt_history(*args))
        relations = _revisions(p.reassessment_history(*args))
        if (
            not attempts
            or not relations
            or attempts[-1] != row.selected_decision_revision
            or relations[-1] != links[0].revision
        ):
            raise PairRestartMenuError("Newer decision history requires fresh review.")
        current30 = p.current_attempt(*args)
        current31 = p.current_reassessment(*args)
        selected30 = p.read_attempt(*args, attempts[-1])
        written31 = p.read_reassessment(*args, relations[-1])
        if current30 is None or current31 is not None:
            raise PairRestartMenuError("Canonical selected pointer changed.")
        first = selected30.decision
        second = written31.decision
        first_hash = _digest(attempt_selection_decision_to_json_bytes(first))
        second_hash = _digest(reassessment_decision_to_json_bytes(second))
        if (
            current30.decision_sha256 != selected30.decision_sha256
            or first_hash != selected30.decision_sha256
            or second_hash != written31.decision_sha256
            or first_hash
            != next(
                (item.sha256 for item in history.attempt_rows if item.pointer_selected),
                None,
            )
            or second_hash != links[0].sha256
            or first.source_snapshot != source
            or first.class_id != inventory.class_id
            or first.grade_item_id != inventory.grade_item_id
            or first.student_id != row.student_id
            or first.work != publication.work
            or first.decision_revision != attempts[-1]
            or first.actor.kind != "teacher"
            or first.actor.actor_id != actor.actor_id
            or first.selected_attempts != selected
            or second.class_id != first.class_id
            or second.grade_item_id != first.grade_item_id
            or second.student_id != first.student_id
            or second.work != first.work
            or second.decision_revision != relations[-1]
            or second.actor.kind != "teacher"
            or second.actor.actor_id != actor.actor_id
            or second.rationale != first.rationale
            or second.attempt_selection.decision_revision != first.decision_revision
            or second.attempt_selection.decision_sha256 != first_hash
        ):
            raise PairRestartMenuError(
                "Stored #30/#31 pair differs from reviewed source."
            )
        receipts = p.receipts(root, first.class_id)
        if not isinstance(receipts, tuple):
            raise PairRestartMenuError("Complete original receipts must be readable.")
        original31 = tuple(
            receipt
            for receipt in receipts
            if receipt.preview.kind == "reassessment_decision"
            and receipt.preview.target.candidate_sha256 == second_hash
        )
        if len(original31) != 1:
            raise PairRestartMenuError("Original #31 receipt missing or ambiguous.")
        receipt = original31[0]
        original30 = tuple(
            candidate
            for candidate in receipts
            if candidate.preview.kind == "attempt_decision"
            and candidate.preview.target.candidate_sha256 == first_hash
        )
        if len(original30) != 1:
            raise PairRestartMenuError("Original #30 receipt missing or ambiguous.")
        if (
            receipt.preview.actor != actor
            or receipt.preview.scope.class_id != first.class_id
            or receipt.preview.scope.grade_item_id != first.grade_item_id
            or receipt.preview.scope.workspace_sha256
            != _identity("workspace", str(root))
            or receipt.preview.target.identity_sha256
            != _identity(
                "reassessment_decision",
                first.class_id,
                first.grade_item_id,
                first.work.module_id,
                first.work.work_id,
                first.student_id,
            )
            or receipt.preview.target.revision != second.decision_revision
            or receipt.preview.target.expected_current_revision is not None
            or receipt.preview.target.expected_current_sha256 is not None
            or original30[0].preview.actor != actor
            or original30[0].preview.target.revision != first.decision_revision
            or original30[0].preview.target.identity_sha256
            != _identity(
                "attempt_decision",
                first.class_id,
                first.grade_item_id,
                first.work.module_id,
                first.work.work_id,
                first.student_id,
            )
        ):
            raise PairRestartMenuError("Original teacher receipt does not match pair.")
        previous_digest = (
            None
            if len(attempts) == 1
            else p.read_attempt(*args, attempts[-2]).decision_sha256
        )
        # Reconstruct the exact *historical* candidate, not a new next revision.
        # E2A remains the only service authorized to resume original selection.
        authoring = AttemptDecisionAuthoringPreview(
            candidate=first,
            history=attempts[:-1],
            latest_persisted_decision_sha256=previous_digest,
            reviewed_current_decision_revision=(
                original30[0].preview.target.expected_current_revision
            ),
            expected_membership_revision=first.membership_revision,
            expected_membership_sha256=first.membership_revision_sha256,
            expected_policy_revision=first.policy.policy_revision,
            expected_policy_sha256=first.policy.policy_revision_sha256,
        )
        reviewed = ProspectiveReassessmentReview(
            decision=second,
            upstream_decision_sha256=first_hash,
            reassessment_decision_sha256=second_hash,
            policy_sha256=second.policy.policy_revision_sha256,
            expected_current_reassessment=(None, None),
            history_before=relations[:-1],
            student_label=row.display_label,
            teacher_treatment="teacher_reviewed_reassessment",
        )
        return authoring, reviewed
    except PairRestartMenuError:
        raise
    except Exception as error:
        raise PairRestartMenuError(
            "Historical receipt reconciliation unavailable."
        ) from error


@dataclass(frozen=True, slots=True)
class PairRestartMenuPorts:
    """Injectable only for synthetic tests; production always delegates to E2A."""

    fresh_projection: Callable[..., GuidedProjectionResult] = _fresh_projection
    inventory: Callable[..., AssessmentAttemptInventory] = _inventory
    history: Callable[..., CorrectionHistory] = load_correction_decision_history
    actor: Callable[[], TeacherActionActor] = _saved_actor
    pair: Callable[
        ..., tuple[AttemptDecisionAuthoringPreview, ProspectiveReassessmentReview]
    ] = load_exact_written_pair
    restart: Callable[..., PreparedPairRestart] = prepare_exact_pair_restart
    renderer: Callable[[PreparedPairRestart], str] = render_exact_pair_restart


def _safe(value: object, *, maximum: int = 115) -> str:
    return "".join(
        (
            character
            if character.isprintable() and character not in {"\x1b", "\x7f"}
            else "?"
        )
        for character in str(value)
    )[:maximum]


def run_teacher_exact_pair_restart_menu(
    root: Path,
    prepared: GuidedProjectionResult,
    inventory: AssessmentAttemptInventory,
    row: StudentAttemptInventoryRow,
    session_context: TeacherSessionContext,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    *,
    ports: PairRestartMenuPorts | None = None,
) -> bool:
    """Confirm only original already-written #31 selection, once, through E2A."""
    p = ports or PairRestartMenuPorts()
    try:
        publication = prepared.authorized.current_context.publication
        if (
            not isinstance(root, Path)
            or not root.is_absolute()
            or session_context.active_class_id != inventory.class_id
            or session_context.active_work != publication.work
            or session_context.active_publication_id != inventory.publication_id
            or session_context.active_grade_item_id != inventory.grade_item_id
            or session_context.active_student_id != row.student_id
        ):
            raise PairRestartMenuError("Teacher session no longer bound.")
        fresh = p.fresh_projection(root, publication.work, inventory.publication_id)
        if (
            fresh.authorized.current_context.publication.work != publication.work
            or fresh.authorized.current_context.publication.publication_id
            != inventory.publication_id
            or fresh.authorized.assessment.reusable_for_current_use is not True
        ):
            raise PairRestartMenuError("Current source authorization changed.")
        updated = p.inventory(
            root,
            inventory.grade_item_id,
            fresh,
            inventory.class_label or "",
            inventory.assessment_title or "",
        )
        if (
            not isinstance(updated, AssessmentAttemptInventory)
            or updated.class_id != inventory.class_id
            or updated.grade_item_id != inventory.grade_item_id
            or updated.publication_id != inventory.publication_id
            or updated.cache_key != fresh.authorized.stored.cache_key
            or updated.snapshot_digest != fresh.authorized.stored.snapshot_digest
            or updated.source_status != "current"
            or updated.membership_state != "included"
        ):
            raise PairRestartMenuError("Refreshed assessment scope differs.")
        current_students = tuple(
            item for item in updated.students if item.student_id == row.student_id
        )
        if len(current_students) != 1:
            raise PairRestartMenuError("Student no longer currently authorized.")
        current_row = current_students[0]
        current_history = p.history(root, fresh, updated, current_row)
        actor = p.actor()
        authoring, review = p.pair(
            root, fresh, updated, current_row, current_history, actor
        )
        # These are immutable typed references, not untrusted UI input.
        if (
            not isinstance(authoring, AttemptDecisionAuthoringPreview)
            or not isinstance(review, ProspectiveReassessmentReview)
            or not isinstance(actor, TeacherActionActor)
            or authoring.candidate.class_id != updated.class_id
            or authoring.candidate.grade_item_id != updated.grade_item_id
            or authoring.candidate.work != publication.work
            or authoring.candidate.student_id != current_row.student_id
            or authoring.candidate.actor.actor_id != actor.actor_id
            or review.decision.actor.actor_id != actor.actor_id
            or review.decision.student_id != current_row.student_id
            or review.decision.attempt_selection.decision_revision
            != authoring.candidate.decision_revision
            or review.upstream_decision_sha256
            != _digest(attempt_selection_decision_to_json_bytes(authoring.candidate))
        ):
            raise PairRestartMenuError("Exact typed #30/#31 reconciliation failed.")
        action = p.restart(
            root, prepared=fresh, authoring=authoring, review=review, actor=actor
        )
        if not isinstance(action, PreparedPairRestart):
            raise PairRestartMenuError("Exact original-receipt restart unavailable.")
        rendered = p.renderer(action)
    except Exception:
        clear_fn()
        print_menu_header(output, "Exact #31 Restart — Unavailable")
        write_lines(
            output,
            "A unique original written #31 receipt and current #30 decision",
            "could not both be reverified. No action was resumed or rewritten.",
            "Review the class interrupted-saves journal and canonical history.",
        )
        pause_for_user(input_fn)
        return True
    clear_fn()
    print_menu_header(output, "Review Original Written #31 Selection")
    write_lines(
        output,
        f"Student: {_safe(current_row.display_label)}",
        rendered,
        "",
        "Type RESUME to select the exact original #31 revision.",
        "Any other input cancels without changing academic state.",
    )
    print_standard_navigation(output)
    command = read_choice(input_fn, "Confirmation: ")
    if command != "RESUME":
        parse_navigation_choice(command)
        write_lines(output, "Cancelled. No academic state changed.")
        return True
    try:
        outcome = action.resume(confirmed=True)
    except Exception:
        clear_fn()
        print_menu_header(output, "Exact #31 Restart — Outcome Uncertain")
        write_lines(
            output,
            "Selection may have occurred. Do not repeat RESUME.",
            "Inspect canonical #30/#31 state and the original receipt.",
        )
        return True
    clear_fn()
    if (
        outcome.status == "pair_current_verified"
        and outcome.exact_pair_current
        and outcome.continue_to_standards_review
    ):
        print_menu_header(output, "Exact #30/#31 Pair Verified")
        write_lines(
            output,
            "Both original decisions are now independently current.",
            "No immutable decision, receipt, Standard or Grade was created.",
            "Return to the assessment, then select V for Standards review.",
        )
    else:
        print_menu_header(output, "Exact #31 Restart — Recovery Required")
        write_lines(
            output,
            f"Outcome: {_safe(outcome.status)}",
            "The pair is not independently verified as current.",
            "Do not repeat RESUME. Reconcile original receipt and pointers.",
        )
    pause_for_user(input_fn)
    return True


__all__ = (
    "PairRestartContextPorts",
    "PairRestartMenuError",
    "PairRestartMenuPorts",
    "load_exact_written_pair",
    "run_teacher_exact_pair_restart_menu",
)
