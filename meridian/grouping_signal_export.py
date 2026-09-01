"""Pure projection from one exact #38 derivation into Core grouping_signal_set_v1.

This module owns only Meridian's semantic projection boundary for issue #40.
It does not resolve review state, assess currentness, write Core exchange state,
persist an export receipt, export CSV, or interact with Concord.
"""

from __future__ import annotations

from datetime import datetime

from pds_core.grouping_signals import (
    GROUPING_SIGNAL_RECORD_TYPE,
    GROUPING_SIGNAL_SCHEMA_VERSION,
    GroupingSignalDimension,
    GroupingSignalSet,
    GroupingSignalSource,
    GroupingSignalStudentBand,
    GroupingSignalValidationError,
    validate_grouping_signal_set,
)

from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationSnapshot,
    GroupingSignalDerivationValidationError,
    grouping_signal_derivation_reference,
    validate_grouping_signal_derivation_snapshot,
)


class GroupingSignalExportProjectionError(ValueError):
    """Raised when an exact #38 derivation cannot form a valid Core signal."""


class GroupingSignalExportZeroContributorsError(GroupingSignalExportProjectionError):
    """Raised when Core v1 cannot represent an all-noncontributing derivation."""


def build_grouping_signal_export_candidate(
    derivation: GroupingSignalDerivationSnapshot,
    *,
    signal_set_id: str,
    created_at: datetime,
) -> GroupingSignalSet:
    """Project one exact immutable #38 derivation into a Core signal candidate.

    The returned value is validated Core ``grouping_signal_set_v1`` state only.
    This function is pure: it does not write Core exchange storage or any
    Meridian-owned export state.
    """

    try:
        exact_derivation = validate_grouping_signal_derivation_snapshot(
            derivation
        )
        derivation_reference = grouping_signal_derivation_reference(
            exact_derivation
        )
    except GroupingSignalDerivationValidationError as error:
        raise GroupingSignalExportProjectionError(
            f"Grouping-signal derivation is invalid: {error}"
        ) from error

    student_bands = tuple(
        GroupingSignalStudentBand(
            student_id=item.student_id,
            dimension_id=exact_derivation.dimension_id,
            band=_contributing_band(item.band),
        )
        for item in exact_derivation.student_derivations
        if item.disposition == "contributing"
    )
    if not student_bands:
        raise GroupingSignalExportZeroContributorsError(
            "Core grouping_signal_set_v1 requires at least one contributing "
            "student band; the exact #38 derivation has zero contributors."
        )

    try:
        candidate = GroupingSignalSet(
            schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
            record_type=GROUPING_SIGNAL_RECORD_TYPE,
            signal_set_id=signal_set_id,
            class_id=exact_derivation.class_id,
            created_at=created_at,
            source=GroupingSignalSource(
                kind="module_generated",
                module_id="meridian",
                snapshot_id=derivation_reference.derivation_id,
                snapshot_digest_algorithm="sha256",
                snapshot_digest=derivation_reference.derivation_sha256,
            ),
            dimensions=(
                GroupingSignalDimension(
                    dimension_id=exact_derivation.dimension_id,
                    band_count=exact_derivation.band_count,
                ),
            ),
            student_bands=student_bands,
        )
        return validate_grouping_signal_set(candidate)
    except (GroupingSignalValidationError, TypeError, ValueError) as error:
        raise GroupingSignalExportProjectionError(
            f"Core grouping-signal projection is invalid: {error}"
        ) from error


def _contributing_band(value: int | None) -> int:
    if value is None:
        raise GroupingSignalExportProjectionError(
            "Contributing #38 student derivation is missing its exact band."
        )
    return value
