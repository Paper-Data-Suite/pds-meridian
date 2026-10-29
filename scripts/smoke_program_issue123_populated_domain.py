"""#123 11G: installed, populated, read-only teacher domain acceptance.

The academic workspace is synthetic and isolated beneath the caller's root.
The real installed Core/Meridian readers, selected Grade Item/proficiency state,
and named controllers are used; no protected publication access is granted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Callable

import smoke_program_explanation_traces as trace_fixture
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.academic_work_registration_storage import (
    load_current_academic_work_registration,
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.rosters import create_roster, write_roster
from pds_core.routes import (
    class_dir,
    class_metadata_path,
    class_roster_path,
    module_work_dir,
)
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_storage import select_grade_item_membership_revision
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision
from meridian.grade_items_workflow import project_grade_items_review
from meridian.menu_proficiency import _load_grade_item
from meridian.menu_teacher_named_review import (
    run_named_grade_item_proficiency,
    run_named_grade_item_review,
)
from meridian.proficiency_mapping_storage import (
    write_mapping_profile_revision,
    write_proficiency_scale_revision,
)
from meridian.standards_proficiency_storage import (
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
)
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import (
    NavigationScopeUnavailable,
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_session import TeacherSessionContext

YEAR = "2026-2027"
PRIMARY = "synthetic_class_2026"
OTHER = "english_10"
STUDENT = "student_1"
STANDARD = trace_fixture.STANDARD_ID
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


@dataclass
class Script:
    responses: list[str]
    prompts: list[str] = field(default_factory=list)

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected additional prompt: " + prompt)
        return self.responses.pop(0)


def _installed() -> None:
    import pds_core

    import meridian

    prefix = Path(sys.prefix).resolve()
    for module in (meridian, pds_core):
        origin = getattr(module, "__file__", None)
        if not origin or not Path(origin).resolve().is_relative_to(prefix):
            raise AssertionError("Runtime module was imported outside installed venv.")
    for distribution, version in (("pds-meridian", "0.4.2"), ("pds-core", "0.6.6")):
        if importlib.metadata.version(distribution) != version:
            raise AssertionError("Unexpected installed distribution version.")


def _tree(root: Path) -> tuple[tuple[str, str], ...]:
    """Snapshot synthetic academic content, including any unexpected new files."""
    return tuple(
        sorted(
            (p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob("*")
            if p.is_file()
        )
    )


def _students() -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for number in range(1, 30):
        duplicate = number in (1, 22)
        rows.append(
            {
                "student_id": f"student_{number}",
                "first_name": "Alex" if duplicate else f"Learner{number:02d}",
                "last_name": "Rivera" if duplicate else f"Surname{number:02d}",
                "period": "2",
            }
        )
    return tuple(rows)


def _secondary_class(workspace: Path) -> None:
    class_dir(workspace, OTHER).mkdir(parents=True)
    write_class_metadata(
        class_metadata_path(workspace, OTHER),
        ClassMetadata(
            class_id=OTHER,
            school_year=YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    write_roster(
        class_roster_path(workspace, OTHER),
        create_roster(
            OTHER,
            (
                {
                    "student_id": "other_001",
                    "first_name": "Taylor",
                    "last_name": "Chen",
                    "period": "1",
                },
            ),
        ),
    )


def _archived_grade_item(workspace: Path) -> None:
    stored = write_grade_item_revision(
        workspace,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=PRIMARY,
            grade_item_id="archived_portfolio",
            grade_item_revision=1,
            supersedes_revision=None,
            title="Archived Writing Portfolio",
            purpose="standards_proficiency",
            status="archived",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    assert stored.revision.grade_item_id == "archived_portfolio"
    select_grade_item_revision(
        workspace,
        PRIMARY,
        "archived_portfolio",
        1,
        expected_current_revision=None,
    )


def _producer_titles(workspace: Path) -> None:
    """Register work labels through Core only; do not invent publications."""
    for producer, work_id, title in (
        ("scoreform", "story_reading", "Story and Identity Reading Check"),
        ("quillan", "memoir_analysis", "Personal Memoir Analysis"),
    ):
        work = ModuleWorkRef(producer, PRIMARY, work_id)
        module_work_dir(workspace, work).mkdir(parents=True)
        write_academic_work_registration(
            workspace,
            AcademicWorkRegistration(
                schema_version="1",
                record_type="academic_work_registration",
                work=work,
                registration_revision=1,
                producer_contract_version="v1",
                title=title,
                work_kind="assignment",
                academic_intent="summative",
                lifecycle="active",
                created_at=NOW,
                updated_at=NOW,
                source_records=(),
            ),
            expected_current_revision=None,
        )
        current = load_current_academic_work_registration(workspace, work)
        if current is None or current.title != title:
            raise AssertionError("Producer work label did not survive Core reload.")


def _seed(root: Path) -> Path:
    # Reuse the #42 trace fixture's persisted provenance; do not substitute
    # calculation-only placeholder eligibility, association or mapping digests.
    # All test writes stay inside this new temporary synthetic workspace.
    workspace = root / "workspace"
    trace_fixture._core_workspace(workspace)
    write_roster(
        class_roster_path(workspace, PRIMARY),
        create_roster(PRIMARY, _students()),
        overwrite=True,
    )
    _secondary_class(workspace)
    scale = write_proficiency_scale_revision(
        workspace, trace_fixture._scale()
    ).stored.scale
    profile = write_mapping_profile_revision(
        workspace, trace_fixture._mapping_profile(scale)
    ).stored
    write_standard_proficiency_policy_revision(
        workspace, trace_fixture._grade_item_policy(scale)
    )
    grade_basis, membership = trace_fixture._grade_item_and_membership(workspace)
    selected_item = select_grade_item_revision(
        workspace,
        PRIMARY,
        trace_fixture.GRADE_ITEM_ID,
        1,
        expected_current_revision=None,
    )
    selected_membership = select_grade_item_membership_revision(
        workspace,
        PRIMARY,
        trace_fixture.GRADE_ITEM_ID,
        trace_fixture.WORK,
        1,
        expected_current_membership_revision=None,
    )
    assert selected_item is not None and selected_membership is not None
    stored = trace_fixture._write_calculated_grade_item_result(
        workspace, scale, profile, grade_basis, membership
    )
    assert stored.snapshot.outcome.status == "calculated"
    select_standard_proficiency_result_revision(
        workspace,
        PRIMARY,
        trace_fixture.GRADE_ITEM_ID,
        STUDENT,
        STANDARD,
        1,
        expected_current_result_revision=None,
    )
    _archived_grade_item(workspace)
    _producer_titles(workspace)
    rebuild_academic_catalog(workspace)
    # Verify the provenance using the *same* real explanation loader as the
    # teacher path, before any menu interaction is counted as qualified.
    explained = _load_grade_item(
        workspace, PRIMARY, trace_fixture.GRADE_ITEM_ID, STUDENT, STANDARD
    )
    assert explained.status == "calculated"
    assert explained.proficiency_label == "Proficient"
    return workspace


def _chosen_position(choices: tuple[object, ...], identity: str) -> str:
    matches = [
        index
        for index, choice in enumerate(choices, start=1)
        if getattr(choice, "identity") == (identity,)
    ]
    if len(matches) != 1:
        raise AssertionError("Expected exactly one canonical selection.")
    return str(matches[0])


def _execute(
    action: Callable[..., None],
    answers: Script,
    **kwargs: object,
) -> str:
    output = StringIO()
    action(input_fn=answers, output=output, clear_fn=lambda: None, **kwargs)
    if answers.responses:
        raise AssertionError("Unexpected unused teacher responses.")
    return output.getvalue()


def _no_raw(prompts: list[str], rendered: str) -> None:
    raw = "\n".join(prompts)
    for forbidden in (
        "Class ID:",
        "Grade Item ID:",
        "Student ID:",
        "Policy ID:",
        "sha256:",
        "Projection cache key:",
    ):
        if forbidden in raw:
            raise AssertionError("Ordinary route requested a technical identifier.")
    for secret in ("student_1", "essay_1", "unit1_assessment", "a" * 64):
        if secret in rendered:
            raise AssertionError("Ordinary route exposed internal identity/provenance.")


def _journey(workspace: Path) -> None:
    nav = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=lambda: workspace,
            active_year_loader=lambda _root: YEAR,
        ),
    )
    catalog = TeacherAcademicChoiceCatalog(nav)
    class_options = load_teacher_choices(catalog, scope="class")
    assert {x.identity for x in class_options} == {(PRIMARY,), (OTHER,)}
    assert len(nav.readers.roster_loader(workspace, PRIMARY).students) == 29
    class_number = _chosen_position(class_options, PRIMARY)

    # Real installed named Grade Item domain controller and persisted storage.
    # The class choice is made in this first domain and retained afterward.
    nav.choose_class(PRIMARY)
    item_options = load_teacher_choices(
        catalog, scope="grade_item", selected={"class": PRIMARY}
    )
    assert {x.identity for x in item_options} == {
        ("unit1_assessment",),
        ("archived_portfolio",),
    }
    nav.session.clear()
    script = Script(
        [class_number, _chosen_position(item_options, "unit1_assessment"), ""]
    )
    before = _tree(workspace)
    display = _execute(
        run_named_grade_item_review,
        script,
        navigation=nav,
        catalog=catalog,
        review_loader=project_grade_items_review,
    )
    for expected in ("Unit 1 Assessment", "Work relationships: 1", "Read-only"):
        if expected not in display:
            raise AssertionError("Installed Grade Item review missing " + expected)
    assert nav.session.active_class_id == PRIMARY
    assert nav.session.active_grade_item_id == "unit1_assessment"
    _no_raw(script.prompts, display)
    assert _tree(workspace) == before

    roster = load_teacher_choices(catalog, scope="student", selected={"class": PRIMARY})
    assert len(roster) == 29
    names = [choice for choice in roster if choice.label == "Alex Rivera"]
    assert len(names) == 2 and names[0].identity != names[1].identity
    assert names[0].display != names[1].display
    assert all("student_" not in x.display for x in roster)
    pupil = _chosen_position(roster, STUDENT)
    standards = load_teacher_choices(
        catalog,
        scope="standard",
        selected={
            "class": PRIMARY,
            "grade_item": "unit1_assessment",
            "student": STUDENT,
        },
    )
    assert len(standards) == 1 and standards[0].identity == (STANDARD,)
    script = Script(
        [_chosen_position(item_options, "unit1_assessment"), pupil, "1", ""]
    )
    display = _execute(
        run_named_grade_item_proficiency,
        script,
        navigation=nav,
        catalog=catalog,
        load_proficiency=_load_grade_item,
    )
    for expected in (
        "Unit 1 Assessment",
        "Student: Alex Rivera",
        "Current proficiency: Proficient",
        "Read-only selected result",
    ):
        if expected not in display:
            raise AssertionError(
                "Installed proficiency read missing " + expected + ": " + display[-700:]
            )
    _no_raw(script.prompts, display)
    assert nav.session.active_student_id == STUDENT
    assert _tree(workspace) == before

    # Only a verified selected result appears; another student's absence is
    # not reinterpreted as a zero or an inferred performance level.
    assert not load_teacher_choices(
        catalog,
        scope="standard",
        selected={
            "class": PRIMARY,
            "grade_item": "unit1_assessment",
            "student": "student_22",
        },
    )
    period = PeriodProficiencyChoiceCatalog(nav)
    periods = load_teacher_choices(period, scope="period", selected={"class": PRIMARY})
    assert len(periods) == 1 and periods[0].identity == ("mp1",)
    nav.choose_period("mp1")
    assert nav.current_period() is not None

    # An explicit denial is redacted and cannot mark a student as selected.
    nav.session.clear_student()
    denied = Script(
        [_chosen_position(item_options, "unit1_assessment"), pupil, "1", ""]
    )

    def denied_explanation(*_args: object) -> object:
        raise PermissionError("synthetic-private-evidence-token")

    blocked = _execute(
        run_named_grade_item_proficiency,
        denied,
        navigation=nav,
        catalog=catalog,
        load_proficiency=denied_explanation,
    )
    assert "could not be verified or explained safely" in blocked
    assert "synthetic-private-evidence-token" not in blocked
    assert nav.session.active_student_id is None
    assert _tree(workspace) == before

    # Core calendar changes between views invalidate the exact period witness.
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=YEAR,
        calendar_revision=2,
        created_at=trace_fixture.NOW,
        updated_at=trace_fixture.NOW + timedelta(minutes=5),
        periods=(
            AcademicPeriod(
                "mp1",
                "marking_period",
                "Marking Period 1",
                date(2026, 9, 1),
                date(2026, 11, 8),
                None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                "mp2",
                "marking_period",
                "Marking Period 2",
                date(2026, 11, 9),
                date(2027, 1, 22),
                None,
                sequence=2,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(workspace, calendar, expected_current_revision=1)
    rebuild_academic_catalog(workspace)
    try:
        nav.current_period()
    except NavigationScopeUnavailable:
        pass
    else:
        raise AssertionError("Changed academic calendar was silently retained.")
    assert nav.current_period() is None
    periods = load_teacher_choices(period, scope="period", selected={"class": PRIMARY})
    assert len(periods) == 2 and {x.identity for x in periods} == {("mp1",), ("mp2",)}
    nav.choose_period("mp2")
    assert nav.current_period().label == "Marking Period 2"

    # Switching classes clears child context, including the selected period.
    nav.choose_class(OTHER)
    assert nav.session.active_student_id is None
    assert nav.session.active_grade_item_id is None
    assert nav.current_period() is None
    assert nav.current_class().class_id == OTHER
    nav.choose_class(PRIMARY)
    assert nav.session.active_grade_item_id is None
    assert nav.current_period() is None

    # Review/scope operations did not alter any selected source record; the
    # only post-snapshot modifications are intentional synthetic calendar seed.
    assert project_grade_items_review(workspace, PRIMARY).class_id == PRIMARY
    print("Meridian #123 11G populated installed domain acceptance passed.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    _installed()
    if args.root.exists() and any(args.root.iterdir()):
        raise RuntimeError("Installed smoke root must be initially empty.")
    args.root.mkdir(parents=True, exist_ok=True)
    workspace = _seed(args.root)
    _journey(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
