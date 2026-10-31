"""Guided selection of the latest authored override decision (#123 Slice 6B1).

The only persistent operation is Meridian's existing exact CAS selection
committer. No override is authored or withdrawn here. Core #237 UI is not
reimplemented; scoped choices are always reverified before commit.
"""

from __future__ import annotations

from collections.abc import Callable
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
    from meridian.menu_overrides import OverrideScope, OverrideSelectionPlan

SelectionPreviewer: TypeAlias = Callable[
    [Path, "OverrideScope"], "OverrideSelectionPlan"
]
SelectionCommitter: TypeAlias = Callable[[Path, "OverrideSelectionPlan"], str]


def _check_plan(plan: "OverrideSelectionPlan", scope: "OverrideScope") -> None:
    """Correlate presentation and canonical selection before any confirmation."""
    if plan.scope != scope or plan.target_decision not in {"override", "withdraw"}:
        raise _ScopeChanged("The override target differs from the chosen scope.")
    preview = plan.preview
    reference = preview.target_reference
    decision = preview.target_decision
    if (
        reference.class_id != scope.class_id
        or reference.student_id != scope.student_id
        or reference.school_year != scope.period.school_year
        or reference.period_id != scope.period.period_id
        or reference.calendar_revision != scope.calendar_revision
        or reference.calculation_family != scope.family
        or reference.override_revision != plan.target_revision
        or reference.override_sha256 != plan.target_sha256
        or decision.decision != plan.target_decision
        or preview.history[-1] != plan.target_revision
    ):
        raise _ScopeChanged("Override preview is inconsistent with its source.")
    current = preview.expected_current
    if plan.current_revision != (
        None if current is None else current.override_revision
    ) or plan.current_sha256 != (None if current is None else current.override_sha256):
        raise _ScopeChanged("Current selection is inconsistent with the preview.")
    if plan.target_decision == "override":
        replacement = decision.replacement_grade
        if replacement is None or plan.replacement_grade != format(replacement, "f"):
            raise _ScopeChanged("Override replacement does not match the preview.")
    elif plan.replacement_grade is not None or decision.replacement_grade is not None:
        raise _ScopeChanged("A withdrawal cannot apply a replacement Grade.")


def run_named_latest_override_selection(
    *,
    navigation: TeacherNavigationContext,
    selection_previewer: SelectionPreviewer,
    selection_committer: SelectionCommitter,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Make an already-authored latest decision current with one explicit USE."""
    committed = False
    attempted = False
    try:
        # Only imported at invocation time: the controller imports this module.
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
            raise _ScopeChanged("Class changed.")
        period_result = _marking_period(
            navigation,
            periods,
            class_id=class_id,
            root=root,
            input_fn=input_fn,
            output=output,
            clear_fn=clear_fn,
        )
        if period_result is None:
            return
        period, period_choice = period_result
        student = select_teacher_choice(
            catalog=classes,
            scope="student",
            selected={"class": class_id},
            title="Choose Student",
            question="Whose authored override decision should Meridian use?",
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
        plan = selection_previewer(root, scope)
        _check_plan(plan, scope)
        check_scope()
        clear_fn()
        print_menu_header(output, "Use Authored Grade Override Decision")
        write_lines(
            output,
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Grade calculation: {family.replace('_', ' ')}",
            "",
        )
        if plan.target_decision == "withdraw":
            write_lines(
                output,
                "Latest authored decision: withdrawal",
                "Using it will stop applying the selected replacement Grade.",
                "It does not create a new override or recalculate the base Grade.",
            )
        else:
            write_lines(
                output,
                "Latest authored decision: replacement Grade",
                f"Replacement Grade: {plan.replacement_grade}",
                "Using it changes the selected override decision, not its source.",
            )
        write_lines(
            output,
            f"Latest authored version: {plan.target_revision}",
            (
                "Currently selected: none"
                if plan.current_revision is None
                else f"Currently selected version: {plan.current_revision}"
            ),
            "",
        )
        if (
            plan.current_revision == plan.target_revision
            and plan.current_sha256 == plan.target_sha256
        ):
            write_lines(output, "This decision is already current. No change made.")
            pause_for_user(input_fn)
            return
        write_lines(
            output,
            "Only the latest authored decision can be selected here.",
            "Type USE to make it current, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "USE":
            write_lines(output, "Canceled. Current override was not changed.")
            pause_for_user(input_fn)
            return
        check_scope()
        fresh_plan = selection_previewer(root, scope)
        _check_plan(fresh_plan, scope)
        if fresh_plan != plan:
            raise _ScopeChanged("Override selection changed since confirmation.")
        check_scope()
        attempted = True
        disposition = selection_committer(root, plan)
        committed = True
        if disposition not in {"created", "updated", "existing"}:
            write_lines(
                output,
                "Selection returned an unrecognized outcome.",
                "Inspect the current override before taking another action.",
            )
            pause_for_user(input_fn)
            return
        navigation.session.select_student(student.identity[0])
        write_lines(
            output,
            "",
            "The latest authored override decision is now current.",
            f"Selection outcome: {disposition}.",
            "No override or withdrawal revision was authored by this action.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "Class, marking period, student, or override selection changed.",
            "No selection was attempted. Refresh and review again.",
        )
        pause_for_user(input_fn)
    except Exception:
        if attempted or committed:
            write_lines(
                output,
                "The override selection outcome could not be verified safely.",
                "Inspect the current override before retrying; it may have changed.",
            )
        else:
            write_lines(
                output,
                "The latest override decision could not be verified safely.",
                "No selection was attempted. Check Advanced or refresh the scope.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_latest_override_selection",)
