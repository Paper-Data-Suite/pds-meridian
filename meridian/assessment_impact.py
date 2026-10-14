"""Grade Item / Assessment Impact report for Meridian Issue #111 Slice 11.

"Impact" here is descriptive and provenance-based.  The report records exact
participation and result lineage; it never claims a Grade Item caused a Grade or
proficiency change when other inputs may have changed concurrently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_result_revisions,
    list_academic_period_proficiency_result_standard_ids,
    load_academic_period_proficiency_result_revision,
)
from meridian.conventional_grade_explanation import (
    ConventionalGradeBreakdownExplanation,
    ConventionalGradeItemExplanation,
    ConventionalGradePreviewExplanation,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_item_storage import (
    GradeItemStorageError,
    StoredGradeItemRevision,
    load_current_grade_item_revision,
)
from meridian.grade_preview_comparison import GradePreviewComparison
from meridian.grade_report_preview import GradeReportPreview, GradeReportPreviewRow
from meridian.hybrid_grade_explanation import HybridGradePreviewExplanation
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
from meridian.student_proficiency_growth import (
    ProficiencyTrajectoryRevision,
    trajectory_revision_observation,
)
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)


class AssessmentImpactError(RuntimeError):
    """Base error for Grade Item / Assessment Impact reporting."""

    code = "assessment_impact.error"


class AssessmentImpactValidationError(AssessmentImpactError, ValueError):
    code = "assessment_impact.invalid"


class AssessmentImpactSourceError(AssessmentImpactError):
    code = "assessment_impact.source_unavailable"


class AssessmentImpactCurrentnessConflictError(AssessmentImpactError):
    code = "assessment_impact.currentness_conflict"


@dataclass(frozen=True, slots=True)
class ProficiencyBasisEvent:
    """One exact result revision where the selected Grade Item entered the basis."""

    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    selected_current: bool
    contributing: bool
    previous_proficiency: str
    current_proficiency: str


@dataclass(frozen=True, slots=True)
class AssessmentStudentImpact:
    """Bounded per-student Grade Item participation projection."""

    student_id: str
    student_name: str
    grade_family: str | None
    standards: tuple[str, ...]
    proficiency_participation: tuple[str, ...]
    conventional_participation: tuple[str, ...]
    evidence_states: tuple[str, ...]
    basis_events: tuple[str, ...]
    checkpoint_association: str | None

    @property
    def represented(self) -> bool:
        return bool(
            self.standards
            or self.proficiency_participation
            or self.conventional_participation
            or self.evidence_states
            or self.basis_events
            or self.checkpoint_association
        )


@dataclass(frozen=True, slots=True)
class _HistoryCapture:
    by_student: tuple[tuple[str, tuple[ProficiencyBasisEvent, ...]], ...]
    standards_by_student: tuple[tuple[str, tuple[str, ...]], ...]
    current_participation: tuple[tuple[str, tuple[str, ...]], ...]
    witness_sha256: str
    source_references: tuple[TeacherReportSourceReference, ...]


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_assessment_impact(
    workspace_root: str | Path,
    *,
    grade_item_id: str,
    build_request: ReportingSnapshotBuildRequest,
    authorizations: tuple[ReportingSnapshotProjectionAuthorization, ...] = (),
    prior_checkpoint: ReportingSnapshotReference | None = None,
    generated_at: datetime | None = None,
    dependencies: DiagnosticsDependencies | None = None,
) -> TeacherReportPreview:
    """Build a class-wide descriptive Grade Item participation report."""

    root = Path(workspace_root)
    timestamp = utc_now() if generated_at is None else generated_at
    class_id = build_request.definition_reference.class_id
    try:
        grade_item = load_current_grade_item_revision(
            root,
            class_id,
            grade_item_id,
        )
        if grade_item is None:
            raise AssessmentImpactSourceError(
                "Selected Grade Item has no explicit current revision."
            )

        initial_live = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="assessment_impact_live_preview",
            build_request=build_request,
            authorizations=authorizations,
            created_at=timestamp,
            dependencies=dependencies,
        )
        student_ids = _require_class_request_coverage(
            root,
            class_id,
            initial_live.live_report,
        )
        roster = build_report_display_name_observation(
            root,
            class_id,
            student_ids,
        )
        histories = _capture_histories(
            root,
            class_id=class_id,
            target_period=build_request.target_period,
            grade_item_id=grade_item_id,
            student_ids=student_ids,
        )
        comparisons = _checkpoint_comparisons(
            root,
            prior_checkpoint,
            initial_live.live_report,
        )

        preview = compose_assessment_impact(
            class_id=class_id,
            target_period=build_request.target_period,
            calendar_revision=build_request.calendar_revision,
            grade_item=grade_item,
            roster_observation=roster,
            live_grade_report=initial_live.live_report,
            live_grade_report_sha256=initial_live.live_report_sha256,
            histories=histories,
            checkpoint_comparisons=comparisons,
            prior_checkpoint=prior_checkpoint,
            build_request_sha256=reporting_snapshot_build_request_sha256(build_request),
            generated_at=timestamp,
        )

        final_grade_item = load_current_grade_item_revision(
            root,
            class_id,
            grade_item_id,
        )
        final_live = prepare_reporting_snapshot_freeze(
            root,
            snapshot_id="assessment_impact_live_preview",
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
        final_histories = _capture_histories(
            root,
            class_id=class_id,
            target_period=build_request.target_period,
            grade_item_id=grade_item_id,
            student_ids=student_ids,
        )
    except AssessmentImpactError:
        raise
    except (
        AcademicPeriodProficiencyStorageError,
        GradeItemStorageError,
        ReportExportRosterError,
        ReportingSnapshotComparisonError,
        ReportingSnapshotWorkflowError,
        OSError,
        ValueError,
    ) as error:
        raise AssessmentImpactSourceError(
            "Assessment Impact source state could not be verified safely."
        ) from error

    if (
        final_grade_item is None
        or final_grade_item.revision_sha256 != grade_item.revision_sha256
    ):
        raise AssessmentImpactCurrentnessConflictError(
            "Selected Grade Item revision changed during impact generation."
        )
    if final_live.live_report_sha256 != initial_live.live_report_sha256:
        raise AssessmentImpactCurrentnessConflictError(
            "Live Grade report changed during impact generation."
        )
    if export_roster_observation_sha256(final_roster) != (
        export_roster_observation_sha256(roster)
    ):
        raise AssessmentImpactCurrentnessConflictError(
            "Displayed roster identity changed during impact generation."
        )
    if final_histories.witness_sha256 != histories.witness_sha256:
        raise AssessmentImpactCurrentnessConflictError(
            "Academic Period proficiency lineage changed during impact generation."
        )
    return preview


def compose_assessment_impact(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    grade_item: StoredGradeItemRevision,
    roster_observation: ExportRosterObservation,
    live_grade_report: GradeReportPreview,
    live_grade_report_sha256: str,
    histories: _HistoryCapture,
    checkpoint_comparisons: tuple[GradePreviewComparison, ...] = (),
    prior_checkpoint: ReportingSnapshotReference | None = None,
    build_request_sha256: str | None = None,
    generated_at: datetime,
) -> TeacherReportPreview:
    """Compose one deterministic descriptive assessment-participation report."""

    if grade_item.revision.class_id != class_id:
        raise AssessmentImpactValidationError("Grade Item must match report class.")
    if roster_observation.class_id != class_id:
        raise AssessmentImpactValidationError(
            "roster observation must match report class."
        )
    grade_item_id = grade_item.revision.grade_item_id
    names = {
        item.student_id: item.values[0].value for item in roster_observation.students
    }
    standards_map = dict(histories.standards_by_student)
    current_map = dict(histories.current_participation)
    events_map = dict(histories.by_student)
    comparison_map = _comparison_map(checkpoint_comparisons)

    impacts: list[AssessmentStudentImpact] = []
    for student_id in sorted(names):
        row = _grade_row_for_student(live_grade_report, student_id)
        family = None if row is None else row.target.calculation_family
        conventional, standards_from_grade, evidence_states = _grade_participation(
            row,
            grade_item_id,
        )
        history_standards = standards_map.get(student_id, ())
        standards = tuple(sorted(set(history_standards + standards_from_grade)))
        current = current_map.get(student_id, ())
        events = events_map.get(student_id, ())
        event_text = tuple(_event_text(event) for event in events)
        checkpoint = _checkpoint_association(
            comparison_map.get(student_id),
            represented=bool(conventional or standards or current or events),
        )
        impacts.append(
            AssessmentStudentImpact(
                student_id=student_id,
                student_name=names[student_id],
                grade_family=family,
                standards=standards,
                proficiency_participation=current,
                conventional_participation=conventional,
                evidence_states=evidence_states,
                basis_events=event_text,
                checkpoint_association=checkpoint,
            )
        )

    rows = tuple(
        TeacherReportRow(
            f"impact_{index:05d}",
            (
                impact.student_id,
                impact.student_name,
                impact.grade_family,
                "yes" if impact.represented else "no",
                ", ".join(impact.standards) or None,
                "; ".join(impact.proficiency_participation) or None,
                "; ".join(impact.conventional_participation) or None,
                ", ".join(impact.evidence_states) or None,
                "; ".join(impact.basis_events) or None,
                impact.checkpoint_association,
                (
                    "Descriptive participation only; concurrent inputs may also "
                    "have changed."
                    if impact.represented
                    else None
                ),
            ),
        )
        for index, impact in enumerate(impacts, start=1)
    )

    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "grade_item_revision",
            (f"{grade_item_id}:r{grade_item.revision.grade_item_revision}"),
            grade_item.revision_sha256,
        ),
        TeacherReportSourceReference(
            "roster_observation",
            "display_names",
            export_roster_observation_sha256(roster_observation),
        ),
        TeacherReportSourceReference(
            "live_grade_report",
            "current_live_grade_report",
            _sha256(live_grade_report_sha256),
        ),
        *histories.source_references,
    ]
    if build_request_sha256 is not None:
        sources.append(
            TeacherReportSourceReference(
                "reporting_snapshot_build_request",
                "current_live_request",
                _sha256(build_request_sha256),
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

    represented = sum(impact.represented for impact in impacts)
    current_prof = sum(bool(impact.proficiency_participation) for impact in impacts)
    conventional_count = sum(
        bool(impact.conventional_participation) for impact in impacts
    )
    basis_events = sum(len(impact.basis_events) for impact in impacts)
    checkpoint_links = sum(
        impact.checkpoint_association is not None for impact in impacts
    )
    represented_standards = sorted(
        {standard for impact in impacts for standard in impact.standards}
    )
    represented_standards_text = ", ".join(represented_standards) or "none"
    diagnostics: tuple[TeacherReportDiagnostic, ...] = ()
    if checkpoint_links:
        diagnostics = (
            TeacherReportDiagnostic(
                "assessment_impact.checkpoint_association_noncausal",
                "info",
                (
                    "Checkpoint associations identify material Grade-basis changes "
                    "while this Grade Item participates. They are not causal claims."
                ),
            ),
        )

    return compose_teacher_report_preview(
        report_kind="assessment_impact",
        title="Grade Item / Assessment Impact",
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        source_references=tuple(sources),
        generated_at=generated_at,
        summary=(
            (
                f"Grade Item: {grade_item.revision.title} "
                f"({grade_item_id}, revision "
                f"{grade_item.revision.grade_item_revision})."
            ),
            f"Students with represented participation/history: {represented}.",
            f"Standards represented: {represented_standards_text}.",
            f"Current proficiency participation students: {current_prof}.",
            f"Current conventional contribution students: {conventional_count}.",
            f"Exact proficiency basis-entry events: {basis_events}.",
            f"Checkpoint basis associations: {checkpoint_links}.",
            (
                "Impact is descriptive and provenance-based. This report does not "
                "claim the Grade Item caused a proficiency or Grade change."
            ),
        ),
        columns=(
            TeacherReportColumn("student_id", "Student ID"),
            TeacherReportColumn("student_name", "Student"),
            TeacherReportColumn("grade_family", "Grade Family"),
            TeacherReportColumn("represented", "Represented"),
            TeacherReportColumn("standards", "Standards Represented"),
            TeacherReportColumn(
                "proficiency_participation",
                "Current Proficiency Participation",
            ),
            TeacherReportColumn(
                "conventional_participation",
                "Conventional / Hybrid Contribution",
            ),
            TeacherReportColumn("evidence_states", "Evidence States"),
            TeacherReportColumn(
                "basis_events",
                "Exact Proficiency Basis Entry",
            ),
            TeacherReportColumn(
                "checkpoint_association",
                "Checkpoint Basis Association",
            ),
            TeacherReportColumn("causality", "Interpretation"),
        ),
        rows=rows,
        diagnostics=diagnostics,
    )


def _capture_histories(
    root: Path,
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    grade_item_id: str,
    student_ids: tuple[str, ...],
) -> _HistoryCapture:
    by_student: list[tuple[str, tuple[ProficiencyBasisEvent, ...]]] = []
    standards_by_student: list[tuple[str, tuple[str, ...]]] = []
    current_participation: list[tuple[str, tuple[str, ...]]] = []
    witness: list[dict[str, object]] = []
    sources: dict[tuple[str, str], TeacherReportSourceReference] = {}

    for student_id in student_ids:
        standards = list_academic_period_proficiency_result_standard_ids(
            root,
            class_id,
            target_period.school_year,
            target_period.period_id,
            student_id,
        )
        represented_standards: set[str] = set()
        current_rows: list[str] = []
        events: list[ProficiencyBasisEvent] = []
        standard_witnesses: list[dict[str, object]] = []

        for standard_id in standards:
            revisions = list_academic_period_proficiency_result_revisions(
                root,
                class_id,
                target_period.school_year,
                target_period.period_id,
                student_id,
                standard_id,
            )
            current_revision = get_current_academic_period_proficiency_result_revision(
                root,
                class_id,
                target_period.school_year,
                target_period.period_id,
                student_id,
                standard_id,
            )
            observations: list[ProficiencyTrajectoryRevision] = []
            revision_witnesses: list[dict[str, object]] = []
            for revision in revisions:
                stored = load_academic_period_proficiency_result_revision(
                    root,
                    class_id,
                    target_period.school_year,
                    target_period.period_id,
                    student_id,
                    standard_id,
                    revision,
                )
                observation = trajectory_revision_observation(stored)
                observations.append(observation)
                revision_witnesses.append(
                    {
                        "revision": revision,
                        "sha256": observation.result_sha256,
                    }
                )
                if grade_item_id in observation.candidate_grade_item_ids:
                    represented_standards.add(standard_id)
                    _add_source(
                        sources,
                        TeacherReportSourceReference(
                            "academic_period_proficiency_result",
                            (
                                f"{student_id}|{standard_id}|"
                                f"r{observation.result_revision}"
                            ),
                            observation.result_sha256,
                        ),
                    )
                if (
                    current_revision == observation.result_revision
                    and grade_item_id in observation.candidate_grade_item_ids
                ):
                    participation_role = (
                        "contributing"
                        if grade_item_id in observation.contributing_grade_item_ids
                        else "candidate"
                    )
                    current_rows.append(
                        (
                            f"{standard_id}:r{observation.result_revision}:"
                            f"{observation.status}:"
                            f"{observation.proficiency_level_id or 'none'}:"
                            f"{participation_role}"
                        )
                    )

            previous: ProficiencyTrajectoryRevision | None = None
            for observation in observations:
                entered = grade_item_id in observation.candidate_grade_item_ids and (
                    previous is None
                    or grade_item_id not in previous.candidate_grade_item_ids
                )
                if entered:
                    events.append(
                        ProficiencyBasisEvent(
                            student_id=student_id,
                            standard_id=standard_id,
                            result_revision=observation.result_revision,
                            result_sha256=observation.result_sha256,
                            selected_current=(
                                current_revision == observation.result_revision
                            ),
                            contributing=(
                                grade_item_id in observation.contributing_grade_item_ids
                            ),
                            previous_proficiency=_trajectory_label(previous),
                            current_proficiency=_trajectory_label(observation),
                        )
                    )
                previous = observation

            standard_witnesses.append(
                {
                    "standard_id": standard_id,
                    "current_revision": current_revision,
                    "revisions": revision_witnesses,
                }
            )

        by_student.append(
            (
                student_id,
                tuple(
                    sorted(
                        events,
                        key=lambda item: (
                            item.standard_id,
                            item.result_revision,
                            item.result_sha256,
                        ),
                    )
                ),
            )
        )
        standards_by_student.append((student_id, tuple(sorted(represented_standards))))
        current_participation.append((student_id, tuple(sorted(current_rows))))
        witness.append(
            {
                "student_id": student_id,
                "standards": standard_witnesses,
            }
        )

    return _HistoryCapture(
        by_student=tuple(by_student),
        standards_by_student=tuple(standards_by_student),
        current_participation=tuple(current_participation),
        witness_sha256=_json_sha256(witness),
        source_references=tuple(sources.values()),
    )


def _grade_participation(
    row: GradeReportPreviewRow | None,
    grade_item_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if row is None or row.status == "unavailable" or row.explanation is None:
        return (), (), ()

    explanation = row.explanation
    conventional: list[str] = []
    standards: set[str] = set()
    evidence_states: set[str] = set()

    if isinstance(explanation, ConventionalGradePreviewExplanation):
        conventional.extend(
            _conventional_item_text(explanation.items, grade_item_id, "conventional")
        )
    elif isinstance(explanation, StandardsGradePreviewExplanation):
        s, e = _standards_participation(explanation.standards, grade_item_id)
        standards.update(s)
        evidence_states.update(e)
    elif isinstance(explanation, HybridGradePreviewExplanation):
        conventional_breakdown = explanation.conventional_component.breakdown
        standards_breakdown = explanation.standards_component.breakdown
        if not isinstance(
            conventional_breakdown, ConventionalGradeBreakdownExplanation
        ) or not isinstance(
            standards_breakdown, StandardsGradeBreakdownExplanation
        ):
            raise AssessmentImpactValidationError(
                "hybrid Grade component breakdown types are inconsistent."
            )
        conventional.extend(
            _conventional_item_text(
                conventional_breakdown.items,
                grade_item_id,
                (
                    "hybrid/conventional "
                    f"component_weight={explanation.conventional_component.configured_weight}"
                ),
            )
        )
        s, e = _standards_participation(
            standards_breakdown.standards,
            grade_item_id,
            prefix=(
                "hybrid/standards "
                f"component_weight={explanation.standards_component.configured_weight}"
            ),
        )
        standards.update(s)
        evidence_states.update(e)
    else:
        raise AssessmentImpactValidationError(
            "unsupported current Grade explanation type."
        )

    return (
        tuple(sorted(conventional)),
        tuple(sorted(standards)),
        tuple(sorted(evidence_states)),
    )


def _conventional_item_text(
    items: tuple[ConventionalGradeItemExplanation, ...],
    grade_item_id: str,
    prefix: str,
) -> tuple[str, ...]:
    result: list[str] = []
    for item in items:
        if item.grade_item.reference.grade_item_id != grade_item_id:
            continue
        contribution = "none" if item.contribution is None else str(item.contribution)
        weight = "none" if item.weight is None else str(item.weight)
        category = item.category_id or "none"
        result.append(
            (
                f"{prefix}: action={item.action}; source={item.source_state}; "
                f"weight={weight}; category={category}; contribution={contribution}"
            )
        )
    return tuple(result)


def _standards_participation(
    standards: tuple[StandardsGradeStandardExplanation, ...],
    grade_item_id: str,
    *,
    prefix: str = "standards",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    represented: set[str] = set()
    evidence_states: set[str] = set()
    for standard in standards:
        nested = standard.nested_proficiency_explanation
        if nested is None:
            continue
        matching = [
            item
            for item in nested.grade_items
            if item.grade_item.grade_item_id == grade_item_id
        ]
        if not matching:
            continue
        represented.add(standard.standard_id)
        for item in matching:
            evidence_states.add(
                (
                    f"{prefix}:{standard.standard_id}:"
                    f"grade_item_status={item.status}:"
                    f"grade_action={standard.action}"
                )
            )
            nested_item = item.nested_grade_item_explanation
            if nested_item is None:
                continue
            for evidence in nested_item.evidence:
                if evidence.aggregation_status == "excluded":
                    evidence_states.add(f"{standard.standard_id}:excluded")
                if evidence.mapping_status in {"unmapped", "unsupported"}:
                    evidence_states.add(f"{standard.standard_id}:unmapped")
                for stage in evidence.stages:
                    if stage.name != "eligibility":
                        continue
                    for detail in stage.details:
                        if detail.key == "disposition" and detail.value is not None:
                            evidence_states.add(
                                f"{standard.standard_id}:eligibility={detail.value}"
                            )
    return tuple(sorted(represented)), tuple(sorted(evidence_states))


def _checkpoint_association(
    comparison: GradePreviewComparison | None,
    *,
    represented: bool,
) -> str | None:
    if comparison is None or not represented:
        return None
    if comparison.relationship == "new":
        return (
            "Grade row is new/newly available while this Grade Item is represented; "
            "not a causal claim."
        )
    if comparison.relationship == "removed":
        return (
            "Prior Grade row was removed/unavailable; this report does not attribute "
            "that change to the Grade Item."
        )
    basis_reasons = {
        "membership_or_participation_changed",
        "evidence_or_proficiency_basis_changed",
        "weighting_changed",
        "base_grade_changed",
        "effective_grade_changed",
    }
    matched = tuple(reason for reason in comparison.reasons if reason in basis_reasons)
    if not matched:
        return None
    return (
        "Material Grade basis changed while this Grade Item participates "
        f"({', '.join(matched)}); concurrent inputs may also have changed."
    )


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
            raise AssessmentImpactValidationError(
                "Assessment Impact requires one Grade row per student."
            )
        result[target.student_id] = value
    return result


def _grade_row_for_student(
    report: GradeReportPreview,
    student_id: str,
) -> GradeReportPreviewRow | None:
    matching = [row for row in report.rows if row.target.student_id == student_id]
    if len(matching) > 1:
        raise AssessmentImpactValidationError(
            "Assessment Impact requires one Grade row per student."
        )
    return None if not matching else matching[0]


def _event_text(event: ProficiencyBasisEvent) -> str:
    selected = "current" if event.selected_current else "historical"
    participation = "contributing" if event.contributing else "candidate"
    return (
        f"{event.standard_id}: r{event.result_revision} entered basis "
        f"({selected}, {participation}); "
        f"{event.previous_proficiency} -> {event.current_proficiency}"
    )


def _trajectory_label(
    value: ProficiencyTrajectoryRevision | None,
) -> str:
    if value is None:
        return "no prior result"
    if value.status == "insufficient_evidence":
        return "insufficient_evidence"
    return value.proficiency_level_id or "no level"


def _require_class_request_coverage(
    root: Path,
    class_id: str,
    report: GradeReportPreview,
) -> tuple[str, ...]:
    from pds_core.classes import load_class_roster

    roster = load_class_roster(root, class_id)
    roster_students = tuple(sorted(student.student_id for student in roster.students))
    report_students = tuple(sorted(row.target.student_id for row in report.rows))
    if len(set(report_students)) != len(report_students):
        raise AssessmentImpactValidationError(
            "Assessment Impact requires exactly one Grade family row per student."
        )
    if report_students != roster_students:
        raise AssessmentImpactValidationError(
            "Assessment Impact build request must cover the exact current class roster."
        )
    return roster_students


def _add_source(
    target: dict[tuple[str, str], TeacherReportSourceReference],
    source: TeacherReportSourceReference,
) -> None:
    key = (source.source_kind, source.source_id)
    previous = target.get(key)
    if previous is not None and previous != source:
        raise AssessmentImpactValidationError(
            "Assessment Impact source identity resolves to conflicting digests."
        )
    target[key] = source


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
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
        raise AssessmentImpactValidationError("expected lowercase SHA-256 digest.")
    return value


__all__ = [
    "AssessmentImpactCurrentnessConflictError",
    "AssessmentImpactError",
    "AssessmentImpactSourceError",
    "AssessmentImpactValidationError",
    "AssessmentStudentImpact",
    "ProficiencyBasisEvent",
    "build_assessment_impact",
    "compose_assessment_impact",
]
