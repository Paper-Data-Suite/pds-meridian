"""Read-only #39 preview/diagnostics stage for Create Planning Signal."""

from __future__ import annotations

from pathlib import Path

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grouping_signal_preview import (
    GroupingSignalPreviewReference,
    GroupingSignalPreviewValidationError,
)
from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
    GroupingSignalTeacherProjectionError,
    build_grouping_signal_teacher_projection,
)


class PlanningSignalPreviewDiagnosticsError(RuntimeError):
    """Base failure for the read-only #39 preview/diagnostics stage."""

    code = "teacher_workflow.create_planning_signal.preview_diagnostics_error"


class PlanningSignalPreviewDiagnosticsScopeError(
    PlanningSignalPreviewDiagnosticsError,
    ValueError,
):
    """Raised when the requested exact #39 preview scope is invalid."""

    code = "teacher_workflow.create_planning_signal.preview_diagnostics_invalid"


class PlanningSignalPreviewDiagnosticsDependencyError(
    PlanningSignalPreviewDiagnosticsError
):
    """Raised when canonical #39 projection dependencies cannot be read safely."""

    code = (
        "teacher_workflow.create_planning_signal."
        "preview_diagnostics_dependency_error"
    )


def project_planning_signal_preview_diagnostics(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
) -> GroupingSignalTeacherPreviewProjection:
    """Project one exact persisted #39 preview without writing later-stage state."""
    try:
        exact_policy_id = validate_identifier(policy_id, "policy_id")
        reference = GroupingSignalPreviewReference(
            class_id=class_id,
            preview_id=preview_id,
            preview_sha256=preview_sha256,
        )
    except (
        IdentifierValidationError,
        GroupingSignalPreviewValidationError,
        ValueError,
    ) as error:
        raise PlanningSignalPreviewDiagnosticsScopeError(str(error)) from error

    try:
        projection = build_grouping_signal_teacher_projection(
            workspace_root,
            reference,
        )
    except GroupingSignalTeacherProjectionError as error:
        raise PlanningSignalPreviewDiagnosticsDependencyError(str(error)) from error

    if projection.preview_reference != reference:
        raise PlanningSignalPreviewDiagnosticsDependencyError(
            "Canonical #39 teacher projection did not preserve the exact "
            "requested preview reference."
        )
    if projection.class_id != reference.class_id:
        raise PlanningSignalPreviewDiagnosticsDependencyError(
            "Canonical #39 teacher projection changed the requested class scope."
        )
    if projection.policy_reference.policy_id != exact_policy_id:
        raise PlanningSignalPreviewDiagnosticsScopeError(
            "Exact #39 preview is bound to a different #37 policy family."
        )
    if projection.policy_reference.class_id != reference.class_id:
        raise PlanningSignalPreviewDiagnosticsDependencyError(
            "Exact #39 preview policy provenance disagrees with its class scope."
        )
    return projection
