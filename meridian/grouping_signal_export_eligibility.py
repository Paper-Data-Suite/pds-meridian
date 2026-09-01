"""Read-only export eligibility over explicitly selected #39 review state.

This module resolves and revalidates teacher authorization for issue #40.
It performs no Core grouping-signal write, Meridian export-receipt write, CSV
write, review mutation, derivation generation, preview generation, or Concord
operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    GroupingSignalPreviewReference,
)
from meridian.grouping_signal_review import GroupingSignalReviewReference
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    StoredGroupingSignalReview,
    load_current_grouping_signal_review,
)

GroupingSignalExportBlockCode: TypeAlias = Literal[
    "no_selected_review",
    "review_not_accepted",
    "review_stale",
    "derivation_not_current",
    "review_selection_changed",
]


class GroupingSignalExportEligibilityError(RuntimeError):
    """Base error for read-only #40 export eligibility."""


class GroupingSignalExportEligibilityReadError(
    GroupingSignalExportEligibilityError
):
    """Raised when exact #38/#39 authorization state cannot be read safely."""


class GroupingSignalExportBlockedError(GroupingSignalExportEligibilityError):
    """Raised when deliberate export authorization is absent or no longer valid."""

    code: GroupingSignalExportBlockCode
    reason_codes: tuple[str, ...]

    def __init__(
        self,
        code: GroupingSignalExportBlockCode,
        *,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.reason_codes = tuple(sorted(set(reason_codes)))
        detail = (
            ""
            if not self.reason_codes
            else f" ({', '.join(self.reason_codes)})"
        )
        super().__init__(f"Grouping-signal export blocked: {code}{detail}.")


@dataclass(frozen=True, slots=True)
class GroupingSignalExportEligibility:
    """Exact selected review authorization validated against live #38 state."""

    derivation_reference: GroupingSignalDerivationReference
    preview_reference: GroupingSignalPreviewReference
    review_reference: GroupingSignalReviewReference
    currentness: GroupingSignalPreviewCurrentness

    def __post_init__(self) -> None:
        if not isinstance(
            self.derivation_reference,
            GroupingSignalDerivationReference,
        ):
            raise GroupingSignalExportEligibilityReadError(
                "derivation_reference must be an exact #38 reference."
            )
        self.derivation_reference.__post_init__()
        if not isinstance(self.preview_reference, GroupingSignalPreviewReference):
            raise GroupingSignalExportEligibilityReadError(
                "preview_reference must be an exact #39 preview reference."
            )
        self.preview_reference.__post_init__()
        if not isinstance(self.review_reference, GroupingSignalReviewReference):
            raise GroupingSignalExportEligibilityReadError(
                "review_reference must be an exact #39 review reference."
            )
        self.review_reference.__post_init__()
        if not isinstance(self.currentness, GroupingSignalPreviewCurrentness):
            raise GroupingSignalExportEligibilityReadError(
                "currentness must be a GroupingSignalPreviewCurrentness."
            )
        self.currentness.__post_init__()

        class_id = self.derivation_reference.class_id
        if (
            self.preview_reference.class_id != class_id
            or self.review_reference.class_id != class_id
            or self.review_reference.derivation_id
            != self.derivation_reference.derivation_id
        ):
            raise GroupingSignalExportEligibilityReadError(
                "Export eligibility references must share one exact derivation "
                "class/identity scope."
            )
        if (
            self.currentness.state != "current"
            or self.currentness.current_derivation_reference
            != self.derivation_reference
        ):
            raise GroupingSignalExportEligibilityReadError(
                "Export eligibility must contain an exact current derivation."
            )


def resolve_grouping_signal_export_eligibility(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> GroupingSignalExportEligibility:
    """Resolve the explicitly selected accepted review against live #38 state."""

    selected = _load_selected_review(
        workspace_root,
        class_id,
        derivation_id,
    )
    if selected is None:
        raise GroupingSignalExportBlockedError("no_selected_review")
    return _eligibility_from_selected(workspace_root, selected)


def revalidate_grouping_signal_export_eligibility(
    workspace_root: str | Path,
    expected: GroupingSignalExportEligibility,
) -> GroupingSignalExportEligibility:
    """Final read-only gate immediately before a later Core write.

    The exact selected review must still be the same digest-bound revision and
    its exact #38 derivation must still be current.
    """

    if not isinstance(expected, GroupingSignalExportEligibility):
        raise GroupingSignalExportEligibilityReadError(
            "expected must be a GroupingSignalExportEligibility."
        )
    expected.__post_init__()

    selected = _load_selected_review(
        workspace_root,
        expected.derivation_reference.class_id,
        expected.derivation_reference.derivation_id,
    )
    if selected is None or selected.reference != expected.review_reference:
        raise GroupingSignalExportBlockedError("review_selection_changed")

    current = _eligibility_from_selected(workspace_root, selected)
    if current != expected:
        raise GroupingSignalExportEligibilityReadError(
            "Exact export authorization changed without a selected-review "
            "identity change."
        )
    return current


def _load_selected_review(
    workspace_root: str | Path,
    class_id: str,
    derivation_id: str,
) -> StoredGroupingSignalReview | None:
    try:
        return load_current_grouping_signal_review(
            workspace_root,
            class_id,
            derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise GroupingSignalExportEligibilityReadError(
            "Could not load and verify the explicitly selected #39 review."
        ) from error


def _eligibility_from_selected(
    workspace_root: str | Path,
    selected: StoredGroupingSignalReview,
) -> GroupingSignalExportEligibility:
    review = selected.review
    if review.decision != "accepted_for_export":
        raise GroupingSignalExportBlockedError("review_not_accepted")

    currentness = _assess_currentness(
        workspace_root,
        review.derivation_reference,
    )
    return GroupingSignalExportEligibility(
        derivation_reference=review.derivation_reference,
        preview_reference=review.preview_reference,
        review_reference=selected.reference,
        currentness=currentness,
    )


def _assess_currentness(
    workspace_root: str | Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> GroupingSignalPreviewCurrentness:
    try:
        currentness = assess_grouping_signal_derivation_currentness(
            workspace_root,
            derivation_reference,
        )
    except GroupingSignalCurrentnessError as error:
        raise GroupingSignalExportEligibilityReadError(
            "Could not re-assess the exact #38 derivation for export."
        ) from error

    if (
        currentness.state == "current"
        and currentness.current_derivation_reference == derivation_reference
    ):
        return currentness

    if currentness.state == "stale":
        raise GroupingSignalExportBlockedError(
            "review_stale",
            reason_codes=currentness.reason_codes,
        )

    reasons = currentness.reason_codes
    if not reasons:
        reasons = ("derivation_reference_mismatch",)
    raise GroupingSignalExportBlockedError(
        "derivation_not_current",
        reason_codes=reasons,
    )
