"""Read-only #39 currentness assessment for exact #38 derivations."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
    GroupingSignalDerivationSnapshot,
    grouping_signal_derivation_reference,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_generation import (
    GroupingSignalGenerationError,
    resolve_current_grouping_signal_derivation,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewCurrentness

_STALE_REASON_ORDER: Final[tuple[str, ...]] = (
    "algorithm_changed",
    "policy_selection_changed",
    "roster_membership_changed",
    "source_result_reference_changed",
    "source_proficiency_changed",
    "source_resolution_changed",
)


class GroupingSignalCurrentnessError(RuntimeError):
    """Base error for read-only grouping-signal currentness assessment."""


class GroupingSignalCurrentnessReadError(GroupingSignalCurrentnessError):
    """Raised when exact source/current state cannot be read safely."""


def assess_grouping_signal_derivation_currentness(
    workspace_root: str | Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> GroupingSignalPreviewCurrentness:
    """Assess one exact #38 derivation against current state without writing."""
    if not isinstance(derivation_reference, GroupingSignalDerivationReference):
        raise GroupingSignalCurrentnessReadError(
            "derivation_reference must be an exact #38 reference."
        )
    derivation_reference.__post_init__()

    try:
        stored = load_grouping_signal_derivation_reference(
            workspace_root,
            derivation_reference,
        )
    except GroupingSignalDerivationStorageError as error:
        raise GroupingSignalCurrentnessReadError(
            "Could not load the exact #38 derivation for currentness assessment."
        ) from error

    source = stored.snapshot
    try:
        candidate = resolve_current_grouping_signal_derivation(
            workspace_root,
            source.class_id,
            source.policy_reference.policy_id,
        )
    except GroupingSignalGenerationError as error:
        raise GroupingSignalCurrentnessReadError(
            "Could not resolve the current #38 generation state."
        ) from error

    if candidate.status == "blocked":
        reason_codes = tuple(sorted({item.code for item in candidate.blockers}))
        return GroupingSignalPreviewCurrentness(
            "blocked",
            reason_codes,
            None,
        )

    current_snapshot = candidate.snapshot
    if current_snapshot is None:
        raise GroupingSignalCurrentnessReadError(
            "Generated currentness candidate is unexpectedly absent."
        )
    current_reference = grouping_signal_derivation_reference(current_snapshot)
    if current_reference == derivation_reference:
        return GroupingSignalPreviewCurrentness(
            "current",
            (),
            derivation_reference,
        )

    return GroupingSignalPreviewCurrentness(
        "stale",
        _stale_reasons(source, current_snapshot),
        current_reference,
    )


def grouping_signal_derivation_stale_reasons(
    source: GroupingSignalDerivationSnapshot,
    current: GroupingSignalDerivationSnapshot,
) -> tuple[str, ...]:
    """Return deterministic semantic differences between two valid snapshots."""
    if not isinstance(source, GroupingSignalDerivationSnapshot):
        raise GroupingSignalCurrentnessReadError(
            "source must be a GroupingSignalDerivationSnapshot."
        )
    if not isinstance(current, GroupingSignalDerivationSnapshot):
        raise GroupingSignalCurrentnessReadError(
            "current must be a GroupingSignalDerivationSnapshot."
        )
    source.__post_init__()
    current.__post_init__()
    if source.class_id != current.class_id:
        raise GroupingSignalCurrentnessReadError(
            "currentness comparison cannot cross class scope."
        )
    return _stale_reasons(source, current)


def _stale_reasons(
    source: GroupingSignalDerivationSnapshot,
    current: GroupingSignalDerivationSnapshot,
) -> tuple[str, ...]:
    reasons: set[str] = set()

    if source.algorithm_version != current.algorithm_version:
        reasons.add("algorithm_changed")
    if source.policy_reference != current.policy_reference:
        reasons.add("policy_selection_changed")
    if source.roster_basis != current.roster_basis:
        reasons.add("roster_membership_changed")

    source_by_student = {
        item.student_id: item for item in source.student_derivations
    }
    current_by_student = {
        item.student_id: item for item in current.student_derivations
    }
    if set(source_by_student) != set(current_by_student):
        reasons.add("source_resolution_changed")

    for student_id in sorted(set(source_by_student) & set(current_by_student)):
        before = source_by_student[student_id]
        after = current_by_student[student_id]
        if before.source_result != after.source_result:
            reasons.add("source_result_reference_changed")
        if (
            before.proficiency_level_id != after.proficiency_level_id
            or before.scale_position != after.scale_position
            or before.band != after.band
        ):
            reasons.add("source_proficiency_changed")
        if (
            before.source_state != after.source_state
            or before.disposition != after.disposition
        ):
            reasons.add("source_resolution_changed")

    if (
        source.calculation_fingerprint != current.calculation_fingerprint
        and not reasons
    ):
        reasons.add("source_resolution_changed")

    return tuple(
        reason for reason in _STALE_REASON_ORDER if reason in reasons
    )
