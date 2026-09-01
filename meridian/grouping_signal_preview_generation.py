"""Workspace orchestration for immutable #39 grouping-signal previews.

This module resolves one explicit #38 derivation, its exact bound #37 policy
revision and academic dependencies, assesses #38 currentness read-only, builds
one deterministic preview, and persists only that preview.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    load_grouping_signal_policy_revision,
    validate_grouping_signal_policy_dependencies,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewError,
    build_grouping_signal_preview_snapshot,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    GroupingSignalPreviewWriteDisposition,
    StoredGroupingSignalPreview,
    write_grouping_signal_preview,
)


class GroupingSignalPreviewGenerationError(RuntimeError):
    """Base error for workspace-level preview generation."""


class GroupingSignalPreviewGenerationReadError(
    GroupingSignalPreviewGenerationError
):
    """Raised when exact derivation/policy/current state cannot be read safely."""


class GroupingSignalPreviewGenerationValidationError(
    GroupingSignalPreviewGenerationError,
    ValueError,
):
    """Raised when exact preview inputs disagree."""


@dataclass(frozen=True, slots=True)
class GroupingSignalPreviewGenerationResult:
    """One persisted immutable preview and its write disposition."""

    stored: StoredGroupingSignalPreview
    write_disposition: GroupingSignalPreviewWriteDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.stored, StoredGroupingSignalPreview):
            raise GroupingSignalPreviewGenerationValidationError(
                "stored must be a StoredGroupingSignalPreview."
            )
        if self.write_disposition not in {"created", "existing"}:
            raise GroupingSignalPreviewGenerationValidationError(
                "write_disposition must be created or existing."
            )


def generate_grouping_signal_preview(
    workspace_root: str | Path,
    derivation_reference: GroupingSignalDerivationReference,
) -> GroupingSignalPreviewGenerationResult:
    """Build/persist one preview for an explicit exact #38 derivation reference."""

    if not isinstance(derivation_reference, GroupingSignalDerivationReference):
        raise GroupingSignalPreviewGenerationValidationError(
            "derivation_reference must be an exact #38 reference."
        )
    derivation_reference.__post_init__()

    try:
        stored_derivation = load_grouping_signal_derivation_reference(
            workspace_root,
            derivation_reference,
        )
    except GroupingSignalDerivationStorageError as error:
        raise GroupingSignalPreviewGenerationReadError(
            "Could not load the exact requested #38 derivation."
        ) from error

    bound_policy = stored_derivation.snapshot.policy_reference
    try:
        stored_policy = load_grouping_signal_policy_revision(
            workspace_root,
            bound_policy.class_id,
            bound_policy.policy_id,
            bound_policy.policy_revision,
        )
    except GroupingSignalPolicyStorageError as error:
        raise GroupingSignalPreviewGenerationReadError(
            "Could not load the exact #37 policy bound by the derivation."
        ) from error
    if stored_policy.reference != bound_policy:
        raise GroupingSignalPreviewGenerationReadError(
            "Stored #37 policy digest does not match derivation provenance."
        )

    try:
        dependencies = validate_grouping_signal_policy_dependencies(
            workspace_root,
            stored_policy.policy,
        )
    except GroupingSignalPolicyStorageError as error:
        raise GroupingSignalPreviewGenerationReadError(
            "Could not verify the exact academic dependencies for the preview."
        ) from error

    try:
        currentness = assess_grouping_signal_derivation_currentness(
            workspace_root,
            derivation_reference,
        )
    except GroupingSignalCurrentnessError as error:
        raise GroupingSignalPreviewGenerationReadError(
            "Could not assess derivation currentness."
        ) from error

    try:
        preview = build_grouping_signal_preview_snapshot(
            stored_derivation.snapshot,
            stored_policy.policy,
            dependencies.target_scale.scale,
            currentness,
        )
        written = write_grouping_signal_preview(workspace_root, preview)
    except GroupingSignalPreviewStorageError as error:
        raise GroupingSignalPreviewGenerationReadError(
            "Could not persist the immutable grouping-signal preview."
        ) from error
    except GroupingSignalPreviewError as error:
        raise GroupingSignalPreviewGenerationValidationError(
            str(error)
        ) from error

    return GroupingSignalPreviewGenerationResult(
        stored=written.stored,
        write_disposition=written.disposition,
    )
