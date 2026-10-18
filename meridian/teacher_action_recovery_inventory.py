"""#122 read-only recovery inbox over bounded validated action receipts.

This inventory never claims a canonical academic outcome from a journal alone.
Resume of an academic action requires a newly bound domain authority and is
not provided by this read-only module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from meridian.teacher_action_receipts import (
    TeacherActionReceipt,
    TeacherActionReceiptStore,
)


class TeacherActionRecoveryInventoryError(RuntimeError):
    """An inventory cannot safely be displayed as complete."""


@dataclass(frozen=True, slots=True)
class RecoveryInboxEntry:
    """Opaque teacher-facing checkpoint, not a verified academic record."""

    kind: str
    stage: str
    disposition: str
    recorded_at: str
    needs_review: bool
    scope_matches_workspace: bool
    receipt: TeacherActionReceipt = field(repr=False)

    @property
    def title(self) -> str:
        labels = {
            "grade_item": "Grade Item",
            "grade_item_membership": "Work relationship",
            "eligibility": "Evidence eligibility",
            "attempt_policy": "Attempt policy",
            "attempt_decision": "Attempt decision",
            "standards_association": "Standard association",
            "proficiency_result": "Proficiency result",
        }
        return labels.get(self.kind, "Teacher action")

    @property
    def description(self) -> str:
        if not self.scope_matches_workspace:
            return "Different workspace path — review required"
        if self.needs_review:
            return "Interrupted or uncertain checkpoint — review required"
        return "Receipt finalized — current academic state not rechecked"


@dataclass(frozen=True, slots=True)
class RecoveryInbox:
    """Bounded class-scoped result; no student IDs or evidence content."""

    class_id: str
    entries: tuple[RecoveryInboxEntry, ...]

    @property
    def review_count(self) -> int:
        return sum(entry.needs_review for entry in self.entries)

    @property
    def completed_receipt_count(self) -> int:
        return len(self.entries) - self.review_count


def read_recovery_inbox(
    store: TeacherActionReceiptStore,
) -> RecoveryInbox:
    """Review journal checkpoint metadata only; never write or select records.

    An unreadable or unexpected file aborts the entire scan so the inbox does
    not misleadingly claim to contain every relevant interrupted action.
    """
    if not isinstance(store, TeacherActionReceiptStore):
        raise TeacherActionRecoveryInventoryError("A class receipt store is required.")
    expected_workspace = hashlib.sha256(
        "\x1f".join(("workspace", str(store.root))).encode("utf-8")
    ).hexdigest()
    entries: list[RecoveryInboxEntry] = []
    for receipt in store.list_receipts():
        checkpoint = receipt.checkpoints[-1]
        scoped = receipt.preview.scope.workspace_sha256 == expected_workspace
        finalized = (
            checkpoint.stage == "receipt_finalized"
            and checkpoint.disposition == "completed"
            and scoped
        )
        entries.append(
            RecoveryInboxEntry(
                kind=receipt.preview.kind,
                stage=checkpoint.stage,
                disposition=checkpoint.disposition,
                recorded_at=receipt.updated_at,
                needs_review=not finalized,
                scope_matches_workspace=scoped,
                receipt=receipt,
            )
        )
    # Review-worthy items first; within each class of items, most recent first.
    entries.sort(
        key=lambda entry: (entry.recorded_at, entry.receipt.action_id),
        reverse=True,
    )
    entries.sort(key=lambda entry: not entry.needs_review)
    return RecoveryInbox(class_id=store.class_id, entries=tuple(entries))


__all__ = (
    "RecoveryInbox",
    "RecoveryInboxEntry",
    "TeacherActionRecoveryInventoryError",
    "read_recovery_inbox",
)
