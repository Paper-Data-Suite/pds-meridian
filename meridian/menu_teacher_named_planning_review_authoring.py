"""Teacher-named, deliberate authoring of an immutable Planning Review (#123 10E).

Selection is transient and read-only. The existing #39 review-authoring service
owns freshness, revision history, warning acknowledgment, and the write.
Authoring never makes a review current and never exports or forms groups.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.menu_teacher_named_explain_preview_review import (
    PlanningPreviewChoiceCatalog,
    PlanningPreviewSummary,
)
from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_planning_diagnostics import (
    _checked_projection,
    _DiagnosticsChanged,
)
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.grouping_signal_preview_projection import (
        GroupingSignalTeacherPreviewProjection,
    )
    from meridian.planning_signal_review_authoring_workflow import (
        PlanningSignalReviewAuthoringPreview,
        PlanningSignalReviewAuthoringResult,
    )

ReviewDecision: TypeAlias = Literal["accepted_for_export", "rejected"]
DiagnosticsProjector: TypeAlias = Callable[
    [Path, str, str, str, str], "GroupingSignalTeacherPreviewProjection"
]
AuthoringPreviewer: TypeAlias = Callable[
    [Path, str, str, str, str, ReviewDecision, tuple[str, ...], str, datetime],
    "PlanningSignalReviewAuthoringPreview",
]
AuthoringCommitter: TypeAlias = Callable[
    [Path, "PlanningSignalReviewAuthoringPreview"],
    "PlanningSignalReviewAuthoringResult",
]
Clock: TypeAlias = Callable[[], datetime]

# Main-menu TeacherAttributionInput supplies verified identity for this exact
# established prompt. Direct legacy callers retain explicit attribution.
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class _ReviewChanged(RuntimeError):
    """The selected preview, authoring candidate, or saved result is inconsistent."""


def _check_candidate(
    preview: PlanningSignalReviewAuthoringPreview,
    projection: GroupingSignalTeacherPreviewProjection,
    summary: PlanningPreviewSummary,
    class_id: str,
    decision: ReviewDecision,
    acknowledgments: tuple[str, ...],
    actor_id: str,
) -> None:
    """Prove an injected/service preview binds the exact teacher-reviewed intent."""
    _checked_projection(preview.projection, summary, class_id)
    candidate = preview.candidate
    reference = candidate.preview_reference
    derivation = candidate.derivation_reference
    if (
        preview.projection != projection
        or preview.class_id != class_id
        or candidate.class_id != class_id
        or preview.derivation_id != summary.derivation_id
        or reference.class_id != class_id
        or reference.preview_id != summary.preview_id
        or reference.preview_sha256 != summary.preview_sha256
        or derivation.class_id != class_id
        or derivation.derivation_id != summary.derivation_id
        or derivation.derivation_sha256 != summary.derivation_sha256
        or preview.decision != decision
        or candidate.decision != decision
        or preview.acknowledged_warning_ids != acknowledgments
        or candidate.acknowledged_warning_ids != acknowledgments
        or preview.actor_id != actor_id
        or candidate.actor.actor_id != actor_id
        or candidate.actor.kind != "teacher"
        or preview.review_revision != candidate.review_revision
        or type(candidate.review_revision) is not int
        or candidate.review_revision < 1
        or candidate.supersedes_revision
        != (None if candidate.review_revision == 1 else candidate.review_revision - 1)
        or preview.expected_current_review_revision != summary.selected_review_revision
        or preview.blocking_diagnostic_ids
        != tuple(
            sorted(
                d.diagnostic_id
                for d in projection.diagnostics
                if d.severity == "blocking"
            )
        )
        or preview.warning_diagnostic_ids
        != tuple(
            sorted(
                d.diagnostic_id
                for d in projection.diagnostics
                if d.severity == "warning"
            )
        )
        or preview.reviewed_at != candidate.reviewed_at
    ):
        raise _ReviewChanged("Review candidate differs from the named selection.")
    if decision == "accepted_for_export" and (
        projection.live_currentness.state != "current"
        or projection.live_currentness.current_derivation_reference
        != projection.derivation_reference
        or preview.blocking_diagnostic_ids
    ):
        raise _ReviewChanged("Cannot accept a non-current or blocked preview.")


def _check_result(
    result: PlanningSignalReviewAuthoringResult,
    preview: PlanningSignalReviewAuthoringPreview,
) -> None:
    if (
        result.preview != preview
        or result.review_revision != preview.review_revision
        or result.decision != preview.decision
        or result.write_disposition not in {"created", "existing"}
        or not isinstance(result.review_sha256, str)
        or _SHA256.fullmatch(result.review_sha256) is None
        or result.review_selection_action != "not_performed"
        or result.core_export_action != "not_performed"
        or result.csv_export_action != "not_performed"
        or result.selection_changed_during_write
    ):
        raise _ReviewChanged("Persisted review result is inconsistent.")


def run_named_planning_review_authoring(
    *,
    navigation: TeacherNavigationContext,
    diagnostics_projector: DiagnosticsProjector,
    authoring_previewer: AuthoringPreviewer,
    authoring_committer: AuthoringCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    preview_catalog: PlanningPreviewChoiceCatalog | None = None,
) -> None:
    """Choose a saved preview by name, review decision, WRITE only its review."""
    attempted = False
    try:
        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        catalog = preview_catalog or PlanningPreviewChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified = navigation.current_class()
        if (
            verified is None
            or verified.workspace != root
            or verified.class_id != class_id
        ):
            raise _ReviewChanged("Verified class context changed.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_preview_review",
            selected={"class": class_id},
            title="Saved Planning Previews",
            question="Which saved Planning Preview should receive a teacher review?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return

        def check_scope() -> PlanningPreviewSummary:
            if navigation.current_class() != verified:
                raise _ReviewChanged("Selected class changed.")
            _current_choice(
                catalog,
                scope="planning_preview_review",
                selected={"class": class_id},
                choice=chosen,
            )
            if len(chosen.identity) != 1:
                raise _ReviewChanged("Invalid saved preview identity.")
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != chosen
            ):
                raise _ReviewChanged("Saved preview or selected review changed.")
            return current

        summary = check_scope()
        projection = diagnostics_projector(
            root,
            class_id,
            summary.policy_id,
            summary.preview_id,
            summary.preview_sha256,
        )
        _checked_projection(projection, summary, class_id)
        if check_scope() != summary:
            raise _ReviewChanged("Selected preview changed during projection.")
        warnings = tuple(
            sorted(
                item.diagnostic_id
                for item in projection.diagnostics
                if item.severity == "warning"
            )
        )
        blockers = tuple(
            sorted(
                item.diagnostic_id
                for item in projection.diagnostics
                if item.severity == "blocking"
            )
        )
        clear_fn()
        print_menu_header(output, "Teacher Planning Review — Inspect Preview")
        write_lines(
            output,
            f"Policy: {summary.title}",
            f"Marking period: {summary.period_label} ({summary.school_year})",
            f"Standard: {summary.standard_id}",
            f"Students: {projection.coverage.roster_student_count} rostered, "
            f"{projection.coverage.contributing_student_count} contributing",
            "Live currentness: " + projection.live_currentness.state.replace("_", " "),
            f"Warnings: {len(warnings)}; blocking diagnostics: {len(blockers)}",
            "",
        )
        for item in projection.diagnostics:
            write_lines(output, f"[{item.severity}] {item.message}")
        write_lines(
            output,
            "",
            "1. Accept for Core export (requires current, unblocked preview)",
            "2. Reject this preview",
            "B. Cancel | M. Main Menu | Q. Quit",
        )
        answer = read_choice(input_fn, "Decision: ")
        command = parse_navigation_choice(answer)
        if command is NavigationChoice.BACK or not answer:
            return
        if answer not in {"1", "2"}:
            write_lines(output, "Invalid decision; no review was authored.")
            pause_for_user(input_fn)
            return
        decision: ReviewDecision = (
            "accepted_for_export" if answer == "1" else "rejected"
        )
        if decision == "accepted_for_export" and (
            projection.live_currentness.state != "current" or blockers
        ):
            write_lines(
                output,
                "This preview cannot currently be accepted for export.",
                "No teacher review was authored.",
            )
            pause_for_user(input_fn)
            return
        acknowledgments: tuple[str, ...] = ()
        if decision == "accepted_for_export" and warnings:
            write_lines(
                output,
                "",
                "Accepting requires explicit acknowledgment of all warnings above.",
                f"Warnings requiring acknowledgment: {len(warnings)}",
                "Type ACK to acknowledge every listed warning, or B to cancel.",
            )
            ack = read_choice(input_fn, "Warning acknowledgment: ")
            command = parse_navigation_choice(ack)
            if command is NavigationChoice.BACK or ack != "ACK":
                write_lines(
                    output, "Warnings not acknowledged; no review was authored."
                )
                return
            acknowledgments = warnings
        if check_scope() != summary:
            raise _ReviewChanged("Selected preview changed before authoring.")
        actor_id = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        command = parse_navigation_choice(actor_id)
        if command is NavigationChoice.BACK or not actor_id:
            write_lines(output, "No attribution; no review was authored.")
            return
        reviewed_at = clock()
        plan = authoring_previewer(
            root,
            class_id,
            summary.policy_id,
            summary.preview_id,
            summary.preview_sha256,
            decision,
            acknowledgments,
            actor_id,
            reviewed_at,
        )
        _check_candidate(
            plan,
            projection,
            summary,
            class_id,
            decision,
            acknowledgments,
            actor_id,
        )
        if check_scope() != summary:
            raise _ReviewChanged("Selected preview changed during authoring.")
        while True:
            if check_scope() != summary:
                raise _ReviewChanged("Selected preview changed before confirmation.")
            clear_fn()
            print_menu_header(output, "Review Teacher Decision Before Write")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label}",
                f"Decision: {decision.replace('_', ' ')}",
                f"Review revision: {plan.review_revision}",
                f"Warnings acknowledged: {len(acknowledgments)}",
                f"Blocking diagnostics: {len(blockers)}",
                "Selected review remains unchanged by this operation.",
                "",
                "Type WRITE to save this exact review revision.",
                "B or blank cancels; M or Q navigates.",
                "T. Technical details / provenance",
            )
            answer = read_choice(input_fn, "Confirmation: ")
            if answer.casefold() == "t":
                if check_scope() != summary:
                    raise _ReviewChanged("Selected preview changed before details.")
                clear_fn()
                print_menu_header(output, "Planning Review — Technical Candidate")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"policy_id: {summary.policy_id}",
                    f"preview_id: {summary.preview_id}",
                    f"preview_sha256: {summary.preview_sha256}",
                    f"derivation_id: {summary.derivation_id}",
                    f"derivation_sha256: {summary.derivation_sha256}",
                    f"review_revision: {plan.review_revision}",
                    "selected_review_revision: "
                    + (
                        str(summary.selected_review_revision)
                        if summary.selected_review_revision is not None
                        else "none"
                    ),
                )
                pause_for_user(input_fn)
                continue
            command = parse_navigation_choice(answer)
            if command is NavigationChoice.BACK or not answer:
                write_lines(output, "No teacher review was authored.")
                return
            if answer != "WRITE":
                write_lines(output, "No teacher review was authored.")
                pause_for_user(input_fn)
                return
            if check_scope() != summary:
                raise _ReviewChanged("Selected preview changed before commit.")
            attempted = True
            result = authoring_committer(root, plan)
            _check_result(result, plan)
            clear_fn()
            print_menu_header(output, "Planning Review Saved")
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Decision: {decision.replace('_', ' ')}",
                f"Saved review revision: {result.review_revision}",
                f"Write outcome: {result.write_disposition}",
                "",
                "Saving did not select this review or export a Core signal.",
            )
            pause_for_user(input_fn)
            return
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_ReviewChanged, _DiagnosticsChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, Planning Preview, or review candidate changed.",
            "Check the review history before retrying."
            if attempted
            else "No save was requested; refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Review could not be saved or verified safely.",
            "A write may have completed; inspect review history before retrying."
            if attempted
            else "No save was requested; use Advanced for diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_planning_review_authoring",)
