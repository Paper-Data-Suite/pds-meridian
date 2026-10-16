"""Teacher-authored benchmark annotations without rewriting protected evidence.

Issue #117 Slice 6: render explicit instructional decisions onto an existing
verified benchmark report, then save through the immutable plan store. This
service never discovers, projects, reads, or opens producer evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.benchmark_analysis import (
    BenchmarkInstructionalGroup,
    InstructionalResponse,
    StandardInterpretation,
    TargetedInstructionResult,
)
from meridian.benchmark_plan_storage import (
    BENCHMARK_PLAN_RECORD_TYPE,
    BENCHMARK_PLAN_SCHEMA_VERSION,
    BenchmarkPlanConflictError,
    BenchmarkPlanNotFoundError,
    BenchmarkPlanRevision,
    BenchmarkPlanWriteResult,
    load_latest_benchmark_plan_revision,
    write_benchmark_plan_revision,
)
from meridian.teacher_report import (
    TeacherReportPreview,
    TeacherReportRow,
    compose_teacher_report_preview,
    validate_teacher_report_preview,
)


class BenchmarkPlanAuthoringError(ValueError):
    """An incomplete or ungrounded teacher planning decision."""

    code = "benchmark_plan.authoring_invalid"


class BenchmarkPlanSourceChangedError(BenchmarkPlanAuthoringError):
    """The currently selected evidence no longer matches a saved plan."""

    code = "benchmark_plan.source_changed"


TeacherStandardJudgment: TypeAlias = StandardInterpretation
_PLAN_PREFIX = "zz_plan_"
_COLUMNS = (
    "section",
    "subject",
    "metric",
    "value",
    "denominator",
    "semantics",
    "teacher_authored",
)
_SECTIONS = (
    "1. Assessment Data",
    "2. Standards and Item Analysis",
    "3. Instructional Response",
    "4. Results from Targeted Instruction",
)


def _text(value: str, field: str, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise BenchmarkPlanAuthoringError(f"{field} must be text.")
    if value != value.strip() or "\x00" in value or len(value) > 20_000:
        raise BenchmarkPlanAuthoringError(f"{field} must be bounded, trimmed text.")
    if required and not value:
        raise BenchmarkPlanAuthoringError(f"{field} is required.")
    return value


def _identifier(value: str, field: str) -> str:
    try:
        return validate_identifier(value)
    except (IdentifierValidationError, TypeError) as error:
        raise BenchmarkPlanAuthoringError(f"{field} is invalid.") from error


@dataclass(frozen=True, slots=True)
class TeacherStandardAssessment:
    """An explicit judgment; never a computed proficiency classification."""

    standard_id: str
    judgment: TeacherStandardJudgment
    basis: str
    comparable_evidence_confirmed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "standard_id", _text(self.standard_id, "standard_id", required=True)
        )
        if self.judgment not in {"strong", "challenging", "unclassified"}:
            raise BenchmarkPlanAuthoringError("standard judgment is invalid.")
        object.__setattr__(self, "basis", _text(self.basis, "basis"))
        if type(self.comparable_evidence_confirmed) is not bool:
            raise BenchmarkPlanAuthoringError(
                "comparable evidence confirmation must be boolean."
            )
        if self.judgment != "unclassified" and (
            not self.comparable_evidence_confirmed or not self.basis
        ):
            raise BenchmarkPlanAuthoringError(
                "Strong/challenging judgments require an explicit basis and "
                "teacher confirmation of comparable evidence."
            )


@dataclass(frozen=True, slots=True)
class BenchmarkTeacherAnnotations:
    """All teacher-entered interpretations for one complete plan revision."""

    interpretation: str = ""
    standards: tuple[TeacherStandardAssessment, ...] = ()
    groups: tuple[BenchmarkInstructionalGroup, ...] = ()
    responses: tuple[InstructionalResponse, ...] = ()
    follow_up: TargetedInstructionResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interpretation", _text(self.interpretation, "interpretation")
        )
        for field, values, kind, limit in (
            ("standards", self.standards, TeacherStandardAssessment, 128),
            ("groups", self.groups, BenchmarkInstructionalGroup, 40),
            ("responses", self.responses, InstructionalResponse, 80),
        ):
            if not isinstance(values, tuple) or len(values) > limit or any(
                not isinstance(value, kind) for value in values
            ):
                raise BenchmarkPlanAuthoringError(f"{field} has invalid entries.")
        if self.follow_up is not None and not isinstance(
            self.follow_up, TargetedInstructionResult
        ):
            raise BenchmarkPlanAuthoringError("follow_up is invalid.")
        for field, ids in (
            ("standards", tuple(value.standard_id for value in self.standards)),
            ("groups", tuple(value.group_id for value in self.groups)),
            ("responses", tuple(value.response_id for value in self.responses)),
        ):
            if len(ids) != len(set(ids)):
                raise BenchmarkPlanAuthoringError(
                    f"{field} contain duplicate identities."
                )


def _baseline_rows(report: TeacherReportPreview) -> tuple[TeacherReportRow, ...]:
    """Discard only previously authored rows and replaced empty placeholders."""
    return tuple(row for row in report.rows if not row.row_id.startswith(_PLAN_PREFIX))


def _evidence_rows(report: TeacherReportPreview) -> tuple[TeacherReportRow, ...]:
    """Compare source-derived rows, excluding replaceable empty-plan prompts."""
    return tuple(
        row
        for row in _baseline_rows(report)
        if not (
            (row.values[0] == _SECTIONS[2] and row.values[2] == "No response recorded")
            or (
                row.values[0] == _SECTIONS[3]
                and row.values[2] == "No reassessment recorded"
            )
        )
    )


def compose_teacher_benchmark_plan(
    report: TeacherReportPreview,
    annotations: BenchmarkTeacherAnnotations,
    *,
    roster_student_ids: tuple[str, ...],
) -> TeacherReportPreview:
    """Create a new preview, leaving native evidence and source hashes unchanged.

    Roster IDs come from Core's verified class roster at the caller boundary;
    this authoring service uses them for referential validation only.
    """
    original = validate_teacher_report_preview(report)
    if original.report_kind != "benchmark_analysis_instructional_response":
        raise BenchmarkPlanAuthoringError("Only Benchmark Report 9 can be annotated.")
    if tuple(column.column_id for column in original.columns) != _COLUMNS:
        raise BenchmarkPlanAuthoringError("The benchmark column contract changed.")
    if not isinstance(annotations, BenchmarkTeacherAnnotations):
        raise BenchmarkPlanAuthoringError("annotations must be a complete typed draft.")
    if not isinstance(roster_student_ids, tuple):
        raise BenchmarkPlanAuthoringError("A verified roster tuple is required.")
    roster = {_identifier(item, "roster student") for item in roster_student_ids}
    if len(roster) != len(roster_student_ids):
        raise BenchmarkPlanAuthoringError("Roster contains duplicate identities.")
    base_rows = _baseline_rows(original)
    present_sections = {row.values[0] for row in original.rows}
    if _SECTIONS[0] not in present_sections:
        raise BenchmarkPlanAuthoringError(
            "The benchmark assessment section is missing."
        )
    known_standards = {
        row.values[1]
        for row in base_rows
        if row.values[0] == _SECTIONS[1]
        and row.values[2] not in {"Difficult item", "Patterns and observations"}
    }
    for judgment in annotations.standards:
        if judgment.standard_id not in known_standards:
            raise BenchmarkPlanAuthoringError(
                "A standard judgment must reference an observed benchmark standard."
            )
    for group in annotations.groups:
        if not set(group.student_ids).issubset(roster):
            raise BenchmarkPlanAuthoringError(
                "A planning group includes a student outside the class roster."
            )
    for response in annotations.responses:
        if not set(response.student_ids).issubset(roster):
            raise BenchmarkPlanAuthoringError(
                "A planning group includes a student outside the class roster."
            )
    if annotations.follow_up is not None and not set(
        annotations.follow_up.students_still_needing_support
    ).issubset(roster):
        raise BenchmarkPlanAuthoringError(
            "Follow-up includes a student outside the class roster."
        )

    rows = [
        row for row in base_rows
        if not (
            (annotations.responses and row.values[0] == _SECTIONS[2]
             and row.values[2] == "No response recorded")
            or (annotations.follow_up is not None and row.values[0] == _SECTIONS[3]
                and row.values[2] == "No reassessment recorded")
            or (annotations.interpretation and row.values[0] == _SECTIONS[1]
                and row.values[1] == "Teacher interpretation")
        )
    ]
    counter = 0

    def add(
        section: str,
        subject: str,
        metric: str,
        value: str | None,
        denominator: str | None,
        semantics: str,
    ) -> None:
        nonlocal counter
        counter += 1
        rows.append(
            TeacherReportRow(
                f"{_PLAN_PREFIX}{counter:05d}",
                (section, subject, metric, value, denominator, semantics, "yes"),
            )
        )

    if annotations.interpretation:
        add(
            _SECTIONS[1], "Teacher interpretation", "Patterns and observations",
            annotations.interpretation, None,
            "Teacher-authored interpretation; not a calculated result",
        )
    for judgment in sorted(annotations.standards, key=lambda item: item.standard_id):
        add(
            _SECTIONS[1], judgment.standard_id,
            f"Teacher judgment: {judgment.judgment.replace('_', ' ').title()}",
            judgment.basis or None, None,
            (
                "Teacher confirmed comparable evidence"
                if judgment.comparable_evidence_confirmed
                else "No comparable-evidence classification established"
            ),
        )
    for group in sorted(annotations.groups, key=lambda item: item.group_id):
        add(
            _SECTIONS[0], f"Optional group: {group.label}", "Members",
            f"{len(group.student_ids)} selected student(s)",
            f"roster={len(roster)}",
            f"Teacher-selected group; rationale={group.rationale}; "
            "does not change native proficiency",
        )
    for response in sorted(annotations.responses, key=lambda item: item.response_id):
        add(
            _SECTIONS[2], response.response_kind.replace("_", " ").title(),
            response.target, response.strategy_resource,
            f"students={len(response.student_ids)}",
            (
                f"status={response.status}; "
                f"planned={response.planned_date or 'not set'}; "
                f"reevaluate={response.reevaluation_date or 'not set'}; "
                f"rework={', '.join(response.rework_items) or 'none'}; "
                f"retest={', '.join(response.retest_targets) or 'none'}; "
                f"reflection={response.teacher_reflection or 'none'}"
            ),
        )
    follow_up = annotations.follow_up
    if follow_up is not None:
        add(
            _SECTIONS[3], follow_up.reassessment_tool,
            follow_up.reassessment_date.isoformat(), follow_up.follow_up_results,
            (
                "students_still_needing_support="
                f"{len(follow_up.students_still_needing_support)}"
            ),
            (
                "standards="
                f"{', '.join(follow_up.standards_needing_attention) or 'none'}; "
                f"additional_support={follow_up.additional_support_strategy}; "
                f"source={follow_up.follow_up_source_id or 'teacher-entered'}; "
                f"comparison_basis={follow_up.comparison_basis or 'not compared'}; "
                f"observations={follow_up.teacher_observations}; "
                "observed changes are not causally attributed to instruction"
            ),
        )

    # A revisited plan may have replaced the generated empty placeholders in
    # an earlier revision. Restore truthful empty sections when an author
    # clears previously authored responses or follow-up observations.
    if not any(row.values[0] == _SECTIONS[1] for row in rows):
        add(
            _SECTIONS[1], "Standards / items", "No analysis supplied", None,
            None, "No standard or item results were supplied by this assessment",
        )
    if not any(row.values[0] == _SECTIONS[2] for row in rows):
        add(
            _SECTIONS[2], "Teacher plan", "No response recorded", None,
            None, "No teacher-authored response recorded",
        )
    if not any(row.values[0] == _SECTIONS[3] for row in rows):
        add(
            _SECTIONS[3], "Follow-up", "No reassessment recorded", None,
            None, "No follow-up evidence or completion inferred",
        )

    return compose_teacher_report_preview(
        report_kind=original.report_kind,
        title=original.title,
        class_id=original.class_id,
        target_period=original.target_period,
        calendar_revision=original.calendar_revision,
        source_references=original.source_references,
        generated_at=original.generated_at,
        summary=original.summary,
        columns=original.columns,
        rows=rows,
        diagnostics=original.diagnostics,
    )


def save_teacher_benchmark_plan(
    workspace_root: str | Path,
    *,
    report: TeacherReportPreview,
    annotations: BenchmarkTeacherAnnotations,
    roster_student_ids: tuple[str, ...],
    plan_id: str,
    teacher_id: str,
    assessment_id: str,
    confirmation: str,
    expected_previous_revision_sha256: str | None = None,
    saved_at: datetime | None = None,
) -> BenchmarkPlanWriteResult:
    """Append an immutable revision only after explicit, source-bound confirmation.

    A missing previous digest means CREATE only, never silently update. A
    revision digest authorizes editing exactly the latest matching revision.
    The resulting currentness is conservative (unverified) until separately
    requalified against live academic and publication authority.
    """
    if confirmation != "SAVE PLAN":
        raise BenchmarkPlanAuthoringError(
            "Saving requires exact SAVE PLAN confirmation."
        )
    drafted = compose_teacher_benchmark_plan(
        report, annotations, roster_student_ids=roster_student_ids
    )
    plan_key = _identifier(plan_id, "plan_id")
    teacher_key = _identifier(teacher_id, "teacher_id")
    assessment_key = _identifier(assessment_id, "assessment_id")
    if not drafted.source_references:
        raise BenchmarkPlanAuthoringError(
            "A saved plan requires traceable assessment/report source references."
        )
    current_time = datetime.now(UTC) if saved_at is None else saved_at
    if not isinstance(current_time, datetime) or current_time.tzinfo is None:
        raise BenchmarkPlanAuthoringError("saved_at must be timezone-aware.")
    current_time = current_time.astimezone(UTC)

    try:
        latest = load_latest_benchmark_plan_revision(
            workspace_root, drafted.class_id, plan_key
        )
    except BenchmarkPlanNotFoundError:
        latest = None
    if latest is None:
        if expected_previous_revision_sha256 is not None:
            raise BenchmarkPlanConflictError(
                "No plan exists at the supplied predecessor revision."
            )
        previous = None
        revision_number = 1
        created = current_time
    else:
        if expected_previous_revision_sha256 != latest.revision_sha256:
            raise BenchmarkPlanConflictError(
                "The plan has changed. Reopen its latest revision before editing."
            )
        original = latest.revision
        if (
            original.teacher_id != teacher_key
            or original.assessment_id != assessment_key
            or original.report.target_period != drafted.target_period
            or original.report.calendar_revision != drafted.calendar_revision
            or original.report.title != drafted.title
            or original.report.columns != drafted.columns
            or original.report.summary != drafted.summary
            or original.report.diagnostics != drafted.diagnostics
            or original.report.source_references != drafted.source_references
            or _evidence_rows(original.report) != _evidence_rows(drafted)
        ):
            raise BenchmarkPlanSourceChangedError(
                "Saved plan and current benchmark sources disagree. "
                "Refresh before editing."
            )
        previous = latest.revision_sha256
        revision_number = original.plan_revision + 1
        created = original.created_at
    if current_time < created:
        raise BenchmarkPlanAuthoringError("Save time cannot precede plan creation.")
    revision = BenchmarkPlanRevision(
        BENCHMARK_PLAN_SCHEMA_VERSION,
        BENCHMARK_PLAN_RECORD_TYPE,
        plan_key,
        revision_number,
        teacher_key,
        drafted.class_id,
        assessment_key,
        created,
        current_time,
        True,
        "unverified",
        drafted,
        previous,
    )
    return write_benchmark_plan_revision(workspace_root, revision)


__all__ = (
    "BenchmarkPlanAuthoringError",
    "BenchmarkPlanSourceChangedError",
    "BenchmarkTeacherAnnotations",
    "TeacherStandardAssessment",
    "compose_teacher_benchmark_plan",
    "save_teacher_benchmark_plan",
)
