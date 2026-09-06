"""Read-only planning-review attention derived from canonical #39 state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.classes import class_folder
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.school_years import SchoolYearValidationError, validate_school_year

from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewSnapshot
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    list_grouping_signal_preview_ids,
    load_grouping_signal_preview,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewError,
    assess_grouping_signal_review_applicability,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    list_grouping_signal_review_revisions,
    load_current_grouping_signal_review,
)
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    MeridianAttentionSummary,
    build_meridian_attention_summary,
)

PlanningAttentionCurrentness: TypeAlias = Literal["current", "stale", "blocked"]
PlanningAttentionReviewState: TypeAlias = Literal[
    "none",
    "unselected_history",
    "selected_current",
    "selected_rejected",
    "selected_stale",
]


class PlanningAttentionError(RuntimeError):
    """Base error for read-only planning-attention inspection."""


class PlanningAttentionReadError(PlanningAttentionError):
    """Raised when canonical planning state cannot be inspected safely."""


class PlanningAttentionIntegrityError(PlanningAttentionReadError):
    """Raised when derived planning-attention facts are contradictory."""


@dataclass(frozen=True, slots=True)
class PlanningAttentionScopeState:
    """One exact derivation's currentness/review state for one policy scope."""

    policy_id: str
    derivation_id: str
    currentness: PlanningAttentionCurrentness
    review_state: PlanningAttentionReviewState

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(
            self,
            "derivation_id",
            _identifier(self.derivation_id, "derivation_id"),
        )
        if self.currentness not in {"current", "stale", "blocked"}:
            raise PlanningAttentionIntegrityError(
                "planning attention currentness is invalid."
            )
        if self.review_state not in {
            "none",
            "unselected_history",
            "selected_current",
            "selected_rejected",
            "selected_stale",
        }:
            raise PlanningAttentionIntegrityError(
                "planning attention review_state is invalid."
            )
        if self.currentness == "current" and self.review_state == "selected_stale":
            raise PlanningAttentionIntegrityError(
                "a current derivation cannot carry a stale selected review."
            )
        if self.currentness != "current" and self.review_state == "selected_current":
            raise PlanningAttentionIntegrityError(
                "a noncurrent derivation cannot carry a current selected review."
            )


def build_planning_attention_summary(
    states: tuple[PlanningAttentionScopeState, ...],
    class_id: str,
) -> MeridianAttentionSummary:
    """Collapse exact derivation facts into one attention item per policy scope."""

    class_value = _identifier(class_id, "class_id")
    by_derivation: dict[str, PlanningAttentionScopeState] = {}
    for state in states:
        if not isinstance(state, PlanningAttentionScopeState):
            raise PlanningAttentionIntegrityError(
                "states must contain only PlanningAttentionScopeState values."
            )
        prior = by_derivation.get(state.derivation_id)
        if prior is not None and prior != state:
            raise PlanningAttentionIntegrityError(
                "one derivation_id cannot carry contradictory attention state."
            )
        by_derivation[state.derivation_id] = state

    by_policy: dict[str, list[PlanningAttentionScopeState]] = {}
    for state in by_derivation.values():
        by_policy.setdefault(state.policy_id, []).append(state)

    pending = 0
    selection_pending = 0
    stale = 0
    for policy_id in sorted(by_policy):
        policy_states = by_policy[policy_id]
        current_states = [
            state for state in policy_states if state.currentness == "current"
        ]
        if len(current_states) > 1:
            raise PlanningAttentionIntegrityError(
                "one planning policy cannot have multiple current derivations."
            )
        if current_states:
            current = current_states[0]
            if current.review_state == "none":
                pending += 1
            elif current.review_state == "unselected_history":
                selection_pending += 1
            elif current.review_state in {"selected_current", "selected_rejected"}:
                pass
            else:
                raise PlanningAttentionIntegrityError(
                    "current planning scope has impossible review state."
                )
            continue

        if any(state.review_state == "selected_stale" for state in policy_states):
            stale += 1

    items: list[MeridianAttentionItem] = []
    if pending:
        items.append(
            MeridianAttentionItem(
                code="meridian_planning_review_pending",
                count=pending,
                class_id=class_value,
            )
        )
    if selection_pending:
        items.append(
            MeridianAttentionItem(
                code="meridian_planning_review_selection_pending",
                count=selection_pending,
                class_id=class_value,
            )
        )
    if stale:
        items.append(
            MeridianAttentionItem(
                code="meridian_planning_review_stale",
                count=stale,
                class_id=class_value,
            )
        )
    return build_meridian_attention_summary(tuple(items))


def inspect_planning_attention_for_class(
    workspace_root: str | Path,
    class_id: str,
    *,
    active_school_year: str | None = None,
) -> MeridianAttentionSummary:
    """Inspect exact persisted #39 state for one class without writing."""

    class_value = _identifier(class_id, "class_id")
    school_year = _optional_school_year(active_school_year)
    root = Path(workspace_root).expanduser().resolve(strict=False)
    folder = class_folder(root, class_value)
    try:
        if folder.class_dir.is_symlink() or not folder.class_dir.is_dir():
            raise PlanningAttentionReadError(
                "requested class does not resolve to a canonical class directory."
            )
    except OSError as error:
        raise PlanningAttentionReadError(
            "requested class cannot be inspected safely."
        ) from error

    try:
        preview_ids = list_grouping_signal_preview_ids(root, class_value)
        snapshots_by_derivation: dict[str, GroupingSignalPreviewSnapshot] = {}
        policy_by_derivation: dict[str, str] = {}
        for preview_id in preview_ids:
            stored = load_grouping_signal_preview(root, class_value, preview_id)
            snapshot = stored.snapshot
            if (
                school_year is not None
                and snapshot.academic_basis.target_period.period.school_year
                != school_year
            ):
                continue
            derivation_id = snapshot.derivation_reference.derivation_id
            policy_id = snapshot.policy_reference.policy_id
            prior_policy = policy_by_derivation.get(derivation_id)
            if prior_policy is not None and prior_policy != policy_id:
                raise PlanningAttentionIntegrityError(
                    "one derivation appears under multiple planning policies."
                )
            snapshots_by_derivation.setdefault(derivation_id, snapshot)
            policy_by_derivation[derivation_id] = policy_id

        states: list[PlanningAttentionScopeState] = []
        for derivation_id in sorted(snapshots_by_derivation):
            snapshot = snapshots_by_derivation[derivation_id]
            derivation_reference = snapshot.derivation_reference
            currentness = assess_grouping_signal_derivation_currentness(
                root,
                derivation_reference,
            )
            selected = load_current_grouping_signal_review(
                root,
                class_value,
                derivation_id,
            )
            review_state: PlanningAttentionReviewState
            if selected is None:
                revisions = list_grouping_signal_review_revisions(
                    root,
                    class_value,
                    derivation_id,
                )
                review_state = "unselected_history" if revisions else "none"
            else:
                applicability = assess_grouping_signal_review_applicability(
                    selected.review,
                    currentness,
                )
                if applicability.status == "current":
                    review_state = "selected_current"
                elif applicability.status == "not_accepted":
                    review_state = "selected_rejected"
                else:
                    review_state = "selected_stale"

            states.append(
                PlanningAttentionScopeState(
                    policy_id=policy_by_derivation[derivation_id],
                    derivation_id=derivation_id,
                    currentness=currentness.state,
                    review_state=review_state,
                )
            )
    except PlanningAttentionReadError:
        raise
    except (
        OSError,
        GroupingSignalPreviewStorageError,
        GroupingSignalReviewStorageError,
        GroupingSignalCurrentnessError,
        GroupingSignalReviewError,
        ValueError,
    ) as error:
        raise PlanningAttentionReadError(
            "canonical planning state cannot be inspected safely."
        ) from error

    return build_planning_attention_summary(tuple(states), class_value)


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PlanningAttentionIntegrityError(f"{field} must be a string.")
    try:
        return validate_identifier(value, field)
    except IdentifierValidationError as error:
        raise PlanningAttentionIntegrityError(str(error)) from error


def _optional_school_year(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_school_year(value)
    except SchoolYearValidationError as error:
        raise PlanningAttentionReadError(str(error)) from error


__all__ = [
    "PlanningAttentionCurrentness",
    "PlanningAttentionError",
    "PlanningAttentionIntegrityError",
    "PlanningAttentionReadError",
    "PlanningAttentionReviewState",
    "PlanningAttentionScopeState",
    "build_planning_attention_summary",
    "inspect_planning_attention_for_class",
]
