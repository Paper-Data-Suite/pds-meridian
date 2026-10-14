"""Marking-Period Readiness report for Meridian Issue #111 Slice 11.

This report is a bounded pre-close audit over existing Meridian authority.  It
never finalizes a Grade, asserts SIS readiness, creates attention, or writes to
an external system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyExplanation,
)
from meridian.conventional_grade_explanation import (
    ConventionalGradeBreakdownExplanation,
    ConventionalGradePreviewExplanation,
)
from meridian.current_grade_preview import CurrentGradePreviewExplanation
from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_preview_comparison import GradePreviewComparison
from meridian.grade_preview_explanation import GradePreviewExplanation
from meridian.grade_report_attention import (
    GradeReportAttentionReadError,
    inspect_grade_report_attention_for_class,
)
from meridian.grade_report_preview import GradeReportPreview, GradeReportPreviewRow
from meridian.hybrid_grade_explanation import HybridGradePreviewExplanation
from meridian.proficiency_attention import MeridianAttentionSummary
from meridian.report_export_roster import (
    ExportRosterObservation,
    ReportExportRosterError,
    build_report_display_name_observation,
    export_roster_observation_sha256,
)
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_comparison import (
    ReportingSnapshotComparisonError,
    compare_reporting_snapshot_to_grade_report_preview,
    load_reporting_snapshot_for_comparison,
)
from meridian.reporting_snapshot_record import (
    ReportingSnapshotBuildRequest,
    reporting_snapshot_build_request_sha256,
)
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionError,
    ReportingSnapshotSelectionReference,
    StoredReportingSnapshotSelection,
    load_current_reporting_snapshot_selection,
)
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotProjectionAuthorization,
    ReportingSnapshotWorkflowError,
    prepare_reporting_snapshot_freeze,
)
from meridian.standards_grade_explanation import (
    StandardsGradeBreakdownExplanation,
    StandardsGradePreviewExplanation,
    StandardsGradeStandardExplanation,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

ReadinessDisposition: TypeAlias = Literal["CLEAR", "REVIEW_NEEDED"]

_RELEVANT_ATTENTION_CODES: Final[frozenset[str]] = frozenset(
    {
        "meridian_grade_result_stale",
        "meridian_reporting_publication_changed",
        "meridian_reporting_snapshot_refresh_needed",
        "meridian_reporting_snapshot_selection_pending",
    }
)


class MarkingPeriodReadinessError(RuntimeError):
    """Base error for Marking-Period Readiness reporting."""

    code = "marking_period_readiness.error"


class MarkingPeriodReadinessValidationError(
    MarkingPeriodReadinessError,
    ValueError,
):
    code = "marking_period_readiness.invalid"


class MarkingPeriodReadinessSourceError(MarkingPeriodReadinessError):
    code = "marking_period_readiness.source_unavailable"


class MarkingPeriodReadinessCurrentnessConflictError(MarkingPeriodReadinessError):
    code = "marking_period_readiness.currentness_conflict"


@dataclass(frozen=True, slots=True)
class ReadinessStudentState:
    """Privacy-bounded current student reporting state."""

    student_id: str
    student_name: str
    calculation_family: str
    grade_status: str
    effective_grade: str | None
    freshness_status: str
    active_override: bool
    evidence_facts: tuple[str, ...]
    proficiency_insufficient: bool
    checkpoint_change: str | None
    review_reasons: tuple[str, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_marking_period_readiness(
    workspace_root: str | Path,
    *,
    build_request: ReportingSnapshotBuildRequest,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...] = (),
    prior_checkpoint: ReportingSnapshotReference | None = None,
    generated_at: datetime | None = None,
    dependencies: DiagnosticsDependencies | None = None,
) -> TeacherReportPreview:
    """Build one whole-class, read-only pre-close audit with revalidation."""

    root = Path(workspace_root)
    timestamp = utc_now() if generated_at is None else generated_at
    try:
        initial_live = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="readiness_live_preview",
            build_request=build_request,
            authorizations=authorizations,
            created_at=timestamp,
            dependencies=dependencies,
        )
        class_id = build_request.definition_reference.class_id
        _require_class_request_coverage(root, class_id, initial_live.live_report)

        student_ids = tuple(
            sorted(row.target.student_id for row in initial_live.live_report.rows)
        )
        roster = build_report_display_name_observation(root, class_id, student_ids)
        attention = inspect_grade_report_attention_for_class(
            root,
            class_id,
            active_school_year=build_request.target_period.school_year,
        )
        selection = load_current_reporting_snapshot_selection(
            root,
            class_id,
            build_request.definition_reference.definition_id,
            build_request.target_period,
            build_request.calendar_revision,
        )
        comparisons = _checkpoint_comparisons(
            root,
            prior_checkpoint,
            initial_live.live_report,
        )
        preview = compose_marking_period_readiness(
            class_id=class_id,
            target_period=build_request.target_period,
            calendar_revision=build_request.calendar_revision,
            live_grade_report=initial_live.live_report,
            live_grade_report_sha256=initial_live.live_report_sha256,
            roster_observation=roster,
            attention_summary=attention,
            current_snapshot_reference=(
                None if selection is None else selection.selection.snapshot_reference
            ),
            current_selection_reference=(
                None if selection is None else selection.reference
            ),
            checkpoint_comparisons=comparisons,
            prior_checkpoint=prior_checkpoint,
            build_request_sha256=reporting_snapshot_build_request_sha256(build_request),
            generated_at=timestamp,
        )

        final_live = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="readiness_live_preview",
            build_request=build_request,
            authorizations=authorizations,
            created_at=timestamp,
            dependencies=dependencies,
        )
        final_roster = build_report_display_name_observation(
            root,
            class_id,
            student_ids,
        )
        final_attention = inspect_grade_report_attention_for_class(
            root,
            class_id,
            active_school_year=build_request.target_period.school_year,
        )
        final_selection = load_current_reporting_snapshot_selection(
            root,
            class_id,
            build_request.definition_reference.definition_id,
            build_request.target_period,
            build_request.calendar_revision,
        )
    except MarkingPeriodReadinessError:
        raise
    except (
        GradeReportAttentionReadError,
        ReportExportRosterError,
        ReportingSnapshotComparisonError,
        ReportingSnapshotSelectionError,
        ReportingSnapshotWorkflowError,
        OSError,
        ValueError,
    ) as error:
        raise MarkingPeriodReadinessSourceError(
            "Marking-Period Readiness source state could not be verified safely."
        ) from error

    if final_live.live_report_sha256 != initial_live.live_report_sha256:
        raise MarkingPeriodReadinessCurrentnessConflictError(
            "Live Grade report changed during readiness generation."
        )
    if export_roster_observation_sha256(final_roster) != (
        export_roster_observation_sha256(roster)
    ):
        raise MarkingPeriodReadinessCurrentnessConflictError(
            "Displayed roster identity changed during readiness generation."
        )
    if final_attention != attention:
        raise MarkingPeriodReadinessCurrentnessConflictError(
            "Existing Grade/report attention changed during readiness generation."
        )
    if _selection_reference(final_selection) != _selection_reference(selection):
        raise MarkingPeriodReadinessCurrentnessConflictError(
            "ReportingSnapshot current-use selection changed during readiness "
            "generation."
        )
    return preview


def compose_marking_period_readiness(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    live_grade_report: GradeReportPreview,
    live_grade_report_sha256: str,
    roster_observation: ExportRosterObservation,
    attention_summary: MeridianAttentionSummary,
    current_snapshot_reference: ReportingSnapshotReference | None,
    current_selection_reference: ReportingSnapshotSelectionReference | None,
    checkpoint_comparisons: tuple[GradePreviewComparison, ...] = (),
    prior_checkpoint: ReportingSnapshotReference | None = None,
    build_request_sha256: str | None = None,
    generated_at: datetime,
) -> TeacherReportPreview:
    """Compose one deterministic readiness report from already-observed authority."""

    if roster_observation.class_id != class_id:
        raise MarkingPeriodReadinessValidationError(
            "roster observation must match report class."
        )
    names = {
        item.student_id: item.values[0].value for item in roster_observation.students
    }
    checkpoint_map = _comparison_map(checkpoint_comparisons)
    student_states = tuple(
        _student_state(
            row,
            names.get(row.target.student_id, row.target.student_id),
            checkpoint_map.get(row.target.student_id),
        )
        for row in live_grade_report.rows
    )

    relevant_attention = tuple(
        item
        for item in attention_summary.items
        if item.code in _RELEVANT_ATTENTION_CODES
    )
    attention_count = sum(item.count for item in relevant_attention)
    review_count = sum(bool(item.review_reasons) for item in student_states)
    disposition: ReadinessDisposition = (
        "REVIEW_NEEDED" if review_count or attention_count else "CLEAR"
    )
    overall = (
        "Review needed before external marking-period close"
        if disposition == "REVIEW_NEEDED"
        else "No unresolved Meridian reporting blockers detected"
    )

    rows = tuple(
        TeacherReportRow(
            f"readiness_{index:05d}",
            (
                state.student_id,
                state.student_name,
                state.calculation_family,
                state.grade_status,
                state.effective_grade,
                state.freshness_status,
                "yes" if state.active_override else "no",
                ", ".join(state.evidence_facts) or "none observed",
                "yes" if state.proficiency_insufficient else "no",
                state.checkpoint_change,
                ", ".join(state.review_reasons) or "none",
                "REVIEW_NEEDED" if state.review_reasons else "CLEAR",
            ),
        )
        for index, state in enumerate(student_states, start=1)
    )

    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "live_grade_report",
            "current_live_grade_report",
            _sha256(live_grade_report_sha256),
        ),
        TeacherReportSourceReference(
            "roster_observation",
            "display_names",
            export_roster_observation_sha256(roster_observation),
        ),
        TeacherReportSourceReference(
            "grade_report_attention",
            "existing_attention_summary",
            _attention_sha256(attention_summary),
        ),
    ]
    if build_request_sha256 is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot_build_request",
                "current_live_request",
                _sha256(build_request_sha256),
            )
        )
    if current_snapshot_reference is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot",
                f"current_use:{current_snapshot_reference.snapshot_id}",
                current_snapshot_reference.snapshot_sha256,
            )
        )
    if current_selection_reference is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot_selection",
                (
                    f"{current_selection_reference.definition_id}:"
                    f"r{current_selection_reference.selection_revision}"
                ),
                current_selection_reference.selection_sha256,
            )
        )
    if prior_checkpoint is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot",
                f"prior:{prior_checkpoint.snapshot_id}",
                prior_checkpoint.snapshot_sha256,
            )
        )

    diagnostics = tuple(
        TeacherReportDiagnostic(
            item.code,
            "info",
            (f"{item.definition.label}: {item.count} {item.definition.count_unit}."),
        )
        for item in relevant_attention
    )

    no_selected = sum(
        state.grade_status == "no_selected_grade" for state in student_states
    )
    stale = sum(state.freshness_status == "stale" for state in student_states)
    blocked = sum(state.grade_status == "blocked" for state in student_states)
    insufficient = sum(state.grade_status == "insufficient" for state in student_states)
    overrides = sum(state.active_override for state in student_states)
    proficiency_insufficient = sum(
        state.proficiency_insufficient for state in student_states
    )
    checkpoint_text = (
        "No prior checkpoint comparison was requested."
        if prior_checkpoint is None
        else (
            f"Prior checkpoint compared across {len(checkpoint_comparisons)} "
            "Grade rows."
        )
    )
    current_checkpoint = (
        "none selected"
        if current_snapshot_reference is None
        else (
            f"{current_snapshot_reference.snapshot_id} "
            f"({current_snapshot_reference.snapshot_sha256})"
        )
    )

    return compose_teacher_report_preview(
        report_kind="marking_period_readiness",
        title="Marking-Period Readiness",
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        source_references=tuple(sources),
        generated_at=generated_at,
        summary=(
            overall,
            f"Students reviewed: {len(student_states)}.",
            (
                f"No selected Grade={no_selected}; stale={stale}; blocked={blocked}; "
                f"insufficient={insufficient}."
            ),
            (
                f"Current proficiency insufficiency={proficiency_insufficient}; "
                f"active teacher overrides={overrides}."
            ),
            f"Existing Grade/report attention count={attention_count}.",
            f"Exact current-use checkpoint: {current_checkpoint}.",
            checkpoint_text,
            (
                "This is a Meridian pre-close audit only. It does not mean an SIS "
                "is ready, a district approved a Grade, or a report card was posted."
            ),
        ),
        columns=(
            TeacherReportColumn("student_id", "Student ID"),
            TeacherReportColumn("student_name", "Student"),
            TeacherReportColumn("family", "Grade Family"),
            TeacherReportColumn("grade_status", "Grade Status"),
            TeacherReportColumn("effective_grade", "Effective Grade"),
            TeacherReportColumn("freshness", "Freshness"),
            TeacherReportColumn("override", "Active Override"),
            TeacherReportColumn("evidence", "Evidence / Mapping Facts"),
            TeacherReportColumn(
                "proficiency_insufficient",
                "Current Proficiency Insufficiency",
            ),
            TeacherReportColumn("checkpoint_change", "Prior Checkpoint Change"),
            TeacherReportColumn("review_reasons", "Review Reasons"),
            TeacherReportColumn("readiness", "Meridian Audit State"),
        ),
        rows=rows,
        diagnostics=diagnostics,
    )


def _student_state(
    row: GradeReportPreviewRow,
    student_name: str,
    comparison: GradePreviewComparison | None,
) -> ReadinessStudentState:
    checkpoint = _comparison_text(comparison)
    if row.status == "unavailable":
        return ReadinessStudentState(
            student_id=row.target.student_id,
            student_name=student_name,
            calculation_family=row.target.calculation_family,
            grade_status="no_selected_grade",
            effective_grade=None,
            freshness_status="unavailable",
            active_override=False,
            evidence_facts=(),
            proficiency_insufficient=False,
            checkpoint_change=checkpoint,
            review_reasons=("no selected Grade",),
        )

    explanation = row.explanation
    if explanation is None:
        raise MarkingPeriodReadinessValidationError(
            "available Grade row is missing its explanation."
        )
    common = _common(explanation)
    facts, proficiency_insufficient = _family_facts(explanation)
    reasons: list[str] = []
    if common.base_result_status in {"blocked", "insufficient"}:
        reasons.append(f"Grade {common.base_result_status}")
    if common.base_freshness_status == "stale":
        reasons.append("Grade result stale")
    if facts:
        reasons.append("evidence/proficiency review")
    if proficiency_insufficient:
        reasons.append("current proficiency insufficient")

    return ReadinessStudentState(
        student_id=row.target.student_id,
        student_name=student_name,
        calculation_family=row.target.calculation_family,
        grade_status=common.base_result_status,
        effective_grade=(
            None if common.effective_grade is None else str(common.effective_grade)
        ),
        freshness_status=common.base_freshness_status,
        active_override=common.effective_source == "override",
        evidence_facts=facts,
        proficiency_insufficient=proficiency_insufficient,
        checkpoint_change=checkpoint,
        review_reasons=tuple(dict.fromkeys(reasons)),
    )


def _family_facts(
    explanation: CurrentGradePreviewExplanation,
) -> tuple[tuple[str, ...], bool]:
    if isinstance(explanation, ConventionalGradePreviewExplanation):
        return _conventional_facts(
            ConventionalGradeBreakdownExplanation(
                status=explanation.common.base_result_status,  # type: ignore[arg-type]
                mode=explanation.mode,
                items=explanation.items,
                categories=explanation.categories,
                formula=explanation.formula,
                reasons=explanation.reasons,
            )
        )
    if isinstance(explanation, StandardsGradePreviewExplanation):
        return _standards_facts(explanation.standards)
    if isinstance(explanation, HybridGradePreviewExplanation):
        conventional_breakdown = explanation.conventional_component.breakdown
        standards_breakdown = explanation.standards_component.breakdown
        if not isinstance(
            conventional_breakdown,
            ConventionalGradeBreakdownExplanation,
        ) or not isinstance(
            standards_breakdown,
            StandardsGradeBreakdownExplanation,
        ):
            raise MarkingPeriodReadinessValidationError(
                "Hybrid Grade component breakdown types are inconsistent."
            )
        conventional_facts, conventional_insufficient = _conventional_facts(
            conventional_breakdown
        )
        standards_facts, standards_insufficient = _standards_facts(
            standards_breakdown.standards
        )
        return (
            tuple(dict.fromkeys(conventional_facts + standards_facts)),
            conventional_insufficient or standards_insufficient,
        )
    raise MarkingPeriodReadinessValidationError(
        "unsupported current Grade explanation type."
    )


def _conventional_facts(
    breakdown: ConventionalGradeBreakdownExplanation,
) -> tuple[tuple[str, ...], bool]:
    facts: list[str] = []
    for item in breakdown.items:
        if item.source_state in {"pending", "incomplete", "unavailable", "unresolved"}:
            facts.append(
                f"{item.grade_item.reference.grade_item_id}:{item.source_state}"
            )
    return tuple(sorted(set(facts))), breakdown.status == "insufficient"


def _standards_facts(
    standards: tuple[StandardsGradeStandardExplanation, ...],
) -> tuple[tuple[str, ...], bool]:
    facts: list[str] = []
    insufficient = False
    for standard in standards:
        if standard.source_state in {
            "missing",
            "pending",
            "incomplete",
            "unavailable",
            "unresolved",
        }:
            facts.append(f"{standard.standard_id}:{standard.source_state}")
        if standard.source_state == "insufficient_evidence":
            insufficient = True
            facts.append(f"{standard.standard_id}:insufficient_evidence")
        nested = standard.nested_proficiency_explanation
        if nested is None:
            continue
        if nested.calculation.status == "insufficient_evidence":
            insufficient = True
        facts.extend(_proficiency_facts(nested))
    return tuple(sorted(set(facts))), insufficient


def _proficiency_facts(
    value: AcademicPeriodProficiencyExplanation,
) -> tuple[str, ...]:
    facts: set[str] = set()
    for grade_item in value.grade_items:
        nested = grade_item.nested_grade_item_explanation
        if nested is None:
            continue
        for evidence in nested.evidence:
            if evidence.mapping_status in {"unmapped", "unsupported"}:
                facts.add(f"{grade_item.grade_item.grade_item_id}:unmapped")
            if evidence.exclusion_reason == "attempt_selection_unresolved":
                facts.add(f"{grade_item.grade_item.grade_item_id}:attempt_unresolved")
            if evidence.exclusion_reason == "reassessment_unresolved":
                facts.add(
                    f"{grade_item.grade_item.grade_item_id}:reassessment_unresolved"
                )
            for stage in evidence.stages:
                if stage.name != "eligibility":
                    continue
                for detail in stage.details:
                    if detail.key == "disposition" and detail.value == "pending":
                        facts.add(f"{grade_item.grade_item.grade_item_id}:pending")
    return tuple(sorted(facts))


def _checkpoint_comparisons(
    root: Path,
    reference: ReportingSnapshotReference | None,
    live_report: GradeReportPreview,
) -> tuple[GradePreviewComparison, ...]:
    if reference is None:
        return ()
    stored = load_reporting_snapshot_for_comparison(root, reference)
    return compare_reporting_snapshot_to_grade_report_preview(
        stored.snapshot,
        live_report,
    )


def _comparison_map(
    values: tuple[GradePreviewComparison, ...],
) -> dict[str, GradePreviewComparison]:
    result: dict[str, GradePreviewComparison] = {}
    for value in values:
        target = value.current_target or value.prior_target
        if target is None:
            continue
        if target.student_id in result:
            raise MarkingPeriodReadinessValidationError(
                "Checkpoint comparison contains more than one Grade family for a "
                "student; readiness requires one Grade row per student."
            )
        result[target.student_id] = value
    return result


def _comparison_text(value: GradePreviewComparison | None) -> str | None:
    if value is None:
        return None
    if value.relationship == "new":
        return "new/newly available"
    if value.relationship == "removed":
        return "removed/unavailable"
    if not value.changed:
        return "unchanged"
    delta = value.effective_grade_delta
    if delta is not None and delta > 0:
        direction = f"increased {delta}"
    elif delta is not None and delta < 0:
        direction = f"decreased {abs(delta)}"
    else:
        direction = "material basis change"
    reasons = ", ".join(value.reasons)
    return f"{direction}; {reasons}"


def _common(
    explanation: CurrentGradePreviewExplanation,
) -> GradePreviewExplanation:
    if isinstance(explanation, ConventionalGradePreviewExplanation):
        return explanation.common
    if isinstance(explanation, StandardsGradePreviewExplanation):
        return explanation.common
    if isinstance(explanation, HybridGradePreviewExplanation):
        return explanation.common
    raise MarkingPeriodReadinessValidationError(
        "unsupported current Grade explanation type."
    )


def _require_class_request_coverage(
    root: Path,
    class_id: str,
    report: GradeReportPreview,
) -> None:
    from pds_core.classes import load_class_roster

    roster = load_class_roster(root, class_id)
    roster_students = {student.student_id for student in roster.students}
    report_students = [row.target.student_id for row in report.rows]
    if len(set(report_students)) != len(report_students):
        raise MarkingPeriodReadinessValidationError(
            "Readiness requires exactly one Grade family row per student."
        )
    if set(report_students) != roster_students:
        raise MarkingPeriodReadinessValidationError(
            "Readiness build request must cover the exact current class roster."
        )


def _selection_reference(
    stored: StoredReportingSnapshotSelection | None,
) -> ReportingSnapshotSelectionReference | None:
    return None if stored is None else stored.reference


def _attention_sha256(value: MeridianAttentionSummary) -> str:
    payload = [
        {
            "code": item.code,
            "count": item.count,
            "class_id": item.class_id,
        }
        for item in value.items
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MarkingPeriodReadinessValidationError(
            "expected lowercase SHA-256 digest."
        )
    return value


__all__ = [
    "MarkingPeriodReadinessCurrentnessConflictError",
    "MarkingPeriodReadinessError",
    "MarkingPeriodReadinessSourceError",
    "MarkingPeriodReadinessValidationError",
    "ReadinessStudentState",
    "build_marking_period_readiness",
    "compose_marking_period_readiness",
]
