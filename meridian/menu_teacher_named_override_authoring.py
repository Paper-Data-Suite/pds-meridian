"""Teacher-named authoring of one immutable replacement Grade decision (#123 6B2).

A WRITE persists a new override revision but deliberately does not select it.
The saved teacher attribution bridge is retained through its existing exact
``Teacher actor ID: `` prompt. The separate 6B1 USE route applies a decision.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
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
    from meridian.menu_overrides import OverrideAuthoringPlan, OverrideScope

AuthoringPreviewer: TypeAlias = Callable[
    [Path, "OverrideScope", Decimal, str, str, datetime],
    "OverrideAuthoringPlan",
]
AuthoringCommitter: TypeAlias = Callable[[Path, "OverrideAuthoringPlan"], str]
Clock: TypeAlias = Callable[[], datetime]

# This is the existing TeacherAttributionInput adapter prompt, not a new
# teacher-entered record identifier. Keep its exact runtime value.
_TEACHER_ATTRIBUTION_PROMPT = "Teacher actor ID: "


def _check_plan(
    plan: "OverrideAuthoringPlan",
    scope: "OverrideScope",
    replacement: Decimal,
    actor_id: str,
    rationale: str,
) -> None:
    """Bind a teacher preview to the canonical, exact immutable candidate."""
    if (
        plan.scope != scope
        or plan.replacement_grade != format(replacement, "f")
        or plan.actor_id != actor_id
        or plan.rationale != rationale
    ):
        raise _ScopeChanged("Override preview does not match reviewed inputs.")
    preview = plan.preview
    candidate = preview.candidate
    if (
        candidate.class_id != scope.class_id
        or candidate.student_id != scope.student_id
        or candidate.target_period != scope.period
        or candidate.calendar_revision != scope.calendar_revision
        or candidate.calculation_family != scope.family
        or candidate.decision != "override"
        or candidate.replacement_grade != replacement
        or candidate.actor.actor_id != actor_id
        or candidate.rationale != rationale
        or candidate.override_revision != plan.candidate_revision
        or preview.candidate_sha256 != plan.candidate_sha256
        or preview.source.source_status != plan.source_status
        or preview.source.freshness_status != plan.source_freshness
        or (
            None
            if preview.source.base_grade is None
            else format(preview.source.base_grade, "f")
        )
        != plan.source_grade
    ):
        raise _ScopeChanged("Override candidate differs from its preview.")


def run_named_override_authoring(
    *,
    navigation: TeacherNavigationContext,
    authoring_previewer: AuthoringPreviewer,
    authoring_committer: AuthoringCommitter,
    clock: Clock,
    input_fn: InputFunction,
    output: TextIO,
    clear_fn: ClearFunction,
    class_catalog: TeacherAcademicChoiceCatalog | None = None,
    period_catalog: PeriodProficiencyChoiceCatalog | None = None,
) -> None:
    """Record one replacement decision without changing the selected override."""
    attempted = False
    try:
        # The parent controller imports this module; load its model on invocation.
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
            raise _ScopeChanged("Class scope changed before authoring.")
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
            question="Whose replacement Grade decision should be recorded?",
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
        grade_text = read_choice(input_fn, "Replacement Grade: ")
        if not grade_text:
            write_lines(output, "Canceled. No override decision was written.")
            return
        try:
            replacement = Decimal(grade_text)
        except InvalidOperation:
            write_lines(output, "Enter a valid numeric Grade. Nothing was saved.")
            pause_for_user(input_fn)
            return
        if not replacement.is_finite():
            write_lines(output, "A replacement Grade must be finite. Nothing saved.")
            pause_for_user(input_fn)
            return
        rationale = read_choice(input_fn, "Rationale: ")
        if not rationale:
            write_lines(output, "Canceled. A rationale is required; nothing saved.")
            pause_for_user(input_fn)
            return
        # The composed teacher menu intercepts *this exact prompt* and supplies
        # the saved/explicitly overridden teacher attribution without a new API.
        actor_id = read_choice(input_fn, _TEACHER_ATTRIBUTION_PROMPT)
        if not actor_id:
            write_lines(output, "No teacher attribution; nothing was written.")
            pause_for_user(input_fn)
            return
        decided_at = clock()
        check_scope()
        plan = authoring_previewer(
            root, scope, replacement, actor_id, rationale, decided_at
        )
        _check_plan(plan, scope, replacement, actor_id, rationale)
        check_scope()
        clear_fn()
        print_menu_header(output, "Record Replacement Grade Decision")
        write_lines(
            output,
            f"Marking period: {period.label}",
            f"Student: {student.label}",
            f"Grade calculation: {family.replace('_', ' ')}",
            f"Replacement Grade to record: {plan.replacement_grade}",
            f"Selected base result: {plan.source_status.replace('_', ' ')}",
            (
                "Base Grade: no numeric Grade (not zero)"
                if plan.source_grade is None
                else f"Base Grade: {plan.source_grade}"
            ),
            f"Base freshness: {plan.source_freshness.replace('_', ' ')}",
            f"Rationale: {plan.rationale}",
            "Teacher attribution: recorded with the decision",
            "",
            "WRITE creates an immutable decision but does NOT make it current.",
            "Use menu option 6 afterward to apply the authored decision.",
            "Type WRITE to record it, or press Enter to cancel.",
        )
        if read_choice(input_fn, "Confirmation: ") != "WRITE":
            write_lines(output, "Canceled. No override decision was written.")
            pause_for_user(input_fn)
            return
        check_scope()
        latest = authoring_previewer(
            root, scope, replacement, actor_id, rationale, decided_at
        )
        _check_plan(latest, scope, replacement, actor_id, rationale)
        if latest != plan:
            raise _ScopeChanged("Override source or history changed after review.")
        check_scope()
        attempted = True
        disposition = authoring_committer(root, plan)
        if disposition not in {"created", "existing"}:
            write_lines(
                output,
                "The write returned an unrecognized outcome.",
                "Inspect override history before attempting another write.",
            )
            pause_for_user(input_fn)
            return
        navigation.session.select_student(student.identity[0])
        write_lines(
            output,
            "",
            f"Replacement Grade decision recorded ({disposition}).",
            "It is NOT the current override decision yet.",
            "Use option 6 to review and apply the latest authored decision.",
        )
        pause_for_user(input_fn)
    except (ReturnToMainMenu, QuitPDS):
        raise
    except _ScopeChanged:
        write_lines(
            output,
            "The class, period, student or authoring basis changed.",
            "No write was attempted. Refresh the selection and try again.",
        )
        pause_for_user(input_fn)
    except Exception:
        if attempted:
            write_lines(
                output,
                "The write outcome cannot be verified safely.",
                "A revision may have been stored. Inspect override history first.",
            )
        else:
            write_lines(
                output,
                "The replacement Grade decision could not be prepared safely.",
                "No write was attempted. Check policy/evidence or Advanced details.",
            )
        pause_for_user(input_fn)


__all__ = ("run_named_override_authoring",)
