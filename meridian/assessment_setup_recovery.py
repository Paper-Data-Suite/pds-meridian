"""#124 E1: conservative, read-only restart inspection for composite setup.

An action receipt is not the canonical truth and a Grade Item title is not an
identity. This service never creates/reselects academic records or receipts.
E2 must provide exact durable correlation and separately approved recovery.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.assessment_setup_choices import (
    NamedAssessmentList,
    load_named_assessment_choices,
)
from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.grade_items_workflow import GradeItemsReview, project_grade_items_review
from meridian.teacher_action_guided import _identity
from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)

RecoveryState: TypeAlias = Literal[
    "pristine",
    "ready_verified",
    "grade_item_written_not_selected",
    "grade_item_selected_link_missing",
    "membership_written_not_selected",
    "relationship_needs_review",
    "receipts_need_review",
    "source_changed",
    "inspection_unavailable",
]

NamedReader: TypeAlias = Callable[..., NamedAssessmentList]
GradeReader: TypeAlias = Callable[[Path, str], GradeItemsReview]
ReceiptReader: TypeAlias = Callable[[Path, str], tuple[TeacherActionReceipt, ...]]


def _read_receipts(root: Path, class_id: str) -> tuple[TeacherActionReceipt, ...]:
    return TeacherActionReceiptStore(root, class_id).list_receipts()


@dataclass(frozen=True, slots=True)
class AssessmentSetupRecoveryReaders:
    """Read-only canonical and journal ports, injectable in isolated tests."""

    named: NamedReader = load_named_assessment_choices
    grades: GradeReader = project_grade_items_review
    receipts: ReceiptReader = _read_receipts


@dataclass(frozen=True, slots=True)
class AssessmentSetupRecoveryInspection:
    """Bounded restart advice, never a capability to replay a prior action."""

    state: RecoveryState
    reason: str
    review_sha256: str
    grade_item_id: str
    grade_action_ids: tuple[str, ...]
    membership_action_ids: tuple[str, ...]
    grade_selected_revision: int | None
    membership_selected_revision: int | None

    @property
    def ready(self) -> bool:
        return self.state == "ready_verified"

    @property
    def can_resume_without_review(self) -> bool:
        # Deliberately false until E2 binds both stage IDs to a durable intent.
        return False


def inspect_assessment_setup_recovery(
    workspace_root: str | Path,
    preview: AssessmentSetupPreview,
    *,
    readers: AssessmentSetupRecoveryReaders = AssessmentSetupRecoveryReaders(),
) -> AssessmentSetupRecoveryInspection:
    """Inspect a frozen C1 identity after restart without changing any files.

    No untrusted receipt or catalog row can authorize fresh creation, selection,
    or automatic retry. A prior action with no receipt still requires review
    if any Grade Item history occupies its exact proposed identity.
    """
    if not isinstance(preview, AssessmentSetupPreview):
        raise TypeError("An exact reviewed setup preview is required.")
    root = Path(workspace_root).resolve()

    def result(
        state: RecoveryState,
        reason: str,
        grades: tuple[str, ...] = (),
        members: tuple[str, ...] = (),
        grade_revision: int | None = None,
        member_revision: int | None = None,
    ) -> AssessmentSetupRecoveryInspection:
        return AssessmentSetupRecoveryInspection(
            state,
            reason,
            preview.review_sha256,
            preview.grade_item_id,
            grades,
            members,
            grade_revision,
            member_revision,
        )

    if not root.is_dir():
        return result("inspection_unavailable", "workspace_unavailable")
    try:
        named = readers.named(
            root,
            class_id=preview.class_id,
            school_year=preview.school_year,
            period_id=preview.marking_period_id,
        )
        matches = tuple(
            item for item in named.items if item.candidate.work == preview.work
        )
        if len(matches) != 1:
            return result("source_changed", "assessment_identity_missing")
        one = matches[0]
        candidate = one.candidate
        if (
            named.class_id != preview.class_id
            or named.school_year != preview.school_year
            or named.period_id != preview.marking_period_id
            or candidate.work != preview.work
            or candidate.registration_revision != preview.registration_revision
            or candidate.lifecycle != preview.registration_lifecycle
            or candidate.title != preview.assessment_title
            or candidate.calendar_revision != preview.calendar_revision
            or candidate.period_id != preview.marking_period_id
            or candidate.publication_id != preview.publication_id
            or (one.publication_state == "current_results_verified")
            != (preview.publication_id is not None)
        ):
            return result("source_changed", "reviewed_source_drift")
        review = readers.grades(root, preview.class_id)
        receipts = readers.receipts(root, preview.class_id)
        if review.class_id != preview.class_id:
            return result("inspection_unavailable", "grade_scope_invalid")
        if len(review.items) > 500 or len(receipts) > 10000:
            return result("inspection_unavailable", "inventory_limit")
        rows = tuple(
            item for item in review.items if item.grade_item_id == preview.grade_item_id
        )
        if len(rows) > 1:
            return result("relationship_needs_review", "duplicate_grade_identity")
        row = rows[0] if rows else None
        relevant = tuple(
            receipt
            for receipt in receipts
            if receipt.preview.scope.class_id == preview.class_id
            and receipt.preview.scope.grade_item_id == preview.grade_item_id
            and receipt.preview.kind in ("grade_item", "grade_item_membership")
        )
        grade_actions: list[str] = []
        member_actions: list[str] = []
        receipt_conflict = False
        for receipt in relevant:
            action = receipt.preview
            scope = action.scope
            if (
                scope.workspace_sha256 != _identity("workspace", str(root))
                or action.actor.actor_id != preview.actor_attribution
                or action.kind != action.target.family
            ):
                receipt_conflict = True
            if action.kind == "grade_item":
                grade_actions.append(action.action_id)
                if (
                    preview.kind != "create_and_link"
                    or scope.school_year is not None
                    or action.target.revision != 1
                ):
                    receipt_conflict = True
            else:
                member_actions.append(action.action_id)
                if (
                    scope.school_year != preview.school_year
                    or scope.academic_period_id != preview.marking_period_id
                    or scope.work_identity_sha256
                    != _identity(
                        "work",
                        preview.class_id,
                        preview.work.module_id,
                        preview.work.work_id,
                    )
                ):
                    receipt_conflict = True
        grade_ids = tuple(sorted(grade_actions))
        member_ids = tuple(sorted(member_actions))
        grade_revision = None if row is None else row.selected_revision
        members = (
            ()
            if row is None
            else tuple(item for item in row.memberships if item.work == preview.work)
        )
        member_revision = members[0].selected_revision if len(members) == 1 else None
        if (
            receipt_conflict
            or len(set(grade_ids)) != len(grade_ids)
            or len(set(member_ids)) != len(member_ids)
        ):
            return result(
                "receipts_need_review",
                "receipt_scope_conflict",
                grade_ids,
                member_ids,
                grade_revision,
                member_revision,
            )
        if len(grade_ids) > 1 or len(member_ids) > 1:
            return result(
                "receipts_need_review",
                "multiple_action_attempts",
                grade_ids,
                member_ids,
                grade_revision,
                member_revision,
            )
        if row is None:
            if candidate.setup_state not in ("needs_create", "choose_existing"):
                return result(
                    "relationship_needs_review",
                    "catalog_grade_disagrees",
                    grade_ids,
                    member_ids,
                )
            return result(
                "receipts_need_review"
                if relevant or preview.kind != "create_and_link"
                else "pristine",
                "prior_action_without_grade" if relevant else "grade_item_absent",
                grade_ids,
                member_ids,
            )
        if len(members) > 1 or (
            row.selected_revision is not None
            and (
                row.status != "active"
                or row.title != preview.grade_item_title
                or row.purpose != preview.grade_item_purpose
                or (
                    preview.selected_grade_item_revision is not None
                    and row.selected_revision != preview.selected_grade_item_revision
                )
                or (preview.kind == "create_and_link" and row.selected_revision != 1)
            )
        ):
            return result(
                "relationship_needs_review",
                "grade_identity_or_revision_changed",
                grade_ids,
                member_ids,
                grade_revision,
                member_revision,
            )
        if row.selected_revision is None:
            return result(
                "grade_item_written_not_selected",
                "grade_history_without_selection",
                grade_ids,
                member_ids,
                grade_revision,
                member_revision,
            )
        if members:
            member = members[0]
            if member.selected_revision is None:
                return result(
                    "membership_written_not_selected",
                    "membership_history_without_selection",
                    grade_ids,
                    member_ids,
                    grade_revision,
                    member_revision,
                )
            if (
                member.decision != "included"
                or member.grade_item_basis_state != "matches_current_grade_item"
                or member.registration_revision != preview.registration_revision
                or member.academic_period_school_year != preview.school_year
                or member.academic_period_id != preview.marking_period_id
                or member.academic_period_calendar_revision != preview.calendar_revision
            ):
                return result(
                    "relationship_needs_review",
                    "membership_not_operative",
                    grade_ids,
                    member_ids,
                    grade_revision,
                    member_revision,
                )
            if candidate.setup_state == "ready" and (
                candidate.ready_grade_item_id == preview.grade_item_id
            ):
                return result(
                    "ready_verified",
                    "canonical_current_exact",
                    grade_ids,
                    member_ids,
                    grade_revision,
                    member_revision,
                )
            return result(
                "relationship_needs_review",
                "readiness_projection_disagrees",
                grade_ids,
                member_ids,
                grade_revision,
                member_revision,
            )
        return result(
            "grade_item_selected_link_missing",
            "canonical_grade_has_no_membership",
            grade_ids,
            member_ids,
            grade_revision,
            member_revision,
        )
    except Exception:
        # Do not turn a corrupt/missing source, journal or unknown I/O error
        # into permission to create another Grade Item.
        return result("inspection_unavailable", "canonical_or_receipt_read_failed")


__all__ = (
    "AssessmentSetupRecoveryInspection",
    "AssessmentSetupRecoveryReaders",
    "RecoveryState",
    "inspect_assessment_setup_recovery",
)
