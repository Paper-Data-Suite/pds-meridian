"""Read-only Planning Preview diagnostics using verified teacher-named choices.

Issue #123 Slice 10D. A saved preview and its currently selected review have
separate authorities. Recheck both after projection; do not claim that a live
currentness observation remains true after the read. No planning writes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TextIO, TypeAlias

from pds_core.menu_navigation import (
    NavigationChoice,
    QuitPDS,
    ReturnToMainMenu,
    parse_navigation_choice,
)

from meridian.grouping_signal_preview_projection import (
    GroupingSignalTeacherPreviewProjection,
)
from meridian.menu_teacher_named_explain_preview_review import (
    PlanningPreviewChoiceCatalog,
    PlanningPreviewSummary,
)
from meridian.menu_teacher_named_grades import _current_choice, _ScopeChanged
from meridian.menu_teacher_named_review import _class
from meridian.menu_ui import (
    ClearFunction,
    InputFunction,
    pause_for_user,
    print_menu_header,
    print_standard_navigation,
    read_choice,
    write_lines,
)
from meridian.teacher_navigation_context import TeacherNavigationContext
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

DiagnosticsProjector: TypeAlias = Callable[
    [Path, str, str, str, str], GroupingSignalTeacherPreviewProjection
]


class _DiagnosticsChanged(RuntimeError):
    """Exact preview/review selection and projection no longer agree."""


def _checked_projection(
    value: GroupingSignalTeacherPreviewProjection,
    summary: PlanningPreviewSummary,
    class_id: str,
) -> None:
    """Fail closed before showing an injected or live diagnostic projection."""
    preview = value.preview_reference
    policy = value.policy_reference
    derivation = value.derivation_reference
    coverage = value.coverage
    review = value.review_status
    selected = review.selected_review_reference
    selected_revision = summary.selected_review_revision
    selected_sha = summary.selected_review_sha256
    if (
        value.class_id != class_id
        or preview.class_id != class_id
        or preview.preview_id != summary.preview_id
        or preview.preview_sha256 != summary.preview_sha256
        or derivation.class_id != class_id
        or derivation.derivation_id != summary.derivation_id
        or derivation.derivation_sha256 != summary.derivation_sha256
        or policy.class_id != class_id
        or policy.policy_id != summary.policy_id
        or policy.policy_revision != summary.policy_revision
        or policy.policy_sha256 != summary.policy_sha256
        or value.policy_title != summary.title
        or value.school_year != summary.school_year
        or value.period_id != summary.period_id
        or value.calendar_revision != summary.calendar_revision
        or value.standard_id != summary.standard_id
        or value.dimension_id != summary.dimension_id
        or value.band_count != summary.band_count
        or coverage.roster_student_count != summary.roster_count
        or type(coverage.contributing_student_count) is not int
        or type(coverage.noncontributing_student_count) is not int
        or coverage.contributing_student_count < 0
        or coverage.noncontributing_student_count < 0
        or coverage.contributing_student_count + coverage.noncontributing_student_count
        != summary.roster_count
        or value.live_currentness.state not in {"current", "stale", "blocked"}
    ):
        raise _DiagnosticsChanged("Diagnostics do not match selected saved preview.")
    if selected_revision is None:
        if (
            selected_sha is not None
            or selected is not None
            or review.decision is not None
        ):
            raise _DiagnosticsChanged("An unexpected review was selected.")
    elif (
        selected_sha is None
        or selected is None
        or selected.class_id != class_id
        or selected.derivation_id != summary.derivation_id
        or selected.review_revision != selected_revision
        or selected.review_sha256 != selected_sha
        or review.decision not in {"accepted_for_export", "rejected"}
    ):
        raise _DiagnosticsChanged("Selected review provenance differs.")
    bands = value.band_summaries
    if (
        len(bands) != summary.band_count
        or {b.band for b in bands} != set(range(1, summary.band_count + 1))
        or any(type(b.student_count) is not int or b.student_count < 0 for b in bands)
        or sum(b.student_count for b in bands) != coverage.contributing_student_count
    ):
        raise _DiagnosticsChanged("Preview band distribution is inconsistent.")
    if any(
        diagnostic.severity not in {"warning", "blocking", "info"}
        or not isinstance(diagnostic.message, str)
        or not isinstance(diagnostic.diagnostic_id, str)
        for diagnostic in value.diagnostics
    ):
        raise _DiagnosticsChanged("Preview diagnostics are malformed.")


def run_named_planning_preview_diagnostics(
    *,
    navigation: TeacherNavigationContext,
    diagnostics_projector: DiagnosticsProjector,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    preview_catalog: PlanningPreviewChoiceCatalog | None = None,
) -> None:
    """Choose exact saved preview by name and inspect live diagnostics read-only."""
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
            raise _DiagnosticsChanged("Verified class context changed.")
        chosen = select_teacher_choice(
            catalog=catalog,
            scope="planning_preview_review",
            selected={"class": class_id},
            title="Saved Planning Previews",
            question="Which saved Planning Preview should be checked?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if chosen is None:
            return

        def check_scope() -> PlanningPreviewSummary:
            if navigation.current_class() != verified:
                raise _DiagnosticsChanged("Selected class changed during review.")
            _current_choice(
                catalog,
                scope="planning_preview_review",
                selected={"class": class_id},
                choice=chosen,
            )
            if len(chosen.identity) != 1:
                raise _DiagnosticsChanged("Preview choice identity is invalid.")
            current = catalog.inspect(root, class_id, chosen.identity[0])
            if (
                current.school_year != verified.school_year
                or current.choice() != chosen
            ):
                raise _DiagnosticsChanged("Saved preview/review witness changed.")
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
            raise _DiagnosticsChanged("Preview or review changed during projection.")
        while True:
            if check_scope() != summary:
                raise _DiagnosticsChanged("Preview or review changed before display.")
            clear_fn()
            print_menu_header(output, "Saved Planning Preview & Diagnostics")
            coverage = projection.coverage
            write_lines(
                output,
                f"Policy: {summary.title}",
                f"Marking period: {summary.period_label} ({summary.school_year})",
                f"Standard: {summary.standard_id}",
                f"Dimension: {summary.dimension_id}",
                "Live currentness at read: "
                + projection.live_currentness.state.replace("_", " "),
                f"Coverage: {coverage.roster_student_count} rostered, "
                f"{coverage.contributing_student_count} contributing, "
                f"{coverage.noncontributing_student_count} noncontributing",
                "",
                "Band distribution:",
            )
            for band in projection.band_summaries:
                write_lines(
                    output,
                    f"  {band.band}. {band.label}: {band.student_count} students",
                )
            if projection.diagnostics:
                write_lines(output, "", "Diagnostics:")
                for item in projection.diagnostics:
                    write_lines(output, f"  [{item.severity}] {item.message}")
            else:
                write_lines(output, "", "Diagnostics: none")
            review = projection.review_status
            decision = review.decision
            applicability = review.applicability
            applicability_state = (
                "unavailable" if applicability is None else applicability.status
            )
            write_lines(
                output,
                "Selected teacher review: "
                + (decision.replace("_", " ") if decision else "none"),
                "Review applicability: " + applicability_state.replace("_", " "),
                "",
                "Currentness and review applicability reflect this read only.",
                "No derivation, preview, review, selection or export was changed.",
                "T. Technical details / provenance",
            )
            print_standard_navigation(output)
            answer = read_choice(input_fn)
            if answer.casefold() == "t":
                if check_scope() != summary:
                    raise _DiagnosticsChanged("Selected review changed before details.")
                clear_fn()
                print_menu_header(output, "Planning Preview — Technical Provenance")
                write_lines(
                    output,
                    f"class_id: {class_id}",
                    f"preview_id: {summary.preview_id}",
                    f"preview_sha256: {summary.preview_sha256}",
                    f"derivation_id: {summary.derivation_id}",
                    f"derivation_sha256: {summary.derivation_sha256}",
                    f"policy_id: {summary.policy_id}",
                    f"policy_revision: {summary.policy_revision}",
                    f"policy_sha256: {summary.policy_sha256}",
                    "selected_review_revision: "
                    + str(summary.selected_review_revision or "none"),
                    "selected_review_sha256: "
                    + (summary.selected_review_sha256 or "none"),
                )
                pause_for_user(input_fn)
                continue
            navigation_choice = parse_navigation_choice(answer)
            if navigation_choice is NavigationChoice.BACK or not answer:
                return
            write_lines(output, "Please choose T, B, M, or Q.")
            pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except (_DiagnosticsChanged, _ScopeChanged):
        write_lines(
            output,
            "Class, saved Planning Preview or selected review changed.",
            "No record was changed. Refresh the named choices.",
        )
        pause_for_user(input_fn)
    except Exception:
        write_lines(
            output,
            "Planning Preview diagnostics could not be verified safely.",
            "No record was changed. Use Advanced for exact diagnostics.",
        )
        pause_for_user(input_fn)


__all__ = ("run_named_planning_preview_diagnostics",)
