"""#123 11K: joined installed teacher journey on a synthetic academic workspace.

Runs real installed Meridian named controllers and authoritative storage readers.
Every seed write occurs before the read-only session and inside an isolated root.
Missing Grade policy is a truthful blocker, not a fabricated numeric Grade.
"""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.academic_period_proficiency_storage import (
    write_academic_period_proficiency_policy_revision,
)
from meridian.grade_items_workflow import project_grade_items_review
from meridian.grouping_signal_policy_storage import (
    select_grouping_signal_policy_revision,
    write_grouping_signal_policy_revision,
)
from meridian.menu_explain import default_explain_menu_dependencies
from meridian.menu_grades import default_grade_menu_dependencies
from meridian.menu_proficiency import _load_grade_item
from meridian.menu_teacher_named_explain_item_proficiency import (
    run_named_grade_item_proficiency_explanation,
)
from meridian.menu_teacher_named_grades import run_named_current_grade_review
from meridian.menu_teacher_named_planning_readiness import (
    PlanningReadinessPolicyCatalog,
    run_named_planning_readiness,
)
from meridian.menu_teacher_named_review import (
    run_named_grade_item_proficiency,
    run_named_grade_item_review,
)
from meridian.planning_signal_workflow import project_planning_signal_readiness
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_session import TeacherSessionContext

if TYPE_CHECKING:
    from scripts import smoke_program_explanation_traces as trace_fixture
    from scripts import smoke_program_issue123_populated_domain as base
else:
    import smoke_program_explanation_traces as trace_fixture
    import smoke_program_issue123_populated_domain as base


def _seed_planning(root: Path) -> None:
    """Select only explicitly written synthetic policies, before observation."""
    trace = trace_fixture
    scale = trace._scale()
    period = write_academic_period_proficiency_policy_revision(
        root, trace._period_policy(scale)
    ).stored.policy
    policy = write_grouping_signal_policy_revision(
        root, trace._grouping_policy(scale, period)
    ).stored.policy
    select_grouping_signal_policy_revision(
        root,
        base.PRIMARY,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )


def _joined(root: Path) -> None:
    """One retained class: Grade Item → proficiency → Grade → Explain → Plan."""
    nav = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=lambda: root,
            active_year_loader=lambda _root: base.YEAR,
        ),
    )
    catalog = TeacherAcademicChoiceCatalog(nav)
    items = load_teacher_choices(catalog, scope="class")
    class_number = base._chosen_position(items, base.PRIMARY)
    assert len(nav.readers.roster_loader(root, base.PRIMARY).students) == 29
    selected_before = base._tree(root)
    selected_item = "unit1_assessment"

    # First named view asks for the class; all later views retain that selection.
    nav.choose_class(base.PRIMARY)
    item_options = load_teacher_choices(
        catalog, scope="grade_item", selected={"class": base.PRIMARY}
    )
    item_number = base._chosen_position(item_options, selected_item)
    nav.session.clear()
    item_script = base.Script([class_number, item_number, ""])
    item_view = base._execute(
        run_named_grade_item_review,
        item_script,
        navigation=nav,
        catalog=catalog,
        review_loader=project_grade_items_review,
    )
    for marker in ("Unit 1 Assessment", "Work relationships: 1", "Read-only"):
        assert marker in item_view, (marker, item_view[-700:])
    base._no_raw(item_script.prompts, item_view)
    assert nav.session.active_class_id == base.PRIMARY
    assert nav.session.active_grade_item_id == selected_item

    roster = load_teacher_choices(
        catalog, scope="student", selected={"class": base.PRIMARY}
    )
    pupil = base._chosen_position(roster, base.STUDENT)
    names = [choice for choice in roster if choice.label == "Alex Rivera"]
    assert len(names) == 2 and names[0].display != names[1].display
    standard_scope = {
        "class": base.PRIMARY,
        "grade_item": selected_item,
        "student": base.STUDENT,
    }
    selected = load_teacher_choices(catalog, scope="standard", selected=standard_scope)
    assert len(selected) == 1 and selected[0].identity == (base.STANDARD,)
    proficiency_script = base.Script([item_number, pupil, "1", ""])
    proficiency_view = base._execute(
        run_named_grade_item_proficiency,
        proficiency_script,
        navigation=nav,
        catalog=catalog,
        load_proficiency=_load_grade_item,
    )
    for marker in ("Student: Alex Rivera", "Current proficiency: Proficient"):
        assert marker in proficiency_view, (marker, proficiency_view[-700:])
    base._no_raw(proficiency_script.prompts, proficiency_view)
    assert nav.session.active_student_id == base.STUDENT

    # Reuse a verified selected period in the actual Grade controller. No Grade
    # policy is invented by the synthetic fixture, so a blocked or ungraded
    # response must never be portrayed as zero.
    nav.choose_period("mp1")
    grade_script = base.Script([pupil, "1", ""])
    grade_view = base._execute(
        run_named_current_grade_review,
        grade_script,
        navigation=nav,
        current_grade_loader=default_grade_menu_dependencies().current_grade_loader,
    )
    assert (
        "Current Grade Review" in grade_view
        or "cannot be verified or is not configured" in grade_view
    ), grade_view[-1000:]
    assert "Base Grade: 0" not in grade_view
    assert "Effective Grade: 0" not in grade_view
    base._no_raw(grade_script.prompts, grade_view)
    assert nav.current_period() is not None

    # Explain the very same selected Grade Item / Student / Standard via the
    # existing provenance service, not a hand-crafted explanatory response.
    explain_script = base.Script([item_number, pupil, "1", "B"])
    explanation = base._execute(
        run_named_grade_item_proficiency_explanation,
        explain_script,
        navigation=nav,
        class_catalog=catalog,
        grade_item_explainer=(
            default_explain_menu_dependencies().grade_item_proficiency
        ),
    )
    for marker in (
        "Grade Item Proficiency Explanation",
        "Student: Alex Rivera",
        "Proficiency: Proficient",
        "Read-only explanation",
    ):
        assert marker in explanation, (marker, explanation[-1000:])
    base._no_raw(explain_script.prompts, explanation)
    assert nav.session.active_class_id == base.PRIMARY

    # Continue in the *same navigation context* to the named planning policy.
    policy_catalog = PlanningReadinessPolicyCatalog(nav)
    policy_choices = load_teacher_choices(
        policy_catalog,
        scope="planning_readiness_policy",
        selected={"class": base.PRIMARY},
    )
    assert len(policy_choices) == 1
    assert policy_choices[0].label == "Reading planning signal"
    plan_script = base.Script(["1", "B"])
    plan_view = base._execute(
        run_named_planning_readiness,
        plan_script,
        navigation=nav,
        readiness_projector=project_planning_signal_readiness,
        class_catalog=catalog,
        policy_catalog=policy_catalog,
    )
    for marker in (
        "Planning Signal — Readiness by Policy Name",
        "Policy: Reading planning signal",
        "Readiness:",
        "Read-only: no derivation, review, or Core export was performed",
    ):
        assert marker in plan_view, (marker, plan_view[-1100:])
    base._no_raw(plan_script.prompts, plan_view)

    # No viewer, explanation, Grade preview, or planning-readiness call wrote
    # academic state. Only the explicitly isolated pre-session seed did so.
    assert base._tree(root) == selected_before
    assert nav.session.active_class_id == base.PRIMARY
    nav.choose_class(base.OTHER)
    assert nav.session.active_student_id is None
    assert nav.session.active_grade_item_id is None
    assert nav.current_period() is None
    assert nav.current_class() is not None
    assert nav.current_class().class_id == base.OTHER
    assert base._tree(root) == selected_before
    print("Meridian #123 11K joined installed teacher journey passed.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    base._installed()
    assert importlib.metadata.version("pds-meridian") == "0.4.2"
    if args.root.exists():
        raise RuntimeError("11K requires a new, absent synthetic root.")
    args.root.mkdir(parents=True)
    workspace = base._seed(args.root)
    _seed_planning(workspace)
    _joined(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
