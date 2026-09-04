"""Read-only #40 Core export preview for Create Planning Signal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pds_core.grouping_signals import GroupingSignalSet
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_export import (
    GroupingSignalExportProjectionError,
    build_grouping_signal_export_candidate,
)
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockCode,
    GroupingSignalExportBlockedError,
    GroupingSignalExportEligibility,
    GroupingSignalExportEligibilityError,
    resolve_grouping_signal_export_eligibility,
    revalidate_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
)
from meridian.planning_signal_preview_diagnostics_workflow import (
    PlanningSignalPreviewDiagnosticsError,
    PlanningSignalPreviewDiagnosticsScopeError,
    project_planning_signal_preview_diagnostics,
)


class PlanningSignalCoreExportPreviewError(RuntimeError):
    """Base failure for the read-only #40 Core export preview stage."""

    code = "teacher_workflow.create_planning_signal.core_export_preview_error"


class PlanningSignalCoreExportPreviewScopeError(
    PlanningSignalCoreExportPreviewError,
    ValueError,
):
    """Raised when the requested exact export-preview scope is invalid."""

    code = "teacher_workflow.create_planning_signal.core_export_preview_invalid"


class PlanningSignalCoreExportPreviewAuthorizationError(
    PlanningSignalCoreExportPreviewError
):
    """Raised when selected #39 review state does not authorize export."""

    code = (
        "teacher_workflow.create_planning_signal."
        "core_export_preview_not_authorized"
    )

    block_code: GroupingSignalExportBlockCode | None
    reason_codes: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        block_code: GroupingSignalExportBlockCode | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self.block_code = block_code
        self.reason_codes = tuple(sorted(set(reason_codes)))
        super().__init__(message)


class PlanningSignalCoreExportPreviewDependencyError(
    PlanningSignalCoreExportPreviewError
):
    """Raised when exact #38/#39/Core candidate state cannot be read safely."""

    code = (
        "teacher_workflow.create_planning_signal."
        "core_export_preview_dependency_error"
    )


class PlanningSignalCoreExportPreviewStaleError(
    PlanningSignalCoreExportPreviewError
):
    """Raised when export authorization changes while the preview is assembled."""

    code = "teacher_workflow.create_planning_signal.core_export_preview_stale"

    block_code: GroupingSignalExportBlockCode | None
    reason_codes: tuple[str, ...]

    def __init__(
        self,
        message: str,
        *,
        block_code: GroupingSignalExportBlockCode | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        self.block_code = block_code
        self.reason_codes = tuple(sorted(set(reason_codes)))
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PlanningSignalCoreExportPreview:
    """Exact authorized Core candidate with no persistence side effect."""

    projection: GroupingSignalTeacherPreviewProjection
    eligibility: GroupingSignalExportEligibility
    signal_set: GroupingSignalSet

    def __post_init__(self) -> None:
        if not isinstance(self.projection, GroupingSignalTeacherPreviewProjection):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "projection must be an exact #39 teacher preview projection."
            )
        if not isinstance(self.eligibility, GroupingSignalExportEligibility):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "eligibility must be canonical #40 export authorization."
            )
        self.eligibility.__post_init__()
        if not isinstance(self.signal_set, GroupingSignalSet):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "signal_set must be a validated Core grouping_signal_set_v1 candidate."
            )

        if self.projection.preview_reference != self.eligibility.preview_reference:
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Teacher projection and export authorization disagree on the exact "
                "#39 preview."
            )
        if (
            self.projection.derivation_reference
            != self.eligibility.derivation_reference
        ):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Teacher projection and export authorization disagree on the exact "
                "#38 derivation."
            )
        if (
            self.projection.review_status.selected_review_reference
            != self.eligibility.review_reference
        ):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Teacher projection and export authorization disagree on the exact "
                "selected #39 review."
            )
        applicability = self.projection.review_status.applicability
        if (
            self.projection.review_status.decision != "accepted_for_export"
            or applicability is None
            or applicability.status != "current"
        ):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Export preview requires the projected selected review to be "
                "accepted_for_export and current."
            )

        if self.signal_set.class_id != self.projection.class_id:
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Core candidate changed the authorized class scope."
            )
        if (
            self.signal_set.source.module_id != "meridian"
            or self.signal_set.source.snapshot_id
            != self.eligibility.derivation_reference.derivation_id
            or self.signal_set.source.snapshot_digest
            != self.eligibility.derivation_reference.derivation_sha256
        ):
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Core candidate does not bind the exact authorized #38 derivation."
            )

        candidate_students = tuple(
            sorted(item.student_id for item in self.signal_set.student_bands)
        )
        projected_students = tuple(
            sorted(
                row.student_id
                for row in self.projection.student_assignments
                if row.disposition == "contributing"
            )
        )
        if candidate_students != projected_students:
            raise PlanningSignalCoreExportPreviewDependencyError(
                "Core candidate contributors differ from the accepted #39 preview."
            )

    @property
    def contributing_student_ids(self) -> tuple[str, ...]:
        return tuple(sorted(item.student_id for item in self.signal_set.student_bands))

    @property
    def noncontributing_student_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(item.student_id for item in self.projection.noncontributing_students)
        )

    @property
    def final_core_revalidation_required(self) -> bool:
        return True

    @property
    def review_write_action(self) -> str:
        return "not_performed"

    @property
    def review_selection_action(self) -> str:
        return "not_performed"

    @property
    def core_export_action(self) -> str:
        return "not_performed"

    @property
    def export_receipt_action(self) -> str:
        return "not_performed"

    @property
    def csv_export_action(self) -> str:
        return "not_performed"


def preview_planning_signal_core_export(
    workspace_root: str | Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
    *,
    signal_set_id: str,
    created_at: datetime,
) -> PlanningSignalCoreExportPreview:
    """Build an exact authorized Core candidate without writing export state."""
    try:
        exact_signal_set_id = validate_identifier(signal_set_id, "signal_set_id")
    except IdentifierValidationError as error:
        raise PlanningSignalCoreExportPreviewScopeError(str(error)) from error
    if (
        not isinstance(created_at, datetime)
        or created_at.tzinfo is None
        or created_at.utcoffset() is None
    ):
        raise PlanningSignalCoreExportPreviewScopeError(
            "created_at must be an explicit timezone-aware datetime."
        )

    try:
        projection = project_planning_signal_preview_diagnostics(
            workspace_root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
        )
    except PlanningSignalPreviewDiagnosticsScopeError as error:
        raise PlanningSignalCoreExportPreviewScopeError(str(error)) from error
    except PlanningSignalPreviewDiagnosticsError as error:
        raise PlanningSignalCoreExportPreviewDependencyError(str(error)) from error

    try:
        eligibility = resolve_grouping_signal_export_eligibility(
            workspace_root,
            projection.class_id,
            projection.derivation_reference.derivation_id,
        )
    except GroupingSignalExportBlockedError as error:
        raise PlanningSignalCoreExportPreviewAuthorizationError(
            str(error),
            block_code=error.code,
            reason_codes=error.reason_codes,
        ) from error
    except GroupingSignalExportEligibilityError as error:
        raise PlanningSignalCoreExportPreviewDependencyError(str(error)) from error

    if eligibility.preview_reference != projection.preview_reference:
        raise PlanningSignalCoreExportPreviewAuthorizationError(
            "The explicitly selected accepted review authorizes a different exact "
            "#39 preview than the one requested for export."
        )
    if eligibility.derivation_reference != projection.derivation_reference:
        raise PlanningSignalCoreExportPreviewDependencyError(
            "Selected review authorization changed the exact #38 derivation scope."
        )
    if (
        projection.review_status.selected_review_reference
        != eligibility.review_reference
    ):
        raise PlanningSignalCoreExportPreviewStaleError(
            "Selected #39 review changed while assembling the export preview."
        )

    try:
        stored_derivation = load_grouping_signal_derivation_reference(
            workspace_root,
            eligibility.derivation_reference,
        )
    except GroupingSignalDerivationStorageError as error:
        raise PlanningSignalCoreExportPreviewDependencyError(
            "Could not load the exact authorized #38 derivation for export preview."
        ) from error

    try:
        candidate = build_grouping_signal_export_candidate(
            stored_derivation.snapshot,
            signal_set_id=exact_signal_set_id,
            created_at=created_at,
        )
    except GroupingSignalExportProjectionError as error:
        raise PlanningSignalCoreExportPreviewDependencyError(str(error)) from error

    try:
        final_eligibility = revalidate_grouping_signal_export_eligibility(
            workspace_root,
            eligibility,
        )
    except GroupingSignalExportBlockedError as error:
        raise PlanningSignalCoreExportPreviewStaleError(
            str(error),
            block_code=error.code,
            reason_codes=error.reason_codes,
        ) from error
    except GroupingSignalExportEligibilityError as error:
        raise PlanningSignalCoreExportPreviewDependencyError(str(error)) from error

    if final_eligibility != eligibility:
        raise PlanningSignalCoreExportPreviewStaleError(
            "Exact #40 export authorization changed while assembling the preview."
        )

    return PlanningSignalCoreExportPreview(
        projection=projection,
        eligibility=final_eligibility,
        signal_set=candidate,
    )
