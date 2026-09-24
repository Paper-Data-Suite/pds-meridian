"""Teacher-facing Create Planning Signal controller for Meridian issue #57."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import NavigationChoice, parse_navigation_choice
from pds_core.workspace import WorkspaceRootError, resolve_workspace_root

from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
)
from meridian.grouping_signal_review import GroupingSignalReviewDecisionValue
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    clear_screen,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.planning_signal_core_export_commit_workflow import (
    PlanningSignalCoreExportCommitError,
    PlanningSignalCoreExportCommitResult,
    commit_planning_signal_core_export,
)
from meridian.planning_signal_core_export_preview_workflow import (
    PlanningSignalCoreExportPreview,
    PlanningSignalCoreExportPreviewError,
    preview_planning_signal_core_export,
)
from meridian.planning_signal_derivation_persistence_workflow import (
    PlanningSignalDerivationPersistenceError,
    PlanningSignalDerivationPersistencePreview,
    PlanningSignalDerivationPersistenceResult,
    commit_planning_signal_derivation_persistence_preview,
    preview_planning_signal_derivation_persistence,
)
from meridian.planning_signal_export_commit_workflow import (
    PlanningSignalExportCommitError,
    PlanningSignalExportCommitResult,
    commit_planning_signal_export,
)
from meridian.planning_signal_preview_diagnostics_workflow import (
    PlanningSignalPreviewDiagnosticsError,
    project_planning_signal_preview_diagnostics,
)
from meridian.planning_signal_preview_write_workflow import (
    PlanningSignalPreviewWriteError,
    PlanningSignalPreviewWritePreview,
    PlanningSignalPreviewWriteResult,
    commit_planning_signal_preview_write,
    preview_planning_signal_preview_write,
)
from meridian.planning_signal_review_authoring_workflow import (
    PlanningSignalReviewAuthoringError,
    PlanningSignalReviewAuthoringPreview,
    PlanningSignalReviewAuthoringResult,
    commit_planning_signal_review_authoring,
    preview_planning_signal_review_authoring,
)
from meridian.planning_signal_review_selection_workflow import (
    PlanningSignalReviewSelectionError,
    PlanningSignalReviewSelectionPreview,
    PlanningSignalReviewSelectionWorkflowResult,
    commit_planning_signal_review_selection,
    preview_planning_signal_review_selection,
)
from meridian.planning_signal_workflow import (
    PlanningSignalReadinessProjection,
    PlanningSignalWorkflowError,
    project_planning_signal_readiness,
)

WorkspaceResolver: TypeAlias = Callable[[], Path]
Clock: TypeAlias = Callable[[], datetime]
ReadinessProjector: TypeAlias = Callable[
    [Path, str, str], PlanningSignalReadinessProjection
]
DerivationPreviewer: TypeAlias = Callable[
    [PlanningSignalReadinessProjection], PlanningSignalDerivationPersistencePreview
]
DerivationCommitter: TypeAlias = Callable[
    [Path, PlanningSignalDerivationPersistencePreview],
    PlanningSignalDerivationPersistenceResult,
]
PreviewWritePreviewer: TypeAlias = Callable[
    [Path, str, str, str, str], PlanningSignalPreviewWritePreview
]
PreviewWriteCommitter: TypeAlias = Callable[
    [Path, PlanningSignalPreviewWritePreview], PlanningSignalPreviewWriteResult
]
DiagnosticsProjector: TypeAlias = Callable[
    [Path, str, str, str, str], GroupingSignalTeacherPreviewProjection
]
ReviewAuthoringPreviewer: TypeAlias = Callable[
    [
        Path,
        str,
        str,
        str,
        str,
        GroupingSignalReviewDecisionValue,
        tuple[str, ...],
        str,
        datetime,
    ],
    PlanningSignalReviewAuthoringPreview,
]
ReviewAuthoringCommitter: TypeAlias = Callable[
    [Path, PlanningSignalReviewAuthoringPreview], PlanningSignalReviewAuthoringResult
]
ReviewSelectionPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, int, str], PlanningSignalReviewSelectionPreview
]
ReviewSelectionCommitter: TypeAlias = Callable[
    [Path, PlanningSignalReviewSelectionPreview],
    PlanningSignalReviewSelectionWorkflowResult,
]
ExportPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, str, datetime], PlanningSignalCoreExportPreview
]
ExportCommitResult: TypeAlias = (
    PlanningSignalCoreExportCommitResult | PlanningSignalExportCommitResult
)
ExportCommitter: TypeAlias = Callable[
    [Path, PlanningSignalCoreExportPreview, Path | None], ExportCommitResult
]


@dataclass(frozen=True, slots=True)
class PlanningSignalMenuDependencies:
    workspace_resolver: WorkspaceResolver
    clock: Clock
    readiness_projector: ReadinessProjector
    derivation_previewer: DerivationPreviewer
    derivation_committer: DerivationCommitter
    preview_write_previewer: PreviewWritePreviewer
    preview_write_committer: PreviewWriteCommitter
    diagnostics_projector: DiagnosticsProjector
    review_authoring_previewer: ReviewAuthoringPreviewer
    review_authoring_committer: ReviewAuthoringCommitter
    review_selection_previewer: ReviewSelectionPreviewer
    review_selection_committer: ReviewSelectionCommitter
    export_previewer: ExportPreviewer
    export_committer: ExportCommitter


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _preview_review_authoring(
    root: Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
    decision: GroupingSignalReviewDecisionValue,
    acknowledged_warning_ids: tuple[str, ...],
    actor_id: str,
    reviewed_at: datetime,
) -> PlanningSignalReviewAuthoringPreview:
    if decision not in {"accepted_for_export", "rejected"}:
        raise ValueError("review decision must be accepted_for_export or rejected")
    return preview_planning_signal_review_authoring(
        root,
        class_id,
        policy_id,
        preview_id,
        preview_sha256,
        decision=decision,
        acknowledged_warning_ids=acknowledged_warning_ids,
        actor_id=actor_id,
        reviewed_at=reviewed_at,
    )


def _preview_export(
    root: Path,
    class_id: str,
    policy_id: str,
    preview_id: str,
    preview_sha256: str,
    signal_set_id: str,
    created_at: datetime,
) -> PlanningSignalCoreExportPreview:
    return preview_planning_signal_core_export(
        root,
        class_id,
        policy_id,
        preview_id,
        preview_sha256,
        signal_set_id=signal_set_id,
        created_at=created_at,
    )


def _commit_export(
    root: Path,
    preview: PlanningSignalCoreExportPreview,
    csv_destination: Path | None,
) -> ExportCommitResult:
    if csv_destination is None:
        return commit_planning_signal_core_export(root, preview)
    return commit_planning_signal_export(
        root,
        preview,
        csv_destination=csv_destination,
    )


def default_planning_signal_menu_dependencies() -> PlanningSignalMenuDependencies:
    return PlanningSignalMenuDependencies(
        workspace_resolver=resolve_workspace_root,
        clock=_utc_now,
        readiness_projector=project_planning_signal_readiness,
        derivation_previewer=preview_planning_signal_derivation_persistence,
        derivation_committer=commit_planning_signal_derivation_persistence_preview,
        preview_write_previewer=preview_planning_signal_preview_write,
        preview_write_committer=commit_planning_signal_preview_write,
        diagnostics_projector=project_planning_signal_preview_diagnostics,
        review_authoring_previewer=_preview_review_authoring,
        review_authoring_committer=commit_planning_signal_review_authoring,
        review_selection_previewer=preview_planning_signal_review_selection,
        review_selection_committer=commit_planning_signal_review_selection,
        export_previewer=_preview_export,
        export_committer=_commit_export,
    )


def _humanize(value: str) -> str:
    return value.replace("_", " ")


def _scope(input_fn: InputFunction) -> tuple[str, str] | None:
    class_id = read_choice(input_fn, "Class ID (blank to cancel): ")
    if not class_id:
        return None
    if parse_navigation_choice(class_id) is NavigationChoice.BACK:
        return None
    policy_id = read_choice(input_fn, "Grouping-signal policy ID: ")
    if not policy_id:
        return None
    return class_id, policy_id


def _preview_scope(
    input_fn: InputFunction,
) -> tuple[str, str, str, str] | None:
    scope = _scope(input_fn)
    if scope is None:
        return None
    class_id, policy_id = scope
    preview_id = read_choice(input_fn, "Planning preview ID: ")
    preview_sha256 = read_choice(input_fn, "Planning preview sha256: ")
    return class_id, policy_id, preview_id, preview_sha256


def _show_readiness(value: PlanningSignalReadinessProjection, output: TextIO) -> None:
    print_menu_header(output, "Create Planning Signal — Readiness")
    if value.policy is None:
        write_lines(
            output,
            "No grouping-signal policy is currently selected for this policy ID.",
            f"Readiness: {_humanize(value.generation_status)}",
        )
    else:
        period = value.policy.target_period.period
        write_lines(
            output,
            f"Policy: {value.policy.title}",
            f"Academic Period: {period.school_year} / {period.period_id}",
            f"Standard: {value.policy.standard_id}",
            f"Dimension: {value.policy.dimension_id}",
            f"Bands: {value.policy.band_count}",
            f"Readiness: {_humanize(value.generation_status)}",
        )
        if value.roster_student_count is not None:
            write_lines(
                output,
                (
                    "Students: "
                    f"{value.roster_student_count} rostered, "
                    f"{value.contributing_student_count or 0} contributing, "
                    f"{value.noncontributing_student_count or 0} noncontributing"
                ),
            )
    if value.blocker_codes:
        write_lines(output, "", "Needs attention:")
        for code in value.blocker_codes:
            print(f"  - {_humanize(code)}", file=output)
    write_lines(
        output,
        "",
        "This review writes no derivation, preview, review, Core signal, or CSV.",
    )


def _review_readiness(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Planning Signal Readiness")
    scope = _scope(input_fn)
    if scope is None:
        return
    class_id, policy_id = scope
    try:
        value = deps.readiness_projector(
            deps.workspace_resolver(), class_id, policy_id
        )
    except (WorkspaceRootError, PlanningSignalWorkflowError, ValueError) as error:
        write_lines(output, "", "Planning readiness could not be reviewed safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    _show_readiness(value, output)
    pause_for_user(input_fn)


def _write_derivation(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Create Planning Signal — Write Derivation")
    scope = _scope(input_fn)
    if scope is None:
        return
    class_id, policy_id = scope
    try:
        root = deps.workspace_resolver()
        readiness = deps.readiness_projector(root, class_id, policy_id)
        preview = deps.derivation_previewer(readiness)
    except (
        WorkspaceRootError,
        PlanningSignalWorkflowError,
        PlanningSignalDerivationPersistenceError,
        ValueError,
    ) as error:
        write_lines(output, "", "Derivation preview could not be prepared safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Planning Derivation Before Write")
    write_lines(
        output,
        f"Derivation ID: {preview.derivation_id}",
        f"Students: {preview.roster_student_count} rostered",
        f"Contributing: {preview.contributing_student_count}",
        f"Noncontributing: {preview.noncontributing_student_count}",
        f"Calculation fingerprint: {preview.calculation_fingerprint}",
        "",
        "Writing this immutable derivation does not create a #39 preview.",
        "Type WRITE to persist this exact derivation.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No planning derivation was written.")
        pause_for_user(input_fn)
        return
    try:
        result = deps.derivation_committer(root, preview)
    except PlanningSignalDerivationPersistenceError as error:
        write_lines(output, "", "The reviewed derivation could not be written safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Derivation write: {result.write_disposition}.",
        f"Derivation ID: {result.derivation_id}",
        f"Derivation sha256: {result.derivation_sha256}",
        "No preview, teacher review, selection, or export was performed.",
    )
    pause_for_user(input_fn)


def _write_preview(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Create Planning Signal — Write Preview")
    scope = _scope(input_fn)
    if scope is None:
        return
    class_id, policy_id = scope
    derivation_id = read_choice(input_fn, "Persisted derivation ID: ")
    derivation_sha256 = read_choice(input_fn, "Persisted derivation sha256: ")
    try:
        root = deps.workspace_resolver()
        preview = deps.preview_write_previewer(
            root,
            class_id,
            policy_id,
            derivation_id,
            derivation_sha256,
        )
    except (
        WorkspaceRootError,
        PlanningSignalPreviewWriteError,
        ValueError,
    ) as error:
        write_lines(output, "", "Planning-preview write could not be prepared safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Planning Preview Before Write")
    write_lines(
        output,
        f"Derivation ID: {preview.derivation_id}",
        f"Students: {preview.roster_student_count} rostered",
        f"Contributing: {preview.contributing_student_count}",
        f"Noncontributing: {preview.noncontributing_student_count}",
        "",
        "Writing this #39 preview does not author or select a teacher review.",
        "Type WRITE to create the canonical preview.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No planning preview was written.")
        pause_for_user(input_fn)
        return
    try:
        result = deps.preview_write_committer(root, preview)
    except PlanningSignalPreviewWriteError as error:
        write_lines(
            output,
            "",
            "The reviewed planning preview could not be written safely.",
        )
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Preview write: {result.write_disposition}.",
        f"Preview ID: {result.preview_id}",
        f"Preview sha256: {result.preview_sha256}",
        f"Currentness: {_humanize(result.currentness_state)}",
        f"Warnings: {len(result.warning_diagnostic_ids)}",
        f"Blockers: {len(result.blocking_diagnostic_ids)}",
        "No teacher review, selection, or export was performed.",
    )
    pause_for_user(input_fn)


def _show_diagnostics(
    value: GroupingSignalTeacherPreviewProjection,
    *,
    output: TextIO,
) -> None:
    print_menu_header(output, "Planning Signal Preview & Diagnostics")
    coverage = value.coverage
    write_lines(
        output,
        f"Policy: {value.policy_title}",
        f"Academic Period: {value.school_year} / {value.period_id}",
        f"Standard: {value.standard_id}",
        f"Dimension: {value.dimension_id}",
        f"Currentness: {_humanize(value.live_currentness.state)}",
        (
            "Coverage: "
            f"{coverage.roster_student_count} rostered, "
            f"{coverage.contributing_student_count} contributing, "
            f"{coverage.noncontributing_student_count} noncontributing"
        ),
        "",
        "Band distribution:",
    )
    for band in value.band_summaries:
        print(
            f"  {band.band}. {band.label}: {band.student_count} students",
            file=output,
        )
    if value.diagnostics:
        write_lines(output, "", "Diagnostics:")
        for diagnostic in value.diagnostics:
            print(
                f"  [{diagnostic.severity}] {diagnostic.diagnostic_id}: "
                f"{diagnostic.message}",
                file=output,
            )
    else:
        write_lines(output, "", "Diagnostics: none")
    review = value.review_status
    if review.decision is None:
        write_lines(output, "Selected teacher review: none")
    else:
        applicability = review.applicability
        state = "unavailable" if applicability is None else applicability.status
        write_lines(
            output,
            f"Selected teacher review: {_humanize(review.decision)}",
            f"Review applicability: {_humanize(state)}",
        )
    write_lines(output, "", "This diagnostics screen is read-only.")


def _review_diagnostics(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Review Planning Signal Preview")
    scope = _preview_scope(input_fn)
    if scope is None:
        return
    class_id, policy_id, preview_id, preview_sha256 = scope
    try:
        projection = deps.diagnostics_projector(
            deps.workspace_resolver(),
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
        )
    except (
        WorkspaceRootError,
        PlanningSignalPreviewDiagnosticsError,
        ValueError,
    ) as error:
        write_lines(output, "", "Planning diagnostics could not be reviewed safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    _show_diagnostics(projection, output=output)
    pause_for_user(input_fn)


def _review_decision(value: str) -> GroupingSignalReviewDecisionValue:
    normalized = value.strip().casefold()
    if normalized in {"accept", "accepted", "accepted_for_export"}:
        return "accepted_for_export"
    if normalized in {"reject", "rejected"}:
        return "rejected"
    raise ValueError("review decision must be accept or reject")


def _write_review(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Create Planning Signal — Write Teacher Review")
    scope = _preview_scope(input_fn)
    if scope is None:
        return
    class_id, policy_id, preview_id, preview_sha256 = scope
    try:
        root = deps.workspace_resolver()
        projection = deps.diagnostics_projector(
            root, class_id, policy_id, preview_id, preview_sha256
        )
        clear_fn()
        _show_diagnostics(projection, output=output)
        decision = _review_decision(
            read_choice(input_fn, "Review decision (accept/reject): ")
        )
        warning_ids = tuple(
            sorted(
                item.diagnostic_id
                for item in projection.diagnostics
                if item.severity == "warning"
            )
        )
        acknowledged: tuple[str, ...] = ()
        if decision == "accepted_for_export" and warning_ids:
            write_lines(
                output,
                "",
                "Acceptance requires explicit acknowledgment of every warning above.",
            )
            ack = read_choice(
                input_fn,
                "Acknowledge all listed warnings? (yes/no): ",
            ).strip().casefold()
            if ack not in {"yes", "y"}:
                write_lines(output, "", "Teacher review was not authored.")
                pause_for_user(input_fn)
                return
            acknowledged = warning_ids
        actor_id = read_choice(input_fn, "Teacher actor ID: ")
        reviewed_at = deps.clock()
        preview = deps.review_authoring_previewer(
            root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
            decision,
            acknowledged,
            actor_id,
            reviewed_at,
        )
    except (
        WorkspaceRootError,
        PlanningSignalPreviewDiagnosticsError,
        PlanningSignalReviewAuthoringError,
        ValueError,
    ) as error:
        write_lines(output, "", "Teacher-review preview could not be prepared safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Teacher Decision Before Write")
    write_lines(
        output,
        f"Decision: {_humanize(preview.decision)}",
        f"Review revision: {preview.review_revision}",
        f"Warnings acknowledged: {len(preview.acknowledged_warning_ids)}",
        f"Blocking diagnostics: {len(preview.blocking_diagnostic_ids)}",
        f"Teacher: {preview.actor_id}",
        f"Reviewed at: {preview.reviewed_at.isoformat()}",
        (
            "Current selected review revision: none"
            if preview.expected_current_review_revision is None
            else (
                "Current selected review revision: "
                f"{preview.expected_current_review_revision}"
            )
        ),
        "",
        "Writing this immutable review will NOT select it.",
        "Type WRITE to create this exact review revision.",
    )
    if read_choice(input_fn, "Confirmation: ") != "WRITE":
        write_lines(output, "", "No teacher-review revision was written.")
        pause_for_user(input_fn)
        return
    try:
        result = deps.review_authoring_committer(root, preview)
    except PlanningSignalReviewAuthoringError as error:
        write_lines(
            output,
            "",
            "The reviewed teacher decision could not be written safely.",
        )
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Review write: {result.write_disposition}.",
        f"Review revision: {result.review_revision}",
        f"Review sha256: {result.review_sha256}",
        f"Decision: {_humanize(result.decision)}",
        "Current review selection was not changed.",
    )
    pause_for_user(input_fn)


def _select_review(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Create Planning Signal — Select Teacher Review")
    scope = _preview_scope(input_fn)
    if scope is None:
        return
    class_id, policy_id, preview_id, preview_sha256 = scope
    try:
        revision = int(read_choice(input_fn, "Review revision to select: "))
        if revision < 1:
            raise ValueError("review revision must be a positive integer")
        review_sha256 = read_choice(input_fn, "Review sha256: ")
        root = deps.workspace_resolver()
        preview = deps.review_selection_previewer(
            root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
            revision,
            review_sha256,
        )
    except (
        WorkspaceRootError,
        PlanningSignalReviewSelectionError,
        ValueError,
    ) as error:
        write_lines(
            output,
            "",
            "Review-selection preview could not be prepared safely.",
        )
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Teacher-Review Selection")
    write_lines(
        output,
        f"Target review revision: {preview.target_review_revision}",
        f"Target decision: {_humanize(preview.target_decision)}",
        f"Target applicability: {_humanize(preview.target_applicability.status)}",
        f"Target review sha256: {preview.target_review_sha256}",
        (
            "Current selected review revision: none"
            if preview.expected_current_review_revision is None
            else (
                "Current selected review revision: "
                f"{preview.expected_current_review_revision}"
            )
        ),
        "",
        "Type SELECT to make this exact review revision current.",
    )
    if read_choice(input_fn, "Confirmation: ") != "SELECT":
        write_lines(output, "", "Current teacher-review selection was not changed.")
        pause_for_user(input_fn)
        return
    try:
        result = deps.review_selection_committer(root, preview)
    except PlanningSignalReviewSelectionError as error:
        write_lines(
            output,
            "",
            (
                "The reviewed teacher-review selection could not be "
                "committed safely."
            ),
        )
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    write_lines(
        output,
        "",
        f"Review selection: {result.selection_disposition}.",
        f"Selected revision: {result.selected_review_revision}",
        f"Selected decision: {_humanize(result.selected_decision)}",
        "No Core signal or CSV was exported.",
    )
    pause_for_user(input_fn)


def _export_signal(
    *,
    deps: PlanningSignalMenuDependencies,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
) -> None:
    clear_fn()
    print_menu_header(output, "Create Planning Signal — Export")
    scope = _preview_scope(input_fn)
    if scope is None:
        return
    class_id, policy_id, preview_id, preview_sha256 = scope
    signal_set_id = read_choice(input_fn, "Core signal-set ID: ")
    csv_text = read_choice(
        input_fn,
        "Optional CSV destination (blank for no CSV): ",
    )
    csv_destination = None if not csv_text else Path(csv_text)
    created_at = deps.clock()
    try:
        root = deps.workspace_resolver()
        preview = deps.export_previewer(
            root,
            class_id,
            policy_id,
            preview_id,
            preview_sha256,
            signal_set_id,
            created_at,
        )
    except (
        WorkspaceRootError,
        PlanningSignalCoreExportPreviewError,
        ValueError,
    ) as error:
        write_lines(output, "", "Core export preview could not be prepared safely.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    clear_fn()
    print_menu_header(output, "Review Planning Signal Export")
    write_lines(
        output,
        f"Core signal-set ID: {preview.signal_set.signal_set_id}",
        f"Created at: {preview.signal_set.created_at.isoformat()}",
        f"Contributing students: {len(preview.contributing_student_ids)}",
        f"Noncontributing students: {len(preview.noncontributing_student_ids)}",
        (
            "CSV: none"
            if csv_destination is None
            else f"CSV destination: {csv_destination}"
        ),
        "",
        "Final live review/currentness revalidation will run before Core write.",
        "Export does not create Concord grouping state.",
        "Type EXPORT to commit this exact Core signal and Meridian receipt.",
    )
    if read_choice(input_fn, "Confirmation: ") != "EXPORT":
        write_lines(output, "", "No Core signal, receipt, or CSV was written.")
        pause_for_user(input_fn)
        return
    try:
        result = deps.export_committer(root, preview, csv_destination)
    except (
        PlanningSignalCoreExportCommitError,
        PlanningSignalExportCommitError,
    ) as error:
        write_lines(output, "", "Planning-signal export did not complete cleanly.")
        write_lines(output, f"Details: {error}")
        pause_for_user(input_fn)
        return
    core = (
        result.core
        if isinstance(result, PlanningSignalExportCommitResult)
        else result
    )
    write_lines(
        output,
        "",
        f"Core signal write: {core.core_write_disposition}.",
        f"Meridian receipt write: {core.receipt_write_disposition}.",
        f"Core signal digest: {core.core_signal_digest}",
        f"Receipt sha256: {core.receipt_sha256}",
    )
    if isinstance(result, PlanningSignalExportCommitResult) and result.csv is not None:
        write_lines(
            output,
            f"CSV export: {result.csv.disposition}.",
            f"CSV destination: {result.csv.destination}",
            f"CSV sha256: {result.csv.csv_sha256}",
        )
    write_lines(output, "No Concord state was created.")
    pause_for_user(input_fn)


def run_planning_signal_menu(
    *,
    dependencies: PlanningSignalMenuDependencies | None = None,
    input_fn: InputFunction = input,
    output: TextIO | None = None,
    clear_fn: ClearFunction = clear_screen,
) -> None:
    stream = sys.stdout if output is None else output
    deps = dependencies or default_planning_signal_menu_dependencies()
    while True:
        clear_fn()
        print_menu_header(stream, "Create Planning Signal")
        write_lines(
            stream,
            "1. Review readiness",
            "2. Write exact derivation",
            "3. Write planning preview",
            "4. Review preview and diagnostics",
            "5. Write teacher review",
            "6. Select teacher review",
            "7. Export accepted signal to Core",
            "",
            "Each write, selection, and export is a separate confirmation.",
            "No step creates Concord grouping state.",
            "",
        )
        print_standard_navigation(stream)
        choice = read_choice(input_fn)
        nav = parse_navigation_choice(choice)
        if nav is NavigationChoice.BACK or choice == "":
            return
        if choice == "1":
            _review_readiness(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "2":
            _write_derivation(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "3":
            _write_preview(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "4":
            _review_diagnostics(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "5":
            _write_review(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "6":
            _select_review(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        if choice == "7":
            _export_signal(
                deps=deps, input_fn=input_fn, output=stream, clear_fn=clear_fn
            )
            continue
        write_lines(stream, "", "Please choose 1-7, B, M, or Q.")
        pause_for_user(input_fn)
