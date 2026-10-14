"""Benchmark analysis and teacher-authored instructional response report.

This module is a bounded extension of the common teacher-report framework.  It
does not calculate proficiency, alter academic state, or infer an intervention.
Callers supply already-selected native proficiency and producer-supported item
observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

BenchmarkResultStatus: TypeAlias = Literal[
    "valid",
    "missing_result",
    "not_assessed",
    "invalid_unresolved",
    "insufficient_evidence",
]
StandardInterpretation: TypeAlias = Literal["strong", "challenging", "unclassified"]
InterventionStatus: TypeAlias = Literal[
    "planned", "in_progress", "completed", "paused", "cancelled"
]


class BenchmarkAnalysisError(ValueError):
    code = "benchmark_analysis.invalid"


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise BenchmarkAnalysisError(f"{field} must be a string.")
    try:
        return validate_identifier(value)
    except IdentifierValidationError as error:
        raise BenchmarkAnalysisError(f"{field} must be a valid identifier.") from error


def _text(value: object, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise BenchmarkAnalysisError(f"{field} must be a string.")
    if value != value.strip() or "\x00" in value or len(value) > 20_000:
        raise BenchmarkAnalysisError(f"{field} is not bounded text.")
    if required and not value:
        raise BenchmarkAnalysisError(f"{field} must not be empty.")
    return value


def _ids(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    result = tuple(_identifier(item, field) for item in values)
    if result != tuple(sorted(set(result))):
        raise BenchmarkAnalysisError(f"{field} must be unique and sorted.")
    return result


def _references(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    result = tuple(_text(item, field) for item in values)
    if result != tuple(sorted(set(result))):
        raise BenchmarkAnalysisError(f"{field} must be unique and sorted.")
    return result


@dataclass(frozen=True, slots=True)
class BenchmarkStudentResult:
    student_id: str
    student_name: str
    expected: bool
    tested: bool
    result_status: BenchmarkResultStatus
    native_score: str | None = None
    selected_proficiency: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "student_id", _identifier(self.student_id, "student_id")
        )
        object.__setattr__(
            self, "student_name", _text(self.student_name, "student_name")
        )
        if type(self.expected) is not bool or type(self.tested) is not bool:
            raise BenchmarkAnalysisError("expected and tested must be boolean.")
        if self.result_status not in {
            "valid",
            "missing_result",
            "not_assessed",
            "invalid_unresolved",
            "insufficient_evidence",
        }:
            raise BenchmarkAnalysisError("result_status is invalid.")
        if self.result_status == "not_assessed" and self.tested:
            raise BenchmarkAnalysisError("a not-assessed student cannot be tested.")
        if self.result_status in {
            "invalid_unresolved",
            "insufficient_evidence",
        } and not self.tested:
            raise BenchmarkAnalysisError(
                "invalid or insufficient results require an observed test attempt."
            )
        if self.result_status != "valid" and (
            self.native_score is not None or self.selected_proficiency is not None
        ):
            raise BenchmarkAnalysisError(
                "non-valid results cannot invent score or proficiency values."
            )
        if self.native_score is not None:
            object.__setattr__(
                self, "native_score", _text(self.native_score, "native_score")
            )
        if self.selected_proficiency is not None:
            object.__setattr__(
                self,
                "selected_proficiency",
                _identifier(self.selected_proficiency, "selected_proficiency"),
            )


@dataclass(frozen=True, slots=True)
class BenchmarkInstructionalGroup:
    group_id: str
    label: str
    student_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_id", _identifier(self.group_id, "group_id"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        object.__setattr__(self, "student_ids", _ids(self.student_ids, "student_ids"))
        object.__setattr__(self, "rationale", _text(self.rationale, "rationale"))


@dataclass(frozen=True, slots=True)
class BenchmarkStandardObservation:
    standard_id: str
    assessed_students: int
    valid_results: int
    native_summary: str
    interpretation: StandardInterpretation = "unclassified"
    interpretation_basis: str | None = None
    comparable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "standard_id", _text(self.standard_id, "standard_id")
        )
        if type(self.assessed_students) is not int or self.assessed_students < 0:
            raise BenchmarkAnalysisError("assessed_students must be nonnegative.")
        if (
            type(self.valid_results) is not int
            or not 0 <= self.valid_results <= self.assessed_students
        ):
            raise BenchmarkAnalysisError(
                "valid_results must be between zero and assessed_students."
            )
        object.__setattr__(
            self, "native_summary", _text(self.native_summary, "native_summary")
        )
        if self.interpretation not in {"strong", "challenging", "unclassified"}:
            raise BenchmarkAnalysisError("standard interpretation is invalid.")
        if type(self.comparable) is not bool:
            raise BenchmarkAnalysisError("comparable must be boolean.")
        if self.interpretation != "unclassified":
            if not self.comparable or self.interpretation_basis is None:
                raise BenchmarkAnalysisError(
                    "classified standards require comparable evidence and an "
                    "explicit basis."
                )
        if self.interpretation_basis is not None:
            object.__setattr__(
                self,
                "interpretation_basis",
                _text(self.interpretation_basis, "interpretation_basis"),
            )


@dataclass(frozen=True, slots=True)
class BenchmarkItemObservation:
    item_id: str
    correct_responses: int
    incorrect_responses: int
    blank_responses: int = 0
    ambiguous_responses: int = 0
    standard_ids: tuple[str, ...] = ()
    question_type: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _text(self.item_id, "item_id"))
        for field in (
            "correct_responses",
            "incorrect_responses",
            "blank_responses",
            "ambiguous_responses",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise BenchmarkAnalysisError(f"{field} must be nonnegative.")
        object.__setattr__(
            self,
            "standard_ids",
            _references(self.standard_ids, "standard_ids"),
        )
        if self.question_type is not None:
            object.__setattr__(
                self, "question_type", _text(self.question_type, "question_type")
            )

    @property
    def valid_response_count(self) -> int:
        return self.correct_responses + self.incorrect_responses


@dataclass(frozen=True, slots=True)
class InstructionalResponse:
    response_id: str
    response_kind: Literal[
        "reteach", "revisit", "small_group", "enrichment", "extension"
    ]
    target: str
    student_ids: tuple[str, ...]
    strategy_resource: str
    planned_date: date | None = None
    reevaluation_date: date | None = None
    rework_items: tuple[str, ...] = ()
    retest_targets: tuple[str, ...] = ()
    status: InterventionStatus = "planned"
    teacher_reflection: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "response_id", _identifier(self.response_id, "response_id")
        )
        if self.response_kind not in {
            "reteach",
            "revisit",
            "small_group",
            "enrichment",
            "extension",
        }:
            raise BenchmarkAnalysisError("response_kind is invalid.")
        object.__setattr__(self, "target", _text(self.target, "target"))
        object.__setattr__(self, "student_ids", _ids(self.student_ids, "student_ids"))
        object.__setattr__(
            self,
            "strategy_resource",
            _text(self.strategy_resource, "strategy_resource"),
        )
        object.__setattr__(
            self, "rework_items", _references(self.rework_items, "rework_items")
        )
        object.__setattr__(
            self,
            "retest_targets",
            _references(self.retest_targets, "retest_targets"),
        )
        if self.status not in {
            "planned",
            "in_progress",
            "completed",
            "paused",
            "cancelled",
        }:
            raise BenchmarkAnalysisError("intervention status is invalid.")
        object.__setattr__(
            self,
            "teacher_reflection",
            _text(self.teacher_reflection, "teacher_reflection", required=False),
        )
        if (
            self.planned_date is not None
            and self.reevaluation_date is not None
            and self.reevaluation_date < self.planned_date
        ):
            raise BenchmarkAnalysisError(
                "reevaluation_date cannot precede planned_date."
            )


@dataclass(frozen=True, slots=True)
class TargetedInstructionResult:
    reassessment_tool: str
    reassessment_date: date
    follow_up_results: str
    students_still_needing_support: tuple[str, ...]
    standards_needing_attention: tuple[str, ...]
    additional_support_strategy: str
    teacher_observations: str
    follow_up_source_id: str | None = None
    comparison_basis: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reassessment_tool",
            _text(self.reassessment_tool, "reassessment_tool"),
        )
        object.__setattr__(
            self,
            "follow_up_results",
            _text(self.follow_up_results, "follow_up_results"),
        )
        object.__setattr__(
            self,
            "students_still_needing_support",
            _ids(self.students_still_needing_support, "students_still_needing_support"),
        )
        object.__setattr__(
            self,
            "standards_needing_attention",
            _references(
                self.standards_needing_attention,
                "standards_needing_attention",
            ),
        )
        object.__setattr__(
            self,
            "additional_support_strategy",
            _text(self.additional_support_strategy, "additional_support_strategy"),
        )
        object.__setattr__(
            self,
            "teacher_observations",
            _text(self.teacher_observations, "teacher_observations"),
        )
        if self.follow_up_source_id is not None:
            object.__setattr__(
                self,
                "follow_up_source_id",
                _identifier(self.follow_up_source_id, "follow_up_source_id"),
            )
            if self.comparison_basis is None:
                raise BenchmarkAnalysisError(
                    "an evidence-linked follow-up requires a comparison basis."
                )
        if self.comparison_basis is not None:
            object.__setattr__(
                self,
                "comparison_basis",
                _text(self.comparison_basis, "comparison_basis"),
            )


def compose_benchmark_analysis(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    assessment_id: str,
    assessment_title: str,
    proficiency_levels: tuple[str, ...],
    students: tuple[BenchmarkStudentResult, ...],
    source_references: tuple[TeacherReportSourceReference, ...],
    generated_at: datetime,
    groups: tuple[BenchmarkInstructionalGroup, ...] = (),
    standards: tuple[BenchmarkStandardObservation, ...] = (),
    items: tuple[BenchmarkItemObservation, ...] = (),
    responses: tuple[InstructionalResponse, ...] = (),
    follow_up: TargetedInstructionResult | None = None,
    teacher_interpretation: str = "",
) -> TeacherReportPreview:
    """Compose the four-section planner from explicit, already-authorized facts."""
    assessment_id = _identifier(assessment_id, "assessment_id")
    assessment_title = _text(assessment_title, "assessment_title")
    levels = tuple(
        _identifier(item, "proficiency_levels") for item in proficiency_levels
    )
    if len(set(levels)) != len(levels):
        raise BenchmarkAnalysisError("proficiency_levels must be unique.")
    if not levels:
        raise BenchmarkAnalysisError("proficiency_levels must not be empty.")
    ordered_students = tuple(sorted(students, key=lambda item: item.student_id))
    if len({item.student_id for item in ordered_students}) != len(ordered_students):
        raise BenchmarkAnalysisError("students must not contain duplicate identities.")
    unknown = {
        item.selected_proficiency
        for item in ordered_students
        if item.selected_proficiency is not None
        and item.selected_proficiency not in levels
    }
    if unknown:
        raise BenchmarkAnalysisError(
            "selected proficiency must belong to the configured scale."
        )
    student_ids = {item.student_id for item in ordered_students}
    for group in groups:
        if not set(group.student_ids).issubset(student_ids):
            raise BenchmarkAnalysisError(
                "instructional groups must use roster students."
            )
    for response in responses:
        if not set(response.student_ids).issubset(student_ids):
            raise BenchmarkAnalysisError(
                "instructional responses must use roster students."
            )
    if follow_up is not None and not set(
        follow_up.students_still_needing_support
    ).issubset(student_ids):
        raise BenchmarkAnalysisError(
            "follow-up support students must be on the roster."
        )

    rows: list[TeacherReportRow] = []
    row_index = 0

    def add(
        section: str,
        subject: str,
        metric: str,
        value: str | None,
        denominator: str | None,
        semantics: str,
        *,
        authored: bool = False,
    ) -> None:
        nonlocal row_index
        row_index += 1
        rows.append(
            TeacherReportRow(
                f"planner_{row_index:05d}",
                (
                    section,
                    subject,
                    metric,
                    value,
                    denominator,
                    semantics,
                    "yes" if authored else "no",
                ),
            )
        )

    roster = len(ordered_students)
    expected = sum(item.expected for item in ordered_students)
    tested = sum(item.tested for item in ordered_students)
    valid = sum(item.result_status == "valid" for item in ordered_students)
    add(
        "1. Assessment Data",
        assessment_title,
        "Assessment ID",
        assessment_id,
        None,
        "Canonical assessment identity",
    )
    for metric, count, denominator in (
        ("Students on roster", roster, None),
        ("Students expected", expected, f"roster={roster}"),
        ("Students tested", tested, f"expected={expected}"),
        ("Students with a valid result", valid, f"tested={tested}"),
        (
            "Not assessed",
            sum(item.result_status == "not_assessed" for item in ordered_students),
            f"roster={roster}",
        ),
        (
            "Missing result",
            sum(item.result_status == "missing_result" for item in ordered_students),
            f"tested={tested}",
        ),
        (
            "Invalid or unresolved",
            sum(
                item.result_status == "invalid_unresolved" for item in ordered_students
            ),
            f"tested={tested}",
        ),
        (
            "Insufficient evidence",
            sum(
                item.result_status == "insufficient_evidence"
                for item in ordered_students
            ),
            f"tested={tested}",
        ),
    ):
        add(
            "1. Assessment Data",
            "Participation",
            metric,
            str(count),
            denominator,
            "Distinct count; missing values are not zero",
        )
    for level in levels:
        members = tuple(
            item.student_name
            for item in ordered_students
            if item.selected_proficiency == level
        )
        add(
            "1. Assessment Data",
            "Configured proficiency",
            level,
            ", ".join(members) or None,
            f"valid_results={valid}",
            f"Selected proficiency count={len(members)}; no ordinal averaging",
        )
    native_scores = sorted(
        {
            item.native_score
            for item in ordered_students
            if item.native_score is not None
        }
    )
    for native_score in native_scores:
        score_count = sum(
            item.native_score == native_score for item in ordered_students
        )
        add(
            "1. Assessment Data",
            "Native score distribution",
            native_score,
            str(score_count),
            f"valid_results={valid}",
            "Producer-native score text; no proficiency invented from score",
        )
    for group in sorted(groups, key=lambda item: item.group_id):
        names = [
            item.student_name
            for item in ordered_students
            if item.student_id in group.student_ids
        ]
        add(
            "1. Assessment Data",
            f"Optional group: {group.label}",
            "Members",
            ", ".join(names) or None,
            f"roster={roster}",
            group.rationale,
            authored=True,
        )

    for standard in sorted(standards, key=lambda item: item.standard_id):
        add(
            "2. Standards and Item Analysis",
            standard.standard_id,
            standard.interpretation.replace("_", " ").title(),
            standard.native_summary,
            (
                f"valid_results={standard.valid_results}; "
                f"assessed_students={standard.assessed_students}"
            ),
            standard.interpretation_basis
            or "Native standard evidence; no comparative classification",
        )
    difficult = sorted(
        (item for item in items if item.valid_response_count),
        key=lambda item: (
            -Decimal(item.incorrect_responses) / Decimal(item.valid_response_count),
            item.item_id,
        ),
    )[:5]
    for item in difficult:
        percent = (
            Decimal(item.incorrect_responses)
            * Decimal(100)
            / Decimal(item.valid_response_count)
        ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        add(
            "2. Standards and Item Analysis",
            item.item_id,
            "Difficult item",
            (
                f"{item.incorrect_responses}/{item.valid_response_count} "
                f"incorrect ({percent}%)"
            ),
            (
                f"valid_item_responses={item.valid_response_count}; "
                f"blanks={item.blank_responses}; "
                f"ambiguous={item.ambiguous_responses}"
            ),
            (
                f"type={item.question_type or 'not supplied'}; "
                f"standards={', '.join(item.standard_ids) or 'none supplied'}"
            ),
        )
    if teacher_interpretation:
        add(
            "2. Standards and Item Analysis",
            "Teacher interpretation",
            "Patterns and observations",
            _text(teacher_interpretation, "teacher_interpretation"),
            None,
            "Teacher-authored interpretation",
            authored=True,
        )

    for response in sorted(responses, key=lambda item: item.response_id):
        add(
            "3. Instructional Response",
            response.response_kind.replace("_", " ").title(),
            response.target,
            response.strategy_resource,
            f"students={len(response.student_ids)}",
            (
                f"status={response.status}; "
                f"planned={response.planned_date or 'not set'}; "
                f"reevaluate={response.reevaluation_date or 'not set'}; "
                f"rework={', '.join(response.rework_items) or 'none'}; "
                f"retest={', '.join(response.retest_targets) or 'none'}; "
                f"reflection={response.teacher_reflection or 'none'}"
            ),
            authored=True,
        )
    if not responses:
        add(
            "3. Instructional Response",
            "Teacher plan",
            "No response recorded",
            None,
            None,
            "A plan is optional and never inferred from evidence",
            authored=True,
        )

    if follow_up is None:
        add(
            "4. Results from Targeted Instruction",
            "Follow-up",
            "No reassessment recorded",
            None,
            None,
            "A saved plan does not imply implementation or completion",
            authored=True,
        )
    else:
        add(
            "4. Results from Targeted Instruction",
            follow_up.reassessment_tool,
            follow_up.reassessment_date.isoformat(),
            follow_up.follow_up_results,
            (
                "students_still_needing_support="
                f"{len(follow_up.students_still_needing_support)}"
            ),
            (
                "continued_standards="
                f"{', '.join(follow_up.standards_needing_attention) or 'none'}; "
                f"additional_support={follow_up.additional_support_strategy}; "
                f"source={follow_up.follow_up_source_id or 'teacher-entered'}; "
                f"comparison_basis={follow_up.comparison_basis or 'not compared'}; "
                f"observations={follow_up.teacher_observations}"
            ),
            authored=True,
        )

    diagnostics = (
        TeacherReportDiagnostic(
            "benchmark_analysis.noncausal_follow_up",
            "info",
            "Observed follow-up changes are not attributed causally to the "
            "intervention.",
        ),
        TeacherReportDiagnostic(
            "benchmark_analysis.teacher_plan_not_academic_state",
            "info",
            "Teacher-authored groups and plans do not change proficiency, Grades, "
            "or producer evidence.",
        ),
    )
    return compose_teacher_report_preview(
        report_kind="benchmark_analysis_instructional_response",
        title="Benchmark Analysis & Instructional Response Planner",
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        source_references=source_references,
        generated_at=generated_at,
        summary=(
            f"Assessment: {assessment_title} ({assessment_id}).",
            (
                f"Roster: {roster}; expected: {expected}; tested: {tested}; "
                f"valid results: {valid}."
            ),
            (
                "Native scores and selected proficiency are preserved; missing "
                "evidence is not converted to zero or a proficiency level."
            ),
            (
                "Optional groups, instructional responses, and follow-up "
                "observations are teacher-authored planning information, not "
                "official Grade or SIS records."
            ),
        ),
        columns=(
            TeacherReportColumn("section", "Section"),
            TeacherReportColumn("subject", "Subject"),
            TeacherReportColumn("metric", "Metric / Prompt"),
            TeacherReportColumn("value", "Value / Response"),
            TeacherReportColumn("denominator", "Denominator"),
            TeacherReportColumn("semantics", "Evidence / Interpretation"),
            TeacherReportColumn("teacher_authored", "Teacher Authored"),
        ),
        rows=tuple(rows),
        diagnostics=diagnostics,
    )


__all__ = [
    "BenchmarkAnalysisError",
    "BenchmarkInstructionalGroup",
    "BenchmarkItemObservation",
    "BenchmarkStandardObservation",
    "BenchmarkStudentResult",
    "InstructionalResponse",
    "TargetedInstructionResult",
    "compose_benchmark_analysis",
]
