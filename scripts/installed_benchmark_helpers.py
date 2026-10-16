"""Issue #117: installed ScoreForm/Quillan Report 9 teacher acceptance.

These routines extend the existing Issue #110 installed guided-evidence smoke.
They use the already published native manifest fixture; all Core/Meridian
academic records are stored through their public, digest-verified APIs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path
from pds_core.routing_models import ModuleWorkRef

from meridian.benchmark_plan_notes import load_benchmark_plan_notes
from meridian.benchmark_plan_storage import (
    list_benchmark_plan_revisions,
    load_benchmark_plan_revision,
    load_latest_benchmark_plan_revision,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_item_membership_storage import (
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.menu_reports import run_reports_menu
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
)
from meridian.proficiency_mapping_storage import (
    select_proficiency_scale_revision,
    write_proficiency_scale_revision,
)
from meridian.report_menu_execution import (
    LiveReportMenuExecutor,
    ReportMenuExecutionDependencies,
)
from meridian.teacher_report_render import render_teacher_report

_NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
_YEAR = "2026-2027"
_PERIOD = AcademicPeriodRef(_YEAR, "mp1")
_ITEM = "installed_benchmark_assessment"


def setup_installed_benchmark_records(
    workspace: Path, work: ModuleWorkRef, title: str
) -> None:
    """Persist and select authentic Core calendar and Meridian Grade Item state."""
    write_class_metadata(
        class_metadata_path(workspace, work.class_id),
        ClassMetadata(
            class_id=work.class_id,
            school_year=_YEAR,
            created_at=_NOW,
            updated_at=_NOW,
            module_details={},
        ),
    )
    write_academic_period_calendar(
        workspace,
        AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=_YEAR,
            calendar_revision=1,
            created_at=_NOW,
            updated_at=_NOW,
            periods=(
                AcademicPeriod(
                    period_id="mp1",
                    period_type="marking_period",
                    label="Marking Period 1",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 8),
                    parent_period_id=None,
                    sequence=1,
                    lifecycle="active",
                ),
            ),
        ),
        expected_current_revision=None,
    )
    grade = write_grade_item_revision(
        workspace,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=work.class_id,
            grade_item_id=_ITEM,
            grade_item_revision=1,
            supersedes_revision=None,
            title=title,
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=_NOW,
            revised_at=_NOW,
        ),
    ).stored
    select_grade_item_revision(
        workspace, work.class_id, _ITEM, 1,
        expected_current_revision=None,
    )
    write_grade_item_membership_revision(
        workspace,
        GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=work.class_id,
            grade_item_id=_ITEM,
            grade_item_revision=1,
            grade_item_revision_sha256=grade.revision_sha256,
            work_reference=GradeItemWorkReference(
                work=work,
                registration_revision=1,
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=_PERIOD, calendar_revision=1,
            ),
            actor_id="issue117_installed_teacher",
            rationale="Synthetic installed Report 9 acceptance",
            decided_at=_NOW,
        ),
    )
    select_grade_item_membership_revision(
        workspace, work.class_id, _ITEM, work, 1,
        expected_current_membership_revision=None,
    )
    # Report 9 requires one configured current class scale, but it never
    # manufactures student proficiency judgments from native producer results.
    write_proficiency_scale_revision(
        workspace,
        ProficiencyScale(
            schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
            record_type=PROFICIENCY_SCALE_RECORD_TYPE,
            class_id=work.class_id,
            scale_id="course_proficiency",
            scale_revision=1,
            supersedes_revision=None,
            title="Installed benchmark proficiency scale",
            description="Teacher-configured synthetic classroom levels.",
            levels=(
                ProficiencyLevel("developing", 1, "Developing", "Early evidence."),
                ProficiencyLevel("approaching", 2, "Approaching", "Partial evidence."),
                ProficiencyLevel("meeting", 3, "Meeting", "Meets the standard."),
                ProficiencyLevel("exceeding", 4, "Exceeding", "Extends the standard."),
            ),
            proficiency_threshold_level_id="meeting",
            actor=MappingActor("teacher", "issue117_teacher"),
            rationale=None,
            revised_at=_NOW,
        ),
    )
    select_proficiency_scale_revision(
        workspace, work.class_id, "course_proficiency", 1,
        expected_current_scale_revision=None,
    )
    # The catalog is disposable; rebuild after academic metadata changes.
    rebuild_academic_catalog(workspace)


class _ScriptedInput:
    def __init__(self, *answers: str) -> None:
        self._answers = iter(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._answers)


def run_installed_benchmark_teacher_journey(
    workspace: Path,
    work: ModuleWorkRef,
    diagnostics: DiagnosticsDependencies,
    *,
    publication_id: str,
) -> None:
    """Use actual Reports -> 9 -> P -> SAVE PLAN from installed packages."""
    scripted = _ScriptedInput(
        "9", "1",  # Reports, choose report details
        "1", "1", "1",  # Class, period, assessment
        "1", "p",  # Generate preview, open teacher planner
        "1",  # Create first plan
        "issue117_teacher", "Reteach evidence-backed claims.",
        "n", "n", "n", "n",  # No optional annotations yet
        "SAVE PLAN", "b", "b", "b", "b",
    )
    output = StringIO()
    run_reports_menu(
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
        executor=LiveReportMenuExecutor(
            ReportMenuExecutionDependencies(diagnostics=diagnostics)
        ),
    )
    rendered = output.getvalue()
    if "Local benchmark plan revision 1 saved." not in rendered:
        raise AssertionError(
            "Installed Report 9 did not complete the teacher's SAVE PLAN action. "
            "Check current publication, authorization and menu selection."
        )
    if "Benchmark Analysis" not in rendered:
        raise AssertionError("Report 9 teacher preview was not presented.")
    if publication_id in rendered or publication_id in "\n".join(scripted.prompts):
        raise AssertionError("Opaque publication identity leaked into teacher menus.")
    stored = load_latest_benchmark_plan_revision(
        workspace, work.class_id, f"benchmark_mp1_{_ITEM}"
    )
    if stored.revision.plan_revision != 1:
        raise AssertionError("Expected one immutable confirmed local plan revision.")
    notes = load_benchmark_plan_notes(workspace, stored)
    if notes is None or notes.interpretation != "Reteach evidence-backed claims.":
        raise AssertionError("Saved teacher annotations did not restore losslessly.")
    markdown = render_teacher_report(stored.revision.report, "markdown")
    headings = (
        "Assessment Data",
        "Standards and Item Analysis",
        "Instructional Response",
        "Results from Targeted Instruction",
    )
    if not all(heading in markdown.decode("utf-8") for heading in headings):
        raise AssertionError("Saved Report 9 is missing a required section.")
    if not any(
        reference.source_kind == "publication"
        for reference in stored.revision.report.source_references
    ):
        raise AssertionError("Report 9 lacks an authorized publication reference.")
    if any(
        reference.source_kind == "reporting_snapshot"
        for reference in stored.revision.report.source_references
    ):
        raise AssertionError("Report 9 incorrectly requires a ReportingSnapshot.")

    # A later reassessment belongs to a NEW immutable teacher-authored plan
    # revision. The original evidence and notes must remain reconstructible.
    follow_up_scripted = _ScriptedInput(
        "9", "1",  # Reports / benchmark report details.
        "1", "1", "1",  # Class / marking period / assessment.
        "1", "p",  # Current preview / teacher plan.
        "4",  # Edit saved revision; keep existing sections by default.
        "", "", "", "",  # Interpretation, judgments, groups, responses.
        "n",  # Replace the previously empty reassessment section.
        "y",  # Record new observed reassessment results.
        "Exit ticket", "2026-10-25",
        "Students cited more precise textual evidence after reteaching.",
        "1",  # One explicitly selected student still needs support.
        "",  # No unsupported claim about standard comparability.
        "Small-group evidence conference",
        "Continue brief source-evidence practice",
        "",  # Teacher observation, no invented evidence-source ID.
        "SAVE PLAN", "b", "b", "b", "b",
    )
    revised_output = StringIO()
    run_reports_menu(
        input_fn=follow_up_scripted,
        output=revised_output,
        clear_fn=lambda: None,
        executor=LiveReportMenuExecutor(
            ReportMenuExecutionDependencies(diagnostics=diagnostics)
        ),
    )
    rendered_revision = revised_output.getvalue()
    if "Local benchmark plan revision 2 saved." not in rendered_revision:
        raise AssertionError(
            "Installed Report 9 could not save a reassessment revision "
            "through the normal teacher menu."
        )
    if publication_id in rendered_revision or publication_id in "\n".join(
        follow_up_scripted.prompts
    ):
        raise AssertionError("An opaque publication ID appeared in teacher menus.")
    plan_id = f"benchmark_mp1_{_ITEM}"
    if list_benchmark_plan_revisions(workspace, work.class_id, plan_id) != (1, 2):
        raise AssertionError("Expected two and only two immutable plan revisions.")
    first = load_benchmark_plan_revision(workspace, work.class_id, plan_id, 1)
    latest = load_latest_benchmark_plan_revision(workspace, work.class_id, plan_id)
    if first.revision_sha256 != stored.revision_sha256:
        raise AssertionError("Original plan's immutable digest changed.")
    if load_benchmark_plan_notes(workspace, first) != notes:
        raise AssertionError("Reassessment changed historical teacher annotations.")
    restored = load_benchmark_plan_notes(workspace, latest)
    if restored is None or restored.follow_up is None:
        raise AssertionError("Reassessment notes were not restored from revision 2.")
    if restored.interpretation != notes.interpretation:
        raise AssertionError("Reassessment discarded the original interpretation.")
    if (
        restored.standards != notes.standards
        or restored.groups != notes.groups
        or restored.responses != notes.responses
    ):
        raise AssertionError("Existing instructional decisions did not survive edit.")
    follow_up = restored.follow_up
    if (
        follow_up.reassessment_tool != "Exit ticket"
        or follow_up.reassessment_date != date(2026, 10, 25)
        or follow_up.students_still_needing_support != ("student_alpha",)
        or follow_up.follow_up_source_id is not None
    ):
        raise AssertionError("Reassessment details were changed or invented.")
    if (
        latest.revision.report.source_references
        != stored.revision.report.source_references
    ):
        raise AssertionError("Revision changed authoritative assessment sources.")
    revision_markdown = render_teacher_report(latest.revision.report, "markdown")
    if b"Exit ticket" not in revision_markdown:
        raise AssertionError("Follow-up section missing from rendered teacher plan.")
