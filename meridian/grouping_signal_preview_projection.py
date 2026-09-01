"""Teacher-facing read-only projection for #39 grouping-signal previews.

This module joins current Core roster display names transiently onto one exact
persisted preview. Display names are presentation-only: they are never written
into preview/review canonical bytes and never affect any fingerprint or digest.

Previewing does not export. Accepting does not export. Export happens only in
Meridian issue #40.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from pds_core.rosters import RosterError, load_roster, student_display_name
from pds_core.routes import class_roster_path

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyResultReference,
)
from meridian.grouping_signal_currentness import (
    GroupingSignalCurrentnessError,
    assess_grouping_signal_derivation_currentness,
)
from meridian.grouping_signal_derivation import (
    GroupingSignalDerivationReference,
)
from meridian.grouping_signal_policy import (
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicyReference,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewBandSummary,
    GroupingSignalPreviewCoverage,
    GroupingSignalPreviewCurrentness,
    GroupingSignalPreviewDiagnostic,
    GroupingSignalPreviewReference,
    GroupingSignalPreviewStudentRow,
    GroupingSignalPreviewTieGroup,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewApplicability,
    GroupingSignalReviewDecisionValue,
    GroupingSignalReviewReference,
    assess_grouping_signal_review_applicability,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    load_current_grouping_signal_review,
)
from meridian.proficiency_mapping import ProficiencyScaleReference

PREVIEW_DOES_NOT_EXPORT_NOTICE: Final[str] = "Previewing does not export."
ACCEPTANCE_DOES_NOT_EXPORT_NOTICE: Final[str] = "Accepting does not export."
EXPORT_ONLY_IN_ISSUE_40_NOTICE: Final[str] = "Export happens only in #40."

_DIAGNOSTIC_MESSAGES: Final[dict[str, str]] = {
    "derivation_not_current": (
        "The reviewed derivation is not current and cannot be accepted for export."
    ),
    "current_generation_blocked": (
        "Current derivation resolution is blocked by one or more source conditions."
    ),
    "zero_contributors": (
        "No students contribute a band; Core grouping-signal export is unavailable."
    ),
    "missing_noncontributors": (
        "One or more roster students have no selected Academic Period result and "
        "remain noncontributing."
    ),
    "insufficient_noncontributors": (
        "One or more roster students have insufficient evidence and remain "
        "noncontributing."
    ),
    "partial_coverage": (
        "The derivation does not have contributing band assignments for the full "
        "roster."
    ),
    "empty_bands": (
        "One or more configured bands contain no contributing students."
    ),
    "single_occupied_band": (
        "All contributing students currently occupy one configured band."
    ),
}


class GroupingSignalTeacherProjectionError(RuntimeError):
    """Base error for teacher-facing preview projection."""


class GroupingSignalTeacherProjectionReadError(
    GroupingSignalTeacherProjectionError
):
    """Raised when exact preview/current review state cannot be read safely."""


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherStudentRow:
    """One teacher-facing student row with transient current roster name."""

    student_id: str
    display_name: str | None
    source_state: str
    disposition: str
    source_result: AcademicPeriodProficiencyResultReference | None
    proficiency_level_id: str | None
    scale_position: int | None
    band: int | None


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherBandSummary:
    """One neutral teacher-facing band summary."""

    band: int
    label: str
    minimum_scale_position: int
    maximum_scale_position: int
    proficiency_level_ids: tuple[str, ...]
    student_ids: tuple[str, ...]
    student_display_names: tuple[str | None, ...]
    student_count: int


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherTieGroup:
    proficiency_level_id: str
    scale_position: int
    band: int
    band_label: str
    student_ids: tuple[str, ...]
    student_display_names: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherDiagnostic:
    diagnostic_id: str
    code: str
    severity: str
    message: str
    student_ids: tuple[str, ...]
    student_display_names: tuple[str | None, ...]
    bands: tuple[int, ...]
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherReviewStatus:
    """Explicit selected review plus its live applicability."""

    selected_review_reference: GroupingSignalReviewReference | None
    decision: GroupingSignalReviewDecisionValue | None
    acknowledged_warning_ids: tuple[str, ...]
    actor_id: str | None
    reviewed_at: datetime | None
    applicability: GroupingSignalReviewApplicability | None


@dataclass(frozen=True, slots=True)
class GroupingSignalTeacherPreviewProjection:
    """Complete noncanonical teacher-facing view of one exact preview."""

    preview_reference: GroupingSignalPreviewReference
    class_id: str
    school_year: str
    period_id: str
    calendar_revision: int
    standard_id: str
    source_policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    target_scale_reference: ProficiencyScaleReference
    derivation_reference: GroupingSignalDerivationReference
    derivation_algorithm_version: str
    derivation_calculation_fingerprint: str
    live_currentness: GroupingSignalPreviewCurrentness
    policy_reference: GroupingSignalDerivationPolicyReference
    policy_title: str
    dimension_id: str
    band_count: int
    band_definitions: tuple[GroupingSignalBandDefinition, ...]
    tie_handling: str
    missing_result_handling: str
    insufficient_result_handling: str
    coverage: GroupingSignalPreviewCoverage
    band_summaries: tuple[GroupingSignalTeacherBandSummary, ...]
    student_assignments: tuple[GroupingSignalTeacherStudentRow, ...]
    ties: tuple[GroupingSignalTeacherTieGroup, ...]
    noncontributing_students: tuple[GroupingSignalTeacherStudentRow, ...]
    diagnostics: tuple[GroupingSignalTeacherDiagnostic, ...]
    review_status: GroupingSignalTeacherReviewStatus
    notices: tuple[str, str, str]


def build_grouping_signal_teacher_projection(
    workspace_root: str | Path,
    preview_reference: GroupingSignalPreviewReference,
) -> GroupingSignalTeacherPreviewProjection:
    """Build one read-only teacher view from an exact persisted #39 preview."""

    if not isinstance(preview_reference, GroupingSignalPreviewReference):
        raise GroupingSignalTeacherProjectionReadError(
            "preview_reference must be an exact #39 preview reference."
        )
    preview_reference.__post_init__()

    try:
        stored_preview = load_grouping_signal_preview_reference(
            workspace_root,
            preview_reference,
        )
    except GroupingSignalPreviewStorageError as error:
        raise GroupingSignalTeacherProjectionReadError(
            "Could not load the exact grouping-signal preview."
        ) from error

    preview = stored_preview.snapshot
    try:
        live_currentness = assess_grouping_signal_derivation_currentness(
            workspace_root,
            preview.derivation_reference,
        )
    except GroupingSignalCurrentnessError as error:
        raise GroupingSignalTeacherProjectionReadError(
            "Could not assess live derivation currentness."
        ) from error

    display_names = _current_display_names(
        workspace_root,
        preview.derivation_reference.class_id,
    )
    students = tuple(
        _teacher_student_row(row, display_names)
        for row in preview.student_rows
    )
    by_student = {row.student_id: row for row in students}

    band_summaries = tuple(
        _teacher_band_summary(summary, display_names)
        for summary in preview.band_summaries
    )
    ties = tuple(
        _teacher_tie_group(group, display_names)
        for group in preview.tie_groups
    )
    diagnostics = tuple(
        _teacher_diagnostic(item, display_names)
        for item in preview.diagnostics
    )
    noncontributors = tuple(
        by_student[row.student_id]
        for row in preview.student_rows
        if row.disposition == "noncontributing"
    )

    try:
        selected = load_current_grouping_signal_review(
            workspace_root,
            preview.derivation_reference.class_id,
            preview.derivation_reference.derivation_id,
        )
    except GroupingSignalReviewStorageError as error:
        raise GroupingSignalTeacherProjectionReadError(
            "Could not load the explicitly selected grouping-signal review."
        ) from error

    if selected is None:
        review_status = GroupingSignalTeacherReviewStatus(
            selected_review_reference=None,
            decision=None,
            acknowledged_warning_ids=(),
            actor_id=None,
            reviewed_at=None,
            applicability=None,
        )
    else:
        review_status = GroupingSignalTeacherReviewStatus(
            selected_review_reference=selected.reference,
            decision=selected.review.decision,
            acknowledged_warning_ids=selected.review.acknowledged_warning_ids,
            actor_id=selected.review.actor.actor_id,
            reviewed_at=selected.review.reviewed_at,
            applicability=assess_grouping_signal_review_applicability(
                selected.review,
                live_currentness,
            ),
        )

    basis = preview.academic_basis
    return GroupingSignalTeacherPreviewProjection(
        preview_reference=stored_preview.reference,
        class_id=preview.derivation_reference.class_id,
        school_year=basis.target_period.period.school_year,
        period_id=basis.target_period.period.period_id,
        calendar_revision=basis.target_period.calendar_revision,
        standard_id=basis.standard_id,
        source_policy_reference=basis.source_policy,
        target_scale_reference=basis.target_scale,
        derivation_reference=preview.derivation_reference,
        derivation_algorithm_version=preview.derivation_algorithm_version,
        derivation_calculation_fingerprint=(
            preview.derivation_calculation_fingerprint
        ),
        live_currentness=live_currentness,
        policy_reference=preview.policy_reference,
        policy_title=preview.policy_title,
        dimension_id=preview.dimension_id,
        band_count=preview.band_count,
        band_definitions=preview.band_definitions,
        tie_handling=preview.tie_handling,
        missing_result_handling=preview.missing_result_handling,
        insufficient_result_handling=preview.insufficient_result_handling,
        coverage=preview.coverage,
        band_summaries=band_summaries,
        student_assignments=students,
        ties=ties,
        noncontributing_students=noncontributors,
        diagnostics=diagnostics,
        review_status=review_status,
        notices=(
            PREVIEW_DOES_NOT_EXPORT_NOTICE,
            ACCEPTANCE_DOES_NOT_EXPORT_NOTICE,
            EXPORT_ONLY_IN_ISSUE_40_NOTICE,
        ),
    )


def format_grouping_signal_teacher_projection(
    projection: GroupingSignalTeacherPreviewProjection,
) -> str:
    """Render one deterministic plain-text teacher view."""

    if not isinstance(projection, GroupingSignalTeacherPreviewProjection):
        raise GroupingSignalTeacherProjectionReadError(
            "projection must be GroupingSignalTeacherPreviewProjection."
        )

    lines: list[str] = []
    _section(lines, "Class")
    lines.append(f"Class ID: {projection.class_id}")

    _section(lines, "Academic Basis")
    lines.extend(
        (
            f"School year: {projection.school_year}",
            f"Academic Period: {projection.period_id}",
            f"Calendar revision: {projection.calendar_revision}",
            f"Standard ID: {projection.standard_id}",
            f"#35 policy: {projection.source_policy_reference!r}",
            f"Proficiency scale: {projection.target_scale_reference!r}",
        )
    )

    _section(lines, "Derivation Identity")
    lines.extend(
        (
            f"Derivation: {projection.derivation_reference!r}",
            f"Algorithm: {projection.derivation_algorithm_version}",
            "Calculation fingerprint: "
            f"{projection.derivation_calculation_fingerprint}",
            f"Live currentness: {projection.live_currentness.state}",
        )
    )
    if projection.live_currentness.reason_codes:
        lines.append(
            "Currentness reasons: "
            + ", ".join(projection.live_currentness.reason_codes)
        )

    _section(lines, "Policy")
    lines.extend(
        (
            f"Policy: {projection.policy_reference!r}",
            f"Title: {projection.policy_title}",
            f"Dimension: {projection.dimension_id}",
            f"Band count: {projection.band_count}",
            f"Tie handling: {projection.tie_handling}",
            f"Missing-result handling: {projection.missing_result_handling}",
            "Insufficient-result handling: "
            f"{projection.insufficient_result_handling}",
        )
    )

    _section(lines, "Band Definitions")
    for definition in projection.band_definitions:
        lines.append(
            f"Band {definition.band}: scale positions "
            f"{definition.minimum_scale_position}-"
            f"{definition.maximum_scale_position}"
        )

    _section(lines, "Coverage")
    coverage = projection.coverage
    lines.extend(
        (
            f"Roster students: {coverage.roster_student_count}",
            f"Contributing students: {coverage.contributing_student_count}",
            f"Noncontributing students: {coverage.noncontributing_student_count}",
            f"Missing noncontributors: {coverage.missing_noncontributor_count}",
            "Insufficient-evidence noncontributors: "
            f"{coverage.insufficient_noncontributor_count}",
            f"Occupied bands: {coverage.occupied_band_count}",
            f"Empty bands: {coverage.empty_band_count}",
        )
    )

    _section(lines, "Band Distribution")
    for band in projection.band_summaries:
        lines.append(
            f"{band.label}: {band.student_count} student(s); "
            f"levels={','.join(band.proficiency_level_ids)}"
        )

    _section(lines, "Student Assignments")
    for student in projection.student_assignments:
        lines.append(_student_line(student))

    _section(lines, "Ties")
    if not projection.ties:
        lines.append("None.")
    else:
        for tie in projection.ties:
            lines.append(
                f"{tie.band_label}; level={tie.proficiency_level_id}; "
                f"scale_position={tie.scale_position}; "
                f"students={','.join(tie.student_ids)}"
            )

    _section(lines, "Noncontributing Students")
    if not projection.noncontributing_students:
        lines.append("None.")
    else:
        for student in projection.noncontributing_students:
            lines.append(_student_line(student))

    _section(lines, "Diagnostics / Limitations")
    if not projection.diagnostics:
        lines.append("None.")
    else:
        for item in projection.diagnostics:
            lines.append(
                f"[{item.severity}] {item.code} ({item.diagnostic_id}): "
                f"{item.message}"
            )

    _section(lines, "Review Status")
    review = projection.review_status
    if review.selected_review_reference is None:
        lines.append("No review revision is explicitly selected.")
    else:
        lines.extend(
            (
                f"Selected review: {review.selected_review_reference!r}",
                f"Decision: {review.decision}",
                "Acknowledged warning IDs: "
                + (
                    ", ".join(review.acknowledged_warning_ids)
                    if review.acknowledged_warning_ids
                    else "None"
                ),
                f"Teacher actor: {review.actor_id}",
                "Reviewed at: "
                + (
                    review.reviewed_at.isoformat()
                    if review.reviewed_at is not None
                    else "unavailable"
                ),
                "Applicability: "
                + (
                    review.applicability.status
                    if review.applicability is not None
                    else "unavailable"
                ),
            )
        )
        if (
            review.applicability is not None
            and review.applicability.reason_codes
        ):
            lines.append(
                "Applicability reasons: "
                + ", ".join(review.applicability.reason_codes)
            )

    _section(lines, "Export Boundary")
    lines.extend(projection.notices)
    return "\n".join(lines) + "\n"


def _teacher_student_row(
    row: GroupingSignalPreviewStudentRow,
    display_names: dict[str, str],
) -> GroupingSignalTeacherStudentRow:
    return GroupingSignalTeacherStudentRow(
        student_id=row.student_id,
        display_name=display_names.get(row.student_id),
        source_state=row.source_state,
        disposition=row.disposition,
        source_result=row.source_result,
        proficiency_level_id=row.proficiency_level_id,
        scale_position=row.scale_position,
        band=row.band,
    )


def _teacher_band_summary(
    summary: GroupingSignalPreviewBandSummary,
    display_names: dict[str, str],
) -> GroupingSignalTeacherBandSummary:
    return GroupingSignalTeacherBandSummary(
        band=summary.band,
        label=f"Band {summary.band}",
        minimum_scale_position=summary.minimum_scale_position,
        maximum_scale_position=summary.maximum_scale_position,
        proficiency_level_ids=summary.proficiency_level_ids,
        student_ids=summary.student_ids,
        student_display_names=tuple(
            display_names.get(student_id)
            for student_id in summary.student_ids
        ),
        student_count=summary.student_count,
    )


def _teacher_tie_group(
    group: GroupingSignalPreviewTieGroup,
    display_names: dict[str, str],
) -> GroupingSignalTeacherTieGroup:
    return GroupingSignalTeacherTieGroup(
        proficiency_level_id=group.proficiency_level_id,
        scale_position=group.scale_position,
        band=group.band,
        band_label=f"Band {group.band}",
        student_ids=group.student_ids,
        student_display_names=tuple(
            display_names.get(student_id)
            for student_id in group.student_ids
        ),
    )


def _teacher_diagnostic(
    item: GroupingSignalPreviewDiagnostic,
    display_names: dict[str, str],
) -> GroupingSignalTeacherDiagnostic:
    return GroupingSignalTeacherDiagnostic(
        diagnostic_id=item.diagnostic_id,
        code=item.code,
        severity=item.severity,
        message=_DIAGNOSTIC_MESSAGES[item.code],
        student_ids=item.student_ids,
        student_display_names=tuple(
            display_names.get(student_id)
            for student_id in item.student_ids
        ),
        bands=item.bands,
        details=item.details,
    )


def _current_display_names(
    workspace_root: str | Path,
    class_id: str,
) -> dict[str, str]:
    try:
        roster = load_roster(class_roster_path(workspace_root, class_id))
    except RosterError:
        return {}
    if roster.class_id != class_id:
        return {}
    return {
        student.student_id: student_display_name(student)
        for student in roster.students
    }


def _student_line(student: GroupingSignalTeacherStudentRow) -> str:
    name = (
        f" ({student.display_name})"
        if student.display_name is not None
        else ""
    )
    band = f"Band {student.band}" if student.band is not None else "none"
    level = (
        student.proficiency_level_id
        if student.proficiency_level_id is not None
        else "none"
    )
    position = (
        str(student.scale_position)
        if student.scale_position is not None
        else "none"
    )
    return (
        f"{student.student_id}{name}: source={student.source_state}; "
        f"disposition={student.disposition}; level={level}; "
        f"scale_position={position}; band={band}"
    )


def _section(lines: list[str], title: str) -> None:
    if lines:
        lines.append("")
    lines.append(title)
    lines.append("-" * len(title))
