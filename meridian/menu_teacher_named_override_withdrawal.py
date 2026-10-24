"""Teacher-named immutable withdrawal authoring (#123 Slice 6B3).

WITHDRAW records an immutable withdrawal, but never selects it. The prior
selected replacement remains in force until a separate, confirmed USE action.
Canonical preview and CAS-backed authoring remain Meridian domain authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.menu_teacher_named_grades import _family, _marking_period, _ScopeChanged
from meridian.menu_teacher_named_override_review import _revalidate
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
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_navigation_terminal import select_teacher_choice

if TYPE_CHECKING:
    from meridian.menu_overrides import OverrideScope, OverrideWithdrawalPlan

WithdrawalPreviewer: TypeAlias = Callable[
    [Path, "OverrideScope", str, str, datetime], "OverrideWithdrawalPlan"
]
WithdrawalCommitter: TypeAlias = Callable[[Path, "OverrideWithdrawalPlan"], str]
Clock: TypeAlias = Callable[[], datetime]

# Exact existing TeacherAttributionInput prompt, not an academic record ID.
# Avoid introducing a new literal read_choice raw-ID call site (#110 audit).
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "


def _check_plan(
    plan: "OverrideWithdrawalPlan",
    scope: "OverrideScope",
    actor_id: str,
    rationale: str,
) -> None:
    """Verify all displayed withdrawal metadata against the domain preview."""
    preview = plan.preview
    selected = preview.selected_override_reference
    prior = preview.selected_override_decision
    candidate = preview.candidate
    if (
        plan.scope != scope
        or plan.actor_id != actor_id
        or plan.rationale != rationale
        or selected.class_id != scope.class_id
        or selected.student_id != scope.student_id
        or selected.school_year != scope.period.school_year
        or selected.period_id != scope.period.period_id
        or selected.calendar_revision != scope.calendar_revision
        or selected.calculation_family != scope.family
        or selected.override_revision != plan.selected_revision
        or selected.override_sha256 != plan.selected_sha256
        or prior.decision != "override"
        or prior.replacement_grade is None
        or preview.source.source_status != plan.source_status
        or (
            None
            if preview.source.base_grade is None
            else format(preview.source.base_grade, "f")
        )
        != plan.source_grade
        or candidate.class_id != scope.class_id
        or candidate.student_id != scope.student_id
        or candidate.target_period != scope.period
        or candidate.calendar_revision != scope.calendar_revision
        or candidate.calculation_family != scope.family
        or candidate.decision != "withdraw"
        or candidate.replacement_grade is not None
        or candidate.withdrawn_override_reference != selected
        or candidate.source_result != prior.source_result
        or candidate.override_revision != plan.candidate_revision
        or preview.candidate_sha256 != plan.candidate_sha256
        or candidate.actor.actor_id != actor_id
        or candidate.rationale != rationale
        or preview.history_before[-1] + 1 != plan.candidate_revision
    ):
        raise _ScopeChanged("Withdrawal decision differs from its reviewed basis.")


def run_named_override_withdrawal(
    *,
    navigation: TeacherNavigationContext,
    withdrawal_previewer: WithdrawalPreviewer,
    withdrawal_committer: WithdrawalCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Author one explicit withdrawal; never silently change current selection."""
    attempted = False
    try:
        # Import only at invocation: the Overrides controller imports this module.
        from meridian.menu_overrides import OverrideScope

        classes = class_catalog or TeacherAcademicChoiceCatalog(navigation)
        periods = period_catalog or PeriodProficiencyChoiceCatalog(navigation)
        active = _class(
            navigation, classes, input_fn=input_fn, output=output, clear_fn=clear_fn
        )
        if active is None:
            return
        root, class_id = active
        verified_class = navigation.current_class()
        if (
            verified_class is None
            or verified_class.workspace != root
            or verified_class.class_id != class_id
        ):
            raise _ScopeChanged("Class scope changed before withdrawal.")
        period_selection = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if period_selection is None:
            return
        period, period_choice = period_selection
        student = select_teacher_choice(
            catalog=classes,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Whose selected replacement Grade should be withdrawn?",
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if student is None:
            return
        family = _family(input_fn=input_fn, output=output, clear_fn=clear_fn)
        if family is None:
            return
        scope = OverrideScope(
            class_id=class_id,
            student_id=student.identity[0],
            period=AcademicPeriodRef(period.school_year, period.period_id),
            calendar_revision=period.calendar_revision,
            family=family,
        )

        def check_scope() -> None:
            _revalidate(
                navigation=navigation,
                root=root,
                class_id=class_id,
                school_year=verified_class.school_year,
                period=period,
                period_choice=period_choice,
                student=student,
                class_catalog=classes,
                period_catalog=periods,
            )

        check_scope()
        rationale = read_choice(input_fn, "Withdrawal rationale: ")
        if not rationale:
            write_lines(output, "Canceled. Withdrawal requires a rationale.")
            pause_for_user(input_fn)
            return
        # The composed menu resolves saved teacher attribution for this exact
        # runtime prompt; one-action overrides retain their established rules.
        actor_id = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor_id:
            write_lines(output, "No teacher attribution. Nothing was recorded.")
            pause_for_user(input_fn)
            return
        decided_at = clock()
        check_scope()
        plan = withdrawal_previewer(root, scope, actor_id, rationale, decided_at)
        _check_plan(plan, scope, actor_id, rationale)
        check_scope()
        clear_fn()
        print_menu_header(output, "Record Grade Override Withdrawal")
        write_lines(
            output,
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Grade calculation: {family.replace('_', ' ')}",
            f"Selected active override version: {plan.selected_revision}",
            f"New withdrawal version: {plan.candidate_revision}",
            f"Selected base result: {plan.source_status.replace('_', ' ')}",
            (
                "Base Grade: no numeric Grade (not zero)"
                if plan.source_grade is None
                else f"Base Grade: {plan.source_grade}"
            ),
            f"Withdrawal rationale: {plan.rationale}",
            "Teacher attribution: recorded with the decision",
            "",
            "WITHDRAW records a withdrawal but does NOT make it current.",
            "The selected replacement stays current until the new decision is used.",
            "Use option 6 afterward to select the withdrawal decision.",
            "Type WITHDRAW to record it, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "WITHDRAW":
            write_lines(output, "Canceled. No withdrawal was recorded.")
            pause_for_user(input_fn)
            return
        check_scope()
        latest = withdrawal_previewer(root, scope, actor_id, rationale, decided_at)
        _check_plan(latest, scope, actor_id, rationale)
        if latest != plan:
            raise _ScopeChanged("Withdrawal source or history changed after review.")
        check_scope()
        attempted = True
        disposition = withdrawal_committer(root, plan)
        if disposition not in {"created", "existing"}:
            write_lines(
                output,
                "The write returned an unrecognized outcome.",
                "Inspect override history before attempting another withdrawal.",
            )
            pause_for_user(input_fn)
            return
        navigation.session.select_student(student.identity[0])
        write_lines(
            output,
            "",
            f"Withdrawal decision recorded ({disposition}).",
            "The prior selected replacement Grade remains current.",
            "Use option 6 to review and select the latest withdrawal decision.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "Class, marking period, student or withdrawal basis changed.",
            "No write was attempted. Refresh the selection and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "The withdrawal write outcome cannot be verified safely.",
                "A decision may have been stored. Inspect override history first.",
                "Do not assume the prior selected override was changed.",
            )
        else:
            write_lines(
                output,
                "Withdrawal cannot be prepared or no active override is selected.",
                "No write was attempted. Check the selected override or Advanced.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_override_withdrawal",)
