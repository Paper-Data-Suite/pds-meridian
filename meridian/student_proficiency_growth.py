"""Student Proficiency Growth / Trajectory report for Issue #111 Slice 9.

The report describes immutable Academic Period proficiency result lineage. It
does not average attempts and does not infer historical selector events that
Meridian does not persist.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef, validate_academic_period_ref
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyAggregationPolicyReference,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_result_revisions,
    list_academic_period_proficiency_result_standard_ids,
    load_academic_period_proficiency_policy_revision,
    load_academic_period_proficiency_result_revision,
)
from meridian.proficiency_mapping import (
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)
from meridian.report_export_roster import (
    ExportRosterObservation,
    ReportExportRosterError,
    build_report_display_name_observation,
    export_roster_observation_sha256,
)
from meridian.standards_evidence import normalize_standard_id
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
)

TrajectoryChange: TypeAlias = Literal[
    "INITIAL",
    "UP",
    "DOWN",
    "UNCHANGED",
    "STATE_CHANGED",
    "UNCHANGED_STATE",
    "SCALE_CHANGED",
]


class StudentProficiencyGrowthError(RuntimeError):
    code = "student_proficiency_growth.error"


class StudentProficiencyGrowthValidationError(
    StudentProficiencyGrowthError,
    ValueError,
):
    code = "student_proficiency_growth.invalid"


class StudentProficiencyGrowthSourceError(StudentProficiencyGrowthError):
    code = "student_proficiency_growth.source_unavailable"


class StudentProficiencyGrowthCurrentnessConflictError(StudentProficiencyGrowthError):
    code = "student_proficiency_growth.currentness_conflict"


@dataclass(frozen=True, slots=True)
class ProficiencyTrajectoryRevision:
    class_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    student_id: str
    standard_id: str
    result_revision: int
    supersedes_revision: int | None
    result_sha256: str
    calculated_at: datetime
    target_scale: ProficiencyScaleReference
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    status: str
    proficiency_level_id: str | None
    inputs_sha256: str
    candidate_grade_item_ids: tuple[str, ...]
    contributing_grade_item_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "target_period",
            validate_academic_period_ref(self.target_period),
        )
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        try:
            standard_id = normalize_standard_id(self.standard_id)
        except ValueError as error:
            raise StudentProficiencyGrowthValidationError(str(error)) from error
        object.__setattr__(self, "standard_id", standard_id)
        revision = _positive_int(self.result_revision, "result_revision")
        object.__setattr__(self, "result_revision", revision)
        if revision == 1:
            if self.supersedes_revision is not None:
                raise StudentProficiencyGrowthValidationError(
                    "revision 1 must not supersede another result."
                )
        elif self.supersedes_revision != revision - 1:
            raise StudentProficiencyGrowthValidationError(
                "result revision must supersede the immediately prior revision."
            )
        object.__setattr__(
            self,
            "result_sha256",
            _sha256(self.result_sha256, "result_sha256"),
        )
        if self.calculated_at.tzinfo is None or self.calculated_at.utcoffset() is None:
            raise StudentProficiencyGrowthValidationError(
                "calculated_at must be timezone-aware."
            )
        object.__setattr__(
            self,
            "calculated_at",
            self.calculated_at.astimezone(UTC),
        )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StudentProficiencyGrowthValidationError(
                "target_scale must be ProficiencyScaleReference."
            )
        if not isinstance(
            self.policy_reference,
            AcademicPeriodProficiencyAggregationPolicyReference,
        ):
            raise StudentProficiencyGrowthValidationError(
                "policy_reference must be exact Academic Period policy provenance."
            )
        if self.status not in {"calculated", "insufficient_evidence"}:
            raise StudentProficiencyGrowthValidationError(
                "unsupported proficiency result status."
            )
        level = self.proficiency_level_id
        if self.status == "calculated":
            level = _identifier(level, "proficiency_level_id")
        elif level is not None:
            raise StudentProficiencyGrowthValidationError(
                "insufficient result must not carry a proficiency level."
            )
        object.__setattr__(self, "proficiency_level_id", level)
        object.__setattr__(
            self,
            "inputs_sha256",
            _sha256(self.inputs_sha256, "inputs_sha256"),
        )
        candidate = _grade_item_ids(
            self.candidate_grade_item_ids,
            "candidate_grade_item_ids",
        )
        contributing = _grade_item_ids(
            self.contributing_grade_item_ids,
            "contributing_grade_item_ids",
        )
        if any(item not in candidate for item in contributing):
            raise StudentProficiencyGrowthValidationError(
                "contributing Grade Items must be present in candidate Grade Items."
            )
        object.__setattr__(self, "candidate_grade_item_ids", candidate)
        object.__setattr__(self, "contributing_grade_item_ids", contributing)


@dataclass(frozen=True, slots=True)
class TrajectoryCurrentSelection:
    standard_id: str
    current_result_revision: int | None

    def __post_init__(self) -> None:
        try:
            standard = normalize_standard_id(self.standard_id)
        except ValueError as error:
            raise StudentProficiencyGrowthValidationError(str(error)) from error
        object.__setattr__(self, "standard_id", standard)
        if self.current_result_revision is not None:
            object.__setattr__(
                self,
                "current_result_revision",
                _positive_int(
                    self.current_result_revision,
                    "current_result_revision",
                ),
            )


@dataclass(frozen=True, slots=True)
class _GrowthState:
    observations: tuple[ProficiencyTrajectoryRevision, ...]
    selections: tuple[TrajectoryCurrentSelection, ...]
    scales: tuple[ProficiencyScale, ...]
    policies: tuple[AcademicPeriodProficiencyAggregationPolicy, ...]
    roster: ExportRosterObservation
    witness_sha256: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def trajectory_revision_observation(
    stored: StoredAcademicPeriodProficiencyResult,
) -> ProficiencyTrajectoryRevision:
    """Project one exact stored result revision into bounded trajectory state."""

    if not isinstance(stored, StoredAcademicPeriodProficiencyResult):
        raise StudentProficiencyGrowthValidationError(
            "stored must be StoredAcademicPeriodProficiencyResult."
        )
    stored.__post_init__()
    snapshot = stored.snapshot
    period = snapshot.target_period.period
    return ProficiencyTrajectoryRevision(
        class_id=snapshot.class_id,
        target_period=AcademicPeriodRef(period.school_year, period.period_id),
        calendar_revision=snapshot.target_period.calendar_revision,
        student_id=snapshot.student_id,
        standard_id=snapshot.standard_id,
        result_revision=snapshot.result_revision,
        supersedes_revision=snapshot.supersedes_revision,
        result_sha256=stored.result_sha256,
        calculated_at=snapshot.calculated_at,
        target_scale=snapshot.target_scale,
        policy_reference=snapshot.policy_reference,
        status=snapshot.outcome.status,
        proficiency_level_id=snapshot.outcome.proficiency_level_id,
        inputs_sha256=snapshot.inputs_sha256,
        candidate_grade_item_ids=tuple(
            item.grade_item.grade_item_id for item in snapshot.inputs.entries
        ),
        contributing_grade_item_ids=tuple(
            item.grade_item_id
            for item in snapshot.outcome.explanation_entries
            if item.contributed
        ),
    )


def build_student_proficiency_growth(
    workspace_root: str | Path,
    *,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    generated_at: datetime | None = None,
    standard_filter: tuple[str, ...] = (),
) -> TeacherReportPreview:
    """Build one live trajectory with append/selection currentness revalidation."""

    root = Path(workspace_root)
    initial = _capture_growth_state(
        root,
        class_id=class_id,
        student_id=student_id,
        target_period=target_period,
        standard_filter=standard_filter,
    )
    preview = compose_student_proficiency_growth(
        class_id=class_id,
        student_id=student_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        observations=initial.observations,
        current_selections=initial.selections,
        scales=initial.scales,
        policies=initial.policies,
        roster_observation=initial.roster,
        generated_at=utc_now() if generated_at is None else generated_at,
        standard_filter=standard_filter,
    )
    final = _capture_growth_state(
        root,
        class_id=class_id,
        student_id=student_id,
        target_period=target_period,
        standard_filter=standard_filter,
    )
    if final.witness_sha256 != initial.witness_sha256:
        raise StudentProficiencyGrowthCurrentnessConflictError(
            "Student proficiency trajectory changed during report generation."
        )
    return preview


def compose_student_proficiency_growth(
    *,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    observations: tuple[ProficiencyTrajectoryRevision, ...],
    current_selections: tuple[TrajectoryCurrentSelection, ...],
    scales: tuple[ProficiencyScale, ...],
    policies: tuple[AcademicPeriodProficiencyAggregationPolicy, ...],
    roster_observation: ExportRosterObservation,
    generated_at: datetime,
    standard_filter: tuple[str, ...] = (),
) -> TeacherReportPreview:
    """Compose exact revision lineage without averaging attempts."""

    checked_class = _identifier(class_id, "class_id")
    checked_student = _identifier(student_id, "student_id")
    checked_period = validate_academic_period_ref(target_period)
    checked_calendar = _positive_int(calendar_revision, "calendar_revision")

    if not isinstance(roster_observation, ExportRosterObservation):
        raise StudentProficiencyGrowthValidationError(
            "roster_observation must be ExportRosterObservation."
        )
    roster_observation.__post_init__()
    roster_names = {
        item.student_id: item.values[0].value for item in roster_observation.students
    }
    if (
        roster_observation.class_id != checked_class
        or roster_observation.source_fields != ("roster.display_name",)
        or tuple(roster_names) != (checked_student,)
    ):
        raise StudentProficiencyGrowthValidationError(
            "trajectory roster observation must contain exactly this student's "
            "display name."
        )

    scale_map: dict[tuple[str, int, str], ProficiencyScale] = {}
    for scale in scales:
        if not isinstance(scale, ProficiencyScale):
            raise StudentProficiencyGrowthValidationError(
                "scales must contain ProficiencyScale values."
            )
        scale.__post_init__()
        scale_reference = proficiency_scale_reference(scale)
        key = (
            scale_reference.scale_id,
            scale_reference.scale_revision,
            scale_reference.scale_sha256,
        )
        if key in scale_map:
            raise StudentProficiencyGrowthValidationError(
                "scales must not duplicate an exact scale scale_reference."
            )
        if scale_reference.class_id != checked_class:
            raise StudentProficiencyGrowthValidationError(
                "trajectory scale must match report class."
            )
        scale_map[key] = scale

    policy_map: dict[
        tuple[str, int, str],
        AcademicPeriodProficiencyAggregationPolicy,
    ] = {}
    for policy in policies:
        if not isinstance(policy, AcademicPeriodProficiencyAggregationPolicy):
            raise StudentProficiencyGrowthValidationError(
                "policies must contain AcademicPeriodProficiencyAggregationPolicy "
                "values."
            )
        policy.__post_init__()
        policy_reference = academic_period_proficiency_aggregation_policy_reference(
            policy
        )
        key = (
            policy_reference.policy_id,
            policy_reference.policy_revision,
            policy_reference.policy_sha256,
        )
        if key in policy_map:
            raise StudentProficiencyGrowthValidationError(
                "policies must not duplicate an exact policy policy_reference."
            )
        if policy_reference.class_id != checked_class:
            raise StudentProficiencyGrowthValidationError(
                "trajectory policy must match report class."
            )
        policy_map[key] = policy

    history = tuple(observations)
    if not history:
        raise StudentProficiencyGrowthValidationError(
            "student trajectory requires at least one proficiency result revision."
        )
    for item in history:
        if not isinstance(item, ProficiencyTrajectoryRevision):
            raise StudentProficiencyGrowthValidationError(
                "observations must contain ProficiencyTrajectoryRevision values."
            )
        if (
            item.class_id != checked_class
            or item.student_id != checked_student
            or item.target_period != checked_period
        ):
            raise StudentProficiencyGrowthValidationError(
                "trajectory observation scope does not match report scope."
            )
        scale_key = (
            item.target_scale.scale_id,
            item.target_scale.scale_revision,
            item.target_scale.scale_sha256,
        )
        if scale_key not in scale_map:
            raise StudentProficiencyGrowthValidationError(
                "trajectory observation exact target scale is unavailable."
            )
        policy_key = (
            item.policy_reference.policy_id,
            item.policy_reference.policy_revision,
            item.policy_reference.policy_sha256,
        )
        if policy_key not in policy_map:
            raise StudentProficiencyGrowthValidationError(
                "trajectory observation exact policy is unavailable."
            )

    by_standard: dict[str, list[ProficiencyTrajectoryRevision]] = {}
    for item in history:
        by_standard.setdefault(item.standard_id, []).append(item)
    for standard_id, values in by_standard.items():
        ordered = sorted(values, key=lambda item: item.result_revision)
        expected = list(range(1, len(ordered) + 1))
        if [item.result_revision for item in ordered] != expected:
            raise StudentProficiencyGrowthValidationError(
                f"trajectory revisions for {standard_id!r} are not contiguous."
            )
        by_standard[standard_id] = ordered

    selection_map: dict[str, int | None] = {}
    for selection in current_selections:
        if not isinstance(selection, TrajectoryCurrentSelection):
            raise StudentProficiencyGrowthValidationError(
                "current_selections must contain TrajectoryCurrentSelection values."
            )
        if selection.standard_id in selection_map:
            raise StudentProficiencyGrowthValidationError(
                "current selections must not duplicate a standard."
            )
        if selection.standard_id not in by_standard:
            raise StudentProficiencyGrowthValidationError(
                "current selection identifies a standard absent from trajectory."
            )
        if (
            selection.current_result_revision is not None
            and selection.current_result_revision
            not in {item.result_revision for item in by_standard[selection.standard_id]}
        ):
            raise StudentProficiencyGrowthValidationError(
                "current selection references a revision absent from trajectory."
            )
        selection_map[selection.standard_id] = selection.current_result_revision
    if set(selection_map) != set(by_standard):
        raise StudentProficiencyGrowthValidationError(
            "current selections must cover every trajectory standard exactly once."
        )
    for standard_id, current_revision in selection_map.items():
        if current_revision is None:
            continue
        current = next(
            item
            for item in by_standard[standard_id]
            if item.result_revision == current_revision
        )
        if current.calendar_revision != checked_calendar:
            raise StudentProficiencyGrowthValidationError(
                "current selected proficiency result uses a different report "
                "calendar revision."
            )

    requested = _standard_ids(standard_filter)
    if requested:
        unknown = tuple(item for item in requested if item not in by_standard)
        if unknown:
            raise StudentProficiencyGrowthValidationError(
                "standard_filter contains a standard with no trajectory history: "
                f"{unknown!r}."
            )
        selected_standards = requested
    else:
        selected_standards = tuple(sorted(by_standard))

    rows: list[TeacherReportRow] = []
    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "roster_observation",
            "display_name",
            export_roster_observation_sha256(roster_observation),
        )
    ]
    diagnostics: list[TeacherReportDiagnostic] = []
    trajectory_summary: list[str] = []
    row_index = 0

    used_scale_keys: set[tuple[str, int, str]] = set()
    used_policy_keys: set[tuple[str, int, str]] = set()

    for standard_id in selected_standards:
        revisions = by_standard[standard_id]
        current_revision = selection_map[standard_id]
        if current_revision is None:
            diagnostics.append(
                TeacherReportDiagnostic(
                    f"student_growth.no_current.{_diagnostic_suffix(standard_id)}",
                    "info",
                    f"{standard_id} has result history but no current "
                    "selected revision.",
                )
            )
        labels: list[str] = []
        previous: ProficiencyTrajectoryRevision | None = None
        for item in revisions:
            row_index += 1
            scale_key = (
                item.target_scale.scale_id,
                item.target_scale.scale_revision,
                item.target_scale.scale_sha256,
            )
            scale = scale_map[scale_key]
            used_scale_keys.add(scale_key)
            policy_key = (
                item.policy_reference.policy_id,
                item.policy_reference.policy_revision,
                item.policy_reference.policy_sha256,
            )
            policy = policy_map[policy_key]
            used_policy_keys.add(policy_key)

            label = _proficiency_label(item, scale)
            labels.append(label)
            change = _change(previous, item, scale_map)
            lineage = _lineage_label(
                item.result_revision,
                max_revision=revisions[-1].result_revision,
                current_revision=current_revision,
            )
            basis = _basis_change(previous, item)
            rows.append(
                TeacherReportRow(
                    f"trajectory_{row_index:05d}",
                    (
                        standard_id,
                        str(item.result_revision),
                        lineage,
                        item.calculated_at.isoformat(),
                        str(item.calendar_revision),
                        label,
                        change,
                        ", ".join(item.contributing_grade_item_ids) or "none",
                        basis,
                        _policy_display(policy),
                    ),
                )
            )
            sources.append(
                TeacherReportSourceReference(
                    "academic_period_proficiency_result",
                    f"{checked_student}|{standard_id}|r{item.result_revision}",
                    item.result_sha256,
                )
            )
            previous = item

        trajectory_summary.append(
            f"{standard_id}: {' -> '.join(labels)}; "
            + (
                "no current selected revision."
                if current_revision is None
                else f"current selection r{current_revision}."
            )
        )

    for scale_id, revision, digest in sorted(used_scale_keys):
        sources.append(
            TeacherReportSourceReference(
                "proficiency_scale",
                f"{scale_id}:r{revision}",
                digest,
            )
        )
    for policy_id, revision, digest in sorted(used_policy_keys):
        sources.append(
            TeacherReportSourceReference(
                "academic_period_proficiency_policy",
                f"{policy_id}:r{revision}",
                digest,
            )
        )

    selection_witness = [
        {
            "standard_id": standard_id,
            "current_result_revision": selection_map[standard_id],
        }
        for standard_id in selected_standards
    ]
    sources.append(
        TeacherReportSourceReference(
            "current_proficiency_selection",
            checked_student,
            _json_sha256(selection_witness),
        )
    )

    summary = (
        f"Student: {roster_names[checked_student]} ({checked_student}).",
        "Trajectory follows exact immutable Academic Period proficiency result "
        "revision lineage; historical attempts are not averaged.",
        "Meridian does not persist historical selector events here; the report "
        "marks the current selected revision and does not invent past selections.",
        f"Requested report calendar revision: {checked_calendar}. Historical result "
        "rows retain their own recorded calendar revisions.",
        *trajectory_summary,
    )

    return compose_teacher_report_preview(
        report_kind="student_proficiency_growth",
        title="Student Proficiency Growth / Trajectory",
        class_id=checked_class,
        target_period=checked_period,
        calendar_revision=checked_calendar,
        source_references=sources,
        generated_at=generated_at,
        summary=summary,
        columns=(
            TeacherReportColumn("standard", "Standard"),
            TeacherReportColumn("revision", "Revision"),
            TeacherReportColumn("lineage", "Lineage"),
            TeacherReportColumn("calculated_at", "Calculated At"),
            TeacherReportColumn("calendar_revision", "Calendar Revision"),
            TeacherReportColumn("proficiency", "Result Proficiency"),
            TeacherReportColumn("change", "Change"),
            TeacherReportColumn(
                "participating_grade_items",
                "Participating Grade Items",
            ),
            TeacherReportColumn("evidence_basis", "Evidence Basis"),
            TeacherReportColumn("policy", "Policy / Decision Provenance"),
        ),
        rows=rows,
        diagnostics=diagnostics,
    )


def _capture_growth_state(
    root: Path,
    *,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    standard_filter: tuple[str, ...],
) -> _GrowthState:
    checked_class = _identifier(class_id, "class_id")
    checked_student = _identifier(student_id, "student_id")
    checked_period = validate_academic_period_ref(target_period)
    requested = _standard_ids(standard_filter)
    try:
        available = list_academic_period_proficiency_result_standard_ids(
            root,
            checked_class,
            checked_period.school_year,
            checked_period.period_id,
            checked_student,
        )
        if requested:
            unknown = tuple(item for item in requested if item not in available)
            if unknown:
                raise StudentProficiencyGrowthSourceError(
                    "Requested standard has no Academic Period proficiency history: "
                    f"{unknown!r}."
                )
            standards = requested
        else:
            standards = available
        if not standards:
            raise StudentProficiencyGrowthSourceError(
                "Student has no Academic Period proficiency result history."
            )

        observations: list[ProficiencyTrajectoryRevision] = []
        selections: list[TrajectoryCurrentSelection] = []
        scale_refs: dict[tuple[str, int, str], ProficiencyScaleReference] = {}
        policy_refs: dict[
            tuple[str, int, str],
            AcademicPeriodProficiencyAggregationPolicyReference,
        ] = {}
        witness_histories: list[dict[str, object]] = []

        for standard_id in standards:
            revisions = list_academic_period_proficiency_result_revisions(
                root,
                checked_class,
                checked_period.school_year,
                checked_period.period_id,
                checked_student,
                standard_id,
            )
            current_revision = get_current_academic_period_proficiency_result_revision(
                root,
                checked_class,
                checked_period.school_year,
                checked_period.period_id,
                checked_student,
                standard_id,
            )
            selections.append(TrajectoryCurrentSelection(standard_id, current_revision))
            revision_digests: list[dict[str, object]] = []
            for revision in revisions:
                stored = load_academic_period_proficiency_result_revision(
                    root,
                    checked_class,
                    checked_period.school_year,
                    checked_period.period_id,
                    checked_student,
                    standard_id,
                    revision,
                )
                observation = trajectory_revision_observation(stored)
                observations.append(observation)
                scale_reference = observation.target_scale
                scale_key = (
                    scale_reference.scale_id,
                    scale_reference.scale_revision,
                    scale_reference.scale_sha256,
                )
                scale_refs[scale_key] = scale_reference
                policy_reference = observation.policy_reference
                policy_key = (
                    policy_reference.policy_id,
                    policy_reference.policy_revision,
                    policy_reference.policy_sha256,
                )
                policy_refs[policy_key] = policy_reference
                revision_digests.append(
                    {
                        "revision": revision,
                        "result_sha256": observation.result_sha256,
                    }
                )
            witness_histories.append(
                {
                    "standard_id": standard_id,
                    "revisions": revision_digests,
                    "current_result_revision": current_revision,
                }
            )

        scales: list[ProficiencyScale] = []
        for key in sorted(scale_refs):
            exact_scale_reference = scale_refs[key]
            stored_scale = load_proficiency_scale_revision(
                root,
                exact_scale_reference.class_id,
                exact_scale_reference.scale_id,
                exact_scale_reference.scale_revision,
            )
            if stored_scale.reference != exact_scale_reference:
                raise StudentProficiencyGrowthSourceError(
                    "Trajectory target-scale digest does not match exact history."
                )
            scales.append(stored_scale.scale)

        policies: list[AcademicPeriodProficiencyAggregationPolicy] = []
        for key in sorted(policy_refs):
            exact_policy_reference = policy_refs[key]
            stored_policy = load_academic_period_proficiency_policy_revision(
                root,
                exact_policy_reference.class_id,
                exact_policy_reference.policy_id,
                exact_policy_reference.policy_revision,
            )
            if stored_policy.reference != exact_policy_reference:
                raise StudentProficiencyGrowthSourceError(
                    "Trajectory aggregation-policy digest does not match exact history."
                )
            policies.append(stored_policy.policy)

        roster = build_report_display_name_observation(
            root,
            checked_class,
            (checked_student,),
        )
    except StudentProficiencyGrowthError:
        raise
    except (
        AcademicPeriodProficiencyStorageError,
        ProficiencyMappingStorageError,
        ReportExportRosterError,
        OSError,
        ValueError,
    ) as error:
        raise StudentProficiencyGrowthSourceError(
            "Student proficiency trajectory source state could not be verified safely."
        ) from error

    witness = {
        "roster_sha256": export_roster_observation_sha256(roster),
        "histories": witness_histories,
        "scales": [
            {
                "scale_id": reference.scale_id,
                "scale_revision": reference.scale_revision,
                "scale_sha256": reference.scale_sha256,
            }
            for reference in sorted(
                scale_refs.values(),
                key=lambda item: (
                    item.scale_id,
                    item.scale_revision,
                    item.scale_sha256,
                ),
            )
        ],
        "policies": [
            {
                "policy_id": reference.policy_id,
                "policy_revision": reference.policy_revision,
                "policy_sha256": reference.policy_sha256,
            }
            for reference in sorted(
                policy_refs.values(),
                key=lambda item: (
                    item.policy_id,
                    item.policy_revision,
                    item.policy_sha256,
                ),
            )
        ],
    }
    return _GrowthState(
        observations=tuple(observations),
        selections=tuple(selections),
        scales=tuple(scales),
        policies=tuple(policies),
        roster=roster,
        witness_sha256=_json_sha256(witness),
    )


def _proficiency_label(
    item: ProficiencyTrajectoryRevision,
    scale: ProficiencyScale,
) -> str:
    if item.status == "insufficient_evidence":
        return "Insufficient evidence"
    level_id = item.proficiency_level_id
    for level in scale.levels:
        if level.level_id == level_id:
            return level.label
    raise StudentProficiencyGrowthValidationError(
        "calculated trajectory level is absent from exact target scale."
    )


def _change(
    previous: ProficiencyTrajectoryRevision | None,
    current: ProficiencyTrajectoryRevision,
    scale_map: dict[tuple[str, int, str], ProficiencyScale],
) -> TrajectoryChange:
    if previous is None:
        return "INITIAL"
    if previous.target_scale != current.target_scale:
        return "SCALE_CHANGED"
    if previous.status != current.status:
        return "STATE_CHANGED"
    if current.status == "insufficient_evidence":
        return "UNCHANGED_STATE"
    key = (
        current.target_scale.scale_id,
        current.target_scale.scale_revision,
        current.target_scale.scale_sha256,
    )
    scale = scale_map[key]
    positions = {level.level_id: level.position for level in scale.levels}
    previous_level = previous.proficiency_level_id
    current_level = current.proficiency_level_id
    if previous_level not in positions or current_level not in positions:
        raise StudentProficiencyGrowthValidationError(
            "trajectory level is absent from exact target scale."
        )
    if positions[current_level] > positions[previous_level]:
        return "UP"
    if positions[current_level] < positions[previous_level]:
        return "DOWN"
    return "UNCHANGED"


def _lineage_label(
    revision: int,
    *,
    max_revision: int,
    current_revision: int | None,
) -> str:
    if revision == current_revision and revision < max_revision:
        return "CURRENT_SELECTED / SUPERSEDED"
    if revision == current_revision:
        return "CURRENT_SELECTED"
    if revision < max_revision:
        return "SUPERSEDED"
    return "LATEST_UNSELECTED"


def _basis_change(
    previous: ProficiencyTrajectoryRevision | None,
    current: ProficiencyTrajectoryRevision,
) -> str:
    if previous is None:
        return "initial basis"
    if previous.inputs_sha256 == current.inputs_sha256:
        return "unchanged"
    old = set(previous.contributing_grade_item_ids)
    new = set(current.contributing_grade_item_ids)
    added = sorted(new - old)
    removed = sorted(old - new)
    parts = ["changed"]
    if added:
        parts.append("+" + ",".join(added))
    if removed:
        parts.append("-" + ",".join(removed))
    if not added and not removed:
        parts.append("same participating Grade Items")
    return "; ".join(parts)


def _policy_display(policy: AcademicPeriodProficiencyAggregationPolicy) -> str:
    actor = f"{policy.actor.kind}:{policy.actor.actor_id}"
    rationale = "none" if policy.rationale is None else policy.rationale
    return (
        f"{policy.title} r{policy.policy_revision}; actor={actor}; "
        f"rationale={rationale}"
    )


def _standard_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    try:
        standards = tuple(normalize_standard_id(item) for item in values)
    except ValueError as error:
        raise StudentProficiencyGrowthValidationError(str(error)) from error
    if len(set(standards)) != len(standards):
        raise StudentProficiencyGrowthValidationError(
            "standard_filter must not contain duplicates."
        )
    return tuple(sorted(standards))


def _grade_item_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    ids = tuple(_identifier(item, "grade_item_id") for item in values)
    if len(set(ids)) != len(ids):
        raise StudentProficiencyGrowthValidationError(
            f"{label} must not contain duplicates."
        )
    if ids != tuple(sorted(ids)):
        raise StudentProficiencyGrowthValidationError(
            f"{label} must use canonical Grade Item ordering."
        )
    return ids


def _diagnostic_suffix(standard_id: str) -> str:
    return hashlib.sha256(standard_id.encode("utf-8")).hexdigest()[:16]


def _identifier(value: str | None, label: str) -> str:
    if value is None:
        raise StudentProficiencyGrowthValidationError(f"{label} must not be null.")
    try:
        return validate_identifier(value, field_name=label)
    except IdentifierValidationError as error:
        raise StudentProficiencyGrowthValidationError(str(error)) from error


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise StudentProficiencyGrowthValidationError(
            f"{label} must be a positive integer."
        )
    return value


def _sha256(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StudentProficiencyGrowthValidationError(
            f"{label} must be a lowercase SHA-256 digest."
        )
    return value


def _json_sha256(value: object) -> str:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ProficiencyTrajectoryRevision",
    "StudentProficiencyGrowthCurrentnessConflictError",
    "StudentProficiencyGrowthError",
    "StudentProficiencyGrowthSourceError",
    "StudentProficiencyGrowthValidationError",
    "TrajectoryChange",
    "TrajectoryCurrentSelection",
    "build_student_proficiency_growth",
    "compose_student_proficiency_growth",
    "trajectory_revision_observation",
]
