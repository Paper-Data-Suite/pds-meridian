"""Evidence Coverage / Sufficiency report for Meridian Issue #111 Slice 10.

The report is deliberately epistemic: it distinguishes exact Meridian evidence
states from attention-worthy absence.  In particular, a missing selected Grade
Item result is reported as "no represented result", never as proof that a
student failed to submit work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pds_core.academic_periods import AcademicPeriodRef, validate_academic_period_ref
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodGradeItemExplanation,
    AcademicPeriodProficiencyExplanation,
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
from meridian.class_standards_profile import (
    ClassStandardsProfileError,
    _capture_profile_state,
)
from meridian.grade_item_proficiency_explanation import (
    EvidenceSourceExplanation,
    ExplanationTraceError,
    ProvenanceStageExplanation,
)
from meridian.proficiency_mapping import proficiency_scale_reference
from meridian.report_export_roster import (
    ExportRosterObservation,
    export_roster_observation_sha256,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

_ATTENTION_ORDER: Final[tuple[str, ...]] = (
    "NO_CURRENT_JUDGMENT",
    "NO_PARTICIPATING_GRADE_ITEMS",
    "NO_REPRESENTED_GRADE_ITEM_RESULT",
    "INSUFFICIENT_EVIDENCE",
    "BELOW_PERIOD_MINIMUM",
    "BELOW_CONFIGURED_MINIMUM",
    "NO_PERFORMANCE_EVIDENCE",
    "RETURNED_BEFORE_FULL_REVIEW",
    "PRODUCER_REPORTED_MISSING_STATE",
    "PENDING_EVIDENCE",
    "UNMAPPED_EVIDENCE",
    "ATTEMPT_SELECTION_UNRESOLVED",
    "REASSESSMENT_UNRESOLVED",
    "EXCLUDED_EVIDENCE",
    "PERIOD_SCOPE_MISMATCH",
    "ONE_PARTICIPATING_SOURCE",
)
_ATTENTION_SET: Final[frozenset[str]] = frozenset(_ATTENTION_ORDER)


class EvidenceCoverageError(RuntimeError):
    """Base error for Evidence Coverage / Sufficiency reporting."""

    code = "evidence_coverage.error"


class EvidenceCoverageValidationError(EvidenceCoverageError, ValueError):
    code = "evidence_coverage.invalid"


class EvidenceCoverageSourceError(EvidenceCoverageError):
    code = "evidence_coverage.source_unavailable"


class EvidenceCoverageCurrentnessConflictError(EvidenceCoverageError):
    code = "evidence_coverage.currentness_conflict"


@dataclass(frozen=True, slots=True)
class EvidenceCoverageMissingTarget:
    """One roster/student reporting standard with no selected period result."""

    student_id: str
    standard_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        if not isinstance(self.standard_id, str) or not self.standard_id.strip():
            raise EvidenceCoverageValidationError("standard_id must be nonblank text.")
        object.__setattr__(self, "standard_id", self.standard_id.strip())


@dataclass(frozen=True, slots=True)
class _CoverageRow:
    student_id: str
    student_name: str
    standard_id: str
    standard_proficiency: str
    grade_item_id: str | None
    grade_item_title: str | None
    work_ids: tuple[str, ...]
    producers: tuple[str, ...]
    period_state: str
    period_calculated_count: int | None
    period_minimum: int | None
    performance_source_count: int | None
    source_minimum: int | None
    attention: tuple[str, ...]
    knowledge: str
    period_result_revision: int | None
    period_result_sha256: str | None
    grade_item_result_revision: int | None
    grade_item_result_sha256: str | None


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_current_evidence_coverage(
    workspace_root: str | Path,
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    generated_at: datetime | None = None,
    student_filter: tuple[str, ...] = (),
    standard_filter: tuple[str, ...] = (),
    grade_item_filter: tuple[str, ...] = (),
    attention_filter: tuple[str, ...] = (),
    producer_filter: tuple[str, ...] = (),
    attention_only: bool = False,
) -> TeacherReportPreview:
    """Build current evidence coverage from selected proficiency authority only."""

    root = Path(workspace_root)
    try:
        initial = _capture_profile_state(
            root,
            class_id=class_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
        )
    except ClassStandardsProfileError as error:
        raise EvidenceCoverageSourceError(
            "Evidence Coverage could not resolve the active reporting-standard scope."
        ) from error

    observation_map = {
        (item.student_id, item.standard_id): item for item in initial.observations
    }
    explanations: list[AcademicPeriodProficiencyExplanation] = []
    missing: list[EvidenceCoverageMissingTarget] = []
    student_ids = tuple(student.student_id for student in initial.roster.students)

    for student_id in student_ids:
        for standard_id in initial.standard_ids:
            observation = observation_map.get((student_id, standard_id))
            if observation is None:
                missing.append(EvidenceCoverageMissingTarget(student_id, standard_id))
                continue
            try:
                explanation = explain_academic_period_proficiency(
                    root,
                    AcademicPeriodProficiencyTraceTarget(
                        class_id=class_id,
                        school_year=target_period.school_year,
                        period_id=target_period.period_id,
                        student_id=student_id,
                        standard_id=standard_id,
                        selection="current",
                    ),
                )
            except ExplanationTraceError as error:
                raise EvidenceCoverageSourceError(
                    "A selected Academic Period proficiency result could not be "
                    "explained safely for Evidence Coverage."
                ) from error
            active_scale = proficiency_scale_reference(initial.scale)
            if (
                observation.calendar_revision != calendar_revision
                or observation.target_scale != active_scale
            ):
                raise EvidenceCoverageSourceError(
                    "Selected Academic Period proficiency does not use the active "
                    "report calendar/scale."
                )
            if (
                explanation.result_revision != observation.result_revision
                or explanation.result_sha256 != observation.result_sha256
            ):
                raise EvidenceCoverageCurrentnessConflictError(
                    "Selected Academic Period proficiency changed while Evidence "
                    "Coverage was being assembled."
                )
            explanations.append(explanation)

    preview = compose_evidence_coverage(
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        roster_observation=initial.roster,
        explanations=tuple(explanations),
        missing_targets=tuple(missing),
        generated_at=utc_now() if generated_at is None else generated_at,
        profile_policy_source=TeacherReportSourceReference(
            "grade_policy",
            (
                f"{initial.policy_reference.policy_id}:"
                f"r{initial.policy_reference.policy_revision}"
            ),
            initial.policy_reference.policy_sha256,
        ),
        profile_activation_source=TeacherReportSourceReference(
            "grade_policy_activation",
            (
                f"{initial.activation_reference.school_year}:"
                f"{initial.activation_reference.period_id}:"
                f"r{initial.activation_reference.activation_revision}"
            ),
            initial.activation_reference.activation_sha256,
        ),
        profile_scale_source=TeacherReportSourceReference(
            "proficiency_scale",
            (f"{initial.scale.scale_id}:r{initial.scale.scale_revision}"),
            proficiency_scale_reference(initial.scale).scale_sha256,
        ),
        student_filter=student_filter,
        standard_filter=standard_filter,
        grade_item_filter=grade_item_filter,
        attention_filter=attention_filter,
        producer_filter=producer_filter,
        attention_only=attention_only,
    )

    try:
        final = _capture_profile_state(
            root,
            class_id=class_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
        )
    except ClassStandardsProfileError as error:
        raise EvidenceCoverageSourceError(
            "Evidence Coverage source state could not be revalidated."
        ) from error
    if final.witness_sha256 != initial.witness_sha256:
        raise EvidenceCoverageCurrentnessConflictError(
            "Evidence Coverage basis changed during report generation."
        )
    return preview


def compose_evidence_coverage(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    roster_observation: ExportRosterObservation,
    explanations: tuple[AcademicPeriodProficiencyExplanation, ...],
    missing_targets: tuple[EvidenceCoverageMissingTarget, ...],
    generated_at: datetime,
    profile_policy_source: TeacherReportSourceReference | None = None,
    profile_activation_source: TeacherReportSourceReference | None = None,
    profile_scale_source: TeacherReportSourceReference | None = None,
    student_filter: tuple[str, ...] = (),
    standard_filter: tuple[str, ...] = (),
    grade_item_filter: tuple[str, ...] = (),
    attention_filter: tuple[str, ...] = (),
    producer_filter: tuple[str, ...] = (),
    attention_only: bool = False,
) -> TeacherReportPreview:
    """Compose a deterministic evidence-attention report from exact explanations."""

    checked_class = _identifier(class_id, "class_id")
    checked_period = validate_academic_period_ref(target_period)
    checked_calendar = _positive_int(calendar_revision, "calendar_revision")
    if roster_observation.class_id != checked_class:
        raise EvidenceCoverageValidationError(
            "roster observation must match report class."
        )
    if roster_observation.source_fields != ("roster.display_name",):
        raise EvidenceCoverageValidationError(
            "Evidence Coverage uses only bounded roster display names."
        )
    roster_names = {
        item.student_id: item.values[0].value for item in roster_observation.students
    }

    requested_students = _identifiers(student_filter, "student_filter")
    requested_standards = _text_values(standard_filter, "standard_filter")
    requested_items = _identifiers(grade_item_filter, "grade_item_filter")
    requested_attention = _attention_values(attention_filter)
    requested_producers = _identifiers(producer_filter, "producer_filter")

    rows: list[_CoverageRow] = []
    seen_targets: set[tuple[str, str]] = set()

    for explanation in explanations:
        _validate_explanation_scope(
            explanation,
            checked_class,
            checked_period,
            checked_calendar,
        )
        key = (explanation.student_id, explanation.standard_id)
        if key in seen_targets:
            raise EvidenceCoverageValidationError(
                "explanations must not duplicate student/standard identity."
            )
        seen_targets.add(key)
        if explanation.student_id not in roster_names:
            raise EvidenceCoverageValidationError(
                "explanation student is absent from the report roster."
            )
        rows.extend(
            _rows_from_explanation(
                explanation,
                roster_names[explanation.student_id],
            )
        )

    for missing in missing_targets:
        key = (missing.student_id, missing.standard_id)
        if key in seen_targets:
            raise EvidenceCoverageValidationError(
                "missing target duplicates a supplied current explanation."
            )
        if missing.student_id not in roster_names:
            raise EvidenceCoverageValidationError(
                "missing target student is absent from the report roster."
            )
        seen_targets.add(key)
        rows.append(
            _CoverageRow(
                student_id=missing.student_id,
                student_name=roster_names[missing.student_id],
                standard_id=missing.standard_id,
                standard_proficiency="No current judgment",
                grade_item_id=None,
                grade_item_title=None,
                work_ids=(),
                producers=(),
                period_state="no_current_judgment",
                period_calculated_count=None,
                period_minimum=None,
                performance_source_count=None,
                source_minimum=None,
                attention=("NO_CURRENT_JUDGMENT",),
                knowledge=(
                    "No current selected Academic Period proficiency result exists "
                    "for this reporting standard. This absence does not establish "
                    "submission or review status; a result may simply not yet be "
                    "represented or selected in Meridian."
                ),
                period_result_revision=None,
                period_result_sha256=None,
                grade_item_result_revision=None,
                grade_item_result_sha256=None,
            )
        )

    filtered = [
        row
        for row in rows
        if _row_matches(
            row,
            student_filter=requested_students,
            standard_filter=requested_standards,
            grade_item_filter=requested_items,
            attention_filter=requested_attention,
            producer_filter=requested_producers,
            attention_only=attention_only,
        )
    ]
    filtered.sort(
        key=lambda item: (
            item.student_id,
            item.standard_id,
            item.grade_item_id or "",
            item.work_ids,
            item.attention,
        )
    )

    report_rows = tuple(
        TeacherReportRow(
            f"coverage_{index:05d}",
            (
                row.student_id,
                row.student_name,
                row.standard_id,
                row.standard_proficiency,
                row.grade_item_id,
                row.grade_item_title,
                ", ".join(row.work_ids) or None,
                ", ".join(row.producers) or None,
                row.period_state,
                _optional_int(row.period_calculated_count),
                _optional_int(row.period_minimum),
                _optional_int(row.performance_source_count),
                _optional_int(row.source_minimum),
                ", ".join(row.attention),
                row.knowledge,
            ),
        )
        for index, row in enumerate(filtered, start=1)
    )

    source_map: dict[tuple[str, str], TeacherReportSourceReference] = {}
    for source in (
        profile_policy_source,
        profile_activation_source,
        profile_scale_source,
        TeacherReportSourceReference(
            "roster_observation",
            "display_names",
            export_roster_observation_sha256(roster_observation),
        ),
    ):
        if source is not None:
            _add_source(source_map, source)

    explanation_lookup = {
        (item.student_id, item.standard_id): item for item in explanations
    }
    for row in filtered:
        source_explanation = explanation_lookup.get((row.student_id, row.standard_id))
        if source_explanation is None:
            continue
        _add_source(
            source_map,
            TeacherReportSourceReference(
                "academic_period_proficiency_result",
                (
                    f"{row.student_id}|{row.standard_id}|r{source_explanation.result_revision}"
                ),
                source_explanation.result_sha256,
            ),
        )
        for grade_item in source_explanation.grade_items:
            nested = grade_item.nested_grade_item_explanation
            if nested is None:
                continue
            if row.grade_item_id not in {None, nested.grade_item_id}:
                continue
            _add_source(
                source_map,
                TeacherReportSourceReference(
                    "standard_proficiency_result",
                    (
                        f"{nested.grade_item_id}|{nested.student_id}|"
                        f"{nested.standard_id}|r{nested.result_revision}"
                    ),
                    nested.result_sha256,
                ),
            )

    attention_rows = sum(row.attention != ("COMPLETE",) for row in filtered)
    no_current = sum("NO_CURRENT_JUDGMENT" in row.attention for row in filtered)
    missing_result = sum(
        "NO_REPRESENTED_GRADE_ITEM_RESULT" in row.attention for row in filtered
    )
    returned = sum("RETURNED_BEFORE_FULL_REVIEW" in row.attention for row in filtered)
    diagnostics: list[TeacherReportDiagnostic] = []
    if no_current:
        diagnostics.append(
            TeacherReportDiagnostic(
                "evidence_coverage.no_current_judgment",
                "info",
                f"{no_current} rows have no current selected standard judgment.",
            )
        )
    if missing_result:
        diagnostics.append(
            TeacherReportDiagnostic(
                "evidence_coverage.no_represented_grade_item_result",
                "info",
                (
                    f"{missing_result} rows expected a Grade Item result but have no "
                    "represented result; this is not proof of non-submission."
                ),
            )
        )
    if returned:
        diagnostics.append(
            TeacherReportDiagnostic(
                "evidence_coverage.returned_before_full_review",
                "info",
                (
                    f"{returned} rows include producer state "
                    "returned_without_full_review."
                ),
            )
        )

    return compose_teacher_report_preview(
        report_kind="evidence_coverage",
        title="Evidence Coverage / Missing & Incomplete Evidence",
        class_id=checked_class,
        target_period=checked_period,
        calendar_revision=checked_calendar,
        source_references=tuple(source_map.values()),
        generated_at=generated_at,
        summary=(
            f"Rows shown: {len(filtered)}.",
            f"Rows needing attention: {attention_rows}.",
            (
                "Absence is reported as no represented result/current judgment; "
                "Meridian does not convert absence into a claim of non-submission."
            ),
            (
                "Configured minimums are reported exactly when present; a thin "
                "evidence count is not called insufficient unless the stored policy "
                "or result state supports that conclusion."
            ),
        ),
        columns=(
            TeacherReportColumn("student_id", "Student ID"),
            TeacherReportColumn("student_name", "Student"),
            TeacherReportColumn("standard", "Standard"),
            TeacherReportColumn("standard_proficiency", "Current Proficiency"),
            TeacherReportColumn("grade_item", "Grade Item"),
            TeacherReportColumn("grade_item_title", "Grade Item Title"),
            TeacherReportColumn("work", "Work"),
            TeacherReportColumn("producer", "Producer"),
            TeacherReportColumn("period_state", "Coverage State"),
            TeacherReportColumn(
                "period_calculated_items",
                "Calculated Grade Items",
            ),
            TeacherReportColumn("period_minimum", "Period Minimum"),
            TeacherReportColumn(
                "performance_sources",
                "Performance Sources",
            ),
            TeacherReportColumn("source_minimum", "Source Minimum"),
            TeacherReportColumn("attention", "Attention"),
            TeacherReportColumn("knowledge", "What Meridian Knows"),
        ),
        rows=report_rows,
        diagnostics=diagnostics,
    )


def grade_item_attention_flags(
    item: AcademicPeriodGradeItemExplanation,
) -> tuple[str, ...]:
    """Return exact attention flags for one period Grade Item explanation."""

    flags: set[str] = set()
    if item.status == "missing_result":
        flags.add("NO_REPRESENTED_GRADE_ITEM_RESULT")
    elif item.status == "insufficient_evidence":
        flags.add("INSUFFICIENT_EVIDENCE")
    elif item.status == "period_scope_mismatch":
        flags.add("PERIOD_SCOPE_MISMATCH")

    nested = item.nested_grade_item_explanation
    if nested is not None:
        calculation = nested.calculation
        minimum = nested.policy.minimum_performance_observations
        if calculation.performance_observation_count < minimum:
            flags.add("BELOW_CONFIGURED_MINIMUM")
        if calculation.performance_observation_count == 0:
            flags.add("NO_PERFORMANCE_EVIDENCE")
        elif calculation.performance_observation_count == 1:
            flags.add("ONE_PARTICIPATING_SOURCE")
        for reason in calculation.insufficiency_reasons:
            if reason.kind == "below_minimum_performance_observations":
                flags.add("BELOW_CONFIGURED_MINIMUM")
            elif reason.kind == "no_performance_evidence":
                flags.add("NO_PERFORMANCE_EVIDENCE")
        for evidence in nested.evidence:
            flags.update(evidence_source_attention_flags(evidence))

    return _ordered_attention(flags)


def evidence_source_attention_flags(
    evidence: EvidenceSourceExplanation,
) -> tuple[str, ...]:
    """Project contract-backed evidence states without opening raw student work."""

    flags: set[str] = set()
    if evidence.native_state_code == "returned_without_full_review":
        flags.add("RETURNED_BEFORE_FULL_REVIEW")
    if evidence.native_state_code in {"missing", "missing_submission"}:
        flags.add("PRODUCER_REPORTED_MISSING_STATE")
    if evidence.aggregation_status == "excluded":
        flags.add("EXCLUDED_EVIDENCE")
    if evidence.mapping_status in {"unmapped", "unsupported"}:
        flags.add("UNMAPPED_EVIDENCE")
    if evidence.exclusion_reason == "attempt_selection_unresolved":
        flags.add("ATTEMPT_SELECTION_UNRESOLVED")
    if evidence.exclusion_reason == "reassessment_unresolved":
        flags.add("REASSESSMENT_UNRESOLVED")

    eligibility = _stage_details(evidence.stages, "eligibility")
    if eligibility.get("disposition") == "pending":
        flags.add("PENDING_EVIDENCE")
    return _ordered_attention(flags)


def _rows_from_explanation(
    explanation: AcademicPeriodProficiencyExplanation,
    student_name: str,
) -> list[_CoverageRow]:
    standard_label = _standard_label(explanation)
    period_minimum = explanation.policy.minimum_calculated_results
    calculated_count = explanation.calculation.calculated_result_count
    period_below_minimum = calculated_count < period_minimum

    if not explanation.grade_items:
        flags = {"NO_PARTICIPATING_GRADE_ITEMS"}
        if period_below_minimum:
            flags.add("BELOW_PERIOD_MINIMUM")
        return [
            _CoverageRow(
                student_id=explanation.student_id,
                student_name=student_name,
                standard_id=explanation.standard_id,
                standard_proficiency=standard_label,
                grade_item_id=None,
                grade_item_title=None,
                work_ids=(),
                producers=(),
                period_state=explanation.calculation.status,
                period_calculated_count=calculated_count,
                period_minimum=period_minimum,
                performance_source_count=None,
                source_minimum=None,
                attention=_ordered_attention(flags),
                knowledge=(
                    "The current selected Academic Period result contains no Grade "
                    "Item candidates for this standard."
                ),
                period_result_revision=explanation.result_revision,
                period_result_sha256=explanation.result_sha256,
                grade_item_result_revision=None,
                grade_item_result_sha256=None,
            )
        ]

    result: list[_CoverageRow] = []
    for item in explanation.grade_items:
        flags = set(grade_item_attention_flags(item))
        if period_below_minimum:
            flags.add("BELOW_PERIOD_MINIMUM")
        if not flags:
            flags.add("COMPLETE")

        work_ids = tuple(
            sorted(
                f"{membership.module_id}:{membership.work_id}"
                for membership in item.memberships
            )
        )
        producers = tuple(
            sorted({membership.module_id for membership in item.memberships})
        )
        nested = item.nested_grade_item_explanation
        performance_count = (
            None if nested is None else nested.calculation.performance_observation_count
        )
        source_minimum = (
            None if nested is None else nested.policy.minimum_performance_observations
        )
        grade_item_result_revision = None if nested is None else nested.result_revision
        grade_item_result_sha256 = None if nested is None else nested.result_sha256
        result.append(
            _CoverageRow(
                student_id=explanation.student_id,
                student_name=student_name,
                standard_id=explanation.standard_id,
                standard_proficiency=standard_label,
                grade_item_id=item.grade_item.grade_item_id,
                grade_item_title=item.grade_item.title,
                work_ids=work_ids,
                producers=producers,
                period_state=item.status,
                period_calculated_count=calculated_count,
                period_minimum=period_minimum,
                performance_source_count=performance_count,
                source_minimum=source_minimum,
                attention=_ordered_attention(flags),
                knowledge=_knowledge_for_item(item),
                period_result_revision=explanation.result_revision,
                period_result_sha256=explanation.result_sha256,
                grade_item_result_revision=grade_item_result_revision,
                grade_item_result_sha256=grade_item_result_sha256,
            )
        )
    return result


def _knowledge_for_item(item: AcademicPeriodGradeItemExplanation) -> str:
    if item.status == "missing_result":
        return (
            "The selected Academic Period result expected this Grade Item but "
            "contains no Grade Item proficiency result. Meridian cannot distinguish "
            "non-submission from incomplete/unrepresented review from that absence."
        )
    if item.status == "period_scope_mismatch":
        reason = item.period_scope_mismatch_reason or "unspecified"
        return (
            "The Grade Item is represented but is outside the exact Academic "
            f"Period scope ({reason})."
        )
    nested = item.nested_grade_item_explanation
    if nested is None:
        return (
            "The selected Academic Period result represents this Grade Item without "
            "a nested Grade Item proficiency explanation."
        )
    facts = [
        (
            f"Grade Item proficiency is {nested.calculation.status}; "
            f"performance sources={nested.calculation.performance_observation_count}; "
            f"configured minimum={nested.policy.minimum_performance_observations}."
        )
    ]
    native_states = sorted(
        {
            evidence.native_state_code
            for evidence in nested.evidence
            if evidence.native_state_code is not None
        }
    )
    if native_states:
        facts.append("Producer/native states: " + ", ".join(native_states) + ".")
    pending = sum(
        _stage_details(evidence.stages, "eligibility").get("disposition") == "pending"
        for evidence in nested.evidence
    )
    if pending:
        facts.append(f"Pending eligibility sources={pending}.")
    return " ".join(facts)


def _standard_label(explanation: AcademicPeriodProficiencyExplanation) -> str:
    level_id = explanation.calculation.proficiency_level_id
    if level_id is None:
        return "Insufficient evidence"
    for level in explanation.scale.levels:
        if level.level_id == level_id:
            return level.label
    raise EvidenceCoverageValidationError(
        "Selected Academic Period proficiency level is absent from its exact scale."
    )


def _stage_details(
    stages: tuple[ProvenanceStageExplanation, ...],
    name: str,
) -> dict[str, str]:
    matching = [stage for stage in stages if stage.name == name]
    if len(matching) > 1:
        raise EvidenceCoverageValidationError(
            "Evidence provenance contains duplicate stage names."
        )
    if not matching:
        return {}
    return {
        field.key: "" if field.value is None else str(field.value)
        for field in matching[0].details
    }


def _validate_explanation_scope(
    value: AcademicPeriodProficiencyExplanation,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> None:
    if not isinstance(value, AcademicPeriodProficiencyExplanation):
        raise EvidenceCoverageValidationError(
            "explanations must contain AcademicPeriodProficiencyExplanation values."
        )
    if value.class_id != class_id:
        raise EvidenceCoverageValidationError("explanation class scope mismatch.")
    if (
        value.target_period.school_year != target_period.school_year
        or value.target_period.period_id != target_period.period_id
        or value.target_period.calendar_revision != calendar_revision
    ):
        raise EvidenceCoverageValidationError(
            "explanation Academic Period scope mismatch."
        )


def _row_matches(
    row: _CoverageRow,
    *,
    student_filter: tuple[str, ...],
    standard_filter: tuple[str, ...],
    grade_item_filter: tuple[str, ...],
    attention_filter: tuple[str, ...],
    producer_filter: tuple[str, ...],
    attention_only: bool,
) -> bool:
    if student_filter and row.student_id not in student_filter:
        return False
    if standard_filter and row.standard_id not in standard_filter:
        return False
    if grade_item_filter and row.grade_item_id not in grade_item_filter:
        return False
    if attention_filter and not set(attention_filter).intersection(row.attention):
        return False
    if producer_filter and not set(producer_filter).intersection(row.producers):
        return False
    if attention_only and row.attention == ("COMPLETE",):
        return False
    return True


def _ordered_attention(values: set[str]) -> tuple[str, ...]:
    unknown = values - _ATTENTION_SET - {"COMPLETE"}
    if unknown:
        raise EvidenceCoverageValidationError(
            f"unsupported Evidence Coverage attention state: {sorted(unknown)!r}."
        )
    if not values:
        return ("COMPLETE",)
    if values == {"COMPLETE"}:
        return ("COMPLETE",)
    values.discard("COMPLETE")
    return tuple(item for item in _ATTENTION_ORDER if item in values)


def _attention_values(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(item.strip().upper() for item in values)
    unknown = set(normalized) - _ATTENTION_SET - {"COMPLETE"}
    if unknown:
        raise EvidenceCoverageValidationError(
            f"attention_filter contains unsupported values: {sorted(unknown)!r}."
        )
    return tuple(sorted(set(normalized)))


def _identifiers(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    result = tuple(_identifier(item, label) for item in values)
    if len(set(result)) != len(result):
        raise EvidenceCoverageValidationError(f"{label} must not contain duplicates.")
    return tuple(sorted(result))


def _text_values(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    result = tuple(item.strip() for item in values)
    if any(not item for item in result):
        raise EvidenceCoverageValidationError(f"{label} values must be nonblank.")
    if len(set(result)) != len(result):
        raise EvidenceCoverageValidationError(f"{label} must not contain duplicates.")
    return tuple(sorted(result))


def _identifier(value: str, label: str) -> str:
    try:
        return validate_identifier(value, field_name=label)
    except IdentifierValidationError as error:
        raise EvidenceCoverageValidationError(str(error)) from error


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise EvidenceCoverageValidationError(f"{label} must be a positive integer.")
    return value


def _optional_int(value: int | None) -> str | None:
    return None if value is None else str(value)


def _add_source(
    target: dict[tuple[str, str], TeacherReportSourceReference],
    source: TeacherReportSourceReference,
) -> None:
    key = (source.source_kind, source.source_id)
    existing = target.get(key)
    if existing is not None and existing != source:
        raise EvidenceCoverageValidationError(
            "Evidence Coverage source identity resolves to conflicting digests."
        )
    target[key] = source


__all__ = [
    "EvidenceCoverageCurrentnessConflictError",
    "EvidenceCoverageError",
    "EvidenceCoverageMissingTarget",
    "EvidenceCoverageSourceError",
    "EvidenceCoverageValidationError",
    "build_current_evidence_coverage",
    "compose_evidence_coverage",
    "evidence_source_attention_flags",
    "grade_item_attention_flags",
]
