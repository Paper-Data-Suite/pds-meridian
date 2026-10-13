"""Class Standards Profile report for Meridian Issue #111 Slice 9.

The report projects explicitly selected Academic Period proficiency state into a
class-wide matrix and per-standard distributions. It never calculates new
proficiency, invents a missing judgment, or converts absence to a low level.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pds_core.academic_periods import AcademicPeriodRef, validate_academic_period_ref
from pds_core.classes import load_class_roster
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.rosters import RosterError

from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    list_current_academic_period_proficiency_results,
)
from meridian.grade_policy import (
    GradePolicyReference,
    HybridGradeConfiguration,
    ProfileStandardGroup,
    StandardsBasedGradeConfiguration,
)
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationStorageError,
    resolve_grade_policy_activation,
)
from meridian.grade_policy_storage import (
    GradePolicyStorageError,
    load_grade_policy_revision,
)
from meridian.proficiency_mapping import (
    ProficiencyScale,
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
from meridian.sis_gradebook_reconciliation import (
    CurrentProficiencyObservation,
    current_proficiency_observation,
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


class ClassStandardsProfileError(RuntimeError):
    """Base error for the class standards profile report."""

    code = "class_standards_profile.error"


class ClassStandardsProfileValidationError(ClassStandardsProfileError, ValueError):
    code = "class_standards_profile.invalid"


class ClassStandardsProfileSourceError(ClassStandardsProfileError):
    code = "class_standards_profile.source_unavailable"


class ClassStandardsProfileCurrentnessConflictError(ClassStandardsProfileError):
    code = "class_standards_profile.currentness_conflict"


@dataclass(frozen=True, slots=True)
class _ProfileState:
    scale: ProficiencyScale
    standard_ids: tuple[str, ...]
    profile_groups: tuple[ProfileStandardGroup, ...]
    roster: ExportRosterObservation
    observations: tuple[CurrentProficiencyObservation, ...]
    policy_reference: GradePolicyReference
    activation_reference: GradePolicyActivationReference
    witness_sha256: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_current_class_standards_profile(
    workspace_root: str | Path,
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    generated_at: datetime | None = None,
    standard_filter: tuple[str, ...] = (),
    student_filter: tuple[str, ...] = (),
    proficiency_level_filter: tuple[str, ...] = (),
    profile_group_filter: str | None = None,
) -> TeacherReportPreview:
    """Build a live matrix with optimistic currentness revalidation."""

    root = Path(workspace_root)
    initial = _capture_profile_state(
        root,
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
    )
    preview = compose_class_standards_profile(
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        target_scale=initial.scale,
        reporting_standard_ids=initial.standard_ids,
        roster_observation=initial.roster,
        current_observations=initial.observations,
        generated_at=utc_now() if generated_at is None else generated_at,
        policy_reference=initial.policy_reference,
        activation_reference=initial.activation_reference,
        profile_groups=initial.profile_groups,
        standard_filter=standard_filter,
        student_filter=student_filter,
        proficiency_level_filter=proficiency_level_filter,
        profile_group_filter=profile_group_filter,
    )
    final = _capture_profile_state(
        root,
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
    )
    if final.witness_sha256 != initial.witness_sha256:
        raise ClassStandardsProfileCurrentnessConflictError(
            "Class standards profile basis changed during report generation."
        )
    return preview


def compose_class_standards_profile(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    target_scale: ProficiencyScale,
    reporting_standard_ids: tuple[str, ...],
    roster_observation: ExportRosterObservation,
    current_observations: tuple[CurrentProficiencyObservation, ...],
    generated_at: datetime,
    policy_reference: GradePolicyReference | None = None,
    activation_reference: GradePolicyActivationReference | None = None,
    profile_groups: tuple[ProfileStandardGroup, ...] = (),
    standard_filter: tuple[str, ...] = (),
    student_filter: tuple[str, ...] = (),
    proficiency_level_filter: tuple[str, ...] = (),
    profile_group_filter: str | None = None,
) -> TeacherReportPreview:
    """Compose a deterministic matrix and distributions from bounded authority."""

    checked_class = _identifier(class_id, "class_id")
    checked_period = validate_academic_period_ref(target_period)
    checked_calendar = _positive_int(calendar_revision, "calendar_revision")

    if not isinstance(target_scale, ProficiencyScale):
        raise ClassStandardsProfileValidationError(
            "target_scale must be a ProficiencyScale."
        )
    target_scale.__post_init__()
    if target_scale.class_id != checked_class:
        raise ClassStandardsProfileValidationError(
            "target scale must match report class."
        )
    scale_reference = proficiency_scale_reference(target_scale)

    standards = _standard_ids(reporting_standard_ids, "reporting_standard_ids")
    if not standards:
        raise ClassStandardsProfileValidationError(
            "class standards profile requires at least one reporting standard."
        )
    groups = _profile_groups(profile_groups, standards)

    selected_standards = standards
    if profile_group_filter is not None:
        group_id = _identifier(profile_group_filter, "profile_group_filter")
        group = next((item for item in groups if item.group_id == group_id), None)
        if group is None:
            raise ClassStandardsProfileValidationError(
                "profile_group_filter does not identify an active policy group."
            )
        selected_standards = group.standard_ids

    requested_standards = _standard_ids(standard_filter, "standard_filter")
    if requested_standards:
        unknown = tuple(
            item for item in requested_standards if item not in selected_standards
        )
        if unknown:
            raise ClassStandardsProfileValidationError(
                "standard_filter contains a standard outside the selected "
                f"reporting scope: {unknown!r}."
            )
        selected_standards = requested_standards

    if not isinstance(roster_observation, ExportRosterObservation):
        raise ClassStandardsProfileValidationError(
            "roster_observation must be ExportRosterObservation."
        )
    roster_observation.__post_init__()
    if (
        roster_observation.class_id != checked_class
        or roster_observation.source_fields != ("roster.display_name",)
    ):
        raise ClassStandardsProfileValidationError(
            "roster observation must contain only display names for the report class."
        )
    roster_names = {
        student.student_id: student.values[0].value
        for student in roster_observation.students
    }

    requested_students = _student_ids(student_filter)
    if requested_students:
        unknown_students = tuple(
            item for item in requested_students if item not in roster_names
        )
        if unknown_students:
            raise ClassStandardsProfileValidationError(
                "student_filter contains a student outside the current roster: "
                f"{unknown_students!r}."
            )
        candidate_students = requested_students
    else:
        candidate_students = tuple(sorted(roster_names))

    level_ids = tuple(level.level_id for level in target_scale.levels)
    level_labels = {level.level_id: level.label for level in target_scale.levels}
    requested_levels = _level_ids(proficiency_level_filter)
    unknown_levels = tuple(item for item in requested_levels if item not in level_ids)
    if unknown_levels:
        raise ClassStandardsProfileValidationError(
            "proficiency_level_filter contains an unknown target-scale level: "
            f"{unknown_levels!r}."
        )

    observation_map: dict[
        tuple[str, str],
        CurrentProficiencyObservation,
    ] = {}
    for observation in current_observations:
        if not isinstance(observation, CurrentProficiencyObservation):
            raise ClassStandardsProfileValidationError(
                "current_observations must contain CurrentProficiencyObservation."
            )
        key = (observation.student_id, observation.standard_id)
        if key in observation_map:
            raise ClassStandardsProfileValidationError(
                "current observations must not duplicate student/standard identity."
            )
        if observation.class_id != checked_class:
            raise ClassStandardsProfileValidationError(
                "current observation class does not match report class."
            )
        if observation.target_period != checked_period:
            continue
        if observation.student_id not in roster_names:
            continue
        if observation.standard_id not in standards:
            continue
        if observation.calendar_revision != checked_calendar:
            raise ClassStandardsProfileValidationError(
                "selected proficiency result uses a different calendar revision."
            )
        if observation.target_scale != scale_reference:
            raise ClassStandardsProfileValidationError(
                "selected proficiency result uses a different exact target scale."
            )
        observation_map[key] = observation

    visible_students = candidate_students
    if requested_levels:
        matching_students: list[str] = []
        for student_id in candidate_students:
            matches_requested_level = False
            for standard_id in selected_standards:
                filter_observation = observation_map.get((student_id, standard_id))
                if (
                    filter_observation is not None
                    and filter_observation.status == "calculated"
                    and filter_observation.proficiency_level_id in requested_levels
                ):
                    matches_requested_level = True
                    break
            if matches_requested_level:
                matching_students.append(student_id)
        visible_students = tuple(matching_students)

    columns = [
        TeacherReportColumn("student_id", "Student ID"),
        TeacherReportColumn("student_name", "Student"),
    ]
    columns.extend(
        TeacherReportColumn(f"standard_{index:03d}", standard_id)
        for index, standard_id in enumerate(selected_standards, start=1)
    )

    rows: list[TeacherReportRow] = []
    for index, student_id in enumerate(visible_students, start=1):
        cells: list[str | None] = [
            student_id,
            roster_names[student_id],
        ]
        for standard_id in selected_standards:
            cell_observation = observation_map.get((student_id, standard_id))
            if cell_observation is None:
                cells.append("No current judgment")
            elif cell_observation.status == "insufficient_evidence":
                cells.append("Insufficient evidence")
            else:
                cell_level_id = cast(
                    str,
                    cell_observation.proficiency_level_id,
                )
                try:
                    cells.append(level_labels[cell_level_id])
                except KeyError as error:
                    raise ClassStandardsProfileValidationError(
                        "calculated observation level is absent from target scale."
                    ) from error
        rows.append(
            TeacherReportRow(
                f"student_{index:04d}",
                tuple(cells),
            )
        )

    distribution_specs: list[tuple[str, str, str | None]] = [
        (level.label, "level", level.level_id) for level in target_scale.levels
    ]
    distribution_specs.extend(
        (
            ("Insufficient evidence", "insufficient", None),
            ("No current judgment", "absent", None),
        )
    )
    for index, (label, kind, distribution_level_id) in enumerate(
        distribution_specs,
        start=1,
    ):
        cells = [None, f"Count — {label}"]
        for standard_id in selected_standards:
            count = 0
            for student_id in visible_students:
                distribution_observation = observation_map.get(
                    (student_id, standard_id)
                )
                if kind == "absent":
                    count += int(distribution_observation is None)
                elif kind == "insufficient":
                    count += int(
                        distribution_observation is not None
                        and distribution_observation.status == "insufficient_evidence"
                    )
                else:
                    count += int(
                        distribution_observation is not None
                        and distribution_observation.status == "calculated"
                        and distribution_observation.proficiency_level_id
                        == distribution_level_id
                    )
            cells.append(str(count))
        rows.append(
            TeacherReportRow(
                f"zz_distribution_{index:04d}",
                tuple(cells),
            )
        )

    matrix_observation: list[dict[str, object]] = []
    for student_id in visible_students:
        for standard_id in selected_standards:
            matrix_selected = observation_map.get((student_id, standard_id))
            selected_state: dict[str, object] | None
            if matrix_selected is None:
                selected_state = None
            else:
                selected_state = {
                    "result_revision": matrix_selected.result_revision,
                    "result_sha256": matrix_selected.result_sha256,
                    "status": matrix_selected.status,
                    "proficiency_level_id": (matrix_selected.proficiency_level_id),
                }
            matrix_observation.append(
                {
                    "student_id": student_id,
                    "standard_id": standard_id,
                    "selected": selected_state,
                }
            )
    matrix_sha256 = _json_sha256(matrix_observation)

    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "proficiency_scale",
            f"{scale_reference.scale_id}:r{scale_reference.scale_revision}",
            scale_reference.scale_sha256,
        ),
        TeacherReportSourceReference(
            "roster_observation",
            "display_names",
            export_roster_observation_sha256(roster_observation),
        ),
        TeacherReportSourceReference(
            "current_proficiency_selection",
            "class_standards_matrix",
            matrix_sha256,
        ),
    ]
    if policy_reference is not None:
        sources.append(
            TeacherReportSourceReference(
                "grade_policy",
                f"{policy_reference.policy_id}:r{policy_reference.policy_revision}",
                policy_reference.policy_sha256,
            )
        )
    if activation_reference is not None:
        sources.append(
            TeacherReportSourceReference(
                "grade_policy_activation",
                f"{activation_reference.school_year}:"
                f"{activation_reference.period_id}:"
                f"r{activation_reference.activation_revision}",
                activation_reference.activation_sha256,
            )
        )

    for student_id in visible_students:
        for standard_id in selected_standards:
            source_observation = observation_map.get((student_id, standard_id))
            if source_observation is None:
                continue
            sources.append(
                TeacherReportSourceReference(
                    "academic_period_proficiency_result",
                    f"{student_id}|{standard_id}|r{source_observation.result_revision}",
                    source_observation.result_sha256,
                )
            )

    missing_count = 0
    insufficient_count = 0
    for student_id in visible_students:
        for standard_id in selected_standards:
            count_observation = observation_map.get((student_id, standard_id))
            if count_observation is None:
                missing_count += 1
            elif count_observation.status == "insufficient_evidence":
                insufficient_count += 1
    diagnostics: list[TeacherReportDiagnostic] = []
    if missing_count:
        diagnostics.append(
            TeacherReportDiagnostic(
                "standards_profile.no_current_judgment",
                "info",
                f"{missing_count} matrix cells have no current selected judgment.",
            )
        )
    if insufficient_count:
        diagnostics.append(
            TeacherReportDiagnostic(
                "standards_profile.insufficient_evidence",
                "info",
                f"{insufficient_count} matrix cells retain "
                "insufficient evidence state.",
            )
        )

    summary = (
        f"Students shown: {len(visible_students)}.",
        f"Reporting standards shown: {len(selected_standards)}.",
        f"Exact proficiency scale: {target_scale.title} "
        f"(revision {target_scale.scale_revision}).",
        "No current judgment is preserved as absence and is never converted "
        "to a low proficiency level.",
    )

    return compose_teacher_report_preview(
        report_kind="class_standards_profile",
        title="Class Standards Profile",
        class_id=checked_class,
        target_period=checked_period,
        calendar_revision=checked_calendar,
        source_references=sources,
        generated_at=generated_at,
        summary=summary,
        columns=columns,
        rows=rows,
        diagnostics=diagnostics,
    )


def _capture_profile_state(
    root: Path,
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> _ProfileState:
    checked_class = _identifier(class_id, "class_id")
    checked_period = validate_academic_period_ref(target_period)
    checked_calendar = _positive_int(calendar_revision, "calendar_revision")
    try:
        activation = resolve_grade_policy_activation(
            root,
            checked_class,
            checked_period,
        )
        if (
            activation.status != "activated"
            or activation.activation is None
            or activation.policy_reference is None
        ):
            raise ClassStandardsProfileSourceError(
                "Class Standards Profile requires an explicitly activated "
                "standards-capable Grade policy for this Academic Period."
            )
        if activation.activation.decision.calendar_revision != checked_calendar:
            raise ClassStandardsProfileSourceError(
                "Active Grade policy uses a different Academic Period calendar "
                "revision."
            )
        activation_reference = activation.activation.reference
        policy_reference = activation.policy_reference
        stored_policy = load_grade_policy_revision(
            root,
            policy_reference.class_id,
            policy_reference.policy_id,
            policy_reference.policy_revision,
        )
        if stored_policy.reference != policy_reference:
            raise ClassStandardsProfileSourceError(
                "Activated Grade policy digest does not match exact policy history."
            )
        policy = stored_policy.policy
        if policy.calculation_family == "standards_based":
            configuration = cast(StandardsBasedGradeConfiguration, policy.configuration)
        elif policy.calculation_family == "hybrid":
            hybrid = cast(HybridGradeConfiguration, policy.configuration)
            configuration = hybrid.standards_based
        else:
            raise ClassStandardsProfileSourceError(
                "Active Grade policy is conventional and does not define a "
                "standards reporting set."
            )

        scale_ref = configuration.target_scale
        stored_scale = load_proficiency_scale_revision(
            root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
        if stored_scale.reference != scale_ref:
            raise ClassStandardsProfileSourceError(
                "Active Grade policy target-scale digest does not match exact history."
            )

        roster = load_class_roster(root, checked_class)
        student_ids = tuple(sorted(student.student_id for student in roster.students))
        student_set = set(student_ids)
        roster_observation = build_report_display_name_observation(
            root,
            checked_class,
            student_ids,
        )

        standard_ids = tuple(item.standard_id for item in configuration.standards)
        standard_set = set(standard_ids)
        current_stored = list_current_academic_period_proficiency_results(
            root,
            checked_class,
            checked_period.school_year,
            checked_period.period_id,
        )
        observations = tuple(
            current_proficiency_observation(item)
            for item in current_stored
            if item.snapshot.student_id in student_set
            and item.snapshot.standard_id in standard_set
        )
    except ClassStandardsProfileError:
        raise
    except (
        AcademicPeriodProficiencyStorageError,
        GradePolicyActivationStorageError,
        GradePolicyStorageError,
        ProficiencyMappingStorageError,
        ReportExportRosterError,
        RosterError,
        OSError,
        ValueError,
    ) as error:
        raise ClassStandardsProfileSourceError(
            "Class Standards Profile source state could not be verified safely."
        ) from error

    observation_map = {
        (item.student_id, item.standard_id): item for item in observations
    }
    witness = {
        "activation_sha256": activation_reference.activation_sha256,
        "policy_sha256": policy_reference.policy_sha256,
        "scale_sha256": stored_scale.reference.scale_sha256,
        "roster_sha256": export_roster_observation_sha256(roster_observation),
        "calendar_revision": checked_calendar,
        "selections": [
            {
                "student_id": student_id,
                "standard_id": standard_id,
                "selection": (
                    None
                    if (item := observation_map.get((student_id, standard_id))) is None
                    else {
                        "result_revision": item.result_revision,
                        "result_sha256": item.result_sha256,
                        "calendar_revision": item.calendar_revision,
                        "target_scale_sha256": item.target_scale.scale_sha256,
                        "status": item.status,
                        "proficiency_level_id": item.proficiency_level_id,
                    }
                ),
            }
            for student_id in student_ids
            for standard_id in standard_ids
        ],
    }
    return _ProfileState(
        scale=stored_scale.scale,
        standard_ids=standard_ids,
        profile_groups=(
            ()
            if configuration.profile_constraints is None
            else configuration.profile_constraints.groups
        ),
        roster=roster_observation,
        observations=observations,
        policy_reference=policy_reference,
        activation_reference=activation_reference,
        witness_sha256=_json_sha256(witness),
    )


def _profile_groups(
    values: tuple[ProfileStandardGroup, ...],
    reporting_standard_ids: tuple[str, ...],
) -> tuple[ProfileStandardGroup, ...]:
    groups = tuple(values)
    if any(not isinstance(item, ProfileStandardGroup) for item in groups):
        raise ClassStandardsProfileValidationError(
            "profile_groups must contain ProfileStandardGroup values."
        )
    if tuple(item.group_id for item in groups) != tuple(
        sorted(item.group_id for item in groups)
    ):
        raise ClassStandardsProfileValidationError(
            "profile_groups must use canonical group_id order."
        )
    allowed = set(reporting_standard_ids)
    for group in groups:
        if any(standard_id not in allowed for standard_id in group.standard_ids):
            raise ClassStandardsProfileValidationError(
                "profile group contains a standard outside reporting scope."
            )
    return groups


def _student_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    students = tuple(_identifier(item, "student_id") for item in values)
    if len(set(students)) != len(students):
        raise ClassStandardsProfileValidationError(
            "student_filter must not contain duplicates."
        )
    return tuple(sorted(students))


def _standard_ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    try:
        standards = tuple(normalize_standard_id(item) for item in values)
    except ValueError as error:
        raise ClassStandardsProfileValidationError(str(error)) from error
    if len(set(standards)) != len(standards):
        raise ClassStandardsProfileValidationError(
            f"{label} must not contain duplicates."
        )
    return tuple(sorted(standards))


def _level_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    levels = tuple(_identifier(item, "proficiency_level_id") for item in values)
    if len(set(levels)) != len(levels):
        raise ClassStandardsProfileValidationError(
            "proficiency_level_filter must not contain duplicates."
        )
    return tuple(sorted(levels))


def _identifier(value: str, label: str) -> str:
    try:
        return validate_identifier(value, field_name=label)
    except IdentifierValidationError as error:
        raise ClassStandardsProfileValidationError(str(error)) from error


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ClassStandardsProfileValidationError(
            f"{label} must be a positive integer."
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
    "ClassStandardsProfileCurrentnessConflictError",
    "ClassStandardsProfileError",
    "ClassStandardsProfileSourceError",
    "ClassStandardsProfileValidationError",
    "build_current_class_standards_profile",
    "compose_class_standards_profile",
]
